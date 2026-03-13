from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SERVICE_API_KEY: str = ""
    FLASH_URL: str = ""
    FLASH_SERVICE_KEY: str = ""
    DATA_DIR: str = "./data"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    PORT: int = 8080
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = ""
    EXPANSION_ENABLED: bool = False
    EXPANSION_CONCURRENCY: int = 1
    EXPANSION_INTERVAL: int = 300
    EXPANSION_TARGET: int = 0
    EXPANSION_DAILY_BUDGET: float = 5.0
    DAILY_CRON_ENABLED: bool = False
    DATABASE_URL: str = ""
    ADMIN_KEY: str = ""
    RATE_LIMIT_PUBLIC: str = "60/minute"
    RATE_LIMIT_AUTH_READ: str = "300/minute"
    RATE_LIMIT_AUTH_WRITE: str = "30/minute"
    CORS_ORIGINS: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
