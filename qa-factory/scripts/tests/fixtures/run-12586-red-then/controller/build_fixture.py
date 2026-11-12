#!/usr/bin/env python3
"""Rebuild `TP1-12586/` next to this file from the stand run (t-1541, K-R2-S of spec t-1508 5.2).

    python -B build_fixture.py <path to artifacts/TP1-12586 of the run> [cutoff event sequence, default 138]

The run state at the moment the author's plan rework `S5-qa-automator-5` was refused (28.10.2026 12:10:29 UTC): the events up to
sequence 138 (the dispatch, 12:08:44; the next event, 139, is the checkpoint at 12:12:59), `pipeline.json`, the plan and its
review receipt, the case files and their versions, and the plan critic's forms. Cyrillic is transliterated (the package is
English, FR-30), the machine path prefixes are replaced by `<home>` / `<project>` / `<project-slug>` (AR-4: no user name, no checkout
layout), and the event chain is re-hashed over the changed payloads (`event_store.content_hash`), so `EventStore.read` accepts the copy.
`--rescrub` applies only the path replacement to the copy already here."""
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from event_store import content_hash  # noqa: E402

TICKET = "TP1-12586"
LATIN = ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "h", "ts", "ch",
         "sh", "sch", "", "y", "", "e", "yu", "ya"]
LETTERS = {chr(0x430 + i): latin_form for i, latin_form in enumerate(LATIN)}   # the 32 letters of the alphabet, a..ya
LETTERS[chr(0x451)] = "e"                                                       # the letter yo


def latin(text: str) -> str:
    out = []
    for ch in text:
        low = LETTERS.get(ch.lower())
        out.append(ch if low is None else (low.capitalize() if ch != ch.lower() else low))
    return "".join(out)


SEP = r"(?:\\\\|\\|/)"          # a path separator as the bytes hold it: JSON-escaped `\\`, plain `\`, or `/`
MACHINE = [                      # (pattern, replacement): the paths of the machine the run was made on (AR-4, t-1556 F11)
    (re.compile(rf"[A-Za-z]:{SEP}Users{SEP}[^\\/\"\s]+"), "<home>"),                       # the user's home, name included
    (re.compile(rf"[A-Za-z]:{SEP}AI{SEP}Factory{SEP}[^\\/\"\s]+"), "<project>"),           # a checkout under the working root
    (re.compile(r"[A-Za-z]--[A-Za-z0-9._-]+-Factory-[A-Za-z0-9._-]+"), "<project-slug>"),                      # a transcript folder name of the host
]


def machine_free(text: str) -> str:
    """The text with every machine path prefix replaced by `<home>` / `<project>` / `<project-slug>`; the rest of the path stays."""
    for pattern, replacement in MACHINE:
        text = pattern.sub(replacement, text)
    return text


def normalize(text: str) -> str:
    return machine_free(latin(text))


def copy_text(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(normalize(src.read_text(encoding="utf-8")).encode("utf-8"))


def rechain(path: Path) -> None:
    previous, lines = "", []
    for line in path.read_bytes().decode("utf-8").splitlines():
        event = json.loads(line)
        event.pop("event_hash")
        event["previous_hash"] = previous
        previous = event["event_hash"] = content_hash(event)
        lines.append(json.dumps(event, ensure_ascii=False))
    path.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))      # LF on every platform


def rescrub() -> None:
    """`python -B build_fixture.py --rescrub`: apply `machine_free` to the copy already here (no stand needed), idempotent, and
    re-hash the event chain over the changed payloads."""
    out = Path(__file__).resolve().parent / TICKET
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        text = path.read_bytes().decode("utf-8")
        if machine_free(text) != text:
            path.write_bytes(machine_free(text).encode("utf-8"))      # bytes: no newline translation
    rechain(out / "state" / "events.jsonl")


JOBS = [    # state/execution-jobs/<name>.json of the run, all created before the cutoff (12:10 UTC): for key K-R4-6 of spec t-1508 5.4
    "1655108caf5158c71605b1b0c83cfe9e03d138d405c6f6f2465d201505863cef",    # initial, api, 05:48
    "32a19c", "48d62b",                                                       # red_probe, api (prefixes of the file names)
    "36e8ac",                                                                 # initial, api, 09:15
    "7e0475",                                                                 # repair_verify, api, 10:38: the newest ordinary one
]


def copy_jobs(run: Path) -> None:
    """The ordinary and red-probe jobs of the profile `api` that K-R4-6 reads (`ordinary_jobs(...)[0]`), scrubbed like the rest."""
    folder = run / "state" / "execution-jobs"
    for prefix in JOBS:
        (src,) = sorted(folder.glob(prefix + "*.json"))
        copy_text(src, Path(__file__).resolve().parent / TICKET / "state" / "execution-jobs" / src.name)


def main() -> None:
    if sys.argv[1:] == ["--rescrub"]:
        return rescrub()
    if len(sys.argv) == 3 and sys.argv[1] == "--jobs":      # add the jobs to the copy already here
        return copy_jobs(Path(sys.argv[2]))
    run, cutoff = Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 138
    out = Path(__file__).resolve().parent / TICKET
    if out.exists():
        shutil.rmtree(out)
    previous, lines = "", []
    for line in normalize((run / "state" / "events.jsonl").read_text(encoding="utf-8")).splitlines()[:cutoff]:
        event = json.loads(line)
        event.pop("event_hash")
        event["previous_hash"] = previous
        previous = event["event_hash"] = content_hash(event)
        lines.append(json.dumps(event, ensure_ascii=False))
    (out / "state").mkdir(parents=True)
    (out / "state" / "events.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    for rel in ("pipeline.json", "state/plan-baseline.json", "work/s5-plan.json", "work/s5-plan-reviews.json", "work/test-plan.json"):
        copy_text(run / rel, out / rel)
    for folder in ("work/test-cases", "state/case-versions"):
        for src in sorted(p for p in (run / folder).rglob("*") if p.is_file()):
            copy_text(src, out / folder / src.relative_to(run / folder))
    for src in sorted((run / "work" / "handoffs").glob("S5-qa-code-critic-*.yaml")):
        copy_text(src, out / "work" / "handoffs" / src.name)
    copy_jobs(run)


if __name__ == "__main__":
    main()
