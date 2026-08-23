# Changelog

All notable changes to this skill are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**The version tracks the skill, not the format.** They happen to line up at
`0.2.x` today because this release is what added OKF v0.2 support, but a future
`0.3.0` would not imply an OKF v0.3 — the OKF version this skill targets is
always the one pinned in `okf/references/SPEC.md`'s attribution header.

## [Unreleased]

### Changed

- **Followed OKF to its own repository.** Upstream moved the format out of
  `GoogleCloudPlatform/knowledge-catalog`, whose `okf/` directory is now a frozen,
  unmaintained snapshot, and said so in its README. The vendored spec, both
  workflows, and every citation now pin
  [`ad30107`](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107/SPEC.md) in
  `GoogleCloudPlatform/open-knowledge-format`. CI's env var is `OKF_UPSTREAM_REF`, was
  `KNOWLEDGE_CATALOG_REF`.

### Fixed

- **`stale_after` and `sources[].last_modified` accept an ISO 8601 timestamp.**
  §5 now asks for a datetime with an explicit offset — tightened upstream without
  an `okf_version` bump, so nothing signalled the change. The bare-`YYYY-MM-DD`
  check warned on the exact form upstream now writes: 16 spurious warnings across
  the reference bundles, which the `--strict` gate turned into a red build. A bare
  date stays accepted, because bundles written against the earlier v0.2 text
  declare the same version and are not retroactively non-conformant.

### Added

- `usage_window.from` and `.to` are checked as timestamps. Only the presence of
  the two keys was validated before; their values were never looked at.
- `SKILL.md` states the timestamp convention and its one exception. The two
  authoring examples were still teaching bare dates, so agents following the
  skill kept emitting the form upstream moved away from — the validator accepted
  it, which is exactly why nothing caught it. `log.md` date headings (§9) stay
  `YYYY-MM-DD`; the spec is explicit about that and the validator's
  `DATE_HEADING_RE` is unchanged.

## [0.2.0] — 2026-07-30

Targets **OKF v0.2**, pinned to upstream
[`3fcbb9f`](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f/okf/SPEC.md).

### Added

- **`generate_index.py`** — a stdlib-only `index.md` generator. Non-destructive
  by design: an index that already exists keeps its entry order, titles, and
  descriptions, and only additions and removals apply. The reference bundles
  curate all three, so a blind regeneration would silently discard curation.
  `--check` fails without writing, for CI; `--rebuild` opts into a full rewrite.
- **Trust and freshness reporting** — `validate_okf.py --report` prints each
  concept's `type`, `status`, trust tier (§5.3), and staleness (§5.5), with
  totals. `--today` pins the clock so output is reproducible.
- **Attested Computation support** (§10) — the skill teaches the contract
  (`runtime`, `parameters`, `executor`, `attester`) and the rule that a caller
  supplies parameter values and never rewrites the computation.
- **Test suite and CI** — 105 tests, stdlib `unittest`, no dependencies. CI runs
  Python 3.9/3.11/3.13 on Linux plus 3.13 on macOS; the macOS leg exists because
  link resolution is case-exact and a case-insensitive volume must not diverge.
- **Scheduled upstream-freshness workflow** — checks the pinned reference
  bundles against the real clock weekly and reports by maintaining a single
  issue: opened when a concept passes its `stale_after`, refreshed while it
  persists, closed when it clears.
- **Dependabot config** for the workflow Actions, the repo's only pinned
  dependencies.

### Changed

- **Cross-linking guidance is now file-relative, not `/`-absolute.** A leading
  `/` resolves against the GitHub *site* rather than the bundle root, so it 404s
  whenever a bundle sits in a subdirectory — a layout the spec explicitly
  supports. Upstream's own reference-agent prompt forbids it outright, and the
  reference bundles are 175 relative to 8 absolute, with the agent-produced ones
  entirely relative. This diverges from §6.1's stated preference, deliberately
  and with the reason documented.
- **Body sections follow practice**: prose → `# Schema` → `# Common query
  patterns`. `# Examples` is the spec's conventional name but appears **zero**
  times across the reference bundles, against 31 uses of the former.
- **Index convention documented mechanically** — entries grouped under the
  concept's `type`, sections alphabetical, entries sorted by title,
  subdirectories last linking `<dir>/index.md`.
- **The validator parses OKF v0.2.** The previous line-splitting frontmatter
  reader could not represent it at all: nested block maps, sequences of flow
  maps, and values containing colons (`at: 2026-06-30T14:00:00Z`,
  `by: human:ahormati`) were unreadable. Replaced with a YAML-subset parser,
  still stdlib-only.
- **The upstream commit is pinned in exactly one place** —
  `okf/references/SPEC.md`'s attribution header. CI derives it from there and
  tests assert every other citation agrees, so a version bump cannot half-happen.
- GitHub Actions updated to current majors (`checkout` v4 → v7,
  `setup-python` v5 → v7); v4 targeted the deprecated Node 20 runtime.

### Fixed

- **A UTF-8 BOM made a valid document a hard error.** Now decoded via
  `utf-8-sig`.
- **A fenced block indented inside a list item had its contents link-checked**,
  so example markdown inside a numbered list produced phantom broken links.
- **Index entries indented or bulleted with `+` were read as no entries at all.**
- **A `description:` wrapped across two lines lost everything after the first.**
  YAML line folding was not handled, and the truncation was silent.
- **Link resolution is now case-exact** rather than deferring to the filesystem.
  A link to `/tables/Customers.md` when only `customers.md` exists used to pass
  on macOS and fail on Linux. This can surface new warnings on macOS; they are
  real, and CI was already reporting them.
- **Dates are calendar-validated**, so `2026-13-99` and `2026-02-30` no longer
  pass a shape-only check.

### Compatibility

v0.1 bundles remain valid input. The two retired conventions — `timestamp` and
the `# Citations` body list — are reported as migration warnings, never errors,
and the skill documents reading both.

## [0.1.0] — 2026-07-13

Initial release. Agent Skill for Claude Code and Codex teaching OKF v0.1:
bundle structure, concept documents, cross-linking, index and log files, and a
stdlib-only conformance validator.

[Unreleased]: https://github.com/lorsabyan/okf-skill/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/lorsabyan/okf-skill/releases/tag/v0.2.0
[0.1.0]: https://github.com/lorsabyan/okf-skill/releases/tag/v0.1.0
