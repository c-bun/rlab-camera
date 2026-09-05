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
      </div>`;
    gallery.appendChild(card);
  }
}

document.getElementById("capture-btn").addEventListener("click", capture);
document.getElementById("preview-btn").addEventListener("click", togglePreview);
loadControls();
loadGallery();
