// Shared control-panel helpers used by both the capture page (app.js) and the
// timecourse page (timecourse.js): build the manual-control form from the backend's
// reported controls, read/write settings from it, and load/recall/delete presets.

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

// --- Presets: named, server-side, shared across lab members. Loadable on both pages;
// saving a new preset lives on the capture page only. ---
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

async function deletePreset(id) {
  try {
    const res = await fetch(`/api/presets/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await res.text());
    await loadPresets();
  } catch (err) {
    document.getElementById("status").textContent = "Error deleting preset: " + err.message;
  }
}
