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
import codecs
import posixpath
import sys
from pathlib import Path
from urllib.parse import quote, unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_okf import RESERVED, URI_SCHEME_RE, _visible, bundle_version, concept_type, list_md_files, parse_frontmatter  # noqa: E402

from okf_markdown import index_append_boundary, index_sections, markdown_lines

SUBDIR_HEADING = "Subdirectories"
# Literal text inside a CommonMark link label can otherwise become inline markup.
LABEL_ESCAPES = str.maketrans({char: "\\" + char for char in "\\[]*_`<&"})


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
    lines = markdown_lines(text)
    if lines[0].rstrip("\r\n") != "---":
        return "", text
    for i, line in enumerate(lines[1:], 1):
        if line.rstrip("\r\n") in ("---", "..."):
            end = i + 1
            while end < len(lines) and not lines[end].strip():
                end += 1
            return "".join(lines[:end]), "".join(lines[end:])
    return "", text


def parse_index(text: str) -> list[tuple[str, list[tuple[str, str, str]]]]:
    return [(s.heading, [(e.title, e.target, e.description) for e in s.entries])
            for s in index_sections(text)]


def _render_entries(entries: list[tuple[str, str, str]]) -> str:
    lines = []
    for title, link, description in entries:
        description = " ".join(description.splitlines())
        suffix = f" - {description}" if description else ""
        label = " ".join(title.splitlines()).translate(LABEL_ESCAPES)
        lines.append(f"* [{label}]({link}){suffix}\n")
    return "".join(lines)


def _render(sections: list[tuple[str, list[tuple[str, str, str]]]]) -> str:
    return "\n".join(f"# {heading}\n\n{_render_entries(entries)}" for heading, entries in sections)


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
    text: str,
    rebuild: bool = False,
) -> str | None:
    """Render the index body for one directory, or None when nothing to list."""
    found = _discover(directory, root, dir_descriptions, concepts, directories)
    _, body = split_frontmatter_prefix(text) if directory == root else ("", text)
    if found and (rebuild or not body.strip()):
        # Fresh index: mechanical convention. Subdirectories last, types
        # alphabetical, entries by title.
        grouped: dict[str, list[tuple[str, str, str]]] = {}
        for link, (heading, title, description) in found.items():
            grouped.setdefault(heading, []).append((title, link, description))
        order = sorted(grouped, key=lambda h: (h == SUBDIR_HEADING, h.lower()))
        return _render([
            (h, sorted(grouped[h], key=lambda e: e[0].lower())) for h in order
        ])

    # Edit only listing lines. Keep prose, blank lines and surviving entries
    # in their original positions, including text before or after a list.
    lines = markdown_lines(body)
    sections = index_sections(body)
    listed = set()
    base = "/" + directory.relative_to(root).as_posix()
    for section in sections:
        for entry in section.entries:
            link = entry.target
            if link not in found and not _resolves(root, directory, link):
                end = entry.item_end
                while end > entry.paragraph_end and not lines[end - 1].strip():
                    end -= 1
                for line in range(entry.line, end):
                    lines[line] = ""
                continue
            if not URI_SCHEME_RE.match(link) and not link.startswith("//"):
                target = unquote(link.partition("#")[0].partition("?")[0])
                listed.add(posixpath.normpath(posixpath.join(base, target)))

    additions = {}
    for link, (heading, title, description) in found.items():
        if posixpath.normpath(posixpath.join(base, unquote(link))) not in listed:
            additions.setdefault(heading, []).append((title, link, description))

    # Apply insertions from the bottom up so source line positions stay valid.
    insertions = {}
    subdirectories = len(lines)
    newline = next((line[len(line.rstrip("\r\n")):] for line in lines if line.endswith(("\n", "\r"))), "\n")
    for section in sections:
        if section.heading == SUBDIR_HEADING:
            subdirectories = section.line
        entries = additions.pop(section.heading, [])
        if not entries:
            continue
        block = _render_entries(entries)
        if section.entries:
            last = section.entries[-1]
            position = last.item_end
            # The item span includes nested blocks and sometimes trailing blank lines.
            while position > last.paragraph_end and not lines[position - 1].strip():
                position -= 1
        else:
            # Start the list at a known block boundary, even if later prose
            # ends inside an HTML block that consumes everything up to EOF.
            position = section.heading_end
            block = "\n" + block + "\n"
        insertions[position] = insertions.get(position, "") + block

    if additions:
        append_at, delimiter = index_append_boundary(body, sections, len(lines))
    for heading in sorted(additions, key=lambda h: (h == SUBDIR_HEADING, h.lower())):
        entries = additions[heading]
        position = append_at if heading == SUBDIR_HEADING else min(append_at, subdirectories)
        block = _render([(heading, entries)])
        insertions[position] = insertions.get(position, "") + "\n" + block + "\n"

    if additions and delimiter and len(lines) in insertions:
        insertions[len(lines)] = delimiter + "\n\n" + insertions[len(lines)]

    for position, block in sorted(insertions.items(), reverse=True):
        if position and lines[position - 1] and not lines[position - 1].endswith(("\n", "\r")):
            block = "\n" + block
        lines.insert(position, block.replace("\n", newline))
    updated = "".join(lines)
    return updated if found or updated != body else None


def generate(root: Path, check: bool, rebuild: bool = False) -> tuple[list[Path], list[Path]]:
    """Write (or verify) every index. Returns (changed, unchanged)."""
    changed: list[Path] = []
    unchanged: list[Path] = []
    dir_descriptions: dict[Path, str] = {}

    directories = set()
    concepts = {}
    legacy = bundle_version(root, require_valid_metadata=True) in ("0.1", "0.2")
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
    pending = {}
    for directory in sorted(directories, key=lambda p: (-len(p.parts), str(p))):
        index_path = directory / "index.md"
        try:
            original = index_path.read_bytes()
        except FileNotFoundError:
            original = b""
        try:
            existing_text = original.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{index_path}: invalid UTF-8") from exc
        body = build_index(directory, root, dir_descriptions, concepts, directories, existing_text, rebuild)
        if body is None:
            continue
        children = [concepts[p] for p in directory.iterdir() if p in concepts]
        if len(children) == 1:
            dir_descriptions[directory] = children[0][2]

        prefix, _ = split_frontmatter_prefix(existing_text) if directory == root else ("", "")
        if prefix and body and not prefix.endswith(("\n", "\r")):
            prefix += "\n"
        content = prefix + body

        if existing_text == content:
            unchanged.append(index_path)
            continue
        if index_path.is_symlink() or (index_path.exists() and index_path.stat().st_nlink > 1):
            raise ValueError(f"{index_path}: cannot update a linked index in place")
        changed.append(index_path)
        encoding = "utf-8-sig" if original.startswith(codecs.BOM_UTF8) else "utf-8"
        pending[index_path] = content.encode(encoding)

    if not check:
        for path, data in pending.items():
            path.write_bytes(data)

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

    try:
        changed, unchanged = generate(args.bundle, args.check, args.rebuild)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
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
