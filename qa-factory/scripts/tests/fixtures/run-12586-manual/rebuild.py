#!/usr/bin/env python3
"""Rebuild the fixture `TP1-12586/` from the recorded run (HF4-14). Not run by any test; kept so the copy is reproducible.

    python -B rebuild.py <path to the stand's artifacts/TP1-12586> <this fixture's TP1-12586 folder>

What it does (README.txt says why): copies the few files gate A needs, cuts the event log at the event BEFORE the
gate A decision (seq 46), turns every Cyrillic letter into Latin letters of the same shape (the package and its
fixtures are English, FR-30) and re-chains the events (the chain hashes every payload, so a changed word needs new
hashes), puts the three manual-agent rows' obligations back to what the strategist authored (the stand's plan was
reworked after the decision), and writes the person's words in English.
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from event_store import content_hash  # noqa: E402

CUT = 46
# the Russian alphabet by code point (0x430..0x44f): the package carries no Cyrillic character, not even in the tool
# that removes it (FR-30)
LATIN = dict(zip(map(chr, range(0x430, 0x450)),
                 ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p",
                  "r", "s", "t", "u", "f", "el", "ts", "ch", "sh", "ttl", "", "y", "", "e", "os", "ya"]))
LATIN[chr(0x451)] = "e"


def latin(text: str) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        if low in LATIN:
            word = LATIN[low]
            out.append(word.upper() if ch != low else word)
        else:
            out.append(ch)
    return "".join(out)


def walk(value):
    if isinstance(value, str):
        return latin(value)
    if isinstance(value, list):
        return [walk(v) for v in value]
    if isinstance(value, dict):
        return {walk(k): walk(v) for k, v in value.items()}
    return value


def copy_tree(source: Path, target: Path, *names: str) -> None:
    for name in names:
        src, dst = source.joinpath(*name.split("/")), target.joinpath(*name.split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        elif src.exists():
            shutil.copy(src, dst)


def main(source: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    copy_tree(source, target, "state/plan-baseline.json", "state/story-case-links.json", "state/case-versions",
              "work/test-cases", "work/question-answers.jsonl",
              "work/sources/SRC-fb6eba4fbc5e3ad00118/assessment", "work/sources/SRC-a4a01f76e6db46898144/9e64d42a381be43c")
    # the event log: events 1..CUT, English, re-chained
    previous, lines = "", []
    for line in (source / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines()[:CUT]:
        event = walk(json.loads(line))
        event.pop("event_hash")
        event["previous_hash"] = previous
        previous = event["event_hash"] = content_hash(event)
        lines.append(json.dumps(event, ensure_ascii=False))
    (target / "state").mkdir(parents=True, exist_ok=True)
    (target / "state" / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    # the other files that carried Cyrillic
    for name in ("work/source-inventory.json", "pipeline.json"):
        data = walk(json.loads((source / name).read_text(encoding="utf-8-sig")))
        if name == "pipeline.json":    # only the override the person gave BEFORE the decision exists at the cut
            data["stage_overrides"] = [o for o in data.get("stage_overrides") or [] if o.get("stage") == "S4"][:1]
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    answers = target / "work" / "question-answers.jsonl"
    answers.write_text("".join(json.dumps(walk(json.loads(line)), ensure_ascii=False) + "\n"
                               for line in answers.read_text(encoding="utf-8").splitlines() if line.strip()),
                       encoding="utf-8", newline="\n")
    # the plan as the strategist authored the three manual-agent rows (the stand's file is the reworked one)
    plan = json.loads((source / "work" / "test-plan.json").read_text(encoding="utf-8-sig"))
    for row in plan["rows"]:
        for ob in row.get("coverage_obligations") or []:
            if ob["obligation_id"] in ("OB-13", "OB-15"):
                ob["decision"] = "new"
                ob.pop("evidence_policy", None)
            elif ob["obligation_id"] == "OB-17":      # Q7 had not settled the oracle at the cut
                ob["decision"], ob["oracle_status"] = "unresolved", "unresolved"
                ob.pop("evidence_policy", None)
    (target / "work" / "test-plan.json").write_text(json.dumps(walk(plan), ensure_ascii=False, indent=1) + "\n",
                                                    encoding="utf-8", newline="\n")
    for path in target.rglob("*"):    # LF only: git stores LF, and the copy must be the bytes a clean checkout has
        if path.is_file() and b"\r\n" in path.read_bytes():
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n"))
    (target / "state" / "words").mkdir(parents=True, exist_ok=True)
    (target / "state" / "words" / "gate-a-decision.txt").write_text(
        "R-3: a\nR-5: a\nR-1: a\napprove\napprove as is\n", encoding="utf-8", newline="\n")


def proceed(target: Path) -> None:
    """`python -B rebuild.py --proceed`: apply the machine-path scrub of `run-12586-red-then/controller/build_fixture.py`
    (`machine_free`: `<home>`, `<project>`, `<project-slug>`, AR-4, t-1556 F11) to the copy already here (no stand needed),
    idempotent, and re-hash the event chain over the changed payloads. One scrub, one place: the function is that file's."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "run-12586-red-then" / "controller"))
    from build_fixture import machine_free  # noqa: E402
    for path in sorted(p for p in target.rglob("*") if p.is_file()):
        text = path.read_bytes().decode("utf-8")
        if machine_free(text) != text:
            path.write_bytes(machine_free(text).encode("utf-8"))      # bytes: no newline translation
    previous, lines = "", []
    for line in (target / "state" / "events.jsonl").read_bytes().decode("utf-8").splitlines():
        event = json.loads(line)
        event.pop("event_hash")
        event["previous_hash"] = previous
        previous = event["event_hash"] = content_hash(event)
        lines.append(json.dumps(event, ensure_ascii=False))
    (target / "state" / "events.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--proceed"]:
        proceed(Path(__file__).resolve().parent / "TP1-12586")
    else:
        main(Path(sys.argv[1]), Path(sys.argv[2]))
