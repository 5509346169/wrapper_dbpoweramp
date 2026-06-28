#!/usr/bin/env node
// CI guard: scan a built site directory for any reference to https:// or
// http:// (except local file: and the GitHub Pages URL we own) in script src
// and link href attributes. Fails the build if any are found.
//
// Usage: node scripts/check-no-cdn.mjs <built-dir>
// Default: site

import { readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { argv, exit } from "node:process";

const target = resolve(argv[2] ?? "site");
const allowedHosts = new Set([
  "5509346169.github.io",
  "github.com",
  "raw.githubusercontent.com",
]);

const offenders = [];
const visited = new Set();

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (visited.has(full)) continue;
    visited.add(full);
    const st = statSync(full);
    if (st.isDirectory()) {
      walk(full);
      continue;
    }
    if (!/\.html?$/.test(extname(entry))) continue;
    const html = readFileSync(full, "utf8");
    const re = /\b(?:src|href)\s*=\s*"([^"]+)"/gi;
    let m;
    while ((m = re.exec(html))) {
      const url = m[1];
      if (!/^https?:\/\//i.test(url)) continue;
      const host = url.replace(/^https?:\/\//i, "").split("/")[0];
      if (allowedHosts.has(host)) continue;
      offenders.push({ file: full, url });
    }
  }
}

walk(target);
if (offenders.length === 0) {
  console.log(`OK — no CDN URLs found under ${target}/`);
  exit(0);
}

console.error(`Found ${offenders.length} non-allowlisted external URL(s):`);
for (const o of offenders) {
  console.error(`  ${o.file}: ${o.url}`);
}
exit(1);
