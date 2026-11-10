/**
 * Modal Clip Editor: Timeline trimming, clickable transcript word emphasis,
 * effect editing, and single-clip re-render (08 s6).
 */

import { getJSON, patchJSON, postJSON } from "./api.js";

let currentJobId = null;
let currentClipId = null;
let currentClipData = null;
let currentWords = [];
let currentEditList = { events: [], caption_emphasis: [] };
let onSaveCallback = null;

const modal = document.getElementById("editor-modal");
const modalVideo = document.getElementById("editor-video");
const modalTitle = document.getElementById("editor-clip-title");
const inputStart = document.getElementById("editor-start-time");
const inputEnd = document.getElementById("editor-end-time");
const transcriptList = document.getElementById("editor-transcript");
const effectsList = document.getElementById("editor-effects-list");
const saveBtn = document.getElementById("editor-save-btn");
const closeBtn = document.getElementById("editor-close-btn");

/**
 * Format float seconds to mm:ss.s
 */
function fmtTime(s) {
  const m = Math.floor(s / 60);
  const sec = (s % 60).toFixed(1);
  return `${m}:${sec < 10 ? "0" : ""}${sec}`;
}

/**
 * Open the modal editor for a specific clip.
 */
export async function openEditor(jobId, clipId, onSave) {
  currentJobId = jobId;
  currentClipId = clipId;
  onSaveCallback = onSave;

  modalTitle.textContent = `Editing Clip: ${clipId}`;
  modal.style.display = "flex";

  try {
    // 1. Fetch clip details
    currentClipData = await getJSON(`/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(clipId)}`);
    inputStart.value = currentClipData.start.toFixed(2);
    inputEnd.value = currentClipData.end.toFixed(2);

    // Set video src
    modalVideo.src = `/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(clipId)}/video`;
    modalVideo.load();

    // 2. Fetch words artifact
    try {
      const wordsArt = await getJSON(`/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(clipId)}/words`);
      currentWords = wordsArt.words || [];
    } catch {
      currentWords = [];
    }

    // 3. Fetch edit list
    try {
      currentEditList = await getJSON(`/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(clipId)}/edit-list`);
      if (!currentEditList.caption_emphasis) currentEditList.caption_emphasis = [];
      if (!currentEditList.events) currentEditList.events = [];
    } catch {
      currentEditList = { events: [], caption_emphasis: [] };
    }

    renderTranscript();
    renderEffects();
  } catch (err) {
    alert(`Failed to load clip details: ${err.message}`);
    closeEditor();
  }
}

/**
 * Close the editor modal.
 */
export function closeEditor() {
  modal.style.display = "none";
  modalVideo.pause();
  modalVideo.src = "";
  currentJobId = null;
  currentClipId = null;
}

/**
 * Render words in transcript list. Clicking word seeks; clicking with Shift or clicking emphasis icon toggles emphasis.
 */
function renderTranscript() {
  transcriptList.innerHTML = "";
  if (currentWords.length === 0) {
    transcriptList.innerHTML = `<p style="color: var(--muted); font-size: 13px;">No word timings available.</p>`;
    return;
  }

  currentWords.forEach((wObj, idx) => {
    const span = document.createElement("span");
    const isEmphasized = currentEditList.caption_emphasis.includes(idx);

    span.className = `editor-word ${isEmphasized ? "emphasized" : ""}`;
    span.textContent = wObj.w + " ";
    span.title = `Time: ${wObj.s_clip.toFixed(2)}s (Click to seek, Double-click to toggle emphasis)`;

    span.addEventListener("click", (e) => {
      if (e.shiftKey) {
        toggleWordEmphasis(idx);
      } else {
        modalVideo.currentTime = Math.max(0, wObj.s_clip);
        modalVideo.play();
      }
    });

    span.addEventListener("dblclick", () => {
      toggleWordEmphasis(idx);
    });

    transcriptList.appendChild(span);
  });
}

function toggleWordEmphasis(idx) {
  const emp = currentEditList.caption_emphasis;
  const pos = emp.indexOf(idx);
  if (pos >= 0) {
    emp.splice(pos, 1);
  } else {
    emp.push(idx);
  }
  renderTranscript();
}

/**
 * Render visual and audio effects list with delete and text edit options.
 */
function renderEffects() {
  effectsList.innerHTML = "";
  if (!currentEditList.events || currentEditList.events.length === 0) {
    effectsList.innerHTML = `<p style="color: var(--muted); font-size: 13px;">No effects planned for this clip.</p>`;
    return;
  }

  currentEditList.events.forEach((ev, idx) => {
    const item = document.createElement("div");
    item.className = "effect-item-row";

    const isTextEffect = ev.type === "hook_card" || ev.type === "recap_line";
    const textVal = ev.params ? (ev.params.text || "") : "";

    item.innerHTML = `
      <div style="flex: 1;">
        <span class="badge" style="background: #262b36; font-size: 11px;">${ev.type}</span>
        <span style="color: var(--muted); font-size: 12px; margin-left: 6px;">t=${ev.t0.toFixed(2)}s – ${ev.t1.toFixed(2)}s</span>
        ${
          isTextEffect
            ? `<input type="text" class="input effect-text-input" value="${textVal}" style="display: block; margin-top: 4px; padding: 4px 8px; font-size: 12px;">`
            : ""
        }
      </div>
      <button class="btn btn-secondary delete-effect-btn" style="min-height: 28px; padding: 2px 8px; font-size: 12px; color: var(--bad);">&times;</button>
    `;

    const delBtn = item.querySelector(".delete-effect-btn");
    delBtn.addEventListener("click", () => {
      currentEditList.events.splice(idx, 1);
      renderEffects();
    });

    if (isTextEffect) {
      const txtInput = item.querySelector(".effect-text-input");
      txtInput.addEventListener("input", (e) => {
        if (!ev.params) ev.params = {};
        ev.params.text = e.target.value;
      });
    }

    effectsList.appendChild(item);
  });
}

// Wire Save & Re-render button
if (saveBtn) {
  saveBtn.addEventListener("click", async () => {
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving & Re-rendering...";

    try {
      const newStart = parseFloat(inputStart.value);
      const newEnd = parseFloat(inputEnd.value);

      // 1. Patch start and end
      await patchJSON(`/api/clips/${encodeURIComponent(currentJobId)}/${encodeURIComponent(currentClipId)}`, {
        start: newStart,
        end: newEnd,
      });

      // 2. Patch edit list
      await patchJSON(`/api/clips/${encodeURIComponent(currentJobId)}/${encodeURIComponent(currentClipId)}/edit-list`, {
        events: currentEditList.events,
        caption_emphasis: currentEditList.caption_emphasis,
      });

      // 3. Trigger re-render
      await postJSON(`/api/clips/${encodeURIComponent(currentJobId)}/${encodeURIComponent(currentClipId)}/rerender`);

      alert("Changes saved! Re-rendering has been initiated in background.");
      if (onSaveCallback) onSaveCallback();
      closeEditor();
    } catch (err) {
      alert(`Save failed: ${err.message}`);
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = "Save & Re-render";
    }
  });
}

if (closeBtn) {
  closeBtn.addEventListener("click", closeEditor);
}
