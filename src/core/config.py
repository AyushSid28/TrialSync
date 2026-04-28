from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow",
    )

    APP_NAME: str = "FastAPI Clean Architecture"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1
    LOG_LEVEL: str = "info"
    LOGFIRE_WRITE_TOKEN: str = ""

    DATABASE_URL: PostgresDsn
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    ALLOWED_ORIGINS: str = "http://localhost:3000"

    API_V1_PREFIX: str = "/api/v1"
    API_KEY: str = Field(
        description="Expected value for the X-API-Key header on protected routes.",
    )

    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""

    # ---------------------------------------------------------------------------
    # Rate limiting
    # ---------------------------------------------------------------------------
    RATE_LIMIT_ENABLED: bool = True
    # Maximum number of requests allowed within RATE_LIMIT_WINDOW_SECONDS
    RATE_LIMIT_REQUESTS: int = 100
    # Sliding-window duration in seconds
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    # Cooldown penalty applied once the limit is exceeded (seconds)
    RATE_LIMIT_COOLDOWN_SECONDS: int = 60

    @field_validator("ALLOWED_ORIGINS")
    @classmethod
    def parse_origins(cls, v: str) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v


settings = Settings()
