/**
 * Job progress tracking, SSE updates, and clip card review UI.
 */

import { getJSON, postJSON, openEvents } from "./api.js";

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
  } else if (job.status === "review") {
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
 * Render individual clip card.
 */
function renderClipCard(c) {
  const card = document.createElement("div");
  card.className = `clip-card ${c.decision}`;
  card.dataset.id = c.id;
  card.dataset.tier = c.tier;

  const youtubeSourceUrl = originalVideoId
    ? `https://youtu.be/${originalVideoId}?t=${Math.floor(c.start)}`
    : "#";

  card.innerHTML = `
    <div style="display: flex; justify-content: space-between; align-items: center;">
      <span class="badge badge-tier-${c.tier}">Tier ${c.tier}</span>
      <span style="font-weight: 700; color: var(--accent); font-size: 14px;">Score: ${Math.round(c.final_score)}</span>
    </div>

    <div style="font-weight: 600; font-size: 15px; margin-top: 4px;">${c.hook_text || c.topic || "Clip " + c.id}</div>

    <div style="font-size: 13px; color: var(--muted); display: flex; justify-content: space-between;">
      <span>Time: <a href="${youtubeSourceUrl}" target="_blank" style="color: #5e81ac;">${fmtTime(c.start)} – ${fmtTime(c.end)}</a></span>
      <span>${Math.round(c.duration)}s</span>
    </div>

    <div style="display: flex; gap: 6px; align-items: center; font-size: 12px; margin-top: 2px;">
      <span class="badge" style="background: ${c.risk === "high" ? "var(--bad)" : (c.risk === "medium" ? "var(--warn)" : "#2ecc71")}; color: #0f1115;">
        Risk: ${c.risk}
      </span>
      <span style="color: var(--muted);">Status: ${c.status}</span>
    </div>

    <div style="display: flex; gap: 8px; margin-top: 10px;">
      <button class="btn btn-secondary approve-btn" style="flex: 1; min-height: 32px; font-size: 13px; ${c.decision === "approved" ? "background: var(--ok); color: #000;" : ""}">Approve</button>
      <button class="btn btn-secondary reject-btn" style="flex: 1; min-height: 32px; font-size: 13px; ${c.decision === "rejected" ? "background: var(--bad); color: #fff;" : ""}">Reject</button>
    </div>
  `;

  const approveBtn = card.querySelector(".approve-btn");
  const rejectBtn = card.querySelector(".reject-btn");

  approveBtn.addEventListener("click", () => {
    c.decision = c.decision === "approved" ? "pending" : "approved";
    renderClipsGrid();
  });

  rejectBtn.addEventListener("click", () => {
    c.decision = c.decision === "rejected" ? "pending" : "rejected";
    renderClipsGrid();
  });

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

      summaryText.textContent = `${clips.length} moments selected: ${aCount} Tier A, ${bCount} Tier B, ${cCount} Tier C`;
      summarySignals.textContent = `All clips selected above score threshold (min 60).`;
      renderClipsGrid();
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
    allClips.forEach((c) => {
      if (c.tier === "A") c.decision = "approved";
    });
    renderClipsGrid();
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

init();
