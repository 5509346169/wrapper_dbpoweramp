// Command palette core — loads search.json on first open, fuzzy-matches,
// keyboard-navigates the result list. Tiny built-in scorer (no Fuse.js dep
// so the bundle stays under a few KB).

const INDEX_URL = "/wrapper_dbpoweramp/search.json";
let CACHE = null;

async function loadIndex() {
  if (CACHE) return CACHE;
  try {
    const res = await fetch(INDEX_URL, { credentials: "omit" });
    if (!res.ok) throw new Error(`search.json HTTP ${res.status}`);
    CACHE = await res.json();
  } catch (_) {
    CACHE = [];
  }
  return CACHE;
}

function score(query, text) {
  if (!query) return 1;
  const q = query.toLowerCase();
  const t = text.toLowerCase();
  if (t === q) return 100;
  if (t.startsWith(q)) return 50;
  const idx = t.indexOf(q);
  if (idx < 0) return 0;
  return 30 - Math.min(idx, 30);
}

function highlight(text, query) {
  if (!query) return text;
  const idx = text.toLowerCase().indexOf(query.toLowerCase());
  if (idx < 0) return text;
  return (
    text.slice(0, idx) +
    "<mark>" + text.slice(idx, idx + query.length) + "</mark>" +
    text.slice(idx + query.length)
  );
}

function renderResults(root, items, query) {
  const list = root.querySelector("[data-cmdk-results]");
  if (!list) return;
  list.innerHTML = "";
  if (items.length === 0) {
    const empty = document.createElement("li");
    empty.setAttribute("aria-disabled", "true");
    empty.innerHTML = '<a><span style="color:var(--ink-mute)">No results.</span></a>';
    list.appendChild(empty);
    return;
  }
  items.slice(0, 12).forEach((item, i) => {
    const li = document.createElement("li");
    li.dataset.index = String(i);
    li.innerHTML = `<a href="${item.url}">${highlight(item.title, query)}<br><small style="color:var(--ink-mute)">${item.section || ""}</small></a>`;
    list.appendChild(li);
  });
}

function activeIndex(root) {
  const list = root.querySelector("[data-cmdk-results]");
  if (!list) return 0;
  const items = Array.from(list.querySelectorAll("li[data-index]"));
  const idx = items.findIndex((li) => li.getAttribute("aria-selected") === "true");
  return Math.max(0, idx);
}

function setActive(root, idx) {
  const list = root.querySelector("[data-cmdk-results]");
  if (!list) return;
  const items = Array.from(list.querySelectorAll("li[data-index]"));
  items.forEach((li, i) => {
    if (i === idx) li.setAttribute("aria-selected", "true");
    else li.removeAttribute("aria-selected");
  });
}

export async function openPalette(root) {
  root.hidden = false;
  const input = root.querySelector("[data-cmdk-input]");
  if (input) {
    input.value = "";
    input.focus();
  }
  const index = await loadIndex();
  renderResults(root, index, "");
  setActive(root, 0);
}

export function closePalette(root) {
  root.hidden = true;
}

export function attachPalette(root) {
  const input = root.querySelector("[data-cmdk-input]");
  const backdrop = root.querySelector("[data-cmdk-close]");
  if (backdrop) backdrop.addEventListener("click", () => closePalette(root));

  if (input) {
    input.addEventListener("input", async () => {
      const q = input.value.trim();
      const index = await loadIndex();
      const ranked = index
        .map((it) => ({
          it,
          s: Math.max(score(q, it.title), score(q, it.section || ""), score(q, it.summary || "")),
        }))
        .filter((x) => x.s > 0)
        .sort((a, b) => b.s - a.s)
        .map((x) => x.it);
      renderResults(root, ranked, q);
      setActive(root, 0);
    });

    input.addEventListener("keydown", (e) => {
      const list = root.querySelector("[data-cmdk-results]");
      if (!list) return;
      const items = list.querySelectorAll("li[data-index]");
      if (e.key === "ArrowDown") {
        e.preventDefault();
        const next = Math.min(activeIndex(root) + 1, items.length - 1);
        setActive(root, next);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const prev = Math.max(activeIndex(root) - 1, 0);
        setActive(root, prev);
      } else if (e.key === "Enter") {
        const idx = activeIndex(root);
        const link = items[idx] && items[idx].querySelector("a");
        if (link) {
          e.preventDefault();
          window.location.href = link.getAttribute("href");
        }
      }
    });
  }
}
