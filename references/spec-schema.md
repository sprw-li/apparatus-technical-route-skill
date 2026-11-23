# `spec.json` schema reference — schema **1.1**

`spec.json` is the **single authored input** of the apparatus / technical-route
pipeline. It is the only artefact that contains scientific judgement (components,
streams, steps, phases, numbers, panel claims, citations); everything downstream
(layout, typography, export, gates A–K) is deterministic script work
(`work/CONTRACT.md` §1).

Two authorities back this file, and this file is their map:

* `scripts/scene.py::validate_spec` — structural validation, the only place a spec can be
  rejected (CLI **exit 4**). Every rule and code below was read out of that function; do not
  document a field the code does not accept.
* `scripts/domain.py` — the apparatus/route vocabulary (part and stream-kind aliases, step /
  phase / waste / branch / loop word lists, plus pure canonicalisation helpers). It is data +
  pure functions only and deliberately does **not** import `scene`, so the extractor and the
  renderer can share it without an import cycle. For a renderer or a gate this table is the
  authority. For `autospec.py` it is a **supplement**: autospec's own built-in vocabulary is
  filled first and this table is merged with `setdefault` afterwards, and aliases shorter than
  four characters are dropped — a rule calibrated for ASCII that also discards 2-3 character CJK
  words (`domain.alias_weight()` exists to make such a filter CJK-aware).

**Schema 1.1 is additive over 1.0.** Every field, enum value and error code of schema 1.0 is
still legal and still means the same thing; the ruling that keeps the mirror honest is
`domain.schema_agreement(scene)` (empty list = no drift).

Exit-code contract: a spec that yields any `severity:"error"` issue is rejected by
`scene.load_spec` and the CLI returns **exit 4** (`EXIT_SPEC`). `severity:"warn"` issues never
block a build.

---

## 1. Top level

| Key | Type | Required | Validated by `validate_spec` | Notes |
|---|---|---|---|---|
| `version` | string | recommended | not validated | Schema version. Put `"1.1"`; `"1.0"` is still accepted and means the legacy behaviour. `scene.VERSION` (runtime) stays `"1.0"` on purpose — only the *schema* revision is `scene.SPEC_SCHEMA_VERSION` = `"1.1"`. |
| `meta` | object | **yes** | `E001` error if missing / not an object | |
| `palette` | object | recommended | see §3 | |
| `texts` | object | recommended | not structurally validated | Consumed by `ar.py result` for caption/conclusion contract keys. |
| `evidence` | array | **yes** | `E020` error if missing or empty | |
| `panels` | array | **yes** | `E030` error if missing or empty | Validation **returns early** here — no panel body is checked. |
| `uncertainty` | array | optional | not validated | Copied verbatim into `result.json.uncertainty` by `ar.py::build_result`. |
| `limitations` | array | optional | not validated | Copied verbatim into `result.json.limitations`. |
| `change_records` | array | optional | not validated | Copied verbatim into `result.json.change_records`. |

There is **no** `title`/`caption`/`nodes` at top level. Titles live in `meta` and `texts`; node
lists live inside `panels`.

---

## 2. `meta`

| Key | Type | Required | Rule |
|---|---|---|---|
| `case_id` | string | **yes** | Non-empty (`E002` error otherwise). Becomes `result.json.case_id`. |
| `title` | string | recommended | Not validated. Used when an `output_contract` key mentions `title`. |
| `subtitle` | string | optional | Not validated. |
| `workorder` | string | optional (**v1.1**) | If present and not a non-empty string → `E100`. The value reserved by this task is `"apparatus_and_technical_route"` (`scene.WORKORDER_APPARATUS_ROUTE`); it selects the W071 role-coverage rule below. |
| `orientation` | `"portrait"` \| `"landscape"` | optional (**v1.1**) | `E101` error for any other value. A layout hint for the renderer; when absent the orientation is inferred from `canvas` (`domain.orientation_from_canvas`). |
| `expected_relations` | array of `{from,to,kind}` | optional (**v1.1**) | `E102` if not a list; each item needs non-empty `from`/`to` (`E103`) and an optional `kind` drawn from `scene.EDGE_KINDS` (`E104`). This is the **organiser/material-declared connection list**; gate **J906** reconciles it against the rendered scene. |
| `language` | string | recommended | `W012` warn if not a string. Passed to `fonts.resolve_fonts(lang)` — controls CJK font resolution. Use `"en"`, `"zh"`, or `"auto"` (default when absent). |
| `canvas` | object | recommended | See below. Defaults to `{"w_mm":180,"h_mm":120,"margin_mm":3,"dpi":300}`. |
| `layout` | object | recommended | Not validated by `validate_spec`; consumed by `layout.py`. |
| `note` | string | optional | Free text. Put the honesty label here on examples. |
| `degraded_fonts` | bool | optional | Read by `ar.py::build_result`; when truthy it appends the font-fallback sentence to `result.json.limitations`. |

### `meta.canvas`

Non-numeric values are silently ignored and the default is used (`merged.update` only takes
`_num` values). Ranges are checked **after** merging with defaults.

| Key | Default | Rule | Code |
|---|---|---|---|
| `w_mm` | 180 | must satisfy `20 <= w_mm <= 1000` | `E003` error |
| `h_mm` | 120 | must satisfy `20 <= h_mm <= 1000` | `E004` error |
| `dpi` | 300 | must satisfy `72 <= dpi <= 1200` | `E005` error |
| `margin_mm` | 3 | must satisfy `0 <= margin_mm <= 20` | `E006` error |
| — | — | must satisfy `0 < margin_mm*2 < min(w_mm,h_mm)` (margins must leave a drawing area) | `E007` error |

`180 × 120 mm` is the historical single-page journal default. The canvas you declare is a
**minimum**: `layout.py` may grow the page to fit content. The resolved value is what appears in
`scene.json.canvas`, `export_report.page_mm` and the PDF MediaBox — read those rather than
assuming your declaration was kept. `result.json.runtime.dpi` records the dpi actually used.

### `meta.layout`

Not checked by `validate_spec`; consumed by `layout.py`:

| Key | Type | Behaviour |
|---|---|---|
| `columns` | int | Panel-grid column count. Anything that is not an `int` or is `< 1` falls back to `2`; the value is then clamped to `1..len(panels)`. |
| `row_order` | array of role strings | Reading order of panel rows. Only used when it is a list; role strings not present in the spec are ignored. For an apparatus figure, `["apparatus","flow","route","data"]` is the natural order. |

### `meta.scalebar` (optional)

A scale bar is only drawn when this object exists (`layout._maybe_scalebar`). A panel-level
`panels[].scalebar` is also accepted; the first panel that declares one is used when `meta` does
not.

| Key | Type | Default | Behaviour |
|---|---|---|---|
| `length_mm` | number | `10.0` | Clamped to `2.0 … 60.0` mm. |
| `label` | string | `"<length> mm"` | Text beside the bar. |
| `panel` | string | last panel | Id of the panel to attach the bar to. |

Only declare a scale bar when the material actually gives you one; an apparatus schematic that
is explicitly "not to scale" must not carry one.

---

## 3. `palette`

| Key | Type | Rule |
|---|---|---|
| `id` | string | If absent → `W010` warn ("defaulting to okabe-ito"). If present but not a known id **and** no `colors` list → `E011` error. |
| `colors` | array of hex strings | When present and non-empty, wins over `id` (`scene.resolve_palette`). |
| `cvd_safe` | bool | Not validated; documentation flag only. |

Built-in palette ids (from `scene.PALETTES`):

* `okabe-ito` — the canonical colour-vision-deficiency-safe categorical palette
* `grayscale-safe` — `#1a1a1a #4d4d4d #808080 #b3b3b3`

Sequential cmaps (from `scene.CMAPS`, used by `colorbars[].cmap` and heatmaps):
`viridis`, `batlow`, `cividis`, `grey`.

---

## 4. `texts`

Free-form strings read by `ar.py::_contract_value` when an `output_contract` key matches.
Not structurally validated, but keep them non-empty — an empty string is treated as "not
derivable" and pushes `status` to `partial`.

| Key | Used for contract keys containing |
|---|---|
| `title` | `title` |
| `caption` | `caption`, `legend` |
| `legend_note` | `legend`, `caption` (fallback) |
| `conclusion` | `summary`, `abstract`, `conclusion` |
| `summary` | (fallback for the above) |

---

## 5. `evidence[]` — the provenance ledger

Required and non-empty. **Every** entity, relation, step, phase, port and number drawn on the
page must resolve here. Gate E re-checks each `source` against the real material bytes.

| Key | Type | Required | Rule |
|---|---|---|---|
| `id` | string | **yes** | Non-empty (`E022`), unique within the spec (`E023`). Nodes/edges/charts/phases reference it by this string. |
| `claim` | string | **yes** | Non-empty (`E024`). |
| `kind` | string | recommended | `W028` warn when missing. Suggested values: `entity` \| `relation` \| `number` \| `condition`. |
| `value` | number \| null | optional | Displayed value. |
| `unit` | string \| null | optional | e.g. `"L"`, `"mL/min"`, `"percent"`, `"°C"`. |
| `source` | object | **yes** | `E025` error if not an object. |

### `evidence[].source`

| Key | Type | Required | Rule |
|---|---|---|---|
| `file` | string | **yes** | Non-empty (`E026`). Must name a file that exists under the case material set — gate E fails otherwise. |
| `locator` | string | **yes** | Non-empty (`E026`). A resolvable span locator, e.g. `"L21-L22"` for markdown line ranges, `"row 9"` for CSV rows, `"page 3"` for PDF pages. `evidence.resolve_locator` parses it; an unparseable locator is a gate-E failure. |
| `quote` | string | **yes** | Non-empty after `.strip()` (`E027`). Must be a **verbatim** substring of the located span — gate E matches it literally; a paraphrase fails. |

---

## 6. `panels[]`

Required and non-empty.

| Key | Type | Required | Rule |
|---|---|---|---|
| `id` | string | **yes** | Non-empty (`E032`), unique (`E033`). |
| `role` | string | **yes** | One of the schema-1.1 role domain (`E034` error otherwise). See below. |
| `title` | string | **yes** | Non-empty (`E035`). |
| `nodes` | array | recommended | `E036` if present but not a list. |
| `edges` | array | recommended | Validated whenever present. |
| `charts` | array | recommended | Validated whenever present. |
| `legend` | object \| null | optional | `E058`/`E059` if malformed. |
| `colorbars` | array | optional | Validated whenever present. |
| `sequence` | array of node id | optional (**v1.1**) | Authoritative execution/reading order for a flow or route panel. |
| `phases` | array of phase object | optional (**v1.1**) | Technical-route phases. |
| `declared_edges` | array of `{from,to,kind}` | optional (**v1.1**) | Connections this panel claims. |
| `scalebar` | object | optional | See §2. |

### 6.0 `role` domain

Legacy four (still exactly legal — `scene.PANEL_ROLES`):
`problem`, `method`, `results`, `conclusion`.

v1.1 recommended roles (`scene.PANEL_ROLES_V11` = the six below **plus** the legacy four):

| `role` | Meaning |
|---|---|
| `apparatus` | apparatus structure / components and their connections |
| `flow` | ordered process steps, branches, loops, waste outlets |
| `route` | technical route: phases and their dependencies |
| `data` | data encoding (charts, value-carrying nodes) |
| `conditions` | experimental conditions / legend-heavy panel |
| `notes` | free annotations |

`scene.CORE_APPARATUS_ROLES = ("apparatus","flow","route")` is the set whose total absence
drives `W071` (see §8).

### 6.1 `panels[].nodes[]`

Legacy keys:

| Key | Type | Required | Rule |
|---|---|---|---|
| `id` | string | **yes** | Non-empty (`E038`), and unique **across the whole spec**, not just the panel (`E039`). |
| `label` | string | **yes** | Non-empty (`E040`). Drawn as the primary line. |
| `shape` | string | optional | One of `rrect`, `rect`, `circle`, `ellipse`, `hexagon`, `diamond`, `capsule`, `note`. Unknown → `W041` warn and falls back to `rrect`. Default `rrect`. When a v1.1 `part` is given, the renderer draws that part's symbol and `shape` becomes the fallback. |
| `sublabel` | string | optional | Second text line inside the node. |
| `value` | number \| null | optional | Numeric value shown/coded on the node. |
| `unit` | string \| null | optional | Unit for `value`. |
| `derived` | bool | optional | Set `true` when `value` is **not itself** in the source (e.g. a computed ratio). |
| `source_values` | array of numbers | required when `derived` is true | The **input** values gate E verifies appear in the cited quote(s). `derived: true` without `source_values` → `E907` **warn**, and the displayed value is then not value-checked at all. |
| `source` | string (evidence id) | **required for gate E** | `W042` warn at spec-validation time, but gate E raises a hard error **`E903`** for any node without one → `check` exits `1`. Must equal an `evidence[].id`, else `E904`. |
| `sources` | array of evidence ids | alternative to `source` | Accepted wherever `source` is (a node may carry both). |

v1.1 semantic keys (all optional, all checked by `validate_spec`):

| Key | Type | Rule / meaning | Gate |
|---|---|---|---|
| `part` | enum | One of `scene.PART_TYPES`: `vessel tank reactor column pump valve sensor probe flask mixer separator reservoir condenser heater cooler junction sample reagent waste instrument generic`. Any other value → `E130`. Required for every node of an `apparatus` panel (`K901`). | K901 |
| `step_no` | int ≥ 1 | Process-step number; must be an integer ≥ 1 and not a boolean → else `E131`. | J902 |
| `branch` | non-empty string | Parallel-branch group id: nodes sharing a `branch` are parallel. Non-string/empty → `E132`. | J903 |
| `loop_to` | node id | Recycle target. Must be a non-empty string (`E133`) **and name a node in the same panel** (`E134`). | J903 |
| `terminal` | bool | Terminal / sink node. Non-boolean → `E135`. A terminal node must have no outgoing edge in the panel (`J903`). | J903 |
| `stage` | non-empty string | Id of the route phase (`phases[].id`) this node belongs to. Non-string/empty → `E136`. | J904 |
| `group` | non-empty string | Swimlane / grouping id. Non-string/empty → `E137`. Rendering hint only; not checked by J/K. | — |
| `ports` | array of port objects | Declared interfaces. See below. | K902 |

`nodes[].ports[]`:

| Key | Type | Required | Rule |
|---|---|---|---|
| `id` | non-empty string | **yes** | `E139` if missing/empty, `E140` if duplicated inside the same node. |
| `name` | non-empty string | optional | Human name (`"inlet"`, `"retentate"`). `E142` if present but not a non-empty string. |
| `side` | `left` \| `right` \| `top` \| `bottom` | optional | `E141` for any other value (`scene.PORT_SIDES`). |
| `mate` | non-empty string | optional | Node id this port connects to. `E142` if not a non-empty string. |
| `source` | non-empty string | optional | Evidence id for the port (gate E covers ports). `E142` if not a non-empty string. |
| — | — | — | `ports` itself must be a list: `E138` otherwise (and `E138` per non-object item). |

### 6.2 `panels[].edges[]`

| Key | Type | Required | Rule |
|---|---|---|---|
| `id` | string | **yes** | Non-empty (`E044`). |
| `from` | string (node id) | **yes** | Non-empty (`E045`) and must be a node **in the same panel** (`E046`). |
| `to` | string (node id) | **yes** | Same rule as `from`. |
| `kind` | string \| null | optional | If not null it must be one of the 19 kinds below (`E047`). `null`/absent is accepted. |
| `label` | string | optional | Edge label rendered along the connector. |
| `linestyle` | `solid` \| `dashed` \| `dotted` \| `dashdot` | optional (**v1.1**) | `E150` for any other value. Default: the per-kind default in `scene.EDGE_VISUALS`. |
| `arrow` | `none` \| `end` \| `both` | optional (**v1.1**) | `E151` for any other value. Default: the per-kind default in `scene.EDGE_VISUALS`. |
| `legend_key` | non-empty string | optional (**v1.1**) | Points at a legend item (`E152` if not a non-empty string). Free-form key; the renderer matches it case-insensitively against `legend.items[].label`. |
| `ports` | `[from_port, to_port]` or `{"from","to"}` | optional (**v1.1**) | Two non-empty port ids, or an equivalent object → else `E153`. Each id must exist on the respective node (`K902`). |
| `source` / `sources` | evidence id(s) | **required for gate E** | `W048` warn at spec-validation time; missing → gate E error **`E903`** → `check` exits `1`. |

#### `kind` values

`scene.EDGE_KINDS` is the **union** of the legacy six and the thirteen v1.1 kinds (19 total).
It is what `validate_spec` (`E047`) and `validate.py` (arrow recognition) both read, so an edge
drawn with a v1.1 kind is still a recognised arrow.

Legacy six (`scene.EDGE_KINDS_LEGACY`) — unchanged in 1.1:

| `kind` | Meaning |
|---|---|
| `activation` | positive regulation / induction → arrow head |
| `inhibition` | negative regulation / block → bar head |
| `flow` | procedural or spatial progression |
| `spatial` | physical placement / compartment relation (no arrow) |
| `feedback` | regulatory loop returning on itself |
| `translocation` | movement between compartments |

v1.1 kinds (`scene.EDGE_KINDS_V11`), with the defaults `scene.resolve_edge_style` applies when
the edge does not set `linestyle`/`arrow` explicitly:

| `kind` | Default linestyle | Default arrow | Head | Semantics |
|---|---|---|---|---|
| `material` | solid | end | solid | solid material / solids flow |
| `fluid` | solid | end | solid | liquid / solution flow |
| `gas` | solid | end | hollow | gas flow |
| `energy` | dashed | end | triangle | energy input (electrical, UV, …) |
| `heat` | dashed | end | triangle | heat / cooling duty |
| `signal` | dotted | end | dot | information, measurement, data |
| `control` | dashdot | end | solid | control / regulation / set point |
| `assembly` | solid | none | none | mechanical / bolted connection |
| `sequence` | solid | end | solid | step ordering |
| `branch` | solid | end | solid | split into parallel trains |
| `merge` | solid | end | solid | joining of trains |
| `loop` | solid | end | solid | recycle / return |
| `waste` | dashed | end | solid | waste / effluent outlet |

Gate **K904** compares the resolved `(kind,linestyle,colour)` multiset declared by the legend
with the one actually rendered, so `resolve_edge_style` (not a private table in the renderer) is
the single source of those defaults.

### 6.3 `panels[].charts[]`

| Key | Type | Required | Rule |
|---|---|---|---|
| `id` | string | recommended | Used for stable SVG ids. |
| `type` | string | **yes** | Must be in `bar`, `barh`, `line`, `scatter`, `dot`, `heatmap`, `violin`, `waterfall`, `none` (`E050` error). |
| `title` | string | optional | Chart title text. |
| `unit` | string | **recommended** | `W057` warn when falsy. |
| `x` | object | required for `line`/`scatter`/`dot` | `{"label": "<axis title>", "values": [<numbers>]}`. |
| `categories` | array of strings | required for `bar`/`barh` | Category tick labels. |
| `series` | array | **yes** | `E051` error if missing or empty. |

`panels[].charts[].series[]`:

| Key | Type | Required | Rule |
|---|---|---|---|
| `name` | string | **yes** | `E053` error if not a string. |
| `values` | array of numbers | **yes** | `E054` if missing/empty, `E055` if any element is not a number (booleans count as non-numbers). |
| `source` | evidence id | **required for gate E** | `W056` warn at spec-validation time; missing → gate E error **`E903`**. Gate E also checks that the number actually occurs in that quote (`E906`). |
| `sources` | array of evidence ids | alternative to `source` | Use when one series' values come from several rows/items. |
| `derived` | bool | optional | Set `true` when the numbers are computed rather than quoted. |
| `source_values` | array of numbers | required when `derived` is true | `derived` without `source_values` → `E907` warn. |

Category charts: `len(categories)` must match each `series.values`. Line charts read the x-axis
from `x.values`.

### 6.4 `panels[].legend`

| Key | Type | Required | Rule |
|---|---|---|---|
| `title` | string | optional | Legend heading. |
| `items` | array | **yes** when `legend` is present | `E058` if `legend` is not an object, `E059` if `items` is not a list. |
| `items[].label` | string | recommended | Must correspond to a data category — gate D compares the legend item multiset with the chart series-name multiset (case-insensitively). Also the match target for `edges[].legend_key`. |
| `items[].color` | string | recommended | Hex colour; must be legible under gate C. Missing colour → the palette colour for that index is used. |
| `items[].shape` | string | optional | Swatch shape; defaults to `rect`. |
| `items[].kind` | edge kind | optional (**v1.1**) | The stream kind this legend entry stands for. Any value outside `scene.EDGE_KINDS` → `E160`. |
| `items[].part` | part type | optional (**v1.1**) | The node `part` this legend entry stands for. Any value outside `scene.PART_TYPES` → `E161`. |
| `items[].linestyle` | linestyle | optional (**v1.1**) | Declared swatch line pattern; part of the K904 multiset comparison. |
| `items[].source` | evidence id | optional | Gate E checks it for dangling ids if present. |

When an item declares `kind`/`part`, gate **K904** requires the legend-declared
`(kind,linestyle,colour)` multiset to equal the one actually rendered — a legend that advertises
a stream the figure does not draw is a **K failure**, not a warning.

A legend whose items do not fit its box is truncated and a `W_LEGEND_OVERFLOW` scene warning is
recorded rather than silently drawn outside.

### 6.5 `panels[].colorbars[]`

| Key | Type | Required | Rule |
|---|---|---|---|
| `id` | string | recommended | |
| `title` | string | optional | |
| `vmin` | number | **yes** | `E061` if not numeric. |
| `vmax` | number | **yes** | `E061` if not numeric; must be `> vmin` or `E062`. |
| `cmap` | string | **yes** | One of `viridis`, `batlow`, `cividis`, `grey` (`E063`). |
| `unit` | string | **recommended** | `W064` warn when falsy. |

Gate D checks that the declared `vmin`/`vmax` equal the data min/max actually used.

### 6.6 `panels[].sequence` (v1.1)

Authoritative execution / reading order for a `flow` or `route` panel. Gate **J901** requires
every entry to be a node of that panel and to appear at most once; the schema-level mirror of
that rule is enforced by `validate_spec`:

| Defect | Code |
|---|---|
| `sequence` is not a list | `E110` |
| an entry is not a non-empty string | `E111` |
| an entry is not a node **in this panel** | `E112` |
| a node id appears twice | `E113` |

`sequence` is what the renderer uses to lay the steps out; it is not required to list every node,
but gate J902 additionally requires the `step_no` values of a flow/route panel to be `1..N`
with no gap (a gap must be declared in `phases`/`limitations`).

### 6.7 `panels[].phases` (v1.1)

A technical-route phase. `phases` must be a list (`E114`); each entry is an object (`E115`).

| Key | Type | Required | Rule |
|---|---|---|---|
| `id` | non-empty string | **yes** | `E115` if missing; `E116` if duplicated within the panel. Referenced by `nodes[].stage` and `depends_on`. |
| `title` | string | recommended | `E119` if present but not a string. |
| `goal` | string | recommended | `E119` if present but not a string. |
| `methods` | array | optional | `E118` if present but not a list. |
| `inputs` | array | optional | `E118` if present but not a list. |
| `outputs` | array | optional | `E118` if present but not a list. |
| `depends_on` | array of phase id | optional | `E117` if not a list, or if any entry is not a `phases[].id` of the same panel. Gate **J904** then requires the dependency graph to be acyclic and prints the cycle path on failure. |
| `source` | evidence id | **required for gate E** | `E119` if present but not a string; gate E covers phase provenance. |

### 6.8 `panels[].declared_edges` (v1.1)

The panel-local counterpart of `meta.expected_relations`: a list of `{from,to,kind}` the author
claims the panel draws.

| Defect | Code |
|---|---|
| not a list | `E120` |
| an item is not an object, or `from`/`to` missing/empty | `E103` |
| `kind` present but outside `scene.EDGE_KINDS` | `E104` |

Endpoint **membership is deliberately not a schema-level rule** here: these lists declare
connections for the rendered scene as a whole and may reference nodes of another panel. Gate
**J906** is what reconciles them: every `(from,to,kind)` in `expected_relations` ∪
`declared_edges` must be found among the rendered edges, a missing one is listed, and a reversed
`(to,from,kind)` match is also a failure ("the arrow was drawn the wrong way").

---

## 7. How the schema reaches `scene.json`

Gates **J** and **K** read the built `scene.json`, not the spec, so the authored semantics must
survive the render step. `ar.py build` therefore calls

```python
sc = scene.attach_topology(layout.layout(spec, fs), spec)
```

before exporting. `scene.attach_topology` is a pure, **idempotent** merge that never mutates the
spec and never overwrites a key the renderer already set:

| Source | Keys copied into `scene.json` |
|---|---|
| `meta` | `workorder`, `orientation`, `expected_relations` |
| each panel | `sequence`, `phases`, `declared_edges` |
| each node | `part`, `step_no`, `branch`, `loop_to`, `terminal`, `stage`, `group`, `ports` |
| each edge | `kind`, `linestyle`, `arrow`, `legend_key`, `ports`, plus the resolved `head` glyph |

`linestyle`/`arrow` are written **resolved** (`scene.resolve_edge_style`), i.e. the per-kind
default from §6.2 is materialised even when the author did not spell it out. That is what makes
the K904 multiset comparison meaningful.

Two identical builds of the same spec produce a byte-identical `scene.json` (checked by the
probe in `work/verify/schema-probe/` and by the pipeline's own determinism gates).

---

## 8. Code table

`exit 4` for any row marked **error**; **warn** rows never block a build. Codes ≤ `E063`/`W070`
are schema-1.0 rules and keep their exact meaning (the 1.1 work only *adds* values to the enums
they test, never weakens a check). Codes ≥ `E100` are schema-1.1 additions.

| Code | Sev | Path | Trigger |
|---|---|---|---|
| `E000` | error | `$` | spec is not a JSON object |
| `E001` | error | `$.meta` | missing/non-object `meta` |
| `E002` | error | `$.meta.case_id` | missing/empty `case_id` |
| `E003`–`E007` | error | `$.meta.canvas…` | canvas ranges / margins (see §2) |
| `E011` | error | `$.palette.id` | unknown palette id and no `colors[]` |
| `E020`–`E027` | error | `$.evidence…` | evidence list / id / claim / source / quote |
| `E030` | error | `$.panels` | no panel |
| `E031`–`E033` | error | `$.panels[i]…` | panel object / id required / duplicate id |
| `E034` | error | `…​.role` | role outside `scene.PANEL_ROLES_V11` (legacy four included) |
| `E035` | error | `…​.title` | panel title required |
| `E036`–`E040` | error | `…​.nodes…` | nodes list / node object / id / duplicate id / label |
| `E041` | warn | `…​.nodes[i].shape` | unknown shape → `rrect` |
| `E043`–`E047` | error | `…​.edges…` | edge object / id / endpoints / membership (`E046`) / kind |
| `E049`–`E055` | error | `…​.charts…` | chart object / type / series / name / values |
| `E058`, `E059` | error | `…​.legend…` | legend object / items list |
| `E060`–`E063` | error | `…​.colorbars…` | colorbar object / vmin / vmax / cmap |
| **`E100`** | error | `$.meta.workorder` | not a non-empty string |
| **`E101`** | error | `$.meta.orientation` | not `portrait`/`landscape` |
| **`E102`** | error | `$.meta.expected_relations` | not a list |
| **`E103`** | error | `$.meta.expected_relations[i]` / `…​.declared_edges[i]` | item not an object, or `from`/`to` missing |
| **`E104`** | error | same `.kind` | kind outside `scene.EDGE_KINDS` |
| **`E110`** | error | `…​.sequence` | not a list |
| **`E111`** | error | `…​.sequence[i]` | entry not a node id string |
| **`E112`** | error | `…​.sequence[i]` | entry is not a node of this panel |
| **`E113`** | error | `…​.sequence[i]` | node repeated in the order |
| **`E114`** | error | `…​.phases` | not a list |
| **`E115`** | error | `…​.phases[i]` | phase not an object / missing `id` |
| **`E116`** | error | `…​.phases[i].id` | duplicate phase id in the panel |
| **`E117`** | error | `…​.phases[i].depends_on` | not a list, or entry not a phase id of this panel |
| **`E118`** | error | `…​.phases[i].{methods,inputs,outputs}` | present but not a list |
| **`E119`** | error | `…​.phases[i].{title,goal,source}` | present but not a string |
| **`E120`** | error | `…​.declared_edges` | not a list |
| **`E130`** | error | `…​.nodes[i].part` | part outside `scene.PART_TYPES` |
| **`E131`** | error | `…​.nodes[i].step_no` | not an integer ≥ 1 |
| **`E132`** | error | `…​.nodes[i].branch` | not a non-empty string |
| **`E133`** | error | `…​.nodes[i].loop_to` | not a non-empty string |
| **`E134`** | error | `…​.nodes[i].loop_to` | target is not a node of this panel |
| **`E135`** | error | `…​.nodes[i].terminal` | not a boolean |
| **`E136`** | error | `…​.nodes[i].stage` | not a non-empty string |
| **`E137`** | error | `…​.nodes[i].group` | not a non-empty string |
| **`E138`** | error | `…​.nodes[i].ports` | not a list / item not an object |
| **`E139`** | error | `…​.ports[j].id` | port id required |
| **`E140`** | error | `…​.ports[j].id` | duplicate port id in the node |
| **`E141`** | error | `…​.ports[j].side` | side outside `scene.PORT_SIDES` |
| **`E142`** | error | `…​.ports[j].{name,mate,source}` | present but not a non-empty string |
| **`E150`** | error | `…​.edges[i].linestyle` | outside `scene.LINESTYLES` |
| **`E151`** | error | `…​.edges[i].arrow` | outside `scene.ARROW_MODES` |
| **`E152`** | error | `…​.edges[i].legend_key` | not a non-empty string |
| **`E153`** | error | `…​.edges[i].ports` | not `[from,to]` (two non-empty strings) or `{from,to}` |
| **`E160`** | error | `…​.legend.items[i].kind` | outside `scene.EDGE_KINDS` |
| **`E161`** | error | `…​.legend.items[i].part` | outside `scene.PART_TYPES` |
| `W010` | warn | `$.palette.id` | no palette id → okabe-ito |
| `W012` | warn | `$.meta.language` | language not set |
| `W028` | warn | `$.evidence[i].kind` | evidence kind missing |
| `W042` | warn | `…​.nodes[i].source` | node has no evidence source |
| `W048` | warn | `…​.edges[i].source` | edge has no evidence source |
| `W056`/`W057` | warn | `…​.charts…` | series without source / chart without unit |
| `W064` | warn | `…​.colorbars[i].unit` | colorbar without unit |
| `W070` | warn | `$.panels` | **legacy role coverage**: one warning per missing legacy role — emitted **only when `meta.workorder != "apparatus_and_technical_route"`** |
| **`W071`** | warn | `$.panels` | `meta.workorder == "apparatus_and_technical_route"` and none of `apparatus`/`flow`/`route` appears as a panel role |

The W070/W071 split is the additive rule of §3.2: an apparatus workorder is no longer measured
against the four-element graphical-abstract reading order, while every other spec keeps exactly
the warnings it had in schema 1.0.

---

## 9. Minimal legal spec (apparatus + flow + route)

Validates with **0 errors and 0 warnings**. It declares an apparatus panel with ports and parts,
a flow panel with `sequence`, `step_no`, `branch`, `loop_to` and `terminal`, and a route panel
with `phases`/`depends_on`; `meta.expected_relations` mirrors the drawn edges. Together with the
`declared_edges` of the apparatus panel it is exactly what gate J906 reconciles.

```json
{
  "version": "1.1",
  "meta": {
    "case_id": "CASE-AR-0001",
    "title": "Minimal apparatus + flow + route figure",
    "workorder": "apparatus_and_technical_route",
    "orientation": "landscape",
    "language": "en",
    "canvas": { "w_mm": 200, "h_mm": 140, "margin_mm": 3, "dpi": 300 },
    "layout": { "columns": 2, "row_order": ["apparatus", "flow", "route"] },
    "expected_relations": [
      { "from": "K2", "to": "K1", "kind": "fluid" },
      { "from": "K3", "to": "K1", "kind": "heat" },
      { "from": "S1", "to": "S2", "kind": "sequence" },
      { "from": "S2", "to": "S3", "kind": "branch" }
    ]
  },
  "palette": { "id": "okabe-ito" },
  "texts": { "conclusion": "One-sentence take-home." },
  "evidence": [
    {
      "id": "E1",
      "kind": "condition",
      "claim": "K1 stirred tank is fed by K2 pump and heated by K3 jacket",
      "value": null,
      "unit": null,
      "source": {
        "file": "apparatus-list.md",
        "locator": "L5",
        "quote": "K1 stirred tank is fed by K2 pump and heated by K3 jacket"
      }
    }
  ],
  "panels": [
    {
      "id": "PA", "role": "apparatus", "title": "Apparatus: stirred tank with pump and jacket",
      "nodes": [
        { "id": "K1", "part": "tank", "shape": "rrect", "label": "Stirred tank K1",
          "value": 2.0, "unit": "L", "group": "reactor train", "source": "E1",
          "ports": [
            { "id": "K1_in", "name": "inlet", "side": "top", "mate": "K2", "source": "E1" },
            { "id": "K1_out", "name": "outlet", "side": "bottom", "source": "E1" }
          ] },
        { "id": "K2", "part": "pump", "shape": "rrect", "label": "Feed pump K2",
          "group": "reactor train", "source": "E1",
          "ports": [ { "id": "K2_out", "name": "outlet", "side": "right", "mate": "K1", "source": "E1" } ] },
        { "id": "K3", "part": "heater", "shape": "rrect", "label": "Jacket K3",
          "group": "reactor train", "source": "E1",
          "ports": [ { "id": "K3_out", "name": "heat", "side": "left", "mate": "K1", "source": "E1" } ] }
      ],
      "edges": [
        { "id": "KE1", "from": "K2", "to": "K1", "kind": "fluid", "label": "feed",
          "linestyle": "solid", "arrow": "end", "legend_key": "fluid",
          "ports": ["K2_out", "K1_in"], "source": "E1" },
        { "id": "KE2", "from": "K3", "to": "K1", "kind": "heat", "label": "jacket",
          "linestyle": "dashed", "arrow": "end", "legend_key": "heat",
          "ports": ["K3_out", "K1_in"], "source": "E1" }
      ],
      "legend": { "title": "stream kind", "items": [
        { "label": "fluid", "kind": "fluid", "linestyle": "solid", "color": "#0072B2" },
        { "label": "heat", "kind": "heat", "linestyle": "dashed", "color": "#D55E00" },
        { "label": "tank", "part": "tank", "shape": "rrect", "color": "#009E73" }
      ] },
      "charts": [],
      "declared_edges": [
        { "from": "K2", "to": "K1", "kind": "fluid" },
        { "from": "K3", "to": "K1", "kind": "heat" }
      ]
    },
    {
      "id": "PF", "role": "flow", "title": "Process flow: four steps, one split into a parallel pair",
      "sequence": ["S1", "S2", "S3", "S4"],
      "nodes": [
        { "id": "S1", "step_no": 1, "shape": "rrect", "label": "Charge feed", "source": "E1" },
        { "id": "S2", "step_no": 2, "shape": "rrect", "label": "React", "terminal": false, "source": "E1" },
        { "id": "S3", "step_no": 3, "branch": "B_SPLIT", "loop_to": "S1", "shape": "rrect",
          "label": "Separate train A", "group": "lane A", "source": "E1" },
        { "id": "S4", "step_no": 3, "branch": "B_SPLIT", "terminal": true, "part": "waste",
          "shape": "rrect", "label": "Waste out", "group": "lane B", "source": "E1" }
      ],
      "edges": [
        { "id": "SE1", "from": "S1", "to": "S2", "kind": "sequence", "source": "E1" },
        { "id": "SE2", "from": "S2", "to": "S3", "kind": "branch", "linestyle": "dotted", "source": "E1" },
        { "id": "SE3", "from": "S2", "to": "S4", "kind": "branch", "linestyle": "dotted", "source": "E1" },
        { "id": "SE4", "from": "S3", "to": "S1", "kind": "loop", "linestyle": "dashdot",
          "arrow": "both", "source": "E1" },
        { "id": "SE5", "from": "S4", "to": "S3", "kind": "assembly", "arrow": "none", "source": "E1" }
      ],
      "charts": [],
      "declared_edges": [
        { "from": "S1", "to": "S2", "kind": "sequence" },
        { "from": "S2", "to": "S3", "kind": "branch" },
        { "from": "S2", "to": "S4", "kind": "branch" },
        { "from": "S3", "to": "S1", "kind": "loop" }
      ]
    },
    {
      "id": "PR", "role": "route", "title": "Technical route: three phases with a dependency chain",
      "sequence": ["R1N", "R2N", "R3N"],
      "phases": [
        { "id": "PH1", "title": "Screen", "goal": "rank two catalysts",
          "methods": ["batch screen"], "inputs": ["two powders"], "outputs": ["shortlist"],
          "depends_on": [], "source": "E1" },
        { "id": "PH2", "title": "Optimise", "goal": "maximise yield per joule",
          "methods": ["factorial design"], "inputs": ["shortlist"], "outputs": ["window"],
          "depends_on": ["PH1"], "source": "E1" },
        { "id": "PH3", "title": "Validate", "goal": "hold a window for 24 h",
          "methods": ["continuous run"], "inputs": ["window"], "outputs": ["report"],
          "depends_on": ["PH2"], "source": "E1" }
      ],
      "nodes": [
        { "id": "R1N", "step_no": 1, "stage": "PH1", "shape": "rrect", "label": "Phase 1", "source": "E1" },
        { "id": "R2N", "step_no": 2, "stage": "PH2", "shape": "rrect", "label": "Phase 2", "source": "E1" },
        { "id": "R3N", "step_no": 3, "stage": "PH3", "shape": "rrect", "label": "Phase 3", "source": "E1" }
      ],
      "edges": [
        { "id": "RE1", "from": "R1N", "to": "R2N", "kind": "sequence", "source": "E1" },
        { "id": "RE2", "from": "R2N", "to": "R3N", "kind": "sequence", "source": "E1" }
      ],
      "charts": [],
      "declared_edges": [
        { "from": "R1N", "to": "R2N", "kind": "sequence" },
        { "from": "R2N", "to": "R3N", "kind": "sequence" }
      ]
    }
  ]
}
```

Notes on this template:

* `meta.workorder` is set and all three core roles are present, so neither W070 nor W071 fires.
* Every node/edge carries `source`, so W042/W048 stay silent; the single evidence item is enough
  for a structurally clean spec (gate E additionally needs the quote to resolve in the real
  material when `check` runs).
* `SE5` (`assembly`) omits `linestyle`/`arrow` on purpose: `resolve_edge_style` supplies
  `solid`/`none`, and that resolved pair is what lands in `scene.json` and what K904 compares.
* The same spec is kept as a runnable probe in `work/verify/schema-probe/spec.json`; its
  validator output is `0 issue(s), 0 error(s)`.

---

## 10. Reference spec

The hand-authored reference spec is `examples/synthetic-001/expected/spec.json`
(`SYNTHETIC EXAMPLE - NOT AN OFFICIAL CASE`, `case_id` = `SYNTHETIC-AR-001`). Measured from that
file:

| Property | Value |
|---|---|
| schema version | `1.1` |
| roles | `apparatus`, `flow`, `route`, `data` |
| panels | 4 — P1 apparatus (11 nodes / 12 edges / 12 declared), P2 flow (9 / 12 / 12, 1 legend, sequence of 9), P3 route (4 / 3 / 3, 4 phases), P4 data (4 / 0, 1 chart, 1 legend) |
| totals | 28 nodes, 27 edges, 15 `expected_relations`, 40 evidence items |
| canvas | declared 240 × 250 mm, resolved 240 × 250 mm |

Status of that spec (`scene.validate_spec`, this repository):

| Check | Result |
|---|---|
| `scene.validate_spec` | **0 errors, 0 warnings** |
| `ar.py build` | exit **0**, `scene.json` carries every v1.1 passthrough key |
| `ar.py selftest --quick` | exit **0**, 11/11 checks, gates A–K present, `status=ok` |

Two behaviours worth copying explicitly:

* The chart series in P4 use the **`sources` list** form when a series spans several CSV rows.
* Converted values (a fold change, a space-time yield) are **`derived: true` with
  `source_values`**, because a computed number cannot appear verbatim in the source text.

---

> **Provenance annotation — the three ways to satisfy gate E.**
> 1. **Direct**: the number appears verbatim in the cited quote (`source` on a node/edge/phase/
>    series). Gate E looks for it under `%g`, `%.1f`, `%.2f`, `%.3f` or an integer/plain
>    rendering, with digit boundaries (`2.8` matches `2.8`, not `12.85`).
> 2. **Multi-source**: a series whose values come from several rows cites `sources: [id, …]`;
>    each value must appear in **one of** the quotes.
> 3. **Derived**: a computed value sets `derived: true` and lists its inputs in `source_values`;
>    gate E then verifies the **inputs** are in the quote(s) instead. `derived` without
>    `source_values` → `E907` warn and no value check at all.
>
> Missing `source` entirely is `E903` (error); an unknown id is `E904`; an unresolvable quote is
> `E905`; a number absent from every cited quote is `E906` (error). Nothing here is advisory —
> any of these errors makes `ar.py check` exit `1`. Gate E covers nodes, edges, chart series,
> legend items, **steps, phases and ports**.
