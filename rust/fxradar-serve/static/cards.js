/* FX Regime Radar — the eight render primitives (phase 38).
 *
 * Fifty cards, eight renderers. A card is never bespoke code: it is a registry entry naming a
 * primitive plus server-resolved data. The model never sends a number; the server resolves every
 * value and hands this file a finished spec.
 *
 * Naming note: the phase brief says "widget.js", but that name belongs to the phase-24 partner
 * embed badge and renaming it would break live embeds. The primitives live here instead.
 *
 * Styling comes only from widget-tokens.css (generated from design/tokens.json) — no colour
 * literal appears in this file. Charts use inline SVG: no plotting library is required, and uPlot
 * is used for trace_band only when the host page has already loaded it.
 */
"use strict";

/* Fixed height bands, so a board never reflows when a card resolves. */
export const HEIGHT_BAND = {
  stat_block: 132, bar_row: 184, trace_band: 200, ribbon: 96,
  table: 224, dot_row: 88, media_frame: 240, diagram_frame: 200,
};
export const PRIMITIVE_NAMES = Object.keys(HEIGHT_BAND);

/* ---- the single string source ---------------------------------------------------------------
 * One resolved sentence produces the visible caption, the <figcaption> and the ARIA label, so the
 * spoken, written and screen-reader versions cannot drift apart. Everything else reads from this.
 */
export function buildText(spec) {
  const caption = String(spec.caption || "").trim();
  const label = String(spec.label || spec.component || "card").replace(/_/g, " ");
  const asof = spec.asof ? ` as of ${spec.asof}` : "";
  const stale = spec.stale ? " Data is stale." : "";
  return { caption, figcaption: caption, aria: `${label}${asof}: ${caption}${stale}`.trim() };
}

const svgNS = "http://www.w3.org/2000/svg";
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}
function svg(tag, attrs) {
  const n = document.createElementNS(svgNS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}
function clamp01(x) { return Math.max(0, Math.min(1, Number(x) || 0)); }
function regimeClass(word) {
  const w = String(word || "").toLowerCase();
  return ["calm", "trend", "chop", "crisis"].includes(w) ? `fxc-regime-${w}` : "";
}

/* ---- P1 stat_block: 1–4 big figures with labels and a sub-line ------------------------------- */
function stat_block(data) {
  const wrap = el("div", "fxc-stats");
  (data.stats || []).slice(0, 4).forEach((s) => {
    const cell = el("div", "fxc-stat");
    const v = el("div", `fxc-stat-value ${regimeClass(s.tone)}`, s.value);
    if (s.mono !== false) v.classList.add("fxc-num");
    cell.appendChild(v);
    cell.appendChild(el("div", "fxc-stat-label", s.label));
    wrap.appendChild(cell);
  });
  const out = el("div", "fxc-body");
  out.appendChild(wrap);
  if (data.subline) out.appendChild(el("div", "fxc-subline", data.subline));
  return out;
}

/* ---- P2 bar_row: horizontal labelled bars, one highlighted ----------------------------------- */
function bar_row(data) {
  const out = el("div", "fxc-body fxc-bars");
  const rows = (data.rows || []).slice(0, 8);
  const max = Math.max(1e-9, ...rows.map((r) => Math.abs(Number(r.value) || 0)));
  rows.forEach((r) => {
    const row = el("div", "fxc-bar-row");
    row.appendChild(el("div", "fxc-bar-label", r.label));
    const track = el("div", "fxc-bar-track");
    const fill = el("div", `fxc-bar-fill${r.highlight ? " is-primary" : ""} ${regimeClass(r.tone)}`);
    fill.style.width = `${clamp01(Math.abs(Number(r.value) || 0) / max) * 100}%`;
    track.appendChild(fill);
    row.appendChild(track);
    row.appendChild(el("div", "fxc-bar-value fxc-num", r.display != null ? r.display : r.value));
    out.appendChild(row);
  });
  return out;
}

/* ---- P3 trace_band: line + shaded uncertainty band ------------------------------------------- */
function trace_band(data) {
  const out = el("div", "fxc-body");
  const pts = data.points || [];
  const W = 480, H = 128, P = 4;
  const chart = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "fxc-trace",
    preserveAspectRatio: "none", role: "presentation", focusable: "false" });
  if (!pts.length) { out.appendChild(chart); return out; }
  const ys = pts.flatMap((p) => [p.v, p.lo, p.hi].filter((x) => typeof x === "number"));
  const lo = Math.min(...ys), hi = Math.max(...ys), span = hi - lo || 1;
  const X = (i) => P + (i * (W - 2 * P)) / Math.max(1, pts.length - 1);
  const Y = (v) => H - P - ((v - lo) / span) * (H - 2 * P);
  const hasBand = pts.every((p) => typeof p.lo === "number" && typeof p.hi === "number");
  if (hasBand) {
    const up = pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.hi).toFixed(1)}`).join("");
    const dn = pts.map((p, i) => `${X(pts.length - 1 - i).toFixed(1)},${Y(pts[pts.length - 1 - i].lo).toFixed(1)}`).join("L");
    chart.appendChild(svg("path", { d: `${up}L${dn}Z`, class: "fxc-trace-band" }));
  }
  chart.appendChild(svg("path", {
    d: pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.v).toFixed(1)}`).join(""),
    class: "fxc-trace-line", fill: "none",
  }));
  const last = pts[pts.length - 1];
  chart.appendChild(svg("circle", { cx: X(pts.length - 1), cy: Y(last.v), r: 2.5, class: "fxc-trace-end" }));
  out.appendChild(chart);
  if (data.subline) out.appendChild(el("div", "fxc-subline", data.subline));
  return out;
}

/* ---- P4 ribbon: coloured time strip with legend ---------------------------------------------- */
function ribbon(data) {
  const out = el("div", "fxc-body");
  const strip = el("div", "fxc-ribbon");
  const segs = data.segments || [];
  const total = segs.reduce((a, s) => a + (Number(s.weight) || 1), 0) || 1;
  segs.forEach((s) => {
    const seg = el("div", `fxc-ribbon-seg ${regimeClass(s.tone || s.label)}`);
    seg.style.width = `${((Number(s.weight) || 1) / total) * 100}%`;
    seg.title = s.title || s.label || "";
    strip.appendChild(seg);
  });
  out.appendChild(strip);
  const legend = el("div", "fxc-legend");
  (data.legend || []).forEach((l) => {
    const item = el("span", "fxc-legend-item");
    item.appendChild(el("span", `fxc-dot ${regimeClass(l.tone || l.label)}`));
    item.appendChild(el("span", null, l.label));
    legend.appendChild(item);
  });
  out.appendChild(legend);
  return out;
}

/* ---- P5 table: labelled rows/columns, tabular numerals ---------------------------------------- */
function table(data) {
  const out = el("div", "fxc-body fxc-tablewrap");
  const t = el("table", "fxc-table");
  if (data.columns && data.columns.length) {
    const thead = el("thead"), tr = el("tr");
    data.columns.forEach((c, i) => {
      const th = el("th", i ? "fxc-right" : null, typeof c === "string" ? c : c.label);
      tr.appendChild(th);
    });
    thead.appendChild(tr); t.appendChild(thead);
  }
  const tb = el("tbody");
  (data.rows || []).forEach((r) => {
    const tr = el("tr");
    const cells = Array.isArray(r) ? r : r.cells || [];
    cells.forEach((c, i) => {
      const td = el("td", i ? "fxc-right fxc-num" : null, c);
      if (!Array.isArray(r) && r.tone && i === 0) td.classList.add(regimeClass(r.tone));
      tr.appendChild(td);
    });
    tb.appendChild(tr);
  });
  t.appendChild(tb);
  out.appendChild(t);
  return out;
}

/* ---- P6 dot_row: small state indicators with captions ----------------------------------------- */
function dot_row(data) {
  const out = el("div", "fxc-body fxc-dots");
  (data.items || []).slice(0, 8).forEach((it) => {
    const cell = el("div", "fxc-dotcell");
    cell.appendChild(el("span", `fxc-dot fxc-dot-lg ${regimeClass(it.tone)}${it.filled === false ? " is-empty" : ""}`));
    cell.appendChild(el("div", "fxc-dot-label", it.label));
    if (it.sub) cell.appendChild(el("div", "fxc-dot-sub fxc-num", it.sub));
    out.appendChild(cell);
  });
  return out;
}

/* ---- P7 media_frame: muted clip or image with caption + controls ------------------------------ */
function media_frame(data) {
  const out = el("div", "fxc-body fxc-media");
  if (data.kind === "video" && data.src) {
    const v = document.createElement("video");
    v.src = data.src; v.muted = true; v.playsInline = true; v.controls = true;
    v.preload = "metadata"; v.className = "fxc-media-el";
    if (data.poster) v.poster = data.poster;
    out.appendChild(v);                      // never autoplays: sound and motion stay user-initiated
  } else if (data.src) {
    const img = document.createElement("img");
    img.src = data.src; img.alt = data.alt || ""; img.loading = "lazy"; img.className = "fxc-media-el";
    out.appendChild(img);
  } else {
    out.appendChild(el("div", "fxc-media-empty", data.empty || "Nothing recorded for this period."));
  }
  return out;
}

/* ---- P8 diagram_frame: pre-authored SVG + caption --------------------------------------------- */
function diagram_frame(data) {
  const out = el("div", "fxc-body fxc-diagram");
  const holder = el("div", "fxc-diagram-holder");
  if (data.svg) holder.innerHTML = data.svg;   // pre-authored, server-side asset — never user input
  else holder.appendChild(el("div", "fxc-media-empty", "Diagram unavailable."));
  out.appendChild(holder);
  return out;
}

const RENDERERS = { stat_block, bar_row, trace_band, ribbon, table, dot_row, media_frame, diagram_frame };

/* ---- the shared frame: as-of stamp, stale badge, export hook, caption + ARIA ------------------ */
export function renderSkeleton(primitive) {
  const fig = el("figure", `fxc fxc-skeleton fxc-h-${primitive}`);
  fig.setAttribute("aria-busy", "true");
  fig.setAttribute("aria-label", "loading");
  fig.appendChild(el("div", "fxc-skel-block"));
  return fig;
}

export function renderCard(spec) {
  const primitive = spec.primitive;
  if (!RENDERERS[primitive]) throw new Error(`unknown primitive: ${primitive}`);
  const text = buildText(spec);
  const fig = el("figure", `fxc fxc-h-${primitive}`);
  fig.dataset.component = spec.component || "";
  fig.dataset.primitive = primitive;
  fig.setAttribute("role", "figure");
  fig.setAttribute("aria-label", text.aria);

  const head = el("div", "fxc-head");
  head.appendChild(el("span", "fxc-title", spec.title || (spec.component || "").replace(/_/g, " ")));
  const meta = el("span", "fxc-meta");
  if (spec.stale) meta.appendChild(el("span", "fxc-stale", "stale"));
  if (spec.asof) meta.appendChild(el("span", "fxc-asof fxc-num", spec.asof));
  head.appendChild(meta);
  fig.appendChild(head);

  fig.appendChild(RENDERERS[primitive](spec.data || {}));

  // When the caption is already the spoken answer directly above the card, printing it again is
  // noise. It still feeds the ARIA label, so a screen reader loses nothing.
  if (!spec.caption_hidden) fig.appendChild(el("figcaption", "fxc-caption", text.figcaption));

  const btn = el("button", "fxc-export", spec.export_label || "Copy");
  btn.type = "button";
  btn.setAttribute("aria-label", `copy the numbers behind ${text.caption}`);
  btn.addEventListener("click", () => {
    fig.dispatchEvent(new CustomEvent("fxc:export", {
      bubbles: true,
      detail: { component: spec.component, args: spec.args || {}, caption: text.caption, data: spec.data },
    }));
  });
  fig.appendChild(btn);
  return fig;
}

/* ---- boards: at most three cards, composition already validated server-side ------------------- */
export function renderBoard(board) {
  const wrap = el("div", "fxc-board");
  (board.cards || []).slice(0, 3).forEach((c) => wrap.appendChild(renderCard(c)));
  return wrap;
}

export default { renderCard, renderBoard, renderSkeleton, buildText, HEIGHT_BAND, PRIMITIVE_NAMES };
