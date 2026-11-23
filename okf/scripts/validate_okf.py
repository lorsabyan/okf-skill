#!/usr/bin/env python3
"""Validate a directory tree against the Open Knowledge Format (OKF) v0.3 specification (including legacy bundles).

Errors are conformance violations (§11, exit 1); warnings are
soft-guidance issues the spec says consumers must tolerate (exit 0).

v0.1 bundles remain valid input: legacy `timestamp` and `# Citations` are
reported as migration warnings, never errors.

Usage:
    python3 validate_okf.py <bundle-dir> [--strict]

    --strict    treat warnings as errors
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import unquote

try:
    from okf_markdown import computation_section, footnote_labels, headings, index_sections, link_targets, markdown_lines
    from ruamel.yaml import YAML, YAMLError
    from ruamel.yaml.constructor import SafeConstructor
except ModuleNotFoundError as exc:
    raise SystemExit(f"Install the script dependencies with: {sys.executable} -m pip install -r "
                     f"{Path(__file__).with_name('requirements.txt')}") from exc

RESERVED = {"index.md", "log.md"}
KNOWN_VERSIONS = {"0.1", "0.2", "0.3"}
STATUS_VALUES = {"draft", "stable", "deprecated"}

# Fences may be indented (e.g. inside a numbered list); the closing fence need
# not share the opening indent. An unclosed fence matches nothing, by design.
URI_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


def is_iso_date(value: object) -> bool:
    """A calendar-valid 'YYYY-MM-DD'. Rejects 2026-02-30, which a shape-only
    regex would wave through."""
    try:
        date.fromisoformat(str(value))
    except ValueError:
        return False
    return True


def is_iso_datetime(value: object) -> bool:
    return _timestamp(value) is not None


def _timestamp(value: object) -> datetime | None:
    text = str(value).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2}))?", text):
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        instant = datetime.fromisoformat(text)
    except ValueError:
        return None
    return instant if instant.tzinfo else instant.replace(tzinfo=timezone.utc)


def trust_tier(frontmatter: dict) -> str:
    """Derive the trust tier from verification of the current content (§5.3)."""
    generated = frontmatter.get("generated")
    changed = _timestamp(generated.get("at")) if isinstance(generated, dict) else None
    tier = "unverified"
    for event in _as_list(frontmatter.get("verified")):
        if not isinstance(event, dict) or not event.get("by"):
            continue
        confirmed = _timestamp(event.get("at"))
        if confirmed is None or (generated and (changed is None or confirmed < changed)):
            continue
        if str(event["by"]).startswith("human:"):
            return "human-reviewed"
        tier = "machine-confirmed"
    return tier


def stale_since(frontmatter: dict, today: date) -> date | None:
    """Compare instants, keeping the deadline date used in reports."""
    deadline = _timestamp(frontmatter.get("stale_after"))
    if deadline is None:
        return None
    if isinstance(today, datetime):
        now = today if today.tzinfo else today.replace(tzinfo=timezone.utc)
    else:
        now = datetime.combine(today, time.min, tzinfo=timezone.utc)
    return deadline.date() if now >= deadline else None


class CoreConstructor(SafeConstructor):
    """Keep implicit date-like scalars as strings under the YAML core schema."""


CoreConstructor.add_constructor("tag:yaml.org,2002:timestamp", SafeConstructor.construct_scalar)


def parse_frontmatter(text: str, legacy: bool = False) -> tuple[dict | None, str]:
    lines = [line.rstrip("\r\n") for line in markdown_lines(text)]
    if not lines or lines[0] != "---":
        return None, text
    delimiters = ("---", "...") if legacy else ("---",)
    end = next((i for i, line in enumerate(lines[1:], 1) if line in delimiters), None)
    if end is None:
        return None, text
    body = "\n".join(lines[end + 1:])
    yaml = YAML(typ="safe", pure=True)
    yaml.Constructor = CoreConstructor
    try:
        data = yaml.load("\n".join(lines[1:end]))
    except (YAMLError, ValueError, OverflowError):
        return None, body
    if data is None and all(not line.split("#", 1)[0].strip() for line in lines[1:end]):
        return {}, body
    return (data if isinstance(data, dict) else None), body


def bundle_version(root: Path, *, require_valid_metadata: bool = False) -> str:
    index = root / "index.md"
    if _visible(root, index) and index.is_file():
        text, clean = _read(index)
        fm, _ = parse_frontmatter(text, legacy=True)
        version = str((fm or {}).get("okf_version") or "")
        if require_valid_metadata:
            if not clean:
                raise ValueError(f"{index}: invalid UTF-8")
            if text.startswith(("---\r", "---\n")) or text == "---":
                if version not in ("0.1", "0.2"):
                    fm, _ = parse_frontmatter(text)
                if fm is None:
                    raise ValueError(f"{index}: malformed or unterminated YAML frontmatter")
        return version
    return ""


def concept_type(fm: dict | None) -> str:
    value = (fm or {}).get("type")
    return value.strip() if isinstance(value, str) else ""


# Bundle checks
# --------------------------------------------------------------------------

def _visible(root: Path, path: Path) -> bool:
    if any(part.startswith(".") for part in path.relative_to(root).parts):
        return False
    try:
        relative = path.resolve().relative_to(root.resolve())
        return not any(part.startswith(".") for part in relative.parts)
    except (ValueError, OSError, RuntimeError):
        return False


def list_md_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if _visible(root, p) and p.is_file())


def _read(path: Path) -> tuple[str, bool]:
    """Read as UTF-8, tolerating (and reporting) a BOM-free decode failure.
    utf-8-sig strips a leading BOM so BOM-prefixed docs are not misread as
    lacking frontmatter."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8-sig"), True
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace"), False


def _as_list(value) -> list:
    """§5.2: a bare mapping where a list is expected is a one-element list."""
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _looks_like_path(value: str) -> bool:
    """Distinguish an in-bundle path from a URL or a §5.1 scope descriptor
    ('all queries in BigQuery project X')."""
    if not value or URI_SCHEME_RE.match(value) or re.search(r"\s", value):
        return False
    return value.startswith(("/", "./", "../")) or "/" in value or "." in Path(value).name


class Bundle:
    def __init__(self, root: Path):
        self.root = root
        self.md_files = list_md_files(root)
        self.version = bundle_version(root)
        self.legacy = self.version in ("0.1", "0.2")
        # Case-exact set of every real file, so results do not depend on whether
        # the filesystem happens to be case-insensitive.
        self.files = {
            "/" + p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if _visible(root, p) and p.is_file()
        }
        self.descriptions: dict[str, str] = {}
        self.listing_dirs: set[Path] = set()

    def resolve(self, doc: Path, target: str) -> str | None:
        """Resolve a link/path target to a bundle-absolute path, or None if it
        escapes the bundle."""
        target = unquote(target.partition("#")[0].partition("?")[0])
        rel_dir = doc.parent.relative_to(self.root).as_posix()
        base = f"/{rel_dir}" if rel_dir != "." else ""
        if target.startswith("/"):
            base = ""
        parts: list[str] = []
        for part in f"{base}/{target}".split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if not parts:
                    return None
                parts.pop()
            else:
                parts.append(part)
        return "/" + "/".join(parts)

    def exists(self, path: str | None) -> bool:
        return path is not None and path in self.files


def check_bundle(root: Path, today: date | None = None) -> tuple[list[str], list[str]]:
    errors, warnings, _ = _validate(Bundle(root), today)
    return errors, warnings


def _validate(bundle: Bundle, today: date | None) -> tuple[list[str], list[str], int]:
    root = bundle.root
    count = 0
    errors: list[str] = []
    warnings: list[str] = []
    today = today or datetime.now(timezone.utc)

    # Pass 1: frontmatter, so index drift can compare against descriptions.
    parsed: dict[Path, tuple[dict | None, str, str]] = {}
    for path in bundle.md_files:
        text, clean = _read(path)
        rel = path.relative_to(root).as_posix()
        if not clean:
            warnings.append(f"{rel}: not valid UTF-8 (spec §4); undecodable bytes were replaced")
        fm, body = parse_frontmatter(text, bundle.legacy)
        parsed[path] = (fm, body, text)
        # An index lists local concepts and branches leading to concepts or
        # child indexes. Its own presence does not require an entry.
        if path.name == "index.md" or (path.name not in RESERVED and concept_type(fm)):
            directory = path.parent if path.name == "index.md" else path
            while directory != root and directory.parent not in bundle.listing_dirs:
                directory = directory.parent
                bundle.listing_dirs.add(directory)
        if fm and path.name not in RESERVED:
            desc = fm.get("description")
            if isinstance(desc, str) and desc:
                self_path = "/" + rel
                bundle.descriptions[self_path] = desc

    for path in bundle.md_files:
        fm, body, text = parsed[path]
        rel = path.relative_to(root).as_posix()
        is_root_index = path.name == "index.md" and path.parent == root

        has_block = text.startswith(("---\r", "---\n")) or text == "---"
        if fm is None and has_block:
            errors.append(f"{rel}: unparseable YAML frontmatter block")
            continue
        if path.name in RESERVED:
            if bundle.version and not bundle.legacy and fm is not None and not is_root_index:
                errors.append(f"{rel}: only the root index may have frontmatter")
            _check_reserved(bundle, path, rel, fm, body, text, is_root_index, errors, warnings)
        else:
            if not concept_type(fm):
                issues = errors if bundle.legacy else warnings
                reason = "missing or unparseable YAML frontmatter block" if fm is None else "missing a non-empty string 'type'"
                issues.append(f"{rel}: {reason}")
                continue
            count += 1
            _check_concept(bundle, path, rel, fm, body, warnings, today)

        for target in link_targets(body):
            if URI_SCHEME_RE.match(target) or target.startswith(("#", "//")):
                continue
            target_path = target.partition("#")[0].partition("?")[0]
            if not unquote(target_path).endswith(".md"):
                continue  # directory links and assets
            resolved = bundle.resolve(path, target_path)
            if resolved is not None and not bundle.exists(resolved):
                warnings.append(f"{rel}: link to missing concept '{target}'")

        if fm is not None and path.name not in RESERVED:
            _check_footnotes(rel, fm, body, warnings)

    for directory in sorted({p.parent for p, (fm, _, _) in parsed.items()
                             if p.name not in RESERVED and concept_type(fm)}):
        if not (directory / "index.md").exists():
            label = directory.relative_to(root).as_posix() or "."
            warnings.append(f"{label}/: no index.md (progressive disclosure)")

    return errors, warnings, count


def _check_reserved(bundle, path, rel, fm, body, text, is_root_index, errors, warnings) -> None:
    if path.name == "index.md":
        if fm is not None and not is_root_index and bundle.legacy:
            warnings.append(f"{rel}: frontmatter in index.md is only permitted at the bundle root (for okf_version)")
        if is_root_index and fm:
            extra = sorted(str(k) for k in fm if k != "okf_version")
            if extra and bundle.legacy:
                warnings.append(f"{rel}: root index.md frontmatter should carry only 'okf_version', found {', '.join(extra)}")
            declared = fm.get("okf_version")
            if declared and str(declared) not in KNOWN_VERSIONS:
                warnings.append(f"{rel}: declares okf_version '{declared}'; this validator knows {', '.join(sorted(KNOWN_VERSIONS))}")
        haystack = body if fm is not None else text
        structural = warnings if bundle.legacy else errors
        sections = index_sections(haystack)
        entries = [entry for section in sections for entry in section.entries]
        if not sections:
            structural.append(f"{rel}: index.md has no section heading")
        if path.parent in bundle.listing_dirs and not entries:
            structural.append(f"{rel}: index.md has no '* [Title](url) - description' entries")
        else:
            _check_index_entries(bundle, path, rel, entries, warnings)
    elif path.name == "log.md":
        dates = [title for tag, title in headings(body) if tag == "h2"]
        structural = warnings if bundle.legacy else errors
        if not dates or any(not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or not is_iso_date(d) for d in dates):
            structural.append(f"{rel}: log.md requires valid '## YYYY-MM-DD' date headings")


def _check_index_entries(bundle, path, rel, entries, warnings) -> None:
    """§8: entries SHOULD carry a description drawn from the linked concept.

    Only a *missing* description is flagged. Abridging it is idiomatic — the
    upstream reference bundles all shorten long frontmatter descriptions for
    the index — so comparing the two texts for equality reports style, not
    defects."""
    for entry in entries:
        target = entry.target
        if entry.description.strip() or URI_SCHEME_RE.match(target) or target.startswith("//"):
            continue
        resolved = bundle.resolve(path, target)
        if not resolved or not resolved.endswith(".md"):
            continue
        if bundle.descriptions.get(resolved):
            warnings.append(f"{rel}: entry for '{target}' has no description, though the concept defines one (§8)")


def _check_concept(bundle, path, rel, fm, body, warnings, today) -> None:
    if not fm.get("description"):
        warnings.append(f"{rel}: no 'description' - index generators and previews rely on it")

    # v0.1 -> v0.2 migration nudges (never errors; v0.1 docs stay consumable).
    if fm.get("timestamp") and not fm.get("generated"):
        warnings.append(f"{rel}: legacy v0.1 'timestamp'; v0.2 records this as 'generated: {{ by, at }}' (§5.2)")
    if "Citations" in body and any(title == "Citations" for _, title in headings(body)):
        warnings.append(f"{rel}: legacy v0.1 '# Citations' body list; v0.2 records provenance in 'sources' (§5.1)")

    _check_trust(rel, fm, warnings)
    _check_lifecycle(rel, fm, warnings, today)
    _check_sources(rel, fm, warnings)
    _check_paths(bundle, path, rel, fm, warnings)
    if str(fm.get("type", "")).strip().lower() == "attested computation":
        _check_computation(rel, fm, body, warnings, bundle.legacy)


def _check_datetime(rel, label, value, warnings) -> None:
    if value and not is_iso_datetime(value):
        warnings.append(f"{rel}: '{label}' is not an ISO 8601 datetime, found {value!r}")


def _check_trust(rel, fm, warnings) -> None:
    generated = fm.get("generated")
    if generated not in (None, "", []):
        if not isinstance(generated, dict):
            warnings.append(f"{rel}: 'generated' should be a mapping with 'by' and 'at' (§5.2)")
        else:
            if not generated.get("by"):
                warnings.append(f"{rel}: 'generated.by' is required within 'generated' (§5.2)")
            _check_datetime(rel, "generated.at", generated.get("at"), warnings)

    for n, event in enumerate(_as_list(fm.get("verified"))):
        if not isinstance(event, dict):
            warnings.append(f"{rel}: 'verified[{n}]' should be a mapping with 'by' and 'at' (§5.2)")
            continue
        if not event.get("by"):
            warnings.append(f"{rel}: 'verified[{n}]' has no 'by' actor (§5.2)")
        if not event.get("at"):
            warnings.append(f"{rel}: verified[{n}] has no verification time")
        _check_datetime(rel, f"verified[{n}].at", event.get("at"), warnings)


def _status(fm: dict) -> str:
    value = fm.get("status")
    return "stable" if value in (None, "", []) else str(value)


def _check_lifecycle(rel, fm, warnings, today) -> None:
    status = _status(fm)
    if status not in STATUS_VALUES:
        warnings.append(f"{rel}: 'status' is {status!r}; §5.4 defines {', '.join(sorted(STATUS_VALUES))}")
    stale_after = fm.get("stale_after")
    if stale_after not in (None, "", []) and not is_iso_datetime(stale_after):
        warnings.append(f"{rel}: 'stale_after' should be an absolute ISO 8601 timestamp (§5.5), found {stale_after!r}")
    else:
        deadline = stale_since(fm, today)
        if deadline:
            warnings.append(f"{rel}: stale since {deadline.isoformat()} (§5.5); content needs review")


def _check_sources(rel, fm, warnings) -> None:
    for n, entry in enumerate(_as_list(fm.get("sources"))):
        if not isinstance(entry, dict):
            warnings.append(f"{rel}: 'sources[{n}]' should be a mapping (§5.1)")
            continue
        if not entry.get("resource"):
            warnings.append(f"{rel}: 'sources[{n}]' has no 'resource', which is required within an entry (§5.1)")
        last_modified = entry.get("last_modified")
        if last_modified and not is_iso_datetime(last_modified):
            warnings.append(f"{rel}: 'sources[{n}].last_modified' should be an ISO 8601 timestamp (§5.1), found {last_modified!r}")
        usage_count = entry.get("usage_count")
        if usage_count is not None and not re.fullmatch(r"\d+", str(usage_count)):
            warnings.append(f"{rel}: 'sources[{n}].usage_count' should be a number (§5.1), found {usage_count!r}")

    window = fm.get("usage_window")
    if window not in (None, "", []) and not (isinstance(window, dict) and window.get("from") and window.get("to")):
        warnings.append(f"{rel}: 'usage_window' should be a mapping with 'from' and 'to' timestamps (§5.1)")
    elif isinstance(window, dict):
        for edge in ("from", "to"):
            value = window.get(edge)
            if value and not is_iso_datetime(value):
                warnings.append(f"{rel}: 'usage_window.{edge}' should be an ISO 8601 timestamp (§5.1), found {value!r}")


def _check_paths(bundle, path, rel, fm, warnings) -> None:
    """§6.2 path-valued fields. A bare relative path is accepted against either
    the document's directory or the bundle root, since both are in use."""
    candidates: list[tuple[str, object]] = [("resource", fm.get("resource"))]
    for n, entry in enumerate(_as_list(fm.get("sources"))):
        if isinstance(entry, dict):
            candidates.append((f"sources[{n}].resource", entry.get("resource")))
    candidates.append(("computation", fm.get("computation")))
    if fm.get("status") == "deprecated":
        candidates.append(("superseded_by", fm.get("superseded_by")))
    for field in ("executor", "attester"):
        block = fm.get(field)
        if isinstance(block, dict):
            candidates.append((f"{field}.resource", block.get("resource")))

    for label, value in candidates:
        if not isinstance(value, str) or not value or URI_SCHEME_RE.match(value):
            continue
        if label.startswith("sources[") and not _looks_like_path(value):
            continue
        target = value.split("#")[0]
        resolved = bundle.resolve(path, target)
        if resolved is None or target.startswith("//") or bundle.exists(resolved):
            continue
        if bundle.version in ("", "0.1", "0.2") and bundle.exists(bundle.resolve(bundle.root / "index.md", target)):
            continue
        warnings.append(f"{rel}: '{label}' points at missing in-bundle path '{value}' (§6.2)")


def _check_computation(rel, fm, body, warnings, legacy) -> None:
    if not fm.get("runtime"):
        warnings.append(f"{rel}: 'runtime' is required for an Attested Computation (§10.2)")
    for n, param in enumerate(_as_list(fm.get("parameters"))):
        if not isinstance(param, dict):
            warnings.append(f"{rel}: 'parameters[{n}]' should be a mapping of {{ name, type, required }} (§10.2)")
        elif not param.get("name"):
            warnings.append(f"{rel}: 'parameters[{n}]' has no 'name' (§10.2)")
        elif not legacy and not param.get("type"):
            warnings.append(f"{rel}: 'parameters[{n}]' has no 'type' (§10.2)")
    if not fm.get("computation"):
        has_heading, has_fence = computation_section(body)
        if not has_heading:
            warnings.append(f"{rel}: no 'computation' path and no '# Computation' body section (§10.3)")
        elif not legacy and not has_fence:
            warnings.append(f"{rel}: missing fenced computation in the Computation section (§10.3)")
    executor = fm.get("executor")
    if isinstance(executor, dict) and not executor.get("resource"):
        warnings.append(f"{rel}: 'executor' has no 'resource' naming how to run the computation (§10.2)")


def _check_footnotes(rel, fm, body, warnings) -> None:
    """§5.1: a footnote label attributing a claim joins to a sources[].id.
    Only a label with neither a definition nor a matching id is dangling."""
    ids = {
        str(entry["id"])
        for entry in _as_list(fm.get("sources"))
        if isinstance(entry, dict) and entry.get("id")
    }
    if "[^" not in body:
        return
    uses, defined = footnote_labels(body)
    for label in dict.fromkeys(uses):
        if label not in ids and label not in defined:
            warnings.append(f"{rel}: footnote '[^{label}]' matches no 'sources[].id' and has no definition (§5.1)")


def collect_report(root: Path, today: date | None = None) -> list[dict]:
    """Per-concept trust and lifecycle signals, for --report."""
    today = today or datetime.now(timezone.utc)
    rows: list[dict] = []
    legacy = bundle_version(root) in ("0.1", "0.2")
    for path in list_md_files(root):
        if path.name in RESERVED:
            continue
        text, _ = _read(path)
        fm, _body = parse_frontmatter(text, legacy)
        if not concept_type(fm):
            continue
        deadline = stale_since(fm, today)
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "type": str(fm.get("type") or "-"),
            "status": _status(fm),
            "tier": trust_tier(fm),
            "stale": deadline,
            "invalid_deadline": fm.get("stale_after") not in (None, "", []) and not is_iso_datetime(fm["stale_after"]),
        })
    return rows


def print_report(rows: list[dict]) -> None:
    if not rows:
        print("No concept docs found.")
        return
    width_path = max(len(r["path"]) for r in rows)
    width_type = max(len(r["type"]) for r in rows)
    width_status = max(len(r["status"]) for r in rows)
    print()
    for row in sorted(rows, key=lambda r: r["path"]):
        freshness = f"STALE (since {row['stale'].isoformat()})" if row["stale"] else "fresh"
        if row["invalid_deadline"]:
            freshness = "unknown (invalid stale_after)"
        print(
            f"{row['path']:<{width_path}}  {row['type']:<{width_type}}  "
            f"{row['status']:<{width_status}}  {row['tier']:<17}  {freshness}"
        )

    tiers = {"human-reviewed": 0, "machine-confirmed": 0, "unverified": 0}
    for row in rows:
        tiers[row["tier"]] += 1
    stale = sum(1 for r in rows if r["stale"])
    deprecated = sum(1 for r in rows if r["status"] == "deprecated")
    summary = ", ".join(f"{count} {tier}" for tier, count in tiers.items() if count)
    print(f"\n{len(rows)} concepts: {summary} | {stale} stale | {deprecated} deprecated")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--report", action="store_true",
                    help="print per-concept trust tier and staleness (inspection only)")
    ap.add_argument("--today", metavar="YYYY-MM-DD",
                    help="evaluate staleness at midnight UTC on this date")
    args = ap.parse_args()

    if not args.bundle.is_dir():
        print(f"error: {args.bundle} is not a directory", file=sys.stderr)
        return 2

    today = None
    if args.today:
        try:
            today = date.fromisoformat(args.today)
        except ValueError:
            print(f"error: --today must be YYYY-MM-DD, got {args.today!r}", file=sys.stderr)
            return 2

    if args.report:
        print_report(collect_report(args.bundle, today))
        return 0

    bundle = Bundle(args.bundle)
    errors, warnings, n_concepts = _validate(bundle, today)
    for msg in errors:
        print(f"ERROR   {msg}")
    for msg in warnings:
        print(f"warning {msg}")

    print(f"\n{args.bundle}: {n_concepts} concept doc(s), {len(errors)} error(s), {len(warnings)} warning(s)")
    if errors or (args.strict and warnings):
        return 1
    version = bundle.version
    if version and version not in KNOWN_VERSIONS:
        print(f"Best-effort checks passed for unknown OKF version {version}.")
    else:
        print(f"Bundle is conformant with OKF v{version or '0.3'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
