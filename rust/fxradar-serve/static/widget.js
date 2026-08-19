/* FX Regime Radar badge widget (phase 24).
 * Embed:  <script src="https://HOST/widget.js?partner=yourname" data-pair="EURUSD" async></script>
 * Fetches /api/regimes/{pair} from the script's own origin and renders a small badge:
 * regime dot + regime WORD + "siren p<anomaly_pct>" + disclaimer line. No tracking beyond the
 * optional ?partner= tag, which is echoed on the fetch for attribution logging. Vanilla JS, no deps.
 */
(function () {
  "use strict";
  var script = document.currentScript;
  if (!script) { return; }
  var pair = (script.getAttribute("data-pair") || "EURUSD").toUpperCase();
  var src = script.src || "";
  var origin = src.indexOf("://") > 0 ? src.split("/").slice(0, 3).join("/") : "";
  var partner = "";
  var qi = src.indexOf("?");
  if (qi > 0) {
    src.slice(qi + 1).split("&").forEach(function (kv) {
      var p = kv.split("=");
      if (p[0] === "partner") { partner = decodeURIComponent(p[1] || ""); }
    });
  }
  var COLORS = { calm: "#3ECF8E", trend: "#4DA3FF", chop: "#F5B942", crisis: "#FF5C5C" };
  var BG = "#151D2E", TEXT = "#E8ECF4", MUTED = "#9AA6B8", LINE = "rgba(255,255,255,.08)";
  var MONO = "'IBM Plex Mono', 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace";

  var root = document.createElement("div");
  root.setAttribute("data-fxradar-widget", pair);
  root.style.cssText = "display:inline-flex;flex-direction:column;gap:4px;padding:10px 14px;" +
    "border-radius:12px;background:" + BG + ";color:" + TEXT + ";border:1px solid " + LINE +
    ";font-family:" + MONO + ";font-size:13px;line-height:1.35;font-feature-settings:'tnum';" +
    "min-width:220px;box-sizing:border-box;";
  root.textContent = "FX Regime Radar · " + pair + " · loading…";
  script.parentNode.insertBefore(root, script.nextSibling);

  function render(d) {
    var regime = String(d.regime || "unknown").toLowerCase();
    var color = COLORS[regime] || MUTED;
    var siren = (d.anomaly_pct === null || d.anomaly_pct === undefined) ? "n/a" : "p" + Math.round(Number(d.anomaly_pct));
    var risk = (d.change_risk_5d === null || d.change_risk_5d === undefined) ? "" : " · change risk 5d " + (Number(d.change_risk_5d) * 100).toFixed(1) + "%";
    root.textContent = "";
    var top = document.createElement("div");
    top.style.cssText = "display:flex;align-items:center;gap:8px;";
    var dot = document.createElement("span");
    dot.setAttribute("aria-hidden", "true");
    dot.style.cssText = "display:inline-block;width:10px;height:10px;border-radius:50%;background:" + color + ";box-shadow:0 0 0 3px " + color + "33;";
    var word = document.createElement("span");
    word.style.cssText = "font-weight:600;letter-spacing:.02em;text-transform:uppercase;color:" + color + ";";
    word.textContent = regime;
    var pairEl = document.createElement("span");
    pairEl.style.cssText = "color:" + MUTED + ";";
    pairEl.textContent = pair + (d.date ? " · " + d.date : "");
    top.appendChild(dot); top.appendChild(word); top.appendChild(pairEl);
    var mid = document.createElement("div");
    mid.style.cssText = "color:" + TEXT + ";";
    mid.textContent = "siren " + siren + risk;
    var foot = document.createElement("div");
    foot.style.cssText = "color:" + MUTED + ";font-size:10px;";
    foot.textContent = "FX Regime Radar · educational, not investment advice";
    root.appendChild(top); root.appendChild(mid); root.appendChild(foot);
  }

  var url = origin + "/api/regimes/" + encodeURIComponent(pair) + (partner ? "?partner=" + encodeURIComponent(partner) : "");
  fetch(url, { headers: { "Accept": "application/json" } })
    .then(function (r) { if (!r.ok) { throw new Error("HTTP " + r.status); } return r.json(); })
    .then(render)
    .catch(function (e) {
      root.textContent = "FX Regime Radar · " + pair + " · unavailable (" + e.message + ") · educational, not investment advice";
      root.style.color = MUTED;
    });
})();
