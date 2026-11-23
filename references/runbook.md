# Runbook

The exact command sequence, the exit-code semantics, the budget plan, and how to recover from a
failed gate. Every command here was taken from `scripts/ar.py` (checked with `--help` on each
subcommand); every exit code was read out of `ar.py::main`/`cmd_*` and `scene.py::load_spec`.

Run from the Skill root (paths below assume `/skills/weekly-skill`, `/input`, `/app/work`,
`/app/output`).

## 0. Environment

```
python3 --version            # 3.8+; verified on 3.12.14
python3 scripts/ar.py --help # exit 0
```

Recommended flags: `PYTHONIOENCODING=utf-8` (the CLI logs CJK) and `PYTHONDONTWRITEBYTECODE=1`
(keeps `__pycache__` out of the tree). A render crash is exit `2` and writes
`build-error.json` (`{error, message, traceback[-25:]}`) into `--out`.

## 1. The canonical sequence

```
# 1. read the real input files
cat /input/case.json /input/task.md ; ls -la /input/materials/

# 2. ingest
python3 scripts/ar.py ingest --input /input --work /app/work

# 3. author /app/work/spec.json  (the ONLY LLM/human step; see references/spec-schema.md)

# 4. deterministic build
python3 scripts/ar.py build --spec /app/work/spec.json --out /app/output --dpi 300

# 5. write result.json   <-- BEFORE check, so gate I has something to read
python3 scripts/ar.py result --out /app/output --input /input --work /app/work

# 6. run gates A-K
python3 scripts/ar.py check --out /app/output --spec /app/work/spec.json --work /app/work

# 7. re-write result.json so its status/audit reflect the gate results
python3 scripts/ar.py result --out /app/output --input /input --work /app/work
```

**Why step 5 precedes step 6.** Gate I reads `result.json` from `--out`. On a first run there is no
`result.json` yet, so `check` would report gate I as failed and exit `1` even though gates A–H all
passed. Writing `result.json` first (it needs only `build`'s output) makes the gate run clean;
steps 6–7 then regenerate `result.json` with `audit.checks_failed` / `checks_warned` and the correct
`status`.

`ar.py build` writes `figure_spec.resolved.json`; `check` falls back to it when `--spec` is omitted,
but pass `--spec` explicitly so the check runs against exactly the spec you authored. `check --work`
and `result --work` are needed for gate E / the evidence ledger; `result` defaults `--work` to the
sibling `work/` directory of `--out`.

**Measured on the bundled fixture (2026-11-23 16:20 +08:00, `examples/synthetic-001`):**

| Step | Exit | Key output |
|---|---|---|
| `ingest` | `0` | `5 material(s), 60 evidence item(s), case_id=SYNTHETIC-AR-001` |
| `build` | `0` | `figure.pdf, figure.png, figure.svg` |
| `result` (first) | `0` | `status=partial artifacts=6` (no gates yet — honest) |
| `check` | `0` | `check: all checks passed (0 warn)` — 11 gates, 0 failed, 0 warn |
| `result` (second) | `0` | `status=ok artifacts=7` |

Whole sequence: **31 s wall**. Budget: 900 s.

## 2. The one-shot form (`run`)

```
python3 scripts/ar.py run --input /input --work /app/work --out /app/output
```

`run` = `ingest → (spec.json if present, else autospec) → build → result → check → result`, and it
**returns the check exit code**. It writes `result.json` *before* the gates precisely so gate I has
something to validate, then re-writes it so `status`/`audit` reflect the real gate outcomes — i.e.
`run` performs the exact sequence of §1.

Measured on the bundled fixture's **input only** (no authored spec in the work dir, so the autospec
fallback is used): `python3 scripts/ar.py run --input examples/synthetic-001/input --work W --out O`
→ **exit `0`**, gates A–K all pass. `autospec` produced a 4-panel, 33-item-evidence spec from the
new materials; it is a floor, not the deliverable.

## 3. Exit codes

| Code | Meaning | Where it comes from |
|---|---|---|
| `0` | success, or all gates passed (warns are still `0`) | every command |
| `1` | **only** this: at least one validation gate failed | `check`, `run` |
| `2` | usage / IO / render failure: bad flags, missing `--input` directory, empty input directory, an unavailable module, or a build that raised | `ar.py::_need`, `ingest.ingest`, argparse, `cmd_build`'s `except Exception` (writes `build-error.json`), `main()`'s catch-all |
| `3` | required artefact missing: `check` cannot find a spec, `result` cannot find `figure_spec.resolved.json` | `cmd_check`, `cmd_result` |
| `4` | illegal spec: `scene.validate_spec` produced at least one `severity:"error"` (also a `--spec` path that does not exist) | `cmd_autospec`, `cmd_build`, `cmd_check`, `cmd_edit` |

`exit 1` is unambiguous — **only** a gate failure produces it. If you see a traceback with exit `2`,
read `build-error.json`; a traceback on exit `1` would be a defect in this Skill, because `main()`
converts every other exception to `2`.

Notes that matter in practice:

* **A warn is not a failure.** `check` exits `0` when gates report `warn` — e.g. gate D's
  "no series/colour pairs to compare on a kind legend" branch. Read `validation_report.json` (or
  `result.json.audit.checks_warned`) rather than trusting the code.
* **`check` before `build`** → exit `3` (no spec found). **`result` before `build`** → exit `3`
  (`missing …/figure_spec.resolved.json`).
* **Spec rejected at build** → exit `4`, and `spec-issues.json` is written into `--out` with every
  `{code, severity, path, message}`. `autospec`/`edit` write `spec-issues.json` next to the output
  spec instead.
* **Spec-validation *warnings*** (e.g. `W010`, `W042`, `W048`, `W056`, `W057`, `W064`, `W070`,
  `W071`) are **not persisted by the CLI** — `ar.py` calls `scene.load_spec`, which discards warns
  on success. So the absence of a `spec-issues.json` does **not** mean there were no warnings. To
  see them, call `scene.validate_spec` yourself (§4).

## 4. Budget plan (64 requests / 900 s / 16384 tokens per response)

| Step | Requests | Notes |
|---|---|---|
| read `/input` | 1 | read `case.json`, `task.md`, and list materials in one pass |
| `ingest` | 1 | one shell call; then read `materials.json` once |
| author `spec.json` | 3–8 | the expensive step; write the whole file in one write, then validate locally |
| `build` + `result` + `check` + `result` | 1–2 | combine into a single shell invocation (measured: 31 s for the whole fixture sequence) |
| repair loop (if a gate fails) | 1–6 | edit the spec, rebuild, recheck — at most twice |
| final `result` + readback | 1 | |

Practical rules:

* **Do not re-read material from disk** after `ingest`; `materials.json` is the cache and carries
  the locators you need.
* **Validate the spec before building.** This is free and catches all `E*` errors:

  ```
  python3 -c "import json,sys; sys.path.insert(0,'scripts'); import scene; \
  s=json.load(open('/app/work/spec.json',encoding='utf-8')); \
  [print(i['severity'],i['code'],i['path'],i['message']) for i in scene.validate_spec(s)]"
  ```

  Empty output = zero errors and zero warnings. Fix every `error` here rather than paying for a
  failed `build`.
* **Batch shell work** into one call where possible; each call is a request.
* **Save a partial early.** After the first successful `build`, run `result` so an honest partial
  deliverable exists even if you run out of budget later.

## 5. Recovery from a failed gate

Read the gate detail — every detail string contains the measured number, so it tells you what to
change:

```
python3 -c "import json; r=json.load(open('/app/output/validation_report.json')); \
[print(c['id'], c['status'], c['detail']) for c in r['checks'] if c['status']!='pass']"
```

| Gate | Typical detail | Fix in `spec.json` |
|---|---|---|
| A | `%d outside, worst=<id> +X mm overshoot` | remove a node from an overcrowded panel, or reduce `meta.layout.columns` |
| B | `worst_overflow=<id> X mm > Y mm (bbox.w) +Z mm` | shorten `label`/`sublabel`; drop node/edge labels that crowd the cell (`W_EDGE_LABEL_TIGHT` is the early warning) |
| B | `worst_truncation=<id> N token(s) dropped: ['…']` | the layout ran out of room in that cell: shorten the label, or move content out of that panel |
| B | `missing in <id>: ['…']` | install a font that covers the character, or replace the character |
| B | `worst_size=<id> body X pt < 7.0pt` | do not shrink below the floor; drop content instead |
| C | `CVD dE X < 6.0 (…)` / `grayscale dL* X < 5.0` / `contrast N below WCAG` | give every legend item a distinct CVD-safe colour (identical swatches give ΔE 0.00), reduce the simultaneous categories, darken text |
| D | `legend[N] has K orphan item(s) not in any chart series` | make data-legend labels exactly the series names |
| D | `colorbar[…] declared A..B excludes node/edge values min=X max=Y` | set `vmin`/`vmax` to the real data range (15 % slack is allowed beyond it) |
| D | `scene arrow kinds {…} != spec edge kinds {…}` | the build dropped/retyped arrows — report it rather than editing exports |
| E | `dangling source ids, e.g. … -> 'E9'` | add the missing evidence item, or repoint the element |
| E | `first unresolved: E5 (quote (58 chars) not found verbatim in apparatus-list.md)` | copy the quote exactly from the material (whitespace may differ, words may not) |
| E | `module error: … has no evidence source` (`E903`) | every node, edge and chart series needs a `source` |
| E | `module error: value 7.0 is not present in the quote of evidence E2` (`E906`) | the number is not in the quote: cite the row/item that really contains it (`sources: [...]` for a multi-row series), declare `derived: true` + `source_values` if it is computed, or drop the number. **Numbers are read out of `label`/`sublabel` text too** |
| E | `module warn: … marked derived but declares no source_values` (`E907`) | add `source_values` with the real inputs, or remove `derived` and cite the value directly |
| F | `<g>` unnamed / duplicate ids / `0 non-empty <text> nodes` / `N required label(s) absent` | a layout or build defect; rebuild and report it — never rasterise to silence the gate |
| G | `NON-DETERMINISTIC: …` | a non-deterministic input leaked into the spec; fix it, do not re-run and hope |
| H | `PNG px … != page/dpi expectation …`, `PDF embeds 0 font programs`, `PDF … 0 Tj/TJ` | reinstall/point at a font that embeds; rebuild. Report if the backend is at fault |
| I | `N contract key(s) empty/missing: […]` | fix `case.json` usage / re-run `result`; drop any `--status` override |
| J | `J902 … step_no … gaps` | make `step_no` contiguous `1..N`, and give parallel nodes the *same* number (`/app/work` prints "legal parallel repeat") rather than inventing `.5` |
| J | `J904 … cycle …` | break the `phases[].depends_on` cycle (the message prints the cycle path) |
| J | `J906 … missing / reversed` | make `meta.expected_relations` and `panels[].declared_edges` match exactly what is drawn, including direction |
| K | `K901 … apparatus node(s) with a legal part: 10/11` | give every `role="apparatus"` node a `part` from the fixed enum |
| K | `K902 … port reference(s)` | declare the named port on the node (`nodes[].ports[]`) or drop it from `edge.ports` |
| K | `K903 merge/branch/waste` | merge targets need in-degree ≥ 2, branch sources out-degree ≥ 2, and a `waste` edge should end on a node with `part: "waste"` |
| K | `K904 legend declares (kind, linestyle, colour) x1 but the scene renders it x0` | put the colour **in the legend item**, not on the edge, and give each item a distinct colour so gate C stays green |

After **two** repair loops, stop and ship honestly:

```
python3 scripts/ar.py result --out /app/output --input /input --work /app/work --status partial
```

then put the failing gate id and its detail into the spec's `uncertainty` (or accept the
`check_failed` entry `result` already added) and say what is unresolved in your reply to the user.

## 6. Reproducing a run and checking determinism

Determinism is verified at **two different scopes**, and they are not interchangeable:

* **export scope** — gate **G** (`validate.py::gate_g`) re-exports an **already-built `scene.json`**
  into `.determinism_check/` and compares sha256 per artefact. It proves the *rendering half* is
  deterministic; it does **not** re-run `ingest → spec → layout`.
* **whole-chain scope** — `selftest.py`'s `determinism-full-chain` runs the entire pipeline twice
  from the same input in two fresh work directories and compares svg/png/pdf.

Check both:

```
# (a) build twice into different dirs  -- export scope, independent of gate G
python3 scripts/ar.py build --spec /app/work/spec.json --out /app/out1
python3 scripts/ar.py build --spec /app/work/spec.json --out /app/out2
python3 -c "import hashlib; [print(n, hashlib.sha256(open('/app/out1/'+n,'rb').read()).hexdigest()==hashlib.sha256(open('/app/out2/'+n,'rb').read()).hexdigest()) for n in ('figure.svg','figure.png','figure.pdf')]"

# (b) the build's own re-export comparison
python3 -c "import json;print(json.load(open('/app/out1/export_report.json'))['determinism'])"

# (c) gate G, which re-exports into .determinism_check and compares
python3 scripts/ar.py check --out /app/out1 --spec /app/work/spec.json --work /app/work
```

Gate G deletes its scratch directories (`.determinism_check`, `.edit_check`) in a `finally` block;
`export.py` likewise removes `.determinism_tmp`. If a run is interrupted those directories can be
left behind — they contain no deliverable and can be deleted, but they must not be shipped (they are
binaries under `--out`, which is the runtime output dir, not the bundle).

**Measured on the shipped fixture (2026-11-23 16:20):** gate G `pass` with
`figure.pdf run1=run2=091a61d844551981`, `figure.png c6fa268a990cd220`,
`figure.svg 3c88977cdab62973`; `export_report_claims_identical=True`. An independent rebuild into a
second directory (3 s later) reproduced the same three sha256 — verified in §5 of
[`rubric-mapping.md`](rubric-mapping.md).

## 7. Self-test, contract matrix and gain check

```
python3 scripts/ar.py selftest          # full: whole chain + injected-defect negatives
python3 scripts/ar.py selftest --quick  # skips the slow full-chain and negative phases
python3 scripts/contract_matrix.py      # adversarial output_contract key sets
python3 scripts/gain_check.py           # the measured 使用增益 A/B
```

`selftest` exercises the whole chain, **injected-defect negatives** (the discriminative test: a
defect must make a gate fail, otherwise the gate is not load-bearing), plus `determinism-full-chain`
and `contract-key-matrix`. `contract_matrix` builds cases whose `output_contract` uses plain /
exotic / colliding / terse-CJK / absent key names and asserts every declared key comes back
non-empty with `status:"ok"` and the `case_id` taken from `case.json`. `gain_check` is documented in
[`measured-gain.md`](measured-gain.md) — it is **not** a model-quality benchmark.

Run all of them after any change to a module, and treat a failure as a blocker.

### Scratch directories and re-runnability (measured 2026-11-23 13:4x)

An earlier revision of these two scripts hardcoded `<parent-of-submission>/verify/t3/<name>` as the
scratch root and copied with `shutil.copytree(..., dirs_exist_ok=False)`, which made them fail on a
second run — or when run concurrently — with `FileExistsError: … materials`. **That is fixed in the
shipped revision** (verified in source and in a live run):

* both scripts now use a **per-PID** scratch root (`verify/t3/gain_check.<pid>` /
  `verify/t3/contract-matrix-<pid>`) that the run creates and removes itself;
* both accept `--out DIR` to place the scratch elsewhere; `contract_matrix.py` also takes `--keep`;
* the copy uses `dirs_exist_ok=True`;
* measured: a fresh `python3 scripts/gain_check.py` run created `verify/t3/gain_check.29276/` and
  reported its own report path — no collision with the concurrently running teammate.

`gain_check.py` runs in **quick mode by default** (5 of the 9 defect classes, and the *defect*
condition exports SVG at 96 dpi to stay inside the budget); `--full` exercises all 9 classes with
svg+png+pdf at 300 dpi. Each individual run has a **300 s** cap (`RUN_TIMEOUT`), and a run that hits
it is reported as the condition failing with a negative exit code — see
[`measured-gain.md`](measured-gain.md).

**Harness budget (measured 14:13).** `selftest.py` caps each harness subprocess at **240 s**
(`selftest.py:42`) and invokes `contract_matrix.py` at `selftest.py:164` with that cap, but the
current `contract_matrix.py` performs **40 `ar.py` invocations** (10 key sets × 4 stages) and needs
**≈10 min**. Full `ar.py selftest` therefore fails at `harness-completed` with
`TimeoutExpired: … contract_matrix.py timed out after 240 seconds` even though every check that did
run passed — including `determinism-full-chain` and the ten injected-defect negatives. A single
`ar.py run` on the fixture measures **13.4 s** (exit `0`, `check: all checks passed (0 warn)`), so
this is a budget mismatch, not a slow pipeline. Use `selftest --quick` + a standalone
`contract_matrix.py` run as the verification pair until the cap is raised.
