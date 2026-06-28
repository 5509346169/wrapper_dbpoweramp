---
layout: landing
permalink: /
title: dBpoweramp Wrapper
tagline: Audiophile-grade audio conversion, on your terms.
slug: index
category: getting-started
order: 0
summary: A CLI tool that wraps dBpoweramp (via Wine on Linux, natively on Windows) and FFmpeg for cross-platform audio format conversion with audiophile-grade presets.
audience: [user, engineer, power-user]
---

<section class="landing__hero">
  <div class="landing__hero-copy">
    <p class="landing__eyebrow fade-up">Documentation · {{ site.data.versions[0].version }}</p>
    <h1 class="landing__title fade-up fade-up-2">
      Audio conversion, the way it should sound.
    </h1>
    <p class="landing__lede fade-up fade-up-3">
      A single CLI for FFmpeg and dBpoweramp on Linux and Windows. Lossy-aware. Resume-safe. Sidecar-preserving. Tuned by people who care how their library sounds.
    </p>
    <p class="fade-up fade-up-4">
      <a class="landing__cta" href="{{ '/installation/' | relative_url }}">Install &nbsp;→</a>
    </p>
  </div>

  <div class="landing__hero-art fade-up fade-up-3">
    {% include components/waveform.html density=128 caption="Three layers: carrier, harmonics, noise floor" %}
  </div>
</section>

<section class="landing__tracks">
  <article class="landing__track fade-up">
    <h3>Get started</h3>
    <p>Install Python, FFmpeg, and (optionally) dBpoweramp. Convert your first folder in five minutes.</p>
    <p>
      <a href="{{ '/installation/' | relative_url }}">Installation →</a>
      &nbsp;·&nbsp;
      <a href="{{ '/configuration/' | relative_url }}">Configuration →</a>
    </p>
  </article>

  <article class="landing__track fade-up fade-up-2">
    <h3>Use it</h3>
    <p>Every flag, every preset, every lossy action. Grouped by intent.</p>
    <p>
      <a href="{{ '/cli/' | relative_url }}">CLI reference →</a>
      &nbsp;·&nbsp;
      <a href="{{ '/presets/' | relative_url }}">Presets →</a>
    </p>
  </article>

  <article class="landing__track fade-up fade-up-3">
    <h3>Engineer it</h3>
    <p>Pipeline architecture, backends, concurrency model, error handling.</p>
    <p>
      <a href="{{ '/architecture/' | relative_url }}">Architecture →</a>
      &nbsp;·&nbsp;
      <a href="{{ '/api/' | relative_url }}">Public API →</a>
    </p>
  </article>
</section>

<section class="landing__presets">
  <h2 class="fade-up">Presets</h2>
  <p class="fade-up">Six shipping presets cover the most common audiophile workflows.</p>
  <p class="fade-up">
    {%- for preset in site.data.presets -%}
      {% include components/codec-chip.html slug=preset.slug %}
    {%- endfor -%}
  </p>
  <p><a href="{{ '/presets/' | relative_url }}">Read the preset reference →</a></p>
</section>

<section class="landing__quickstart fade-up">
  <h2>Quick start</h2>
  {% include components/code-block.html lang="sh" title="Convert your first library" content="python main.py -I ~/Music -O ~/Converted -p mp3-v0-vbr --lossy-action copy" %}
</section>

<section class="landing__principles fade-up">
  <h2>Design principles</h2>
  <ol>
    <li>Fail-fast validation — check prerequisites before touching any file.</li>
    <li>Idempotent operations — safe to re-run with the same arguments.</li>
    <li>Graceful degradation — handle errors without crashing.</li>
    <li>Transparent operation — verbose output shows exactly what is happening.</li>
    <li>Zero-configuration defaults — works out of the box with sensible choices.</li>
  </ol>
</section>
