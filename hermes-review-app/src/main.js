// Hermes Skill Review -- entry point.
//
// Flow: reviewer opens a folder (containing pending/approved/rejected
// subfolders of GEPA proposal JSON files) -> browses the pending queue ->
// reads each proposal's before/after diff and stated learning point ->
// approves or rejects with an optional note. Approve/reject moves the file
// and writes a `.decision.json` audit sidecar (see src-tauri/src/main.rs).
//
// This app intentionally does NOT talk to mps_server or touch any petitioner
// data -- by the time a correction reaches this stage it should already be
// anonymised down to a "learning point" (see the safe/unsafe table in
// nanoclaw-tauri-client/docs/letter-knowledge-base.md). This screen's only
// job is the human-review gate before a correction is allowed to influence
// nanoClaw's prompts.

import "./style.css";
import { open } from "@tauri-apps/plugin-dialog";
import { invoke } from "@tauri-apps/api/core";

const STORE_KEY = "hermes-review.base_dir";

const app = document.getElementById("app");
let baseDir = localStorageGet(STORE_KEY);
let queue = [];
let selected = null;
let reviewerId = "";

function localStorageGet(key) {
  // NOTE: plain in-memory fallback -- browser storage APIs are deliberately
  // avoided per the project's "no localStorage in webview" convention. This
  // app re-prompts for a folder each launch unless Claude Code wires up the
  // Rust store plugin (as nanoclaw-tauri-client does for server config).
  return null;
}

render();

async function render() {
  app.innerHTML = "";
  const shell = document.createElement("div");

  shell.innerHTML = `
    <div class="toolbar">
      <strong>Hermes Skill Review</strong>
      <span class="muted" id="dir-label">${baseDir ? escapeHtml(baseDir) : "No folder selected"}</span>
      <div class="spacer"></div>
      <input id="reviewer-id" aria-label="Reviewer ID" placeholder="Reviewer ID" value="${escapeHtml(reviewerId)}" />
      <button id="pick-dir">Choose proposals folder…</button>
      <button id="refresh" ${baseDir ? "" : "disabled"}>Refresh</button>
    </div>
    <div class="layout">
      <aside class="queue" id="queue"></aside>
      <main class="detail" id="detail"><p class="muted" style="padding:24px">Select a proposal to review.</p></main>
    </div>
  `;
  app.appendChild(shell);

  shell.querySelector("#pick-dir").addEventListener("click", pickDirectory);
  shell.querySelector("#refresh").addEventListener("click", loadQueue);
  shell.querySelector("#reviewer-id").addEventListener("input", (event) => {
    reviewerId = event.target.value;
  });

  if (baseDir) await loadQueue();
}

async function pickDirectory() {
  const dir = await open({ directory: true, multiple: false, title: "Select the GEPA proposals folder" });
  if (!dir) return;
  baseDir = Array.isArray(dir) ? dir[0] : dir;
  selected = null;
  await render();
}

async function loadQueue() {
  const host = document.getElementById("queue");
  host.innerHTML = `<p class="muted" style="padding:16px">Loading…</p>`;
  try {
    queue = await invoke("list_pending", { baseDir });
  } catch (e) {
    host.innerHTML = `<div class="banner error" style="margin:16px">${escapeHtml(String(e))}</div>`;
    return;
  }
  if (!queue.length) {
    host.innerHTML = `<p class="muted" style="padding:16px">Nothing pending review. New GEPA batches land in <code>pending/</code>.</p>`;
    return;
  }
  host.innerHTML = "";
  for (const item of queue) {
    const row = document.createElement("div");
    row.className = "queue-item" + (selected?.file_name === item.file_name ? " selected" : "");
    row.innerHTML = `
      <span class="tag">${escapeHtml(item.agency)}</span>
      <div style="margin-top:6px"><strong>${escapeHtml(item.id)}</strong></div>
      <div class="muted" style="font-size:13px;margin-top:2px">${escapeHtml(item.issue)}</div>
    `;
    row.addEventListener("click", () => openProposal(item));
    host.appendChild(row);
  }
}

async function openProposal(summary) {
  selected = summary;
  await loadQueue(); // re-render queue with new selection highlight
  const host = document.getElementById("detail");
  host.innerHTML = `<p class="muted" style="padding:24px">Loading proposal…</p>`;

  let detail;
  try {
    detail = await invoke("read_proposal", { baseDir, fileName: summary.file_name });
  } catch (e) {
    host.innerHTML = `<div class="banner error" style="margin:24px">${escapeHtml(String(e))}</div>`;
    return;
  }

  const p = detail.raw ?? {};
  host.innerHTML = `
    <h2 style="margin:0 0 4px">${escapeHtml(p.id ?? summary.file_name)}</h2>
    <p class="muted" style="margin:0">
      <span class="tag">${escapeHtml(p.agency ?? "?")}</span>
      &nbsp; ${escapeHtml(p.issue ?? "")}
    </p>

    <div class="banner info">
      <strong>Learning point:</strong> ${escapeHtml(p.correction ?? "(none provided)")}
    </div>
    <p class="muted" style="font-size:12px">Proposal SHA-256: <code>${escapeHtml(detail.sha256)}</code></p>

    <div class="diff-grid">
      <div>
        <label class="muted" style="font-size:13px">Before (AI draft excerpt)</label>
        <div class="diff-pane before">${escapeHtml(p.before ?? "(no excerpt provided)")}</div>
      </div>
      <div>
        <label class="muted" style="font-size:13px">After (vetter-corrected excerpt)</label>
        <div class="diff-pane after">${escapeHtml(p.after ?? "(no excerpt provided)")}</div>
      </div>
    </div>

    <div class="field">
      <label>Reviewer note (optional, saved to the audit sidecar)</label>
      <textarea id="note" rows="2" placeholder="e.g. confirmed pattern recurs across HDB cases this month"></textarea>
    </div>

    <div id="decision-error"></div>

    <div style="display:flex;gap:8px;margin-top:8px">
      <button class="danger" id="reject-btn">Reject</button>
      <div class="spacer"></div>
      <button class="primary" id="approve-btn">Approve &amp; queue for nanoClaw prompt update</button>
    </div>
  `;

  host.querySelector("#approve-btn").addEventListener("click", () => decide("approve"));
  host.querySelector("#reject-btn").addEventListener("click", () => decide("reject"));
}

async function decide(decision) {
  if (!selected) return;
  if (reviewerId.trim().length < 3) {
    document.getElementById("decision-error").textContent = "Enter your reviewer ID before making a decision.";
    return;
  }
  const note = document.getElementById("note")?.value?.trim() || null;
  const errHost = document.getElementById("decision-error");
  const verb = decision === "approve" ? "approve" : "reject";

  if (!confirm(`${verb === "approve" ? "Approve" : "Reject"} this correction? It will be moved out of the pending queue.`)) return;

  try {
    await invoke("decide_proposal", {
      baseDir,
      fileName: selected.file_name,
      decision,
      reviewerId: reviewerId.trim(),
      reviewerNote: note,
    });
    selected = null;
    document.getElementById("detail").innerHTML = `<p class="muted" style="padding:24px">Select a proposal to review.</p>`;
    await loadQueue();
  } catch (e) {
    errHost.innerHTML = `<div class="banner error">${escapeHtml(String(e))}</div>`;
  }
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
