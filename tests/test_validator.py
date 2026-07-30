"""Validator tests: known false positives, true positives, and the CLI contract."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import SCRIPTS, bundle  # must precede the script imports: adds okf/scripts to sys.path
from validate_okf import check_bundle, collect_report, trust_tier  # noqa: E402

VALIDATOR = SCRIPTS / "validate_okf.py"


class BundleCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def check(self, files, encodings=None, today=None):
        bundle(self.root, files, encodings)
        return check_bundle(self.root, today or date(2026, 7, 30))

    def assertClean(self, files, encodings=None, today=None):
        errors, warnings = self.check(files, encodings, today)
        self.assertEqual(errors, [], f"unexpected errors: {errors}")
        self.assertEqual(warnings, [], f"unexpected warnings: {warnings}")

    def assertWarningMatches(self, needle, files, **kw):
        _errors, warnings = self.check(files, **kw)
        self.assertTrue(
            any(needle in w for w in warnings),
            f"expected a warning containing {needle!r}, got {warnings}",
        )

    def assertErrorMatches(self, needle, files, **kw):
        errors, _warnings = self.check(files, **kw)
        self.assertTrue(
            any(needle in e for e in errors),
            f"expected an error containing {needle!r}, got {errors}",
        )


class FalsePositives(BundleCase):
    """Each of these was reported as a defect by an earlier version."""

    def test_bom_prefixed_concept_is_not_an_error(self):
        self.assertClean(
            {
                "index.md": "# Root\n\n* [Orders](tables/index.md) - tables\n",
                "tables/index.md": "# Tables\n\n* [Orders](orders.md) - One row per order.\n",
                "tables/orders.md": "---\ntype: BigQuery Table\ndescription: One row per order.\n---\n\nBody.\n",
            },
            encodings={"tables/orders.md": "utf-8-sig"},
        )

    def test_links_inside_an_indented_fence_are_not_checked(self):
        body = (
            "---\ntype: BigQuery Table\ndescription: One row per order.\n---\n\n"
            "1. Run this:\n\n"
            "   ```sql\n"
            "   SELECT * FROM [x](missing-target.md);\n"
            "   ```\n"
        )
        self.assertClean({
            "index.md": "# Root\n\n* [Orders](orders.md) - One row per order.\n",
            "orders.md": body,
        })

    def test_indented_and_plus_bullet_index_entries_are_recognized(self):
        self.assertClean({
            "index.md": "# Root\n\n  * [A](a.md) - first\n  + [B](b.md) - second\n",
            "a.md": "---\ntype: Metric\ndescription: first\n---\n\nBody.\n",
            "b.md": "---\ntype: Metric\ndescription: second\n---\n\nBody.\n",
        })

    def test_footnote_with_its_own_definition_is_not_dangling(self):
        """Reference bundles use numeric footnotes that define themselves rather
        than joining to a sources id."""
        self.assertClean({
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": (
                "---\ntype: Reference\ndescription: first\n---\n\n"
                "A claim.[^1]\n\n[^1]: Verified from an external doc.\n"
            ),
        })

    def test_root_index_may_declare_okf_version(self):
        self.assertClean({
            "index.md": '---\nokf_version: "0.2"\n---\n\n# Root\n\n* [A](a.md) - first\n',
            "a.md": "---\ntype: Metric\ndescription: first\n---\n\nBody.\n",
        })


class Conformance(BundleCase):
    def test_missing_type_is_an_error(self):
        self.assertErrorMatches("'type'", {
            "index.md": "# Root\n\n* [A](a.md) - x\n",
            "a.md": "---\ntitle: No type\n---\n\nBody.\n",
        })

    def test_unparseable_frontmatter_is_an_error(self):
        self.assertErrorMatches("unparseable", {
            "index.md": "# Root\n\n* [A](a.md) - x\n",
            "a.md": "---\ntype: Metric\nnot a mapping line\n---\n\nBody.\n",
        })

    def test_unknown_type_and_extra_keys_are_tolerated(self):
        self.assertClean({
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": "---\ntype: Something Nobody Registered\ndescription: first\nvendor_key: yes\n---\n\nBody.\n",
        })


class SoftGuidance(BundleCase):
    BASE = {"index.md": "# Root\n\n* [A](a.md) - first\n"}

    def concept(self, extra_frontmatter="", body="Body.\n"):
        files = dict(self.BASE)
        files["a.md"] = f"---\ntype: Metric\ndescription: first\n{extra_frontmatter}---\n\n{body}"
        return files

    def test_broken_link_warns(self):
        self.assertWarningMatches("missing concept", self.concept(body="See [gone](gone.md).\n"))

    def test_case_mismatched_link_warns_on_every_platform(self):
        files = self.concept(body="See [b](B.md).\n")
        files["b.md"] = "---\ntype: Metric\ndescription: second\n---\n\nBody.\n"
        files["index.md"] = "# Root\n\n* [A](a.md) - first\n* [B](b.md) - second\n"
        self.assertWarningMatches("missing concept", files)

    def test_legacy_timestamp_warns(self):
        self.assertWarningMatches("legacy v0.1 'timestamp'", self.concept("timestamp: 2026-07-01T00:00:00Z\n"))

    def test_legacy_citations_heading_warns(self):
        self.assertWarningMatches("# Citations", self.concept(body="# Citations\n\n[1] https://x\n"))

    def test_generated_requires_by(self):
        self.assertWarningMatches("'generated.by'", self.concept("generated: { at: 2026-07-01T00:00:00Z }\n"))

    def test_non_calendar_datetime_warns(self):
        self.assertWarningMatches("ISO 8601", self.concept("generated: { by: human:x, at: 2026-13-99T99:99:99Z }\n"))

    def test_impossible_date_warns(self):
        self.assertWarningMatches("ISO 8601", self.concept("generated: { by: human:x, at: 2026-02-30 }\n"))

    def test_unknown_status_warns(self):
        self.assertWarningMatches("'status'", self.concept("status: retired\n"))

    def test_source_entry_needs_resource(self):
        self.assertWarningMatches("no 'resource'", self.concept("sources:\n  - id: x\n    title: No resource\n"))

    def test_scope_descriptor_resource_is_not_treated_as_a_path(self):
        self.assertClean(self.concept("sources:\n  - id: x\n    resource: all queries in BigQuery project X\n"))

    def test_missing_in_bundle_path_warns(self):
        self.assertWarningMatches("missing in-bundle path", self.concept("resource: tables/nope.md\n"))

    def test_dangling_footnote_warns(self):
        self.assertWarningMatches("footnote", self.concept(body="A claim.[^nope]\n"))

    def test_footnote_matching_a_source_id_is_clean(self):
        self.assertClean(self.concept(
            "sources:\n  - id: ok\n    resource: https://x.example\n",
            body="A claim.[^ok]\n",
        ))

    def test_missing_index_warns(self):
        errors, warnings = self.check({"a.md": "---\ntype: Metric\ndescription: x\n---\n\nBody.\n"})
        self.assertEqual(errors, [])
        self.assertTrue(any("no index.md" in w for w in warnings), warnings)


class AttestedComputation(BundleCase):
    def files(self, extra="", body="Body.\n"):
        return {
            "index.md": "# Root\n\n* [C](c.md) - a computation\n",
            "c.md": f"---\ntype: Attested Computation\ndescription: a computation\n{extra}---\n\n{body}",
        }

    def test_runtime_required(self):
        self.assertWarningMatches("'runtime'", self.files(body="# Computation\n\n    SELECT 1\n"))

    def test_missing_computation_warns(self):
        self.assertWarningMatches("no 'computation' path", self.files("runtime: bigquery\n"))

    def test_inline_computation_section_satisfies_it(self):
        self.assertClean(self.files("runtime: bigquery\n", body="# Computation\n\n    SELECT 1\n"))

    def test_parameter_without_name_warns(self):
        self.assertWarningMatches("'parameters[0]'", self.files(
            "runtime: bigquery\nparameters:\n  - { type: integer, required: true }\n",
            body="# Computation\n\n    SELECT 1\n",
        ))

    def test_executor_needs_resource(self):
        self.assertWarningMatches("'executor' has no 'resource'", self.files(
            "runtime: bigquery\nexecutor:\n  receipt: [job_id]\n",
            body="# Computation\n\n    SELECT 1\n",
        ))


class TrustAndLifecycle(BundleCase):
    def test_trust_tier_unverified(self):
        self.assertEqual(trust_tier({}), "unverified")

    def test_trust_tier_machine_confirmed(self):
        self.assertEqual(
            trust_tier({"verified": [{"by": "process:nightly", "at": "2026-07-01T00:00:00Z"}]}),
            "machine-confirmed",
        )

    def test_trust_tier_human_reviewed(self):
        self.assertEqual(
            trust_tier({"verified": [
                {"by": "process:nightly", "at": "2026-07-01T00:00:00Z"},
                {"by": "human:ahormati", "at": "2026-07-02T00:00:00Z"},
            ]}),
            "human-reviewed",
        )

    def test_bare_verified_mapping_counts_as_one_element_list(self):
        self.assertEqual(trust_tier({"verified": {"by": "human:x", "at": "2026-07-01T00:00:00Z"}}),
                         "human-reviewed")

    def test_stale_after_in_the_future_is_clean(self):
        self.assertClean({
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": "---\ntype: Metric\ndescription: first\nstale_after: 2026-12-31\n---\n\nBody.\n",
        }, today=date(2026, 7, 30))

    def test_stale_after_in_the_past_warns(self):
        self.assertWarningMatches("stale since 2026-06-30", {
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": "---\ntype: Metric\ndescription: first\nstale_after: 2026-06-30\n---\n\nBody.\n",
        }, today=date(2026, 7, 30))

    def test_stale_on_the_boundary_day(self):
        """Spec §5.5: stale when today >= stale_after, so the day itself counts."""
        self.assertWarningMatches("stale since 2026-07-30", {
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": "---\ntype: Metric\ndescription: first\nstale_after: 2026-07-30\n---\n\nBody.\n",
        }, today=date(2026, 7, 30))

    def test_report_rows(self):
        bundle(self.root, {
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": (
                "---\ntype: Metric\ndescription: first\nstatus: deprecated\n"
                "stale_after: 2026-06-30\nverified: { by: human:x, at: 2026-01-01T00:00:00Z }\n---\n\nBody.\n"
            ),
        })
        rows = collect_report(self.root, date(2026, 7, 30))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tier"], "human-reviewed")
        self.assertEqual(rows[0]["status"], "deprecated")
        self.assertEqual(rows[0]["stale"], date(2026, 6, 30))


class CommandLine(BundleCase):
    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(self.root), *args],
            capture_output=True, text=True,
        )

    def test_clean_bundle_exits_zero(self):
        bundle(self.root, {
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": "---\ntype: Metric\ndescription: first\n---\n\nBody.\n",
        })
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("conformant with OKF v0.2", result.stdout)

    def test_error_exits_one(self):
        bundle(self.root, {
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": "---\ntitle: no type\n---\n\nBody.\n",
        })
        self.assertEqual(self.run_cli().returncode, 1)

    def test_strict_promotes_warnings(self):
        bundle(self.root, {
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": "---\ntype: Metric\n---\n\nBody.\n",  # no description => warning
        })
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.run_cli("--strict").returncode, 1)

    def test_missing_directory_exits_two(self):
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), str(self.root / "nope")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)

    def test_report_mode_prints_tiers_and_does_not_gate(self):
        bundle(self.root, {
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": "---\ntitle: no type\n---\n\nBody.\n",  # would be an error in check mode
        })
        result = self.run_cli("--report")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("unverified", result.stdout)

    def test_today_flag_drives_staleness(self):
        bundle(self.root, {
            "index.md": "# Root\n\n* [A](a.md) - first\n",
            "a.md": "---\ntype: Metric\ndescription: first\nstale_after: 2026-12-31\n---\n\nBody.\n",
        })
        self.assertNotIn("stale since", self.run_cli("--today", "2026-07-30").stdout)
        self.assertIn("stale since", self.run_cli("--today", "2027-01-01").stdout)

    def test_bad_today_flag_exits_two(self):
        bundle(self.root, {"a.md": "---\ntype: Metric\ndescription: x\n---\n\nBody.\n"})
        self.assertEqual(self.run_cli("--today", "not-a-date").returncode, 2)


if __name__ == "__main__":
    unittest.main()
