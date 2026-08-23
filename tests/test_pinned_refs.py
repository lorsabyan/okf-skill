"""The vendored upstream commit must be pinned in exactly one place.

The SHA used to be copy-pasted into five files with nothing tying them
together, so a v0.3 bump could half-happen: the spec updated, CI still checking
against the old commit, the README still citing it. SPEC.md's attribution
header is now the source of truth, CI derives the ref from it, and these tests
fail if any other file disagrees.
"""

from __future__ import annotations

import re
import unittest

from helpers import CI_YML, PINNED_REF_RE, README_MD, SPEC_MD, pinned_ref
from helpers import REPO_ROOT  # noqa: E402

TRACKED = ("README.md", "okf/references/SPEC.md", "tests/test_reference_bundles.py")


class PinnedRef(unittest.TestCase):
    def test_source_of_truth_is_a_commit_not_a_branch(self):
        ref = pinned_ref()
        self.assertRegex(ref, r"^[0-9a-f]{7,40}$")
        header = SPEC_MD.read_text(encoding="utf-8")[:600]
        self.assertNotIn("blob/main", header)
        self.assertNotIn("blob/master", header)

    def test_every_file_cites_the_same_commit(self):
        expected = pinned_ref()
        mismatches = []
        for rel in TRACKED:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            for found in PINNED_REF_RE.findall(text):
                if found != expected:
                    mismatches.append(f"{rel}: {found}")
        self.assertEqual(mismatches, [], f"expected every citation to be {expected}")

    def test_readme_cites_the_commit_at_all(self):
        """Guards the inverse of the test above: a file that stopped mentioning
        the commit would pass an all-citations-match check vacuously."""
        self.assertIn(pinned_ref(), README_MD.read_text(encoding="utf-8"))

    def test_ci_derives_the_ref_rather_than_hardcoding_it(self):
        ci = CI_YML.read_text(encoding="utf-8")
        hardcoded = re.findall(r"OKF_UPSTREAM_REF:\s*([0-9a-f]{7,40})", ci)
        self.assertEqual(hardcoded, [], "ci.yml must read the ref from SPEC.md, not pin its own copy")
        self.assertIn("okf/references/SPEC.md", ci, "ci.yml must derive the ref from the vendored spec")

    def test_ci_extraction_matches_the_python_one(self):
        """The workflow parses SPEC.md with sed; make sure that pattern yields the
        same answer as pinned_ref(), so the two cannot drift apart."""
        import subprocess

        pattern = r"s|.*blob/\([0-9a-f]\{7,40\}\)/.*|\1|p"
        result = subprocess.run(
            ["sed", "-n", pattern, str(SPEC_MD)],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout.split("\n")[0].strip(), pinned_ref())
        self.assertIn(pattern, CI_YML.read_text(encoding="utf-8"),
                      "ci.yml must use the sed pattern this test verifies")


class PinnedAsOfDate(unittest.TestCase):
    """CI pins the clock so upstream's stale_after dates passing cannot fail the
    build. The gate and the test suite must pin the same day."""

    def test_ci_defines_the_as_of_date_once(self):
        ci = CI_YML.read_text(encoding="utf-8")
        declared = re.findall(r"REFERENCE_AS_OF:\s*[\"']?(\d{4}-\d{2}-\d{2})", ci)
        self.assertEqual(len(declared), 1, "expected exactly one REFERENCE_AS_OF declaration")

    def test_ci_uses_the_variable_not_a_literal_date(self):
        ci = CI_YML.read_text(encoding="utf-8")
        literal_today = re.findall(r"--today\s+(\d{4}-\d{2}-\d{2})", ci)
        self.assertEqual(literal_today, [], "--today must reference REFERENCE_AS_OF, not a literal")

    def test_ci_passes_the_date_to_the_test_suite(self):
        self.assertIn("OKF_AS_OF", CI_YML.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
