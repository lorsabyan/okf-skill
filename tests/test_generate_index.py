"""Index generator tests.

The load-bearing property is that regenerating never churns a curated index:
the reference bundles order entries meaningfully and abridge titles, and an
agent runs this tool automatically.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SCRIPTS, bundle  # must precede the script imports: adds okf/scripts to sys.path
from generate_index import generate, parse_index, split_frontmatter_prefix  # noqa: E402

GENERATOR = SCRIPTS / "generate_index.py"


class GeneratorCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def build(self, files):
        bundle(self.root, files)

    def run_generate(self, check=False, rebuild=False):
        return generate(self.root, check, rebuild)

    def index(self, rel="index.md"):
        return (self.root / rel).read_text(encoding="utf-8")

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(GENERATOR), str(self.root), *args],
            capture_output=True, text=True,
        )


class FreshIndex(GeneratorCase):
    def test_groups_by_type_alphabetically_and_sorts_entries_by_title(self):
        self.build({
            "revenue.md": "---\ntype: Metric\ntitle: Revenue\ndescription: Recognized revenue.\n---\n\nB.\n",
            "aov.md": "---\ntype: Metric\ntitle: Average Order Value\ndescription: Mean order value.\n---\n\nB.\n",
            "orders.md": "---\ntype: BigQuery Table\ntitle: Orders\ndescription: One row per order.\n---\n\nB.\n",
        })
        self.run_generate()
        self.assertEqual(self.index(), (
            "# BigQuery Table\n"
            "\n"
            "* [Orders](orders.md) - One row per order.\n"
            "\n"
            "# Metric\n"
            "\n"
            "* [Average Order Value](aov.md) - Mean order value.\n"
            "* [Revenue](revenue.md) - Recognized revenue.\n"
        ))

    def test_subdirectories_come_last_and_link_the_index(self):
        self.build({
            "orders.md": "---\ntype: BigQuery Table\ntitle: Orders\ndescription: One row per order.\n---\n\nB.\n",
            "refs/vote_types.md": "---\ntype: Reference\ntitle: Vote types\ndescription: Enum lookup.\n---\n\nB.\n",
        })
        self.run_generate()
        body = self.index()
        self.assertIn("# Subdirectories\n\n* [refs](refs/index.md) - Enum lookup.\n", body)
        self.assertLess(body.index("# BigQuery Table"), body.index("# Subdirectories"))

    def test_title_falls_back_to_filename_stem(self):
        self.build({"orders.md": "---\ntype: Metric\ndescription: A metric.\n---\n\nB.\n"})
        self.run_generate()
        self.assertIn("* [orders](orders.md) - A metric.", self.index())

    def test_description_suffix_omitted_when_absent(self):
        self.build({"orders.md": "---\ntype: Metric\ntitle: Orders\n---\n\nB.\n"})
        self.run_generate()
        self.assertIn("* [Orders](orders.md)\n", self.index())

    def test_untyped_concept_grouped_under_other(self):
        self.build({"x.md": "---\ntitle: No type\ndescription: d\n---\n\nB.\n"})
        self.run_generate()
        self.assertIn("# Other", self.index())


class PreservesCuration(GeneratorCase):
    """Mirrors what acme_retail does: curated order, abridged titles and blurbs."""

    CURATED = (
        "# Metric\n"
        "\n"
        "* [Revenue](revenue.md) - Recognized revenue per Acme's FY2026 policy.\n"
        "* [Gross Margin](gross-margin.md) - Gross margin per the FY2026 standard.\n"
    )

    def setUp(self):
        super().setUp()
        self.build({
            "index.md": self.CURATED,
            "revenue.md": (
                "---\ntype: Metric\ntitle: Acme Retail — Revenue\n"
                "description: Recognized revenue for a period, per the FY2026 policy. Long form.\n---\n\nB.\n"
            ),
            "gross-margin.md": (
                "---\ntype: Metric\ntitle: Acme Retail — Gross Margin\n"
                "description: Gross margin for a period, per the FY2026 standard. Long form.\n---\n\nB.\n"
            ),
        })

    def test_regeneration_is_a_no_op(self):
        changed, unchanged = self.run_generate(check=True)
        self.assertEqual(changed, [])
        self.assertEqual(len(unchanged), 1)

    def test_curated_order_titles_and_descriptions_survive(self):
        self.run_generate()
        self.assertEqual(self.index(), self.CURATED)

    def test_new_concept_is_appended_to_its_section(self):
        (self.root / "aov.md").write_text(
            "---\ntype: Metric\ntitle: Average Order Value\ndescription: Mean order value.\n---\n\nB.\n"
        )
        self.run_generate()
        self.assertEqual(self.index(), self.CURATED + "* [Average Order Value](aov.md) - Mean order value.\n")

    def test_removed_concept_is_dropped(self):
        (self.root / "gross-margin.md").unlink()
        self.run_generate()
        self.assertNotIn("gross-margin.md", self.index())
        self.assertIn("* [Revenue](revenue.md)", self.index())

    def test_new_type_gets_its_own_section(self):
        (self.root / "orders.md").write_text(
            "---\ntype: BigQuery Table\ntitle: Orders\ndescription: One row per order.\n---\n\nB.\n"
        )
        self.run_generate()
        self.assertIn("# BigQuery Table\n\n* [Orders](orders.md) - One row per order.\n", self.index())

    def test_rebuild_discards_curation(self):
        self.run_generate(rebuild=True)
        body = self.index()
        self.assertIn("Acme Retail — Gross Margin", body)  # full title restored
        self.assertLess(body.index("Gross Margin"), body.index("Revenue"))  # alphabetical


class PreservesOtherContent(GeneratorCase):
    def test_non_markdown_entry_is_kept(self):
        """acme_retail/attesters/index.md lists a .py file; regenerating must
        not drop it just because it is not a concept doc."""
        self.build({
            "attesters/index.md": (
                "# Attester\n\n* [sql_equality.py](sql_equality.py) - Canonicalizes SQL.\n"
            ),
            "attesters/sql_equality.py": "# code\n",
            "orders.md": "---\ntype: Metric\ntitle: Orders\ndescription: d\n---\n\nB.\n",
        })
        self.run_generate()
        self.assertIn("sql_equality.py", self.index("attesters/index.md"))

    def test_directory_with_an_index_but_no_concepts_is_still_listed(self):
        self.build({
            "attesters/index.md": "# Attester\n\n* [sql_equality.py](sql_equality.py) - Canonicalizes SQL.\n",
            "attesters/sql_equality.py": "# code\n",
            "orders.md": "---\ntype: Metric\ntitle: Orders\ndescription: d\n---\n\nB.\n",
        })
        self.run_generate()
        self.assertIn("* [attesters](attesters/index.md)", self.index())

    def test_dead_entry_is_dropped(self):
        self.build({
            "index.md": "# Metric\n\n* [Orders](orders.md) - d\n* [Ghost](ghost.md) - gone\n",
            "orders.md": "---\ntype: Metric\ntitle: Orders\ndescription: d\n---\n\nB.\n",
        })
        self.run_generate()
        self.assertNotIn("ghost.md", self.index())

    def test_root_frontmatter_is_preserved(self):
        self.build({
            "index.md": '---\nokf_version: "0.2"\n---\n\n# Metric\n\n* [Orders](orders.md) - d\n',
            "orders.md": "---\ntype: Metric\ntitle: Orders\ndescription: d\n---\n\nB.\n",
        })
        self.run_generate()
        self.assertTrue(self.index().startswith('---\nokf_version: "0.2"\n---\n\n'))


class Idempotence(GeneratorCase):
    def test_second_run_changes_nothing(self):
        self.build({
            "orders.md": "---\ntype: BigQuery Table\ntitle: Orders\ndescription: d\n---\n\nB.\n",
            "refs/x.md": "---\ntype: Reference\ntitle: X\ndescription: e\n---\n\nB.\n",
        })
        self.run_generate()
        first = self.index()
        changed, _ = self.run_generate()
        self.assertEqual(changed, [])
        self.assertEqual(self.index(), first)


class Helpers(unittest.TestCase):
    def test_parse_index_reads_ordered_sections(self):
        sections = parse_index("# A\n\n* [One](one.md) - first\n\n# B\n\n* [Two](two.md)\n")
        self.assertEqual([h for h, _ in sections], ["A", "B"])
        self.assertEqual(sections[0][1], [("One", "one.md", "first")])
        self.assertEqual(sections[1][1], [("Two", "two.md", "")])

    def test_split_frontmatter_prefix(self):
        prefix, body = split_frontmatter_prefix('---\nokf_version: "0.2"\n---\n\n# A\n')
        # The prefix is what gets written back verbatim; the body is only parsed,
        # so its trailing newline is not preserved.
        self.assertEqual(prefix, '---\nokf_version: "0.2"\n---\n\n')
        self.assertEqual(body, "# A")

    def test_split_frontmatter_prefix_without_block(self):
        prefix, body = split_frontmatter_prefix("# A\n")
        self.assertEqual(prefix, "")
        self.assertEqual(body, "# A\n")


class CommandLine(GeneratorCase):
    def test_check_exits_one_when_stale_and_writes_nothing(self):
        self.build({"orders.md": "---\ntype: Metric\ntitle: Orders\ndescription: d\n---\n\nB.\n"})
        result = self.run_cli("--check")
        self.assertEqual(result.returncode, 1)
        self.assertFalse((self.root / "index.md").exists())

    def test_check_exits_zero_when_current(self):
        self.build({"orders.md": "---\ntype: Metric\ntitle: Orders\ndescription: d\n---\n\nB.\n"})
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.run_cli("--check").returncode, 0)

    def test_missing_directory_exits_two(self):
        result = subprocess.run(
            [sys.executable, str(GENERATOR), str(self.root / "nope")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
