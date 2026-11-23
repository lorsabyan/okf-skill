#!/usr/bin/env python3
"""Generate OKF `index.md` files for every directory in a bundle.

A new index is built to the convention upstream's generator emits: entries
grouped under the concept's `type` as the section heading, sections
alphabetical, entries sorted by title, file-relative links, and subdirectories
last under `# Subdirectories` linking to each directory's own `index.md`.

An index that already exists is updated, not rewritten: entries whose target
still exists keep their position, title, and description, entries whose target
is gone are dropped, and new concepts are appended to their type's section.
Curated order and hand-abridged titles therefore survive regeneration, which
matters because the reference bundles curate both. `--rebuild` discards all of
that and applies the mechanical convention instead.

Shares its frontmatter parser with validate_okf.py.

Usage:
    python3 generate_index.py <bundle-dir> [--check] [--rebuild]

    --check     exit 1 if any index is out of date, write nothing
    --rebuild   ignore existing structure; regenerate from frontmatter
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_okf import INDEX_PARSE_RE, RESERVED, URI_SCHEME_RE, _visible, bundle_version, concept_type, list_md_files, parse_frontmatter  # noqa: E402

SUBDIR_HEADING = "Subdirectories"
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def _decode(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _read_concept(path: Path, legacy: bool) -> tuple[str, str, str] | None:
    """Return (type, title, description), or None when frontmatter is unreadable."""
    text = _decode(path)
    if text is None:
        return None
    frontmatter, _ = parse_frontmatter(text, legacy)
    kind = concept_type(frontmatter)
    if not kind:
        return None
    title = str(frontmatter.get("title") or "").strip() or path.stem
    description = str(frontmatter.get("description") or "").strip()
    return kind, title, description


def split_frontmatter_prefix(text: str) -> tuple[str, str]:
    """Split a leading frontmatter block off an index. Only a bundle-root index
    may carry one (it declares okf_version), and it is preserved verbatim."""
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines()
    if lines[0] != "---":
        return "", text
    for i, line in enumerate(lines[1:], 1):
        if line in ("---", "..."):
            body = "\n".join(lines[i + 1:]).lstrip("\n")
            return "\n".join(lines[: i + 1]) + "\n\n", body
    return "", text


def parse_index(text: str) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """Read an index body into ordered (heading, entries) sections."""
    sections: list[tuple[str, list[tuple[str, str, str]]]] = []
    current: list[tuple[str, str, str]] | None = None
    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            current = []
            sections.append((heading.group(1), current))
            continue
        entry = INDEX_PARSE_RE.match(line)
        if entry and current is not None:
            title, link, description = entry.groups()
            current.append((title, link, description.strip()))
    return sections


def _render(sections: list[tuple[str, list[tuple[str, str, str]]]]) -> str:
    blocks = []
    for heading, entries in sections:
        if not entries:
            continue
        lines = [f"# {heading}", ""]
        for title, link, description in entries:
            lines.append(f"* [{title}]({link})" + (f" - {description}" if description else ""))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n" if blocks else ""


def _discover(directory, root, dir_descriptions, concepts, directories):
    """What the directory actually contains now: {link: (heading, title, desc)}."""
    found: dict[str, tuple[str, str, str]] = {}
    for child in sorted(directory.iterdir()):
        if not _visible(root, child):
            continue
        if child in concepts:
            found[quote(child.name)] = concepts[child]
        elif child in directories:
            # Listed because it has, or will get, an index of its own — including
            # a directory of code such as `attesters/`, which carries an index but
            # no concept docs. Upstream synthesizes a blurb with an LLM; offline,
            # borrow the lone child's description when there is exactly one.
            found[f"{quote(child.name)}/index.md"] = (
                SUBDIR_HEADING, child.name, dir_descriptions.get(child, "")
            )
    return found


def _resolves(root: Path, directory: Path, link: str) -> bool:
    """Whether an existing entry still points at something real. Broader than
    concept discovery on purpose: indexes legitimately list non-markdown assets
    (`sql_equality.py`), and regenerating must not drop them."""
    target = link.split("#")[0].split("?")[0]
    if not target or URI_SCHEME_RE.match(target) or target.startswith("//"):
        return True  # not ours to judge
    target = unquote(target)
    path = root / target.lstrip("/") if target.startswith("/") else directory / target
    return not _visible(root, path) or path.exists()


def build_index(
    directory: Path,
    root: Path,
    dir_descriptions: dict[Path, str],
    concepts: dict,
    directories: set,
    rebuild: bool = False,
) -> str | None:
    """Render the index body for one directory, or None when nothing to list."""
    found = _discover(directory, root, dir_descriptions, concepts, directories)
    if not found:
        # With no discoverable concepts, an index may still document assets.
        # Remove dead entries while preserving its other content verbatim.
        text = _decode(directory / "index.md")
        if text is None:
            return None
        _, body = split_frontmatter_prefix(text) if directory == root else ("", text)
        kept = []
        for line in body.splitlines(keepends=True):
            entry = INDEX_PARSE_RE.match(line)
            if entry is None or _resolves(root, directory, entry.group(2)):
                kept.append(line)
        updated = "".join(kept)
        return updated if updated != body else None

    existing_text = _decode(directory / "index.md") if not rebuild else None
    _, existing_body = split_frontmatter_prefix(existing_text) if existing_text else ("", "")
    existing = parse_index(existing_body) if existing_body else []

    if not existing:
        # Fresh index: mechanical convention. Subdirectories last, types
        # alphabetical, entries by title.
        grouped: dict[str, list[tuple[str, str, str]]] = {}
        for link, (heading, title, description) in found.items():
            grouped.setdefault(heading, []).append((title, link, description))
        order = sorted(grouped, key=lambda h: (h == SUBDIR_HEADING, h.lower()))
        return _render([
            (h, sorted(grouped[h], key=lambda e: e[0].lower())) for h in order
        ])

    # Update in place: keep surviving entries as written, drop dead ones.
    sections: list[tuple[str, list[tuple[str, str, str]]]] = []
    seen: set[str] = set()
    listed_targets: set[str] = set()
    for heading, entries in existing:
        kept = []
        for title, link, description in entries:
            if link not in seen and (link in found or _resolves(root, directory, link)):
                kept.append((title, link, description))
                seen.add(link)
                target = unquote(link.partition("#")[0].partition("?")[0])
                if not URI_SCHEME_RE.match(target) and not target.startswith("//"):
                    base = "/" + directory.relative_to(root).as_posix()
                    listed_targets.add(posixpath.normpath(posixpath.join(base, target)))
        sections.append((heading, kept))

    # Append what is new, into its own heading when one already exists.
    by_heading = {heading: entries for heading, entries in sections}
    for link, (heading, title, description) in found.items():
        target = directory.relative_to(root) / unquote(link)
        if link in seen or "/" + target.as_posix() in listed_targets:
            continue
        if heading in by_heading:
            by_heading[heading].append((title, link, description))
        else:
            new_entries = [(title, link, description)]
            # Keep Subdirectories last if it is present.
            insert_at = next(
                (i for i, (h, _) in enumerate(sections) if h == SUBDIR_HEADING), len(sections)
            )
            sections.insert(insert_at, (heading, new_entries))
            by_heading[heading] = new_entries

    return _render([(h, e) for h, e in sections if e])


def generate(root: Path, check: bool, rebuild: bool = False) -> tuple[list[Path], list[Path]]:
    """Write (or verify) every index. Returns (changed, unchanged)."""
    changed: list[Path] = []
    unchanged: list[Path] = []
    dir_descriptions: dict[Path, str] = {}

    directories = set()
    concepts = {}
    legacy = bundle_version(root) in ("0.1", "0.2")
    for path in list_md_files(root):
        if path.name == "log.md":
            continue
        if path.name != "index.md":
            entry = _read_concept(path, legacy)
            if entry is None:
                continue
            concepts[path] = entry
        directory = path.parent
        while directory not in directories:
            directories.add(directory)
            if directory == root:
                break
            directory = directory.parent

    directories = {d for d in directories if _visible(root, d / "index.md")}
    for directory in sorted(directories, key=lambda p: (-len(p.parts), str(p))):
        body = build_index(directory, root, dir_descriptions, concepts, directories, rebuild)
        if body is None:
            continue
        children = [concepts[p] for p in directory.iterdir() if p in concepts]
        if len(children) == 1:
            dir_descriptions[directory] = children[0][2]

        index_path = directory / "index.md"
        existing_text = _decode(index_path) or ""
        prefix, _ = split_frontmatter_prefix(existing_text) if directory == root else ("", "")
        content = prefix + body

        if existing_text == content:
            unchanged.append(index_path)
            continue
        changed.append(index_path)
        if not check:
            index_path.write_text(content, encoding="utf-8")

    return changed, unchanged


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if any index is out of date; write nothing")
    ap.add_argument("--rebuild", action="store_true",
                    help="ignore existing structure and regenerate from frontmatter")
    args = ap.parse_args()

    if not args.bundle.is_dir():
        print(f"error: {args.bundle} is not a directory", file=sys.stderr)
        return 2

    changed, unchanged = generate(args.bundle, args.check, args.rebuild)
    verb = "would update" if args.check else "wrote"
    for path in changed:
        print(f"{verb} {path.relative_to(args.bundle).as_posix()}")

    state = "stale" if args.check else "written"
    print(f"\n{args.bundle}: {len(changed)} {state}, {len(unchanged)} up to date")
    if args.check and changed:
        print("Indexes are out of date. Run without --check to regenerate.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
