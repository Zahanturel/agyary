"use strict";

/**
 * The menu, behind the header icon: who you are, the text size, installing, signing
 * out, deleting the account, and which version of the app this phone runs.
 */

import { updateMyName, deleteMyAccount } from "../api.js";
import { state, saveSession } from "../state.js";
import { chrome, mainEl, setHeader, showError, showInfo, getTextSize, setTextSize } from "/mobed-app/js/ui.js";
import { navigate } from "/mobed-app/js/router.js";
import { flagProblems } from "/mobed-app/js/fielderrors.js";
import { APP_NAME } from "../brand.js";
import { esc } from "../util.js";
import { signOut, forgetEverything } from "../session.js";
import { paintInstall, shellVersion } from "../install.js";

export function renderMenu() {
  chrome(true);
  setHeader(APP_NAME);

  mainEl.innerHTML = `
    <div class="card">
      <h2>You</h2>
      <label for="mName">Name</label>
      <input type="text" id="mName" value="${esc(state.user.name)}" autocomplete="name">
      <div style="margin-top:10px"><button class="small" id="mSaveName">Save name</button></div>
    </div>

    <div class="card">
      <h2>My agyari</h2>
      <p class="meta">The agyari you have chosen, or choose one now.</p>
      <button type="button" class="secondary" id="mAgyari" style="width:100%">My agyari</button>
    </div>

    <div class="card">
      <h2>Text size</h2>
      <p class="meta">Makes the words in the app bigger on this phone.</p>
      <div id="mTextSize">
        <label class="choice"><input type="radio" name="mText" value="regular" ${getTextSize() === "regular" ? "checked" : ""}><span>Regular</span></label>
        <label class="choice"><input type="radio" name="mText" value="large" ${getTextSize() === "large" ? "checked" : ""}><span>Large</span></label>
        <label class="choice"><input type="radio" name="mText" value="xl" ${getTextSize() === "xl" ? "checked" : ""}><span>Extra large</span></label>
      </div>
    </div>

    <div class="card" id="mInstall"></div>

    <div class="card">
      <button class="ghost" id="mSignOut">Sign out</button>
      <p class="meta" style="margin:10px 0 0" id="mVersion"></p>
    </div>

    <div class="card">
      <button class="ghost small" id="mDelete">Delete my account</button>
      <div id="mDeleteConfirm"></div>
    </div>`;

  document.getElementById("mAgyari").onclick = () => navigate("#/agyari");
  paintInstall(document.getElementById("mInstall"));
  shellVersion().then((v) => {
    const el = document.getElementById("mVersion");
    if (el && v) el.textContent = "App version " + v;
  });

  mainEl.querySelectorAll('input[name="mText"]').forEach((r) => { r.onchange = () => setTextSize(r.value); });

  document.getElementById("mSaveName").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const nameEl = document.getElementById("mName");
    const name = nameEl.value.trim();
    if (!name) return flagProblems(nameEl.closest(".card"), [{ target: "#mName", message: "Please enter your name." }]);
    btn.disabled = true;   // one save per tap
    try {
      state.user = await updateMyName(name);
      saveSession();
      showInfo("Saved.");
    } catch (e) {
      showError(e.message);
    } finally {
      btn.disabled = false;
    }
  };

  document.getElementById("mSignOut").onclick = (ev) => signOut(ev.currentTarget);

  // Two steps, in plain words: what goes, and that it cannot be undone.
  document.getElementById("mDelete").onclick = () => {
    const box = document.getElementById("mDeleteConfirm");
    box.innerHTML = `
      <p style="margin:12px 0 8px"><b>Delete your account?</b></p>
      <p class="meta" style="margin:0 0 12px">This removes your account and everything in it. It cannot be
        undone. You can always sign up again later.</p>
      <div class="row tight">
        <button class="danger small" id="mDeleteYes">Delete everything</button>
        <button class="ghost small" id="mDeleteNo">Keep my account</button>
      </div>`;
    document.getElementById("mDeleteNo").onclick = () => { box.innerHTML = ""; };
    document.getElementById("mDeleteYes").onclick = async (e) => {
      e.target.disabled = true;
      try {
        await deleteMyAccount();
      } catch (err) {
        e.target.disabled = false;
        return showError(err.message);
      }
      forgetEverything();
    };
  };
}
