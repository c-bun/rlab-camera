// Build the manual-control panel from the backend's reported controls, so the UI
// always reflects what the current camera actually supports.

async function loadControls() {
  const res = await fetch("/api/controls");
  const { controls } = await res.json();
  const form = document.getElementById("controls-form");
  form.innerHTML = "";
  for (const c of controls) {
    form.appendChild(renderField(c));
  }
}

function renderField(c) {
  const wrap = document.createElement("div");
  wrap.className = "field";

  const label = document.createElement("label");
  label.textContent = c.label + (c.unit ? ` (${c.unit})` : "");
  label.htmlFor = c.name;
  if (c.description) {
    // Show the explanation on hover so the form stays uncluttered.
    const info = document.createElement("span");
    info.className = "info-icon";
    info.textContent = "ⓘ";
    info.title = c.description;
    info.setAttribute("aria-label", c.description);
    label.append(" ", info);
  }
  wrap.appendChild(label);

  let input;
  if (c.kind === "choice") {
    input = document.createElement("select");
    for (const opt of c.choices || []) {
      const o = document.createElement("option");
      o.value = opt;
      o.textContent = opt;
      if (opt === c.default) o.selected = true;
      input.appendChild(o);
    }
  } else if (c.kind === "bool") {
    input = document.createElement("input");
    input.type = "checkbox";
    input.checked = !!c.default;
  } else {
    input = document.createElement("input");
    input.type = "number";
    if (c.min != null) input.min = c.min;
    if (c.max != null) input.max = c.max;
    if (c.step != null) input.step = c.step;
    if (c.default != null) input.value = c.default;
  }
  input.id = c.name;
  input.name = c.name;
  input.dataset.kind = c.kind;
  wrap.appendChild(input);

  if (c.min != null && c.max != null) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = `range ${c.min} – ${c.max}`;
    wrap.appendChild(meta);
  }
  return wrap;
}

function collectSettings() {
  const settings = {};
  for (const el of document.querySelectorAll("#controls-form [name]")) {
    if (el.dataset.kind === "bool") settings[el.name] = el.checked;
    else if (el.dataset.kind === "number") settings[el.name] = el.value === "" ? null : Number(el.value);
    else settings[el.name] = el.value;
  }
  return settings;
}

// Inverse of collectSettings(): load a stored settings dict back into the control
// panel. Iterating the form's inputs (not the settings keys) means extra keys that
// aren't controls — captured_at, the actual resolution recorded on a capture — are
// simply ignored. If a live preview is running it picks up the change on its next poll.
function applySettings(settings) {
  for (const el of document.querySelectorAll("#controls-form [name]")) {
    if (!(el.name in settings) || settings[el.name] == null) continue;
    if (el.dataset.kind === "bool") el.checked = !!settings[el.name];
    else el.value = settings[el.name];
  }
}

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

// --- Presets: named, server-side, shared across lab members. ---
async function loadPresets() {
  const res = await fetch("/api/presets");
  const presets = await res.json();
  const list = document.getElementById("presets-list");
  list.innerHTML = "";
  if (presets.length === 0) {
    const empty = document.createElement("li");
    empty.className = "preset-empty";
    empty.textContent = "No presets saved yet.";
    list.appendChild(empty);
    return;
  }
  for (const p of presets) {
    const li = document.createElement("li");
    li.className = "preset-item";
    const name = document.createElement("span");
    name.className = "preset-item-name";
    name.textContent = p.name;

    const recall = document.createElement("button");
    recall.type = "button";
    recall.textContent = "Recall";
    recall.addEventListener("click", () => {
      applySettings(p.settings);
      document.getElementById("status").textContent = `Loaded preset “${p.name}”`;
    });

    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "Delete";
    del.className = "preset-delete";
    del.addEventListener("click", () => deletePreset(p.id));

    li.append(name, recall, del);
    list.appendChild(li);
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

async function deletePreset(id) {
  try {
    const res = await fetch(`/api/presets/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await res.text());
    await loadPresets();
  } catch (err) {
    document.getElementById("status").textContent = "Error deleting preset: " + err.message;
  }
}

document.getElementById("capture-btn").addEventListener("click", capture);
document.getElementById("preview-btn").addEventListener("click", togglePreview);
document.getElementById("save-preset-btn").addEventListener("click", savePreset);
loadControls();
loadGallery();
loadPresets();
