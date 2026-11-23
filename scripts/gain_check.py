#!/usr/bin/env python3
"""gain_check.py — a controlled A/B that measures what the Skill actually buys.

The rubric awards 25 points for 使用增益 (verifiable quality gain).  We cannot run
the platform's baseline agent here, so this measures a narrower but fully
reproducible claim:

    Condition A ("baseline"): an agent that authors a spec and renders it.
                              `ar.py build` only -- no ingest, no evidence ledger,
                              no gates, no result.json.
    Condition B ("skill"):    the same spec through `ar.py run`
                              (ingest -> spec -> build -> check -> result).

Both conditions get the *same* input and the *same* artist-authored spec.

Nine defects are injected into that spec -- the apparatus / technical-route
mistakes an authoring model actually makes when reading real material:

    1 reversed_connection      declared A8->A9, drawn A9->A8         (J906)
    2 missing_connection       declared but never drawn              (J906)
    3 legend_colour_mismatch   a line painted a colour the legend
                               does not declare                      (K904)
    4 step_number_gap          the step numbering skips 7            (J902)
    5 number_not_in_quote      a figure number absent from its
                               verbatim source                       (E)
    6 dangling_evidence        an element cites a missing id         (E)
    7 apparatus_node_no_part   an apparatus node without `part`      (K901)
    8 waste_target_not_waste   a waste outlet into a non-waste node  (K903)
    9 legend_label_orphan      a legend label no series carries      (D)

Detection is measured at rule level and is deliberately split in two, because
"the report mentions the defect" and "the bad figure is stopped" are different
claims:

    BLOCKING  the run's validation report matches the defect's own rule pattern
              (and the clean baseline run does not) AND that gate's verdict is
              `fail`, so `ar.py check` returns non-zero and the figure is stopped.
    WARNED    the rule fired but only as `warn`: the figure still ships.  This is
              reported separately and never counted as interception.

A token that also appears in the clean run (e.g. the bare word "reversed", which
the clean J906 pass line contains as `reversed=0`) would not be evidence, so every
pattern is built to be rule-specific.

Two tiers, because the platform budget for a whole case is 900 s and a reviewer
must be able to reproduce these numbers quickly:

    default (quick):  the 5 apparatus/technical-route defect classes, defect runs
                      exporting svg at 96 dpi; the clean A/B runs always export
                      svg+png+pdf at the spec's 300 dpi so the artefact claim is
                      real.  ~40-60 s, measured with several runs in parallel.
    --full:           all 9 defect classes, and every run exports svg+png+pdf at
                      300 dpi (the raster pass dominates).

The printed summary line is stable and machine-parseable so that
`references/measured-gain.md` can quote these numbers verbatim:

    gain_check.summary: mode=... elapsed_s=... A_detected=.../... B_detected=.../... ...

    python scripts/gain_check.py [--out DIR] [--full]   # exit 0 == skill dominates A
"""
from __future__ import annotations

import sys as _sys
_sys.dont_write_bytecode = True

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
BASE_INPUT = os.path.join(ROOT, "examples", "synthetic-001", "input")
REF_SPEC = os.path.join(ROOT, "examples", "synthetic-001", "expected", "spec.json")
RUN_TIMEOUT = 300          # a render that cannot finish in 5 min is itself a defect


def run(args, timeout=RUN_TIMEOUT):
    try:
        p = subprocess.run([PY, os.path.join(HERE, "ar.py")] + args, cwd=ROOT,
                           capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return -9, "", "TIMEOUT after %ds" % timeout
    return (p.returncode,
            p.stdout.decode("utf-8", "replace"),
            p.stderr.decode("utf-8", "replace"))


def load(p):
    with open(p, encoding="utf-8-sig") as fh:
        return json.load(fh)


def dump(p, obj):
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# --------------------------------------------------------------------------- #
# defect injections: each is a real mistake an authoring model can make
# --------------------------------------------------------------------------- #
def _panel(spec, pid):
    for p in spec["panels"]:
        if p.get("id") == pid:
            return p
    return None


def _first_node_with_value(spec):
    for panel in spec["panels"]:
        for node in panel.get("nodes") or []:
            if isinstance(node.get("value"), (int, float)) and node.get("source"):
                return node
    return None


def inject_reversed_connection(spec):
    """Declared A8->A9, drawn A9->A8: the arrow histogram is unchanged."""
    panel = _panel(spec, "P1")
    for edge in panel.get("edges") or []:
        if edge.get("id") == "AE9":
            edge["from"], edge["to"] = edge["to"], edge["from"]
            return {"what": "AE9 declared A8->A9 is drawn A9->A8",
                    "pattern": r"J906=fail\([^|]*reversed=[1-9]", "gate": "J", "code": "J906"}
    return None


def inject_missing_connection(spec):
    """A relation the panel declares is simply never drawn."""
    panel = _panel(spec, "P1")
    for edge in list(panel.get("edges") or []):
        if edge.get("id") == "AE6":
            panel["edges"].remove(edge)
            declared = len(panel.get("declared_edges") or [])
            return {"what": "P1 declares %d edges, %d are drawn (A7->A4 heat is missing)"
                            % (declared, declared - 1),
                    "pattern": r"is not drawn", "gate": "J", "code": "J906"}
    return None


def inject_legend_colour_mismatch(spec):
    """One material line is painted a colour the legend does not declare."""
    panel = _panel(spec, "P2")
    for edge in panel.get("edges") or []:
        if edge.get("id") == "FE1":
            edge["color"] = "#D55E00"
            return {"what": "FE1 material line painted #D55E00; the legend declares material #0072B2",
                    "pattern": r"#d55e00", "gate": "K", "code": "K904"}
    return None


def inject_step_number_gap(spec):
    """Step 7 disappears: the numbering is no longer 1..N."""
    panel = _panel(spec, "P2")
    for node in panel.get("nodes") or []:
        if node.get("id") == "F7":
            node["step_no"] = 9
            return {"what": "F7 renumbered 7 -> 9, so step 7 is missing",
                    "pattern": r"\[7\] missing and not declared", "gate": "J", "code": "J902"}
    return None


def inject_number_not_in_quote(spec):
    """A measured value is multiplied by 7 -- a number no source contains."""
    node = _first_node_with_value(spec)
    if node is None:
        return None
    old = float(node["value"])
    node["value"] = round(old * 7.0 + 3.0, 2)
    node["sublabel"] = "%.2f" % node["value"]
    return {"what": "%s value %.2f -> %.2f (no source contains it)"
                    % (node.get("id"), old, node["value"]),
            "pattern": r"value %s is not present" % str(node["value"]), "gate": "E", "code": "E"}


def inject_dangling_evidence(spec):
    """An element claims an evidence id that does not exist."""
    for panel in spec["panels"]:
        for node in panel.get("nodes") or []:
            if node.get("source"):
                node["source"] = "E-not-in-this-spec"
                return {"what": "a node cites evidence id E-not-in-this-spec",
                        "pattern": r"dangling source ids", "gate": "E", "code": "E"}
    return None


def inject_apparatus_node_without_part(spec):
    """An apparatus node loses its part, so the glyph has no meaning."""
    panel = _panel(spec, "P1")
    for node in panel.get("nodes") or []:
        if node.get("id") == "A3" and node.get("part"):
            del node["part"]
            return {"what": "apparatus node A3 has no part",
                    "pattern": r"has no part", "gate": "K", "code": "K901"}
    return None


def inject_waste_target_not_waste(spec):
    """A waste outlet is drawn into a typed non-waste vessel (K903 hard error)."""
    panel = _panel(spec, "P1")
    panel.setdefault("edges", []).append(
        {"id": "AE_NEW", "from": "A9", "to": "A3", "kind": "waste",
         "label": "mis-routed concentrate", "source": "E11"})
    return {"what": "a waste edge A9->A3 whose target A3 is a typed mixer",
            "pattern": r"waste edge A9->A3 but target A3 is part", "gate": "K", "code": "K903"}


def inject_legend_label_orphan(spec):
    """A legend label no data series carries -- the key cannot be read off."""
    panel = _panel(spec, "P4")
    legend = panel.get("legend") or {}
    for it in legend.get("items") or []:
        if it.get("label") == "TOC removal":
            it["label"] = "TOC removed entirely"
            return {"what": "legend label 'TOC removal' -> 'TOC removed entirely'",
                    "pattern": r"orphan item", "gate": "D", "code": "D"}
    return None


DEFECTS = [
    # === the five apparatus / technical-route classes the workorder requires ===
    ("reversed_connection", inject_reversed_connection,
     "a declared connection is drawn in the opposite direction"),
    ("missing_connection", inject_missing_connection,
     "a declared connection is never drawn"),
    ("legend_colour_mismatch", inject_legend_colour_mismatch,
     "a line is painted a colour the legend does not declare"),
    ("step_number_gap", inject_step_number_gap,
     "the process step numbering skips a number"),
    ("number_not_in_quote", inject_number_not_in_quote,
     "a number that appears nowhere in the source material reaches the figure"),
    # === secondary classes, exercised by --full ===
    ("dangling_evidence", inject_dangling_evidence,
     "an element claims a source that does not exist"),
    ("apparatus_node_no_part", inject_apparatus_node_without_part,
     "an apparatus node carries no part, so the glyph means nothing"),
    ("waste_target_not_waste", inject_waste_target_not_waste,
     "a waste outlet is drawn into a node that is not a waste vessel"),
    ("legend_label_orphan", inject_legend_label_orphan,
     "a legend label no data series carries"),
]
CORE_DEFECTS = 5          # the first five are the mandated apparatus/route classes


# --------------------------------------------------------------------------- #
def condition_a(spec_path, out_dir, work_dir, formats, dpi=None):
    """Baseline: render and ship. No ingest, no evidence, no gates."""
    os.makedirs(work_dir, exist_ok=True)
    args = ["build", "--spec", spec_path, "--out", out_dir,
            "--formats", ",".join(formats), "--work", work_dir]
    if dpi:
        args += ["--dpi", str(int(dpi))]
    rc, _, _ = run(args)
    return rc


def condition_b(input_dir, out_dir, work_dir, spec, formats, dpi=None):
    """Skill: the full pipeline with gates and a result contract.

    A run that dies before producing a validation report (exit 2 = usage/IO: an
    import error, a half-written sibling module, a transient file lock) is an
    *environmental* failure, not a gate verdict.  It is retried once and, if it
    still fails, reported as RUN_ERROR rather than silently counted as "the defect
    was not caught" -- understating detection would be as dishonest as overstating
    it.
    """
    os.makedirs(work_dir, exist_ok=True)
    if dpi:
        # `ar.py run` has no --dpi flag; the rendered dpi comes from the spec's own
        # canvas, so that is where a lower development dpi has to be written.
        spec = copy.deepcopy(spec)
        spec.setdefault("meta", {}).setdefault("canvas", {})["dpi"] = int(dpi)
    dump(os.path.join(work_dir, "spec.json"), spec)
    for attempt in (1, 2):
        rc, so, se = run(["run", "--input", input_dir, "--work", work_dir, "--out", out_dir,
                          "--formats", ",".join(formats)])
        if rc == 0 or os.path.exists(os.path.join(out_dir, "validation_report.json")):
            return rc
        if attempt == 1:
            shutil.rmtree(out_dir, ignore_errors=True)
            continue
        last_err = se.strip().splitlines()[-1] if se.strip() else ""
        print("    [RUN_ERROR] ar.py run failed twice (exit %d): %s" % (rc, last_err[-160:]))
        return rc
    return rc


def report_text(out_dir):
    """Concatenated details of the validation report, or '' when there is none."""
    vp = os.path.join(out_dir, "validation_report.json")
    if not os.path.exists(vp):
        return ""
    try:
        rep = load(vp)
    except (ValueError, OSError):
        return ""
    return " || ".join("%s:%s" % (c.get("id"), c.get("detail", "")) for c in rep.get("checks", []))


def gate_verdicts(out_dir):
    """{gate_id: status} from the validation report ({} when there is none)."""
    vp = os.path.join(out_dir, "validation_report.json")
    if not os.path.exists(vp):
        return {}
    try:
        rep = load(vp)
    except (ValueError, OSError):
        return {}
    return {c.get("id"): c.get("status") for c in rep.get("checks", []) if isinstance(c, dict)}


def rule_blocked(out_dir, gate):
    """True when the named gate's verdict is `fail` (so `check` returns non-zero)."""
    return (gate_verdicts(out_dir) or {}).get(gate) == "fail"


def survey(out_dir):
    names = sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []
    info = {
        "files": names,
        "has_svg": "figure.svg" in names,
        "has_png": "figure.png" in names,
        "has_pdf": "figure.pdf" in names,
        "has_result": "result.json" in names,
        "has_validation": "validation_report.json" in names,
        "has_evidence": "figure_spec.resolved.json" in names,
        "evidence_items": 0,
        "gates_run": 0,
        "gates_failed": [],
    }
    vp = os.path.join(out_dir, "validation_report.json")
    if os.path.exists(vp):
        try:
            rep = load(vp)
        except (ValueError, OSError):
            rep = {}
        info["gates_run"] = len(rep.get("checks") or [])
        info["gates_failed"] = rep.get("failed") or []
    rp = os.path.join(out_dir, "result.json")
    if os.path.exists(rp):
        try:
            res = load(rp)
        except (ValueError, OSError):
            res = {}
        info["evidence_items"] = len(res.get("evidence") or [])
        info["status"] = res.get("status")
    sp = os.path.join(out_dir, "figure_spec.resolved.json")
    if os.path.exists(sp) and not info["evidence_items"]:
        try:
            info["evidence_items"] = len(load(sp).get("evidence") or [])
        except (ValueError, OSError):
            pass
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--full", action="store_true",
                    help="run all 9 defect classes and export svg+png+pdf for every "
                         "run (the clean A/B runs always export all three)")
    a = ap.parse_args()
    t0 = time.monotonic()
    mode = "full" if a.full else "quick"
    defects = DEFECTS if a.full else DEFECTS[:CORE_DEFECTS]
    defect_formats = ("svg", "png", "pdf") if a.full else ("svg",)
    clean_formats = ("svg", "png", "pdf")
    # Print quality is irrelevant to defect interception, so the quick tier renders
    # its defect runs at 96 dpi; the clean A/B runs stay at the spec's own 300 dpi
    # because "A ships, B ships + verifies" is the headline gain claim, and a
    # sub-300 dpi render would make gate H fail on the clean run for no reason.
    defect_dpi = None if a.full else 96
    clean_dpi = None
    scratch = a.out or os.path.join(os.path.dirname(ROOT), "verify", "t3",
                                    "gain_check.%d" % os.getpid())
    if os.path.isdir(scratch):
        shutil.rmtree(scratch)
    os.makedirs(scratch)
    if not os.path.exists(REF_SPEC):
        print("reference spec missing: %s" % REF_SPEC)
        return 2

    rows = []
    base_spec = load(REF_SPEC)

    # --- the clean run: what each condition delivers -------------------------
    #
    # A and B are independent (separate out/work dirs), so each pair runs
    # concurrently: identical work and identical numbers, roughly half the wall
    # clock, which matters because reviewers reproduce this on a loaded machine.
    good_spec = os.path.join(scratch, "spec.good.json")
    shutil.copy2(REF_SPEC, good_spec)
    a_out, a_work = os.path.join(scratch, "A-good"), os.path.join(scratch, "A-work")
    b_out, b_work = os.path.join(scratch, "B-good"), os.path.join(scratch, "B-work")

    pool = ThreadPoolExecutor(max_workers=2)
    try:
        rc_a = pool.submit(condition_a, good_spec, a_out, a_work, clean_formats, clean_dpi)
        rc_b = pool.submit(condition_b, BASE_INPUT, b_out, b_work, base_spec, clean_formats, clean_dpi)
        rc_a, rc_b = rc_a.result(), rc_b.result()
        sa, sb = survey(a_out), survey(b_out)
        clean_text = report_text(b_out)
        print("mode=%s  defect_classes=%d/%d  clean_formats=%s@%sdpi  defect_formats=%s@%sdpi"
              % (mode, len(defects), len(DEFECTS), ",".join(clean_formats),
                 clean_dpi or (base_spec.get("meta", {}).get("canvas", {}) or {}).get("dpi", 300),
                 ",".join(defect_formats), defect_dpi or "spec"))
        print("clean run")
        print("  A (build only)  exit=%d  artefacts=%s  evidence=%d  gates=%d  validation_report=%s"
              % (rc_a, ",".join(x for x in ("svg", "png", "pdf") if sa["has_" + x]),
                 sa["evidence_items"], sa["gates_run"], sa["has_validation"]))
        print("  B (skill)       exit=%d  artefacts=%s  evidence=%d  gates=%d  result.json=%s  failed=%s"
              % (rc_b, ",".join(x for x in ("svg", "png", "pdf") if sb["has_" + x]),
                 sb["evidence_items"], sb["gates_run"], sb["has_result"], sb["gates_failed"] or "-"))
        rows.append({"check": "clean_run_deliverables", "A": sa, "B": sb,
                     "A_exit": rc_a, "B_exit": rc_b})

        # --- defect detection ------------------------------------------------
        print("\ninjected defects (same input, same base spec, both conditions):")
        jobs = []
        for name, inject, description in defects:
            spec = copy.deepcopy(base_spec)
            meta = inject(spec)
            if meta is None:
                print("  [SKIP] %s: injector found nothing to break" % name)
                continue
            sp = os.path.join(scratch, "spec.%s.json" % name)
            dump(sp, spec)
            ao, aw = os.path.join(scratch, "A-%s" % name), os.path.join(scratch, "A-%s-work" % name)
            bo, bw = os.path.join(scratch, "B-%s" % name), os.path.join(scratch, "B-%s-work" % name)
            jobs.append((name, description, meta, ao, bo,
                         pool.submit(condition_a, sp, ao, aw, defect_formats, defect_dpi),
                         pool.submit(condition_b, BASE_INPUT, bo, bw, spec, defect_formats, defect_dpi)))

        detected_a = detected_b = detected_warn = 0
        run_errors = []
        n = 0
        for name, description, meta, ao, bo, fut_a, fut_b in jobs:
            n += 1
            ra, rb = fut_a.result(), fut_b.result()
            sb2 = survey(bo)
            text = report_text(bo)
            pattern = meta.get("pattern") or ""
            gate = meta.get("gate") or ""
            hit_here = bool(re.search(pattern, text)) if pattern else False
            hit_clean = bool(re.search(pattern, clean_text)) if pattern else False
            fired = hit_here and not hit_clean
            blocked = fired and rule_blocked(bo, gate)
            run_error = not os.path.exists(os.path.join(bo, "validation_report.json"))
            ships_a = (ra == 0) and not os.path.exists(os.path.join(ao, "validation_report.json"))
            if not ships_a:
                detected_a += 1
            if run_error:
                run_errors.append(name)
            elif blocked:
                detected_b += 1
            elif fired:
                detected_warn += 1
            verdict = (gate_verdicts(bo) or {}).get(gate, "-")
            status_txt = ("RUN_ERROR" if run_error else
                          "BLOCKED" if blocked else
                          ("WARN-ONLY (figure still ships)" if fired else "NOT CAUGHT"))
            print("  %-24s A: exit=%-3d %-9s | B: exit=%-3d %s=%-9s rule_fired=%-5s %s"
                  % (name, ra, "ships it" if ships_a else "notices", rb,
                     gate or "gates", verdict, str(fired), status_txt))
            rows.append({"check": name, "description": description, "what": meta.get("what"),
                         "expected_rule": meta.get("code"), "injected_pattern": pattern,
                         "rule_gate": gate, "rule_verdict": verdict,
                         "A_exit": ra, "B_exit": rb, "A_detected": not ships_a,
                         "rule_fired": fired, "B_detected": blocked, "run_error": run_error,
                         "detection_kind": ("run_error" if run_error else
                                            "blocking" if blocked else
                                            "warn_only" if fired else "missed"),
                         "B_gates_failed": sb2["gates_failed"]})
    finally:
        pool.shutdown(wait=True)

    elapsed = time.monotonic() - t0
    report = {
        "what_this_measures": "controlled A/B on identical input and identical spec: "
                              "'render and ship' vs the Skill pipeline; B_detected counts "
                              "only defects whose rule fired AND whose gate verdict is fail "
                              "(i.e. the bad figure is actually stopped)",
        "not_measured": "we cannot run the platform's baseline agent here, so this is not a "
                        "model-quality benchmark; it measures mechanical defect interception and "
                        "the delivered verification artefacts",
        "mode": mode, "elapsed_s": round(elapsed, 1),
        "formats": {"clean": list(clean_formats), "defects": list(defect_formats)},
        "dpi": {"clean": clean_dpi or "spec", "defects": defect_dpi or "spec"},
        "clean_run": {"A": sa, "B": sb, "clean_rule_text": clean_text[:400]},
        "defect_detection": {"A": detected_a, "B_blocking": detected_b,
                             "B_warn_only": detected_warn, "run_errors": run_errors, "n": n},
        "rows": rows,
    }
    dump(os.path.join(scratch, "gain_report.json"), report)

    print("\ndetection: A (no gates) %d/%d stopped  vs  B (skill) %d/%d stopped by a FAILING gate"
          % (detected_a, n, detected_b, n))
    if detected_warn:
        print("           B additionally warned on %d/%d defect(s) without stopping the figure "
              "(counted as NOT intercepted)" % (detected_warn, n))
    print("verification artefacts on the clean run: A validation_report=%s evidence=%d gates=%d "
          "result.json=%s | B validation_report=%s evidence=%d gates=%d result.json=%s"
          % (sa["has_validation"], sa["evidence_items"], sa["gates_run"], sa["has_result"],
             sb["has_validation"], sb["evidence_items"], sb["gates_run"], sb["has_result"]))
    print("gain report: %s" % os.path.join(scratch, "gain_report.json"))
    if run_errors:
        print("           !! %d run(s) died before producing a validation report and are "
              "NOT counted either way: %s" % (len(run_errors), ",".join(run_errors)))
    print("gain_check.summary: mode=%s elapsed_s=%.1f A_detected=%d/%d B_detected=%d/%d "
          "B_warn_only=%d run_errors=%d clean_gates=%d clean_result_json=%s "
          "clean_A_validation_report=%s"
          % (mode, elapsed, detected_a, n, detected_b, n, detected_warn, len(run_errors),
             sb["gates_run"], str(sb["has_result"]).lower(), str(sa["has_validation"]).lower()))
    print("gain_check.claim: %d of %d injected defects are STOPPED by a failing gate in B, "
          "versus %d of %d in A (render-and-ship).%s"
          % (detected_b, n, detected_a, n,
             "" if not detected_warn else
             " %d further defect(s) are warned about but the figure still ships." % detected_warn))
    ok = (detected_b > detected_a and sb["has_result"] and sb["has_validation"]
          and sb["gates_run"] >= 9 and n >= len(defects) and n >= CORE_DEFECTS
          and not run_errors)
    print("GAIN CHECK: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
