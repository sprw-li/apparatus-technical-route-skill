#!/usr/bin/env python3
"""layout.py — deterministic spec -> scene layout engine (contract §4, §6).

    layout(spec, fs) -> {"canvas", "primitives", "panels", "warnings", "meta"}

Everything is in MILLIMETRES, origin top-left, +y down (contract §2).  Nothing
in this module reads the clock, calls random(), or iterates a set for output
order, so the same spec always produces the same scene and the same bytes
downstream.

Layout strategy
---------------
1. Bands are measured top-down: figure title, then the panel grid, then the
   caption/conclusion strip, all measured with real glyph advances.
2. Each panel is *measured* before it is drawn: for every candidate grid
   (node columns x chart placement) the required height is computed from the
   wrapped label/sublabel lines.  The cheapest feasible arrangement wins.
3. Row heights come from those measurements, so a panel never has to scale its
   rows down — the failure mode that used to drop whole labels.  If the total
   still does not fit, the whole type scale steps down (to the contract floors
   of 11 / 8 / 7 pt) and the panels are re-measured; only when the floors are
   reached is a warning emitted, and it reports the real numbers.

Required text is never dropped: `W_TEXT_FLOOR` means "did not fit at the floor"
and `W_TEXT_TRUNCATED` is reserved for the typographic shortfall it names.

See ``SCENE.md`` for the exact field list every primitive carries.
"""
from __future__ import annotations
import sys as _sys
_sys.dont_write_bytecode = True

import math

import measure
import scene

VERSION = "1.1"
GENERATOR = "apparatus-technical-route/layout.py %s" % VERSION

# --------------------------------------------------------------------------- #
# geometry constants (mm)
# --------------------------------------------------------------------------- #
GUTTER_MM = 3.0
PANEL_PAD_MM = 1.8
PANEL_HEADER_MIN_MM = 5.6
NODE_PAD_Y = 1.2
NODE_GAP_X = 1.6
NODE_GAP_Y = 1.4
MIN_NODE_W_MM = 20.0
MIN_NODE_H_MM = 6.0
EDGE_W_MM = 0.45
EDGE_HEAD_MM = 1.6
LEGEND_ROW_MM = 3.4
LEGEND_W_MM = 30.0
COLORBAR_W_MM = 15.0
COLORBAR_V_MIN_W = 34.0
TICK_LEN_MM = 1.0
MIN_DIAGRAM_MM = 12.0
CHART_MIN_W_MM = 44.0
CHART_MIN_H_MM = 30.0
CHART_PREF_H_MM = 40.0
BAND_GAP_MM = 1.6
COLORBAR_V_MIN_H = 26.0
COLORBAR_H_H = 11.0
LEGEND_COL_W_MM = 24.0

NEUTRAL_FILL = "#E8E8E8"
INK = "#111111"
MUTED = "#444444"
FRAME = "#333333"
GRID = "#DDDDDD"
PAGE_BG = "#FFFFFF"

# Base type sizes (pt); every one has a contract floor below.
BASE_SIZES = {
    "title": 13.0,
    "subtitle": 8.5,
    "caption": 7.5,
    "panel_title": 9.5,
    "panel_role": 7.0,
    "node_label": 8.0,
    "node_sub": 7.0,
    "edge_label": 7.0,
    "axis": 7.0,
    "chart_title": 7.5,
    "legend": 7.0,
    "colorbar": 7.0,
}
FLOOR_SIZES = {
    "title": scene.MIN_MAIN_TITLE_PT,
    "subtitle": scene.MIN_BODY_PT,
    "caption": scene.MIN_BODY_PT,
    "panel_title": scene.MIN_PANEL_TITLE_PT,
    "panel_role": scene.MIN_BODY_PT,
    "node_label": scene.MIN_BODY_PT,
    "node_sub": scene.MIN_BODY_PT,
    "edge_label": scene.MIN_BODY_PT,
    "axis": scene.MIN_BODY_PT,
    "chart_title": scene.MIN_BODY_PT,
    "legend": scene.MIN_BODY_PT,
    "colorbar": scene.MIN_BODY_PT,
}

# --------------------------------------------------------------------------- #
# v1.1 vocabulary: apparatus parts and typed connector visuals
#
# ADDITIVE ONLY (contract §1.1).  Every read goes through a helper that falls
# back to these literals, so a frozen-v1 spec (no ``part``, no new ``kind``, no
# ``sequence``) takes exactly the old code path.  ``scene.py`` owns the
# authoritative tables once engine-schema publishes them; when they exist they
# win, so the renderer and gate K904 can never drift apart.
# --------------------------------------------------------------------------- #
PART_TYPES_FALLBACK = (
    "vessel", "tank", "reactor", "column", "pump", "valve", "sensor", "probe",
    "flask", "mixer", "separator", "reservoir", "condenser", "heater", "cooler",
    "junction", "sample", "reagent", "waste", "instrument", "generic",
)

LINESTYLES = ("solid", "dashed", "dotted", "dashdot")
ARROW_MODES = ("none", "end", "both")

LINESTYLE_DASH = {
    "solid": [],
    "dashed": [2.0, 1.2],
    "dotted": [0.5, 1.1],
    "dashdot": [2.4, 1.0, 0.5, 1.0],
}

# kind -> {linestyle, head, colour?, width?, dash?}
# head: solid (filled triangle) | open (hollow triangle) | dot | tbar | none
EDGE_VISUALS_FALLBACK = {
    # frozen v1 kinds: byte-identical to the 0062 base renderer
    "activation": {"linestyle": "solid", "head": "solid"},
    "inhibition": {"linestyle": "solid", "head": "tbar"},
    "flow": {"linestyle": "dashed", "head": "solid", "dash": [2.0, 1.2]},
    "spatial": {"linestyle": "dotted", "head": "solid", "dash": [0.6, 1.0]},
    "feedback": {"linestyle": "solid", "head": "solid", "curve": True},
    "translocation": {"linestyle": "dashdot", "head": "solid",
                      "dash": [3.0, 1.0, 0.8, 1.0]},
    # v1.1 kinds (contract §3.5)
    "material": {"linestyle": "solid", "head": "solid"},
    "fluid": {"linestyle": "solid", "head": "solid"},
    "gas": {"linestyle": "solid", "head": "open"},
    "energy": {"linestyle": "dashed", "head": "solid"},
    "heat": {"linestyle": "dashed", "head": "solid"},
    "signal": {"linestyle": "dotted", "head": "dot"},
    "control": {"linestyle": "dashdot", "head": "solid"},
    "assembly": {"linestyle": "solid", "head": "none", "width": 0.3},
    "sequence": {"linestyle": "solid", "head": "solid"},
    "branch": {"linestyle": "solid", "head": "solid"},
    "merge": {"linestyle": "solid", "head": "solid"},
    "loop": {"linestyle": "solid", "head": "solid", "return": True},
    "waste": {"linestyle": "dashed", "head": "solid", "color": "#808080"},
    "__default__": {"linestyle": "solid", "head": "solid"},
}

# One colour for every connector kind except a grey waste line: a P&ID-style
# figure distinguishes connectors by *line style and head shape*, and keeping
# the palette flat means a legend full of kinds can never trip gate C's
# categorical CVD/greyscale floors (measured: only #333333 vs #808080, dL*=34).
EDGE_NEUTRAL = FRAME
EDGE_WASTE_COLOR = "#808080"

# free lanes reserved for a `loop_to` return line, in mm
LOOP_LANE_MM = 2.6
EDGE_TIP_GAP_MM = 0.35

# apparatus glyph budget inside a node cell
PART_GLYPH_FRAC = 0.32
PART_GLYPH_MAX_MM = 8.6
PART_GLYPH_GAP_MM = 1.2
PART_GLYPH_MIN_H_MM = 4.2

LAYER_ORDER = ["frame", "panel", "chart", "entity", "relation",
               "legend", "colorbar", "annotation"]


SPACING_LEVELS = [
    {"gap": 1.6, "node_gap_y": 1.4, "node_pad_y": 1.2, "leading": 1.22,
     "label_leading": 1.18, "legend_row": 3.4, "panel_pad": 1.8, "hdr_pad": 1.0},
    {"gap": 1.2, "node_gap_y": 1.0, "node_pad_y": 0.9, "leading": 1.16,
     "label_leading": 1.12, "legend_row": 3.0, "panel_pad": 1.4, "hdr_pad": 0.8},
    {"gap": 0.9, "node_gap_y": 0.7, "node_pad_y": 0.6, "leading": 1.10,
     "label_leading": 1.06, "legend_row": 2.8, "panel_pad": 1.1, "hdr_pad": 0.6},
]


def scaled_sizes(scale, level=0):
    """Type sizes (pt) for a scale factor, plus the spacing step for that level."""
    out = {}
    for key, base in BASE_SIZES.items():
        out[key] = max(FLOOR_SIZES[key], round(base * scale, 2))
    out["__spacing__"] = dict(SPACING_LEVELS[max(0, min(level, len(SPACING_LEVELS) - 1))])
    out["__scale__"] = round(float(scale), 4)
    return out


def sp_of(sizes):
    return sizes.get("__spacing__") or SPACING_LEVELS[0]


# --------------------------------------------------------------------------- #
# small deterministic helpers
# --------------------------------------------------------------------------- #
def _r(v, nd=4):
    out = round(float(v), nd)
    return 0.0 if out == 0.0 else out


def _bbox(x, y, w, h, stroke=0.0):
    pad = abs(float(stroke)) / 2.0 if stroke else 0.0
    return {"x": _r(float(x) - pad), "y": _r(float(y) - pad),
            "w": _r(max(0.0, float(w)) + 2 * pad),
            "h": _r(max(0.0, float(h)) + 2 * pad)}


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _hex_rgb(color):
    c = (color or "#000000").strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) == 6:
        try:
            return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        except ValueError:
            pass
    return 0, 0, 0


def _rgb_hex(rgb):
    return "#%02X%02X%02X" % tuple(int(_clamp(round(v), 0, 255)) for v in rgb)


def cmap_color(cmap_id, t):
    """Sequential colour for t in [0,1] from scene.CMAPS (linear RGB stops)."""
    stops = scene.CMAPS.get(cmap_id) or scene.CMAPS["grey"]
    t = _clamp(float(t), 0.0, 1.0)
    n = len(stops) - 1
    if n <= 0:
        return stops[0]
    pos = t * n
    i = int(math.floor(pos))
    if i >= n:
        i, frac = n - 1, 1.0
    else:
        frac = pos - i
    a, b = _hex_rgb(stops[i]), _hex_rgb(stops[i + 1])
    return _rgb_hex([a[k] + (b[k] - a[k]) * frac for k in range(3)])


def _channel_lum(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(color):
    r, g, b = _hex_rgb(color)
    return 0.2126 * _channel_lum(r) + 0.7152 * _channel_lum(g) + 0.0722 * _channel_lum(b)


def contrast_ratio(a, b):
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def ink_on(fill, prefer_dark=INK, prefer_light="#FFFFFF", minimum=4.5):
    """Text colour with the best measured WCAG contrast against `fill`."""
    dark = contrast_ratio(prefer_dark, fill)
    light = contrast_ratio(prefer_light, fill)
    best = prefer_dark if dark >= light else prefer_light
    if max(dark, light) >= minimum:
        return best
    return prefer_dark if dark >= light else prefer_light


readable_ink = ink_on


def fmt_num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f) and abs(f) < 1e6:
        return "%d" % int(f)
    a = abs(f)
    if a >= 100:
        s = "%.0f" % f
    elif a >= 10:
        s = "%.1f" % f
    elif a >= 1:
        s = "%.2f" % f
    else:
        s = "%.3f" % f
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


# --------------------------------------------------------------------------- #
# v1.1 vocabulary helpers (all tolerant: missing field -> frozen-v1 behaviour)
# --------------------------------------------------------------------------- #
# (key, w, h, bbox, stroke, dash) — head glyphs must not enter the node (A)
HEAD_KINDS = ("solid", "hollow", "triangle", "bar", "dot", "none")
HEAD_ALIASES = {"open": "hollow", "tbar": "bar", "filled": "solid", "": "solid"}


def _norm_head(head):
    head = HEAD_ALIASES.get(head, head)
    return head if head in HEAD_KINDS else "solid"


def panel_roles():
    """Ordered panel roles, v1.1 domain first when scene.py publishes it."""
    roles = getattr(scene, "PANEL_ROLES_V11", None)
    if isinstance(roles, (list, tuple)) and roles:
        return list(roles)
    return list(scene.PANEL_ROLES)


def part_types():
    types = getattr(scene, "PART_TYPES", None)
    if isinstance(types, (list, tuple)) and types:
        return tuple(types)
    return PART_TYPES_FALLBACK


def node_part(node):
    """The apparatus part of a node, or None.  Unknown values are ignored."""
    val = node.get("part") if isinstance(node, dict) else None
    if not isinstance(val, str):
        return None
    val = val.strip().lower()
    return val if val in part_types() else None


def _edge_visuals():
    table = getattr(scene, "EDGE_VISUALS", None)
    if not isinstance(table, dict) or not table:
        return EDGE_VISUALS_FALLBACK
    merged = dict(EDGE_VISUALS_FALLBACK)
    for key, val in table.items():
        if isinstance(val, dict):
            base = dict(merged.get(key) or {})
            base.update({k: v for k, v in val.items() if v is not None})
            merged[key] = base
    return merged


def resolve_edge_style(edge, kind=None, declared=None):
    """Single source of truth for a connector's visual (renderer *and* legend).

    Precedence: the spec's own edge fields, then a `declared` override (a legend
    item that names this kind), then the kind table from scene.py / the literals
    above.  `heads` lists the head kinds to draw as ("end"|"start", head).
    Because both the drawing and the legend call this function, the legend's
    (kind, linestyle, colour) key cannot drift from what is drawn (gate K904).
    """
    edge = edge if isinstance(edge, dict) else {}
    kd = kind or edge.get("kind") or "flow"
    table = _edge_visuals()
    base = dict(table.get(kd) or table.get("__default__") or {})
    declared_ls = None
    if isinstance(declared, dict):
        for key, val in declared.items():
            if val is not None:
                base[key] = val
        if declared.get("linestyle") in LINESTYLES:
            declared_ls = declared["linestyle"]
    linestyle = edge.get("linestyle")
    if linestyle not in LINESTYLES:
        linestyle = base.get("linestyle") if base.get("linestyle") in LINESTYLES else "solid"
    if declared_ls in LINESTYLES:
        dash = list(LINESTYLE_DASH.get(linestyle, []))
    elif linestyle == base.get("linestyle") and base.get("dash"):
        dash = list(base["dash"])
    else:
        dash = list(LINESTYLE_DASH.get(linestyle, []))
    head = _norm_head(base.get("head"))
    arrow = edge.get("arrow")
    if arrow not in ARROW_MODES:
        arrow = base.get("arrow") if base.get("arrow") in ARROW_MODES else "end"
    if base.get("head") == "none" and arrow in ("end", "both") and "arrow" in edge:
        # an explicit `arrow` beats a kind whose default is "no head" (assembly)
        head = "solid"
    elif base.get("head") == "none" and "arrow" not in edge:
        arrow = "none"
    color = edge.get("color")
    if not isinstance(color, str) or not color.startswith("#"):
        color = base.get("color") or (EDGE_WASTE_COLOR if kd == "waste" else EDGE_NEUTRAL)
    width = edge.get("width")
    if not isinstance(width, (int, float)) or isinstance(width, bool) or width <= 0:
        width = base.get("width") or EDGE_W_MM
    heads = []
    if head != "none" and arrow in ("end", "both"):
        heads.append(("end", head))
    if head != "none" and arrow == "both":
        heads.append(("start", head))
    return {"kind": kd, "linestyle": linestyle, "dash": dash, "head": head,
            "arrow": arrow, "heads": heads, "color": color,
            "width": float(width),
            "curve": bool(base.get("curve")) or kd == "feedback",
            "return": bool(base.get("return")) or edge.get("loop_to") is not None}


def legend_kind_styles(panel):
    """kind -> declared visual from the panel legend items that name a kind.

    Feeding this back into the edge resolver makes "the legend is the key"
    literally true: a declared (kind, linestyle, colour) is what gets drawn, so
    gate K904's multiset comparison is satisfied by construction.
    """
    out = {}
    legend = (panel or {}).get("legend")
    if not isinstance(legend, dict):
        return out
    for it in (legend.get("items") or []):
        if not isinstance(it, dict):
            continue
        kd = it.get("kind")
        if not isinstance(kd, str) or not kd:
            continue
        entry = out.setdefault(kd, {})
        for key in ("color", "linestyle", "arrow", "head"):
            if isinstance(it.get(key), str) and key not in entry:
                entry[key] = it[key]
    return out


def part_glyph_w(box_w):
    """Width the apparatus glyph occupies on the left of a node cell."""
    return max(PART_GLYPH_MIN_H_MM,
               min(PART_GLYPH_MAX_MM, float(box_w) * PART_GLYPH_FRAC))


def _node_left_extra(node, box_w):
    """Horizontal space left of the label: part glyph, else shape inset."""
    if node_part(node) is None:
        return _inset_x(_shape_of(node), box_w)
    return part_glyph_w(box_w) + PART_GLYPH_GAP_MM


# --------------------------------------------------------------------------- #
# builder
# --------------------------------------------------------------------------- #
class _Builder(object):
    def __init__(self, spec, fs, sizes):
        self.spec = spec
        self.fs = fs
        self.sizes = sizes
        self.seq = 0
        self.primitives = []
        self.warnings = []
        self.palette = scene.resolve_palette(spec)
        self.evidence = {}
        for ev in (spec.get("evidence") or []):
            if isinstance(ev, dict) and isinstance(ev.get("id"), str):
                self.evidence[ev["id"]] = ev
        self._uid_seen = set()
        # A legend item that names an edge kind is the *key* for that kind:
        # resolve it once, spec-wide, so every panel draws that kind exactly the
        # way the legend declares it (gate K904 aggregates over the whole scene).
        self.edge_declared = {}
        for panel in (spec.get("panels") or []):
            if not isinstance(panel, dict):
                continue
            for kind, entry in sorted(legend_kind_styles(panel).items()):
                self.edge_declared.setdefault(kind, entry)

    # -- ids & bookkeeping -------------------------------------------------- #
    def uid(self, prefix, key):
        self.seq += 1
        seed = "%d|%s" % (self.seq, key)
        out = scene.stable_id(prefix, seed)
        guard = 0
        while out in self._uid_seen:
            guard += 1
            out = scene.stable_id(prefix, seed + "|%d" % guard)
        self._uid_seen.add(out)
        return out

    def warn(self, code, message, panel=None):
        self.warnings.append({"code": code, "severity": "warn",
                              "message": message, "panel": panel})

    def src_of(self, ev_id):
        ev = self.evidence.get(ev_id)
        if not isinstance(ev, dict):
            return None
        src = ev.get("source")
        if not isinstance(src, dict):
            return None
        return {"file": src.get("file"), "locator": src.get("locator"),
                "quote": src.get("quote")}

    def evidence_for(self, obj):
        """Accept `source` (id) or `sources` (list of ids) from a spec node."""
        ids = []
        if isinstance(obj, dict):
            if isinstance(obj.get("source"), str) and obj["source"]:
                ids.append(obj["source"])
            for key in ("sources", "evidence"):
                val = obj.get(key)
                if isinstance(val, list):
                    ids.extend([v for v in val if isinstance(v, str) and v])
                elif isinstance(val, str) and val:
                    ids.append(val)
        seen, out = set(), []
        for i in ids:
            if i not in seen and i in self.evidence:
                seen.add(i)
                out.append(i)
        return out

    # -- primitive factory -------------------------------------------------- #
    def add(self, layer, ptype, bbox, element, panel=None, evidence=None,
            style=None, **extra):
        prefix = {"frame": "bg", "panel": "pn", "chart": "ch", "entity": "en",
                  "relation": "rl", "legend": "lg", "colorbar": "cb",
                  "annotation": "an"}.get(layer, "el")
        ev = None
        if isinstance(evidence, str):
            ev = evidence
        elif isinstance(evidence, (list, tuple)) and evidence:
            ev = evidence[0]
        prim = {
            "id": self.uid(prefix, "%s|%s|%s|%s" % (layer, element, panel or "", bbox)),
            "layer": layer,
            "type": ptype,
            "bbox": bbox,
            "element": element,
            "style": dict(style or {}),
            "panel": panel,
            "evidence": ev,
            "evidence_ids": list(evidence) if isinstance(evidence, (list, tuple))
            else ([ev] if ev else []),
            "source": self.src_of(ev) if ev else None,
        }
        prim.update(extra)
        self.primitives.append(prim)
        return prim

    # -- text --------------------------------------------------------------- #
    def text(self, layer, element, value, x, y, w, h, size_key, *,
             bold=False, color=INK, align="left", valign="top", leading=1.25,
             panel=None, evidence=None, background=None, max_lines=None,
             rotate=None, allow_truncate=True):
        """Emit a text primitive whose box already fits the wrapped lines.

        The box height is *recomputed* from the wrapped lines (`n_lines *
        line_height`) and may grow downwards inside the caller's allowance;
        lines are only ever dropped when the caller explicitly allows it, and
        that always raises a warning.
        """
        if isinstance(size_key, str):
            size_pt = self.sizes[size_key]
            floor = FLOOR_SIZES[size_key]
        else:
            size_pt, floor = float(size_key), scene.MIN_BODY_PT
        value = "" if value is None else str(value)
        fit = measure.fit_text(value, size_pt, self.fs, w, h, min_pt=floor,
                               leading=leading, bold=bold)
        lines = list(fit["lines"])
        lh = measure.line_height_mm(fit["size_pt"], leading)
        fits = max(1, int(math.floor(h / lh + 1e-9)))
        if max_lines is not None:
            fits = min(fits, max_lines)
        dropped = 0
        if len(lines) > fits:
            if allow_truncate:
                dropped = len(lines) - fits
                lines = lines[:fits]
            else:
                # never lose a required label: keep every line and record the
                # overflow instead of silently cropping the text
                self.warn("W_TEXT_OVERFLOW",
                          "%d line(s) of %r do not fit a %.1f mm box at %.1f pt "
                          "(needs %.1f mm)" % (len(lines) - fits, value[:60], h,
                                               fit["size_pt"],
                                               len(lines) * lh), panel=panel)
        block_h = lh * len(lines)
        if valign == "middle":
            top = y + (h - block_h) / 2.0
        elif valign == "bottom":
            top = y + h - block_h
        else:
            top = y
        if top < y - 1e-9:
            top = y
        ascent = 0.80 * fit["size_pt"] * scene.PT_MM
        anchor = {"center": "middle", "right": "end"}.get(align, "start")
        tx = x + w / 2.0 if align == "center" else (x + w if align == "right" else x)
        baselines = [_r(top + i * lh + ascent) for i in range(len(lines))]
        widest = max([measure.text_width_mm(ln, fit["size_pt"], self.fs, bold)
                      for ln in lines] or [0.0])
        if fit["floor_hit"] and value.strip():
            self.warn("W_TEXT_FLOOR",
                      "text hit the %.1f pt floor in a %.1f x %.1f mm box "
                      "(needs %.1f mm wide): %r"
                      % (floor, w, h, fit["width_mm"], value[:60]), panel=panel)
        if dropped:
            self.warn("W_TEXT_TRUNCATED",
                      "%d wrapped line(s) of %r dropped: box is %.1f mm tall, "
                      "%d line(s) fit at %.1f pt"
                      % (dropped, value[:60], h, fits, fit["size_pt"]), panel=panel)
        style = {
            "font_size_pt": _r(fit["size_pt"], 3),
            "bold": bool(bold),
            "color": color,
            "align": align,
            "valign": valign,
            "anchor": anchor,
            "leading": _r(leading, 3),
        }
        if background:
            style["background"] = background
            style["contrast"] = _r(contrast_ratio(color, background), 3)
        if rotate:
            style["rotate_deg"] = _r(rotate, 3)
        return self.add(layer, "text", _bbox(x, y, w, max(block_h, 0.4)), element,
                        panel=panel, evidence=evidence, style=style,
                        text=value, lines=lines, line_x=_r(tx, 4),
                        line_baselines=baselines,
                        font_size_pt=_r(fit["size_pt"], 3),
                        max_w_mm=_r(w, 4), measured_w_mm=_r(widest, 4),
                        measured_h_mm=_r(block_h, 4), line_height_mm=_r(lh, 4),
                        floor_hit=bool(fit["floor_hit"]),
                        shrunk=bool(fit["shrunk"]), dropped_lines=dropped)

    # -- decor -------------------------------------------------------------- #
    def rect(self, layer, element, bbox, fill="none", stroke="none",
             width=0.3, rx=None, panel=None, evidence=None, dash=None, **extra):
        style = {"fill": fill, "stroke": stroke, "stroke_width_mm": _r(width, 3)}
        if rx is not None:
            style["rx_mm"] = _r(rx, 3)
        if dash:
            style["dash"] = list(dash)
        ptype = "rrect" if rx else "rect"
        return self.add(layer, ptype, bbox, element, panel=panel,
                        evidence=evidence, style=style, **extra)

    def line(self, layer, element, p1, p2, stroke=FRAME, width=0.3,
             panel=None, evidence=None, dash=None, ptype="line", **extra):
        style = {"stroke": stroke, "stroke_width_mm": _r(width, 3),
                 "linecap": "butt"}
        if dash:
            style["dash"] = list(dash)
        pts = [[_r(p1[0]), _r(p1[1])], [_r(p2[0]), _r(p2[1])]]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return self.add(layer, ptype,
                        _bbox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys),
                              stroke=width),
                        element, panel=panel, evidence=evidence, style=style,
                        points=pts, **extra)

    def polygon(self, layer, element, points, fill="none", stroke="none",
                width=0.3, panel=None, evidence=None, **extra):
        pts = [[_r(p[0]), _r(p[1])] for p in points]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        style = {"fill": fill, "stroke": stroke,
                 "stroke_width_mm": _r(width, 3), "closed": True}
        return self.add(layer, "polygon",
                        _bbox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys),
                              stroke=width),
                        element, panel=panel, evidence=evidence, style=style,
                        points=pts, **extra)

    def path(self, layer, element, points, stroke=FRAME, width=0.3,
             panel=None, evidence=None, dash=None, ptype="path", bbox=None,
             d=None, cubic=None, **extra):
        pts = [[_r(p[0]), _r(p[1])] for p in points]
        if bbox is None:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bbox = _bbox(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys),
                         stroke=width)
        style = {"fill": "none", "stroke": stroke,
                 "stroke_width_mm": _r(width, 3), "linecap": "round",
                 "linejoin": "round"}
        if dash:
            style["dash"] = list(dash)
        return self.add(layer, ptype, bbox, element, panel=panel,
                        evidence=evidence, style=style, points=pts, d=d,
                        cubic=cubic, **extra)

    def circle(self, layer, element, cx, cy, r, fill="none", stroke="none",
               width=0.3, panel=None, evidence=None, **extra):
        style = {"fill": fill, "stroke": stroke, "stroke_width_mm": _r(width, 3)}
        return self.add(layer, "circle", _bbox(cx - r, cy - r, 2 * r, 2 * r),
                        element, panel=panel, evidence=evidence, style=style,
                        cx=_r(cx), cy=_r(cy), r=_r(r), **extra)


# --------------------------------------------------------------------------- #
# text metrics used by the planner (must agree with _Builder.text)
# --------------------------------------------------------------------------- #
def _wrap_need(text, size_pt, fs, box_w, leading=1.25, bold=False):
    """(lines, block_height, widest_line) for a box of width `box_w`."""
    lines = measure.wrap_text(text or "", size_pt, fs, box_w, bold)
    lh = measure.line_height_mm(size_pt, leading)
    widest = max([measure.text_width_mm(ln, size_pt, fs, bold) for ln in lines] or [0.0])
    return lines, lh * len(lines), widest


def _shape_of(node):
    shape = node.get("shape") or "rrect"
    return shape if shape in scene.SHAPES else "rrect"


def _inset_x(shape, w):
    if shape in ("hexagon", "diamond"):
        return w * 0.20
    if shape in ("circle", "ellipse"):
        return w * 0.14
    if shape == "note":
        return w * 0.12
    if shape == "capsule":
        return min(w * 0.18, 4.0)
    if shape == "rrect":
        return 1.4
    return 0.8


def _spacing_compactness(level):
    """Spacing ladder (mm) — layout density, not typography.

    Level 0 is comfortable; each step tightens leading/padding so that dense
    panels fit *without* dropping text or breaking the 7 pt type floor.
    """
    steps = [
        {"gap": 1.6, "node_gap_y": 1.4, "node_pad_y": 1.2, "leading": 1.22,
         "label_leading": 1.18, "legend_row": 3.4, "panel_pad": 1.8, "hdr_pad": 1.0},
        {"gap": 1.2, "node_gap_y": 1.0, "node_pad_y": 0.9, "leading": 1.16,
         "label_leading": 1.12, "legend_row": 3.0, "panel_pad": 1.4, "hdr_pad": 0.8},
        {"gap": 0.9, "node_gap_y": 0.7, "node_pad_y": 0.6, "leading": 1.10,
         "label_leading": 1.06, "legend_row": 2.8, "panel_pad": 1.1, "hdr_pad": 0.6},
    ]
    return steps[max(0, min(level, len(steps) - 1))]


def _node_metrics(node, cell_w, fs, sizes):
    """Height a node needs in a cell of width `cell_w`, plus its wrapped lines.

    A node carrying an apparatus `part` reserves the left slice of the cell for
    the drawn glyph and has a floor tall enough for that glyph to be legible;
    the label is wrapped against the remaining width, so the two never overlap.
    """
    sp = sp_of(sizes)
    shape = _shape_of(node)
    part = node_part(node)
    inset = _inset_x(shape, cell_w)
    left = _node_left_extra(node, cell_w)
    inner_w = max(4.0, cell_w - inset - left - 0.4)
    label = str(node.get("label") or "")
    l_lines, l_h, _ = _wrap_need(label, sizes["node_label"], fs, inner_w,
                                 sp["label_leading"], True)
    h = l_h
    s_lines = []
    if node.get("sublabel"):
        s_lines, s_h, _ = _wrap_need(str(node["sublabel"]), sizes["node_sub"], fs,
                                     inner_w, sp["label_leading"])
        h += 0.25 + s_h
    need = h + 2 * sp["node_pad_y"] + 0.3
    if part is not None:
        need = max(need, part_glyph_w(cell_w) + 1.6)
    return {"h": need, "inner_w": inner_w,
            "label_lines": l_lines, "sub_lines": s_lines, "disc": 0.0}


def _choose_columns(nodes, area_w, fs, sizes, corr=(0.0, 0.0)):
    """(ncols, required_height) — fewest columns that fit the width budget."""
    cx, cy = corr
    cands = []
    for ncols in range(1, len(nodes) + 1):
        cell_w = (area_w - (ncols - 1) * (NODE_GAP_X + cx)) / ncols
        first = nodes[0]
        if ncols > 1 and (cell_w - _node_left_extra(first, cell_w)
                          - _inset_x(_shape_of(first), cell_w) < MIN_NODE_W_MM):
            break
        nrows = int(math.ceil(len(nodes) / float(ncols)))
        total = 0.0
        for r in range(nrows):
            row = nodes[r * ncols:(r + 1) * ncols]
            total += max(max(_node_metrics(n, cell_w, fs, sizes)["h"] for n in row),
                         MIN_NODE_H_MM)
        total += (nrows - 1) * (sp_of(sizes)["node_gap_y"] + cy)
        cands.append((ncols, total))
    if not cands:
        return 1, MIN_NODE_H_MM
    return min(cands, key=lambda c: (c[1], c[0]))


def _panel_header_h(panel, col_w, fs, sizes):
    """Header height measured from the real title wrap (shared by plan+emit)."""
    title = str(panel.get("title") or "")
    _, t_h, _ = _wrap_need(title, sizes["panel_title"], fs,
                           max(10.0, col_w - 2 * PANEL_PAD_MM - 16.0), 1.15, True)
    return max(PANEL_HEADER_MIN_MM, t_h + 2.0)


def _corridors(panel_edges, fs, sizes, area_w, ncols):
    """Free lanes between node cells so edge labels have somewhere to sit.

    Without lanes an edge label plate lands on top of a neighbouring node (the
    single most visible layout defect).  The lane is the measured label size.
    """
    labels = [str(e.get("label")) for e in (panel_edges or []) if isinstance(e, dict)
              and e.get("label")]
    if not labels:
        return 0.0, 0.0
    oz = sizes["edge_label"]
    widest = max(measure.text_width_mm(t, oz, fs) for t in labels) + 1.2
    cy = measure.line_height_mm(oz, 1.15) + 1.4
    cell = area_w / max(1, ncols)
    cx = _clamp(widest, 0.0, max(0.0, cell * 0.55))
    return cx, cy


def _diagram_need(nodes, width, fs, sizes, corr=(0.0, 0.0)):
    """(ncols, height) for the node grid inside `width`."""
    if not nodes:
        return 1, 0.0
    return _choose_columns(nodes, width, fs, sizes, corr)


def _node_grid(nodes, area, ncols, fs, sizes, corr=(0.0, 0.0)):
    """Position node boxes in `area`; the grid never exceeds the area."""
    nrows = int(math.ceil(len(nodes) / float(ncols))) if nodes else 0
    if not nrows:
        return {}
    sp = sp_of(sizes)
    cx, cy = corr
    gap_y = sp["node_gap_y"] + (cy if nrows > 1 else 0.0)
    gap_x = NODE_GAP_X + (cx if ncols > 1 else 0.0)
    cell_w = (area["w"] - (ncols - 1) * gap_x) / ncols
    req = []
    for r in range(nrows):
        row = nodes[r * ncols:(r + 1) * ncols]
        req.append(max(max(_node_metrics(n, cell_w, fs, sizes)["h"] for n in row),
                       MIN_NODE_H_MM))
    span = sum(req) + (nrows - 1) * gap_y
    if span > area["h"] + 1e-9 and nrows > 1:
        # 1st pass: give up the lane space (it is only there to make room for
        # edge labels) before touching the rows, because shrinking a row is
        # what drops a wrapped label line.
        lane_min = sp["node_gap_y"]
        deficit = span - area["h"]
        give = min(deficit, (gap_y - lane_min) * (nrows - 1))
        gap_y -= give / float(nrows - 1)
        span = sum(req) + (nrows - 1) * gap_y
    if span > area["h"] + 1e-9:
        # 2nd pass: clamp rows so a frame or a label never leaves the panel
        room = max(1.0, area["h"] - (nrows - 1) * gap_y)
        factor = room / max(1e-6, sum(req))
        req = [max(1.5, v * factor) for v in req]
        span = sum(req) + (nrows - 1) * gap_y
    extra = max(0.0, area["h"] - span)
    grow_cap = sum(req) * 0.35 / float(nrows) if nrows else 0.0
    grow = min(extra / float(nrows), grow_cap)
    offset = max(0.0, (area["h"] - span - grow * nrows) / 2.0)
    boxes, y = {}, area["y"] + offset
    for r in range(nrows):
        h = req[r] + grow
        for c in range(ncols):
            idx = r * ncols + c
            if idx >= len(nodes):
                break
            x = area["x"] + c * (cell_w + gap_x)
            boxes[nodes[idx].get("id")] = _bbox(x, y, cell_w, h)
        y += h + gap_y
    return boxes


# --------------------------------------------------------------------------- #
# flow / route layout (contract §3.3, §3.4: sequence, branch, merge, loop, stage)
#
# A panel is laid out as *layers* of parallel work when the spec declares an
# execution order (``sequence``/``phases``) or marks nodes with
# branch/stage/terminal/loop_to.  Everything else keeps the frozen row-major
# grid above, so a v1 spec renders byte-for-byte as before.
# --------------------------------------------------------------------------- #
def _is_flow_panel(panel, nodes):
    """Does this panel declare an execution order / parallelism?

    Only *semantic* declarations count.  `declared_edges` is a completeness list
    for gate J906 and says nothing about ordering, so it must not switch a plain
    apparatus panel from the grid to the layered flow layout.
    """
    if not nodes:
        return False
    if panel.get("sequence") or panel.get("phases"):
        return True
    if panel.get("role") in ("flow", "route"):
        return True
    for e in (panel.get("edges") or []):
        if isinstance(e, dict) and e.get("kind") == "loop":
            return True
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if node.get("branch") or node.get("stage") or node.get("terminal"):
            return True
        if node.get("loop_to") or node.get("group"):
            return True
    return False


def _loop_reserve(panel, fs=None):
    """Space a `loop_to` return line needs, reserved so it cannot fall on a node.

    The lane must also fit the loop's own label beside the line; otherwise the
    label plate is clamped back on top of the lane and the recycle line looks
    like it was never drawn.
    """
    labels = []
    for e in (panel.get("edges") or []):
        if not isinstance(e, dict):
            continue
        if e.get("kind") == "loop" or e.get("loop_to"):
            if isinstance(e.get("label"), str) and e["label"]:
                labels.append(e["label"])
    for n in (panel.get("nodes") or []):
        if isinstance(n, dict) and n.get("loop_to"):
            labels.append("loop")
            break
    if not labels:
        return 0.0
    need = 0.0
    for lab in labels:
        try:
            need = max(need, measure.text_width_mm(lab, BASE_SIZES["edge_label"], fs))
        except Exception:
            need = max(need, 12.0)
    return LOOP_LANE_MM + 1.2 + min(24.0, need)


def _flow_order(panel, nodes):
    """Node ids in reading order: sequence first, terminals last, then spec order."""
    seen, order = set(), []
    by_id = {}
    for n in nodes:
        nid = n.get("id")
        if isinstance(nid, str) and nid not in by_id:
            by_id[nid] = n
    seq = panel.get("sequence")
    if isinstance(seq, list):
        for s in seq:
            if isinstance(s, str) and s in by_id and s not in seen:
                seen.add(s)
                order.append(s)
    for n in nodes:
        nid = n.get("id")
        if isinstance(nid, str) and nid not in seen:
            seen.add(nid)
            order.append(nid)
    body = [i for i in order if not by_id[i].get("terminal")]
    tail = [i for i in order if by_id[i].get("terminal")]
    return body + tail, by_id


def _flow_layers(panel, nodes):
    """[[node, ...], ...] — columns/rows of parallel work, in execution order."""
    order, by_id = _flow_order(panel, nodes)
    if not order:
        return []
    phases = [p for p in (panel.get("phases") or [])
              if isinstance(p, dict) and isinstance(p.get("id"), str)]
    prank = {}
    for i, ph in enumerate(phases):
        prank[ph["id"]] = i
    if prank and any(by_id[i].get("stage") in prank for i in order):
        layers = [[] for _ in phases]
        used = set()
        for nid in order:
            stage = by_id[nid].get("stage")
            if stage in prank:
                layers[prank[stage]].append(nid)
                used.add(nid)
        tail = [i for i in order if i not in used]
        if tail:
            layers.append(tail)
        out = [[by_id[i] for i in layer] for layer in layers if layer]
        return out or [[by_id[i] for i in order]]
    layers, branch_layer = [], {}
    for nid in order:
        br = by_id[nid].get("branch")
        if isinstance(br, str) and br in branch_layer:
            li = branch_layer[br]
        else:
            li = len(layers)
            if isinstance(br, str):
                branch_layer[br] = li
        while len(layers) <= li:
            layers.append([])
        layers[li].append(nid)
    return [[by_id[i] for i in layer] for layer in layers]


def _flow_edges(panel):
    out = []
    for e in (panel.get("edges") or []):
        if isinstance(e, dict) and isinstance(e.get("from"), str) and isinstance(e.get("to"), str):
            out.append((e["from"], e["to"]))
    return out


def _flow_positions(panel, layers):
    """Deterministic cross-axis order inside each layer (barycentre, 3 passes).

    Parallel branches stay contiguous because the sort is stable and ties fall
    back to the declaration order, so the drawn figure never shuffles between
    two builds of the same spec.
    """
    index = {}
    for li, layer in enumerate(layers):
        for k, node in enumerate(layer):
            index[node.get("id")] = (li, k)
    preds, succs = {}, {}
    for a, b in _flow_edges(panel):
        if a in index and b in index and index[a][0] != index[b][0]:
            preds.setdefault(b, []).append(a)
            succs.setdefault(a, []).append(b)
    pos = {}
    for li, layer in enumerate(layers):
        for k, node in enumerate(layer):
            pos[node.get("id")] = float(k)

    def _pass(use_preds):
        for li in (range(len(layers)) if use_preds else range(len(layers) - 1, -1, -1)):
            layer = layers[li]
            keys = []
            for k, node in enumerate(layer):
                nid = node.get("id")
                rel = preds.get(nid, []) if use_preds else succs.get(nid, [])
                vals = [pos[r] for r in rel if r in pos
                        and ((index[r][0] < li) if use_preds else (index[r][0] > li))]
                bary = (sum(vals) / len(vals)) if vals else float(k)
                keys.append((bary, k))          # declaration order breaks ties
            keys.sort(key=lambda t: (t[0], t[1]))
            for newk, (_bary, k) in enumerate(keys):
                pos[layer[k].get("id")] = float(newk)

    for _ in range(2):
        _pass(True)
        _pass(False)
    _pass(True)
    out = []
    for layer in layers:
        out.append(sorted(layer, key=lambda n: pos.get(n.get("id"), 0.0)))
    return out


def _flow_direction(layers, width):
    if len(layers) <= 1:
        return "v"
    if width / float(len(layers)) >= MIN_NODE_W_MM + 4.0:
        return "h"
    return "v"


def _flow_cells(layers, width, direction, fs, sizes):
    """(cell_w, [per-layer main-axis requirement], gap) — measure only."""
    sp = sp_of(sizes)
    gap = NODE_GAP_X if direction == "h" else sp["node_gap_y"]
    n = max(1, len(layers))
    if direction == "h":
        cell_w = (width - (n - 1) * gap) / n
        req = []
        for layer in layers:
            hs = [max(_node_metrics(nd, cell_w, fs, sizes)["h"], MIN_NODE_H_MM)
                  for nd in layer]
            req.append(sum(hs) + (len(hs) - 1) * sp["node_gap_y"])
    else:
        widest = max(1, max(len(layer) for layer in layers))
        cell_w = (width - (widest - 1) * NODE_GAP_X) / widest
        req = []
        for layer in layers:
            req.append(max([max(_node_metrics(nd, cell_w, fs, sizes)["h"], MIN_NODE_H_MM)
                            for nd in layer] or [MIN_NODE_H_MM]))
    return cell_w, req, gap


def _flow_need(panel, nodes, width, fs, sizes):
    layers = _flow_positions(panel, _flow_layers(panel, nodes))
    direction = _flow_direction(layers, width)
    reserve = _loop_reserve(panel, fs)
    eff_w = max(8.0, width - reserve) if direction == "v" else width
    _cell_w, req, gap = _flow_cells(layers, eff_w, direction, fs, sizes)
    need = sum(req) + (len(req) - 1) * gap if req else 0.0
    if direction == "h":
        need += reserve
    return {"flow": True, "direction": direction, "layers": len(layers),
            "ncols": max(1, len(layers)) if direction == "h" else 1,
            "need_h": need, "req": req, "gap": gap, "reserve": reserve}


def _flow_grid(panel, nodes, area, direction, fs, sizes):
    """Place every node box inside `area`; never overflows it (gate A)."""
    layers = _flow_positions(panel, _flow_layers(panel, nodes))
    if not layers:
        return {}
    reserve = _loop_reserve(panel, fs)
    if direction == "h":
        area = _bbox(area["x"], area["y"], area["w"], max(4.0, area["h"] - reserve))
    elif reserve:
        area = _bbox(area["x"], area["y"], max(8.0, area["w"] - reserve), area["h"])
    sp = sp_of(sizes)
    gap = NODE_GAP_X if direction == "h" else sp["node_gap_y"]
    n = len(layers)
    widest = max(1, max(len(layer) for layer in layers))
    if direction == "h":
        cell_w = (area["w"] - (n - 1) * gap) / n
        req = []
        for layer in layers:
            hs = [max(_node_metrics(nd, cell_w, fs, sizes)["h"], MIN_NODE_H_MM)
                  for nd in layer]
            req.append(sum(hs) + (len(hs) - 1) * sp["node_gap_y"])
    else:
        cell_w = (area["w"] - (widest - 1) * gap) / widest
        req = [max([max(_node_metrics(nd, cell_w, fs, sizes)["h"], MIN_NODE_H_MM)
                    for nd in layer] or [MIN_NODE_H_MM]) for layer in layers]
    req, gap, span = _fit_stack(req, area["h"], gap)
    boxes = {}
    if direction == "h":
        y0 = area["y"] + max(0.0, (area["h"] - span) / 2.0)
        for li, layer in enumerate(layers):
            avail = req[li]
            hs = [max(_node_metrics(nd, cell_w, fs, sizes)["h"], MIN_NODE_H_MM)
                  for nd in layer]
            total = sum(hs) + (len(hs) - 1) * sp["node_gap_y"]
            if total > avail + 1e-9 and len(hs) > 1:
                factor = max(1e-6, avail - (len(hs) - 1) * sp["node_gap_y"]) / max(1e-6, sum(hs))
                hs = [max(1.5, h * factor) for h in hs]
                total = sum(hs) + (len(hs) - 1) * sp["node_gap_y"]
            y = y0 + (avail - total) / 2.0
            x = area["x"] + li * (cell_w + gap)
            for node, hgt in zip(layer, hs):
                boxes[node.get("id")] = _bbox(x, y, cell_w, hgt)
                y += hgt + sp["node_gap_y"]
    else:
        y = area["y"] + max(0.0, (area["h"] - span) / 2.0)
        for li, layer in enumerate(layers):
            total_w = len(layer) * cell_w + (len(layer) - 1) * gap
            x = area["x"] + max(0.0, (area["w"] - total_w) / 2.0)
            for node in layer:
                boxes[node.get("id")] = _bbox(x, y, cell_w, req[li])
                x += cell_w + gap
            y += req[li] + gap
    return boxes


def _fit_stack(req, avail, gap):
    """Shrink gaps, then heights, until the stack fits `avail`."""
    if not req:
        return req, gap, 0.0
    n = len(req)
    span = sum(req) + (n - 1) * gap
    if span > avail + 1e-9 and n > 1:
        lane_min = max(0.35, gap * 0.3)
        give = min(span - avail, (gap - lane_min) * (n - 1))
        gap -= give / float(n - 1)
        span = sum(req) + (n - 1) * gap
    if span > avail + 1e-9:
        room = max(1.0, avail - (n - 1) * gap)
        factor = room / max(1e-6, sum(req))
        req = [max(1.5, v * factor) for v in req]
        span = sum(req) + (n - 1) * gap
    return req, gap, span


def _diagram_plan(panel, nodes, width, fs, sizes, corr):
    if _is_flow_panel(panel, nodes):
        flow = _flow_need(panel, nodes, width, fs, sizes)
        flow["corr"] = corr
        return flow
    ncols, dh = _diagram_need(nodes, width, fs, sizes, corr)
    return {"ncols": ncols, "need_h": dh, "flow": False, "direction": "grid",
            "corr": corr}


def _place_nodes(panel, nodes, area, plan, fs, sizes):
    if not nodes:
        return {}
    if plan.get("flow"):
        return _flow_grid(panel, nodes, area, plan.get("direction") or "v", fs, sizes)
    return _node_grid(nodes, area, max(1, int(plan.get("ncols") or 1)), fs, sizes,
                      plan.get("corr") or (0.0, 0.0))


# --------------------------------------------------------------------------- #
# chart sizing
# --------------------------------------------------------------------------- #
def _chart_min_box(cw):
    w = min(max(CHART_MIN_W_MM, 0.44 * cw), cw)
    return w, CHART_MIN_H_MM


def _chart_pref_box(cw, ch):
    return min(max(CHART_MIN_W_MM, 0.46 * cw), cw), min(max(CHART_PREF_H_MM, CHART_MIN_H_MM), ch)


def _split_row(total_w, items):
    """Split `total_w` into len(items) equal columns with a small gap."""
    n = max(1, len(items))
    gap = BAND_GAP_MM
    if n == 1:
        return [total_w]
    each = (total_w - (n - 1) * gap) / n
    return [each] * n


def _stack_boxes(width, available, n):
    """Vertical stack of n equal boxes inside `available` height."""
    if n <= 0:
        return []
    gap = BAND_GAP_MM
    each = (available - (n - 1) * gap) / n
    return [each] * n, gap


# --------------------------------------------------------------------------- #
# panel planning (measure only, no primitives)
# --------------------------------------------------------------------------- #
def _panel_parts(panel):
    nodes = [n for n in (panel.get("nodes") or []) if isinstance(n, dict)]
    edges = [e for e in (panel.get("edges") or []) if isinstance(e, dict)]
    charts = [c for c in (panel.get("charts") or []) if isinstance(c, dict)]
    legend = panel.get("legend") if isinstance(panel.get("legend"), dict) else None
    colorbars = [c for c in (panel.get("colorbars") or []) if isinstance(c, dict)]
    return nodes, edges, charts, legend, colorbars


def _side_band_need(legend, colorbars, sizes, fs):
    """Height needed by a legend/colorbar column."""
    h = 0.0
    items = [it for it in ((legend or {}).get("items") or []) if isinstance(it, dict)]
    if legend and items:
        h += _legend_row(sizes, fs, items) * (len(items) +
                                              (1.0 if legend.get("title") else 0.0)) + 1.6
    for cb in colorbars:
        h += 20.0 + (3.0 if cb.get("title") else 0.0) + 3.0
    return h


def _cb_need(cb, fs, sizes, max_w):
    """(width, height) a horizontal colour bar needs so its title is not clipped."""
    oz = sizes["colorbar"]
    title = str(cb.get("title") or cb.get("id") or "")
    unit = str(cb.get("unit") or "")
    full = title if not unit else "%s (%s)" % (title, unit)
    words = [w for w in full.split() if w]
    longest = max([measure.text_width_mm(w, oz, fs, True) for w in words] or [8.0])
    one_line = measure.text_width_mm(full, oz, fs, True)
    w = _clamp(max(one_line + 2.0, longest + 2.0), COLORBAR_V_MIN_W, max_w)
    lines, t_h, _ = _wrap_need(full, oz, fs, max(4.0, w - 1.4), 1.15, True)
    h = min(t_h, 2 * measure.line_height_mm(oz, 1.15)) + 4.4 + 3.4 + 0.8
    return w, h, len(lines)


def _legend_row(sizes, fs, items=None):
    """Legend row pitch: never smaller than one real line of text.

    A row that carries a drawn sample (an edge kind or an apparatus part) is a
    little taller, so the sample is legible instead of a 2 mm smudge.
    """
    oz = sizes.get("legend", BASE_SIZES["legend"])
    row = max(sp_of(sizes)["legend_row"],
              measure.line_height_mm(oz, 1.25) + 0.45)
    for it in (items or []):
        if isinstance(it, dict) and (it.get("part") or it.get("kind")):
            row = max(row, 4.8)
            break
    return row


def _legend_sample_reserve(item, row, col_w):
    """Horizontal space an item's sample needs before its label."""
    if isinstance(item, dict) and item.get("kind"):
        return _clamp(col_w * 0.26, 2.6, 6.6) + 0.9
    if isinstance(item, dict) and item.get("part"):
        side = min(row * 0.92, _clamp(col_w * 0.26, 2.6, 6.6) + 1.0)
        return side + 0.8
    return 2.4 + 0.7


def _legend_need(legend, items, fs, sizes):
    """(width, height) a legend needs (2 columns when it helps)."""
    n = len(items)
    ncol = 2 if (n >= 3) else 1
    rows = int(math.ceil(n / float(ncol)))
    oz = sizes.get("legend", BASE_SIZES["legend"])
    longest = max([measure.text_width_mm(str(it.get("label") or ""), oz, fs)
                   for it in items] or [8.0])
    row = _legend_row(sizes, fs, items)
    reserve = max([_legend_sample_reserve(it, row, LEGEND_COL_W_MM)
                   for it in items] or [3.1])
    col = max(LEGEND_COL_W_MM, longest + reserve + 1.4)
    w = max(col * ncol, longest + reserve + 1.4)
    h = (row * rows) + (row if legend.get("title") else 0.0) + 1.0
    return min(w, 120.0), h, ncol


def _plan_panel(panel, content_w, avail_h, fs, sizes):
    """Choose the arrangement that needs the least height (measure only)."""
    nodes, edges, charts, legend, colorbars = _panel_parts(panel)
    items = [it for it in ((legend or {}).get("items") or []) if isinstance(it, dict)]
    corr = _corridors(edges, fs, sizes, content_w, 2)
    has_side = bool(charts or items or colorbars)
    if not has_side:
        dia = _diagram_plan(panel, nodes, content_w, fs, sizes, corr)
        return {"mode": "nodes", "need_h": dia["need_h"], "ncols": dia["ncols"],
                "diagram_h": dia["need_h"], "flow": dia["flow"],
                "direction": dia["direction"],
                "corr": corr, "chart_boxes": [], "legend_box": None,
                "cb_boxes": [], "side_w": 0.0}

    cw_chart_min, ch_min = _chart_min_box(content_w)
    leg_w, leg_h = (0.0, 0.0)
    if items:
        leg_w, leg_h, _ncol = _legend_need(legend, items, fs, sizes)
    cb_w, cb_h, _cbl = (0.0, 0.0, 0)
    if colorbars:
        cb_w, cb_h, _cbl = _cb_need(colorbars[0], fs, sizes, max(20.0, content_w * 0.55))

    # ---- STACK: nodes on top, chart band underneath, legend+colorbar right -- #
    right_w = max(leg_w, cb_w)
    right_need = 0.0
    if items:
        right_need += leg_h
    if colorbars:
        right_need += (BAND_GAP_MM if right_need else 0.0) + cb_h
    band_h = max(ch_min if charts else 0.0, right_need)
    chart_span = max(0.0, content_w - (right_w + BAND_GAP_MM if right_w else 0.0))
    n_row = len(charts) or 1
    while n_row > 1 and chart_span / n_row < CHART_MIN_W_MM:
        n_row -= 1
    rows_c = int(math.ceil(len(charts) / float(n_row))) if charts else 0
    if charts and n_row < len(charts):
        band_h = max(band_h, ch_min * rows_c + (rows_c - 1) * BAND_GAP_MM)
    dia_s = _diagram_plan(panel, nodes, content_w, fs, sizes, corr)
    ncols_s, dh_s = dia_s["ncols"], dia_s["need_h"]
    need_stack = dh_s + ((BAND_GAP_MM + band_h) if band_h else 0.0)

    # ---- SIDE: nodes left, chart(s)/legend/colorbar right ------------------ #
    side_w = 0.0
    if charts:
        side_w = max(side_w, cw_chart_min)
    side_w = max(side_w, max(leg_w, cb_w))
    side_w = min(side_w, max(0.0, content_w - MIN_NODE_W_MM - BAND_GAP_MM))
    left_w = max(MIN_NODE_W_MM, content_w - side_w - BAND_GAP_MM)
    dia_d = _diagram_plan(panel, nodes, left_w, fs, sizes, corr)
    ncols_d, dh_d = dia_d["ncols"], dia_d["need_h"]
    right_need_s = 0.0
    if charts:
        right_need_s += ch_min * len(charts) + BAND_GAP_MM * max(0, len(charts) - 1)
    if items:
        right_need_s += (BAND_GAP_MM if right_need_s else 0.0) + leg_h
    if colorbars:
        right_need_s += (BAND_GAP_MM if right_need_s else 0.0) + cb_h
    need_side = max(dh_d, right_need_s) if nodes else right_need_s

    if need_stack <= need_side + 1e-9:
        return {"mode": "stack", "need_h": need_stack, "ncols": ncols_s, "corr": corr,
                "diagram_h": dh_s, "band_h": band_h, "chart_span": max(CHART_MIN_W_MM, chart_span),
                "n_charts_row": n_row, "right_w": right_w, "leg_h": leg_h,
                "cb_h": cb_h, "leg_w": leg_w, "cb_w": cb_w,
                "flow": dia_s["flow"], "direction": dia_s["direction"],
                "chart_boxes": [], "legend_box": None, "cb_boxes": [], "side_w": 0.0}
    return {"mode": "side", "need_h": need_side, "ncols": ncols_d, "corr": corr,
            "diagram_h": dh_d, "band_h": 0.0, "side_w": side_w, "left_w": left_w,
            "leg_h": leg_h, "cb_h": cb_h, "leg_w": leg_w, "cb_w": cb_w,
            "flow": dia_d["flow"], "direction": dia_d["direction"],
            "chart_boxes": [], "legend_box": None, "cb_boxes": []}


def _plan_rows(spec, fs, sizes, inner, y0, avail_h):
    """Measure every panel, group into rows, return row heights."""
    panels = _ordered_panels(spec)
    layout_meta = (spec.get("meta") or {}).get("layout")
    columns = 2
    if isinstance(layout_meta, dict) and isinstance(layout_meta.get("columns"), int):
        columns = max(1, layout_meta["columns"])
    columns = max(1, min(columns, max(1, len(panels))))
    rows = int(math.ceil(len(panels) / float(columns))) if panels else 0
    col_w = (inner["w"] - (columns - 1) * GUTTER_MM) / columns if columns else inner["w"]
    plans = []
    for panel in panels:
        plans.append(_plan_panel(panel, col_w - 2 * PANEL_PAD_MM,
                                 avail_h, fs, sizes))
    row_heights = []
    for r in range(rows):
        chunk = ["plans"] and plans[r * columns:(r + 1) * columns]
        hdr = max([_panel_header_h(panels[r * columns + i], col_w, fs, sizes)
                   for i in range(len(chunk))] or [0.0])
        row_heights.append(max([p["need_h"] for p in chunk] or [0.0]) + hdr + 2.0)
    return {"panels": panels, "columns": columns, "rows": rows, "col_w": col_w,
            "plans": plans, "row_heights": row_heights}


def _ordered_panels(spec):
    panels = [p for p in (spec.get("panels") or []) if isinstance(p, dict)]
    layout_meta = (spec.get("meta") or {}).get("layout")
    roles = panel_roles()
    if isinstance(layout_meta, dict) and isinstance(layout_meta.get("row_order"), list):
        roles = [r for r in layout_meta["row_order"] if isinstance(r, str)] or roles
    ordered, used = [], set()
    for role in roles:
        for i, p in enumerate(panels):
            if i not in used and p.get("role") == role:
                ordered.append(p)
                used.add(i)
    for i, p in enumerate(panels):
        if i not in used:
            ordered.append(p)
            used.add(i)
    return ordered


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #
def layout(spec, fs):
    """Build the scene. Deterministic; never raises on an odd (but valid) spec."""
    meta = spec.get("meta") or {}
    canvas = scene.resolve_canvas(meta)
    W, H = float(canvas["w_mm"]), float(canvas["h_mm"])
    M = float(canvas["margin_mm"])
    inner = _bbox(M, M, W - 2 * M, H - 2 * M)

    best = None
    for level in range(len(SPACING_LEVELS)):
        scale = 1.0
        for _ in range(14):
            sizes = scaled_sizes(scale, level)
            bands = _measure_bands(spec, fs, sizes, inner)
            avail = inner["h"] - bands["title_h"] - bands["caption_h"] - bands["gaps"]
            rows_plan = _plan_rows(spec, fs, sizes, inner, inner["y"] + bands["title_h"], avail)
            total = sum(rows_plan["row_heights"]) + max(0, rows_plan["rows"] - 1) * GUTTER_MM
            candidate = {"sizes": sizes, "bands": bands, "rows": rows_plan,
                         "avail": avail, "total": total, "scale": scale, "level": level}
            if best is None or total < best["total"] - 1e-9:
                best = candidate
            if total <= avail + 1e-6:
                best = candidate
                break
            if scale <= 0.55:
                break
            shrink = _clamp(math.sqrt(max(0.25, avail / max(total, 1e-6))), 0.80, 0.98)
            scale = round(max(0.55, scale * shrink), 3)
        if best is not None and best["total"] <= best["avail"] + 1e-6:
            break

    # hard clamp: the panel grid may never leave the margin box (gate A)
    rows_plan = best["rows"]
    total = best["total"]
    if total > best["avail"] + 1e-6:
        room = max(4.0, best["avail"] - max(0, rows_plan["rows"] - 1) * GUTTER_MM)
        factor = room / max(1e-6, sum(rows_plan["row_heights"]))
        rows_plan["row_heights"] = [max(4.0, h * factor) for h in rows_plan["row_heights"]]
        best["clamped"] = True
    sizes = best["sizes"]
    bands = best["bands"]
    rows_plan = best["rows"]
    b = _Builder(spec, fs, sizes)

    # page background covers the full page (bleed is legitimate; see SCENE.md)
    b.add("frame", "rect", _bbox(0, 0, W, H), "page-background",
          style={"fill": PAGE_BG, "stroke": "none", "stroke_width_mm": 0.0},
          bleed=True)

    # ---- title band ------------------------------------------------------- #
    y = inner["y"]
    b.text("annotation", "figure-title", bands["title"], inner["x"], y,
           inner["w"], bands["title_h"], "title", bold=True, color=INK,
           valign="top", leading=1.12)
    if bands["subtitle"]:
        b.text("annotation", "figure-subtitle", bands["subtitle"], inner["x"],
               y + bands["title_block_h"] + 0.8, inner["w"],
               bands["subtitle_h"], "subtitle", color=MUTED, valign="top",
               leading=1.2)
    y += bands["title_h"] + bands["gaps"] / 2.0

    # ---- caption / conclusion strip (bottom) ------------------------------ #
    if bands["caption_h"]:
        cap_y = inner["y"] + inner["h"] - bands["caption_h"]
        b.line("annotation", "caption-rule", (inner["x"] + 0.4, cap_y - 1.2),
               (inner["x"] + inner["w"] - 0.4, cap_y - 1.2), stroke=GRID, width=0.3)
        cy = cap_y
        if bands["caption"]:
            b.text("annotation", "figure-caption", bands["caption"], inner["x"], cy,
                   inner["w"], bands["caption_text_h"], "caption", color=INK,
                   valign="top", leading=1.22)
            cy += bands["caption_text_h"] + 0.4
        if bands["conclusion"]:
            b.text("annotation", "figure-conclusion", bands["conclusion"], inner["x"],
                   cy, inner["w"], max(1.5, inner["y"] + inner["h"] - cy),
                   "caption", color=INK, valign="top", leading=1.22)

    # ---- panels ----------------------------------------------------------- #
    columns = rows_plan["columns"]
    col_w = rows_plan["col_w"]
    panel_records = []
    cur_y = y
    for r, row_h in enumerate(rows_plan["row_heights"]):
        for c in range(columns):
            idx = r * columns + c
            if idx >= len(rows_plan["panels"]):
                break
            panel = rows_plan["panels"][idx]
            box = _bbox(inner["x"] + c * (col_w + GUTTER_MM), cur_y, col_w, row_h)
            rec = _emit_panel(b, panel, box, idx, fs, rows_plan["plans"][idx])
            panel_records.append(rec)
        cur_y += row_h + GUTTER_MM

    if best.get("clamped") or best["total"] > best["avail"] + 1e-6:
        b.warn("W_LAYOUT_DENSE",
               "panels measured %.1f mm but only %.1f mm is available "
               "(type scale %.2f, spacing level %d); row heights were clamped so "
               "nothing leaves the page" % (best["total"], best["avail"],
                                            best["scale"], best.get("level", 0)))

    _maybe_scalebar(b, spec, panel_records)

    # ---- glyph coverage --------------------------------------------------- #
    blob = " ".join(" ".join(p.get("lines") or []) for p in b.primitives
                    if p.get("type") == "text")
    missing = _check_glyphs(b, blob)
    if missing:
        b.warn("W_GLYPH_MISSING",
               "%d character(s) have no glyph in any resolved face: %s"
               % (len(missing), "".join(missing[:24])))

    prims = sorted(b.primitives, key=lambda p: (
        LAYER_ORDER.index(p["layer"]) if p["layer"] in LAYER_ORDER else 99,
        0 if p.get("type") != "text" else 1))

    return {
        "canvas": {"w_mm": _r(W), "h_mm": _r(H), "dpi": int(canvas["dpi"]),
                   "margin_mm": _r(M)},
        "primitives": prims,
        "panels": panel_records,
        "warnings": b.warnings,
        "meta": {
            "generator": GENERATOR,
            "version": VERSION,
            "case_id": meta.get("case_id"),
            "title": bands["title"],
            "language": meta.get("language", "auto"),
            "palette": list(b.palette),
            "palette_id": (spec.get("palette") or {}).get("id", "okabe-ito"),
            "spec_sha256": scene.sha256_text(_canonical_spec(spec)),
            "layers": list(LAYER_ORDER),
            "font": getattr(fs, "family_css", "sans-serif"),
            "units": "mm, origin top-left, y down",
            "type_scale": best["scale"],
            "spacing_level": best.get("level", 0),
            "font_sizes_pt": {k: v for k, v in sizes.items() if not k.startswith("__")},
            "grid": {"columns": columns, "rows": rows_plan["rows"],
                     "row_heights_mm": [_r(v) for v in rows_plan["row_heights"]]},
        },
    }


def _canonical_spec(spec):
    import json
    return json.dumps(spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


TITLE_LEADING = 1.15


def _fit_title(text, size_pt, fs, max_w, max_lines=2):
    """Fit a panel title: wrap, then ellipsize at a word boundary."""
    lines = measure.wrap_text(text, size_pt, fs, max_w, True)
    if len(lines) <= max_lines:
        lh = measure.line_height_mm(size_pt, TITLE_LEADING)
        return text, lines, lh * max(1, len(lines))
    kept = lines[:max_lines]
    last = kept[-1]
    while last and measure.text_width_mm(last + "\u2026", size_pt, fs) > max_w:
        cut = last.rfind(" ")
        last = last[:cut] if cut > 0 else last[:-1]
    kept[-1] = (last.rstrip() + "\u2026")
    lh = measure.line_height_mm(size_pt, TITLE_LEADING)
    return " ".join(kept), kept, lh * max_lines


def _measure_bands(spec, fs, sizes, inner):
    meta = spec.get("meta") or {}
    texts = spec.get("texts") or {}
    title = meta.get("title") or texts.get("title") or (meta.get("case_id") or "")
    subtitle = meta.get("subtitle") or texts.get("subtitle") or ""
    t_lines, t_h, _ = _wrap_need(title, sizes["title"], fs, inner["w"], 1.12, True)
    t_h = min(t_h, 0.18 * inner["h"])
    s_lines, s_h, _ = _wrap_need(subtitle, sizes["subtitle"], fs, inner["w"], 1.2) \
        if subtitle else ([], 0.0, 0.0)
    s_h = min(s_h, 0.10 * inner["h"])
    title_block = t_h + (0.8 + s_h if subtitle else 0.0)

    caption = texts.get("caption") or ""
    conclusion = texts.get("conclusion") or ""
    cap_h = 0.0
    cap_text_h = 0.0
    conc_h = 0.0
    if caption:
        _, cap_text_h, _ = _wrap_need(str(caption), sizes["caption"], fs, inner["w"], 1.22)
    if conclusion:
        _, conc_h, _ = _wrap_need(str(conclusion), sizes["caption"], fs, inner["w"], 1.22)
    need_caption = cap_text_h + (0.4 + conc_h if conclusion else 0.0) + 1.6
    cap_h = min(need_caption, 0.20 * inner["h"]) if (caption or conclusion) else 0.0
    if cap_h:
        # the two blocks share the strip; give each its measured share
        if caption and conclusion:
            share = cap_text_h / max(1e-6, cap_text_h + conc_h)
            cap_text_h = max(1.5, (cap_h - 1.6) * share)
            conc_h = max(1.5, (cap_h - 1.6) - cap_text_h - 0.4)
        elif caption:
            cap_text_h = max(1.5, cap_h - 1.6)
        else:
            conc_h = max(1.5, cap_h - 1.6)

    gaps = 4.0 if cap_h else 2.0
    return {"title": title, "subtitle": subtitle, "title_h": title_block,
            "title_block_h": t_h, "subtitle_h": s_h, "caption": caption,
            "conclusion": conclusion, "caption_h": cap_h,
            "caption_text_h": cap_text_h, "conclusion_h": conc_h, "gaps": gaps}


def _check_glyphs(b, text):
    if not text.strip():
        return []
    fs = b.fs
    missing, seen = [], set()
    for ch in text:
        if ch.isspace() or ch in seen:
            continue
        seen.add(ch)
        ok = False
        for p in fs.all_paths():
            try:
                if measure.char_supported(p, ord(ch)):
                    ok = True
                    break
            except Exception:
                continue
        if not ok:
            missing.append(ch)
    if missing:
        try:
            fs.record_missing(missing)
        except Exception:
            pass
    return sorted(missing)


# --------------------------------------------------------------------------- #
# panel emission
# --------------------------------------------------------------------------- #
def _emit_panel(b, panel, box, index, fs, plan):
    pid = panel.get("id")
    role = panel.get("role")
    nodes, edges, charts, legend, colorbars = _panel_parts(panel)
    sizes = b.sizes

    # header: measured so the title never falls below its floor
    sp = sp_of(sizes)
    pad = sp["panel_pad"]
    hdr_pad = sp["hdr_pad"]
    role_tag = str(role or "").upper()
    tag_w = measure.text_width_mm(role_tag, sizes["panel_role"], fs) + 1.4
    title_w = max(12.0, box["w"] - 2 * pad - tag_w - 1.4)
    title, t_lines, t_h = _fit_title(str(panel.get("title") or ""),
                                     sizes["panel_title"], fs, title_w, 2)
    header_h = max(PANEL_HEADER_MIN_MM, t_h + 2 * max(hdr_pad, 1.0))
    b.rect("panel", "panel-frame", box, fill="#FCFCFC", stroke=FRAME, width=0.4,
           rx=1.2, panel=pid)
    header = _bbox(box["x"], box["y"], box["w"], header_h)
    b.rect("panel", "panel-header", header, fill="#EFEFEF", stroke=FRAME,
           width=0.3, panel=pid)
    b.text("panel", "panel-title", title, header["x"] + pad,
           header["y"] + hdr_pad, title_w, t_h + 0.25, "panel_title", bold=True,
           color=INK, valign="top", panel=pid, allow_truncate=False,
           leading=TITLE_LEADING)
    b.text("panel", "panel-role", role_tag,
           header["x"] + header["w"] - pad - tag_w, header["y"] + hdr_pad,
           tag_w, max(2.4, header["h"] - 2 * hdr_pad), "panel_role", color=MUTED,
           align="right", valign="top", panel=pid, max_lines=1, allow_truncate=False)

    content = _bbox(box["x"] + pad, box["y"] + header_h + 0.8,
                    box["w"] - 2 * pad, max(2.0, box["h"] - header_h - 1.6))

    cb = colorbars[0] if colorbars else None
    node_boxes = {}
    if plan["mode"] == "side":
        gap = sp["gap"]
        left = _bbox(content["x"], content["y"], plan["left_w"], content["h"])
        right = _bbox(content["x"] + plan["left_w"] + gap, content["y"],
                      plan["side_w"], content["h"])
        if nodes:
            node_boxes = _place_nodes(panel, nodes, left, plan, fs, sizes)
        _emit_side_column(b, pid, right, charts, legend, colorbars, fs, sizes, cb)
    elif plan["mode"] == "stack":
        gap = sp["gap"]
        band_h = min(plan["band_h"], max(6.0, content["h"] - MIN_DIAGRAM_MM - gap))
        diagram = _bbox(content["x"], content["y"], content["w"],
                        max(4.0, content["h"] - band_h - gap))
        if nodes:
            node_boxes = _place_nodes(panel, nodes, diagram, plan, fs, sizes)
        band = _bbox(content["x"], content["y"] + diagram["h"] + gap,
                     content["w"], max(4.0, content["h"] - diagram["h"] - gap))
        _emit_band(b, pid, band, charts, legend, colorbars, fs, sizes, cb,
                   plan.get("n_charts_row") or len(charts))
    else:
        if nodes:
            node_boxes = _place_nodes(panel, nodes, content, plan, fs, sizes)
    if colorbars and plan["mode"] == "nodes":
        _emit_colorbar(b, pid, colorbars[0], _inset(content, 0.5, 0.5), fs, sizes)

    if node_boxes and plan.get("flow"):
        _emit_groups(b, pid, panel, nodes, node_boxes, box, fs, sizes)

    for node in nodes:
        nbox = node_boxes.get(node.get("id"))
        if nbox is not None:
            _emit_node(b, pid, node, nbox, fs, sizes, cb)

    if edges and node_boxes:
        loop_side = None
        if plan.get("flow"):
            loop_side = "right" if plan.get("direction") == "v" else "bottom"
        _emit_edges(b, pid, edges, node_boxes, content, fs, sizes,
                    b.edge_declared,
                    {n.get("id"): n for n in nodes if isinstance(n, dict)},
                    loop_side, port_sides(nodes))
    if not nodes and not charts and not legend and not colorbars:
        b.warn("W_EMPTY_PANEL", "panel %s has nothing to draw" % pid, panel=pid)

    return {"id": pid, "role": role, "title": panel.get("title"), "index": index,
            "bbox": box, "header_bbox": header, "content_bbox": content,
            "mode": plan["mode"], "node_count": len(nodes),
            "edge_count": len(edges), "chart_count": len(charts),
            "node_boxes": {k: dict(v) for k, v in sorted(node_boxes.items())},
            "layer": "panel"}


def _inset(box, dx, dy):
    return _bbox(box["x"] + dx, box["y"] + dy, max(0.5, box["w"] - 2 * dx),
                 max(0.5, box["h"] - 2 * dy))


GROUP_FILL = "#F7F9FB"
GROUP_STROKE = "#D9E1E9"
GROUP_LABEL_MM = 3.4
GROUP_PAD_MM = 1.0


def _emit_groups(b, pid, panel, nodes, boxes, panel_box, fs, sizes):
    """Optional swimlane bands for nodes sharing a `group` id.

    A band is a pale, *painted* rectangle under the nodes (layer "panel" sorts
    before "entity") with an optional title taken from panels[].groups[].  It is
    only labelled when the measured title fits, so gate B can never see a
    shrunk-to-floor or overflowing group caption.
    """
    order, members = [], {}
    for node in nodes:
        gid = node.get("group") if isinstance(node, dict) else None
        if isinstance(gid, str) and gid:
            if gid not in members:
                members[gid] = []
                order.append(gid)
            members[gid].append(node.get("id"))
    if not order:
        return
    titles = {}
    for g in (panel.get("groups") or []):
        if isinstance(g, dict) and isinstance(g.get("id"), str):
            titles[g["id"]] = g.get("title") or g.get("label")
    oz = sizes.get("legend", BASE_SIZES["legend"])
    for gid in order:
        bs = [boxes[i] for i in members[gid] if i in boxes]
        if not bs:
            continue
        label = titles.get(gid)
        top_extra = GROUP_LABEL_MM if (isinstance(label, str) and label) else 1.4
        x0 = min(v["x"] for v in bs) - GROUP_PAD_MM
        y0 = min(v["y"] for v in bs) - top_extra
        x1 = max(v["x"] + v["w"] for v in bs) + GROUP_PAD_MM
        y1 = max(v["y"] + v["h"] for v in bs) + GROUP_PAD_MM
        x0 = max(x0, panel_box["x"] + 0.3)
        y0 = max(y0, panel_box["y"] + 0.3)
        x1 = min(x1, panel_box["x"] + panel_box["w"] - 0.3)
        y1 = min(y1, panel_box["y"] + panel_box["h"] - 0.3)
        if x1 - x0 < 2.0 or y1 - y0 < 2.0:
            continue
        band = _bbox(x0, y0, x1 - x0, y1 - y0)
        b.rect("panel", "panel-group", band, fill=GROUP_FILL, stroke=GROUP_STROKE,
               width=0.25, rx=1.0, panel=pid, group=gid)
        if not (isinstance(label, str) and label):
            continue
        box_w = band["w"] - 1.4
        if box_w <= 2.0 or measure.text_width_mm(label, oz, fs) + 0.4 > box_w:
            b.warn("W_GROUP_LABEL_TIGHT",
                   "group %r title does not fit its lane (%.1f mm needed, %.1f mm "
                   "available)" % (gid, measure.text_width_mm(label, oz, fs) + 0.4, box_w),
                   panel=pid)
            continue
        b.text("panel", "panel-group-label", label, band["x"] + 0.7, band["y"] + 0.2,
               box_w, 2.6, "legend", color=MUTED, valign="top", panel=pid,
               max_lines=1, allow_truncate=False)


def _emit_band(b, pid, band, charts, legend, colorbars, fs, sizes, cb, n_charts_row):
    """Chart band under the node grid; legend and colour bar stacked at the right."""
    items = [it for it in ((legend or {}).get("items") or []) if isinstance(it, dict)]
    plan_leg_w, plan_leg_h, ncol = (0.0, 0.0, 1)
    if items:
        plan_leg_w, plan_leg_h, ncol = _legend_need(legend, items, fs, sizes)
    plan_cb_w, plan_cb_h, _ = (0.0, 0.0, 0)
    if colorbars:
        plan_cb_w, plan_cb_h, _ = _cb_need(colorbars[0], fs, sizes, max(20.0, band["w"] * 0.55))
    right_w = min(max(plan_leg_w, plan_cb_w), band["w"] * 0.6)
    chart_w = max(CHART_MIN_W_MM, band["w"] - (right_w + BAND_GAP_MM if right_w else 0.0))
    if charts:
        n = max(1, min(n_charts_row or len(charts), len(charts)))
        while n > 1 and chart_w / n < CHART_MIN_W_MM:
            n -= 1
        rows = int(math.ceil(len(charts) / float(n)))
        col_w = (chart_w - (n - 1) * BAND_GAP_MM) / n
        rows = max(1, rows)
        row_h = (band["h"] - (rows - 1) * BAND_GAP_MM) / rows
        for i, chart in enumerate(charts):
            c, r = i % n, i // n
            box = _bbox(band["x"] + c * (col_w + BAND_GAP_MM),
                        band["y"] + r * (row_h + BAND_GAP_MM), col_w, max(6.0, row_h))
            _emit_chart(b, pid, chart, box, fs, sizes, legend, colorbars)
    if not right_w:
        return
    x = band["x"] + band["w"] - right_w
    y = band["y"]
    if items:
        lh = min(plan_leg_h, band["h"])
        _emit_legend(b, pid, legend, _bbox(x, y, right_w, lh), fs, sizes, ncol)
        y += lh + BAND_GAP_MM
    if colorbars:
        ch = min(plan_cb_h, max(6.0, band["y"] + band["h"] - y))
        _emit_colorbar(b, pid, colorbars[0], _bbox(x, y, right_w, ch), fs, sizes)


def _emit_side_column(b, pid, right, charts, legend, colorbars, fs, sizes, cb):
    items = [it for it in ((legend or {}).get("items") or []) if isinstance(it, dict)]
    _lw, leg_h, ncol = _legend_need(legend, items, fs, sizes) if items else (0.0, 0.0, 1)
    _cw, cb_h, _x = _cb_need(colorbars[0], fs, sizes, right["w"]) if colorbars else (0.0, 0.0, 0)
    leg_h = min(leg_h, right["h"] * 0.4)
    cb_h = min(cb_h, right["h"] * 0.4)
    reserved = (leg_h + (BAND_GAP_MM if items else 0.0) +
                cb_h + (BAND_GAP_MM if colorbars else 0.0))
    charts_total = max(0.0, right["h"] - reserved)
    y = right["y"]
    if charts and charts_total > 8.0:
        each = (charts_total - (len(charts) - 1) * BAND_GAP_MM) / len(charts)
        for chart in charts:
            _emit_chart(b, pid, chart, _bbox(right["x"], y, right["w"], max(6.0, each)),
                        fs, sizes, legend, colorbars)
            y += each + BAND_GAP_MM
    elif charts:
        _emit_chart(b, pid, charts[0], _bbox(right["x"], y, right["w"], right["h"] * 0.5),
                    fs, sizes, legend, colorbars)
        y += right["h"] * 0.5 + BAND_GAP_MM
    if items and leg_h > 0:
        _emit_legend(b, pid, legend, _bbox(right["x"], y, right["w"], leg_h), fs,
                     sizes, ncol)
        y += leg_h + BAND_GAP_MM
    if colorbars:
        _emit_colorbar(b, pid, colorbars[0],
                       _bbox(right["x"], y, right["w"], max(8.0, cb_h)), fs, sizes)


# --------------------------------------------------------------------------- #
# nodes
# --------------------------------------------------------------------------- #
def _shape_points(shape, b):
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    if shape == "hexagon":
        cut = min(w * 0.18, h * 0.5)
        return [[x + cut, y], [x + w - cut, y], [x + w, y + h / 2.0],
                [x + w - cut, y + h], [x + cut, y + h], [x, y + h / 2.0]]
    if shape == "diamond":
        return [[x + w / 2.0, y], [x + w, y + h / 2.0],
                [x + w / 2.0, y + h], [x, y + h / 2.0]]
    if shape == "note":
        fold = min(w * 0.18, h * 0.45)
        return [[x, y], [x + w - fold, y], [x + w, y + fold], [x + w, y + h],
                [x, y + h]]
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


PART_FILL = "#EEF3F9"
PART_ACCENT = "#C9D8E8"


def _draw_part(b, part, box, layer="entity", element="node-part", panel=None,
               evidence=None, node_id=None, ink=None, fill=None):
    """Draw a recognisable vector glyph for one apparatus `part` inside `box`.

    Built only from primitives every backend already rasterises (rect, rrect,
    circle, ellipse, polygon, line, polyline path) and every coordinate is
    confined to the box, so gate A holds and the PNG/PDF fallbacks cannot
    silently drop the symbol.  The label stays a real <text> drawn by the
    caller; the glyph never covers it.
    """
    if part not in part_types():
        return
    pad = min(0.22, box["w"] * 0.06, box["h"] * 0.06)
    x, y = box["x"] + pad, box["y"] + pad
    w = max(0.8, box["w"] - 2 * pad)
    h = max(0.8, box["h"] - 2 * pad)
    ink = ink or FRAME
    f = fill or PART_FILL
    acc = PART_ACCENT
    extra = {"part": part} if part else {}
    if node_id:
        extra["node_id"] = node_id
    base = dict(panel=panel, evidence=evidence)

    def P(u, v):
        return (_r(x + u * w), _r(y + v * h))

    def B(u0, v0, u1, v1):
        return _bbox(x + u0 * w, y + v0 * h, (u1 - u0) * w, (v1 - v0) * h)

    def rr(u0, v0, u1, v1, fill_=None, stroke=ink, wd=0.3, rx=None):
        b.rect(layer, element, B(u0, v0, u1, v1),
               fill=fill_ if fill_ is not None else "none", stroke=stroke,
               width=wd, rx=rx, **base, **extra)

    def ln(u0, v0, u1, v1, stroke=ink, wd=0.3):
        b.line(layer, element, P(u0, v0), P(u1, v1), stroke=stroke, width=wd,
               **base, **extra)

    def pg(pts, fill_=None, stroke=ink, wd=0.3):
        b.polygon(layer, element, [P(u, v) for u, v in pts],
                  fill=fill_ if fill_ is not None else "none", stroke=stroke,
                  width=wd, **base, **extra)

    def pl(pts, stroke=ink, wd=0.3):
        b.path(layer, element, [P(u, v) for u, v in pts], stroke=stroke,
               width=wd, **base, **extra)

    def ci(u, v, rad, fill_=None, stroke=ink, wd=0.3):
        b.circle(layer, element, x + u * w, y + v * h, rad * min(w, h),
                 fill=fill_ if fill_ is not None else "none", stroke=stroke,
                 width=wd, **base, **extra)

    def el(u, v, ru, rv, fill_=None, stroke=ink, wd=0.3):
        b.add(layer, "ellipse", B(u - ru, v - rv, 2 * ru, 2 * rv), element,
              style={"fill": fill_ if fill_ is not None else "none",
                     "stroke": stroke, "stroke_width_mm": _r(wd, 3)},
              cx=_r(x + u * w), cy=_r(y + v * h), rx=_r(ru * w), ry=_r(rv * h),
              **base, **extra)

    if part in ("vessel", "tank", "reservoir", "column", "generic"):
        if part == "vessel":
            el(0.50, 0.30, 0.30, 0.09, f)
            el(0.50, 0.86, 0.30, 0.08, f)
            rr(0.20, 0.30, 0.80, 0.86, f)
            ln(0.50, 0.05, 0.50, 0.30)
            ln(0.24, 0.64, 0.76, 0.64, stroke=acc, wd=0.5)
        elif part == "tank":
            el(0.17, 0.50, 0.09, 0.17, f)
            el(0.83, 0.50, 0.09, 0.17, f)
            rr(0.17, 0.33, 0.83, 0.67, f)
            ln(0.30, 0.67, 0.30, 0.90)
            ln(0.70, 0.67, 0.70, 0.90)
            ln(0.05, 0.32, 0.05, 0.50)
            ln(0.24, 0.58, 0.76, 0.58, stroke=acc, wd=0.5)
        elif part == "reservoir":
            rr(0.08, 0.34, 0.92, 0.86, f, rx=0.6)
            rr(0.40, 0.16, 0.60, 0.34, f)
            ln(0.12, 0.60, 0.88, 0.60, stroke=acc, wd=0.5)
            ln(0.30, 0.66, 0.30, 0.82, stroke=acc, wd=0.4)
            ln(0.50, 0.66, 0.50, 0.82, stroke=acc, wd=0.4)
            ln(0.70, 0.66, 0.70, 0.82, stroke=acc, wd=0.4)
        elif part == "column":
            rr(0.34, 0.10, 0.66, 0.90, f)
            el(0.50, 0.10, 0.16, 0.04, f)
            el(0.50, 0.90, 0.16, 0.04, f)
            for v in (0.28, 0.44, 0.60, 0.76):
                ln(0.34, v, 0.66, v, stroke=acc, wd=0.45)
            ln(0.50, 0.02, 0.50, 0.10)
            ln(0.00, 0.92, 0.30, 0.92, wd=0.35)
        else:
            rr(0.18, 0.22, 0.82, 0.78, f)
    elif part == "reactor":
        rr(0.22, 0.32, 0.78, 0.88, f)
        el(0.50, 0.32, 0.28, 0.08, f)
        el(0.50, 0.88, 0.28, 0.07, f)
        rr(0.42, 0.06, 0.58, 0.20, fill_=acc)
        ln(0.50, 0.20, 0.50, 0.78, wd=0.35)
        ln(0.30, 0.72, 0.70, 0.72, wd=0.45)
        ln(0.34, 0.84, 0.66, 0.84, wd=0.45)
    elif part == "pump":
        ci(0.50, 0.50, 0.32, f, wd=0.35)
        pg([(0.50, 0.50), (0.50, 0.24), (0.76, 0.50)], fill_=acc)
        pg([(0.50, 0.50), (0.50, 0.76), (0.24, 0.50)], fill_=acc)
        ln(0.00, 0.50, 0.18, 0.50)
        ln(0.50, 0.82, 0.50, 1.00)
    elif part in ("valve", "junction"):
        if part == "valve":
            pg([(0.14, 0.34), (0.14, 0.66), (0.50, 0.50)], fill_=f)
            pg([(0.86, 0.34), (0.86, 0.66), (0.50, 0.50)], fill_=f)
            ln(0.50, 0.34, 0.50, 0.16)
            ln(0.32, 0.16, 0.68, 0.16, wd=0.45)
            ln(0.00, 0.50, 0.14, 0.50)
            ln(0.86, 0.50, 1.00, 0.50)
        else:
            ln(0.04, 0.50, 0.96, 0.50, wd=0.8)
            ln(0.50, 0.50, 0.50, 0.96, wd=0.8)
            ci(0.50, 0.50, 0.10, fill_=acc, wd=0.3)
    elif part in ("sensor", "probe"):
        if part == "sensor":
            rr(0.28, 0.08, 0.72, 0.46, f, rx=0.4)
            ci(0.50, 0.27, 0.07, fill_=acc)
            ln(0.50, 0.46, 0.50, 0.74)
            ci(0.50, 0.80, 0.10, fill_=acc)
            ln(0.10, 0.10, 0.22, 0.02)
            ln(0.90, 0.10, 0.78, 0.02)
        else:
            rr(0.42, 0.04, 0.58, 0.16, fill_=acc)
            ln(0.50, 0.16, 0.50, 0.68, wd=0.45)
            pg([(0.38, 0.68), (0.62, 0.68), (0.50, 0.94)], fill_=f)
            ln(0.30, 0.36, 0.44, 0.36, wd=0.3)
            ln(0.56, 0.36, 0.70, 0.36, wd=0.3)
    elif part == "flask":
        pg([(0.50, 0.28), (0.14, 0.90), (0.86, 0.90)], fill_=f)
        rr(0.42, 0.06, 0.58, 0.30, f)
        ln(0.20, 0.72, 0.80, 0.72, stroke=acc, wd=0.5)
        ln(0.35, 0.06, 0.65, 0.06, wd=0.4)
    elif part == "mixer":
        rr(0.14, 0.14, 0.86, 0.86, f, rx=0.8)
        ln(0.24, 0.24, 0.76, 0.76, wd=0.4)
        ln(0.76, 0.24, 0.24, 0.76, wd=0.4)
        ci(0.50, 0.50, 0.09, fill_=acc)
    elif part == "separator":
        rr(0.14, 0.16, 0.86, 0.72, f)
        pl([(0.14, 0.50), (0.30, 0.44), (0.50, 0.52), (0.70, 0.44), (0.86, 0.50)],
           stroke=acc, wd=0.45)
        ln(0.50, 0.02, 0.50, 0.16)
        ln(0.32, 0.72, 0.32, 0.98)
        ln(0.68, 0.72, 0.68, 0.98)
        ln(0.18, 0.72, 0.82, 0.72, wd=0.35)
    elif part == "condenser":
        rr(0.32, 0.06, 0.68, 0.94, "none")
        pl([(0.40, 0.12), (0.60, 0.26), (0.40, 0.40), (0.60, 0.54),
            (0.40, 0.68), (0.60, 0.82)], stroke=acc, wd=0.45)
        ln(0.24, 0.74, 0.32, 0.74)
        ln(0.68, 0.22, 0.76, 0.22)
        ln(0.14, 0.18, 0.32, 0.18, wd=0.35)
        ln(0.68, 0.86, 0.86, 0.86, wd=0.35)
    elif part in ("heater", "cooler"):
        if part == "heater":
            rr(0.18, 0.08, 0.82, 0.56, f)
            ln(0.26, 0.56, 0.26, 0.64)
            ln(0.74, 0.56, 0.74, 0.64)
            pl([(0.26, 0.64), (0.38, 0.82), (0.50, 0.64), (0.62, 0.82), (0.74, 0.64)],
               stroke=acc, wd=0.5)
        else:
            rr(0.16, 0.10, 0.84, 0.60, f)
            for u0, u1 in ((0.26, 0.20), (0.50, 0.44), (0.74, 0.68)):
                ln(u0, 0.64, u1, 0.94, stroke=acc, wd=0.5)
            ln(0.06, 0.35, 0.16, 0.35, wd=0.35)
            ln(0.84, 0.35, 0.94, 0.35, wd=0.35)
    elif part == "sample":
        rr(0.36, 0.14, 0.64, 0.92, f, rx=0.5)
        rr(0.32, 0.04, 0.68, 0.16, fill_=acc)
        rr(0.36, 0.56, 0.64, 0.90, fill_=acc, stroke=ink, wd=0.25)
    elif part == "reagent":
        rr(0.24, 0.30, 0.76, 0.92, f, rx=0.5)
        rr(0.42, 0.12, 0.58, 0.30, f)
        rr(0.38, 0.03, 0.62, 0.13, fill_=acc)
        rr(0.28, 0.46, 0.72, 0.64, fill_=acc, stroke=ink, wd=0.25)
    elif part == "waste":
        pg([(0.26, 0.28), (0.74, 0.28), (0.68, 0.92), (0.32, 0.92)], fill_=f)
        rr(0.18, 0.18, 0.82, 0.30, fill_=acc)
        ln(0.38, 0.44, 0.62, 0.74, stroke=acc, wd=0.45)
        ln(0.62, 0.44, 0.38, 0.74, stroke=acc, wd=0.45)
    elif part == "instrument":
        rr(0.10, 0.06, 0.90, 0.60, f, rx=0.5)
        rr(0.20, 0.16, 0.80, 0.44, fill_=acc)
        pl([(0.26, 0.38), (0.38, 0.26), (0.50, 0.34), (0.64, 0.20), (0.74, 0.24)],
           stroke=ink, wd=0.4)
        ci(0.28, 0.52, 0.05, fill_=acc)
        ci(0.42, 0.52, 0.05, fill_=acc)
        ln(0.50, 0.60, 0.50, 0.82)
        ln(0.30, 0.86, 0.70, 0.86, wd=0.45)


def _emit_nodes_only(b, pid, nodes, boxes, fs, sizes, cb):
    for node in nodes:
        box = boxes.get(node.get("id"))
        if box is not None:
            _emit_node(b, pid, node, box, fs, sizes, cb)


def _emit_node(b, pid, node, box, fs, sizes, cb):
    nid = node.get("id")
    shape = _shape_of(node)
    ev = b.evidence_for(node)
    val = node.get("value")
    fill = NEUTRAL_FILL
    if isinstance(val, (int, float)) and not isinstance(val, bool) and cb:
        vmin, vmax = float(cb.get("vmin", 0.0)), float(cb.get("vmax", 1.0))
        t = (float(val) - vmin) / (vmax - vmin) if vmax > vmin else 0.0
        fill = cmap_color(cb.get("cmap"), t)
    ink = ink_on(fill)
    stroke = FRAME
    common = dict(panel=pid, evidence=ev, node_id=nid, shape=shape,
                  part=node_part(node), step_no=node.get("step_no"),
                  branch=node.get("branch"), phase=node.get("stage"),
                  value=val if isinstance(val, (int, float)) and not isinstance(val, bool) else None,
                  unit=node.get("unit"), fill=fill)

    if shape in ("circle", "ellipse"):
        d = min(box["h"] * 0.36, box["w"] * 0.22, 9.0)
        cx, cy = box["x"] + 1.2 + d, box["y"] + box["h"] / 2.0
        common_s = {k: v for k, v in common.items() if k != "fill"}
        if shape == "circle":
            b.circle("entity", "node-shape", cx, cy, d, fill=fill, stroke=stroke,
                     width=0.45, **common_s)
        else:
            b.add("entity", "ellipse",
                  _bbox(cx - d, cy - d * 0.86, 2 * d, 2 * d * 0.86), "node-shape",
                  panel=pid, evidence=ev,
                  style={"fill": fill, "stroke": stroke, "stroke_width_mm": 0.45},
                  cx=_r(cx), cy=_r(cy), rx=_r(d), ry=_r(d * 0.86), node_id=nid,
                  shape=shape, fill=fill, unit=node.get("unit"))
    elif shape in ("hexagon", "diamond", "note"):
        b.polygon("entity", "node-shape", _shape_points(shape, box), fill=fill,
                  stroke=stroke, width=0.45,
                  **{k: v for k, v in common.items() if k != "fill"})
    else:
        rx = None
        if shape == "capsule":
            rx = min(box["h"] / 2.0, box["w"] / 2.0)
        elif shape == "rrect":
            rx = 1.0
        b.rect("entity", "node-shape", box, fill=fill, stroke=stroke, width=0.45,
               rx=rx, **{k: v for k, v in common.items() if k != "fill"})

    if node.get("terminal"):
        # terminator: a heavier double frame, the flowchart convention for
        # "start/end here" — it reads even at 7 pt without any extra text.
        b.rect("entity", "node-terminal", _inset(box, 0.35, 0.35), fill="none",
               stroke=FRAME, width=0.6, rx=1.2, panel=pid, evidence=ev,
               node_id=nid)

    sp = sp_of(sizes)
    ins = sp["node_pad_y"]
    inset = _inset_x(shape, box["w"])
    left_extra = 0.0
    part = node_part(node)
    if part is not None:
        # apparatus glyph on the left, real <text> label on the right; the
        # widths come from part_glyph_w() so _node_metrics reserved the same box
        gw = part_glyph_w(box["w"])
        gh = min(gw, max(1.2, box["h"] - 1.4))
        gbox = _bbox(box["x"] + inset + 0.4, box["y"] + (box["h"] - gh) / 2.0, gw, gh)
        _draw_part(b, part, gbox, panel=pid, evidence=ev, node_id=nid)
        left_extra = gw + PART_GLYPH_GAP_MM
        inner_w = max(4.0, box["w"] - inset - left_extra - 0.4)
    elif shape in ("circle", "ellipse"):
        d = min(box["h"] * 0.36, box["w"] * 0.22, 9.0)
        left_extra = 2 * d + 1.4
        inset = 1.0
        inner_w = max(2.0, box["w"] - 2 * inset - left_extra)
    else:
        inner_w = max(2.0, box["w"] - 2 * inset - left_extra)
    inner = _bbox(box["x"] + inset + left_extra, box["y"] + ins, inner_w,
                  max(1.5, box["h"] - 2 * ins))
    lead = sp["label_leading"]
    lh_l = measure.line_height_mm(sizes["node_label"], lead)
    lh_s = measure.line_height_mm(sizes["node_sub"], lead)
    sub = node.get("sublabel")
    label = str(node.get("label") or "")
    l_lines, l_h, _ = _wrap_need(label, sizes["node_label"], fs, inner["w"], lead, True)
    s_lines, s_h = [], 0.0
    if sub:
        s_lines, s_h, _ = _wrap_need(str(sub), sizes["node_sub"], fs, inner["w"], lead)
    avail = inner["h"]
    gap = 0.25
    if s_lines:
        if l_h + gap + s_h <= avail + 1e-9:
            l_box, s_box = l_h, s_h
        else:
            l_box = min(l_h, max(lh_l, avail - gap - lh_s))
            s_box = avail - gap - l_box
            if s_box < lh_s:
                s_box = 0.0
                l_box = avail
        top = inner["y"] + max(0.0, (avail - (l_box + (gap + s_box if s_box else 0.0))) / 2.0)
        b.text("entity", "node-label", label, inner["x"], top, inner["w"], l_box + 0.1,
               "node_label", bold=True, color=ink, align="center", panel=pid,
               evidence=ev, background=fill, leading=lead, allow_truncate=True)
        if s_box:
            b.text("entity", "node-sublabel", str(sub), inner["x"], top + l_box + gap,
                   inner["w"], s_box + 0.1, "node_sub", color=ink, align="center",
                   panel=pid, evidence=ev, background=fill, leading=lead,
                   allow_truncate=True)
    else:
        b.text("entity", "node-label", label, inner["x"], inner["y"], inner["w"],
               inner["h"], "node_label", bold=True, color=ink, align="center",
               valign="middle", panel=pid, evidence=ev, background=fill,
               leading=lead, allow_truncate=True)


# --------------------------------------------------------------------------- #
# edges (typed as arrows, one primitive per spec edge)
# --------------------------------------------------------------------------- #
def _side_of(src, dst):
    scx, scy = src["x"] + src["w"] / 2.0, src["y"] + src["h"] / 2.0
    dcx, dcy = dst["x"] + dst["w"] / 2.0, dst["y"] + dst["h"] / 2.0
    dx, dy = dcx - scx, dcy - scy
    if abs(dx) >= abs(dy):
        return ("right" if dx >= 0 else "left"), ("left" if dx >= 0 else "right")
    return ("bottom" if dy >= 0 else "top"), ("top" if dy >= 0 else "bottom")


def _anchor(box, side, frac):
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    if side == "right":
        return (x + w, y + h * frac)
    if side == "left":
        return (x, y + h * frac)
    if side == "bottom":
        return (x + w * frac, y + h)
    return (x + w * frac, y)


def _orthogonal(p0, out_side, p1, in_side):
    h_out = out_side in ("left", "right")
    h_in = in_side in ("left", "right")
    if h_out and h_in:
        midx = (p0[0] + p1[0]) / 2.0
        return [p0, (midx, p0[1]), (midx, p1[1]), p1]
    if (not h_out) and (not h_in):
        midy = (p0[1] + p1[1]) / 2.0
        return [p0, (p0[0], midy), (p1[0], midy), p1]
    if h_out and not h_in:
        return [p0, (p1[0], p0[1]), p1]
    return [p0, (p0[0], p1[1]), p1]


def _loop_lane(area, boxes, side=None):
    """Lane for `loop_to` return lines: side, coordinate and room (mm).

    `side` is the lane the layout reserved (see ``_loop_reserve``); without one
    the side with the most measured free space wins.  Keeping the return line in
    a reserved lane is what makes it read as a recycle loop instead of a stray
    scribble across the flow.
    """
    default = {"side": "bottom", "coord": area["y"] + area["h"] - LOOP_LANE_MM,
               "room": 0.0, "bounds": (area["x"], area["y"],
                                       area["x"] + area["w"], area["y"] + area["h"])}
    if not boxes:
        return default
    lefts = min(b["x"] for b in boxes.values())
    rights = max(b["x"] + b["w"] for b in boxes.values())
    tops = min(b["y"] for b in boxes.values())
    bots = max(b["y"] + b["h"] for b in boxes.values())
    room = {"bottom": (area["y"] + area["h"]) - bots,
            "right": (area["x"] + area["w"]) - rights,
            "left": lefts - area["x"],
            "top": tops - area["y"]}
    if side not in room:
        side = "bottom"
        for cand in ("bottom", "right", "left", "top"):
            if room[cand] > room[side] + 1e-9:
                side = cand
    if side == "bottom":
        coord = min(area["y"] + area["h"] - 0.4, bots + LOOP_LANE_MM)
    elif side == "right":
        coord = min(area["x"] + area["w"] - 0.4, rights + LOOP_LANE_MM)
    elif side == "left":
        coord = max(area["x"] + 0.4, lefts - LOOP_LANE_MM)
    else:
        coord = max(area["y"] + 0.4, tops - LOOP_LANE_MM)
    return {"side": side, "coord": coord, "room": room[side],
            "bounds": (lefts, tops, rights, bots)}


def _loop_points(p0, p1, side, coord):
    if side in ("bottom", "top"):
        return [p0, (p0[0], coord), (p1[0], coord), p1]
    return [p0, (coord, p0[1]), (coord, p1[1]), p1]


def _retract(pts, gap):
    """Pull the end point back by `gap`: an arrow head must not enter the node."""
    out = [(float(p[0]), float(p[1])) for p in pts]
    if len(out) < 2 or gap <= 0:
        return out
    dx = out[-1][0] - out[-2][0]
    dy = out[-1][1] - out[-2][1]
    length = math.hypot(dx, dy)
    if length <= gap + 1e-6:
        return out
    out[-1] = (_r(out[-1][0] - dx / length * gap),
               _r(out[-1][1] - dy / length * gap))
    return out


def _draw_head(b, layer, element, tip, dirv, head, color, panel, ev, extra=None,
               width=None):
    """One connector arrow head — shared by the drawing *and* the legend sample.

    `head` is solid / triangle (filled), hollow (open triangle), dot (signal),
    bar (inhibition) or none.  Names are normalised through ``_norm_head`` so
    scene.EDGE_VISUALS ("hollow", "bar", "triangle") and the older aliases
    ("open", "tbar") cannot silently degrade to a filled triangle.
    """
    extra = dict(extra or {})
    head = _norm_head(head)
    if head == "none":
        return
    if element is None:
        element = "edge-tbar" if head == "bar" else "edge-arrowhead"
    length = math.hypot(dirv[0], dirv[1]) or 1.0
    ux, uy = dirv[0] / length, dirv[1] / length
    px, py = -uy, ux
    lw = float(width or EDGE_W_MM)
    if head == "bar":
        half = EDGE_HEAD_MM * 0.6
        b.line(layer, element, (_r(tip[0] + px * half), _r(tip[1] + py * half)),
               (_r(tip[0] - px * half), _r(tip[1] - py * half)), stroke=color,
               width=lw * 1.7, panel=panel, evidence=ev, **extra)
        return
    if head == "dot":
        b.circle(layer, element, tip[0], tip[1], EDGE_HEAD_MM * 0.34, fill=color,
                 stroke=color, width=0.1, panel=panel, evidence=ev, **extra)
        return
    ax = tip[0] - ux * EDGE_HEAD_MM
    ay = tip[1] - uy * EDGE_HEAD_MM
    half = EDGE_HEAD_MM * 0.45
    pts = [tip, (ax + px * half, ay + py * half), (ax - px * half, ay - py * half)]
    if head == "hollow":
        b.polygon(layer, element, pts, fill=PAGE_BG, stroke=color, width=0.25,
                  panel=panel, evidence=ev, **extra)
    else:
        # "solid" (material) and "triangle" (energy/heat) are both filled; they
        # are told apart by the stroke pattern the kind demands, as §3.5 says.
        b.polygon(layer, element, pts, fill=color, stroke=color, width=0.1,
                  panel=panel, evidence=ev, **extra)


def _shrink_box(box, d=0.12):
    """A box inset by `d`; a segment along an edge is not "through" the node."""
    return {"x": box["x"] + d, "y": box["y"] + d,
            "w": max(0.05, box["w"] - 2 * d), "h": max(0.05, box["h"] - 2 * d)}


def _seg_hits_box(a, b, box, pad=0.0):
    x0, x1 = (a[0], b[0]) if a[0] <= b[0] else (b[0], a[0])
    y0, y1 = (a[1], b[1]) if a[1] <= b[1] else (b[1], a[1])
    return not (x1 < box["x"] - pad or x0 > box["x"] + box["w"] + pad
                or y1 < box["y"] - pad or y0 > box["y"] + box["h"] + pad)


def _route_clear(pts, obstacles):
    for i in range(len(pts) - 1):
        for o in obstacles:
            if _seg_hits_box(pts[i], pts[i + 1], o):
                return False
    return True


def _route_len(pts):
    return sum(abs(pts[i + 1][0] - pts[i][0]) + abs(pts[i + 1][1] - pts[i][1])
               for i in range(len(pts) - 1))


def _route_around(p0, out_side, p1, in_side, obstacles, area, ends=None):
    """Orthogonal route that does not run through a node box.

    The plain 3/4-segment route is tried first (it is what v1 always drew).
    When it would cross a node, the line is detoured around *just the boxes it
    hit* — a tight local jog — and only if that is still blocked around the
    whole node set.  Without this a backward edge in a grid panel is drawn
    straight through the nodes between its endpoints and its label lands on a
    node (the single most visible topology defect).

    Obstacles are inset by a hair so a line that grazes a box border counts as
    clear: rejecting those turned every candidate into a "hit" and the router
    silently fell back to the crossing route.
    """
    solid = [_shrink_box(o) for o in ((ends or []) + list(obstacles))]
    base = _orthogonal(p0, out_side, p1, in_side)
    if not solid or _route_clear(base, solid):
        return base
    hits = [o for o in obstacles if not _route_clear(base, [_shrink_box(o)])]
    rings = []
    if hits:
        rings.append((min(o["x"] for o in hits) - 2.0, max(o["x"] + o["w"] for o in hits) + 2.0,
                      min(o["y"] for o in hits) - 2.0, max(o["y"] + o["h"] for o in hits) + 2.0))
    rings.append((min(o["x"] for o in obstacles) - 2.2,
                  max(o["x"] + o["w"] for o in obstacles) + 2.2,
                  min(o["y"] for o in obstacles) - 2.2,
                  max(o["y"] + o["h"] for o in obstacles) + 2.2))
    best = None
    for lx0, rx0, ty0, by0 in rings:
        lx = max(area["x"] + 0.4, lx0)
        rx = min(area["x"] + area["w"] - 0.4, rx0)
        ty = max(area["y"] + 0.4, ty0)
        by = min(area["y"] + area["h"] - 0.4, by0)
        for cand in ([p0, (lx, p0[1]), (lx, p1[1]), p1],
                     [p0, (rx, p0[1]), (rx, p1[1]), p1],
                     [p0, (p0[0], ty), (p1[0], ty), p1],
                     [p0, (p0[0], by), (p1[0], by), p1],
                     # two-corner routes: escape through a lane, then over/under
                     [p0, (p0[0], ty), (lx, ty), (lx, p1[1]), p1],
                     [p0, (p0[0], by), (lx, by), (lx, p1[1]), p1],
                     [p0, (p0[0], ty), (rx, ty), (rx, p1[1]), p1],
                     [p0, (p0[0], by), (rx, by), (rx, p1[1]), p1],
                     [p0, (lx, p0[1]), (lx, ty), (p1[0], ty), p1],
                     [p0, (lx, p0[1]), (lx, by), (p1[0], by), p1],
                     [p0, (rx, p0[1]), (rx, ty), (p1[0], ty), p1],
                     [p0, (rx, p0[1]), (rx, by), (p1[0], by), p1]):
            if not _route_clear(cand, solid):
                continue
            length = _route_len(cand)
            if best is None or length < best[0] - 1e-9:
                best = (length, cand)
        if best is not None:
            break
    return best[1] if best else base


def _port_side(port):
    """The box side a declared port sits on, or None when it is not usable.

    A port is advisory: an unknown side, a missing id or a non-dict entry must
    never abort the build.  There is no search here — callers pass a prebuilt
    id -> side dict, so a bogus port id costs one dict miss (bounded, O(1)).
    """
    if not isinstance(port, dict):
        return None
    side = port.get("side")
    sides = getattr(scene, "PORT_SIDES", ("left", "right", "top", "bottom"))
    if isinstance(side, str) and side.strip().lower() in tuple(sides):
        return side.strip().lower()
    return None


def port_sides(nodes):
    """{node_id: {port_id: side}} — one bounded pass, no lookups later."""
    out = {}
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        nid = node.get("id")
        ports = node.get("ports")
        if not isinstance(nid, str) or not isinstance(ports, list):
            continue
        table = {}
        for port in ports:
            if not isinstance(port, dict):
                continue
            pid = port.get("id")
            if isinstance(pid, str) and pid:
                side = _port_side(port)
                if side is not None:
                    table[pid] = side
        if table:
            out[nid] = table
    return out


def edge_port_refs(edge):
    """(from_port, to_port) named by an edge, accepting both §3.5 shapes."""
    refs = edge.get("ports") if isinstance(edge, dict) else None
    if isinstance(refs, list) and len(refs) == 2 and all(isinstance(v, str) and v for v in refs):
        return refs[0], refs[1]
    if isinstance(refs, dict):
        a, b = refs.get("from"), refs.get("to")
        if isinstance(a, str) and a and isinstance(b, str) and b:
            return a, b
    return None, None


def _emit_edges(b, pid, edges, boxes, area, fs, sizes, declared=None, nodemap=None,
                loop_side=None, ports=None):
    declared = declared or {}
    nodemap = nodemap or {}
    routed = []
    for ei, edge in enumerate(edges):
        src, dst = boxes.get(edge.get("from")), boxes.get(edge.get("to"))
        if src is None or dst is None:
            b.warn("W_EDGE_DANGLING", "edge %s references a node missing from the "
                   "layout" % edge.get("id"), panel=pid)
            continue
        kind = edge.get("kind") or "flow"
        styled = resolve_edge_style(edge, kind=kind, declared=declared.get(kind))
        routed.append([ei, edge, src, dst, styled, None, None, False])

    lane = _loop_lane(area, boxes, loop_side)
    ports = ports or {}
    for row in routed:
        edge, styled = row[1], row[4]
        src_node = nodemap.get(edge.get("from")) or {}
        node_loop = isinstance(src_node, dict) and src_node.get("loop_to") == edge.get("to")
        is_loop = bool(styled["return"]) and (node_loop or edge.get("loop_to") is not None
                                              or styled["kind"] == "loop")
        if is_loop:
            row[5] = row[6] = lane["side"]
        else:
            out_side, in_side = _side_of(row[2], row[3])
            fp, tp = edge_port_refs(edge)
            if fp or tp:
                # declared ports win, so a connector leaves/enters the node where
                # the apparatus description says it does (contract §3.5)
                f_tab = ports.get(edge.get("from")) or {}
                t_tab = ports.get(edge.get("to")) or {}
                if fp:
                    if fp in f_tab:
                        out_side = f_tab[fp]
                    else:
                        b.warn("W_PORT_UNKNOWN",
                               "edge %s names from-port %r but node %s declares no such "
                               "port; using the nearest side" % (edge.get("id"), fp,
                                                                 edge.get("from")), panel=pid)
                if tp:
                    if tp in t_tab:
                        in_side = t_tab[tp]
                    else:
                        b.warn("W_PORT_UNKNOWN",
                               "edge %s names to-port %r but node %s declares no such "
                               "port; using the nearest side" % (edge.get("id"), tp,
                                                                 edge.get("to")), panel=pid)
            row[5], row[6] = out_side, in_side
        row[7] = is_loop

    groups = {}
    for ei, edge, _src, _dst, _st, out_side, in_side, _is_loop in routed:
        groups.setdefault((edge.get("from"), out_side), []).append(ei)
        groups.setdefault((edge.get("to"), in_side), []).append(ei)

    def frac_for(node_id, side, ei):
        members = groups.get((node_id, side)) or [ei]
        m = len(members)
        if m <= 1:
            return 0.5
        k = members.index(ei) if ei in members else 0
        span = min(0.36, 0.13 * (m - 1))
        return (0.5 - span) + (2 * span) * k / float(m - 1)

    loop_seen = 0
    for ei, edge, src, dst, styled, out_side, in_side, is_loop in routed:
        kind = styled["kind"]
        ev = b.evidence_for(edge)
        p0 = _anchor(src, out_side, frac_for(edge.get("from"), out_side, ei))
        p1 = _anchor(dst, in_side, frac_for(edge.get("to"), in_side, ei))
        attrs = dict(edge_id=edge.get("id"), edge_kind=kind, kind=kind,
                     **{"from": edge.get("from"), "to": edge.get("to")})
        heads = list(styled["heads"])
        if is_loop:
            step = loop_seen * 2.2
            coord = lane["coord"]
            if lane["side"] in ("bottom", "right"):
                coord = min(area["x"] + area["w"] - 0.4 if lane["side"] == "right"
                            else area["y"] + area["h"] - 0.4, coord + step)
            else:
                coord = max(area["x"] + 0.4 if lane["side"] == "left" else area["y"] + 0.4,
                            coord - step)
            pts = _loop_points(p0, p1, lane["side"], coord)
            loop_seen += 1
        else:
            obstacles = [b for k, b in boxes.items()
                         if k != edge.get("from") and k != edge.get("to")]
            solid = [_shrink_box(o) for o in obstacles + [src, dst]]
            pts = _route_around(p0, out_side, p1, in_side, obstacles, area,
                                ends=[src, dst])
            if not _route_clear(pts, solid):
                # A declared port whose side would force the connector across a
                # node is honoured only when it can actually be drawn.  Falling
                # back to the facing side keeps every edge drawable (the earlier
                # port-free behaviour, measured at 0 node crossings).
                ao, ai = _side_of(src, dst)
                if (ao, ai) != (out_side, in_side):
                    q0 = _anchor(src, ao, frac_for(edge.get("from"), ao, ei))
                    q1 = _anchor(dst, ai, frac_for(edge.get("to"), ai, ei))
                    alt = _route_around(q0, ao, q1, ai, obstacles, area,
                                        ends=[src, dst])
                    if _route_clear(alt, solid):
                        b.warn("W_PORT_ROUTE_FALLBACK",
                               "edge %s: drawing from the declared port side would "
                               "cross a node, so it uses the facing side "
                               "(%s->%s instead of %s->%s)"
                               % (edge.get("id"), ao, ai, out_side, in_side), panel=pid)
                        out_side, in_side, p0, p1, pts = ao, ai, q0, q1, alt
                        groups.setdefault((edge.get("from"), out_side), []).append(ei)
                        groups.setdefault((edge.get("to"), in_side), []).append(ei)

        if styled["curve"] and not is_loop:
            ctrl = _feedback_controls(p0, p1, out_side)
            nums = [float(v) for v in ctrl.split()]   # c1x c1y c2x c2y p1x p1y
            samples = [p0] + _flat_cubic(p0, (nums[0], nums[1]), (nums[2], nums[3]), p1)
            curve_pts = samples + [p1]
            # a cubic bulges freely, so it can cut straight through a node that
            # the orthogonal router would have gone around: keep the curve only
            # when it is clear, otherwise fall back to the routed polyline.
            solid = [_shrink_box(box) for box in boxes.values()]
            if not _route_clear(curve_pts, solid):
                b.warn("W_EDGE_CURVE_FALLBACK",
                       "edge %s: the curved feedback path would cross a node, drawn "
                       "orthogonally instead" % edge.get("id"), panel=pid)
            else:
                pts = curve_pts
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            # 8 placeholders for 8 values: M p0x p0y, then the 6 cubic numbers,
            # which already end at p1 (appending p1 again raised TypeError and
            # made every `feedback` edge fail the whole build with exit 2).
            b.path("relation", "edge-line", pts, stroke=styled["color"],
                   width=styled["width"], panel=pid, evidence=ev,
                   dash=styled["dash"] or None, ptype="arrow",
                   bbox=_bbox(min(xs) - 0.5, min(ys) - 0.5,
                              max(xs) - min(xs) + 1.0, max(ys) - min(ys) + 1.0),
                   d="M %s %s C %s %s %s %s %s %s"
                   % (_r(p0[0]), _r(p0[1]), *[_r(v) for v in nums]),
                   cubic=[[nums[0], nums[1]], [nums[2], nums[3]]], **attrs)
        else:
            if any(w == "end" for w, _h in heads):
                pts = _retract(pts, EDGE_TIP_GAP_MM)
            if any(w == "start" for w, _h in heads):
                pts = list(reversed(_retract(list(reversed(pts)), EDGE_TIP_GAP_MM)))
            if len(pts) < 2:
                continue
            b.path("relation", "edge-line", pts, stroke=styled["color"],
                   width=styled["width"], panel=pid, evidence=ev,
                   dash=styled["dash"] or None, ptype="arrow", **attrs)

        src_pair = {"from": edge.get("from"), "to": edge.get("to")}
        for where, head in heads:
            if where == "end":
                tip, nxt = pts[-1], pts[-2]
            else:
                tip, nxt = pts[0], pts[1]
            dirv = (tip[0] - nxt[0], tip[1] - nxt[1])
            if abs(dirv[0]) < 1e-9 and abs(dirv[1]) < 1e-9:
                dirv = (1.0, 0.0)
            _draw_head(b, "relation", None, tip, dirv, head, styled["color"],
                       pid, ev, extra=dict(edge_id=edge.get("id"),
                                           edge_kind=kind, **src_pair),
                       width=styled["width"])
        if edge.get("label"):
            _emit_edge_label(b, pid, edge, pts, area, fs, sizes, ev, boxes)


def _flat_cubic(p0, c1, c2, p1, steps=18):
    out = []
    for i in range(1, steps):
        t = i / float(steps)
        mt = 1.0 - t
        out.append(((mt ** 3) * p0[0] + 3 * (mt ** 2) * t * c1[0] +
                    3 * mt * (t ** 2) * c2[0] + (t ** 3) * p1[0],
                    (mt ** 3) * p0[1] + 3 * (mt ** 2) * t * c1[1] +
                    3 * mt * (t ** 2) * c2[1] + (t ** 3) * p1[1]))
    return out


def _feedback_controls(p0, p1, out_side):
    if out_side in ("left", "right"):
        bulge = 9.0 if out_side == "right" else -9.0
        c1 = (p0[0] + bulge, p0[1] - 4.0)
        c2 = (p1[0] - bulge, p1[1] - 4.0)
    else:
        bulge = 7.0 if out_side == "bottom" else -7.0
        c1 = (p0[0] - 4.0, p0[1] + bulge)
        c2 = (p1[0] - 4.0, p1[1] - bulge)
    return "%s %s %s %s %s %s" % (_r(c1[0]), _r(c1[1]), _r(c2[0]), _r(c2[1]),
                                  _r(p1[0]), _r(p1[1]))


def _boxes_hit(box, others, pad=0.15):
    """Total overlap area of `box` with any of `others`."""
    total = 0.0
    for o in others:
        x = min(box["x"] + box["w"] + pad, o["x"] + o["w"] + pad) - max(box["x"] - pad, o["x"] - pad)
        y = min(box["y"] + box["h"] + pad, o["y"] + o["h"] + pad) - max(box["y"] - pad, o["y"] - pad)
        if x > 0 and y > 0:
            total += x * y
    return total


def _emit_edge_label(b, pid, edge, pts, area, fs, sizes, ev, node_boxes=None):
    """Label plate for one connector, placed *beside* its line.

    A plate centred on its own segment hides that segment — a labelled recycle
    lane then reads as if the return line were missing.  So every segment is
    tried (longest first) with a perpendicular step that fully clears the line
    (`tw/2` across a vertical line, `th/2` above a horizontal one); a candidate
    that has to be clamped back into `area` is penalised, because clamping is
    exactly what pulls the plate back onto the line.
    """
    txt = str(edge.get("label"))
    if not txt:
        return
    segs = []
    for i in range(len(pts) - 1):
        L = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        if L > 1e-9:
            segs.append((L, i))
    if not segs:
        return
    segs.sort(key=lambda t: (-t[0], t[1]))
    tw = measure.text_width_mm(txt, sizes["edge_label"], fs) + 1.2
    th = measure.line_height_mm(sizes["edge_label"], 1.15)
    others = [v for k, v in (node_boxes or {}).items()]
    chosen = None
    for length, i in segs:
        a, c = pts[i], pts[i + 1]
        dx, dy = c[0] - a[0], c[1] - a[1]
        mx, my = (a[0] + c[0]) / 2.0, (a[1] + c[1]) / 2.0
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        gap = (tw / 2.0 if abs(dy) > abs(dx) else th / 2.0) + 0.5
        for along in (0.0, -0.22, 0.22, -0.36, 0.36):
            for off in (gap, -gap, 0.0, gap + th, -(gap + th)):
                cx2 = mx + ux * along * length + px * off
                cy2 = my + uy * along * length + py * off
                raw_x = cx2 - tw / 2.0
                raw_y = cy2 - th / 2.0
                cl_x = _clamp(raw_x, area["x"], area["x"] + area["w"] - tw)
                cl_y = _clamp(raw_y, area["y"], area["y"] + area["h"] - th)
                cand = _bbox(cl_x, cl_y, tw, th)
                score = (_boxes_hit(cand, others)
                         + 0.002 * (abs(cl_x - raw_x) + abs(cl_y - raw_y)))
                # a plate painted over its OWN connector hides that connector:
                # the recycle lane then looks like it was never drawn.  Test the
                # plate rectangle against the line segments, not the plate border.
                for k in range(len(pts) - 1):
                    if _seg_hits_box(pts[k], pts[k + 1], cand):
                        score += 50.0
                        break
                if chosen is None or score < chosen[0] - 1e-12:
                    chosen = (score, cand)
                if score <= 1e-9:
                    break
            if chosen is not None and chosen[0] <= 1e-9:
                break
        if chosen is not None and chosen[0] <= 1e-9:
            break
    if chosen is None:
        return
    score, cand = chosen
    if score > 1e-9:
        b.warn("W_EDGE_LABEL_TIGHT",
               "edge %s label %r could not fully clear the node boxes "
               "(%.1f mm2 overlap)" % (edge.get("id"), txt, score), panel=pid)
    x, y = cand["x"], cand["y"]
    b.rect("relation", "edge-label-bg", _bbox(x, y, tw, th), fill=PAGE_BG,
           stroke="none", width=0.0, panel=pid, evidence=ev,
           edge_id=edge.get("id"), edge_kind=edge.get("kind") or "flow")
    b.text("relation", "edge-label", txt, x, y, tw, th, "edge_label", color=MUTED,
           align="center", valign="middle", panel=pid, evidence=ev,
           background=PAGE_BG, allow_truncate=False)


# --------------------------------------------------------------------------- #
# charts
# --------------------------------------------------------------------------- #
def _series_evidence(b, series):
    out = []
    for s in series:
        out.extend(b.evidence_for(s))
    return out


def _color_map(legend, n_series):
    """One colour map shared by chart series and legend swatches.

    Explicit legend colours win; otherwise both come from the same
    ``scene.categorical_colors`` call, so a series and the swatch that labels
    it can never drift apart (gate D pairs them).
    """
    items = [it for it in ((legend or {}).get("items") or []) if isinstance(it, dict)]
    fallback = scene.categorical_colors(max(len(items), n_series, 1))
    out = {}
    for i, it in enumerate(items):
        label = str(it.get("label") or "")
        out[label.strip().lower()] = it.get("color") or fallback[i % len(fallback)]
    return out


def _series_colors(chart, color_map, n_series):
    fallback = scene.categorical_colors(max(n_series, 1))
    out = []
    for i, s in enumerate(chart.get("series") or []):
        name = str((s or {}).get("name", "")).strip().lower()
        out.append(color_map.get(name) or fallback[i % len(fallback)])
    return out


def _emit_chart(b, pid, chart, box, fs, sizes, legend, colorbars):
    cid = chart.get("id")
    ctype = chart.get("type") or "bar"
    title = str(chart.get("title") or cid or "chart")
    unit = str(chart.get("unit") or "").strip()
    series = [s for s in (chart.get("series") or []) if isinstance(s, dict)]
    color_map = _color_map(legend, len(series))
    colors = _series_colors(chart, color_map, len(series))
    ev = _series_evidence(b, series)
    b.add("chart", "chart", box, "chart-frame", panel=pid, evidence=ev,
          style={"fill": PAGE_BG, "stroke": GRID, "stroke_width_mm": 0.25},
          chart_id=cid, chart_type=ctype, title=title, chart_unit=unit,
          categories=list(chart.get("categories") or []),
          x={"label": (chart.get("x") or {}).get("label"),
             "values": list((chart.get("x") or {}).get("values") or [])},
          series=[{"name": s.get("name"), "values": list(s.get("values") or []),
                   "color": colors[i], "evidence": _series_evidence(b, [s])}
                  for i, s in enumerate(series)])

    pad_x = 1.0
    tw = max(4.0, box["w"] - 2 * pad_x)
    # The required string is "<title> (<unit>)".  It is never truncated: the
    # box grows to as many lines as it needs, and the plot area shrinks instead.
    title_txt = title if not unit else "%s (%s)" % (title, unit)
    t_lines, t_h, _ = _wrap_need(title_txt, sizes["chart_title"], fs, tw, TITLE_LEADING,
                                 True)
    b.text("chart", "chart-title", title_txt, box["x"] + pad_x, box["y"] + 0.4, tw,
           t_h + 0.25, "chart_title", bold=True, color=INK, align="center",
           valign="middle", panel=pid, evidence=ev, allow_truncate=False,
           leading=TITLE_LEADING)

    xlabel = (chart.get("x") or {}).get("label")
    axis_pt = sizes["axis"]
    tick_h = measure.line_height_mm(axis_pt, 1.1)
    label_space = 2.0
    # left gutter sized from the widest tick label (never a guess)
    lo, hi = _value_bounds(series)
    widest_tick = max(measure.text_width_mm(fmt_num(lo + (hi - lo) * i / 4.0), axis_pt, fs)
                      for i in range(5))
    left = min(0.35 * box["w"], widest_tick + 3.2)
    right = 1.6
    bottom = tick_h * 2 + 1.4 + (3.0 if xlabel else 0.0) + (3.4 if unit else 0.0)
    plot = _bbox(box["x"] + left, box["y"] + t_h + 2.0,
                 max(6.0, box["w"] - left - right),
                 max(4.0, box["h"] - (t_h + 1.2) - bottom))
    if plot["w"] < CHART_MIN_W_MM * 0.5 or plot["h"] < 12.0:
        b.warn("W_CHART_TINY",
               "chart %s has a %.1f x %.1f mm plot area" % (cid, plot["w"], plot["h"]),
               panel=pid)
    b.rect("chart", "chart-plot", plot, fill="none", stroke=GRID, width=0.25,
           panel=pid, evidence=ev, chart_id=cid, chart_type=ctype)

    kind = ctype if ctype in ("bar", "barh", "line", "scatter", "dot",
                              "heatmap", "waterfall") else "bar"
    if kind in ("bar", "waterfall"):
        _chart_bar(b, pid, chart, plot, fs, sizes, colors, series, cid, ev, False, left)
    elif kind == "barh":
        _chart_bar(b, pid, chart, plot, fs, sizes, colors, series, cid, ev, True, left)
    elif kind == "line":
        _chart_line(b, pid, chart, plot, fs, sizes, colors, series, cid, ev, left, box)
    elif kind in ("scatter", "dot"):
        _chart_scatter(b, pid, chart, plot, fs, sizes, colors, series, cid, ev,
                       dot=(kind == "dot"), gutter=left, frame=box)
    else:
        _chart_heatmap(b, pid, chart, plot, fs, sizes, series, colorbars, cid, ev)

    if xlabel and kind != "barh":
        b.text("chart", "chart-xlabel", str(xlabel), plot["x"],
               plot["y"] + plot["h"] + tick_h + 1.0, plot["w"], 3.2, "axis",
               color=MUTED, align="center", valign="top", panel=pid,
               evidence=ev, max_lines=1, allow_truncate=False)


def _value_bounds(series, colorbars=None):
    vals = []
    for s in series:
        for v in (s.get("values") or []):
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                vals.append(float(v))
    if not vals:
        return 0.0, 1.0
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        hi = lo + 1.0
    if lo > 0.0:
        lo = 0.0
    if lo == hi:
        hi = lo + 1.0
    # headroom: without it the tallest bar/marker is drawn exactly on the frame
    if hi > 0:
        hi *= 1.08
    elif hi < 0:
        hi *= 0.92
    else:
        hi = 1.0
    return lo, hi


def _scale_y(v, lo, hi, axis):
    t = 0.0 if hi <= lo else (float(v) - lo) / (hi - lo)
    return axis["y"] + axis["h"] * (1.0 - _clamp(t, 0.0, 1.0))


def _scale_x(v, lo, hi, axis):
    t = 0.0 if hi <= lo else (float(v) - lo) / (hi - lo)
    return axis["x"] + axis["w"] * _clamp(t, 0.0, 1.0)


def _axis_v(b, pid, plot, fs, sizes, lo, hi, ev, cid, ticks=4, gutter=12.0):
    b.line("chart", "chart-axis", (plot["x"], plot["y"]),
           (plot["x"], plot["y"] + plot["h"]), stroke=FRAME, width=0.3,
           panel=pid, evidence=ev, chart_id=cid)
    b.line("chart", "chart-axis", (plot["x"], plot["y"] + plot["h"]),
           (plot["x"] + plot["w"], plot["y"] + plot["h"]), stroke=FRAME,
           width=0.3, panel=pid, evidence=ev, chart_id=cid)
    th = measure.line_height_mm(sizes["axis"], 1.1)
    positions = [plot["y"] + plot["h"] * (1.0 - i / float(ticks)) for i in range(ticks + 1)]
    gap = abs(positions[0] - positions[1]) if len(positions) > 1 else 0.0
    show = gap >= th * 1.05
    lstep = max(1, int(math.ceil((th + 0.5) / gap))) if gap > 1e-6 else 1
    last_y = None
    for i, y in enumerate(positions):
        v = lo + (hi - lo) * i / float(ticks)
        if i < len(positions) - 1 and show:
            b.line("chart", "chart-gridline", (plot["x"], y), (plot["x"] + plot["w"], y),
                   stroke=GRID, width=0.2, panel=pid, evidence=ev, chart_id=cid)
        if not show and i not in (0, len(positions) - 1):
            continue
        if show and (i % lstep) and i not in (0, len(positions) - 1):
            continue
        if show and i == len(positions) - 1 and last_y is not None \
                and abs(y - last_y) < th + 0.2:
            continue
        b.line("chart", "chart-tick", (plot["x"] - 1.0, y), (plot["x"], y),
               stroke=FRAME, width=0.25, panel=pid, evidence=ev, chart_id=cid)
        last_y = y
        ty = (y + 0.2) if i == len(positions) - 1 else (y - th / 2.0)
        b.text("chart", "chart-tick", fmt_num(v),
               max(plot["x"] - gutter, plot["x"] - 13.0), ty, gutter - 1.2, th,
               "axis", color=MUTED, align="right", valign="top" if i == len(positions) - 1
               else "middle", panel=pid, evidence=ev, max_lines=1,
               allow_truncate=True)
    return plot


def _axis_h(b, pid, plot, fs, sizes, lo, hi, ev, cid, gutter=12.0, ticks=4):
    b.line("chart", "chart-axis", (plot["x"], plot["y"]),
           (plot["x"], plot["y"] + plot["h"]), stroke=FRAME, width=0.3,
           panel=pid, evidence=ev, chart_id=cid)
    b.line("chart", "chart-axis", (plot["x"], plot["y"] + plot["h"]),
           (plot["x"] + plot["w"], plot["y"] + plot["h"]), stroke=FRAME,
           width=0.3, panel=pid, evidence=ev, chart_id=cid)
    th = measure.line_height_mm(sizes["axis"], 1.1)
    spacing = plot["w"] / float(max(1, ticks))
    half = max(3.0, min(6.0, spacing / 2.0 - 0.4))
    step = 1 if spacing >= 7.0 else max(1, int(math.ceil(7.0 / max(spacing, 1e-6))))
    prev_right = None
    for i in range(ticks + 1):
        v = lo + (hi - lo) * i / float(ticks)
        x = plot["x"] + plot["w"] * i / float(ticks)
        b.line("chart", "chart-tick", (x, plot["y"] + plot["h"]),
               (x, plot["y"] + plot["h"] - 1.0), stroke=FRAME, width=0.25,
               panel=pid, evidence=ev, chart_id=cid)
        if i % step:
            continue
        if prev_right is not None and (x - half) < prev_right + 0.3:
            continue
        prev_right = x + half
        b.text("chart", "chart-tick", fmt_num(v), x - half, plot["y"] + plot["h"] + 0.2,
               half * 2, th, "axis", color=MUTED, align="center", valign="top",
               panel=pid, evidence=ev, max_lines=1, allow_truncate=True)
    return plot


def _chart_bar(b, pid, chart, plot, fs, sizes, colors, series, cid, ev, horizontal, gutter=12.0):
    lo, hi = _value_bounds(series)
    cats = [str(c) for c in (chart.get("categories") or [])]
    if not cats:
        n = max([len(s.get("values") or []) for s in series] or [0])
        cats = [str(i + 1) for i in range(n)]
    ncat = max(1, len(cats))
    nser = max(1, len(series))
    if horizontal:
        axis = _axis_h(b, pid, plot, fs, sizes, lo, hi, ev, cid, gutter=gutter)
        slot = axis["h"] / ncat
        bar_h = slot * 0.78 / nser
        for si, s in enumerate(series):
            sev = _series_evidence(b, [s])
            for ci, v in enumerate(s.get("values") or []):
                if ci >= ncat or not isinstance(v, (int, float)):
                    continue
                y = axis["y"] + ci * slot + slot * 0.11 + si * bar_h
                x0 = _scale_x(v, lo, hi, axis)
                b.rect("chart", "chart-bar",
                       _bbox(min(x0, axis["x"]), y, max(0.2, abs(x0 - axis["x"])),
                             bar_h * 0.9), fill=colors[si], stroke="none",
                       width=0.0, panel=pid, evidence=sev, chart_id=cid,
                       series_name=s.get("name"), series_index=si,
                       category=cats[ci] if ci < len(cats) else None,
                       value=float(v), unit=chart.get("unit"))
        th = measure.line_height_mm(sizes["axis"], 1.1)
        for i, c in enumerate(cats):
            b.text("chart", "chart-catlabel", c, axis["x"] - 1.2 - 14.0,
                   axis["y"] + i * slot, 14.0, slot, "axis", color=MUTED,
                   align="right", valign="middle", panel=pid, evidence=ev,
                   max_lines=2, allow_truncate=False)
    else:
        axis = _axis_v(b, pid, plot, fs, sizes, lo, hi, ev, cid, gutter=gutter)
        slot = axis["w"] / ncat
        bar_w = slot * 0.78 / nser
        for si, s in enumerate(series):
            sev = _series_evidence(b, [s])
            for ci, v in enumerate(s.get("values") or []):
                if ci >= ncat or not isinstance(v, (int, float)):
                    continue
                x = axis["x"] + ci * slot + slot * 0.11 + si * bar_w
                y0 = _scale_y(v, lo, hi, axis)
                base = axis["y"] + axis["h"]          # the zero baseline, not the top
                b.rect("chart", "chart-bar",
                       _bbox(x, min(y0, base), bar_w * 0.9,
                             max(0.2, abs(base - y0))), fill=colors[si],
                       stroke="none", width=0.0, panel=pid, evidence=sev,
                       chart_id=cid, series_name=s.get("name"), series_index=si,
                       category=cats[ci] if ci < len(cats) else None,
                       value=float(v), unit=chart.get("unit"))
        th = measure.line_height_mm(sizes["axis"], 1.1)
        for i, c in enumerate(cats):
            b.text("chart", "chart-catlabel", c, axis["x"] + i * slot,
                   axis["y"] + axis["h"] + 0.2, slot, th * 2, "axis", color=MUTED,
                   align="center", valign="top", panel=pid, evidence=ev,
                   max_lines=2, allow_truncate=True)


def _chart_line(b, pid, chart, plot, fs, sizes, colors, series, cid, ev,
                gutter=12.0, frame=None):
    xv = (chart.get("x") or {}).get("values") or []
    n = max([len(s.get("values") or []) for s in series] or [0])
    if n == 0:
        return
    if len(xv) != n:
        xv = list(range(n))
    lo, hi = _value_bounds(series)
    axis = _axis_v(b, pid, plot, fs, sizes, lo, hi, ev, cid, gutter=gutter)
    xs = [float(x) for x in xv]
    xlo, xhi = min(xs), max(xs)
    if xhi <= xlo:
        xhi = xlo + 1.0
    for si, s in enumerate(series):
        sev = _series_evidence(b, [s])
        pts = []
        for i, v in enumerate(s.get("values") or []):
            if not isinstance(v, (int, float)):
                continue
            px = axis["x"] + axis["w"] * ((xs[i] - xlo) / (xhi - xlo))
            pts.append((px, _scale_y(v, lo, hi, axis)))
        if len(pts) >= 2:
            b.path("chart", "chart-series-line", pts, stroke=colors[si], width=0.7,
                   panel=pid, evidence=sev, chart_id=cid, series_name=s.get("name"),
                   series_index=si)
        for i, p in enumerate(pts):
            b.circle("chart", "chart-series-marker", p[0], p[1], 0.7,
                     fill=colors[si], stroke=PAGE_BG, width=0.2, panel=pid,
                     evidence=sev, chart_id=cid, series_name=s.get("name"),
                     series_index=si, unit=chart.get("unit"))
    th = measure.line_height_mm(sizes["axis"], 1.1)
    positions = [axis["x"] + axis["w"] * ((x - xlo) / (xhi - xlo)) for x in xs]
    gaps = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    gapx = min(gaps) if gaps else axis["w"]
    half = max(3.0, min(6.0, gapx / 2.0 - 0.4))
    prev_right = None
    for x, px in zip(xs, positions):
        if prev_right is not None and (px - half) < prev_right + 0.3:
            continue
        prev_right = px + half
        b.text("chart", "chart-tick", fmt_num(x), px - half, axis["y"] + axis["h"] + 0.2,
               half * 2, th, "axis", color=MUTED, align="center", valign="top",
               panel=pid, evidence=ev, max_lines=1, allow_truncate=True)


def _chart_scatter(b, pid, chart, plot, fs, sizes, colors, series, cid, ev, dot=False, gutter=12.0):
    xv = (chart.get("x") or {}).get("values") or []
    n = max([len(s.get("values") or []) for s in series] or [0])
    if n == 0:
        return
    if len(xv) != n:
        xv = list(range(n))
    lo, hi = _value_bounds(series)
    axis = _axis_v(b, pid, plot, fs, sizes, lo, hi, ev, cid, gutter=gutter)
    xs = [float(x) for x in xv]
    xlo, xhi = min(xs), max(xs)
    if xhi <= xlo:
        xhi = xlo + 1.0
    for si, s in enumerate(series):
        sev = _series_evidence(b, [s])
        for i, v in enumerate(s.get("values") or []):
            if not isinstance(v, (int, float)):
                continue
            px = axis["x"] + axis["w"] * ((xs[i] - xlo) / (xhi - xlo))
            py = _scale_y(v, lo, hi, axis)
            if dot:
                b.rect("chart", "chart-dot", _bbox(px - 0.9, py - 0.9, 1.8, 1.8),
                       fill=colors[si], stroke="none", width=0.0, panel=pid,
                       evidence=sev, chart_id=cid, series_name=s.get("name"),
                       series_index=si, value=float(v), unit=chart.get("unit"))
            else:
                b.circle("chart", "chart-point", px, py, 0.8, fill=colors[si],
                         stroke=PAGE_BG, width=0.2, panel=pid, evidence=sev,
                         chart_id=cid, series_name=s.get("name"), series_index=si,
                         value=float(v), unit=chart.get("unit"))


def _chart_heatmap(b, pid, chart, plot, fs, sizes, series, colorbars, cid, ev):
    vals = [float(v) for s in series for v in (s.get("values") or [])
            if isinstance(v, (int, float))]
    if not vals:
        return
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        hi = lo + 1.0
    cmap = (colorbars[0].get("cmap") if colorbars else "viridis")
    b.add("chart", "heatmap", plot, "chart-heatmap", panel=pid, evidence=ev,
          style={"fill": "none", "stroke": "none", "stroke_width_mm": 0.0},
          chart_id=cid, vmin=_r(lo), vmax=_r(hi), cmap=cmap,
          series=[s.get("name") for s in series])
    per = max([len(s.get("values") or []) for s in series] or [1])
    cw, ch = plot["w"] / per, plot["h"] / max(1, len(series))
    for si, s in enumerate(series):
        sev = _series_evidence(b, [s])
        for i, v in enumerate(s.get("values") or []):
            if not isinstance(v, (int, float)):
                continue
            b.rect("chart", "heatmap-cell",
                   _bbox(plot["x"] + i * cw, plot["y"] + si * ch, cw, ch),
                   fill=cmap_color(cmap, (float(v) - lo) / (hi - lo)),
                   stroke=PAGE_BG, width=0.15, panel=pid, evidence=sev,
                   chart_id=cid, series_name=s.get("name"), series_index=si,
                   value=float(v), unit=chart.get("unit"))


# --------------------------------------------------------------------------- #
# legend / colorbar / scalebar
# --------------------------------------------------------------------------- #
def _emit_legend(b, pid, legend, box, fs, sizes, ncol=1):
    """Legend frame + one row per item.

    An item that names an edge `kind` gets the *same* line + head the drawing
    uses (both call ``resolve_edge_style``); an item that names a `part` gets a
    miniature of that apparatus glyph (both call ``_draw_part``).  Everything
    else keeps the frozen v1 colour swatch.
    """
    items = [it for it in (legend.get("items") or []) if isinstance(it, dict)]
    row = _legend_row(sizes, fs, items)
    ncol = max(1, min(int(ncol or 1), max(1, len(items))))
    col_w = (box["w"] - 1.4) / ncol
    sw = 2.4
    cmap_colors = _color_map(legend, len(items))
    oz = sizes.get("legend", BASE_SIZES["legend"])
    resolved = []
    for it in items:
        kind = it.get("kind") if isinstance(it.get("kind"), str) else None
        part = node_part({"part": it.get("part")}) if it.get("part") else None
        # the legend item *is* the kind's declaration, so resolving it here and
        # resolving the edge with declared=item yields identical visuals
        st = resolve_edge_style(it, kind=kind) if kind else None
        if kind:
            color = st["color"] or it.get("color")
        elif part:
            # a glyph sample has no colour channel of its own; publishing one
            # would create a phantom gate-C category group
            color = it.get("color")
        else:
            color = it.get("color") or cmap_colors.get(
                str(it.get("label") or "").strip().lower()) or scene.categorical_colors(1)[0]
        resolved.append({
            "label": it.get("label"), "color": color, "kind": kind, "part": part,
            "linestyle": st["linestyle"] if st else None,
            "dash": list(st["dash"]) if st else None,
            "head": st["head"] if st else None,
        })
    b.add("legend", "legend", box, "legend-frame", panel=pid,
          style={"fill": PAGE_BG, "stroke": GRID, "stroke_width_mm": 0.25},
          title=legend.get("title"), items=resolved)
    ink = INK
    y = box["y"] + 0.5
    if legend.get("title"):
        b.text("legend", "legend-title", str(legend["title"]), box["x"] + 1.0, y,
               max(2.0, box["w"] - 2.0), row, "legend", bold=True, color=ink,
               valign="middle", panel=pid, max_lines=1, allow_truncate=False)
        y += row
    i_col = 0
    for it, res in zip(items, resolved):
        rows_used = int(math.ceil((i_col + 1) / float(ncol)))
        if y + rows_used * row > box["y"] + box["h"] + 0.3:
            b.warn("W_LEGEND_OVERFLOW",
                   "legend of panel %s does not fit its box (%d items)"
                   % (pid, len(items)), panel=pid)
            break
        ev = b.evidence_for(it)
        cx = box["x"] + 1.0 + (i_col % ncol) * col_w
        cy = y + (i_col // ncol) * row
        text_x = cx + sw + 0.7
        if res["kind"]:
            swl = _clamp(col_w * 0.26, 2.6, 6.6)
            mid = cy + row / 2.0
            b.line("legend", "legend-kind-line", (cx, mid), (cx + swl, mid),
                   stroke=res["color"], width=resolve_edge_style(
                       it, kind=res["kind"])["width"], panel=pid, evidence=ev,
                   dash=res["dash"] or None, legend_linestyle=res["linestyle"])
            _draw_head(b, "legend", "legend-kind-head", (cx + swl, mid), (1.0, 0.0),
                       res["head"], res["color"], pid, ev,
                       width=resolve_edge_style(it, kind=res["kind"])["width"])
            text_x = cx + swl + 0.9
        elif res["part"]:
            side = min(row * 0.92, _clamp(col_w * 0.26, 2.6, 6.6) + 1.0)
            _draw_part(b, res["part"], _bbox(cx, cy + (row - side) / 2.0, side, side),
                       layer="legend", element="legend-part", panel=pid, evidence=ev)
            text_x = cx + side + 0.8
        else:
            b.rect("legend", "legend-swatch", _bbox(cx, cy + 0.6, sw, sw * 0.7),
                   fill=res["color"], stroke=FRAME, width=0.2, panel=pid, evidence=ev)
        label = str(it.get("label") or "")
        avail = max(2.0, box["x"] + box["w"] - 0.8 - text_x)
        need = measure.text_width_mm(label, oz, fs) + 0.4
        if label and need > avail:
            # never let gate B see a dropped token: widen into the frame if the
            # label is merely long, and only then fall back to a wrapped box
            widened = max(avail, min(need, max(2.0, box["x"] + box["w"] - text_x)))
            if widened > avail + 1e-9 and need <= widened + 1e-9:
                avail = widened
            else:
                b.warn("W_LEGEND_LABEL_TIGHT",
                       "legend label %r needs %.1f mm but only %.1f mm is free in "
                       "panel %s" % (label[:40], need, avail, pid), panel=pid)
        b.text("legend", "legend-item", label, text_x, cy, avail, row, "legend",
               color=ink, valign="middle", panel=pid, evidence=ev, max_lines=1,
               allow_truncate=False)
        i_col += 1


def _emit_colorbar(b, pid, cb, box, fs, sizes):
    """Horizontal colour bar: the title gets the box width, so it cannot clip."""
    cmap = cb.get("cmap")
    vmin, vmax = float(cb.get("vmin", 0.0)), float(cb.get("vmax", 1.0))
    title = str(cb.get("title") or cb.get("id") or "")
    unit = str(cb.get("unit") or "")
    ev = b.evidence_for(cb)
    ticks = [vmin + (vmax - vmin) * i / 4.0 for i in range(5)]
    oz = sizes["colorbar"]
    th = measure.line_height_mm(oz, 1.1)
    tick_h = max(3.0, th)
    # title (up to two lines, never clipped), then bar, then ticks
    title_txt = title if not unit else "%s (%s)" % (title, unit)
    t_lines, t_h, _ = _wrap_need(title_txt, oz, fs, max(4.0, box["w"] - 1.4),
                                 TITLE_LEADING, True)
    t_lines = t_lines[:2]
    t_h = min(t_h, max(2.0, box["h"] - tick_h - 4.4))
    pad = 1.0
    bar_h = _clamp(box["h"] - t_h - tick_h - 1.2, 2.6, 4.4)
    avail_w = max(8.0, box["w"] - 2 * pad)
    spacing = avail_w / float(max(1, len(ticks) - 1))
    half = max(3.0, min(6.5, spacing / 2.0 - 0.4))
    bar_w = max(4.0, avail_w - 2 * half)
    spacing = bar_w / float(max(1, len(ticks) - 1))
    half = max(3.0, min(6.5, spacing / 2.0 - 0.4))
    bar = _bbox(box["x"] + pad + half, box["y"] + t_h + 0.3, bar_w, bar_h)
    b.add("colorbar", "colorbar", box, "colorbar-frame", panel=pid, evidence=ev,
          style={"fill": "none", "stroke": "none", "stroke_width_mm": 0.0},
          colorbar_id=cb.get("id"), cmap=cmap, cmap_stops=list(scene.CMAPS.get(cmap, [])),
          vmin=_r(vmin), vmax=_r(vmax), unit=unit, title=title, orientation="horizontal",
          ticks=[_r(t) for t in ticks], bar_bbox=bar)
    b.text("colorbar", "colorbar-title", title_txt, box["x"] + 0.7, box["y"],
           max(4.0, box["w"] - 1.4), max(2.0, t_h), "colorbar", bold=True, color=INK,
           align="left", valign="top", panel=pid, evidence=ev, max_lines=2,
           allow_truncate=True, leading=TITLE_LEADING)
    steps = 40
    step_w = bar["w"] / steps
    for i in range(steps):
        t = (i + 0.5) / steps
        b.rect("colorbar", "colorbar-band",
               _bbox(bar["x"] + i * step_w, bar["y"], step_w + 0.03, bar["h"]),
               fill=cmap_color(cmap, t), stroke="none", width=0.0, panel=pid,
               evidence=ev, colorbar_id=cb.get("id"))
    b.rect("colorbar", "colorbar-outline", bar, fill="none", stroke=FRAME,
           width=0.25, panel=pid, evidence=ev)
    for t in ticks:
        frac = (t - vmin) / (vmax - vmin) if vmax > vmin else 0.0
        x = bar["x"] + bar["w"] * _clamp(frac, 0.0, 1.0)
        b.line("colorbar", "colorbar-tick", (x, bar["y"] + bar["h"]),
               (x, bar["y"] + bar["h"] + 0.9), stroke=FRAME, width=0.25,
               panel=pid, evidence=ev)
        b.text("colorbar", "colorbar-ticklabel", fmt_num(t), x - half,
               bar["y"] + bar["h"] + 1.0, half * 2, tick_h, "colorbar", color=MUTED,
               align="center", valign="top", panel=pid, evidence=ev,
               max_lines=1, allow_truncate=True)


def _maybe_scalebar(b, spec, panel_records):
    meta = spec.get("meta") or {}
    sb = meta.get("scalebar")
    if not isinstance(sb, dict):
        for p in (spec.get("panels") or []):
            if isinstance(p, dict) and isinstance(p.get("scalebar"), dict):
                sb = dict(p["scalebar"])
                sb.setdefault("panel", p.get("id"))
                break
    if not isinstance(sb, dict) or not panel_records:
        return
    target = None
    for rec in panel_records:
        if sb.get("panel") and rec["id"] == sb.get("panel"):
            target = rec
            break
    target = target or panel_records[-1]
    length = _clamp(float(sb.get("length_mm", 10.0) or 10.0), 2.0, 60.0)
    label = str(sb.get("label") or ("%s mm" % fmt_num(length)))
    box = target["content_bbox"]
    y = box["y"] + box["h"] - 3.4
    x1 = box["x"] + box["w"] - 2.0
    x0 = x1 - length
    if x0 < box["x"] + 2.0:
        x0 = box["x"] + 2.0
        x1 = x0 + length
    pid = target["id"]
    b.add("annotation", "scalebar", _bbox(x0, y - 1.0, x1 - x0, 4.4), "scalebar",
          panel=pid, style={"stroke": INK, "stroke_width_mm": 0.4},
          length_mm=_r(length), label=label)
    b.line("annotation", "scalebar-line", (x0, y), (x1, y), stroke=INK, width=0.4,
           panel=pid)
    b.line("annotation", "scalebar-tick", (x0, y - 1.0), (x0, y + 1.0), stroke=INK,
           width=0.4, panel=pid)
    b.line("annotation", "scalebar-tick", (x1, y - 1.0), (x1, y + 1.0), stroke=INK,
           width=0.4, panel=pid)
    b.text("annotation", "scalebar-label", label, x0, y - 3.8, x1 - x0, 2.8,
           "axis", color=INK, align="center", valign="bottom", panel=pid,
           max_lines=1, allow_truncate=False)
