// Progressive enhancement only. Every number on these pages is already in the HTML the server
// sent; nothing here is required to read the market state. If this file fails to load, the page is
// still correct — which is the whole reason the state is baked at build time.
(function () {
  "use strict";

  // Register the service worker so a cold open offline shows yesterday's reading with a badge.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("sw.js").catch(function () {});
    });
  }

  // If the cached page is older than the published state, say so rather than showing a stale
  // number as though it were today's. The badge is the honest version of a fast page.
  var meta = document.querySelector('[data-through]');
  fetch("state.json", { cache: "no-cache" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (fresh) {
      if (!fresh || !meta) return;
      if (fresh.data_through && fresh.data_through !== meta.getAttribute("data-through")) {
        var b = document.createElement("p");
        b.className = "badge";
        b.setAttribute("role", "status");
        b.textContent = "A newer reading is published — reload for " + fresh.data_through;
        var main = document.querySelector("main");
        if (main) main.insertBefore(b, main.firstChild);
      }
    })
    .catch(function () {});
})();
