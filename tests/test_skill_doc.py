"""Tests that SKILL.md and the scripts cannot drift apart.

The skill is prose, so nothing enforces that what it teaches is valid OKF or
matches the tools shipped beside it. These tests extract its examples and run
them through the validator, and assert the guidance the earlier revisions got
wrong stays fixed.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from helpers import REPO_ROOT, SKILL_MD, write  # noqa: F401  also adds okf/scripts to sys.path
from validate_okf import check_bundle, parse_frontmatter  # noqa: E402

SKILL = SKILL_MD.read_text(encoding="utf-8")
FENCE_RE = re.compile(r"^(`{3,4})markdown\n(.*?)^\1", re.M | re.S)
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def skill_frontmatter() -> dict:
    parsed, _ = parse_frontmatter(SKILL)
    assert parsed is not None, "SKILL.md must open with a YAML frontmatter block"
    return parsed


def example_concepts() -> list[str]:
    """Every ```markdown fence in SKILL.md that is itself a concept doc."""
    return [
        block for _fence, block in FENCE_RE.findall(SKILL)
        if block.lstrip().startswith("---")
    ]


class SkillFrontmatter(unittest.TestCase):
    def test_has_name_and_description(self):
        frontmatter = skill_frontmatter()
        self.assertEqual(frontmatter["name"], "okf")
        self.assertTrue(frontmatter["description"])

    def test_description_within_limit(self):
        self.assertLessEqual(len(skill_frontmatter()["description"]), 1024)


class TaughtExamplesAreValid(unittest.TestCase):
    """Build a bundle out of SKILL.md's own examples and validate it."""

    def test_examples_exist(self):
        self.assertGreaterEqual(len(example_concepts()), 2, "expected concept examples in SKILL.md")

    def test_every_example_parses_and_declares_a_type(self):
        for block in example_concepts():
            frontmatter, _ = parse_frontmatter(block)
            self.assertIsNotNone(frontmatter, f"example does not parse:\n{block[:120]}")
            self.assertTrue(frontmatter.get("type"), f"example has no type:\n{block[:120]}")

    def test_examples_validate_as_a_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = []
            for i, block in enumerate(example_concepts()):
                name = f"concept{i}.md"
                write(root / name, block)
                names.append(name)

            # Satisfy the links and paths the examples reference.
            for target in ("order_lines.md", "customers.md"):
                write(root / target, "---\ntype: BigQuery Table\ndescription: Support doc.\n---\n\nBody.\n")
            write(root / "references" / "skills" / "run-on-bq.md",
                  "---\ntype: Reference\ndescription: Executor.\n---\n\nBody.\n")
            write(root / "references" / "attesters" / "revenue.py", "# attester\n")
            write(root / "references" / "skills" / "index.md",
                  "# Reference\n\n* [Run on BQ](run-on-bq.md) - Executor.\n")
            write(root / "references" / "attesters" / "index.md",
                  "# Attester\n\n* [revenue.py](revenue.py) - Attester code.\n")
            write(root / "references" / "index.md",
                  "# Subdirectories\n\n* [skills](skills/index.md) - Executors.\n"
                  "* [attesters](attesters/index.md) - Attesters.\n")
            entries = "\n".join(f"* [{n}]({n}) - Example concept." for n in names)
            write(root / "index.md",
                  '---\nokf_version: "0.2"\n---\n\n# Example\n\n' + entries
                  + "\n* [order_lines.md](order_lines.md) - Support doc."
                  "\n* [customers.md](customers.md) - Support doc.\n"
                  "\n# Subdirectories\n\n* [references](references/index.md) - Supporting material.\n")

            errors, warnings = check_bundle(root)
            self.assertEqual(errors, [], f"SKILL.md examples produce errors: {errors}")
            self.assertEqual(warnings, [], f"SKILL.md examples produce warnings: {warnings}")


class GuidanceRegressions(unittest.TestCase):
    def test_no_bundle_absolute_links_in_examples(self):
        """A leading '/' does not resolve on GitHub when the bundle is a
        subdirectory, so the skill must not model it."""
        offenders = []
        for block in example_concepts():
            offenders += [t for t in LINK_RE.findall(block) if t.startswith("/")]
        self.assertEqual(offenders, [], f"absolute links in SKILL.md examples: {offenders}")

    def test_teaches_relative_links_explicitly(self):
        self.assertIn("Never start a link with `/`", SKILL)

    def test_teaches_the_de_facto_query_section(self):
        self.assertIn("# Common query patterns", SKILL)

    def test_documents_the_index_generator(self):
        self.assertIn("generate_index.py", SKILL)

    def test_documents_the_type_grouped_index_convention(self):
        self.assertIn("# Subdirectories", SKILL)

    def test_documents_v01_fallbacks(self):
        for token in ("timestamp", "# Citations"):
            self.assertIn(token, SKILL)

    def test_referenced_scripts_exist(self):
        for name in ("validate_okf.py", "generate_index.py"):
            self.assertTrue((REPO_ROOT / "okf" / "scripts" / name).is_file(), name)

    def test_spec_reference_is_vendored_and_pinned(self):
        spec = REPO_ROOT / "okf" / "references" / "SPEC.md"
        self.assertTrue(spec.is_file())
        head = spec.read_text(encoding="utf-8")[:600]
        self.assertIn("blob/3fcbb9f", head, "vendored SPEC must cite a pinned commit, not a branch")
        self.assertIn("**Version 0.2**", spec.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
