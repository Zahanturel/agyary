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
    menu = (JS / "screens" / "menu.js").read_text(encoding="utf-8")
    sign_out = menu[menu.index('getElementById("mSignOut")'):]
    assert sign_out.index("e.status === 0 || e.status >= 500") < sign_out.index("clearSession()")


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
    menu = (JS / "screens" / "menu.js").read_text(encoding="utf-8")
    sign_out = menu[menu.index('getElementById("mSignOut")'):]
    delete = menu[menu.index('getElementById("mDeleteYes")'):menu.index('getElementById("mSignOut")')]
    assert "forgetLastPhone()" in sign_out and "forgetLastPhone()" in delete


def test_the_slip_delete_question_is_brought_into_view_and_focused():
    """At 390 px the question opened under the tab bar and focus stayed on the
    button that opened it (audit evidence 390-slip-delete-confirm-hidden.jpg)."""
    slip = (JS / "screens" / "slip.js").read_text(encoding="utf-8")
    opener = slip[slip.index('getElementById("slipDeleteOpen")'):]
    assert 'id="delAsk" tabindex="-1"' in opener
    assert "panel.scrollIntoView(" in opener and 'getElementById("delAsk").focus(' in opener
