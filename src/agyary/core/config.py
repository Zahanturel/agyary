from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "agyary"
    app_env: str = "development"
    app_debug: bool = True

    database_url: str = "postgresql+asyncpg://agyary:agyary@localhost:5432/agyary"


@lru_cache
def get_settings() -> Settings:
    return Settings()
