#!/usr/bin/env python3
"""validate.py — verification gates A–K (contract §6, frozen).

Owner: validate-export.  ``run_checks`` returns

    {"checks": [{"id","name","status","detail"}], "failed": [ids], "warned": [ids]}

Every check is *measured*, and every detail string carries at least one number.
Status semantics:
    pass  — the measured quantity met the declared threshold
    warn  — the property could not be established from the available inputs
            (UNVERIFIABLE) or is a documented soft-limit breach; NOT a pass
    fail  — the measured quantity breached a hard threshold

No check may return "pass" for an unmeasured property.  Nothing here weakens a
threshold to accommodate a specific artefact.
"""
from __future__ import annotations
import sys as _sys
_sys.dont_write_bytecode = True

import importlib
import itertools
import json
import math
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import scene  # noqa: E402

# --------------------------------------------------------------------------- #
# thresholds (documented, calibrated in scratch/calib_c.py)
# --------------------------------------------------------------------------- #
CVD_MIN_DE = 6.0          # CIELAB ΔE76 floor for colour-coded alternatives
GRAY_MIN_DL = 5.0         # L* separation floor under grayscale conversion
WCAG_NORMAL = 4.5         # WCAG 2.1 AA body text
WCAG_LARGE = 3.0          # WCAG 2.1 AA large text (>=18pt, or >=14pt bold)
LARGE_PT = 18.0
LARGE_BOLD_PT = 14.0
BBOX_TOL_MM = 1e-6
COLORBAR_SLACK_FRAC = 0.15   # allowed axis rounding beyond the data range

# --------------------------------------------------------------------------- #
# contract §3.4/§3.5 extended vocabulary.
#
# scene.py owns these tables, but gates J/K must keep working while a sibling is
# still landing the schema, and must not turn an old spec red.  So the domain is
# read from scene.py when present and unioned with this frozen fallback; every
# new field is read with ``.get()`` and every absent field is "not applicable",
# never a failure.
# --------------------------------------------------------------------------- #
LEGACY_EDGE_KINDS = ("activation", "inhibition", "flow", "spatial", "feedback", "translocation")
NEW_EDGE_KINDS = ("material", "fluid", "gas", "energy", "heat", "signal", "control",
                  "assembly", "sequence", "branch", "merge", "loop", "waste")
PART_ENUM = ("vessel", "tank", "reactor", "column", "pump", "valve", "sensor", "probe",
             "flask", "mixer", "separator", "reservoir", "condenser", "heater", "cooler",
             "junction", "sample", "reagent", "waste", "instrument", "generic")
APPARATUS_ROLES = ("apparatus", "flow", "route")
# contract §3.5: the visual encoding each edge kind must carry.  scene.py's
# EDGE_VISUALS is the authority (its own comment says the gate must read that
# table rather than re-invent it); this fallback only covers a scene.py that has
# not landed yet, so the gate can never disagree with the schema silently.
LINESTYLE_BY_KIND_FALLBACK = {
    "material": "solid", "fluid": "solid", "gas": "solid", "assembly": "solid",
    "sequence": "solid", "branch": "solid", "merge": "solid", "loop": "solid",
    "energy": "dashed", "heat": "dashed", "waste": "dashed",
    "signal": "dotted", "control": "dashdot",
    "activation": "solid", "inhibition": "solid", "flow": "solid", "spatial": "solid",
    "feedback": "dashed", "translocation": "dashed",
}
SELF_LOOP_KINDS = ("loop", "feedback")


def _all_edge_kinds():
    out = []
    for k in tuple(getattr(scene, "EDGE_KINDS", ()) or ()) + LEGACY_EDGE_KINDS + NEW_EDGE_KINDS:
        if k not in out:
            out.append(k)
    return tuple(out)


def _all_parts():
    out = []
    for k in (tuple(getattr(scene, "PART_TYPES", ()) or ())
              + tuple(getattr(scene, "PARTS", ()) or ()) + PART_ENUM):
        if k not in out:
            out.append(k)
    return tuple(out)


def _linestyle_table():
    table = dict(LINESTYLE_BY_KIND_FALLBACK)
    visuals = getattr(scene, "EDGE_VISUALS", None)
    if isinstance(visuals, dict):
        for kind, vis in visuals.items():
            if isinstance(vis, dict) and isinstance(vis.get("linestyle"), str):
                table[kind] = vis["linestyle"]
    return table


ALL_EDGE_KINDS = _all_edge_kinds()
ALL_PARTS = _all_parts()
LINESTYLE_BY_KIND = _linestyle_table()

# --- colour-vision-deficiency simulation (Viénot/Brettel-style, linear sRGB) --
CVD_MATRICES = {
    "protan": ((0.11238, 0.88762, 0.0), (0.11238, 0.88762, 0.0), (0.00401, 0.0, 0.99599)),
    "deutan": ((0.29275, 0.70725, 0.0), (0.29275, 0.70725, 0.0), (-0.02234, 0.0, 1.02234)),
    "tritan": ((1.0, 0.0, 0.0), (0.0, 0.12740, 0.87260), (0.0, 0.12740, 0.87260)),
}

# Helvetica advance widths /1000 (fallback only: preferred path is measure.py)
_AFM = {}
for _c, _w in zip(" !\"#$%&'()*+,-./", [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278]):
    _AFM[_c] = _w
for _i, _c in enumerate("0123456789"):
    _AFM[_c] = 556
for _c, _w in zip(":;<=>?@", [278, 278, 584, 584, 584, 556, 1015]):
    _AFM[_c] = _w
for _c, _w in zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611]):
    _AFM[_c] = _w
for _c, _w in zip("[\\]^_`", [278, 278, 278, 469, 556, 333]):
    _AFM[_c] = _w
for _c, _w in zip("abcdefghijklmnopqrstuvwxyz", [556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500]):
    _AFM[_c] = _w
for _c, _w in zip("{|}~", [334, 260, 334, 584]):
    _AFM[_c] = _w

_NAMED = {"black": (0, 0, 0), "white": (1, 1, 1), "red": (1, 0, 0), "green": (0, 128 / 255, 0),
          "blue": (0, 0, 1), "gray": (128 / 255, 128 / 255, 128 / 255), "grey": (128 / 255,) * 3,
          "none": None, "transparent": None}

_FS_CACHE = {}


# --------------------------------------------------------------------------- #
# colour math
# --------------------------------------------------------------------------- #
def hex_to_rgb(value):
    """'#rgb' | '#rrggbb' | 'rgb(r,g,b)' | a few CSS names -> (r,g,b) in 0..1."""
    if not isinstance(value, str):
        return None
    s = value.strip().lower()
    if s in _NAMED:
        return _NAMED[s]
    m = re.match(r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)", s)
    if m:
        return tuple(max(0.0, min(1.0, float(m.group(i)) / 255.0)) for i in (1, 2, 3))
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) >= 6 and re.fullmatch(r"[0-9a-f]{6}", h[:6]):
            return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return None


def _linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _unlinear(c):
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def relative_luminance(rgb):
    r, g, b = (_linear(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(rgb1, rgb2):
    l1, l2 = relative_luminance(rgb1), relative_luminance(rgb2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def simulate(rgb, kind):
    """Apply a protan/deutan/tritan matrix in linear sRGB, return sRGB tuple."""
    m = CVD_MATRICES[kind]
    v = [_linear(x) for x in rgb]
    return tuple(_unlinear(sum(m[i][j] * v[j] for j in range(3))) for i in range(3))


def to_lab(rgb):
    r, g, b = (_linear(x) for x in rgb)
    x = 0.4124564 * r + 0.3575761 * g + 0.1804375 * b
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = 0.0193339 * r + 0.1191920 * g + 0.9503041 * b
    xn, yn, zn = 0.95047, 1.0, 1.08883

    def f(t):
        return t ** (1 / 3) if t > 216 / 24389 else (841 / 108) * t + 4 / 29
    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(lab1, lab2):
    """CIE76 colour difference (Euclidean in CIELAB)."""
    return math.sqrt(sum((lab1[i] - lab2[i]) ** 2 for i in range(3)))


# --------------------------------------------------------------------------- #
# soft imports / measurement helpers
# --------------------------------------------------------------------------- #
def _soft_import(name):
    try:
        return importlib.import_module(name)
    except Exception:
        return None


def resolve_fs(spec):
    lang = ((spec or {}).get("meta") or {}).get("language", "auto")
    if lang in _FS_CACHE:
        return _FS_CACHE[lang]
    fs = None
    mod = _soft_import("fonts")
    if mod is not None:
        try:
            fs = mod.resolve_fonts(lang)
        except Exception:
            fs = None
    _FS_CACHE[lang] = fs
    return fs


def measure_width_mm(text, size_pt, fs, bold=False):
    """Text width in mm.  Preferred: measure.text_width_mm (render-core).

    Returns (width_mm, source) where source is 'measure' or 'afm-fallback'.
    """
    mod = _soft_import("measure")
    if mod is not None and hasattr(mod, "text_width_mm"):
        try:
            return float(mod.text_width_mm(text, size_pt, fs, bold)), "measure"
        except Exception:
            pass
    total = 0.0
    for ch in str(text):
        w = _AFM.get(ch)
        if w is None:
            w = 1000 if ord(ch) > 0x2E7F else 500   # CJK full width / default
        total += w
    if bold:
        total *= 1.05
    return total / 1000.0 * size_pt * scene.PT_MM, "afm-fallback"


def glyph_coverage(text, fs):
    """(missing_glyphs_list, source) — [] means covered."""
    mod = _soft_import("fonts")
    if mod is None or fs is None:
        return None, "unavailable"
    try:
        if hasattr(mod, "glyph_coverage_ok"):
            ok = mod.glyph_coverage_ok(text, fs)
            return ([] if ok else ["?"]), "fonts.glyph_coverage_ok"
    except Exception:
        pass
    try:
        if hasattr(mod, "missing_glyphs"):
            paths = getattr(fs, "paths", {}) or {}
            fp = paths.get("regular") or paths.get("cjk")
            miss = mod.missing_glyphs(text, fp)
            return list(miss), "fonts.missing_glyphs"
    except Exception:
        pass
    return None, "unavailable"


# --------------------------------------------------------------------------- #
# scene accessors (defensive: SCENE.md may not exist yet)
# --------------------------------------------------------------------------- #
_SIZE_KEYS = ("size_pt", "font_pt", "font_size_pt", "fontsize_pt", "pt", "size")
_CONTAINER_KEYS = ("container_w_mm", "max_w_mm", "max_width_mm", "wrap_w_mm", "box_w_mm")
_KIND_KEYS = ("kind", "edge_kind", "arrow_kind", "semantic", "relation")
_FILL_KEYS = ("fill", "color", "colour")
_TEXT_KEYS = ("text", "label", "value_text", "string")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def bbox_of(prim):
    b = prim.get("bbox")
    if isinstance(b, dict) and all(_num(b.get(k)) for k in ("x", "y", "w", "h")):
        return b
    c = prim.get("container")
    if isinstance(c, dict) and all(_num(c.get(k)) for k in ("x", "y", "w", "h")):
        return c
    return None


def size_pt_of(prim):
    for k in _SIZE_KEYS:
        v = prim.get(k)
        if _num(v) and 0 < v < 400:
            return float(v)
    st = prim.get("style") if isinstance(prim.get("style"), dict) else {}
    for k in _SIZE_KEYS:
        v = st.get(k)
        if _num(v) and 0 < v < 400:
            return float(v)
    return None


def text_of(prim):
    for k in _TEXT_KEYS:
        v = prim.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def prim_color(prim):
    st = prim.get("style") if isinstance(prim.get("style"), dict) else {}
    for k in _FILL_KEYS:
        for src in (prim, st):
            v = src.get(k)
            rgb = hex_to_rgb(v)
            if rgb is not None:
                return rgb, str(v)
    return None, None


def prim_kind(prim):
    st = prim.get("style") if isinstance(prim.get("style"), dict) else {}
    for k in _KIND_KEYS:
        for src in (prim, st):
            v = src.get(k)
            if isinstance(v, str) and v:
                return v
    return None


def is_arrow_prim(prim):
    """Arrow/relation primitive, in either shape the renderer may publish.

    * type in {arrow, edge, connector}  (contract §4 primitive types), or
    * type == "path" carrying an edge kind (kind / style.kind in scene.EDGE_KINDS).
    """
    if not isinstance(prim, dict):
        return False
    t = prim.get("type")
    if t in ("arrow", "edge", "connector"):
        return True
    if t == "path":
        return prim_kind(prim) in ALL_EDGE_KINDS
    return False


def is_page_frame(prim, canvas):
    """A page-sized background frame: layer=='frame' and bbox covers >=99% of the page.

    Such a primitive is a full-bleed background, so it can never satisfy a page
    margin.  Everything else (including any frame that does NOT cover the page)
    stays subject to the margin rule.
    """
    if str((prim or {}).get("layer") or "").lower() != "frame":
        return False
    b = bbox_of(prim)
    if b is None:
        return False
    W, H = float(canvas["w_mm"]), float(canvas["h_mm"])
    page_area = W * H
    if page_area <= 0:
        return False
    inside = (b["x"] >= -1.0 and b["y"] >= -1.0
              and b["x"] + b["w"] <= W + 1.0 and b["y"] + b["h"] <= H + 1.0)
    return inside and (b["w"] * b["h"]) >= 0.99 * page_area


def canvas_of(scene_obj, spec):
    canvas = dict(scene.DEFAULT_CANVAS)
    for src in (((spec or {}).get("meta") or {}).get("canvas") or {}, (scene_obj or {}).get("canvas") or {}):
        for k, v in src.items():
            if _num(v):
                canvas[k] = float(v)
    return canvas


def _text_prims(scene_obj):
    return [p for p in ((scene_obj or {}).get("primitives") or [])
            if isinstance(p, dict) and p.get("type") == "text"]


def norm_ws(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


# --------------------------------------------------------------------------- #
# spec walkers
# --------------------------------------------------------------------------- #
def iter_legends(panel):
    for key in ("legend", "legends"):
        v = panel.get(key)
        if isinstance(v, dict):
            yield v
        elif isinstance(v, list):
            for it in v:
                if isinstance(it, dict):
                    yield it


def iter_source_refs(spec):
    """Yield (json_path, evidence_id) for every element that claims provenance.

    CONTRACT §8.1: ``series.sources`` (list) is equivalent to ``series.source``.
    One tuple is emitted per referenced id, so the counter equals the number of
    references the evidence module actually checks.

    Coverage (CONTRACT §4 E, extended): node / edge / **step** / **phase** /
    **port** / series / legend.  The last three classes are new fields, so they
    are walked with ``.get()`` and cost nothing on an old spec.
    """
    out = []
    for pi, panel in enumerate((spec or {}).get("panels") or []):
        if not isinstance(panel, dict):
            continue
        pp = "$.panels[%d]" % pi
        for ni, node in enumerate(panel.get("nodes") or []):
            if isinstance(node, dict) and node.get("source"):
                out.append(("%s.nodes[%d](%s)" % (pp, ni, node.get("id")), node.get("source")))
            if isinstance(node, dict):
                for qi, port in enumerate(node.get("ports") or []):
                    if isinstance(port, dict) and port.get("source"):
                        out.append(("%s.nodes[%d](%s).ports[%d](%s)"
                                    % (pp, ni, node.get("id"), qi, port.get("id")),
                                    port.get("source")))
        for ei, edge in enumerate(panel.get("edges") or []):
            if isinstance(edge, dict) and edge.get("source"):
                out.append(("%s.edges[%d](%s)" % (pp, ei, edge.get("id")), edge.get("source")))
        for ti, step in enumerate(panel.get("steps") or []):
            if isinstance(step, dict):
                refs = step.get("sources") if isinstance(step.get("sources"), (list, tuple)) else None
                refs = refs or ([step["source"]] if step.get("source") else [])
                for r in refs:
                    if isinstance(r, str) and r:
                        out.append(("%s.steps[%d](%s)" % (pp, ti, step.get("id")), r))
        for hi, phase in enumerate(panel.get("phases") or []):
            if isinstance(phase, dict):
                refs = phase.get("sources") if isinstance(phase.get("sources"), (list, tuple)) else None
                refs = refs or ([phase["source"]] if phase.get("source") else [])
                for r in refs:
                    if isinstance(r, str) and r:
                        out.append(("%s.phases[%d](%s)" % (pp, hi, phase.get("id")), r))
        for ci, chart in enumerate(panel.get("charts") or []):
            for si, s in enumerate((chart or {}).get("series") or []):
                if not isinstance(s, dict):
                    continue
                refs = s.get("sources")
                if not isinstance(refs, (list, tuple)):
                    refs = [s.get("source")] if s.get("source") else []
                for r in refs:
                    if isinstance(r, str) and r:
                        out.append(("%s.charts[%d].series[%d]" % (pp, ci, si), r))
        for bi, cb in enumerate(panel.get("colorbars") or []):
            if isinstance(cb, dict) and cb.get("source"):
                out.append(("%s.colorbars[%d]" % (pp, bi), cb.get("source")))
        for li, leg in enumerate(iter_legends(panel)):
            for ii, it in enumerate(leg.get("items") or []):
                if isinstance(it, dict) and it.get("source"):
                    out.append(("%s.legend[%d].items[%d]" % (pp, li, ii), it.get("source")))
    # spec-level steps/phases are accepted too (some authors hoist them out of
    # the panel); they are the same elements, so they get the same source rule.
    for key in ("steps", "phases"):
        for si, item in enumerate((spec or {}).get(key) or []):
            if not isinstance(item, dict):
                continue
            for r in _refs_of(item):
                out.append(("$.%s[%d](%s)" % (key, si, item.get("id")), r))
    return out


def _refs_of(element):
    """Normalised evidence references of one element (single id or list)."""
    if not isinstance(element, dict):
        return []
    refs = element.get("sources")
    if not isinstance(refs, (list, tuple)):
        refs = [element.get("source")] if element.get("source") else []
    return [r for r in refs if isinstance(r, str) and r]


def iter_edges(spec):
    out = []
    for pi, panel in enumerate((spec or {}).get("panels") or []):
        if not isinstance(panel, dict):
            continue
        for ei, edge in enumerate(panel.get("edges") or []):
            if isinstance(edge, dict):
                out.append(("%s[%d]" % (panel.get("id"), ei), edge))
    return out


def iter_charts(spec):
    out = []
    for pi, panel in enumerate((spec or {}).get("panels") or []):
        if not isinstance(panel, dict):
            continue
        for ci, chart in enumerate(panel.get("charts") or []):
            if isinstance(chart, dict):
                out.append((panel, chart))
    return out


# --------------------------------------------------------------------------- #
# topology helpers (gates J/K) — deliberately tolerant readers
# --------------------------------------------------------------------------- #
def spec_panels(spec):
    return [p for p in ((spec or {}).get("panels") or []) if isinstance(p, dict)]


def spec_nodes(spec):
    """[(panel, node)] for every node of every panel."""
    out = []
    for panel in spec_panels(spec):
        for node in panel.get("nodes") or []:
            if isinstance(node, dict):
                out.append((panel, node))
    return out


def node_by_id(spec):
    return {n.get("id"): n for _, n in spec_nodes(spec) if n.get("id")}


def _norm_label(text):
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def label_index(spec):
    """normalised label / raw label -> [node ids]; a label may repeat."""
    out = {}
    for _, node in spec_nodes(spec):
        nid = node.get("id")
        if not nid:
            continue
        for key in {_norm_label(node.get("label")), str(node.get("label") or "").strip().lower()}:
            if key:
                out.setdefault(key, []).append(nid)
    return out


def resolve_endpoint(name, ids, labels):
    """Resolve a declaration endpoint to a node id (accepts ids *or* labels)."""
    if not isinstance(name, str) or not name:
        return None
    if name in ids:
        return name
    for key in (name.strip().lower(), _norm_label(name)):
        if key and key in labels:
            return labels[key][0]
    return None


def _linestyle_from_dash(dash):
    """Map an SVG dash array onto the contract §3.5 linestyle vocabulary."""
    if not isinstance(dash, (list, tuple)) or not dash:
        return "solid"
    try:
        d = [float(x) for x in dash]
    except (TypeError, ValueError):
        s = " ".join(str(x) for x in dash).lower()
        if "dot" in s and "dash" in s:
            return "dashdot"
        if "dot" in s:
            return "dotted"
        if "dash" in s:
            return "dashed"
        return "solid"
    if len(d) >= 4:
        return "dashdot"
    if len(d) == 2:
        a, b = d
        if a <= 1.1 and (abs(a - b) <= 0.15 or (b > 0 and a / b <= 0.8)):
            return "dotted"
        return "dashed"
    return "dashed"


def _linestyle_of(prim):
    st = prim.get("style") if isinstance(prim.get("style"), dict) else {}
    for src in (prim, st):
        for k in ("linestyle", "line_style", "dash_style"):
            v = src.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
    for src in (prim, st):
        d = src.get("dash")
        if isinstance(d, str) and d.strip():
            s = d.strip().lower()
            if s in ("solid", "dashed", "dotted", "dashdot", "none"):
                return "solid" if s == "none" else s
            return _linestyle_from_dash(re.split(r"[ ,]+", s))
        if isinstance(d, (list, tuple)) and d:
            return _linestyle_from_dash(d)
    return "solid"


def _canon_colour(value):
    rgb = hex_to_rgb(value)
    if rgb is not None:
        return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in rgb)
    if isinstance(value, str) and value.strip():
        s = value.strip().lower()
        if s not in ("none", "transparent"):
            return s
    return None


def prim_colour(prim):
    """The colour a stroke-based primitive is painted with (stroke wins)."""
    st = prim.get("style") if isinstance(prim.get("style"), dict) else {}
    for k in ("stroke", "color", "colour", "fill"):
        for src in (st, prim):
            c = _canon_colour(src.get(k))
            if c:
                return c
    return None


def scene_edge_records(scene_obj):
    """Every rendered edge/arrow primitive, with the §3.5 visual encoding read off it."""
    out = []
    for p in (scene_obj or {}).get("primitives") or []:
        if not isinstance(p, dict) or not is_arrow_prim(p):
            continue
        out.append({"prim": p,
                    "from": p.get("from"), "to": p.get("to"),
                    "kind": prim_kind(p) or "unspecified",
                    "linestyle": _linestyle_of(p),
                    "color": prim_colour(p),
                    "panel": p.get("panel"),
                    "edge_id": p.get("edge_id")})
    return out


def scene_arrows_vs_spec(spec, scene_obj):
    """(spec kind multiset, scene kind multiset) used by gate D."""
    spec_kinds, scene_kinds = {}, {}
    for _, edge in iter_edges(spec):
        k = edge.get("kind") or "unspecified"
        spec_kinds[k] = spec_kinds.get(k, 0) + 1
    for rec in scene_edge_records(scene_obj):
        k = rec["kind"]
        scene_kinds[k] = scene_kinds.get(k, 0) + 1
    return spec_kinds, scene_kinds


# --------------------------------------------------------------------------- #
# gate A — canvas / margins
# --------------------------------------------------------------------------- #
def gate_a(spec, scene_obj, export_report, out_dir, materials):
    canvas = canvas_of(scene_obj, spec)
    W, H, margin = canvas["w_mm"], canvas["h_mm"], canvas.get("margin_mm", 3.0)
    prims = (scene_obj or {}).get("primitives") or []
    if not prims:
        return "fail", ("page %.1fx%.1f mm margin %.2f mm: 0 primitives in scene.json, "
                        "0 measured, containment UNVERIFIABLE (build did not publish a scene)"
                        % (W, H, margin))
    worst, viol, nobbox, exempt = None, 0, 0, 0
    for p in prims:
        if not isinstance(p, dict):
            continue
        b = bbox_of(p)
        if b is None:
            nobbox += 1
            continue
        if is_page_frame(p, canvas):
            exempt += 1
            continue
        over = max(margin - b["x"], margin - b["y"],
                   (b["x"] + b["w"]) - (W - margin), (b["y"] + b["h"]) - (H - margin))
        if over > BBOX_TOL_MM:
            viol += 1
            if worst is None or over > worst[1]:
                worst = (str(p.get("id", "?")), over)
    frame_note = "%d page-sized frame exempt" % exempt
    if viol:
        return "fail", ("page %.2fx%.2f mm margin %.2f mm, primitives=%d (no bbox: %d, %s): "
                        "%d outside, worst=%s +%.3f mm overshoot"
                        % (W, H, margin, len(prims), nobbox, frame_note, viol, worst[0], worst[1]))
    if nobbox == len(prims):
        return "warn", ("page %.2fx%.2f mm margin %.2f mm: %d primitives, none carries a bbox "
                        "(%s) -> containment UNVERIFIABLE" % (W, H, margin, len(prims), frame_note))
    return "pass", ("page %.2fx%.2f mm margin %.2f mm, primitives=%d (no bbox: %d, %s): "
                    "violations=0, worst margin=%+.3f mm"
                    % (W, H, margin, len(prims), nobbox, frame_note, -margin))


# --------------------------------------------------------------------------- #
# gate B — typography
# --------------------------------------------------------------------------- #
def gate_b(spec, scene_obj, export_report, out_dir, materials):
    fs = resolve_fs(spec)
    texts = _text_prims(scene_obj)
    if not texts:
        return "fail", "0 text primitives in scene.json -> font size/width UNVERIFIABLE (measured 0)"

    panel_titles = [norm_ws(p.get("title")) for p in (spec.get("panels") or []) if isinstance(p, dict)]
    meta = (spec or {}).get("meta") or {}
    main_titles = [norm_ws(t) for t in [meta.get("title"), ((spec or {}).get("texts") or {}).get("title")] if t]

    def classify(prim, t):
        role = str(prim.get("role") or prim.get("layer") or "").lower()
        if ("main" in role and "title" in role) or role in ("title", "figure_title", "main_title"):
            return "main_title"
        if ("panel" in role and "title" in role) or role == "panel_title":
            return "panel_title"
        if t in main_titles:
            return "main_title"
        if t in panel_titles:
            return "panel_title"
        return "body"

    limits = {"body": scene.MIN_BODY_PT, "panel_title": scene.MIN_PANEL_TITLE_PT,
              "main_title": scene.MIN_MAIN_TITLE_PT}
    min_seen = {k: None for k in limits}
    below = []
    overflow = []
    unknown_size = 0
    missing_glyphs = {}
    truncated = []
    glyph_src = "unavailable"
    widths_src = set()
    checked_text = []
    for p in texts:
        t = text_of(p)
        if t is None:
            continue
        checked_text.append(t)
        sp = size_pt_of(p)
        if sp is None:
            unknown_size += 1
            continue
        cls = classify(p, norm_ws(t))
        lim = limits[cls]
        min_seen[cls] = sp if min_seen[cls] is None else min(min_seen[cls], sp)
        if sp + 1e-9 < lim:
            below.append((str(p.get("id", "?")), cls, round(sp, 2), lim))
        lines = p.get("lines") if isinstance(p.get("lines"), list) else None
        if lines:
            mw = max(measure_width_mm(str(ln), sp, fs, bool(p.get("bold")))[0] for ln in lines)
            widths_src.add(measure_width_mm(str(lines[0]), sp, fs, bool(p.get("bold")))[1])
            rendered = norm_ws(" ".join(str(ln) for ln in lines))
            declared_tokens = norm_ws(t).split()
            dropped = [tok for tok in declared_tokens if tok not in rendered.split()]
            if dropped:
                truncated.append((str(p.get("id", "?")), len(dropped), dropped[:4]))
        else:
            mw, src = measure_width_mm(t, sp, fs, bool(p.get("bold")))
            widths_src.add(src)
        container, ckey = None, "none"
        for k in _CONTAINER_KEYS:
            if _num(p.get(k)):
                container, ckey = float(p[k]), k
                break
        if container is None and isinstance(p.get("container"), dict) and _num(p["container"].get("w")):
            container, ckey = float(p["container"]["w"]), "container.w"
        if container is None:
            b = bbox_of(p)
            if b is not None:
                container, ckey = b["w"], "bbox.w"
        if container is not None and mw - container > 0.05:
            overflow.append((str(p.get("id", "?")), round(mw, 2), round(container, 2), ckey))
        miss, gsrc = glyph_coverage(t, fs)
        glyph_src = gsrc
        if miss:
            missing_glyphs[str(p.get("id", "?"))] = miss[:4]

    def _mn(k):
        v = min_seen[k]
        return "n/a" if v is None else "%.2fpt" % v
    parts = ["text_nodes=%d" % len(texts),
             "min_body=%s(>=%.1f)" % (_mn("body"), limits["body"]),
             "min_panel_title=%s(>=%.1f)" % (_mn("panel_title"), limits["panel_title"]),
             "min_main_title=%s(>=%.1f)" % (_mn("main_title"), limits["main_title"]),
             "below_floor=%d" % len(below),
             "overflow_events=%d" % len(overflow),
             "truncated_labels=%d" % len(truncated),
             "unknown_size=%d" % unknown_size,
             "glyph_missing=%d(items)" % len(missing_glyphs),
             "widths=%s" % ("+".join(sorted(widths_src)) or "n/a")]
    if overflow:
        o = max(overflow, key=lambda x: x[1] - x[2])
        parts.append("worst_overflow=%s %.2fmm > %.2fmm (%s) +%.2fmm" % (o[0], o[1], o[2], o[3], o[1] - o[2]))
    if below:
        b0 = min(below, key=lambda x: x[2])
        parts.append("worst_size=%s %s %.2fpt < %.1fpt" % (b0[0], b0[1], b0[2], b0[3]))
    if glyph_src == "unavailable":
        parts.append("glyph_check=unavailable")
    if truncated:
        t0 = truncated[0]
        parts.append("worst_truncation=%s %d token(s) dropped: %s" % (t0[0], t0[1], t0[2]))
    detail = ", ".join(parts)
    if missing_glyphs:
        first = sorted(missing_glyphs)[0]
        return "fail", detail + " | missing in %s: %s" % (first, missing_glyphs[first])
    if below or overflow or truncated:
        return "fail", detail
    if unknown_size and unknown_size == len([p for p in texts if text_of(p) is not None]):
        return "warn", detail + " | no font size published on any text primitive"
    if glyph_src == "unavailable":
        return "warn", detail
    return "pass", detail


# --------------------------------------------------------------------------- #
# gate C — colour accessibility
# --------------------------------------------------------------------------- #
def _colour_groups(spec, scene_obj):
    """[(label, [hex, ...])] — colours that encode alternatives within one panel."""
    groups = []
    for pi, panel in enumerate((spec or {}).get("panels") or []):
        if not isinstance(panel, dict):
            continue
        pid = panel.get("id") or "P%d" % pi
        for li, leg in enumerate(iter_legends(panel)):
            cols = [it.get("color") for it in (leg.get("items") or []) if isinstance(it, dict)]
            cols = [c for c in cols if hex_to_rgb(c)]
            if len(cols) > 1:
                groups.append(("%s.legend[%d]" % (pid, li), cols))
        for ci, chart in enumerate(panel.get("charts") or []):
            cols = [s.get("color") for s in (chart.get("series") or []) if isinstance(s, dict)]
            cols = [c for c in cols if hex_to_rgb(c)]
            if len(cols) > 1:
                groups.append(("%s.chart[%s]" % (pid, chart.get("id") or ci), cols))
    # scene-level legend/chart primitives, when render-core publishes colours
    for p in (scene_obj or {}).get("primitives") or []:
        if not isinstance(p, dict):
            continue
        t = p.get("type")
        if t == "legend" and isinstance(p.get("items"), list):
            cols = [it.get("color") or it.get("fill") for it in p["items"] if isinstance(it, dict)]
            cols = [c for c in cols if hex_to_rgb(c)]
            if len(cols) > 1:
                groups.append(("scene:legend:%s" % p.get("id", "?"), cols))
        elif t == "chart" and isinstance(p.get("series"), list):
            cols = [s.get("color") or s.get("fill") for s in p["series"] if isinstance(s, dict)]
            cols = [c for c in cols if hex_to_rgb(c)]
            if len(cols) > 1:
                groups.append(("scene:chart:%s" % p.get("id", "?"), cols))
    return groups


_PAINTED = ("rect", "rrect", "circle", "ellipse", "path", "polygon", "capsule", "hexagon",
            "diamond", "note", "panel", "chart", "colorbar", "legend", "scalebar", "frame")

# A background is an *area*, so a hairline cannot sit behind a label's centre: a
# 0.45 mm arrowhead or a stroked connector whose bbox happens to contain the
# label's centroid would otherwise be scored as the label's background colour
# (dark arrow + dark text -> a bogus 1:1 contrast failure).  Only a primitive that
# actually covers an area counts.
MIN_BG_MM = 0.6


def area_fill(prim):
    """The colour a primitive covers an area with, or None if it only strokes.

    Distinct from ``prim_color`` on purpose: an explicit ``fill: none`` means the
    primitive is drawn with its stroke only, so it can never be a text background
    no matter what its stroke colour is.
    """
    if not isinstance(prim, dict):
        return None
    st = prim.get("style") if isinstance(prim.get("style"), dict) else {}
    saw_fill = False
    for src in (prim, st):
        if "fill" not in src:
            continue
        saw_fill = True
        rgb = hex_to_rgb(src.get("fill"))
        if rgb is None:
            return None                      # 'none'/'transparent'/unparseable
        return src.get("fill")
    if not saw_fill:
        # containers may carry their colour in color/colour (no fill key at all)
        rgb, raw = prim_color(prim)
        if rgb is not None:
            return raw
    return None


def _text_background_pairs(spec, scene_obj):
    """[(element_id, fg_hex, bg_hex, fg_rgb, bg_rgb, size_pt, bold, bg_source)].

    The background of a label is the *topmost painted primitive that contains it*
    (a chip/panel fill), falling back to the page background.  Using the page
    background for every label would score white text on a dark chip as 1:1.
    """
    canvas = canvas_of(scene_obj, spec)
    prims = [p for p in ((scene_obj or {}).get("primitives") or []) if isinstance(p, dict)]
    page_area = canvas["w_mm"] * canvas["h_mm"]
    bg_rgb, bg_raw, bg_src = None, None, "page-default"
    for p in prims:
        if p.get("type") != "rect" and str(p.get("layer") or "").lower() != "frame":
            continue
        b = bbox_of(p)
        if not b or page_area <= 0:
            continue
        if (b["w"] * b["h"]) >= 0.9 * page_area:
            rgb, raw = prim_color(p)
            if rgb is not None:
                bg_rgb, bg_raw, bg_src = rgb, raw, str(p.get("id", "page-rect"))
                break
    if bg_rgb is None:
        bg_raw = (((spec or {}).get("meta") or {}).get("background")
                  or ((spec or {}).get("palette") or {}).get("background") or "#ffffff")
        bg_rgb = hex_to_rgb(bg_raw) or (1.0, 1.0, 1.0)
        bg_raw = bg_raw if hex_to_rgb(bg_raw) else "#ffffff(default)"
    painted = []
    for p in prims:
        if p.get("type") not in _PAINTED:
            continue
        b = bbox_of(p)
        if not b:
            continue
        if min(b["w"], b["h"]) < MIN_BG_MM:
            continue                          # a hairline covers no area
        raw_fill = area_fill(p)
        if raw_fill is None:
            continue                          # fill:none / stroke-only primitive
        rgb = hex_to_rgb(raw_fill)
        if rgb is None:
            continue
        painted.append((p, b, rgb, raw_fill))
    pairs = []
    for p in _text_prims(scene_obj):
        fg, fg_raw = prim_color(p)
        if fg is None:
            continue
        tb = bbox_of(p)
        bgc, bgr_raw, src = bg_rgb, bg_raw, bg_src
        if tb is not None:
            cx = tb["x"] + tb["w"] / 2.0
            cy = tb["y"] + tb["h"] / 2.0
            for q, b, rgb, raw in painted:      # later primitives paint on top
                if q is p:
                    continue
                if b["x"] - 1e-6 <= cx <= b["x"] + b["w"] + 1e-6 and b["y"] - 1e-6 <= cy <= b["y"] + b["h"] + 1e-6:
                    if (b["w"] * b["h"]) >= 0.9 * page_area:
                        continue
                    bgc, bgr_raw, src = rgb, raw, str(q.get("id", "?"))
        pairs.append((str(p.get("id", "?")), fg_raw, bgr_raw, fg, bgc, size_pt_of(p),
                      bool(p.get("bold")), src))
    return pairs


def gate_c(spec, scene_obj, export_report, out_dir, materials):
    groups = _colour_groups(spec, scene_obj)
    palette = scene.resolve_palette(spec)
    pal_rgb = [hex_to_rgb(c) for c in palette if hex_to_rgb(c)]
    stats = []
    if len(pal_rgb) > 1:
        for kind in ("normal", "protan", "deutan", "tritan"):
            sim = pal_rgb if kind == "normal" else [simulate(c, kind) for c in pal_rgb]
            labs = [to_lab(c) for c in sim]
            m = min(delta_e(labs[i], labs[j]) for i, j in itertools.combinations(range(len(labs)), 2))
            stats.append("palette_%s_min_dE=%.2f" % (kind, m))
    if groups:
        worst_cvd = None
        worst_gray = None
        for label, cols in groups:
            rgbs = [hex_to_rgb(c) for c in cols]
            for kind in ("normal", "protan", "deutan", "tritan"):
                sim = rgbs if kind == "normal" else [simulate(c, kind) for c in rgbs]
                labs = [to_lab(c) for c in sim]
                for i, j in itertools.combinations(range(len(labs)), 2):
                    d = delta_e(labs[i], labs[j])
                    if worst_cvd is None or d < worst_cvd[0]:
                        worst_cvd = (d, label, kind, cols[i], cols[j])
            ls = [to_lab(c)[0] for c in rgbs]
            for i, j in itertools.combinations(range(len(ls)), 2):
                dl = abs(ls[i] - ls[j])
                if worst_gray is None or dl < worst_gray[0]:
                    worst_gray = (dl, label, cols[i], cols[j])
        stats.append("categorical_groups=%d" % len(groups))
        stats.append("worst_CVD_min_dE=%.2f(%s/%s %s vs %s, floor %.1f)"
                     % (worst_cvd[0], worst_cvd[2], worst_cvd[1], worst_cvd[3], worst_cvd[4], CVD_MIN_DE))
        stats.append("worst_gray_min_dL*=%.2f(%s %s vs %s, floor %.1f)"
                     % (worst_gray[0], worst_gray[1], worst_gray[2], worst_gray[3], GRAY_MIN_DL))
    else:
        stats.append("categorical_groups=0")

    pairs = _text_background_pairs(spec, scene_obj)
    worst_ct = None
    ct_fail = []
    for eid, fg_raw, bg_raw, fg, bg, sp, bold, bg_src in pairs:
        cr = contrast_ratio(fg, bg)
        large = (sp is not None and sp >= LARGE_PT) or (sp is not None and bold and sp >= LARGE_BOLD_PT)
        need = WCAG_LARGE if large else WCAG_NORMAL
        if worst_ct is None or cr < worst_ct[0]:
            worst_ct = (cr, eid, fg_raw, bg_raw, need, bg_src)
        if cr + 1e-9 < need:
            ct_fail.append((eid, round(cr, 2), need))
    if pairs:
        bg_counts = {}
        for _, _, _, _, _, _, _, s in pairs:
            bg_counts[s] = bg_counts.get(s, 0) + 1
        stats.append("text_bg_pairs=%d(backgrounds %d: %s)"
                     % (len(pairs), len(bg_counts),
                        ",".join("%s:%d" % kv for kv in sorted(bg_counts.items())[:4])))
        stats.append("worst_contrast=%.2f:1(%s fg=%s on bg=%s[%s] need>=%.1f)"
                     % (worst_ct[0], worst_ct[1], worst_ct[2], worst_ct[3], worst_ct[5], worst_ct[4]))
        stats.append("contrast_below=%d" % len(ct_fail))
    else:
        stats.append("text_bg_pairs=0")

    detail = ", ".join(stats)
    if not groups and not pairs:
        return "warn", detail + " | no colour-coded categories and no coloured text -> UNVERIFIABLE"
    fails = []
    if groups and worst_cvd[0] + 1e-9 < CVD_MIN_DE:
        fails.append("CVD dE %.2f < %.1f (%s/%s)" % (worst_cvd[0], CVD_MIN_DE, worst_cvd[1], worst_cvd[2]))
    if groups and worst_gray[0] + 1e-9 < GRAY_MIN_DL:
        fails.append("grayscale dL* %.2f < %.1f (%s)" % (worst_gray[0], GRAY_MIN_DL, worst_gray[1]))
    if ct_fail:
        fails.append("contrast %d below WCAG" % len(ct_fail))
    if fails:
        return "fail", detail + " | " + "; ".join(fails)
    if not groups or not pairs:
        return "warn", detail + " | partial evidence (groups=%d, text_bg_pairs=%d)" % (len(groups), len(pairs))
    return "pass", detail


# --------------------------------------------------------------------------- #
# gate D — encoding fidelity (legend / colorbar / units / arrows)
# --------------------------------------------------------------------------- #
def _panel_data_values(panel):
    """Values a panel's colour channels encode, grouped by unit.

    A colourbar titled "(fold)" cannot encode pmol/min readings, so comparing its
    range against every value in the panel is wrong: it reports a mismatch for
    data the bar does not claim to describe.
    """
    vals = []
    for node in panel.get("nodes") or []:
        if isinstance(node, dict) and _num(node.get("value")):
            vals.append((float(node["value"]), node.get("unit")))
    for edge in panel.get("edges") or []:
        if isinstance(edge, dict) and _num(edge.get("value")):
            vals.append((float(edge["value"]), edge.get("unit")))
    return vals


def gate_d(spec, scene_obj, export_report, out_dir, materials):
    problems, notes, unverified = [], [], []
    legend_checked = 0
    colorbar_checked = 0
    unit_missing = []
    colour_pairs = 0
    for pi, panel in enumerate((spec or {}).get("panels") or []):
        if not isinstance(panel, dict):
            continue
        pid = panel.get("id") or "P%d" % pi
        charts = [(c.get("id") or "chart%d" % i, [s.get("name") for s in (c.get("series") or [])
                                                   if isinstance(s, dict)])
                  for i, c in enumerate(panel.get("charts") or []) if isinstance(c, dict)]
        charts = [(cid, names) for cid, names in charts if names]
        # CONTRACT 8.7: a legend's label set == the union of series names of the
        # panel's charts.  CONTRACT 6 D: that union must also equal a chart's
        # category set (multiset) — i.e. the colours encode one chart's categories.
        #
        # A legend whose items declare `kind`/`part` is a *semantic* key for the
        # connectors/vessels, not a data-category key, so the series-name rule is
        # simply the wrong rule for it: gate K904 owns that comparison.  Applying
        # D's rule there produced an UNVERIFIABLE warn on every kind-only legend
        # (no chart in the panel), which is a false alarm, not a coverage gap.
        for li, leg in enumerate(iter_legends(panel)):
            entries = [it for it in (leg.get("items") or []) if isinstance(it, dict)]
            semantic = [it for it in entries if it.get("kind") or it.get("part")]
            data_items = [it for it in entries if not (it.get("kind") or it.get("part"))]
            items = [it.get("label") for it in data_items]
            items = [x for x in items if x]
            if not items:
                if semantic:
                    notes.append("%s.legend[%d] %d kind/part item(s) -> semantic key, "
                                 "D series rule not applicable (gate K904 checks it)"
                                 % (pid, li, len(semantic)))
                continue
            legend_checked += 1
            want = sorted(x.strip().casefold() for x in items)
            if not charts:
                unverified.append("%s.legend[%d]: %d items but 0 chart series -> UNVERIFIABLE"
                             % (pid, li, len(want)))
                continue
            union = sorted({n.strip().casefold() for cid, names in charts for n in names if n})
            exact = [cid for cid, names in charts
                     if sorted(n.strip().casefold() for n in names if n) == want]
            allnames = [n.strip().casefold() for cid, names in charts for n in names if n]
            orphans = sorted(x for x in want if x not in allnames)
            if orphans:
                problems.append("%s.legend[%d] has %d orphan item(s) not in any chart series: %s"
                                % (pid, li, len(orphans), orphans[:4]))
            if union != want:
                problems.append("%s.legend[%d] %d items != union of series names in %d chart(s) %s "
                                "(CONTRACT 8.7) missing=%s extra=%s"
                                % (pid, li, len(want), len(charts), [c for c, _ in charts],
                                   sorted(set(union) - set(want)), sorted(set(want) - set(union))))
            elif len(charts) == 1:
                # a single colour-coded chart must also match as a multiset (6 D)
                if sorted(n.strip().casefold() for n in charts[0][1] if n) != want:
                    problems.append("%s.legend[%d] %d items != multiset of chart %s series %s"
                                    % (pid, li, len(want), charts[0][0], charts[0][1]))
                else:
                    notes.append("%s.legend[%d] %d items == series union == chart %s series (multiset)"
                                 % (pid, li, len(want), charts[0][0]))
            else:
                exact_txt = ""
                if exact:
                    exact_txt = ", equals chart %s series exactly" % ",".join(exact)
                notes.append("%s.legend[%d] %d items == union of series names across %d chart(s)%s "
                             "(no single chart has this multiset; 8.7 set rule satisfied)"
                             % (pid, li, len(want), len(charts), exact_txt))

        # a colour-coded chart with no *data* legend cannot be read off the figure
        # (a kind/part legend documents connectors, not chart categories)
        legs_here = list(iter_legends(panel))
        data_legs = [leg for leg in legs_here
                     if any(isinstance(it, dict) and it.get("label")
                            and not (it.get("kind") or it.get("part"))
                            for it in (leg.get("items") or []))]
        if charts and not data_legs:
            problems.append("%s has %d chart(s) with %d series name(s) but 0 data legend "
                            "-> colour channel unmapped (%d semantic legend(s) present)"
                            % (pid, len(charts),
                               len({n.strip().casefold() for _, names in charts for n in names if n}),
                               len(legs_here) - len(data_legs)))
        leg_colors, ser_colors = {}, {}
        for leg in data_legs:
            for it in leg.get("items") or []:
                if isinstance(it, dict) and it.get("label") and it.get("color") \
                        and not (it.get("kind") or it.get("part")):
                    leg_colors[str(it["label"]).strip().casefold()] = str(it["color"]).strip().lower()
        for c in panel.get("charts") or []:
            for s in (c.get("series") or []):
                if isinstance(s, dict) and s.get("name") and s.get("color"):
                    ser_colors.setdefault(str(s["name"]).strip().casefold(), str(s["color"]).strip().lower())
        colour_pairs += len(set(leg_colors) & set(ser_colors))
        mismatch = sorted(k for k in leg_colors if k in ser_colors and leg_colors[k] != ser_colors[k])
        if mismatch:
            problems.append("%s legend colour != series colour for %d name(s): %s"
                            % (pid, len(mismatch),
                               ["%s %s!=%s" % (k, leg_colors[k], ser_colors[k]) for k in mismatch[:3]]))

        # colourbar vs the values it encodes (node/edge values, else heatmap data)
        for bi, cb in enumerate(panel.get("colorbars") or []):
            if not isinstance(cb, dict):
                continue
            if not cb.get("unit"):
                unit_missing.append("%s.colorbar[%s].unit" % (pid, cb.get("id")))
            vmin, vmax = cb.get("vmin"), cb.get("vmax")
            if not (_num(vmin) and _num(vmax)):
                problems.append("%s.colorbar[%s] vmin/vmax not numeric" % (pid, cb.get("id")))
                continue
            heat = [c for c in (panel.get("charts") or [])
                    if isinstance(c, dict) and c.get("type") == "heatmap"]
            vals = []
            for h in heat:
                for s in h.get("series") or []:
                    vals += [float(v) for v in (s.get("values") or []) if _num(v)]
            src_desc = "heatmap"
            if not vals:
                pairs = _panel_data_values(panel)
                cb_unit = (cb.get("unit") or "").strip().lower()
                # only values whose unit matches the bar's own unit belong to it
                same = [v for v, u in pairs
                        if not cb_unit or (u or "").strip().lower() == cb_unit]
                vals = same or [v for v, _ in pairs]
                src_desc = "node/edge values (unit %s)" % (cb.get("unit") or "?")
            if not vals:
                unverified.append("%s.colorbar[%s] vmin=%.3f vmax=%.3f: 0 data values in panel -> UNVERIFIABLE"
                             % (pid, cb.get("id"), vmin, vmax))
                continue
            colorbar_checked += 1
            dmin, dmax = min(vals), max(vals)
            span = max(vmax - vmin, 1e-12)
            allowed = max(COLORBAR_SLACK_FRAC * span, 0.05 * max(dmax - dmin, 1e-12))
            slack_low, slack_high = dmin - vmin, vmax - dmax
            if slack_low < -1e-9 or slack_high < -1e-9:
                problems.append("%s.colorbar[%s] declared %.3f..%.3f excludes %s min=%.3f max=%.3f"
                                % (pid, cb.get("id"), vmin, vmax, src_desc, dmin, dmax))
            elif max(slack_low, slack_high) > allowed + 1e-9:
                problems.append("%s.colorbar[%s] declared %.3f..%.3f too loose for %s %.3f..%.3f "
                                "(slack %.3f>%.3f)"
                                % (pid, cb.get("id"), vmin, vmax, src_desc, dmin, dmax,
                                   max(slack_low, slack_high), allowed))
            else:
                notes.append("%s.colorbar[%s] %.3f..%.3f covers %s %.3f..%.3f (slack %.3f/%.3f<=%.3f)"
                             % (pid, cb.get("id"), vmin, vmax, src_desc, dmin, dmax,
                                slack_low, slack_high, allowed))

    # units on every chart
    for panel, chart in iter_charts(spec):
        if not chart.get("unit"):
            unit_missing.append("%s.chart[%s].unit" % (panel.get("id"), chart.get("id")))

    # arrow direction counts vs spec edge kinds
    spec_kinds = {}
    for label, edge in iter_edges(spec):
        k = edge.get("kind") or "unspecified"
        spec_kinds[k] = spec_kinds.get(k, 0) + 1
    scene_arrows = [p for p in (scene_obj or {}).get("primitives") or [] if is_arrow_prim(p)]
    scene_kinds = {}
    for p in scene_arrows:
        k = prim_kind(p) or "unspecified"
        scene_kinds[k] = scene_kinds.get(k, 0) + 1
    spec_total = sum(spec_kinds.values())
    scene_total = len(scene_arrows)
    if not scene_arrows and spec_total:
        problems.append("spec has %d edges %s but scene has 0 arrow primitives" % (spec_total, spec_kinds))
    elif scene_kinds != spec_kinds and "unspecified" not in scene_kinds:
        problems.append("scene arrow kinds %s != spec edge kinds %s" % (scene_kinds, spec_kinds))
    elif scene_total != spec_total:
        problems.append("scene arrow count %d != spec edge count %d" % (scene_total, spec_total))

    # Per-edge direction/wiring. A histogram cannot tell a reversed arrow from a
    # correct one: swapping every edge's from/to keeps the counts identical while
    # the causal arrows point backwards, which is the single worst error a
    # mechanism figure can make.
    direction_checked = direction_bad = 0
    if scene_arrows and any("from" in p or "to" in p for p in scene_arrows):
        spec_pairs = {}
        for label, edge in iter_edges(spec):
            a, b = edge.get("from"), edge.get("to")
            if isinstance(a, str) and isinstance(b, str):
                spec_pairs[(a, b)] = edge.get("kind") or "unspecified"
        scene_pairs = {}
        for p in scene_arrows:
            a, b = p.get("from"), p.get("to")
            if isinstance(a, str) and isinstance(b, str):
                scene_pairs[(a, b)] = prim_kind(p) or "unspecified"
        direction_checked = len(scene_pairs)
        for (a, b), kind in scene_pairs.items():
            if (a, b) not in spec_pairs:
                if (b, a) in spec_pairs:
                    problems.append("arrow %s->%s is REVERSED (spec says %s->%s)" % (a, b, b, a))
                else:
                    problems.append("arrow %s->%s matches no spec edge" % (a, b))
                direction_bad += 1
            elif spec_pairs[(a, b)] != kind:
                problems.append("arrow %s->%s kind %r != spec %r" % (a, b, kind, spec_pairs[(a, b)]))
                direction_bad += 1
        for pair in spec_pairs:
            if pair not in scene_pairs:
                problems.append("spec edge %s->%s has no arrow in the scene" % pair)
                direction_bad += 1

    # CONTRACT §3.5 (D extension): the *visual encoding* must match the spec too.
    # A histogram of kinds cannot see that a dashed energy arrow was drawn solid,
    # so every edge that declares a linestyle is compared against the prim the
    # renderer actually painted.  When the spec is silent, the kind's contract
    # encoding is reported as an observation only -- never as a failure, because
    # the spec remains the sole authority for what was asked for.
    linestyle_checked = linestyle_bad = linestyle_unknown = 0
    scene_by_pair = {}
    for rec in scene_edge_records(scene_obj):
        if isinstance(rec["from"], str) and isinstance(rec["to"], str):
            scene_by_pair.setdefault((rec["from"], rec["to"]), []).append(rec)
    for _, edge in iter_edges(spec):
        pair = (edge.get("from"), edge.get("to"))
        want = edge.get("linestyle")
        if isinstance(want, str) and want.strip():
            recs = scene_by_pair.get(pair) or []
            if not recs:
                linestyle_unknown += 1
                continue
            got = recs[0]["linestyle"]
            linestyle_checked += 1
            if got != want.strip().lower():
                problems.append("edge %s->%s declared linestyle %r but was rendered %r"
                                % (edge.get("from"), edge.get("to"),
                                   want.strip().lower(), got))
                linestyle_bad += 1
        else:
            implied = LINESTYLE_BY_KIND.get(edge.get("kind"))
            recs = scene_by_pair.get(pair) or []
            if not implied or not recs:
                continue
            got = recs[0]["linestyle"]
            if got != implied:
                notes.append("edge %s->%s kind %r rendered %r (contract §3.5 suggests %r)"
                             % (edge.get("from"), edge.get("to"), edge.get("kind"), got, implied))

    if unit_missing:
        problems.append("%d element(s) missing unit: %s" % (len(unit_missing), unit_missing[:5]))

    detail = ("legends_checked=%d, legend_series_colour_pairs=%d, colorbars_checked=%d, spec_edges=%d%s, "
              "scene_arrows=%d%s, edge_direction_checked=%d, linestyle_checked=%d, linestyle_mismatch=%d, "
              "linestyle_unknown=%d, units_missing=%d, problems=%d%s"
              % (legend_checked, colour_pairs, colorbar_checked, spec_total,
                 "{%s}" % ",".join("%s:%d" % kv for kv in sorted(spec_kinds.items())),
                 scene_total,
                 "{%s}" % ",".join("%s:%d" % kv for kv in sorted(scene_kinds.items())),
                 direction_checked, linestyle_checked, linestyle_bad, linestyle_unknown,
                 len(unit_missing),
                 len(problems),
                 (" | " + "; ".join(problems[:3])) if problems else (" | " + "; ".join(notes[:3]))))
    detail_unverified = "; ".join(unverified[:3])
    if problems:
        return "fail", detail
    # `unverified` = a comparison that could not be made (soft UNVERIFIABLE).
    # `notes` = a comparison that WAS made and matched; those are informational
    # and must not downgrade the gate, otherwise a legend can never pass.
    if unverified and not (legend_checked or colorbar_checked):
        return "warn", detail
    if legend_checked == 0 and colorbar_checked == 0:
        return "warn", detail + " | no legend and no bound colorbar -> UNVERIFIABLE"
    if unverified:
        return "warn", detail
    return "pass", detail


# --------------------------------------------------------------------------- #
# gate E — provenance
# --------------------------------------------------------------------------- #
def _material_texts(materials):
    out = []
    mats = (materials or {}).get("materials")
    if not isinstance(mats, list):
        mats = materials if isinstance(materials, list) else []
    for m in mats:
        if not isinstance(m, dict):
            continue
        text = m.get("text")
        if not isinstance(text, str) or not text:
            pages = m.get("pages")
            if isinstance(pages, list):
                text = "\n".join(p if isinstance(p, str) else str(p) for p in pages)
        if not isinstance(text, str):
            text = ""
        out.append({"path": str(m.get("path") or ""), "text": text, "kind": m.get("kind")})
    return out


def _pick_material(src_file, mats):
    norm = str(src_file or "").replace("\\", "/")
    for m in mats:
        if m["path"].replace("\\", "/") == norm:
            return m, "exact"
    for m in mats:
        if m["path"].replace("\\", "/").endswith("/" + norm) or m["path"].replace("\\", "/") == norm:
            return m, "relative"
    for m in mats:
        if os.path.basename(m["path"].replace("\\", "/")) == os.path.basename(norm):
            return m, "basename"
    return None, "missing"


def _locator_span(locator, text):
    """Resolve 'L21-L22' / 'L7' / 'row 9' to (start,end) char offsets, or None."""
    loc = str(locator or "").strip()
    lines = text.splitlines(keepends=True)
    m = re.match(r"^L(\d+)(?:\s*-\s*L?(\d+))?$", loc)
    if m:
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if a < 1 or b > len(lines) or a > b:
            return None, "line span out of range (file has %d lines)" % len(lines)
        start = sum(len(x) for x in lines[:a - 1])
        end = sum(len(x) for x in lines[:b])
        return (start, end), None
    m = re.match(r"^rows?\s+(\d+)(?:\s*-\s*(\d+))?$", loc, re.I)
    if m:
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if a < 1 or b > len(lines) or a > b:
            return None, "row span out of range (file has %d lines)" % len(lines)
        start = sum(len(x) for x in lines[:a - 1])
        end = sum(len(x) for x in lines[:b])
        return (start, end), None
    return None, "unrecognised locator"


def _own_provenance(spec, materials):
    """Identical semantics to evidence.check_provenance, measured by us."""
    mats = _material_texts(materials)
    ev_items = [e for e in ((spec or {}).get("evidence") or []) if isinstance(e, dict)]
    ev_ids = {e.get("id") for e in ev_items}
    refs = iter_source_refs(spec)
    dangling = [(path, ref) for path, ref in refs if ref not in ev_ids]
    empty_mats = len(mats) == 0 or all(not m["text"] for m in mats)
    resolved, unresolved = [], []
    for ev in ev_items:
        src = ev.get("source") or {}
        quote = norm_ws(src.get("quote"))
        loc = src.get("locator")
        if empty_mats:
            unresolved.append({"id": ev.get("id"), "reason": "no material text available"})
            continue
        mat, how = _pick_material(src.get("file"), mats)
        if mat is None or not mat["text"]:
            unresolved.append({"id": ev.get("id"), "reason": "source.file %r not in materials (%s)"
                               % (src.get("file"), how)})
            continue
        hay = norm_ws(mat["text"])
        if not quote or quote not in hay:
            unresolved.append({"id": ev.get("id"), "reason": "quote (%d chars) not found verbatim in %s"
                               % (len(quote), os.path.basename(mat["path"]))})
            continue
        span, why = _locator_span(loc, mat["text"])
        if span is None:
            resolved.append({"id": ev.get("id"), "file": mat["path"], "locator": loc,
                             "mode": "quote-verbatim, locator unresolved (%s)" % why})
            continue
        seg = norm_ws(mat["text"][span[0]:span[1]])
        if quote in seg:
            resolved.append({"id": ev.get("id"), "file": mat["path"], "locator": loc, "mode": "span"})
        else:
            unresolved.append({"id": ev.get("id"),
                               "reason": "quote found in file but outside locator %s span" % loc})
    return {"refs": len(refs), "dangling": dangling, "resolved": resolved,
            "unresolved": unresolved, "empty_materials": empty_mats, "materials": len(mats)}


_NUM_RE = re.compile(r"(?<![A-Za-z0-9._\-])-?\d+(?:\.\d+)?(?![A-Za-z])")


def numbers_in(text):
    """Every measurable number in a string (identifiers such as HIF-1alpha stay out)."""
    out = []
    for m in _NUM_RE.finditer(str(text or "")):
        try:
            out.append(float(m.group(0)))
        except ValueError:
            pass
    return out


def element_visible_numbers(element):
    """Every number the element can print, from ``value`` and from its text."""
    out = []
    if not isinstance(element, dict):
        return out

    def add(v):
        if _num(v):
            out.append(float(v))

    if element.get("derived"):
        for v in element.get("source_values") or []:
            add(v)
    else:
        add(element.get("value"))
        for v in element.get("values") or []:
            add(v)
    for key, val in element.items():
        if key in ("value", "values", "source_values", "source", "sources", "id", "from", "to"):
            continue
        if isinstance(val, str):
            out.extend(numbers_in(val))
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    out.extend(numbers_in(item))
    seen, uniq = set(), []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def number_in_text(value, text):
    """True when ``value`` appears in ``text`` under any of the usual renderings."""
    if value is None:
        return True
    try:
        cands = ["%g" % value, "%.1f" % value, "%.2f" % value, "%.3f" % value,
                 str(int(value)) if float(value).is_integer() else str(value)]
        if float(value).is_integer():
            cands.append("%02d" % int(value))
    except (TypeError, ValueError):
        return True
    hay = norm_ws(text)
    return any(re.search(r"(?<![0-9.])" + re.escape(c) + r"(?![0-9])", hay) for c in cands)


def _own_step_phase_port_numbers(spec):
    """CONTRACT §4 E extension: step / phase / port must obey the same number rule.

    ``evidence.check_provenance`` covers node/edge/series/legend/texts/meta; the
    new element classes are checked here so that a number printed by a process
    step is traceable by exactly the same rule as a number printed by a node.
    Returns measured counters and the offending items (never a status).
    """
    ev = {e.get("id"): e for e in ((spec or {}).get("evidence") or []) if isinstance(e, dict)}
    targets = []
    for pi, panel in enumerate(spec_panels(spec)):
        for ti, step in enumerate(panel.get("steps") or []):
            if isinstance(step, dict):
                targets.append(("$.panels[%d].steps[%d](%s)" % (pi, ti, step.get("id")), step))
        for hi, phase in enumerate(panel.get("phases") or []):
            if isinstance(phase, dict):
                targets.append(("$.panels[%d].phases[%d](%s)" % (pi, hi, phase.get("id")), phase))
        for ni, node in enumerate(panel.get("nodes") or []):
            for qi, port in enumerate(node.get("ports") or []):
                if isinstance(port, dict):
                    targets.append(("$.panels[%d].nodes[%d](%s).ports[%d]"
                                    % (pi, ni, node.get("id"), qi), port))
    checked = unverifiable = 0
    off_quote, unsourced = [], []
    for label, el in targets:
        vals = element_visible_numbers(el)
        if not vals:
            continue
        refs = _refs_of(el)
        if not refs:
            unsourced.append("%s prints %d number(s) with no source" % (label, len(vals)))
            continue
        quotes = []
        for r in refs:
            src = ((ev.get(r) or {}).get("source") or {})
            q = src.get("quote")
            if isinstance(q, str) and q.strip():
                quotes.append(q)
        if not quotes:
            unverifiable += len(vals)
            continue
        for v in vals:
            checked += 1
            if not any(number_in_text(v, q) for q in quotes):
                off_quote.append("%s prints %g, absent from the quote of %s"
                                 % (label, v, ",".join(refs)))
    return {"elements": len(targets), "checked": checked, "unverifiable": unverifiable,
            "off_quote": off_quote, "unsourced": unsourced}


def gate_e(spec, scene_obj, export_report, out_dir, materials):
    own = _own_provenance(spec, materials)
    ext = _own_step_phase_port_numbers(spec)
    mod = _soft_import("evidence")
    mod_note = "own"
    mod_issues = []
    if mod is not None and hasattr(mod, "check_provenance"):
        try:
            mod_issues = mod.check_provenance(spec, materials) or []
            mod_note = "evidence.check_provenance"
        except Exception as exc:
            mod_note = "evidence.check_provenance raised (%s); fell back to own" % type(exc).__name__
    mod_err = [i for i in mod_issues if isinstance(i, dict) and i.get("severity") == "error"]
    mod_warn = [i for i in mod_issues if isinstance(i, dict) and i.get("severity") != "error"]
    detail = ("source_checks=%s, materials=%d, refs=%d, dangling=%d, evidence_items=%d, "
              "quotes_resolved=%d, quotes_unresolved=%d, module_issues=%d(err=%d,warn=%d), "
              "ext_elements=%d, ext_numbers_checked=%d, ext_numbers_off_quote=%d, ext_numbers_unverifiable=%d"
              % (mod_note, own["materials"], own["refs"], len(own["dangling"]),
                 len(((spec or {}).get("evidence") or [])), len(own["resolved"]),
                 len(own["unresolved"]), len(mod_issues), len(mod_err), len(mod_warn),
                 ext["elements"], ext["checked"], len(ext["off_quote"]), ext["unverifiable"]))
    if own["dangling"]:
        d0 = own["dangling"][0]
        return "fail", detail + " | dangling source ids, e.g. %s -> %r" % (d0[0], d0[1])
    if own["empty_materials"]:
        return "warn", detail + " | UNVERIFIABLE: 0 material text, %d quotes unchecked" % len(own["unresolved"])
    if own["unresolved"]:
        u0 = own["unresolved"][0]
        return "fail", detail + " | first unresolved: %s (%s)" % (u0.get("id"), u0.get("reason"))
    if ext["unsourced"]:
        return "fail", detail + " | number(s) with no evidence source: %s" % ext["unsourced"][0]
    if ext["off_quote"]:
        return "fail", detail + " | number(s) not in their source quote: %s" % ext["off_quote"][0]
    if mod_err:
        msgs = "; ".join(str(m.get("message") or m) for m in mod_err[:4])
        if len(mod_err) > 4:
            msgs += "; (+%d more)" % (len(mod_err) - 4)
        return "fail", detail + " | module error(s): %s" % msgs
    if mod_warn:
        return "warn", detail + " | module warn: %s" % (mod_warn[0].get("message") or mod_warn[0])
    if own["refs"] == 0 and len(((spec or {}).get("evidence") or [])) == 0:
        return "warn", detail + " | no provenance claims to check"
    return "pass", detail


# --------------------------------------------------------------------------- #
# gate F — editability
# --------------------------------------------------------------------------- #
def _localname(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _svg_labels(spec, scene_obj):
    """Labels the emitted SVG must carry as real <text>.

    Returns (required, advisory) where
        required = {normalised_label: {"origin": str, "panel": panel_id|None}}
        advisory = {normalised_label: {"origin": str}}   (free prose, reported only)

    required covers every label the scene actually typeset (text primitives) plus
    node labels / panel titles / legend items from the spec.
    """
    required, advisory = {}, {}

    def _add(target, label, origin, panel=None):
        key = norm_ws(label)
        if key and key not in target:
            target[key] = {"origin": origin, "panel": panel}

    for p in _text_prims(scene_obj):
        t = text_of(p)
        if t:
            _add(required, t, "scene:%s" % p.get("id", "?"), p.get("panel"))
    for pi, panel in enumerate((spec or {}).get("panels") or []):
        if not isinstance(panel, dict):
            continue
        pid = panel.get("id")
        for node in panel.get("nodes") or []:
            if isinstance(node, dict) and node.get("label"):
                _add(required, node["label"], "node:%s" % node.get("id"), pid)
        if panel.get("title"):
            _add(required, panel["title"], "panel:%s" % pid, pid)
        for leg in iter_legends(panel):
            for it in leg.get("items") or []:
                if isinstance(it, dict) and it.get("label"):
                    _add(required, it["label"], "legend:%s" % pid, pid)
    for key in ("title", "subtitle", "caption", "conclusion", "summary"):
        v = ((spec or {}).get("texts") or {}).get(key)
        if v:
            _add(advisory, v, "text:%s" % key)
    for k in list(advisory):
        if k in required:
            advisory.pop(k)
    return required, advisory


def gate_f(spec, scene_obj, export_report, out_dir, materials):
    svg_path = os.path.join(out_dir, "figure.svg")
    if not os.path.exists(svg_path):
        return "fail", "figure.svg missing at %s (0 bytes) -> editability UNVERIFIABLE" % svg_path
    with open(svg_path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return "fail", "figure.svg does not parse: %s (bytes=%d)" % (exc, len(raw.encode('utf-8')))

    text_nodes, groups, all_ids, images = [], [], [], []
    for el in root.iter():
        ln = _localname(el.tag)
        if ln == "text":
            parts = [el.text] if (el.text or "").strip() else []
            for child in el:
                if _localname(child.tag) == "tspan":
                    parts.append("".join(child.itertext()))
            content = " ".join(p for p in parts if p and p.strip()) if parts else "".join(el.itertext())
            if content.strip():
                text_nodes.append(content)
        elif ln == "g":
            groups.append(el.get("id"))
        elif ln == "image":
            images.append(el)
        i = el.get("id")
        if i is not None:
            all_ids.append(i)
    dups = sorted({i for i in all_ids if all_ids.count(i) > 1})
    named = sum(1 for g in groups if g)
    unnamed = len(groups) - named

    # full-page rasterisation check
    canvas = canvas_of(scene_obj, spec)
    page_area = canvas["w_mm"] * canvas["h_mm"]
    full_raster = 0
    for el in images:
        def _len_mm(v):
            if not isinstance(v, str):
                return None
            m = re.match(r"^\s*([\d.]+)\s*(mm|cm|in|pt|px)?", v)
            if not m:
                return None
            val = float(m.group(1))
            unit = m.group(2) or "px"
            return {"mm": val, "cm": val * 10, "in": val * 25.4, "pt": val * 25.4 / 72, "px": val * 25.4 / 96}[unit]
        w = _len_mm(el.get("width"))
        h = _len_mm(el.get("height"))
        if w and h and page_area > 0 and (w * h) >= 0.5 * page_area:
            full_raster += 1

    required, advisory = _svg_labels(spec, scene_obj)
    candidates = [norm_ws(" ".join(text_nodes))]
    for el in root.iter():
        if _localname(el.tag) == "g":
            inner = norm_ws(" ".join("".join(t.itertext()) for t in el.iter() if _localname(t.tag) == "text"))
            if inner:
                candidates.append(inner)

    # per-panel text-index, for the token rule below
    panel_text = {}
    for el in root.iter():
        if _localname(el.tag) != "text":
            continue
        content = norm_ws("".join(el.itertext()))
        pid = el.get("data-panel")
        if pid:
            panel_text.setdefault(pid, []).append(content)
    for el in root.iter():
        if _localname(el.tag) != "g":
            continue
        pid = el.get("data-panel")
        if not pid:
            continue
        for t in el.iter():
            if _localname(t.tag) == "text":
                content = norm_ws("".join(t.itertext()))
                if content:
                    panel_text.setdefault(pid, []).append(content)
    panel_tokens = {pid: set(norm_ws(" ".join(lines)).split()) for pid, lines in panel_text.items()}
    for pid in panel_text:
        panel_tokens[pid] |= set(" ".join(panel_text[pid]).split())

    def _has(lab):
        lab = norm_ws(lab)
        return any(lab and lab in c for c in candidates)

    def _has_tokenwise(lab, pid):
        """Rule 2: every whitespace token of the label occurs in that panel's texts.

        This is how a title and its "(unit)" suffix drawn as two separate <text>
        nodes pass; it cannot hide a truncated/garbled label because every token
        must still be present, and the token match is reported separately.
        """
        toks = norm_ws(lab).split()
        if not toks or not pid:
            return False
        have = panel_tokens.get(pid)
        if not have:
            return False
        return all(t in have for t in toks)

    missing, tokenwise = [], []
    for lab, info in required.items():
        if _has(lab):
            continue
        if _has_tokenwise(lab, info["panel"]):
            tokenwise.append(lab)
        else:
            missing.append((info["origin"], lab))
    adv_missing = [(info["origin"], lab) for lab, info in advisory.items() if not _has(lab)]
    detail = ("svg_bytes=%d, text_nodes=%d, groups=%d(named=%d,unnamed=%d), ids=%d(unique=%d,dup=%d), "
              "images=%d(full_page=%d), required_labels=%d, labels_present=%d"
              "(contiguous=%d,token-covered=%d), labels_missing=%d, advisory_labels=%d(present=%d), "
              "rule={contiguous substring OR all label tokens present in that panel's text nodes}"
              % (len(raw.encode("utf-8")), len(text_nodes), len(groups), named, unnamed,
                 len(all_ids), len(set(all_ids)), len(dups), len(images), full_raster,
                 len(required), len(required) - len(missing),
                 len(required) - len(missing) - len(tokenwise), len(tokenwise), len(missing),
                 len(advisory), len(advisory) - len(adv_missing)))

    problems = []
    if not text_nodes:
        problems.append("0 non-empty <text> nodes (labels are paths, not editable text)")
    if missing:
        problems.append("%d required label(s) absent (neither contiguous nor token-covered), e.g. %r"
                        % (len(missing), missing[0][1][:40]))
    if unnamed:
        problems.append("%d unnamed <g> group(s)" % unnamed)
    if dups:
        problems.append("%d duplicate id(s): %s" % (len(dups), dups[:4]))
    if full_raster:
        problems.append("%d <image> element(s) cover >=50%% of the page" % full_raster)

    # round-trip: patch one real label in a COPY, assert it lands and structure survives
    roundtrip = "not run"
    if text_nodes and not problems:
        edit_mod = _soft_import("edit")
        if edit_mod is None:
            roundtrip = "edit module unavailable"
        else:
            tmp_dir = os.path.join(out_dir, ".edit_check")
            try:
                if os.path.isdir(tmp_dir):
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                os.makedirs(tmp_dir)
                tmp_svg = os.path.join(tmp_dir, "figure.svg")
                with open(tmp_svg, "w", encoding="utf-8", newline="") as fh:
                    fh.write(raw)
                target = text_nodes[0]
                res = edit_mod.patch_svg_text(tmp_svg, {target: target + " [edited]"})
                ok = (res.get("changed_bytes") and res.get("applied") and res.get("parses")
                      and res.get("structure_preserved"))
                if not ok:
                    problems.append("patch_svg_text round-trip failed: applied=%s changed=%s parses=%s "
                                    "structure=%s" % (res.get("applied"), res.get("changed_bytes"),
                                                      res.get("parses"), res.get("structure_preserved")))
                roundtrip = ("patched 1 label(%r, %d chars), applied=%d changed=%s parses=%s "
                             "structure=%s ids_preserved=%s"
                             % (target[:16], len(target), len(res.get("applied") or []),
                                res.get("changed_bytes"), res.get("parses"),
                                res.get("structure_preserved"), res.get("ids_preserved")))
            except Exception as exc:
                problems.append("patch_svg_text raised %s: %s" % (type(exc).__name__, exc))
                roundtrip = "raised %s" % type(exc).__name__
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    detail += ", roundtrip={%s}" % roundtrip
    if problems:
        return "fail", detail + " | " + "; ".join(problems)
    if not required:
        return "warn", detail + " | scene and spec declare 0 labels -> label presence is vacuous"
    return "pass", detail


# --------------------------------------------------------------------------- #
# gate G — determinism
# --------------------------------------------------------------------------- #
def gate_g(spec, scene_obj, export_report, out_dir, materials):
    names = [n for n in ("figure.svg", "figure.png", "figure.pdf")
             if os.path.exists(os.path.join(out_dir, n))]
    if not names:
        return "fail", "no exported artefacts in %s (0 files)" % out_dir
    if not scene_obj:
        return "fail", "%d artefact(s) present but scene.json is empty -> re-export UNVERIFIABLE" % len(names)
    export_mod = _soft_import("export")
    if export_mod is None:
        return "fail", "export module unavailable; cannot re-export %d artefact(s)" % len(names)
    fs = resolve_fs(spec)
    formats = tuple(n.split(".")[-1] for n in names)
    tmp = os.path.join(out_dir, ".determinism_check")
    hashes, identical = {}, True
    try:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        export_mod.export_all(scene_obj, spec, fs, tmp, formats=formats)
        for n in names:
            h1 = export_mod.sha256_file(os.path.join(out_dir, n))
            p2 = os.path.join(tmp, n)
            h2 = export_mod.sha256_file(p2) if os.path.exists(p2) else None
            same = h1 == h2
            identical = identical and same
            hashes[n] = {"run1": h1[:16], "run2": (h2 or "MISSING")[:16], "identical": same}
    except Exception as exc:
        return "fail", ("re-export raised %s: %s (0/%d artefacts compared)"
                        % (type(exc).__name__, exc, len(names)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    claimed = ((export_report or {}).get("determinism") or {}).get("identical")
    detail = ("re-exported %d artefact(s) to %s; identical=%s; %s"
              % (len(names), ".determinism_check", identical,
                 "; ".join("%s run1=%s run2=%s" % (n, v["run1"], v["run2"]) for n, v in sorted(hashes.items()))))
    if claimed is not None:
        detail += "; export_report_claims_identical=%s" % claimed
    if not identical:
        bad = [n for n, v in hashes.items() if not v["identical"]]
        return "fail", detail + " | NON-DETERMINISTIC: %s" % bad
    return "pass", detail


# --------------------------------------------------------------------------- #
# gate H — export quality
# --------------------------------------------------------------------------- #
def gate_h(spec, scene_obj, export_report, out_dir, materials):
    export_mod = _soft_import("export")
    if export_mod is None or not hasattr(export_mod, "sniff_png"):
        return "fail", "export module (byte sniffers) unavailable -> PNG/PDF quality UNVERIFIABLE"
    canvas = canvas_of(scene_obj, spec)
    rep = export_report or {}
    dpi = rep.get("dpi") or canvas.get("dpi") or 300
    try:
        dpi = int(round(float(dpi)))
    except Exception:
        dpi = 300
    page = rep.get("page_mm") or [canvas["w_mm"], canvas["h_mm"]]
    # the page that was actually emitted must be the page the spec asked for
    spec_canvas = dict(scene.DEFAULT_CANVAS)
    spec_canvas.update({k: float(v) for k, v in (((spec or {}).get("meta") or {}).get("canvas") or {}).items()
                        if _num(v)})
    want_page = [spec_canvas["w_mm"], spec_canvas["h_mm"]]
    page_off = max(abs(float(page[0]) - want_page[0]), abs(float(page[1]) - want_page[1]))
    exp_px = [int(round(float(page[0]) / 25.4 * dpi)), int(round(float(page[1]) / 25.4 * dpi))]
    exp_box = [round(float(page[0]) * 72.0 / 25.4, 3), round(float(page[1]) * 72.0 / 25.4, 3)]

    problems, parts = [], []
    parts.append("page_mm=%s(spec asks %s, off %.2f mm)" % ([round(float(page[0]), 2), round(float(page[1]), 2)],
                                                           want_page, page_off))
    if page_off > 0.5:
        problems.append("emitted page %sx%s mm != spec canvas %sx%s mm (off %.2f mm)"
                        % (page[0], page[1], want_page[0], want_page[1], page_off))
    png_path = os.path.join(out_dir, "figure.png")
    if not os.path.exists(png_path):
        problems.append("figure.png missing")
        parts.append("png=missing")
    else:
        s = export_mod.sniff_png(png_path)
        mdpi = s.get("dpi")
        mdpi_eff = round(float(mdpi)) if mdpi is not None else None
        parts.append("png_px=%s(expected %s)" % (s.get("px"), exp_px))
        parts.append("png_dpi_meta=%s(need>=300)" % mdpi)
        parts.append("png_pHYs=%s" % s.get("has_phys"))
        if s.get("px") != exp_px:
            problems.append("PNG px %s != page/dpi expectation %s" % (s.get("px"), exp_px))
        if mdpi is None:
            problems.append("PNG has no resolution metadata (0 dpi recorded)")
        elif mdpi_eff < 300:
            problems.append("PNG dpi metadata %.4f (rounds to %d) < 300" % (float(mdpi), mdpi_eff))

    pdf_path = os.path.join(out_dir, "figure.pdf")
    if not os.path.exists(pdf_path):
        problems.append("figure.pdf missing")
        parts.append("pdf=missing")
    else:
        p = export_mod.sniff_pdf(pdf_path)
        mb = p.get("mediabox_pt")
        parts.append("pdf_pages=%s(need 1)" % p.get("pages"))
        parts.append("pdf_mediabox=%s(expected %s)pt" % (mb, exp_box))
        parts.append("pdf_font_programs=%s embedded=%s" % (p.get("font_programs"), p.get("fonts_embedded")))
        parts.append("pdf_text_ops=%s vector=%s" % (p.get("text_ops"), p.get("vector_text")))
        parts.append("pdf_image_objects=%s" % p.get("image_objects"))
        if p.get("pages") != 1:
            problems.append("PDF page count %s != 1" % p.get("pages"))
        if mb is None:
            problems.append("PDF has no MediaBox (0 measured)")
        elif abs(mb[0] - exp_box[0]) > 1.0 or abs(mb[1] - exp_box[1]) > 1.0:
            problems.append("PDF MediaBox %s != page %s pt" % (mb, exp_box))
        if not p.get("fonts_embedded"):
            problems.append("PDF embeds 0 font programs (no FontFile2/FontFile3)")
        if not p.get("vector_text"):
            problems.append("PDF content has 0 Tj/TJ text operators (text is not vector)")
    # cross-check every number export.py reported against what we just measured.
    # (The previous version compared rp["px"] to a re-cast of itself, which is
    # tautologically false, so a wholesale falsified report passed H, G and I.)
    rp = rep.get("png") or {}
    if rp.get("px") and os.path.exists(png_path):
        if [int(v) for v in rp["px"]] != list(s.get("px") or []):
            problems.append("export_report.png.px=%s != measured %s" % (rp.get("px"), s.get("px")))
    rd = rep.get("dpi")
    if rd is not None and abs(float(rd) - float(dpi)) > 1.0:
        problems.append("export_report.dpi=%s != scene dpi %s" % (rd, dpi))
    rpages = (rep.get("pdf") or {}).get("pages")
    if rpages is not None and os.path.exists(pdf_path) and rpages != p.get("pages"):
        problems.append("export_report.pdf.pages=%s != measured %s" % (rpages, p.get("pages")))
    rfe = (rep.get("pdf") or {}).get("fonts_embedded")
    if rfe is not None and os.path.exists(pdf_path) and bool(rfe) != bool(p.get("fonts_embedded")):
        problems.append("export_report.pdf.fonts_embedded=%s != measured %s"
                        % (rfe, p.get("fonts_embedded")))
    rvec = (rep.get("pdf") or {}).get("vector")
    if rvec is not None and os.path.exists(pdf_path) and bool(rvec) != bool(p.get("vector_text")):
        problems.append("export_report.pdf.vector=%s != measured %s" % (rvec, p.get("vector_text")))
    rpage = rep.get("page_mm")
    if rpage and (abs(float(rpage[0]) - float(page[0])) > 0.5
                  or abs(float(rpage[1]) - float(page[1])) > 0.5):
        problems.append("export_report.page_mm=%s != measured %s" % (rpage, page))
    parts.append("report_cross_checked=px,dpi,pages,fonts,vector,page_mm")
    detail = ", ".join(parts)
    if problems:
        return "fail", detail + " | " + "; ".join(problems)
    return "pass", detail


# --------------------------------------------------------------------------- #
# gate I — contract
# --------------------------------------------------------------------------- #
# An absolute filesystem path inside a delivered artefact.  Two classes, because
# their consequences differ:
#   AUTHOR_PATH  an author-machine profile path (a Windows drive rooted at the
#                per-user profile directory, or a POSIX per-user home).  Forbidden
#                outright by the workspace rules, so it downgrades gate I.
#   ABS_PATH     any other absolute path (a system font directory, a container
#                work root).  It makes the artefact machine-dependent, so it is
#                reported with its count but does not by itself change the verdict.
# A URL scheme is not a path: `http://` would otherwise match "p://" as a drive.
_AUTHOR_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]"
                             r"|/(?:Users|home)/[A-Za-z]")
_ABS_PATH_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/app/|/home/|/root/|/tmp/")


def _scan_abs_paths(out_dir):
    """Absolute paths inside the artefacts this run delivers.

    Gate G only compares figure.svg/png/pdf, so a directory-dependent field in
    export_report.json (which result.json then hashes) was invisible to it: the
    figures matched while result.json changed with the output directory.  This
    makes that class of defect measurable at gate-I time.
    """
    found = []
    for name in ("result.json", "export_report.json", "scene.json",
                 "figure_spec.resolved.json", "figure.svg"):
        path = os.path.join(out_dir, name)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        author = _AUTHOR_PATH_RE.findall(text)
        absall = _ABS_PATH_RE.findall(text)
        if author or absall:
            # Deliberately no path sample in the result: quoting the offending path
            # back into the report would copy the very thing being flagged into
            # result.json and validation_report.json, which are themselves delivered
            # artefacts.  The file name and counts are enough to locate it.
            found.append({"file": name, "author": len(author), "absolute": len(absall)})
    return found


def _nonempty(v):
    if v is None:
        return False
    if isinstance(v, (str, list, dict, tuple)):
        return len(v) > 0
    return True


def gate_i(spec, scene_obj, export_report, out_dir, materials):
    result_path = os.path.join(out_dir, "result.json")
    if not os.path.exists(result_path):
        return "fail", "result.json missing at %s (0 keys) -> contract UNVERIFIABLE" % result_path
    try:
        with open(result_path, "r", encoding="utf-8-sig") as fh:
            result = json.load(fh)
    except Exception as exc:
        return "fail", "result.json does not parse: %s" % exc
    case_id = result.get("case_id")
    contract = (materials or {}).get("output_contract")
    if not isinstance(contract, dict) or not contract:
        cj = (materials or {}).get("case_json_path")
        if cj and os.path.exists(cj):
            try:
                with open(cj, "r", encoding="utf-8-sig") as fh:
                    contract = (json.load(fh) or {}).get("output_contract")
            except Exception:
                contract = None
    keys = list(contract.keys()) if isinstance(contract, dict) else []
    abs_paths = _scan_abs_paths(out_dir)
    author_paths = [f for f in abs_paths if f["author"]]
    hard_empty, soft_empty = [], []
    for k in keys:
        v = result.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            hard_empty.append(k)
        elif isinstance(v, (list, dict, tuple)) and len(v) == 0:
            soft_empty.append(k)
    unfilled = hard_empty + soft_empty
    artifacts = result.get("artifacts") or {}
    missing_files, sha_bad, bytes_bad = [], [], []
    self_written, checked = [], 0
    export_mod = _soft_import("export")
    for name, rec in (artifacts.items() if isinstance(artifacts, dict) else []):
        if not isinstance(rec, dict):
            missing_files.append(name)
            continue
        p = rec.get("path") or name
        full = p if os.path.isabs(str(p)) else os.path.join(out_dir, str(p))
        if not os.path.exists(full):
            missing_files.append("%s->%s" % (name, p))
            continue
        base = os.path.basename(full)
        if base == "validation_report.json":
            # this very check run rewrites validation_report.json, so the hash
            # recorded by an earlier result.json cannot be compared to it
            self_written.append(base)
            continue
        checked += 1
        if rec.get("bytes") is not None and int(rec["bytes"]) != os.path.getsize(full):
            bytes_bad.append(name)
        if rec.get("sha256") and export_mod is not None and hasattr(export_mod, "sha256_file"):
            if export_mod.sha256_file(full) != rec["sha256"]:
                sha_bad.append(name)
    detail = ("result_keys=%d, case_id=%s, contract_keys=%d, hard_empty=%d, soft_empty=%d, artifacts=%d, "
              "sha_checked=%d, self_written_skipped=%d%s, missing_files=%d, sha_mismatch=%d, bytes_mismatch=%d, "
              "abs_path_hits=%d, author_path_hits=%d%s"
              % (len(result), repr(case_id)[:40], len(keys), len(hard_empty), len(soft_empty),
                 len(artifacts.keys()) if isinstance(artifacts, dict) else 0,
                 checked, len(self_written),
                 ("(" + ",".join(self_written) + ")") if self_written else "",
                 len(missing_files), len(sha_bad), len(bytes_bad),
                 sum(f["absolute"] for f in abs_paths),
                 sum(f["author"] for f in abs_paths),
                 (" (" + "; ".join("%s abs=%d author=%d"
                                   % (f["file"], f["absolute"], f["author"])
                                   for f in abs_paths[:3]) + ")") if abs_paths else ""))
    problems = []
    if author_paths:
        problems.append("%d author-machine absolute path(s) inside delivered artefact(s): %s"
                        % (sum(f["author"] for f in abs_paths),
                           "; ".join("%s (author=%d)" % (f["file"], f["author"])
                                     for f in author_paths[:3])))
    if not _nonempty(case_id):
        problems.append("case_id is empty")
    if hard_empty:
        problems.append("%d contract key(s) empty/missing: %s" % (len(hard_empty), hard_empty[:6]))
    if soft_empty:
        detail += " | declared-empty list/dict keys (not a pass): %s" % soft_empty[:6]
    if missing_files:
        problems.append("%d artifact path(s) do not exist: %s" % (len(missing_files), missing_files[:4]))
    if sha_bad:
        problems.append("%d artifact sha256 mismatch: %s" % (len(sha_bad), sha_bad[:4]))
    if bytes_bad:
        problems.append("%d artifact byte count mismatch: %s" % (len(bytes_bad), bytes_bad[:4]))
    if problems:
        return "fail", detail + " | " + "; ".join(problems)
    if not keys:
        return "warn", detail + " | 0 output_contract keys available -> contract coverage UNVERIFIABLE"
    if soft_empty:
        return "warn", detail
    return "pass", detail


# --------------------------------------------------------------------------- #
# gate J — topology & order (CONTRACT §4.1)
# --------------------------------------------------------------------------- #
def _panel_node_ids(panel):
    return {n.get("id") for n in (panel.get("nodes") or [])
            if isinstance(n, dict) and n.get("id")}


def _declared_numbers(*texts):
    out = set()
    for t in texts:
        if isinstance(t, (list, tuple, dict)):
            t = json.dumps(t, ensure_ascii=False)
        for m in re.finditer(r"(?<![0-9.])-?\d+(?:\.\d+)?(?![0-9])", str(t or "")):
            try:
                out.add(int(float(m.group(0))))
            except ValueError:
                pass
    return out


def declared_relations(spec):
    """Every ``(origin, from, to, kind)`` the case declares the figure must draw.

    Sources (CONTRACT §3.1/§3.3): ``meta.expected_relations``, a top-level
    ``expected_relations``, ``panels[].declared_edges`` and a top-level
    ``declared_edges``.  Endpoints may be node ids or node labels; a relation may
    be an object or an ``"A -> B"`` string.  Nothing here is required on an old
    spec, so a spec with none of these returns [].
    """
    out = []

    def norm(rel, origin):
        if isinstance(rel, str):
            m = re.match(r"^\s*(.+?)\s*(?:->|-->|\u2192|\u2013>)\s*(.+?)\s*$", rel)
            if not m:
                return None
            return (origin, m.group(1).strip(), m.group(2).strip(), None)
        if not isinstance(rel, dict):
            return None
        a = rel.get("from", rel.get("source", rel.get("subject")))
        b = rel.get("to", rel.get("target", rel.get("object")))
        if (a is None or b is None) and isinstance(rel.get("pair"), (list, tuple)) \
                and len(rel["pair"]) == 2:
            a, b = rel["pair"]
        k = rel.get("kind", rel.get("type", rel.get("relation")))
        if a is None or b is None:
            return None
        return (origin, a, b, k.strip() if isinstance(k, str) and k.strip() else None)

    meta = (spec or {}).get("meta") or {}
    for ri, rel in enumerate(meta.get("expected_relations") or []):
        r = norm(rel, "$.meta.expected_relations[%d]" % ri)
        if r:
            out.append(r)
    for ri, rel in enumerate((spec or {}).get("expected_relations") or []):
        r = norm(rel, "$.expected_relations[%d]" % ri)
        if r:
            out.append(r)
    for pi, panel in enumerate(spec_panels(spec)):
        for ri, rel in enumerate(panel.get("declared_edges") or []):
            r = norm(rel, "$.panels[%d](%s).declared_edges[%d]" % (pi, panel.get("id"), ri))
            if r:
                out.append(r)
    for ri, rel in enumerate((spec or {}).get("declared_edges") or []):
        r = norm(rel, "$.declared_edges[%d]" % ri)
        if r:
            out.append(r)
    return out


def gate_j(spec, scene_obj, export_report, out_dir, materials):
    """Topology and order: J901..J906 (CONTRACT §4.1)."""
    codes = {}          # code -> (status, message)
    problems = []       # every failure, in code order

    # ---- J901 sequence ids exist, are this panel's nodes, and are unique -----
    seq_checked = 0
    seq_bad = []
    for panel in spec_panels(spec):
        seq = panel.get("sequence")
        if not isinstance(seq, list):
            continue
        ids = _panel_node_ids(panel)
        seq_checked += len(seq)
        dup = sorted({x for x in seq if isinstance(x, str) and seq.count(x) > 1})
        unknown = [x for x in seq if not isinstance(x, str) or x not in ids]
        if dup:
            seq_bad.append("%s.sequence repeats %d id(s) %s" % (panel.get("id"), len(dup), dup[:4]))
        if unknown:
            seq_bad.append("%s.sequence has %d id(s) that are not nodes of this panel: %s"
                           % (panel.get("id"), len(unknown), unknown[:4]))
    if seq_bad:
        problems.extend(seq_bad)
        codes["J901"] = ("fail", "%d id(s) across %d sequence list(s): %s"
                         % (seq_checked, sum(1 for p in spec_panels(spec)
                                             if isinstance(p.get("sequence"), list)),
                            seq_bad[0]))
    elif seq_checked:
        codes["J901"] = ("pass", "%d sequence id(s) all resolve to panel nodes" % seq_checked)
    else:
        codes["J901"] = ("not_applicable", "0 panel declares a sequence")

    # ---- J902 step_no is 1..N contiguous (gaps must be declared) ------------
    #
    # A parallel branch legitimately shares a step number (CONTRACT §3.4: nodes in
    # one `branch` group run in parallel), so a repeated step_no is legal exactly
    # when every node carrying it is in the same non-empty branch group.  Two
    # different steps claiming the same number is still an ordering error.
    step_checked = 0
    parallel_repeats = 0
    step_bad = []
    for panel in spec_panels(spec):
        holders = {}
        for node in panel.get("nodes") or []:
            if isinstance(node, dict) and _num(node.get("step_no")) \
                    and float(node["step_no"]).is_integer() and node["step_no"] >= 1:
                holders.setdefault(int(node["step_no"]), []).append(node)
        if not holders:
            continue
        nums = sorted(holders)
        step_checked += sum(len(v) for v in holders.values())
        dup_bad = []
        for value, nodes in sorted(holders.items()):
            if len(nodes) < 2:
                continue
            groups = {str(n.get("branch") or "").strip() for n in nodes}
            if len(groups) == 1 and groups != {""}:
                parallel_repeats += 1
            else:
                dup_bad.append("step_no %d is used by %d nodes with branch groups %s"
                               % (value, len(nodes), sorted(groups) or ["<none>"]))
        missing = [i for i in range(1, max(nums) + 1) if i not in holders]
        declared = _declared_numbers(panel.get("phases"), panel.get("limitations"),
                                    spec.get("limitations"), (spec or {}).get("phases"))
        undeclared = [i for i in missing if i not in declared]
        if dup_bad:
            step_bad.append("%s: %s" % (panel.get("id"), "; ".join(dup_bad[:3])))
        if undeclared:
            step_bad.append("%s.step_no is not 1..%d contiguous: %s missing and not declared "
                            "in phases/limitations" % (panel.get("id"), max(nums), undeclared[:6]))
    if step_bad:
        problems.extend(step_bad)
        codes["J902"] = ("fail", "%d step_no value(s) checked, %d parallel repeat(s): %s"
                         % (step_checked, parallel_repeats, step_bad[0]))
    elif step_checked:
        codes["J902"] = ("pass", "%d step_no value(s) contiguous 1..N, %d legal parallel repeat(s)"
                         % (step_checked, parallel_repeats))
    else:
        codes["J902"] = ("not_applicable", "0 node declares step_no")

    # ---- J903 loop_to / branch group / terminal ----------------------------
    loop_checked = branch_checked = terminal_checked = 0
    topo_bad = []
    all_ids = set(node_by_id(spec))
    for panel in spec_panels(spec):
        ids = _panel_node_ids(panel)
        outdeg = {}
        for edge in panel.get("edges") or []:
            if isinstance(edge, dict):
                outdeg[edge.get("from")] = outdeg.get(edge.get("from"), 0) + 1
        groups = {}
        for node in panel.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            tgt = node.get("loop_to")
            if isinstance(tgt, str) and tgt:
                loop_checked += 1
                if tgt not in ids and tgt not in all_ids:
                    topo_bad.append("%s node %s loop_to %r is not a node"
                                    % (panel.get("id"), node.get("id"), tgt))
            br = node.get("branch")
            if isinstance(br, str) and br.strip():
                groups.setdefault(br.strip(), []).append(node.get("id"))
            if node.get("terminal") is True:
                terminal_checked += 1
                n_out = outdeg.get(node.get("id"), 0)
                if n_out:
                    topo_bad.append("%s terminal node %s has %d outgoing edge(s)"
                                    % (panel.get("id"), node.get("id"), n_out))
        for br, members in groups.items():
            branch_checked += 1
            if len(members) < 2:
                topo_bad.append("%s branch group %r has %d node(s) (needs >=2)"
                                % (panel.get("id"), br, len(members)))
    if topo_bad:
        problems.extend(topo_bad)
        codes["J903"] = ("fail", "loop_to=%d, branch_groups=%d, terminal=%d: %s"
                         % (loop_checked, branch_checked, terminal_checked, topo_bad[0]))
    elif loop_checked or branch_checked or terminal_checked:
        codes["J903"] = ("pass", "loop_to=%d, branch_groups=%d, terminal=%d all consistent"
                         % (loop_checked, branch_checked, terminal_checked))
    else:
        codes["J903"] = ("not_applicable", "0 loop_to/branch/terminal declaration")

    # ---- J904 phases[].depends_on: exist and acyclic (print the cycle) -------
    phases = []
    for panel in spec_panels(spec):
        for phase in panel.get("phases") or []:
            if isinstance(phase, dict):
                phases.append(phase)
    for phase in (spec or {}).get("phases") or []:
        if isinstance(phase, dict):
            phases.append(phase)
    dep_checked = 0
    dep_bad = []
    if phases:
        dep = {}
        for phase in phases:
            pid = phase.get("id")
            if isinstance(pid, str) and pid:
                dep.setdefault(pid, [])
                for d in phase.get("depends_on") or []:
                    if isinstance(d, str) and d and d not in dep[pid]:
                        dep[pid].append(d)
        for pid, deps in dep.items():
            for d in deps:
                dep_checked += 1
                if d not in dep:
                    dep_bad.append("phase %r depends_on %r which does not exist" % (pid, d))
        color = {k: 0 for k in dep}          # 0 white, 1 grey, 2 black
        stack, cycles = [], []

        def visit(u):
            color[u] = 1
            stack.append(u)
            for v in dep.get(u, []):
                if v not in color:
                    continue
                if color[v] == 1:
                    cycles.append(stack[stack.index(v):] + [v])
                    return True
                if color[v] == 0 and visit(v):
                    return True
            stack.pop()
            color[u] = 2
            return False

        for key in list(dep):
            if color.get(key) == 0 and visit(key):
                break
        if cycles:
            dep_bad.append("phase dependency cycle: %s" % " -> ".join(cycles[0]))
    if dep_bad:
        problems.extend(dep_bad)
        codes["J904"] = ("fail", "%d phase(s), %d dependency edge(s): %s"
                         % (len(phases), dep_checked, dep_bad[0]))
    elif phases:
        codes["J904"] = ("pass", "%d phase(s), %d dependency edge(s), 0 cycle, 0 dangling"
                         % (len(phases), dep_checked))
    else:
        codes["J904"] = ("not_applicable", "0 phase declared")

    # ---- J905 every rendered edge endpoint exists ---------------------------
    scene_edges = scene_edge_records(scene_obj)
    ep_checked = 0
    ep_bad = []
    for rec in scene_edges:
        panel_ids = None
        if isinstance(rec.get("panel"), str):
            for panel in spec_panels(spec):
                if panel.get("id") == rec["panel"]:
                    panel_ids = _panel_node_ids(panel)
                    break
        for side in ("from", "to"):
            ref = rec[side]
            if not isinstance(ref, str) or not ref:
                continue
            ep_checked += 1
            if panel_ids:
                if ref not in panel_ids:
                    ep_bad.append("scene edge %s->%s has %s=%r not in panel %s nodes"
                                  % (rec["from"], rec["to"], side, ref, rec["panel"]))
            elif ref not in all_ids:
                ep_bad.append("scene edge %s->%s has %s=%r which is not a node of the spec"
                              % (rec["from"], rec["to"], side, ref))
    if ep_bad:
        problems.extend(ep_bad)
        codes["J905"] = ("fail", "%d endpoint(s) checked over %d rendered edge(s): %s"
                         % (ep_checked, len(scene_edges), ep_bad[0]))
    elif ep_checked:
        codes["J905"] = ("pass", "%d endpoint(s) over %d rendered edge(s) all resolve"
                         % (ep_checked, len(scene_edges)))
    else:
        codes["J905"] = ("not_applicable", "0 rendered edge carries from/to")

    # ---- J906 declared (from,to,kind) must be drawn, and not reversed -------
    #
    # CONTRACT §4.1 says the requirement set is ``meta.expected_relations`` UNION
    # ``panels[].declared_edges``: the same relation declared in both places is
    # ONE requirement.  Autospec legitimately writes both (the meta list plus a
    # per-panel copy), so concatenating them and consuming rendered edges one by
    # one reported a fully drawn figure as "7 of 14 missing".  Deduplicate on
    # (from,to,kind) first, then match by existence.
    declared = declared_relations(spec)
    ids = set(node_by_id(spec))
    labels = label_index(spec)
    pool = {}
    for rec in scene_edges:
        if isinstance(rec["from"], str) and isinstance(rec["to"], str):
            key = (rec["from"], rec["to"], rec["kind"])
            pool[key] = pool.get(key, 0) + 1
    matched = 0
    reversed_list, missing, unresolved = [], [], []
    unique, seen = [], set()
    for origin, a_raw, b_raw, kind_raw in declared:
        a = resolve_endpoint(a_raw, ids, labels)
        b = resolve_endpoint(b_raw, ids, labels)
        if a is None or b is None:
            unresolved.append("%s: %r -> %r (endpoint is not a node id or label)"
                              % (origin, a_raw, b_raw))
            continue
        key = (a, b, kind_raw or None)
        if key in seen:
            continue
        seen.add(key)
        unique.append((origin, a, b, kind_raw or None))
    declared_keys = set()
    for origin, a, b, kind in unique:
        if kind:
            declared_keys.add((a, b, kind))
            if pool.get((a, b, kind), 0) > 0:
                matched += 1
            elif pool.get((b, a, kind), 0) > 0:
                reversed_list.append("%s: declared %s->%s(%s) but the scene draws %s->%s(%s)"
                                     % (origin, a, b, kind, b, a, kind))
            else:
                missing.append("%s: declared %s->%s(%s) is not drawn" % (origin, a, b, kind))
        else:
            if any(c > 0 and k[0] == a and k[1] == b for k, c in pool.items()):
                matched += 1
            elif any(c > 0 and k[0] == b and k[1] == a for k, c in pool.items()):
                reversed_list.append("%s: declared %s->%s (kind unspecified) but the scene draws "
                                     "the reverse" % (origin, a, b))
            else:
                missing.append("%s: declared %s->%s (kind unspecified) is not drawn" % (origin, a, b))
    undeclared = 0
    if declared_keys:
        undeclared = sum(1 for rec in scene_edges
                         if isinstance(rec["from"], str) and isinstance(rec["to"], str)
                         and (rec["from"], rec["to"], rec["kind"]) not in declared_keys)
    j906_problems = reversed_list + missing + unresolved
    j906_counts = ("declared=%d unique of %d, matched=%d, reversed=%d, missing=%d, unresolved=%d, "
                   "undeclared_rendered=%d, self_consistent=%s"
                   % (len(unique), len(declared), matched, len(reversed_list), len(missing),
                      len(unresolved), undeclared,
                      matched + len(reversed_list) + len(missing) == len(unique)))
    if j906_problems:
        problems.extend(j906_problems)
        listed = "; ".join(j906_problems[:8])
        if len(j906_problems) > 8:
            listed += "; (+%d more)" % (len(j906_problems) - 8)
        codes["J906"] = ("fail", j906_counts + ": " + listed)
    elif unique:
        codes["J906"] = ("pass", j906_counts)
    else:
        codes["J906"] = ("not_applicable", "0 declared relation (meta.expected_relations "
                         "and panels[].declared_edges both absent or empty)")

    return _combine_codes("J", codes, problems, extra="declared_unique=%d" % len(unique))


def _combine_codes(gate, codes, problems, extra=""):
    """Merge per-code verdicts into the module's (status, detail[, codes]) shape."""
    order = sorted(codes)
    statuses = [codes[k][0] for k in order]
    if "fail" in statuses:
        status = "fail"
    elif "warn" in statuses:
        status = "warn"
    else:
        status = "pass"
    parts = []
    for k in order:
        st, msg = codes[k]
        parts.append("%s=%s(%s)" % (k, st, msg))
    detail = "%s codes_failed=%d, codes_warn=%d, codes_na=%d%s"
    detail = detail % (gate, statuses.count("fail"), statuses.count("warn"),
                       statuses.count("not_applicable"),
                       (", " + extra) if extra else "")
    detail += " | " + "; ".join(parts)
    return {"status": status, "detail": detail, "codes": {k: codes[k][0] for k in order}}


# --------------------------------------------------------------------------- #
# gate K — apparatus semantics & legend consistency (CONTRACT §4.2)
# --------------------------------------------------------------------------- #
def gate_k(spec, scene_obj, export_report, out_dir, materials):
    """Apparatus semantics and legend consistency: K901..K905 (CONTRACT §4.2)."""
    codes = {}
    problems = []
    panels = spec_panels(spec)

    # ---- K901 role=apparatus nodes carry a valid part ----------------------
    app_panels = [p for p in panels if str(p.get("role") or "") == "apparatus"]
    part_checked, part_bad = 0, []
    for panel in app_panels:
        for node in panel.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            part = node.get("part")
            if not isinstance(part, str) or not part.strip():
                part_bad.append("%s.%s has no part" % (panel.get("id"), node.get("id")))
            elif part.strip() not in ALL_PARTS:
                part_bad.append("%s.%s part %r is not a legal part"
                                % (panel.get("id"), node.get("id"), part))
            else:
                part_checked += 1
    if not app_panels:
        codes["K901"] = ("not_applicable", "0 panel with role=apparatus")
    elif part_bad:
        problems.extend(part_bad)
        codes["K901"] = ("fail", "%d/%d apparatus node(s) with a legal part: %s"
                         % (part_checked, part_checked + len(part_bad), part_bad[0]))
    else:
        codes["K901"] = ("pass", "%d apparatus node(s) all carry a legal part" % part_checked)

    # ---- K902 edge.ports exist on the endpoint nodes ------------------------
    by_id = node_by_id(spec)
    port_checked, port_bad = 0, []
    for label, edge in iter_edges(spec):
        refs = edge.get("ports")
        if not isinstance(refs, (list, tuple)) or len(refs) < 2:
            continue
        for side, needed in (("from", refs[0]), ("to", refs[1])):
            node = by_id.get(edge.get(side))
            ids = [p.get("id") for p in (node or {}).get("ports") or [] if isinstance(p, dict)]
            port_checked += 1
            if needed not in ids:
                port_bad.append("%s edge %s %s-port %r not in node %s ports %s"
                                % (label, edge.get("id"), side, needed,
                                   edge.get(side), ids[:6]))
    if port_bad:
        problems.extend(port_bad)
        codes["K902"] = ("fail", "%d port reference(s) checked: %s" % (port_checked, port_bad[0]))
    elif port_checked:
        codes["K902"] = ("pass", "%d edge port reference(s) all declared on their node" % port_checked)
    else:
        codes["K902"] = ("not_applicable", "0 edge declares ports")

    # ---- K903 merge in-degree / branch out-degree / waste target ------------
    merge_checked = branch_edge_checked = waste_checked = 0
    merge_bad, waste_bad, waste_unverified = [], [], []
    for panel in panels:
        indeg, outdeg = {}, {}
        for edge in panel.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            outdeg[edge.get("from")] = outdeg.get(edge.get("from"), 0) + 1
            indeg[edge.get("to")] = indeg.get(edge.get("to"), 0) + 1
        for edge in panel.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            kind = edge.get("kind")
            if kind == "merge":
                merge_checked += 1
                n_in = indeg.get(edge.get("to"), 0)
                if n_in < 2:
                    merge_bad.append("%s merge %s->%s but in-degree of %s is %d (needs >=2)"
                                     % (panel.get("id"), edge.get("from"), edge.get("to"),
                                        edge.get("to"), n_in))
            elif kind == "branch":
                branch_edge_checked += 1
                n_out = outdeg.get(edge.get("from"), 0)
                if n_out < 2:
                    merge_bad.append("%s branch %s->%s but out-degree of %s is %d (needs >=2)"
                                     % (panel.get("id"), edge.get("from"), edge.get("to"),
                                        edge.get("from"), n_out))
            elif kind == "waste":
                waste_checked += 1
                target = by_id.get(edge.get("to")) or {}
                tpart = str(target.get("part") or "").strip()
                if tpart != "waste":
                    if tpart:
                        # The target *is typed* and the type contradicts the edge:
                        # a waste outlet drawn into a reactor is a wrong connection,
                        # a mechanically decidable fact -- hard fail, not a warning.
                        waste_bad.append("%s waste edge %s->%s but target %s is part %r"
                                         % (panel.get("id"), edge.get("from"), edge.get("to"),
                                            edge.get("to"), tpart))
                    else:
                        # The target declares no part at all: nothing contradicts the
                        # edge, the figure just does not say.  That is a coverage gap
                        # (UNVERIFIABLE), so it must not be reported as a failure.
                        waste_unverified.append("%s waste edge %s->%s; target %s declares no part"
                                                % (panel.get("id"), edge.get("from"),
                                                   edge.get("to"), edge.get("to")))
    if merge_bad or waste_bad:
        problems.extend(merge_bad + waste_bad)
        first = (merge_bad + waste_bad)[0]
        codes["K903"] = ("fail", "merge=%d, branch=%d, waste=%d, waste_target_wrong=%d: %s"
                         % (merge_checked, branch_edge_checked, waste_checked,
                            len(waste_bad), first))
    elif waste_unverified:
        codes["K903"] = ("warn", "merge=%d, branch=%d ok; %d waste edge(s) whose target "
                         "declares no part (UNVERIFIABLE): %s"
                         % (merge_checked, branch_edge_checked, len(waste_unverified),
                            waste_unverified[0]))
    elif merge_checked or branch_edge_checked or waste_checked:
        codes["K903"] = ("pass", "merge=%d, branch=%d, waste=%d all consistent"
                         % (merge_checked, branch_edge_checked, waste_checked))
    else:
        codes["K903"] = ("not_applicable", "0 branch/merge/waste edge")

    # ---- K904 legend declaration vs what the figure actually paints ---------
    declared_styles, declared_parts = {}, set()
    for panel in panels:
        for leg in iter_legends(panel):
            for it in leg.get("items") or []:
                if not isinstance(it, dict):
                    continue
                kind = it.get("kind")
                if isinstance(kind, str) and kind.strip():
                    kind = kind.strip()
                    ls = it.get("linestyle")
                    ls = ls.strip().lower() if isinstance(ls, str) and ls.strip() \
                        else LINESTYLE_BY_KIND.get(kind, "solid")
                    col = _canon_colour(it.get("color")) or _canon_colour(it.get("colour"))
                    key = (kind, ls, col)
                    declared_styles[key] = declared_styles.get(key, 0) + 1
                part = it.get("part")
                if isinstance(part, str) and part.strip():
                    declared_parts.add(part.strip())
    rendered_styles = {}
    if declared_styles:
        declared_kinds = {k for (k, _, _) in declared_styles}
        distinct = set()
        for rec in scene_edge_records(scene_obj):
            if rec["kind"] in declared_kinds:
                distinct.add((rec["kind"], rec["linestyle"], rec["color"]))
        for key in distinct:
            rendered_styles[key] = 1
    part_missing = []
    if declared_parts:
        rendered_parts = {n.get("part") for _, n in spec_nodes(spec)
                          if isinstance(n.get("part"), str) and n.get("part")}
        for p in (scene_obj or {}).get("primitives") or []:
            if isinstance(p, dict) and isinstance(p.get("part"), str) and p.get("part"):
                rendered_parts.add(p["part"])
        part_missing = sorted(x for x in declared_parts if x not in rendered_parts)
    k904_bad = []
    for key, n in sorted(declared_styles.items()):
        if rendered_styles.get(key, 0) < n:
            k904_bad.append("legend declares %s x%d but the scene renders it x%d"
                            % (key, n, rendered_styles.get(key, 0)))
    for key in sorted(rendered_styles):
        if key not in declared_styles:
            k904_bad.append("the scene renders %s which no legend item declares" % (key,))
    for part in part_missing:
        k904_bad.append("legend declares part %r but no node in the figure is of that part" % part)
    if k904_bad:
        problems.extend(k904_bad)
        listed = "; ".join(k904_bad[:8])
        if len(k904_bad) > 8:
            listed += "; (+%d more)" % (len(k904_bad) - 8)
        codes["K904"] = ("fail", "legend_entries_with_kind=%d, rendered_styles=%d, declared_parts=%d, "
                         "missing_parts=%d, mismatches=%d: %s"
                         % (sum(declared_styles.values()), len(rendered_styles),
                            len(declared_parts), len(part_missing), len(k904_bad), listed))
    elif declared_styles or declared_parts:
        codes["K904"] = ("pass", "legend_entries_with_kind=%d == rendered_styles=%d, "
                         "declared_parts=%d all present"
                         % (sum(declared_styles.values()), len(rendered_styles), len(declared_parts)))
    else:
        codes["K904"] = ("not_applicable", "0 legend item declares kind/part")

    # ---- K905 self-loops are only loop/feedback -----------------------------
    loops_checked, loop_bad = 0, []
    for label, edge in iter_edges(spec):
        if edge.get("from") != edge.get("to") or not edge.get("from"):
            continue
        loops_checked += 1
        if (edge.get("kind") or "") not in SELF_LOOP_KINDS:
            loop_bad.append("%s self-loop %s->%s has kind %r (only %s allowed)"
                            % (label, edge.get("from"), edge.get("to"),
                               edge.get("kind"), list(SELF_LOOP_KINDS)))
    if loop_bad:
        problems.extend(loop_bad)
        codes["K905"] = ("fail", "%d self-loop(s) checked: %s" % (loops_checked, loop_bad[0]))
    elif loops_checked:
        codes["K905"] = ("pass", "%d self-loop(s) all kind loop/feedback" % loops_checked)
    else:
        codes["K905"] = ("not_applicable", "0 self-loop")

    return _combine_codes("K", codes, problems)


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
GATES = [
    ("A", "canvas/margins", gate_a),
    ("B", "typography", gate_b),
    ("C", "color-accessibility", gate_c),
    ("D", "encoding-fidelity", gate_d),
    ("E", "provenance", gate_e),
    ("F", "editability", gate_f),
    ("G", "determinism", gate_g),
    ("H", "export-quality", gate_h),
    ("I", "contract", gate_i),
    ("J", "topology-order", gate_j),
    ("K", "apparatus-legend", gate_k),
]


def run_checks(spec, scene_obj, export_report, out_dir, materials):
    """Run gates A–K.  Returns {"checks": [...], "failed": [...], "warned": [...]}.

    Each check entry is ``{"id","name","status","detail"}``; a gate that reports
    per-rule verdicts (J, K) also publishes ``codes`` = {code: verdict}, so the
    audit trail names every rule, not just the gate letter.
    """
    out_dir = os.path.abspath(out_dir)
    checks, failed, warned = [], [], []
    for gid, gname, fn in GATES:
        codes = None
        try:
            res = fn(spec, scene_obj, export_report, out_dir, materials)
            if isinstance(res, dict):
                status, detail, codes = res.get("status"), res.get("detail"), res.get("codes")
            else:
                status, detail = res
        except Exception as exc:  # a crashing gate is a failure, never a pass
            status, detail = "fail", "check raised %s: %s" % (type(exc).__name__, exc)
        if status not in ("pass", "fail", "warn"):
            status = "fail"
            detail = "invalid status from checker; " + str(detail)
        entry = {"id": gid, "name": gname, "status": status, "detail": str(detail)}
        if isinstance(codes, dict) and codes:
            entry["codes"] = codes
        checks.append(entry)
        if status == "fail":
            failed.append(gid)
        elif status == "warn":
            warned.append(gid)
    return {"checks": checks, "failed": failed, "warned": warned}
