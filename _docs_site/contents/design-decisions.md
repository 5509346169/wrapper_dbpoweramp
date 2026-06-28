---
permalink: /design-decisions/
layout: default
title: Design decisions & DFII
slug: design-decisions
category: meta
order: 5
summary: Why the audiophile theme, the DFII self-check, and what was deliberately not done.
audience: [engineer]
---

This page records the design decisions that shaped the documentation site, and the DFII (Design Feasibility & Impact Index) self-check that justified them.

## Why an audiophile theme?

The wrapper is a tool for users who care deeply about audio quality — people who can hear the difference between a V0 MP3 and a 320 CBR, and who choose dBpoweramp over an FFmpeg one-liner because they want the Reference codecs. The docs have to feel like they belong to that audience: cold, precise, well-typed, no skeuomorphic chrome, no playful illustrations.

Concretely:

- **Cool monochrome palette** — midnight, graphite, ice, silver, cloud, with a single audiophile accent (signal cyan). The palette reads as "high-end gear" rather than "consumer electronics".
- **Didone display face (Bodoni Moda)** — high stroke contrast and tight apertures, which match the physical proportions of a needle on vinyl.
- **Clean sans body (Inter)** — for legibility at body sizes; the display face is reserved for headings, eyebrows, and metric numerals.
- **Animated SVG waveforms** — not decorative: they double as the in-page progress indicator.

## Why hub-and-spoke + three-pane?

There are two clear content shapes in this docset:

1. **Hub pages** — *Getting started*, *Architecture*, *Configuration* — entry points with broad summaries and clear next steps. These live as landing pages with a sidebar.
2. **Alphabetical reference** — *CLI*, *Presets*, *API*, *Modules*, *Backends* — large lookup surfaces where users arrive with a known term. These live in a three-pane layout (alphabetical index / reading view / on-this-page rail).

A single layout would force one of these into the wrong shape. The two layouts share the same header, footer, palette, and component library.

## Why no CDN?

The repository's CI runs offline against third-party APIs at unpredictable intervals. Any CDN dependency becomes a build that can fail for reasons unrelated to the code change. Beyond reliability:

- **Subresource integrity** — local bundles are hash-pinned at build time. CDNs change content under our feet.
- **Reproducibility** — `bundle install && npm ci && make docs-build` always produces the same output.
- **Offline dev** — the docs work on a plane.

The cost is the local bundling step (`npm run vendor`). It's a single `esbuild` invocation; CI guards it with `check-no-cdn.mjs` so the policy cannot regress.

## DFII self-check

DFII is a five-axis scoring rubric — Impact, Fit, Feasibility, Performance, Consistency risk — that gives a single number to design direction. It was self-applied at the design-token phase.

| Axis | Score | Rationale |
|------|-------|-----------|
| **Impact** | 4 | Bodoni Moda display + animated SVG waveform are recognizable in the first 3 seconds; the palette reads as audiophile gear, not consumer electronics |
| **Fit** | 4 | Matches the audiophile audience, and the engineer-grade depth the codebase actually has |
| **Feasibility** | 4 | Jekyll 4 + Sass + vanilla ES modules is well-trodden; no exotic runtime dependencies |
| **Performance** | 4 | No client framework, no large JS bundles; fonts are subset at build time; vendor bundle is one HTTP request |
| **Consistency risk** | 2 | Single theme, single layout family |

**DFII = (4 + 4 + 4 + 4) − 2 = 14** — excellent. Execute fully.

The full reasoning lives inline at `_sass/01-tokens/README.md` so the next person editing tokens sees the score before changing the visual language.

## What was deliberately not done

- **No search engine beyond the in-page command palette.** A full-text search plugin would add JS and a serverless indexer; the command palette is enough for this surface area.
- **No dark-mode toggle in CSS only.** The theme uses a CSS variable layer (`$color-*`), so dark mode is one override file away, but the audiophile palette is already dark. We did not add a light theme because it would dilute the identity.
- **No animated transitions beyond the waveform and progress bars.** Motion budgets are spent where they earn attention.
- **No Mermaid diagrams on the landing page.** Diagrams live where they aid understanding (`/architecture/`, `/workflow/`); the landing page is a navigation surface.
- **No SDK page.** The CLI and Python API are documented under their respective hubs; we did not invent a separate SDK page to fill out the nav.

## How to extend the theme

When adding a new page or layout:

1. Pick the right layout: `default` for most pages, `landing` for hub pages, `reference` for alphabetical lookup, `print` for printable views.
2. Use existing components (`{% include components/callout.html type="..." %}`) before inventing new ones.
3. If you must add a new component, document it under `_includes/components/README.md` (TODO) with: name, parameters, when to use, when not to use.
4. Re-run the DFII rubric against the change. If Consistency risk grows past 3, reconsider.