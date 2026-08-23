"""Validate the upstream reference bundles — the strongest regression signal.

Skipped unless the bundles are available locally, so the suite stays offline by
default. CI clones open-knowledge-format at the pinned commit and points
OKF_REFERENCE_BUNDLES at its bundles directory.

    git clone https://github.com/GoogleCloudPlatform/open-knowledge-format
    cd open-knowledge-format && git checkout ad30107
    OKF_REFERENCE_BUNDLES=$PWD/bundles python3 -m unittest discover tests
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from helpers import bundle  # noqa: F401  adds okf/scripts to sys.path
from generate_index import generate  # noqa: E402
from validate_okf import check_bundle  # noqa: E402

BUNDLES = os.environ.get("OKF_REFERENCE_BUNDLES")
EXPECTED = ("ga4", "stackoverflow", "crypto_bitcoin", "acme_retail")

# The bundles were authored with stale_after dates in late 2026; pin the clock so
# the suite does not start failing once those pass. CI supplies the same day it
# gives the validator gate, via REFERENCE_AS_OF, so the two cannot disagree; the
# literal below is only a fallback for running the suite by hand.
AS_OF = date.fromisoformat(os.environ.get("OKF_AS_OF") or "2026-07-30")


@unittest.skipUnless(BUNDLES, "set OKF_REFERENCE_BUNDLES to the upstream bundles directory")
class ReferenceBundles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(BUNDLES or "")
        if not cls.root.is_dir():
            raise unittest.SkipTest(f"{cls.root} is not a directory")

    def each_bundle(self):
        for name in EXPECTED:
            path = self.root / name
            if path.is_dir():
                yield name, path

    def test_all_expected_bundles_present(self):
        found = [name for name, _ in self.each_bundle()]
        self.assertEqual(sorted(found), sorted(EXPECTED))

    def test_validate_with_no_errors_or_warnings(self):
        for name, path in self.each_bundle():
            with self.subTest(bundle=name):
                errors, warnings = check_bundle(path, AS_OF)
                self.assertEqual(errors, [], f"{name}: {errors}")
                self.assertEqual(warnings, [], f"{name}: {warnings}")

    def test_indexes_are_already_current(self):
        """The generator must agree with upstream's own indexes, or it would
        churn every bundle it touches."""
        for name, path in self.each_bundle():
            with self.subTest(bundle=name):
                with tempfile.TemporaryDirectory() as tmp:
                    copy = Path(tmp) / name
                    shutil.copytree(path, copy)
                    changed, unchanged = generate(copy, check=True)
                    self.assertEqual([p.name for p in changed], [], f"{name} would be rewritten")
                    self.assertTrue(unchanged)

    def test_regeneration_is_byte_identical(self):
        for name, path in self.each_bundle():
            with self.subTest(bundle=name):
                with tempfile.TemporaryDirectory() as tmp:
                    copy = Path(tmp) / name
                    shutil.copytree(path, copy)
                    generate(copy, check=False)
                    generate(copy, check=False)
                    for original in path.rglob("index.md"):
                        rewritten = copy / original.relative_to(path)
                        self.assertEqual(
                            rewritten.read_text(encoding="utf-8"),
                            original.read_text(encoding="utf-8"),
                            f"{name}/{original.relative_to(path)} changed",
                        )


if __name__ == "__main__":
    unittest.main()
