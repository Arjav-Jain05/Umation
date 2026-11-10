/**
 * Home page client script (index.html): URL validation, job submission, and jobs list auto-refresh.
 */

import { getJSON, postJSON } from "./api.js";

const urlInput = document.getElementById("url-input");
const ackCheckbox = document.getElementById("ack-fair-use");
const startBtn = document.getElementById("start-btn");
const jobsListTable = document.getElementById("jobs-list");
const optionsToggle = document.getElementById("options-toggle");
const optionsPanel = document.getElementById("options-panel");
const sysBanner = document.getElementById("sys-banner");

// Options elements
const optMinTier = document.getElementById("opt-min-tier");
const optMaxClipS = document.getElementById("opt-max-clip-s");
const optLayout = document.getElementById("opt-layout");
const optEffects = document.getElementById("opt-effects");
const optFast = document.getElementById("opt-fast");
const optQuality = document.getElementById("opt-quality");

// Toggle options panel
if (optionsToggle && optionsPanel) {
  optionsToggle.addEventListener("click", () => {
    optionsPanel.style.display = optionsPanel.style.display === "none" ? "block" : "none";
  });
}

/**
 * Validate YouTube single video URL.
 */
function isValidYouTubeUrl(url) {
  const clean = (url || "").trim();
  if (!clean) return false;
  if (clean.includes("/shorts/") || clean.includes("/playlist") || clean.includes("/channel/")) {
    return false;
  }
  const reg = /^(https?:\/\/)?(www\.|m\.)?(youtube\.com\/(watch\?v=|live\/)|youtu\.be\/)[a-zA-Z0-9_-]{11}/;
  return reg.test(clean);
}

function updateStartState() {
  const validUrl = isValidYouTubeUrl(urlInput.value);
  const ackChecked = ackCheckbox.checked;
  startBtn.disabled = !(validUrl && ackChecked);
}

if (urlInput) urlInput.addEventListener("input", updateStartState);
if (ackCheckbox) ackCheckbox.addEventListener("change", updateStartState);

// Handle Job Submit
if (startBtn) {
  startBtn.addEventListener("click", async () => {
    startBtn.disabled = true;
    startBtn.textContent = "Queueing...";

    const opts = {
      min_tier: optMinTier?.value || "C",
      max_clip_s: parseInt(optMaxClipS?.value || "60", 10),
      layout: optLayout?.value || "auto",
      effects: optEffects ? optEffects.checked : true,
      fast_mode: optFast ? optFast.checked : false,
      max_height: optQuality && optQuality.checked ? 1440 : 1080,
    };

    try {
      const res = await postJSON("/api/jobs", {
        url: urlInput.value.trim(),
        ack_fair_use: ackCheckbox.checked,
        options: opts,
      });

      if (res.job_id) {
        window.location.href = `/web/job.html?id=${encodeURIComponent(res.job_id)}`;
      }
    } catch (err) {
      alert(`Could not start job: ${err.message}`);
      startBtn.textContent = "Find viral clips";
      updateStartState();
    }
  });
}

/**
 * Render jobs list table.
 */
function renderJobs(jobs) {
  const tbody = jobsListTable.querySelector("tbody");
  if (!jobs || jobs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="color: var(--muted); text-align: center; padding: 24px;">No jobs yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = jobs
    .map((j) => {
      const title = j.title || j.url;
      const channel = j.channel || "—";
      const badgeClass = `badge badge-${j.status}`;
      const clipsCount = j.clips_total > 0 ? `${j.clips_ok}/${j.clips_total}` : "—";
      const created = j.created_at ? new Date(j.created_at).toLocaleTimeString() : "—";

      return `
      <tr>
        <td style="max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${title}">${title}</td>
        <td>${channel}</td>
        <td><span class="${badgeClass}">${j.status}</span></td>
        <td>${j.stage || "—"}</td>
        <td>${clipsCount}</td>
        <td>${created}</td>
        <td><a href="/web/job.html?id=${encodeURIComponent(j.id)}" class="btn btn-secondary" style="min-height: 28px; padding: 4px 10px; font-size: 13px;">Open</a></td>
      </tr>
    `;
    })
    .join("");
}

/**
 * Fetch and refresh jobs periodically.
 */
let refreshTimer = null;
async function refreshJobs() {
  try {
    const jobs = await getJSON("/api/jobs");
    renderJobs(jobs);

    // Auto-refresh every 5s if any job is queued or running
    const hasActive = jobs.some((j) => j.status === "queued" || j.status === "running");
    if (hasActive && !refreshTimer) {
      refreshTimer = setInterval(refreshJobs, 5000);
    } else if (!hasActive && refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    }
  } catch (err) {
    console.error("Failed to fetch jobs:", err);
  }
}

// Check system check status for top banner
async function checkSystem() {
  try {
    const checks = await getJSON("/api/system/check");
    const fails = checks.filter((c) => c.status === "FAIL");
    const warns = checks.filter((c) => c.status === "WARN");

    if (fails.length > 0) {
      sysBanner.className = "banner bad";
      sysBanner.innerHTML = `<strong>System Configuration Issues:</strong><ul>` +
        fails.map((f) => `<li>${f.check}: ${f.detail} (Fix: ${f.fix})</li>`).join("") + `</ul>`;
    } else if (warns.length > 0) {
      sysBanner.className = "banner warn";
      sysBanner.innerHTML = `<strong>System Warnings:</strong><ul>` +
        warns.map((w) => `<li>${w.check}: ${w.detail}</li>`).join("") + `</ul>`;
    }
  } catch (err) {
    console.error("System check fetch failed:", err);
  }
}

// Initial loads
checkSystem();
refreshJobs();
