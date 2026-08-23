#!/usr/bin/env python3
"""Validate a directory tree against the Open Knowledge Format (OKF) v0.2 spec.

Stdlib-only. Errors are v0.2 conformance violations (§11, exit 1); warnings are
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
from datetime import date, datetime
from pathlib import Path

RESERVED = {"index.md", "log.md"}
KNOWN_VERSIONS = {"0.1", "0.2"}
STATUS_VALUES = {"draft", "stable", "deprecated"}

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
DATE_HEADING_RE = re.compile(r"^## \d{4}-\d{2}-\d{2}\s*$")
# Fences may be indented (e.g. inside a numbered list); the closing fence need
# not share the opening indent. An unclosed fence matches nothing, by design.
FENCED_BLOCK_RE = re.compile(r"^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1`*[ \t]*$", re.M | re.S)
INDEX_ENTRY_RE = re.compile(r"^\s*[*+-]\s+\[", re.M)
# "* [Title](target) - description", the §8 index entry shape.
INDEX_PARSE_RE = re.compile(r"^\s*[*+-]\s+\[([^\]]*)\]\(([^)\s]+)\)\s*[-–—:]?\s*(.*)$", re.M)
FOOTNOTE_USE_RE = re.compile(r"(?<!\])\[\^([^\]\s]+)\](?!:)")
FOOTNOTE_DEF_RE = re.compile(r"^\s*\[\^([^\]\s]+)\]:", re.M)
CITATIONS_HEADING_RE = re.compile(r"^#{1,6}\s+Citations\s*$", re.M)
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
    """A calendar-valid ISO 8601 timestamp; a bare date is accepted.

    §5 now asks for a datetime with an explicit offset ('2026-06-30T14:00:00Z'),
    tightened upstream in open-knowledge-format@ad30107 without an `okf_version`
    bump. Bare 'YYYY-MM-DD' stays acceptable rather than becoming a warning:
    bundles written against the earlier v0.2 text declare the same version and
    are not retroactively non-conformant.

    'Z' is normalized because fromisoformat only accepts it from Python 3.11."""
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return is_iso_date(value)
    return True


def trust_tier(frontmatter: dict) -> str:
    """A concept's trust tier, derived from `verified` (SPEC §5.3).

    No `verified` key => unverified; non-`human:` actors only =>
    machine-confirmed; any `human:` actor => human-reviewed."""
    events = _as_list(frontmatter.get("verified"))
    if not events:
        return "unverified"
    for event in events:
        if isinstance(event, dict) and str(event.get("by") or "").startswith("human:"):
            return "human-reviewed"
    return "machine-confirmed"


def stale_since(frontmatter: dict, today: date) -> date | None:
    """The `stale_after` date when the concept is stale on `today`, else None
    (SPEC §5.5: stale when today >= stale_after).

    `stale_after` carries a time component since ad30107, but the comparison
    stays at day granularity to match `--today`. A deadline later the same day
    therefore reads as stale from midnight — erring toward reporting staleness,
    which is the safe direction for a warning."""
    raw = frontmatter.get("stale_after")
    if not raw:
        return None
    try:
        deadline = date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None
    return deadline if today >= deadline else None


# --------------------------------------------------------------------------
# Minimal YAML subset parser
#
# OKF v0.2 frontmatter is genuinely nested: block maps, block sequences of
# either flow maps or block maps, inline flow maps and lists, and values that
# themselves contain colons (`at: 2026-06-30T14:00:00Z`, `by: human:ahormati`).
# A line-splitting parser cannot read it, so this handles the subset the spec
# uses. Not a general YAML implementation: anchors, multi-document streams and
# complex keys are out of scope.
# --------------------------------------------------------------------------

def _strip_comment(s: str) -> str:
    """Drop a trailing YAML comment. '#' only starts one at line start or after
    whitespace, and never inside a quoted scalar (so URLs keep their fragments)."""
    in_single = in_double = False
    for i, ch in enumerate(s):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _split_kv(s: str) -> tuple[str | None, str]:
    """Split 'key: value' at the first colon that terminates the key — i.e. one
    followed by whitespace or end of line, outside quotes. This keeps
    'at: 2026-06-30T14:00:00Z' and 'by: human:ahormati' intact."""
    in_single = in_double = False
    for i, ch in enumerate(s):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ":" and not in_single and not in_double:
            if i + 1 >= len(s) or s[i + 1] in " \t":
                return _unquote(s[:i]), s[i + 1:].strip()
    return None, ""


def _split_flow(s: str) -> list[str]:
    """Split a flow collection's interior on top-level commas."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    in_single = in_double = False
    for ch in s:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if not in_single and not in_double:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(buf))
                buf = []
                continue
        buf.append(ch)
    if "".join(buf).strip():
        parts.append("".join(buf))
    return parts


def _parse_flow(s: str):
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        return [_parse_flow(p) for p in _split_flow(s[1:-1])]
    if s.startswith("{") and s.endswith("}"):
        out: dict = {}
        for part in _split_flow(s[1:-1]):
            key, val = _split_kv(part.strip())
            if key is None:
                continue
            out[key] = _parse_flow(val) if val[:1] in ("[", "{") else _unquote(val)
        return out
    return _unquote(s)


def _parse_block(items: list[list], i: int, indent: int) -> tuple[object, int, bool]:
    """Parse the block starting at items[i] with the given indent.
    items entries are mutable [indent, text] pairs. Returns (value, next_i, ok)."""
    ok = True
    if i < len(items) and items[i][0] == indent and re.match(r"-(\s|$)", items[i][1]):
        seq: list = []
        while i < len(items) and items[i][0] == indent and re.match(r"-(\s|$)", items[i][1]):
            text = items[i][1]
            pad = len(text) - len(text[1:].lstrip(" ")) if len(text) > 1 else 1
            content = text[pad:]
            content_indent = indent + pad
            if not content:
                i += 1
                if i < len(items) and items[i][0] > indent:
                    val, i, sub_ok = _parse_block(items, i, items[i][0])
                    ok = ok and sub_ok
                else:
                    val = None
                seq.append(val)
            elif content[0] in "[{":
                seq.append(_parse_flow(content))
                i += 1
            elif _split_kv(content)[0] is not None:
                # Block mapping whose first key sits on the dash line. Re-anchor
                # that line at the key's own column, then parse it as a mapping.
                items[i] = [content_indent, content]
                val, i, sub_ok = _parse_block(items, i, content_indent)
                ok = ok and sub_ok
                seq.append(val)
            else:
                seq.append(_unquote(content))
                i += 1
        return seq, i, ok

    mapping: dict = {}
    while i < len(items) and items[i][0] == indent:
        text = items[i][1]
        if re.match(r"-(\s|$)", text):
            break
        key, val = _split_kv(text)
        if key is None:
            i += 1
            ok = False  # a line that is neither 'key: value' nor a sequence item
            continue
        i += 1
        if val == "":
            if i < len(items) and items[i][0] > indent:
                parsed, i, sub_ok = _parse_block(items, i, items[i][0])
                ok = ok and sub_ok
            elif i < len(items) and items[i][0] == indent and re.match(r"-(\s|$)", items[i][1]):
                parsed, i, sub_ok = _parse_block(items, i, indent)  # flush-left sequence
                ok = ok and sub_ok
            else:
                parsed = None
        elif re.fullmatch(r"[|>][+-]?\d*", val):
            folded = val[0] == ">"
            buf: list[str] = []
            while i < len(items) and items[i][0] > indent:
                buf.append(items[i][1])
                i += 1
            parsed = (" " if folded else "\n").join(buf)
        elif val[0] in "[{":
            parsed = _parse_flow(val)
        else:
            # A plain scalar may wrap onto following, more-indented lines
            # (YAML line folding). A non-empty value cannot also have nested
            # children, so every deeper line here is a continuation.
            continuation: list[str] = []
            while i < len(items) and items[i][0] > indent:
                continuation.append(items[i][1])
                i += 1
            parsed = _unquote(" ".join([val, *continuation]) if continuation else val)
        mapping[key] = parsed
    return mapping, i, ok


def parse_frontmatter(text: str) -> tuple[dict | None, str]:
    """Return (frontmatter mapping or None if absent/unparseable, body)."""
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return None, text
    try:
        end = next(i for i, ln in enumerate(lines[1:], 1) if ln.strip() in ("---", "..."))
    except StopIteration:
        return None, text
    body = "\n".join(lines[end + 1:])

    items: list[list] = []
    for raw in lines[1:end]:
        stripped = _strip_comment(raw.expandtabs(4))
        if not stripped.strip():
            continue
        items.append([len(stripped) - len(stripped.lstrip(" ")), stripped.strip()])
    if not items:
        return {}, body

    data, _, ok = _parse_block(items, 0, items[0][0])
    if not ok or not isinstance(data, dict):
        return None, body
    return data, body


# --------------------------------------------------------------------------
# Bundle checks
# --------------------------------------------------------------------------

def _visible(root: Path, path: Path) -> bool:
    return not any(part.startswith(".") for part in path.relative_to(root).parts)


def list_md_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if _visible(root, p))


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
    if value is None:
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
        self.concepts = [p for p in self.md_files if p.name not in RESERVED]
        # Case-exact set of every real file, so results do not depend on whether
        # the filesystem happens to be case-insensitive.
        self.files = {
            "/" + p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and _visible(root, p)
        }
        self.descriptions: dict[str, str] = {}

    def resolve(self, doc: Path, target: str) -> str | None:
        """Resolve a link/path target to a bundle-absolute path, or None if it
        escapes the bundle."""
        if target.startswith("/"):
            return target
        rel_dir = doc.parent.relative_to(self.root).as_posix()
        base = f"/{rel_dir}" if rel_dir != "." else ""
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
    errors: list[str] = []
    warnings: list[str] = []
    today = today or date.today()
    bundle = Bundle(root)

    # Pass 1: frontmatter, so index drift can compare against descriptions.
    parsed: dict[Path, tuple[dict | None, str, str]] = {}
    for path in bundle.md_files:
        text, clean = _read(path)
        rel = path.relative_to(root).as_posix()
        if not clean:
            warnings.append(f"{rel}: not valid UTF-8 (spec §4); undecodable bytes were replaced")
        fm, body = parse_frontmatter(text)
        parsed[path] = (fm, body, text)
        if fm and path.name not in RESERVED:
            desc = fm.get("description")
            if isinstance(desc, str) and desc:
                self_path = "/" + rel
                bundle.descriptions[self_path] = desc

    for path in bundle.md_files:
        fm, body, text = parsed[path]
        rel = path.relative_to(root).as_posix()
        is_root_index = path.name == "index.md" and path.parent == root

        if path.name in RESERVED:
            _check_reserved(bundle, path, rel, fm, body, text, is_root_index, warnings)
        else:
            if fm is None:
                errors.append(f"{rel}: missing or unparseable YAML frontmatter block")
                continue
            if not fm.get("type"):
                errors.append(f"{rel}: frontmatter is missing a non-empty 'type' field")
            _check_concept(bundle, path, rel, fm, body, warnings, today)

        # Fenced code often quotes example markdown; don't link-check it.
        prose = FENCED_BLOCK_RE.sub("", text)
        for target in LINK_RE.findall(prose):
            if URI_SCHEME_RE.match(target) or target.startswith("#"):
                continue
            target_path = target.split("#")[0]
            if not target_path.endswith(".md"):
                continue  # directory links and assets
            resolved = bundle.resolve(path, target_path)
            if resolved is not None and not bundle.exists(resolved):
                warnings.append(f"{rel}: link to missing concept '{target}'")

        if fm is not None and path.name not in RESERVED:
            _check_footnotes(rel, fm, prose, warnings)

    for directory in sorted({p.parent for p in bundle.md_files}):
        if not (directory / "index.md").exists():
            label = directory.relative_to(root).as_posix() or "."
            warnings.append(f"{label}/: no index.md (progressive disclosure)")

    return errors, warnings


def _check_reserved(bundle, path, rel, fm, body, text, is_root_index, warnings) -> None:
    if path.name == "index.md":
        if fm is not None and not is_root_index:
            warnings.append(f"{rel}: frontmatter in index.md is only permitted at the bundle root (for okf_version)")
        if is_root_index and fm:
            extra = sorted(k for k in fm if k != "okf_version")
            if extra:
                warnings.append(f"{rel}: root index.md frontmatter should carry only 'okf_version', found {', '.join(extra)}")
            declared = fm.get("okf_version")
            if declared and str(declared) not in KNOWN_VERSIONS:
                warnings.append(f"{rel}: declares okf_version '{declared}'; this validator knows {', '.join(sorted(KNOWN_VERSIONS))}")
        haystack = body if fm is not None else text
        if not INDEX_ENTRY_RE.search(haystack):
            warnings.append(f"{rel}: index.md has no '* [Title](url) - description' entries")
        else:
            _check_index_entries(bundle, path, rel, haystack, warnings)
    elif path.name == "log.md":
        if not any(DATE_HEADING_RE.match(ln) for ln in text.splitlines()):
            warnings.append(f"{rel}: log.md has no '## YYYY-MM-DD' date headings")


def _check_index_entries(bundle, path, rel, haystack, warnings) -> None:
    """§8: entries SHOULD carry a description drawn from the linked concept.

    Only a *missing* description is flagged. Abridging it is idiomatic — the
    upstream reference bundles all shorten long frontmatter descriptions for
    the index — so comparing the two texts for equality reports style, not
    defects."""
    for _title, target, entry_desc in INDEX_PARSE_RE.findall(haystack):
        if entry_desc.strip() or URI_SCHEME_RE.match(target) or not target.endswith(".md"):
            continue
        resolved = bundle.resolve(path, target.split("#")[0])
        if bundle.descriptions.get(resolved or ""):
            warnings.append(f"{rel}: entry for '{target}' has no description, though the concept defines one (§8)")


def _check_concept(bundle, path, rel, fm, body, warnings, today) -> None:
    if not fm.get("description"):
        warnings.append(f"{rel}: no 'description' - index generators and previews rely on it")

    # v0.1 -> v0.2 migration nudges (never errors; v0.1 docs stay consumable).
    if fm.get("timestamp") and not fm.get("generated"):
        warnings.append(f"{rel}: legacy v0.1 'timestamp'; v0.2 records this as 'generated: {{ by, at }}' (§5.2)")
    if CITATIONS_HEADING_RE.search(body):
        warnings.append(f"{rel}: legacy v0.1 '# Citations' body list; v0.2 records provenance in 'sources' (§5.1)")

    _check_trust(rel, fm, warnings)
    _check_lifecycle(rel, fm, warnings, today)
    _check_sources(rel, fm, warnings)
    _check_paths(bundle, path, rel, fm, warnings)
    if str(fm.get("type", "")).strip().lower() == "attested computation":
        _check_computation(rel, fm, body, warnings)


def _check_datetime(rel, label, value, warnings) -> None:
    if value and not is_iso_datetime(value):
        warnings.append(f"{rel}: '{label}' is not an ISO 8601 datetime, found {value!r}")


def _check_trust(rel, fm, warnings) -> None:
    generated = fm.get("generated")
    if generated is not None:
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
        _check_datetime(rel, f"verified[{n}].at", event.get("at"), warnings)


def _check_lifecycle(rel, fm, warnings, today) -> None:
    status = fm.get("status")
    if status and str(status).strip().lower() not in STATUS_VALUES:
        warnings.append(f"{rel}: 'status' is {status!r}; §5.4 defines {', '.join(sorted(STATUS_VALUES))}")
    stale_after = fm.get("stale_after")
    if stale_after and not is_iso_datetime(stale_after):
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
    if window is not None and not (isinstance(window, dict) and window.get("from") and window.get("to")):
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
    for field in ("executor", "attester"):
        block = fm.get(field)
        if isinstance(block, dict):
            candidates.append((f"{field}.resource", block.get("resource")))

    for label, value in candidates:
        if not isinstance(value, str) or not _looks_like_path(value):
            continue
        target = value.split("#")[0]
        if bundle.exists(bundle.resolve(path, target)) or bundle.exists("/" + target.lstrip("/")):
            continue
        warnings.append(f"{rel}: '{label}' points at missing in-bundle path '{value}' (§6.2)")


def _check_computation(rel, fm, body, warnings) -> None:
    if not fm.get("runtime"):
        warnings.append(f"{rel}: 'runtime' is required for an Attested Computation (§10.2)")
    for n, param in enumerate(_as_list(fm.get("parameters"))):
        if not isinstance(param, dict):
            warnings.append(f"{rel}: 'parameters[{n}]' should be a mapping of {{ name, type, required }} (§10.2)")
        elif not param.get("name"):
            warnings.append(f"{rel}: 'parameters[{n}]' has no 'name' (§10.2)")
    has_heading = re.search(r"^#{1,6}\s+Computation\s*$", body, re.M)
    if not fm.get("computation") and not has_heading:
        warnings.append(f"{rel}: no 'computation' path and no '# Computation' body section (§10.3)")
    executor = fm.get("executor")
    if isinstance(executor, dict) and not executor.get("resource"):
        warnings.append(f"{rel}: 'executor' has no 'resource' naming how to run the computation (§10.2)")


def _check_footnotes(rel, fm, prose, warnings) -> None:
    """§5.1: a footnote label attributing a claim joins to a sources[].id.
    Only a label with neither a definition nor a matching id is dangling."""
    ids = {
        str(entry["id"])
        for entry in _as_list(fm.get("sources"))
        if isinstance(entry, dict) and entry.get("id")
    }
    defined = set(FOOTNOTE_DEF_RE.findall(prose))
    for label in dict.fromkeys(FOOTNOTE_USE_RE.findall(prose)):
        if label not in ids and label not in defined:
            warnings.append(f"{rel}: footnote '[^{label}]' matches no 'sources[].id' and has no definition (§5.1)")


def collect_report(root: Path, today: date | None = None) -> list[dict]:
    """Per-concept trust and lifecycle signals, for --report."""
    today = today or date.today()
    rows: list[dict] = []
    for path in list_md_files(root):
        if path.name in RESERVED:
            continue
        text, _ = _read(path)
        fm, _body = parse_frontmatter(text)
        fm = fm or {}
        deadline = stale_since(fm, today)
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "type": str(fm.get("type") or "-"),
            "status": str(fm.get("status") or "stable"),
            "tier": trust_tier(fm),
            "stale": deadline,
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
                    help="evaluate staleness against this date instead of today")
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

    errors, warnings = check_bundle(args.bundle, today)
    for msg in errors:
        print(f"ERROR   {msg}")
    for msg in warnings:
        print(f"warning {msg}")

    n_concepts = len([p for p in list_md_files(args.bundle) if p.name not in RESERVED])
    print(f"\n{args.bundle}: {n_concepts} concept doc(s), {len(errors)} error(s), {len(warnings)} warning(s)")
    if errors or (args.strict and warnings):
        return 1
    print("Bundle is conformant with OKF v0.2.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
