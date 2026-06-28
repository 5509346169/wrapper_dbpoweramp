// Static preflight that mimics the parts of `bundle exec jekyll build`
// we can run without Ruby: frontmatter shape, include resolution, permalink
// uniqueness, intra-site link target existence, mermaid/graphviz balance,
// and callout-type allowlist. Does not run Jekyll itself.
//
// Usage: node _docs_site/scripts/static-preflight.mjs

import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { extname, join, resolve, dirname, basename } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const site = resolve(__dirname, "..");
const contentsDir = resolve(site, "contents");
const includesDir = resolve(site, "_includes");

const errors = [];
const warnings = [];

function err(file, msg) {
  errors.push({ file: file.replace(site + "\\", "").replace(site + "/", ""), msg });
}
function warn(file, msg) {
  warnings.push({ file: file.replace(site + "\\", "").replace(site + "/", ""), msg });
}

// --- 1. Collect every page in contents/ and parse its frontmatter ---
const pages = [];
function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      walk(full);
      continue;
    }
    if (!/\.(md|markdown)$/i.test(extname(entry))) continue;
    pages.push(full);
  }
}
walk(contentsDir);

const permalinks = new Map(); // permalink -> file
const fmBlocks = []; // {file, permalink, layout}

for (const file of pages) {
  const raw = readFileSync(file, "utf8");
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (!m) {
    err(file, "no YAML frontmatter (must start with ---)");
    continue;
  }
  const fm = m[1];
  // Tiny YAML parser limited to the subset we use: `key: value` lines,
  // `key: [a, b]`, and `key:` followed by indented sub-keys.
  const fmObj = {};
  const lines = fm.split(/\r?\n/);
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const km = line.match(/^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$/);
    if (km) {
      const [, key, valueRaw] = km;
      let value = valueRaw.replace(/^['"]|['"]$/g, "").trim();
      if (value === "" || value === undefined) {
        // block: collect indented lines
        const block = {};
        i++;
        while (i < lines.length && /^\s+/.test(lines[i])) {
          const sub = lines[i].match(/^\s+([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$/);
          if (sub) {
            block[sub[1]] = sub[2].replace(/^['"]|['"]$/g, "").trim();
          }
          i++;
        }
        fmObj[key] = block;
        continue;
      }
      if (value.startsWith("[") && value.endsWith("]")) {
        value = value
          .slice(1, -1)
          .split(",")
          .map((s) => s.trim().replace(/^['"]|['"]$/g, ""))
          .filter(Boolean);
      }
      fmObj[key] = value;
    }
    i++;
  }

  if (!fmObj.permalink) {
    err(file, "missing `permalink:` in frontmatter");
    continue;
  }
  if (!fmObj.layout) {
    warn(file, "no `layout:` declared; will fall back to _config defaults (default)");
  }
  if (permalinks.has(fmObj.permalink)) {
    err(file, `permalink '${fmObj.permalink}' collides with ${permalinks.get(fmObj.permalink)}`);
  } else {
    permalinks.set(fmObj.permalink, file);
  }
  fmBlocks.push({ file, permalink: fmObj.permalink, layout: fmObj.layout });
}

// --- 2. Verify {% include %} targets all exist ---
for (const file of pages) {
  const raw = readFileSync(file, "utf8");
  const re = /\{%-?\s*include\s+([^\s%}]+)\s*-?%\}/g;
  let m;
  while ((m = re.exec(raw))) {
    const target = resolve(includesDir, m[1]);
    if (!existsSync(target)) {
      err(file, `{% include ${m[1]} %} — file not found at ${target}`);
    }
  }
}

// --- 3. Verify {% mermaid %} / {% graphviz %} blocks balance ---
for (const file of pages) {
  const raw = readFileSync(file, "utf8");
  const opens = (raw.match(/\{%\s*(mermaid|graphviz)\s*%\}/g) || []).length;
  const closes = (raw.match(/\{%\s*end(mermaid|graphviz)\s*%\}/g) || []).length;
  if (opens !== closes) {
    err(file, `mermaid/graphviz blocks unbalanced: ${opens} open vs ${closes} close`);
  }
}

// --- 4. Callout type allowlist ---
const ALLOWED_CALLOUT = new Set(["note", "warning", "audiophile"]);
for (const file of pages) {
  const raw = readFileSync(file, "utf8");
  const re = /\{%-?\s*include\s+components\/callout\.html[^%}]*type=("?)([a-z]+)\1[^%}]*-?%\}/g;
  let m;
  while ((m = re.exec(raw))) {
    const t = m[2];
    if (!ALLOWED_CALLOUT.has(t)) {
      err(file, `unknown callout type '${t}' (allowed: ${[...ALLOWED_CALLOUT].join(", ")})`);
    }
  }
}

// --- 5. Intra-site link targets — only check [/slug/] style links to root permalinks ---
// Strip fenced code blocks first so we don't false-positive on docs that show
// example paths inside ``` fences.
for (const file of pages) {
  let raw = readFileSync(file, "utf8");
  raw = raw.replace(/```[\s\S]*?```/g, "").replace(/`[^`\n]*`/g, "");
  const re = /\]\((\/[A-Za-z0-9_\-./#]+)\)/g;
  let m;
  while ((m = re.exec(raw))) {
    const href = m[1];
    // External-looking: skip
    if (href.startsWith("//")) continue;
    const pathPart = href.split("#")[0].replace(/\/$/, "") || "/";
    if (pathPart === "/") continue; // landing page always exists
    if (!permalinks.has(pathPart + "/") && !permalinks.has(pathPart)) {
      warn(
        file,
        `intra-site link to '${href}' — no page declares a matching permalink (this is a soft warning: the anchor could be valid if it points to a section id, or to a page emitted by another module).`,
      );
    }
  }
}

// --- Report ---
console.log(`Pages: ${pages.length}`);
console.log(`Unique permalinks: ${permalinks.size}`);
console.log(`Errors: ${errors.length}`);
console.log(`Warnings: ${warnings.length}`);
if (errors.length || warnings.length) {
  console.log("");
  for (const e of errors) console.log(`  ERR  ${e.file}: ${e.msg}`);
  for (const w of warnings) console.log(`  WARN ${w.file}: ${w.msg}`);
}
process.exit(errors.length ? 1 : 0);