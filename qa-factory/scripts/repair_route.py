#!/usr/bin/env python3
"""Where a critic's review sends the window: a repair round, a mechanical round, or the close.

The driver used to send every repair as `test_defect` and count rounds in a local constant, although
the critic had already written the real cause of each finding in its own form and the controller
already keeps the round ledger (B-007, FR-47). This module is the one place that reads the two
together: the review's typed findings (`work/handoffs/<critic dispatch>.yaml`: `findings[].cause`
and `findings[].blocking`) and the controller's `repair_budget`. It is a pure function - it
dispatches nothing, writes nothing - so the driver's loop and the tests read the same rule.

Import-only: no CLI.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The verdicts that send a window back to its author (the same pair the driver's loops read).
SEND_BACK = ("concerns", "review")
# Causes that are nobody's round: the author cannot repair a stand, a factory script or the
# reviewer's own mistake, so they are named and never dispatched.
NOT_ROUNDS = ("environment", "tooling", "reviewer_error")


def read_form(path):
    """The critic's form as data, or None when it is absent or does not read as a form."""
    try:
        import handoff_check
        data = handoff_check.form_view(path).data      # the form plus its waiting values file (SC1-2, B-1)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


REMARK_LIMIT = 300
ELLIPSIS = "…"


def _remark(value) -> str:
    """One remark field as a single line, whole up to REMARK_LIMIT characters; one character more is cut
    and ends with the ellipsis (the cut text is REMARK_LIMIT long, ellipsis included). The ONE cut of
    every field `findings` keeps, so the ledger and the report show the critic's own words at one length."""
    flat = " ".join(str(value if value is not None else "").split())
    return flat if len(flat) <= REMARK_LIMIT else flat[:REMARK_LIMIT - 1].rstrip() + ELLIPSIS


def findings(form) -> list:
    """The typed findings of a form: [{"id", "problem", "cause", "blocking", "file", "line", "expected",
    "fix"}], placeholders dropped.

    An unknown or missing cause reads as `test_defect` (the controller's own default for a
    receipt without one); `blocking` is true unless the reviewer wrote false. `file`, `line`, `expected`
    and `fix` are the critic's own words for the report (C1-5c): an absent field is `""`, never a
    guess, and the ledger names the absence (I4)."""
    import handoff
    # The reviewers' causes (B-364): `ticket_changed` is the driver's word, so a finding that carries it reads as
    # `test_defect` here, the safe side - a round that spends the cap, never one that hides a test's defect.
    from controller import REVIEWER_CAUSES
    rows = form.get("findings") if isinstance(form, dict) else None
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or handoff.is_placeholder(row.get("id")):
            continue
        cause = row.get("cause")
        blocking = row.get("blocking")
        out.append({"id": str(row.get("id")).strip(), "problem": _remark(row.get("problem")),
                    "cause": cause if cause in REVIEWER_CAUSES else "test_defect",
                    "blocking": not (blocking is False or str(blocking).strip().lower() == "false"),
                    "file": _remark(row.get("file")), "line": _remark(row.get("line")),
                    "expected": _remark(row.get("expected")), "fix": _remark(row.get("fix"))})
    return out


def _count(budget, key):
    value = budget.get(key) if isinstance(budget, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def route(verdict, form, budget) -> dict:
    """{"action": "test_defect" | "mechanical" | "close", "reason", "not_rounds", "note", "code"}.

    `code` is the seam reason of a close over a rejection (the R-codes, t-698 §2): "cap" (the test_defect cap is spent),
    "unknown" (the budget cannot be read), "mech_cap" (the mechanical cap is spent), "nobody" (the blocking findings are no
    author's round), "sent_back" (the verdict sent the window back naming no blocking finding), "untyped" (the verdict sent the window
    back and the form holds no typed finding at all - or no readable form); "" for every other route.

    First match wins: (a) no typed findings to read -> a close with code "untyped" when the verdict sends the
    window back (no cause is assumed), a plain close otherwise; (b) the verdict sends back
    and a blocking test_defect stands -> a test_defect round (blocking mechanical ones ride along);
    (c) a blocking mechanical finding, whatever the verdict -> the author's mechanical round (also
    when (b) found the test_defect cap used up: a window is never closed while its author is owed a
    mechanical round); (d) otherwise close. A cap that is used up closes. A budget that cannot be read closes too:
    the round count is the controller's and never a local constant."""
    verdict = str(verdict or "").strip()
    sends_back = verdict in SEND_BACK
    rows = findings(form) if form is not None else []
    blocking = [f for f in rows if f["blocking"]]
    not_rounds = [{"id": f["id"], "cause": f["cause"]} for f in blocking if f["cause"] in NOT_ROUNDS]
    counted, cap = _count(budget, "counted"), _count(budget, "cap")

    def answer(action, reason, note="", code=""):
        return {"action": action, "reason": reason, "not_rounds": not_rounds, "note": note, "code": code}

    def test_defect_round(reason, note=""):
        if counted is None or cap is None:
            return answer("close", "repair budget unknown", note, "unknown")
        if counted < cap:
            return answer("test_defect", reason, note)
        return answer("close", "cap reached", note, "cap")

    if form is None or (not rows and sends_back):
        # nothing typed to read: an approving verdict has nothing to send back. A sending-back one with no typed
        # finding is a close the site question settles (code "untyped"): no cause is ever assumed, so no round
        # is dispatched on one nobody wrote (F4, AR-28, FR-59).
        if not sends_back:
            return answer("close", "the review does not send the window back")
        return answer("close", "no typed findings", code="untyped")
    at_cap = ""
    if sends_back and any(f["cause"] == "test_defect" for f in blocking):
        found = test_defect_round("blocking test_defect finding")
        # A used-up test_defect cap does not close a window whose author is still owed a mechanical
        # round: the mechanical round spends none of that cap, so the route falls through to (c).
        if found["action"] != "close" or found["reason"] != "cap reached" \
                or not any(f["cause"] == "mechanical" for f in blocking):
            return found
        at_cap = "cap reached; "
    if any(f["cause"] == "mechanical" for f in blocking):
        mechanical, allowed = _count(budget, "mechanical"), _count(budget, "mechanical_cap")
        if mechanical is None or allowed is None:
            return answer("close", "repair budget unknown", code="unknown")
        if mechanical < allowed:
            return answer("mechanical", "blocking mechanical finding")
        return answer("close", at_cap + "mechanical cap reached — carried as a named debt",
                      code="cap" if at_cap else "mech_cap")
    if not sends_back:
        return answer("close", "the review does not send the window back")
    # A close that no seam reason explains is still a close over a rejection: either the blocking findings are
    # nobody's round, or the verdict sent the window back naming none (the seam asks in both, t-698 A8).
    return answer("close", "no blocking finding is the author's to repair", code="nobody" if not_rounds else "sent_back")
