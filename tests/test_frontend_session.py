"""The PWA's session and shell code, run for real under Node.

There is no build step and no browser in the suite, but the modules that keep
a mobed signed in (api.js, state.js) and the service worker touch nothing of
the page, so Node can run them with fetch, the cache and storage stubbed.
These are the regressions from the 30 Oct 2026 audit: a refresh that ended its
own session (FE-01), a server error taken for a sign-out (FE-02), an error
page cached over a working app (FE-03), and a phone number kept after sign-out
(FE-07). Skipped where Node is not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "src" / "agyary" / "api" / "static"
JS = STATIC / "mobed" / "js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed")


def _node(script: str) -> dict:
    """Run an ES module script; it prints one JSON line, which is returned."""
    done = subprocess.run(
        [NODE, "--no-warnings", "--input-type=module", "-e", script],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def _module(path: Path) -> str:
    return path.resolve().as_uri()


STORAGE = """
const store = new Map();
globalThis.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
};
"""


def test_parallel_calls_share_one_refresh():
    """Three calls that all meet an expired token make ONE refresh, not three
    with the same cookie (the server ends the session on the second)."""
    out = _node(STORAGE + f"""
const {{ api, tryRefresh }} = await import({json.dumps(_module(JS / "api.js"))});
let refreshes = 0;
globalThis.fetch = async (url, opts) => {{
  if (url.endsWith("/auth/refresh")) {{
    refreshes += 1;
    await new Promise(r => setTimeout(r, 30));
    return new Response(JSON.stringify({{ access_token: "fresh" }}), {{ status: 200 }});
  }}
  const auth = (opts.headers || {{}})["Authorization"];
  return auth === "Bearer fresh"
    ? new Response(JSON.stringify({{ ok: true }}), {{ status: 200 }})
    : new Response(JSON.stringify({{ detail: "expired" }}), {{ status: 401 }});
}};
const results = await Promise.all([api("/a"), api("/b"), api("/c")]);
const parallel = refreshes;
await tryRefresh();
console.log(JSON.stringify({{ parallel, after: refreshes, results }}));
""")
    assert out["parallel"] == 1
    assert out["results"] == [{"ok": True}] * 3
    assert out["after"] == 2          # a later refresh is a new one, not a stale answer


def test_a_refusal_mid_use_goes_to_sign_in():
    """FE-09: a definitive 401 raised jargon and left the mobed on a dead screen."""
    out = _node(STORAGE + f"""
const {{ api }} = await import({json.dumps(_module(JS / "api.js"))});
const {{ state }} = await import({json.dumps(_module(JS / "state.js"))});
state.user = {{ id: 1 }};
let told = 0;
globalThis.dispatchEvent = () => {{ told += 1; }};
globalThis.fetch = async () => new Response(JSON.stringify({{ detail: "ended" }}), {{ status: 401 }});
let status = null;
try {{ await api("/x"); }} catch (e) {{ status = e.status; }}
console.log(JSON.stringify({{ told, status }}));
""")
    assert out == {"told": 1, "status": 401}


def test_a_broken_address_and_blocked_storage_do_not_crash():
    """FE-10, FE-11. Both modules need a page to run, so this pins the shape."""
    drafts = (JS / "drafts.js").read_text(encoding="utf-8")
    clear = drafts[drafts.index("export function clearAllDrafts"):]
    assert clear.index("try {") < clear.index("globalThis[name]")
    router = (JS / "router.js").read_text(encoding="utf-8")
    assert "try {" in router[router.index("function match("):router.index("decodeURIComponent") + 80]


def test_the_shell_is_precached_fresh_from_the_network():
    """FE-06."""
    assert '{ cache: "reload" }' in (STATIC / "mobed-sw.js").read_text(encoding="utf-8")


def test_a_code_found_on_the_clipboard_is_not_sent_by_itself():
    """FE-14: a lone six digits could be a bank's code."""
    login = (JS / "screens" / "login.js").read_text(encoding="utf-8")
    quiet = login[login.index("const quietRead"):login.index('addEventListener("visibilitychange"')]
    assert "fill(code, { send: false })" in quiet


def test_tappable_rows_reach_the_keyboard():
    """UX-04: everything the screens wire up as a row is covered by one list."""
    ui = (JS / "ui.js").read_text(encoding="utf-8")
    for row in (".search-result", ".section-bar", ".event", ".geh-slot.booked", ".geh-slot.open",
                ".note.tap", ".obs-head", "[data-oid]"):
        assert row in ui
    assert 'e.key !== "Enter" && e.key !== " "' in ui


def test_only_a_401_means_signed_out():
    """FE-02: a 5xx, Cloudflare's 52x or a 429 says nothing about the session.
    Treated as a refusal, boot cleared the session and every draft. Our own
    refresh refuses only with a 401; a 403 could only be Cloudflare's block page."""
    out = _node(STORAGE + f"""
const {{ tryRefresh, REFRESH_OFFLINE }} = await import({json.dumps(_module(JS / "api.js"))});
const seen = {{}};
for (const status of [401, 403, 429, 500, 502, 503, 530]) {{
  globalThis.fetch = async () => new Response("{{}}", {{ status }});
  const r = await tryRefresh();
  seen[status] = r === REFRESH_OFFLINE ? "offline" : r;
}}
globalThis.fetch = async () => {{ throw new TypeError("network"); }};
seen.network = (await tryRefresh()) === REFRESH_OFFLINE ? "offline" : "other";
console.log(JSON.stringify(seen));
""")
    assert out == {"401": False, "403": "offline", "429": "offline", "500": "offline", "502": "offline",
                   "503": "offline", "530": "offline", "network": "offline"}


def _run_worker(network_status: int) -> dict:
    return _node(f"""
import {{ readFileSync }} from "node:fs";
const listeners = {{}};
const puts = [];
const self = {{
  addEventListener: (type, fn) => {{ listeners[type] = fn; }},
  skipWaiting: () => {{}}, clients: {{ claim: () => {{}} }},
}};
const caches = {{
  open: async () => ({{ put: async (req, res) => {{ puts.push(await res.text()); }} }}),
  match: async () => new Response("cached shell", {{ status: 200 }}),
  keys: async () => [],
}};
const fetch = async () => new Response("from network", {{ status: {network_status} }});
const source = readFileSync({json.dumps(str(STATIC / "mobed-sw.js"))}, "utf8");
new Function("self", "caches", "fetch", source)(self, caches, fetch);
let responded, waited = [];
listeners.fetch({{
  request: new Request("https://mobed.example/mobed"),
  respondWith: p => {{ responded = p; }},
  waitUntil: p => {{ waited.push(p); }},
}});
const res = await responded;
await Promise.all(waited);
console.log(JSON.stringify({{ status: res.status, body: await res.text(), puts }}));
""")


def test_the_service_worker_never_caches_or_shows_an_error_page():
    """FE-03: a 502 during a deploy is not cached over the shell, and the
    cached shell is shown instead of the error."""
    bad = _run_worker(502)
    assert bad == {"status": 200, "body": "cached shell", "puts": []}
    good = _run_worker(200)
    assert good == {"status": 200, "body": "from network", "puts": ["from network"]}


def test_the_cached_shell_is_shown_when_the_network_is_too_slow():
    """FE-05: on "connected but dead" signal the launch does not hang. The fetch
    is left running, and what it brings is still cached for next time."""
    out = _node(f"""
import {{ readFileSync }} from "node:fs";
const listeners = {{}}, puts = [];
const self = {{ addEventListener: (type, fn) => {{ listeners[type] = fn; }},
  skipWaiting: () => {{}}, clients: {{ claim: () => {{}} }} }};
const caches = {{
  open: async () => ({{ put: async (req, res) => {{ puts.push(await res.text()); }} }}),
  match: async () => new Response("cached shell", {{ status: 200 }}),
}};
let arrive;
const fetch = () => new Promise(resolve => {{ arrive = resolve; }});
const quick = (fn) => globalThis.setTimeout(fn, 0);
const source = readFileSync({json.dumps(str(STATIC / "mobed-sw.js"))}, "utf8");
new Function("self", "caches", "fetch", "setTimeout", source)(self, caches, fetch, quick);
let responded, waited = [];
listeners.fetch({{ request: new Request("https://mobed.example/mobed"),
  respondWith: p => {{ responded = p; }}, waitUntil: p => {{ waited.push(p); }} }});
const res = await responded;
const shown = await res.text();
arrive(new Response("new shell", {{ status: 200 }}));
await Promise.all(waited);
console.log(JSON.stringify({{ shown, puts }}));
""")
    assert out == {"shown": "cached shell", "puts": ["new shell"]}


def test_a_request_that_never_answers_gives_up_with_plain_words():
    """FE-05: a save or a screen must not hang for ever."""
    out = _node(STORAGE + f"""
const realTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms) => realTimeout(fn, ms > 1000 ? 5 : ms);
const {{ api, tryRefresh, REFRESH_OFFLINE }} = await import({json.dumps(_module(JS / "api.js"))});
globalThis.fetch = (url, opts) => new Promise((_, no) => {{
  opts.signal.addEventListener("abort", () => no(Object.assign(new Error("stop"), {{ name: "AbortError" }})));
}});
let failure;
try {{ await api("/slow"); }} catch (e) {{ failure = {{ status: e.status, detail: e.detail }}; }}
const refresh = (await tryRefresh()) === REFRESH_OFFLINE;
console.log(JSON.stringify({{ failure, refresh }}));
""")
    assert out["failure"]["status"] == 0 and "too long" in out["failure"]["detail"]
    assert out["refresh"] is True


def test_a_failed_load_is_never_shown_as_an_empty_day():
    """UX-01. renderCalendar, ui.js and the screens need a page to run, so this
    pins the shape: the browser check is in the audit's ACTION-LIST."""
    calendar = (JS / "calendar.js").read_text(encoding="utf-8")
    assert "loadFailedHtml(what" in calendar and "items.incomplete" in calendar
    tab = (JS / "screens" / "calendar.js").read_text(encoding="utf-8")
    board = (JS / "screens" / "machi_calendar.js").read_text(encoding="utf-8")
    assert ".catch(() => [])" not in tab and "Promise.allSettled" in tab
    assert "catch (e)" not in board[board.index("async function loadItems"):board.index("function gehSlotHtml")]
    behdins = (JS / "screens" / "behdins.js").read_text(encoding="utf-8")
    assert "getBehdin(aid, cid).catch(ifMissing(null))" in behdins


def test_signing_out_with_no_signal_says_so_and_keeps_the_session():
    """FE-04: only the server can clear the cookie, so a sign-out that never
    reached it left the phone to sign itself back in."""
    session = (JS / "session.js").read_text(encoding="utf-8")
    sign_out = session[session.index("export async function signOut"):]
    assert sign_out.index("e.status === 0 || e.status >= 500") < sign_out.index("clearSession()")
    # Settings and the waiting screen (D9) both sign out through it.
    menu = (JS / "screens" / "menu.js").read_text(encoding="utf-8")
    waiting = (JS / "screens" / "waiting.js").read_text(encoding="utf-8")
    assert "signOut(ev.currentTarget)" in menu and "signOut(ev.currentTarget)" in waiting


def test_signing_out_forgets_the_last_phone_number():
    """FE-07: the number typed at sign-in is forgotten on sign-out and on
    account deletion, so a lent phone does not offer it to the next person."""
    out = _node(STORAGE + f"""
const {{ LAST_PHONE_KEY, forgetLastPhone }} = await import({json.dumps(_module(JS / "state.js"))});
localStorage.setItem(LAST_PHONE_KEY, "+919944400001");
forgetLastPhone();
console.log(JSON.stringify({{ key: LAST_PHONE_KEY, left: localStorage.getItem(LAST_PHONE_KEY) }}));
""")
    assert out == {"key": "mobed_last_phone", "left": None}
    session = (JS / "session.js").read_text(encoding="utf-8")
    sign_out = session[session.index("export async function signOut"):session.index("export function hasAccess")]
    menu = (JS / "screens" / "menu.js").read_text(encoding="utf-8")
    delete = menu[menu.index('getElementById("mDeleteYes")'):menu.index('getElementById("mSignOut")')]
    assert "forgetLastPhone()" in sign_out and "forgetLastPhone()" in delete


def test_the_slip_delete_question_is_brought_into_view_and_focused():
    """At 390 px the question opened under the tab bar and focus stayed on the
    button that opened it (audit evidence 390-slip-delete-confirm-hidden.jpg)."""
    slip = (JS / "screens" / "slip.js").read_text(encoding="utf-8")
    opener = slip[slip.index('getElementById("slipDeleteOpen")'):]
    assert 'id="delAsk" tabindex="-1"' in opener
    assert "panel.scrollIntoView(" in opener and 'getElementById("delAsk").focus(' in opener


def test_the_sign_up_name_step_fits_a_doongerwadi_manager_too():
    """The name is asked before a new account says what it is, so a Doongerwadi or prayer
    hall manager read that it was for "your slips" (a mobed's thing). A mobed still reads
    about slips; a manager's own screens never mention them."""
    login = (JS / "screens" / "login.js").read_text(encoding="utf-8")
    step = login[login.index("function renderWaNameStep"):login.index("async function finishSignIn")]
    assert "This is the name that will appear on your slips." not in step
    assert "This is your name in Mobed Diary. For a mobed, it is also the name on your slips." in step
    for screen in ("manager.js", "manager_record.js", "manager_behdins.js", "waiting.js"):
        assert "slip" not in (JS / "screens" / screen).read_text(encoding="utf-8").lower(), screen


def test_sign_up_and_other_moments_are_shown_in_india_time():
    """Admin -> Mobeds showed "Signed up" as the first ten characters of the server's UTC
    timestamp: the day in UK time, a day early for anyone signing up before 5:30 am in India.
    The admin's recent failures and a behdin's STOP did the same with their day."""
    out = _node(STORAGE + f"""
const {{ istShortWhen, istYmd, istHm }} = await import({json.dumps(_module(JS / "util.js"))});
const late = "2026-11-21T20:15:00+00:00";   // 1:45 am on 22 Nov in India
console.log(JSON.stringify({{ day: istYmd(late), time: istHm(late), shown: istShortWhen(late) }}));
""")
    assert out["day"] == "2026-11-22" and out["time"] == "01:45"
    assert out["shown"].endswith(", 01:45") and "22" in out["shown"] and "21" not in out["shown"]
    for screen in ("admin_mobeds.js", "admin.js"):
        source = (JS / "screens" / screen).read_text(encoding="utf-8")
        assert ".slice(0, 10)" not in source and "istShortWhen(" in source, screen
    behdins = (JS / "screens" / "behdins.js").read_text(encoding="utf-8")
    assert "gregShort(istYmd(reminders.stopped_at))" in behdins


def test_the_bell_and_the_red_count_are_read_again_after_a_request_is_acted_on():
    """The bell kept what it had until the app was opened again, so a notice about a request
    just answered stayed there. Each action that worked now reads the bell and the Requests
    red count again: one read each per tap, never on a timer. The screens need a page to run,
    so this pins the shape."""
    notes = (JS / "notifications.js").read_text(encoding="utf-8")
    helper = notes[notes.index("export function refreshAfterAction"):]
    helper = helper[:helper.index("\n}") + 2]
    assert "refreshNotifications();" in helper and "refreshRequestCount();" in helper
    assert "setInterval" not in notes and "setTimeout" not in notes
    requests = (JS / "screens" / "requests.js").read_text(encoding="utf-8")
    # (where the code starts, where it ends, what the refresh comes after)
    for start, end, after in [
        ("async function answer(", "// --- All set", "await answerRequest("),          # I can pray / Not this time
        ("function confirmBackOut(", "async function answer(", "await backOutRequest("),  # I can't go any more
        ("async function act(", "async function refused(", "await call()"),             # Ask everyone, I'll pray
        ("function askGoing(", "// --- Confirm with who's going", "await boardCallResult("),
        ("function confirmShort(", "// --- Can't go", "await boardConfirmShort("),
        ("function confirmCantGo(", "// --- We can't take this", "await boardCantGo("),
        ("async function redrawSaying(", "// --- An app mobed", "async function redrawSaying("),
    ]:
        body = requests[requests.index(start):requests.index(end)]
        assert body.index(after) < body.index("refreshAfterAction();"), start
    decline = requests[requests.index("function confirmDecline("):]
    assert decline.index("await declineRequest(") < decline.index("redrawSaying(q, `Declined.")
    record = (JS / "screens" / "manager_record.js").read_text(encoding="utf-8")
    for start, end in [("function confirmElsewhere(", "function confirmWithdraw("),       # Send to another
                       ("function confirmWithdraw(", "// --- Choosing the fire temple"),  # Withdraw
                       ("function confirmSend(", "\n}\n")]:                              # Send
        body = record[record.index(start):]
        body = body[:body.index(end)]
        call = "await managerSend(" if start == "function confirmSend(" else "await managerWithdraw("
        assert body.index(call) < body.index("refreshAfterAction();"), start


def test_a_mobed_is_written_to_as_sahebji_and_their_first_name_never_namaste():
    """Owner, 22 Nov 2026: a Parsi app greets a mobed "Sahebji <first name>". The manager's ready
    message to the mobed or panthaky said "Namaste <full name>". A title typed before the name
    is skipped; a family is always addressed by their full name (not tested here)."""
    names = ["Er. Hormuz Dadachanji", "Ervad Hormuz Dadachanji", "Dasturji Dr. Hormuz D",
             "Hormuz Dadachanji", "Er.", "", "  Hormuz  ", "Dastur Rustom", "Shri Rustom"]
    out = _node(STORAGE + f"""
const {{ firstName }} = await import({json.dumps(_module(JS / "util.js"))});
console.log(JSON.stringify({json.dumps(names)}.map(firstName)));
""")
    # Only Parsi titles are skipped (owner's word review, 23 Nov 2026): "Dastur" is a
    # surname ("Dasturji" is the title), and there is no Shri or Smt.
    assert out == ["Hormuz", "Hormuz", "Hormuz", "Hormuz", "Er.", "", "Hormuz", "Dastur", "Shri"]
    # The server's own helper (the WhatsApp text to a mobed no longer needed) says the same.
    from agyary.services import funeral_whatsapp
    assert [funeral_whatsapp.first_name(n) for n in names] == out
    record = (JS / "screens" / "manager_record.js").read_text(encoding="utf-8")
    assert "recordMobedText(name, me, place, rec.prayed_name)" in record
    board = (JS / "screens" / "requests.js").read_text(encoding="utf-8")
    assert "askMobedText(b, m)" in board
    util = (JS / "util.js").read_text(encoding="utf-8")
    assert "const first = firstName(m && m.name);" in util and util.count("Sahebji ${first}") == 2
    for path in list(JS.rglob("*.js")) + list((JS.parent.parent / "behdin").rglob("*.js")):
        assert "namaste" not in path.read_text(encoding="utf-8").lower(), path


def _assert_layout(text: str) -> None:
    """The shape of every WhatsApp message (owner, 24 Nov 2026): the greeting alone on line 1,
    an empty line after it, never two empty lines in a row, no trailing spaces, no blank edges."""
    lines = text.split("\n")
    assert lines[0].startswith("Sahebji") and lines[0].endswith(",") and lines[1] == ""
    assert "\n\n\n" not in text and text == text.strip()
    assert all(line == line.rstrip() for line in lines)


def test_the_message_to_a_mobed_is_laid_out_in_short_lines():
    board = {"agyari": {"name": "Goti Adarian"}, "prayed_name": "Behdin Rustom", "place": {"name": "Doongerwadi (test)"},
             "geh_saarnu": {"text": "Tue 24/11/2026, Havan geh"}, "uthamna": {"text": "Thu 26/11/2026, 4:00 pm"}}
    out = _node(STORAGE + f"""
const {{ askMobedText, recordMobedText }} = await import({json.dumps(_module(JS / "util.js"))});
const b = {json.dumps(board)};
console.log(JSON.stringify([askMobedText(b, {{ name: "Er. Delzeen Mistry" }}),
  askMobedText({{ ...b, geh_saarnu: null, uthamna: null }}, {{ name: "" }}),
  recordMobedText("Er. Delzeen Mistry", "Er. Test", "Doongerwadi (test)", "Behdin Rustom"),
  recordMobedText("Delzeen", "", "", "Behdin Rustom")]));
""")
    assert out[0] == (
        "Sahebji Delzeen,\n\n"
        "A prayer request has come to Goti Adarian.\n\n"
        "*Prayers for:* Behdin Rustom\n*Place:* Doongerwadi (test)\n"
        "*Geh-saarnu:* Tue 24/11/2026, Havan geh\n*Uthamna:* Thu 26/11/2026, 4:00 pm\n\n"
        "Can you pray?")
    assert out[1].startswith("Sahebji,\n\n") and "Geh-saarnu" not in out[1] and "Uthamna" not in out[1]
    assert out[2] == "Sahebji Delzeen,\n\nThis is Er. Test of Doongerwadi (test).\n\nAbout the prayers for Behdin Rustom."
    assert out[3] == "Sahebji Delzeen,\n\nAbout the prayers for Behdin Rustom."
    for text in out:
        _assert_layout(text)
