"""One mutation, one test file, a byte-copy rollback: the runner behind a builder's mutation witness.

    python -B scripts/tests/mutate_once.py <spec.json> <mutation id>

The spec is a JSON file: {"target": "story_run.py", "test": "tests/test_x.py", "mutations": {"<id>": {"old": "...", "new": "..."}}};
`target` and `test` are paths under `scripts/`. The `old` text must occur in the target EXACTLY ONCE (else the run stops before
touching anything). The runner takes a byte copy of the target BEFORE the mutation, runs the ONE test file (`python -B <test>`),
restores the target FROM THE COPY in a `finally`, and prints the verbatim last line of the test, the first FAIL lines, and the
sha256 of the target before and after (builder-rules 7a; command hygiene point 7). Exit 0 when the test file FAILED (the mutation
was killed), 1 when it passed (the mutation survived), 2 when the sha256 after differs from the one before.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main(argv: list) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 64
    spec = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    mutation = spec["mutations"][argv[2]]
    target, test = SCRIPTS / spec["target"], SCRIPTS / spec["test"]
    original = target.read_bytes()
    before = sha(original)
    text = original.decode("utf-8")
    found = text.count(mutation["old"])
    if found != 1:
        print(f"--- {argv[2]}: the anchor is found {found} times, expected exactly 1; nothing was touched")
        return 64
    try:
        target.write_bytes(text.replace(mutation["old"], mutation["new"]).encode("utf-8"))
        run = subprocess.run([sys.executable, "-B", str(test)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    finally:
        target.write_bytes(original)
    after = sha(target.read_bytes())
    lines = run.stdout.splitlines()
    fails = [line for line in lines if line.startswith("FAIL")]
    summary = [line for line in lines if line.startswith("=== ")]
    last = summary[-1] if summary else f"no summary line (a crash?): {run.stderr.strip()[-200:]}"
    print(f"--- {argv[2]}: {test.name} exit={run.returncode}; {last}; FAIL lines: {len(fails)}")
    for line in fails[:3]:
        print("    " + line[:160])
    print(f"    sha256 {target.name} before {before} after {after} equal={before == after}")
    if before != after:
        return 2
    return 0 if run.returncode != 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
