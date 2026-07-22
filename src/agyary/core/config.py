from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "agyary"
    app_env: str = "development"
    app_debug: bool = True

    database_url: str = "postgresql+asyncpg://agyary:agyary@localhost:5432/agyary"

    # WhatsApp Cloud API: one Meta app/System User token sends on behalf of
    # every registered agyary (Agyary.wa_phone_number_id is the per-tenant
    # bit, there is no per-tenant token).
    whatsapp_api_token: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
