# Rubric mapping — scoring point → artefact → proving command

Every row names the artefact the reviewer can open and the **command that produced or proves it**.
Nothing here is asserted without a command that has been run on this bundle; the measured values are
the ones in the "Evidence of execution" section.

---

## 1. The six elements of a scientific figure (CONTRACT §5)

| Element | Artefact the reviewer opens | Proving command | Measured evidence |
|---|---|---|---|
| **科学实体** — the apparatus components and other entities | `scene.json` `primitives[]` with `part`; `result.json.evidence[]` | `python3 scripts/ar.py build --spec … --out …` | gate **K901** `pass(11 apparatus node(s) all carry a legal part)`; `part` drawn as a glyph by `layout.part_glyph_w` |
| **空间关系** — who is connected to whom, with direction | `scene.json` rendered edges; `validation_report.json` `checks[J]` | `python3 scripts/ar.py check --out … --spec … --work …` | gate **J** `J905=pass(50 endpoint(s) over 25 rendered edge(s) all resolve)`, `J906=pass(declared=25 unique of 50, matched=25, reversed=0, missing=0, undeclared_rendered=0)` |
| **数据编码** — the numbers and charts | `scene.json` chart primitives + `legend`; `spec.json` `nodes[].value/unit` | `ar.py build` then `ar.py check` | gate **D** `pass` (`problems=0`, data-legend multiset == series multiset); gate **E** `pass` (`quotes_resolved=40/40`, `module_issues=0`) |
| **图例标注** — the legend really describes the drawing | `scene.json` legend primitives; `checks[K]` | `ar.py check` | gate **K904** `pass(legend_entries_with_kind=11 == rendered_styles=11)` |
| **可编辑源文件** — layered, editable, source-preserving | `figure.svg` (named `<g>`, real `<text>`), `figure_spec.resolved.json`, `change_records` | `ar.py build`; `ar.py edit --spec … --edits …`; `ar.py check` | gate **F** `pass(groups=7(named=7), ids=306(unique=306), images=0, required_labels=99, labels_present=99, roundtrip applied=1 changed=True)`; `edit` exit `0` with 3 recorded changes |
| **导出格式** — print-ready exports | `figure.png` (300 dpi), `figure.pdf` (1 page, vector, embedded fonts) | `ar.py build --dpi 300`; `ar.py check` | gate **H** `pass(png_px=[2835,2953]==expected, pdf_pages=1, pdf_font_programs=2 embedded=True, pdf_text_ops=130 vector=True, pdf_image_objects=0)` |

## 2. The workorder's own requirements

The workorder (`apparatus_and_technical_route`) adds: real editable SVG/PNG/PDF **and a
source-preserving edit**, and "scientific judgement remains native/LLM Judge, not a literal quote or
export pass".

| Requirement | How it is met | Proof |
|---|---|---|
| apparatus structure (not a pathway diagram) | panel role `apparatus` with `part` + `ports` | `K901`, `K902` pass; `examples/synthetic-001/expected/spec.json` P1 |
| step order | panel role `flow` with `sequence` + `step_no` | `J901`, `J902` pass (`1..N` contiguous, 1 legal parallel repeat) |
| material flow and direction | `material`/`fluid`/`gas`/`waste`/`loop` edges plus declared topology | `J906` (`reversed=0`, `missing=0`) and gate D's `scene_arrows == spec_edges` |
| parallel branches, merges, recycle | `branch`/`merge`/`loop` kinds, `loop_to`, `branch` group | `J903=pass(loop_to=2, branch_groups=1, terminal=2)`; `K903=pass(merge=2, branch=2, waste=2)` |
| technical-route phases | panel role `route` with `phases[].depends_on` | `J904=pass(4 phase(s), 3 dependency edge(s), 0 cycle, 0 dangling)` |
| **source-preserving edit** (not a redraw) | `ar.py edit` applies spec-level ops and records them | measured: `edit` exit `0`, `edit: applied 3 change(s)`, `change_records` length 3 with `from`/`to` per change; the following `build` exit `0` |
| real editable source | `figure.svg` is layered text, not a raster | gate F `images=0`, `named=7/7`, real `<text>`; `patch_svg_text` round-trip `structure=True ids_preserved=True` |

## 3. Verification, honesty and cost

| Scoring point | Artefact | Proving command | Measured |
|---|---|---|---|
| **结果可核验性** (verifiability) | `result.json.evidence[]` with per-item `source` + `resolved`; `validation_report.json` | `ar.py check` | gate E `pass`, `refs=77, dangling=0, quotes_resolved=40, quotes_unresolved=0, module_issues=0` |
| **使用增益** | per-PID `verify/t3/gain_check.<pid>/gain_report.json` | `python3 scripts/gain_check.py` (default quick mode) | exit `0`, `GAIN CHECK: PASS`, `A_detected=0/5 B_detected=5/5 **B_warn_only=0** run_errors=0` (39.2 s); `--full` 9 classes measured by the tool author at `0/9 vs 9/9 stopped by a failing gate` — a warn-only outcome is counted separately and never as interception; see [`measured-gain.md`](measured-gain.md) |
| **不编造** | every printed number resolves to a verbatim quote | `ar.py check` (gate E `E906`) + `gain_check`'s `number_not_in_quote` defect | `gain_check`: A ships the fabricated number, B catches it (`E906`) |
| **稳定性** (no invented results under failure) | `result.json.status` + `audit.checks_failed` | `ar.py result --status partial`; `ar.py check` | a check-failed run reports `status: partial` with a `check_failed` uncertainty entry; the fixture's green run reports `ok`, `checks_failed=[]`, `unfilled_fields={}` |
| **确定性与可复现** | `export_report.determinism`, gate G, `selftest` | `ar.py check` (gate G); `python3 scripts/ar.py selftest` | `check` `pass`, all three artefacts identical inside the build (`figure.pdf 091a61d8…`, `figure.png c6fa268a…`, `figure.svg 3c88977c…`); two `build` runs 3 s apart into different directories reproduced all three sha256; full `selftest` **23/23, exit `0`** (see row 10) including `determinism-full-chain` |
| **契约覆盖 / 未卜先知** | `audit.unmapped_contract_keys` | `ar.py result`; `python3 scripts/contract_matrix.py` | measured `unmapped=["apparatus","process_flow","technical_route"]`, `unfilled=[]`, gate I `hard_empty=0 soft_empty=0`; `contract_matrix` builds 5 adversarial key sets |
| **成本** | the whole run's wall clock | §1 command sequence | **31 s** for ingest+build+result+check+result against a 900 s budget |
| **GitHub 公开链接 (+5)** | [`GITHUB_URL.txt`](../GITHUB_URL.txt) | `cat GITHUB_URL.txt` | line 1 = `https://github.com/sprw-li/apparatus-technical-route-skill`, line 2 = `SKILL.md`; the repository is public and holds this bundle's files **at the repository root** (`SKILL.md`, `scripts/`, `references/`, `examples/`, `README.md`). The repository is created and currently empty; the Lead pushes this bundle to it. Link reachability is **not** verified from here |

## 4. Bundle budget (platform cap: ≤ 50 files, ≤ 500 KB each, ≤ 2 MB total)

Measured 2026-11-23 16:41 +08:00, from the submission root (the numbers move while scripts are being
edited in parallel, so treat this as a reading, not a constant; the official validator reported the
same totals):

```
files=36  total=1,169,134 B  (1.12 MB of the 2 MB cap)
largest=scripts/layout.py 145,913 B  (of the 500 KB per-file cap)
```

Re-verified on every `selftest` run as its `bundle-budget` line. The same command also asserts the
bundle contains **no `.png`/`.pdf`** and no `__pycache__`.

## 5. Evidence of execution (commands actually run on this bundle)

All of the following were run on 2026-11-23 between 12:5x and 13:3x +08:00 from the submission root.

| # | Command | Exit | Key output |
|---|---|---|---|
| 1 | `python3 scripts/ar.py ingest --input examples/synthetic-001/input --work W` | `0` | `5 material(s), 60 evidence item(s), case_id=SYNTHETIC-AR-001` |
| 2 | `python3 scripts/ar.py build --spec examples/synthetic-001/expected/spec.json --out O --dpi 300` | `0` | `figure.pdf, figure.png, figure.svg` |
| 3 | `python3 scripts/ar.py result --out O --input examples/synthetic-001/input --work W` | `0` | (first pass) `status=partial artifacts=6` |
| 4 | `python3 scripts/ar.py check --out O --spec examples/synthetic-001/expected/spec.json --work W` | **`0`** | `check: all checks passed (0 warn)`; 11 gates, A–K all pass, `failed=[]`, `warned=[]` |
| 5 | `python3 scripts/ar.py result …` (second pass) | `0` | `status=ok artifacts=7` |
| 6 | `python3 scripts/ar.py run --input examples/synthetic-001/input --work W2 --out O2` (no seeded spec → autospec path) | `0` | 11 gates, **0 failed / 0 warn**, `status=ok`; `autospec` wrote a 4-panel, 33-evidence spec |
| 7 | `python3 scripts/ar.py edit --spec … --edits edits.json --out spec2.json` then `build` | `0` / `0` | `edit: applied 3 change(s)`; `change_records` length 3 |
| 8 | `python3 scripts/ar.py autospec --work W --out spec-autospec.json` | `0` | `4 panel(s), 33 evidence` |
| 9 | `python3 scripts/gain_check.py` | `0` | `GAIN CHECK: PASS`; `A_detected=0/5 B_detected=5/5 B_warn_only=0 run_errors=0`, 39.2 s (`--full`: tool author measured `0/9 vs 9/9 stopped by a failing gate`, 336.7 s) |
| 10 | `python3 scripts/ar.py selftest --quick` / `python3 scripts/ar.py selftest` | `0` / `0` | `--quick` **11/11** in 25.5 s; full **23/23** in 233.5 s (incl. `determinism-full-chain`, the injected-defect negatives, and an in-harness `contract_matrix --quick` 4-set subset) |
| 11 | `build` twice into two directories, 3 s apart | `0` / `0` | `figure.svg` `3c88977c…` / `figure.png` `c6fa268a…` / `figure.pdf` `091a61d8…` — each identical across the two directories; script tree byte-unchanged during the run |
| 12 | `Select-String` sweep over the delivery tree | — | **0** matches for the stale entry-script name, **0** author-machine absolute paths, **0** personal-profile paths (`Users`); **0** `.png`/`.pdf`; **0** `__pycache__` |
| 13 | brand sweep incl. `examples/synthetic-001/expected/figure.svg` | — | the generated SVG contains **0** occurrences of the previous product's hyphenated brand string, and 3 × `apparatus-technical-route`; 25 `edge-line` connectors and 112/112 `<text>` with coordinates. Residual mentions remain only in files outside this task's write domain (see the handoff report) |
| 14 | `python3 scripts/contract_matrix.py` (standalone, full 10-set matrix) | `0` | `CONTRACT MATRIX: PASS (10/10 key sets)`, 260.6 s |
| 15 | `python3 _shared/tools/validate_skill_submission.py <submission-dir>` | `0` | `{"status":"ok","files":36,...,"name":"apparatus-technical-route","errors":[]}` (byte total re-read at freeze time) |

## 6. What is *not* claimed

* **No score.** The platform grades by human/LLM judgement; no number, percentile or comparison
  against another Skill is claimed anywhere in this bundle.
* **No model-quality claim.** `gain_check` measures defect interception, not drawing quality.
* **No fresh-case result.** `examples/synthetic-001` is a **synthetic** fixture
  (`SYNTHETIC EXAMPLE - NOT AN OFFICIAL CASE`); nothing in this bundle is presented as an official
  case result.
* **No claim that the gates cover everything**: an undeclared edge kind in a legend, a
  `W_EDGE_LABEL_TIGHT`/`W_PORT_ROUTE_FALLBACK` overlap, an unparsed PDF and a truncated source file
  are recorded rather than gated, and the one intermittent determinism incident (root cause
  UNVERIFIED, not reproduced since) is reported in [`failure-modes.md`](failure-modes.md) §6 instead
  of being hidden.
* **No claim of renderer-level visual verification.** The SVG is verified at attribute level
  (112/112 `<text>` carry `x`/`y`) and geometry level (all coordinates in-page, 71 grid cells
  occupied), but no SVG renderer is available on this host, so nobody here has *looked at* a
  rasterised page — see [`failure-modes.md`](failure-modes.md) §8.
* **No claim that the GitHub link resolves.** `GITHUB_URL.txt` names the public repository the Lead
  created; link reachability is not verified from this workspace.
