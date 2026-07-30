"""Shared test helpers: import the skill's scripts and build throwaway bundles.

Fixtures are built in code rather than committed as files. Two of the
regressions under test are whitespace- and encoding-sensitive (a UTF-8 BOM, a
fence indented inside a list item), and an editor or a git filter can silently
normalize those away in a checked-in file. Constructing them here keeps them
exact.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "okf" / "scripts"
SKILL_MD = REPO_ROOT / "okf" / "SKILL.md"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding=encoding)
    return path


def concept(type_: str = "BigQuery Table", **fields) -> str:
    """A minimal valid concept doc, plus any extra frontmatter lines."""
    lines = [f"type: {type_}"] + [f"{key}: {value}" for key, value in fields.items()]
    return "---\n" + "\n".join(lines) + "\n---\n\nBody text.\n"


def bundle(root: Path, files: dict[str, str], encodings: dict[str, str] | None = None) -> Path:
    """Materialize a bundle from {relative path: contents}."""
    encodings = encodings or {}
    for rel, text in files.items():
        write(root / rel, text, encodings.get(rel, "utf-8"))
    return root
