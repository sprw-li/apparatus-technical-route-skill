#!/usr/bin/env python3
"""autospec.py — derive a figure spec from the material WITHOUT an LLM.

Why this exists
---------------
The Skill's normal path is: an agent reads the material and authors ``spec.json``
(science), then the deterministic scripts draw it.  If the agent is unavailable,
runs out of budget, or the case is a stress case, this module still has to
produce something honest and usable — so the pipeline degrades instead of dying.

Guarantees:
    * deterministic: same materials + ledger -> byte-identical spec
      (no randomness, no clock, no hash-order dependence);
    * valid: the returned spec passes ``scene.validate_spec`` with zero errors
      (a repair pass removes anything it cannot substantiate);
    * honest: every node/edge/series cites an evidence id whose quote really
      occurs in a material, and anything it could not extract becomes an entry
      in ``uncertainty``/``limitations`` instead of an invented value.
"""
from __future__ import annotations
import sys as _sys
_sys.dont_write_bytecode = True

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import scene            # noqa: E402
import evidence as ev   # noqa: E402

MAX_NODES_PER_PANEL = {"problem": 4, "method": 6, "results": 9, "conclusion": 5}
MAX_CHARTS = 1                 # one chart per panel: two charts would union their
#                              series names into a legend of >4 colours, and beyond
#                              four categories the Okabe-Ito set cannot also clear
#                              the 5.0 greyscale dL* floor (see scene.PALETTES).
MAX_SERIES = 3
MAX_EDGES_PER_PANEL = 6
# A comfortable single page. The default 180x120 double-column canvas is too
# tight for an auto-derived dense figure, and the layout engine must never be
# asked to place content outside the margin box.
AUTOSPEC_CANVAS = {"w_mm": 200.0, "h_mm": 170.0, "margin_mm": 3.0, "dpi": 300}

# The one caption both autospec paths ship.  It names the real product (an
# apparatus / technical-route figure) and still says out loud that no LLM authored
# it -- relabelling a deterministic fallback as an authored result would be a lie.
AUTOSPEC_CAPTION = (
    "Single-page apparatus and technical-route figure derived automatically from the supplied "
    "materials: apparatus structure, ordered process steps with their flows, and route phases. "
    "Every element cites a verbatim source quote.")

ROLE_KEYWORDS = {
    "problem": ("background", "intro", "rationale", "problem", "question", "motivation",
                "hypothesis", "aim", "objective", "abstract", "\u80cc\u666f", "\u95ee\u9898"),
    "method": ("method", "material", "experimental", "approach", "protocol", "procedure",
               "workflow", "assay", "\u65b9\u6cd5", "\u5b9e\u9a8c"),
    "results": ("result", "finding", "observation", "measurement", "outcome",
                "\u7ed3\u679c"),
    "conclusion": ("conclusion", "discussion", "summary", "outlook", "perspective",
                   "implication", "legend", "\u7ed3\u8bba", "\u8ba8\u8bba"),
}
ROLE_ORDER = ("problem", "method", "results", "conclusion")

UNIT_HINTS = (
    ("fold", "fold"), ("pct", "percent"), ("percent", "percent"),
    ("pmol", "pmol/min"), ("nmol_per_mg", "nmol/mg"), ("nmol", "nmol/mg"),
    ("mph", "mpH/min"), ("mmhg", "mmHg"), ("umol", "umol/L"), ("mM", "mM"),
    ("activity", "per second"), ("per_s", "per second"),
)


# --------------------------------------------------------------------------- #
def _cjk_ratio(text):
    if not text:
        return 0.0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return cjk / float(max(1, len(text)))


def _clean_label(text, limit=34):
    """Short, whole-word label.

    Never cut inside a word: a hard mid-word cut produces a token the layout
    engine cannot wrap ("cardiomyoblas"), which it then drops, and a dropped
    token is a gate B/F failure. If the first word alone is too long, keep it
    (the layout can shrink) rather than mangling it.
    """
    t = ev._norm(text)
    t = re.sub(r"^[#*\-\s]+", "", t)
    t = re.sub(r"\s*[\(\[][^)\]]*[\)\]]\s*$", "", t)
    if len(t) <= limit:
        return t or "unnamed"
    words = t.split(" ")
    kept = []
    for w in words:
        cand = " ".join(kept + [w])
        if len(cand) > limit:
            break
        kept.append(w)
    if kept:
        return " ".join(kept).rstrip(" ,;:")
    return words[0] if words else (t or "unnamed")


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40]


_UNIT_WORDS = {
    "fold", "folds", "pmol", "nmol", "umol", "mmol", "mol", "min", "mins", "minute",
    "minutes", "sec", "s", "h", "hr", "hrs", "hour", "hours", "mg", "ml", "l", "kg",
    "mph", "ph", "percent", "pct", "au", "arb", "units", "unit", "per", "of",
}


def header_info(header):
    """CSV header -> (human label, canonical unit).

    The unit is carried by the chart's ``unit`` field, so it is stripped from the
    label: a series called "MitoSOX fold" both duplicates the axis unit and gets
    truncated in a narrow legend, which loses a required label (gate B/F).
    """
    h = str(header or "").strip()
    low = h.lower()
    label = h.replace("_", " ").replace("-", " ").strip()
    label = re.sub(r"\s+", " ", label)
    unit = None
    for token, u in UNIT_HINTS:
        if token.lower() in low:
            unit = u
            break
    if unit is None:
        if low in ("time_h", "time", "hours") or low.endswith("_h"):
            unit = "h"
        elif "viability" in low:
            unit = "percent"
        else:
            unit = "AU"
    words = [w for w in label.split(" ") if w]
    while words and words[-1].lower() in _UNIT_WORDS:
        words.pop()
    trimmed = " ".join(words)
    if len(trimmed) >= 3:
        label = trimmed
    return _clean_label(label, 30), unit


def _numeric(cell):
    try:
        return float(str(cell).strip())
    except (TypeError, ValueError):
        return None


def _column_numbers(table, index):
    out = []
    for row in table.get("rows") or []:
        cells = row.get("cells") or []
        if index < len(cells):
            out.append(_numeric(cells[index]))
    return out


def _cat_stats(rows, index):
    """-> (distinct labels in order, mean label length) for a candidate axis."""
    uniq = []
    for row in rows:
        cells = row.get("cells") or []
        if index >= len(cells):
            continue
        label = str(cells[index]).strip()
        if label and label not in uniq:
            uniq.append(label)
    avg = (sum(len(x) for x in uniq) / float(len(uniq))) if uniq else 0.0
    return uniq, avg


# --------------------------------------------------------------------------- #
# tables -> charts
# --------------------------------------------------------------------------- #
def charts_from_tables(materials, table_evidence, fac=None):
    """-> (charts, used_evidence_ids, notes). Charts never mix units.

    Every plotted value must be backed by an evidence item whose quote really
    contains it (gate E906).  The row claims used to be looked up in the ledger
    with ``table_evidence[0]`` as fallback, so when the ledger's 60-item cap
    dropped the table rows the chart silently cited an unrelated sentence and the
    figure showed numbers no source contained.  Now each plotted row is given its
    own evidence (from the ledger when present, otherwise built from the table
    span) and a series whose rows cannot be sourced is dropped, not laundered.
    """
    tables = []
    for mat in (materials.get("materials") or []):
        for table in (mat.get("tables") or []):
            if table.get("rows"):
                tables.append((mat, table))
    if not tables:
        return [], [], ["no tabular source data found; charts were derived from inline numbers only"]

    notes = []
    mat, table = tables[0]
    header = [str(h) for h in (table.get("header") or [])]
    rows = table.get("rows") or []
    if len(header) < 2 or len(rows) < 2:
        return [], [], ["table %s has too few rows/columns for a chart" % table.get("name")]

    numeric_idx, cat_idx = [], None
    for i in range(len(header)):
        vals = _column_numbers(table, i)
        good = [v for v in vals if v is not None]
        if vals and len(good) >= max(2, int(0.8 * len(vals))):
            numeric_idx.append(i)
        elif cat_idx is None:
            cat_idx = i

    # The category axis must actually fit the page.  A long free-text column
    # ("condenser temperature") overflows the axis, the renderer then drops a
    # token, and gates B/F report a label that is on the figure nowhere.  Prefer a
    # short categorical column; otherwise use an integer-valued numeric column
    # (a real value from the row) as the x axis.
    if cat_idx is not None:
        uniq, avg = _cat_stats(rows, cat_idx)
        if not (2 <= len(uniq) <= 10 and avg <= 10.5):
            cat_idx = None
    if cat_idx is None:
        for i in list(numeric_idx):
            vals = [v for v in _column_numbers(table, i) if v is not None]
            if not vals or any(not float(v).is_integer() for v in vals):
                continue
            uniq = sorted({int(v) for v in vals})
            if 2 <= len(uniq) <= 12 and (uniq[-1] - uniq[0]) <= 12:
                cat_idx = i
                numeric_idx = [j for j in numeric_idx if j != i]
                break
    if not numeric_idx:
        return [], [], ["table %s has no numeric column" % table.get("name")]

    # categories: last row per distinct label (the endpoint of a time course)
    cats, cat_rows = [], []
    if cat_idx is not None:
        seen = {}
        for row in rows:
            cells = row.get("cells") or []
            key = str(cells[cat_idx]).strip() if cat_idx < len(cells) else ""
            if key == "":
                continue
            if key not in seen:
                seen[key] = len(cats)
                cats.append(_clean_label(key, 14))
                cat_rows.append(row)
            else:
                cat_rows[seen[key]] = row
    if not cats:
        cats = ["value"]
        cat_rows = [rows[-1]]

    # evidence for the rows actually plotted
    row_ev = {}
    for item in table_evidence or []:
        if item.get("row") is not None:
            row_ev.setdefault(item.get("row"), item["id"])

    def ev_for(row):
        n = row.get("n")
        if n in row_ev:
            return row_ev[n]
        if fac is None:
            return None
        start, end = row.get("start"), row.get("end")
        if start is None or end is None or end <= start:
            return None
        return fac.add(mat, start, end, "number", claim="table row")

    def ev_header():
        if fac is None:
            return row_ev.get(None)
        hr = table.get("header_row") or {}
        start, end = hr.get("start"), hr.get("end")
        if start is None or end is None or end <= start:
            return None
        return fac.add(mat, start, end, "number", claim="table header")

    groups = {}
    for i in numeric_idx:
        label, unit = header_info(header[i])
        vals = []
        for row in cat_rows:
            cells = row.get("cells") or []
            vals.append(_numeric(cells[i]) if i < len(cells) else None)
        if any(v is None for v in vals):
            continue
        groups.setdefault(unit, []).append((i, label, vals))

    if not groups:
        return [], [], ["table %s yielded no complete numeric series" % table.get("name")]

    def spread(entry):
        vals = entry[2]
        lo, hi = min(vals), max(vals)
        return abs(hi - lo) / max(1e-9, abs(hi), abs(lo))

    charts, used = [], []
    # deterministic group order: unit groups sorted by their best spread
    ordered_units = sorted(groups, key=lambda u: (-max(spread(e) for e in groups[u]), u))
    for unit in ordered_units[:MAX_CHARTS]:
        entries = sorted(groups[unit], key=lambda e: (-spread(e), e[0]))[:MAX_SERIES]
        # every plotted row must be cited, otherwise the chart would show numbers
        # whose own source span is not referenced (gate E906)
        row_sources = []
        hid = ev_header()
        if hid:
            row_sources.append(hid)          # the header carries any digits in the title
        unsourced = False
        for row in cat_rows:
            sid = ev_for(row)
            if not sid:
                unsourced = True
                break
            if sid not in row_sources:
                row_sources.append(sid)
        if unsourced or not row_sources:
            notes.append("chart for %s was dropped: a plotted row has no resolvable source span, "
                         "and a data series must not be backed by an unrelated evidence id"
                         % table.get("name"))
            continue
        series = []
        for i, label, vals in entries:
            series.append({"name": label, "values": [round(v, 6) for v in vals],
                           "sources": list(row_sources)})
        used.extend(row_sources)
        charts.append({
            "id": scene.stable_id("C", "%s|%s" % (table.get("name"), unit)),
            "type": "bar",
            # keep the title short enough to render without truncation: the
            # category axis already says what the grouping is
            "title": _clean_label(header[entries[0][0]], 30),
            "unit": unit,
            "categories": cats,
            "series": series,
        })
    if charts:
        notes.append("charts built from %s (%d row(s) x %d column(s)); every plotted row is cited"
                     % (table.get("name"), len(rows), len(header)))
    return charts, used, notes


def charts_from_numbers(items):
    """Fallback: a before/after chart from sentences that contain >= 2 numbers."""
    series, used = [], []
    for item in items:
        if item.get("cells") or item.get("kind") != "number":
            continue
        nums = item.get("numbers") or []
        if len(nums) < 2:
            continue
        # a series name has to fit a legend column; the sentence prefix is far too
        # long, so use the short subject phrase the number belongs to
        label = _subject_of_number(item) or _clean_label(item.get("claim"), 16)
        unit = item.get("unit") or "AU"
        name = label
        series.append({"name": name[:18], "values": [round(nums[0], 6), round(nums[-1], 6)],
                       "sources": [item["id"]]})
        used.append(item["id"])
        if len(series) >= MAX_SERIES:
            break
    if not series:
        return [], [], ["no chart could be built: no numeric series and no paired numbers in the text"]
    chart = {"id": scene.stable_id("C", "inline-numbers"), "type": "bar",
             "title": "Reported change (first vs last value in sentence)", "unit": series[0] and
             (next((i.get("unit") for i in items if i["id"] == series[0]["sources"][0]), None) or "AU"),
             "categories": ["start", "end"], "series": series}
    return [chart], used, ["charts built from inline numbers in the text (no table available)"]


# --------------------------------------------------------------------------- #
# panels
# --------------------------------------------------------------------------- #
def _role_of(item):
    section = (item.get("section") or "").lower()
    for role in ROLE_ORDER:
        for kw in ROLE_KEYWORDS[role]:
            if kw in section:
                return role
    kind = item.get("kind")
    if kind == "condition" and "method" in ev._norm(item.get("claim") or "").lower():
        return "method"
    return None


def _entity_names(item):
    """Entity-ish names contributed by one evidence item, in order."""
    names = []
    for rel in (item.get("relations") or []):
        names.append(rel.get("subject"))
        names.append(rel.get("object"))
    if not names:
        if item.get("kind") == "number" and item.get("value") is not None:
            # a measured quantity is an entity too: label it with the phrase the
            # number belongs to, so the results panel actually shows the data
            names.append(_subject_of_number(item))
        elif item.get("kind") in ("entity", "condition"):
            claim = _clean_label(item.get("claim"), 16)
            if 2 <= len(claim) <= 30:
                names.append(claim)
    out = []
    for n in names:
        n = ev._clean_term(n) if n else None
        if n and n.lower() not in [o.lower() for o in out]:
            out.append(n)
    return out


def _subject_of_number(item):
    """The phrase immediately before the first number of a measured claim.

    Kept deliberately short: PDF-extracted sentences are long, and a long label
    is what makes the layout engine drop its last token (gate B/F). Four words
    is enough to identify the quantity and reliably fits a node box.
    """
    claim = ev._norm(item.get("claim") or "")
    m = re.search(r"(?<![A-Za-z0-9._\-])-?\d", claim)
    prefix = claim[:m.start()] if m else claim
    prefix = re.sub(r"[\(\[]\s*$", "", prefix).strip(" ,;:-")
    words = [w for w in prefix.split(" ") if w]
    if len(words) > 4:
        words = words[-4:]
    label = " ".join(words)
    label = re.sub(r"^(?:and|the|a|an|of|in|was|were|is|are|by|that|which)\s+", "", label, flags=re.I)
    return _clean_label(label, 16)


def build_panels(materials, ledger, fac=None):
    items = list(ledger.get("items") or [])
    if not items:
        items = ev.fallback_evidence(materials)
    charts, chart_ev, chart_notes = charts_from_tables(materials, items, fac=fac)
    if not charts:
        alt, alt_ev, alt_notes = charts_from_numbers(items)
        charts, chart_ev, chart_notes = alt, alt_ev, chart_notes + alt_notes

    # assign items to roles, first come first served, then fill empty roles
    by_role = {r: [] for r in ROLE_ORDER}
    unassigned = []
    for item in items:
        role = _role_of(item)
        (by_role[role] if role else unassigned).append(item)
    for role in ROLE_ORDER:
        while not by_role[role] and unassigned:
            by_role[role].append(unassigned.pop(0))
    # leftovers go to results (they are the densest panel) without breaking order
    by_role["results"].extend(unassigned)

    # charts belong to the panel that owns the data: results if it has numbers
    chart_panel = {}
    for chart in charts:
        chart_panel[chart["id"]] = "results" if any(
            it.get("kind") == "number" for it in by_role["results"]) else "method"

    role_titles = {
        "problem": "Problem: what the material sets out to resolve",
        "method": "Method: how the material was produced",
        "results": "Results: the measured outcome",
        "conclusion": "Conclusion: what the results support",
    }
    if _cjk_ratio((materials.get("task_text") or "") + " " +
                  " ".join((m.get("text") or "")[:2000] for m in (materials.get("materials") or []))) > 0.15:
        role_titles = {
            "problem": "\u95ee\u9898\uff1a\u6750\u6599\u8981\u89e3\u51b3\u4ec0\u4e48",
            "method": "\u65b9\u6cd5\uff1a\u6750\u6599\u662f\u600e\u4e48\u5f97\u6765\u7684",
            "results": "\u7ed3\u679c\uff1a\u5b9e\u6d4b\u5230\u4e86\u4ec0\u4e48",
            "conclusion": "\u7ed3\u8bba\uff1a\u7ed3\u679c\u652f\u6301\u4ec0\u4e48",
        }

    panels, used_evidence = [], []
    global_nodes = {}
    valued_nodes = []
    for ri, role in enumerate(ROLE_ORDER):
        role_items = by_role[role]
        cap = MAX_NODES_PER_PANEL.get(role, 6)
        nodes, node_ids = [], []
        for item in role_items:
            for name in _entity_names(item):
                if len(nodes) >= cap:
                    break
                nid = scene.stable_id("N", name.lower())
                if nid in global_nodes:
                    continue
                value, unit = (item.get("value"), item.get("unit")) if item.get("kind") == "number" else (None, None)
                node = {"id": nid, "shape": "hexagon" if item.get("kind") == "relation" else "rrect",
                        "label": _clean_label(name, 18), "source": item["id"]}
                if value is not None:
                    node["sublabel"] = ("%g" % value) + (" " + unit if unit else "")
                    node["value"] = float(value)
                    node["unit"] = unit
                    valued_nodes.append((nid, float(value), unit))
                nodes.append(node)
                node_ids.append(nid)
                global_nodes[nid] = role
                used_evidence.append(item["id"])
            if len(nodes) >= cap:
                break

        nodes_by_name = {n["label"].lower(): n["id"] for n in nodes}
        edges = []
        for item in role_items:
            if len(edges) >= MAX_EDGES_PER_PANEL:
                break
            for rel in (item.get("relations") or []):
                subj = ev._clean_term(rel.get("subject")) or ""
                obj = ev._clean_term(rel.get("object")) or ""
                if not subj or not obj:
                    continue
                for name in (subj, obj):
                    if name.lower() not in nodes_by_name:
                        if len(nodes) >= cap:
                            break
                        nid = scene.stable_id("N", name.lower())
                        if nid in global_nodes:
                            break
                        nodes.append({"id": nid, "shape": "rrect",
                                      "label": _clean_label(name, 18), "source": item["id"]})
                        node_ids.append(nid)
                        nodes_by_name[name.lower()] = nid
                        global_nodes[nid] = role
                        used_evidence.append(item["id"])
                a, b = nodes_by_name.get(subj.lower()), nodes_by_name.get(obj.lower())
                if not a or not b or a == b:
                    continue
                if any(e["from"] == a and e["to"] == b for e in edges):
                    continue
                edges.append({"id": scene.stable_id("R", "%s|%s|%s" % (a, b, rel.get("kind"))),
                              "from": a, "to": b, "kind": rel.get("kind") or "activation",
                              "label": _clean_label(rel.get("verb") or "", 18),
                              "source": item["id"]})
                used_evidence.append(item["id"])

        panel = {"id": "P%d" % (ri + 1), "role": role,
                 "title": role_titles[role],
                 "nodes": nodes, "edges": edges, "charts": []}
        for chart in charts:
            if chart_panel.get(chart["id"]) == role:
                panel["charts"].append(chart)
                used_evidence.extend(chart_ev)
        if panel["charts"]:
            labels, seen = [], set()
            for chart in panel["charts"]:
                for s in chart["series"]:
                    key = s["name"].lower()
                    if key not in seen:
                        seen.add(key)
                        labels.append(s["name"])
            panel["legend"] = {"title": "series", "items": [
                {"label": lab, "color": col}
                for lab, col in zip(labels, scene.categorical_colors(len(labels)))]}
        # the panel must not be empty: keep a labelled claim node
        if not panel["nodes"] and role_items:
            it = role_items[0]
            nid = scene.stable_id("N", _clean_label(it.get("claim"), 16).lower())
            if nid not in global_nodes:
                panel["nodes"].append({"id": nid, "shape": "rrect",
                                       "label": _clean_label(it.get("claim"), 18),
                                       "source": it["id"]})
                global_nodes[nid] = role
                used_evidence.append(it["id"])
        panels.append(panel)

    # colourbar over the encoded values (same channel the node fills use).
    # Its range must cover exactly what it encodes: mixing units (a 21 percent
    # reading next to 0.19 per second) produces a bar whose printed ends match
    # nothing on the figure, which gate D rejects.
    if valued_nodes:
        units = {}
        for _, _, u in valued_nodes:
            units[u] = units.get(u, 0) + 1
        unit = sorted(units.items(), key=lambda kv: (-kv[1], str(kv[0])))[0][0]
        target = max(panels, key=lambda p: sum(1 for n in p["nodes"]
                                               if isinstance(n.get("value"), (int, float))
                                               and n.get("unit") == unit))
        cb_vals = [n["value"] for n in target["nodes"]
                   if isinstance(n.get("value"), (int, float)) and n.get("unit") == unit]
        if len(cb_vals) < 2:
            # a colour channel needs at least two encoded values to be meaningful;
            # without that the bar would describe data the panel does not show.
            pass
        else:
            target.setdefault("colorbars", []).append({
                "id": scene.stable_id("CB", "%s|%s" % (target["id"], unit)),
                "title": "value encoded by node fill", "unit": unit or "AU",
                "vmin": round(min(cb_vals), 6), "vmax": round(max(cb_vals), 6),
                "cmap": "viridis"})
    # a supplied structure file is a workorder: make sure every declared relation
    # is actually drawn, otherwise the fallback figure can silently omit the
    # paper's headline arrow
    declared = ev.workorder_relations(materials)
    if declared:
        target = panels[2] if len(panels) > 2 else panels[-1]      # results panel
        by_label = {}
        for p in panels:
            for n in p["nodes"]:
                by_label.setdefault(ev._norm_label(n["label"]), n["id"])
        wired = {(e["from"], e["to"]) for p in panels for e in p["edges"]}
        drawn = 0
        for rel in declared:
            a = _resolve_label(rel["subject"], by_label)
            b = _resolve_label(rel["object"], by_label)
            if not a or not b or a == b:
                continue
            if (a, b) in wired:
                drawn += 1
                continue
            if (b, a) in wired:
                # the figure would contradict the workorder: flip it rather than
                # ship a reversed arrow
                for p in panels:
                    for e in p["edges"]:
                        if e["from"] == b and e["to"] == a:
                            e["from"], e["to"] = a, b
                drawn += 1
                continue
            kind = rel["kind"] if rel["kind"] in scene.EDGE_KINDS else "activation"
            # draw the declared relation in whichever panel already holds its
            # subject, instead of forcing it into the results panel
            host = next((p for p in panels if a in {n["id"] for n in p["nodes"]}), None)
            if host is None:
                continue
            src = next((n.get("source") for n in host["nodes"]
                        if n["id"] == a and n.get("source")), None)
            if not src:
                src = next((n.get("source") for n in host["nodes"] if n.get("source")), None)
            if not src:
                continue          # repair() would drop a sourceless edge anyway
            host["edges"].append({"id": scene.stable_id("R", "%s|%s|%s" % (a, b, kind)),
                                  "from": a, "to": b, "kind": kind,
                                  "label": _clean_label(rel["subject"], 18),
                                  "source": src})
            wired.add((a, b))
            drawn += 1
        chart_notes.append("workorder: %d declared relation(s) represented in the figure" % drawn)

    return panels, used_evidence, chart_notes


def _resolve_label(name, by_label):
    key = ev._norm_label(name)
    if key in by_label:
        return by_label[key]
    for lab, nid in by_label.items():
        if lab and (lab in key or key in lab):
            return nid
    return None


# --------------------------------------------------------------------------- #
# apparatus / technical-route extraction (contract §3, deterministic, no LLM)
#
# The workorder is "apparatus_and_technical_route": the material names physical
# parts, declares connections and writes the procedure down as numbered steps and
# named phases.  This section turns that prose into an editable spec.  It never
# invents an entity or a relation: every node/edge/phase cites a verbatim quote
# from a real material file and anything it cannot substantiate goes to
# limitations/uncertainty instead.
#
# scripts/domain.py (owned by the schema workstream) may carry the same
# vocabulary; when it is importable its tables are merged, but the built-in
# fallback below guarantees the extractor still works without it.
# --------------------------------------------------------------------------- #
try:                                     # noqa: E402
    import domain as _domain              # type: ignore
except Exception:                         # noqa: BLE001 - optional module
    _domain = None

APP_MAX_PARTS = 10
APP_MAX_STEPS = 8
APP_MAX_PHASES = 6
APP_MAX_APPARATUS_EDGES = 8
APP_MAX_FLOW_EDGES = 8
APP_MAX_ROUTE_EDGES = 6

PART_TYPES = ("vessel", "tank", "reactor", "column", "pump", "valve", "sensor", "probe",
              "flask", "mixer", "separator", "reservoir", "condenser", "heater", "cooler",
              "junction", "sample", "reagent", "waste", "instrument", "generic")

# (part -> English/Chinese aliases); matching is longest-alias-first.
PART_WORDS = {
    "tank": ("feed tank", "buffer tank", "storage tank", "surge tank", "tank", "储罐", "贮罐", "罐"),
    "reactor": ("stirred tank reactor", "bioreactor", "reactor", "反应器", "反应釜", "搅拌釜", "发酵罐"),
    "column": ("distillation column", "chromatography column", "packed column", "column",
               "色谱柱", "层析柱", "精馏塔", "柱"),
    "pump": ("peristaltic pump", "syringe pump", "diaphragm pump", "feed pump", "pump",
             "进料泵", "蠕动泵", "泵"),
    "valve": ("inlet valve", "outlet valve", "check valve", "needle valve", "valve",
              "截止阀", "阀门", "阀"),
    "sensor": ("transmitter", "sensor", "传感器", "变送器"),
    "probe": ("ph probe", "temperature probe", "probe", "探头", "探针", "电极"),
    "flask": ("round-bottom flask", "erlenmeyer flask", "flask", "圆底烧瓶", "锥形瓶", "烧瓶"),
    "mixer": ("static mixer", "agitator", "impeller", "stirrer", "mixer",
              "搅拌器", "搅拌桨", "混合器"),
    "separator": ("membrane module", "membrane separator", "centrifuge", "decanter",
                  "separator", "module", "分离器", "离心机", "分液器", "膜组件"),
    "reservoir": ("reservoir", "reserve tank", "储液罐", "储液池", "缓冲罐", "水槽"),
    "condenser": ("reflux condenser", "condenser", "冷凝器", "冷凝管", "冷凝塔"),
    "heater": ("heating jacket", "heat exchanger", "heating mantle", "heater", "加热套",
               "加热板", "换热器", "加热器", "加热炉", "加热"),
    "cooler": ("cooling coil", "chiller", "cooler", "冷却盘管", "冷却塔", "冷却器", "冰浴"),
    "junction": ("manifold", "junction", "三通", "接头", "汇流点", "管汇"),
    "sample": ("sampling port", "sample port", "sample loop", "取样口", "取样阀", "样品瓶"),
    "reagent": ("reagent", "buffer", "catalyst", "试剂", "缓冲液", "催化剂"),
    "waste": ("waste vessel", "waste tank", "effluent", "purge", "waste", "废液罐", "废料罐",
              "废液", "废料", "废弃物", "尾气"),
    "instrument": ("spectrophotometer", "spectrometer", "analyzer", "analyser", "detector",
                   "data logger", "flow meter", "gas flow meter", "pressure gauge",
                   "ph monitor", "ph meter", "flow monitor", "level indicator", "controller",
                   "recorder", "hplc", "仪器", "分析仪", "检测器", "光谱仪", "质谱仪", "流量计",
                   "液相色谱", "监测仪", "记录仪", "控制器"),
    "vessel": ("vessel", "釜体", "容器"),
}
PART_DISPLAY = {
    "vessel": "Vessel", "tank": "Tank", "reactor": "Reactor", "column": "Column",
    "pump": "Pump", "valve": "Valve", "sensor": "Sensor", "probe": "Probe",
    "flask": "Flask", "mixer": "Mixer", "separator": "Separator", "reservoir": "Reservoir",
    "condenser": "Condenser", "heater": "Heater", "cooler": "Cooler", "junction": "Junction",
    "sample": "Sample port", "reagent": "Reagent", "waste": "Waste vessel",
    "instrument": "Instrument", "generic": "Unit",
}
PART_SHAPE = {
    "tank": "capsule", "reactor": "rrect", "column": "rect", "pump": "circle",
    "valve": "diamond", "sensor": "circle", "probe": "circle", "flask": "note",
    "mixer": "circle", "separator": "diamond", "reservoir": "capsule", "condenser": "rect",
    "heater": "rrect", "cooler": "rrect", "junction": "diamond", "sample": "rrect",
    "reagent": "rrect", "waste": "note", "instrument": "rrect", "vessel": "capsule",
    "generic": "rrect",
}

# Desired edge kind -> a kind the live schema must accept.  The v1.1 vocabulary
# (material/fluid/gas/energy/signal/...) only renders as itself once scene.py
# carries it; until then the same relation is drawn with a legal legacy kind and
# the semantic kind is preserved in meta.expected_relations_semantic.
KIND_FALLBACK = {
    "material": "flow", "fluid": "flow", "gas": "flow", "waste": "flow",
    "sequence": "flow", "branch": "flow", "merge": "flow",
    "energy": "activation", "heat": "activation",
    "signal": "feedback", "control": "feedback", "loop": "feedback",
    "assembly": "spatial",
}
NEW_EDGE_KINDS = ("material", "fluid", "gas", "energy", "heat", "signal", "control",
                  "assembly", "sequence", "branch", "merge", "loop", "waste")

_TAG_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,4}[-]?\d{1,4}[A-Z]?)(?![A-Za-z0-9])")
# The material may declare the device type outright: "A12 UV-LED driver (part: instrument)".
# That annotation is authoritative and is safer than any alias table.
_PART_HINT = re.compile(r"\((?:part|type)\s*[:=]\s*([A-Za-z_\-]+)\)", re.I)
_TAG_STOP = {"SOP", "PL", "FIG", "TAB", "TABLE", "STEP", "PH", "CB", "OK", "PDF", "CSV",
             "PNG", "SVG", "ISO", "GB", "DIN"}

# Umbrella words: they name a *category of drawing*, not a device.  A section
# heading ("3 Experimental apparatus and process") or a title ("Apparatus list")
# contains one of these and nothing else, and minting a part from it put an
# entity on the figure that no material lists -- the quote resolved verbatim, so
# gate E could not catch it.  This set is a second, independent line of defence:
# it keeps working even if a shared alias table grows such a word back.
_GENERIC_PART_WORDS = {
    "apparatus", "equipment", "setup", "set-up", "schematic", "instrumentation",
    "assembly line", "device", "hardware", "rig", "system", "process", "procedure",
    "unit", "component", "module", "machinery", "plant", "line", "train",
    "装置", "设备", "仪器", "系统", "流程", "工艺", "装置图", "装置示意", "设备清单",
    "部件", "组件", "单元", "通用件", "仪器设备", "装置清单",
}

_ARROW_SPLIT = re.compile(r"\s*(?:->|-->|=>|→|⇒|⟶|—>)\s*")
_TRANSPORT_RX = (
    (re.compile(r"\b(?:transfer(?:s|red|ring)?|flow(?:s|ed|ing)?|feed(?:s|ing)?|pump(?:s|ed|ing)?"
                r"|deliver(?:s|ed|ing)?|discharg(?:e|es|ed|ing)|pass(?:es|ed)?|send(?:s|t)?"
                r"|rout(?:e|es|ed)|charg(?:e|es|ed)|dose(?:s|d)?|add(?:s|ed)?|mov(?:e|es|ed|ing)"
                r"|run(?:s)?|ran|lead(?:s|ing)?|led|carr(?:y|ies|ied)|return(?:s|ed|ing)?"
                r"|drain(?:s|ed|ing)?|vent(?:s|ed|ing)?|withdraw(?:s|n|ing)?|pip(?:e|es|ed|ing)"
                r"|direct(?:s|ed|ing)?|recirculat(?:e|es|ed|ing)|sparg(?:e|es|ed|ing)"
                r"|suppl(?:y|ies|ied)|empt(?:y|ies|ied)|fill(?:s|ed|ing)?)\b[^.;:!?]{0,40}?"
                r"\b(?:in)?to\b", re.I), "material"),
    (re.compile(r"\b(?:enters?|entered|entering)\b", re.I), "material"),
    (re.compile(r"\binto\b", re.I), "material"),
    (re.compile(r"\b(?:logged|recorded|measured|monitored|tracked)\s+by\b", re.I), "signal"),
    (re.compile(r"\b(?:connect(?:s|ed)?|coupl(?:e|es|ed)|join(?:s|ed)?|mount(?:s|ed)?)"
                r"\s+(?:in)?to\b", re.I), "assembly"),
)
_CN_TRANSPORT_RX = (
    (re.compile(r"输送[^。；，,]{0,14}至"), "material"),
    (re.compile(r"(?:送|泵|流|通|导|注|加入)[^。；，,]{0,10}入"), "material"),
    (re.compile(r"(?:排|排放)[^。；，,]{0,10}至"), "waste"),
    (re.compile(r"排入"), "waste"),
    (re.compile(r"收集[^。；，,]{0,10}至"), "waste"),
)
_KIND_WORDS = (
    ("waste", ("waste", "effluent", "purge", "discharge", "废液", "废料", "尾气", "排放", "废弃物")),
    ("gas", ("vapour", "vapor", "gas", "气相", "蒸汽", "尾气", "co2", "n2", "o2")),
    ("energy", ("heat", "heating", "heater", "heated", "thermal", "steam",
                "cool", "cooling", "cooler", "chiller", "加热", "冷却", "热")),
    ("signal", ("signal", "logged", "monitor", "measure", "sensor reading", "信号", "数据", "监测", "检测")),
    ("control", ("control", "regulat", "feedback", "setpoint", "控制", "调节", "反馈")),
    ("assembly", ("connect", "coupled", "mounted", "assembly", "joined", "连接", "装配", "固定")),
    ("loop", ("recycle", "reflux", "recirculat", "回流", "循环")),
    ("sequence", ("subsequently", "then", "随后", "然后", "接着")),
)
_EXPLICIT_KIND_WORDS = tuple(KIND_FALLBACK) + tuple(_KIND_WORDS[i][0] for i in range(len(_KIND_WORDS)))


def _alias_is_ascii(alias):
    return all(ord(ch) < 128 for ch in alias)


def _part_alias_order():
    table = {}
    for part, words in PART_WORDS.items():
        for w in words:
            table.setdefault(w.lower(), part)
    extra = _domain_part_words()
    for w, part in extra.items():
        if part in PART_TYPES and w:
            table.setdefault(str(w).lower(), part)
    return tuple(sorted(table.items(), key=lambda kv: (-len(kv[0]), kv[0])))


_DOMAIN_ALIAS_STOP = {"well", "unit", "cell", "chip", "vat", "bed", "line", "loop", "arm", "bag",
                      "device", "system", "\u6392\u653e", "\u6392\u6c61",
                      # single-character CJK nouns: weight 2, i.e. the same risk class
                      # as two-letter ASCII words ("at", "in", "of").  They are
                      # deliberately NOT taken from the shared table; the built-in
                      # table already carries them, and multi-character forms
                      # (\u8272\u8c31\u67f1 / \u5c42\u6790\u67f1 / \u8fdb\u6599\u6cf5 ...) win by longest-alias-first.
                      # Lowering the weight threshold instead would admit every
                      # two-letter English word, so never do that.
                      "\u67f1", "\u6cf5", "\u7f50", "\u9600"}


def _alias_weight(alias):
    """Information weight of an alias: a CJK character carries a whole morpheme.

    Counting raw characters treated "\u70ed\u7535\u5076" (thermocouple, three characters) as shorter than
    "well", so 43 Chinese device nouns in the shared table were silently dropped.
    domain.py exports the same function; its value is used when available so a
    single definition governs both modules.
    """
    text = alias or ""
    fn = getattr(_domain, "alias_weight", None) if _domain is not None else None
    if callable(fn):
        try:
            value = fn(text)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        except Exception:  # noqa: BLE001 - optional module
            pass
    return sum(2 if ord(ch) > 0x7F else 1 for ch in text)


def _domain_part_words():
    """Best-effort merge of a domain.py alias table (shape is not contractual).

    Aliases that carry almost no information are dropped: ASCII words shorter
    than four characters and the ambiguous ones listed in ``_DOMAIN_ALIAS_STOP``.
    A Chinese device noun is measured by :func:`_alias_weight`, not by its length
    in characters, so "\u70ed\u7535\u5076" / "\u7403\u9600" / "\u7cbe\u998f\u67f1" survive while bare "well" / "unit" / "cell" do not.
    """
    if _domain is None:
        return {}
    for name in ("PART_ALIASES", "PART_WORDS", "PART_ALIAS", "PART_KEYWORDS"):
        table = getattr(_domain, name, None)
        if not isinstance(table, dict):
            continue
        out = {}
        for k, v in table.items():
            if isinstance(v, str):
                candidates = [(k, v)]
            elif isinstance(v, (list, tuple)):
                candidates = [(alias, k) for alias in v]
            elif isinstance(k, (list, tuple)) and isinstance(v, str):
                candidates = [(alias, v) for alias in k]
            else:
                continue
            for alias, part in candidates:
                if not isinstance(alias, str) or not isinstance(part, str):
                    continue
                alias = alias.strip()
                if _alias_weight(alias) < 4 or alias.lower() in _DOMAIN_ALIAS_STOP:
                    continue
                out[alias] = part
        if out:
            return out
    return {}


_PART_ALIAS_ORDER = None


def _part_aliases():
    global _PART_ALIAS_ORDER
    if _PART_ALIAS_ORDER is None:
        _PART_ALIAS_ORDER = _part_alias_order()
    return _PART_ALIAS_ORDER


def _live_edge_kinds():
    kinds = set(getattr(scene, "EDGE_KINDS", ()) or ())
    for name in ("EDGE_KINDS_V11", "EDGE_KINDS_V1_1"):
        extra = getattr(scene, name, None)
        if extra:
            kinds |= set(extra)
    return kinds


def _effective_kind(desired):
    live = _live_edge_kinds()
    if desired in live:
        return desired
    fallback = KIND_FALLBACK.get(desired)
    if fallback and fallback in live:
        return fallback
    if "flow" in live:
        return "flow"
    return sorted(live)[0] if live else "flow"


def _live_panel_roles():
    for name in ("PANEL_ROLES_V11", "PANEL_ROLES"):
        roles = getattr(scene, name, None)
        if roles:
            return list(roles)
    return []


def _role(name, fallback):
    return name if name in _live_panel_roles() else fallback


def _live_part_types():
    live = set(getattr(scene, "PART_TYPES", ()) or ())
    return live or set(PART_TYPES)


def _effective_part(part):
    live = _live_part_types()
    part = part if part in PART_TYPES else "generic"
    if part in live:
        return part
    if "generic" in live:
        return "generic"
    return sorted(live)[0] if live else "generic"


def _key(text):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (text or "").lower())


def _norm(text):
    return ev._norm(text)


# --------------------------------------------------------------------------- #
# evidence factory: one resolvable item per (file, locator, quote)
# --------------------------------------------------------------------------- #
class _EvidenceFactory(object):
    def __init__(self, materials):
        self.materials = materials
        self.items = []
        self._seen = {}

    def add(self, mat, start, end, kind, claim=None):
        if not isinstance(mat, dict):
            return None
        item = ev.evidence_for(mat, start, end, kind, claim=claim)
        if item is None:
            return None
        key = (item["source"]["file"], item["source"]["locator"],
               _norm(item["source"]["quote"]))
        if key in self._seen:
            return self._seen[key]
        res = ev.resolve_locator(item, self.materials)
        if not (res or {}).get("ok"):
            found = (res or {}).get("locator")
            if found and found != item["source"]["locator"]:
                item["source"]["locator"] = found
                res = ev.resolve_locator(item, self.materials)
        if not (res or {}).get("ok"):
            return None                     # never ship an unverifiable quote
        item["id"] = "X%d" % (len(self.items) + 1)
        item["section"] = "apparatus" if kind in ("part", "connection") else kind
        item["resolved"] = res
        self.items.append(item)
        self._seen[key] = item["id"]
        return item["id"]


# --------------------------------------------------------------------------- #
# parts
# --------------------------------------------------------------------------- #
def _alias_hits(line):
    low = line.lower()
    used = [False] * len(line)
    hits = []
    for alias, part in _part_aliases():
        if not alias:
            continue
        if _alias_is_ascii(alias):
            for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])", low):
                if any(used[m.start():m.end()]):
                    continue
                for i in range(m.start(), m.end()):
                    used[i] = True
                hits.append((m.start(), m.end(), part, alias))
        else:
            pos = low.find(alias)
            while pos >= 0:
                end = pos + len(alias)
                if not any(used[pos:end]):
                    for i in range(pos, end):
                        used[i] = True
                    hits.append((pos, end, part, alias))
                pos = low.find(alias, end)
    hits.sort(key=lambda h: (h[0], h[1], h[2]))
    return hits


def _tags_in(line):
    out = []
    for m in _TAG_RE.finditer(line):
        tag = m.group(1)
        if tag.upper().split("-")[0] in _TAG_STOP:
            continue
        out.append((m.start(), m.end(), tag))
    return out


def _part_hint(line):
    """The device type the material declares outright, e.g. ``(part: pump)``."""
    m = _PART_HINT.search(line or "")
    if not m:
        return None
    raw = m.group(1).strip().lower().replace("-", "_")
    if raw in PART_TYPES:
        return raw
    try:
        import domain as _dom
        got = _dom.canonical_part(raw, allowed=PART_TYPES)
    except Exception:  # noqa: BLE001 - optional module
        got = None
    return got if got in PART_TYPES else None


def _cell_spans(line):
    """Character spans between the ``|`` separators of a markdown/CSV table row."""
    bars = [m.start() for m in re.finditer(r"\|", line or "")]
    return [(a + 1, b) for a, b in zip(bars, bars[1:])]


def _in_parens(line, start, end):
    """True when the span sits inside (...) or （...）: an annotation, not a name."""
    for opener, closer in (("(", ")"), ("\uff08", "\uff09")):
        left = line.rfind(opener, 0, start)
        right = line.rfind(closer, 0, start)
        if left > right:
            close_at = line.find(closer, start)
            if close_at < 0 or close_at >= end:
                return True
    return False


def _row_tag_and_cells(line, tags):
    """(tags that identify THIS row, cells where its device name may appear).

    Only the first tag-bearing cell identifies the row.  Later columns often
    mention other units ("... transfers medium to R-201"); treating those as the
    row identity minted a "Reagent R-201" out of a service description, before the
    real reactor row had a chance to define R-201 as a reactor.
    """
    cells = _cell_spans(line)
    if not cells or not tags:
        return tags, None
    for ci, (cs, ce) in enumerate(cells):
        row_tags = [t for t in tags if cs <= t[0] and t[1] <= ce]
        if not row_tags:
            continue
        name_cells = [(cs, ce)]
        if ci + 1 < len(cells):
            name_cells.append(cells[ci + 1])
        return row_tags, name_cells
    return tags, None


def _tag_for(hit, tags, taken):
    best = None
    for start, end, tag in tags:
        if tag in taken:
            continue
        if start >= hit[1] and start - hit[1] > 26:
            continue
        if end <= hit[0] and hit[0] - end > 26:
            continue
        dist = min(abs(start - hit[1]), abs(hit[0] - end))
        key = (dist, start)
        if best is None or key < best[0]:
            best = (key, tag)
    return best[1] if best else None


def _apparatus_nodes(materials, fac):
    nodes, notes = [], []
    order, by_tag, by_label = [], {}, {}
    capped, overflow = False, []
    skipped_generic, skipped_heading = [], []
    for mat in ev._text_materials(materials):
        text = mat.get("text") or ""
        for start, end, line in ev.line_spans(text):
            hits = _alias_hits(line)
            tags = _tags_in(line)
            if _cell_spans(line):
                tags, name_cells = _row_tag_and_cells(line, tags)
            else:
                name_cells = None
            hint = _part_hint(line)
            if not hits and not (hint and tags):
                continue
            is_heading = ev.heading_like(line)
            hits = [h for h in hits
                    if not _in_parens(line, h[0], h[1])
                    and (name_cells is None
                         or any(cs <= h[0] and h[1] <= ce for cs, ce in name_cells))]
            if not hits and not (hint and tags):
                continue
            taken = set()
            for hit in hits:
                alias = (hit[3] or "").strip().lower()
                if alias in _GENERIC_PART_WORDS:
                    # an umbrella word is never a part, whatever the shared alias
                    # table says: "apparatus" in a chapter title is not a unit
                    if hint and tags:
                        break        # the material declares the type explicitly below
                    if alias not in skipped_generic:
                        skipped_generic.append(alias)
                    continue
                part = _effective_part(hit[2])
                tag = _tag_for(hit, tags, taken)
                if tags and not tag:
                    # a line that names tagged units describes THOSE units ("the
                    # reactor" in the row for R-201); making it a second, untagged
                    # part is how a figure gains a unit the material never lists
                    continue
                if is_heading and not tag:
                    # a title / section heading can only introduce a device that it
                    # NAMES WITH A TAG ("Reactor R-201"); a bare noun in a heading
                    # ("3 Experimental apparatus and process") is document furniture
                    if alias not in skipped_heading:
                        skipped_heading.append(alias)
                    continue
                if tag:
                    taken.add(tag)
                    key = tag.lower()
                else:
                    key = _key(PART_DISPLAY.get(part, part))
                if key in by_tag:
                    continue
                label = "%s %s" % (PART_DISPLAY.get(part, part), tag) if tag else \
                    PART_DISPLAY.get(part, part)
                lab_key = _key(label)
                if lab_key in by_label:
                    continue
                if len(order) >= APP_MAX_PARTS:
                    # remember how this unit would have been named, so the
                    # limitation is only reported when it is really not drawn
                    if tag:
                        overflow.append(({tag.lower(), PART_DISPLAY.get(part, part).lower()}, tag))
                    capped = True
                    break
                eid = fac.add(mat, start, end, "part", claim=line)
                if not eid:
                    continue
                node = {"id": scene.stable_id("N", key), "shape": PART_SHAPE.get(part, "rrect"),
                        "label": _clean_label(label, 22), "part": part, "source": eid,
                        "_keys": [tag.lower()] if tag else [], "_display": part,
                        "_tag": tag}
                for written in (PART_DISPLAY.get(part, part), hit[3]):
                    node["_keys"].append(written.lower())
                nodes.append(node)
                order.append(key)
                by_tag[key] = node["id"]
                by_label[lab_key] = node["id"]
            # an explicit "(part: X)" annotation is the material telling us the
            # device type -- far more reliable than any alias, and it also covers
            # units whose own name is not in the alias table ("UV-LED driver")
            if hint and tags:
                for _start, _end, tag in tags:
                    if tag in taken:
                        continue
                    taken.add(tag)
                    key = tag.lower()
                    if key in by_tag:
                        continue
                    part = _effective_part(hint)
                    label = "%s %s" % (PART_DISPLAY.get(part, part), tag)
                    lab_key = _key(label)
                    if lab_key in by_label:
                        continue
                    if len(order) >= APP_MAX_PARTS:
                        overflow.append(({tag.lower(), PART_DISPLAY.get(part, part).lower()}, tag))
                        capped = True
                        break
                    eid = fac.add(mat, start, end, "part", claim=line)
                    if not eid:
                        continue
                    node = {"id": scene.stable_id("N", key),
                            "shape": PART_SHAPE.get(part, "rrect"),
                            "label": _clean_label(label, 22), "part": part, "source": eid,
                            "_keys": [key, PART_DISPLAY.get(part, part).lower()],
                            "_display": part, "_tag": tag}
                    nodes.append(node)
                    order.append(key)
                    by_tag[key] = node["id"]
                    by_label[lab_key] = node["id"]
            if capped:
                break
        if capped:
            break
    nodes, remap = _merge_untagged_nodes(nodes)
    kept_keys = set()
    for node in nodes:
        kept_keys.update(k for k in (node.get("_keys") or []))
    dropped = [display for keys, display in overflow if not (keys & kept_keys)]
    if dropped:
        notes.append("the material names %d more unit(s) (%s) than the figure shows; they are "
                     "recorded here instead of being invented"
                     % (len(dropped), ", ".join(dropped[:3])))
    if skipped_generic:
        notes.append("umbrella word(s) %s were not treated as an apparatus part: they name a "
                     "category of drawing, not a device, so no entity was minted from them"
                     % ", ".join(skipped_generic[:4]))
    return [_public_node(n) for n in nodes], _key_index(nodes), notes


def _merge_untagged_nodes(nodes):
    """Fold an untagged part into the unique tagged part of the same type.

    "the reactor" and "R-201" are the same equipment; keeping both would put a
    duplicate vessel on the figure and split the arrows between them.
    """
    tagged = {}
    for node in nodes:
        if node.get("_tag"):
            tagged.setdefault(node.get("_display"), []).append(node)
    remap = {}
    for node in nodes:
        if node.get("_tag"):
            continue
        candidates = tagged.get(node.get("_display")) or []
        if len(candidates) != 1:
            continue
        keep = candidates[0]
        keep["_keys"] = list(dict.fromkeys((keep.get("_keys") or []) + (node.get("_keys") or [])))
        remap[node["id"]] = keep["id"]
    if remap:
        nodes = [n for n in nodes if n["id"] not in remap]
    return nodes, remap


def _public_node(node):
    return {k: v for k, v in node.items() if not k.startswith("_")}


def _key_index(nodes):
    out = []
    for n in nodes:
        keys = [k for k in (n.get("_keys") or []) if k]
        if n.get("_tag"):
            keys.append(n["_tag"].lower())
        seen, uniq = set(), []
        for k in keys:
            if k not in seen:
                seen.add(k)
                uniq.append(k)
        out.append({"id": n["id"], "_keys": uniq, "part": n.get("part")})
    return out


def _node_span(segment, node):
    low = (segment or "").lower()
    best = None
    for key in node.get("_keys") or []:
        if not key:
            continue
        if _alias_is_ascii(key):
            m = re.search(r"(?<![A-Za-z0-9])" + re.escape(key) + r"(?![A-Za-z0-9])", low)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), m.end())
        else:
            pos = low.find(key)
            if pos >= 0 and (best is None or pos < best[0]):
                best = (pos, pos + len(key))
    return best


def _first_node_in(segment, nodes):
    best = None
    for node in nodes:
        span = _node_span(segment, node)
        if span and (best is None or span[0] < best[0]):
            best = (span[0], node["id"])
    return best[1] if best else None


def _last_node_in(segment, nodes):
    best = None
    for node in nodes:
        span = _node_span(segment, node)
        if span and (best is None or span[1] > best[0]):
            best = (span[1], node["id"])
    return best[1] if best else None


def _explicit_kind(line, default):
    for m in re.finditer(r"[\(\[]([^\)\]]{2,60})[\)\]]", line):
        inner = m.group(1).lower()
        for word in _EXPLICIT_KIND_WORDS:
            if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", inner):
                return word
    for kind, words in _KIND_WORDS:
        for word in words:
            if word in line.lower():
                return kind
    return default


def _connector_splits(line):
    """-> [(left, right, kind)] for directed connectors only (never a bare 'to')."""
    out = []
    parts_ = _ARROW_SPLIT.split(line)
    if len(parts_) > 1:
        for i in range(len(parts_) - 1):
            left, right = parts_[i], parts_[i + 1]
            if left.strip() and right.strip():
                out.append((left, right, "material"))
        return out
    for rx, kind in _TRANSPORT_RX + _CN_TRANSPORT_RX:
        for m in rx.finditer(line):
            left, right = line[:m.start()], line[m.end():]
            if left.strip() and right.strip():
                out.append((left, right, kind))
    return out


_PORT_DECL = re.compile(r"\([^()]{0,40}?\b(from|to)\b\s*([A-Z]{1,4}[-]?\d{1,4})[^()]{0,40}?\)", re.I)
_PORT_WORD = re.compile(r"\bports?\b|接口|进出口", re.I)


def _connections(materials, fac, app_nodes):
    """Directed connections among apparatus nodes, deduplicated, capped."""
    edges, notes = [], []
    seen = set()
    capped = [False]

    def node_by_tag(tag):
        low = (tag or "").lower()
        for node in app_nodes:
            if low in (node.get("_keys") or []):
                return node["id"]
        return None

    def add(a, b, semantic, mat, start, end, line):
        if not a or not b or a == b:
            return
        kind = _effective_kind(semantic)
        if kind == "waste":
            target = next((n for n in app_nodes if n["id"] == b), None)
            if not target or target.get("part") != "waste":
                kind, semantic = _effective_kind("material"), "material"
        if (a, b, kind) in seen:
            return
        if len(edges) >= APP_MAX_APPARATUS_EDGES:
            capped[0] = True
            return
        eid = fac.add(mat, start, end, "connection", claim=line)
        if not eid:
            return
        seen.add((a, b, kind))
        edges.append({"id": scene.stable_id("R", "%s|%s|%s" % (a, b, kind)),
                      "from": a, "to": b, "kind": kind,
                      "label": _clean_label(PART_DISPLAY.get(semantic, semantic), 16),
                      "source": eid})

    for mat in ev._text_materials(materials):
        text = mat.get("text") or ""
        for start, end, line in ev.line_spans(text):
            # explicit port declarations: "inlet (bottom, from A3), outlet (top, to A6)"
            if _PORT_WORD.search(line):
                decls = _PORT_DECL.findall(line)
                if decls:
                    first = _PORT_DECL.search(line)
                    owner = _last_node_in(line[:first.start()], app_nodes) or \
                        _first_node_in(line, app_nodes)
                    if owner:
                        for direction, tag in decls:
                            other = node_by_tag(tag)
                            if not other:
                                continue
                            if direction.lower() == "to":
                                add(owner, other, "material", mat, start, end, line)
                            else:
                                add(other, owner, "material", mat, start, end, line)
            for left, right, default_kind in _connector_splits(line):
                a = _last_node_in(left, app_nodes)
                b = _first_node_in(right, app_nodes)
                if not a or not b or a == b:
                    continue
                semantic = _explicit_kind(line, default_kind)
                add(a, b, semantic, mat, start, end, line)
    if capped[0]:
        notes.append("connection extraction capped at %d edges; further declared connections "
                     "were dropped (listed in limitations, never invented)" % APP_MAX_APPARATUS_EDGES)
    return edges, notes


# --------------------------------------------------------------------------- #
# steps (flow) and phases (route)
# --------------------------------------------------------------------------- #
def _flow_nodes(materials, fac, app_nodes):
    nodes, notes = [], []
    claims = ev.step_claims(materials)
    picked = []
    for c in claims:
        k = _key(c["text"])
        if not k:
            continue
        dup = False
        for p in picked:
            pk = _key(p["text"])
            # the same numbered step is often present twice (a PDF re-states the
            # markdown procedure); a prefix match plus the same number catches it
            # without merging genuinely different steps
            if (pk.startswith(k) or k.startswith(pk)) and len(k) >= 12:
                dup = True
                break
            if c["source_no"] == p["source_no"] and k[:24] == pk[:24]:
                dup = True
                break
        if dup:
            continue
        picked.append(c)
        if len(picked) >= APP_MAX_STEPS:
            break
    if picked:
        orig = [c["source_no"] for c in picked]
        expected = list(range(1, len(picked) + 1))
        if orig != expected:
            notes.append("source step numbering %s was renumbered 1..%d in document order so the "
                         "flow sequence stays contiguous (gate J902)" % (orig, len(picked)))
    for i, c in enumerate(picked, start=1):
        eid = fac.add(c["mat"], c["start"], c["end"], "step", claim=c["text"])
        if not eid:
            continue
        nodes.append({"id": scene.stable_id("N", "step%d|%s" % (i, _key(c["text"]))),
                      "shape": "capsule", "label": _clean_label(c["text"], 26),
                      "step_no": i, "source": eid})
    if not nodes:
        # no numbered procedure: reuse the apparatus order so the flow panel is
        # still a real, sourced route instead of an invented one
        notes.append("no numbered procedure was found in the material; the flow panel follows "
                     "the apparatus in document order (no step claim could be made)")
        for i, node in enumerate(app_nodes[:APP_MAX_STEPS], start=1):
            if not node.get("source"):
                continue
            nodes.append({"id": scene.stable_id("N", "flow%d|%s" % (i, node["id"])),
                          "shape": "capsule", "label": node["label"], "step_no": i,
                          "source": node["source"]})
    return nodes, notes


def _phase_dep_target(phrase, title_index, prior_ids, order_ids):
    num = None
    m = re.search(r"(phase|stage|阶段)\s*([0-9]{1,2}|[一二三四五六七八九十]{1,3})", phrase, re.I)
    if m:
        tok = m.group(2)
        num = int(tok) if tok.isdigit() else ev._CN_NUMBER.get(tok)
    if num is not None and 1 <= num <= len(order_ids):
        cand = order_ids[num - 1]
        if cand in prior_ids:
            return cand
    key = _key(phrase)
    for title, pid in title_index.items():
        if key and (key in title or title in key) and pid in prior_ids:
            return pid
    return None


def _route_phases(materials, fac):
    claims = ev.phase_claims(materials) + ev.phase_claims_from_tables(materials)
    phases, nodes, notes = [], [], []
    seen = set()
    for c in claims:
        k = _key(c.get("title"))
        if not k or k in seen:
            continue
        seen.add(k)
        if len(phases) >= APP_MAX_PHASES:
            notes.append("phase extraction capped at %d phases" % APP_MAX_PHASES)
            break
        pid = scene.stable_id("PH", k)
        eid = fac.add(c["mat"], c["start"], c["end"], "phase", claim=c.get("title"))
        if not eid:
            continue
        fields = c.get("fields") or {}
        phase = {"id": pid, "title": _clean_label(c.get("title") or "Phase", 30),
                 "goal": "; ".join(fields.get("goal") or []),
                 "methods": list(fields.get("methods") or []),
                 "inputs": list(fields.get("inputs") or []),
                 "outputs": list(fields.get("outputs") or []),
                 "depends_on": [], "source": eid}
        phase["_explicit"] = list(fields.get("depends_on") or [])
        phases.append(phase)
        nid = scene.stable_id("N", "stage|" + k)
        nodes.append({"id": nid, "shape": "rrect", "label": _clean_label(c.get("title") or "Phase", 22),
                      "stage": pid, "source": eid, "_phase": pid})
    order_ids = [p["id"] for p in phases]
    title_index = {_key(p["title"]): p["id"] for p in phases}
    for i, phase in enumerate(phases):
        deps = []
        for phrase in phase.get("_explicit") or []:
            target = _phase_dep_target(phrase, title_index, set(order_ids[:i]), order_ids)
            if target and target not in deps:
                deps.append(target)
            elif target is None:
                notes.append("explicit dependency %r of phase %r could not be resolved to an "
                             "earlier phase and was dropped" % (phrase, phase["title"]))
        if not deps and i > 0:
            deps = [order_ids[i - 1]]
        phase["depends_on"] = deps
    for phase in phases:
        phase.pop("_explicit", None)
    return phases, nodes, notes


# --------------------------------------------------------------------------- #
def _apparatus_mode(materials, items):
    text = materials.get("task_text") or ""
    for m in (materials.get("materials") or []):
        if m.get("parsed") and m.get("role") == "material":
            text += "\n" + (m.get("text") or "")[:6000]
    low = text.lower()
    for kw in ("apparatus", "technical route", "process flow", "flow diagram", "unit operation",
               "装置", "工艺", "流程", "路线", "设备", "反应器", "反应釜"):
        if kw in low:
            return True
    if len(ev.step_claims(materials)) >= 2:
        return True
    if ev.phase_claims(materials) or ev.phase_claims_from_tables(materials):
        return True
    return False


def derive_apparatus_spec(materials, ledger, case_id):
    items = list(ledger.get("items") or [])
    if not items:
        items = ev.fallback_evidence(materials)
    fac = _EvidenceFactory(materials)
    notes, limitations = [], []

    app_nodes, app_index, app_notes = _apparatus_nodes(materials, fac)
    notes.extend(app_notes)
    flow_nodes, flow_notes = _flow_nodes(materials, fac, app_nodes)
    notes.extend(flow_notes)
    phases, route_nodes, route_notes = _route_phases(materials, fac)
    notes.extend(route_notes)
    app_edges, edge_notes = _connections(materials, fac, app_index)
    notes.extend(edge_notes)

    # charts come from the ledger's table claims (each row already has evidence)
    charts, chart_ev, chart_notes = charts_from_tables(materials, items, fac=fac)
    if not charts:
        charts, alt_ev, chart_notes2 = charts_from_numbers(items)
        chart_ev = alt_ev or chart_ev
        chart_notes = chart_notes + chart_notes2
    notes.extend(chart_notes)

    ro_app = _role("apparatus", "problem")
    ro_flow = _role("flow", "method")
    ro_route = _role("route", "conclusion")
    ro_data = _role("data", "results")
    if _role("conditions", "results") == "conditions" and not _live_panel_roles():
        ro_data = "results"

    panels = []
    panels.append({"id": "P1", "role": ro_app, "title": "Apparatus: parts named in the material",
                   "nodes": app_nodes, "edges": app_edges, "charts": []})
    flow_edges = []
    for i in range(len(flow_nodes) - 1):
        a, b = flow_nodes[i]["id"], flow_nodes[i + 1]["id"]
        kind = _effective_kind("sequence")
        src = flow_nodes[i + 1].get("source") or flow_nodes[i].get("source")
        if not src:
            continue
        flow_edges.append({"id": scene.stable_id("R", "%s|%s|%s" % (a, b, kind)),
                           "from": a, "to": b, "kind": kind, "label": "next", "source": src})
    flow_edges = flow_edges[:APP_MAX_FLOW_EDGES]
    panels.append({"id": "P2", "role": ro_flow,
                   "title": "Technical route: numbered procedure",
                   "nodes": flow_nodes, "edges": flow_edges, "charts": [],
                   "sequence": [n["id"] for n in flow_nodes]})
    route_edges = []
    node_of_phase = {n.get("_phase"): n["id"] for n in route_nodes}
    for phase in phases:
        for dep in phase.get("depends_on") or []:
            a, b = node_of_phase.get(dep), node_of_phase.get(phase["id"])
            src = phase.get("source")
            if not a or not b or not src:
                continue
            kind = _effective_kind("sequence")
            route_edges.append({"id": scene.stable_id("R", "%s|%s|%s" % (a, b, kind)),
                                "from": a, "to": b, "kind": kind, "label": "then", "source": src})
    route_edges = route_edges[:APP_MAX_ROUTE_EDGES]
    route_panel = {"id": "P3", "role": ro_route, "title": "Phases of the technical route",
                   "nodes": [_public_node(n) for n in route_nodes],
                   "edges": route_edges, "charts": [],
                   "sequence": [n["id"] for n in route_nodes]}
    if phases:
        route_panel["phases"] = [_public_phase(p) for p in phases]
    panels.append(route_panel)

    data_panel = {"id": "P4", "role": ro_data, "title": "Conditions and measured values",
                  "nodes": [], "edges": [], "charts": charts}
    if charts:
        names, seen_names = [], set()
        for chart in charts:
            for series in chart.get("series") or []:
                key = (series.get("name") or "").lower()
                if key and key not in seen_names:
                    seen_names.add(key)
                    names.append(series["name"])
        if names:
            data_panel["legend"] = {"title": "series", "items": [
                {"label": lab, "color": col}
                for lab, col in zip(names, scene.categorical_colors(len(names)))]}
    panels.append(data_panel)

    # never empty, but never invented either: a panel with no part/step/phase gets
    # a real sourced claim node -- never a section heading, never a fabricated
    # device.  If nothing suitable exists the panel stays empty and says so.
    if not app_nodes:
        panels[0]["nodes"] = _placeholder_nodes(items, ro_app, part=_effective_part("generic"))
    if not flow_nodes:
        panels[1]["nodes"] = _placeholder_nodes(items, ro_flow)
        panels[1].pop("sequence", None)
    if not route_nodes:
        panels[2]["nodes"] = _placeholder_nodes(items, ro_route)
        panels[2].pop("sequence", None)
        limitations.append("No phase/stage structure could be extracted, so the technical-route "
                           "panel carries a sourced statement instead of an invented phase list.")
    if not app_nodes:
        limitations.append("No equipment could be identified in the material (no device name or tag "
                           "was found); the apparatus panel carries a verbatim sourced statement "
                           "instead of an invented unit, and no device is drawn.")

    used = [n.get("source") for p in panels for n in p["nodes"]]
    used += [e.get("source") for p in panels for e in p["edges"]]
    used += list(chart_ev)
    evidence_items = _collect_evidence(fac, items, used)
    if not evidence_items:
        evidence_items = ev.fallback_evidence(materials)

    limitations.extend(notes)
    if not materials.get("parsable"):
        limitations.append("No material file yielded readable text; the figure can only restate "
                           "the task/input metadata and makes no scientific claim.")
    if not phases:
        limitations.append("No phase/stage headings were found; depends_on is therefore empty and "
                           "gate J904 has nothing to check.")
    uncertainty = []
    for w in (materials.get("warnings") or []):
        uncertainty.append({"kind": w.get("kind"), "subject": w.get("subject"),
                            "reason": w.get("reason"), "needs_human": bool(w.get("needs_human"))})

    title = _title(materials, {"items": items}, case_id)
    language = "zh" if _cjk_ratio(" ".join(
        (m.get("text") or "")[:4000] for m in (materials.get("materials") or []))) > 0.15 else "en"
    canvas = dict(AUTOSPEC_CANVAS)
    orientation = "landscape" if canvas["w_mm"] >= canvas["h_mm"] else "portrait"
    spec = {
        "version": scene.VERSION,
        "meta": {
            "case_id": case_id,
            "title": title,
            "subtitle": _clean_label(_norm(materials.get("task_text") or ""), 140),
            "language": language,
            "canvas": canvas,
            "orientation": orientation,
            "workorder": "apparatus_and_technical_route",
            "layout": {"columns": 2, "row_order": [ro_app, ro_flow, ro_route, ro_data]},
            "generated_by": "autospec (deterministic fallback, no LLM)",
        },
        "palette": {"id": "okabe-ito", "cvd_safe": True},
        "texts": {
            "caption": AUTOSPEC_CAPTION,
            "conclusion": _route_conclusion(phases, panels),
        },
        "evidence": evidence_items,
        "panels": panels,
        "uncertainty": uncertainty,
        "limitations": limitations,
        "change_records": [{"kind": "autospec", "source": "materials.json + evidence-ledger.json",
                            "result": "deterministic apparatus/route spec", "human_edit": False}],
    }
    return repair(spec, required_roles=[ro_app, ro_flow, ro_route, ro_data])


def _collect_evidence(fac, items, used):
    """The evidence items actually cited by the figure (deterministic order).

    Items created by the factory come first, then ledger items, each in first-use
    order.  Only cited items ship, so the ledger cannot pad the figure with claims
    the drawing never makes.
    """
    cited, seen = [], set()
    for eid in used:
        if eid and eid not in seen:
            seen.add(eid)
            cited.append(eid)
    by_id = {}
    for item in items:
        by_id.setdefault(item.get("id"), item)
    out = [it for it in fac.items if it["id"] in seen]
    for eid in cited:
        if eid in by_id:
            out.append(by_id[eid])
    return out


def _public_phase(phase):
    return {k: v for k, v in phase.items() if not k.startswith("_")}


def _route_conclusion(phases, panels):
    if phases:
        titles = [p.get("title") for p in phases if p.get("title")]
        if titles:
            return "Technical route: " + " -> ".join(titles[:5]) + "."
    return _conclusion_text(panels)


def _placeholder_nodes(items, role, part=None):
    """One honest, sourced node so a panel is never empty.

    Section headings and umbrella claims are skipped: a panel that could not be
    derived must say so in ``limitations`` instead of dressing a chapter title up
    as an entity.  Returns [] when nothing suitable exists.
    """
    for item in items:
        raw = item.get("claim") or ""
        if not item.get("id") or ev.heading_like(raw):
            continue
        # a heading glued to the paragraph that follows it (common in PDF text) is
        # still a heading: check the leading words, not only the whole claim
        if ev.heading_like(" ".join(ev._norm(raw).split()[:6])):
            continue
        claim = _clean_label(raw, 26)
        if not claim:
            continue
        node = {"id": scene.stable_id("N", "note|%s|%s" % (role, _key(claim))),
                "shape": "rrect", "label": claim, "source": item["id"]}
        if part:
            node["part"] = part
        return [node]
    return []


# --------------------------------------------------------------------------- #
# top level
# --------------------------------------------------------------------------- #
def _case_title(materials):
    """The case's own title from case.json, or None (never invented)."""
    for mat in (materials.get("materials") or []):
        if mat.get("role") != "case" or not mat.get("parsed"):
            continue
        try:
            data = json.loads(mat.get("text") or "{}")
        except (ValueError, TypeError):
            return None
        if isinstance(data, dict):
            for key in ("title", "case_title", "name", "short_title"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return _clean_label(value.strip(), 96)
    return None


def _title(materials, ledger, case_id):
    # the case's own title is its identity and wins over any sentence the material
    # happens to contain
    case_title = _case_title(materials)
    if case_title:
        return case_title
    for item in (ledger.get("items") or []):
        claim = ev._norm(item.get("claim") or "")
        claim = re.sub(r"^(?:title|heading)\s*[:\-]\s*", "", claim, flags=re.I)
        if item.get("kind") == "entity" or claim.endswith(":"):
            continue
        if 20 <= len(claim) <= 120:
            return _clean_label(claim, 96)
    task = ev._norm(materials.get("task_text") or "")
    if task:
        return _clean_label(task, 96)
    # nothing readable anywhere: name the product this Skill actually produces,
    # without asserting any scientific content
    return "Apparatus and technical route for %s" % case_id


def derive_spec(materials, ledger):
    case_id = materials.get("case_id") or "unknown-case"
    items = list(ledger.get("items") or [])
    if not items:
        items = ev.fallback_evidence(materials)
        ledger = {"items": items, "counts": {"items": len(items)}, "warnings": []}

    # the apparatus/technical-route workorder takes its own deterministic path;
    # everything else keeps the legacy four-role behaviour unchanged
    if _apparatus_mode(materials, items):
        return derive_apparatus_spec(materials, ledger, case_id)

    language = "zh" if _cjk_ratio(" ".join(
        (m.get("text") or "")[:4000] for m in (materials.get("materials") or []))) > 0.15 else "en"

    title = _title(materials, {"items": items}, case_id)
    fac = _EvidenceFactory(materials)
    panels, used, notes = build_panels(materials, {"items": items}, fac=fac)

    # only ship evidence that is cited by something, plus any number evidence the
    # charts rely on; this keeps the ledger auditable instead of a wall of text.
    # Evidence the factory had to build (a table row the ledger's cap dropped) is
    # included here, otherwise the chart would cite a dangling id.
    evidence_items = _collect_evidence(fac, items, used)
    if not evidence_items:
        fallback_id = items[0]["id"] if items else None
        evidence_items = _collect_evidence(fac, items, [fallback_id])
    if not evidence_items:
        evidence_items = ev.fallback_evidence(materials)

    warnings = list(materials.get("warnings") or [])
    uncertainty = []
    for w in warnings:
        uncertainty.append({"kind": w.get("kind"), "subject": w.get("subject"),
                            "reason": w.get("reason"), "needs_human": bool(w.get("needs_human"))})
    limitations = []
    for note in notes:
        limitations.append(note)
    if not materials.get("parsable"):
        limitations.append("No material file yielded readable text; the figure can only restate "
                           "the task/input metadata and makes no scientific claim.")
    if len(panels[2]["nodes"]) == 0:
        limitations.append("No numeric result could be attributed to a source span; the results "
                           "panel carries only qualitative claims.")

    spec = {
        "version": scene.VERSION,
        "meta": {
            "case_id": case_id,
            "title": title,
            "subtitle": _clean_label(ev._norm(materials.get("task_text") or ""), 140),
            "language": language,
            "canvas": dict(AUTOSPEC_CANVAS),
            "layout": {"columns": 2, "row_order": list(ROLE_ORDER)},
            "generated_by": "autospec (deterministic fallback, no LLM)",
        },
        "palette": {"id": "okabe-ito", "cvd_safe": True},
        "texts": {
            "caption": AUTOSPEC_CAPTION,
            "conclusion": _conclusion_text(panels),
        },
        "evidence": evidence_items,
        "panels": panels,
        "uncertainty": uncertainty,
        "limitations": limitations,
        "change_records": [{"kind": "autospec", "source": "materials.json + evidence-ledger.json",
                            "result": "deterministic spec", "human_edit": False}],
    }
    spec = repair(spec)
    return spec


def _conclusion_text(panels):
    for panel in panels:
        if panel.get("role") == "conclusion":
            labels = [n.get("label") for n in panel.get("nodes") or []]
            if labels:
                return "; ".join(labels[:3]) + "."
    return ""


def repair(spec, required_roles=None):
    """Deterministic repair: drop anything the model cannot substantiate."""
    required_roles = list(ROLE_ORDER if required_roles is None else required_roles)
    evidence_ids = {e.get("id") for e in (spec.get("evidence") or [])}
    if not evidence_ids:
        spec["evidence"] = []
        return spec
    for panel in spec.get("panels") or []:
        nodes = [n for n in (panel.get("nodes") or [])
                 if n.get("id") and n.get("label") and n.get("source") in evidence_ids]
        ids = {n["id"] for n in nodes}
        panel["nodes"] = nodes
        edges = []
        live_kinds = _live_edge_kinds()
        for e in panel.get("edges") or []:
            if e.get("from") in ids and e.get("to") in ids and e.get("from") != e.get("to") \
                    and e.get("kind") in live_kinds and e.get("source") in evidence_ids:
                edges.append(e)
        panel["edges"] = edges
        charts = []
        for c in panel.get("charts") or []:
            if c.get("type") not in scene.CHART_TYPES:
                continue
            series = [s for s in (c.get("series") or [])
                      if s.get("name") and isinstance(s.get("values"), list) and s["values"]
                      and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in s["values"])]
            if not series:
                continue
            # keep only source references that actually exist
            for s in series:
                keep = [r for r in (s.get("sources") or []) if r in evidence_ids]
                if keep:
                    s["sources"] = keep
                else:
                    s.pop("sources", None)
                if s.get("source") not in evidence_ids:
                    s.pop("source", None)
            series = [s for s in series if s.get("source") or s.get("sources")]
            if not series:
                continue
            c["series"] = series
            if not c.get("unit"):
                c["unit"] = "AU"
            charts.append(c)
        panel["charts"] = charts
        if panel.get("legend") is not None:
            names = []
            for c in charts:
                for s in c["series"]:
                    if s["name"] not in names:
                        names.append(s["name"])
            items = [i for i in (panel["legend"].get("items") or [])
                     if isinstance(i, dict) and i.get("label")]
            if names:
                palette = scene.PALETTES["okabe-ito"]
                panel["legend"] = {"title": panel["legend"].get("title") or "series",
                                   "items": [{"label": n, "color": palette[k % len(palette)]}
                                             for k, n in enumerate(names)]}
            elif items:
                panel["legend"] = {"title": panel["legend"].get("title") or "series", "items": items}
            else:
                panel.pop("legend", None)
        for cb in panel.get("colorbars") or []:
            if not (isinstance(cb.get("vmin"), (int, float)) and isinstance(cb.get("vmax"), (int, float))):
                continue
            if cb["vmax"] <= cb["vmin"]:
                cb["vmax"] = cb["vmin"] + 1.0
            if cb.get("cmap") not in scene.CMAPS:
                cb["cmap"] = "viridis"
            if not cb.get("unit"):
                cb["unit"] = "AU"
        cbs = []
        for cb in panel.get("colorbars") or []:
            if isinstance(cb.get("vmin"), (int, float)) and isinstance(cb.get("vmax"), (int, float)) \
                    and cb["vmax"] > cb["vmin"] and cb.get("cmap") in scene.CMAPS:
                cbs.append(cb)
        if cbs:
            panel["colorbars"] = cbs
        else:
            panel.pop("colorbars", None)

        # --- v1.1 structure (sequence / phases / declared_edges) --------------
        seq, seen_seq = [], set()
        for sid in panel.get("sequence") or []:
            if sid in ids and sid not in seen_seq:
                seen_seq.add(sid)
                seq.append(sid)
        if seq:
            panel["sequence"] = seq
        else:
            panel.pop("sequence", None)
        if panel.get("phases") is not None:
            phases = [p for p in panel.get("phases") or []
                      if isinstance(p, dict) and p.get("id") and p.get("title")]
            pids = [p["id"] for p in phases]
            for p in phases:
                p["depends_on"] = [d for d in (p.get("depends_on") or [])
                                   if isinstance(d, str) and d in pids and d != p["id"]]
            phases = _break_cycles(phases)
            if phases:
                stage_ids = {p["id"] for p in phases}
                panel["phases"] = phases
                panel["nodes"] = [n for n in panel["nodes"]
                                  if not n.get("stage") or n.get("stage") in stage_ids]
                ids = {n["id"] for n in panel["nodes"]}
                panel["edges"] = [e for e in panel.get("edges") or []
                                  if e.get("from") in ids and e.get("to") in ids]
            else:
                panel.pop("phases", None)
        # a terminal node may not carry an outgoing edge (gate J903)
        outgoing = {e.get("from") for e in panel.get("edges") or []}
        for node in panel["nodes"]:
            if node.get("terminal") and node["id"] in outgoing:
                node.pop("terminal", None)
        declared = [{"from": e.get("from"), "to": e.get("to"), "kind": e.get("kind")}
                    for e in panel.get("edges") or []]
        if declared:
            panel["declared_edges"] = declared
        else:
            panel.pop("declared_edges", None)

    # the declared relation list is rebuilt from what is actually drawn, so
    # gate J906 compares the figure against a list the figure really satisfies
    expected, seen_exp = [], set()
    for panel in spec.get("panels") or []:
        for edge in panel.get("edges") or []:
            key3 = (edge.get("from"), edge.get("to"), edge.get("kind"))
            if key3 in seen_exp:
                continue
            seen_exp.add(key3)
            expected.append({"from": edge["from"], "to": edge["to"], "kind": edge.get("kind")})
    if expected:
        spec.setdefault("meta", {})["expected_relations"] = expected
    else:
        spec.setdefault("meta", {}).pop("expected_relations", None)

    # role coverage is part of the product, not just a warning
    present = {p.get("role") for p in spec.get("panels") or []}
    for role in required_roles:
        if role not in present:
            spec.setdefault("panels", []).append({
                "id": "P%d" % (len(spec["panels"]) + 1), "role": role,
                "title": "(%s panel could not be derived from the material)" % role,
                "nodes": [], "edges": [], "charts": []})
    return spec


def _break_cycles(phases):
    """Drop depends_on entries that would create a cycle (gate J904)."""
    ids = [p["id"] for p in phases]
    deps = {p["id"]: list(p.get("depends_on") or []) for p in phases}
    state = {}

    def visit(pid, stack):
        state[pid] = 1
        kept = []
        for dep in deps.get(pid) or []:
            if state.get(dep) == 1:
                continue                       # back edge -> drop it
            if state.get(dep) is None:
                visit(dep, stack + [dep])
            kept.append(dep)
        deps[pid] = kept
        state[pid] = 2

    for pid in ids:
        if state.get(pid) is None:
            visit(pid, [pid])
    for p in phases:
        p["depends_on"] = deps.get(p["id"], [])
    return phases


def main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="derive a spec without an LLM")
    ap.add_argument("--materials", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    with open(a.materials, "r", encoding="utf-8-sig") as fh:
        materials = json.load(fh)
    with open(a.ledger, "r", encoding="utf-8-sig") as fh:
        ledger = json.load(fh)
    spec = derive_spec(materials, ledger)
    issues = scene.validate_spec(spec)
    errors = [i for i in issues if i["severity"] == "error"]
    with open(a.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(spec, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    sys.stderr.write("[autospec] panels=%d evidence=%d errors=%d\n"
                     % (len(spec["panels"]), len(spec["evidence"]), len(errors)))
    for e in errors:
        sys.stderr.write("  ERR %s %s %s\n" % (e["code"], e["path"], e["message"]))
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
