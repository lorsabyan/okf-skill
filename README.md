# okf-skill

[![CI](https://github.com/lorsabyan/okf-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/lorsabyan/okf-skill/actions/workflows/ci.yml)

An [Agent Skill](https://agentskills.io) that teaches coding agents — **Claude Code** and
**OpenAI Codex** — to author, validate, and consume
[Open Knowledge Format (OKF) v0.2](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/3fcbb9f/okf/SPEC.md)
knowledge bundles: directories of markdown files with YAML frontmatter that describe
datasets, tables, metrics, APIs, playbooks, and attested computations.

## What's inside

```
okf/                            # this directory is the skill; symlink or copy it
├── SKILL.md                    # format quick-reference + authoring/validating/consuming workflows
├── references/
│   └── SPEC.md                 # full OKF v0.2 spec (verbatim from GoogleCloudPlatform/knowledge-catalog)
└── scripts/
    ├── validate_okf.py         # conformance validator + trust/freshness report (exit 0 = conformant)
    └── generate_index.py       # index.md generator; non-destructive, --check for CI
tests/                          # not part of the skill payload
```

## Install

### Claude Code

Symlink (recommended — tracks this repo as you pull updates) or copy the
`okf/` folder into your skills directory:

```sh
ln -sfn "$PWD/okf" ~/.claude/skills/okf
```

```sh
rm -rf ~/.claude/skills/okf && cp -r okf ~/.claude/skills/okf
```

Swap `~/.claude` for `<project>/.claude` to scope it to one project. Claude
Code picks it up automatically; it triggers on OKF / knowledge-bundle tasks,
or invoke it explicitly with `/okf`.

### Codex CLI

Codex uses the same SKILL.md format:

```sh
ln -sfn "$PWD/okf" ~/.codex/skills/okf
```

## Validator

Stdlib-only, no dependencies. CI covers Python 3.9, 3.11, and 3.13 on Linux
plus 3.13 on macOS; the code uses no syntax newer than 3.7.

```sh
python3 okf/scripts/validate_okf.py <bundle-dir> [--strict]
```

**Errors** (exit 1) are the three v0.2 conformance rules from §11: every
non-reserved `.md` file has a parseable YAML frontmatter block, every block
has a non-empty `type`, and reserved files (`index.md`, `log.md`) follow
their structure.

**Warnings** (exit 0) are soft guidance the spec says consumers must
tolerate:

- broken cross-links, and path-valued fields (`resource`, `sources[].resource`,
  `computation`, `executor.resource`, `attester.resource`) pointing at files
  that aren't in the bundle
- missing `description`, missing `index.md`, index entries with no description
- malformed provenance, trust, and lifecycle fields — `generated.by`,
  non-calendar dates in `generated.at` / `verified[].at` / `stale_after` /
  `last_modified`, unknown `status`, `sources` entries without a `resource`
- `Attested Computation` concepts missing `runtime`, a computation, or an
  `executor.resource`
- footnotes matching no `sources[].id` and having no definition
- concepts whose `stale_after` has passed
- legacy v0.1 `timestamp` and `# Citations`, as migration hints

`--strict` promotes warnings to errors. Reserved-file structure is reported
as warnings rather than errors, which is more permissive than a literal
reading of §11.3 — use `--strict` if you want those enforced.

v0.1 bundles remain valid input: their two retired conventions are reported
as migration warnings, never errors.

### Trust and freshness report

`--report` prints per-concept trust tier (§5.3) and staleness (§5.5) instead of
validating. `--today YYYY-MM-DD` pins the clock so output is reproducible.

```sh
python3 okf/scripts/validate_okf.py <bundle-dir> --report
```

```
metrics/revenue.md      Metric   stable      human-reviewed     fresh
playbooks/oncall.md     Playbook draft       unverified         STALE (since 2026-06-30)

9 concepts: 8 human-reviewed, 1 unverified | 1 stale | 1 deprecated
```

## Index generator

```sh
python3 okf/scripts/generate_index.py <bundle-dir> [--check] [--rebuild]
```

Writes an `index.md` for every directory: entries grouped under the concept's
`type`, sections alphabetical, entries sorted by title, subdirectories last
under `# Subdirectories`.

It is **non-destructive**. An index that already exists keeps its entry order,
titles, and descriptions — the reference bundles curate all three, and blindly
regenerating from frontmatter would silently discard that. Only new concepts get
appended and removed ones dropped. `--rebuild` opts into a full rewrite;
`--check` writes nothing and exits 1 when an index is out of date, for CI.

## Tests

```sh
cd tests && python3 -m unittest discover -s . -t .
```

105 tests, stdlib `unittest`, no dependencies. Fixtures are constructed in code
because two regressions under test are encoding- and whitespace-sensitive (a
UTF-8 BOM, a fence indented inside a list item) and an editor would normalize
them away in a committed file.

The reference-bundle tests are skipped unless you point them at a local
checkout — CI clones upstream at the pinned commit:

```sh
OKF_REFERENCE_BUNDLES=/path/to/knowledge-catalog/okf/bundles python3 -m unittest discover -s . -t .
```

All four upstream bundles (`ga4`, `stackoverflow`, `crypto_bitcoin`,
`acme_retail`) validate with zero errors and zero warnings under `--strict`, and
the index generator is a no-op on every one of them. CI also diffs the vendored
`SPEC.md` against upstream at the pinned commit, so the two cannot drift.

## Maintenance

**Bumping the vendored spec.** The upstream commit is pinned in exactly one
place: the attribution header of `okf/references/SPEC.md`. To move to a newer
upstream revision, replace the spec body and edit that header — CI reads the
commit from it, and `tests/test_pinned_refs.py` fails if the README or anything
else still cites the old one. There is no second copy to remember.

**The pinned clock.** CI evaluates the reference bundles as of
`REFERENCE_AS_OF` in the workflow, not the real date, so upstream's
`stale_after` dates passing cannot turn this repo's builds red — that is
upstream's lifecycle event, not a regression here. A separate non-fatal step
runs against the real clock and posts a notice for every upstream concept that
has gone stale, so you find out without the build failing. The same date is
handed to the test suite as `OKF_AS_OF`, so the gate and the tests cannot
disagree.

## Related

- [okf-reader](https://github.com/lorsabyan/okf-reader) — static-first web app
  for humans to read, navigate, and explore OKF bundles.

## License

Apache 2.0. `okf/references/SPEC.md` is reproduced verbatim from
[GoogleCloudPlatform/knowledge-catalog](https://github.com/GoogleCloudPlatform/knowledge-catalog)
at commit `3fcbb9f` (Copyright Google LLC, Apache 2.0); everything else in
this repo is original.
