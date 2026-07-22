import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse

from agyary.api.routes.calendar import router as calendar_router
from agyary.api.routes.chat import router as chat_router
from agyary.api.routes.whatsapp import router as whatsapp_router
from agyary.core.config import get_settings
from agyary.core.database import async_session_factory
from agyary.messaging import send_worker

settings = get_settings()


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


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.include_router(calendar_router)
app.include_router(chat_router)
app.include_router(whatsapp_router)

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/chat", include_in_schema=False)
def chat_ui() -> FileResponse:
    """The WhatsApp-conversation simulator (vanilla HTML/JS)."""
    return FileResponse(_STATIC_DIR / "chat.html", media_type="text/html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
