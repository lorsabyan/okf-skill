#!/usr/bin/env python3
"""Run the benchmark corpus through every OKF validator available and score it.

    python3 benchmark/run.py [--markdown]

Scores two things, because either alone is gameable:

  detection    — of the DEFECTS bundles, how many produce any report.
                 A validator that reports everything scores 100%.
  clean pass   — of the CLEAN bundles, how many produce nothing.
                 A validator that reports nothing scores 100%.

Only a tool that does well on both is useful. The clean half is the harder
one and the reason this benchmark exists.

Validators are discovered, not assumed. This repo's is always run; okf-reader's
independent TypeScript implementation is run when OKF_READER points at a
checkout, which is the interesting comparison — two implementations of one spec,
written separately, disagreeing where the spec is ambiguous.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from corpus import CLEAN, DEFECTS  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "okf" / "scripts" / "validate_okf.py"
# Pinned so a case built around a date does not change verdict with the calendar.
AS_OF = "2026-07-30"


def materialize(root: Path, case: dict) -> Path:
    for rel, text in case["files"].items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding=case.get("encodings", {}).get(rel, "utf-8"))
    return root


def run_okf_skill(bundle: Path) -> tuple[int, int]:
    """Returns (errors, warnings)."""
    result = subprocess.run(
        [sys.executable, str(VALIDATOR), str(bundle), "--today", AS_OF],
        capture_output=True, text=True,
    )
    errors = sum(1 for ln in result.stdout.splitlines() if ln.startswith("ERROR"))
    warnings = sum(1 for ln in result.stdout.splitlines() if ln.startswith("warning"))
    return errors, warnings


def run_okf_reader(bundle: Path) -> tuple[int, int] | None:
    """okf-reader's @okf/core CLI, when a checkout is available."""
    reader = os.environ.get("OKF_READER")
    if not reader or not shutil.which("bun"):
        return None
    cli = Path(reader) / "packages" / "okf-core" / "src" / "cli.ts"
    if not cli.is_file():
        return None
    result = subprocess.run(
        ["bun", str(cli), str(bundle)],
        capture_output=True, text=True, cwd=reader,
    )
    errors = sum(1 for ln in result.stdout.splitlines() if ln.startswith("ERROR"))
    warnings = sum(1 for ln in result.stdout.splitlines() if ln.startswith("warning"))
    return errors, warnings


VALIDATORS = {"okf-skill": run_okf_skill, "okf-reader": run_okf_reader}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--markdown", action="store_true", help="emit results.md tables")
    args = ap.parse_args()

    available = {}
    with tempfile.TemporaryDirectory() as probe:
        smoke = materialize(Path(probe) / "smoke", {"files": {"a.md": "---\ntype: Metric\ndescription: d\n---\n\nB.\n"}})
        for name, fn in VALIDATORS.items():
            if fn(smoke) is not None:
                available[name] = fn

    if not available:
        print("error: no validator available", file=sys.stderr)
        return 2

    rows: dict[str, dict] = {}
    for case_name, case in {**DEFECTS, **CLEAN}.items():
        is_defect = case_name in DEFECTS
        rows[case_name] = {"defect": is_defect, "spec": case["spec"], "why": case["why"], "results": {}}
        for vname, fn in available.items():
            with tempfile.TemporaryDirectory() as tmp:
                bundle = materialize(Path(tmp) / "b", case)
                errors, warnings = fn(bundle)
            reported = errors + warnings > 0
            if is_defect:
                # An error where a warning was expected still counts as detected;
                # severity is a policy choice the spec leaves open (§11).
                ok = reported
            else:
                ok = not reported
            rows[case_name]["results"][vname] = {"errors": errors, "warnings": warnings, "ok": ok}

    emit = emit_markdown if args.markdown else emit_text
    emit(rows, list(available))
    return 0


def _score(rows, vname, defect: bool) -> tuple[int, int]:
    subset = [r for r in rows.values() if r["defect"] is defect]
    return sum(1 for r in subset if r["results"][vname]["ok"]), len(subset)


def emit_text(rows, names) -> None:
    width = max(len(n) for n in rows)
    print(f"\n{'case':<{width}}  {'':>8}  " + "  ".join(f"{n:<12}" for n in names))
    for half, label in ((True, "DEFECT — should be reported"), (False, "CLEAN — should be silent")):
        print(f"\n  {label}")
        for name, row in rows.items():
            if row["defect"] is not half:
                continue
            cells = []
            for n in names:
                r = row["results"][n]
                mark = "ok  " if r["ok"] else "MISS" if half else "FP  "
                cells.append(f"{mark} {r['errors']}e/{r['warnings']}w".ljust(12))
            print(f"  {name:<{width}}  {row['spec']:>8}  " + "  ".join(cells))
    print()
    for n in names:
        d_hit, d_tot = _score(rows, n, True)
        c_hit, c_tot = _score(rows, n, False)
        print(f"  {n:<12} detection {d_hit}/{d_tot}   clean pass {c_hit}/{c_tot}")
    print()


def emit_markdown(rows, names) -> None:
    for half, label in ((True, "Defects — a report is expected"), (False, "Clean — silence is expected")):
        print(f"\n### {label}\n")
        print("| Case | Spec | " + " | ".join(names) + " | Why it is here |")
        print("|---|---|" + "---|" * len(names) + "---|")
        for name, row in rows.items():
            if row["defect"] is not half:
                continue
            cells = []
            for n in names:
                r = row["results"][n]
                mark = "✅" if r["ok"] else ("❌ miss" if half else "❌ false positive")
                cells.append(f"{mark} <sub>{r['errors']}e/{r['warnings']}w</sub>")
            print(f"| `{name}` | {row['spec']} | " + " | ".join(cells) + f" | {row['why']} |")
    print("\n### Score\n")
    print("| Validator | Detection | Clean pass |")
    print("|---|---|---|")
    for n in names:
        d_hit, d_tot = _score(rows, n, True)
        c_hit, c_tot = _score(rows, n, False)
        print(f"| {n} | {d_hit}/{d_tot} | {c_hit}/{c_tot} |")
    print()


if __name__ == "__main__":
    sys.exit(main())
