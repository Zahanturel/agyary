from pathlib import Path

from fastapi import FastAPI, Header
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agyary.api.routes.calendar import router as calendar_router
from agyary.api.routes.mobed import router as mobed_router
from agyary.api.routes.whatsapp import router as whatsapp_router
from agyary.core.config import get_settings

settings = get_settings()
settings.validate_runtime_secrets()


app = FastAPI(
    title=settings.app_name,
    # The interactive API explorer/schema is a map of every endpoint and
    # payload shape - useful in dev, a gift to an attacker in production.
    # Hide it outside debug mode; debug is the same flag that already gates
    # the cookie Secure attribute (core/config.py).
    docs_url="/docs" if settings.app_debug else None,
    redoc_url="/redoc" if settings.app_debug else None,
    openapi_url="/openapi.json" if settings.app_debug else None,
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # The PWA is a dozen ES modules with no build step, so no filename
    # hashing to bust caches with. Without this the browser is free to
    # serve some modules from its own cache after a deploy and fetch
    # others fresh - a half-updated app, which fails in ways far stranger
    # than being wholly out of date. "no-cache" means revalidate, not
    # don't store: the usual answer is a cheap 304.
    path = request.url.path
    if path == "/mobed" or path.startswith("/mobed-app") or path == "/machi":
        response.headers["Cache-Control"] = "no-cache"
    return response


app.include_router(calendar_router)
app.include_router(mobed_router)
app.include_router(whatsapp_router)

_STATIC_DIR = Path(__file__).parent / "static"
_MOBED_DIR = _STATIC_DIR / "mobed"
_MACHI_DIR = _STATIC_DIR / "machi"


# Which PWA a bare hostname belongs to, keyed on the leftmost DNS label.
# Deliberately not the full domain: this then works identically on
# gotiadarian.com, a staging domain, or a machine name, and there is no
# production hostname buried in the app.
#
# The alternative was a Cloudflare Transform Rule rewriting the path in the
# dashboard. Same result, but it is invisible from the repo - when routing
# misbehaves later, nothing in the code would explain why. A tunnel ingress
# rule cannot do this itself: it matches on hostname and path, it does not
# prepend one, so every hostname arrives here at "/".
_HOST_APPS = {"mobed": "/mobed", "machi": "/machi"}
_DEFAULT_APP = "/mobed"


def app_path_for_host(host: str | None) -> str:
    """The app a request to "/" on ``host`` should land in.

    Anything unrecognised - an IP, localhost, the apex domain, a missing
    Host header - falls back to the mobed app, which is the product.
    """
    if not host:
        return _DEFAULT_APP
    label = host.split(":")[0].split(".")[0].lower()
    return _HOST_APPS.get(label, _DEFAULT_APP)


@app.get("/", include_in_schema=False)
def root(host: str | None = Header(default=None)) -> RedirectResponse:
    """Send a bare hostname to the PWA that hostname is for.

    mobed.gotiadarian.com and machi.gotiadarian.com are the same app behind
    the same tunnel, so the Host header is the only thing distinguishing
    them. Without this, "/" would 404 - which is exactly what someone hits
    when a shared link drops the path.

    307, never 301: a permanent redirect is cached by browsers indefinitely
    and would outlive any change to this mapping. Vary: Host because the
    response genuinely differs by it, and a shared cache that missed that
    would serve one app's users the other app.
    """
    response = RedirectResponse(url=app_path_for_host(host), status_code=307)
    response.headers["Vary"] = "Host"
    return response


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


# Self-hosted Geist variable fonts (OFL-licensed, see static/fonts/LICENSE) -
# no CDN dependency, no npm/build step at runtime. One variable file per
# family covers the whole 100-900 weight axis.
@app.get("/mobed-fonts/geist-sans.woff2", include_in_schema=False)
def font_geist_sans() -> FileResponse:
    return FileResponse(_STATIC_DIR / "fonts" / "geist-sans.woff2", media_type="font/woff2")


@app.get("/mobed-fonts/geist-mono.woff2", include_in_schema=False)
def font_geist_mono() -> FileResponse:
    return FileResponse(_STATIC_DIR / "fonts" / "geist-mono.woff2", media_type="font/woff2")


# --- Machi PWA ---------------------------------------------------------------
# A separate shell with its own route table, manifest and SW, sharing the
# same JS modules, CSS, fonts and API as the mobed app.

@app.get("/machi", include_in_schema=False)
def machi_ui() -> FileResponse:
    return FileResponse(_MACHI_DIR / "index.html", media_type="text/html")


@app.get("/machi-manifest.json", include_in_schema=False)
def machi_manifest() -> FileResponse:
    return FileResponse(_STATIC_DIR / "machi-manifest.json", media_type="application/manifest+json")


@app.get("/machi-sw.js", include_in_schema=False)
def machi_service_worker() -> FileResponse:
    return FileResponse(_STATIC_DIR / "machi-sw.js", media_type="application/javascript")


# --- Privacy policy ----------------------------------------------------------
# Served by both apps on every hostname, deliberately unauthenticated and
# JS-free: Meta will not publish the app without a policy URL its reviewer
# can fetch, and a reviewer is not going to sign in with WhatsApp to read it.
# A flat file rather than a PWA route for the same reason - it has to render
# with no session, no service worker and no JavaScript at all.
@app.get("/privacy", include_in_schema=False)
def privacy_policy() -> FileResponse:
    return FileResponse(_STATIC_DIR / "privacy.html", media_type="text/html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
