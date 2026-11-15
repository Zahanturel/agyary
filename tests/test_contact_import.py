"""Import from contacts: the behdin's name and number read from the phone.

behdin_add.js is run for real under Node with the Contact Picker, the server
and as much of a page as it touches stubbed. What matters:
  - the button is only where a name and number are asked for (the compact
    add form and the Add behdin page), never beside "+ Add a new behdin";
  - the phone refusing to open its contacts is said on screen, with the
    browser's own reason - for months a refusal was taken for a cancel and
    the button "did nothing";
  - an answer that comes back at once (the list never opened: Chrome is not
    allowed to read contacts) says where to allow it, and a real back-out
    says nothing;
  - an address book's numbers come out as the one shape the server stores,
    and the mobile is taken over a landline.
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

# Just enough page for ui.js to load, and for the add form to draw into.
# `picker` decides what navigator.contacts.select does.
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
  prepend(el) { banners.push([el.className, el.textContent]); },
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
const calls = { select: [], fetch: [] };
let picker = async () => [];
Object.defineProperty(navigator, "contacts", {
  configurable: true,
  value: { select: (props, opts) => { calls.select.push({ props, opts }); return picker(); } },
});
const later = (ms, value) => new Promise(r => setTimeout(() => r(value), ms));
globalThis.fetch = async (url, opts) => {
  calls.fetch.push({ url, method: (opts && opts.method) || "GET" });
  return new Response(JSON.stringify({}), { status: 200 });
};
console.error = () => {};
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
picker = async () => later(1200, [
  { name: ["Zubin Mistry"], tel: ["022 2345 6789", "98200 12345"] },
  { name: ["Farida Kaka"], tel: ["+44 20 7946 0958"] },
  { name: ["Only A Name"], tel: [] },
  { name: [], tel: ["99300 11223"] },
  { name: [], tel: ["12"] },
]);
console.log(JSON.stringify({ picked: await add.pickContacts(), calls: calls.select, banners }));
""")
    assert out["picked"] == [
        {"name": "Zubin Mistry", "phone": "+919820012345"},
        {"name": "Farida Kaka", "phone": "+442079460958"},
        {"name": "Only A Name", "phone": ""},
        {"name": "", "phone": "+919930011223"},
    ]
    assert out["calls"] == [{"props": ["name", "tel"], "opts": {"multiple": True}}]
    assert out["banners"] == []


def test_the_phone_refusing_to_open_its_contacts_is_said_on_screen():
    """MDN: select() rejects with InvalidStateError 'if launching a contact
    picker failed'. That is the case the old code took for a cancel."""
    out = _run("""
picker = async () => { const e = new Error("Unable to open a contacts selector"); e.name = "InvalidStateError"; throw e; };
console.log(JSON.stringify({ picked: await add.pickContacts({ multiple: false }), banners }));
""")
    assert out["picked"] == []
    assert out["banners"] == [[
        "error-banner",
        "Your contacts could not be opened (InvalidStateError: Unable to open a contacts selector). "
        "Please type the name and number instead.",
    ]]


def test_nothing_back_at_once_says_where_to_allow_contacts():
    out = _run("""
picker = async () => [];
console.log(JSON.stringify({ picked: await add.pickContacts(), banners, hint: add.CONTACTS_DID_NOT_OPEN }));
""")
    assert out["picked"] == []
    assert out["banners"] == [["info-banner", out["hint"]]]
    assert "Settings, then Apps, Chrome, Permissions, Contacts" in out["hint"]


def test_backing_out_of_the_list_says_nothing():
    out = _run("""
picker = async () => later(add.TOO_QUICK_MS + 200, []);
console.log(JSON.stringify({ picked: await add.pickContacts(), banners }));
""")
    assert out == {"picked": [], "banners": []}


def test_without_a_picker_nothing_is_offered():
    out = _run("""
delete window.ContactsManager;
const panel = { innerHTML: "", querySelectorAll: () => [] };
add.renderAddBehdin(panel, {});
console.log(JSON.stringify({ can: add.canPickContacts(), picked: await add.pickContacts(), calls: calls.select.length, form: panel.innerHTML }));
""")
    assert out["can"] is False and out["picked"] == [] and out["calls"] == 0
    assert "Import from contacts" not in out["form"] and 'id="abName"' in out["form"]


def test_the_add_form_imports_one_contact_and_shows_its_name():
    """The event and machi search hide this form's name row (the search box
    stands in for it); an imported name is shown, to be checked."""
    out = _run("""
const panel = { innerHTML: "", querySelectorAll: () => [] };
add.renderAddBehdin(panel, { prefill: { name: "Zub" } });
const button = panel.innerHTML.includes('id="abImport"');
document.getElementById("abNameRow").style.display = "none";
picker = async () => later(1200, [{ name: ["Zubin <Plumber>"], tel: ["098200-12345"] }]);
await document.getElementById("abImport").onclick();
const v = id => document.getElementById(id).value;
console.log(JSON.stringify({
  button, opts: calls.select.map(c => c.opts), row: document.getElementById("abNameRow").style.display,
  name: v("abName"), cc: v("abPhone_cc"), phone: v("abPhone"), banners,
  saved: calls.fetch.filter(f => f.method !== "GET").length,
}));
""")
    assert out["button"] is True
    assert out["opts"] == [{"multiple": False}]
    assert out["row"] == ""
    assert (out["name"], out["cc"], out["phone"]) == ("Zubin <Plumber>", "91", "9820012345")
    assert out["banners"] == [] and out["saved"] == 0   # filled for checking, never saved by the pick


def test_a_contact_without_a_number_says_so_and_keeps_what_was_typed():
    out = _run("""
const panel = { innerHTML: "", querySelectorAll: () => [] };
add.renderAddBehdin(panel, {});
document.getElementById("abPhone").value = "98765";
picker = async () => later(1200, [{ name: ["Farida Kaka"], tel: [] }]);
await document.getElementById("abImport").onclick();
console.log(JSON.stringify({ name: document.getElementById("abName").value, phone: document.getElementById("abPhone").value, banners }));
""")
    assert out["name"] == "Farida Kaka" and out["phone"] == "98765"
    assert out["banners"] == [["info-banner", "That contact has no phone number. Please type it in."]]


@pytest.mark.parametrize("screen", ["event.js", "machi_event.js"])
def test_the_first_step_of_both_forms_has_only_add_a_new_behdin(screen):
    """Import from contacts is not beside "+ Add a new behdin": it is inside
    what that button (or a search that finds nobody) leads to."""
    src = (JS / "screens" / screen).read_text(encoding="utf-8")
    assert 'id="bhNew">+ Add a new behdin</button>' in src
    assert "Import from contacts" not in src and "canPickContacts" not in src and "pickContacts" not in src
    assert 'navigate("#/behdins/new")' in src and "renderAddBehdin(panel, {" in src


def test_the_add_behdin_page_offers_it_one_at_a_time_when_booking():
    src = (JS / "screens" / "behdins.js").read_text(encoding="utf-8")
    page = src[src.index("function buildBehdinNew"):src.index("export async function renderBehdinDetail")]
    assert "${canPickContacts() ? `" in page and 'id="bnImport"' in page
    assert page.index('id="bnImport"') < page.index('id="bnName"')
    assert "pickContacts({ multiple: !returnTo })" in page
    assert 'fillFromContact(picked[0], { nameId: "bnName", phoneId: "bnPhone" })' in page
