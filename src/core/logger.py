"""
Production-ready logging configuration with Logfire integration.

This module provides a centralized logging setup that:
- Integrates Python's built-in logging with Logfire
- Uses async queue handlers for non-blocking log processing
- Supports JSON formatting for structured logging
- Includes sensitive data filtering for security compliance
- Allows standard logging.getLogger(__name__) usage throughout the application
- Daily rotating log files in development with automatic cleanup
"""

import logging
import logging.handlers
import queue
import json
import re
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any
import logfire
from src.core import settings


class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def __init__(self, fmt_keys: Optional[dict[str, str]] = None):
        super().__init__()
        self.fmt_keys = fmt_keys or {
            "level": "levelname",
            "message": "message",
            "timestamp": "timestamp",
            "logger": "name",
            "module": "module",
            "function": "funcName",
            "line": "lineno",
            "thread_name": "threadName",
        }

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {}

        for key, attr in self.fmt_keys.items():
            if attr == "timestamp":
                log_data[key] = datetime.fromtimestamp(record.created).isoformat()
            elif attr == "message":
                log_data[key] = record.getMessage()
            else:
                log_data[key] = getattr(record, attr, None)

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add any extra data passed via extra parameter
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "created",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "thread",
                "threadName",
                "exc_info",
                "exc_text",
                "stack_info",
                "taskName",
            ]:
                if "extra" not in log_data:
                    log_data["extra"] = {}
                log_data["extra"][key] = value

        return json.dumps(log_data)


class SensitiveDataFilter(logging.Filter):
    """Filter to redact sensitive data from logs."""
    
    SENSITIVE_PATTERNS = [
        (re.compile(r'password["\']?\s*[:=]\s*["\']?([^"\'}\s,]+)', re.IGNORECASE), "password"),
        (re.compile(r'token["\']?\s*[:=]\s*["\']?([^"\'}\s,]+)', re.IGNORECASE), "token"),
        (re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?([^"\'}\s,]+)', re.IGNORECASE), "api_key"),
        (re.compile(r'secret["\']?\s*[:=]\s*["\']?([^"\'}\s,]+)', re.IGNORECASE), "secret"),
        (re.compile(r"authorization:\s*bearer\s+([^\s]+)", re.IGNORECASE), "bearer_token"),
    ]
    
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern, field_name in self.SENSITIVE_PATTERNS:
            message = pattern.sub(f"{field_name}=***REDACTED***", message)
        record.msg = message
        record.args = ()
        return True


def cleanup_old_logs(log_dir: str = "logs", days_to_keep: int = 5) -> int:
    """
    Delete log files older than specified number of days.
    
    Args:
        log_dir: Directory containing log files
        days_to_keep: Number of days to keep logs (default: 5)
    
    Returns:
        Number of log files deleted
    
    Usage:
        # At application startup or in a scheduled task
        deleted_count = cleanup_old_logs(days_to_keep=5)
    """
    deleted_count = 0
    log_path = Path(log_dir)
    
    if not log_path.exists():
        return 0
    
    cutoff_date = datetime.now() - timedelta(days=days_to_keep)
    
    try:
        for log_file in log_path.glob("app-*.log.jsonl"):
            if log_file.is_file():
                file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if file_mtime < cutoff_date:
                    log_file.unlink()
                    deleted_count += 1
                    logging.debug(f"Deleted old log file: {log_file.name}")
    except Exception as e:
        logging.warning(f"Error during log cleanup: {e}")
    
    return deleted_count


# Global listener reference for graceful shutdown
_listener: Optional[logging.handlers.QueueListener] = None


def setup_logging(
    env: Optional[str] = None, use_logfire: bool = True, log_level: Optional[str] = None
) -> logging.handlers.QueueListener:
    """
    Configure application-wide logging with Logfire integration.

    This function sets up:
    - Root logger configuration with appropriate log level
    - Queue-based async logging for non-blocking performance
    - Logfire handler for cloud logging (when enabled)
    - Console handler for development visibility
    - File handlers with rotation for persistence
    - Sensitive data filtering for security compliance

    Args:
        env: Environment name ('production', 'development'). Defaults to settings.ENVIRONMENT
        use_logfire: Whether to enable Logfire integration. Defaults to True
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL). Defaults to settings.LOG_LEVEL

    Returns:
        QueueListener instance for graceful shutdown

    Usage in application code:
        # At application startup (e.g., in main.py lifespan):
        listener = setup_logging()

        # In any module:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("Application started", extra={"user_id": 123})

        # At application shutdown:
        shutdown_logging()
    """
    global _listener

    # Use settings defaults if not provided
    env = env or settings.ENVIRONMENT
    log_level = log_level or settings.LOG_LEVEL

    # Parse log level
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Create the async queue for non-blocking logging
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(-1)  # Infinite size

    # Configure formatters
    simple_formatter = logging.Formatter(
        fmt="[%(levelname)s|%(module)s|L%(lineno)d] %(asctime)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    json_formatter = JsonFormatter(
        fmt_keys={
            "level": "levelname",
            "message": "message",
            "timestamp": "timestamp",
            "logger": "name",
            "module": "module",
            "function": "funcName",
            "line": "lineno",
            "thread_name": "threadName",
        }
    )

    # Create sensitive data filter
    sensitive_filter = SensitiveDataFilter()
    
    # Configure handlers
    handlers: list[logging.Handler] = []
    
    # Console handler (always enabled in development)
    if env != "production":
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(simple_formatter)
        console_handler.addFilter(sensitive_filter)
        handlers.append(console_handler)
    
    # File handler for local persistence
    try:
        os.makedirs("logs", exist_ok=True)
        
        # Clean up old log files at startup (development only)
        if env != "production":
            deleted_count = cleanup_old_logs(log_dir="logs", days_to_keep=5)
            if deleted_count > 0:
                logging.info(f"Cleaned up {deleted_count} old log files")
        
        # Use daily rotating files in development, size-based rotation in production
        if env == "production":
            file_handler = logging.handlers.RotatingFileHandler(
                filename="logs/app.log.jsonl",
                maxBytes=10_000_000,  # 10MB
                backupCount=3,
                encoding="utf-8",
            )
        else:
            # Daily rotating logs for development with date suffix
            today = datetime.now().strftime("%Y-%m-%d")
            file_handler = logging.handlers.TimedRotatingFileHandler(
                filename=f"logs/app-{today}.log.jsonl",
                when="midnight",  # Rotate at midnight
                interval=1,  # Every 1 day
                backupCount=5,  # Keep 5 days of logs
                encoding="utf-8",
            )
            # Set suffix for rotated files
            file_handler.suffix = "%Y-%m-%d"
        
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(json_formatter)
        file_handler.addFilter(sensitive_filter)
        handlers.append(file_handler)
    except Exception as e:
        logging.warning(f"Failed to create file handler: {e}")

    # Logfire handler (cloud logging)
    if use_logfire and env == "production":
        try:
            logfire.configure(
                send_to_logfire=True,
                console=False,  # Don't duplicate console output
                token=settings.LOGFIRE_WRITE_TOKEN,
            )
            logfire_handler = logfire.LogfireLoggingHandler()
            logfire_handler.setLevel(numeric_level)
            handlers.append(logfire_handler)
        except Exception as e:
            logging.warning(f"Failed to configure Logfire: {e}")
            # Fallback to error file if Logfire fails
            try:
                fallback_handler = logging.FileHandler("logs/production_errors.log")
                fallback_handler.setLevel(logging.ERROR)
                fallback_handler.setFormatter(json_formatter)
                fallback_handler.addFilter(sensitive_filter)
                handlers.append(fallback_handler)
            except Exception:
                pass
    elif use_logfire and env == "development":
        try:
            logfire.configure(
                send_to_logfire=True,
                console=False,
            )
            logfire_handler = logfire.LogfireLoggingHandler()
            logfire_handler.setLevel(numeric_level)
            handlers.append(logfire_handler)
        except Exception as e:
            logging.warning(f"Logfire not configured in development: {e}")

    # Start the queue listener with all handlers
    _listener = logging.handlers.QueueListener(log_queue, *handlers, respect_handler_level=True)
    _listener.start()

    # Configure root logger with queue handler
    queue_handler = logging.handlers.QueueHandler(log_queue)
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    root_logger.handlers.clear()  # Remove any existing handlers
    root_logger.addHandler(queue_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Log the successful setup
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging configured successfully",
        extra={
            "environment": env,
            "log_level": log_level,
            "logfire_enabled": use_logfire,
            "handlers_count": len(handlers),
        },
    )

    return _listener


def shutdown_logging() -> None:
    """
    Gracefully shutdown the logging system.

    Call this at application shutdown to ensure all log records
    are flushed and handlers are properly closed.
    """
    global _listener

    if _listener:
        _listener.stop()
        _listener = None

    # Flush all handlers
    logging.shutdown()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance by name.

    This is a convenience wrapper around logging.getLogger() that ensures
    the logging system is properly configured.

    Args:
        name: Logger name, typically __name__ of the calling module.
              If None, returns the root logger.

    Returns:
        Logger instance

    Usage:
        from src.core.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Operation completed")

    Note: You can also use logging.getLogger(__name__) directly after
    setup_logging() has been called.
    """
    return logging.getLogger(name)
