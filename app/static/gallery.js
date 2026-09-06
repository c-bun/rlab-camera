"use strict";

// Selection state. A run selected via its stack checkbox is downloaded whole;
// individual captures and expanded frames are selected by image id.
const selectedImages = new Set();
const selectedRuns = new Set();

let ungroupedIds = []; // image ids of ad-hoc captures (for "select all")
let runIds = []; // experiment ids shown as stacks (for "select all")

function thumbSrc(img) {
  // Browsers can't render TIFF inline — use the server JPEG thumbnail for those.
  const isTiff = img.image_format === "tiff" || img.image_format === "tif";
  return isTiff ? `/api/images/${img.id}/thumbnail` : `/api/images/${img.id}/file`;
}

function updateToolbar() {
  const n = selectedImages.size + selectedRuns.size;
  document.getElementById("selected-count").textContent = `${n} selected`;
  document.getElementById("download-btn").disabled = n === 0;
  const all = ungroupedIds.length + runIds.length;
  const selectAll = document.getElementById("select-all");
  selectAll.checked = all > 0 && n === all;
}

function captureTile(img) {
  const tile = document.createElement("div");
  tile.className = "tile";

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "tile-check";
  check.checked = selectedImages.has(img.id);
  check.addEventListener("change", () => {
    if (check.checked) selectedImages.add(img.id);
    else selectedImages.delete(img.id);
    updateToolbar();
  });

  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <img src="${thumbSrc(img)}" alt="capture ${img.id}" loading="lazy">
    <div class="info">
      #${img.id} · ${img.width}×${img.height} · ${img.image_format}<br>
      <a href="/api/images/${img.id}/file?download=true">Download</a>
    </div>`;

  tile.appendChild(check);
  tile.appendChild(card);
  return tile;
}

function stackTile(exp) {
  const tile = document.createElement("div");
  tile.className = "tile stack";

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "tile-check";
  check.checked = selectedRuns.has(exp.id);
  check.addEventListener("change", () => {
    if (check.checked) selectedRuns.add(exp.id);
    else selectedRuns.delete(exp.id);
    updateToolbar();
  });

  const card = document.createElement("div");
  card.className = "card";
  card.title = "Click to show frames";
  card.innerHTML = `
    <img src="/api/images/${exp.cover_image_id}/thumbnail" alt="run ${exp.id}" loading="lazy">
    <div class="info">
      <span class="run-name">${escapeHtml(exp.name)}</span>
      ${exp.frames_captured} frames <span class="badge-count">${exp.status}</span>
    </div>`;

  // Clicking the card body (not the checkbox) expands the run's frames inline.
  let expander = null;
  card.addEventListener("click", async () => {
    if (expander) {
      expander.remove();
      expander = null;
      return;
    }
    expander = document.createElement("div");
    expander.className = "frames-expander";
    expander.innerHTML = `<p class="empty">Loading frames…</p>`;
    tile.after(expander);
    try {
      const res = await fetch(`/api/experiments/${exp.id}/images?limit=500`);
      const frames = await res.json();
      expander.innerHTML = "";
      if (!frames.length) {
        expander.innerHTML = `<p class="empty">No frames.</p>`;
        return;
      }
      for (const img of frames) expander.appendChild(captureTile(img));
    } catch (err) {
      expander.innerHTML = `<p class="empty">Error: ${escapeHtml(err.message)}</p>`;
    }
  });

  tile.appendChild(check);
  tile.appendChild(card);
  return tile;
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : String(s);
  return div.innerHTML;
}

async function load() {
  const status = document.getElementById("status");
  const grid = document.getElementById("gallery-grid");
  try {
    const res = await fetch("/api/gallery");
    const data = await res.json();
    runIds = data.experiments.map((e) => e.id);
    ungroupedIds = data.images.map((i) => i.id);

    grid.innerHTML = "";
    for (const exp of data.experiments) grid.appendChild(stackTile(exp));
    for (const img of data.images) grid.appendChild(captureTile(img));

    if (!data.experiments.length && !data.images.length) {
      grid.innerHTML = `<p class="gallery-empty">No images yet.</p>`;
    }
    updateToolbar();
  } catch (err) {
    status.textContent = "Error loading gallery: " + err.message;
  }
}

function selectAll(checked) {
  selectedImages.clear();
  selectedRuns.clear();
  if (checked) {
    for (const id of ungroupedIds) selectedImages.add(id);
    for (const id of runIds) selectedRuns.add(id);
  }
  // Re-render so every checkbox (including expanded frames) reflects the new state.
  load();
}

async function downloadSelected() {
  const btn = document.getElementById("download-btn");
  const status = document.getElementById("status");
  btn.disabled = true;
  status.textContent = "Preparing download…";
  try {
    const res = await fetch("/api/gallery/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_ids: [...selectedImages],
        experiment_ids: [...selectedRuns],
      }),
    });
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(detail.detail || res.statusText);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "rlab-gallery.zip";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    status.textContent = "Download ready.";
  } catch (err) {
    status.textContent = "Download failed: " + err.message;
  } finally {
    btn.disabled = false;
    updateToolbar();
  }
}

document.getElementById("select-all").addEventListener("change", (e) => selectAll(e.target.checked));
document.getElementById("download-btn").addEventListener("click", downloadSelected);
load();
