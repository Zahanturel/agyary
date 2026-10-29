import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.staticfiles import StaticFiles

from agyary.api.routes.admin import router as admin_router
from agyary.api.routes.calendar import router as calendar_router
from agyary.api.routes.memorials import router as memorials_router
from agyary.api.routes.mobed import router as mobed_router
from agyary.api.routes.otp import router as otp_router
from agyary.api.routes.reminders import router as reminders_router
from agyary.api.routes.whatsapp import router as whatsapp_router
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.services import bot_check, reminder_worker

settings = get_settings()
settings.validate_runtime_secrets()

# uvicorn configures its own loggers and nothing else, so the app's INFO lines
# (the reminder loop saying what it planned and sent, a dry run showing what it
# would send) would otherwise be dropped on the server. Only the "agyary" tree
# is raised: setting the root to INFO would also switch on SQLAlchemy's
# statement logging.
_app_log = logging.getLogger("agyary")
if not _app_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _app_log.addHandler(_handler)
    _app_log.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Run the evening loop alongside the app. It always runs, because it also
    leaves the in-app "last prayer is tomorrow" notices; but it sends nothing
    to anyone unless REMINDERS_SEND_MODE says so, and with sending off it does
    no more than that one cheap check in the evening window."""
    worker = asyncio.create_task(reminder_worker.run_forever())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(
    lifespan=lifespan,
    title=settings.app_name,
    # The interactive API explorer/schema is a map of every endpoint and
    # payload shape - useful in dev, a gift to an attacker in production.
    # Hide it outside debug mode; debug is the same flag that already gates
    # the cookie Secure attribute (core/config.py).
    docs_url="/docs" if settings.app_debug else None,
    redoc_url="/redoc" if settings.app_debug else None,
    openapi_url="/openapi.json" if settings.app_debug else None,
)


# Every path that makes up a PWA shell, as opposed to its data. These must
# always be revalidated: there is no build step and so no hashed filenames to
# make a stale copy harmless.
_NO_CACHE_PATHS = frozenset({
    "/mobed",
    "/mobed-sw.js",
    "/mobed-manifest.json",
    "/privacy",
    "/delete-account",
})


class _NoQueryStrings(logging.Filter):
    """Access log lines keep the path but drop the query string, which can
    carry a behdin search or a name (PV-3)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and "?" in args[2]:
            record.args = args[:2] + (args[2].split("?", 1)[0],) + args[3:]
        return True


logging.getLogger("uvicorn.access").addFilter(_NoQueryStrings())


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # The app is its own origin and nothing else: no inline script, no inline
    # event handlers, no eval and no third-party host anywhere in it, so the
    # browser is told to run nothing but our own files. That turns any injected
    # markup into text instead of code. Styles stay inline because the screens
    # set style attributes. frame-ancestors is the modern X-Frame-Options.
    # The one exception: once the bot check is configured, Cloudflare's
    # Turnstile script and its frame, for the sign-in code request (D3).
    turnstile = bot_check.CHALLENGE_ORIGIN if get_settings().turnstile_site_key.strip() else None
    script_src = f"'self' {turnstile}" if turnstile else "'self'"
    frame_src = turnstile or "'none'"
    response.headers["Content-Security-Policy"] = (
        f"default-src 'self'; script-src {script_src}; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; manifest-src 'self'; "
        f"worker-src 'self'; frame-src {frame_src}; object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    # Camera, microphone, location and payment are never needed. The clipboard
    # and contacts are, so they are not listed here.
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    if not settings.app_debug:
        # Production is HTTPS only (Cloudflare). Told once, a browser refuses
        # to talk to it over plain HTTP for six months. Not sent in debug, where
        # a laptop serves http on localhost.
        response.headers["Strict-Transport-Security"] = "max-age=15552000"
    # The PWA is a dozen ES modules with no build step, so no filename
    # hashing to bust caches with. Without this the browser is free to
    # serve some modules from its own cache after a deploy and fetch
    # others fresh - a half-updated app, which fails in ways far stranger
    # than being wholly out of date. "no-cache" means revalidate, not
    # don't store: the usual answer is a cheap 304.
    #
    # This has to cover the service workers and manifests too, not just the
    # modules. A worker served from a stale edge cache is worse than a stale
    # module: it is the thing that decides how everything else is fetched, so
    # an old one keeps serving old modules and no reload can escape it. Miss
    # one path here and Cloudflare caches that path for four hours on its own
    # authority - which is exactly how a shipped deploy stayed invisible on a
    # phone while every server-side check passed.
    path = request.url.path
    if path in _NO_CACHE_PATHS or path.startswith("/mobed-app"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.include_router(calendar_router)
app.include_router(admin_router)
app.include_router(mobed_router)
app.include_router(memorials_router)
app.include_router(otp_router)
app.include_router(reminders_router)
app.include_router(whatsapp_router)

_STATIC_DIR = Path(__file__).parent / "static"
_MOBED_DIR = _STATIC_DIR / "mobed"


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send a bare hostname to the app. There is one app (Machi is a tab of it),
    on whatever hostname: without this, "/" would 404 - which is exactly what
    someone hits when a shared link drops the path.

    307, never 301: a permanent redirect is cached by browsers indefinitely
    and would outlive any change to where the app lives.
    """
    return RedirectResponse(url="/mobed", status_code=307)


@app.get("/mobed", include_in_schema=False)
def mobed_ui() -> FileResponse:
    """The mobed PWA shell (vanilla HTML + ES modules, still no build step).

    Everything under the hash lives in the client-side router, so this one
    file answers /mobed for every route.
    """
    return FileResponse(_MOBED_DIR / "index.html", media_type="text/html")


# The PWA's own modules and stylesheet. A mount rather than a route each,
# because the app is now a dozen ES modules instead of one inlined script -
# and native `import` needs each one served with a JS content type, which
# StaticFiles handles.
app.mount("/mobed-app", StaticFiles(directory=_MOBED_DIR), name="mobed-app")


@app.get("/mobed-manifest.json", include_in_schema=False)
def mobed_manifest() -> FileResponse:
    return FileResponse(_STATIC_DIR / "mobed-manifest.json", media_type="application/manifest+json")


@app.get("/mobed-sw.js", include_in_schema=False)
def mobed_service_worker() -> FileResponse:
    return FileResponse(_STATIC_DIR / "mobed-sw.js", media_type="application/javascript")


@app.get("/mobed-icon.svg", include_in_schema=False)
def mobed_icon() -> FileResponse:
    return FileResponse(_STATIC_DIR / "mobed-icon.svg", media_type="image/svg+xml")


# PNG icons for installing the app and for the Android (Trusted Web Activity)
# build, which needs bitmaps; "maskable" keeps the emblem inside the circle
# Android may crop it to.
_PNG_ICONS = frozenset({"mobed-icon-192.png", "mobed-icon-512.png", "mobed-icon-maskable-512.png"})


@app.get("/{name}.png", include_in_schema=False)
def mobed_png_icon(name: str) -> FileResponse:
    if f"{name}.png" not in _PNG_ICONS:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(_STATIC_DIR / f"{name}.png", media_type="image/png")


# Digital Asset Links: tells Android that the Play Store app may open this
# site full-screen, without a browser bar (Trusted Web Activity). It lists the
# SHA-256 fingerprints of the keys the app is signed with - the upload key, and
# Google Play's own signing key once the app is on Play (ANDROID_CERT_FINGERPRINTS).
@app.get("/.well-known/assetlinks.json", include_in_schema=False)
def asset_links() -> JSONResponse:
    s = get_settings()
    prints = [p.strip().upper() for p in s.android_cert_fingerprints.split(",") if p.strip()]
    if not prints:
        return JSONResponse([])
    return JSONResponse([{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {"namespace": "android_app", "package_name": s.android_package_name,
                   "sha256_cert_fingerprints": prints},
    }])


# Self-hosted Geist variable fonts (OFL-licensed, see static/fonts/LICENSE) -
# no CDN dependency, no npm/build step at runtime. One variable file per
# family covers the whole 100-900 weight axis.
@app.get("/mobed-fonts/geist-sans.woff2", include_in_schema=False)
def font_geist_sans() -> FileResponse:
    return FileResponse(_STATIC_DIR / "fonts" / "geist-sans.woff2", media_type="font/woff2")


@app.get("/mobed-fonts/geist-mono.woff2", include_in_schema=False)
def font_geist_mono() -> FileResponse:
    return FileResponse(_STATIC_DIR / "fonts" / "geist-mono.woff2", media_type="font/woff2")


# --- Privacy policy ----------------------------------------------------------
# Served on every hostname, deliberately unauthenticated and
# JS-free: Meta will not publish the app without a policy URL its reviewer
# can fetch, and a reviewer is not going to sign in with WhatsApp to read it.
# A flat file rather than a PWA route for the same reason - it has to render
# with no session, no service worker and no JavaScript at all.
@app.get("/privacy", include_in_schema=False)
def privacy_policy() -> FileResponse:
    return FileResponse(_STATIC_DIR / "privacy.html", media_type="text/html")


# How to delete an account, for Google Play's account-deletion rule: like the
# policy, it must be readable without signing in.
@app.get("/delete-account", include_in_schema=False)
def delete_account_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "delete-account.html", media_type="text/html")


WORKER_STALE = timedelta(minutes=3)


# HEAD too: the free tier of UptimeRobot can only send HEAD, and a 405 there would read as "down".
@app.api_route("/health", methods=["GET", "HEAD"])
async def health(deep: bool = False, db: AsyncSession = Depends(get_db)) -> Response:
    """Plain: the web server answers (the container's own check). With
    ?deep=1, for an uptime monitor outside: the database answers and the
    evening loop has finished a pass in the last few minutes (OP-2) - 503
    otherwise, so a dead loop is noticed even when the site looks fine."""
    if not deep:
        return JSONResponse({"status": "ok"})
    try:
        await db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # noqa: BLE001 - any failure is "not ok", reported not raised
        database = "unreachable"
    last = reminder_worker.last_pass_at
    worker = "ok" if last and datetime.now(timezone.utc) - last < WORKER_STALE else "stale"
    healthy = database == "ok" and worker == "ok"
    return JSONResponse(
        {"status": "ok" if healthy else "unhealthy", "database": database, "worker": worker},
        status_code=200 if healthy else 503,
    )
