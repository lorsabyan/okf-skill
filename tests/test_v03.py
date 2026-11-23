"""Cross-version behavior at the public validator, report and index entry points."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import bundle
from generate_index import generate
from validate_okf import check_bundle, collect_report, parse_frontmatter, trust_tier


class Version03(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "bundle"
        self.metadata = '---\nokf_version: "0.3"\ntitle: Test\nlicense: MIT\nx-owner: ops\n---\n'
        bundle(self.root, {"index.md": self.metadata + "\n# Concepts\n\n* [A](a.md) - A\n",
                           "a.md": "---\ntype: Metric\ndescription: A\n---\n"})

    def test_mixed_markdown_and_root_metadata_survive_rebuild(self):
        bundle(self.root, {"README.md": "# Read me", "notes/about.md": "---\ntitle: About\n---\n",
                           "sales figures.md": "---\ntype: Metric\ndescription: Sales\n---\n"})
        generate(self.root, False, rebuild=True)
        index = (self.root / "index.md").read_text()
        self.assertTrue(index.startswith(self.metadata))
        self.assertIn("(sales%20figures.md)", index)
        self.assertNotIn("notes/", index)
        errors, warnings = check_bundle(self.root)
        self.assertFalse(errors)
        self.assertEqual(len(warnings), 2, warnings)
        self.assertEqual({r["path"] for r in collect_report(self.root)}, {"a.md", "sales figures.md"})

    def test_root_relative_index_entry_keeps_its_curated_label(self):
        path = self.root / "index.md"
        original = self.metadata.replace("x-owner: ops", "x-note: |\n  ---\n  ops")
        original += "\n# Selected\n\n* [Curated](/a.md) - A\n"
        path.write_text(original)
        self.assertEqual(generate(self.root, True)[0], [])
        generate(self.root, False)
        self.assertEqual(path.read_text(), original)

    def test_path_fields_file_relative_and_legacy_fallback(self):
        bundle(self.root, {"sub/b.md": "---\ntype: Metric\ndescription: B\nstatus: deprecated\nsuperseded_by: a.md\n---\n"})
        def missing():
            return any("superseded_by" in w for w in check_bundle(self.root)[1])
        self.assertTrue(missing())
        p = self.root / "sub/b.md"
        p.write_text(p.read_text().replace("by: a.md", "by: /sub/../a.md"))
        self.assertFalse(missing())
        p.write_text(p.read_text().replace("by: /sub/../a.md", "by: a.md"))
        idx = self.root / "index.md"
        idx.write_text(idx.read_text().replace('"0.3"', '"0.2"'))
        self.assertFalse(missing())

    def test_only_current_valid_verification_counts(self):
        fm = {"generated": {"by": "tool/1", "at": "2026-06-10T12:00:00Z"},
              "verified": [{"by": "human:old", "at": "2026-06-10T14:59:59+03:00"},
                           {"by": "human:missing"}, {"at": "2026-06-11"}]}
        self.assertEqual(trust_tier(fm), "unverified")
        fm["verified"].append({"by": "process:ci", "at": "2026-06-10T15:00:00+03:00"})
        self.assertEqual(trust_tier(fm), "machine-confirmed")
        fm["verified"].append({"by": "human:new", "at": "2026-06-11"})
        self.assertEqual(trust_tier(fm), "human-reviewed")

    def test_naive_deadline_is_unknown_and_duplicate_keys_are_invalid(self):
        path = self.root / "a.md"
        path.write_text("---\ntype: Metric\nstale_after: 2026-08-10T12:00:00\n---\n")
        self.assertTrue(collect_report(self.root)[0]["invalid_deadline"])
        path.write_text("---\ntype: Metric\nx-producer: {a: true, a: false}\n---\n")
        self.assertTrue(check_bundle(self.root)[0])
        fm, _ = parse_frontmatter("---\ntype: Metric\nx-extra: {on: true, legacy: yes}\n---")
        self.assertEqual(fm["x-extra"], {"on": True, "legacy": "yes"})

    def test_external_symlinks_never_supply_concepts_or_receive_indexes(self):
        outside = self.root.parent / "outside.md"
        outside.write_text("---\ntype: Private\n---\n")
        (self.root / "outside.md").symlink_to(outside)
        (self.root / "index.md").unlink()
        (self.root / "index.md").symlink_to(outside)
        self.assertEqual([r["path"] for r in collect_report(self.root)], ["a.md"])
        self.assertFalse(check_bundle(self.root)[0])
        generate(self.root, False)
        self.assertEqual(outside.read_text(), "---\ntype: Private\n---\n")

    def test_computation_fence_must_be_inside_the_section(self):
        path = self.root / "a.md"
        contract = "---\ntype: Attested Computation\ndescription: A\nruntime: sql\n---\n"
        path.write_text(contract + "## Computation\ntext\n## Example\n```sql\nSELECT 1\n```\n")
        self.assertTrue(any("fenced computation" in w for w in check_bundle(self.root)[1]))
        path.write_text(contract + "## Computation\n### Query\n```sql\nSELECT 1\n```\n")
        self.assertEqual(check_bundle(self.root), ([], []))
