// Timecourse page. Defines a run (interval + duration + capture settings), then
// watches it: polls the run's progress and its frames while capturing, so they can
// be viewed and downloaded live. Shared helpers (loadControls / collectSettings /
// applySettings / loadPresets) live in controls.js, included before this file.

const POLL_INTERVAL_MS = 3000; // frames arrive at the capture interval (seconds), not sub-second
let pollTimer = null;
let pollInFlight = false;
let currentExpId = null;

const $ = (id) => document.getElementById(id);

function expectedFrames(interval, duration) {
  if (!(interval > 0) || !(duration >= interval)) return null;
  return Math.floor(duration / interval) + 1;
}

function updateEstimate() {
  const interval = Number($("exp-interval").value);
  const duration = Number($("exp-duration").value);
  const n = expectedFrames(interval, duration);
  $("frame-estimate").textContent =
    n == null ? "Enter an interval ≤ duration." : `≈ ${n} frames over this run.`;
}

function fmtDuration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function showRunning() {
  $("setup-panel").hidden = true;
  $("running-panel").hidden = false;
}

function showSetup() {
  $("setup-panel").hidden = false;
  $("running-panel").hidden = true;
}

async function startRun() {
  const status = $("status");
  const name = $("exp-name").value.trim();
  if (!name) {
    status.textContent = "Enter a name for the run.";
    $("exp-name").focus();
    return;
  }
  const btn = $("start-btn");
  btn.disabled = true;
  status.textContent = "Starting run…";
  try {
    const res = await fetch("/api/experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        notes: $("exp-notes").value.trim(),
        interval_seconds: Number($("exp-interval").value),
        duration_seconds: Number($("exp-duration").value),
        settings: collectSettings(),
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    const exp = await res.json();
    status.textContent = "";
    enterRun(exp);
  } catch (err) {
    status.textContent = "Error: " + err.message;
  } finally {
    btn.disabled = false;
  }
}

async function stopRun() {
  if (currentExpId == null) return;
  $("stop-btn").disabled = true;
  try {
    const res = await fetch(`/api/experiments/${currentExpId}/stop`, { method: "POST" });
    if (!res.ok) throw new Error(await res.text());
    await pollOnce(); // reflect the stopped state immediately
  } catch (err) {
    $("status").textContent = "Error stopping run: " + err.message;
  } finally {
    $("stop-btn").disabled = false;
  }
}

function enterRun(exp) {
  currentExpId = exp.id;
  $("run-name").textContent = exp.name;
  $("run-notes").textContent = exp.notes || "";
  $("run-notes").hidden = !exp.notes;
  $("new-btn").hidden = true;
  $("stop-btn").hidden = false;
  $("stop-btn").disabled = false;
  showRunning();
  renderRun(exp);
  startPolling();
}

function newRun() {
  stopPolling();
  currentExpId = null;
  $("gallery").innerHTML = "";
  $("status").textContent = "";
  showSetup();
}

function renderRun(exp) {
  const pct = exp.expected_total
    ? Math.min(100, (exp.frames_captured / exp.expected_total) * 100)
    : 0;
  $("progress-fill").style.width = pct + "%";
  let line = `${exp.frames_captured} / ${exp.expected_total} frames · ${exp.status}`;
  if (exp.status === "running") {
    line += ` · ${fmtDuration(exp.seconds_remaining)} remaining`;
  }
  $("run-progress").textContent = line;

  if (exp.status !== "running") {
    // Run ended (complete or stopped): stop polling, offer a new run.
    stopPolling();
    $("stop-btn").hidden = true;
    $("new-btn").hidden = false;
  }
}

async function renderFrames() {
  if (currentExpId == null) return;
  const res = await fetch(`/api/experiments/${currentExpId}/images?limit=500`);
  if (!res.ok) return;
  const images = await res.json();
  const gallery = $("gallery");
  gallery.innerHTML = "";
  for (const img of images) {
    const card = document.createElement("div");
    card.className = "card";
    // Browsers can't render TIFF in <img>; use the server JPEG thumbnail for those.
    const isTiff = img.image_format === "tiff" || img.image_format === "tif";
    const thumbSrc = isTiff
      ? `/api/images/${img.id}/thumbnail`
      : `/api/images/${img.id}/file`;
    card.innerHTML = `
      <img src="${thumbSrc}" alt="frame ${img.id}" loading="lazy">
      <div class="info">
        #${img.id} · ${img.width}×${img.height} · ${img.image_format}<br>
        <a href="/api/images/${img.id}/file?download=true">Download</a>
      </div>`;
    gallery.appendChild(card);
  }
}

async function pollOnce() {
  if (pollInFlight || currentExpId == null) return;
  pollInFlight = true;
  try {
    const res = await fetch(`/api/experiments/${currentExpId}`);
    if (!res.ok) throw new Error(await res.text());
    renderRun(await res.json());
    await renderFrames();
  } catch (err) {
    $("status").textContent = "Update error: " + err.message;
  } finally {
    pollInFlight = false;
  }
}

function startPolling() {
  if (pollTimer !== null) return;
  pollTimer = setInterval(pollOnce, POLL_INTERVAL_MS);
  pollOnce(); // first update immediately
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

// On load: build the control panel + presets, then resume into an active run if one
// exists (so closing the tab or a service restart lands you back on the run).
async function init() {
  await loadControls();
  await loadPresets();
  updateEstimate();
  $("exp-interval").addEventListener("input", updateEstimate);
  $("exp-duration").addEventListener("input", updateEstimate);
  $("start-btn").addEventListener("click", startRun);
  $("stop-btn").addEventListener("click", stopRun);
  $("new-btn").addEventListener("click", newRun);

  try {
    const res = await fetch("/api/experiments");
    const runs = await res.json();
    const active = runs.find((r) => r.status === "running");
    if (active) enterRun(active);
  } catch {
    /* leave the setup view up */
  }
}

init();
