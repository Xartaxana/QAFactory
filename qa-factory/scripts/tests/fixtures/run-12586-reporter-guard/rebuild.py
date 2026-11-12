#!/usr/bin/env python3
"""Rebuild the fixture `TP1-12586/` from the recorded run (GB-2, HF5-18). Not run by any test; kept so the copy is reproducible.

    python -B rebuild.py <path to the stand's artifacts/TP1-12586> [<this fixture's TP1-12586 folder>]

With no source the script says so and exits 2: the fixture in the repository is already built (README.txt).

It copies `pipeline.json`, `work/ledger.json`, `work/automation-manifest.json` (bulk lists emptied) and line 1 of `state/dispatch-denials.jsonl`, turns every Cyrillic letter
into its Latin transliteration (the package and its fixtures are English, FR-30), replaces the person's gate B words by
their English twin, and replaces the stand's absolute paths by `<stand>` / `<home>` (FR-37, AR-4). The pipeline has no
hash chain, so no re-chaining is needed (the gate B fixture next door has one).
"""
import json
import re
import sys
from pathlib import Path

# the Russian alphabet by code point (0x430..0x44f): the package carries no Cyrillic character, not even here (FR-30)
LATIN = dict(zip(map(chr, range(0x430, 0x450)),
                 ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p",
                  "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
LATIN[chr(0x451)] = "e"
GATE_B_WORDS = "1) 1 and 2 are one bug\n2) I will check by hand\n3) no MR needed\n"
STAND = re.compile(r"[A-Za-z]:[\\/]+AI[\\/]+Factory[\\/]+testproject1-[\w.-]+")
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


def main(source: Path, target: Path) -> None:
    pipeline = json.loads((source / "pipeline.json").read_text(encoding="utf-8"))
    pipeline["gates"]["B"]["authorization_source"] = GATE_B_WORDS
    pipeline["reopened_by_words"] = GATE_B_WORDS
    (target / "work").mkdir(parents=True, exist_ok=True)
    (target / "pipeline.json").write_text(json.dumps(walk(pipeline), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    ledger = json.loads((source / "work" / "ledger.json").read_text(encoding="utf-8"))
    (target / "work" / "ledger.json").write_text(json.dumps(walk(ledger), indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    # rule 3 (the manifest) speaks before rule 4 for an S8 role: it reads `unresolved[]` only. The bulky lists are emptied
    # (100 KB of test rows the guard never reads); `unresolved` and `revision` stay as recorded.
    manifest = json.loads((source / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
    for key in ("tests", "then_bindings", "obligation_bindings", "runs", "plan_remarks", "deviations"):
        manifest[key] = []
    (target / "work" / "automation-manifest.json").write_text(json.dumps(walk(manifest), indent=2, ensure_ascii=True) + "\n",
                                                              encoding="utf-8")
    first = (source / "state" / "dispatch-denials.jsonl").read_text(encoding="utf-8").splitlines()[0]
    (target.parent / "dispatch-denial-line1.jsonl").write_text(json.dumps(walk(json.loads(first)), ensure_ascii=True) + "\n",
                                                               encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2 or not Path(sys.argv[1]).is_dir():
        print("the recorded run is absent: the fixture in the repository is already built (README.txt)")
        sys.exit(2)
    main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent / "TP1-12586")
