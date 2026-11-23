# Examples

This directory demonstrates the Skill end to end on a **synthetic** fixture.

> ## ⚠️ SYNTHETIC EXAMPLE - NOT AN OFFICIAL CASE
> `synthetic-001` is invented material: a fictional **bench-scale photocatalytic oxidation rig** and
> its technical route, whose numbers were made up to exercise the pipeline. It must never be
> presented or cited as a real measurement, and nothing here is an official challenge case or an
> official result.

## What is in here

```
examples/
├── README.md                     <- you are reading it
└── synthetic-001/
    ├── input/                    <- the case as the runtime would receive it
    │   ├── case.json             <- case_id + output_contract (what result.json must return)
    │   ├── task.md               <- the workorder, labelled SYNTHETIC
    │   └── materials/
    │       ├── apparatus-list.md <- 装置清单: components, parts, ports, couplings, with line locators
    │       ├── process-flow.md   <- 工艺流程 + 技术路线: 8 ordered steps, parallel/recycle streams,
    │       │                       4 route phases with depends_on
    │       └── conditions.csv    <- the "source data" table (8 runs, row locators)
    └── expected/                 <- outputs of a real run of this Skill on the input above
        ├── spec.json             <- the editable source: the authored, validated spec (v1.1)
        ├── figure.svg            <- the editable rendered source (UTF-8 text)
        └── result.json           <- the structured case result produced by `ar.py result`
```

Only **UTF-8 text** ships in this bundle, so the raster/vector binaries are not stored here. See
"Rendered exports" below for their measured properties and sha256.

## The fixture is a complete, checkable unit

It is deliberately small but exercises every part of the contract:

* all four panels — **apparatus** (11 nodes, 10 coupling edges), **flow** (9 nodes, 12 stream edges),
  **route** (4 nodes, 3 order edges, 4 `phases` with a `depends_on` chain), **data** (4 nodes, 1
  grouped bar chart, 1 data legend) — on a canvas declared 240 × 250 mm and resolved to
  **240 × 250 mm**;
* **28 nodes / 25 edges** spanning **eleven edge kinds**: `material`×6, `fluid`×4, `sequence`×3,
  `loop`×2, `waste`×2, `branch`×2, `merge`×2, `gas`, `energy`, `heat`, `control`;
* apparatus semantics: **11 nodes carry a legal `part`** (`tank`, `pump`, `mixer`, `reactor`,
  `instrument`×2, `sensor`, `heater`, `separator`, `reservoir`, `waste`) and **8 edge port
  references** resolve against the ports declared on `A1`, `A2`, `A4`, `A5`, `A6`, `A8`, `A12`;
* a real recycle loop (membrane retentate → feed reservoir), a two-module **parallel branch**
  (`branch` group `B_MEM`) and a **merge** back into the permeate line, with `loop_to` and
  `terminal` declared;
* **40 evidence items**, each with a verbatim `quote` and a resolvable `locator` (`L11` for markdown
  lines, `row 4` for CSV rows), including one **`derived: true` + `source_values`** element (the
  space-time yield `7.69 %/min = 61.5 % / 8.0 min`), one **`sources: [...]` multi-source node** and
  a chart series that cites four CSV rows;
* four legends: three **kind legends** (apparatus couplings, process streams, route links) and one
  data legend; every rendered kind is declared, and `K904` measures `11 == 11`;
* an `output_contract` in `case.json` that deliberately includes three workorder-specific keys with
  **no direct field mapping** (`apparatus`, `process_flow`, `technical_route`) so the disclosed
  run-summary fill is exercised.

## Run it yourself

From the submission root:

```
python3 scripts/ar.py ingest --input examples/synthetic-001/input --work /tmp/ar-work
```

Then copy the reference spec into place, build, write `result.json`, and *then* run the gates
(gate I reads `result.json`, so `check` must come after `result`):

```
cp examples/synthetic-001/expected/spec.json /tmp/ar-work/spec.json
python3 scripts/ar.py build  --spec /tmp/ar-work/spec.json --out /tmp/ar-out --dpi 300
python3 scripts/ar.py result --out /tmp/ar-out --input examples/synthetic-001/input --work /tmp/ar-work
python3 scripts/ar.py check  --out /tmp/ar-out --spec /tmp/ar-work/spec.json --work /tmp/ar-work
python3 scripts/ar.py result --out /tmp/ar-out --input examples/synthetic-001/input --work /tmp/ar-work
```

`build` → exit `0`; `result` → exit `0`; `check` → exit `0` only when every gate passes
(`exit 1` and `check: FAILED N check(s): …` otherwise — read `validation_report.json`).

To see the no-LLM fallback instead of the authored spec, skip the `cp` and run:

```
python3 scripts/ar.py run --input examples/synthetic-001/input --work /tmp/ar-work --out /tmp/ar-out
```

`autospec` derives a structurally valid, deliberately conservative spec (measured: 4 panels, 33
evidence items, resolved page 200 × 170 mm) — good enough to produce artefacts and prove the
machinery, **not** a substitute for an authored spec. Measured: that path exits `0` with **all 11
gates passing and 0 warns**, `status: "ok"`.

## How to read `expected/`

| File | What to do with it |
|---|---|
| `spec.json` | the template: copy it and rewrite the science for your own case. It validates with **0 errors** and resolves `40/40` quotes; it is the structural template for a `role: apparatus` + `flow` + `route` + `data` figure. |
| `figure.svg` | open it in a browser or Inkscape; check that groups are named, text is selectable/editable, and no whole-image bitmap is present (measured `groups=7(named=7)`, `text_nodes=112`, `images=0`). |
| `result.json` | the shape the evaluator reads back: `case_id`, `status`, `artifacts` (path/bytes/sha256), `sources`, `evidence`, `uncertainty`, `limitations`, `audit`. Produced by a real run, so it is a worked example of a passing result, not a fixture. |

## Rendered exports (not stored in the bundle)

`figure.png` (300 dpi, **2835 × 2953 px measured** for the resolved 240 × 250 mm page) and
`figure.pdf` (1 page, vector, embedded TrueType; MediaBox **680.315 × 708.6614 pt measured**, 2
embedded font programmes, 130 `Tj`/`TJ` operators, 0 image objects) are produced by the same build.
`export_report.json` records their measured properties (pixel size, `pHYs` dpi, page count,
`/FontFile` count, `Tj`/`TJ` counts, `MediaBox`) and their sha256.

Measured sha256 of the frozen run (2026-11-23 16:20 +08:00, after the `<text>`-positioning fix):

| Artefact | Bytes | sha256 |
|---|---|---|
| `figure.svg` | 134,400 | `3c88977cdab62973db4004a77b9dc408d021d6fab7e77bcf37801f9459d71b89` |
| `figure.png` | 1,001,258 | `c6fa268a990cd220bf356096877a36caf1e4acca13f42a57b1c344f1f407abd7` |
| `figure.pdf` | 1,111,949 | `091a61d84455198128464acadff67237bcbc67c2b5bdd72e6ead1e355edc7b80` |

Rebuilding the same spec into a second directory reproduces all three byte-for-byte (verified: two
`build` runs 3 s apart into different directories gave identical sha256 for svg/png/pdf). Because
the bundle must contain only UTF-8 text, those binaries live outside it; reproduce them with the
`build` command above and compare against `export_report.json`.

**Connector lines really are in the artefact.** The generated `figure.svg` contains **25
`data-type="arrow"` elements and 25 `edge-line` paths**, i.e. one rendered connector per spec edge —
this is the property an earlier base revision failed to produce (edge primitives were typed `arrow`
while the SVG/raster backends only drew `path`). The SVG is also **free of the previous product's
brand**: the old hyphenated brand string occurs **0** times in the file, while
`apparatus-technical-route` occurs 3 times (`data-generator`, the metadata block and the `<desc>`).

> The sha256 values above belong to the frozen run and to that revision of `scripts/`. A later
> revision of `layout.py`/`svg_backend.py`/`export.py` will change them; regenerate and re-quote
> rather than copying these numbers into a report.

> **Fixed, verified — recorded because it was real.** An earlier revision of `svg_backend.py` emitted
> `<text>` elements with **no `x`/`y` attributes and no ancestor `transform`** (measured: 112
> `<text>`, 0 with coordinates), so a conforming renderer stacked the labels at the origin even
> though every gate, gate F included, passed. The shipped `figure.svg` is generated by the fixed
> backend and measures **112/112 `<text>` with `x` and `y`**, `x ∈ 3.00..235.20`, `y ∈ 6.67..244.53`,
> **112/112 inside the page box**, spread over **71 of 400 grid cells** (all-at-origin would be 1),
> at most 4 labels per cell. Renderer-level visual confirmation is **UNVERIFIED** (no usable SVG
> renderer on this host), so the evidence is attribute-level and geometry-level, not a screenshot.
> Take-away for reuse: **"gate F passes" is not a statement about visual layout** — gate F proves the
> text is real and labelled, not that it is positioned.

For the **default** 180 × 120 mm canvas the expected raster is 2126 × 1417 px and the expected
MediaBox 510.236 × 340.157 pt; this example's spec declares 240 × 250 mm, which the layout keeps.

## Run status

| Claim | Status |
|---|---|
| `spec.json` passes `scene.validate_spec` | **executed** — 0 error issues; 4 panels, 28 nodes, 25 edges, 1 chart, 4 legends, 40 evidence items, canvas **240 × 250 mm** |
| `ar.py ingest` on `input/` exits `0` | **executed** — `5 material(s), 60 evidence item(s), case_id=SYNTHETIC-AR-001` |
| **Every evidence quote resolves verbatim** | **executed** — gate **E** `pass`: `materials=5, refs=77, dangling=0, evidence_items=40, quotes_resolved=40, quotes_unresolved=0, module_issues=0` |
| **All eleven gates pass** | **executed** — `check` → **exit `0`**, `check: all checks passed (0 warn)`; A–K all `pass`, `failed=[]`, `warned=[]`. Gate D reports the three kind legends as a *semantic key* (`P1/P2/P3.legend[0] … -> semantic key, D series rule not applicable (gate K904 checks it)`) and the one data legend as a multiset match; the non-fatal `W_EDGE_LABEL_TIGHT` scene warning (`AE7 'outlet'`, 6.7 mm² overlap) is recorded in `export_report.scene_warnings`, not as a gate failure |
| **Topology and order** | **executed** — gate **J** `pass`: `J901=13 sequence ids`, `J902=13 step_no contiguous 1..N, 1 legal parallel repeat`, `J903=loop_to 2 / branch group 1 / terminal 2`, `J904=4 phases, 3 deps, 0 cycle`, `J905=50 endpoints/25 edges`, `J906=declared 25 matched 25, reversed 0, missing 0` |
| **Apparatus semantics and legend key** | **executed** — gate **K** `pass`: `K901=11 apparatus nodes with a legal part`, `K902=8 edge port references`, `K903=merge 2 / branch 2 / waste 2`, `K904=11 declared == 11 rendered`, `K905=n/a` |
| `build` / `result` | **executed** — build exit `0` (svg+png+pdf); final `result` exit `0` with **`status: "ok"`**, `audit.checks_failed=[]`, `audit.checks_warned=[]`, `audit.unfilled_fields={}` |
| **Determinism (in-build)** | **executed** — gate **G** `pass` (`figure.pdf` run1 == run2 == `091a61d844551981`), and a rebuild into a second directory 3 s later reproduced all three sha256 (`svg 3c88977c…`, `png c6fa268a…`, `pdf 091a61d8…`) |
| **Determinism (whole chain)** | **executed** — the `selftest` `determinism-full-chain` check (`ingest->spec->build` twice in fresh work dirs) **passes** on this tree. Note the harness caveat on the row below: the full `selftest` run currently aborts on a budget cap before the summary, so the whole-run exit code is `1` for that reason only. One intermittent `determinism :: differ=['figure.pdf']` was observed earlier the same day and is retested in [`references/failure-modes.md`](../references/failure-modes.md) §6 (not reproduced since) |
| `gain_check.py` (measured 使用增益) | **executed** — **exit `0`**, `GAIN CHECK: PASS`; `A_detected=0/5 B_detected=5/5 **B_warn_only=0 run_errors=0**`, 39.2 s (a defect counts as intercepted **only when a gate fails**); `--full` (9 classes) measured by the tool author at 0/9 vs 9/9 — see [`references/measured-gain.md`](../references/measured-gain.md) |
| `ar.py selftest --quick` | **executed** — **11/11 exit `0`** in 25.5 s (`determinism`, `gates-A-to-I-present` = A–K, `svg-is-editable-text`, `bundle-budget`) |
| `ar.py selftest` (full) | **executed** — **23/23 exit `0`** in 233.5 s, including `determinism-full-chain`, the injected-defect negatives and an in-harness `contract_matrix --quick` 4-set subset. The **full 10-set matrix is a separate standalone command** (`python3 scripts/contract_matrix.py` → exit `0`, `PASS (10/10 key sets)`, 260.6 s), deliberately left outside the harness's 240 s per-step cap — see [`references/failure-modes.md`](../references/failure-modes.md) §7 |
| `result.json` in this directory | **a real run's output** — `status: "ok"`, `case_id: "SYNTHETIC-AR-001"`, 7 artifacts with sha256, 60 evidence items with resolvable sources, `audit.unmapped_contract_keys=["apparatus","process_flow","technical_route"]` |
| The PNG/PDF are **not** in the bundle | **executed** — the tree contains 0 `.png`/`.pdf` files |

The three files in `expected/` were copied verbatim from the output directory of that run — `spec.json`
is the authored source (hand-written, then validated), while `figure.svg` and `result.json` are
**not** hand-written. Never trust a number in this directory that is not accompanied by the command
that produced it.
