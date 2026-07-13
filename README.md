# okf-skill

An [Agent Skill](https://agentskills.io) that teaches coding agents — **Claude Code** and
**OpenAI Codex** — to author, validate, and consume
[Open Knowledge Format (OKF) v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
knowledge bundles: directories of markdown files with YAML frontmatter that describe
datasets, tables, metrics, APIs, playbooks, and other concepts.

## What's inside

```
okf/
├── SKILL.md                    # the skill: format quick-reference + authoring/validating/consuming workflows
├── references/
│   └── SPEC.md                 # full OKF v0.1 spec (reproduced from GoogleCloudPlatform/knowledge-catalog)
└── scripts/
    └── validate_okf.py         # stdlib-only conformance validator (exit 0 = conformant)
```

## Install

### Claude Code

Copy (or symlink) the `okf/` folder into your skills directory:

```sh
# personal (all projects)
cp -r okf ~/.claude/skills/okf

# or project-scoped
cp -r okf <project>/.claude/skills/okf
```

Claude Code picks it up automatically; it triggers on OKF / knowledge-bundle
tasks, or invoke it explicitly with `/okf`.

### Codex CLI

Codex uses the same SKILL.md format:

```sh
cp -r okf ~/.codex/skills/okf
```

## Validator

```sh
python okf/scripts/validate_okf.py <bundle-dir> [--strict]
```

Checks v0.1 conformance (parseable frontmatter, non-empty `type`, reserved-file
structure) as errors, and soft guidance (broken cross-links, missing
descriptions/indexes) as warnings. `--strict` promotes warnings to errors.
Verified against the three reference bundles shipped in the upstream repo
(ga4, stackoverflow, crypto_bitcoin) — all pass with zero errors and warnings.

## License

Apache 2.0. `okf/references/SPEC.md` is reproduced from
[GoogleCloudPlatform/knowledge-catalog](https://github.com/GoogleCloudPlatform/knowledge-catalog)
(Copyright Google LLC, Apache 2.0); everything else in this repo is original.
