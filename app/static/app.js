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

// Turn the LED panels off. Used when the user stops live view or a run starts — NOT in
// stopPreview() itself, since a manual capture pauses the preview there and then relies on
// the capture to drive the panels (on→off), which turning them off here would race.
function illuminationOff() {
  fetch("/api/illumination/off", { method: "POST" }).catch(() => {});
}

function togglePreview() {
  if (isPreviewing()) {
    stopPreview();
    illuminationOff();
  } else startPreview();
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
    // Timecourse frames say which acquisition/timepoint they are (textContent: the
    // acquisition name is user-entered).
    if (img.acquisition) {
      const tag = document.createElement("div");
      tag.className = "acq-tag";
      tag.textContent = `${img.acquisition} · t${img.timepoint ?? "?"}`;
      card.querySelector(".info").prepend(tag);
    }
    // Recall this capture's stored settings into the control panel. Bind the settings
    // object here rather than embedding JSON in the template string.
    card.querySelector(".use-settings-btn").addEventListener("click", () => {
      applySettings(img.settings);
      $("status").textContent = `Loaded settings from #${img.id}`;
    });
    gallery.appendChild(card);
  }
}

// Interval/duration and the acquisition list aren't part of #controls-form/
// #illumination-form (collectSettings()), so pull them in separately for presets.
// Returns {} if the fields aren't on this page.
function collectTimecourseFields() {
  const interval = $("exp-interval");
  const duration = $("exp-duration");
  if (!interval || !duration) return {};
  const fields = {
    interval_seconds: Number(interval.value) * 60,
    duration_seconds: Number(duration.value) * 3600,
  };
  if (acquisitions.length) fields.acquisitions = acquisitions;
  return fields;
}

// --- Acquisitions: the ordered list of settings snapshots a run captures at every
// timepoint (e.g. an illuminated frame for growth, then a long dark exposure for
// luminescence). Empty means "use the current settings as the only acquisition". ---
let acquisitions = [];

// Called by the preset Recall handler in controls.js.
function setAcquisitions(list) {
  acquisitions = list.map((a) => ({ name: a.name, settings: { ...a.settings } }));
  renderAcquisitions();
}

function acqSummary(s) {
  const parts = [];
  if (s.ExposureTime != null) parts.push(`${fmtExposure(s.ExposureTime)} exposure`);
  if (s.AnalogueGain != null) parts.push(`gain ${s.AnalogueGain}`);
  if (s.illum_enable) {
    parts.push(`light ${s.illum_color} @ ${s.illum_brightness ?? 100}%`);
  } else parts.push("light off");
  return parts.join(" · ");
}

function fmtExposure(us) {
  const s = us / 1e6;
  return s >= 1 ? `${+s.toFixed(2)} s` : `${+(us / 1000).toFixed(2)} ms`;
}

function renderAcquisitions() {
  const list = $("acquisitions-list");
  list.innerHTML = "";
  acquisitions.forEach((acq, i) => {
    const li = document.createElement("li");
    li.className = "acq-item";
    const head = document.createElement("div");
    head.className = "acq-head";
    const name = document.createElement("span");
    name.className = "acq-name";
    name.textContent = acq.name;
    head.append(name);

    const button = (label, title, onClick, disabled = false) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.title = title;
      b.disabled = disabled;
      b.addEventListener("click", onClick);
      head.append(b);
    };
    button("Load", "Load these settings into the controls to tune them in live view", () => {
      applySettings(acq.settings);
      refreshIllumStatus();
      acqMessage(`Loaded “${acq.name}” into the controls — tune, then Update.`);
    });
    button("Update", "Replace with the current control settings", () => {
      acq.settings = collectSettings();
      renderAcquisitions();
      acqMessage(`Updated “${acq.name}” from the current controls.`);
    });
    button("↑", "Move earlier", () => moveAcquisition(i, -1), i === 0);
    button("↓", "Move later", () => moveAcquisition(i, 1), i === acquisitions.length - 1);
    button("✕", "Remove", () => {
      acquisitions.splice(i, 1);
      renderAcquisitions();
    });

    const summary = document.createElement("div");
    summary.className = "acq-summary";
    if (acq.settings.illum_enable) {
      const swatch = document.createElement("span");
      swatch.className = "acq-swatch";
      swatch.style.background = acq.settings.illum_color;
      summary.append(swatch, " ");
    }
    summary.append(acqSummary(acq.settings));
    li.append(head, summary);
    list.appendChild(li);
  });
  $("acq-empty").hidden = acquisitions.length > 0;
  updateEstimate();
}

function moveAcquisition(i, delta) {
  const [acq] = acquisitions.splice(i, 1);
  acquisitions.splice(i + delta, 0, acq);
  renderAcquisitions();
}

// Feedback for the acquisition controls, shown right under them — the page-wide
// #status line sits far below the fold, so a message there reads as "nothing happened".
function acqMessage(text, { error = false } = {}) {
  const msg = $("acq-msg");
  msg.textContent = text;
  msg.classList.toggle("error", error);
  msg.hidden = !text;
  $("acq-name").setAttribute("aria-invalid", error ? "true" : "false");
}

function addAcquisition() {
  const input = $("acq-name");
  const name = input.value.trim();
  if (!name) {
    acqMessage("Enter a name first (e.g. brightfield, luminescence).", { error: true });
    input.focus();
    return;
  }
  if (acquisitions.some((a) => a.name === name)) {
    acqMessage(`“${name}” already exists — use its Update button to change it.`, {
      error: true,
    });
    input.focus();
    return;
  }
  acquisitions.push({ name, settings: collectSettings() });
  input.value = "";
  acqMessage(`Added “${name}”.`);
  renderAcquisitions();
}

// What the run will capture at each timepoint: the list, or the current settings alone.
function runAcquisitions() {
  return acquisitions.length ? acquisitions : [{ name: "default", settings: collectSettings() }];
}

// Mirrors scheduler.estimate_timepoint_seconds: each capture costs ~2 of its own
// exposures plus ~2 s overhead, and switching from the previous acquisition drains
// ~5 frames still in flight at that acquisition's exposure.
function estimateTimepointSeconds(list) {
  const exps = list.map((a) => (a.settings.ExposureTime || 0) / 1e6);
  return exps.reduce(
    (t, e, i) => t + 2 * e + 2 + (exps.length > 1 ? 5 * exps.at(i - 1) : 0),
    0,
  );
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
    const settings = { ...collectSettings(), ...collectTimecourseFields() };
    const res = await fetch("/api/presets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, settings }),
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
  const m = Math.max(1, acquisitions.length);
  $("frame-estimate").textContent =
    n == null
      ? "Enter an interval ≤ duration."
      : m > 1
        ? `≈ ${n} timepoints × ${m} acquisitions = ${n * m} frames over this run.`
        : `≈ ${n} frames over this run.`;

  // The server rejects a run whose timepoint can't fit in one interval; say so up front.
  const needed = estimateTimepointSeconds(runAcquisitions());
  const warn = $("timing-warn");
  warn.hidden = !(interval > 0 && needed > interval);
  warn.textContent = `⚠ One timepoint needs ~${fmtDuration(needed)} (switching away from a long exposure waits out ~5 of its frames), longer than the ${fmtDuration(interval)} interval.`;
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
  // Stop live view and turn the panels off BEFORE creating the run. The run's first frame
  // fires immediately server-side and lights the panels itself (synced per-frame), so an
  // off() sent *after* creation would race that frame and leave it half-lit. Awaiting the
  // off() here closes that gap; the run handles the panels from frame 0 on.
  stopPreview();
  try {
    await fetch("/api/illumination/off", { method: "POST" });
  } catch {
    /* best-effort: the run's per-frame sync drives the panels regardless */
  }
  try {
    const res = await fetch("/api/experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        notes: $("exp-notes").value.trim(),
        interval_seconds: Number($("exp-interval").value) * 60,
        duration_seconds: Number($("exp-duration").value) * 3600,
        acquisitions: runAcquisitions(),
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
  // The run drives the camera on its own cadence; live view would fight it, so stop it.
  // Panels are synced per-frame by perform_capture. We do NOT turn them off here: startRun
  // already did that before creating the run (turning them off after creation would race
  // the immediate first frame), and on resume the run owns the panels frame-to-frame.
  stopPreview();
  // Keep timecourse mode selected so ending the run returns to the run-setup fields.
  $("timecourse-toggle").checked = true;
  syncTimecourseUI();
  $("run-name").textContent = exp.name;
  $("run-notes").textContent = exp.notes || "";
  $("run-notes").hidden = !exp.notes;
  // On resume (page reload mid-run) restore the run's acquisition list so "New run"
  // starts from the same setup. A single "default" acquisition means none were defined.
  const named = exp.acquisitions.length > 1 || exp.acquisitions[0].name !== "default";
  if (!acquisitions.length && named) setAcquisitions(exp.acquisitions);
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
  const multi = exp.acquisition_names.length > 1;
  let line = multi
    ? `${exp.timepoints_captured} / ${exp.expected_timepoints} timepoints · ${exp.status}`
    : `${exp.frames_captured} / ${exp.expected_total} frames · ${exp.status}`;
  if (exp.status === "running") {
    line += ` · ${fmtDuration(exp.seconds_remaining)} remaining`;
  }
  $("run-progress").textContent = line;

  // Per-acquisition frame counts, so a failing acquisition (e.g. a dark exposure
  // that errors) is visible rather than hidden in the total.
  const list = $("run-acquisitions");
  list.innerHTML = "";
  list.hidden = !multi;
  if (multi) {
    for (const name of exp.acquisition_names) {
      const li = document.createElement("li");
      li.textContent = `${name}: ${exp.frames_by_acquisition[name]} / ${exp.expected_timepoints}`;
      list.appendChild(li);
    }
  }

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
// Poll panel connectivity so the illumination warning stays current (a panel can drop
// mid-session). Cheap: the status endpoint is a no-op on the mock backend.
const ILLUM_STATUS_INTERVAL_MS = 5000;

async function init() {
  await loadControls();
  await loadIllumination();
  await loadPresets();
  refreshIllumStatus();
  setInterval(refreshIllumStatus, ILLUM_STATUS_INTERVAL_MS);
  await loadGallery();
  updateEstimate();
  syncTimecourseUI();

  $("capture-btn").addEventListener("click", onPrimaryClick);
  $("preview-btn").addEventListener("click", togglePreview);
  $("save-preset-btn").addEventListener("click", savePreset);
  $("timecourse-toggle").addEventListener("change", syncTimecourseUI);
  $("exp-interval").addEventListener("input", updateEstimate);
  $("exp-duration").addEventListener("input", updateEstimate);
  // With no acquisitions defined the timing check uses the live controls (exposure).
  $("controls-form").addEventListener("input", updateEstimate);
  $("add-acq-btn").addEventListener("click", addAcquisition);
  $("acq-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") addAcquisition();
  });
  $("acq-name").addEventListener("input", () => {
    if ($("acq-msg").classList.contains("error")) acqMessage("");
  });
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
