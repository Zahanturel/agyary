"use strict";

/**
 * "Share with the family" on a memorial: the whole schedule as a PDF and as a
 * message, three ways out -
 *   - download the PDF, to send from any device;
 *   - open WhatsApp on THIS device with the message ready (or copy it);
 *   - send the PDF from the shared Mobed Diary number, for a mobed whose
 *     computer has no WhatsApp. That one is only offered when the server says
 *     it can (it is switched on, the family has agreed, and so on), and says
 *     why when it cannot.
 * A short note typed here goes on the PDF and in the message.
 */

import { memorialShareInfo, memorialSchedulePdf, memorialShareSend } from "./api.js";
import { esc } from "./util.js";
import { showError, showInfo } from "./ui.js";

// Beyond this a wa.me link may be refused by the browser or WhatsApp, so the
// link opens the chat without text and the mobed pastes the copied message.
const MAX_LINK_TEXT = 3500;

export function shareCardHtml() {
  return `
    <div class="card" id="shareCard">
      <h2>Share with the family</h2>
      <p class="meta">All the dates as a PDF and a message. A short note you add here goes on both.</p>
      <label for="shNote">Short note <span class="meta">(optional)</span></label>
      <textarea id="shNote" rows="2" maxlength="300" placeholder="e.g. Please be at the agyari by 7 am"></textarea>
      <div class="row tight" style="margin-top:12px;flex-wrap:wrap">
        <button class="small" id="shPdf" type="button">Download PDF</button>
        <a class="button small secondary" id="shWa" target="_blank" rel="noopener" href="#" aria-disabled="true">Open WhatsApp</a>
        <button class="ghost small" id="shCopy" type="button">Copy message</button>
      </div>
      <p class="meta" id="shWaNote" style="margin:8px 0 0"></p>
      <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border)">
        <button class="small" id="shSend" type="button" disabled>Send from the Mobed Diary number</button>
        <p class="meta" id="shSendNote" style="margin:8px 0 0"></p>
        <div id="shSendConfirm"></div>
      </div>
    </div>`;
}

export function wireShareCard(root, aid, memorial) {
  const $ = (sel) => root.querySelector(sel);
  const noteEl = $("#shNote");
  let info = null, token = 0, timer = null;

  const digits = (phone) => String(phone || "").replace(/\D/g, "");

  const paint = () => {
    if (!info) return;
    const wa = $("#shWa");
    const text = encodeURIComponent(info.text);
    const tooLong = text.length > MAX_LINK_TEXT;
    wa.href = `https://wa.me/${digits(info.phone)}` + (tooLong ? "" : `?text=${text}`);
    wa.removeAttribute("aria-disabled");
    $("#shWaNote").textContent = tooLong
      ? "The message is long, so WhatsApp will open on the chat without it: use Copy message, then paste."
      : `Opens a chat with ${info.behdin_name} on this device.`;
    const send = $("#shSend");
    send.disabled = !info.can_send;
    $("#shSendNote").textContent = info.can_send
      ? `Sends the PDF to ${info.behdin_name} from the shared number. They get the dates in the PDF.`
      : (info.cannot_send_because || "");
  };

  const load = async () => {
    const mine = ++token;
    try {
      const got = await memorialShareInfo(aid, memorial.id, noteEl.value.trim());
      if (mine !== token || !root.isConnected) return;
      info = got;
      paint();
    } catch (e) {
      if (mine === token && root.isConnected) $("#shWaNote").textContent = "Couldn't prepare the message: " + e.message;
    }
  };
  load();
  noteEl.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 400); });

  $("#shWa").addEventListener("click", (e) => { if (!info) e.preventDefault(); });

  $("#shPdf").onclick = async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    try {
      const { blob, filename } = await memorialSchedulePdf(aid, memorial.id, noteEl.value.trim());
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
    } catch (e) {
      showError("Couldn't make the PDF: " + e.message);
    } finally {
      btn.disabled = false;
    }
  };

  $("#shCopy").onclick = async () => {
    if (!info) await load();
    if (!info) return;
    try {
      await navigator.clipboard.writeText(info.text);
      showInfo("Message copied.");
    } catch (e) {
      showError("Couldn't copy - select the message and copy it by hand.");
    }
  };

  $("#shSend").onclick = () => {
    const box = $("#shSendConfirm");
    if (box.firstChild || !info || !info.can_send) return;
    box.innerHTML = `<p class="meta" style="margin:8px 0">Send the PDF to <b>${esc(info.behdin_name)}</b>
      (${esc(info.phone)}) from the Mobed Diary number?</p>
      <div class="row tight"><button class="small" id="shSendYes" type="button">Send</button>
      <button class="ghost small" id="shSendNo" type="button">Cancel</button></div>`;
    $("#shSendNo").onclick = () => { box.innerHTML = ""; };
    $("#shSendYes").onclick = async (ev) => {
      ev.currentTarget.disabled = true;
      try {
        await memorialShareSend(aid, memorial.id, noteEl.value.trim());
        box.innerHTML = "";
        showInfo(`Sent to ${info.behdin_name}.`);
        load();   // the daily limit may now be reached
      } catch (e) {
        box.innerHTML = "";
        showError(e.message);
      }
    };
  };
}
