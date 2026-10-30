from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "agyary"
    # Production unless told otherwise, so a server whose .env lost this line
    # refuses debug rather than running it (CFG-03). A laptop sets development.
    app_env: str = "production"
    # Off unless asked for. Debug signs anyone in as any number (the simulate
    # webhook, OTP codes in the response) and drops Secure cookies and HSTS, so
    # a server built from a forgotten .env must come up with it off - and a
    # production one refuses to start with it on (validate_runtime_secrets).
    # A laptop serving plain http on localhost needs APP_DEBUG=true in .env.
    app_debug: bool = False

    database_url: str = "postgresql+asyncpg://agyary:agyary@localhost:5432/agyary"

    # WhatsApp Cloud API, receiving: both of these are read by the webhook and
    # nothing else. What we send needs the token further down, an approved
    # template and money per message - see services/wa_login.py for why the
    # main sign-in avoids all of that by having the mobed message us instead.
    #
    # verify_token is a string you invent and paste into Meta's webhook
    # configuration; app_secret is the Meta App's own secret, and the
    # webhook verifies every payload's HMAC against it and fails closed
    # when it is blank rather than comparing against b"" and accepting
    # everything.
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""

    # --- What we send: reminders, schedules, reports, sign-in codes -----------
    # Business-initiated, so unlike receiving this needs a System User access
    # token, the number's phone_number_id, and a template Meta has approved.
    # None of them belong in the repo: set them in .env on the server.
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_graph_version: str = "v23.0"
    whatsapp_reminder_template: str = "memorial_reminder"
    whatsapp_template_language: str = "en"
    # A memorial's schedule sent as a PDF from the shared number. off until the
    # template (a document header and three text variables) is approved by Meta;
    # then live, which still needs the family's consent and the allowlist.
    # The daily report to a mobed (services/daily_report.py): in the app whenever they
    # have asked for it, and on WhatsApp too when the mode is live - which waits for
    # the template below to be approved. It goes out from daily_report_hour (IST) and
    # not after the cutoff, so a mobed who turns it on late is not woken for it.
    whatsapp_daily_report_template: str = "daily_report"
    daily_report_send_mode: str = "off"
    daily_report_hour: int = 20
    daily_report_cutoff_hour: int = 22
    whatsapp_share_template: str = "memorial_schedule"
    memorial_share_send_mode: str = "off"
    memorial_share_daily_cap: int = 20         # one mobed, per IST day (a new account: lower)
    memorial_share_global_daily_cap: int = 100  # all mobeds, per IST day; hitting it alerts the admins
    # A number whose account was deleted cannot send schedules from our number
    # for this long after signing up again (SEC-02).
    deleted_account_cooldown_days: int = 30

    # off: nothing is planned or sent. dry_run: reminders are planned and
    # logged as they would be sent, and nothing leaves the building. live:
    # they are sent - but only to numbers in `reminders_allowlist` (a comma
    # separated list of E.164 numbers), or to everyone when it is "*". An
    # empty list in live mode sends to nobody, so going live is two deliberate
    # steps rather than one flag.
    reminders_send_mode: str = "off"
    reminders_allowlist: str = ""
    # Whether a NEW account has automatic sending on (users.automatic_reminders,
    # D4). True for the pilot; a free tier later sets it false.
    reminders_automatic_default: bool = True
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
    # Requests from one address, counted in the database (a restart cannot reset them).
    otp_per_address_hourly: int = 10
    otp_per_address_daily: int = 30
    # Cloudflare Turnstile, the bot check every code request must pass (D1, D3).
    # If either is missing, no code is sent, even with OTP_MODE=live (routes/otp.py).
    turnstile_site_key: str = ""
    turnstile_secret_key: str = ""
    # The site a Turnstile token must have been earned on. Empty skips the check.
    turnstile_hostname: str = "mobed.gotiadarian.com"

    # --- Spend and abuse guardrails -----------------------------------------
    # Every reminder costs money, and a bug or a bad actor must not be able to
    # run that up. These are ceilings, not targets: a reminder over any of them
    # is not sent, the mobed is told so they can send it by hand, and the admins
    # are alerted. Counted over reminders planned or sent, never failed ones.
    reminders_daily_cap: int = 150           # all fire temples, per IST day
    reminders_monthly_cap: int = 2000        # all fire temples, per IST month
    reminders_per_mobed_daily_cap: int = 40  # one mobed
    reminders_per_agyary_daily_cap: int = 100  # one fire temple
    # An account in its first days may send only a handful a day (D1), unless
    # the owner vouches for it (comma separated E.164) or it is an admin.
    reminders_new_account_days: int = 7
    reminders_new_account_daily_cap: int = 5
    reminders_vouched: str = ""
    # Only for the estimate on the admin screen; the real price is Meta's.
    reminders_cost_per_message_inr: float = 0.14
    # This many failures in a row (not counting a single bad number) pause all
    # sending until an admin resumes it.
    reminders_breaker_failures: int = 5
    # The kind one-line reply to a family's first STOP: at most this many a day
    # (each is a paid WhatsApp message since 1 Oct 2026).
    reminders_stop_ack_daily_cap: int = 20
    # An outside heartbeat check (e.g. a Healthchecks.io ping URL) the evening
    # loop pings after every pass, "/fail" appended when one goes wrong (OP-2).
    # Empty: no pings.
    heartbeat_url: str = ""
    # The Android app (Trusted Web Activity) and the keys it is signed with,
    # for /.well-known/assetlinks.json. The default is the upload key; once the
    # app is on Google Play, add Play's app-signing fingerprint (Play Console ->
    # Test and release -> App integrity) after it, comma separated.
    android_package_name: str = "com.gotiadarian.mobeddiary"
    android_cert_fingerprints: str = (
        "66:E7:28:89:5A:E3:B8:85:1E:91:1D:72:7E:47:0F:89:27:40:98:4C:3C:13:D0:4D:D4:CF:E8:63:9F:97:E8:90"
    )
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
    # But no session lives longer than this, however often it is used (AU-2):
    # after a year the mobed signs in again.
    jwt_session_max_days: int = 365
    # Refresh tokens from before sessions existed are moved into a session on
    # their next use until this date (YYYY-MM-DD), and refused after it.
    jwt_legacy_tokens_until: str = "2027-01-31"

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
    # AU-1: "on" sends a short confirmation number back to the phone a sign-in
    # code came from, and the sign-in finishes only when it is typed on the
    # screen that started it - what stops "send us a code" being phished. It is a
    # real WhatsApp message (about a utility message's price), so it is off until
    # the owner turns it on; with it off, sign-in works as before.
    signin_confirmation: str = "off"

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
        if len(self.jwt_secret_key.strip()) < 32:
            raise RuntimeError(
                "JWT_SECRET_KEY is too short: it needs at least 32 characters. Generate one with "
                "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
            )
        if self.app_debug and self.app_env.strip().lower() != "development":
            raise RuntimeError(
                "APP_DEBUG is true outside APP_ENV=development. Debug mode lets anyone "
                "sign in as any number. Set APP_DEBUG=false in .env before starting."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
