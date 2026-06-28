#!/usr/bin/env node
// Mirrors _site/ -> site/ so CI and the Pages artifact are one extra step
// apart from Jekyll's intermediate output. Lets reviewers diff pre/post
// transforms in the future without re-running the full build.

import { cpSync, rmSync, mkdirSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const src = resolve(root, "_site");
const dst = resolve(root, "site");

if (!existsSync(src)) {
  console.error(`_site/ does not exist. Run 'make docs-build' first.`);
  process.exit(1);
}

if (existsSync(dst)) rmSync(dst, { recursive: true, force: true });
mkdirSync(dst, { recursive: true });
cpSync(src, dst, { recursive: true });
console.log(`Copied _site/ -> site/`);
