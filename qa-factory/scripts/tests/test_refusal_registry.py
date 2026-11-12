"""refusal_registry.py — A24: the registry matches the shipped sources, and every entry is
either passable by a person's word or says why it is not.

The audit is worth only as much as its scanner, so this file checks the scanner on synthetic
sources (a refusal nobody registered is caught; a registered refusal that was deleted is
caught) and then runs it against the real package, which is the regression that matters: a
refusal added to a hook without an entry fails here before it fails a live story.
"""
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, cleanup, finish, \
    run_script, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import refusal_registry as RR  # noqa: E402


def _fake_package(body: str) -> Path:
    """A throwaway <root>/scripts/stage_guard.py the scanner can be pointed at."""
    root = temp_dir("qa-factory-refusals-")
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "stage_guard.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return root


def part_scanner() -> None:
    root = _fake_package("""
        def deny(message):
            return 2

        def check_dispatch(event):
            if event:
                return deny("a brand new refusal nobody wrote down")
            raise ValueError("a raised one too")
    """)
    try:
        found = RR.sites(root)
        check_eq("the scanner sees both shapes of refusal", len(found), 2)
        check_eq("keyed by the function that refuses",
                 sorted({s["function"] for s in found}), ["check_dispatch"])
        check_in("and by the text of the refusal, without its quotes",
                 "a brand new refusal nobody wrote down", [s["call"] for s in found])
        check("a refusal with no entry is a finding",
              any("is not in refusal_registry.REGISTRY" in e for e in RR.findings(root)))
    finally:
        cleanup(root)

    # A registered refusal that has since been deleted is the other half: an entry pointing
    # at nothing tells a reader the factory still stops there when it no longer does.
    root = _fake_package("""
        def deny(message):
            return 2

        def check_dispatch(event):
            return 0
    """)
    try:
        stale = [e for e in RR.findings(root) if "the entry is stale" in e]
        check("a registered refusal that is gone is a finding", bool(stale),
              "nothing reported stale")
    finally:
        cleanup(root)


def part_live_package() -> None:
    check_eq("the shipped package has no unregistered refusal", RR.findings(PLUGIN_ROOT), [])
    p = run_script("refusal_registry.py", "--check")
    check("refusal_registry.py --check is green", p.returncode == 0,
          (p.stdout + p.stderr)[-600:])
    check_in("and names the refusals a person's word cannot pass",
             "a person's word cannot pass", p.stdout)

    # Every entry earns its place: what it refuses, the proof, and either the way through or
    # the reason there is none. "A person's word passes any block" is checked here, not
    # remembered.
    for entry in RR.REGISTRY:
        eid = entry["id"]
        check(f"{eid} names what it refuses", bool(str(entry.get("refuses") or "").strip()))
        check(f"{eid} names the test that proves it", bool(str(entry.get("test") or "").strip()))
        if not str(entry.get("override") or "").strip():
            check(f"{eid} says why no word can pass it",
                  bool(str(entry.get("unpassable_because") or "").strip()))
    check_eq("every id is unique", len({e["id"] for e in RR.REGISTRY}), len(RR.REGISTRY))

    # The two rules of the dispatch path that a person CAN pass are the ones TP1-15045 was about;
    # if either loses its waiver command the registry has stopped describing the code.
    for eid in ("SG-stage-rules", "CTRL-dispatch", "SD-stage-close"):
        entry = next(e for e in RR.REGISTRY if e["id"] == eid)
        check_in(f"{eid} names waiver.py as the way through", "waiver.py", entry["override"])

    # The profile-write refusal (t-286): registered, its door is the orchestrator's launch_check, and
    # a misspelled `call` makes A24 report the live refusal as unregistered again (negative control).
    entry = next(e for e in RR.REGISTRY if e["id"] == "PT-config-write")
    check_in("PT-config-write names the orchestrator's proof as the way through",
             "launch_check.py --profile <id>", entry["override"])
    check_in("PT-config-write names what the role reports", "launch: <cause>", entry["override"])
    saved = list(RR.REGISTRY)
    try:
        RR.REGISTRY[:] = [dict(e, call="CONFIG_WRITE_MSG.formta(what=what)") if e["id"] == "PT-config-write"
                          else e for e in saved]
        check("a misspelled PT-config-write call is a finding again",
              any("guard_pre_tool.py" in e and "CONFIG_WRITE_MSG.format(what=what)" in e
                  and "is not in refusal_registry.REGISTRY" in e for e in RR.findings(PLUGIN_ROOT)))
    finally:
        RR.REGISTRY[:] = saved

    # The combined dispatch refusal (t-868, F-1): the row names the compound call, says that the S6-S8 manifest
    # reason is one more item of it, and a misspelled call is a finding again (negative control).
    entry = next(e for e in RR.REGISTRY if e["id"] == "SG-stage-rules")
    check_eq("SG-stage-rules registers the compound deny", entry["call"], "DV.compound(blocking, prefix=")
    check_in("SG-stage-rules says the S6-S8 manifest reason is an item of the same refusal", "S6-S8", entry["refuses"])
    check_in("SG-stage-rules says one reason is one sentence", "One reason is the one sentence", entry["refuses"])
    check("SG-stage-rules is a live row (a site of check_dispatch starts with its call)",
          any(s["file"] == "stage_guard.py" and s["function"] == "check_dispatch"
              and s["call"].startswith(entry["call"]) for s in RR.sites(PLUGIN_ROOT)))
    try:
        RR.REGISTRY[:] = [dict(e, call="DV.compund(blocking, prefix=") if e["id"] == "SG-stage-rules" else e
                          for e in saved]
        check("a misspelled SG-stage-rules call is a finding again",
              any("stage_guard.py" in e and "DV.compound(blocking, prefix=" in e
                  and "is not in refusal_registry.REGISTRY" in e for e in RR.findings(PLUGIN_ROOT)))
    finally:
        RR.REGISTRY[:] = saved

    # The manifest that was not read (t-910, C4-1): the row exists, covers a live site of check_dispatch, says why no word
    # passes it, names both texts and the policy-skip world; dropping the row, or its test, is a finding (negative control).
    entry = next((e for e in RR.REGISTRY if e["id"] == "SG-manifest-unread"), None)
    check("SG-manifest-unread is registered", entry is not None)
    if entry is not None:
        for word in ("is absent", "could not be read", "pipeline.json", "skipped", "zero items"):
            check_in(f"SG-manifest-unread names `{word}`", word, entry["refuses"])
        # a person's word passes it (P13, FR-57): the row names that door and does not call the refusal unpassable
        check_in("SG-manifest-unread names the waiver door", "waiver.py", entry["override"])
        check_in("SG-manifest-unread: the pass is the standard gate_override record", "gate_override", entry["override"])
        check_eq("SG-manifest-unread is not marked unpassable", entry["unpassable_because"], "")
        check_in("SG-manifest-unread names the pinning test", "part_manifest_not_read", entry["test"])
        check("SG-manifest-unread is a live row (a site of check_dispatch starts with its call)",
              any(s["file"] == "stage_guard.py" and s["function"] == "check_dispatch"
                  and s["call"].startswith(entry["call"]) for s in RR.sites(PLUGIN_ROOT)))
        try:
            RR.REGISTRY[:] = [dict(e, function="check_dispatchh") if e["id"] == "SG-manifest-unread" else e for e in saved]
            check("a stale SG-manifest-unread row is a finding again",
                  any("SG-manifest-unread" in e and "the entry is stale" in e for e in RR.findings(PLUGIN_ROOT)))
        finally:
            RR.REGISTRY[:] = saved
    pin_src = (PLUGIN_ROOT / "scripts" / "tests" / "test_stage_guard.py").read_text(encoding="utf-8")
    check_in("the test the row names exists in test_stage_guard.py", "def part_manifest_not_read", pin_src)

    named = {Path(part.strip().split()[0]).name
             for entry in RR.REGISTRY for part in str(entry["test"]).split(",")
             if part.strip().startswith("scripts/tests/")}
    missing = sorted(n for n in named if not (PLUGIN_ROOT / "scripts" / "tests" / n).is_file())
    check("every test a registry entry names exists", not missing, f"missing: {missing}")


def part_fail_closed() -> None:
    """a refusal closed to a person's word BECAUSE a check did not run must say how it
    stops repeating itself. Without that, a defect inside the guard freezes the story where
    the person's word cannot reach it either: the same dead end, one level down."""
    closed = RR.escalations()
    check_eq("the two fail-closed refusals are the ones the plan named",
             sorted(e["id"] for e in closed), ["PT-patch-unchecked", "PT-unparsed-event"])
    for entry in closed:
        check_eq(f"{entry['id']} escalates after two in a row", entry.get("escalates_after"), 2)
        check_in(f"{entry['id']} names the factory as the owner of the diagnosis",
                 "factory", entry.get("escalation") or entry.get("unpassable_because") or "")

    # And the audit says so: an entry that is fail-closed with neither a pass nor an
    # escalation is a finding, not a silence.
    saved = list(RR.REGISTRY)
    try:
        RR.REGISTRY[:] = [dict(e, escalates_after=0, escalation="") if e["id"] == "PT-unparsed-event"
                          else e for e in saved]
        check("a fail-closed refusal with no escalation is a finding",
              any("escalates_after" in e for e in RR.findings(PLUGIN_ROOT)))
        RR.REGISTRY[:] = [dict(e, escalation="") if e["id"] == "PT-unparsed-event" else e
                          for e in saved]
        check("and `escalates_after` with nothing behind it is a finding too",
              any("no `escalation`" in e for e in RR.findings(PLUGIN_ROOT)))
    finally:
        RR.REGISTRY[:] = saved
    check_eq("the real registry is clean again", RR.findings(PLUGIN_ROOT), [])

    # a `next` answer that does not let the story move is a refusal like any other.
    entry = next(e for e in RR.REGISTRY if e["id"] == "CTRL-next-blocked")
    check_in("wait_existing_job is registered as a refusal", "wait_existing_job", entry["refuses"])
    check_in("and the way through is the person's word routed to release",
             "--operation release", entry["override"])
    check_in("carried by waiver.py", "waiver.py", entry["override"])


def main() -> None:
    part_scanner()
    part_live_package()
    part_fail_closed()
    finish("test_refusal_registry")


if __name__ == "__main__":
    main()
