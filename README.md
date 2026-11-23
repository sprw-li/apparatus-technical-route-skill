# apparatus-technical-route — a deterministic Skill for apparatus and technical-route figures

Turn the materials of a paper, protocol or process into **one** page that shows the **apparatus
structure**, the **ordered process steps with their material flow**, the **phases of the technical
route** and the **data that encodes them** — with every component, stream, step, phase and number
traceable to a real source file, and both an **editable layered source** and **print-ready
exports**.

* `SKILL.md` — what an Agent loads and follows.
* `scripts/` — the deterministic pipeline (`ar.py` CLI + modules).
* `references/` — the deep documentation (schema, runbook, provenance, exports, failures, rubric).
* `examples/` — a worked **synthetic** example (clearly not an official case).

The design rule: **the LLM authors the science into `spec.json`; the scripts do all geometry,
typography, export and checking.** Same spec in → byte-identical artefacts out.

---

## 1. Requirements and dependencies

The **core is stdlib-only** (`scene.py`, `ar.py`, `export.py`, `edit.py`, `domain.py` import
nothing outside the Python standard library). Optional third-party packages unlock accuracy or
extra input formats; every one of them degrades gracefully when absent.

| Package | Version verified here | Needed for | If missing |
|---|---|---|---|
| Python | **3.12.14** (tested); code targets 3.8+ | everything | — |
| `matplotlib` | 3.11.2 | `ft2font` text metrics; bundled DejaVu Sans as the last-resort face | `measure.py` uses `fontTools`, then a built-in Helvetica AFM width table |
| `fontTools` | 4.68.0 | exact advance widths; glyph/cmap coverage | metrics fall back to the AFM table; glyph check falls back to ASCII-only |
| `Pillow` (PIL) | 13.0.0 | PNG raster backend (PNG writing, `pHYs` dpi) | PNG export is unavailable; SVG + PDF still work |
| `openpyxl` | 3.1.5 | `.xlsx`/`.xlsm` material extraction | `ingest.py` falls back to raw OOXML parsing |
| `pypdf` | 7.1.1 | PDF text extraction (first choice) | next extractor in the cascade is tried |
| `pdfminer.six` | 20260107 | PDF text extraction (second choice) | next extractor tried, then the raw Flate/`BT…ET` fallback |
| `PyPDF2` / `PyMuPDF (fitz)` | not installed here | alternative PDF extractors | cascade order is explicit; absence is recorded, not fatal |

PDF extraction is a **four-deep cascade** (`pypdf → PyPDF2 → pdfminer.six → PyMuPDF`) with a
stdlib raw-stream fallback; the extractor actually used is recorded per material as
`pdf_extractor` + `parse_reason`.

Install the optional extras:

```
python3 -m pip install matplotlib fontTools Pillow openpyxl pypdf pdfminer.six
```

Nothing else is needed. There is **no** service, network call, credentials file or hand-editing
step anywhere in the pipeline.

## 2. Install

Copy the whole Skill directory to the location the runtime uses, e.g. `/skills/weekly-skill/`,
preserving `SKILL.md`, `scripts/*.py`, `references/*.md` and `examples/**`. No build step, no
packaging, no compilation. From any shell:

```
python3 /skills/weekly-skill/scripts/ar.py --help
```

The code is portable; no absolute path is baked into any script — every path is resolved from CLI
arguments or from the input/output directories. On Windows use the `py`/`python` launcher instead
of `python3`, and set `GA_USE_FT2FONT=1` only if you want to force the `ft2font` measurement path
(by default the Skill deliberately avoids importing matplotlib's package init, which costs ~20–50 s
on a cold interpreter and would eat the run budget for no accuracy gain).

## 3. Quickstart

Place `case.json`, `task.md` and the material files under the case input directory, then:

```
python3 scripts/ar.py ingest   --input /input      --work /app/work
#   ... author /app/work/spec.json from materials.json + evidence-ledger.json (the LLM step) ...
python3 scripts/ar.py build    --spec /app/work/spec.json --out /app/output --dpi 300
python3 scripts/ar.py result   --out /app/output --input /input --work /app/work   # BEFORE check: gate I reads result.json
python3 scripts/ar.py check    --out /app/output --spec /app/work/spec.json --work /app/work
python3 scripts/ar.py result   --out /app/output --input /input --work /app/work   # re-run so status/audit reflect the gates
```

**The order is `build → result → check → result`, not `build → check → result`.** Gate **I**
validates `result.json`, so running `check` before `result` makes gate I report
`result.json missing … -> contract UNVERIFIABLE` and exit `1` even when every other gate passed.

Measured on the bundled fixture (2026-11-23 16:20 +08:00, `examples/synthetic-001`, this repo):
`ingest` exit `0` (5 material(s), 60 ledger item(s), `case_id=SYNTHETIC-AR-001`), `build` exit `0`,
`result` exit `0`, `check` **exit `0`** (11 gates, **0 failed, 0 warn**), final `result`
exit `0` with **`status: "ok"`**. Whole sequence: **31 s wall**, well inside the 900 s budget.

A `result` run *before* the gates is still useful and honest: it reports `status: "partial"` with a
`not_validated` uncertainty entry saying the artefacts have not been gated yet.

One-shot, with the deterministic no-LLM fallback:

```
python3 scripts/ar.py run --input /input --work /app/work --out /app/output
```

`run` uses `/app/work/spec.json` when it exists, otherwise derives one with `autospec`, then builds,
checks and writes `result.json` — and exits with the **check** exit code. It guarantees artefacts
but not quality; an authored spec is what the rubric rewards.

## 4. CLI reference

All flags below were taken from `python3 scripts/ar.py <cmd> --help`.

| Command | Arguments | Writes |
|---|---|---|
| `ingest` | `--input DIR --work DIR` | `work/materials.json`, `work/evidence-ledger.json` |
| `autospec` | `--work DIR [--input DIR] --out SPEC` | deterministic fallback `spec.json` (`--input` needed only if `materials.json` is absent) |
| `build` | `--spec SPEC --out DIR [--work DIR] [--formats svg,png,pdf] [--dpi 300]` | `figure.svg`, `figure.png`, `figure.pdf`, `export_report.json`, `figure_spec.resolved.json`, `scene.json` |
| `check` | `--out DIR [--spec SPEC] [--work DIR]` | `validation_report.json` (gates A–K) |
| `result` | `--out DIR [--input DIR] [--work DIR] [--status ok\|partial\|needs_human]` | `result.json` |
| `edit` | `--spec SPEC --edits EDITS.json --out SPEC2` | edited spec + `change_records` (− `spec-issues.json` on error) |
| `run` | `--input DIR --work DIR --out DIR [--formats ...]` | the whole chain |
| `selftest` | `[--quick]` | end-to-end self-test: full-chain determinism, contract matrix, injected-defect negatives |

`check` looks for the spec at `--spec`, else `OUT/figure_spec.resolved.json`; `result` needs
`OUT/figure_spec.resolved.json` to exist (i.e. run `build` first), and gate I needs `result.json`
to exist (i.e. run `result` before `check`).

Two further bundled scripts are not `ar.py` subcommands (run them directly):

| Script | What it does |
|---|---|
| `scripts/contract_matrix.py` | adversarial test of unknown `output_contract` key names: builds several cases (plain / exotic / colliding / terse-CJK / no contract) and asserts every declared key comes back non-empty with `status:"ok"` and the `case_id` from `case.json` |
| `scripts/gain_check.py` | the controlled A/B that measures 使用增益: `build` only vs the full pipeline, plus injected authoring defects — see [`references/measured-gain.md`](references/measured-gain.md) |

### `output_contract` key mapping

The case schema is not published, so a case may name its outputs anything. `ar.py` maps keys by
**ordered, precise rules** and never returns `None` for an unknown key:

1. keys containing `status` are deferred and filled with the computed status **after** it is known;
2. the provenance/verification family is matched **first** (`evidence`, `provenance`, `source`,
   `citation`, `reference`, `trace` → the evidence ledger; `validation`, `check`, `audit`, `gate`
   → the gate results), *before* any artefact-name matching;
3. artefact families (`svg`/`editable`, `png`/`preview`/`render`/`raster`, `pdf`/`export`/`print`,
   `spec`/`scene`/`layout`);
4. prose (`caption`, `conclusion`/`summary`/`answer`, `title`) and structured content
   (`panel`/`chart`/`data`/`series`);
5. anything still unmatched receives a **truthful run summary** (a `note`, the `case_id`, the
   primary artefact, the artefact list, panel ids, evidence count) and its key is listed in
   **`result.json.audit.unmapped_contract_keys`** — so an indirect fill is disclosed rather than
   passed off as a direct mapping.

Measured on the bundled fixture, whose `case.json` deliberately asks for three workorder-specific
keys that have no direct mapping: `audit.unmapped_contract_keys ==
["apparatus","process_flow","technical_route"]`, `audit.unfilled_fields == {}`, gate I
`hard_empty=0, soft_empty=0`, final `status: "ok"`.

### Exit codes

| Code | Meaning | Emitted by |
|---|---|---|
| `0` | success / all gates passed (warns still `0`) | all commands |
| `1` | at least one validation gate failed | `check`, `run` |
| `2` | usage / IO error (bad flags, missing input dir, missing module, render crash → `build-error.json`) | all commands |
| `3` | required artefact missing (e.g. `check`/`result` before `build`) | `check`, `result` |
| `4` | `spec.json` is illegal (structural errors from `scene.validate_spec`) | `autospec`, `build`, `check`, `edit` |

## 5. Inputs and outputs

**Input** (`/input`): `case.json` (its `output_contract` names the JSON keys to return), `task.md`,
and material files under `/input/materials/**` (`.md`, `.txt`, `.csv`, `.tsv`, `.json`, `.xlsx`,
`.pdf`, images).

**Output** (`/app/output`):

| File | Kind | What it is |
|---|---|---|
| `figure.svg` | editable source | layered SVG: named `<g id>`, real `<text>`, `data-*` attributes, `<metadata>` |
| `figure_spec.resolved.json` | editable source | the spec actually used (the round-trip starting point) |
| `scene.json` | intermediate | the layout result: primitives with mm bboxes |
| `figure.png` | export | 300 dpi sRGB raster, `pHYs` dpi recorded |
| `figure.pdf` | export | 1-page vector PDF with embedded font programmes |
| `export_report.json` | record | measured page/dpi/px, PDF page count/fonts/vector, SVG node counts, determinism hashes, scene warnings |
| `validation_report.json` | record | gates A–K with `checks[]`, `failed[]`, `warned[]` |
| `result.json` | record | the structured case result (below) |

### `result.json`

Carries `case_id`, `status` (`ok` / `partial` / `needs_human`), `scope`, `artifacts` (path, bytes,
sha256), `sources` (each material + sha256), `evidence` (per-claim source + resolution),
`contract_values`, every key named by the case's `output_contract`, `change_records`,
`uncertainty`, `limitations`, and `audit` (`unfilled_fields`, `unmapped_contract_keys`,
`checks_ok`, `checks_failed`, `checks_warned`, `determinism`, `font`), plus `runtime` (python,
platform, scene version, dpi).

Measured on the bundled fixture: `status "ok"`, 7 artifacts with sha256 (6 on disk + the
self-written `result.json`), `sources` 6, `evidence` 60 (the whole ingest ledger), `uncertainty` 1,
`limitations` 2, `change_records` 0, `runtime.skill = "apparatus-technical-route (ar.py)"`.
`status` can be `ok` only when a `validation_report.json` actually exists — a `result` run before
the gates reports `partial` with a `not_validated` uncertainty entry. An explicit `--status` can
only ever **lower** the automatic status.

> The `runtime` and `font.paths` blocks of a real run record the **host that produced the
> artefacts** (here `C:\WINDOWS\Fonts\arial.ttf` etc.). That is evidence, not a configuration
> requirement: fonts are resolved from an ordered candidate list at build time and the fallback is
> disclosed in `export_report.font`.

## 6. Export parameters

| Parameter | Value |
|---|---|
| Page | **default** 180 × 120 mm (single page, two-column journal width); the bundled example declares 240 × 250 mm and the layout resolves it to 240 × 250 mm |
| Units | mm, origin top-left, +y down; fonts in pt |
| Raster DPI | 300 |
| PNG size | page × dpi — 2126 × 1417 px for the default page, **2835 × 2953 px measured** for the example |
| Colour space | sRGB |
| PDF | 1 page, vector text, embedded TrueType; MediaBox = page in pt — 510.236 × 340.157 pt (default), **680.315 × 708.6614 pt measured** (example) |
| SVG | layered and named; text remains real `<text>` — measured 112 `<text>` nodes (all carrying `x`/`y`), 7 named `<g>`, 0 `<image>`, 134,400 B |
| Determinism | verified per artefact by re-exporting and comparing sha256 — **all three formats identical** on the frozen run (gate G passes) |

Full detail, including how each property is measured from the artefact bytes, the font-resolution
order and the **kind → linestyle → colour** key the example uses:
[`references/exports-fonts-colour.md`](references/exports-fonts-colour.md).

## 7. Worked example

See [`examples/README.md`](examples/README.md). The bundled case `examples/synthetic-001/` is
**synthetic and labelled as such** (a bench-scale photocatalytic oxidation rig) — it exists to
demonstrate the interface end-to-end, not to stand in for an official case.
`examples/synthetic-001/expected/` holds `spec.json` (v1.1, 0 errors) plus, from the real run in
which **all eleven gates pass**, the generated `figure.svg` and the `result.json`
(`status: "ok"`). The PNG and PDF are not stored (every bundle file must be UTF-8 text); their
measured properties and sha256 are quoted in `examples/README.md` and
[`references/rubric-mapping.md`](references/rubric-mapping.md).

## 8. Reuse guide

To build a figure for your own case:

1. **Copy the case skeleton**: `cp -r examples/synthetic-001 /tmp/mycase`, then replace
   `input/materials/**` and `input/case.json`. Keep `output_contract` — it is what the evaluator
   reads back.
2. **Run `ingest`** and read `materials.json`. Every locator you will quote lives here; do not
   invent line numbers.
3. **Copy `expected/spec.json` as your template** and rewrite it section by section:
   `meta.case_id`/`workorder`, the panels' `role`/`title`/`sequence`/`phases`, each node's
   `label`/`sublabel`/`part`/`ports`/`step_no`, each edge's `kind`/`ports`, the legend items that
   name a `kind`, the chart series, and one `evidence[]` item per claim. Keep the canvas and palette
   unless the case demands otherwise.
4. **Rebuild and re-check** until `check` exits 0.
5. **Reuse the gates**: `check` is case-independent, so it is also your regression suite. Add a case
   to `examples/` only if it is synthetic or fully publishable.

Rendering templates, SVG layer names and the gate list are reusable as-is; the only thing that is
case-specific is `spec.json` and the materials it cites.

## 9. Resource budget

The platform allows **≤ 50 UTF-8 text files, ≤ 500 KB each, ≤ 2 MB total, no symlinks**. Measured
on this bundle (sampled 2026-11-23 16:41 +08:00; the numbers move while the scripts are being
edited in parallel, so treat them as a reading, not a constant; the official submission validator
reported the same totals):

```
files=36  total=1,169,134 B (1.12 MB of the 2 MB cap)
largest=scripts/layout.py 145,913 B (of the 500 KB per-file cap)
```

`ar.py selftest --quick` prints the same budget check as its `bundle-budget` line, so it is
re-verified on every run. Re-measure with:

```
python3 -c "import os; fs=[os.path.join(d,f) for d,_,g in os.walk('.') for f in g \
if '__pycache__' not in d]; print(len(fs), sum(os.path.getsize(f) for f in fs), \
max((os.path.getsize(f),f) for f in fs))"
```

(run from the submission root). Only UTF-8 **text** ships in the bundle: no PNG/PDF binaries, no
caches, no symlinks. Rendered binaries are described in prose with their measured properties and
sha256.

## 10. Maintenance

* **Frozen interfaces.** `scene.py` (data model + validation), the CLI surface in `ar.py`, and the
  artifact names are the contract. Changing one means updating `references/spec-schema.md` and
  `references/runbook.md`.
* **Add a validation gate** by adding a check to `validate.py` and a row to the gate table in
  `SKILL.md` and `references/rubric-mapping.md`. Never add a gate that cannot produce a
  pass/fail for a concrete artefact.
* **Negative-test first.** `python3 scripts/ar.py selftest` runs the whole chain plus
  injected-defect cases, so a change that only makes the happy path pass is caught.
* **Determinism is a regression target**, not a hope: any build prints
  `export_report.determinism.identical`. If it turns false, stop and fix the cause.
* **Updating the docs**: every command you document must be a command you ran. Quote exit codes and
  measured numbers; label anything unverified as unverified.

## 11. Licence and attribution

* **Original work.** The Skill's scripts, schemas, references and example fixture were written for
  this submission. No third-party source code is vendored into the bundle.
* **Third-party use is by import only** (matplotlib, Pillow, fontTools, openpyxl, pypdf,
  pdfminer.six), under their own licences; they are optional dependencies and are not redistributed
  here.
* **Data standards reused**: the categorical palette ids follow the Okabe–Ito colour-vision-
  deficiency-safe palette (Okabe & Ito, *Color Universal Design*, 2008); the
  `viridis`/`cividis`/`batlow` cmap stop values follow their published definitions (viridis is
  public domain/CC0; cividis is public domain). Colormap *names* and stop values are reused, not
  library code.
* **Font metrics**: the built-in fallback width table in `measure.py` is the publicly published
  Helvetica/Arial AFM advance-width data (metrics are not copyrightable); no font file is
  redistributed — faces are resolved from the host system or matplotlib's bundled DejaVu.
* **The bundled example is synthetic.** `examples/synthetic-001` is invented material, labelled
  `SYNTHETIC EXAMPLE - NOT AN OFFICIAL CASE` in its `case.json`, `task.md`, materials and spec. It
  is not a measurement and must never be cited as one.
* **No benchmark claim.** No score, runtime or comparison against a baseline Agent is claimed
  anywhere in this bundle.

## 12. Documentation map

| File | Read it for |
|---|---|
| [`SKILL.md`](SKILL.md) | the Agent-facing procedure |
| [`references/spec-schema.md`](references/spec-schema.md) | every `spec.json` field + validation code |
| [`references/runbook.md`](references/runbook.md) | command sequence, budget plan, recovery |
| [`references/provenance-and-evidence.md`](references/provenance-and-evidence.md) | evidence ledger, locators, gate E |
| [`references/exports-fonts-colour.md`](references/exports-fonts-colour.md) | export/font/colour detail + the kind→style key |
| [`references/failure-modes.md`](references/failure-modes.md) | observed behaviour of each failure class |
| [`references/rubric-mapping.md`](references/rubric-mapping.md) | scoring point → artefact → proving command |
| [`references/measured-gain.md`](references/measured-gain.md) | the measured A/B for 使用增益, and what it does **not** measure |
| [`examples/README.md`](examples/README.md) | the worked example |
