// Capture page. Single manual capture, plus an optional timecourse run (interval +
// duration) driven by the same control form and toggled on with the "Timecourse run"
// checkbox. Shared helpers (loadControls / collectSettings / applySettings /
// loadPresets / deletePreset) live in controls.js, included before this file.

const $ = (id) => document.getElementById(id);

// --- Live view: poll /api/preview ~2×/sec with the current control values, so
// tweaking a control updates the image without a full capture. Auto-starts on load. ---
const PREVIEW_INTERVAL_MS = 500;
let previewTimer = null;
let previewInFlight = false;
let previewUrl = null;

function isPreviewing() {
  return previewTimer !== null;
}

async function tickPreview() {
  if (previewInFlight) return; // skip if the last poll hasn't returned
  previewInFlight = true;
  try {
    const res = await fetch("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectSettings()),
    });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const img = $("preview");
    img.src = url;
    img.hidden = false;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = url;
  } catch (err) {
    $("status").textContent = "Live view error: " + err.message;
    stopPreview();
  } finally {
    previewInFlight = false;
  }
}

function startPreview() {
  if (isPreviewing()) return;
  $("preview-btn").textContent = "Stop live view";
  previewTimer = setInterval(tickPreview, PREVIEW_INTERVAL_MS);
  tickPreview(); // show a first frame immediately
}

function stopPreview() {
  if (previewTimer !== null) {
    clearInterval(previewTimer);
    previewTimer = null;
  }
  $("preview-btn").textContent = "Start live view";
}

function togglePreview() {
  if (isPreviewing()) stopPreview();
  else startPreview();
}

// --- Single manual capture ---
async function capture() {
  const btn = $("capture-btn");
  const status = $("status");
  const wasPreviewing = isPreviewing();
  // Pause the live view during a capture so the two don't fight over the
  // camera's resolution reconfigure.
  if (wasPreviewing) stopPreview();
  btn.disabled = true;
  status.textContent = "Capturing…";
  try {
    const res = await fetch("/api/capture", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectSettings()),
    });
    if (!res.ok) throw new Error(await res.text());
    const img = await res.json();
    status.textContent = `Captured #${img.id} (${img.width}×${img.height})`;
    await loadGallery();
  } catch (err) {
    status.textContent = "Error: " + err.message;
  } finally {
    btn.disabled = false;
    if (wasPreviewing) startPreview();
  }
}

// --- Recent captures: the 3 newest images (ad-hoc captures or timecourse frames). ---
async function loadGallery() {
  const res = await fetch("/api/images?limit=3");
  const images = await res.json();
  const gallery = $("gallery");
  gallery.innerHTML = "";
  for (const img of images) {
    const card = document.createElement("div");
    card.className = "card";
    // Browsers can't render TIFF in <img>, so preview it via the server-generated
    // JPEG thumbnail (same captured pixels, downscaled). JPEG/PNG show the file directly.
    const isTiff = img.image_format === "tiff" || img.image_format === "tif";
    const thumbSrc = isTiff
      ? `/api/images/${img.id}/thumbnail`
      : `/api/images/${img.id}/file`;
    card.innerHTML = `
      <img src="${thumbSrc}" alt="capture ${img.id}" loading="lazy">
      <div class="info">
        #${img.id} · ${img.width}×${img.height} · ${img.image_format}<br>
        <a href="/api/images/${img.id}/file?download=true">Download</a>
        <button type="button" class="use-settings-btn">Use settings</button>
      </div>`;
    // Recall this capture's stored settings into the control panel. Bind the settings
    // object here rather than embedding JSON in the template string.
    card.querySelector(".use-settings-btn").addEventListener("click", () => {
      applySettings(img.settings);
      $("status").textContent = `Loaded settings from #${img.id}`;
    });
    gallery.appendChild(card);
  }
}

async function savePreset() {
  const input = $("preset-name");
  const status = $("status");
  const name = input.value.trim();
  if (!name) {
    status.textContent = "Enter a name to save a preset.";
    input.focus();
    return;
  }
  try {
    const res = await fetch("/api/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, settings: collectSettings() }),
    });
    if (!res.ok) throw new Error(await res.text());
    input.value = "";
    status.textContent = `Saved preset “${name}”`;
    await loadPresets();
  } catch (err) {
    status.textContent = "Error saving preset: " + err.message;
  }
}

// --- Timecourse toggle: reveal the scheduling fields and turn the primary button
// into "Start run". ---
function isTimecourse() {
  return $("timecourse-toggle").checked;
}

function syncTimecourseUI() {
  const on = isTimecourse();
  $("timecourse-fields").hidden = !on;
  $("capture-btn").textContent = on ? "Start run" : "Capture";
}

function expectedFrames(interval, duration) {
  if (!(interval > 0) || !(duration >= interval)) return null;
  return Math.floor(duration / interval) + 1;
}

function updateEstimate() {
  const interval = Number($("exp-interval").value) * 60;
  const duration = Number($("exp-duration").value) * 3600;
  const n = expectedFrames(interval, duration);
  $("frame-estimate").textContent =
    n == null ? "Enter an interval ≤ duration." : `≈ ${n} frames over this run.`;
}

// The primary button captures once, or starts a run when timecourse mode is on.
function onPrimaryClick() {
  if (isTimecourse()) startRun();
  else capture();
}

// --- Timecourse run: define it, then poll progress + recent frames while capturing. ---
const POLL_INTERVAL_MS = 3000; // frames arrive at the capture interval (seconds), not sub-second
let pollTimer = null;
let pollInFlight = false;
let currentExpId = null;

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
  const btn = $("capture-btn");
  btn.disabled = true;
  status.textContent = "Starting run…";
  try {
    const res = await fetch("/api/experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        notes: $("exp-notes").value.trim(),
        interval_seconds: Number($("exp-interval").value) * 60,
        duration_seconds: Number($("exp-duration").value) * 3600,
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
  // The run drives the camera on its own cadence; live view would fight it.
  stopPreview();
  // Keep timecourse mode selected so ending the run returns to the run-setup fields.
  $("timecourse-toggle").checked = true;
  syncTimecourseUI();
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
  $("status").textContent = "";
  showSetup();
  startPreview(); // resume live view for tuning the next capture/run
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

async function pollOnce() {
  if (pollInFlight || currentExpId == null) return;
  pollInFlight = true;
  try {
    const res = await fetch(`/api/experiments/${currentExpId}`);
    if (!res.ok) throw new Error(await res.text());
    renderRun(await res.json());
    await loadGallery(); // newest frames of the active run land in the recent strip
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

// On load: build the controls + presets, then either resume an active run or start
// the live view for a fresh setup.
async function init() {
  await loadControls();
  await loadPresets();
  await loadGallery();
  updateEstimate();
  syncTimecourseUI();

  $("capture-btn").addEventListener("click", onPrimaryClick);
  $("preview-btn").addEventListener("click", togglePreview);
  $("save-preset-btn").addEventListener("click", savePreset);
  $("timecourse-toggle").addEventListener("change", syncTimecourseUI);
  $("exp-interval").addEventListener("input", updateEstimate);
  $("exp-duration").addEventListener("input", updateEstimate);
  $("stop-btn").addEventListener("click", stopRun);
  $("new-btn").addEventListener("click", newRun);

  // Resume into an active run if one exists (survives tab close / service restart);
  // otherwise start the default live view.
  try {
    const res = await fetch("/api/experiments");
    const runs = await res.json();
    const active = runs.find((r) => r.status === "running");
    if (active) {
      enterRun(active);
      return;
    }
  } catch {
    /* fall through to live view */
  }
  startPreview();
}

init();
