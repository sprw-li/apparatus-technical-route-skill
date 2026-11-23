#!/usr/bin/env python3
"""domain.py — apparatus / technical-route vocabulary for the 0061 workorder.

This module is *data plus pure functions*.  It deliberately does **not** import
`scene` (or anything else from the pipeline): `scene` is the schema authority and
importing it here would create a cycle once the renderer or the extractor pulls
this module in.  The canonical value sets below therefore mirror the tuples in
`scene.py`; keep them in step, and check the mirror mechanically with
`schema_agreement(scene)` (pass the imported module — this file still imports
nothing).

Two consumers, with an asymmetry worth knowing before you add an alias here:

* `autospec.py` (deterministic fallback spec) maps free text from apparatus
  lists / process descriptions / route tables onto canonical `part`, edge `kind`,
  step numbers, phases and waste streams.  It merges this module's
  `PART_ALIASES` **only as a supplement**: its own built-in bank is filled first
  and this table is merged with `setdefault` afterwards (`autospec._part_alias_order`),
  so on any overlap autospec's value wins.  It also drops aliases shorter than
  four characters (`autospec._domain_part_words`), which is calibrated for ASCII
  and silently discards 2-3 character CJK words — see `alias_weight()` below.
  `_domain_part_words` is therefore where a 2-3 character alias has to be
  changed if it must reach the extractor.
* renderers and gates read the same canonical names so a legend swatch, the
  drawn symbol and the gate comparison cannot drift apart.  For them this module
  *is* the authority, which is why the tables here stay deliberately narrow: an
  umbrella word ("apparatus", "equipment", "装置", "设备") names a drawing, not a
  device, and must never map to a `part`.

Every function is pure (no I/O, no clock, no randomness) and deterministic: the
same input string always yields the same canonical value.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# canonical value sets (mirror scene.py; see schema_agreement)
# --------------------------------------------------------------------------- #
PART_TYPES = ("vessel", "tank", "reactor", "column", "pump", "valve", "sensor",
              "probe", "flask", "mixer", "separator", "reservoir", "condenser",
              "heater", "cooler", "junction", "sample", "reagent", "waste",
              "instrument", "generic")

EDGE_KINDS_LEGACY = ("activation", "inhibition", "flow", "spatial", "feedback", "translocation")
EDGE_KINDS_V11 = ("material", "fluid", "gas", "energy", "heat", "signal", "control",
                  "assembly", "sequence", "branch", "merge", "loop", "waste")
EDGE_KINDS = EDGE_KINDS_LEGACY + EDGE_KINDS_V11

LINESTYLES = ("solid", "dashed", "dotted", "dashdot")
ARROW_MODES = ("none", "end", "both")
PORT_SIDES = ("left", "right", "top", "bottom")
ORIENTATIONS = ("portrait", "landscape")

PANEL_ROLES = ("problem", "method", "results", "conclusion")
PANEL_ROLES_V11 = ("apparatus", "flow", "route", "data", "conditions", "notes") + PANEL_ROLES
CORE_APPARATUS_ROLES = ("apparatus", "flow", "route")

WORKORDER_APPARATUS_ROUTE = "apparatus_and_technical_route"

# --------------------------------------------------------------------------- #
# keyword / alias tables (English + Chinese).  Matching is longest-alias-first,
# so a compound term ("层析柱") wins over its single-character head ("柱").
# --------------------------------------------------------------------------- #
PART_ALIASES = {
    # --- vessels and tanks ------------------------------------------------- #
    # NOTE ON GENERIC NOUNS: a bare umbrella word ("apparatus", "equipment",
    # "unit", "装置", "设备") is NOT a part alias.  A section heading such as
    # "3 Experimental apparatus and process" contains no equipment at all, and
    # mapping it to a part minted a ghost entity on the figure whose verbatim
    # quote was the heading itself, which gate E cannot catch.  Only words that
    # name a specific kind of device belong here.
    "vessel": ["vessel", "vessels", "cuvette", "chamber", "容器", "器皿", "反应容器"],
    "tank": ["tank", "feed tank", "holding tank", "罐", "储罐", "槽", "液槽",
             "水箱", "料罐"],
    "reactor": ["reactor", "bioreactor", "fermenter", "fermentor", "反应器", "反应釜",
                "生物反应器", "发酵罐"],
    "column": ["column", "packed bed", "chromatography column", "distillation column",
               "柱", "层析柱", "色谱柱", "精馏柱", "填料柱"],
    # --- transport and control --------------------------------------------- #
    "pump": ["pump", "peristaltic pump", "syringe pump", "泵", "蠕动泵", "输液泵", "进料泵"],
    "valve": ["valve", "stopcock", "three-way valve", "阀", "阀门", "三通阀", "调节阀",
              "球阀"],
    "sensor": ["sensor", "transmitter", "probe station", "传感器", "感测器", "变送器",
               "检测探头"],
    "probe": ["probe", "electrode", "thermocouple", "探头", "探针", "电极", "热电偶"],
    # --- reaction vessels and separation ----------------------------------- #
    "flask": ["flask", "round-bottom flask", "erlenmeyer", "烧瓶", "三角瓶", "锥形瓶",
              "圆底烧瓶"],
    "mixer": ["mixer", "stirrer", "agitator", "impeller", "搅拌器", "混合器", "搅拌桨",
              "均质器"],
    "separator": ["separator", "centrifuge", "settler", "filter", "membrane", "分离器",
                  "离心机", "分液器", "过滤装置", "膜组件"],
    "reservoir": ["reservoir", "feed reservoir", "bottle", "储液罐", "贮液器", "储液池",
                  "原料罐"],
    "condenser": ["condenser", "liebig condenser", "condensation trap", "冷凝器", "冷凝管",
                  "冷凝阱"],
    # --- thermal ----------------------------------------------------------- #
    "heater": ["heater", "hotplate", "heating mantle", "heat exchanger", "加热器", "加热套",
               "加热台", "换热器", "热源"],
    "cooler": ["cooler", "chiller", "cold trap", "ice bath", "cooling jacket", "冷却器",
               "冷却夹套", "冷水浴", "冷阱"],
    # --- plumbing and materials -------------------------------------------- #
    "junction": ["junction", "manifold", "connector", "接头", "三通", "连接件",
                 "汇合点", "分配器"],
    "sample": ["sample", "sampling port", "aliquot", "specimen", "样品", "试样", "取样口",
               "采样点"],
    "reagent": ["reagent", "substrate", "reactant", "medium", "试剂", "反应物",
                "底物", "培养基", "进料"],
    "waste": ["waste", "waste stream", "effluent", "purge", "byproduct",
              "废料", "废液", "废气", "废水", "废物", "排污", "排放",
              "副产物", "尾料"],
    # --- instruments and fallbacks ----------------------------------------- #
    # "monitor" is a verb far more often than a device ("monitor the pH"), so it
    # lives in EDGE/signal vocabulary, not in the part table.  Only *specific*
    # device phrases may be listed; these are kept in step with the instrument
    # bank in autospec.py so the two tables say the same thing about a phrase.
    "instrument": ["instrument", "analyzer", "detector", "spectrometer",
                   "ph monitor", "ph meter", "flow monitor", "flow meter",
                   "gas flow meter", "pressure gauge", "data logger",
                   "level indicator", "controller", "recorder",
                   "仪器", "分析仪", "检测器", "监测器", "光谱仪",
                   "监测仪", "记录仪", "控制器"],
    # the fallback part keeps only words that name a physical sub-assembly; bare
    # "unit"/"component"/"单元" are umbrella words and behave like "apparatus".
    # "module" is retained on purpose even though autospec's built-in bank maps
    # the bare word to `separator` (via "membrane module"): the overlap is inert
    # because autospec._GENERIC_PART_WORDS blocks a bare "module" at extraction
    # time, while keeping it lets an explicit "(part: module)" hint resolve to
    # the `generic` fallback instead of falling through to None.
    "generic": ["generic", "module", "部件", "组件", "通用件"],
}

EDGE_KIND_ALIASES = {
    # legacy six
    "activation": ["activation", "activate", "induction", "induces", "stimulates",
                   "upregulate", "激活", "促进", "上调", "诱导"],
    "inhibition": ["inhibition", "inhibit", "inhibits", "block", "blocks", "suppress",
                   "downregulate", "抑制", "阻断", "下调", "压制"],
    "flow": ["flow", "flows to", "flows into", "feeds", "流向", "流入", "通往", "进入"],
    "spatial": ["spatial", "located", "adjacent", "next to", "空间", "位于", "相邻", "邻接"],
    "feedback": ["feedback loop", "feedback", "反馈回路", "反馈环"],
    "translocation": ["translocation", "transported", "transfer", "translocate",
                      "转运", "转移", "迁移"],
    # v1.1 apparatus / route
    "material": ["material", "materials", "solid", "powder", "granule", "物料", "固体",
                 "粉料", "原料流"],
    "fluid": ["fluid", "liquid", "solution", "stream", "liquor", "液体", "液相", "溶液",
              "料液", "液流"],
    "gas": ["gas", "vapour", "vapor", "off-gases", "headspace", "气体", "气相", "蒸汽",
            "尾气"],
    "energy": ["energy", "power", "electricity", "utility", "能量", "动力", "电力", "公用工程"],
    "heat": ["heat", "heating", "thermal", "heating fluid", "cooling water", "热量", "温度",
             "加热", "冷却", "热流"],
    "signal": ["signal", "data", "measurement", "reading", "telemetry", "信号", "数据",
               "测量", "采集"],
    "control": ["control", "setpoint", "regulate", "regulation", "actuator", "控制",
                "调节", "设定值", "闭环"],
    "assembly": ["assembly", "mount", "mounting", "mechanical", "bolted", "装配",
                 "机械连接", "装配连接", "固定连接"],
    "sequence": ["sequence", "next", "then", "subsequently", "步骤", "先后", "顺序",
                 "下一步", "随后"],
    "branch": ["branch", "split", "fork", "diverge", "parallel", "分流", "分叉", "支路",
               "并行", "并联"],
    "merge": ["merge", "join", "combine", "converge", "recombine", "汇合", "合流", "合并",
              "汇集"],
    "loop": ["loop", "recycle", "recirculate", "reflux", "return line", "循环", "回流",
             "返流", "回收"],
    "waste": ["waste", "effluent", "purge", "vent", "discharge", "byproduct", "废料",
              "废液", "废气", "废水", "排污", "排放", "副产物"],
}

# Words that mark a line/fragment as a numbered or ordered step.
STEP_WORDS = ("步骤", "步", "工序", "操作", "step", "stage", "stage ", "operation")
# Words that mark a whole phase / route stage rather than a single step.
PHASE_WORDS = ("阶段", "技术路线", "路线", "里程碑", "研究阶段", "phase", "milestone",
               "workstream", "route stage")
# Words that mark a waste / effluent stream.
WASTE_WORDS = ("废料", "废液", "废气", "废水", "废物", "排污", "排放", "副产物",
               "waste", "effluent", "purge", "vent", "discharge", "byproduct")
BRANCH_WORDS = ("并行", "支路", "分叉", "分支", "分流", "并联", "branch", "parallel",
                "fork", "split", "diverge")
MERGE_WORDS = ("汇合", "合流", "合并", "汇集", "merge", "join", "converge", "recombine")
LOOP_WORDS = ("回流", "循环", "返流", "回收", "loop", "recycle", "recirculate", "reflux")
TERMINAL_WORDS = ("终止", "结束", "最终", "终点", "产物", "成品", "terminal", "end",
                  "final", "output", "product")
# Words that hint at the panel role a text block belongs to.
ROLE_ALIASES = {
    "apparatus": ["apparatus", "setup", "schematic", "equipment", "装置", "设备", "仪器",
                  "装置图", "装置示意"],
    "flow": ["flow", "process flow", "procedure", "protocol", "工艺", "流程", "工艺流程",
             "操作流程", "步骤"],
    "route": ["route", "technical route", "roadmap", "workflow", "路线", "技术路线",
              "路径", "技术方案", "研究路线"],
    "data": ["data", "chart", "plot", "results", "数据", "图表", "结果", "曲线"],
    "conditions": ["conditions", "parameters", "settings", "条件", "参数", "反应条件",
                   "工况"],
    "notes": ["notes", "legend", "caption", "说明", "注释", "图注", "脚注"],
}

_WS_RE = re.compile(r"\s+")
# A step number must be *marked* as one: either a step word introduces it
# ("Step 3", "第 3 步", "工序 4") or it numbers a list line ("3. 进料").  A bare
# number is never accepted, so "pH 7.2" or "2.8-fold" cannot become step 7/2.
_STEP_RE = re.compile(
    r"(?:第|步骤|工序)\s*[#:：#]?\s*(\d+)"
    r"|(?:step|stage)\s*[#:：#]?\s*(\d+)"
    r"|^[ \t]*(\d+)\s*[.、)：:]\s*\S",
    re.IGNORECASE | re.MULTILINE)


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #
def normalize(text):
    """Case-folded, whitespace-collapsed string (``None`` -> ``""``)."""
    return _WS_RE.sub(" ", str(text if text is not None else "")).strip().lower()


def alias_weight(alias):
    """Information weight of an alias, counting a CJK character as two.

    ``len()`` is an ASCII yardstick: it treats "thermocouple" (12) as far more
    informative than "热电偶" (3), although both name exactly one device.  Any
    minimum-length filter over aliases should use this instead of ``len``, e.g.
    ``alias_weight(a) >= 6`` keeps both and still rejects "well"/"bed".
    """
    return sum(2 if ord(ch) > 127 else 1 for ch in str(alias or ""))


def flat_part_aliases():
    """``{alias(lower) -> canonical part}`` for the whole part table.

    Convenience for a caller that wants to merge this table into its own: build
    the mapping once and ``setdefault`` it, rather than re-deriving the shape.
    """
    out = {}
    for part, aliases in PART_ALIASES.items():
        for alias in aliases:
            if isinstance(alias, str) and alias.strip():
                out.setdefault(alias.strip().lower(), part)
    return out


def flat_edge_kind_aliases():
    """``{alias(lower) -> canonical edge kind}`` for the whole kind table."""
    out = {}
    for kind, aliases in EDGE_KIND_ALIASES.items():
        for alias in aliases:
            if isinstance(alias, str) and alias.strip():
                out.setdefault(alias.strip().lower(), kind)
    return out


def _alias_lookup(aliases, text, allowed=None):
    """Longest-alias-first canonicalisation of free text."""
    needle = normalize(text)
    if not needle:
        return None
    keys = list(aliases)
    if allowed is not None:
        keys = [k for k in keys if k in allowed]
    # exact match wins, then the longest alias contained in the text
    for key in keys:
        for alias in aliases[key]:
            if needle == normalize(alias):
                return key
    best, best_len = None, -1
    for key in keys:
        for alias in aliases[key]:
            a = normalize(alias)
            if a and a in needle and len(a) > best_len:
                best, best_len = key, len(a)
    return best


def canonical_part(text, allowed=None):
    """Canonical apparatus ``part`` for a free-text label, or ``None``."""
    return _alias_lookup(PART_ALIASES, text, allowed)


def canonical_kind(text, allowed=None):
    """Canonical edge ``kind`` for a free-text label, or ``None``."""
    return _alias_lookup(EDGE_KIND_ALIASES, text, allowed)


def has_any(text, words):
    """True when any keyword occurs in ``text`` (case/whitespace-insensitive)."""
    needle = normalize(text)
    return any(normalize(w) in needle for w in words)


def detect_step_no(text, default=None):
    """First number that reads as a step number, else ``default``.

    ``"Step 3"``, ``"第 3 步"``, ``"工序 4"`` and ``"3. 进料"`` all yield the
    number; an unmarked number (``"pH 7.2"``, ``"2.8"``) yields ``default``.
    """
    needle = str(text if text is not None else "")
    for match in _STEP_RE.finditer(needle):
        for group in match.groups():
            if group:
                return int(group)
    return default


def is_step_line(text):
    return has_any(text, STEP_WORDS) or detect_step_no(text) is not None


def is_phase_line(text):
    return has_any(text, PHASE_WORDS)


def is_waste_label(text):
    return has_any(text, WASTE_WORDS)


def is_branch_label(text):
    return has_any(text, BRANCH_WORDS)


def is_merge_label(text):
    return has_any(text, MERGE_WORDS)


def is_loop_label(text):
    return has_any(text, LOOP_WORDS)


def is_terminal_label(text):
    return has_any(text, TERMINAL_WORDS)


def suggest_role(text, default="apparatus"):
    """Best panel role for a free-text block heading."""
    role = _alias_lookup(ROLE_ALIASES, text, PANEL_ROLES_V11)
    return role or default


def orientation_from_canvas(w_mm, h_mm):
    """``"landscape"`` when the page is at least as wide as it is tall."""
    try:
        w, h = float(w_mm), float(h_mm)
    except (TypeError, ValueError):
        return "portrait"
    return "landscape" if w >= h else "portrait"


def schema_agreement(scene_module):
    """List of drift messages between this mirror and an imported `scene` module.

    The caller passes the module (``import scene``); this file never imports it,
    so the cycle stays broken.  An empty list means the mirror is exact.
    """
    drift = []
    pairs = (("PART_TYPES", PART_TYPES), ("EDGE_KINDS", EDGE_KINDS),
             ("EDGE_KINDS_LEGACY", EDGE_KINDS_LEGACY), ("EDGE_KINDS_V11", EDGE_KINDS_V11),
             ("LINESTYLES", LINESTYLES), ("ARROW_MODES", ARROW_MODES),
             ("PORT_SIDES", PORT_SIDES), ("ORIENTATIONS", ORIENTATIONS),
             ("PANEL_ROLES", PANEL_ROLES), ("PANEL_ROLES_V11", PANEL_ROLES_V11),
             ("CORE_APPARATUS_ROLES", CORE_APPARATUS_ROLES))
    for name, mine in pairs:
        theirs = getattr(scene_module, name, None)
        if theirs is None:
            drift.append("scene.%s is missing" % name)
        elif tuple(theirs) != tuple(mine):
            drift.append("scene.%s != domain.%s" % (name, name))
    wo = getattr(scene_module, "WORKORDER_APPARATUS_ROUTE", None)
    if wo is not None and wo != WORKORDER_APPARATUS_ROUTE:
        drift.append("scene.WORKORDER_APPARATUS_ROUTE != domain.WORKORDER_APPARATUS_ROUTE")
    return drift
