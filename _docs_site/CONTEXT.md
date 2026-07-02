# Jekyll → Hugo Migration: Implementation Context

This file captures the decisions made during the phase discussion. Downstream agents
(researchers, planners) should treat these as **locked** — act on them without
re-asking the user.

---

## Phase: Jekyll → Hugo migration for GitHub Pages CI

**What is being migrated:** `_docs_site/` — a Jekyll 4 static site with a custom
"audiophile" theme (Sass tokens, hand-built components, esbuild JS bundling, no-CDN
policy, Ruby plugins, GitHub Pages deployment via two workflows).

**Goal:** Replace Jekyll with Hugo, preserve the audiophile look-and-feel, preserve
the no-CDN/local-bundling policy, and preserve the PR preview workflow. URL structure
may change (clean slate) but old links are redirected via `_redirects`.

---

## Theme & Components

### T1 — Theme fate
**Decision: Port the custom audiophile theme 1:1 into Hugo.**

- Do NOT switch to a stock Hugo theme (Hextra, Doks, etc.).
- The Hugo site's `themes/hugo-audiophile/` directory will own the Sass tokens,
  layouts, partials, and component templates.
- Fonts (Bodoni Moda, Geist, JetBrains Mono) remain as-is; the CSS custom-property
  palette (`--paper`, `--ink`, `--accent`, etc.) is preserved identically in Hugo's
  asset pipeline.

### T2 — Component parity
**Decision: Full parity required.**

Every Jekyll component must exist in Hugo. The non-negotiable set:

| Component | Location in Jekyll | Hugo equivalent |
|---|---|---|
| Animated waveform | `_includes/components/waveform.html` + `assets/js/entry-waveform.js` | `layouts/shortcodes/waveform.html` + `assets/js/waveform.js` |
| Codec chip | `_includes/components/codec-chip.html` | `layouts/shortcodes/codec-chip.html` |
| Callout (note/warning/audiophile) | `_includes/components/callout.html` | `layouts/shortcodes/callout.html` |
| Code block with copy button | `_includes/components/code-block.html` | `layouts/shortcodes/code-block.html` + JS |
| Version selector | `_includes/components/version-selector.html` | `layouts/shortcodes/version-selector.html` |
| Command palette | `_includes/components/command-palette.html` | Same structure, adapted to Hugo output |
| Mermaid diagrams | `_plugins/mermaid.rb` + `_includes/components/mermaid.html` | Hugo shortcode `layouts/shortcodes/mermaid.html` + locally bundled mermaid.js |
| Graphviz diagrams | `_plugins/graphviz.rb` + `_includes/components/graphviz.html` | Hugo shortcode + locally bundled `@hpcc-js/wasm-graphviz` |
| Landing page | `_layouts/landing.html` | `layouts/landing.html` |
| Reference layout | `_layouts/reference.html` | `layouts/reference.html` |
| Print layout | `_layouts/print.html` | `layouts/print.html` |

The `design-decisions.md` page is **dropped** — it is Jekyll-meta documentation,
not product documentation.

### T3 — JS bundling
**Decision: Keep esbuild + vendored local bundles. No CDN at runtime.**

- Keep `scripts/vendor-build.mjs` (esbuild) unchanged.
- Bundled output (`assets/vendor/*.js`) stays in the repo.
- `check-no-cdn.mjs` continues to run on `public/` after the Hugo build.
- Hugo Pipes are NOT used for JS — esbuild is the JS pipeline.
- For Sass: Hugo can use Dart Sass via its built-in `resources.Execute`
  or the `hugo-bin` postcss pipeline, OR we keep `scripts/build-css.mjs` unchanged
  and copy the output. The CI step order becomes:
  `npm ci → npm run css → npm run vendor → hugo → check-no-cdn.mjs → upload artifact`.

### T4 — Build pipeline shape
Hugo build replaces Jekyll. The multi-step becomes:
```
npm ci && npm run css && npm run vendor
hugo (--gc --minify --environment production)
node scripts/check-no-cdn.mjs public
upload-pages-artifact
```

---

## Authoring Experience & Content Layout

### A1 — Content location
**Decision: Section/subdirectory bundles — `content/<section>/<sub>/_index.md`.**

Example mapping from the current flat `contents/*.md`:

```
contents/
├── index.md          → content/_index.md              (homepage / landing)
├── overview.md       → content/overview/_index.md
├── installation.md   → content/getting-started/installation.md
├── configuration.md  → content/configuration/_index.md
├── cli.md            → content/configuration/cli.md
├── presets.md        → content/configuration/presets.md
├── architecture.md  → content/architecture/_index.md
├── backends.md       → content/architecture/backends.md
├── workflow.md       → content/architecture/workflow.md
├── file-index.md    → content/engineering/file-index.md
├── lossy-handling.md→ content/engineering/lossy-handling.md
├── sidecar-files.md → content/engineering/sidecar-files.md
├── error-handling.md→ content/engineering/error-handling.md
├── testing.md        → content/engineering/testing.md
├── api.md           → content/reference/api.md
└── modules.md        → content/reference/modules.md
```

- Each page gets a folder (so future images/assets can be co-located as Hugo page bundles).
- `design-decisions.md` is NOT migrated.

### A2 — Front matter conversion
**Decision: Use `scriv` or a Jekyll-to-Hugo converter (e.g. `hugo import jekyll`) to handle the migration automatically, then clean up.**

- Run the converter first to get a baseline migration of all 17 pages.
- Drop Jekyll-specific keys: `permalink`, `layout`, `slug`, `category`.
- Keep Hugo-compatible keys: `title`, `summary`, `audience`.
- Hugo weight/order via `weight` in front matter (derive from the existing `order` values).
- The `audience` array maps to Hugo's `outputs: ["html", "json"]` or stays as custom front matter — it's a metadata field, not a Hugo concept.

### A3 — Data files
**Decision: Hugo-native YAML data files — `data/navigation.yaml`, `data/presets.yaml`, `data/versions.yaml`.**

| Jekyll | Hugo |
|---|---|
| `_data/navigation.yml` | `data/navigation.yaml` |
| `_data/presets.yml` | `data/presets.yaml` |
| `_data/versions.yml` | `data/versions.yaml` |

- Content: copy as-is; adjust Liquid template syntax to Go template syntax.
- Hugo reads these at build time; no runtime impact.
- The `navigation.yaml` drives the sidebar; Hugo's native section ordering
  (`weight`) can replace the Jekyll `order` approach, or keep weight on pages.

### A4 — Search index
**Decision: Use Hugo's built-in search or a search theme module that produces a search index at build time.**

- Options: Hugo's native `outputFormats = ["HTML", "JSON"]` per page, or a theme
  module (e.g. `hugo-search-engines`, `minisearch`).
- The custom Ruby `search_index.rb` plugin is **dropped** — Hugo has no Ruby plugin system.
- The command palette's `palette.js` loads `/wrapper_dbpoweramp/search.json`; adapt the
  URL to the Hugo equivalent or configure `search-index` output format.
- If Hugo's native JSON output is used, the command palette JS is updated to read
  `index.json` (or whatever path Hugo emits) instead of the custom `search.json`.

---

## Build Pipeline & CI

### C1 — GitHub Actions workflow
**Decision: Replace the Jekyll workflow with `peaceiris/actions-hugo` (or equivalent) — single Hugo setup + build step.**

`deploy.yml` becomes:
```yaml
- uses: actions/checkout@v4
- uses: peaceiris/actions-hugo@v3
  with:
    hugo-version: '0.139'
- uses: actions/setup-node@v4
  with:
    node-version: '20'
    cache: npm
    cache-dependency-path: _docs_site/package-lock.json
- name: Install npm dependencies
  run: npm ci
- name: CSS + JS bundle
  run: npm run css && npm run vendor
- name: Hugo build
  run: hugo --gc --minify --environment production
- name: CDN guard
  run: node scripts/check-no-cdn.mjs public
- uses: actions/upload-pages-artifact@v3
  with:
    path: _docs_site/public
```

### C2 — Build time budget
**Decision: Sub-2 minutes is the target.**

Hugo is fast. With `peaceiris/actions-hugo` caching and `npm ci` with the existing
`package-lock.json` cache key, the build should be under 2 minutes. If it exceeds
2 minutes, the planner investigates: Hugo module cache, asset fingerprinting, or
removing unused fonts from `assets/`.

### C3 — No-CDN policy
**Decision: Keep `scripts/check-no-cdn.mjs` exactly as-is, run it on `public/` after Hugo build.**

- No changes to the script itself.
- It already has the right allowlist (`5509346169.github.io`, `github.com`, `raw.githubusercontent.com`).
- The CI step runs after `hugo` and before `upload-pages-artifact`.

### C4 — PR preview workflow
**Decision: Keep the PR preview workflow (build + comment).**

`pages-preview.yml` is rewritten to use the Hugo action instead of Jekyll:
- Same trigger: `pull_request` on `main`, paths `_docs_site/**` and itself.
- Same permissions: `contents: read`, `pull-requests: write`.
- Build steps mirror the deploy workflow but upload as a preview artifact.
- Comment script (`actions/github-script`) remains unchanged — it just posts "built green."

---

## Content Shape & Permalinks

### P1 — URL strategy
**Decision: Clean slate — change paths if Hugo suggests better ones, but add `_redirects`.**

- Hugo's default behaviour: `content/architecture/backends.md` → `/architecture/backends/`.
- The old Jekyll site used explicit permalinks (`/installation/`, `/cli/`, `/api/`, etc.).
- The migrator should check the resulting URL structure and add explicit `aliases` or
  `_redirects` entries for any URLs that differ from the Jekyll output.
- The base URL is `https://5509346169.github.io/wrapper_dbpoweramp/` — Hugo's
  `baseURL` in `hugo.yaml` must match.

### P2 — Redirects
**Decision: Static `_redirects` file (GitHub Pages compatible).**

- GitHub Pages natively supports a `_redirects` file in the root of the deployed site.
- For every URL that changes, add a line to `static/_redirects`:
  ```
  /installation/ /getting-started/installation/
  /cli/          /configuration/cli/
  ```
- The `netlify-style` format (`source  destination`) is GitHub Pages-compatible.
- After Hugo builds, copy `static/_redirects` to `public/` (or use Hugo's
  `staticDir` which does this automatically).

### P3 — Internal links
**Decision: Hugo-native relative links using `ref` or `relref` shortcodes for build-time validation.**

- Replace Jekyll `relative_url` filters with Hugo shortcodes:
  ```md
  [Architecture](/architecture/)              → {{< relref "architecture" >}}
  [CLI reference](/cli/)                       → {{< relref "configuration/cli" >}}
  [Installation](/installation/)                 → {{< relref "getting-started/installation" >}}
  ```
- This gives build-time validation: broken references fail the build.
- `ref` uses the page's `ref` (or `linkTitle` / `title`); `relref` uses the relative path.
- Alternatively, use Hugo's `ref` in its short form: `{{</* ref "path" */>}}`.
- **Cross-check**: the current content has explicit `/installation/`, `/cli/` etc. links
  in prose. These need to be rewritten. Plan should flag this as a content transformation task.

### P4 — Table of Contents
**Decision: Hugo built-in TOC — drop the client-side JS TOC walker.**

- Hugo emits `{{ .TableOfContents }}` in layouts — replace the JS-driven `[data-toc]`
  walker in `_includes/layout/right-rail.html`.
- Hugo's TOC includes h2/h3 by default (configurable via `toc` front matter or config).
- The Hugo layout partial for the right rail uses `{{ .TableOfContents }}` directly.
- The `[data-toc]` JS walker in `assets/js/entry-theme.js` (or wherever it lives) is **removed**.

---

## Deferred Ideas (captured but not acted on)

- SVG favicon matching the waveform/brand identity — deferred to a follow-up phase.
- Lighthouse CI integration — deferred; no existing score baseline.
- Algolia DocSearch — deferred; the built-in Hugo search is sufficient for this site size.
- Sticky TOC with scroll-spy — deferred; Hugo themes often include this natively if needed.

---

## Output directories

After migration, the directory tree changes from:

```
_docs_site/                        →  _docs_site/
├── _config.yml                    →  hugo.yaml
├── contents/                      →  content/
├── _data/                        →  data/
├── _layouts/                     →  layouts/
├── _includes/                   →  layouts/partials/ and layouts/shortcodes/
├── _plugins/                     →  removed (Ruby plugins have no Hugo equivalent)
├── assets/js/                   →  assets/js/
├── assets/css/main.scss          →  assets/scss/main.scss  (or kept in assets/scss/)
├── assets/vendor/                →  assets/vendor/
├── scripts/                     →  scripts/
│   ├── build-css.mjs            →  scripts/build-css.mjs   (unchanged)
│   ├── vendor-build.mjs          →  scripts/vendor-build.mjs  (unchanged)
│   └── check-no-cdn.mjs         →  scripts/check-no-cdn.mjs (unchanged)
├── _sass/                       →  themes/hugo-audiophile/assets/scss/
├── Gemfile / Gemfile.lock        →  removed (Ruby not needed)
├── package.json                  →  package.json               (trimmed: drop Jekyll deps)
├── _site/                       →  removed (Hugo output goes to public/)
├── site/                       →  removed (artifact is public/ + _redirects)
├── Makefile / Rakefile          →  removed (CI uses shell steps)
└── README.md                    →  updated to reflect Hugo dev workflow
```

Hugo's output: `_docs_site/public/` replaces Jekyll's `_docs_site/_site/`.
The CI `upload-pages-artifact` step points to `public/` instead of `site/`.

---

## Next steps

1. **Research**: Investigate `scriv` vs `hugo import jekyll` vs a custom converter
   for the content migration. Verify the `hugo import jekyll` tool handles the
   `_data/` YAML files, `permalink` front matter, and `{% include %}` Liquid tags.
2. **Plan**: Generate the full implementation plan covering:
   - Hugo installation and `hugo.yaml` config
   - Theme port (Sass → Hugo asset pipeline)
   - Component port (layouts + shortcodes + JS adapters)
   - Content migration (converter + link rewriting)
   - CI workflow rewrite (both `deploy.yml` and `pages-preview.yml`)
   - `_redirects` generation
   - Verification (check every old URL redirects, visual diff of rendered pages)
