"""Score what each reader said against what the page really says.

    uv run --group eval python -m tools.namebook_eval.score namebook-samples [--detail]

The truth for page `X.jpg` is `X.truth.txt`, typed by someone who reads the hand. One
line per line of the book, top to bottom, in Gujarati or English letters - whichever is
easier; the reader's answer in the same script is compared:

    # a comment
    behdin Rustom | behdin Jamshed      <- a pair
    osti Dhun                           <- a single (farmayeshne) name
    ~ behdin Sorab | behdin Framroz     <- struck out on the page
    behdin ? | ervad Hormuzd            <- ? is a name nobody can read (not scored)

The title is optional. Spelling does not count (the owner: mobeds care about the
name, not its spelling), so "Firoz", "Feroze" and "Phiroze" are the same name.

What is counted, worst first:
  invented          a name the reader gave that is not on the page - a mobed would
                    recite it
  wrong (sure)      the wrong name, given as clear
  missed            a name on the page the reader left out, or wrongly called struck
  wrong section     a pair read as a single name, or the reverse
  wrong (flagged)   the wrong name, but marked unsure / unreadable - the review screen
                    sends the mobed straight to it, so this is the acceptable kind
With two runs, "caught" is how many sure-but-wrong names the second reading disagreed
with - i.e. would have been flagged anyway.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

SAME_NAME = 0.75  # similarity of the normalised spellings at which two names are one name
TITLE_WORDS = {
    "khud", "osta", "osti", "ervad", "behdin", "none",
    "ખુદ", "ઓસ્તા", "ઓસ્તી", "એરવદ", "એર્વદ", "બેહદીન", "બહેદીન", "બહેદિન",
}
GUJARATI = re.compile(r"[઀-૿]")


# --- spelling-blind keys ---------------------------------------------------------

def key_en(name: str) -> str:
    s = re.sub(r"[^a-z]", "", name.lower())
    for a, b in (("ee", "i"), ("oo", "u"), ("ph", "f"), ("w", "v"), ("y", "i")):
        s = s.replace(a, b)
    s = re.sub(r"(?<=[bcdfgjklmnpqrstvxz])h", "", s)  # Dhun/Dun, Khorshed/Korshed
    s = re.sub(r"(.)\1+", r"\1", s)  # Jamsshed, Rusttom
    s = re.sub(r"(?<=.{3})(ji|jee|bai)$", "", s)  # Sorabji = Sorab, Dhunbai = Dhun
    return s


def key_gu(name: str) -> str:
    s = "".join(GUJARATI.findall(unicodedata.normalize("NFC", name)))
    s = s.replace("ી", "િ").replace("ૂ", "ુ")  # long i/u = short
    return s.replace("ં", "").replace("઼", "")  # anusvara, nukta


def strip_title(name: str) -> str:
    """Drop a title written into the name itself. Readers are told to keep it apart, but
    Gemma 3 put it in anyway ("Behdin Rustom"); the app strips it the same way."""
    words = name.split()
    while words and words[0].lower().strip(".") in TITLE_WORDS:
        words = words[1:]
    return " ".join(words)


def same_name(truth: str, read_en: str, read_gu: str) -> float:
    """Similarity 0..1 of a true name and a reading, in the truth's own script."""
    read_en, read_gu = strip_title(read_en), strip_title(read_gu)
    if GUJARATI.search(truth):
        a, b = key_gu(truth), key_gu(read_gu)
    else:
        a, b = key_en(truth), key_en(read_en)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


# --- the two sides ----------------------------------------------------------------

@dataclass
class TruthLine:
    names: list[str | None]  # None: a name nobody can read
    struck: bool


@dataclass
class ReadName:
    english: str
    gujarati: str
    legibility: str  # clear | unsure | unreadable


@dataclass
class ReadLine:
    names: list[ReadName]
    struck: str  # no | yes | unsure


def parse_truth(text: str) -> list[TruthLine]:
    lines = []
    for raw in text.splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        struck = raw.startswith("~")
        names: list[str | None] = []
        for part in raw.lstrip("~").split("|"):
            words = part.split()
            if words and words[0].lower() in TITLE_WORDS:
                words = words[1:]
            name = " ".join(words)
            names.append(None if name in ("", "?") else name)
        lines.append(TruthLine(names, struck))
    return lines


def parse_reading(page: dict) -> list[ReadLine]:
    return [
        ReadLine(
            [ReadName(n["english"], n["gujarati"], n["legibility"]) for n in line["names"]],
            line["struck_out"],
        )
        for line in page["lines"]
    ]


# --- lining the two up ------------------------------------------------------------

def _pairings(n_t: int, n_r: int) -> list[list[tuple[int, int]]]:
    """Ways to match names within a line: in order, or (for two and two) swapped."""
    straight = [(i, i) for i in range(min(n_t, n_r))]
    return [straight, [(0, 1), (1, 0)]] if n_t == n_r == 2 else [straight]


def _sim(t: str | None, r: ReadName) -> float:
    return 0.5 if t is None else same_name(t, r.english, r.gujarati)


def line_match(t: TruthLine, r: ReadLine) -> tuple[float, list[tuple[int, int]]]:
    best = (0.0, [])
    for pairing in _pairings(len(t.names), len(r.names)):
        total = sum(_sim(t.names[i], r.names[j]) for i, j in pairing)
        score = total / max(len(t.names), len(r.names), 1)
        if score > best[0] or not best[1]:
            best = (score, pairing)
    return best


def align(truth: list[TruthLine], read: list[ReadLine]) -> list[tuple[int | None, int | None]]:
    """Line up truth and reading in order (a reader may skip or add lines)."""
    n, m = len(truth), len(read)
    sims = [[line_match(t, r)[0] for r in read] for t in truth]
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            take = sims[i][j] + dp[i + 1][j + 1] if sims[i][j] >= 0.3 else -1.0
            dp[i][j] = max(take, dp[i + 1][j], dp[i][j + 1])
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if sims[i][j] >= 0.3 and dp[i][j] == sims[i][j] + dp[i + 1][j + 1]:
            pairs.append((i, j))
            i, j = i + 1, j + 1
        elif dp[i][j] == dp[i + 1][j]:
            pairs.append((i, None))
            i += 1
        else:
            pairs.append((None, j))
            j += 1
    pairs += [(k, None) for k in range(i, n)] + [(None, k) for k in range(j, m)]
    return pairs


def disputed_names(run1: list[ReadLine], run2: list[ReadLine]) -> set[tuple[int, int]]:
    """Names in run 1 that run 2 read differently or not at all."""
    as_truth = [TruthLine([n.english or None for n in line.names], line.struck == "yes")
                for line in run1]
    out = set()
    for i, j in align(as_truth, run2):
        if i is None:
            continue
        if j is None:
            out.update((i, k) for k in range(len(run1[i].names)))
            continue
        _, pairing = line_match(as_truth[i], run2[j])
        matched = {a for a, _ in pairing}
        for a, b in pairing:
            t = as_truth[i].names[a]
            if t is None or same_name(t, run2[j].names[b].english, "") < SAME_NAME:
                out.add((i, a))
        out.update((i, k) for k in range(len(run1[i].names)) if k not in matched)
    return out


# --- the score --------------------------------------------------------------------

def score_page(truth: list[TruthLine], read: list[ReadLine],
               disputed: set[tuple[int, int]] = frozenset(), detail: list | None = None) -> Counter:
    c: Counter = Counter()
    note = detail.append if detail is not None else (lambda *_: None)
    for t in truth:
        if not t.struck:
            c["names on page"] += sum(n is not None for n in t.names)
    for ti, ri in align(truth, read):
        t = truth[ti] if ti is not None else None
        r = read[ri] if ri is not None else None
        if r is None:
            if not t.struck:
                c["missed"] += sum(n is not None for n in t.names)
                note(f"missed line: {t.names}")
            continue
        if t is None:
            if r.struck != "yes":
                for n in r.names:
                    if n.legibility == "unreadable":
                        continue
                    c["invented" if n.legibility == "clear" else "invented (flagged)"] += 1
                    note(f"invented, {n.legibility}: {n.english!r}/{n.gujarati!r}")
            continue
        if len(t.names) != len(r.names):
            c["wrong section"] += 1
            note(f"section: page has {len(t.names)} name(s), read {len(r.names)}")
        if t.struck:
            if r.struck == "no":
                c["struck name read as live"] += 1
                note(f"struck on the page but read as live: {t.names}")
            continue
        if r.struck == "yes":
            c["missed"] += sum(n is not None for n in t.names)
            c["dropped as struck"] += 1
            note(f"wrongly called struck: {t.names}")
            continue
        if r.struck == "unsure":
            c["strike flagged"] += 1
        _, pairing = line_match(t, r)
        matched_t = {a for a, _ in pairing}
        matched_r = {b for _, b in pairing}
        for a, b in pairing:
            name, got = t.names[a], r.names[b]
            if name is None:
                continue
            if same_name(name, got.english, got.gujarati) >= SAME_NAME:
                c["correct"] += 1
                if got.legibility != "clear":
                    c["correct but flagged"] += 1
            elif got.legibility != "clear":
                c["wrong (flagged)"] += 1
                note(f"wrong, flagged {got.legibility}: page {name!r}, read {got.english!r}/{got.gujarati!r}")
            else:
                c["wrong (sure)"] += 1
                if (ri, b) in disputed:
                    c["wrong (sure), caught by run 2"] += 1
                note(f"WRONG, given as clear: page {name!r}, read {got.english!r}/{got.gujarati!r}")
        c["missed"] += sum(1 for a, n in enumerate(t.names) if a not in matched_t and n is not None)
        for b, n in enumerate(r.names):
            if b in matched_r:
                continue
            if n.legibility == "unreadable":
                c["blank slot added"] += 1
                note("an unreadable name added where the page has none")
            else:
                c["invented" if n.legibility == "clear" else "invented (flagged)"] += 1
                note(f"invented, {n.legibility}: {n.english!r}/{n.gujarati!r}")
    return c


ROWS = [
    "names on page", "correct", "correct but flagged", "invented", "wrong (sure)",
    "wrong (sure), caught by run 2", "missed", "dropped as struck", "wrong section",
    "struck name read as live", "invented (flagged)", "wrong (flagged)", "blank slot added",
    "strike flagged",
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("samples", type=Path)
    ap.add_argument("--detail", action="store_true", help="list every mistake, page by page")
    args = ap.parse_args(argv)
    # The Windows console defaults to cp1252, which has no Gujarati letters.
    sys.stdout.reconfigure(encoding="utf-8")

    truths ={p.name.removesuffix(".truth.txt"): parse_truth(p.read_text(encoding="utf-8"))
              for p in args.samples.glob("*.truth.txt")}
    results = args.samples / "results"
    if not truths or not results.is_dir():
        print("Need <page>.truth.txt files and a results/ folder (run read.py first).")
        return 1

    table: dict[str, Counter] = {}
    timing: dict[str, list[float]] = {}
    for reader_dir in sorted(p for p in results.iterdir() if p.is_dir()):
        total, secs, cost = Counter(), [], 0.0
        for page, truth in sorted(truths.items()):
            runs = [json.loads(f.read_text(encoding="utf-8"))
                    for f in sorted(reader_dir.glob(f"{page}.run*.json"))]
            if not runs:
                continue
            total["pages"] += 1
            first = runs[0]
            secs.append(first["seconds"])
            cost += sum(r.get("cost_usd", 0) for r in runs)
            if first["page"] is None:
                total["failed readings"] += 1
                total["names on page"] += sum(n is not None for t in truth if not t.struck for n in t.names)
                total["missed"] += sum(n is not None for t in truth if not t.struck for n in t.names)
                continue
            read = parse_reading(first["page"])
            disputed = set()
            if len(runs) > 1 and runs[1]["page"] is not None:
                disputed = disputed_names(read, parse_reading(runs[1]["page"]))
            lines: list[str] = []
            total += score_page(truth, read, disputed, lines)
            if args.detail and lines:
                print(f"\n[{reader_dir.name}] {page}")
                for line in lines:
                    print("   ", line)
        if total["pages"]:
            table[reader_dir.name] = total
            timing[reader_dir.name] = [sum(secs) / len(secs), cost / total["pages"]]

    readers = list(table)
    width = max(len(r) for r in ["what", *ROWS])
    print("\n" + "what".ljust(width) + "".join(f"  {r[:22]:>22}" for r in readers))
    for row in ["pages", "failed readings", *ROWS]:
        cells = []
        for r in readers:
            v, base = table[r][row], table[r]["names on page"]
            pct = f" ({100 * v / base:.0f}%)" if base and row not in ("pages", "names on page", "failed readings") else ""
            cells.append(f"  {f'{v}{pct}':>22}")
        print(row.ljust(width) + "".join(cells))
    print("seconds per page".ljust(width) + "".join(f"  {timing[r][0]:>22.0f}" for r in readers))
    print("US$ per page (all runs)".ljust(width) + "".join(f"  {timing[r][1]:>22.3f}" for r in readers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
