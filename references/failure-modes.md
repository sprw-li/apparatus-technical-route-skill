# Failure modes — observed behaviour, not theory

Every row below is either (a) a **measured** outcome of the shipped scripts on the bundled fixture,
run on 2026-11-23, or (b) an explicitly marked **UNVERIFIED** expectation. The command, exit code
and the artefact that proves it are named in each section. Where a behaviour was only read out of
the source, the source function is named and the row is marked *source-read*.

Sources of truth: `scripts/ar.py` (exit codes, `--status` handling), `scripts/validate.py`
(gates A–K), `scripts/evidence.py` (`check_provenance`), `scripts/layout.py` (scene warnings),
`scripts/gain_check.py` (the injected-defect matrix).

---

## 1. The measured defect-injection matrix

`python3 scripts/gain_check.py` (default **quick** mode: 5 of the 9 defect classes) injects defects of
the kind an LLM actually makes, into the **same** base spec, and runs both conditions: **A** =
`ar.py build` only, **B** = the full pipeline. Measured **exit `0`** (`GAIN CHECK: PASS`), re-run on
the shipped tree: `mode=quick elapsed_s=39.2 A_detected=0/5 B_detected=5/5 **B_warn_only=0**
run_errors=0 clean_gates=11`.

**Measured matrix (2026-11-23 16:3x, quick mode):**

| Injected defect | A (no gates) | B (Skill) | Gate that fires |
|---|---|---|---|
| `reversed_connection` — a declared `(from,to,kind)` is drawn backwards | exit `0`, **ships it** | exit `1`, **stopped** | **J906** |
| `missing_connection` — a declared relation is not drawn at all | exit `0`, ships it | exit `1`, stopped | **J906** |
| `legend_colour_mismatch` — the legend's `(kind,linestyle,colour)` is not what is painted | exit `0`, ships it | exit `1`, stopped | **K904** |
| `step_number_gap` — `step_no` skips a number | exit `0`, ships it | exit `1`, stopped | **J902** |
| `number_not_in_quote` — a measured value is changed to a number no source contains | exit `0`, ships it | exit `1`, stopped | **E** (`E906`) |
| **total** | **0 / 5** | **5 / 5** | |

`--full` adds four secondary classes — `dangling_evidence` (**E**), `apparatus_node_no_part`
(**K901**), `waste_target_not_waste` (**K903**), `legend_label_orphan` (**D**) — measured by the
tool's own author at **0/9 vs 9/9 stopped by a failing gate** (`mode=full elapsed_s=336.7
B_warn_only=0 run_errors=0`). Full detail in [`measured-gain.md`](measured-gain.md).

On the clean run the same command measured:

| | A (`build` only) | B (Skill) |
|---|---|---|
| artefacts svg/png/pdf | yes / yes / yes | yes / yes / yes |
| `validation_report.json` | **absent** | present, **11 gates** |
| `result.json` | **absent** | present, `status: "ok"` |
| evidence items carried | 40 | 60 (the ingest ledger) |
| exit code | `0` | `0` |

This is the discriminative test the Skill is built around: **a defect must make a gate fail,
otherwise the gate is not load-bearing.** Every injected defect is stopped by a failing gate, and the
only condition under which the bad figure escapes is "no gates at all".

**A rule that merely *warns* does not stop the figure.** `gain_check` counts such cases separately
(`B_warn_only`) and never as interception; on the shipped tree `B_warn_only=0` and `run_errors=0`, so
every one of the counted stops is a real non-zero gate verdict — which is what makes the
"stopped by a FAILING gate" wording true rather than optimistic.

Reproduce:

```
python3 scripts/gain_check.py
python3 -c "import json,glob;p=sorted(glob.glob('<parent>/verify/t3/gain_check.*/gain_report.json'))[-1];\
r=json.load(open(p));print(r['defect_detection'], r['clean_run']['B']['gates_run'], r['clean_run']['B']['has_result'])"
```

Expect `{'A': 0, 'B': 5, 'n': 5} 11 True` in quick mode, and `n: 9` under `--full`.

> Measured re-runnability: both `gain_check.py` and `contract_matrix.py` use a **per-PID** scratch
> root, accept `--out` (and `contract_matrix.py` `--keep`), and copy with `dirs_exist_ok=True` — the
> earlier `FileExistsError` on a second/concurrent run is fixed. See
> [`runbook.md`](runbook.md) §7. Measured on the shipped tree: a `gain_check` run created
> `verify/t3/gain_check.<pid>/` and reported its own report path, with no collision against a
> concurrently running teammate.

---

## 2. Gate-E failure classes (`ar.py check` → exit `1`)

Gate E is the anti-fabrication core; its sub-codes are in
[`provenance-and-evidence.md`](provenance-and-evidence.md). The three *practical* failure classes:

| Observed detail string | Cause | Fix |
|---|---|---|
| `module error: … has no evidence source` (`E903`) | a node/edge/chart series carries no `source` at all | add the evidence id that backs it |
| `dangling source ids, e.g. … -> 'E9'` / `E904` | the cited id is not in `spec.evidence[]` | add the evidence item or repoint the element |
| `module error: value 7.0 is not present in the quote of evidence E2` (`E906`) | the element would print a number that its cited quote does not contain | cite the row/item that really contains it, mark it `derived: true` with real `source_values`, or drop the number |

**Measured, non-obvious behaviour worth knowing:** `evidence._element_values` reads numbers out of
**every string field** of an element except `value`/`values`/`source_values`/`source`/`sources`/
`id`/`from`/`to` — i.e. out of `label`, `sublabel` and edge `label` too. On this fixture that
produced two real failures during authoring:

* a node sublabel `"5.0 L, 10.0 mg/L"` failed against a quote that only mentions `5.0 L`;
* flow edge labels `"step 3"` / `"step 4"` failed against quotes that contain no `3`/`4`.

Both are correct behaviour by the gate's contract (the figure *would* print that number) and the fix
is to make the text traceable or to drop it. A related interaction **was** a false positive and is
now fixed, with a measured two-sided control in
[`exports-fonts-colour.md`](exports-fonts-colour.md) §6: an explicit hex colour literal in
`edge.color` (`"#0072B2"`) used to be scanned as the number `7.0` and fail `E906`; today 25
hex-coloured edges plus an `rgb(...)` node fill give `check` **exit `0`** with E `pass`, while
changing a real `value` to `999.9` (absent from every cited quote) still gives `check` **exit `1`
with `failed=['E']`** — the anti-fabrication check was not weakened by the fix.

## 3. Warnings that are not failures

`ar.py check` exits `0` when gates report `warn`. **Measured on the shipped fixture (16:11): `0 warn`
on the authored spec and `0 warn` on the `autospec` fallback** — `check: all checks passed (0 warn)`.

An **earlier revision of the gate set** did warn on this fixture, and the record is kept because the
distinction matters: gate **D** used to report

```
D warn legends_checked=4, legend_series_colour_pairs=0, colorbars_checked=0,
  spec_edges=25{...}, scene_arrows=25{...}, edge_direction_checked=25,
  linestyle_checked=25, linestyle_mismatch=0, linestyle_unknown=0,
  units_missing=0, problems=0 | P4.legend[0] 2 items == series union == chart C1 series (multiset)
```

That was the *"nothing to compare on a colour-swatch basis"* branch: three of the four legends are
**kind legends** (they key connector kinds, not data categories), so `legend_series_colour_pairs=0`
and `colorbars_checked=0` (the fixture encodes with a grouped bar + legend, no colorbar). Gate D now
states that case explicitly instead of warning:

```
D pass legends_checked=1, ... problems=0 | P1.legend[0] 5 kind/part item(s) -> semantic key,
  D series rule not applicable (gate K904 checks it);  (same for P2, P3)
```

`problems=0`, the data legend matches the chart series exactly, the rendered arrow kinds equal the
spec kinds, and every linestyle and direction agrees.

Also measured and worth expecting: the layout publishes **non-fatal** scene warnings into
`export_report.scene_warnings`. On the shipped fixture there is **1**: `W_EDGE_LABEL_TIGHT` for
`edge AE7 label 'outlet'` (6.7 mm² overlap with the node boxes) — advisory only, `check` still exits
`0`. The other codes are `W_EDGE_LABEL_OVERFLOW` / `W_LEGEND_OVERFLOW`; an earlier revision with
much longer edge labels produced **12** `W_EDGE_LABEL_TIGHT` entries *and* one truncated node label
(gate **B** `truncated_labels=1`, gate **F** `labels_missing=1`). **That truncated-label class is
the one that becomes fatal**: a label the layout drops is real content loss and fails B and F.
Shorten the label or move content out of the crowded panel.

## 4. Exit-code behaviour by command (source-read + spot-measured)

| Situation | Exit | Evidence |
|---|---|---|
| `check` before `build` (no spec found) | `3` | `cmd_check` requires `--spec` or `OUT/figure_spec.resolved.json` |
| `result` before `build` | `3` | `missing …/figure_spec.resolved.json` |
| `build` with a spec that has an `error` issue | `4` | writes `spec-issues.json` into `--out` |
| `edit` whose result is invalid | `4` | writes `spec-issues.json` next to the output spec |
| `autospec` over a work dir with no `materials.json` and no `--input` | `4` or `2` | *source-read*; `autospec --input DIR` re-ingests |
| unknown subcommand / missing required flag | `2` | argparse |
| a build that raises inside a backend | `2` | writes `build-error.json` with the last 25 traceback lines |
| **any gate fails** | `1` | `check`, `run` — and only this produces `1` |
| all gates pass, some warn | `0` | measured on the fixture |

Measured with the bundled fixture (all exit `0`): `ingest`, `build`, `result`, `check`, `result`,
`edit`, `autospec`, `run` (with the spec present **and** with only the input, i.e. the autospec
fallback), `contract_matrix`, `gain_check`.

## 5. `result.json` behaviour under failure

| Condition | `status` | What `result.json` carries |
|---|---|---|
| gates not run yet | `partial` | a `not_validated` uncertainty entry: "artefacts have not been gated; status cannot be 'ok'" |
| gate(s) failed | `partial` | one `{"kind": "check_failed", "subject", "reason", "needs_human": true}` uncertainty entry per failed gate, and `audit.checks_failed` |
| all gates pass | `ok` | `audit.checks_failed=[]`, `audit.checks_warned=[]`, `audit.unfilled_fields={}` (measured on the shipped fixture) |
| a contract key cannot be filled at all | forced `partial` | the key listed in `audit.unfilled_fields` |
| a contract key has no direct mapping | unchanged | the key is filled with a truthful run summary and listed in `audit.unmapped_contract_keys` (measured: `["apparatus","process_flow","technical_route"]` on the fixture) |
| `--status partial` on a green run | `partial` | an explicit `--status` can only ever **lower** the automatic status |

## 6. Determinism — one measured incident, retested and not reproduced

Two scopes, deliberately different ([`runbook.md`](runbook.md) §6):

* **gate G** re-exports an already-built `scene.json` *inside the same process* and compares sha256
  per artefact. Measured `pass` on the frozen fixture, all three artefacts identical.
* **`selftest`'s `determinism-full-chain`** runs the whole pipeline twice in two fresh work
  directories, i.e. across processes and across a wall-clock gap. This is the stricter check.

**Measured incident (2026-11-23 ~13:2x).** `python3 scripts/ar.py selftest --quick` failed
`determinism :: differ=['figure.pdf']` (exit `1`) while gate G passed on the same tree. In the same
window, two `ar.py run` invocations over `examples/synthetic-001/input` produced an **identical SVG**
(`20ed1549e2d12981…`) but a different PNG (`d2d6c1fa05c91ee7…` → `c700d76685f9433e…`) and PDF
(`26284fd44ee3c905…` → `c4bd680e0c2964b9…`).

**Retest on the shipped tree (2026-11-23 16:11, after the render-geom and `<text>`-positioning
fixes).** On the current tree:

* two `build` invocations of the authored spec, **3 s apart**, into two different output
  directories → `figure.svg` `3c88977cdab62973…`, `figure.png` `c6fa268a990cd220…`,
  `figure.pdf` `091a61d844551981…`, **identical across both runs** (verified independently of the
  gate, with `Get-FileHash`), and the script tree was **byte-unchanged during the run** (mtimes and
  sizes compared before/after);
* two earlier revisions of the same check gave `b22060fc…`/`f9eae793…`/`eab0670b…` and
  `8c643609…`/`aba1e370…`/`36cb4d8a…`, also identical across two runs each — so this property has
  now held on three separate revisions;
* the full `ar.py selftest` passes **23/23, exit `0`** (`determinism-full-chain` included) — see §7.
  On the 13:3x revision it also passed 23/23; the harness failure seen in between was purely the
  per-step budget cap, fixed in §7.

**Status: not reproduced since.** The 13:2x failure is retained as a real observation (single
measurement, root cause UNVERIFIED) but the same checks now pass repeatedly, including the stricter
cross-process check. The most likely explanation remains a mid-flight revision of the raster/PDF
backends by a parallel author: the SVG stayed byte-identical while PNG/PDF changed, which is exactly
what a change confined to the raster/PDF code path produces. What is claimed, and remains the
operating rule: gate G is necessary but not sufficient — run `ar.py selftest` before publishing, and
never "fix" non-determinism by rasterising or by dropping a format.

## 7. The self-test harness — it outgrew its own per-step budget, and that is fixed

`selftest.py` runs each harness subprocess with a **240 s** cap (`selftest.py:42`,
`run(args, cwd=None, timeout=240)`). When `contract_matrix.py` grew to ten key sets it needed
**≈10 min**, so the full self-test deterministically failed `harness-completed` while every check
that did run passed:

```
[FAIL] harness-completed   TimeoutExpired: Command '[... 'scripts/contract_matrix.py']'
                           timed out after 240 seconds
SELFTEST FAIL: 11/12 checks passed          (measured 2026-11-23 14:13)
```

**Fixed** by calling the harness with its reduced subset (`selftest.py:168` now passes `--quick`,
4 representative key sets instead of 10). Independently re-run by the author of this file
(2026-11-23 16:2x–16:3x):

| Command | Exit | Measured |
|---|---|---|
| `python3 scripts/ar.py selftest --quick` | `0` | **11/11**, 25.5 s |
| `python3 scripts/ar.py selftest` (full) | `0` | **23/23**, 233.5 s — includes `determinism-full-chain` and the injected-defect negatives; its in-harness contract check is the `--quick` 4-set subset |
| `python3 scripts/contract_matrix.py` (standalone, full) | `0` | `CONTRACT MATRIX: PASS (10/10 key sets)`, 260.6 s |
| `python3 scripts/gain_check.py` (default quick) | `0` | `GAIN CHECK: PASS`, `A_detected=0/5 B_detected=5/5 B_warn_only=0 run_errors=0`, 40.2 s |

Timings are wall-clock on a shared machine and move with load (another run measured 29.8 s for the
4-set subset and 134.3 s for the full matrix); the **exit codes and counts** are the stable part.
Note the deliberate split: the self-test runs the fast subset so the whole harness fits its budget,
while the full 10-set matrix stays a separate standalone command. A single `ar.py run` on the fixture
measures ~30 s, so the pipeline itself was never the problem.

## 8. The SVG positioning gap — found, fixed, verified at attribute/geometry level

Gate **F** proves the SVG text is *real* (`<text>`, named groups, unique ids, no flattened bitmap,
every spec label present) — it does **not** prove the text is *positioned*. A revision of
`svg_backend.py` in this build emitted `<text>` elements with **no `x`/`y` attributes and no ancestor
`transform`**, so a conforming renderer stacked every label at the origin while `check` exited `0`:

```
(measured on the pre-fix revision)  total <text>: 112   with x & y: 0   transform= occurrences: 0
```

**Fixed.** Measured on the shipped `examples/synthetic-001/expected/figure.svg` (16:11):

```
total <text>: 112   with x & y: 112 / 112
x range 3.00..235.20    y range 6.67..244.53    in-page x 112/112, y 112/112
distinct 20x20 grid cells occupied: 69          (all-at-origin would be 1)
most crowded cell holds 4 label(s)
panel titles inside a panel-header rect: 5/5
```

So the fix is verified at **attribute level** (every `<text>` carries coordinates) and **geometry
level** (all coordinates inside the page box, labels spread over 69 grid cells, panel titles landing
inside their header rectangles). **Renderer-level visual confirmation is UNVERIFIED**: no usable SVG
renderer is available on this host (headless Edge cannot start under the sandbox; cairosvg, svglib,
PyMuPDF and reportlab are not installed), so nobody has *looked at* a rasterised page here.

**Lesson for reuse: "gate F passes" is not a statement about visual layout.** Open the SVG (or assert
on coordinates, as above) before claiming a figure looks right.

## 9. What is *not* covered (honest gaps)

* **No automatic scoring.** The platform grades this Skill by human/LLM judgement
  (`strategy = "human_review_only"`); nothing here approximates a judge's scientific reading.
* **No model comparison.** `gain_check` measures defect interception and delivered verification
  artefacts, not model quality — see [`measured-gain.md`](measured-gain.md).
* **Extraction quality is recorded, not fixed.** A PDF that yields no text gets
  `parsed: false` + a `pdf_unparsed` warning with `needs_human: true`; garbled extraction adds
  `low_text_quality`. Gate E then reports `warn` ("UNVERIFIABLE"), never `pass`.
* **A kind legend that omits a rendered kind is not flagged.** Gate K904 only checks the kinds a
  legend *declares*; a rendered `heat` edge with no legend entry passes. The fixture declares every
  kind it renders (11 entries over three panels), but that completeness is currently an authoring
  discipline, not a gate. **UNVERIFIED** as a gate.
* **`W_EDGE_LABEL_TIGHT` is advisory.** Overlapping edge labels are a warning, not a gate failure;
  only a *truncated* label escalates to B/F.
