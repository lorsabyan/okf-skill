#!/usr/bin/env python3
"""Validate a directory tree against the Open Knowledge Format (OKF) v0.1 spec.

Stdlib-only. Errors are v0.1 conformance violations (exit 1); warnings are
soft-guidance issues the spec says consumers must tolerate (exit 0).

Usage:
    python validate_okf.py <bundle-dir> [--strict]

    --strict    treat warnings as errors
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RESERVED = {"index.md", "log.md"}
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
DATE_HEADING_RE = re.compile(r"^## \d{4}-\d{2}-\d{2}\s*$")
FENCED_BLOCK_RE = re.compile(r"^(`{3,}|~{3,}).*?^\1`*\s*$", re.M | re.S)
INDEX_ENTRY_RE = re.compile(r"^[*-] \[", re.M)


def list_md_files(root: Path) -> list[Path]:
    """All .md files in the bundle, skipping hidden directories/files."""
    return sorted(
        p for p in root.rglob("*.md")
        if not any(part.startswith(".") for part in p.relative_to(root).parts)
    )


def split_frontmatter(text: str) -> tuple[dict[str, str] | None, str]:
    """Return (frontmatter dict or None, body). Minimal YAML: top-level
    'key: value' pairs only, which covers every field OKF defines."""
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines()
    if lines[0].strip() != "---":
        return None, text
    try:
        end = next(i for i, ln in enumerate(lines[1:], 1) if ln.strip() == "---")
    except StopIteration:
        return None, text
    fm: dict[str, str] = {}
    for ln in lines[1:end]:
        if not ln.strip() or ln.strip().startswith("#") or ln.startswith((" ", "\t", "-")):
            continue
        if ":" not in ln:
            return None, text  # unparseable top-level line
        key, _, val = ln.partition(":")
        fm[key.strip()] = val.strip().strip("'\"")
    return fm, "\n".join(lines[end + 1:])


def check_bundle(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    md_files = list_md_files(root)
    concepts = {p for p in md_files if p.name not in RESERVED}
    concept_paths = {"/" + p.relative_to(root).as_posix() for p in concepts}
    dirs_with_md = {p.parent for p in md_files}

    for path in md_files:
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        fm, body = split_frontmatter(text)

        if path.name in RESERVED:
            if path.name == "index.md":
                if fm is not None and path.parent != root:
                    warnings.append(f"{rel}: frontmatter in index.md is only permitted at the bundle root (for okf_version)")
                if not INDEX_ENTRY_RE.search(body if fm is not None else text):
                    warnings.append(f"{rel}: index.md has no '* [Title](url) - description' entries")
            elif path.name == "log.md":
                if not any(DATE_HEADING_RE.match(ln) for ln in text.splitlines()):
                    warnings.append(f"{rel}: log.md has no '## YYYY-MM-DD' date headings")
        else:
            if fm is None:
                errors.append(f"{rel}: missing or unparseable YAML frontmatter block")
                continue
            if not fm.get("type"):
                errors.append(f"{rel}: frontmatter is missing a non-empty 'type' field")
            if not fm.get("description"):
                warnings.append(f"{rel}: no 'description' - index generators and previews rely on it")
            if fm.get("timestamp") and not re.match(r"^\d{4}-\d{2}-\d{2}", fm["timestamp"]):
                warnings.append(f"{rel}: 'timestamp' does not look like ISO 8601")

        # Cross-link resolution (broken links are legal -> warning only).
        # Fenced code blocks often quote example markdown; don't scan them.
        prose = FENCED_BLOCK_RE.sub("", text)
        for target in LINK_RE.findall(prose):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue  # external URL or in-page anchor
            target = target.split("#")[0]
            if not target.endswith(".md"):
                continue  # directory links, assets
            if target.startswith("/"):
                resolved = target
            else:
                try:
                    abs_target = (path.parent / target).resolve()
                    resolved = "/" + abs_target.relative_to(root.resolve()).as_posix() \
                        if abs_target.is_relative_to(root.resolve()) else None
                except OSError:
                    continue  # target isn't a representable path on this OS
            if resolved and resolved not in concept_paths and not (root / resolved.lstrip("/")).exists():
                warnings.append(f"{rel}: link to missing concept '{target}'")

    for d in sorted(dirs_with_md):
        if not (d / "index.md").exists():
            warnings.append(f"{d.relative_to(root).as_posix() or '.'}/: no index.md (progressive disclosure)")

    return errors, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle", type=Path)
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    args = ap.parse_args()

    if not args.bundle.is_dir():
        print(f"error: {args.bundle} is not a directory", file=sys.stderr)
        return 2

    errors, warnings = check_bundle(args.bundle)
    for msg in errors:
        print(f"ERROR   {msg}")
    for msg in warnings:
        print(f"warning {msg}")
    n_concepts = len([p for p in list_md_files(args.bundle) if p.name not in RESERVED])
    print(f"\n{args.bundle}: {n_concepts} concept doc(s), {len(errors)} error(s), {len(warnings)} warning(s)")
    if errors or (args.strict and warnings):
        return 1
    print("Bundle is conformant with OKF v0.1.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
