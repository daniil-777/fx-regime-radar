"""The regime orb: an ambient three.js particle sphere that physically expresses the models.

Rendered via `st.iframe` (the successor of `streamlit.components.v1.html`) — same sandboxed iframe.

Regime sets colour and motion, change risk sets jitter, the siren fires a decaying pulse. It is a
DISPLAY of the parquet numbers — it computes nothing. One hero orb for the selected pair (one WebGL
context, no layout shift in the card grid; the cards stay pure HTML). PRESETS below mirror the JS
object of the same name inside the snippet — keep them in sync. Discipline: <= 1 000 particles,
requestAnimationFrame paused when the tab is hidden, prefers-reduced-motion collapses motion to a
gentle drift, WebGL failure falls back to the flat regime dot with zero layout shift, no sound,
no faces. Our snippet is ~7 KB; three.js r128 comes from cdnjs (~150 KB gzipped, cached).
"""

from __future__ import annotations

import html
import json

import streamlit as st

REGIME_COLORS = {"calm": "#34D399", "trend": "#60A5FA", "chop": "#FBBF24", "crisis": "#F87171"}

# Four state presets — the Python mirror of the JS PRESETS object (keep in sync).
PRESETS = {
    "calm": {"spin": 0.08, "jitter": 0.010, "chaos": 0.0, "breathe": 0.010},
    "trend": {"spin": 0.55, "jitter": 0.020, "chaos": 0.0, "breathe": 0.015},
    "chop": {"spin": 0.10, "jitter": 0.120, "chaos": 0.3, "breathe": 0.030},
    "crisis": {"spin": 0.90, "jitter": 0.160, "chaos": 1.0, "breathe": 0.060},
}
PARTICLES = 900
THREE_CDN = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"


def orb_html(
    regime: str, change_risk: float, anomaly_pct: float, size: int = 160, pair: str = ""
) -> str:
    """Self-contained HTML for the orb (used by the component and by the screenshot tool)."""
    regime = regime if regime in PRESETS else "calm"
    color = REGIME_COLORS[regime]
    cfg = {
        "regime": regime,
        "color": color,
        "risk": float(max(0.0, min(1.0, change_risk or 0.0))),
        "pulse": bool((anomaly_pct or 0.0) > 98.0),
        "size": int(size),
        "particles": PARTICLES,
        "presets": PRESETS,
        "pair": pair,
    }
    caption = f"{regime} regime · change risk {cfg['risk']:.0%}" + (
        " · siren pulse" if cfg["pulse"] else ""
    )
    return f"""
<style>html,body{{margin:0;padding:0;overflow:hidden;background:transparent}}</style>
<div id="orb-wrap" style="width:100%;max-width:{size}px;aspect-ratio:1/1;margin:0 auto;position:relative;font-family:Inter,-apple-system,sans-serif;">
  <div id="orb-dot" title="{html.escape(caption)}" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;">
    <div style="width:34%;height:34%;border-radius:50%;background:{color}33;border:2px solid {color};box-shadow:0 0 24px {color}55;"></div>
  </div>
  <canvas id="orb" style="position:absolute;inset:0;display:none;" title="{html.escape(caption)}"></canvas>
  <div id="orb-cap" style="position:absolute;left:0;right:0;bottom:-18px;text-align:center;font-size:10px;color:#8A94A6;opacity:0;transition:opacity .2s;pointer-events:none;">what am I looking at? {html.escape(caption)} — colour and motion follow the regime, jitter follows change risk, a pulse follows the siren</div>
</div>
<script src="{THREE_CDN}"></script>
<script>
(function() {{
  const CFG = {json.dumps(cfg)};
  // Four state presets — must mirror app/orb.py PRESETS
  const PRESETS = CFG.presets;
  const wrap = document.getElementById('orb-wrap'), dot = document.getElementById('orb-dot'),
        canvas = document.getElementById('orb'), cap = document.getElementById('orb-cap');
  wrap.addEventListener('mouseenter', () => cap.style.opacity = 1);
  wrap.addEventListener('mouseleave', () => cap.style.opacity = 0);
  wrap.addEventListener('touchstart', () => {{ cap.style.opacity = 1; setTimeout(() => cap.style.opacity = 0, 2500); }}, {{passive: true}});
  const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let renderer;
  try {{
    if (!window.THREE) throw new Error('three.js not loaded');
    renderer = new THREE.WebGLRenderer({{canvas: canvas, alpha: true, antialias: true, powerPreference: 'low-power'}});
  }} catch (e) {{ window.__orbFallback = String(e); return; }}  // flat dot stays: zero layout shift
  // Fit the drawing buffer to the space the column actually gives us (the wrap is a responsive
  // square, max CFG.size px) — a fixed-size canvas in a narrow column was clipped to a slice.
  const fit = () => Math.max(24, Math.min(CFG.size, Math.round(wrap.clientWidth || CFG.size)));
  let size = fit();
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(size, size, false);
  if (window.ResizeObserver) {{
    new ResizeObserver(() => {{ const s = fit(); if (s !== size) {{ size = s; renderer.setSize(s, s, false); }} }}).observe(wrap);
  }}
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100); camera.position.z = 3.2;
  const N = Math.min(CFG.particles, 1000), base = new Float32Array(N * 3), pos = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {{  // Fibonacci sphere: evenly spread points on a unit sphere
    const y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = i * 2.399963;
    base[3*i] = Math.cos(th) * r; base[3*i+1] = y; base[3*i+2] = Math.sin(th) * r;
  }}
  pos.set(base);
  const geo = new THREE.BufferGeometry(); geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({{color: CFG.color, size: 0.035, transparent: true, opacity: 0.9, sizeAttenuation: true}});
  const points = new THREE.Points(geo, mat); scene.add(points);
  const P = PRESETS[CFG.regime];
  const jitter = P.jitter * (1 + CFG.risk);            // change risk multiplies jitter
  let pulse = CFG.pulse ? 1.0 : 0.0;                    // siren: decaying pulse
  const spin = reduced ? 0.03 : P.spin, jit = reduced ? 0.0 : jitter, chaos = reduced ? 0.0 : P.chaos;
  dot.style.display = 'none'; canvas.style.display = 'block';
  let t = 0, running = true, frames = 0, busy = 0, last = performance.now();
  function frame(now) {{
    if (!running) return;
    const t0 = performance.now(); t += 0.016;
    const breathe = 1 + P.breathe * Math.sin(t * 1.5) + pulse * 0.35;
    for (let i = 0; i < N; i++) {{
      const k = 3*i, n = chaos * Math.sin(t * 3 + i * 0.7) * 0.15;
      pos[k]   = base[k]   * breathe + (Math.random() - 0.5) * jit + n * base[k+1];
      pos[k+1] = base[k+1] * breathe + (Math.random() - 0.5) * jit;
      pos[k+2] = base[k+2] * breathe + (Math.random() - 0.5) * jit - n * base[k];
    }}
    geo.attributes.position.needsUpdate = true;
    points.rotation.y += spin * 0.016; points.rotation.x = 0.35 + 0.05 * Math.sin(t * 0.7);
    mat.opacity = 0.75 + 0.25 * pulse; pulse *= 0.985;   // pulse decays
    renderer.render(scene, camera);
    busy += performance.now() - t0; frames++;
    if (now - last > 2000) {{ window.__orbMsPerFrame = busy / frames; busy = 0; frames = 0; last = now; }}
    requestAnimationFrame(frame);
  }}
  document.addEventListener('visibilitychange', () => {{
    if (document.hidden) {{ running = false; }} else if (!running) {{ running = true; requestAnimationFrame(frame); }}
  }});
  window.__orbReady = true; window.__orbReduced = reduced;
  requestAnimationFrame(frame);
}})();
</script>
"""


def render(
    regime: str, change_risk: float, anomaly_pct: float, size: int = 160, pair: str = ""
) -> None:
    """Embed the orb in the Streamlit page (fixed height: no layout shift whatever happens inside)."""
    html_doc = orb_html(regime, change_risk, anomaly_pct, size, pair)
    if hasattr(st, "iframe"):  # Streamlit >= 1.61: the successor of components.v1.html
        st.iframe(
            html_doc, width="stretch", height=size + 24
        )  # fills the column, canvas fits itself
    else:  # older Streamlit
        import streamlit.components.v1 as components

        components.html(html_doc, height=size + 24)
