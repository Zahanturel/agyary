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

    # Login OTP (services/mobed_auth.py). A 6-digit code is only safe
    # because of the other two numbers: it dies in five minutes and after
    # three wrong guesses.
    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 3
    # The Meta phone_number_id login OTPs are sent FROM. Separate from the
    # per-agyari Agyary.wa_phone_number_id: someone signing in for the first
    # time has no agyari yet, so there is no per-tenant number to send from.
    whatsapp_otp_phone_number_id: str = ""

    # The approved Authentication template the code is sent in. WhatsApp
    # rejects free-text business-initiated messages, so without this nothing
    # can be delivered at all.
    #
    # The language is the template's OWN code, not a display label: "en" and
    # "en_US" are different templates to the API, and a mismatch fails at
    # send time with an unhelpful error.
    #
    # otp_ttl_seconds above must stay in step with the expiry the template
    # states in its footer - the template's text is fixed at approval time,
    # so changing the TTL here alone would make the message tell users
    # something untrue.
    whatsapp_otp_template_name: str = ""
    whatsapp_otp_template_language: str = "en"
    # Authentication templates with a copy-code button need the code passed
    # a second time as a button component. Templates without one reject it.
    whatsapp_otp_template_has_copy_code: bool = True

    # How long an issued role invite stays redeemable (models/invite.py).
    invite_ttl_days: int = 14

    def validate_runtime_secrets(self) -> None:
        """Refuse to serve with a blank JWT signing key.

        An empty ``jwt_secret_key`` doesn't disable auth, which would at
        least be obvious - it signs every session token with the empty
        string, so anyone can mint a token for any user id and the app looks
        like it's working. The default has to stay "" for tooling that
        imports Settings without a .env, so this is an explicit call made at
        app startup (api/main.py) rather than a field validator.
        """
        if not self.jwt_secret_key.strip():
            raise RuntimeError(
                "JWT_SECRET_KEY is empty. Session tokens would be signed with a "
                "blank key and could be forged by anyone. Generate one with "
                "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"` "
                "and set it in .env before starting the app."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
