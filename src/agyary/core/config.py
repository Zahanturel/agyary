from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "agyary"
    app_env: str = "development"
    # Off unless asked for. Debug signs anyone in as any number (the simulate
    # webhook, OTP codes in the response) and drops Secure cookies and HSTS, so
    # a server built from a forgotten .env must come up with it off - and a
    # production one refuses to start with it on (validate_runtime_secrets).
    # A laptop serving plain http on localhost needs APP_DEBUG=true in .env.
    app_debug: bool = False

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

    # --- Memorial reminders (the one thing we send) ---------------------------
    # Business-initiated, so unlike sign-in this needs a System User access
    # token, the number's phone_number_id, and a template Meta has approved.
    # None of them belong in the repo: set them in .env on the server.
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_graph_version: str = "v23.0"
    whatsapp_reminder_template: str = "memorial_reminder"
    whatsapp_template_language: str = "en"

    # off: nothing is planned or sent. dry_run: reminders are planned and
    # logged as they would be sent, and nothing leaves the building. live:
    # they are sent - but only to numbers in `reminders_allowlist` (a comma
    # separated list of E.164 numbers), or to everyone when it is "*". An
    # empty list in live mode sends to nobody, so going live is two deliberate
    # steps rather than one flag.
    reminders_send_mode: str = "off"
    reminders_allowlist: str = ""
    # The evening run: tomorrow's reminders go out from this hour (IST), and
    # whatever has not gone by the cutoff is skipped rather than sent late -
    # "tomorrow" at midnight is no longer true.
    reminders_send_hour: int = 19
    reminders_cutoff_hour: int = 21

    # --- Sign-in codes sent over WhatsApp --------------------------------------
    # A second way to sign in alongside the "send us a code" one: type your
    # number, we WhatsApp you a six digit code (an Authentication template with a
    # Copy code button), and the app reads it back from your clipboard. It is
    # business-initiated and costs a few paise per code, and an unauthenticated
    # endpoint that sends paid messages to any number is exactly what gets
    # abused, so it is off by default and ringed with limits (services/otp.py).
    otp_mode: str = "off"                    # off | live
    otp_template: str = "login_code"
    otp_ttl_seconds: int = 300
    otp_daily_cap: int = 100                 # codes sent per IST day, all numbers
    otp_new_number_hourly_cap: int = 20      # codes to numbers with no account, per hour

    # --- Spend and abuse guardrails -----------------------------------------
    # Every reminder costs money, and a bug or a bad actor must not be able to
    # run that up. These are ceilings, not targets: a reminder over any of them
    # is not sent, the mobed is told so they can send it by hand, and the admins
    # are alerted. Counted over reminders planned or sent, never failed ones.
    reminders_daily_cap: int = 150           # all fire temples, per IST day
    reminders_monthly_cap: int = 2000        # all fire temples, per IST month
    reminders_per_mobed_daily_cap: int = 40  # one mobed
    reminders_per_agyary_daily_cap: int = 100  # one fire temple
    # Only for the estimate on the admin screen; the real price is Meta's.
    reminders_cost_per_message_inr: float = 0.14
    # This many failures in a row (not counting a single bad number) pause all
    # sending until an admin resumes it.
    reminders_breaker_failures: int = 5
    # Comma separated E.164 numbers of the people who can see the admin screen,
    # pause sending, and receive alerts. Empty means nobody is an admin.
    admin_phones: str = ""

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

    # --- Who may sign up ------------------------------------------------------
    # Signing up is creating an account; anyone who already has one always signs
    # in. The policy is open sign-up for any verified number (docs/DECISIONS.md
    # D1), but only once the safeguards that make it safe have shipped - until
    # then sign-up is by invitation. "invite": a new account only for a number in
    # SIGNUP_ALLOWLIST (comma separated E.164) or an admin. "open": any number
    # WhatsApp has verified. To invite a mobed, add their number and restart the
    # app; once they have signed up the entry can go.
    signup_mode: str = "invite"
    signup_allowlist: str = ""

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
        """Refuse to serve with a blank JWT signing key, or in debug mode in
        production.

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
        if self.app_debug and self.app_env.strip().lower() == "production":
            raise RuntimeError(
                "APP_DEBUG is true with APP_ENV=production. Debug mode lets anyone "
                "sign in as any number. Set APP_DEBUG=false in .env before starting."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
