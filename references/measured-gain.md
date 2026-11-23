# Measured gain (使用增益) — what this Skill actually buys

The rubric awards points for 使用增益 and asks for the gain to be **verifiable** by fair comparison.
This file records the controlled A/B that *can* be run locally, and states plainly what it does and
does not measure.

## What is and is not measured

| | |
|---|---|
| **Measured** | defect interception — **does a bad figure reach the user?** — and the verification artefacts the run delivers (evidence ledger, gates A–K, `result.json`) |
| **Not measured** | model quality against the platform's baseline agent. We cannot run the platform's un-Skilled agent here. **No score, speedup or "the model is better" claim is made anywhere in this bundle.** |
| Fair-comparison control | both conditions get the **same input directory**; every defect comparison injects into the **same base spec** and gives that identical spec to both conditions |
| Stop criterion | a defect counts as **intercepted only when a gate FAILS** (non-zero `check` exit). A defect that is merely warned about is counted separately as `B_warn_only` and never as interception |

Produced by [`scripts/gain_check.py`](../scripts/gain_check.py) — a bundled script, not a scratch
probe.

## Command and measured results

```
python3 scripts/gain_check.py            # default: quick mode, 5 of the 9 defect classes
python3 scripts/gain_check.py --full     # all 9 classes, defect exports at 300 dpi
python3 scripts/gain_check.py --out DIR  # scratch elsewhere (per-PID scratch by default)
```

Measured on the shipped tree (author re-run of this file, 2026-11-23 16:3x +08:00):

| Run | Mode | Classes | A (no gates) | B (Skill) | `B_warn_only` | Wall | Exit |
|---|---|---|---|---|---|---|---|
| quick (default) | quick | 5 / 9 | **0 / 5** | **5 / 5 stopped by a failing gate** | `0` | 39.2 s | `0` (`GAIN CHECK: PASS`) |
| `--full` (tool author's run) | full | 9 / 9 | **0 / 9** | **9 / 9 stopped by a failing gate** | `0` | 336.7 s | `0` |

Verbatim quick-mode output of the author's own run:

```
detection: A (no gates) 0/5 stopped  vs  B (skill) 5/5 stopped by a FAILING gate
gain_check.summary: mode=quick elapsed_s=39.2 A_detected=0/5 B_detected=5/5 B_warn_only=0
  run_errors=0 clean_gates=11 clean_result_json=true clean_A_validation_report=false
gain_check.claim: 5 of 5 injected defects are STOPPED by a failing gate in B, versus 0 of 5 in A
  (render-and-ship).
GAIN CHECK: PASS
```

An earlier revision of the harness counted a **warn-only** outcome as interception, so its numbers
looked better than the gate behaviour justified. That is fixed (`B_warn_only` is now reported and
excluded): the `waste_target_not_waste` defect used to come out as `B: exit=0` and is now
`B: exit=1, K=fail` — the gate really does block it.

## The two conditions

| | Condition A — "render and ship" | Condition B — the Skill |
|---|---|---|
| What it runs | `ar.py build` only | `ar.py run` = ingest → spec/autospec → build → check → result |
| Evidence ledger | 40 items on the clean run | 60 items (the whole ingest ledger) |
| Validation gates | **0** | **11** (A–K) |
| `validation_report.json` | **absent** | present |
| `result.json` | **absent** | present, `status: "ok"` |
| exit code (clean run) | `0` | `0` |

Read this honestly: on the clean run the two conditions also differ in *which* spec was used — A
rendered the hand-authored reference `spec.json`, while B's `ar.py run` derived its own spec with
`autospec` because no `spec.json` had been seeded in its work dir. So the clean-run row proves **what
the pipeline delivers** (a ledger, eleven gates and a contract-complete `result.json`), not that the
pipeline draws a better picture. The defect rows are the apples-to-apples comparison, because there
both conditions receive the same injected spec.

## Injected defects — quick mode (5 classes, measured 2026-11-23 16:3x)

| Defect | What is broken | A (no gates) | B (Skill) | Gate that fires |
|---|---|---|---|---|
| `reversed_connection` | a declared relation is drawn in the opposite direction | exit `0`, **ships it** | exit `1`, **stopped** | **J906** |
| `missing_connection` | a declared relation is not drawn | exit `0`, ships it | exit `1`, stopped | **J906** |
| `legend_colour_mismatch` | the legend's `(kind,linestyle,colour)` is not what is painted | exit `0`, ships it | exit `1`, stopped | **K904** |
| `step_number_gap` | `step_no` skips a value on a flow panel | exit `0`, ships it | exit `1`, stopped | **J902** |
| `number_not_in_quote` | a measured value is changed to a number no source contains | exit `0`, ships it | exit `1`, stopped | **E** (`E906`) |
| **total** | | **0 / 5** | **5 / 5** | |

## Injected defects — the 9-class matrix

The four secondary classes, added to the five above, complete the coverage of the workorder's own
failure list:

| Defect | B outcome | Gate that fires |
|---|---|---|
| `dangling_evidence` — an element cites an evidence id that does not exist | stopped | **E** (`E904`) |
| `apparatus_node_no_part` — a `role="apparatus"` node has no `part` | stopped | **K901** |
| `waste_target_not_waste` — a `waste` edge ends on a node that is not `part:"waste"` | stopped (`B: exit=1`, `K=fail`) | **K903** |
| `legend_label_orphan` — a data-legend label matches no chart series | stopped | **D** |
| **total (with the five above)** | **9 / 9 stopped by a failing gate** | |

## Why this is the right claim to make

The caught defects are exactly the failure classes this workorder names — a component that is not in
the apparatus list, a connection drawn the wrong way round or missing, a step sequence with a hole, a
legend that does not describe what is painted, an apparatus node with no apparatus semantics, and a
number that no source contains. A pipeline that catches them *mechanically* is the difference
between "a picture was produced" and "a figure that can enter a scientific workflow":

* a **reversed or missing** connection → **`J906`**, which compares the declared `(from,to,kind)`
  set against the rendered scene and prints `reversed` entries explicitly;
* a **step gap** → **`J902`**, which requires `step_no` to be `1..N` contiguous while accepting a
  *legal parallel repeat* for genuinely parallel trains;
* a **legend that lies** → **`K904`**, which compares the declared `(kind,linestyle,colour)` set
  with the rendered set;
* a **fabricated number** → **`E906`**, which requires every printed number to occur in the quote it
  cites, so a real evidence id cannot launder an invented value;
* a **dangling citation** → **`E904`**;
* an **apparatus node without semantics** → **`K901`**;
* a **waste line into the wrong place** → **`K903`**.

## Reproduce it yourself

```
python3 scripts/gain_check.py
python3 -c "import json,glob; p=sorted(glob.glob('<parent>/verify/t3/gain_check.*/gain_report.json'))[-1];\
r=json.load(open(p)); print(r['defect_detection'], r['clean_run']['B']['gates_run'], r['clean_run']['B']['has_result'])"
```

Expect `{'A': 0, 'B': 5, 'n': 5}` … `11 True` in quick mode, and `n: 9` under `--full`.

## Related verification artefacts

| Artefact | What it proves | Command | Measured (2026-11-23 16:3x) |
|---|---|---|---|
| `scripts/contract_matrix.py` | unknown `output_contract` key names never silently empty the result (per-PID scratch, `--out`, `--keep`) | `python3 scripts/contract_matrix.py` | exit `0`, `CONTRACT MATRIX: PASS (10/10 key sets)`, 260.6 s |
| `scripts/ar.py selftest` | whole chain + injected-defect negatives + full-chain determinism + bundle budget; its in-harness contract check is the `--quick` 4-set subset | `python3 scripts/ar.py selftest` | exit `0`, **23/23**, 233.5 s |
| `scripts/ar.py selftest --quick` | the fast subset (`determinism`, gates A–K present, svg-is-text, bundle budget) | `python3 scripts/ar.py selftest --quick` | exit `0`, **11/11**, 25.5 s |
| gate suite A–K | the eleven measured gates that did the detection above | `python3 scripts/ar.py check --out OUT --spec SPEC --work WORK` | exit `0`, 0 failed, 0 warn |

The one intermittent determinism observation from earlier the same day is carried forward honestly
in [`failure-modes.md`](failure-modes.md) §6; it has not recurred on the shipped tree.
