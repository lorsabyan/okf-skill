---
name: okf
description: Author, validate, consume, and navigate Open Knowledge Format (OKF) knowledge bundles — directories of markdown files with YAML frontmatter that describe datasets, tables, metrics, APIs, playbooks, and other concepts. Use this skill whenever the user mentions OKF, knowledge bundles, a knowledge catalog, "metadata as code", documenting a dataset/schema as markdown, creating concept docs with frontmatter, or asks to generate, check, fix, browse, or answer questions from a bundle of markdown knowledge files. Also use it when converting existing catalog metadata (BigQuery, Dataplex, dbt, OpenAPI, database schemas) into agent-readable markdown documentation.
---

# Open Knowledge Format (OKF)

OKF v0.1 is a vendor-neutral format for representing knowledge — the metadata,
context, and curated insight around data and systems — as plain markdown files
with YAML frontmatter, organized in a directory tree called a **bundle**.
No SDK, no registry, no required tooling: if you can read a file you can
consume OKF, and if you can `git clone` you can ship it.

The full specification is in [references/SPEC.md](references/SPEC.md).
Read it when you need exact rules (reserved filenames, conformance,
versioning). This file covers the 90% you need for day-to-day work.

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

## Concept document format

Every concept file = YAML frontmatter + markdown body:

````markdown
---
type: BigQuery Table            # REQUIRED — the only required field
title: Customer Orders          # recommended: display name
description: One row per completed customer order.   # recommended: one line
resource: https://console.cloud.google.com/bigquery?p=acme&d=sales&t=orders
tags: [sales, orders]
timestamp: 2026-07-13T00:00:00Z # ISO 8601 last meaningful change
# any extra producer-defined keys are allowed
---

# Schema

| Column        | Type   | Description                                     |
|---------------|--------|-------------------------------------------------|
| `order_id`    | STRING | Unique order identifier.                        |
| `customer_id` | STRING | FK to [customers](/tables/customers.md).        |

# Examples

```sql
SELECT COUNT(*) FROM `acme.sales.orders`;
```

# Citations

[1] [BigQuery table schema](https://console.cloud.google.com/bigquery?p=acme&d=sales&t=orders)
````

Rules that matter:

- `type` is the **only required** frontmatter key. Pick descriptive,
  self-explanatory values (`BigQuery Table`, `Metric`, `API Endpoint`,
  `Playbook`, `Reference`); there is no central registry, and consumers must
  tolerate unknown types.
- Prefer **structural markdown** (headings, tables, fenced code) over prose —
  it serves both humans and retrieval.
- Conventional section headings (use when applicable): `# Schema`,
  `# Examples`, `# Citations`.
- Cross-link with **bundle-absolute paths** starting with `/`
  (`[customers](/tables/customers.md)`) — stable under file moves. Relative
  links (`./other.md`) are allowed but second choice.
- External sources backing claims go under `# Citations`, numbered `[1] …`.

## Index and log files

`index.md` — optional per-directory listing for progressive disclosure.
No frontmatter (exception: the bundle-root index may carry a frontmatter
block declaring `okf_version: "0.1"`). Body is sections of bulleted links,
each entry carrying the target's description:

```markdown
# Tables

* [Orders](orders.md) - One row per completed customer order.
* [Customers](customers.md) - One row per registered customer.
```

`log.md` — optional change history, newest first, ISO `YYYY-MM-DD` date
headings, bold verb convention (`**Update**`, `**Creation**`, `**Deprecation**`):

```markdown
# Directory Update Log

## 2026-07-13
* **Creation**: Added [Orders](/tables/orders.md).
```

## Workflow: authoring a bundle

1. **Plan the hierarchy by concept kind**, not by source system — e.g.
   `datasets/`, `tables/`, `references/`, `playbooks/`, with
   `references/metrics/`, `references/joins/` as needed. The layout is free;
   choose what makes the knowledge navigable.
2. **Write one concept per file.** Start from whatever ground truth exists
   (a live schema, API spec, existing docs) and record it as frontmatter +
   structured body. Add `# Citations` for every externally sourced claim.
3. **Cross-link aggressively** with `/`-absolute links: dataset → its tables,
   table → join partners, metric → the tables it is computed from. The link
   graph is where much of the value lives — a bundle without links is just a
   pile of files.
4. **Generate `index.md` for every directory** (and the root), each entry
   reusing the concept's frontmatter `description`. Keep them in sync when
   adding or removing concepts.
5. **Append to `log.md`** under today's date when making meaningful changes.
6. **Validate** (next section) before handing the bundle over.

When converting existing metadata (a database, dbt project, OpenAPI spec),
map each addressable object to one concept, put its canonical URI in
`resource`, and render its schema as a `# Schema` table.

## Workflow: validating a bundle

Run the bundled validator (stdlib-only Python, no dependencies):

```
python scripts/validate_okf.py <bundle-dir>
```

It checks the v0.1 conformance rules — parseable frontmatter with a non-empty
`type` on every concept doc, reserved-file structure — and warns (without
failing) on soft issues: broken cross-links, missing descriptions, missing
`index.md`, index entries drifting from concept descriptions. Exit code 0 =
conformant. Fix errors; use judgment on warnings (broken links are sometimes
intentional placeholders).

When asked to fix a bundle, prefer minimal edits: add missing frontmatter
rather than rewriting bodies, and never discard unknown frontmatter keys or
unknown types — the spec requires tolerating them.

## Workflow: consuming a bundle

Use **progressive disclosure** — don't bulk-load the whole tree:

1. Read the root `index.md` (or list the root directory if absent) to map the
   hierarchy.
2. Descend only into relevant directories via their `index.md` files.
3. Read the specific concept docs you need; follow their cross-links to join
   partners, parent datasets, and referenced metrics for context.
4. Treat frontmatter as queryable structure (filter by `type`, `tags`,
   `timestamp`); treat bodies as the authoritative prose/schema content.
5. Tolerate everything the spec says to tolerate: unknown types, extra keys,
   broken links, missing indexes. Never reject a bundle for those.

To answer a question from a bundle, cite the concept files you used (by
concept ID) in your answer so the user can verify.
