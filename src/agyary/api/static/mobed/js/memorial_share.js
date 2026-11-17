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
 * A short note typed here goes on the PDF and in the message the mobed sends
 * themselves. What goes from the shared number never carries it: that route is
 * our words only (D1).
 */

import { memorialShareInfo, memorialSchedulePdf, memorialShareSend } from "./api.js";
import { showError, showInfo } from "./ui.js";

// Beyond this a wa.me link may be refused by the browser or WhatsApp, so the link
// then opens the chat without text. The short message never gets near it.
const MAX_LINK_TEXT = 3500;

export function shareCardHtml() {
  return `
    <div class="card" id="shareCard">
      <h2>Share with the family</h2>
      <p class="meta">All the dates as a PDF and a message. A short note you add here goes on both.</p>
      <label for="shNote">Short note <span class="meta">(optional)</span></label>
      <textarea id="shNote" rows="2" maxlength="300" placeholder="e.g. Please be at the agyari by 7 am"></textarea>
      <div style="margin-top:12px">
        <button class="small" id="shShare" type="button" disabled>Share PDF and note on WhatsApp</button>
        <p class="meta" id="shShareNote" style="margin:6px 0 0">Preparing the PDF...</p>
      </div>
      <div class="row tight" style="margin-top:12px;flex-wrap:wrap">
        <a class="button small secondary" id="shWa" target="_blank" rel="noopener" href="#" aria-disabled="true">Open chat</a>
        <button class="ghost small" id="shPdf" type="button">Download PDF</button>
        <button class="ghost small" id="shCopy" type="button">Copy all dates</button>
      </div>
      <p class="meta" id="shWaNote" style="margin:8px 0 0"></p>
      <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border)">
        <button class="small" id="shSend" type="button" disabled>Send from the Mobed Diary number</button>
        <p class="meta" id="shSendNote" style="margin:8px 0 0"></p>
      </div>
    </div>`;
}

/** Wires the card and returns a handle on the same share, so the question asked
 *  the moment a memorial is made (memorial.js) sends exactly what the card
 *  would, from the PDF the card has already prepared:
 *    info       what the server said about sharing, once it has (else null)
 *    pdfState   "preparing" | "ready" | "unavailable" (this device cannot hand
 *               a PDF to another app) | "failed"
 *    onChange   call back whenever either of those changes
 *    share()    open the phone's share sheet; true when it was shared
 *    send()     send from the shared number; true when it went */
export function wireShareCard(root, aid, memorial) {
  const $ = (sel) => root.querySelector(sel);
  const noteEl = $("#shNote");
  let info = null, token = 0, timer = null;
  let pdfState = "preparing";
  const watchers = [];
  const setPdfState = (to) => { pdfState = to; watchers.forEach(fn => fn()); };

  const digits = (phone) => String(phone || "").replace(/\D/g, "");

  const paint = () => {
    if (!info) return;
    const wa = $("#shWa");
    // The short message always fits in a link (the dates are in the PDF). A link
    // cannot carry a file, so the PDF is added by hand in this route.
    const text = encodeURIComponent(info.short_text);
    wa.href = `https://wa.me/${digits(info.phone)}` + (text.length > MAX_LINK_TEXT ? "" : `?text=${text}`);
    wa.removeAttribute("aria-disabled");
    $("#shWaNote").textContent =
      `Open chat: ${info.behdin_name}'s chat with the short message typed. WhatsApp links cannot attach a file, ` +
      "so add the PDF with the paperclip (Download PDF first).";
    const send = $("#shSend");
    send.disabled = !info.can_send;
    $("#shSendNote").textContent = info.can_send
      ? `Sends the PDF to ${info.behdin_name} from the shared number, without your note. They get the dates in the PDF.`
      : (info.cannot_send_because || "");
    watchers.forEach(fn => fn());
  };

  // The PDF is made ahead of the tap: the share sheet must open straight from the
  // tap, and a download in between can make the browser refuse it.
  let pdfFile = null;
  const canShareFiles = () => typeof navigator.canShare === "function" && typeof navigator.share === "function";
  const prepareFile = async (mine) => {
    const btn = $("#shShare"), note = $("#shShareNote");
    pdfFile = null;
    btn.disabled = true;
    if (!canShareFiles()) {
      note.textContent = "This browser cannot attach the PDF to WhatsApp by itself. Use Open chat, "
        + "then add the PDF with the paperclip (Download PDF first).";
      return setPdfState("unavailable");
    }
    note.textContent = "Preparing the PDF...";
    setPdfState("preparing");
    try {
      const { blob, filename } = await memorialSchedulePdf(aid, memorial.id, noteEl.value.trim());
      if (mine !== token || !root.isConnected) return;
      const file = new File([blob], filename, { type: "application/pdf" });
      if (!navigator.canShare({ files: [file] })) {
        note.textContent = "This device cannot share a PDF from here. Use Open chat and add the PDF with the paperclip.";
        return setPdfState("unavailable");
      }
      pdfFile = file;
      btn.disabled = false;
      note.textContent = "Opens your phone's share sheet with the PDF attached and the note typed: choose WhatsApp, then "
        + `${info ? info.behdin_name : "the family"}'s chat.`;
      setPdfState("ready");
    } catch (e) {
      if (mine !== token || !root.isConnected) return;
      note.textContent = "Couldn't prepare the PDF: " + e.message;
      setPdfState("failed");
    }
  };

  const load = async () => {
    const mine = ++token;
    try {
      const got = await memorialShareInfo(aid, memorial.id, noteEl.value.trim());
      if (mine !== token || !root.isConnected) return;
      info = got;
      paint();
      prepareFile(mine);
    } catch (e) {
      if (mine !== token || !root.isConnected) return;
      $("#shWaNote").textContent = "Couldn't prepare the message: " + e.message;
      $("#shShareNote").textContent = "";
      setPdfState("failed");
    }
  };
  load();
  noteEl.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 1200); });

  $("#shWa").addEventListener("click", (e) => { if (!info) e.preventDefault(); });

  // True once the share sheet has handed the PDF on. Backing out of the sheet is
  // not an error and says nothing.
  const share = async () => {
    if (!pdfFile || !info) return false;
    try {
      // The text rides along as the caption; some apps ignore it, which is why
      // the note is also on the PDF itself.
      await navigator.share({ files: [pdfFile], text: info.short_text, title: pdfFile.name });
      return true;
    } catch (e) {
      if (e && e.name !== "AbortError") showError("Couldn't open the share sheet: " + e.message);
      return false;
    }
  };
  $("#shShare").onclick = share;

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

  // One tap sends: no second "are you sure". The button is disabled while it goes,
  // so a double tap cannot send twice.
  const send = async () => {
    const btn = $("#shSend");
    if (!info || !info.can_send || btn.disabled) return false;
    btn.disabled = true;
    const label = btn.textContent;
    btn.textContent = "Sending...";
    try {
      await memorialShareSend(aid, memorial.id);
      return true;
    } catch (e) {
      showError(e.message);
      return false;
    } finally {
      btn.textContent = label;
      load();   // re-reads whether it can still send (the daily limit may now be reached)
    }
  };
  $("#shSend").onclick = async () => {
    const to = info && info.behdin_name;
    if (await send()) showInfo(`Sent to ${to}.`);
  };

  return {
    get info() { return info; },
    get pdfState() { return pdfState; },
    onChange(fn) { watchers.push(fn); },
    share,
    send,
  };
}
