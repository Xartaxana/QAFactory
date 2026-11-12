"""collect_gaps.py: the story's record of the project's test files that could not be collected (RH1-3 3.6a).

K-3.6a-*: one writer, one reader; a row per (source, profile) replaced by the last; an empty `broken` erases the key;
no file is no rows and no claim; an unreadable file is `unreadable`, never a clean history."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

import collect_gaps as G  # noqa: E402

BAD = {"path": "tests/test_bad.py", "head": "ImportError: gone"}
DIR = {"path": "tests/servicenow_budget", "head": "ModuleNotFoundError: sdk"}


def main() -> None:
    task = temp_dir("qa-collect-gaps-")
    try:
        check_eq("K-3.6a-none no file: no rows, no complaint", G.read(task), {"rows": [], "unreadable": ""})
        check_eq("K-3.6a-empty-first an empty `broken` with nothing recorded makes no file", (G.record(task, "gate_a", "api", []),
                 (task / "state" / "collect-gaps.json").exists()), ("", False))

        check_eq("K-3.6a-write a row is written", G.record(task, "gate_a", "api", [BAD, DIR], selected=3), "")
        rows = G.read(task)["rows"]
        check_eq("K-3.6a-read ... and read back whole", rows,
                 [{"source": "gate_a", "profile": "api", "broken": [BAD, DIR], "selected": 3}])
        check_eq("K-3.6a-write the file is the story's own state file, valid JSON with a schema version",
                 json.loads((task / "state" / "collect-gaps.json").read_text(encoding="utf-8"))["schema_version"], 1)
        check_eq("K-3.6a-atomic no temporary file is left behind",
                 sorted(p.name for p in (task / "state").iterdir()), ["collect-gaps.json"])

        G.record(task, "s5_collect", "api", [BAD])
        G.record(task, "gate_a", "ui", [BAD])
        check_eq("K-3.6a-key rows are keyed by (source, profile) and sorted",
                 [(r["source"], r["profile"]) for r in G.read(task)["rows"]],
                 [("gate_a", "api"), ("gate_a", "ui"), ("s5_collect", "api")])
        G.record(task, "gate_a", "api", [DIR])
        check_eq("K-3.6a-replace the last record of a key replaces the earlier one",
                 [r["broken"] for r in G.read(task)["rows"] if (r["source"], r["profile"]) == ("gate_a", "api")], [[DIR]])
        G.record(task, "gate_a", "api", [])
        check_eq("K-3.6a-erase an empty `broken` erases the key and only that key",
                 [(r["source"], r["profile"]) for r in G.read(task)["rows"]], [("gate_a", "ui"), ("s5_collect", "api")])

        G.record(task, "s5_collect", "api", [{"path": "tests\\a.py", "head": "x" * 400}, "tests/a.py", {"path": ""}, "tests/b.py"])
        got = [r for r in G.read(task)["rows"] if r["source"] == "s5_collect"][0]["broken"]
        check_eq("K-3.6a-clean backslashes become `/`, a path is kept once, an empty path is dropped, a head is capped",
                 ([b["path"] for b in got], len(got[0]["head"])), (["tests/a.py", "tests/b.py"], 180))

        G.record(task, "s5_collect", "api", [dict(BAD, owner="story"), dict(DIR, owner="project"), {"path": "tests/c.py", "owner": "nobody"}])
        got = [r for r in G.read(task)["rows"] if r["source"] == "s5_collect"][0]["broken"]
        check_eq("F4-owner a stated owner (project / story) is kept, an unknown or absent one is not invented",
                 [b.get("owner") for b in got], ["story", "project", None])
        check_eq("F4-owner ... and a record without owners reads back whole, no `owner` key (the old shape)",
                 G.record(task, "gate_a", "ui", [BAD]) or G.read(task)["rows"][0]["broken"], [BAD])

        import onboarding_probe as OP
        info = [{"check": "s5_toolchain", "message": "x", "broken_files": [BAD, DIR]},
                {"check": "other", "message": "y", "broken_files": [{"path": "z", "head": ""}]},
                {"check": "s5_toolchain", "message": "no files"}]
        check_eq("m5-reader the onboarding probe hands on the files its collect went past, whole, only the s5_toolchain's",
                 OP.left_out_files(info), [BAD, DIR])
        check_eq("m5-reader ... and none for a collect that left none out", OP.left_out_files([]), [])

        check_in("K-3.6a-source an unknown source is refused with the sources named", "gate_a",
                 G.record(task, "somewhere", "api", [BAD]))
        check_eq("K-3.6a-source ... and nothing changed", len(G.read(task)["rows"]), 2)

        (task / "state" / "collect-gaps.json").write_text("{nope", encoding="utf-8")
        got = G.read(task)
        check_eq("K-3.6a-unreadable a file that is not JSON: no rows, the reason in `unreadable`", got["rows"], [])
        check_in("K-3.6a-unreadable ... and it names the file", "collect-gaps.json", got["unreadable"])
        for label, body in (("a list", "[]"), ("rows that are not rows", '{"rows": [1]}'),
                            ("an unknown source", '{"rows": [{"source": "x", "profile": "a", "broken": []}]}')):
            (task / "state" / "collect-gaps.json").write_text(body, encoding="utf-8")
            check(f"K-3.6a-unreadable {label}: unreadable, never a clean history", bool(G.read(task)["unreadable"]))
        check_eq("K-3.6a-unreadable a record over an unreadable file replaces it", (G.record(task, "gate_a", "api", [BAD]),
                 G.read(task)["unreadable"], len(G.read(task)["rows"])), ("", "", 1))
        (task / "state" / "collect-gaps.json").write_bytes(b"\xef\xbb\xbf" + json.dumps({"rows": []}).encode())
        check_eq("K-3.6a-bom a BOM is part of the encoding", G.read(task), {"rows": [], "unreadable": ""})

        blocked = temp_dir("qa-collect-gaps-blocked-")
        (blocked / "state").write_text("a file where the folder should be", encoding="utf-8")
        check_in("K-3.6a-oserror a folder that cannot be made is a reason, not an exception", "was not written",
                 G.record(blocked, "gate_a", "api", [BAD]))
        cleanup(blocked)
    finally:
        cleanup(task)
    finish("test_collect_gaps")


if __name__ == "__main__":
    main()
