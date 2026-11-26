"use strict";

/** Fire temple: the one the person has chosen, and "Change" to choose another from the listed ones, by town. */

import { getMyAgyari, chooseAgyari } from "../api.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml, showError, showInfo } from "/mobed-app/js/ui.js";
import { navGuard } from "/mobed-app/js/router.js";
import { esc, KIND_LABELS } from "../util.js";
import { mountPicker } from "./picker.js";

export function kindLabel(kind) { return KIND_LABELS[kind] || ""; }

export async function renderAgyari() {
  chrome(true);
  setHeader("Fire temple");
  loading();
  const alive = navGuard();

  let mine = null;
  try {
    mine = (await getMyAgyari()).agyari;
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = loadFailedHtml("your fire temple");
    wireRetry(mainEl, () => renderAgyari());
    return;
  }
  if (!alive()) return;

  const draw = (changing) => {
    mainEl.innerHTML = `${mine ? `<div class="card">
        <h2>${esc(mine.name)}</h2>
        <p class="meta" style="margin:0">${esc([mine.city, kindLabel(mine.kind)].filter(Boolean).join(" · "))}</p>
        ${changing ? "" : `<div style="margin-top:var(--space-3)"><button type="button" class="small secondary" id="ftChange">Change</button></div>`}
      </div>` : ""}<div id="ftPick"></div>`;
    const change = document.getElementById("ftChange");
    if (change) change.onclick = () => draw(true);
    if (changing || !mine) {
      mountPicker(document.getElementById("ftPick"), {
        alive, currentId: mine && mine.id, town: mine ? mine.city : "",
        onPick: async (a) => {
          try {
            mine = (await chooseAgyari(a.id)).agyari;
          } catch (err) {
            return showError(err.message);
          }
          showInfo(`${mine.name} selected.`);
          draw(false);
        },
      });
    }
  };
  draw(false);
}
