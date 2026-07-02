// entry-diagrams.js — bundles mermaid + graphviz and renders them on the page.
// No CDN: both packages are installed locally via npm.

import mermaid from "mermaid";
import { instance as vizInstance } from "@viz-js/viz";

// ── mermaid ──────────────────────────────────────────────────────────────────

mermaid.initialize({
  startOnLoad: false,
  securityLevel: "loose",
  theme: "neutral",
  fontFamily: "Geist, system-ui, sans-serif",
});

function renderMermaid() {
  for (const el of document.querySelectorAll("[data-mermaid-source]")) {
    const pre = el.querySelector("pre");
    if (!pre) continue;

    const src = pre.textContent.trim();
    if (!src) continue;

    const div = document.createElement("div");
    div.className = "mermaid";
    div.textContent = src;
    el.replaceWith(div);
  }

  mermaid.run({ nodes: document.querySelectorAll(".mermaid") });
}

// ── graphviz ─────────────────────────────────────────────────────────────────

async function renderGraphviz() {
  const viz = await vizInstance();
  for (const el of document.querySelectorAll("[data-graphviz-source]")) {
    const pre = el.querySelector("pre");
    if (!pre) continue;

    const src = pre.textContent.trim();
    if (!src) continue;

    const result = viz.render(src);
    if (result.status === "success" && result.output) {
      const wrapper = document.createElement("div");
      wrapper.className = "graphviz";
      wrapper.innerHTML = result.output;
      const svg = wrapper.querySelector("svg");
      if (svg) svg.setAttribute("aria-label", "Graphviz diagram");
      el.replaceWith(wrapper);
    }
  }
}

// ── bootstrap ─────────────────────────────────────────────────────────────────

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    renderMermaid();
    renderGraphviz();
  });
} else {
  renderMermaid();
  renderGraphviz();
}
