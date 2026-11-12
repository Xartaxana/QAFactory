#!/usr/bin/env python3
"""Rebuild the fixture `TP1-12586/` from the recorded run (GB-1a, HF5-17). Not run by any test; kept so the copy is reproducible.

    python -B rebuild.py <path to the stand's artifacts/TP1-12586> [<this fixture's TP1-12586 folder>]

With no source the script says so and exits 2: the fixture in the repository is already built (README.txt).

What it does: copies the events up to and INCLUDING the gate B decision (found by `type == decision` and
`payload.gate == B`, never by a number), turns every Cyrillic letter into Latin letters of the same shape (the package and
its fixtures are English, FR-30), replaces the person's gate B words by their English twin, replaces the stand's absolute
paths by the placeholder `<stand>` (FR-37, AR-4: the fixture is bound to no machine) and RE-CHAINS the events through
`event_store.content_hash` (the chain hashes every payload, so a changed word needs new hashes). `sequence`,
`expected_revision`, `idempotency_key`, `event_id`, `task_id` and the payload structure stay as recorded.
"""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from event_store import content_hash  # noqa: E402

# the Russian alphabet by code point (0x430..0x44f): the package carries no Cyrillic character, not even in the tool
# that removes it (FR-30)
LATIN = dict(zip(map(chr, range(0x430, 0x450)),
                 ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p",
                  "r", "s", "t", "u", "f", "el", "ts", "ch", "sh", "owe", "", "y", "", "e", "ng", "ya"]))
LATIN[chr(0x451)] = "e"
GATE_B_WORDS = "1) 1 and 2 are one bug\n2) I will check by hand\n3) no MR needed\n"
# the stand's own root and the user's home, as the journal spells them (backslashes) or a tool prints them (slashes)
STAND = re.compile(r"[A-Za-z]:[\\/]+AI[\\/]+Factory[\\/]+testproject1-dev-\d+")
HOME = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\"\s]+")


def latin(text: str) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        if low in LATIN:
            word = LATIN[low]
            out.append(word.upper() if ch != low else word)
        else:
            out.append(ch)
    return HOME.sub("<home>", STAND.sub("<stand>", "".join(out)))


def walk(value):
    if isinstance(value, str):
        return latin(value)
    if isinstance(value, list):
        return [walk(v) for v in value]
    if isinstance(value, dict):
        return {walk(k): walk(v) for k, v in value.items()}
    return value


def write_chain(events, target: Path) -> None:
    """The events (dicts without `event_hash`), chained through `event_store.content_hash` and written to the journal."""
    previous, lines = "", []
    for event in events:
        event = dict(event)
        event.pop("event_hash", None)
        event["previous_hash"] = previous
        previous = event["event_hash"] = content_hash(event)
        lines.append(json.dumps(event, ensure_ascii=False))
    (target / "state" / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def rebind_gate_a(target: Path) -> None:
    """The words and the plan were turned into English, so the bytes gate A approved changed: put the bindings of the CURRENT
    gate A decision back to what the controller computes over these files (`gate_inputs`, its own function), and re-chain.
    Without it every dispatch of the fixture is refused for 'Gate A sources changed' - a fact about the copy, not the run."""
    from controller import Controller
    events = [json.loads(line) for line in (target / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    bindings = Controller(target).gate_inputs()
    current = [e for e in events if e["type"] == "decision" and e["payload"].get("gate") == "A" and e["payload"].get("status") == "approved"][-1]
    for key in ("plan_content_hash", "plan_semantic_hash", "oracle_content_hashes", "coverage_contract_revisions",
                "lifecycle_actions_hash", "source_inventory_hash"):
        if key in bindings:
            current["payload"][key] = bindings[key]
    write_chain(events, target)


def main(source: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    events = []
    for line in (source / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        gate_b = event["type"] == "decision" and (event.get("payload") or {}).get("gate") == "B"
        event = walk(event)
        if gate_b:
            event["payload"]["authorization_source"] = GATE_B_WORDS
        events.append(event)
        if gate_b:
            break
    (target / "state" / "words").mkdir(parents=True, exist_ok=True)
    write_chain(events, target)
    ledger = walk(json.loads((source / "work" / "ledger.json").read_text(encoding="utf-8-sig")))
    (target / "work").mkdir(parents=True, exist_ok=True)
    (target / "work" / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n",
                                                 encoding="utf-8", newline="\n")
    # what `story_step.py start --stage S8 --role qa-bug-reporter` reads besides the journal (step 0 (c) of GB-1a): the plan and
    # the source inventory with the two snapshots it names; JSON in English, the rest as recorded
    for name in ("work/test-plan.json", "work/source-inventory.json", "work/automation-manifest.json"):
        data = walk(json.loads((source / name).read_text(encoding="utf-8-sig")))
        (target / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    for name in ("work/sources/SRC-fb6eba4fbc5e3ad00118/assessment", "work/sources/SRC-a4a01f76e6db46898144/9e64d42a381be43c"):
        shutil.copytree(source.joinpath(*name.split("/")), target.joinpath(*name.split("/")))
    (target / "state" / "words" / "gate-b-decision.txt").write_text(GATE_B_WORDS, encoding="utf-8", newline="\n")
    for path in target.rglob("*"):    # LF only: git stores LF, and the copy must be the bytes a clean checkout has
        if path.is_file() and b"\r\n" in path.read_bytes():
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    rebind_gate_a(target)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("rebuild.py: no source given. The fixture in the repository is already built; to rebuild it pass the stand's "
              "artifacts/TP1-12586 folder as the first argument.", file=sys.stderr)
        sys.exit(2)
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent / "TP1-12586")
