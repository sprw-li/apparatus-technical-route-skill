# Exports, fonts and colour

Everything in this file is script-determined. If you find yourself wanting to tune a stroke width by
hand, change `spec.json` and rebuild instead — the export is regenerated from the scene every time,
and gates B/C/D/F/G/H/K re-check these properties on every run.

Sources of truth: `scripts/export.py` (measurement + orchestration), `scripts/fonts.py` (face
resolution), `scripts/measure.py` (text metrics), `scripts/layout.py` (edge visuals, legend-driven
colour), `scripts/scene.py` (canvas defaults and limits).

---

## 1. Canvas and units

| Property | Value | Source |
|---|---|---|
| Scene coordinate space | **millimetres, origin top-left, +y down** | `scene.py` header |
| Font sizes | **points** | `scene.py` header |
| Conversion | `pt = mm × 72/25.4`; `mm = pt × 25.4/72` | `scene.mm_to_pt` / `pt_to_mm` |
| Default page | **180 × 120 mm** (single page, two-column journal width) | `scene.DEFAULT_CANVAS` |
| Default margin | 3 mm | `scene.DEFAULT_CANVAS.margin_mm` |
| Default dpi | 300 | `scene.DEFAULT_CANVAS.dpi` |
| Allowed `w_mm`/`h_mm` | 20–1000 | `E003`/`E004` |
| Allowed `dpi` | 72–1200 | `E005` |
| Allowed `margin_mm` | 0–20, and `2×margin < min(w,h)` | `E006`/`E007` |

Resolution order for the page box (`export.resolve_canvas`): scene canvas → `spec.meta.canvas` →
`scene.DEFAULT_CANVAS`. Non-numeric values are ignored, not coerced. The declared canvas is a
**minimum**: the layout may grow the page. The bundled example declares 240 × 250 mm and the layout
resolves **240 × 250 mm** (`off 0.00 mm`); the `autospec` fallback on the same input resolves
200 × 170 mm, which is a good reminder to always read the resolved value.

## 2. Export parameters (the contract)

| Parameter | Value | How it is proven |
|---|---|---|
| Formats | `svg,png,pdf` by default (`ar.py build --formats`) | `export_report.formats` |
| DPI | **300** (`--dpi 300`) | `export_report.dpi` |
| Colour space | **sRGB** (declared) | `export_report.colorspace == "sRGB"` |
| PNG | lossless raster, `pHYs` chunk with dpi | `export_report.png` (parsed from the PNG bytes) |
| PDF | 1 page, **vector text**, **embedded TrueType** | `export_report.pdf` (parsed from the PDF bytes) |
| SVG | layered, named groups, real `<text>` | `export_report.svg` (counted in the SVG text) |

### What actually gets measured

`export.py` does not trust the backends — it re-reads the bytes it just wrote:

* **PNG** (`sniff_png`, stdlib only): signature, `IHDR` pixel size and bit depth, `pHYs` → `dpi`
  (only when the unit is metres), plus a `tEXt`/`iTXt` `dpi=` fallback. `expected_px` is
  `round(w_mm/25.4 × dpi) × round(h_mm/25.4 × dpi)`.
* **PDF** (`sniff_pdf`, stdlib only): `%PDF` header, page count via `/Type /Page` (falling back to
  `/Count`), `MediaBox` in points, **font embedding** via `/FontFile`, `/FontFile2`, `/FontFile3`,
  **vector text** via `Tj`/`TJ` counts, and `/Subtype /Image` for accidental rasterisation. Flate
  streams are decoded with `zlib` before searching.
* **SVG**: `<text>` count, `<g>` count, named-group count, `<image>` count, byte size.

### Measured on the bundled fixture (2026-11-23 13:38 +08:00, authored spec)

| Artefact property | Measured | Gate H requirement |
|---|---|---|
| Page resolved | `240.0 × 250.0 mm` | equals the spec's declaration (`off 0.00 mm`) |
| PNG pixel size | `[2835, 2953]` | `expected_px [2835, 2953]` — equal |
| PNG dpi metadata (`pHYs`, unit = metre) | `299.9994` | `≥ 300`; accepted because `pHYs` stores integer pixels-per-metre, so 300 dpi round-trips `11811 ppm → 299.9994 dpi` while the pixel size matches exactly |
| PDF pages | `1` | `1` |
| PDF MediaBox (pt) | `[680.315, 708.6614]` | `[680.315, 708.661]` — within gate H's 1.0 pt tolerance |
| PDF font programmes embedded | `font_programs=2`, `embedded=True` | `> 0` |
| PDF vector text | `text_ops=130`, `vector=True` | `> 0` |
| PDF raster fallback | `image_objects=0` | informational |
| SVG text / groups / images | `text_nodes=112`, `groups=7 (named 7)`, `images=0` | real `<text>`, named groups, no whole-image bitmap |
| SVG size | `134,400 B` | < 500 KB per-file bundle cap |

For the **default** 180 × 120 mm page at 300 dpi the expected PNG is **2126 × 1417 px** and the
expected MediaBox **510.236 × 340.157 pt**; those two figures are **arithmetic from `export.py`**,
not measured here. The 240 × 250 mm figures above are **measured**.

> Note for reuse: the numbers above belong to the frozen fixture and to the script revision of that
> date. `figure.svg` and `figure.png`/`figure.pdf` are *not* stable across script revisions — a
> re-run after a change to `layout.py` reproduces the SVG (same input, same code path) but not
> necessarily the same sha256 as the committed copy. Regenerate and re-quote rather than copying
> stale hashes.

## 3. Fonts

`fonts.resolve_fonts(lang)` never raises and never returns `None`. It searches explicit, ordered
candidate lists — no directory-scan order, no RNG, no time — so two runs on the same machine pick the
same face.

Search order:

* **Latin**: `arial.ttf` → `calibri.ttf` → `segoeui.ttf` → `DejaVuSans.ttf` → `liberationsans.ttf` →
  `freesans.ttf` (bold partner looked up separately, falls back to regular).
* **CJK**: `simhei.ttf` → `msyh.ttc` → `msyh.ttf` → `NotoSansSC-VF.ttf` →
  `NotoSansCJKsc-Regular.otf` → `simsun.ttc` → `NotoSansJP-VF.ttf` → `NotoSansKR-VF.ttf`
  (plain `.ttf` before `.ttc` collections, because TTC is awkward for PIL/matplotlib PDF).
* Font directories: `%WINDIR%\Fonts`, `%LOCALAPPDATA%\Microsoft\Windows\Fonts`, `~/.fonts`,
  `/usr/share/fonts`, `/Library/Fonts`, and finally matplotlib's bundled `mpl-data/fonts/ttf`
  (DejaVu Sans — the guaranteed last-resort face).

CJK is requested for `lang` in `zh/cn/chinese/ja/jp/japanese/ko/kr/korean`, for anything containing
`han`, **and for `auto`/unset** ("unknown language must stay CJK-capable").

Measured on this host (`lang: "en"`): `export_report.font.degraded = false`, regular
`…\arial.ttf`, bold `…\arialbd.ttf`, cjk `…\simhei.ttf`. The `font.paths` block of a real run records
the host that produced the artefacts — that is evidence of the run, not a configuration requirement.
Degradation semantics (`FontSet.degraded`) — a missing font is a *recorded* condition, never a crash:

| Condition | Effect |
|---|---|
| CJK requested, no CJK face found | `degraded = True`; note added; `spec.meta.degraded_fonts` should be set |
| `degraded` observed at build time | `export_report.font.degraded = true`; `result.json.limitations` gains the font-fallback sentence |
| No Latin face at all | note "falling back to the built-in width table" (measures still work) |
| Face unreadable for glyph checking | only characters outside the built-in ASCII width table are reported missing |

Glyph coverage: `missing_glyphs(text, path)` returns the sorted characters the face cannot draw (via
`fontTools` `cmap`, else `matplotlib.ft2font`, else the ASCII width-table heuristic).
`glyph_coverage_ok(text, fs)` succeeds if **any** resolved face covers every non-space character. A
CJK character inside an otherwise-Latin string automatically selects the CJK face at render time.

### Text measurement

`measure.py` measures in three tiers and never raises:

1. **fontTools** `hmtx` + `head.unitsPerEm` + `cmap` — exact advance widths (kerning ignored).
2. `matplotlib.ft2font`, but only if matplotlib is already imported or `GA_USE_FT2FONT=1`.
   Importing matplotlib costs ~20–50 s on this host, and both paths read the same OpenType tables, so
   the default path deliberately skips it to protect the 900 s budget.
3. A built-in Helvetica/Arial AFM width table (ASCII only).

Widths are computed at a 12 pt reference and scaled linearly, so results are independent of
accumulation order — a prerequisite for gate G to hold across processes.

### Fonts in the SVG

The SVG carries `family_css`, a real fallback chain built from the resolved family plus
`Helvetica Neue, Helvetica, Arial, Segoe UI, DejaVu Sans` and the CJK chain (`Microsoft YaHei,
SimHei, Noto Sans SC, Source Han Sans SC, PingFang SC, Hiragino Sans GB, WenQuanYi Zen Hei`), ending
in `sans-serif`, so the SVG opens on machines that lack the exact face used to lay it out. The
**PDF** is the format that must not depend on the viewer: gate H requires real embedded font
programmes in the PDF bytes.

## 4. Colour

* Default palette `okabe-ito` (8 colours, colour-vision-deficiency safe):
  `#0072B2 #D55E00 #009E73 #CC79A7 #E69F00 #56B4E9 #F0E442 #000000`.
* Alternative categorical palette `grayscale-safe`: `#1a1a1a #4d4d4d #808080 #b3b3b3`.
* Sequential cmaps for colorbars and heatmaps: `viridis`, `batlow`, `cividis`, `grey`.
* `palette.colors` overrides `palette.id` when present.

Accessibility is a **gate**, not a hope. Gate **C** checks that each **legend's** categorical colours
stay distinguishable (ΔE ≥ 6 under normal/protan/deutan/tritan), that grayscale ΔL\* ≥ 5, and that
text contrast is ≥ 4.5:1. Gate **D** separately checks that a data legend's item multiset equals the
data-category multiset, that a colorbar's `vmin`/`vmax` equal the data min/max, and that units are
present.

**Measured on the bundled fixture (authored spec, 7 colour groups):**

```
palette_normal_min_dE=26.43  palette_protan_min_dE=20.71
palette_deutan_min_dE=17.92  palette_tritan_min_dE=9.79      (palette itself, all >= 6.0)
categorical_groups=7
worst_CVD_min_dE=11.98(normal/P2.legend[0] #1a1a1a vs #333333, floor 6.0)
worst_gray_min_dL*=8.22(P2.legend[0] #0072B2 vs #D55E00, floor 5.0)
text_bg_pairs=105(backgrounds 47)  worst_contrast=8.47:1(fg=#444444 on bg=#EFEFEF, need>=4.5)
contrast_below=0
```

The `autospec` fallback on the same input measures `categorical_groups=3`,
`worst_CVD_min_dE=19.49`, `worst_gray_min_dL*=11.77`, `worst_contrast=8.38:1`, `contrast_below=0`.

Three lessons carried into any reuse, each learned from a real failure:

* **A legend's colours are compared pairwise, so duplicates fail.** The first version of this
  fixture gave five legend items the same `#333333`: gate C failed with `CVD dE 0.00 < 6.0` and
  `grayscale dL* 0.00 < 5.0`. A legend whose items are indistinguishable is not a key — the gate is
  right to reject it. The shipped fixture gives every item a distinct, measured-safe colour.
* **Colour-vision safety does not imply grayscale safety.** `#D55E00`/`#009E73` are both CVD-safe
  (palette tritan floor 9.79 ΔE) yet differ by only ΔL\* = 3.55, so they collapse in a grayscale
  print. Blue/orange raised the worst grayscale separation to 11.77 in an earlier revision; the
  shipped set measures 8.22.
* **Colour-vision safety does not imply contrast safety.** An earlier revision failed on
  `fg=#FFFFFF bg=#FFFFFF`: white text on a white page. The fix is to choose the text colour from the
  measured background luminance, not from a hardcoded default.

`text_bg_pairs=N (backgrounds M)` matters: gate C only checks text whose actual background it can
resolve, so a figure whose text sits on the uncoloured page background gets fewer checks — the detail
string publishes the count so coverage is auditable. On the frozen fixture: 105 pairs over 47
resolved backgrounds.

## 5. Determinism

Same spec → same bytes. `export.export_all` implements this as a **check on every build**: it
re-exports all requested formats into a scratch `.determinism_tmp/` directory inside the output dir,
compares sha256 per file, then removes the scratch dir. The result lands in
`export_report.determinism`:

```json
{"identical": true,
 "hashes": {"figure.svg": {"run1": "…", "run2": "…", "identical": true}, …},
 "identical_by_format": {"figure.svg": true, "figure.png": true, "figure.pdf": true}}
```

If the re-export throws, determinism is recorded as `false` with an `error` string — it is a check,
not a crash. `ar.py result` copies the block into `result.json.audit.determinism`, and gate **G**
re-runs the comparison as an independent gate.

Rules that keep this true: no RNG, no system time, no set/dict iteration order in output, and
`scene.stable_id(prefix, seed)` (sha1 of `prefix|seed`, first 8 hex) for ids.

**Measured (authored spec, 2026-11-23 16:20, after the `<text>`-positioning fix):** all three
artefacts byte-identical across the two exports and gate **G** `pass`:

```
figure.pdf run1=091a61d844551981 run2=091a61d844551981
figure.png run1=c6fa268a990cd220 run2=c6fa268a990cd220
figure.svg run1=3c88977cdab62973 run2=3c88977cdab62973
export_report_claims_identical=True
```

Independently of the gate, two `build` runs 3 s apart into two different output directories gave the
same three sha256 (`3c88977c…` / `c6fa268a…` / `091a61d8…`), i.e. determinism holds across processes
on the shipped tree, not only inside one build. Artefact sizes on that run: `figure.svg` 134,400 B,
`figure.png` 1,001,258 B, `figure.pdf` 1,111,949 B.

### Gate G's scope — and what it does *not* cover

`gate_g` re-exports an **already-built scene**: it reads `scene.json`, calls `export.export_all` into
`.determinism_check/`, and compares sha256 against the files already in the output directory. It
therefore proves that **the export backends are deterministic within a process**. It does **not**
re-run `ingest → spec → layout`, and it does not catch a value that varies with wall-clock time at a
granularity coarser than the two exports inside one build.

That gap is covered separately by `selftest.py`'s **`determinism-full-chain`** check, which runs the
whole pipeline twice in two fresh work directories and compares svg/png/pdf. It **passes** on the
shipped tree (`[PASS] determinism-full-chain  ingest->spec->build twice: identical svg/png/pdf`,
inside a full `selftest` run of **23/23, exit `0`**), after one intermittent failure earlier on
2026-11-23 (`differ=['figure.pdf']`) that has not recurred — the incident, its evidence and the two
candidate explanations are in [`failure-modes.md`](failure-modes.md) §6. Do not describe gate G as
covering the whole chain — it does not, and the two checks have deliberately different scopes.

## 6. The kind → style key (and why colours live in the legend)

Gate **K904** compares the set of `(kind, linestyle, colour)` triples a legend **declares** with the
set the scene **paints**. `layout.legend_kind_styles(panel)` feeds the legend's declared style back
into the edge resolver, so "the legend is the key" is literally true. The shipped fixture therefore
declares one legend per panel, covering exactly the kinds that panel renders:

| Panel | Legend title | kind | linestyle | colour |
|---|---|---|---|---|
| P1 apparatus | coupling kind | `material` | solid | `#0072B2` |
| | | `gas` | solid | `#4d4d4d` |
| | | `energy` | dashed | `#F0E442` |
| | | `heat` | dashed | `#E69F00` |
| | | `control` | dashdot | `#CC79A7` |
| P2 flow | stream kind | `fluid` | solid | `#0072B2` |
| | | `loop` | solid | `#D55E00` |
| | | `waste` | dashed | `#b3b3b3` |
| | | `branch` | solid | `#1a1a1a` |
| | | `merge` | solid | `#333333` |
| P3 route | route link | `sequence` | solid | `#0072B2` |
| P4 data | measured quantity | *(no `kind`; data legend)* | — | `#0072B2`, `#E69F00` |

The renderer's own fallback visuals (`layout.EDGE_VISUALS_FALLBACK`) are: `assembly` solid/no head,
`signal` dotted + dot head, `gas` solid + **open** head, `flow` **dashed**, `spatial` dotted,
`translocation` dashdot, `waste` dashed + `#808080`. A legend item's `linestyle`/`color` overrides
that fallback for the declared kind.

Measured: `K904=pass(legend_entries_with_kind=11 == rendered_styles=11)`.

### Colours: two legal forms (both re-verified)

`evidence._element_values` scans *every* string field of an element for printed numbers (see
[`provenance-and-evidence.md`](provenance-and-evidence.md) §3), which **used to** turn a hex colour
literal into a number: `#0072B2` parsed as `7.0`, so an explicit `edge.color` made gate **E** fail
with `value 7.0 is not present in the quote of evidence …`. **That false positive is fixed**
(`evidence.py` now recognises colour literals and skips them wholesale — `_COLOR_LITERAL` /
`_visual_literal`), and both authoring forms are legal:

| Form | How the connector gets its colour | Status |
|---|---|---|
| **Legend-driven** (what the shipped fixture uses) | declare `{label, kind, linestyle, color}` in `panels[].legend.items[]`; `layout.legend_kind_styles` propagates it to every edge of that kind | measured `K904=pass(11 == 11)` |
| **Explicit on the element** | put `color` on `panels[].edges[]`, or `fill` on a node | measured: 25 edges with a hex `color` plus one node with `"fill": "rgb(0, 114, 178)"` → `ar.py check` **exit `0`**, gate E `pass`, gate K `pass`, no failed gate |

The exemption is scoped to *visual* literals only — the value check itself is untouched. Measured
negative control on the same spec: changing one node's `value` to `999.9`, a number no cited quote
contains, gives `ar.py check` **exit `1`** with `failed=['E']` (module issue count 1, `E906`).
Reproduce script: `work/verify/t5/colour_regression.py` (`EXPECT positive check=0, negative check=1 -> OK`).

If you do declare an explicit colour, keep it **consistent with the legend** for that kind, otherwise
K904 reports a declared-vs-rendered mismatch. Two further consequences of the legend path, both
measured:

* a kind must appear in **exactly one** panel's legend, otherwise the same `(kind,linestyle,colour)`
  is declared twice while the scene paints it once, and K904 reports a count mismatch;
* a kind that appears in two panels with different colours produces two rendered styles, and every
  one of them must be declared — the practical solution is to give each panel its own kind
  vocabulary (`material` for the apparatus lines, `fluid` for the process streams) or to draw the
  stream once.

## 7. Export failure

A missing or broken backend is an **explicit error** (`export.ExportError`), never a silent skip: if
`svg_backend`/`raster_backend` cannot be imported, or a backend reports success without writing the
file, the export raises. `ar.py build` surfaces that as exit `2` and writes `build-error.json` rather
than producing a half-empty output directory. Unknown format names in `--formats` are ignored with a
warning recorded in `export_report.warnings`; a backend that reports `degraded` also appends a warning
instead of pretending everything is fine.
