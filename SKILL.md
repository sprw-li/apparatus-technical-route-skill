---
name: apparatus-technical-route
description: >-
  Author, validate and export a single-page apparatus-and-technical-route figure (实验装置图 / 装置示意图 / 工艺流程图 / 技术路线图)
  from the materials of a paper, protocol or process: extract the apparatus structure, the ordered process steps
  with their material flow, the phases of the technical route and the numbers that encode them; carry
  per-element verbatim provenance; then deterministically lay out and export an editable layered SVG plus
  PNG/PDF, run gates A-K and write result.json with an honest status and uncertainty. Use when the user asks for
  a 实验装置图, 装置示意图, 工艺流程图, 技术路线图, a 步骤顺序/材料流向 diagram, an apparatus schematic / process flow / technical route or
  workflow diagram, a P&ID-style rig drawing, 科研绘图, or any publication-ready figure that must keep an editable
  source file and trace every element to a real source. Do NOT use for writing, translating or polishing the
  paper text (abstract, introduction, discussion); do NOT use for statistical analysis, hypothesis testing or
  drawing conclusions from raw data; do NOT use for designing the experiment itself, choosing catalysts or
  writing a protocol. This Skill owns only what appears inside the figure, its topology, its layout, its
  editability and its export quality.
---

# Apparatus and technical-route figure (one page, editable source, print export)

Build **one page** that shows four things and keeps every one of them traceable to a real
material file:

1. **apparatus** — the components (vessels, pumps, reactor, sensors, separators, waste) and how
   they are physically coupled;
2. **flow** — the ordered process steps, including parallel branches, merges and recycle loops,
   with the direction of material, gas, energy and control streams;
3. **route** — the phases of the technical route and which phase depends on which;
4. **data** — the numbers that encode the conditions and outcomes (charts, values, units).

Everything else — text measurement, panel grid, arrow routing, colour, SVG/PNG/PDF generation,
gates A–K, `result.json` — is deterministic script work.

## What the LLM does vs. what the scripts do

Do not blur this split; it is the point of the Skill.

| Work | Who | Where |
|---|---|---|
| The science: which components, which ports mate, which steps are ordered / parallel / recycled, which phase depends on which, which numbers, which verbatim citation backs each element | **You (the agent / a human)** | authored into `spec.json` |
| Text measurement, wrapping, panel grid, arrow routing, colour application, SVG/PNG/PDF generation, gates A–K, `result.json` | **Deterministic scripts** | `scripts/*.py`, never hand-edited |

Corollary: you **never** hand-edit `figure.svg`, `figure.png` or `figure.pdf`. Change `spec.json`
(or `change_records` + `ar.py edit`) and rebuild. The same spec reproduces byte-identical
artefacts.

## Budget

64 model requests, 900 s wall clock, 16384 tokens per response. Plan on **one** ingest, one
authored spec with at most two repair loops, one build, one check, one result. Do not re-read
material you already ingested from disk — `materials.json` is the cache. Save an honest partial
early (`ar.py result --status partial`) and improve incrementally.

## Inputs

Read the real files before anything else. Do not infer content from a filename or a domain label.

```
/input/case.json          # case_id + output_contract (the JSON keys you must return)
/input/task.md            # what this case asks for
/input/materials/**       # the actual evidence: apparatus list, process description, tables,
                          # CSV/XLSX conditions, PDF pages, images
```

`case.json`'s `output_contract` names the keys `result.json` must carry; the `case_id` in
`case.json` must be the `case_id` you put in `spec.meta.case_id`. If a material is empty,
unreadable or missing, record it in `limitations` — do **not** substitute a plausible-looking
value.

## Procedure

### 1. Ingest

```
python3 scripts/ar.py ingest --input /input --work /app/work
```

Writes `/app/work/materials.json` (per-file text, `sha256`, line/row/page locators, parse
warnings) and `/app/work/evidence-ledger.json` (candidate claims with resolvable spans). Exit
`0` = ok, `2` = usage/IO. Read both before authoring.

### 2. Author `spec.json` — the science (the only creative step)

Full field reference, every validation code and a minimal valid example:
[`references/spec-schema.md`](references/spec-schema.md). The shape that matters here:

```json
{ "version": "1.1",
  "meta": {"case_id": "...", "workorder": "apparatus_and_technical_route",
           "orientation": "portrait", "language": "en",
           "canvas": {"w_mm": 240, "h_mm": 250, "dpi": 300},
           "layout": {"columns": 2, "row_order": ["apparatus","flow","route","data"]},
           "expected_relations": [{"from":"A1","to":"A2","kind":"material"}]},
  "palette": {"id": "okabe-ito"},
  "texts": {"caption": "..."},
  "evidence": [{"id":"E1","kind":"entity","claim":"...",
                "source":{"file":"apparatus-list.md","locator":"L8","quote":"<verbatim>"}}],
  "panels": [ {"id":"P1","role":"apparatus", "...": "nodes carry part/ports"},
              {"id":"P2","role":"flow", "sequence":[...], "nodes":[{"step_no":1}], "...":"..."},
              {"id":"P3","role":"route","sequence":[...], "phases":[{"depends_on":[]}]},
              {"id":"P4","role":"data", "...": "charts/legend"} ],
  "uncertainty": [], "limitations": [], "change_records": [] }
```

Rules the validator and the gates enforce:

* **Roles.** Recommended domain: `apparatus`, `flow`, `route`, `data`, `conditions`, `notes`. The
  legacy roles `problem`/`method`/`results`/`conclusion` are still legal. When
  `meta.workorder == "apparatus_and_technical_route"`, a figure with **none** of
  `apparatus`/`flow`/`route` earns the `W071` warning.
* **Apparatus nodes need a `part`** from the fixed enum (`tank`, `pump`, `reactor`, `column`,
  `sensor`, `separator`, `reservoir`, `condenser`, `heater`, `cooler`, `valve`, `mixer`,
  `junction`, `sample`, `reagent`, `waste`, `vessel`, `probe`, `flask`, `instrument`,
  `generic`) — gate **K901** fails otherwise. Declare `ports[{id,name,side,mate,source}]` and
  reference them from `edge.ports`; gate **K902** fails if an edge names a port its node does
  not declare, and **K905** only allows a self-loop for `loop`/`feedback`.
* **Flow/route panels declare `sequence` and `step_no`.** `step_no` must be `1..N` contiguous
  (**J902**); a *legal parallel repeat* is two nodes sharing one number (two membrane modules in
  parallel). `branch` groups need ≥2 nodes, `terminal` nodes must have no out-edge in that panel,
  `loop_to` must resolve (**J903**). Route `phases[].depends_on` must resolve and be acyclic
  (**J904**).
* **`meta.expected_relations` + `panels[].declared_edges`** are the declared topology. Gate
  **J906** checks every declared `(from,to,kind)` really is drawn — and fails on a *reversed*
  pair, which is how a drawn-backwards material stream is caught.
* **Edge kinds.** `material`/`fluid` (solid + filled head), `gas` (solid + open head), `energy`/
  `heat` (dashed), `signal` (dotted), `control` (dash-dot), `assembly`, `sequence`, `branch`,
  `merge`, `loop` (return line), `waste` (dashed grey). Legacy kinds (`activation`, `inhibition`,
  `flow`, `spatial`, `feedback`, `translocation`) remain legal.
* **Colour can come from the legend or from the element — but it must agree.** The recommended form
  is `{label, kind, linestyle, color}` items in the panel legend: the renderer uses them as the key
  for that kind, and gate **K904** compares the declared `(kind, linestyle, colour)` set against what
  the scene really paints. An explicit `color` on an edge (or `fill` on a node) is equally legal —
  colour literals are exempt from the number-in-quote check (`E906`) — but it must match the legend
  for that kind or K904 reports a mismatch. Give every legend item a distinct, colour-vision-safe
  colour: gate **C** measures ΔE under protan/deutan/tritan (≥ 6), grayscale ΔL\* (≥ 5) and text
  contrast (≥ 4.5:1), and identical swatch colours fail immediately.
* **Units.** Every chart carries a `unit`; a colorbar's `vmin`/`vmax` must equal the encoded data
  range (gate **D**).
* **Canvas** 20–1000 mm per side, `dpi` 72–1200, margins leaving a drawing area. The canvas is a
  **minimum** — the layout may grow the page to fit the content; read the resolved value from
  `export_report.page_mm`, never assume your declaration was kept.

Validate the spec **before** building — it is free and catches every `E*` error:

```
python3 -c "import json,sys; sys.path.insert(0,'scripts'); import scene; \
s=json.load(open('/app/work/spec.json',encoding='utf-8')); \
[print(i['severity'],i['code'],i['path'],i['message']) for i in scene.validate_spec(s)]"
```

Empty output = zero errors and zero warnings.

### 3. Build (deterministic)

```
python3 scripts/ar.py build --spec /app/work/spec.json --out /app/output --dpi 300
```

Emits `figure.svg` (layered, named `<g id>`, real `<text>`), `figure.png` (300 dpi sRGB, `pHYs`
dpi), `figure.pdf` (1 page, vector, embedded TrueType), plus `export_report.json`,
`figure_spec.resolved.json` and `scene.json`. Exit `4` = illegal spec (with `spec-issues.json`
written into `--out`), `3`/`2` = IO/usage.

### 4. Write `result.json`

```
python3 scripts/ar.py result --out /app/output --input /input --work /app/work
```

Do this **before** `check`: gate **I** reads `result.json`, so a `check` with no result present
reports gate I as failed. `result` merges every `case.json.output_contract` key with the real
run: `case_id`, `status`, `artifacts`, `sources`, `evidence`, `change_records`, `uncertainty`,
`limitations`, `audit`, `runtime`. A contract key with no direct mapping is filled with a truthful
run summary and **disclosed** in `audit.unmapped_contract_keys`; only a genuinely unfillable key
lands in `audit.unfilled_fields` and forces `status: partial`.

Run it early even if the figure is unfinished — it is the cheapest partial deliverable.

### 5. Check the gates

```
python3 scripts/ar.py check --out /app/output --spec /app/work/spec.json --work /app/work
```

Runs gates **A–K** and writes `validation_report.json` (`checks[]`, `failed[]`, `warned[]`).
Exit `0` = all pass, **exit `1` = at least one gate failed**, `3` = artefacts missing,
`4` = bad spec. Then re-run `ar.py result` so the recorded `status`/`audit` reflect the verdicts —
a green `check` followed by `result` is what yields `status: "ok"`.

| Gate | Proves |
|---|---|
| **A** | every element's bbox is on the canvas with ≥ `margin_mm` (a page-sized `frame` background is exempt and reported as exempt) |
| **B** | font sizes ≥ floor (body 7 pt, panel title 8 pt, main title 11 pt), measured text fits its box, no missing glyphs, no overflow, no truncated labels |
| **C** | categorical colours stay distinguishable under protan/deutan/tritan simulation (ΔE ≥ 6), grayscale ΔL\* ≥ 5, text contrast ≥ 4.5:1 (≥ 3.0:1 for large text) |
| **D** | legend entries == data categories (multiset), colorbar range == data min/max, units present, **rendered arrow kinds/counts == spec edge kinds/counts**, linestyle/direction agreement |
| **E** | every `spec.evidence[].source` resolves to a real span and the `quote` matches **verbatim**; every node/edge/series/step/phase/port with a `source` uses an existing id (`E903`/`E904`/`E905`); every number the element would print occurs in its cited quote (`E906`), or its declared `source_values` do when `derived` (`E907` warns when they are missing) |
| **F** | SVG text is real `<text>`, groups are named, ids unique, not one flattened bitmap, every spec label present, and `patch_svg_text` round-trips |
| **G** | re-exporting the **already-built scene** gives identical sha256 for **each** of SVG/PNG/PDF (export scope only — `ar.py selftest` covers the whole chain) |
| **H** | PNG ≥ 300 dpi and pixel size == page × dpi; PDF is 1 page, vector, fonts embedded; the reported page equals the requested one |
| **I** | every `output_contract` key is non-empty and `artifacts` point at real files (paths, bytes, sha256 re-checked) |
| **J** | **topology and order**: `J901` sequence ids resolve, `J902` `step_no` contiguous 1..N, `J903` `loop_to`/`branch`/`terminal` consistent, `J904` `phases[].depends_on` acyclic, `J905` rendered edge endpoints resolve, `J906` declared `(from,to,kind)` drawn and not reversed |
| **K** | **apparatus semantics and legend consistency**: `K901` apparatus nodes carry a legal `part`, `K902` edge ports exist on their nodes, `K903` merge in-degree ≥ 2 / branch out-degree ≥ 2 / waste target `part == "waste"`, `K904` legend `(kind,linestyle,colour)` set == rendered set, `K905` self-loops only for `loop`/`feedback` |

`warn` never fails `check` — read `validation_report.json` and `result.json.audit.checks_warned`
rather than trusting the exit code alone.

### 6. One-shot form

```
python3 scripts/ar.py run --input /input --work /app/work --out /app/output
```

Runs `ingest → (your spec.json if present, else deterministic autospec) → build → result → check
→ result`, and returns the **check** exit code. It writes `result.json` before the gates because
gate I validates it, then rewrites it so `status` reflects the real outcomes. Use it when you are
out of budget: `autospec` always yields a valid, honestly-limited spec, so the case still produces
artefacts. It is a floor, not the target — an authored spec is what earns the quality points.

### 7. Verify the Skill itself

```
python3 scripts/ar.py selftest --quick    # end-to-end + bundle budget, no negative phase
python3 scripts/ar.py selftest            # full: determinism + injected-defect negatives
python3 scripts/contract_matrix.py        # adversarial output_contract key sets
python3 scripts/gain_check.py             # the measured 使用增益 A/B
```

All four exit `0` on the shipped bundle (measured 2026-11-23 16:2x–16:3x: `selftest --quick` 11/11
in 25.5 s; full `selftest` **23/23 in 233.5 s**, where the in-harness contract check is the
`--quick` 4-key-set subset; standalone `contract_matrix` **10/10 in 260.6 s**; `gain_check` quick
**0/5 vs 5/5 in 40.2 s**). `contract_matrix` matters most for an **unseen** case: the evaluator's
case may name its outputs anything, and an unknown contract key is filled with a truthful run
summary and disclosed rather than silently emptied. `gain_check` measures defect interception — a
defect counts only when a **failing gate** stops the figure, never when it is merely warned about
(`B_warn_only` is reported separately) — and it is **not** a model-quality benchmark.

## When a gate fails

Never "fix" the figure by editing an export. Read `validation_report.json` and act on the cause:

| Symptom | Exit | Do this |
|---|---|---|
| Spec rejected structurally | `4` | Read `spec-issues.json` (in `--out` for `build`, next to the output spec for `autospec`/`edit`), fix `spec.json`, rebuild. |
| **A** element off-canvas | `1` | Remove a node from an overcrowded panel, reduce `meta.layout.columns`, or raise the declared canvas. |
| **B** text overflow / too-small font | `1` | Shorten `label`/`sublabel`; drop a node from an overcrowded panel; drop edge labels that crowd nodes (`W_EDGE_LABEL_TIGHT` in `export_report.scene_warnings` is the early warning). Never shrink below 7 pt. |
| **C** colour | `1` | Give every legend item a **distinct** CVD-safe colour (duplicated swatch colours fail with ΔE 0.00); use `palette.id: "okabe-ito"`; keep ≤ ~6 items per legend. |
| **D** encoding mismatch | `1` | Make legend `items` exactly the chart series names; set `colorbar.vmin/vmax` to the real data range; add the missing `unit`. |
| **E** provenance | `1` | Three distinct causes: an element has no `source` (`E903`) → add one; an id does not exist (`E904`) → fix it; a **value is not in its quote** (`E906`) → find material that really contains that number, remove the number, mark it `derived: true` with real `source_values`, or record the gap under `limitations`/`uncertainty`. **Do not invent a quote and do not change the number to match the quote.** Numbers are also read out of labels/sublabels, so a decorative number in a sublabel needs to be in that element's quote too. |
| **F** editability | `1` | The build is broken — rebuild; if it persists report it, do not rasterise. |
| **G** determinism | `1` | A non-deterministic input leaked into the **export** step (system time, `/ID`, dict order, RNG). Remove it; report if it is in the code. Gate G only re-exports an existing scene — run `ar.py selftest` for the whole chain. |
| **H** export | `1` | Rebuild; if fonts are the cause, ensure a CJK-capable font is installed and record the fallback in `limitations`. |
| **I** contract | `1` | Check `case.json.output_contract` key names; drop any `--status` override and re-run `result`. |
| **J** topology | `1` | Fix `sequence` ids, make `step_no` contiguous 1..N, declare the parallel repeat, break the `depends_on` cycle (the report prints the cycle path), or make `declared_edges`/`expected_relations` match what is really drawn (including direction). |
| **K** apparatus/legend | `1` | Give every apparatus node a legal `part`; declare the named port on the node; fix merge/branch degrees; make the declared `(kind, linestyle, colour)` set (legend items and/or explicit element colours) exactly the rendered set. |
| Artefacts missing | `3` | Run `build` before `check`/`result`. |
| Module/usage error | `2` | Check the CLI against `ar.py <cmd> --help`; a render crash writes `build-error.json` into `--out`. |

If after two repair loops a gate still fails, **stop and ship honestly**: run
`ar.py result --status partial`, put the exact failing gate id and reason into `uncertainty`, and
tell the user what is unresolved. A partial result that names its limits scores; a silent
fabrication does not.

## Do not fabricate (hard rule)

The evidence ledger is the contract between the figure and reality:

* **Every component, stream, step, phase, port, number and unit that reaches the page carries a
  `source`.** Gate E fails mechanically: `E903` (no source at all), `E904`/`E905` (dangling or
  unresolvable citation), `E906` (a printed number is not literally present in the cited quote),
  `E907` (declared `derived` without `source_values`).
* If a material does not contain the value you need, you may **not** supply one. Omit it, or state
  the gap in `limitations`/`uncertainty`.
* Never invent a component, a port, a connection direction, a step order, a phase dependency, a
  flow rate, a temperature or a unit; never restate a number you did not read; never let a
  placeholder survive into the output.
* Never present the bundled synthetic fixture, or any rendered example, as an official case
  result. Never claim a benchmark score or a runtime you did not measure.
* When material is missing, ambiguous or contradictory, say so in `uncertainty` and set `status`
  to `partial` (or `needs_human`); that is a correct, gradeable outcome.

## Revision without redrawing

```
python3 scripts/ar.py edit --spec /app/work/spec.json --edits edits.json --out /app/work/spec2.json
python3 scripts/ar.py build --spec /app/work/spec2.json --out /app/output
```

`edits.json` is a list of structured ops (`set_label`, `retitle_panel`, `set_text`,
`recolor_series`, `set_node_color`, `set_colorbar`, `move_panel`, `reorder_panels`, `add_node`,
`remove_node`, `add_edge`, `remove_edge`, `set_limitations`); an unknown target is skipped with a
reason instead of destroying the figure. `edit` records every change in `change_records`, keeping
provenance and stable ids. Prefer it over retyping the spec: it preserves the edit history that
the rubric's verifiability point asks for, and it is what "editable source, source-preserving edit"
means in practice.

## Reference files

| File | Read it for |
|---|---|
| [`references/spec-schema.md`](references/spec-schema.md) | every `spec.json` field, its validation code and allowed values |
| [`references/runbook.md`](references/runbook.md) | the exact command sequence, exit codes, budget plan, recovery |
| [`references/provenance-and-evidence.md`](references/provenance-and-evidence.md) | how evidence, locators, gate E and the ledger work |
| [`references/exports-fonts-colour.md`](references/exports-fonts-colour.md) | canvas/dpi/sRGB/font-embedding/colour-accessibility detail, incl. the kind→style table |
| [`references/failure-modes.md`](references/failure-modes.md) | observed behaviour for each failure class (exit code, gate, `result.json`) |
| [`references/measured-gain.md`](references/measured-gain.md) | the measured A/B for 使用增益 — defect interception and delivered verification artefacts, and what it does **not** measure |
| [`references/rubric-mapping.md`](references/rubric-mapping.md) | which artefact + command proves each scoring point |
| [`README.md`](README.md) | dependencies, install, reuse, licence, resource budget |
| [`examples/README.md`](examples/README.md) | the worked synthetic example and its rendered artefacts |
