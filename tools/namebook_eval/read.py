"""Read every sample page with one reader and save what it said.

    uv run --group eval python -m tools.namebook_eval.read namebook-samples claude
    uv run --group eval python -m tools.namebook_eval.read namebook-samples ollama:qwen3-vl:8b

A reader is `claude`, `claude:<model>` or `ollama:<model>`. Each page is read --runs
times (default 2: two readings that disagree mark a name as doubtful). Answers go to
<samples>/results/<reader>/<page>.run<N>.json; a page already read is skipped, so a
long local run can be stopped and picked up again.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from tools.namebook_eval.reading import (
    CLAUDE_PRICE,
    LONG_EDGE,
    prepare_image,
    read_with_claude,
    read_with_ollama,
)

PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def slug(reader: str) -> str:
    return reader.replace(":", "_").replace("/", "_")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("samples", type=Path)
    ap.add_argument("reader")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--long-edge", type=int, default=LONG_EDGE)
    ap.add_argument("--only", help="read just this page (file name without extension)")
    args = ap.parse_args(argv)

    kind, _, model = args.reader.partition(":")
    if kind == "claude":
        model = model or "claude-opus-5-5"
        reader = f"claude:{model}"
    elif kind == "ollama" and model:
        reader = args.reader
    else:
        ap.error("reader must be claude, claude:<model> or ollama:<model>")

    photos = sorted(p for p in args.samples.iterdir() if p.suffix.lower() in PHOTO_SUFFIXES)
    if args.only:
        photos = [p for p in photos if p.stem == args.only]
    if not photos:
        print(f"No photos ({', '.join(sorted(PHOTO_SUFFIXES))}) in {args.samples}", file=sys.stderr)
        return 1

    out_dir = args.samples / "results" / slug(reader)
    out_dir.mkdir(parents=True, exist_ok=True)
    total_cost = 0.0
    for photo in photos:
        image = prepare_image(photo, args.long_edge)
        for run in range(1, args.runs + 1):
            out = out_dir / f"{photo.stem}.run{run}.json"
            if out.exists():
                print(f"{photo.name} run {run}: already read")
                continue
            print(f"{photo.name} run {run}: reading with {reader} ...", flush=True)
            if kind == "claude":
                reading = read_with_claude(image, model)
            else:
                reading = read_with_ollama(image, model)
            price = CLAUDE_PRICE.get(model)
            cost = (reading.input_tokens * price[0] + reading.output_tokens * price[1]) / 1e6 if price else 0.0
            total_cost += cost
            record = asdict(reading) | {"photo": photo.name, "run": run, "cost_usd": round(cost, 4)}
            out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            status = reading.error or f"{len(reading.page['lines'])} lines"
            print(f"  {status}; {reading.seconds:.0f}s; {reading.input_tokens}+{reading.output_tokens} "
                  f"tokens; ${cost:.3f}")
    if total_cost:
        print(f"Spent this run: ${total_cost:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
