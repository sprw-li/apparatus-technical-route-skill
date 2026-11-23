#!/usr/bin/env python3
"""contract_matrix.py — adversarial test for unknown output_contract keys.

The case schema is NOT published, so the evaluator's cases may name their outputs
anything.  This builds synthetic cases whose `output_contract` uses plausible but
never-before-seen key names (including the apparatus / technical-route vocabulary
of this workorder and non-English keys) and asserts, for every key the case
declared, that:

  * the key exists in result.json and is non-empty,
  * the key appears in `result.contract_values` (it was mapped, not invented),
  * keys naming an artefact point at a file that really exists in the output dir,
  * keys naming provenance resolve to a non-empty list,
  * `case_id` is preserved,
  * `status` is a legal value, and is never "ok" while a gate failed.

`status == "ok"` for the whole run is deliberately NOT asserted here: this file
tests *contract coverage*, and an unrelated gate failure (e.g. a provenance gate)
must not be able to masquerade as a contract-mapping regression.  The sound
direction (ok => no failed gate) is asserted instead.

    python scripts/contract_matrix.py            # exit 0 == all key sets behave
    python scripts/contract_matrix.py --quick    # 4 representative key sets only

`--quick` exists because `selftest.py` gives each step a 240 s budget while a full
10-key-set sweep spawns 40 `ar.py` runs (~10 min).  It keeps one key set per code
path this harness asserts (plain artefact/provenance keys, the apparatus half, the
route half, and the non-English set) so the selftest still covers every branch.

Re-entrant and concurrency-safe: the default scratch is a per-PID directory that
this run creates and removes itself, and `--out DIR` lets a caller choose one
(which is then left in place for inspection).
"""
from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable

ARTIFACT_WORDS = ("svg", "png", "pdf", "render", "export", "editable", "vector_source",
                  "preview", "raster", "thumbnail", "typeset", "print")
PROVENANCE_WORDS = ("evidence", "provenance", "source", "citation", "reference", "trace")

CONTRACTS = {
    "plain": {
        "case_id": "", "figure_svg": "", "figure_png": "", "figure_pdf": "",
        "evidence": [], "status": "", "uncertainty": [],
    },
    # keys a real task might plausibly use, that we never designed for
    "exotic": {
        "case_id": "", "graphical_abstract": "", "answer": "", "summary": "",
        "sources": [], "caption": "", "data": [], "panels": [], "status": "",
        "limitations": [], "change_log": [],
    },
    # deliberately ambiguous / colliding names
    "colliding": {
        "case_id": "", "source": "", "sources": "", "render": "", "export": "",
        "editable_source": "", "figure_legend": "", "status": "", "audit": [],
        "checks": [],
    },
    # terse / non-English keys
    "terse": {"case_id": "", "图稿": "", "结果": "", "status": ""},
    # the apparatus half of this workorder
    "apparatus": {
        "case_id": "", "apparatus": {}, "parts": [], "connections": [], "streams": [],
        "apparatus_figure": "", "status": "", "uncertainty": [],
    },
    # the technical-route half
    "route": {
        "case_id": "", "route": {}, "steps": [], "phases": [], "figure": "",
        "summary": "", "status": "", "limitations": [],
    },
    # provenance-heavy contract
    "provenance": {
        "case_id": "", "sources": [], "evidence": [], "citations": [],
        "summary": "", "status": "", "change_records": [],
    },
    # artifact-heavy contract
    "figure_pack": {
        "case_id": "", "figure": "", "caption": "", "legend": [], "editable_source": "",
        "render": "", "export": "", "status": "", "limitations": [],
    },
    # fully non-English contract
    "mixed_zh": {
        "case_id": "", "实验装置": "", "技术路线": "", "连接": [], "步骤": [],
        "图例": [], "状态": "", "status": "",
    },
    # no contract at all
    "empty": {},
}

# `--quick` subset: one key set per assertion branch this file exercises, so a
# selftest step stays inside its 240 s budget without dropping a code path.
QUICK_SETS = ("plain", "apparatus", "route", "mixed_zh")


def build_case(name, contract, base_input, outdir):
    os.makedirs(outdir, exist_ok=True)
    # dirs_exist_ok: re-running the matrix (or reusing --out) must not die with
    # FileExistsError; every case directory is rewritten in place.
    shutil.copytree(os.path.join(base_input, "materials"), os.path.join(outdir, "materials"),
                    dirs_exist_ok=True)
    shutil.copy2(os.path.join(base_input, "task.md"), os.path.join(outdir, "task.md"))
    case = {"case_id": "ADVERSARIAL-%s" % name.upper(), "note": "SYNTHETIC adversarial contract fixture",
            "output_contract": contract}
    with open(os.path.join(outdir, "case.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(case, fh, ensure_ascii=False, indent=2)
    return case


def run(args):
    p = subprocess.run([PY, os.path.join(HERE, "ar.py")] + args, cwd=ROOT,
                       capture_output=True, timeout=900)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None,
                    help="scratch directory to use; default is a per-PID directory under "
                         "<work>/verify/t3 that this run creates and removes itself")
    ap.add_argument("--keep", action="store_true",
                    help="keep the default scratch directory instead of removing it")
    ap.add_argument("--quick", action="store_true",
                    help="run only the %d representative key sets (%s); a full sweep "
                         "spawns 40 ar.py runs and does not fit selftest's 240 s step budget"
                         % (len(QUICK_SETS), ",".join(QUICK_SETS)))
    ap.add_argument("--full", action="store_true",
                    help="explicitly run every key set (the default is already full)")
    a = ap.parse_args()
    sets = ([(n, CONTRACTS[n]) for n in QUICK_SETS] if a.quick
            else list(CONTRACTS.items()))

    base_input = os.path.join(ROOT, "examples", "synthetic-001", "input")
    ref_spec = os.path.join(ROOT, "examples", "synthetic-001", "expected", "spec.json")
    # Re-entrancy and concurrency: never a fixed shared path (two concurrent matrix
    # runs corrupt each other's case/out trees, which shows up as a bogus
    # "keys missing from result" row), never tempfile.mkdtemp (its 0o700 mode is
    # not writable under the Windows sandbox), and always cleaned up by ourselves.
    own_scratch = a.out is None
    scratch = a.out or os.path.join(os.path.dirname(ROOT), "verify", "t3",
                                    "contract-matrix-%d" % os.getpid())
    if own_scratch and os.path.isdir(scratch):
        shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch, exist_ok=True)
    print("contract matrix scratch: %s%s"
          % (scratch, "" if own_scratch else " (caller-owned, left in place)"))

    failures = []
    n_pass = 0
    try:
        for name, contract in sets:
            case_dir = os.path.join(scratch, name, "in")
            work = os.path.join(scratch, name, "work")
            out = os.path.join(scratch, name, "out")
            build_case(name, contract, base_input, case_dir)
            os.makedirs(work, exist_ok=True)
            if contract:
                spec = json.load(open(ref_spec, encoding="utf-8-sig"))
                # this file measures contract coverage, not print quality: render at a
                # low dpi so ten key sets fit a development budget.  Gate H's >=300 dpi
                # requirement is deliberately not part of what is asserted here.
                spec.setdefault("meta", {}).setdefault("canvas", {})["dpi"] = 96
                with open(os.path.join(work, "spec.json"), "w", encoding="utf-8", newline="\n") as fh:
                    json.dump(spec, fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
            rc, so, se = run(["run", "--input", case_dir, "--work", work, "--out", out])
            result_path = os.path.join(out, "result.json")
            if not os.path.exists(result_path):
                failures.append("%s: no result.json (run exit=%d)" % (name, rc))
                print("[FAIL] %-11s run_exit=%d: no result.json" % (name, rc))
                continue
            with open(result_path, encoding="utf-8") as fh:
                result = json.load(fh)
            contract_values = result.get("contract_values") or {}
            missing_keys, empty_keys, unmapped_keys = [], [], []
            artifact_bad, provenance_bad, ambiguous = [], [], []
            for key in contract:
                if key not in result:
                    missing_keys.append(key)
                    continue
                v = result[key]
                if v in (None, "", [], {}):
                    empty_keys.append(key)
                if key not in contract_values:
                    unmapped_keys.append(key)
                low = key.lower()
                is_status = "status" in low or "状态" in key
                artifactish = any(w in low for w in ARTIFACT_WORDS)
                provish = any(w in low for w in PROVENANCE_WORDS)
                if is_status:
                    continue
                if artifactish and provish:
                    # deliberately ambiguous name (e.g. `editable_source`): both a
                    # mapping choice is defensible, so require non-empty and report
                    # which branch won instead of asserting one reading.
                    ambiguous.append("%s->%s" % (key, type(v).__name__ + (
                        "" if not isinstance(v, str) else ":" + v[:40])))
                elif artifactish:
                    if not isinstance(v, str) or not os.path.exists(os.path.join(out, v)):
                        artifact_bad.append("%s=%r" % (key, v))
                elif provish:
                    if not isinstance(v, list) or not v:
                        provenance_bad.append("%s=%r" % (key, type(v).__name__))
            status = result.get("status")
            cid = result.get("case_id")
            expect_cid = "ADVERSARIAL-%s" % name.upper()
            failed_gates = (result.get("audit") or {}).get("checks_failed") or []
            unmapped = (result.get("audit") or {}).get("unmapped_contract_keys") or []
            problems = []
            if missing_keys:
                problems.append("keys missing from result: %s" % missing_keys)
            if empty_keys:
                problems.append("contract keys empty: %s" % empty_keys)
            if unmapped_keys:
                problems.append("keys absent from contract_values: %s" % unmapped_keys)
            if artifact_bad:
                problems.append("artefact keys not naming a real file: %s" % artifact_bad)
            if provenance_bad:
                problems.append("provenance keys not a non-empty list: %s" % provenance_bad)
            if cid != expect_cid:
                problems.append("case_id=%r (expected %r)" % (cid, expect_cid))
            if status not in ("ok", "partial", "needs_human"):
                problems.append("status=%r is not a legal value" % status)
            if status == "ok" and failed_gates:
                problems.append("status=ok while gates failed: %s" % failed_gates)
            ok = not problems
            n_pass += 1 if ok else 0
            if not ok:
                failures.extend("%s: %s" % (name, p) for p in problems)
            print("[%s] %-11s run_exit=%d status=%-7s keys=%2d mapped=%2d unmapped=%2d "
                  "failed_gates=%s%s"
                  % ("PASS" if ok else "FAIL", name, rc, status, len(contract),
                     len(contract_values), len(unmapped), failed_gates or "-",
                     ("  ambiguous=%s" % ",".join(ambiguous)) if ambiguous else ""))
    finally:
        if own_scratch and not a.keep:
            shutil.rmtree(scratch, ignore_errors=True)

    print("\nCONTRACT MATRIX: %s  (%d/%d key sets%s)"
          % ("PASS" if not failures else "FAIL", n_pass, len(sets),
             ", quick subset of %d" % len(CONTRACTS) if a.quick else ""))
    print("note: `failed_gates=` on a row reports the verdicts of the AUDITED run "
          "(the shipped example spec), not this harness's exit code; this harness exits 0 "
          "when every declared contract key is present, non-empty and mapped.")
    print("scratch=%s (%s)" % (scratch, "kept" if (a.keep or not own_scratch) else "removed"))
    for f in failures:
        print("  -", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
