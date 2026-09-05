// Capture page. Shared helpers (loadControls / collectSettings / applySettings /
// loadPresets / deletePreset) live in controls.js, included before this file.

// --- Live view: poll /api/preview ~2×/sec with the current control values, so
// tweaking a control updates the image without a full capture. ---
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
    const img = document.getElementById("preview");
    img.src = url;
    img.hidden = false;
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    previewUrl = url;
  } catch (err) {
    document.getElementById("status").textContent = "Live view error: " + err.message;
    stopPreview();
  } finally {
    previewInFlight = false;
  }
}

function startPreview() {
  if (isPreviewing()) return;
  document.getElementById("preview-btn").textContent = "Stop live view";
  previewTimer = setInterval(tickPreview, PREVIEW_INTERVAL_MS);
  tickPreview(); // show a first frame immediately
}

function stopPreview() {
  if (previewTimer !== null) {
    clearInterval(previewTimer);
    previewTimer = null;
  }
  document.getElementById("preview-btn").textContent = "Start live view";
}

function togglePreview() {
  if (isPreviewing()) stopPreview();
  else startPreview();
}

async function capture() {
  const btn = document.getElementById("capture-btn");
  const status = document.getElementById("status");
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

async function loadGallery() {
  const res = await fetch("/api/images?limit=48");
  const images = await res.json();
  const gallery = document.getElementById("gallery");
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
      document.getElementById("status").textContent = `Loaded settings from #${img.id}`;
    });
    gallery.appendChild(card);
  }
}

async function savePreset() {
  const input = document.getElementById("preset-name");
  const status = document.getElementById("status");
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

document.getElementById("capture-btn").addEventListener("click", capture);
document.getElementById("preview-btn").addEventListener("click", togglePreview);
document.getElementById("save-preset-btn").addEventListener("click", savePreset);
loadControls();
loadGallery();
loadPresets();
