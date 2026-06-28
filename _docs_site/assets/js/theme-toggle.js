// Theme toggle — switches data-theme on <html> and persists to localStorage.

const STORAGE_KEY = "theme";

export function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || "light";
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
}

function toggle() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem(STORAGE_KEY, next); } catch (_) {}
}

function init() {
  document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
    btn.addEventListener("click", toggle);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
