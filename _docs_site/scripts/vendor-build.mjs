#!/usr/bin/env node
// Bundles vendored JS/CSS into assets/vendor/ at build time.
// NO CDN at runtime — every dependency must be installed locally via npm.
//
// Usage: node scripts/vendor-build.mjs
// Output: assets/vendor/{theme,palette,waveform,search-palette}.js + manifest

import { build } from "esbuild";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const outDir = resolve(root, "assets/vendor");
mkdirSync(outDir, { recursive: true });

const manifest = [];

// Each entry becomes one bundled file in assets/vendor/.
// The vendor-bundle.txt manifest is checked into the repo and audited
// against the licenses of the installed packages.
const entries = [
  {
    name: "theme",
    entry: resolve(root, "assets/js/entry-theme.js"),
    target: "es2020",
    minify: true,
  },
  {
    name: "waveform",
    entry: resolve(root, "assets/js/entry-waveform.js"),
    target: "es2020",
    minify: true,
  },
  {
    name: "search-palette",
    entry: resolve(root, "assets/js/entry-search.js"),
    target: "es2020",
    minify: true,
  },
];

for (const e of entries) {
  const outfile = resolve(outDir, `${e.name}.js`);
  await build({
    entryPoints: [e.entry],
    bundle: true,
    minify: e.minify,
    target: e.target,
    format: "esm",
    outfile,
    sourcemap: false,
    logLevel: "warning",
  });
  manifest.push({ name: e.name, file: `assets/vendor/${e.name}.js`, target: e.target });
}

const txt = manifest.map((m) => `${m.name}\t${m.file}\t${m.target}`).join("\n") + "\n";
writeFileSync(resolve(outDir, "vendor-bundle.txt"), txt, "utf8");
console.log(`Wrote ${manifest.length} vendor bundle(s) to assets/vendor/`);
