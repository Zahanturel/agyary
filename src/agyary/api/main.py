from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from agyary.api.routes.calendar import router as calendar_router
from agyary.api.routes.chat import router as chat_router
from agyary.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.include_router(calendar_router)
app.include_router(chat_router)

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/chat", include_in_schema=False)
def chat_ui() -> FileResponse:
    """The WhatsApp-conversation simulator (vanilla HTML/JS)."""
    return FileResponse(_STATIC_DIR / "chat.html", media_type="text/html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
