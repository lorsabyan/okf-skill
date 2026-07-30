"""Frontmatter parser tests.

Every case here is a shape OKF v0.2 actually uses that a line-splitting parser
gets wrong. The colon-bearing values and the wrapped plain scalar are the ones
that previously produced silent data loss.
"""

from __future__ import annotations

import unittest

import helpers  # noqa: F401  must precede the script import: adds okf/scripts to sys.path
from validate_okf import parse_frontmatter  # noqa: E402


class ParseFrontmatter(unittest.TestCase):
    def parse(self, text: str):
        return parse_frontmatter(text)[0]

    def test_absent_frontmatter(self):
        self.assertIsNone(self.parse("# Just a heading\n"))

    def test_unterminated_block(self):
        self.assertIsNone(self.parse("---\ntype: Metric\n"))

    def test_empty_block(self):
        self.assertEqual(self.parse("---\n---\nbody\n"), {})

    def test_line_that_is_not_a_mapping_is_unparseable(self):
        self.assertIsNone(self.parse("---\ntype: Metric\nthis has no colon\n---\n"))

    def test_body_is_returned_after_the_block(self):
        fm, body = parse_frontmatter("---\ntype: Metric\n---\n\n# Schema\n\nrow\n")
        self.assertEqual(fm, {"type": "Metric"})
        # Trailing newline is not preserved; the body is only ever scanned.
        self.assertEqual(body, "\n# Schema\n\nrow")

    # --- values containing colons -----------------------------------------

    def test_flow_map_with_iso_datetime(self):
        fm = self.parse("---\ngenerated: { by: agent/x, at: 2026-06-30T14:00:00Z }\n---\n")
        self.assertEqual(fm["generated"], {"by": "agent/x", "at": "2026-06-30T14:00:00Z"})

    def test_actor_prefix_survives(self):
        fm = self.parse("---\nverified: { by: human:ahormati, at: 2026-06-25T09:00:00Z }\n---\n")
        self.assertEqual(fm["verified"]["by"], "human:ahormati")

    def test_quoted_title_with_colon(self):
        fm = self.parse('---\ntitle: "Incident response: freshness alert"\n---\n')
        self.assertEqual(fm["title"], "Incident response: freshness alert")

    def test_url_keeps_scheme_and_fragment(self):
        fm = self.parse("---\nresource: https://x.example/a#frag\n---\n")
        self.assertEqual(fm["resource"], "https://x.example/a#frag")

    # --- sequences ---------------------------------------------------------

    def test_flush_left_sequence(self):
        """The style upstream's serializer emits: dash at the key's own indent."""
        fm = self.parse("---\ntags:\n- ga4\n- ecommerce\n---\n")
        self.assertEqual(fm["tags"], ["ga4", "ecommerce"])

    def test_flush_left_sequence_of_block_maps(self):
        fm = self.parse(
            "---\nsources:\n- id: rev\n  resource: https://wiki/x\n  last_modified: 2026-06-15\n---\n"
        )
        self.assertEqual(fm["sources"], [
            {"id": "rev", "resource": "https://wiki/x", "last_modified": "2026-06-15"}
        ])

    def test_indented_sequence_of_block_maps(self):
        fm = self.parse(
            "---\nsources:\n  - id: a\n    resource: policies/x.md\n  - id: b\n    resource: https://y\n---\n"
        )
        self.assertEqual([e["id"] for e in fm["sources"]], ["a", "b"])
        self.assertEqual(fm["sources"][0]["resource"], "policies/x.md")

    def test_sequence_of_flow_maps(self):
        fm = self.parse(
            "---\nverified:\n  - { by: human:a, at: 2026-06-25T09:00:00Z }\n"
            "  - { by: process:nightly, at: 2026-06-26T02:00:00Z }\n---\n"
        )
        self.assertEqual([e["by"] for e in fm["verified"]], ["human:a", "process:nightly"])

    def test_inline_flow_sequence(self):
        fm = self.parse("---\ntags: [sales, orders, revenue]\n---\n")
        self.assertEqual(fm["tags"], ["sales", "orders", "revenue"])

    # --- nesting -----------------------------------------------------------

    def test_nested_block_map_with_inline_sequence(self):
        fm = self.parse(
            "---\nexecutor:\n  resource: references/skills/run.md\n"
            "  receipt: [job_id, executed_sql]\n---\n"
        )
        self.assertEqual(fm["executor"], {
            "resource": "references/skills/run.md",
            "receipt": ["job_id", "executed_sql"],
        })

    def test_parameters_as_flow_maps(self):
        fm = self.parse("---\nparameters:\n  - { name: year, type: integer, required: true }\n---\n")
        self.assertEqual(fm["parameters"][0]["name"], "year")

    def test_usage_window(self):
        fm = self.parse("---\nusage_window: { from: 2026-06-01, to: 2026-06-30 }\n---\n")
        self.assertEqual(fm["usage_window"], {"from": "2026-06-01", "to": "2026-06-30"})

    # --- scalars -----------------------------------------------------------

    def test_wrapped_plain_scalar_is_folded_not_truncated(self):
        """YAML line folding. Truncating here silently dropped half a sentence."""
        fm = self.parse(
            "---\ndescription: Obfuscated GA4 dataset emulating a web ecommerce\n"
            "  implementation of the Store.\n---\n"
        )
        self.assertEqual(
            fm["description"],
            "Obfuscated GA4 dataset emulating a web ecommerce implementation of the Store.",
        )

    def test_wrapped_scalar_does_not_swallow_the_next_key(self):
        fm = self.parse(
            "---\ndescription: One line\n  continued here.\ntype: Metric\n---\n"
        )
        self.assertEqual(fm["description"], "One line continued here.")
        self.assertEqual(fm["type"], "Metric")

    def test_literal_block_scalar(self):
        fm = self.parse("---\ndescription: |\n  Line one\n  Line two\n---\n")
        self.assertEqual(fm["description"], "Line one\nLine two")

    def test_folded_block_scalar(self):
        fm = self.parse("---\ndescription: >\n  Line one\n  Line two\n---\n")
        self.assertEqual(fm["description"], "Line one Line two")

    def test_trailing_comment_stripped(self):
        fm = self.parse("---\ntype: Metric   # a comment\n---\n")
        self.assertEqual(fm["type"], "Metric")

    def test_hash_inside_quotes_is_not_a_comment(self):
        fm = self.parse('---\ntitle: "a # b"\n---\n')
        self.assertEqual(fm["title"], "a # b")

    def test_full_line_comment_ignored(self):
        fm = self.parse("---\n# leading comment\ntype: Metric\n---\n")
        self.assertEqual(fm, {"type": "Metric"})


if __name__ == "__main__":
    unittest.main()
