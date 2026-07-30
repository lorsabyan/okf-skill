"""Shared test helpers: import the skill's scripts and build throwaway bundles.

Fixtures are built in code rather than committed as files. Two of the
regressions under test are whitespace- and encoding-sensitive (a UTF-8 BOM, a
fence indented inside a list item), and an editor or a git filter can silently
normalize those away in a checked-in file. Constructing them here keeps them
exact.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "okf" / "scripts"
SKILL_MD = REPO_ROOT / "okf" / "SKILL.md"
SPEC_MD = REPO_ROOT / "okf" / "references" / "SPEC.md"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
README_MD = REPO_ROOT / "README.md"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Matches the upstream commit wherever it is cited: a blob URL, prose, or a
# `git checkout`. Deliberately anchored on the 7-40 hex shape, so a file that
# says "main" instead of a commit does not silently match.
PINNED_REF_RE = re.compile(r"(?:blob/|commit\s+`?|checkout\s+)([0-9a-f]{7,40})\b")


def pinned_ref() -> str:
    """The single source of truth for the vendored upstream commit: the blob URL
    in SPEC.md's attribution header. Everything else must agree with it, which
    test_pinned_refs.py enforces."""
    header = SPEC_MD.read_text(encoding="utf-8")[:600]
    found = re.search(r"blob/([0-9a-f]{7,40})/", header)
    assert found, "SPEC.md header must cite a pinned upstream commit in its blob URL"
    return found.group(1)


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
