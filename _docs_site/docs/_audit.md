# Phase 0 — Content Audit (audit-first porting)

Source of truth: `d:\wrapper-dbpoweramp\docs\` against `d:\wrapper-dbpoweramp\mkdocs.yml`.
Target: `_docs_site/docs/<category>/<slug>.md` per `_docs_site/_data/navigation.yml`.

## Inventory (16 files)

| Source file | Lines | Verdict | Target slug | Audience | Notes |
|---|---|---|---|---|---|
| `docs/index.md` | 119 | **rewrite as landing** | `docs/index.md` (root) | user | Becomes the animated-waveform landing; lift "Quick Start", "Key Features", "Available Presets", and "File Index" sections verbatim, fix dead anchors (see `cli.md` cross-refs), drop the long inline TOC table — that becomes the navigation itself. |
| `docs/overview.md` | 177 | **merge** | content split into `index.md` (Key Features + Use Cases) + `architecture.md` (Components table) | mixed | High overlap with `architecture.md` Components table and `index.md` Feature list. Keep the unique "Design Principles" + "Use Cases" content, drop the duplicated pipeline diagram. |
| `docs/installation.md` | 399 | **keep** | `docs/installation.md` | user | Move the "Docker (Optional)" section to the bottom; the troubleshooting block partially overlaps `error-handling.md` — keep install-time checks here, cross-link to `error-handling.md` for the rest. |
| `docs/configuration.md` | 516 | **keep** | `docs/configuration.md` | user | Already a clean reference. Add anchor IDs for every section so other pages can deep-link. |
| `docs/cli.md` | 594 | **keep** | `docs/cli.md` | user | Add explicit anchor IDs: `output-verification`, `db-inspection-cli`, `db-migration-schema` so `index.md` cross-references resolve. Add a top TOC and group flags into "Required", "Backend selection", "Lossy policy", "Execution", "Inspection", "Verification", "DB inspection". |
| `docs/presets.md` | 449 | **keep** | `docs/presets.md` | user | Add codec-chip metadata to `_data/presets.yml` so preset cards render in the landing. |
| `docs/architecture.md` | 298 | **keep** | `docs/architecture.md` (hub) | engineer | Hub page: large hero, two mermaid diagrams already present, "Component map" subsections. Add explicit anchor IDs for each `src/` directory. |
| `docs/backends.md` | 414 | **keep** | `docs/backends.md` | engineer | Backend detail; add anchor IDs. |
| `docs/workflow.md` | 615 | **keep** | `docs/workflow.md` | engineer | Source has a duplicate `5.6 Sidecar Copying` block (lines 348-359) — keep only the first occurrence during port. Add anchor IDs (each phase). |
| `docs/file-index.md` | 333 | **keep** | `docs/file-index.md` | engineer | Index DB reference. |
| `docs/lossy-handling.md` | 257 | **keep** | `docs/lossy-handling.md` | user | Lossy detection + actions. |
| `docs/sidecar-files.md` | 294 | **keep** | `docs/sidecar-files.md` | user | Sidecar reference. |
| `docs/error-handling.md` | 400 | **keep** | `docs/error-handling.md` | engineer | Errors, exit codes, verify result format. |
| `docs/testing.md` | 355 | **keep** | `docs/testing.md` | engineer | Test suite reference. The CI yml snippet is stale — replace with a link to `.github/workflows/`. |
| `docs/api.md` | 742 | **keep** | `docs/api.md` (reference layout) | engineer | Public API. Use the `reference.html` two-pane alphabetical layout. |
| `docs/modules.md` | 1236 | **keep** | `docs/modules.md` (reference layout) | engineer | Longest page. Same alphabetical two-pane layout. The first ~70 lines of "Package Structure" + module list duplicate content in `architecture.md`; keep the directory tree, drop the redundant prose. |

## Duplicates and stale references

- `docs/index.md` lines 26-28 link to anchors in `cli.md` and `workflow.md` that do not exist (`cli.md#output-verification`, `cli.md#db-inspection-cli`, `workflow.md#db-schema-migration`). Anchors must be added to the target pages during port.
- `docs/modules.md` package tree and `docs/architecture.md` component map cover overlapping ground. Keep `modules.md`'s file tree (more granular), keep `architecture.md`'s responsibility prose, and link from each to the other.
- `docs/workflow.md` lines 348-359 duplicate §5.6 verbatim — port only the first occurrence.
- `docs/testing.md` shows an inline `.github/workflows/test.yml` snippet that has since been replaced with the MkDocs deploy workflow — replace with a forward-link to the repo.

## Hub-and-spoke navigation

Final structure (drives `_data/navigation.yml`):

```
Home (landing)              -> index.md
Getting Started             -> installation.md, overview.md
Configuration               -> configuration.md, cli.md, presets.md
Architecture (hub)          -> architecture.md, workflow.md, backends.md
Engineering                 -> file-index.md, lossy-handling.md, sidecar-files.md, error-handling.md, testing.md
Reference (alphabetical)    -> api.md, modules.md
```

## Frontmatter conventions

Every page gets:

```yaml
---
layout: default            # or landing / reference
title: "Human title"
category: getting-started  # matches a nav section
order: 10                  # position within section
summary: "One-line description for SEO and search index"
audience: [user]           # one or more of: user, engineer, power-user
---
```

## Link rewriting rules

- `cli.md#output-verification` -> `/cli/#output-verification`
- `cli.md#db-inspection-cli` -> `/cli/#db-inspection-cli`
- `workflow.md#db-schema-migration` -> `/workflow/#db-schema-migration`
- `overview.md` -> `/overview/`
- `architecture.md` -> `/architecture/`
- All MkDocs admonitions (`!!! note`, `!!! warning`) -> Liquid callout component (`{% include components/callout.html type="note" %}`)
- ` ```mermaid ` fenced blocks -> `{% mermaid %} ... {% endmermaid %}` (handled by `_plugins/mermaid.rb`)

## Out of scope for Phase 0

- No content rewrite yet — that happens in Phase 5
- No theme work
- No Jekyll installation
- The existing `docs/*.md` files stay in place until Phase 5 moves them
