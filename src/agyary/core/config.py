from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "agyary"
    app_env: str = "development"
    app_debug: bool = True

    database_url: str = "postgresql+asyncpg://agyary:agyary@localhost:5432/agyary"

    # WhatsApp Cloud API. Both of these are read by the webhook and nothing
    # else: this deployment receives from Meta and never sends to it, so
    # there is deliberately no API token here. Anything that needs one is a
    # business-initiated message, which needs an approved template and costs
    # money per conversation - see services/wa_login.py for why sign-in
    # avoids all of that by having the mobed message us instead.
    #
    # verify_token is a string you invent and paste into Meta's webhook
    # configuration; app_secret is the Meta App's own secret, and the
    # webhook verifies every payload's HMAC against it and fails closed
    # when it is blank rather than comparing against b"" and accepting
    # everything.
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""

    # Mobed PWA session tokens. No passwords, no OAuth - priests don't want
    # another login to remember, and the WhatsApp number is already the
    # identity.
    jwt_secret_key: str = ""
    jwt_access_token_minutes: int = 60
    # Sliding window (see routes/mobed.py's /auth/refresh - it reissues this
    # cookie on every use): ten years, which for a device opened every few
    # weeks means "signed in once, on this phone, forever". That is the
    # intent - there is no password to fall back on, and re-signing-in costs
    # a trip out to WhatsApp and back. The sliding window is what makes the
    # number almost irrelevant in practice: it only bites on a device left
    # untouched for the whole period. Sign out on the menu screen is the way
    # to end a session deliberately; it clears this cookie server-side.
    jwt_refresh_token_days: int = 3650

    # --- Inbound WhatsApp sign-in -------------------------------------------
    # The mobed messages US a code rather than us texting one to them, so
    # nothing is business-initiated: no template, no per-message cost, and
    # no phone number typed by the caller. What it does need is a real
    # WhatsApp Business Account, which means a number that was not already
    # active on WhatsApp or WhatsApp Business.
    #
    # The dialable E.164 number the wa.me deep link points at, e.g.
    # "+919800000000" - a wa.me link needs the number itself, not Meta's
    # opaque phone_number_id.
    whatsapp_signin_number: str = ""
    # How long a started sign-in stays claimable. Generous because this flow
    # makes the user leave the browser, find the message in WhatsApp and send
    # it. Five minutes is enough to type a code you are looking at; it is not
    # enough to switch apps on a phone that decides to show you six
    # notifications on the way.
    wa_login_ttl_seconds: int = 600

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
