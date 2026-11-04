# Name book: from photographed pages to saved names

Asked for by a senior Mumbai mobed: a family's namgharan book is handwritten in Gujarati
and kept at the fire temple; he wants it in the app. Planned with the owner, 4-5 Nov 2026.

## What it is

A **one-time move from paper into the app.** The mobed opens a behdin, photographs that
family's book (one book or one page per family), checks what was read, and confirms. The
names become that behdin's **saved names**, exactly as if typed: departed pairs and
farmayeshne names, used by every Afringan, Farokshi and slip. From then on the app is the
book; the mobed edits, reorders and deletes names as today. Nothing is photographed again.

## Settled

- **Whose:** the mobed's own behdin record. Not shared with the temple or other mobeds
  (D2 unchanged).
- **The page:** a line with two names is a departed pair, one name is farmayeshne (the
  rule the app already uses). A struck-out name is removed. No other marks matter.
  Death dates are not read; memorials and the calendar are out of scope.
- **The family is chosen by the mobed**, not read from the page. Phone numbers on the page
  are never read.
- **Script:** saved names stay in English letters (no change to slips, WhatsApp or the
  PDF). What the reader saw in Gujarati is kept with the page, for the review and for
  later doubts. Spelling does not matter to mobeds; the name does.
- **Nothing is saved until the mobed confirms**, except the photo, which is saved at once
  so an interrupted review loses nothing. Photos are kept for good (D8): after a one-time
  import they are the only way to settle "was it really Rustom?".
- **Confirming only adds.** Names already saved are marked and skipped (spelling-blind).

## How a page is read

- The reader is a swappable part: Claude (online) or a local open model (nothing leaves the
  server). Chosen by the sample test, not assumed.
- Rules given to every reader: never guess a name (mark it unreadable); never leave out a
  name (an unreadable half keeps its pair); a smudge, stain or fold is not a strikeout.
- Our own code, not the model, turns lines into pairs and farmayeshne.
- Each page is read twice; names the two readings disagree on are flagged.
- The review screen opens on flagged names first: photo, the Gujarati read, the English
  proposed, with one tap to fix, to switch pair/farmayeshne, or to bring back a name
  called struck. "I'll type it myself" gives the same screen empty.

## Data (one migration)

- `name_book_pages`: behdin, mobed, order in the book, photo hash (no double upload), the
  reader's draft (JSON, incl. Gujarati), which reader and when, status
  uploaded / read / confirmed. Goes with the behdin.
- `name_book_page_images`: the photo, 2576 px long edge JPEG (~0.4 MB), in Postgres so the
  nightly encrypted backup carries it.
- `customer_saved_names.source_page_id` (nullable): "from page 2 of the book".
- Erasure and account deletion (D6) take pages and photos too, with tests.

## Privacy and cost

- **Claude:** the photo and our instructions leave the server, nothing else. Anthropic
  does not train on API data by default and deletes it within 30 days. The mobed is told
  so on screen before the first read, and can always type instead. `privacy.html` must
  name Anthropic as a processor (add to the lawyer's list).
- **Cost (to be measured):** about $0.10-0.20 per reading with Opus 5.5, so $0.20-0.40 a
  page read twice, about $1 for a 3-page book, once.
- **Local model:** no data leaves; free per page, but needs memory and time on the server
  (no GPU), so reading would run in the background.

## Steps (check in with the owner before each)

1. **Sample test** (in progress). `tools/namebook_eval/`: read 5-8 real pages, from neat
   to worst, with Claude Opus 5.5 and two local models (Qwen3-VL 8B, Gemma 3 12B), score
   against a transcription typed by someone who reads the hand. Photos and results live in
   `namebook-samples/`, which is never committed. Decide the reader, or whether to read at
   all, on the numbers. Invented and sure-but-wrong names are what count most.
2. Migration + storage + upload API + tests (no reading yet; "type it myself" works).
3. The reader behind the API, background job, twice-read flagging.
4. The review screen (build-free JS), confirm into saved names.
5. Privacy notice, `privacy.html`, erasure; then try it with the mobed on real books.

## Step 1 results so far (5 Nov 2026)

- Qwen3-VL 8B (local): never answered - looped past 3,000 tokens, thinking on or off. Out.
- Gemma 3 12B (local, laptop CPU, ~6 min a page), 3 handwritten sheets, 35 names: 12
  right; on the messy sheet it returned only the titles, every one marked "clear"; never
  once said "unsure"; missed both strikeouts; merged single names into pairs. Confident
  nonsense is the one failure the review screen cannot catch. Not usable.
- Titles are sometimes abbreviated (બ. ઓ. એ.); the instructions now cover it. ઓ. is
  osta or osti by the name's gender, so the title can be wrong on unfamiliar names.
- Still to run: Claude Opus 5.5 (needs the key), and real pages from a temple book.

## Open

- Which reader, from step 1. Local models on hardware like ours look out of the running.
