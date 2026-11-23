#!/usr/bin/env python3
"""scene.py — frozen data model for the graphical-abstract pipeline.

Single source of truth for: coordinate units, spec validation, deterministic ids.
No third-party imports. Safe on a bare CPython 3.8+.

COORDINATES (contract §2, do not change):
    * scene space is MILLIMETRES, origin at the TOP-LEFT corner, +y points DOWN.
    * font sizes are POINTS (1 pt = 25.4/72 mm).
    * a "bbox" is always {"x","y","w","h"} in mm, x/y = top-left corner.
"""
from __future__ import annotations
import sys as _sys
_sys.dont_write_bytecode = True

import hashlib
import json
import os
import re

VERSION = "1.0"

# Schema revision of the *spec* language.  The runtime VERSION above is frozen
# because it is stamped into artefacts and asserted by the determinism checks;
# only the schema grows, and it grows additively (contract §1 / §3).
SPEC_SCHEMA_VERSION = "1.1"

MM_PER_IN = 25.4
PT_MM = 25.4 / 72.0          # mm per point
MM_PT = 72.0 / 25.4          # points per mm

SEVERITY_ORDER = {"error": 0, "warn": 1}

# Minimum typography, in points (contract §2 / §6 B).
MIN_BODY_PT = 7.0
MIN_PANEL_TITLE_PT = 8.0
MIN_MAIN_TITLE_PT = 11.0

DEFAULT_CANVAS = {"w_mm": 180.0, "h_mm": 120.0, "margin_mm": 3.0, "dpi": 300}

WORKORDER_APPARATUS_ROUTE = "apparatus_and_technical_route"

ORIENTATIONS = ("portrait", "landscape")

SHAPES = {"rrect", "rect", "circle", "ellipse", "hexagon", "diamond", "capsule", "note"}

# Legacy four-element graphical-abstract reading order.  Frozen: the reference
# fixture, `layout._ordered_panels` (layout.py:842) and every spec written
# against schema 1.0 must keep behaving exactly as before.
PANEL_ROLES = ("problem", "method", "results", "conclusion")

# v1.1 recommended role domain (contract §3.2).  The apparatus/route roles lead
# the list, the legacy four stay legal, and `validate_spec` accepts anything
# from this tuple.  `PANEL_ROLES_V11` is a tuple so it can replace PANEL_ROLES
# in ordering code without changing its type.
PANEL_ROLES_V11 = ("apparatus", "flow", "route", "data", "conditions", "notes") + PANEL_ROLES

# The three roles whose total absence triggers W071 for an apparatus workorder.
CORE_APPARATUS_ROLES = ("apparatus", "flow", "route")

# Legacy six relation kinds — unchanged and still legal (contract §1.1).
EDGE_KINDS_LEGACY = ("activation", "inhibition", "flow", "spatial", "feedback", "translocation")

# v1.1 apparatus / process / route relation kinds (contract §3.5).
EDGE_KINDS_V11 = ("material", "fluid", "gas", "energy", "heat", "signal", "control",
                  "assembly", "sequence", "branch", "merge", "loop", "waste")

# EDGE_KINDS is the union: every kind `validate_spec` accepts and every kind the
# renderer may draw.  `validate.py:295` uses it to recognise rendered arrows, so
# it must always be the full legal set — never a subset.
EDGE_KINDS = EDGE_KINDS_LEGACY + EDGE_KINDS_V11

# Per-kind visual defaults (contract §3.5).  `arrow` is the endpoint mode from
# ARROW_MODES; `head` is the head glyph style (a renderer hint, not a spec
# value); `linestyle` is the default stroke pattern.  An edge may override
# linestyle/arrow explicitly; gate K904 compares the *resolved* values, so the
# renderer and the gate must read this table rather than re-invent it.
EDGE_VISUALS = {
    "activation": {"linestyle": "solid", "arrow": "end", "head": "solid"},
    "inhibition": {"linestyle": "solid", "arrow": "end", "head": "bar"},
    "flow": {"linestyle": "solid", "arrow": "end", "head": "solid"},
    "spatial": {"linestyle": "solid", "arrow": "none", "head": "none"},
    "feedback": {"linestyle": "dashed", "arrow": "end", "head": "solid"},
    "translocation": {"linestyle": "dashed", "arrow": "end", "head": "solid"},
    "material": {"linestyle": "solid", "arrow": "end", "head": "solid"},
    "fluid": {"linestyle": "solid", "arrow": "end", "head": "solid"},
    "gas": {"linestyle": "solid", "arrow": "end", "head": "hollow"},
    "energy": {"linestyle": "dashed", "arrow": "end", "head": "triangle"},
    "heat": {"linestyle": "dashed", "arrow": "end", "head": "triangle"},
    "signal": {"linestyle": "dotted", "arrow": "end", "head": "dot"},
    "control": {"linestyle": "dashdot", "arrow": "end", "head": "solid"},
    "assembly": {"linestyle": "solid", "arrow": "none", "head": "none"},
    "sequence": {"linestyle": "solid", "arrow": "end", "head": "solid"},
    "branch": {"linestyle": "solid", "arrow": "end", "head": "solid"},
    "merge": {"linestyle": "solid", "arrow": "end", "head": "solid"},
    "loop": {"linestyle": "solid", "arrow": "end", "head": "solid"},
    "waste": {"linestyle": "dashed", "arrow": "end", "head": "solid"},
}

LINESTYLES = ("solid", "dashed", "dotted", "dashdot")
ARROW_MODES = ("none", "end", "both")
DEFAULT_LINESTYLE = "solid"
DEFAULT_ARROW = "end"

# Apparatus part semantics for `panels[].nodes[].part` (contract §3.4).
PART_TYPES = ("vessel", "tank", "reactor", "column", "pump", "valve", "sensor",
              "probe", "flask", "mixer", "separator", "reservoir", "condenser",
              "heater", "cooler", "junction", "sample", "reagent", "waste",
              "instrument", "generic")

# Which side of a node box a port sits on (contract §3.4).
PORT_SIDES = ("left", "right", "top", "bottom")

CHART_TYPES = {"bar", "barh", "line", "scatter", "dot", "heatmap", "violin", "waterfall", "none"}

# Okabe-Ito: the canonical colour-vision-deficiency safe categorical palette.
#
# ORDER MATTERS.  The set is CVD-safe, but three of its members are nearly
# iso-luminant (D55E00 L*=54.2, 009E73 L*=57.7, CC79A7 L*=61.0), so a greyscale
# print cannot tell them apart (measured worst pair dL* = 3.5, below the 5.0
# floor gate C enforces).  The order below is chosen so that the first four
# colours a figure actually uses are separated in L* as well as in hue:
#   0072B2 L*=46.0 | E69F00 L*=70.6 | 009E73 L*=57.7 | 000000 L*=0.0
#   -> worst pairwise dL* = 11.7, worst CVD dE well above the 6.0 floor.
# Beyond four categories the greyscale floor cannot be met from this set alone;
# gate C will say so with measured numbers rather than passing silently.
PALETTES = {
    "okabe-ito": [
        "#0072B2", "#E69F00", "#009E73", "#000000",
        "#F0E442", "#D55E00", "#CC79A7", "#56B4E9",
    ],
    "grayscale-safe": ["#1a1a1a", "#4d4d4d", "#808080", "#b3b3b3"],
}


def categorical_colors(k):
    """The first ``k`` colours of the CVD- and greyscale-aware categorical order."""
    pal = PALETTES["okabe-ito"]
    return [pal[i % len(pal)] for i in range(max(0, int(k)))]

# Sequential cmaps (hex stops) used for colorbars / heatmaps.
CMAPS = {
    "viridis": ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"],
    "batlow": ["#011959", "#10406a", "#1c6f6a", "#8f9e43", "#f7e225"],
    "cividis": ["#00224e", "#335c67", "#7b8b6f", "#c7b86f", "#fee838"],
    "grey": ["#f7f7f7", "#000000"],
}


class SpecError(ValueError):
    """Raised when a spec cannot be used at all (CLI exit 4)."""

    def __init__(self, message, issues=None):
        super().__init__(message)
        self.issues = issues or []


# --------------------------------------------------------------------------- #
# units
# --------------------------------------------------------------------------- #
def mm_to_pt(v):
    return float(v) * MM_PT


def pt_to_mm(v):
    return float(v) * PT_MM


def mm_to_px(v, dpi):
    return float(v) * dpi / MM_PER_IN


def px_to_mm(v, dpi):
    return float(v) * MM_PER_IN / dpi


# --------------------------------------------------------------------------- #
# deterministic ids
# --------------------------------------------------------------------------- #
def stable_id(prefix, seed):
    """Deterministic short id: same (prefix, seed) -> same id, always."""
    h = hashlib.sha1(("%s|%s" % (prefix, seed)).encode("utf-8")).hexdigest()
    return "%s%s" % (prefix, h[:8])


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# spec loading / validation
# --------------------------------------------------------------------------- #
def load_spec(path):
    if not os.path.exists(path):
        raise SpecError("spec not found: %s" % path)
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            spec = json.load(fh)
    except json.JSONDecodeError as exc:
        raise SpecError("spec is not valid JSON: %s" % exc)
    issues = validate_spec(spec)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        raise SpecError("spec has %d error(s)" % len(errors), issues)
    return spec


def _issue(code, severity, path, message):
    return {"code": code, "severity": severity, "path": path, "message": message}


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _str(v):
    """A non-empty string (``""`` is treated as absent, like every other field)."""
    return isinstance(v, str) and bool(v.strip())


def _int_ge1(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def resolve_edge_style(edge):
    """Effective v1.1 visual style of an edge record.

    Explicit ``linestyle``/``arrow`` win; otherwise the per-kind default from
    ``EDGE_VISUALS`` applies (so ``assembly`` is arrow-less without the author
    having to say so).  Returns ``{"kind","linestyle","arrow","head"}`` with
    every value normalised, which is what gate K904 must compare against.
    """
    edge = edge if isinstance(edge, dict) else {}
    kind = edge.get("kind")
    vis = EDGE_VISUALS.get(kind) or {}
    linestyle = edge.get("linestyle")
    arrow = edge.get("arrow")
    if linestyle not in LINESTYLES:
        linestyle = vis.get("linestyle", DEFAULT_LINESTYLE)
    if arrow not in ARROW_MODES:
        arrow = vis.get("arrow", DEFAULT_ARROW)
    return {"kind": kind, "linestyle": linestyle, "arrow": arrow,
            "head": vis.get("head", "solid")}


def _check_port_list(ports, path, issues):
    """Validate a node's ``ports`` array (contract §3.4 / E138..E142)."""
    if ports is None:
        return
    if not isinstance(ports, list):
        issues.append(_issue("E138", "error", path, "ports must be a list of port objects"))
        return
    seen = set()
    for i, port in enumerate(ports):
        pp = "%s[%d]" % (path, i)
        if not isinstance(port, dict):
            issues.append(_issue("E138", "error", pp, "port must be an object"))
            continue
        pid = port.get("id")
        if not _str(pid):
            issues.append(_issue("E139", "error", pp + ".id", "port id required"))
        elif pid in seen:
            issues.append(_issue("E140", "error", pp + ".id", "duplicate port id %r" % pid))
        else:
            seen.add(pid)
        side = port.get("side")
        if side is not None and side not in PORT_SIDES:
            issues.append(_issue("E141", "error", pp + ".side",
                                 "side must be one of %s (got %r)" % (list(PORT_SIDES), side)))
        for k in ("name", "mate", "source"):
            if port.get(k) is not None and not _str(port.get(k)):
                issues.append(_issue("E142", "error", pp + "." + k,
                                     "%s must be a non-empty string" % k))


def _check_declared_edges(declared, path, issues, kind_code):
    """Validate a ``declared_edges`` / ``expected_relations`` list.

    Endpoint *membership* is deliberately NOT checked here: these lists declare
    connections for the rendered scene as a whole, which gate J906 reconciles
    across panels.  Only shape and kind are schema-level concerns.
    """
    if not isinstance(declared, list):
        issues.append(_issue(kind_code, "error", path, "expected_relations/declared_edges must be a list"))
        return
    for i, rel in enumerate(declared):
        rp = "%s[%d]" % (path, i)
        if not isinstance(rel, dict):
            issues.append(_issue("E103", "error", rp, "relation must be an object with from/to"))
            continue
        for k in ("from", "to"):
            if not _str(rel.get(k)):
                issues.append(_issue("E103", "error", rp + "." + k, "relation endpoint required"))
        rk = rel.get("kind")
        if rk is not None and rk not in EDGE_KINDS:
            issues.append(_issue("E104", "error", rp + ".kind",
                                 "kind must be one of %s (got %r)" % (list(EDGE_KINDS), rk)))


def validate_spec(spec):
    """Structural validation only. Geometric checks live in validate.py."""
    issues = []
    if not isinstance(spec, dict):
        return [_issue("E000", "error", "$", "spec must be a JSON object")]

    meta = spec.get("meta")
    if not isinstance(meta, dict):
        issues.append(_issue("E001", "error", "$.meta", "missing meta object"))
        meta = {}
    if not isinstance(meta.get("case_id"), str) or not meta.get("case_id"):
        issues.append(_issue("E002", "error", "$.meta.case_id", "case_id must be a non-empty string"))

    canvas = meta.get("canvas") or {}
    merged = dict(DEFAULT_CANVAS)
    merged.update({k: v for k, v in canvas.items() if _num(v)})
    if not (20 <= merged["w_mm"] <= 1000):
        issues.append(_issue("E003", "error", "$.meta.canvas.w_mm", "w_mm out of range 20..1000"))
    if not (20 <= merged["h_mm"] <= 1000):
        issues.append(_issue("E004", "error", "$.meta.canvas.h_mm", "h_mm out of range 20..1000"))
    if not (72 <= merged["dpi"] <= 1200):
        issues.append(_issue("E005", "error", "$.meta.canvas.dpi", "dpi out of range 72..1200"))
    if not (0 <= merged["margin_mm"] <= 20):
        issues.append(_issue("E006", "error", "$.meta.canvas.margin_mm", "margin_mm out of range 0..20"))
    if not (0 < merged["margin_mm"] * 2 < min(merged["w_mm"], merged["h_mm"])):
        issues.append(_issue("E007", "error", "$.meta.canvas", "margins leave no drawing area"))

    pal = spec.get("palette") or {}
    pid = pal.get("id") if isinstance(pal, dict) else None
    if pid is None:
        issues.append(_issue("W010", "warn", "$.palette.id", "no palette id; defaulting to okabe-ito"))
    elif pid not in PALETTES and not isinstance(pal.get("colors"), list):
        issues.append(_issue("E011", "error", "$.palette.id", "unknown palette %r and no colors[] given" % (pid,)))

    if not isinstance(meta.get("language"), str):
        issues.append(_issue("W012", "warn", "$.meta.language", "language not set; fonts will auto-resolve"))

    # ---- meta, schema 1.1 (contract §3.1) --------------------------------- #
    workorder = meta.get("workorder")
    if workorder is not None and not _str(workorder):
        issues.append(_issue("E100", "error", "$.meta.workorder", "workorder must be a non-empty string"))
    orientation = meta.get("orientation")
    if orientation is not None and orientation not in ORIENTATIONS:
        issues.append(_issue("E101", "error", "$.meta.orientation",
                             "orientation must be one of %s (got %r)" % (list(ORIENTATIONS), orientation)))
    if meta.get("expected_relations") is not None:
        _check_declared_edges(meta.get("expected_relations"), "$.meta.expected_relations",
                              issues, "E102")

    evidence = spec.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        issues.append(_issue("E020", "error", "$.evidence", "evidence list must be non-empty"))
        evidence = []
    seen_ev = set()
    for i, ev in enumerate(evidence):
        p = "$.evidence[%d]" % i
        if not isinstance(ev, dict):
            issues.append(_issue("E021", "error", p, "evidence item must be an object"))
            continue
        eid = ev.get("id")
        if not isinstance(eid, str) or not eid:
            issues.append(_issue("E022", "error", p + ".id", "evidence id required"))
        elif eid in seen_ev:
            issues.append(_issue("E023", "error", p + ".id", "duplicate evidence id %r" % eid))
        else:
            seen_ev.add(eid)
        if not isinstance(ev.get("claim"), str) or not ev.get("claim"):
            issues.append(_issue("E024", "error", p + ".claim", "claim required"))
        src = ev.get("source")
        if not isinstance(src, dict):
            issues.append(_issue("E025", "error", p + ".source", "source object required"))
        else:
            for k in ("file", "locator"):
                if not isinstance(src.get(k), str) or not src.get(k):
                    issues.append(_issue("E026", "error", p + ".source." + k, "source.%s required" % k))
            if not isinstance(src.get("quote"), str) or not src.get("quote").strip():
                issues.append(_issue("E027", "error", p + ".source.quote", "verbatim quote required"))
        if not isinstance(ev.get("kind"), str):
            issues.append(_issue("W028", "warn", p + ".kind", "kind missing (entity|relation|number|condition)"))

    panels = spec.get("panels")
    if not isinstance(panels, list) or not panels:
        issues.append(_issue("E030", "error", "$.panels", "at least one panel required"))
        return issues

    seen_panel = set()
    seen_ids = set()
    for pi, panel in enumerate(panels):
        pp = "$.panels[%d]" % pi
        if not isinstance(panel, dict):
            issues.append(_issue("E031", "error", pp, "panel must be an object"))
            continue
        pid_ = panel.get("id")
        if not isinstance(pid_, str) or not pid_:
            issues.append(_issue("E032", "error", pp + ".id", "panel id required"))
        elif pid_ in seen_panel:
            issues.append(_issue("E033", "error", pp + ".id", "duplicate panel id %r" % pid_))
        else:
            seen_panel.add(pid_)

        role = panel.get("role")
        if role not in PANEL_ROLES_V11:
            issues.append(_issue("E034", "error", pp + ".role",
                                 "role must be one of %s (got %r)" % (list(PANEL_ROLES_V11), role)))
        if not isinstance(panel.get("title"), str) or not panel.get("title"):
            issues.append(_issue("E035", "error", pp + ".title", "panel title required"))

        nodes = panel.get("nodes") or []
        if not isinstance(nodes, list):
            issues.append(_issue("E036", "error", pp + ".nodes", "nodes must be a list"))
            nodes = []
        local = set()
        for ni, node in enumerate(nodes):
            np_ = "%s.nodes[%d]" % (pp, ni)
            if not isinstance(node, dict):
                issues.append(_issue("E037", "error", np_, "node must be an object"))
                continue
            nid = node.get("id")
            if not isinstance(nid, str) or not nid:
                issues.append(_issue("E038", "error", np_ + ".id", "node id required"))
            elif nid in seen_ids:
                issues.append(_issue("E039", "error", np_ + ".id", "node id used twice in spec: %r" % nid))
            else:
                seen_ids.add(nid)
                local.add(nid)
            if not isinstance(node.get("label"), str) or not node.get("label"):
                issues.append(_issue("E040", "error", np_ + ".label", "node label required"))
            shape = node.get("shape", "rrect")
            if shape not in SHAPES:
                issues.append(_issue("E041", "warn", np_ + ".shape", "unknown shape %r -> rrect" % (shape,)))
            if not (node.get("source") or node.get("sources")):
                issues.append(_issue("W042", "warn", np_ + ".source", "node has no evidence source"))

            # ---- node, schema 1.1 (contract §3.4) ------------------------- #
            part = node.get("part")
            if part is not None and part not in PART_TYPES:
                issues.append(_issue("E130", "error", np_ + ".part",
                                     "part must be one of %s (got %r)" % (list(PART_TYPES), part)))
            if node.get("step_no") is not None and not _int_ge1(node.get("step_no")):
                issues.append(_issue("E131", "error", np_ + ".step_no",
                                     "step_no must be an integer >= 1"))
            if node.get("branch") is not None and not _str(node.get("branch")):
                issues.append(_issue("E132", "error", np_ + ".branch", "branch must be a non-empty string"))
            if node.get("loop_to") is not None and not _str(node.get("loop_to")):
                issues.append(_issue("E133", "error", np_ + ".loop_to",
                                     "loop_to must be a non-empty node id"))
            if node.get("terminal") is not None and not isinstance(node.get("terminal"), bool):
                issues.append(_issue("E135", "error", np_ + ".terminal", "terminal must be a boolean"))
            if node.get("stage") is not None and not _str(node.get("stage")):
                issues.append(_issue("E136", "error", np_ + ".stage", "stage must be a non-empty string"))
            if node.get("group") is not None and not _str(node.get("group")):
                issues.append(_issue("E137", "error", np_ + ".group", "group must be a non-empty string"))
            _check_port_list(node.get("ports"), np_ + ".ports", issues)

        # `loop_to` may only point at a node that exists in the same panel; the
        # membership test needs the full node list, hence the second pass.
        for ni, node in enumerate(nodes):
            if not isinstance(node, dict):
                continue
            loop_to = node.get("loop_to")
            if _str(loop_to) and loop_to not in local:
                issues.append(_issue("E134", "error", "%s.nodes[%d].loop_to" % (pp, ni),
                                     "loop_to %r is not a node in this panel" % (loop_to,)))

        # ---- panel-level v1.1 lists (contract §3.3) ----------------------- #
        if panel.get("sequence") is not None:
            seq = panel.get("sequence")
            if not isinstance(seq, list):
                issues.append(_issue("E110", "error", pp + ".sequence",
                                     "sequence must be a list of node ids"))
            else:
                seen_seq = set()
                for si, sid in enumerate(seq):
                    sp_ = "%s.sequence[%d]" % (pp, si)
                    if not _str(sid):
                        issues.append(_issue("E111", "error", sp_, "sequence entry must be a node id"))
                    elif sid not in local:
                        issues.append(_issue("E112", "error", sp_,
                                             "sequence entry %r is not a node in this panel" % (sid,)))
                    if _str(sid):
                        if sid in seen_seq:
                            issues.append(_issue("E113", "error", sp_,
                                                 "sequence repeats node %r" % (sid,)))
                        seen_seq.add(sid)
        if panel.get("phases") is not None:
            phases = panel.get("phases")
            if not isinstance(phases, list):
                issues.append(_issue("E114", "error", pp + ".phases", "phases must be a list"))
            else:
                phase_ids = []
                for fi, ph in enumerate(phases):
                    fp_ = "%s.phases[%d]" % (pp, fi)
                    if not isinstance(ph, dict):
                        issues.append(_issue("E115", "error", fp_, "phase must be an object"))
                        continue
                    phid = ph.get("id")
                    if not _str(phid):
                        issues.append(_issue("E115", "error", fp_ + ".id", "phase id required"))
                    elif phid in phase_ids:
                        issues.append(_issue("E116", "error", fp_ + ".id", "duplicate phase id %r" % phid))
                    else:
                        phase_ids.append(phid)
                    for k in ("title", "goal", "source"):
                        if ph.get(k) is not None and not isinstance(ph.get(k), str):
                            issues.append(_issue("E119", "error", fp_ + "." + k, "%s must be a string" % k))
                    for k in ("methods", "inputs", "outputs"):
                        if ph.get(k) is not None and not isinstance(ph.get(k), list):
                            issues.append(_issue("E118", "error", fp_ + "." + k, "%s must be a list" % k))
                    if ph.get("depends_on") is not None and not isinstance(ph.get("depends_on"), list):
                        issues.append(_issue("E117", "error", fp_ + ".depends_on",
                                             "depends_on must be a list of phase ids"))
                known = set(phase_ids)
                for fi, ph in enumerate(phases):
                    if not isinstance(ph, dict):
                        continue
                    for di, dep in enumerate(ph.get("depends_on") or []):
                        if not _str(dep) or dep not in known:
                            issues.append(_issue("E117", "error",
                                                 "%s.phases[%d].depends_on[%d]" % (pp, fi, di),
                                                 "depends_on %r is not a phase id in this panel" % (dep,)))
        if panel.get("declared_edges") is not None:
            _check_declared_edges(panel.get("declared_edges"), pp + ".declared_edges", issues, "E120")

        for ei, edge in enumerate(panel.get("edges") or []):
            ep = "%s.edges[%d]" % (pp, ei)
            if not isinstance(edge, dict):
                issues.append(_issue("E043", "error", ep, "edge must be an object"))
                continue
            if not isinstance(edge.get("id"), str) or not edge.get("id"):
                issues.append(_issue("E044", "error", ep + ".id", "edge id required"))
            for k in ("from", "to"):
                ref = edge.get(k)
                if not isinstance(ref, str) or not ref:
                    issues.append(_issue("E045", "error", ep + "." + k, "edge endpoint required"))
                elif ref not in local:
                    issues.append(_issue("E046", "error", ep + "." + k,
                                         "edge endpoint %r not a node in this panel" % (ref,)))
            kind = edge.get("kind")
            if kind is not None and kind not in EDGE_KINDS:
                issues.append(_issue("E047", "error", ep + ".kind",
                                     "kind must be one of %s (got %r)" % (list(EDGE_KINDS), kind)))
            if not (edge.get("source") or edge.get("sources")):
                issues.append(_issue("W048", "warn", ep + ".source", "edge has no evidence source"))

            # ---- edge, schema 1.1 (contract §3.5) ------------------------- #
            linestyle = edge.get("linestyle")
            if linestyle is not None and linestyle not in LINESTYLES:
                issues.append(_issue("E150", "error", ep + ".linestyle",
                                     "linestyle must be one of %s (got %r)" % (list(LINESTYLES), linestyle)))
            arrow = edge.get("arrow")
            if arrow is not None and arrow not in ARROW_MODES:
                issues.append(_issue("E151", "error", ep + ".arrow",
                                     "arrow must be one of %s (got %r)" % (list(ARROW_MODES), arrow)))
            if edge.get("legend_key") is not None and not _str(edge.get("legend_key")):
                issues.append(_issue("E152", "error", ep + ".legend_key",
                                     "legend_key must be a non-empty string"))
            if edge.get("ports") is not None:
                eports = edge.get("ports")
                ok = (isinstance(eports, list) and len(eports) == 2
                      and all(_str(v) for v in eports))
                if not ok and isinstance(eports, dict):
                    ok = _str(eports.get("from")) and _str(eports.get("to"))
                if not ok:
                    issues.append(_issue("E153", "error", ep + ".ports",
                                         "ports must be [from_port, to_port] (two non-empty strings)"))

        for ci, chart in enumerate(panel.get("charts") or []):
            cp = "%s.charts[%d]" % (pp, ci)
            if not isinstance(chart, dict):
                issues.append(_issue("E049", "error", cp, "chart must be an object"))
                continue
            ctype = chart.get("type")
            if ctype not in CHART_TYPES:
                issues.append(_issue("E050", "error", cp + ".type",
                                     "chart type must be one of %s" % sorted(CHART_TYPES)))
            series = chart.get("series")
            if not isinstance(series, list) or not series:
                issues.append(_issue("E051", "error", cp + ".series", "chart series required"))
            else:
                for si, s in enumerate(series):
                    if not isinstance(s, dict):
                        issues.append(_issue("E052", "error", "%s.series[%d]" % (cp, si), "series item must be object"))
                        continue
                    if not isinstance(s.get("name"), str):
                        issues.append(_issue("E053", "error", "%s.series[%d].name" % (cp, si), "series name required"))
                    vals = s.get("values")
                    if not isinstance(vals, list) or not vals:
                        issues.append(_issue("E054", "error", "%s.series[%d].values" % (cp, si), "values required"))
                    elif not all(_num(v) for v in vals):
                        issues.append(_issue("E055", "error", "%s.series[%d].values" % (cp, si),
                                             "all values must be numbers"))
                    if not (s.get("source") or s.get("sources")):
                        issues.append(_issue("W056", "warn", "%s.series[%d].source" % (cp, si),
                                             "series has no evidence source"))
            if not chart.get("unit"):
                issues.append(_issue("W057", "warn", cp + ".unit", "chart has no unit"))

        legend = panel.get("legend")
        if legend is not None:
            if not isinstance(legend, dict):
                issues.append(_issue("E058", "error", pp + ".legend", "legend must be an object"))
            elif not isinstance(legend.get("items"), list):
                issues.append(_issue("E059", "error", pp + ".legend.items", "legend items list required"))
            else:
                # ---- legend item, schema 1.1 (contract §3.6) -------------- #
                # `kind`/`part` turn a swatch into a claim about the drawing;
                # gate K904 then compares the declared multiset with the
                # rendered one.  Only the *values* are a schema concern here.
                for li, item in enumerate(legend.get("items") or []):
                    if not isinstance(item, dict):
                        continue
                    lp = "%s.legend.items[%d]" % (pp, li)
                    ik = item.get("kind")
                    if ik is not None and ik not in EDGE_KINDS:
                        issues.append(_issue("E160", "error", lp + ".kind",
                                             "legend item kind must be one of %s (got %r)"
                                             % (list(EDGE_KINDS), ik)))
                    ip = item.get("part")
                    if ip is not None and ip not in PART_TYPES:
                        issues.append(_issue("E161", "error", lp + ".part",
                                             "legend item part must be one of %s (got %r)"
                                             % (list(PART_TYPES), ip)))

        for bi, cb in enumerate(panel.get("colorbars") or []):
            bp = "%s.colorbars[%d]" % (pp, bi)
            if not isinstance(cb, dict):
                issues.append(_issue("E060", "error", bp, "colorbar must be an object"))
                continue
            for k in ("vmin", "vmax"):
                if not _num(cb.get(k)):
                    issues.append(_issue("E061", "error", bp + "." + k, "%s must be numeric" % k))
            if _num(cb.get("vmin")) and _num(cb.get("vmax")) and cb["vmax"] <= cb["vmin"]:
                issues.append(_issue("E062", "error", bp, "vmax must be > vmin"))
            if cb.get("cmap") not in CMAPS:
                issues.append(_issue("E063", "error", bp + ".cmap", "cmap must be one of %s" % sorted(CMAPS)))
            if not cb.get("unit"):
                issues.append(_issue("W064", "warn", bp + ".unit", "colorbar has no unit"))

    # Role coverage.  For an apparatus/technical-route workorder the four-element
    # graphical-abstract reading order is the wrong yardstick, so it is replaced
    # by W071 (contract §3.2); every other spec keeps the legacy W070 exactly as
    # before, which is what makes schema 1.1 additive.
    roles = [p.get("role") for p in panels if isinstance(p, dict)]
    workorder = meta.get("workorder")
    if workorder == WORKORDER_APPARATUS_ROUTE:
        if not any(r in roles for r in CORE_APPARATUS_ROLES):
            issues.append(_issue("W071", "warn", "$.panels",
                                 "workorder %r but no panel has an apparatus/flow/route role"
                                 % (workorder,)))
    else:
        for required in PANEL_ROLES:
            if required not in roles:
                issues.append(_issue("W070", "warn", "$.panels",
                                     "no panel with role %r (four-element coverage)" % required))
    return issues


def resolve_canvas(meta):
    canvas = dict(DEFAULT_CANVAS)
    canvas.update({k: float(v) for k, v in ((meta or {}).get("canvas") or {}).items() if _num(v)})
    return canvas


def resolve_palette(spec):
    pal = spec.get("palette") or {}
    colors = pal.get("colors")
    if isinstance(colors, list) and colors:
        return [c for c in colors if isinstance(c, str)]
    pid = pal.get("id") or "okabe-ito"
    return list(PALETTES.get(pid, PALETTES["okabe-ito"]))


def evidence_ids(spec):
    return {e.get("id") for e in (spec.get("evidence") or []) if isinstance(e, dict)}


_WS = re.compile(r"\s+")


def norm_ws(text):
    return _WS.sub(" ", (text or "")).strip()


# --------------------------------------------------------------------------- #
# spec -> scene topology passthrough (contract §3, gates J/K rely on this)
# --------------------------------------------------------------------------- #
# `layout.py` draws what it needs and returns a scene of geometry.  The authored
# semantics (which part a node is, its step number, a port, an edge's line style)
# would otherwise be lost in the persisted `scene.json`, and gates J/K read that
# file.  `attach_topology` copies the semantic keys across without touching the
# spec and without clobbering any geometric key the renderer added.

NODE_PASSTHROUGH_KEYS = ("part", "step_no", "branch", "loop_to", "terminal",
                         "stage", "group", "ports")
EDGE_PASSTHROUGH_KEYS = ("kind", "linestyle", "arrow", "legend_key", "ports")
PANEL_PASSTHROUGH_KEYS = ("sequence", "phases", "declared_edges")
META_PASSTHROUGH_KEYS = ("workorder", "orientation", "expected_relations")


def _topo_node(node):
    """One deterministic node record carrying every v1.1 semantic key."""
    rec = {"id": node.get("id"), "label": node.get("label"),
           "shape": node.get("shape") or "rrect"}
    for key in NODE_PASSTHROUGH_KEYS:
        rec[key] = node.get(key)
    rec["ports"] = node.get("ports") if isinstance(node.get("ports"), list) else []
    # `terminal` is a boolean flag: absent means "not a terminal node".
    rec["terminal"] = bool(node.get("terminal")) if node.get("terminal") is not None else None
    for key in ("sublabel", "value", "unit", "derived", "source", "sources"):
        if node.get(key) is not None:
            rec[key] = node.get(key)
    return rec


def _topo_edge(edge):
    """One deterministic edge record with the *resolved* v1.1 visual style."""
    visual = resolve_edge_style(edge)
    rec = {"id": edge.get("id"), "from": edge.get("from"), "to": edge.get("to"),
           "kind": edge.get("kind")}
    for key in EDGE_PASSTHROUGH_KEYS:
        rec[key] = edge.get(key)
    rec["linestyle"] = visual["linestyle"]
    rec["arrow"] = visual["arrow"]
    rec["head"] = visual["head"]
    rec["ports"] = edge.get("ports") if edge.get("ports") is not None else []
    for key in ("label", "source", "sources"):
        if edge.get(key) is not None:
            rec[key] = edge.get(key)
    return rec


def topology_from_spec(spec):
    """Spec -> list of panel topology records (no geometry, no mutation)."""
    out = []
    for panel in (spec or {}).get("panels") or []:
        if not isinstance(panel, dict):
            continue
        rec = {
            "id": panel.get("id"),
            "role": panel.get("role"),
            "nodes": [_topo_node(n) for n in (panel.get("nodes") or []) if isinstance(n, dict)],
            "edges": [_topo_edge(e) for e in (panel.get("edges") or []) if isinstance(e, dict)],
        }
        for key in PANEL_PASSTHROUGH_KEYS:
            if panel.get(key) is not None:
                rec[key] = panel.get(key)
        out.append(rec)
    return out


def attach_topology(scene, spec):
    """Merge the authored spec topology into a built scene, in place.

    Idempotent and additive: a renderer-provided `nodes`/`edges` record keeps
    whatever it already set (geometry, bbox, ...) and only gains the missing
    semantic keys.  The spec object is never mutated.  Returns ``scene``.
    """
    if not isinstance(scene, dict) or not isinstance(spec, dict):
        return scene
    topo = {p.get("id"): p for p in topology_from_spec(spec) if p.get("id")}
    for panel in scene.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        t = topo.get(panel.get("id"))
        if t is None:
            continue

        existing = {n.get("id"): n for n in (panel.get("nodes") or [])
                    if isinstance(n, dict) and n.get("id")}
        wanted_ids = {w.get("id") for w in t["nodes"]}
        merged = []
        for want in t["nodes"]:
            rec = dict(existing.get(want.get("id")) or {})
            for key, value in want.items():
                rec.setdefault(key, value)
            merged.append(rec)
        # a renderer may have emitted a node the spec does not name: keep it
        for nid, node in existing.items():
            if nid not in wanted_ids:
                merged.append(node)
        panel["nodes"] = merged

        existing_e = {e.get("id"): e for e in (panel.get("edges") or [])
                      if isinstance(e, dict) and e.get("id")}
        wanted_e = {w.get("id") for w in t["edges"]}
        merged_e = []
        for want in t["edges"]:
            rec = dict(existing_e.get(want.get("id")) or {})
            for key, value in want.items():
                rec.setdefault(key, value)
            merged_e.append(rec)
        for eid, edge in existing_e.items():
            if eid not in wanted_e:
                merged_e.append(edge)
        panel["edges"] = merged_e

        for key in PANEL_PASSTHROUGH_KEYS:
            if key in t and panel.get(key) is None:
                panel[key] = t[key]

    meta = scene.get("meta")
    if isinstance(meta, dict):
        source_meta = spec.get("meta") or {}
        for key in META_PASSTHROUGH_KEYS:
            if source_meta.get(key) is not None and meta.get(key) is None:
                meta[key] = source_meta[key]
    return scene
