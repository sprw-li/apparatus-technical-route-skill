# Provenance and evidence

The point of this Skill is that a figure can be **audited**. Gate E is the audit, and it is
mechanical: every component, stream, step, phase, port, number and unit drawn on the page must
resolve, character by character, into a real material file that the runtime actually handed us.

Sources of truth: `scripts/validate.py::gate_e` / `_own_provenance` (the gate that decides
pass/fail), `scripts/evidence.py` (ledger construction, `check_provenance`, `_element_values`),
`scripts/ingest.py` (extraction, locators, sha256), `ar.py::build_result` (what lands in
`result.json`).

---

## 1. The chain

```
/input/materials/**  --ingest-->  materials.json   (text + locators + sha256 + warnings)
                                      |
                                      v
                            evidence-ledger.json   (candidate claims with sources)
                                      |
              author (LLM/human)  --> spec.json.evidence[]   {id, claim, kind, value, unit,
                                      |                       source:{file,locator,quote}}
                                      v
              nodes / edges / series / steps / phases / ports / legend-items .source = <id>
                                      |
                                      v
                        gate E  -- resolves the quote against the material text and checks
                                    that every referenced id exists
                                      |
                                      v
                    result.json.evidence[]  (per-item source + resolution note)
```

`source` is a small string — an **evidence id** — on every element, and a `{file, locator, quote}`
object on the evidence item itself. This indirection is what lets one quote back many elements and
keeps the figure's text decoupled from the source text.

## 2. What `ingest` produces

`materials.json` carries, per input file: `path`, `role` (`case` / `task` / `material`), `bytes`,
`sha256`, `kind`, `parsed`, `parse_reason`, `text`, `locator_scheme`, `locators[]`, `tables[]`,
`nodes[]`, `pages[]`, `encoding`, `truncated`, `warnings[]`.

Locator schemes are chosen per material kind:

| Material | Scheme | Example |
|---|---|---|
| text / markdown | line spans | `L11` (the reactor line of `apparatus-list.md`) |
| CSV / TSV | row spans | `row 4` (line 1 is the header) |
| JSON | pointer/leaf spans | emitted per leaf node |
| XLSX | cell / row spans | emitted per sheet row |
| PDF | **page** locators (`p.1`, `p.2`, …) | recorded per page |

Measured on the bundled fixture: `ingest` → `5 material(s), 60 evidence item(s),
case_id=SYNTHETIC-AR-001`. (`5` = case.json + task.md + three material files; `60` = the candidate
ledger, which is larger than the 40 items the authored spec cites.)

Every material also carries `sha256`, and `result.json.sources[]` publishes those hashes — that is
how a reviewer confirms the figure was built from the same bytes they hold. Measured:
`result.json.sources` has **6** entries (the 5 inputs + the resolved spec).

### Extraction quality is recorded, not hidden

* A PDF that yields no text gets `parsed: false` and a `pdf_unparsed` warning with
  `needs_human: true`; the extractor cascade actually tried is recorded in `parse_reason`.
* Garbled extraction (`alnum < 0.20` or `printable < 0.80`) still passes text through but adds a
  `low_text_quality` warning — with the honest note that the quotes are still verbatim substrings of
  the extraction.
* Oversized files are recorded by hash with a `too_large` warning; text over the cap is truncated
  and flagged (`truncated: true`).
* A 0-byte file becomes `kind: "empty"` with an `empty_file` warning.

## 3. Gate E, exactly

`validate.gate_e` runs **its own** resolver (`_own_provenance`) and *additionally* calls
`evidence.check_provenance` (any `error` issue fails the gate; a `warn` issue downgrades to warn).
It reports:
`source_checks=…, materials=…, refs=…, dangling=…, evidence_items=…, quotes_resolved=…,
quotes_unresolved=…, module_issues=…(err=…,warn=…)`.

**Measured on the bundled fixture (2026-11-23 12:5x):**

```
source_checks=evidence.check_provenance, materials=5, refs=77, dangling=0, evidence_items=40,
quotes_resolved=40, quotes_unresolved=0, module_issues=0(err=0,warn=0),
ext_elements=17, ext_numbers_checked=1, ext_numbers_off_quote=0, ext_numbers_unverifiable=0
```

Decision order (first match wins):

| Condition | Status |
|---|---|
| any `source` id does not exist in `spec.evidence[].id` (`dangling`) | **fail** |
| no material text available at all | **warn** — "UNVERIFIABLE: 0 material text, N quotes unchecked" |
| any evidence quote not found in its file | **fail** |
| `evidence.check_provenance` returned an `error` issue | **fail** |
| `evidence.check_provenance` returned a `warn` issue | **warn** |
| no provenance claims to check | **warn** |
| otherwise | **pass** |

### `evidence.check_provenance` — the strong half of gate E

Its issue codes:

| Code | Severity | Condition |
|---|---|---|
| `E900` | warn | no parsed material text available — "UNVERIFIABLE … not a pass" |
| `E901` | error | an evidence item's `{file, locator, quote}` does not resolve |
| `E902` | warn | the evidence resolves, but the declared `locator` disagrees with the locator that was actually found |
| `E903` | **error** | an element (`node`, `edge`, or chart `series`, and now `step`/`phase`/`port` with a `source`) carries **no evidence reference at all** |
| `E904` | error | an element cites evidence id(s) absent from `spec.evidence` |
| `E905` | error | an element cites evidence whose quote does not resolve |
| `E906` | **error** | a numeric value the element would print is **not present in any cited quote** — *"figure would show a number its source does not contain"* |
| `E907` | warn | the element is marked `derived: true` but declares no `source_values`, so the displayed number cannot be recomputed from its source |

### What counts as "a number the element would print"

`evidence._element_values` collects:

1. `value` and every entry of `values[]` (or, when `derived` is true, every entry of
   `source_values[]` instead);
2. **plus every number found in any other string field** of the element — which means `label`,
   `sublabel`, and an edge's `label`.

Rule 2 is deliberate ("ATP 18.7 -> 12.4 nmol/mg" is visible in the figure and used to escape the
check entirely) and it has two measured consequences for authors:

* a decorative number in a sublabel must be covered by that element's quote;
* **visual literals are exempt.** A hex/rgb colour used to be parsed as a number (`"#0072B2"` →
  `7.0`) and failed `E906`; `evidence.py` now recognises colour literals (`_COLOR_LITERAL` /
  `_visual_literal`) and skips them, so `edge.color` and a node `fill: "rgb(0, 114, 178)"` are both
  clean. Measured: 25 hex-coloured edges + 1 rgb-filled node → `check` **exit `0`**, E `pass`; the
  same spec with one node `value` changed to `999.9` → `check` **exit `1`**, `failed=['E']`. See
  [`exports-fonts-colour.md`](exports-fonts-colour.md) §6 for both forms.

### Three ways to satisfy the value check

1. **Direct** — `source: "<id>"`; the value must occur in that quote, under any of `%g`, `%.1f`,
   `%.2f`, `%.3f` or an integer/plain rendering (e.g. the node value `0.060` matches `0.060` in
   the cited CSV row), bounded so that `2.8` matches `2.8` but not `12.85`.
2. **Multi-source** — a chart series may use `sources: ["E33","E34","E35","E36"]`, and a node may
   carry `sources: ["E5","E12"]`; every value must appear in **one of** the quotes. Use the list
   form whenever an element spans several rows or two facts (the fixture uses it for the bar chart
   and for the reactor node, whose label carries both the residence time and the 365 nm driver).
3. **Derived** — a computed value (space-time yield `7.69 = 61.5 / 8.0`) sets `"derived": true` and
   `"source_values": [61.5, 8.0]`; the checker then verifies the **inputs** in the quotes and does
   *not* look for `7.69` itself. `derived` without `source_values` is **`E907` warn**, and the value
   is not checked at all — a soft escape hatch that is loudly recorded, not a silent one.

### How a quote is matched

1. `source.file` is matched to a material by, in order: exact path, suffix, then basename. A file
   that matches nothing is unresolved.
2. **Both the material text and the quote are whitespace-normalised** (`re.sub(r"\s+", " ", s)`),
   so a quote may span a line break and repeated spaces do not break it — but a changed word,
   number, hyphen or letter case does.
3. **When the quote occurs more than once, the occurrence inside the declared locator wins**
   (`evidence.resolve_locator`); a disagreement is downgraded to the **`E902` warn**.
4. `source.locator` is resolved to a character span. The resolver accepts `L<n>`, `L<n>-L<m>` (and
   `L<n>-<m>`), and `row <n>` / `rows <n>-<m>` (case-insensitive, 1-based, against the extracted
   text's own line numbering). For the fixture's CSV, `row 4` is the `R3,…` data line.
5. Quote in the file **and** inside the located span → resolved with `mode: "span"`. Quote in the
   file but the locator is unresolvable (a `p.3` page locator on a PDF, or a line span past the end)
   → **resolved** with `mode: "quote-verbatim, locator unresolved (<reason>)"` — deliberate, because
   the verbatim quote is the stronger evidence. Quote in the file but **outside** the located span →
   **unresolved → fail**.

So a wrong line number is a gate-E failure, while a non-span locator is honest-but-passing. When in
doubt, cite a **span locator** and let the gate check it.

### What `ingest`/`evidence` do *not* encode as domain knowledge

`evidence.py` trims sentence-initial/-final stop-words using a **generic English function-word
list** (`_STOP_TERMS`: determiners, pronouns, conjunctions, and the neutral nouns `cells`, `figure`,
`table`, `data`, `values`, `results`). It deliberately contains **no domain vocabulary** from the
bundled fixture — an earlier draft listed `hypoxia`/`normoxia`, which would have made the extractor
look better on our own example than on a real case (overfitting). Any word outside that generic list
is treated as a candidate entity, so a reviewer can read `_STOP_TERMS` and see exactly how much is
heuristic. That is also why the fixture's own vocabulary (rig, reactor, membrane, permeate) is *not*
special-cased anywhere.

## 4. What lands in `result.json`

```json
"evidence": [
  {"id": "E5", "claim": "A4 is a 250 mm annular UV-LED reactor ... 8.0 min residence time",
   "kind": "entity", "value": 8.0, "unit": "min",
   "source": {"file": "apparatus-list.md", "locator": "L11", "quote": "..."},
   "resolved": {"file": "apparatus-list.md", "locator": "L11"}}
],
"sources": [
  {"path": "case.json", "kind": "json", "role": "case input", "sha256": "..."},
  {"path": "materials/conditions.csv", "kind": "csv", "role": "material",
   "sha256": "...", "bytes": 752}
]
```

Measured on the fixture: `result.json.evidence` has **60** items (the whole ingest ledger, not just
the 40 the spec cites), `sources` has **6**. `ar.py::build_result` copies the ledger items through
with their `source` and, when the ledger did not record one, synthesises `resolved: {file, locator}`.
Material warnings and `spec.uncertainty` are concatenated into `result.json.uncertainty`; any failed
gate adds `{"kind": "check_failed", "subject", "reason", "needs_human": true}`.

## 5. Honesty rules that gate E enforces

* **No id, no element.** A node, edge, series, step, phase or port without `source` is a hard
  gate-E failure (`E903`), not a warning. The `W042`/`W048`/`W056` spec warnings are the early echo
  of the same mistake.
* **A dangling reference is a hard failure** (`E904` plus the independent `dangling` count). If you
  delete an evidence item, delete or repoint every element that referenced it.
* **A paraphrase is a hard failure.** Quotes must be copied from the material, not summarised.
  Whitespace may differ; words may not.
* **A number must be in a quote it cites** (`E906`), unless it is honestly declared `derived` with
  its `source_values` (`E907` warns when the inputs are missing). This is the anti-fabrication core:
  you cannot invent a value and attach a real citation.
* **A derived value is a claim about its inputs.** Marking something `derived` moves the check to
  `source_values`; if you cannot name the inputs, the number is not reproducible and should not be
  on the page.
* **Missing material is not fabricated material.** When extraction fails, the correct outcome is an
  evidence-less figure plus a `pdf_unparsed`/`no_materials` warning in `uncertainty` — and, because
  gate E then cannot verify anything, its status is `warn` (UNVERIFIABLE), never `pass`.
* **A `warn` is not a pass.** Gate E refuses to call an unmeasurable property verified. `check`
  still exits 0 on warns, so read `validation_report.json` and `result.json.audit.checks_warned`.

## 6. Reproducing the audit by hand

```
python3 scripts/ar.py ingest --input /input --work /app/work
python3 scripts/ar.py check  --out /app/output --spec /app/work/spec.json --work /app/work
python3 -c "import json;r=json.load(open('/app/output/validation_report.json'));\
print([c['detail'] for c in r['checks'] if c['id']=='E'])"
```

The gate-E detail string always contains the numbers (`refs`, `dangling`, `quotes_resolved`,
`quotes_unresolved`), so it can be quoted directly in a review.
