# Results

Run on 2026-07-30 against `okf-skill` at the tree below and
[`okf-reader`](https://github.com/lorsabyan/okf-reader) `@okf/core` at `580df8e`.
Method and limits: [README](README.md). Corpus: [corpus.py](corpus.py).

Deterministic — no model, no grader. `--today` pinned to `2026-07-30`.
Re-running gives byte-identical output.

## Score

| Validator | Detection (19 defects) | Clean pass (10 clean) |
|---|---|---|
| **okf-skill** | **19/19** | **10/10** |
| okf-reader `@okf/core` | 9/19 | 9/10 |

Read these differently. Detection is largely a **scope** decision — `okf-reader`
is a reader, and it implements the checks its UI needs rather than aiming at
lint coverage. Clean pass is a **correctness** measure, and it is comparable
across tools: a false positive means the tool reports a defect in a bundle that
does not have one.

## The one false positive is real, and it is ours

`okf-reader` reports a broken link inside an **indented fenced code block**. Its
`extractLinkTargets` runs over the whole body without stripping fences, so a
markdown link used as an *example* inside a fence — the ordinary way to document
OKF in OKF — is link-checked as if it were prose.

That is the same defect this repo's validator shipped with and fixed. Filed
against okf-reader rather than quietly excluded from the corpus.


### Defects — a report is expected

| Case | Spec | okf-skill | okf-reader | Why it is here |
|---|---|---|---|---|
| `no-frontmatter` | §11.1 | ✅ <sub>1e/0w</sub> | ✅ <sub>1e/3w</sub> | every non-reserved .md file needs a parseable frontmatter block |
| `unparseable-frontmatter` | §11.1 | ✅ <sub>1e/0w</sub> | ✅ <sub>1e/3w</sub> | a frontmatter line that is neither a mapping nor a sequence item |
| `missing-type` | §11.2 | ✅ <sub>1e/0w</sub> | ✅ <sub>1e/0w</sub> | type is the only always-required key |
| `empty-type` | §11.2 | ✅ <sub>1e/0w</sub> | ✅ <sub>1e/0w</sub> | a blank type is as absent as a missing one |
| `broken-link` | §6.1 | ✅ <sub>0e/1w</sub> | ✅ <sub>0e/1w</sub> | a link to a concept that is not in the bundle |
| `case-mismatched-link` | §6.1 | ✅ <sub>0e/1w</sub> | ✅ <sub>0e/1w</sub> | resolves on a case-insensitive volume, breaks on a case-sensitive one |
| `missing-description` | §4.1 | ✅ <sub>0e/1w</sub> | ✅ <sub>0e/1w</sub> | index generators and previews rely on it |
| `missing-index` | §8 | ✅ <sub>0e/1w</sub> | ❌ miss <sub>0e/0w</sub> | no index.md, so progressive disclosure is unavailable |
| `generated-without-by` | §5.2 | ✅ <sub>0e/1w</sub> | ✅ <sub>0e/1w</sub> | by is required within generated |
| `impossible-date` | §5.2 | ✅ <sub>0e/1w</sub> | ❌ miss <sub>0e/0w</sub> | 2026-02-30 passes a shape-only regex but is not a date |
| `unknown-status` | §5.4 | ✅ <sub>0e/1w</sub> | ❌ miss <sub>0e/0w</sub> | status outside draft | stable | deprecated |
| `past-stale-after` | §5.5 | ✅ <sub>0e/1w</sub> | ✅ <sub>0e/1w</sub> | the concept is stale as of the evaluation date |
| `source-without-resource` | §5.1 | ✅ <sub>0e/1w</sub> | ❌ miss <sub>0e/0w</sub> | resource is required within a sources entry |
| `dangling-footnote` | §5.1 | ✅ <sub>0e/1w</sub> | ❌ miss <sub>0e/0w</sub> | a footnote label joining to no sources id and having no definition |
| `computation-without-runtime` | §10.2 | ✅ <sub>0e/1w</sub> | ❌ miss <sub>0e/0w</sub> | runtime is required for an Attested Computation |
| `computation-without-computation` | §10.3 | ✅ <sub>0e/1w</sub> | ❌ miss <sub>0e/0w</sub> | neither a computation path nor a # Computation body section |
| `dead-path-field` | §6.2 | ✅ <sub>0e/1w</sub> | ❌ miss <sub>0e/0w</sub> | a path-valued frontmatter field pointing at a file not in the bundle |
| `legacy-timestamp` | §13 | ✅ <sub>0e/1w</sub> | ❌ miss <sub>0e/0w</sub> | v0.1 timestamp; v0.2 records this as generated.at |
| `legacy-citations` | §13 | ✅ <sub>0e/1w</sub> | ❌ miss <sub>0e/0w</sub> | v0.1 # Citations body list; v0.2 records provenance in sources |

### Clean — silence is expected

| Case | Spec | okf-skill | okf-reader | Why it is here |
|---|---|---|---|---|
| `bom-prefixed` | §4 | ✅ <sub>0e/0w</sub> | ✅ <sub>0e/0w</sub> | a UTF-8 BOM is legal; a naive reader sees no frontmatter delimiter |
| `indented-fence` | §4.2 | ✅ <sub>0e/0w</sub> | ❌ false positive <sub>0e/1w</sub> | a fence inside a numbered list; its contents are code, not links |
| `indented-index-entries` | §8 | ✅ <sub>0e/0w</sub> | ✅ <sub>0e/0w</sub> | entries indented and bulleted with '+' are still entries |
| `wrapped-scalar` | §4.1 | ✅ <sub>0e/0w</sub> | ✅ <sub>0e/0w</sub> | YAML line folding; truncating it silently loses half the description |
| `bare-verified-mapping` | §5.2 | ✅ <sub>0e/0w</sub> | ✅ <sub>0e/0w</sub> | a single verifier MAY be a bare mapping; consumers MUST read it as a 1-element list |
| `flush-left-sequence` | §4.1 | ✅ <sub>0e/0w</sub> | ✅ <sub>0e/0w</sub> | the sequence style upstream's serializer actually emits |
| `scope-descriptor-source` | §5.1 | ✅ <sub>0e/0w</sub> | ✅ <sub>0e/0w</sub> | a sources resource may be a population descriptor, not a path |
| `unknown-type-and-keys` | §11 | ✅ <sub>0e/0w</sub> | ✅ <sub>0e/0w</sub> | consumers MUST NOT reject unknown types or unrecognized keys |
| `self-defined-footnote` | §5.1 | ✅ <sub>0e/0w</sub> | ✅ <sub>0e/0w</sub> | a numeric footnote that defines itself joins to no source, and need not |
| `future-stale-after` | §5.5 | ✅ <sub>0e/0w</sub> | ✅ <sub>0e/0w</sub> | stale_after in the future is not stale |

### Score

| Validator | Detection | Clean pass |
|---|---|---|
| okf-skill | 19/19 | 10/10 |
| okf-reader | 9/19 | 9/10 |

