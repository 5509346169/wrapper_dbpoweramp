// Compiles _sass/* (via the entry file assets/css/main.scss) into a single
// assets/css/main.css using Dart Sass's JS API. Runs OUTSIDE Jekyll so the
// build does not depend on Ruby native extensions (sass-embedded needs the
// MinGW/MSYS2 toolchain, which is not always installed alongside Ruby on
// Windows). The output style is "expanded" to match the previous Jekyll
// config (`sass: { style: :expanded }`).
//
// Usage: node scripts/build-css.mjs
// Output: static/css/main.css

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import * as sass from "sass";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

const entry = resolve(root, "themes/hugo-audiophile/assets/scss/main.scss");
const out = resolve(root, "static/css/main.css");
const loadPaths = [resolve(root, "themes/hugo-audiophile/assets/scss")];

mkdirSync(dirname(out), { recursive: true });

let result;
try {
  result = sass.compile(entry, {
    style: "expanded",
    loadPaths,
    sourceMap: false,
  });
} catch (err) {
  console.error("Sass error:");
  console.error(err.message);
  process.exit(1);
}

writeFileSync(out, result.css, "utf8");
const rel = out.startsWith(root) ? out.slice(root.length).replace(/^[\\/]/, "") : out;
console.log(`Wrote ${rel} (${result.css.length} bytes)`);