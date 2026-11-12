#!/usr/bin/env python3
"""TR3-9 C2 (axis 33, "which dispatch am I"): `validate_artifacts._s6_runner_half` reads the running S6 runner through
`dispatch_identity.own`. Fast: a temp story folder with `state/controller.json`, no network.

Key: `s6_runner_half_by_identity_beside_a_lane` - a named runner beside another running lane gets its own record; no name
keeps the count rule; two running and no name -> ("", []) (a doubt never skips a refusal); a name held but not fitting -> ("", []).

Run: python -B scripts/tests/test_validate_artifacts_s6_identity.py    or    python -m pytest -p no:cacheprovider scripts/tests/test_validate_artifacts_s6_identity.py -q
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(TESTS))
import dispatch_identity as DI  # noqa: E402
import validate_artifacts as V  # noqa: E402


def lane(ident, kind, cases, status="running", stage="S6", role="qa-runner"):
    return {"id": ident, "role": role, "stage": stage, "status": status, "execution_kind": kind, "manual_case_ids": cases}


class S6RunnerHalfByIdentity(unittest.TestCase):
    def half(self, dispatches, name=""):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "state").mkdir()
            (root / "work").mkdir()
            (root / "state" / "controller.json").write_text(json.dumps({"dispatches": dispatches}), encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k not in (DI.DRIVER_RUN_ENV, DI.DETECTOR_DISPATCH_ENV)}
            if name:
                env[DI.DRIVER_RUN_ENV] = name
            with mock.patch.dict(os.environ, env, clear=True):
                return V._s6_runner_half(root / "work" / "run-report.json")

    def two_lanes(self):
        return {"D1": lane("D1", "manual", ["TC-1"]), "D2": lane("D2", "manual", ["TC-2", " "])}

    def test_s6_runner_half_by_identity_beside_a_lane(self):
        # named, beside another running lane: its own record
        self.assertEqual(self.half(self.two_lanes(), name="D2"), ("manual", ["TC-2"]))
        self.assertEqual(self.half(self.two_lanes(), name="D1"), ("manual", ["TC-1"]))
        # no name, two running: ("", []) as before (the check refuses)
        self.assertEqual(self.half(self.two_lanes()), ("", []))
        # no name, one running: the count rule
        self.assertEqual(self.half({"D1": lane("D1", "automation", [])}), ("automation", []))
        # list-shaped dispatches, one running beside a finished one
        rows = [lane("D0", "automation", [], status="accepted"), lane("D1", "manual", ["TC-1"])]
        self.assertEqual(self.half(rows), ("manual", ["TC-1"]))
        # a name held but not fitting (closed, other stage, other role): ("", []), never the other lane
        beside = dict(self.two_lanes(), D3=lane("D3", "manual", ["TC-3"], status="accepted"))
        self.assertEqual(self.half(beside, name="D3"), ("", []))
        other = dict(self.two_lanes(), S5=lane("S5", "", [], stage="S5", role="builder"))
        self.assertEqual(self.half(other, name="S5"), ("", []))
        # a name this story does not hold: the count rule (two running -> none; one -> it)
        self.assertEqual(self.half(self.two_lanes(), name="elsewhere"), ("", []))
        self.assertEqual(self.half({"D1": lane("D1", "manual", ["TC-1"])}, name="elsewhere"), ("manual", ["TC-1"]))
        # no state file: ("", [])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(V._s6_runner_half(Path(tmp) / "work" / "run-report.json"), ("", []))


if __name__ == "__main__":
    unittest.main()
