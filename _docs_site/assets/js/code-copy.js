// Code-copy buttons. Each [data-code-block] gets a single click handler on
// the [data-code-copy] child. Copies the inner <code> text to clipboard
// and flips the label briefly.

function init() {
  document.querySelectorAll("[data-code-block]").forEach((block) => {
    const btn = block.querySelector("[data-code-copy]");
    if (!btn) return;
    const label = btn.querySelector("[data-code-copy-label]");
    const code = block.querySelector("code");
    btn.addEventListener("click", async () => {
      if (!code) return;
      try {
        await navigator.clipboard.writeText(code.textContent || "");
        btn.dataset.copied = "true";
        if (label) label.textContent = "Copied";
        setTimeout(() => {
          btn.dataset.copied = "false";
          if (label) label.textContent = "Copy";
        }, 1500);
      } catch (_) {
        // Older browsers: select + execCommand fallback
        const range = document.createRange();
        range.selectNodeContents(code);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
