"""Cross-version behavior at the public validator, report and index entry points."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import SCRIPTS, bundle
from generate_index import generate, parse_index
from validate_okf import check_bundle, collect_report, parse_frontmatter, trust_tier


class Version03(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "bundle"
        self.metadata = '---\nokf_version: "0.3"\ntitle: Test\nlicense: MIT\nx-owner: ops\n---\n'
        bundle(self.root, {"index.md": self.metadata + "\n# Concepts\n\n* [A](a.md) - A\n",
                           "a.md": "---\ntype: Metric\ndescription: A\n---\n"})

    def test_curated_index_prose_survives_noop_and_membership_changes(self):
        path = self.root / "index.md"
        intro = "Use fiscal dates for this group.\n\n"
        footer = "\nSee the accounting policy.\n"
        entry = "+ [Daily](a.md) - Curated description.\n"
        original = self.metadata + "\n# Metric\n\n" + intro + entry + footer
        path.write_text(original)
        self.assertEqual(generate(self.root, True)[0], [])
        generate(self.root, False)
        self.assertEqual(path.read_text(), original)
        wrapped = entry + "  Continuation of the curated description.\n"
        path.write_text(original.replace(entry, wrapped))
        bundle(self.root, {"b.md": "---\ntype: Metric\ndescription: B\n---\n"})
        generate(self.root, False)
        self.assertIn(wrapped + "* [b](b.md) - B\n", path.read_text())
        path.write_text(original)
        (self.root / "b.md").unlink()
        (self.root / "a.md").rename(self.root / "b.md")
        generate(self.root, False)
        self.assertEqual(path.read_text(), original.replace(entry, "* [b](b.md) - A\n"))
        self.assertEqual(generate(self.root, True)[0], [])

    def test_quoted_list_is_preserved_and_cannot_supply_index_entries(self):
        path = self.root / "index.md"
        example = "> Example:\n> * [Daily](a.md) - illustration\n> * [Old](old.md) - illustration\n"
        path.write_text(self.metadata + "\n# Metric\n\n" + example)
        self.assertTrue(any("entries" in e for e in check_bundle(self.root)[0]))
        generate(self.root, False)
        self.assertIn(example, path.read_text())
        self.assertEqual(parse_index(path.read_text()[len(self.metadata):]), [("Metric", [("a", "a.md", "A")])])
        self.assertEqual(generate(self.root, True)[0], [])

    def test_generated_title_round_trips_as_literal_link_text(self):
        title = r"Revenue ] FY [A] *gross* \ net &amp; `x`"
        bundle(self.root, {"a.md": f"---\ntype: Metric\ndescription: A\ntitle: '{title}'\n---\n"})
        generate(self.root, False, rebuild=True)
        path = self.root / "index.md"
        self.assertEqual(parse_index(path.read_text()[len(self.metadata):]), [("Metric", [(title, "a.md", "A")])])
        self.assertEqual(check_bundle(self.root), ([], []))
        self.assertEqual(generate(self.root, True)[0], [])

    def test_unclosed_fence_cannot_absorb_generated_entries_or_sections(self):
        path = self.root / "index.md"
        for heading in ("Metric", "Notes"):
            for marker in ("````", "~~~"):
                with self.subTest(heading=heading, marker=marker):
                    example = marker + "text\nexample"
                    path.write_text(self.metadata + f"\n# {heading}\n\n" + example)
                    generate(self.root, False)
                    self.assertIn(example, path.read_text())
                    self.assertEqual(check_bundle(self.root), ([], []))
                    self.assertEqual(generate(self.root, True)[0], [])

    def test_removing_an_entry_removes_its_wrapped_description_only(self):
        path = self.root / "index.md"
        paragraph = "Keep this separate note."
        path.write_text(self.metadata + "\n# Metric\n\n* [Old](old.md) - Old description\n"
                        "  continued obsolete description.\n\n" + paragraph + "\n")
        generate(self.root, False)
        self.assertNotIn("obsolete", path.read_text())
        self.assertNotIn("old.md", path.read_text())
        self.assertIn(paragraph, path.read_text())
        self.assertEqual(check_bundle(self.root), ([], []))
        self.assertEqual(generate(self.root, True)[0], [])

    def test_new_entry_follows_nested_material_in_existing_item(self):
        path = self.root / "index.md"
        item = "* [Alpha](a.md) - A\n  * Applies only to Alpha.\n"
        path.write_text(self.metadata + "\n# Metric\n\n" + item + "\nFooter.\n")
        bundle(self.root, {"b.md": "---\ntype: Metric\ndescription: B\n---\n"})
        generate(self.root, False)
        self.assertIn(item + "* [b](b.md) - B\n\nFooter.", path.read_text())
        self.assertEqual(generate(self.root, True)[0], [])

    def test_same_target_in_two_curated_sections_survives(self):
        path = self.root / "index.md"
        body = "# By region\n\n* [Daily](a.md) - Regional use\n\n# By owner\n\n* [Finance](a.md) - Owner instructions\n"
        path.write_text(self.metadata + "\n" + body)
        self.assertEqual(generate(self.root, True)[0], [])
        bundle(self.root, {"b.md": "---\ntype: Metric\ndescription: B\n---\n"})
        generate(self.root, False)
        self.assertIn(body, path.read_text())
        self.assertEqual(path.read_text().count("(a.md)"), 2)
        self.assertEqual(generate(self.root, True)[0], [])

    def test_new_list_is_outside_section_html(self):
        path = self.root / "index.md"
        for html in ("<div>Fiscal calendar</div>", "<!-- fiscal calendar"):
            with self.subTest(html=html):
                path.write_text(self.metadata + "\n# Metric\n\n" + html + "\n")
                generate(self.root, False)
                self.assertIn(html, path.read_text())
                self.assertEqual(check_bundle(self.root), ([], []))
                self.assertEqual(generate(self.root, True)[0], [])
                # A newly created section must also stay outside the raw block.
                path.write_text(self.metadata + "\n# Notes\n\n" + html + "\n")
                generate(self.root, False)
                self.assertIn("# Notes\n\n" + html, path.read_text())
                self.assertEqual(check_bundle(self.root), ([], []))
                self.assertEqual(generate(self.root, True)[0], [])

    def test_unicode_separator_does_not_shift_markdown_edits(self):
        path = self.root / "index.md"
        for eol in ("\n", "\r\n", "\r"):
            with self.subTest(eol=eol):
                original = self.metadata + "\n# Metric\n\nFiscal\u2028calendar note.\n\n* [Old](old.md) - Retired\n"
                path.write_bytes(original.replace("\n", eol).encode())
                generate(self.root, False)
                expected = original.replace("* [Old](old.md) - Retired", "* [a](a.md) - A")
                self.assertEqual(path.read_bytes(), expected.replace("\n", eol).encode())
                self.assertEqual(check_bundle(self.root), ([], []))
                self.assertEqual(generate(self.root, True)[0], [])

    def test_populated_index_requires_a_complete_link(self):
        path = self.root / "index.md"
        for line in ("* [unfinished", "* [](a.md)", "* [Daily]()", "* [ ](a.md)",
                     "```md\n* [example](a.md)\n```"):
            with self.subTest(line=line):
                path.write_text(self.metadata + "\n# Metric\n\n" + line + "\n")
                self.assertTrue(any("entries" in e for e in check_bundle(self.root)[0]))
        path.write_text(self.metadata + "\n# Metric\n\n* [Daily](a.md) - A\n")
        self.assertEqual(check_bundle(self.root), ([], []))

    def test_used_reference_links_checked_with_inline_link_rules(self):
        path = self.root / "a.md"
        path.write_text(path.read_text() +
                        "\n[Forecast][F] [Quarter][] [Year] `[Unused]`\n\n"
                        "[f]: missing.md#forecast\n[Quarter]: missing-q.md\n"
                        "[Year]: a.md\n[Unused]: unused.md\n")
        errors, warnings = check_bundle(self.root)
        self.assertFalse(errors)
        self.assertEqual(len(warnings), 2, warnings)
        for target in ("missing.md#forecast", "missing-q.md"):
            self.assertTrue(any(target in w for w in warnings), warnings)

    def test_false_and_zero_status_remain_unknown_in_report(self):
        path = self.root / "a.md"
        template = path.read_text().replace("type: Metric", "type: Metric\nstatus: {}")
        for raw in ("false", "0", "null", "[]", "''"):
            with self.subTest(raw=raw):
                path.write_text(template.format(raw))
                errors, warnings = check_bundle(self.root)
                self.assertFalse(errors)
                status = collect_report(self.root)[0]["status"]
                if raw in ("false", "0"):
                    self.assertEqual(status.lower(), raw)
                    self.assertTrue(any("'status'" in w for w in warnings))
                else:
                    self.assertEqual(status, "stable")
                    self.assertEqual(warnings, [])

    def test_malformed_root_index_stops_generation_before_any_write(self):
        index = self.root / "index.md"
        bundle(self.root, {"sub/b.md": "---\ntype: Metric\n---\n"})
        for metadata in ("---\nokf_version: '0.3'\ntitle: Finance\n",
                         "---\nokf_version: '0.3'\ntitle: [\n---\n"):
            index.write_bytes(metadata.encode())
            for flags in ([], ["--check"], ["--rebuild"]):
                with self.subTest(metadata=metadata, flags=flags):
                    result = subprocess.run(
                        [sys.executable, str(SCRIPTS / "generate_index.py"), str(self.root), *flags],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("index.md", result.stderr)
                    self.assertEqual(index.read_bytes(), metadata.encode())
                    self.assertFalse((self.root / "sub/index.md").exists())

    def test_last_removal_produces_a_valid_stable_index(self):
        index = self.root / "index.md"
        (self.root / "a.md").unlink()
        self.assertIn(index, generate(self.root, True)[0])
        generate(self.root, False)
        self.assertTrue(index.read_text().startswith(self.metadata))
        self.assertNotIn("(a.md)", index.read_text())
        self.assertEqual(generate(self.root, True)[0], [])
        self.assertEqual(check_bundle(self.root), ([], []))
        bundle(self.root, {"sub/b.md": "---\ntype: Metric\ndescription: B\n---\n"})
        self.assertTrue(any("entries" in e for e in check_bundle(self.root)[0]))
        generate(self.root, False)
        (self.root / "sub/b.md").unlink()
        generate(self.root, False)
        self.assertEqual(check_bundle(self.root), ([], []))

    def test_extensionless_computation_resources_are_checked(self):
        path = self.root / "a.md"
        path.write_text("---\ntype: Attested Computation\ndescription: A\nruntime: sql\n"
                        "attester: {resource: verify}\nexecutor: {resource: run}\n"
                        "sources: [{resource: all finance queries}]\n---\n"
                        "# Computation\n\n```sql\nSELECT 1\n```\n")
        errors, warnings = check_bundle(self.root)
        self.assertFalse(errors)
        self.assertEqual(len(warnings), 2, warnings)
        for field in ("executor.resource", "attester.resource"):
            self.assertTrue(any(field in w for w in warnings), warnings)
        bundle(self.root, {"verify": "", "run": ""})
        self.assertEqual(check_bundle(self.root), ([], []))

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

    def test_invalid_child_index_aborts_before_any_write(self):
        bundle(self.root, {"aa/a.md": (self.root / "a.md").read_text(), "zz/index.md": ""})
        damaged = self.root / "zz/index.md"
        damaged.write_bytes(b"# M\xe9trique\n")
        for check in (True, False):
            for rebuild in (True, False):
                with self.assertRaisesRegex(ValueError, "zz/index.md: invalid UTF-8"):
                    generate(self.root, check, rebuild)
                self.assertFalse((self.root / "aa/index.md").exists())
                self.assertEqual(damaged.read_bytes(), b"# M\xe9trique\n")

    def test_removed_item_takes_nested_notes_with_it(self):
        path = self.root / "index.md"
        keep = "* [Alpha](a.md) - A\n  * Alpha note\n"
        old = "* [Old](old.md) - Old\n  * Old note\n\n  Old second paragraph.\n"
        path.write_text(self.metadata + "\n# Metric\n\n" + keep + old + "\nFooter.\n")
        generate(self.root, False)
        self.assertEqual(path.read_text(), self.metadata + "\n# Metric\n\n" + keep + "\nFooter.\n")

    def test_computation_examples_do_not_supply_the_contract(self):
        path = self.root / "a.md"
        contract = "---\ntype: Attested Computation\ndescription: A\nruntime: sql\n---\n"
        for body, warning in [
            ("<!--\n# Computation\n```sql\nselect 1\n```\n-->\n", "no 'computation'"),
            ("# Computation\n<!--\n~~~sql\nselect 1\n~~~\n-->\n", "missing fenced"),
            ("Computation\n===========\n~~~sql\nselect 1\n~~~\n", "no 'computation'"),
            ("# Computation\n~~~sql\nselect 1\n", "missing fenced"),
        ]:
            with self.subTest(body=body):
                path.write_text(contract + body)
                self.assertTrue(any(warning in w for w in check_bundle(self.root)[1]))
        path.write_text(contract + "## Computation ##\n### SQL\n~~~sql\nselect 1\n~~~\n")
        self.assertEqual(check_bundle(self.root), ([], []))

    def test_changed_index_preserves_bom(self):
        path = self.root / "index.md"
        path.write_text(self.metadata + "\n# Metric\n", encoding="utf-8-sig")
        generate(self.root, False)
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(generate(self.root, True)[0], [])

    def test_linked_index_cannot_overwrite_a_concept(self):
        path = self.root / "index.md"
        concept = self.root / "a.md"
        original = concept.read_bytes()
        path.unlink()
        path.symlink_to(concept)
        with self.assertRaisesRegex(ValueError, "linked index"):
            generate(self.root, False)
        self.assertEqual(concept.read_bytes(), original)

    def test_multiline_description_remains_one_entry(self):
        bundle(self.root, {"a.md": "---\ntype: Metric\ndescription: |-\n  First\n  # Summary\n---\n"})
        generate(self.root, False, rebuild=True)
        path = self.root / "index.md"
        self.assertEqual(parse_index(path.read_text()[len(self.metadata):]),
                         [("Metric", [("a", "a.md", "First # Summary")])])
        self.assertEqual(generate(self.root, True)[0], [])

    def test_index_description_check_resolves_fragment_and_query(self):
        for suffix in ("#section", "?lang=hy", "?lang=hy#section"):
            (self.root / "index.md").write_text(self.metadata + f"\n# Metric\n\n* [A](a.md{suffix})\n")
            self.assertTrue(any("has no description" in w for w in check_bundle(self.root)[1]))

    def test_log_dates_and_legacy_citations_ignore_examples(self):
        log = self.root / "log.md"
        log.write_text("```markdown\n## 2026-01-01\n```\n")
        self.assertTrue(any("date headings" in e for e in check_bundle(self.root)[0]))
        log.write_text("## 2026-01-01 ##\n\n* Changed.\n\n```\n## Example\n```\n")
        path = self.root / "a.md"
        path.write_text(path.read_text() + "\n<!--\n# Citations\n-->\n")
        self.assertEqual(check_bundle(self.root), ([], []))

    def test_only_footnotes_in_prose_need_a_source(self):
        path = self.root / "a.md"
        path.write_text(path.read_text() + "\n    [^indented]\n\n`[^inline]` <!-- [^comment] -->\n"
                        "\\[^escaped] and [^real] and [^defined].\n\n[^defined]: Proof\n"
                        "\n~~~\n[^in-fence]\n")
        warnings = check_bundle(self.root)[1]
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("[^real]", warnings[0])

    def test_link_label_beginning_with_caret_is_not_a_footnote(self):
        path = self.root / "a.md"
        path.write_text(path.read_text() + "\nConsult [^spec](a.md) for details.\n")
        self.assertEqual(check_bundle(self.root), ([], []))
