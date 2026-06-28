// Mirror of scripts/check-no-cdn.mjs that runs over _layouts/ and _includes/
// (the post-build guard runs over site/). Used as a developer-time preflight
// so a CDN URL slipping into a layout is caught before CI.
//
// Usage: node scripts/check-templates-no-cdn.mjs

import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { extname, join, resolve } from "node:path";
import { exit } from "node:process";

const site = resolve(".");
const targets = ["_layouts", "_includes"].map((p) => resolve(site, p)).filter(existsSync);

const allowedHosts = new Set([
  "5509346169.github.io",
  "github.com",
  "raw.githubusercontent.com",
  "ffmpeg.org",
  "www.gyan.dev",
]);

const offenders = [];
function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
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

for (const t of targets) walk(t);

if (offenders.length === 0) {
  console.log(`OK - no non-allowlisted CDN URLs in ${targets.map((t) => t.replace(site + "\\", "")).join(", ")}/`);
  exit(0);
}
console.error(`Found ${offenders.length} non-allowlisted external URL(s):`);
for (const o of offenders) console.error(`  ${o.file.replace(site + "\\", "")}: ${o.url}`);
exit(1);