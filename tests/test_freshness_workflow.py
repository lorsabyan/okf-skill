"""Tests for the upstream-freshness workflow.

The workflow files up an issue, so its failure modes are obnoxious rather than
invisible: filing a duplicate every week, or failing a build over something that
is upstream's lifecycle event. These assert the properties that prevent both,
and exercise the table formatter on real validator output — including a line
shape that would break a naive pattern.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import CI_YML, FRESHNESS_YML  # noqa: F401  adds okf/scripts to sys.path

WORKFLOW = FRESHNESS_YML.read_text(encoding="utf-8")


class WorkflowShape(unittest.TestCase):
    def test_workflow_exists(self):
        self.assertTrue(FRESHNESS_YML.is_file())

    def test_runs_on_a_schedule(self):
        """Staleness arrives with the calendar, so a push-triggered check would
        miss it entirely during a quiet month."""
        self.assertIn("schedule:", WORKFLOW)
        self.assertIn("cron:", WORKFLOW)

    def test_can_be_dispatched_manually_with_an_as_of_override(self):
        self.assertIn("workflow_dispatch:", WORKFLOW)
        self.assertIn("as_of:", WORKFLOW)

    def test_requests_issue_write_permission(self):
        self.assertIn("issues: write", WORKFLOW)

    def test_does_not_request_contents_write(self):
        """It only reads the repo; a token that could push would be more
        authority than the job needs."""
        self.assertIn("contents: read", WORKFLOW)
        self.assertNotIn("contents: write", WORKFLOW)

    def test_derives_the_pinned_ref_from_the_spec(self):
        self.assertIn("okf/references/SPEC.md", WORKFLOW)
        self.assertIn(r"s|.*blob/\([0-9a-f]\{7,40\}\)/.*|\1|p", WORKFLOW)

    def test_finds_an_existing_issue_before_creating_one(self):
        """Without the lookup this files a fresh issue every Monday."""
        self.assertIn("gh issue list", WORKFLOW)
        self.assertIn("STALENESS_LABEL", WORKFLOW)
        create_at = WORKFLOW.index("gh issue create")
        list_at = WORKFLOW.index("gh issue list")
        self.assertLess(list_at, create_at, "must look for an open issue before creating one")

    def test_refreshes_rather_than_comments_when_already_open(self):
        """Editing keeps one accurate record; a weekly comment is a weekly ping."""
        self.assertIn("gh issue edit", WORKFLOW)

    def test_closes_the_issue_when_nothing_is_stale(self):
        self.assertIn("gh issue close", WORKFLOW)

    def test_creates_its_label_idempotently(self):
        self.assertIn("gh label create", WORKFLOW)

    def test_ci_no_longer_duplicates_the_staleness_check(self):
        """Two copies of this logic is the duplication problem we just removed."""
        ci = CI_YML.read_text(encoding="utf-8")
        self.assertNotIn("::notice title=Upstream bundle stale", ci)
        self.assertIn("upstream-freshness.yml", ci, "ci.yml should point at where the check now lives")


class TableFormatter(unittest.TestCase):
    """The awk in the workflow turns --report lines into a markdown table. It
    counts fields from the end because `type` is free text of any word count and
    `status` is producer-defined, so neither can anchor a pattern."""

    AWK = None

    @classmethod
    def setUpClass(cls):
        start = WORKFLOW.index("awk '{")
        end = WORKFLOW.index("}' stale.tsv", start)
        cls.AWK = WORKFLOW[start + len("awk '"):end + 1]

    def render(self, line: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "stale.tsv"
            data.write_text(line + "\n", encoding="utf-8")
            result = subprocess.run(
                ["awk", self.AWK, str(data)], capture_output=True, text=True, check=True
            )
            return result.stdout.strip()

    def test_extracts_every_column(self):
        row = self.render(
            "acme_retail computations/revenue-ytd.md Attested Computation stable "
            "human-reviewed STALE (since 2026-12-31)"
        )
        self.assertEqual(
            row,
            "| acme_retail | `computations/revenue-ytd.md` | Attested Computation "
            "| stable | human-reviewed | 2026-12-31 |",
        )

    def test_single_word_type(self):
        row = self.render("ga4 tables/events_.md Metric draft unverified STALE (since 2026-01-02)")
        self.assertEqual(row, "| ga4 | `tables/events_.md` | Metric | draft | unverified | 2026-01-02 |")

    def test_type_containing_a_status_word_and_a_custom_status(self):
        """A pattern anchored on the words 'stable' or 'draft' mangles this; the
        positional formatter does not."""
        row = self.render("b x.md Very stable Metric retired unverified STALE (since 2026-01-02)")
        self.assertEqual(row, "| b | `x.md` | Very stable Metric | retired | unverified | 2026-01-02 |")

    def test_closing_paren_is_stripped_from_the_date(self):
        self.assertTrue(
            self.render("b x.md Metric stable unverified STALE (since 2026-01-02)").endswith("2026-01-02 |")
        )


def extract_run_block(step_name: str) -> str:
    """Pull a step's `run:` script out of the workflow, dedented.

    Extracting rather than transcribing means these tests exercise the shipped
    script; a copy would drift the first time the workflow changed."""
    at = WORKFLOW.index(f"- name: {step_name}")
    run_at = WORKFLOW.index("run: |", at) + len("run: |\n")
    lines = []
    for line in WORKFLOW[run_at:].splitlines():
        if line.strip() and not line.startswith(" " * 10):
            break
        lines.append(line[10:])
    return "\n".join(lines)


class IssueLifecycle(unittest.TestCase):
    """Run the real shell block against a stub `gh` and assert which calls it
    makes. Covers the four states the step has to distinguish."""

    SCRIPT = None

    @classmethod
    def setUpClass(cls):
        cls.SCRIPT = extract_run_block("Open, refresh, or close the staleness issue")

    def run_step(self, count: int, existing: str = ""):
        """existing: the issue number `gh issue list` should report, or '' for none."""
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            calls = work / "calls.log"
            stub = work / "bin" / "gh"
            stub.parent.mkdir()
            stub.write_text(
                "#!/bin/sh\n"
                f'echo "$@" >> "{calls}"\n'
                'if [ "$1" = "issue" ] && [ "$2" = "list" ]; then\n'
                f'  printf "%s" "{existing}"\n'
                "fi\n"
                "exit 0\n"
            )
            stub.chmod(0o755)
            (work / "stale.tsv").write_text(
                "b x.md Metric stable unverified STALE (since 2026-01-02)\n" * max(count, 0)
            )
            result = subprocess.run(
                ["bash", "-c", self.SCRIPT],
                cwd=work,
                capture_output=True,
                text=True,
                env={
                    "PATH": f"{stub.parent}:/usr/bin:/bin:/usr/sbin:/sbin",
                    "STALENESS_LABEL": "upstream-staleness",
                    "COUNT": str(count),
                    "AS_OF": "2027-01-01",
                    "KNOWLEDGE_CATALOG_REF": "3fcbb9f",
                },
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            log = calls.read_text() if calls.exists() else ""
            body = (work / "issue.md").read_text() if (work / "issue.md").exists() else ""
            return log, body, result.stdout

    def test_stale_and_no_open_issue_creates_one(self):
        log, body, _ = self.run_step(count=7)
        self.assertIn("issue create", log)
        self.assertNotIn("issue edit", log)
        self.assertNotIn("issue close", log)
        self.assertIn("| Bundle | Concept | Type | Status | Trust | Stale since |", body)
        self.assertIn("`3fcbb9f`", body)

    def test_stale_with_an_open_issue_edits_instead_of_duplicating(self):
        log, _, out = self.run_step(count=7, existing="42")
        self.assertIn("issue edit 42", log)
        self.assertNotIn("issue create", log)
        self.assertNotIn("issue comment", log)  # no weekly ping
        self.assertIn("Refreshed #42", out)

    def test_clean_with_an_open_issue_closes_it(self):
        log, _, out = self.run_step(count=0, existing="42")
        self.assertIn("issue close 42", log)
        self.assertIn("issue comment 42", log)  # says why, once
        self.assertNotIn("issue create", log)
        self.assertIn("Closed #42", out)

    def test_clean_with_no_open_issue_does_nothing(self):
        log, _, out = self.run_step(count=0)
        self.assertNotIn("issue create", log)
        self.assertNotIn("issue close", log)
        self.assertNotIn("issue comment", log)
        self.assertIn("Nothing stale", out)

    def test_label_is_created_before_it_is_used(self):
        log, _, _ = self.run_step(count=7)
        self.assertLess(log.index("label create"), log.index("issue list"))


if __name__ == "__main__":
    unittest.main()
