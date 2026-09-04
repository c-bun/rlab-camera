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
  if (c.description) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = c.description;
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

async function capture() {
  const btn = document.getElementById("capture-btn");
  const status = document.getElementById("status");
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
    card.innerHTML = `
      <img src="/api/images/${img.id}/file" alt="capture ${img.id}" loading="lazy">
      <div class="info">
        #${img.id} · ${img.width}×${img.height} · ${img.image_format}<br>
        <a href="/api/images/${img.id}/file?download=true">Download</a>
      </div>`;
    gallery.appendChild(card);
  }
}

document.getElementById("capture-btn").addEventListener("click", capture);
loadControls();
loadGallery();
