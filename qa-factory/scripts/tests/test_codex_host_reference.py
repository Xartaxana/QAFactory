#!/usr/bin/env python3
"""`references/codex-host.md` is a small, pinned, NAMED reference (CX1-11, t-996 F-4 / B-3).

The file is shared by the nodes of codex batch 1; each node has a byte budget and the file may weigh at most their
sum. CX1-11 wrote the first 600 B; CX1-13 adds the launch-card paragraph (700 B: the pin 600 -> 1300). A reference nothing names fails `selftest.py --homes` ("nothing
loads it"), so `phases/s0.md` §10, which the orchestrator reads on every run, names it (FR-44). The cap of every
reference (`selftest.REFERENCE_MD_MAX_BYTES`) is imported, never restated.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import selftest  # noqa: E402

NODE_BUDGETS = {"CX1-11": 600, "CX1-13": 700, "CX1-14": 400}      # CX1-3 adds its own line here, in its own spec
BUDGET = sum(NODE_BUDGETS.values())
REFERENCE = PLUGIN_ROOT / "references" / "codex-host.md"


def within_budget(path: Path) -> bool:
    return len(Path(path).read_bytes()) <= BUDGET


def main():
    check("the reference exists", REFERENCE.is_file())
    body = REFERENCE.read_bytes()
    check(f"it weighs at most the sum of the node budgets ({BUDGET} B), now {len(body)} B", within_budget(REFERENCE))
    check("and the sum fits the cap every reference obeys", BUDGET <= selftest.REFERENCE_MD_MAX_BYTES)
    text = body.decode("utf-8")
    check("it is English only (FR-30)", not re.search("[" + chr(0x400) + "-" + chr(0x4ff) + "]", text))
    check("it ends with one newline and holds no control byte (FR-29)",
          text.endswith("\n") and not text.endswith("\n\n") and not re.search("[\x00-\x08\x0b-\x1f]", text))
    check("it names the door the scope refusals name", "--operation revise_plan" in text and "case_versions.py" in text)
    check("it names the launch card's door and its two answers (CX1-13)",
          all(word in text for word in ("story_step.py where", "`launch`", "`wait_start`", "`release`")))
    import launch_card
    check("it names the door of a packet committed outside `start` (CX1-14), spelt as the code spells it (FR-37)",
          "story_step.py materialize --task <T> --dispatch-id <ID>" in text
          and launch_card.materialize_door("<T>", "<ID>") in text)
    help_done = subprocess.run([sys.executable, "-B", str(SCRIPTS / "story_step.py"), "materialize", "--help"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
    check("and the command it names parses in the same install (the temporal edge: the text and the operation arrive "
          "together)", help_done.returncode == 0 and "--dispatch-id" in help_done.stdout, help_done.stderr[-300:])
    s0 = (PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s0.md").read_text(encoding="utf-8")
    check("phases/s0.md §10 names it, so something loads it (B-3)", "references/codex-host.md" in s0)

    # AT and BEYOND the budget, on a COPY of the file (never the shipped one)
    work = temp_dir("qa-codex-host-")
    try:
        copy = Path(work) / "codex-host.md"
        shutil.copyfile(REFERENCE, copy)
        copy.write_bytes((body + b"x" * BUDGET)[:BUDGET - 1] + b"\n")
        check_eq("a file AT the budget passes", (len(copy.read_bytes()), within_budget(copy)), (BUDGET, True))
        copy.write_bytes(copy.read_bytes() + b"y")
        check_eq("one byte BEYOND it does not", (len(copy.read_bytes()), within_budget(copy)), (BUDGET + 1, False))
    finally:
        cleanup(work)
    finish("test_codex_host_reference")


if __name__ == "__main__":
    main()
