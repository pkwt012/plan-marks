"use strict";

const COLORS = [
  { name: "Symbol default", value: "" },
  { name: "Black", value: "#141414" },
  { name: "Red", value: "#c4271b" },
  { name: "Blue", value: "#1d4e89" },
  { name: "Green", value: "#1f7a3a" },
  { name: "Orange", value: "#d46b08" },
];

const SCALE_STANDARDS = [
  [1, '1" = 1\'-0"'],
  [0.75, '3/4" = 1\'-0"'],
  [0.5, '1/2" = 1\'-0"'],
  [0.375, '3/8" = 1\'-0"'],
  [0.25, '1/4" = 1\'-0"'],
  [0.1875, '3/16" = 1\'-0"'],
  [0.125, '1/8" = 1\'-0"'],
  [0.09375, '3/32" = 1\'-0"'],
  [0.0625, '1/16" = 1\'-0"'],
];

const state = {
  doc: null,
  pageIndex: 0,
  placements: [],
  selectedId: null,
  armedId: null,
  ink: "",
  defaultSize: 28,
  calibration: null,
  calibStep: 0,
  calibDraft: null,
  tool: null,
  lineDraft: null,
  undo: [],
  redo: [],
  panX: 24,
  panY: 24,
  zoom: 1,
  space: false,
  drag: null,
  imageKey: "",
  imageToken: 0,
  pageUrl: "",
  saveTimer: 0,
  sharpenTimer: 0,
  pendingProject: null,
};

let library = { categories: [], symbols: [] };
let symbolsById = {};
let sizeUndoArmed = false;

const SVGNS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const viewport = $("viewport");
const scene = $("scene");
const pageImg = $("pageImg");
const marksLayer = $("marks");
const calibLayer = $("calibLayer");

function clamp(n, lo, hi) {
  return Math.min(hi, Math.max(lo, n));
}

function uid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return "id-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function normRot(deg) {
  let d = Number(deg) || 0;
  d %= 360;
  if (d < 0) d += 360;
  if (d < 0.05 || d > 359.95) return 0;
  return d;
}

function currentPage() {
  return state.doc ? state.doc.pages[state.pageIndex] : null;
}

function selected() {
  return state.placements.find((item) => item.id === state.selectedId) || null;
}

function placement(id) {
  return state.placements.find((item) => item.id === id) || null;
}

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => {
    el.hidden = true;
  }, 4600);
}

function setBusy(on, label) {
  const veil = $("veil");
  veil.hidden = !on;
  if (label) veil.textContent = label;
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

async function readError(res) {
  try {
    const data = await res.json();
    if (data.error) return data.error;
  } catch (_err) {
    /* response was not JSON */
  }
  return res.statusText || "Request failed";
}

function scaleLabel(inchesPerFoot) {
  let best = null;
  let err = Infinity;
  for (const [value, label] of SCALE_STANDARDS) {
    const delta = Math.abs(value - inchesPerFoot) / value;
    if (delta < err) {
      err = delta;
      best = label;
    }
  }
  if (best && err < 0.08) return best;
  return `${inchesPerFoot.toFixed(3)}" = 1'-0"`;
}

function clientToPdf(cx, cy) {
  const vr = viewport.getBoundingClientRect();
  return {
    x: (cx - vr.left - state.panX) / state.zoom,
    y: (cy - vr.top - state.panY) / state.zoom,
  };
}

function pdfToClient(x, y) {
  const vr = viewport.getBoundingClientRect();
  return {
    x: vr.left + state.panX + x * state.zoom,
    y: vr.top + state.panY + y * state.zoom,
  };
}

function applyTransform() {
  scene.style.transform = `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})`;
  const pct = Math.round((state.zoom * 72) / 96 * 100);
  $("zoomLabel").textContent = pct + "%";
  const handle = document.querySelector(".mark.selected .handle");
  const p = selected();
  if (handle && p && p.kind !== "line" && p.kind !== "legend") positionHandle(handle, p);
  refreshWireChrome();
  drawCalib();
}

function zoomAt(cx, cy, factor) {
  const vr = viewport.getBoundingClientRect();
  const x = cx - vr.left;
  const y = cy - vr.top;
  const worldX = (x - state.panX) / state.zoom;
  const worldY = (y - state.panY) / state.zoom;
  const next = clamp(state.zoom * factor, 0.05, 10);
  state.zoom = next;
  state.panX = x - worldX * next;
  state.panY = y - worldY * next;
  applyTransform();
  scheduleSharpen();
}

function fitView(attempt = 0) {
  const page = currentPage();
  if (!page) return;
  const vr = viewport.getBoundingClientRect();
  if (vr.width < 40 || vr.height < 40) {
    if (attempt < 6) requestAnimationFrame(() => fitView(attempt + 1));
    return;
  }
  const margin = 56;
  const z = Math.min((vr.width - margin) / page.width, (vr.height - margin) / page.height);
  state.zoom = clamp(z > 0 ? z : 0.2, 0.05, 10);
  state.panX = (vr.width - page.width * state.zoom) / 2;
  state.panY = (vr.height - page.height * state.zoom) / 2;
  applyTransform();
  loadPageImage();
}

function actualSize() {
  const vr = viewport.getBoundingClientRect();
  zoomAt(vr.left + vr.width / 2, vr.top + vr.height / 2, 96 / 72 / state.zoom);
}

function chooseDpi() {
  const dpr = window.devicePixelRatio || 1;
  let dpi = Math.round(state.zoom * dpr * 72);
  dpi = clamp(dpi, 60, 150);
  return Math.round(dpi / 10) * 10;
}

function scheduleSharpen() {
  clearTimeout(state.sharpenTimer);
  state.sharpenTimer = setTimeout(() => loadPageImage(), 160);
}

async function loadPageImage() {
  if (!state.doc) return;
  const pageIndex = state.pageIndex;
  const dpi = chooseDpi();
  const key = `${state.doc.id}:${pageIndex}:${dpi}`;
  if (key === state.imageKey) return;
  const token = ++state.imageToken;
  try {
    const res = await fetch(`/api/page/${pageIndex}.png?dpi=${dpi}&doc=${state.doc.id}`);
    if (!res.ok) throw new Error(await readError(res));
    const blob = await res.blob();
    if (token !== state.imageToken) return;
    const url = URL.createObjectURL(blob);
    if (state.pageUrl) URL.revokeObjectURL(state.pageUrl);
    state.pageUrl = url;
    state.imageKey = key;
    pageImg.src = url;
  } catch (err) {
    if (token === state.imageToken) toast(err.message);
  }
}

function showWorkspace() {
  $("empty").hidden = true;
  viewport.hidden = false;
}

function updatePager() {
  const pager = $("pager");
  const select = $("pageSelect");
  if (!state.doc) {
    pager.hidden = true;
    $("docTitle").textContent = "No plan open";
    return;
  }
  pager.hidden = false;
  $("docTitle").textContent = state.doc.filename;
  select.innerHTML = "";
  state.doc.pages.forEach((page, index) => {
    const opt = document.createElement("option");
    opt.value = String(index);
    const fallback = `Sheet ${index + 1}`;
    opt.textContent = page.label && page.label !== String(index + 1) ? `${fallback} · ${page.label}` : fallback;
    select.appendChild(opt);
  });
  select.value = String(state.pageIndex);
  $("prevPage").disabled = state.pageIndex <= 0;
  $("nextPage").disabled = state.pageIndex >= state.doc.pageCount - 1;
  $("exportBtn").disabled = false;
  $("saveBtn").disabled = false;
  $("addBtn").disabled = false;
  $("legendBtn").disabled = false;
  $("lineBtn").disabled = false;
  $("dropLegendBtn").disabled = false;
}

function showPage(index, { fit = false } = {}) {
  state.pageIndex = index;
  const page = currentPage();
  scene.style.width = page.width + "px";
  scene.style.height = page.height + "px";
  pageImg.style.width = page.width + "px";
  pageImg.style.height = page.height + "px";
  updatePager();
  renderMarks();
  if (fit) requestAnimationFrame(() => fitView());
  else {
    applyTransform();
    loadPageImage();
  }
  setStatus();
}

function goToPage(index) {
  if (!state.doc || index < 0 || index >= state.doc.pageCount || index === state.pageIndex) return;
  const prev = currentPage();
  const next = state.doc.pages[index];
  const refit = Math.abs(prev.width - next.width) > 1 || Math.abs(prev.height - next.height) > 1;
  if (state.calibStep === 1 || state.calibStep === 2) {
    state.calibStep = 0;
    state.calibDraft = null;
    toast("Calibration cancelled because the sheet changed.");
  }
  if (state.lineDraft) {
    state.lineDraft = null;
    toast("Dashed line cancelled because the sheet changed.");
  }
  showPage(index, { fit: refit });
  syncInspector();
}

function paintSvg(symbolId, rotation, color) {
  const sym = symbolsById[symbolId];
  if (!sym) return null;
  const colored = sym.svg.replaceAll("#141414", color || sym.defaultColor || "#141414");
  const doc = new DOMParser().parseFromString(colored, "image/svg+xml");
  const node = doc.querySelector("svg");
  if (!node || doc.querySelector("parsererror")) return null;
  const rot = node.querySelector(".rot");
  if (rot && rotation) rot.setAttribute("transform", `rotate(${rotation} 50 50)`);
  return node;
}

function positionMark(el, p) {
  el.style.width = p.size + "px";
  el.style.height = p.size + "px";
  el.style.left = p.x - p.size / 2 + "px";
  el.style.top = p.y - p.size / 2 + "px";
}

function positionHandle(handle, p) {
  const rad = ((p.rotation + 90) * Math.PI) / 180;
  const dist = p.size / 2 + 18 / state.zoom;
  handle.style.left = p.size / 2 + Math.cos(rad) * dist + "px";
  handle.style.top = p.size / 2 + Math.sin(rad) * dist + "px";
  handle.style.transform = `translate(-50%, -50%) scale(${1 / state.zoom})`;
}

function markElement(p) {
  const el = document.createElement("div");
  el.className = "mark" + (p.id === state.selectedId ? " selected" : "");
  el.dataset.id = p.id;
  positionMark(el, p);
  const glyph = document.createElement("div");
  glyph.className = "glyph";
  const svg = paintSvg(p.symbolId, p.rotation, p.color);
  if (svg) glyph.appendChild(document.importNode(svg, true));
  el.appendChild(glyph);
  if (p.id === state.selectedId) {
    const handle = document.createElement("div");
    handle.className = "handle";
    handle.dataset.id = p.id;
    handle.title = "Drag to rotate. Shift snaps to 15°.";
    handle.textContent = "↻";
    positionHandle(handle, p);
    el.appendChild(handle);
  }
  return el;
}

function isSymbol(p) {
  return p && p.kind !== "line" && p.kind !== "legend";
}

function legendBox(width) {
  const lay = library.legend;
  if (!lay || !lay.width) return { width: width || 360, height: 240, scale: 1 };
  const scale = (width || lay.width) / lay.width;
  return { width: lay.width * scale, height: lay.height * scale, scale };
}

function legendElement(p) {
  const lay = library.legend;
  const el = document.createElement("div");
  el.className = "mark legend" + (p.id === state.selectedId ? " selected" : "");
  el.dataset.id = p.id;
  const box = legendBox(p.width);
  el.style.width = box.width + "px";
  el.style.height = box.height + "px";
  el.style.left = p.x + "px";
  el.style.top = p.y + "px";
  const glyph = document.createElement("div");
  glyph.className = "glyph";
  if (lay) {
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("class", "legend-svg");
    svg.setAttribute("viewBox", `0 0 ${lay.width} ${lay.height}`);
    const border = document.createElementNS(SVGNS, "rect");
    border.setAttribute("x", "0.6");
    border.setAttribute("y", "0.6");
    border.setAttribute("width", String(lay.width - 1.2));
    border.setAttribute("height", String(lay.height - 1.2));
    border.setAttribute("fill", "#ffffff");
    border.setAttribute("stroke", "#383838");
    border.setAttribute("stroke-width", "1");
    svg.appendChild(border);
    for (const entry of lay.items || []) {
      const node = paintSvg(entry.id, 0, entry.color);
      if (!node) continue;
      const mark = document.importNode(node, true);
      mark.setAttribute("x", String(entry.x - entry.size / 2));
      mark.setAttribute("y", String(entry.y - entry.size / 2));
      mark.setAttribute("width", String(entry.size));
      mark.setAttribute("height", String(entry.size));
      svg.appendChild(mark);
    }
    for (const label of lay.labels || []) {
      const text = document.createElementNS(SVGNS, "text");
      text.setAttribute("x", String(label.x));
      text.setAttribute("y", String(label.y));
      text.setAttribute("font-family", "Helvetica, Arial, sans-serif");
      text.setAttribute("font-size", String(label.size));
      text.setAttribute("font-weight", label.weight === "bold" ? "700" : "400");
      text.setAttribute("fill", "#141414");
      text.textContent = label.text;
      svg.appendChild(text);
    }
    glyph.appendChild(svg);
  }
  el.appendChild(glyph);
  return el;
}

function wireMetrics() {
  return {
    hit: Math.max(10, 14 / state.zoom),
    handle: 5.5 / state.zoom,
  };
}

function wireLayer(id) {
  let svg = document.getElementById(id);
  if (!svg) {
    svg = document.createElementNS(SVGNS, "svg");
    svg.id = id;
    marksLayer.appendChild(svg);
  }
  const page = currentPage();
  if (page) {
    svg.setAttribute("viewBox", `0 0 ${page.width} ${page.height}`);
    svg.setAttribute("width", String(page.width));
    svg.setAttribute("height", String(page.height));
  }
  return svg;
}

function addWireLine(parent, p, className, color, width, events) {
  const line = document.createElementNS(SVGNS, "line");
  line.setAttribute("class", className);
  line.setAttribute("x1", p.x1);
  line.setAttribute("y1", p.y1);
  line.setAttribute("x2", p.x2);
  line.setAttribute("y2", p.y2);
  line.setAttribute("stroke", color);
  line.setAttribute("stroke-width", String(width));
  line.setAttribute("stroke-dasharray", "8 6");
  line.setAttribute("stroke-linecap", "butt");
  line.setAttribute("fill", "none");
  if (events) line.setAttribute("pointer-events", events);
  parent.appendChild(line);
  return line;
}

function wireGroup(p, draft) {
  const g = document.createElementNS(SVGNS, "g");
  g.setAttribute("class", draft ? "wire wire-draft" : "wire");
  if (!draft) g.dataset.id = p.id;
  const metrics = wireMetrics();
  if (!draft && p.id === state.selectedId) {
    addWireLine(g, p, "wire-halo", "#e2a23a", 3.4, "none");
  }
  addWireLine(g, p, "wire-ink", p.color || state.ink || "#141414", 1.35, "none");
  if (!draft) {
    const hit = addWireLine(g, p, "wire-hit", "#141414", metrics.hit, "stroke");
    hit.setAttribute("stroke-opacity", "0.01");
  }
  return g;
}

function handleGroup(p) {
  const g = document.createElementNS(SVGNS, "g");
  g.dataset.ends = p.id;
  const radius = wireMetrics().handle;
  for (const [end, x, y] of [
    ["1", p.x1, p.y1],
    ["2", p.x2, p.y2],
  ]) {
    const dot = document.createElementNS(SVGNS, "circle");
    dot.setAttribute("class", "wire-end");
    dot.dataset.id = p.id;
    dot.dataset.end = end;
    dot.setAttribute("cx", x);
    dot.setAttribute("cy", y);
    dot.setAttribute("r", String(radius));
    dot.setAttribute("fill", "#e2a23a");
    dot.setAttribute("stroke", "#2a1c06");
    dot.setAttribute("stroke-width", String(1 / state.zoom));
    g.appendChild(dot);
  }
  return g;
}

function renderWires() {
  if (!marksLayer) return;
  const wires = wireLayer("wires");
  const handles = wireLayer("wireHandles");
  wires.replaceChildren();
  handles.replaceChildren();
  if (!currentPage()) return;
  for (const p of state.placements) {
    if (p.kind !== "line" || p.page !== state.pageIndex) continue;
    wires.appendChild(wireGroup(p, false));
    if (p.id === state.selectedId) handles.appendChild(handleGroup(p));
  }
  if (state.lineDraft && state.lineDraft.page === state.pageIndex) {
    wires.appendChild(wireGroup(state.lineDraft, true));
  }
}

function refreshWireChrome() {
  if (!marksLayer) return;
  const metrics = wireMetrics();
  for (const line of marksLayer.querySelectorAll(".wire-hit")) {
    line.setAttribute("stroke-width", String(metrics.hit));
  }
  for (const dot of marksLayer.querySelectorAll(".wire-end")) {
    dot.setAttribute("r", String(metrics.handle));
    dot.setAttribute("stroke-width", String(1 / state.zoom));
  }
}

function renderMarks() {
  marksLayer.innerHTML = "";
  if (!state.doc) return;
  for (const p of state.placements) {
    if (p.page !== state.pageIndex || p.kind === "line") continue;
    marksLayer.appendChild(p.kind === "legend" ? legendElement(p) : markElement(p));
  }
  renderWires();
  drawCalib();
}

function updateLine(p) {
  const g = marksLayer.querySelector(`.wire[data-id="${CSS.escape(p.id)}"]`);
  if (!g) {
    renderWires();
    return;
  }
  for (const line of g.querySelectorAll("line")) {
    line.setAttribute("x1", p.x1);
    line.setAttribute("y1", p.y1);
    line.setAttribute("x2", p.x2);
    line.setAttribute("y2", p.y2);
  }
  const ink = g.querySelector(".wire-ink");
  if (ink) ink.setAttribute("stroke", p.color || "#141414");
  const ends = marksLayer.querySelector(`[data-ends="${CSS.escape(p.id)}"]`);
  if (ends) {
    const first = ends.querySelector('[data-end="1"]');
    const second = ends.querySelector('[data-end="2"]');
    if (first) {
      first.setAttribute("cx", p.x1);
      first.setAttribute("cy", p.y1);
    }
    if (second) {
      second.setAttribute("cx", p.x2);
      second.setAttribute("cy", p.y2);
    }
  }
}

function updateLegend(p) {
  const el = marksLayer.querySelector(`.mark[data-id="${CSS.escape(p.id)}"]`);
  if (!el) {
    renderMarks();
    return;
  }
  const box = legendBox(p.width);
  el.style.width = box.width + "px";
  el.style.height = box.height + "px";
  el.style.left = p.x + "px";
  el.style.top = p.y + "px";
}

function updateMark(p) {
  if (p.kind === "line") {
    updateLine(p);
    return;
  }
  if (p.kind === "legend") {
    updateLegend(p);
    return;
  }
  const el = marksLayer.querySelector(`.mark[data-id="${CSS.escape(p.id)}"]`);
  if (!el) {
    renderMarks();
    return;
  }
  positionMark(el, p);
  const rot = el.querySelector(".rot");
  if (rot) {
    if (p.rotation) rot.setAttribute("transform", `rotate(${p.rotation} 50 50)`);
    else rot.removeAttribute("transform");
  }
  const handle = el.querySelector(".handle");
  if (handle) positionHandle(handle, p);
  const rotInput = $("rotInput");
  if (rotInput && document.activeElement !== rotInput && p.id === state.selectedId) {
    rotInput.value = String(Math.round(p.rotation));
  }
}

function drawCalib() {
  const page = currentPage();
  calibLayer.innerHTML = "";
  if (!page) return;
  calibLayer.setAttribute("viewBox", `0 0 ${page.width} ${page.height}`);
  calibLayer.setAttribute("width", String(page.width));
  calibLayer.setAttribute("height", String(page.height));
  if (state.calibration && state.calibration.page === state.pageIndex) {
    addMeasure(state.calibration, false);
  }
  if (state.calibDraft && state.calibDraft.page === state.pageIndex && state.calibStep) {
    addMeasure(state.calibDraft, true);
  }
}

function addMeasure(m, active) {
  const ns = "http://www.w3.org/2000/svg";
  const color = active ? "#e2a23a" : "#1d4e89";
  const line = document.createElementNS(ns, "line");
  line.setAttribute("x1", m.x1);
  line.setAttribute("y1", m.y1);
  line.setAttribute("x2", m.x2);
  line.setAttribute("y2", m.y2);
  line.setAttribute("stroke", color);
  line.setAttribute("stroke-width", String(1.6 / state.zoom));
  line.setAttribute("stroke-linecap", "round");
  calibLayer.appendChild(line);
  for (const [x, y] of [
    [m.x1, m.y1],
    [m.x2, m.y2],
  ]) {
    const dot = document.createElementNS(ns, "circle");
    dot.setAttribute("cx", x);
    dot.setAttribute("cy", y);
    dot.setAttribute("r", String(4.5 / state.zoom));
    dot.setAttribute("fill", color);
    calibLayer.appendChild(dot);
  }
}

function snapshot() {
  return JSON.stringify({
    placements: state.placements,
    calibration: state.calibration,
    defaultSize: state.defaultSize,
    selectedId: state.selectedId,
  });
}

function pushUndo() {
  state.undo.push(snapshot());
  if (state.undo.length > 80) state.undo.shift();
  state.redo.length = 0;
}

function restore(raw) {
  const data = JSON.parse(raw);
  state.placements = data.placements || [];
  state.calibration = data.calibration || null;
  state.defaultSize = data.defaultSize || 28;
  state.selectedId = data.selectedId || null;
  if (state.selectedId && !selected()) state.selectedId = null;
  renderMarks();
  syncInspector();
  scheduleSave();
  setStatus();
}

function undo() {
  if (!state.undo.length) return;
  state.redo.push(snapshot());
  restore(state.undo.pop());
}

function redo() {
  if (!state.redo.length) return;
  state.undo.push(snapshot());
  restore(state.redo.pop());
}

function projectData() {
  return {
    app: "plan-marks",
    version: 1,
    pdfName: state.doc ? state.doc.filename : "",
    pdfId: state.doc ? state.doc.id : "",
    defaultSize: state.defaultSize,
    calibration: state.calibration,
    placements: state.placements,
  };
}

function scheduleSave() {
  clearTimeout(state.saveTimer);
  state.saveTimer = setTimeout(writeAutosave, 250);
}

function writeAutosave() {
  if (!state.doc) return;
  try {
    localStorage.setItem("planmarks:v1:" + state.doc.id, JSON.stringify(projectData()));
  } catch (_err) {
    /* private mode or a full disk */
  }
}

function applyProject(proj, { quiet = false } = {}) {
  if (!proj || proj.app !== "plan-marks" || proj.version !== 1) {
    toast("That file is not a Plan Marks project.");
    return;
  }
  if (!state.doc) {
    state.pendingProject = proj;
    toast("Open the floor plan PDF and these marks will be placed on it.");
    return;
  }
  pushUndo();
  let skipped = 0;
  const placements = [];
  for (const item of proj.placements || []) {
    const page = Number(item.page);
    if (!Number.isInteger(page) || page < 0 || page >= state.doc.pageCount) {
      skipped += 1;
      continue;
    }
    const color = /^#[0-9a-fA-F]{6}$/.test(item.color || "") ? item.color.toLowerCase() : "#141414";
    if (item.kind === "line") {
      const coords = [item.x1, item.y1, item.x2, item.y2].map(Number);
      if (coords.some((n) => !Number.isFinite(n))) {
        skipped += 1;
        continue;
      }
      placements.push({
        id: item.id || uid(),
        kind: "line",
        page,
        x1: coords[0],
        y1: coords[1],
        x2: coords[2],
        y2: coords[3],
        color,
      });
      continue;
    }
    if (item.kind === "legend") {
      const x = Number(item.x);
      const y = Number(item.y);
      const width = Number(item.width);
      if (![x, y, width].every((n) => Number.isFinite(n))) {
        skipped += 1;
        continue;
      }
      placements.push({
        id: item.id || uid(),
        kind: "legend",
        page,
        x,
        y,
        width: clamp(width, 40, 2000),
      });
      continue;
    }
    if (!symbolsById[item.symbolId]) {
      skipped += 1;
      continue;
    }
    placements.push({
      id: item.id || uid(),
      kind: "symbol",
      symbolId: item.symbolId,
      page,
      x: Number(item.x),
      y: Number(item.y),
      size: clamp(Number(item.size) || state.defaultSize, 8, 400),
      rotation: normRot(item.rotation),
      color,
    });
  }
  state.placements = placements;
  if (proj.defaultSize) state.defaultSize = clamp(Number(proj.defaultSize) || 28, 10, 160);
  state.calibration = proj.calibration || null;
  state.selectedId = null;
  state.calibStep = 0;
  state.calibDraft = null;
  renderMarks();
  syncInspector();
  scheduleSave();
  setStatus();
  if (!quiet && proj.pdfName && proj.pdfName !== state.doc.filename) {
    toast(`Project was saved for ${proj.pdfName}. Marks were applied to this file.`);
  }
  if (skipped) toast("Some marks were skipped because the symbol or sheet is missing.");
}

function renderPalette() {
  const palette = $("palette");
  const scroll = palette.scrollTop;
  const query = ($("filter").value || "").trim().toLowerCase();
  palette.innerHTML = "";
  for (const cat of library.categories) {
    const items = library.symbols.filter((sym) => {
      if (sym.category !== cat.id) return false;
      if (!query) return true;
      const hay = `${sym.name} ${sym.keywords || ""} ${sym.category}`.toLowerCase();
      return hay.includes(query);
    });
    if (!items.length) continue;
    const section = document.createElement("section");
    const title = document.createElement("h2");
    title.textContent = cat.name;
    section.appendChild(title);
    const grid = document.createElement("div");
    grid.className = "grid";
    for (const sym of items) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "sym" + (sym.id === state.armedId ? " active" : "");
      btn.title = sym.hint || sym.name;
      const swatch = document.createElement("div");
      swatch.className = "swatch";
      swatch.innerHTML = sym.svg.replaceAll("#141414", sym.defaultColor || "#141414");
      const name = document.createElement("span");
      name.className = "name";
      name.textContent = sym.name;
      btn.appendChild(swatch);
      btn.appendChild(name);
      btn.addEventListener("click", () => toggleArm(sym.id));
      grid.appendChild(btn);
    }
    section.appendChild(grid);
    palette.appendChild(section);
  }
  if (!palette.children.length) {
    const empty = document.createElement("p");
    empty.className = "hint";
    empty.textContent = "No symbols match that filter.";
    palette.appendChild(empty);
  }
  palette.scrollTop = scroll;
}

function buildSymbolSelect() {
  const select = $("symbolSelect");
  select.innerHTML = "";
  for (const sym of library.symbols) {
    const opt = document.createElement("option");
    opt.value = sym.id;
    opt.textContent = sym.name;
    select.appendChild(opt);
  }
}

function buildColors() {
  const box = $("colors");
  box.innerHTML = "";
  for (const color of COLORS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "swatch-btn";
    btn.dataset.value = color.value;
    btn.title = color.name;
    btn.setAttribute("aria-label", color.name);
    btn.setAttribute("aria-pressed", "false");
    if (color.value) btn.style.background = color.value;
    btn.addEventListener("click", () => applyColor(color.value));
    box.appendChild(btn);
  }
}

function clearDrawingTools() {
  state.tool = null;
  state.lineDraft = null;
  state.calibStep = 0;
  state.calibDraft = null;
}

function toggleArm(id) {
  clearDrawingTools();
  state.armedId = state.armedId === id ? null : id;
  renderPalette();
  syncInspector();
  renderMarks();
  setStatus();
}

function setTool(name) {
  if (!state.doc) return;
  const next = state.tool === name ? null : name;
  clearDrawingTools();
  state.armedId = null;
  state.tool = next;
  renderPalette();
  syncInspector();
  renderMarks();
  setStatus();
}

function sizeText(pt) {
  let text = `${(pt / 72).toFixed(2)}" on the sheet`;
  if (state.calibration) {
    const feet = pt / state.calibration.pointsPerFoot;
    text += ` · ${feet.toFixed(2)} ft on the plan`;
  }
  return text;
}

function syncInspector() {
  const p = selected();
  const sym = state.armedId ? symbolsById[state.armedId] : null;
  const symbolLike = isSymbol(p);
  const hint = $("toolHint");
  if (state.calibStep === 1) hint.textContent = "Click the first end of a known length.";
  else if (state.calibStep === 2) hint.textContent = "Click the other end.";
  else if (state.calibStep === 3) hint.textContent = "Enter how long that distance is, then Apply.";
  else if (state.tool === "line" && state.lineDraft) hint.textContent = "Click the next point. Esc cancels this segment.";
  else if (state.tool === "line") hint.textContent = "Click the first point of a dashed line. Esc puts the tool away.";
  else if (state.tool === "legend") hint.textContent = "Click the sheet to drop a legend of every symbol.";
  else if (sym) hint.textContent = sym.hint || `Click the plan to place ${sym.name}. Esc puts the tool away.`;
  else if (p && p.kind === "line") hint.textContent = "Drag the line to move it. Drag an amber end to change it.";
  else if (p && p.kind === "legend") hint.textContent = "Drag the legend. The slider changes how wide it is.";
  else if (p) hint.textContent = symbolsById[p.symbolId] ? symbolsById[p.symbolId].hint : "Drag to move. Drag the handle to rotate.";
  else hint.textContent = state.doc ? "Pick a symbol, then click the sheet." : "Open a plan, pick a symbol, then click the sheet to place it.";

  const range = $("sizeRange");
  if (p && p.kind === "legend") {
    range.disabled = false;
    range.min = "120";
    range.max = "800";
    range.step = "2";
    if (document.activeElement !== range) range.value = String(Math.round(p.width));
    $("sizeLabel").textContent = "Legend width";
    $("sizeReadout").textContent = sizeText(p.width);
  } else if (p && p.kind === "line") {
    range.disabled = true;
    $("sizeLabel").textContent = "Dashed line";
    $("sizeReadout").textContent = sizeText(Math.hypot(p.x2 - p.x1, p.y2 - p.y1));
  } else {
    range.disabled = false;
    range.min = "10";
    range.max = "160";
    range.step = "1";
    const activeSize = p ? p.size : state.defaultSize;
    if (document.activeElement !== range) range.value = String(Math.round(activeSize));
    $("sizeLabel").textContent = p ? "Selected size" : "Size for new symbols";
    $("sizeReadout").textContent = sizeText(activeSize);
  }
  $("sizeOneFoot").disabled = !state.calibration || (p && !symbolLike);
  for (const btn of document.querySelectorAll(".presets [data-size]")) {
    btn.disabled = Boolean(p && !symbolLike);
  }

  const calibState = $("calibState");
  if (state.calibration) {
    calibState.textContent = `Scale ${state.calibration.label}. It applies to every sheet.`;
    $("calibClear").hidden = false;
  } else {
    calibState.textContent = "Scale not set. Calibrate on a dimension line to read sizes in feet.";
    $("calibClear").hidden = true;
  }
  $("calibForm").hidden = state.calibStep !== 3;
  $("calibBtn").textContent = state.calibStep ? "Cancel" : "Calibrate";
  $("lineBtn").classList.toggle("active", state.tool === "line");
  $("lineBtn").setAttribute("aria-pressed", state.tool === "line" ? "true" : "false");
  $("dropLegendBtn").classList.toggle("active", state.tool === "legend");
  $("dropLegendBtn").setAttribute("aria-pressed", state.tool === "legend" ? "true" : "false");

  $("selectionBox").hidden = !p;
  $("symbolField").hidden = !symbolLike;
  $("rotationField").hidden = !symbolLike;
  $("colors").hidden = Boolean(p && p.kind === "legend");
  if (symbolLike) {
    $("symbolSelect").value = p.symbolId;
    if (document.activeElement !== $("rotInput")) $("rotInput").value = String(Math.round(p.rotation || 0));
  }
  for (const btn of $("colors").querySelectorAll(".swatch-btn")) {
    const match = p && p.kind !== "legend" ? btn.dataset.value === (p.color || "") : btn.dataset.value === state.ink;
    btn.setAttribute("aria-pressed", match ? "true" : "false");
  }
  viewport.classList.toggle("placing", Boolean(state.armedId || state.tool) && !state.calibStep);
}

function setSize(pt, { undo = false } = {}) {
  const p = selected();
  if (p && p.kind === "line") return;
  if (p && p.kind === "legend") {
    pt = clamp(pt, 120, 800);
    if (undo) pushUndo();
    p.width = pt;
    updateMark(p);
    syncInspector();
    scheduleSave();
    return;
  }
  pt = clamp(pt, 10, 160);
  if (undo) pushUndo();
  if (p) p.size = pt;
  else state.defaultSize = pt;
  if (p) updateMark(p);
  syncInspector();
  scheduleSave();
}

function applyColor(value) {
  const p = selected();
  if (p && p.kind === "legend") return;
  if (p) pushUndo();
  state.ink = value;
  const ink = value || "#141414";
  if (state.lineDraft) state.lineDraft.color = ink;
  if (p && p.kind === "line") p.color = ink;
  else if (p) {
    const sym = symbolsById[p.symbolId];
    p.color = value || (sym && sym.defaultColor) || "#141414";
  }
  if (p && p.kind !== "line") renderMarks();
  else if ((p && p.kind === "line") || state.lineDraft) renderWires();
  syncInspector();
  scheduleSave();
}

function bumpRotation(delta) {
  const p = selected();
  if (!isSymbol(p)) return;
  pushUndo();
  p.rotation = normRot(p.rotation + delta);
  updateMark(p);
  scheduleSave();
}

function duplicatePlacement(p, dx, dy) {
  const copy = { ...p, id: uid() };
  if (p.kind === "line") {
    copy.x1 = p.x1 + dx;
    copy.y1 = p.y1 + dy;
    copy.x2 = p.x2 + dx;
    copy.y2 = p.y2 + dy;
  } else {
    copy.x = p.x + dx;
    copy.y = p.y + dy;
  }
  state.placements.push(copy);
  return copy;
}

function duplicateShift(p) {
  if (p.kind === "line") return 16;
  if (p.kind === "legend") return 24;
  return p.size * 0.35;
}

function duplicateSelected() {
  const p = selected();
  if (!p) return;
  pushUndo();
  const shift = duplicateShift(p);
  const copy = duplicatePlacement(p, shift, shift);
  state.selectedId = copy.id;
  renderMarks();
  syncInspector();
  scheduleSave();
  setStatus();
}

function deleteSelected() {
  const p = selected();
  if (!p) return;
  pushUndo();
  state.placements = state.placements.filter((item) => item.id !== p.id);
  state.selectedId = null;
  renderMarks();
  syncInspector();
  scheduleSave();
  setStatus();
}

function placeAt(cx, cy) {
  const sym = symbolsById[state.armedId];
  const page = currentPage();
  if (!sym || !page) return;
  const pt = clientToPdf(cx, cy);
  if (pt.x < -40 || pt.y < -40 || pt.x > page.width + 40 || pt.y > page.height + 40) return;
  pushUndo();
  const mark = {
    id: uid(),
    kind: "symbol",
    symbolId: sym.id,
    page: state.pageIndex,
    x: pt.x,
    y: pt.y,
    size: state.defaultSize,
    rotation: 0,
    color: state.ink || sym.defaultColor || "#141414",
  };
  state.placements.push(mark);
  state.selectedId = mark.id;
  renderMarks();
  syncInspector();
  scheduleSave();
  setStatus();
}

function calibClick(pt) {
  if (state.calibStep === 1) {
    state.calibDraft = { page: state.pageIndex, x1: pt.x, y1: pt.y, x2: pt.x, y2: pt.y };
    state.calibStep = 2;
  } else if (state.calibStep === 2) {
    state.calibDraft.x2 = pt.x;
    state.calibDraft.y2 = pt.y;
    const length = Math.hypot(state.calibDraft.x2 - state.calibDraft.x1, state.calibDraft.y2 - state.calibDraft.y1);
    if (length < 2) {
      toast("Those points are too close. Click two ends of the dimension.");
      return;
    }
    state.calibStep = 3;
    requestAnimationFrame(() => $("calibLen").focus());
  }
  syncInspector();
  drawCalib();
  setStatus();
}

function applyCalibration() {
  const draft = state.calibDraft;
  if (!draft) return;
  const distance = Number($("calibLen").value);
  const unit = $("calibUnit").value;
  const pt = Math.hypot(draft.x2 - draft.x1, draft.y2 - draft.y1);
  if (!(distance > 0) || !Number.isFinite(distance)) {
    toast("Enter a length greater than zero.");
    return;
  }
  let feet = distance;
  if (unit === "in") feet = distance / 12;
  if (unit === "m") feet = distance * 3.280839895;
  const pointsPerFoot = pt / feet;
  const inchesPerFoot = pt / 72 / feet;
  pushUndo();
  state.calibration = {
    page: draft.page,
    x1: draft.x1,
    y1: draft.y1,
    x2: draft.x2,
    y2: draft.y2,
    distance,
    unit,
    pointsPerFoot,
    label: scaleLabel(inchesPerFoot),
  };
  state.calibStep = 0;
  state.calibDraft = null;
  syncInspector();
  drawCalib();
  scheduleSave();
  setStatus();
  toast(`Scale set to ${state.calibration.label}.`);
}

function cancelCalib() {
  state.calibStep = 0;
  state.calibDraft = null;
  syncInspector();
  drawCalib();
  setStatus();
}

function capturePointer(e) {
  try {
    viewport.setPointerCapture(e.pointerId);
  } catch (_err) {
    // The pointer can already be gone. Move and up listeners on window still run.
  }
}

function startPan(e) {
  state.drag = {
    type: "pan",
    x: e.clientX,
    y: e.clientY,
    panX: state.panX,
    panY: state.panY,
  };
  viewport.classList.add("panning");
  capturePointer(e);
}

function placementOrigin(p) {
  if (p.kind === "line") return { x1: p.x1, y1: p.y1, x2: p.x2, y2: p.y2 };
  return { x: p.x, y: p.y };
}

function snapPoint(pt, excludeId) {
  let best = null;
  let bestD = 14;
  for (const item of state.placements) {
    if (item.page !== state.pageIndex || item.id === excludeId) continue;
    const points = item.kind === "line" ? [[item.x1, item.y1], [item.x2, item.y2]] : item.kind === "legend" ? [] : [[item.x, item.y]];
    for (const [x, y] of points) {
      const dist = Math.hypot(pt.x - x, pt.y - y);
      if (dist < bestD) {
        bestD = dist;
        best = { x, y };
      }
    }
  }
  return best || pt;
}

function onSheet(pt, page) {
  return pt.x >= -80 && pt.y >= -80 && pt.x <= page.width + 80 && pt.y <= page.height + 80;
}

function lineClick(pt) {
  const page = currentPage();
  if (!page || !onSheet(pt, page)) return;
  const snapped = snapPoint(pt);
  if (!state.lineDraft) {
    state.lineDraft = { page: state.pageIndex, x1: snapped.x, y1: snapped.y, x2: snapped.x, y2: snapped.y, color: state.ink || "#141414" };
    renderWires();
    syncInspector();
    setStatus();
    return;
  }
  state.lineDraft.x2 = snapped.x;
  state.lineDraft.y2 = snapped.y;
  const length = Math.hypot(state.lineDraft.x2 - state.lineDraft.x1, state.lineDraft.y2 - state.lineDraft.y1);
  if (length < 4) {
    toast("That line is too short. Click a second point.");
    return;
  }
  pushUndo();
  const mark = {
    id: uid(),
    kind: "line",
    page: state.lineDraft.page,
    x1: state.lineDraft.x1,
    y1: state.lineDraft.y1,
    x2: state.lineDraft.x2,
    y2: state.lineDraft.y2,
    color: state.lineDraft.color,
  };
  state.placements.push(mark);
  state.selectedId = mark.id;
  state.lineDraft = null;
  renderMarks();
  syncInspector();
  scheduleSave();
  setStatus();
}

function placeLegend(pt) {
  const page = currentPage();
  const lay = library.legend;
  if (!page || !lay) {
    toast("The legend is not available. Restart the app and try again.");
    return;
  }
  if (!onSheet(pt, page)) return;
  let width = lay.width;
  let height = lay.height;
  const maxW = Math.max(120, page.width - 24);
  const maxH = Math.max(80, page.height - 24);
  if (width > maxW) {
    height *= maxW / width;
    width = maxW;
  }
  if (height > maxH) {
    width *= maxH / height;
    height = maxH;
  }
  const x = clamp(pt.x, 8, Math.max(8, page.width - width - 8));
  const y = clamp(pt.y, 8, Math.max(8, page.height - height - 8));
  pushUndo();
  const mark = { id: uid(), kind: "legend", page: state.pageIndex, x, y, width };
  state.placements.push(mark);
  state.selectedId = mark.id;
  state.tool = null;
  renderMarks();
  syncInspector();
  scheduleSave();
  setStatus();
  toast("Legend placed. Drag it where the crew can read it.");
}

function startMove(e, id) {
  let p = placement(id);
  if (!p) return;
  state.selectedId = id;
  let undoOnMove = true;
  if (e.altKey) {
    pushUndo();
    p = duplicatePlacement(p, 0, 0);
    state.selectedId = p.id;
    undoOnMove = false;
  }
  const pdf = clientToPdf(e.clientX, e.clientY);
  state.drag = {
    type: "move",
    id: p.id,
    startX: pdf.x,
    startY: pdf.y,
    origin: placementOrigin(p),
    moved: false,
    alt: e.altKey,
    undo: undoOnMove,
  };
  capturePointer(e);
  renderMarks();
  syncInspector();
  setStatus();
}

function startEnd(e, id, end) {
  state.selectedId = id;
  state.drag = { type: "end", id, end, undo: true, moved: false };
  capturePointer(e);
  renderMarks();
  syncInspector();
  setStatus();
}

function startRotate(e, id) {
  state.selectedId = id;
  state.drag = { type: "rotate", id, undo: true };
  capturePointer(e);
  renderMarks();
  syncInspector();
}

function onPointerDown(e) {
  if (!state.doc) return;
  if (e.button === 1 || e.button === 2 || state.space) {
    e.preventDefault();
    startPan(e);
    return;
  }
  if (e.button !== 0) return;
  const pt = clientToPdf(e.clientX, e.clientY);
  if (state.tool === "line") {
    e.preventDefault();
    lineClick(pt);
    return;
  }
  const end = e.target.closest(".wire-end");
  if (end) {
    e.preventDefault();
    startEnd(e, end.dataset.id, end.dataset.end);
    return;
  }
  const wire = e.target.closest(".wire");
  if (wire && wire.dataset.id) {
    e.preventDefault();
    startMove(e, wire.dataset.id);
    return;
  }
  const handle = e.target.closest(".handle");
  if (handle) {
    e.preventDefault();
    startRotate(e, handle.dataset.id);
    return;
  }
  const mark = e.target.closest(".mark");
  if (mark) {
    e.preventDefault();
    startMove(e, mark.dataset.id);
    return;
  }
  if (state.calibStep === 1 || state.calibStep === 2) {
    calibClick(pt);
    return;
  }
  if (state.calibStep === 3) return;
  if (state.tool === "legend") {
    placeLegend(pt);
    return;
  }
  if (state.armedId) {
    placeAt(e.clientX, e.clientY);
    return;
  }
  if (state.selectedId) {
    state.selectedId = null;
    renderMarks();
    syncInspector();
    setStatus();
  }
}

function onPointerMove(e) {
  const target = e.target;
  const overSheet = target === viewport || (target instanceof Node && viewport.contains(target));
  if (state.doc && (overSheet || state.drag)) {
    const pt = clientToPdf(e.clientX, e.clientY);
    $("statusMid").textContent = `${(pt.x / 72).toFixed(2)}" from left · ${(pt.y / 72).toFixed(2)}" from top`;
    if (state.calibStep === 2 && state.calibDraft && !state.drag) {
      state.calibDraft.x2 = pt.x;
      state.calibDraft.y2 = pt.y;
      drawCalib();
    }
    if (state.tool === "line" && state.lineDraft && !state.drag) {
      const snapped = snapPoint(pt);
      state.lineDraft.x2 = snapped.x;
      state.lineDraft.y2 = snapped.y;
      renderWires();
    }
  }
  const drag = state.drag;
  if (!drag) return;
  if (drag.type === "pan") {
    state.panX = drag.panX + (e.clientX - drag.x);
    state.panY = drag.panY + (e.clientY - drag.y);
    applyTransform();
    return;
  }
  if (drag.type === "end") {
    const p = placement(drag.id);
    if (!p || p.kind !== "line") return;
    if (drag.undo) {
      pushUndo();
      drag.undo = false;
    }
    const pdf = snapPoint(clientToPdf(e.clientX, e.clientY), p.id);
    if (drag.end === "1") {
      p.x1 = pdf.x;
      p.y1 = pdf.y;
    } else {
      p.x2 = pdf.x;
      p.y2 = pdf.y;
    }
    drag.moved = true;
    updateLine(p);
    return;
  }
  if (drag.type === "move") {
    const pdf = clientToPdf(e.clientX, e.clientY);
    const p = placement(drag.id);
    if (!p) return;
    const dx = pdf.x - drag.startX;
    const dy = pdf.y - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) < 0.6) return;
    if (drag.undo) {
      pushUndo();
      drag.undo = false;
    }
    drag.moved = true;
    if (p.kind === "line") {
      p.x1 = drag.origin.x1 + dx;
      p.y1 = drag.origin.y1 + dy;
      p.x2 = drag.origin.x2 + dx;
      p.y2 = drag.origin.y2 + dy;
    } else {
      p.x = drag.origin.x + dx;
      p.y = drag.origin.y + dy;
    }
    updateMark(p);
    return;
  }
  if (drag.type === "rotate") {
    const p = placement(drag.id);
    if (!p) return;
    if (drag.undo) {
      pushUndo();
      drag.undo = false;
    }
    const c = pdfToClient(p.x, p.y);
    const ang = Math.atan2(e.clientY - c.y, e.clientX - c.x);
    let deg = (ang * 180) / Math.PI - 90;
    if (e.shiftKey) deg = Math.round(deg / 15) * 15;
    p.rotation = normRot(deg);
    updateMark(p);
  }
}

function onPointerUp() {
  const drag = state.drag;
  if (!drag) return;
  if (drag.type === "move" && drag.alt && !drag.moved) {
    const p = placement(drag.id);
    if (p) {
      const shift = duplicateShift(p);
      if (p.kind === "line") {
        p.x1 += shift;
        p.y1 += shift;
        p.x2 += shift;
        p.y2 += shift;
      } else {
        p.x += shift;
        p.y += shift;
      }
      updateMark(p);
    }
  }
  const changed = drag.moved || drag.type === "rotate";
  state.drag = null;
  viewport.classList.remove("panning");
  if (changed) scheduleSave();
}

function setStatus() {
  let left = "No plan open";
  if (state.doc) {
    if (state.calibStep === 1) left = "Calibrate: click the first point of a known length";
    else if (state.calibStep === 2) left = "Calibrate: click the second point";
    else if (state.calibStep === 3) left = "Enter that length, then Apply";
    else if (state.tool === "line" && state.lineDraft) left = "Dashed line: click the next point. Esc cancels this segment.";
    else if (state.tool === "line") left = "Dashed line: click the first point. Esc puts the tool away.";
    else if (state.tool === "legend") left = "Click the sheet to drop the legend.";
    else if (state.armedId) {
      const sym = symbolsById[state.armedId];
      left = `Placing ${sym ? sym.name : "symbol"}. Click the plan. Esc cancels.`;
    } else if (selected() && selected().kind === "line") left = "Drag the line to move it. Drag an end to reshape it.";
    else if (selected() && selected().kind === "legend") left = "Drag the legend. The slider changes its width.";
    else if (selected()) left = "Drag to move. Drag the amber handle to rotate.";
    else left = "Pick a symbol, then click the plan.";
  }
  $("statusLeft").textContent = left;
  if (!state.doc) $("statusMid").textContent = "";
  if (!state.doc) {
    $("statusRight").textContent = "";
    return;
  }
  const here = state.placements.filter((item) => item.page === state.pageIndex).length;
  const scale = state.calibration ? state.calibration.label : "scale not set";
  $("statusRight").textContent = `${here} on this sheet · ${state.placements.length} total · ${scale}`;
}

async function openPdfBytes(buf, filename, { append = false } = {}) {
  setBusy(true, append ? "Adding sheets…" : "Opening plan…");
  try {
    const url = append ? "/api/append" : "/api/open?name=" + encodeURIComponent(filename);
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/pdf" },
      body: buf,
    });
    if (!res.ok) throw new Error(await readError(res));
    const info = await res.json();
    if (append) {
      const had = state.doc ? state.doc.pageCount : 0;
      state.doc = info;
      updatePager();
      scheduleSave();
      toast(`Added ${info.added || info.pageCount - had} sheet${info.added === 1 ? "" : "s"}.`);
      return;
    }
    const previousMarks = state.placements.length;
    state.doc = info;
    state.placements = [];
    state.selectedId = null;
    state.armedId = null;
    state.tool = null;
    state.lineDraft = null;
    state.calibration = null;
    state.calibStep = 0;
    state.calibDraft = null;
    state.undo = [];
    state.redo = [];
    state.imageKey = "";
    state.imageToken += 1;
    showWorkspace();
    showPage(0, { fit: true });
    renderPalette();
    const pending = state.pendingProject;
    state.pendingProject = null;
    if (pending) {
      applyProject(pending);
      toast("Loaded the marks file onto this plan.");
    } else {
      const raw = localStorage.getItem("planmarks:v1:" + info.id);
      if (raw) {
        try {
          const saved = JSON.parse(raw);
          const hasMarks = (saved.placements || []).length || saved.calibration;
          if (hasMarks) {
            applyProject(saved, { quiet: true });
            toast("Restored marks saved in this browser for this PDF.");
          }
        } catch (_err) {
          /* ignore a damaged autosave */
        }
      } else if (previousMarks) {
        toast("Opened a new plan. Marks on the previous file stay in this browser.");
      }
    }
    syncInspector();
    setStatus();
  } catch (err) {
    toast(err.message);
  } finally {
    setBusy(false);
  }
}

async function openFile(file, { append = false } = {}) {
  if (!file) return;
  const buf = await file.arrayBuffer();
  await openPdfBytes(buf, file.name, { append });
}

async function addLegend() {
  if (!state.doc) return;
  setBusy(true, "Adding legend…");
  try {
    const res = await fetch("/api/legend", { method: "POST" });
    if (!res.ok) throw new Error(await readError(res));
    const info = await res.json();
    state.doc = info;
    const start = Math.max(0, info.pageCount - (info.added || 1));
    showPage(start, { fit: true });
    scheduleSave();
    toast("Added a legend sheet.");
  } catch (err) {
    toast(err.message);
  } finally {
    setBusy(false);
  }
}

async function openSample() {
  setBusy(true, "Opening sample…");
  try {
    const res = await fetch("/api/sample.pdf");
    if (!res.ok) throw new Error(await readError(res));
    const buf = await res.arrayBuffer();
    setBusy(false);
    await openPdfBytes(buf, "sample-plan.pdf");
  } catch (err) {
    setBusy(false);
    toast(err.message);
  }
}

function saveProject() {
  if (!state.doc) return;
  const base = state.doc.filename.replace(/\.pdf$/i, "") || "plan";
  const blob = new Blob([JSON.stringify(projectData(), null, 2)], { type: "application/json" });
  download(blob, base + "-marks.json");
}

function loadProjectFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      applyProject(JSON.parse(String(reader.result)));
    } catch (_err) {
      toast("Could not read that project file.");
    }
  };
  reader.readAsText(file);
}

async function exportPdf() {
  if (!state.doc) return;
  const btn = $("exportBtn");
  btn.disabled = true;
  btn.textContent = "Exporting…";
  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ placements: state.placements }),
    });
    if (!res.ok) throw new Error(await readError(res));
    const blob = await res.blob();
    let name = state.doc.filename.replace(/\.pdf$/i, "") + "-marked.pdf";
    const disp = res.headers.get("Content-Disposition") || "";
    const star = /filename\*=UTF-8''([^;]+)/.exec(disp);
    if (star) name = decodeURIComponent(star[1]);
    download(blob, name);
    if (!state.placements.length) toast("No symbols yet. Exported the plan unchanged.");
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = !state.doc;
    btn.textContent = "Export PDF";
  }
}

function isTyping() {
  const tag = document.activeElement && document.activeElement.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function onKeyDown(e) {
  if (e.key === "Escape" && isTyping()) {
    document.activeElement.blur();
    return;
  }
  if (isTyping()) return;
  const meta = e.ctrlKey || e.metaKey;
  if (e.code === "Space") {
    state.space = true;
    e.preventDefault();
    return;
  }
  if (e.key === "Escape") {
    if (state.calibStep) cancelCalib();
    else if (state.lineDraft) {
      state.lineDraft = null;
      renderWires();
      syncInspector();
      setStatus();
    } else if (state.tool) setTool(state.tool);
    else if (state.armedId) toggleArm(state.armedId);
    else if (state.selectedId) {
      state.selectedId = null;
      renderMarks();
      syncInspector();
      setStatus();
    }
    return;
  }
  if (meta && e.key.toLowerCase() === "z") {
    e.preventDefault();
    if (e.shiftKey) redo();
    else undo();
    return;
  }
  if (meta && e.key.toLowerCase() === "y") {
    e.preventDefault();
    redo();
    return;
  }
  if (meta && e.key.toLowerCase() === "d") {
    e.preventDefault();
    duplicateSelected();
    return;
  }
  if (meta && e.key.toLowerCase() === "s") {
    e.preventDefault();
    saveProject();
    return;
  }
  if (meta && e.key.toLowerCase() === "o") {
    e.preventDefault();
    $("filePdf").click();
    return;
  }
  if (meta && e.key === "0") {
    e.preventDefault();
    fitView();
    return;
  }
  if (meta && e.key === "1") {
    e.preventDefault();
    actualSize();
    return;
  }
  if (meta && (e.key === "=" || e.key === "+")) {
    e.preventDefault();
    const vr = viewport.getBoundingClientRect();
    zoomAt(vr.left + vr.width / 2, vr.top + vr.height / 2, 1.15);
    return;
  }
  if (meta && e.key === "-") {
    e.preventDefault();
    const vr = viewport.getBoundingClientRect();
    zoomAt(vr.left + vr.width / 2, vr.top + vr.height / 2, 1 / 1.15);
    return;
  }
  if (e.key === "?" || e.key === "F1") {
    e.preventDefault();
    $("help").showModal();
    return;
  }
  if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    deleteSelected();
    return;
  }
  if (e.key === "PageUp") {
    goToPage(state.pageIndex - 1);
    return;
  }
  if (e.key === "PageDown") {
    goToPage(state.pageIndex + 1);
    return;
  }
  if (!meta && (e.key === "r" || e.key === "R")) {
    const p = selected();
    if (!isSymbol(p)) return;
    if (!e.repeat) pushUndo();
    p.rotation = normRot(p.rotation + (e.shiftKey ? -15 : 15));
    updateMark(p);
    scheduleSave();
    return;
  }
  const nudge = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
  if (!meta && nudge[e.key]) {
    const p = selected();
    if (!p) return;
    e.preventDefault();
    if (!e.repeat) pushUndo();
    const step = e.shiftKey ? 8 : 1;
    const dx = nudge[e.key][0] * step;
    const dy = nudge[e.key][1] * step;
    if (p.kind === "line") {
      p.x1 += dx;
      p.y1 += dy;
      p.x2 += dx;
      p.y2 += dy;
    } else {
      p.x += dx;
      p.y += dy;
    }
    updateMark(p);
    scheduleSave();
  }
}

function onKeyUp(e) {
  if (e.code === "Space") {
    state.space = false;
    if (!state.drag) viewport.classList.remove("panning");
  }
}

function bind() {
  $("openBtn").addEventListener("click", () => $("filePdf").click());
  $("emptyOpen").addEventListener("click", () => $("filePdf").click());
  $("sampleBtn").addEventListener("click", () => openSample());
  $("addBtn").addEventListener("click", () => $("fileAdd").click());
  $("legendBtn").addEventListener("click", () => addLegend());
  $("lineBtn").addEventListener("click", () => setTool("line"));
  $("dropLegendBtn").addEventListener("click", () => setTool("legend"));
  $("exportBtn").addEventListener("click", () => exportPdf());
  $("saveBtn").addEventListener("click", () => saveProject());
  $("loadBtn").addEventListener("click", () => $("fileProj").click());
  $("helpBtn").addEventListener("click", () => $("help").showModal());
  $("filePdf").addEventListener("change", () => {
    const file = $("filePdf").files[0];
    $("filePdf").value = "";
    if (file) openFile(file);
  });
  $("fileAdd").addEventListener("change", () => {
    const file = $("fileAdd").files[0];
    $("fileAdd").value = "";
    if (file) openFile(file, { append: true });
  });
  $("fileProj").addEventListener("change", () => {
    const file = $("fileProj").files[0];
    $("fileProj").value = "";
    if (file) loadProjectFile(file);
  });
  $("prevPage").addEventListener("click", () => goToPage(state.pageIndex - 1));
  $("nextPage").addEventListener("click", () => goToPage(state.pageIndex + 1));
  $("pageSelect").addEventListener("change", () => goToPage(Number($("pageSelect").value)));
  $("zoomIn").addEventListener("click", () => {
    const vr = viewport.getBoundingClientRect();
    zoomAt(vr.left + vr.width / 2, vr.top + vr.height / 2, 1.15);
  });
  $("zoomOut").addEventListener("click", () => {
    const vr = viewport.getBoundingClientRect();
    zoomAt(vr.left + vr.width / 2, vr.top + vr.height / 2, 1 / 1.15);
  });
  $("zoomLabel").addEventListener("click", () => actualSize());
  $("fitBtn").addEventListener("click", () => fitView());
  $("filter").addEventListener("input", () => renderPalette());
  $("sizeRange").addEventListener("pointerdown", () => {
    sizeUndoArmed = true;
  });
  $("sizeRange").addEventListener("input", () => {
    setSize(Number($("sizeRange").value), { undo: sizeUndoArmed });
    sizeUndoArmed = false;
  });
  for (const btn of document.querySelectorAll(".presets [data-size]")) {
    btn.addEventListener("click", () => setSize(Number(btn.dataset.size), { undo: true }));
  }
  $("sizeOneFoot").addEventListener("click", () => {
    if (!state.calibration) return;
    const raw = state.calibration.pointsPerFoot;
    const pt = clamp(raw, 10, 160);
    if (Math.abs(pt - raw) > 0.5) toast("One foot is outside the slider range, so the size was limited.");
    setSize(pt, { undo: true });
  });
  $("calibBtn").addEventListener("click", () => {
    if (state.calibStep) cancelCalib();
    else {
      state.armedId = null;
      state.tool = null;
      state.lineDraft = null;
      state.calibStep = 1;
      state.calibDraft = null;
      renderPalette();
      syncInspector();
      renderMarks();
      setStatus();
    }
  });
  $("calibClear").addEventListener("click", () => {
    pushUndo();
    state.calibration = null;
    syncInspector();
    drawCalib();
    scheduleSave();
    setStatus();
  });
  $("calibApply").addEventListener("click", () => applyCalibration());
  $("calibLen").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      applyCalibration();
    }
  });
  $("symbolSelect").addEventListener("change", () => {
    const p = selected();
    if (!isSymbol(p)) return;
    pushUndo();
    p.symbolId = $("symbolSelect").value;
    if (!state.ink) p.color = (symbolsById[p.symbolId] && symbolsById[p.symbolId].defaultColor) || "#141414";
    renderMarks();
    syncInspector();
    scheduleSave();
  });
  $("rotMinus").addEventListener("click", () => bumpRotation(-15));
  $("rotPlus").addEventListener("click", () => bumpRotation(15));
  $("rot90").addEventListener("click", () => bumpRotation(90));
  $("rot0").addEventListener("click", () => {
    const p = selected();
    if (!isSymbol(p)) return;
    pushUndo();
    p.rotation = 0;
    updateMark(p);
    scheduleSave();
  });
  $("rotInput").addEventListener("change", () => {
    const p = selected();
    if (!isSymbol(p)) return;
    pushUndo();
    p.rotation = normRot($("rotInput").value);
    updateMark(p);
    scheduleSave();
  });
  $("dupBtn").addEventListener("click", () => duplicateSelected());
  $("delBtn").addEventListener("click", () => deleteSelected());

  viewport.addEventListener("pointerdown", onPointerDown);
  viewport.addEventListener("contextmenu", (e) => e.preventDefault());
  viewport.addEventListener("wheel", (e) => {
    if (!state.doc) return;
    e.preventDefault();
    const scale = e.deltaMode === 1 ? 0.04 : 0.0015;
    zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * scale));
  }, { passive: false });
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp);
  window.addEventListener("pointercancel", onPointerUp);
  window.addEventListener("keydown", onKeyDown);
  window.addEventListener("keyup", onKeyUp);
  window.addEventListener("blur", () => {
    state.space = false;
    viewport.classList.remove("panning");
  });
  window.addEventListener("dragover", (e) => {
    if (![...e.dataTransfer.types].includes("Files")) return;
    e.preventDefault();
    document.body.classList.add("dropping");
  });
  window.addEventListener("dragleave", (e) => {
    if (e.target === document.body || e.target === document.documentElement) {
      document.body.classList.remove("dropping");
    }
  });
  window.addEventListener("drop", (e) => {
    if (![...e.dataTransfer.types].includes("Files")) return;
    e.preventDefault();
    document.body.classList.remove("dropping");
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (!file) return;
    const name = file.name.toLowerCase();
    if (name.endsWith(".json")) loadProjectFile(file);
    else openFile(file);
  });
  $("help").addEventListener("click", (e) => {
    if (e.target === $("help")) $("help").close();
  });
}

async function init() {
  const res = await fetch("/api/symbols");
  if (!res.ok) {
    toast("Could not load the symbol library.");
    return;
  }
  library = await res.json();
  symbolsById = Object.fromEntries(library.symbols.map((sym) => [sym.id, sym]));
  buildSymbolSelect();
  buildColors();
  renderPalette();
  syncInspector();
  setStatus();
  bind();
}

init();
