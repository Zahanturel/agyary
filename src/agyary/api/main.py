import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from agyary.api.routes.calendar import router as calendar_router
from agyary.api.routes.chat import router as chat_router
from agyary.api.routes.mobed import router as mobed_router
from agyary.api.routes.whatsapp import router as whatsapp_router
from agyary.core.config import get_settings
from agyary.core.database import async_session_factory
from agyary.messaging import send_worker

settings = get_settings()
settings.validate_runtime_secrets()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    http_client = httpx.AsyncClient()
    semaphore = asyncio.Semaphore(send_worker.DEFAULT_MAX_CONCURRENT_SENDS)

    # Pick up anything left "pending" from an earlier ungraceful shutdown
    # before doing anything else - this machine reboots unattended.
    await send_worker.run_startup_sweep(async_session_factory, http_client, semaphore)

    worker_task = asyncio.create_task(
        send_worker.worker_loop(async_session_factory, http_client, semaphore)
    )
    sweep_task = asyncio.create_task(
        send_worker.sweep_loop(async_session_factory, http_client, semaphore)
    )
    try:
        yield
    finally:
        worker_task.cancel()
        sweep_task.cancel()
        await asyncio.gather(worker_task, sweep_task, return_exceptions=True)
        await http_client.aclose()


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
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
    if path == "/mobed" or path.startswith("/mobed-app"):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.include_router(calendar_router)
# The web-chat simulator is a development tool, not a customer-facing
# surface: it has no auth at all, takes the behdin's phone number as a
# request parameter, and will happily drive that person's whole
# conversation - read their upcoming bookings and saved names, book for
# them, cancel on them - for any number the caller cares to type. It also
# lists every agyari's admin names and phone numbers. Registered only in
# debug mode, the same gate already applied to docs_url/openapi_url above.
if settings.app_debug:
    app.include_router(chat_router)
app.include_router(mobed_router)
app.include_router(whatsapp_router)

_STATIC_DIR = Path(__file__).parent / "static"
_MOBED_DIR = _STATIC_DIR / "mobed"


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """mobed.gotiadarian.com is dedicated to the mobed PWA - the bare
    domain root would otherwise 404, which is exactly what people hit when
    a shared link doesn't include the /mobed path."""
    return RedirectResponse(url="/mobed")


@app.get("/chat", include_in_schema=False)
def chat_ui() -> FileResponse:
    """The WhatsApp-conversation simulator (vanilla HTML/JS).

    Debug-only, matching the /api/chat router gate above - serving the page
    without its API would just be a broken screen, and the page itself
    displays the admin phone numbers it fetches.
    """
    if not settings.app_debug:
        raise HTTPException(status_code=404)
    return FileResponse(_STATIC_DIR / "chat.html", media_type="text/html")


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


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
