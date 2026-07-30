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

Stdlib-only; shares its frontmatter parser with validate_okf.py.

Usage:
    python3 generate_index.py <bundle-dir> [--check] [--rebuild]

    --check     exit 1 if any index is out of date, write nothing
    --rebuild   ignore existing structure; regenerate from frontmatter
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_okf import INDEX_PARSE_RE, RESERVED, parse_frontmatter  # noqa: E402

SUBDIR_HEADING = "Subdirectories"
UNTYPED_HEADING = "Other"
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")


def _decode(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _visible(root: Path, path: Path) -> bool:
    return not any(part.startswith(".") for part in path.relative_to(root).parts)


def _concept_docs(root: Path) -> list[Path]:
    return [md for md in root.rglob("*.md") if md.name not in RESERVED and _visible(root, md)]


def _read_concept(path: Path) -> tuple[str, str, str] | None:
    """Return (type, title, description), or None when frontmatter is unreadable."""
    text = _decode(path)
    if text is None:
        return None
    frontmatter, _ = parse_frontmatter(text)
    if frontmatter is None:
        return None
    concept_type = str(frontmatter.get("type") or "").strip() or UNTYPED_HEADING
    title = str(frontmatter.get("title") or "").strip() or path.stem
    description = str(frontmatter.get("description") or "").strip()
    return concept_type, title, description


def _indexable_dirs(root: Path) -> list[Path]:
    """Every directory holding a concept doc, plus the ancestors leading to it."""
    dirs: set[Path] = set()
    for md in _concept_docs(root):
        current = md.parent
        while True:
            dirs.add(current)
            if current == root:
                break
            current = current.parent
    return sorted(dirs)


def split_frontmatter_prefix(text: str) -> tuple[str, str]:
    """Split a leading frontmatter block off an index. Only a bundle-root index
    may carry one (it declares okf_version), and it is preserved verbatim."""
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return "", text
    for i, line in enumerate(lines[1:], 1):
        if line.strip() in ("---", "..."):
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


def _discover(directory: Path, root: Path, dir_descriptions: dict[Path, str]):
    """What the directory actually contains now: {link: (heading, title, desc)}."""
    found: dict[str, tuple[str, str, str]] = {}
    for child in sorted(directory.iterdir()):
        if not _visible(root, child):
            continue
        if child.is_file() and child.suffix == ".md" and child.name not in RESERVED:
            parsed = _read_concept(child)
            if parsed is None:
                continue
            concept_type, title, description = parsed
            found[child.name] = (concept_type, title, description)
        elif child.is_dir() and (_concept_docs(child) or (child / "index.md").exists()):
            # Listed because it has, or will get, an index of its own — including
            # a directory of code such as `attesters/`, which carries an index but
            # no concept docs. Upstream synthesizes a blurb with an LLM; offline,
            # borrow the lone child's description when there is exactly one.
            found[f"{child.name}/index.md"] = (
                SUBDIR_HEADING, child.name, dir_descriptions.get(child, "")
            )
    return found


def _resolves(directory: Path, link: str) -> bool:
    """Whether an existing entry still points at something real. Broader than
    concept discovery on purpose: indexes legitimately list non-markdown assets
    (`sql_equality.py`), and regenerating must not drop them."""
    target = link.split("#")[0].split("?")[0]
    if not target or target.startswith(("http://", "https://", "/")):
        return True  # not ours to judge
    return (directory / target).exists()


def build_index(
    directory: Path,
    root: Path,
    dir_descriptions: dict[Path, str],
    rebuild: bool = False,
) -> str | None:
    """Render the index body for one directory, or None when nothing to list."""
    found = _discover(directory, root, dir_descriptions)
    if not found:
        return None

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
    for heading, entries in existing:
        kept = []
        for title, link, description in entries:
            if link not in seen and (link in found or _resolves(directory, link)):
                kept.append((title, link, description))
                seen.add(link)
        sections.append((heading, kept))

    # Append what is new, into its own heading when one already exists.
    by_heading = {heading: entries for heading, entries in sections}
    for link, (heading, title, description) in found.items():
        if link in seen:
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

    # Deepest first, so a child's description is known before its parent lists it.
    for directory in sorted(
        _indexable_dirs(root), key=lambda p: (-len(p.relative_to(root).parts), str(p))
    ):
        body = build_index(directory, root, dir_descriptions, rebuild)
        if body is None:
            continue

        concepts = [
            c for c in sorted(directory.iterdir())
            if c.is_file() and c.suffix == ".md" and c.name not in RESERVED and _visible(root, c)
        ]
        if len(concepts) == 1:
            parsed = _read_concept(concepts[0])
            if parsed and parsed[2]:
                dir_descriptions[directory] = parsed[2]

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
