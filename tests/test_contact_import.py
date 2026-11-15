"""Import from contacts: the behdin's name and number read from the phone.

behdin_add.js is run for real under Node with the Contact Picker, the server
and as much of a page as it touches stubbed. What matters: an address book's
numbers come out as the one shape the server stores (or the same person is
saved twice, or as somebody in Iran), the mobile is taken over a landline,
someone already on file is chosen in the same tap, and someone new is shown
in the form for checking - never saved straight from the picker.
Skipped where Node is not installed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "src" / "agyary" / "api" / "static" / "mobed" / "js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed")

# Just enough page for ui.js to load, and for renderAddBehdin to draw into.
PAGE = """
const store = new Map();
globalThis.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
};
const banners = [];
const element = () => ({
  value: "", innerHTML: "", style: {}, dataset: {}, classList: { toggle() {}, add() {}, remove() {} },
  focus() {}, remove() {}, scrollIntoView() {}, querySelectorAll: () => [],
  prepend(el) { banners.push(el.textContent); },
});
const elements = new Map();
globalThis.document = {
  getElementById: id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
  createElement: element,
  documentElement: { dataset: {} },
  body: { classList: { toggle() {} } },
  addEventListener() {},
  querySelectorAll: () => [],
};
globalThis.MutationObserver = class { observe() {} };
globalThis.window = globalThis;
window.ContactsManager = function ContactsManager() {};
let picked = [];
Object.defineProperty(navigator, "contacts", {
  value: { select: async (props, opts) => { calls.select.push(opts); if (picked === "cancel") throw new Error("AbortError"); return picked; } },
});
const calls = { select: [], fetch: [] };
let onFile = [];
globalThis.fetch = async (url, opts) => {
  calls.fetch.push({ url, method: (opts && opts.method) || "GET" });
  return new Response(JSON.stringify(onFile), { status: 200 });
};
"""


def _run(body: str) -> dict:
    mod = json.dumps((JS / "behdin_add.js").resolve().as_uri())
    state = json.dumps((JS / "state.js").resolve().as_uri())
    script = PAGE + f"""
const add = await import({mod});
const {{ state }} = await import({state});
state.currentAgyaryId = 3;
{body}
"""
    done = subprocess.run(
        [NODE, "--no-warnings", "--input-type=module", "-e", script],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_contact_numbers_come_out_as_the_server_stores_them():
    cases = {
        "98200 12345": "+919820012345",
        "098200-12345": "+919820012345",        # a trunk 0, not Iran's +98
        "0 98200 12345": "+919820012345",
        "+91 98200 12345": "+919820012345",
        "+91 (0)98200 12345": "+919820012345",  # a trunk 0 after the code
        "0091 98200 12345": "+919820012345",
        "919820012345": "+919820012345",
        "022 2345 6789": "+912223456789",
        "+44 7700 900123": "+447700900123",
        "+1 (416) 555-0199": "+14165550199",
        "": "",
    }
    out = _run(f"""
const cases = {json.dumps(list(cases))};
console.log(JSON.stringify(Object.fromEntries(cases.map(c => [c, add.normalizeContactPhone(c)]))));
""")
    assert out == cases


def test_the_mobile_is_taken_over_a_landline_listed_first():
    out = _run("""
picked = [
  { name: ["Zubin Mistry"], tel: ["022 2345 6789", "98200 12345"] },
  { name: ["Farida Kaka"], tel: ["+44 20 7946 0958"] },
  { name: ["Only A Name"], tel: [] },
  { name: [], tel: ["99300 11223"] },
  { name: [], tel: ["12"] },
];
console.log(JSON.stringify(await add.pickContacts()));
""")
    assert out == [
        {"name": "Zubin Mistry", "phone": "+919820012345"},
        {"name": "Farida Kaka", "phone": "+442079460958"},
        {"name": "Only A Name", "phone": ""},
        {"name": "", "phone": "+919930011223"},
    ]


def test_someone_already_on_file_is_chosen_in_the_same_tap():
    out = _run("""
picked = [{ name: ["Zubin (plumber)"], tel: ["098200 12345"] }];
onFile = [{ id: 9, name: "Zubin Jamshed Mistry", phone: "+9198200123456" },
          { id: 7, name: "Zubin Mistry", phone: "+919820012345" }];
const chosen = [];
const panel = { innerHTML: "", querySelectorAll: () => [] };
const result = await add.chooseFromContacts(panel, { onChosen: b => chosen.push(b) });
console.log(JSON.stringify({ result, chosen, panel: panel.innerHTML, calls, banners }));
""")
    assert out["result"] == "chosen"
    assert out["chosen"] == [{"id": 7, "name": "Zubin Mistry", "phone": "+919820012345"}]
    assert out["panel"] == ""
    assert out["calls"]["select"] == [{"multiple": False}]
    [lookup] = out["calls"]["fetch"]
    assert lookup["method"] == "GET"
    assert lookup["url"].endswith("/agyaries/3/behdins?q=%2B919820012345")
    assert out["banners"] == ["Zubin Mistry is already on file."]


def test_someone_new_is_shown_for_checking_not_saved_from_the_picker():
    out = _run("""
picked = [{ name: ["Zubin <Plumber>"], tel: ["98200 12345"] }];
onFile = [{ id: 9, name: "A longer number", phone: "+9198200123456" }];
const chosen = [];
const panel = { innerHTML: "", querySelectorAll: () => [] };
const result = await add.chooseFromContacts(panel, { onChosen: b => chosen.push(b) });
console.log(JSON.stringify({ result, chosen, panel: panel.innerHTML, posts: calls.fetch.filter(f => f.method !== "GET") }));
""")
    assert out["result"] == "form"
    assert out["chosen"] == [] and out["posts"] == []
    assert 'value="Zubin &lt;Plumber&gt;"' in out["panel"]
    assert 'value="9820012345"' in out["panel"] and 'value="91"' in out["panel"]
    assert "Import from contacts" not in out["panel"]   # the button is the form's caller's


def test_a_contact_without_a_number_says_so():
    out = _run("""
picked = [{ name: ["Farida Kaka"], tel: [] }];
const panel = { innerHTML: "", querySelectorAll: () => [] };
const result = await add.chooseFromContacts(panel, { onChosen: () => {} });
console.log(JSON.stringify({ result, banners, fetches: calls.fetch.length, panel: panel.innerHTML }));
""")
    assert out["result"] == "form" and out["fetches"] == 0
    assert 'value="Farida Kaka"' in out["panel"]
    assert out["banners"] == ["That contact has no phone number. Please type it in."]


def test_a_cancelled_picker_changes_nothing():
    out = _run("""
picked = "cancel";
const panel = { innerHTML: "", querySelectorAll: () => [] };
const result = await add.chooseFromContacts(panel, { onChosen: () => { throw new Error("chose"); } });
console.log(JSON.stringify({ result, panel: panel.innerHTML, fetches: calls.fetch.length }));
""")
    assert out == {"result": None, "panel": "", "fetches": 0}


def test_without_a_picker_nothing_is_offered():
    out = _run("""
delete window.ContactsManager;
console.log(JSON.stringify({ can: add.canPickContacts(), picked: await add.pickContacts(), calls: calls.select.length }));
""")
    assert out == {"can": False, "picked": [], "calls": 0}


@pytest.mark.parametrize("screen", ["event.js", "machi_event.js"])
def test_the_first_step_of_both_forms_offers_it(screen):
    """The button sits on the first step itself, beside "+ Add a new behdin",
    and only where the phone has a picker."""
    src = (JS / "screens" / screen).read_text(encoding="utf-8")
    assert '${canPickContacts() ? `<button class="secondary small" id="bhContacts">Import from contacts</button>` : ""}' in src
    assert src.index('id="bhNew"') < src.index('id="bhContacts"') < src.index('id="bhNewPanel"')
    assert "chooseFromContacts(panel, {" in src
