#!/usr/bin/env python3
"""Materialize the sample fixture repository as a real git repository with two branches.

    python scripts/make_fixture_repo.py --out <dir> [--fixture sample-pytest-repo] [--feature qa-1]

Creates <dir> with the fixture files committed on `main`, then a `feature/<ticket>` branch with the
matching patch applied and committed. Used by the qa-onboarding / qa-story fixture runs and by evals.
The fixture itself is stored as plain files plus a patch, because a nested .git cannot be committed.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PLUGIN_ROOT / "evals" / "fixtures"


def run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="target directory (created; must not exist or be empty)")
    ap.add_argument("--fixture", default="sample-pytest-repo")
    ap.add_argument("--feature", default="qa-1", help="ticket slug; applies evals/fixtures/<fixture>.feature-<slug>.patch")
    ns = ap.parse_args()

    src = FIXTURES / ns.fixture
    out = Path(ns.out).resolve()
    if not src.is_dir():
        print(f"fixture not found: {src}", file=sys.stderr)
        return 2
    if out.exists() and any(out.iterdir()):
        print(f"target is not empty: {out}", file=sys.stderr)
        return 2
    shutil.copytree(src, out, dirs_exist_ok=True)
    run(["git", "init", "-q", "-b", "main"], out)
    run(["git", "config", "user.email", "fixture@qa-factory.local"], out)
    run(["git", "config", "user.name", "qa-factory fixture"], out)
    run(["git", "add", "-A"], out)
    run(["git", "commit", "-q", "-m", "Initial inventory sample"], out)

    patch = FIXTURES / f"{ns.fixture}.feature-{ns.feature}.patch"
    if patch.exists():
        run(["git", "checkout", "-q", "-b", f"feature/{ns.feature}"], out)
        try:
            run(["git", "apply", "--whitespace=nowarn", str(patch)], out)
        except subprocess.CalledProcessError as exc:
            # Bare `check=True` used to surface this as a raw traceback — a `git apply`
            # conflict then looked unlike the two other failures above (fixture not found,
            # target not empty), which both answer a clean `return 2`. One line, same shape.
            first_line = (exc.stderr or "").strip().splitlines()[:1]
            print(f"git apply failed: {' '.join(exc.cmd)}"
                  + (f": {first_line[0]}" if first_line else ""), file=sys.stderr)
            return 2
        run(["git", "add", "-A"], out)
        run(["git", "commit", "-q", "-m", f"{ns.feature.upper()}: items can carry tags"], out)
        run(["git", "checkout", "-q", "main"], out)
        print(f"{out}: main + feature/{ns.feature}")
    else:
        print(f"{out}: main only (no patch for {ns.feature})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
