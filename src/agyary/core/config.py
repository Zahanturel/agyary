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

    # WhatsApp Flows: the RSA keypair Meta encrypts the data-exchange AES
    # key against. Private key stays here (server-side, PEM, unencrypted -
    # matches how whatsapp_app_secret is already handled); the public key
    # is uploaded to Meta separately at Flow-registration time (a manual,
    # one-off operational step - see wa_flows.py's module docstring).
    whatsapp_flows_private_key_pem: str = ""

    # Flow ids assigned by Meta on registration (one static Flow per
    # picker: Roj/Mah/Geh never change; the priest-picker and
    # per-agyari-services Flows are dynamic but still each get one
    # registered Flow id - the per-tenant part lives in the data-exchange
    # response, not in a separate Flow per agyari).
    whatsapp_flow_id_roj: str = ""
    whatsapp_flow_id_mah: str = ""
    whatsapp_flow_id_geh: str = ""
    whatsapp_flow_id_priest_picker: str = ""
    whatsapp_flow_id_services_picker: str = ""

    # Mobed PWA auth: WhatsApp OTP (existing AuthOtp table/precedent, no
    # send/verify logic previously existed) + JWT, per the pattern already
    # documented in 02-backend-api.md's auth routes section (the one part
    # of that doc not superseded by the v3 redesign). No passwords, no
    # OAuth - priests don't want another login to remember.
    jwt_secret_key: str = ""
    jwt_access_token_minutes: int = 60
    # Sliding window (see routes/mobed.py's /auth/refresh - it reissues this
    # cookie on every use): a mobed who opens the app at least once every 180
    # days is never re-prompted to log in, matching "log in once, never
    # again." Pinning this too low would silently log people out mid-season.
    jwt_refresh_token_days: int = 180


@lru_cache
def get_settings() -> Settings:
    return Settings()
