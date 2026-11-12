"""OH2-1: every `[DEFERRED: <essence>]` marker the onboarding phases write has an `add` that writes its DD row.

A13 (audit_factory.py) pairs a marker in a project's documents with the essence cell of an OPEN
row of the backlog's Deferred decisions table. The phases are the PRODUCER of both halves: they
tell the role to write the marker (steps 2 and 5 of p4-generate.md) and the command that creates
its row (`project_decisions.py add ... --essence "<E>"`, step 8). A13 was the reader with no test
over the producer, so a phase that wrote a marker no command ever paired went unseen until a live
run (the audit detector gap of AR-22: "A13 skips topic 4").

The pairing goes through A13 ITSELF, not a copy of its predicate: every `add` found in the phases
becomes a DD row (`project_decisions.upsert`), a marker is written into a project's strategy
document, and `audit_factory.a13_deferred_decisions()` is run. The scope of "the same step" is the
whole `phases/*.md` set (a marker is written in steps 2 and 5, its row in step 8).

Runnable on its own: `python scripts/tests/test_onboarding_markers.py`.
"""
import contextlib
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import PLUGIN_ROOT, check, check_eq, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

ROOT = temp_project("qa-factory-markers-")
use_project(ROOT)

import audit_factory as A  # noqa: E402  (imported AFTER the project root is set)
import project_decisions as PD  # noqa: E402

PHASES = PLUGIN_ROOT / "skills" / "qa-onboarding" / "phases"
ELLIPSIS = chr(0x2026)

# A marker no `add` pairs, and why it may stay so. The table only SHRINKS (AR-20): a row is deleted
# by the node that gives its marker an `add`, never added without a verdict naming where it goes.
EXCEPTIONS = {
    "application repo paths": "finding plans/piles/onboarding-hooks/findings/20261021-marker-application-repo-paths-bez-komandy-add.md (OH3-2)",
}

# `project_decisions.py [--root X] add --field-ref ... --essence "<E>"`: within ONE backtick span (a
# span never crosses a command), `add` as a word followed by its own `--field-ref` (so `add-finding`
# is not one), the essence the quoted text after `--essence`. Run over whitespace-collapsed text.
ADD_COMMAND = re.compile(r'project_decisions\.py\b[^`]*?\badd\s+--field-ref\b[^`]*?--essence\s+"([^"]+)"')


def collapse(text: str) -> str:
    return " ".join(text.split())


def concrete_markers(text: str) -> set:
    """The markers a phase text writes for real: a template slot (`...`, the ellipsis char, `<...>`) is not one."""
    found = {m.group(1).strip() for m in A.DEFERRED_MARKER.finditer(text)}
    return {e for e in found if e and ELLIPSIS not in e and "..." not in e and "<" not in e}


def add_essences(text: str) -> list:
    return ADD_COMMAND.findall(collapse(text))


def unpaired_markers(texts: dict) -> list:
    """The concrete markers of `texts` (file name -> phase text) that A13 reports unpaired once every
    `add` of `texts` is a DD row. Run in a throw-away project, A13 itself judges each marker."""
    markers = sorted(set().union(*[concrete_markers(t) for t in texts.values()]))
    essences = [e for t in texts.values() for e in add_essences(t)]
    tmp = temp_dir("qa-factory-markers-run-")
    saved_root, saved_state, saved_refresh = A.project_root, A.state_dir, PD._refresh
    saved_findings = list(A.FINDINGS)
    unpaired = []
    try:
        (tmp / "qa-factory" / "strategy").mkdir(parents=True)
        PD._refresh = lambda root: None   # the dashboard projection is not what is judged here
        for n, essence in enumerate(essences, 1):
            PD.upsert(tmp, field_refs=[f"/t{n}"], essence=essence, asked="batch t: test", scope="project", owner="test")
        A.project_root, A.state_dir = (lambda: tmp), (lambda: tmp / "qa-factory")
        for marker in markers:
            (tmp / "qa-factory" / "strategy" / "test-strategy.md").write_text(f"# S\n\n[DEFERRED: {marker}]\n", encoding="utf-8")
            A.FINDINGS.clear()
            with contextlib.redirect_stdout(io.StringIO()):
                A.a13_deferred_decisions()
            if any("the marker [DEFERRED:" in f for f in A.FINDINGS):   # every A13 line about a marker says so
                unpaired.append(marker)
    finally:
        A.project_root, A.state_dir, PD._refresh = saved_root, saved_state, saved_refresh
        A.FINDINGS.clear()
        A.FINDINGS.extend(saved_findings)
        cleanup(tmp)
    return unpaired


def phase_texts() -> dict:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(PHASES.glob("*.md"))}


def test_every_phase_marker_pairs() -> None:
    texts = phase_texts()
    held = sorted(set().union(*[concrete_markers(t) for t in texts.values()]))
    check("K2-1: the phases write concrete markers at all (the collector finds them)", len(held) >= 3, str(held))
    check("K2-1: and the `add` commands with an essence (the collector finds them)",
          len([e for t in texts.values() for e in add_essences(t)]) >= 1)
    unpaired = unpaired_markers(texts)
    loose = [m for m in unpaired if m not in EXCEPTIONS]
    check_eq("K2-1: every concrete phase marker is paired by an `add` essence, or named in the exception table",
             loose, [])
    # K2-2: an exception row is a debt that must stay true: its marker is still written, and still unpaired.
    for marker, reason in EXCEPTIONS.items():
        check(f"K2-2: the exception for [{marker}] is still needed (a phase holds it, no `add` pairs it)",
              marker in held and marker in unpaired,
              "a stale exception: delete the row" if marker in held else "no phase writes this marker any more: delete the row")
        check(f"K2-2: the exception for [{marker}] names where it goes ({reason})", bool(reason.strip()))


def test_the_checker_can_fail() -> None:
    """K2-3: the negative control. A marker with no `add` is reported; the same marker with its `add` is not."""
    marker = "tracker not chosen"
    bare = {"synthetic.md": f"Write `[DEFERRED: {marker}]` where the hole is."}
    check_eq("K2-3 NEGATIVE: a phase writing a marker with no `add` anywhere is reported", unpaired_markers(bare), [marker])
    paired = {"synthetic.md": f"Write `[DEFERRED: {marker}]` there.",
              "other.md": f'Then `project_decisions.py --root . add --field-ref /tracker --essence "{marker}: config.json" '
                          '--asked "batch 1: which tracker?"`.'}
    check_eq("K2-3 POSITIVE: the marker with an `add` in ANOTHER phase file is paired", unpaired_markers(paired), [])
    wrapped = {"synthetic.md": f"`[DEFERRED: {marker}]`",
               "other.md": 'project_decisions.py add\n   --field-ref /x --essence\n   "tracker not chosen: x" --asked "q"'}
    check("K2-3: a wrapped `add` command reads as one line, and add-finding is not an `add`",
          add_essences(wrapped["other.md"]) == ["tracker not chosen: x"]
          and add_essences('`project_decisions.py add-finding --essence "x" --scope s`') == [])
    check_eq("K2-3: a template slot is not a marker", concrete_markers("[DEFERRED: <essence>] [DEFERRED: ...] [DEFERRED: " + ELLIPSIS + "]"), set())
    check_eq("K2-3: a half-paired pair - the `add` essence differs from the marker's - is reported",
             unpaired_markers({"a.md": f"[DEFERRED: {marker}]",
                               "b.md": '`project_decisions.py add --field-ref /x --essence "tracker chosen: x" --asked "q"`'}),
             [marker])


try:
    test_every_phase_marker_pairs()
    test_the_checker_can_fail()
finally:
    cleanup(ROOT)
finish("onboarding markers (OH2-1: every phase marker has its DD row)")
