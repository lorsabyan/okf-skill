"""The benchmark corpus: bundles with labeled, deliberate properties.

Two halves, and the second is the one that matters.

`DEFECTS` are bundles containing exactly one thing a helpful validator should
report. Detecting them is the easy half — a validator that flags everything
scores 100%.

`CLEAN` are bundles that are entirely valid but contain a shape a naive
implementation tends to trip over: a UTF-8 BOM, YAML line folding, a fence
indented inside a list item, a bare `verified` mapping, a scope descriptor
where a path would normally sit. Reporting anything here is a false positive,
and false positives are what get a validator ignored.

Every case is built in code rather than committed as files. Several are
whitespace- and encoding-sensitive, and an editor or a git filter would
normalize them away in a checked-in fixture — silently turning the hardest
cases into trivial ones.
"""

from __future__ import annotations

GEN = "generated: { by: reference_agent/bench, at: 2026-07-01T00:00:00Z }"


def base(**overrides: str) -> dict:
    """A bundle that is unremarkable in every dimension.

    Two concepts linking to each other, both dated and described, with an index.

    This baseline matters more than it looks. An earlier version of this corpus
    used a single undated concept, so every bundle was *also* an orphan and
    *also* undated. Validators that check for those — okf-reader does, this repo's
    does not — reported on every case, which inflated detection (a defect could be
    "found" via unrelated noise) and made all ten clean bundles look like false
    positives. Seed exactly one property; hold everything else quiet.
    """
    files = {
        "index.md": "# Metric\n\n* [A](a.md) - First metric.\n* [B](b.md) - Second metric.\n",
        "a.md": concept(),
        "b.md": f"---\ntype: Metric\ndescription: Second metric.\n{GEN}\n---\n\nSee [a](a.md).\n",
    }
    files.update(overrides)
    return files


def concept(body: str = "See [b](b.md).\n", **frontmatter) -> str:
    """Concept `a`, dated and linked, with frontmatter keys added or replaced.

    Pass `description=None` to drop a default key.
    """
    lines = ["type: Metric", "description: First metric.", GEN]
    for key, value in frontmatter.items():
        lines = [ln for ln in lines if not ln.startswith(f"{key}:") and not (key == "generated" and ln == GEN)]
        if value is not None:
            lines.append(f"{key}: {value}" if not str(value).startswith("\n") else f"{key}:{value}")
    return "---\n" + "\n".join(lines) + "\n---\n\n" + body


# --------------------------------------------------------------------------
# Half 1 — a defect is present. Not reporting it is a miss.
# --------------------------------------------------------------------------

DEFECTS: dict[str, dict] = {
    # --- §11 conformance -----------------------------------------------
    "no-frontmatter": {
        "spec": "§11.1",
        "why": "every non-reserved .md file needs a parseable frontmatter block",
        "files": base(**{"a.md": "Just a body, no frontmatter at all.\n\nSee [b](b.md).\n"}),
    },
    "unparseable-frontmatter": {
        "spec": "§11.1",
        "why": "a frontmatter line that is neither a mapping nor a sequence item",
        "files": base(**{"a.md": f"---\ntype: Metric\ndescription: First metric.\n{GEN}\nthis is not a mapping\n---\n\nSee [b](b.md).\n"}),
    },
    "missing-type": {
        "spec": "§11.2",
        "why": "type is the only always-required key",
        "files": base(**{"a.md": concept(type=None, title="No type here")}),
    },
    "empty-type": {
        "spec": "§11.2",
        "why": "a blank type is as absent as a missing one",
        "files": base(**{"a.md": concept(type='""')}),
    },
    # --- soft guidance --------------------------------------------------
    "broken-link": {
        "spec": "§6.1",
        "why": "a link to a concept that is not in the bundle",
        "files": base(**{"a.md": concept(body="See [gone](gone.md).\n")}),
    },
    "case-mismatched-link": {
        "spec": "§6.1",
        "why": "resolves on a case-insensitive volume, breaks on a case-sensitive one",
        "files": base(**{"a.md": concept(body="See [b](B.md).\n")}),
    },
    "missing-description": {
        "spec": "§4.1",
        "why": "index generators and previews rely on it",
        "files": base(**{"a.md": concept(description=None)}),
    },
    "missing-index": {
        "spec": "§8",
        "why": "no index.md, so progressive disclosure is unavailable",
        "files": {k: v for k, v in base().items() if k != "index.md"},
    },
    "generated-without-by": {
        "spec": "§5.2",
        "why": "by is required within generated",
        "files": base(**{"a.md": concept(generated="{ at: 2026-07-01T00:00:00Z }")}),
    },
    "impossible-date": {
        "spec": "§5.2",
        "why": "2026-02-30 passes a shape-only regex but is not a date",
        "files": base(**{"a.md": concept(generated="{ by: human:x, at: 2026-02-30 }")}),
    },
    "unknown-status": {
        "spec": "§5.4",
        "why": "status outside draft | stable | deprecated",
        "files": base(**{"a.md": concept(status="retired")}),
    },
    "past-stale-after": {
        "spec": "§5.5",
        "why": "the concept is stale as of the evaluation date",
        "files": base(**{"a.md": concept(stale_after="2020-01-01")}),
    },
    "source-without-resource": {
        "spec": "§5.1",
        "why": "resource is required within a sources entry",
        "files": base(**{"a.md": concept(sources="\n  - id: x\n    title: No resource here")}),
    },
    "dangling-footnote": {
        "spec": "§5.1",
        "why": "a footnote label joining to no sources id and having no definition",
        "files": base(**{"a.md": concept(body="A claim.[^nope] See [b](b.md).\n")}),
    },
    "computation-without-runtime": {
        "spec": "§10.2",
        "why": "runtime is required for an Attested Computation",
        "files": base(**{"a.md": concept(type="Attested Computation", body="See [b](b.md).\n\n# Computation\n\n    SELECT 1\n")}),
    },
    "computation-without-computation": {
        "spec": "§10.3",
        "why": "neither a computation path nor a # Computation body section",
        "files": base(**{"a.md": concept(type="Attested Computation", runtime="bigquery")}),
    },
    "dead-path-field": {
        "spec": "§6.2",
        "why": "a path-valued frontmatter field pointing at a file not in the bundle",
        "files": base(**{"a.md": concept(resource="tables/nope.md")}),
    },
    "legacy-timestamp": {
        "spec": "§13",
        "why": "v0.1 timestamp; v0.2 records this as generated.at",
        "files": base(**{"a.md": concept(generated=None, timestamp="2026-07-01T00:00:00Z")}),
    },
    "legacy-citations": {
        "spec": "§13",
        "why": "v0.1 # Citations body list; v0.2 records provenance in sources",
        "files": base(**{"a.md": concept(body="See [b](b.md).\n\n# Citations\n- https://example.com\n")}),
    },
}


# --------------------------------------------------------------------------
# Half 2 — nothing is wrong. Reporting anything is a false positive.
# --------------------------------------------------------------------------

CLEAN: dict[str, dict] = {
    "bom-prefixed": {
        "spec": "§4",
        "why": "a UTF-8 BOM is legal; a naive reader sees no frontmatter delimiter",
        "encodings": {"a.md": "utf-8-sig"},
        "files": base(),
    },
    "indented-fence": {
        "spec": "§4.2",
        "why": "a fence inside a numbered list; its contents are code, not links",
        "files": base(**{"a.md": concept(body="See [b](b.md).\n\n1. Run this:\n\n   ```sql\n   SELECT * FROM [x](does-not-exist.md);\n   ```\n")}),
    },
    "indented-index-entries": {
        "spec": "§8",
        "why": "entries indented and bulleted with '+' are still entries",
        "files": base(**{"index.md": "# Metric\n\n  * [A](a.md) - First metric.\n  + [B](b.md) - Second metric.\n"}),
    },
    "wrapped-scalar": {
        "spec": "§4.1",
        "why": "YAML line folding; truncating it silently loses half the description",
        "files": base(**{"a.md": f"---\ntype: Metric\ndescription: A description that wraps across\n  two physical lines.\n{GEN}\n---\n\nSee [b](b.md).\n"}),
    },
    "bare-verified-mapping": {
        "spec": "§5.2",
        "why": "a single verifier MAY be a bare mapping; consumers MUST read it as a 1-element list",
        "files": base(**{"a.md": concept(verified="{ by: human:x, at: 2026-06-25T09:00:00Z }")}),
    },
    "flush-left-sequence": {
        "spec": "§4.1",
        "why": "the sequence style upstream's serializer actually emits",
        "files": base(**{"a.md": concept(tags="\n- one\n- two", sources="\n- id: s\n  resource: https://example.com")}),
    },
    "scope-descriptor-source": {
        "spec": "§5.1",
        "why": "a sources resource may be a population descriptor, not a path",
        "files": base(**{"a.md": concept(sources="\n  - id: s\n    resource: all queries in BigQuery project X")}),
    },
    "unknown-type-and-keys": {
        "spec": "§11",
        "why": "consumers MUST NOT reject unknown types or unrecognized keys",
        "files": base(**{"a.md": concept(type="Something Nobody Registered", vendor_specific_key="yes")}),
    },
    "self-defined-footnote": {
        "spec": "§5.1",
        "why": "a numeric footnote that defines itself joins to no source, and need not",
        "files": base(**{"a.md": concept(body="A claim.[^1] See [b](b.md).\n\n[^1]: Verified against an external doc.\n")}),
    },
    "future-stale-after": {
        "spec": "§5.5",
        "why": "stale_after in the future is not stale",
        "files": base(**{"a.md": concept(stale_after="2099-01-01")}),
    },
}
