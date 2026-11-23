---
name: okf
description: Author, validate, navigate, and answer questions from Open Knowledge Format (OKF) bundles. Use for OKF catalog conversion, provenance, trust and freshness review, bundle indexes, and attested computations. Supports v0.3 and earlier bundles.
---

# Open Knowledge Format (OKF)

Author new bundles using **OKF v0.3**. Use the bundled [official specification](references/SPEC.md) for exact rules. §12.1 and Appendix B describe compatibility with v0.2, undeclared bundles, and v0.1.

## Core model

- **Bundle** — a directory tree of `.md` files. The unit of distribution.
- **Concept** — one markdown file describing one unit of knowledge (a table,
  a metric, an API, a playbook, an idea). Its **concept ID** is the file path
  without `.md` (e.g. `tables/users.md` → `tables/users`).
- **Reserved filenames** — `index.md` (directory listing) and `log.md`
  (change history) are never concept docs.
- **Links** — standard markdown links between concepts express relationships;
  the surrounding prose conveys the relationship's meaning. Broken links are
  legal (they mark not-yet-written knowledge).

Skip dot-paths and symlinks outside the bundle. Other Markdown files, including README.md, can coexist with concepts. Only a non-reserved Markdown file with a non-empty string `type` is a concept.

## Concept document format

Start and end YAML 1.2 core-schema frontmatter with an exact `---` line. Use unique mapping keys and quote strings that resemble numbers or booleans. Preserve existing values and unknown keys at every level when editing. Use `x-<producer>-<name>` for extensions. Write the body in CommonMark with GFM tables and footnotes.

````markdown
---
type: BigQuery Table            # REQUIRED — the only required field
title: Customer Orders          # recommended: display name
description: One row per completed customer order.   # recommended: one line
resource: https://console.cloud.google.com/bigquery?p=acme&d=sales&t=orders
tags: [sales, orders]
generated: { by: reference_agent/gemini-2.5-pro, at: 2026-07-13T00:00:00Z }
verified: { by: human:ahormati, at: 2026-07-14T09:00:00Z }
status: stable                  # draft | stable | deprecated
stale_after: 2026-12-31T00:00:00Z   # absolute instant; stale when now >= this
sources:
  - id: bq-schema
    resource: https://console.cloud.google.com/bigquery?p=acme&d=sales&t=orders
    title: BigQuery table schema
    author: team:data-platform
    last_modified: 2026-07-01T00:00:00Z
# any extra producer-defined keys are allowed
---

One row per completed customer order across web, mobile, and marketplace
channels. The grain is the order, not the line item — per-line detail lives in
[order_lines](order_lines.md). Covers 2019-01-01 onward.[^bq-schema]

# Schema

| Column        | Type   | Description                                     |
|---------------|--------|-------------------------------------------------|
| `order_id`    | STRING | Unique order identifier.                        |
| `customer_id` | STRING | FK to [customers](customers.md).                |

# Common query patterns

```sql
SELECT COUNT(*) FROM `acme.sales.orders`;
```

[^bq-schema]: BigQuery table schema
````

Rules that matter:

- `type` is the **only required** frontmatter key. Pick descriptive,
  self-explanatory values (`BigQuery Table`, `Metric`, `API Endpoint`,
  `Playbook`, `Reference`, `Attested Computation`); there is no central
  registry, and consumers must tolerate unknown types.
- Prefer **structural markdown** (headings, tables, fenced code) over prose —
  it serves both humans and retrieval.
- **Body section order** for a concept describing an asset: a short prose
  description (1–3 paragraphs), then `# Schema`, then
  `# Common query patterns`. For a table, the opening prose should state the
  grain ("one row per X"), the time range covered, and any sampling or
  obfuscation caveats. `# Computation` is the sanctioned-computation section
  (see below). The spec also names `# Examples` as a generic heading, but
  every reference bundle uses `# Common query patterns` — prefer it for
  queryable assets.
- Attribute a specific claim with a **markdown footnote whose label is a
  `sources[].id`** (`[^bq-schema]`). The label is the join key — do not use
  positional references like `sources[0]`, which misattribute silently the
  moment an agent reorders the list.

### Cross-linking

Use file-relative links such as `[orders](../tables/orders.md)` for GitHub navigation. A leading slash, as in `/tables/orders.md`, starts at the bundle root. Accept both forms in links and path fields. Resolve bare paths from the containing file. Percent-encode spaces and reserved characters, preserve filename case, and treat locations outside the bundle as external. For v0.2 and earlier or undeclared bundles, try the bundle root if a relative path **field** misses. A broken link can mark knowledge still to be written.

## Provenance, trust, and lifecycle

These frontmatter families are what v0.2 adds. All are optional, and their
*absence* carries meaning: an unverified concept is distinguishable from a
verified one. Never reject a concept for missing them.

| Field | Shape | Meaning |
|---|---|---|
| `sources` | list of `{ id, resource, title, author, usage_count, last_modified }` | What the concept derives from. `resource` is required within an entry. |
| `usage_window` | `{ from, to }`, sibling of `sources` | Datetime range framing every `usage_count`. |
| `generated` | `{ by, at }` | How the current content was produced. `by` is required; `at` is the last meaningful content change. |
| `verified` | list of `{ by, at }` | Who confirmed the content. A bare mapping counts as a one-element list. |
| `status` | `draft` \| `stable` \| `deprecated` | Absent ⇒ `stable`. |
| `stale_after` | ISO 8601 timestamp | Stale when `now >= stale_after`. Absolute, never a relative TTL. |

**Timestamp convention** for every timestamp-valued key (`generated.at`,
`verified[].at`, `stale_after`, `sources[].last_modified`, `usage_window.from`
and `.to`): an ISO 8601 datetime with an explicit offset — `2026-06-30T14:00:00Z`.
A date alone denotes midnight UTC. A date-time requires an explicit offset. If a deadline cannot be parsed, report freshness as unknown. A stale concept requires review.

Use `human:<id>` for a person, `team:<id>` for a team, `process:<id>` for automation, or `<producer>/<version>` for a tool. Record actual verification only. A verification needs both `by` and `at`. For every bundle, compare its instant with the last meaningful content change (`generated.at`). Events at or after that instant are current. When generation is absent, all valid events are current. Any current human review gives *human-reviewed*, other current events give *machine-confirmed*, and no current event gives *unverified*. Retain older events as history.

For a moved or retired concept, retain the old file with `status: deprecated` and set `superseded_by` to the replacement path when available. Follow that path for current knowledge. Exclude unknown status values from current-knowledge filters.

## Attested computations

When a concept carries a *number*, `type: Attested Computation` records the
sanctioned way to compute it, so a consumer can confirm the agent ran the
blessed computation instead of improvising its own SQL.

Each computation is **its own concept**; concepts that need the value link to
it. One computation per figure — revenue, profit, and margin are three
concepts, because each verifies, goes stale, and attests independently.

````markdown
---
type: Attested Computation
title: Revenue for fiscal year
description: Recognized revenue for a fiscal year, per Finance's definition.
runtime: bigquery                # REQUIRED for this type
parameters:
  - { name: year, type: integer, required: true }
executor:
  resource: references/skills/run-on-bq.md
  receipt: [job_id, executed_sql, result]
attester:
  resource: references/attesters/revenue.py
status: stable
stale_after: 2026-09-23T00:00:00Z
---

# Computation

```sql
SELECT SUM(amount) AS revenue
FROM finance.recognized_revenue
WHERE fiscal_year = @year
```
````

- `runtime` defines what `parameters` mean (a SQL bind variable, a dbt var, a
  Python argument). Each parameter requires a name and type. Its `required` flag defaults to false.
- Read `computation` when present. Otherwise take the first fenced block under a `Computation` ATX heading, up to the next heading at the same or higher level. A missing computation cannot attest.
- Give the computation **either** inline under `# Computation` **or** as a
  `computation:` path to a file — not both.
- `executor.resource` names run instructions; `executor.receipt` declares the
  evidence a run must return. `attester.resource` names deterministic code
  (no LLM) that checks a receipt.
- **When consuming one: you may only supply values for the declared
  `parameters`. Never author or edit the computation.** That restriction is
  the whole point — it makes "did the sanctioned thing run" a mechanical
  comparison instead of a judgement call.
- `verified` confirms the *definition* matches policy (doc-level, stored);
  attestation confirms a single *run* (per-call, not stored). Both exist.

## Index and log files

`index.md` — optional per-directory listing for progressive disclosure.
No frontmatter (exception: the bundle-root index may carry a frontmatter
block declaring `okf_version: "0.3"`, `title`, `description`, `license`, and extension keys). Preserve this block during regeneration.

Group entries by the concept's **`type`**, using the type name verbatim as the
section heading, sections in alphabetical order. Within a section, sort entries
by title. Put subdirectories last, under a literal `# Subdirectories` heading,
linking to the directory's `index.md`:

```markdown
# BigQuery Table

* [Customers](customers.md) - One row per registered customer.
* [Orders](orders.md) - One row per completed customer order.

# Metric

* [Revenue](revenue.md) - Recognized revenue for a fiscal year.

# Subdirectories

* [references](references/index.md) - Lookup tables and join documentation.
```

Entry format is `* [{title}]({filename}) - {description}`, dropping the
` - {description}` suffix when the concept has none, and falling back to the
filename stem when it has no `title`. Descriptions come from the target's
frontmatter; abridging a long one is fine. Note this links `<dir>/index.md`
rather than the `<dir>/` shown in spec §8 — linking the index file is what
upstream generates and what renders on GitHub.

Run `scripts/generate_index.py` (below) rather than writing these by hand.

`log.md` — optional change history, without frontmatter in v0.3, newest first, ISO `YYYY-MM-DD` date
headings, bold verb convention (`**Update**`, `**Creation**`, `**Deprecation**`):

```markdown
# Directory Update Log

## 2026-07-13
* **Creation**: Added [Orders](tables/orders.md).
```

## Workflow: authoring a bundle

1. **Plan the hierarchy by concept kind**, not by source system — e.g.
   `datasets/`, `tables/`, `references/`, `playbooks/`, with
   `references/metrics/`, `references/joins/`, `computations/` as needed. The
   layout is free; choose what makes the knowledge navigable.
2. **Write one concept per file.** Start from whatever ground truth exists
   (a live schema, API spec, existing docs) and record it as frontmatter +
   structured body.
3. **Record provenance as you go.** Every externally sourced claim gets a
   `sources` entry with an `id`, and the claim gets a `[^id]` footnote. Set
   `generated: { by, at }` with your own actor string on anything you write.
4. **Cross-link aggressively** with file-relative links: dataset → its tables,
   table → join partners, metric → the computation it is produced by. The
   link graph is where much of the value lives — a bundle without links is
   just a pile of files.
5. **Generate `index.md` for every directory** (and the root) by running
   `python3 scripts/generate_index.py <bundle-dir>`. Re-run it after adding or
   removing concepts; `--check` fails without writing if any index is stale.
   For a new bundle, declare `okf_version: "0.3"` in the root index frontmatter. Keep existing version declarations when maintaining older bundles.
6. **Append to `log.md`** under today's date when making meaningful changes.
7. **Validate** (next section) before handing the bundle over.

When converting existing metadata (a database, dbt project, OpenAPI spec),
map each addressable object to one concept, put its canonical URI in
`resource`, render its schema as a `# Schema` table, and cite the extraction
source in `sources`.

## Workflow: validating a bundle

Install the YAML 1.2 reader in your Python environment with `python3 -m pip install -r scripts/requirements.txt`. Resolve these paths from the installed skill directory.

```
python3 scripts/validate_okf.py <bundle-dir> [--strict] [--report] [--today YYYY-MM-DD]
python3 scripts/generate_index.py <bundle-dir> [--check] [--rebuild]
```

**Conformance (§11).** In v0.3 every frontmatter block must be a YAML mapping and reserved files must follow their format. A Markdown file without frontmatter or a type gets a warning and is skipped in reports and index discovery. Accept legacy log frontmatter in undeclared bundles. For a declared v0.2 or v0.1 bundle, continue to require frontmatter and a type on each non-reserved Markdown file.

**Warnings** are soft guidance the spec says consumers must tolerate: broken
cross-links, missing descriptions, missing `index.md`, malformed trust or
provenance fields, path-valued fields pointing at missing files, dangling
footnotes, concepts past their `stale_after`, and legacy v0.1 fields.
`--strict` promotes warnings to errors.

Fix errors; use judgment on warnings — a broken link is sometimes an
intentional placeholder for knowledge not yet written.

`--report` skips validation and prints each concept's `type`, `status`, trust
tier, and staleness, with totals. Use it to answer "what in this bundle still
needs human review, and what has gone stale" before relying on a bundle or
handing one over. `--today` pins the clock to midnight UTC on that date, which is what makes staleness
output reproducible.

When asked to fix a bundle, prefer minimal edits: add missing frontmatter
rather than rewriting bodies, and never discard unknown frontmatter keys or
unknown types — the spec requires tolerating them.

## Workflow: consuming a bundle

Use **progressive disclosure** — don't bulk-load the whole tree:

1. Read the root `index.md` (or list the root directory if absent) to map the
   hierarchy.
2. Descend only into relevant directories via their `index.md` files.
3. Read the specific concept docs you need; follow their cross-links to join
   partners, parent datasets, and referenced computations for context.
4. Treat frontmatter as queryable structure (filter by `type`, `tags`,
   `status`); treat bodies as the authoritative prose/schema content.
5. **Check trust and freshness before relying on a claim.** Derive the trust
   tier from `verified`, and treat a concept as stale when
   `now >= stale_after`. Say so when you rely on something unverified or
   stale rather than presenting it as settled fact.
6. **Honour `status`.** Prefer `stable`; treat `draft` as provisional; do not
   use `deprecated` concepts for new work, even though they remain readable.
7. For a figure backed by an `Attested Computation`, run the sanctioned
   computation with your parameter values — do not compose your own — and
   surface the attestation result. Show the verdict and reason on failure. Present a value as attested only after successful verification with a declared runtime, computation, and attester.
8. Tolerate everything the spec says to tolerate: unknown types, extra keys,
   broken links, missing indexes, absent trust fields. Never reject a bundle
   for those.

To answer a question from a bundle, cite the concept files you used (by
concept ID) in your answer so the user can verify.

## Reading v0.1 bundles

v0.2 supersedes v0.1 and retires two of its conventions. When reading an
older bundle, fall back gracefully; when writing, use v0.3. Preserve the version of an existing bundle unless migrating it.

| v0.1 | v0.2 | Fallback when consuming |
|---|---|---|
| `timestamp: <ISO 8601>` | `generated: { by, at }` | Read `timestamp` as `generated.at` when `generated` is absent. |
| body `# Citations` list, numbered `[1] …` | `sources` frontmatter + `[^id]` footnotes | Still parse a `# Citations` list for v0.1 docs. |
