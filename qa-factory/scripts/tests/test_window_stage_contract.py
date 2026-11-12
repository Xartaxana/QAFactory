"""contract.window_shape_errors / stage_closes_with: an S5 window record's form is checked
all at once, and the stage model says which role's acceptance closes a stage. The shapes
are TP2-2553's own: a window built by hand, one refusal per field; an S4 critic
accepted with `stage_complete: false`.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract as C


def _instance(iid, **extra):
    base = {"instance_id": iid, "input_hash": "h1", "outcome": "passed", "execution_fingerprint": "fp",
            "obligation_refs": [{"obligation_id": "TS-1-O1", "obligation_hash": "oh"}],
            "obligation_ids": ["TS-1-O1"], "obligation_hash": "ah", "assertion_id": "a1",
            "defect_location": "app/x.py:10", "change_disposition": "new_or_changed",
            "change_basis_ref": "manifest:TC-001", "evidence_refs": [{"path": "work/e.json", "sha256": "s"}],
            "review": {"verdict": "approved", "input_hash": "h1"}, "probe": {"verdict": "intended_failure"}}
    base.update(extra)
    return base


def _window(**extra):
    base = {"schema_version": 2, "author_dispatch_id": "S5-qa-automator-1",
            "reviewer_dispatch_id": "S5-qa-code-critic-1", "input_hash": "ih",
            "scope_instances": {"TC-001": ["test_a[x]"]}, "instances": [_instance("test_a[x]")],
            "required_quality_checks": [], "quality_receipts": []}
    base.update(extra)
    return base


class WindowShapeTests(unittest.TestCase):
    def test_a_complete_window_has_no_gaps(self):
        self.assertEqual(C.window_shape_errors(_window()), [])

    def test_every_gap_is_named_at_once(self):
        window = _window()
        del window["scope_instances"], window["quality_receipts"]
        window["instances"] = [{"instance_id": "test_a[x]", "outcome": "green"}]
        errors = C.window_shape_errors(window)
        self.assertIn("scope_instances is missing", errors)
        self.assertIn("quality_receipts is missing", errors)
        self.assertIn("test_a[x]: obligation_refs is missing", errors)
        self.assertIn("test_a[x]: review is missing", errors)
        self.assertTrue(any("outcome must be one of" in e for e in errors), errors)
        self.assertGreater(len(errors), 6)

    def test_scope_and_instances_must_agree(self):
        window = _window(scope_instances={"TC-001": ["test_a[x]", "test_b[y]"]})
        errors = C.window_shape_errors(window)
        self.assertTrue(any("missing test_b[y]" in e for e in errors), errors)
        window = _window(instances=[_instance("test_a[x]"), _instance("test_z[q]")])
        self.assertTrue(any("extra test_z[q]" in e for e in C.window_shape_errors(window)))
        # An EMPTY list for one case is not a SHAPE error any more (FB-10, TP1-13797): a
        # case the manifest carries as `impossible` or `handed_to_person` has no instance to
        # name. The rule did not go away - it moved to the layer that can see the manifest and
        # the completion, `controller.py` ("S5 window needs a nonempty exact scope_instances
        # map: ... lists no instance"), and `test_fixes_13797.py` F1 holds it there. Here the
        # shape check must let it through, or the refusal fires first and the exception can
        # never be reached.
        window = _window(scope_instances={"TC-001": []})
        errors = C.window_shape_errors(window)
        self.assertFalse(any("scope_instances must map" in e for e in errors), errors)
        # what the shape DOES still own: a map whose value is not a list at all
        broken = _window(scope_instances={"TC-001": "test_a[x]"})
        self.assertTrue(any("scope_instances must map" in e for e in C.window_shape_errors(broken)))

    def test_a_changed_instance_without_a_probe_is_named(self):
        item = _instance("test_a[x]")
        del item["probe"]
        self.assertIn("test_a[x]: probe is missing for a new_or_changed instance",
                      C.window_shape_errors(_window(instances=[item])))
        handed = dict(item, outcome="handed_to_person")
        self.assertEqual(C.window_shape_errors(_window(instances=[handed])), [])

    def test_a_blocked_instance_is_a_word_and_owes_no_probe(self):
        """t-219: the stand blocked the instance - written, reviewed, never run to a verdict. The word is the
        manifest's own (`blocked_by_env`); a blocked new_or_changed instance owes no probe, a failed one still does."""
        self.assertIn("blocked_by_env", C.WINDOW_OUTCOMES)
        item = _instance("test_a[x]", outcome="blocked_by_env", execution_fingerprint="", evidence_refs=[])
        del item["probe"]
        self.assertEqual(C.window_shape_errors(_window(instances=[item])), [])
        failed = dict(item, outcome="failed")
        self.assertIn("test_a[x]: probe is missing for a new_or_changed instance",
                      C.window_shape_errors(_window(instances=[failed])))
        stuck = C.window_shape_errors(_window(instances=[dict(item, outcome="stuck")]))
        self.assertTrue(any("outcome must be one of" in e and "blocked_by_env" in e for e in stuck), stuck)
        # the window-level list is optional for the shape: a record without it (an older build) reads as []
        self.assertEqual(C.window_shape_errors(_window(blocked_by_env=[])), [])
        self.assertEqual(C.window_shape_errors(_window()), [])

    def test_a_legacy_window_asks_only_the_legacy_fields(self):
        item = {"instance_id": "t", "input_hash": "h", "outcome": "passed", "change_disposition": "unchanged",
                "change_basis_ref": "b", "evidence_refs": [], "review": {}}
        self.assertEqual(C.window_shape_errors(_window(schema_version=1, scope_instances={"TC-001": ["t"]},
                                                       instances=[item])), [])
        self.assertEqual(C.window_shape_errors("text"), ["window is not an object"])


class StageClosureTests(unittest.TestCase):
    def test_the_stage_model_names_the_closing_role(self):
        self.assertEqual(C.stage_roles("S4"), ["qa-case-designer", "qa-case-critic"])
        self.assertTrue(C.stage_closes_with("S4", "qa-case-critic"))
        self.assertFalse(C.stage_closes_with("S4", "qa-case-designer"))
        self.assertTrue(C.stage_closes_with("S5", "qa-code-critic"))
        self.assertTrue(C.stage_closes_with("S8", "qa-bug-reporter"))
        self.assertTrue(C.stage_closes_with("S1", "qa-scout"))
        self.assertFalse(C.stage_closes_with("S0", ""))
        self.assertEqual(C.stage_roles("S99"), [])


if __name__ == "__main__":
    unittest.main()
