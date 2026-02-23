from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    SERVICE_API_KEY: str = ""
    FLASH_URL: str = "http://timepoint-flash-deploy.railway.internal:8080"
    FLASH_SERVICE_KEY: str = ""
    DATA_DIR: str = "./data"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    PORT: int = 8080
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "google/gemini-2.0-flash-001"
    EXPANSION_ENABLED: bool = False
    DAILY_CRON_ENABLED: bool = False
    DATABASE_URL: str = ""
    ADMIN_KEY: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache()
def get_settings() -> Settings:
    return Settings()
