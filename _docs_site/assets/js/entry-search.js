// Command palette — Cmd-K / Ctrl-K opens a fuzzy search over a generated
// search.json. Bundled to assets/vendor/search-palette.js. No CDN.

import { openPalette, closePalette, attachPalette } from "../js/palette.js";

function init() {
  const root = document.querySelector("[data-cmdk]");
  if (!root) return;
  attachPalette(root);

  document.querySelectorAll("[data-cmdk-open]").forEach((btn) => {
    btn.addEventListener("click", () => openPalette(root));
  });

  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openPalette(root);
    } else if (e.key === "Escape" && !root.hidden) {
      closePalette(root);
    } else if (e.key === "/" && root.hidden && document.activeElement.tagName !== "INPUT" && document.activeElement.tagName !== "TEXTAREA") {
      e.preventDefault();
      openPalette(root);
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
