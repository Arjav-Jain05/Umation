/**
 * Job progress tracking, SSE updates, clip card review UI, and export actions (08 s3-s5).
 */

import { getJSON, patchJSON, postJSON, openEvents } from "./api.js";
import { openEditor } from "./editor.js";

const params = new URLSearchParams(window.location.search);
const jobId = params.get("id");

if (!jobId) {
  alert("No job ID specified");
  window.location.href = "/web/index.html";
}

const videoTitle = document.getElementById("video-title");
const videoChannel = document.getElementById("video-channel");
const videoLink = document.getElementById("video-link");
const jobStatusBadge = document.getElementById("job-status-badge");
const cancelBtn = document.getElementById("cancel-btn");
const resumeBtn = document.getElementById("resume-btn");
const cleanupBtn = document.getElementById("cleanup-btn");
const progressMsg = document.getElementById("progress-msg");
const overallFill = document.getElementById("overall-fill");
const warningsDiv = document.getElementById("warnings");
const summaryDiv = document.getElementById("summary");
const summaryText = document.getElementById("summary-text");
const summarySignals = document.getElementById("summary-signals");
const controlsBar = document.getElementById("controls-bar");
const clipsGrid = document.getElementById("clips");
const approveABtn = document.getElementById("approve-a-btn");
const openFolderBtn = document.getElementById("open-folder-btn");
const downloadAllZipBtn = document.getElementById("download-all-zip-btn");

// Log result modal elements
const resultModal = document.getElementById("result-modal");
const resultPlatform = document.getElementById("result-platform");
const resultUrl = document.getElementById("result-url");
const resultViews = document.getElementById("result-views");
const resultLikes = document.getElementById("result-likes");
const resultCancelBtn = document.getElementById("result-cancel-btn");
const resultSaveBtn = document.getElementById("result-save-btn");
let activeResultClipId = null;

let allClips = [];
let currentFilter = "all";
let originalVideoId = "";

/**
 * Format seconds into mm:ss.
 */
function fmtTime(s) {
  const sec = Math.max(0, Math.round(s));
  const m = Math.floor(sec / 60);
  const r = sec % 60;
  return `${m}:${r < 10 ? "0" : ""}${r}`;
}

/**
 * Clipboard copy with fallback and 1.5s visual feedback.
 */
async function copyToClipboard(text, btnElement) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    const origText = btnElement.textContent;
    btnElement.textContent = "Copied!";
    btnElement.classList.add("btn-copied");
    setTimeout(() => {
      btnElement.textContent = origText;
      btnElement.classList.remove("btn-copied");
    }, 1500);
  } catch (err) {
    alert("Could not copy to clipboard: " + err);
  }
}

/**
 * Update UI for current job state.
 */
function updateJobHeader(job) {
  videoTitle.textContent = job.title || job.url;
  videoChannel.textContent = job.channel || "YouTube";
  videoLink.href = job.url;
  originalVideoId = job.video_id || "";

  jobStatusBadge.className = `badge badge-${job.status}`;
  jobStatusBadge.textContent = job.status;

  if (job.status === "running" || job.status === "queued") {
    cancelBtn.style.display = "inline-flex";
    resumeBtn.style.display = "none";
    cleanupBtn.style.display = "none";
  } else if (job.status === "review" || job.status === "done") {
    cancelBtn.style.display = "none";
    resumeBtn.style.display = "none";
    cleanupBtn.style.display = "inline-flex";
  } else if (job.status === "failed" || job.status === "canceled") {
    cancelBtn.style.display = "none";
    resumeBtn.style.display = "inline-flex";
    cleanupBtn.style.display = "inline-flex";
  }

  overallFill.style.width = `${job.progress || 0}%`;
  if (job.message) {
    progressMsg.textContent = job.message;
  }
}

/**
 * Update stage progress bar.
 */
function updateStageProgress(stage, pct, done = false) {
  const row = document.querySelector(`.stage-row[data-stage="${stage}"]`);
  if (!row) return;
  const fill = row.querySelector(".progress-bar-fill");
  if (fill) {
    fill.style.width = `${pct}%`;
    if (done) fill.classList.add("done");
  }
}

/**
 * Append warning message.
 */
function addWarning(msg) {
  const p = document.createElement("p");
  p.style.color = "var(--warn)";
  p.style.fontSize = "13px";
  p.style.marginTop = "4px";
  p.textContent = `⚠️ ${msg}`;
  warningsDiv.appendChild(p);
}

/**
 * Render individual clip card (08 s4).
 */
function renderClipCard(c) {
  const card = document.createElement("div");
  card.className = `clip-card ${c.decision}`;
  card.dataset.id = c.id;
  card.dataset.tier = c.tier;

  const youtubeSourceUrl = originalVideoId
    ? `https://youtu.be/${originalVideoId}?t=${Math.floor(c.start)}`
    : "#";

  const isPackaged = c.status === "packaged" && c.folder;
  const videoSrc = isPackaged
    ? `/files/output/${c.folder}/clip.mp4`
    : (c.video_url || "");
  const coverSrc = isPackaged
    ? `/files/output/${c.folder}/cover_9x16.jpg`
    : (c.thumb_url || "");
  const thumb16x9Src = isPackaged
    ? `/files/output/${c.folder}/thumb_16x9.jpg`
    : "";

  const partLabel = (c.part_index && c.part_total && c.part_total > 1)
    ? `<span class="badge" style="background: #262b36;">Part ${c.part_index}/${c.part_total}</span>`
    : "";

  card.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <div style="display: flex; gap: 6px; align-items: center;">
        <span class="badge badge-tier-${c.tier}">Tier ${c.tier}</span>
        ${partLabel}
      </div>
      <span style="font-weight: 700; color: var(--accent); font-size: 14px;">Score: ${Math.round(c.final_score)}</span>
    </div>

    <!-- Video Preview -->
    ${
      videoSrc
        ? `<div style="text-align: center; background: #000; border-radius: 8px; overflow: hidden; margin-top: 6px;">
            <video controls preload="metadata" playsinline poster="${coverSrc}" class="clip-video-player" style="width: 100%; aspect-ratio: 9/16; max-height: 380px;">
              <source src="${videoSrc}" type="video/mp4">
            </video>
          </div>`
        : `<div style="height: 200px; display: flex; align-items: center; justify-content: center; background: #0b0d10; border-radius: 8px; color: var(--muted); font-size: 13px;">
            Rendering in progress (${c.status})...
          </div>`
    }

    <!-- Topic & Timing -->
    <div style="font-weight: 600; font-size: 15px; margin-top: 4px;">${c.hook_text || c.topic || "Clip " + c.id}</div>
    <div style="font-size: 13px; color: var(--muted); display: flex; justify-content: space-between;">
      <span>Source: <a href="${youtubeSourceUrl}" target="_blank" style="color: #5e81ac;">${fmtTime(c.start)} – ${fmtTime(c.end)}</a></span>
      <span>${Math.round(c.duration)}s</span>
    </div>

    <!-- Badges -->
    <div style="display: flex; gap: 6px; align-items: center; font-size: 12px; margin-top: 2px;">
      <span class="badge" style="background: ${c.risk === "high" ? "var(--bad)" : (c.risk === "medium" ? "var(--warn)" : "#2ecc71")}; color: #0f1115;">
        Risk: ${c.risk}
      </span>
      <span style="color: var(--muted); font-size: 12px;">Status: ${c.status}</span>
    </div>

    <!-- Action Buttons Grid -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 8px;">
      <button class="btn btn-secondary edit-clip-btn" style="min-height: 32px; font-size: 12px;">Edit Clip</button>
      <button class="btn btn-secondary rerender-clip-btn" style="min-height: 32px; font-size: 12px;">Re-render</button>
      <button class="btn btn-secondary copy-all-btn" style="min-height: 32px; font-size: 12px;">Copy Meta</button>
      <button class="btn btn-secondary log-result-btn" style="min-height: 32px; font-size: 12px;">Log Result</button>
    </div>

    ${
      isPackaged
        ? `<div style="display: flex; gap: 6px; margin-top: 4px;">
            <a href="/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(c.id)}/zip" download class="btn btn-secondary" style="flex: 1; min-height: 32px; font-size: 12px; text-decoration: none;">Download ZIP</a>
            <a href="${videoSrc}" download class="btn btn-secondary" style="flex: 1; min-height: 32px; font-size: 12px; text-decoration: none;">Download MP4</a>
          </div>`
        : ""
    }

    <!-- Decision buttons -->
    <div style="display: flex; gap: 8px; margin-top: 10px;">
      <button class="btn btn-secondary approve-btn" style="flex: 1; min-height: 34px; font-size: 13px; ${c.decision === "approved" ? "background: var(--ok); color: #000;" : ""}">Approve</button>
      <button class="btn btn-secondary reject-btn" style="flex: 1; min-height: 34px; font-size: 13px; ${c.decision === "rejected" ? "background: var(--bad); color: #fff;" : ""}">Reject</button>
    </div>
  `;

  // Pause other videos when this one plays
  const vid = card.querySelector(".clip-video-player");
  if (vid) {
    vid.addEventListener("play", () => {
      document.querySelectorAll(".clip-video-player").forEach((other) => {
        if (other !== vid && !other.paused) other.pause();
      });
    });
  }

  // Wire buttons
  const approveBtn = card.querySelector(".approve-btn");
  const rejectBtn = card.querySelector(".reject-btn");
  const editBtn = card.querySelector(".edit-clip-btn");
  const rerenderBtn = card.querySelector(".rerender-clip-btn");
  const copyAllBtn = card.querySelector(".copy-all-btn");
  const logResultBtn = card.querySelector(".log-result-btn");

  approveBtn.addEventListener("click", async () => {
    const nextDecision = c.decision === "approved" ? "pending" : "approved";
    c.decision = nextDecision;
    renderClipsGrid();
    await patchJSON(`/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(c.id)}`, { decision: nextDecision });
  });

  rejectBtn.addEventListener("click", async () => {
    const nextDecision = c.decision === "rejected" ? "pending" : "rejected";
    c.decision = nextDecision;
    renderClipsGrid();
    await patchJSON(`/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(c.id)}`, { decision: nextDecision });
  });

  if (editBtn) {
    editBtn.addEventListener("click", () => {
      openEditor(jobId, c.id, loadClips);
    });
  }

  if (rerenderBtn) {
    rerenderBtn.addEventListener("click", async () => {
      try {
        await postJSON(`/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(c.id)}/rerender`);
        alert(`Re-render started for clip ${c.id}`);
      } catch (err) {
        alert(`Re-render failed: ${err.message}`);
      }
    });
  }

  if (copyAllBtn) {
    copyAllBtn.addEventListener("click", async () => {
      if (isPackaged) {
        try {
          const res = await fetch(`/files/output/${c.folder}/metadata.txt`);
          const text = await res.text();
          copyToClipboard(text, copyAllBtn);
        } catch {
          copyToClipboard(`Title: ${c.hook_text}\nURL: ${youtubeSourceUrl}`, copyAllBtn);
        }
      } else {
        copyToClipboard(`Title: ${c.hook_text}\nURL: ${youtubeSourceUrl}`, copyAllBtn);
      }
    });
  }

  if (logResultBtn) {
    logResultBtn.addEventListener("click", () => {
      activeResultClipId = c.id;
      resultViews.value = "";
      resultLikes.value = "";
      resultUrl.value = "";
      resultModal.style.display = "flex";
    });
  }

  return card;
}

/**
 * Filter and render all clips into grid.
 */
function renderClipsGrid() {
  clipsGrid.innerHTML = "";
  let filtered = allClips;

  if (currentFilter === "A" || currentFilter === "B" || currentFilter === "C") {
    filtered = allClips.filter((c) => c.tier === currentFilter);
  } else if (currentFilter === "approved") {
    filtered = allClips.filter((c) => c.decision === "approved");
  } else if (currentFilter === "rejected") {
    filtered = allClips.filter((c) => c.decision === "rejected");
  }

  if (filtered.length === 0) {
    clipsGrid.innerHTML = `<p style="grid-column: 1/-1; color: var(--muted); text-align: center; padding: 20px;">No clips match filter.</p>`;
    return;
  }

  filtered.forEach((c) => {
    clipsGrid.appendChild(renderClipCard(c));
  });
}

/**
 * Load and render planned clips for job.
 */
async function loadClips() {
  try {
    const clips = await getJSON(`/api/jobs/${encodeURIComponent(jobId)}/clips`);
    allClips = clips;

    if (clips.length > 0) {
      summaryDiv.style.display = "block";
      controlsBar.style.display = "block";

      const aCount = clips.filter((c) => c.tier === "A").length;
      const bCount = clips.filter((c) => c.tier === "B").length;
      const cCount = clips.filter((c) => c.tier === "C").length;
      const pkgCount = clips.filter((c) => c.status === "packaged").length;

      summaryText.textContent = `${clips.length} moments planned (${pkgCount} packaged): ${aCount} Tier A, ${bCount} Tier B, ${cCount} Tier C`;
      summarySignals.textContent = `All clips selected above score threshold (min 60).`;
      renderClipsGrid();
      loadCandidatesAndInitSlider();
    }
  } catch (err) {
    console.error("Failed to load clips:", err);
  }
}

// Wire Filter Chips
document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    document.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    currentFilter = chip.dataset.filter;
    renderClipsGrid();
  });
});

// Bulk approve A tier
if (approveABtn) {
  approveABtn.addEventListener("click", () => {
    allClips.forEach(async (c) => {
      if (c.tier === "A") {
        c.decision = "approved";
        await patchJSON(`/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(c.id)}`, { decision: "approved" });
      }
    });
    renderClipsGrid();
  });
}

// Bulk open folder
if (openFolderBtn) {
  openFolderBtn.addEventListener("click", async () => {
    try {
      await postJSON("/api/system/open-folder", { path: "output" });
    } catch (err) {
      alert(`Could not open folder: ${err.message}`);
    }
  });
}

// Bulk download all approved zips
if (downloadAllZipBtn) {
  downloadAllZipBtn.addEventListener("click", () => {
    const approved = allClips.filter((c) => c.decision === "approved" && c.status === "packaged");
    if (approved.length === 0) {
      alert("No approved packaged clips found to download.");
      return;
    }
    approved.forEach((c, idx) => {
      setTimeout(() => {
        const link = document.createElement("a");
        link.href = `/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(c.id)}/zip`;
        link.download = `${c.id}_package.zip`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      }, idx * 600);
    });
  });
}

// Log Result Modal buttons
if (resultCancelBtn) {
  resultCancelBtn.addEventListener("click", () => {
    resultModal.style.display = "none";
    activeResultClipId = null;
  });
}

if (resultSaveBtn) {
  resultSaveBtn.addEventListener("click", async () => {
    if (!activeResultClipId) return;
    try {
      await postJSON(`/api/clips/${encodeURIComponent(jobId)}/${encodeURIComponent(activeResultClipId)}/results`, {
        platform: resultPlatform.value,
        url: resultUrl.value || null,
        views: resultViews.value ? parseInt(resultViews.value, 10) : null,
        likes: resultLikes.value ? parseInt(resultLikes.value, 10) : null,
      });
      alert("Result logged successfully!");
      resultModal.style.display = "none";
      activeResultClipId = null;
    } catch (err) {
      alert(`Failed to log result: ${err.message}`);
    }
  });
}

// Button actions
if (cancelBtn) {
  cancelBtn.addEventListener("click", async () => {
    try {
      await postJSON(`/api/jobs/${encodeURIComponent(jobId)}/cancel`);
      alert("Job cancellation requested.");
    } catch (err) {
      alert(`Could not cancel: ${err.message}`);
    }
  });
}

if (resumeBtn) {
  resumeBtn.addEventListener("click", async () => {
    try {
      await postJSON(`/api/jobs/${encodeURIComponent(jobId)}/resume`);
      window.location.reload();
    } catch (err) {
      alert(`Could not resume: ${err.message}`);
    }
  });
}

if (cleanupBtn) {
  cleanupBtn.addEventListener("click", async () => {
    try {
      await postJSON(`/api/jobs/${encodeURIComponent(jobId)}/cleanup`);
      alert("Cleaned up intermediate audio and segment files.");
    } catch (err) {
      alert(`Cleanup failed: ${err.message}`);
    }
  });
}

// Initialize job data & start SSE listener
async function init() {
  try {
    const job = await getJSON(`/api/jobs/${encodeURIComponent(jobId)}`);
    updateJobHeader(job);

    if (job.status === "review" || job.status === "done") {
      loadClips();
    }
  } catch (err) {
    alert(`Failed to load job: ${err.message}`);
  }

  openEvents(jobId, {
    onProgress: (data) => {
      overallFill.style.width = `${data.progress}%`;
      progressMsg.textContent = data.message;
      updateStageProgress(data.stage, 75);
    },
    onStageDone: (data) => {
      updateStageProgress(data.stage, 100, true);
    },
    onWarning: (msg) => {
      addWarning(msg);
    },
    onError: (data) => {
      progressMsg.style.color = "var(--bad)";
      progressMsg.textContent = `Error: ${data.message}`;
      jobStatusBadge.className = "badge badge-failed";
      jobStatusBadge.textContent = "failed";
    },
    onClipUpdate: (data) => {
      // Live per-clip updates
      loadClips();
    },
    onDone: (data) => {
      progressMsg.textContent = data.message || "Pipeline completed successfully!";
      jobStatusBadge.className = "badge badge-review";
      jobStatusBadge.textContent = "review";
      cancelBtn.style.display = "none";
      cleanupBtn.style.display = "inline-flex";
      loadClips();
    },
  });
}

// --- Quality Threshold Slider Implementation (Phase 2 & Section 6) ---
let allCandidates = [];
let candidateHistogram = [];
let suggestedThreshold = 65;
const pinnedCandidateIds = new Set();
const excludedCandidateIds = new Set();

const sliderPanel = document.getElementById("slider-panel");
const qualitySlider = document.getElementById("quality-slider");
const sliderValDisplay = document.getElementById("slider-val-display");
const sliderSelectedCount = document.getElementById("slider-selected-count");
const sliderDurationDisplay = document.getElementById("slider-duration-display");
const sliderEstTime = document.getElementById("slider-est-time");
const histogramContainer = document.getElementById("histogram-container");
const relativeModeToggle = document.getElementById("relative-mode-toggle");
const renderSelectedBtn = document.getElementById("render-selected-btn");

const presetStrictBtn = document.getElementById("preset-strict-btn");
const presetBalancedBtn = document.getElementById("preset-balanced-btn");
const presetLooseBtn = document.getElementById("preset-loose-btn");
const presetSuggestBtn = document.getElementById("preset-suggest-btn");

function renderHistogram(histogram, currentVal) {
  if (!histogramContainer) return;
  histogramContainer.innerHTML = "";
  const maxCount = Math.max(1, ...histogram.map((b) => b.count));

  histogram.forEach((b) => {
    const bar = document.createElement("div");
    const heightPct = Math.round((b.count / maxCount) * 100);
    bar.style.flex = "1";
    bar.style.height = `${Math.max(6, heightPct)}%`;
    bar.style.borderRadius = "3px 3px 0 0";
    bar.title = `${b.range}: ${b.count} candidate(s) (Tier ${b.tier})`;

    // Color code by tier
    if (b.tier === "S") bar.style.background = "#e5a50a";
    else if (b.tier === "A") bar.style.background = "#2ecc71";
    else if (b.tier === "B") bar.style.background = "#3498db";
    else bar.style.background = "#7f8c8d";

    if (b.high <= currentVal) {
      bar.style.opacity = "0.35";
    } else {
      bar.style.opacity = "1";
    }

    histogramContainer.appendChild(bar);
  });
}

function updateSliderFilter(thresholdVal) {
  if (sliderValDisplay) sliderValDisplay.textContent = thresholdVal;
  const isRelative = relativeModeToggle && relativeModeToggle.checked;

  let selected = [];
  if (isRelative) {
    const sorted = [...allCandidates].sort((a, b) => b.final_score - a.final_score);
    const targetCount = Math.max(1, Math.round(sorted.length * (thresholdVal / 100.0)));
    selected = sorted.filter((c, idx) => {
      if (excludedCandidateIds.has(c.id)) return false;
      return pinnedCandidateIds.has(c.id) || idx < targetCount;
    });
  } else {
    selected = allCandidates.filter((c) => {
      if (excludedCandidateIds.has(c.id)) return false;
      return pinnedCandidateIds.has(c.id) || c.final_score >= thresholdVal;
    });
  }

  if (sliderSelectedCount) sliderSelectedCount.textContent = selected.length;
  const totalSec = selected.reduce((acc, c) => acc + (c.end_s - c.start_s), 0);
  if (sliderDurationDisplay) sliderDurationDisplay.textContent = `(${fmtTime(totalSec)} total)`;
  const estRenderSec = Math.round(selected.length * 15);
  if (sliderEstTime) sliderEstTime.textContent = `Est. render: ~${estRenderSec}s`;

  renderHistogram(candidateHistogram, thresholdVal);

  // Update active preset button highlight
  [presetStrictBtn, presetBalancedBtn, presetLooseBtn].forEach((btn) => {
    if (btn) {
      btn.classList.toggle("active", parseFloat(btn.dataset.val) === thresholdVal);
    }
  });
}

async function loadCandidatesAndInitSlider() {
  try {
    const data = await getJSON(`/api/jobs/${encodeURIComponent(jobId)}/candidates`);
    allCandidates = data.candidates || [];
    candidateHistogram = data.histogram || [];
    suggestedThreshold = data.suggested_threshold || 65;

    if (allCandidates.length > 0 && sliderPanel) {
      sliderPanel.style.display = "block";
      const initialVal = qualitySlider ? parseFloat(qualitySlider.value) : 65;
      renderHistogram(candidateHistogram, initialVal);
      updateSliderFilter(initialVal);
    }
  } catch (err) {
    console.warn("Could not load candidates:", err);
  }
}

// Event Listeners for Slider Controls
if (qualitySlider) {
  qualitySlider.addEventListener("input", (e) => {
    updateSliderFilter(parseFloat(e.target.value));
  });
}

if (relativeModeToggle) {
  relativeModeToggle.addEventListener("change", () => {
    if (qualitySlider) updateSliderFilter(parseFloat(qualitySlider.value));
  });
}

if (presetStrictBtn) {
  presetStrictBtn.addEventListener("click", () => {
    if (qualitySlider) qualitySlider.value = 80;
    updateSliderFilter(80);
  });
}

if (presetBalancedBtn) {
  presetBalancedBtn.addEventListener("click", () => {
    if (qualitySlider) qualitySlider.value = 65;
    updateSliderFilter(65);
  });
}

if (presetLooseBtn) {
  presetLooseBtn.addEventListener("click", () => {
    if (qualitySlider) qualitySlider.value = 50;
    updateSliderFilter(50);
  });
}

if (presetSuggestBtn) {
  presetSuggestBtn.addEventListener("click", () => {
    if (qualitySlider) qualitySlider.value = suggestedThreshold;
    updateSliderFilter(suggestedThreshold);
  });
}

if (renderSelectedBtn) {
  renderSelectedBtn.addEventListener("click", async () => {
    try {
      renderSelectedBtn.disabled = true;
      renderSelectedBtn.textContent = "Submitting render...";
      const isRelative = relativeModeToggle && relativeModeToggle.checked;
      const res = await postJSON(`/api/jobs/${encodeURIComponent(jobId)}/render`, {
        threshold: qualitySlider ? parseFloat(qualitySlider.value) : 65.0,
        mode: isRelative ? "relative" : "absolute",
        pins: Array.from(pinnedCandidateIds),
        excludes: Array.from(excludedCandidateIds),
      });
      alert(`Render triggered for ${res.selected_count} selected clips!`);
      loadClips();
    } catch (err) {
      alert(`Failed to trigger render: ${err.message}`);
    } finally {
      renderSelectedBtn.disabled = false;
      renderSelectedBtn.textContent = "Render Selected";
    }
  });
}

init();
