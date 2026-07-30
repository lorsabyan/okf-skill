# Does the validator catch what it should — and stay quiet otherwise?

A validator is easy to score well on one axis and useless on both. Flag
everything and you catch every defect. Flag nothing and you never cry wolf.
This measures both, on a corpus where every case is labeled with the one
property it carries.

## Method

**One baseline, one seeded property.** Every case starts from the same
unremarkable bundle: two concepts that link to each other, both dated, both
described, with an index. Each case then changes exactly one thing. The baseline
itself is verified silent under every validator before the run, so any report is
attributable to the seeded property and nothing else.

That control is not cosmetic. The first version of this corpus used a single
undated concept per case, which made every bundle *also* an orphan and *also*
undated. Validators that check for those reported on every case — inflating
detection, because a defect could be "found" via unrelated noise, and scoring all
ten clean bundles as false positives. The first run produced a confident,
meaningless `0/10`. Fixing the baseline changed one validator's clean score from
0/10 to 9/10.

**Two scores, both required.**

- **detection** — of the 19 defect bundles, how many produce any report.
- **clean pass** — of the 10 clean bundles, how many produce none.

**Deterministic.** No model, no grader, no sampling. `--today` is pinned to
`2026-07-30` so a case built around a date does not change verdict with the
calendar. Re-running gives byte-identical output.

## What the corpus contains

**Defects** (19) — one per case, spanning §11 conformance, cross-linking,
the provenance/trust/lifecycle families, Attested Computations, and the two v0.1
conventions v0.2 retired.

**Clean** (10) — entirely valid bundles carrying a shape naive implementations
trip over: a UTF-8 BOM, YAML line folding, a fence indented inside a list item,
indented and `+`-bulleted index entries, a bare `verified` mapping, a flush-left
sequence, a scope descriptor where a path usually sits, an unknown type with
unknown keys, a self-defining numeric footnote, a future `stale_after`.

The clean half is the point. Every case in it is a real defect that shipped in
this repo's validator at some stage, or a spec allowance an implementation is
likely to miss.

## Limits, stated plainly

- **Two implementations, both mine.** `okf-skill` (this repo, Python) and
  [`okf-reader`](https://github.com/lorsabyan/okf-reader)'s `@okf/core` CLI
  (TypeScript, written separately). Independent implementations of one spec are
  a genuine cross-check, but they are not an ecosystem survey. Other OKF tools
  exist and are not measured here; a PR adding one is welcome.
- **Detection counts *a* report, not the *right* report.** A validator that
  flags the seeded case for an unrelated reason scores a hit. The single-property
  baseline makes that unlikely, not impossible.
- **Not a fairness comparison.** `okf-reader` is a *reader*, and a lower
  detection score there is a scope decision, not a defect — it implements the
  checks its UI needs. The number worth reading across tools is **clean pass**,
  which is about correctness rather than coverage.
- **29 cases is small.** It covers the spec's families, not every clause.

## Running it

```sh
python3 benchmark/run.py                    # this repo's validator only
python3 benchmark/run.py --markdown         # emit the results.md tables
OKF_READER=/path/to/okf-reader python3 benchmark/run.py   # add the TS implementation
```

Validators are discovered, not assumed: `okf-reader` is skipped unless
`OKF_READER` points at a checkout and `bun` is on `PATH`.

Results: [results.md](results.md). Corpus: [corpus.py](corpus.py).
