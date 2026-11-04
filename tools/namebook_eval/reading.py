"""Reading one name-book page with a model: the instructions, the shape of the answer,
and the readers (Claude, or a local model through Ollama).

Every reader gets the same instructions and must answer in the same JSON shape, so
the scorer compares like with like. The reader is a swappable part on purpose: the
app will use whichever one the sample test shows can be trusted.

What a page is (settled with the owner, 5 Nov 2026): one family's namgharan book,
handwritten in Gujarati. A line with two names is a departed pair; a line with one
name is a farmayeshne (living) name. A struck-out name means removed. Nothing else
on the page matters - in particular phone numbers are never read out.
"""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from PIL import Image, ImageOps

# The most detail Claude's high-resolution tier takes in (2576 px long edge); a
# larger photo is only downscaled by the API anyway. The app will store this too.
LONG_EDGE = 2576

# Generous for a full page (each name is ~40 tokens of JSON); see read_with_ollama.
MAX_ANSWER_TOKENS = 3000

TITLES = ("khud","osta", "osti", "ervad", "behdin", "none")

PAGE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "description": "Every line that holds names, top to bottom, in the page's order.",
            "items": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "array",
                        "description": "The names on this line, in the order written. "
                        "Two for a pair, one for a farmayeshne name. A name that is "
                        "there but cannot be read is still listed, as unreadable.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "enum": list(TITLES)},
                                "gujarati": {
                                    "type": "string",
                                    "description": "The name exactly as written, in "
                                    "Gujarati script, without the title. Empty if unreadable.",
                                },
                                "english": {
                                    "type": "string",
                                    "description": "The usual Parsi spelling in English "
                                    "letters. Empty if unreadable.",
                                },
                                "legibility": {
                                    "type": "string",
                                    "enum": ["clear", "unsure", "unreadable"],
                                },
                            },
                            "required": ["title", "gujarati", "english", "legibility"],
                            "additionalProperties": False,
                        },
                    },
                    "struck_out": {"type": "string", "enum": ["no", "yes", "unsure"]},
                    "note": {
                        "type": "string",
                        "description": "Anything the mobed should know about this line "
                        "(smudge, stain, overwritten letter). Empty if nothing.",
                    },
                },
                "required": ["names", "struck_out", "note"],
                "additionalProperties": False,
            },
        },
        "page_note": {
            "type": "string",
            "description": "Headings or other text on the page that are not names, "
            "described briefly. Never copy out phone numbers.",
        },
    },
    "required": ["lines", "page_note"],
    "additionalProperties": False,
}

INSTRUCTIONS = """\
This is a photograph of one page of a Parsi Zoroastrian family's namgharan book: the
names a mobed recites in the Afringan, Farokshi and other prayers. It is handwritten in
Gujarati, by mobeds whose handwriting varies, and the page may be smudged, stained by
water or ink, folded or faded.

How the page is laid out:
- Each line holds either two names (a pair, for the departed) or one name (a
  farmayeshne name, for the living).
- A name is usually preceded by a title. Map it to one of: ઓસ્તા -> osta,
  ઓસ્તી -> osti, એરવદ / એર્વદ -> ervad, બેહદીન / બહેદીન -> behdin, ખુદ -> khud.
  Titles are often shortened to a letter and a dot: બ. -> behdin, એ. -> ervad, and ઓ.
  -> osta for a man's name, osti for a woman's name. If no title is written, use none.
  The title is never part of the name: do not repeat it in the gujarati or english field.
- A name with a deliberate line drawn through it has been struck out.

Read every line that holds names, top to bottom, and report it in the JSON format given.

Rules that matter more than anything else:
1. Never guess a name you cannot read. A mobed will recite whatever you report, so a
   plausible invented name is the worst possible mistake. If a name is there but you
   cannot read it, list it with legibility "unreadable" and leave its text empty. If you
   can read it but are not sure, give your best reading with legibility "unsure".
2. Never leave out a name that is there. If you can see the ink of a second name on a
   line but cannot read it, the line still has two names: one of them unreadable. But a
   line with only one name written on it has one name - do not add an unreadable one
   for empty space or for a smudge where nothing was written.
3. struck_out is "yes" only for a deliberate line through the name. A smudge, a stain,
   a fold or a crease is not a strikeout: say "no" and describe it in the note. If you
   cannot tell, say "unsure".
4. Write the Gujarati exactly as it is written, not corrected. Give the English in the
   usual Parsi spelling (for example Jamshed, Rustom, Dhun, Hormuzd).
5. Do not copy out phone numbers, addresses or anything that is not a name.
"""


def prepare_image(path: Path, long_edge: int = LONG_EDGE) -> bytes:
    """The photo upright (phones store rotation in EXIF), at most `long_edge` on its long
    side, as a high-quality JPEG - one compression pass, so the handwriting survives."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        scale = long_edge / max(im.size)
        if scale < 1:
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=92)
        return out.getvalue()


@dataclass
class Reading:
    reader: str
    page: dict | None
    seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    served_by: str = ""
    error: str = ""
    extra: dict = field(default_factory=dict)


def _api_key_from_env_file() -> str | None:
    """ANTHROPIC_API_KEY from the environment, else from the project's .env (where the
    owner keeps it, like the app's other secrets). Never printed, never in code. None
    lets the SDK look for other credentials and say clearly if there are none."""
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env = Path(__file__).resolve().parents[2] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ANTHROPIC_API_KEY" and value.strip():
                return value.strip().strip("'\"")
    return None


# Claude Opus 5.5 list price per million tokens (Oct 2026), for the cost column only.
CLAUDE_PRICE = {"claude-opus-5-5": (4.00, 20.00), "claude-sonnet-5-5": (2.00, 10.00)}


def read_with_claude(image: bytes, model: str = "claude-opus-5-5", effort: str = "high") -> Reading:
    """One reading by Claude. No refusal fallback on purpose: this measures one model,
    and a silent switch to another would spoil the comparison - a refusal is recorded
    as a failed reading instead."""
    import json

    import anthropic

    client = anthropic.Anthropic(api_key=_api_key_from_env_file())
    started = time.monotonic()
    with client.messages.stream(
        model=model,
        max_tokens=32000,
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": PAGE_SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(image).decode(),
                }},
                {"type": "text", "text": INSTRUCTIONS},
            ],
        }],
    ) as stream:
        msg = stream.get_final_message()
    took = time.monotonic() - started
    usage = dict(input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens)
    if msg.stop_reason != "end_turn":
        return Reading(f"claude:{model}", None, took, **usage, served_by=msg.model,
                       error=f"stop_reason={msg.stop_reason}")
    text = next(b.text for b in msg.content if b.type == "text")
    return Reading(f"claude:{model}", json.loads(text), took, **usage, served_by=msg.model)


def read_with_ollama(image: bytes, model: str, host: str = "http://127.0.0.1:11434") -> Reading:
    """One reading by a local model. Nothing leaves this computer."""
    import json

    started = time.monotonic()
    body = {
        "model": model,
        "stream": False,
        "format": PAGE_SCHEMA,
        # Thinking off: on the first smoke test (5 Nov 2026) Qwen3-VL wrote 3,700+ tokens
        # at ~3 tokens/s on this laptop's CPU for a 5-line page and never answered.
        "think": False,
        # A page's answer is a few hundred tokens; a model that runs past the cap is
        # repeating itself, and that is recorded as a failed reading, not waited out.
        "options": {"temperature": 0, "num_ctx": 16384, "num_predict": MAX_ANSWER_TOKENS},
        "messages": [{
            "role": "user",
            "content": INSTRUCTIONS,
            "images": [base64.standard_b64encode(image).decode()],
        }],
    }
    # On a laptop CPU one page can take many minutes.
    r = httpx.post(f"{host}/api/chat", json=body, timeout=httpx.Timeout(3600, connect=10))
    took = time.monotonic() - started
    if r.status_code != 200:
        return Reading(f"ollama:{model}", None, took, error=f"HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    usage = dict(input_tokens=data.get("prompt_eval_count", 0),
                 output_tokens=data.get("eval_count", 0))
    if data.get("done_reason") == "length":
        return Reading(f"ollama:{model}", None, took, **usage, served_by=model,
                       error=f"ran past {MAX_ANSWER_TOKENS} tokens without finishing (runaway)")
    try:
        page = json.loads(data["message"]["content"])
    except (KeyError, ValueError) as e:
        return Reading(f"ollama:{model}", None, took, **usage, served_by=model,
                       error=f"unparseable answer: {e}")
    return Reading(f"ollama:{model}", page, took, **usage, served_by=model)
