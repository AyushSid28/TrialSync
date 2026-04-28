"""Production server runner using Gunicorn with Uvicorn workers."""
import multiprocessing
from src.core import settings

# Calculate workers: (2 x CPU cores) + 1
workers = (multiprocessing.cpu_count() * 2) + 1

# Gunicorn configuration
bind = f"{settings.HOST}:{settings.PORT}"
worker_class = "uvicorn.workers.UvicornWorker"
workers = settings.WORKERS if settings.WORKERS > 1 else workers
worker_connections = 1000
keepalive = 5

# Logging
accesslog = "-"
errorlog = "-"
loglevel = settings.LOG_LEVEL.lower()

# Graceful timeout for shutdown
graceful_timeout = 30
timeout = 120

# For production, use:
# gunicorn src.main:app -c gunicorn.conf.py
