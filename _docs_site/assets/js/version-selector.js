// Version selector — navigates to the chosen version URL when changed.

function init() {
  document.querySelectorAll("[data-version-select]").forEach((select) => {
    select.addEventListener("change", (e) => {
      const url = e.target.value;
      if (url) window.location.href = url;
    });
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
