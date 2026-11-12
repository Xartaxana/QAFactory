#!/usr/bin/env python3
"""plan_row.py: one field of one plan row, and nothing else on disk.

The rule this file holds: a role changes a field of a plan row with a command, never by rewriting
the plan. On TP1-13797 two booleans on TS-19 cost $16.53 — 31 `Write` calls and 630k output
tokens across four resumptions of one session, because the only way the role knew was to write
`test-plan.json` (78 KB) and `test-plan.md` again.

SC1-3 part 2 adds the keys of the whole-row doors (spec t-1253): a row's bytes are found by parsing (K9: an `id` after a nested
object, an earlier row's nested object carrying the same `id`); `--show` takes several `--row` (K12); `--put-row` replaces one
row and nothing else (K13), only after the plan check (K14), never over bytes it did not read (K15), never an unknown id or a
row short of a field (K16), never one of two rows of the same id (K17); `--map` is the map the guard's refusal carries (K19).
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import artifact_sections as AS  # noqa: E402
import plan_row as PR  # noqa: E402

ROWS = [
    {"id": "TS-1", "disposition": "automate", "source_conflict": False, "oracle_unknown": False,
     "risk_rationale": "the one the plan already had"},
    {"id": "TS-19", "disposition": "unverifiable", "source_conflict": False, "oracle_unknown": False,
     "risk_rationale": "AC7 has no observable in this story"},
]


def run(root: Path, *args):
    proc = subprocess.run([sys.executable, "-B", str(harness.SCRIPTS / "plan_row.py"),
                           "--task", "QA-9", "--task-root", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(root), timeout=120)
    return proc.returncode, proc.stdout + proc.stderr


def main() -> None:
    root = temp_dir("qa-plan-row-")
    try:
        work = root / "work"
        work.mkdir(parents=True, exist_ok=True)
        plan = work / "test-plan.json"
        # one row per line, the shape the strategist's own writer produces
        plan.write_text("{\n \"rows\": [\n"
                        + ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in ROWS)
                        + "\n ]\n}\n", encoding="utf-8")
        (work / "test-plan.md").write_text(
            "| id | what |\n|---|---|\n| TS-19 | whether the filter is visible in the settings UI |\n",
            encoding="utf-8")
        before = plan.read_text(encoding="utf-8")

        code, out = run(root, "--row", "TS-19", "--show")
        check_eq("--show reads a row without writing", code, 0)
        check_in("and prints it", "unverifiable", out)
        check_eq("nothing was written", plan.read_text(encoding="utf-8"), before)

        code, out = run(root, "--row", "TS-19", "--set", "source_conflict=true",
                        "--set", "oracle_unknown=true")
        check_eq("two fields of one row are set", code, 0)
        check_in("the change is printed as before -> after", "source_conflict: false -> true", out)
        check_in("and it says what it did not touch", "1 other rows untouched", out)
        check_in("and it names the human's copy of the row", "test-plan.md", out)
        after = json.loads(plan.read_text(encoding="utf-8-sig"))["rows"]
        row = next(r for r in after if r["id"] == "TS-19")
        check_eq("the booleans are booleans, not the string 'true'",
                 (row["source_conflict"], row["oracle_unknown"]), (True, True))
        check_eq("the row keeps everything else it had",
                 row["risk_rationale"], "AC7 has no observable in this story")
        untouched = next(r for r in after if r["id"] == "TS-1")
        check_eq("the other row is byte-for-byte what it was", untouched, ROWS[0])
        check_in("the markdown table is not edited by code",
                 "whether the filter is visible in the settings UI",
                 (work / "test-plan.md").read_text(encoding="utf-8"))

        code, out = run(root, "--row", "TS-19", "--set", "source_conflict=true")
        check_eq("setting what is already set writes nothing", code, 0)
        check_in("and says so", "already exactly that", out)

        code, out = run(root, "--row", "TS-42", "--set", "source_conflict=true")
        check_eq("an unknown row is refused", code, 2)
        check_in("and the refusal lists the rows there are", "TS-19", out)
        code, out = run(root, "--row", "TS-19", "--set", "invented_field=true")
        check_eq("a field the row does not have is refused", code, 2)
        check_in("and the refusal lists the fields it does have", "disposition", out)
        check_not_in("no traceback reaches the role", "Traceback", out)

        code, out = run(root, "--row", "TS-19", "--set", "disposition=skip")
        check_eq("a non-boolean value is written as the string it is", code, 0)
        after = json.loads(plan.read_text(encoding="utf-8-sig"))["rows"]
        check_eq("disposition is the word, not True",
                 next(r for r in after if r["id"] == "TS-19")["disposition"], "skip")
    finally:
        cleanup(root)
    whole_rows()
    finish("test_plan_row")


def valid(i, **more) -> dict:
    """A row that passes `planning_contract.validate_plan` (the plan check `--put-row` runs on its candidate)."""
    row = {"id": f"TS-{i}", "impact": "medium", "likelihood": "medium", "confidence": "medium", "risk_rationale": "why",
           "risk_source_refs": ["R-1"], "risk_policy_revision": "r1", "coverage_refs": ["R-1"], "unknowns": [],
           "verification_depth": "normal", "required_scenarios": ["s"], "test_level_rationale": "lvl",
           "design_review_required": False, "note": f"note {i}"}
    row.update(more)
    return row


def pretty(rows: list, **top) -> str:
    return json.dumps({"rows": rows, **top}, ensure_ascii=False, indent=1) + "\n"


def place(root: Path, data) -> Path:
    plan = root / "work" / "test-plan.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))      # bytes: write_text turns \n into CRLF on Windows
    return plan


def rows_of(plan: Path) -> list:
    return json.loads(plan.read_bytes().decode("utf-8-sig"))["rows"]


def whole_rows() -> None:
    root = temp_dir("qa-plan-row-whole-")
    try:
        # ---- K9: the bytes a write lands on are the row's own (both shapes of the old defect) ------------------------------------
        nested_first = [valid(1), valid(2), valid(3, note="c")]
        nested_first[2] = {"meta": {"x": 1}, **nested_first[2]}                  # `id` comes AFTER a nested object, in its own row
        plan = place(root, pretty(nested_first))
        code, out = run(root, "--row", "TS-3", "--set", "note=changed")
        check_eq("K9 --set on a row whose id follows a nested object succeeds", code, 0)
        got = rows_of(plan)
        check_eq("K9 the nested object is still where it was (the old code wrote over it)", got[2]["meta"], {"x": 1})
        check_eq("K9 and the field changed is the row's own", (got[2]["id"], got[2]["note"]), ("TS-3", "changed"))
        check_eq("K9 the other rows are what they were", got[:2], nested_first[:2])

        carrier = [valid(1, ref={"id": "TS-3"}), valid(2), valid(3)]            # an EARLIER row's nested object carries the target id
        plan = place(root, pretty(carrier))
        code, out = run(root, "--row", "TS-3", "--set", "note=changed")
        got = rows_of(plan)
        check_eq("K9 --set on TS-3 where TS-1 carries a nested {id: TS-3}: TS-1 is untouched (the old code wrote into it)", got[0], carrier[0])
        check_eq("K9 and TS-3 is the row changed", got[2]["note"], "changed")
        code, out = run(root, "--add-row", json.dumps(valid(4)))
        check_eq("K9 --add-row after such rows keeps the file readable and puts the row last", (code, [r["id"] for r in rows_of(plan)]), (0, ["TS-1", "TS-2", "TS-3", "TS-4"]))

        # ---- K12: --show with several --row; E-1; E-2 ---------------------------------------------------------------------------
        base = [valid(i) for i in range(1, 6)]
        text = pretty(base, lifecycle_actions=[])
        plan = place(root, text)
        code, out = run(root, "--show", "--row", "TS-2", "--row", "TS-4")
        spans = {rid: (first, last) for _, rid, _, _, first, last in AS.plan_rows_indexed(text)[1]}
        lines = text.split("\n")
        check_eq("K12 --show --row A --row B exits 0", code, 0)
        for rid, index in (("TS-2", 1), ("TS-4", 3)):
            first, last = spans[rid]
            want = f"{rid} (rows[{index}], lines {first}-{last})\n" + "\n".join(lines[first - 1:last]).rstrip(",")
            check_in(f"K12 {rid} is printed under its header with the very lines of the file", want, out)
        check_not_in("K12 and a row nobody asked for is not printed", "note 3", out)
        before = plan.read_bytes()
        code, out = run(root, "--show", "--row", "TS-2", "--row", "TS-99")
        check_eq("K12/E-1 one unknown id refuses the whole call", code, 2)
        check_not_in("K12/E-1 and prints no part of the others", "note 2", out)
        check_in("K12/E-1 and lists the ids there are", "ids there: TS-1, TS-2, TS-3, TS-4, TS-5", out)
        check_eq("K12 nothing is written", plan.read_bytes(), before)
        for count, expect_more in ((20, False), (21, True)):
            place(root, pretty([valid(i) for i in range(1, count + 1)]))
            code, out = run(root, "--show", "--row", "TS-999")
            check_eq(f"K12/E-2 {count} rows: the refusal lists TS-20 and {'one more' if expect_more else 'no more'}",
                     ("TS-20" in out, "and 1 more" in out, "TS-21," in out), (True, expect_more, False))
        for count, expect_more in ((20, False), (21, True)):          # F-3 (t-1286): --set on an unknown id says the same as --show
            place(root, pretty([valid(i) for i in range(1, count + 1)]))
            code, out = run(root, "--row", "TS-999", "--set", "note=x")
            check_eq(f"K12/F-3 --set on an unknown id, {count} rows: refused, names the id, lists TS-20 and {'one more' if expect_more else 'no more'}",
                     (code, "no row `TS-999` in test-plan.json" in out, "TS-20" in out, "and 1 more" in out, "TS-21," in out),
                     (2, True, True, expect_more, False))
        place(root, pretty(base))
        code, out = run(root, "--row", "TS-2")
        check_in("K12 --row alone still shows the row (the old call)", "note 2", out)
        check_eq("K12 --set with two --row is a usage refusal", run(root, "--row", "TS-1", "--row", "TS-2", "--set", "note=x")[0], 2)
        check_eq("K12 --show with --set is a usage refusal", run(root, "--show", "--row", "TS-1", "--set", "note=x")[0], 2)
        check_eq("K12 --show with no row is a usage refusal", run(root, "--show")[0], 2)

        one_line = '{"rows": [' + ", ".join(json.dumps(valid(i)) for i in (1, 2)) + "]}"
        place(root, one_line)
        code, out = run(root, "--show", "--row", "TS-2")
        check_in("K12/E-4 a file of one line: the row is shown by its own bytes, and the header says why", "lines 1-1; it shares its line with other bytes", out)
        check_in("K12/E-4 (the bytes of that row)", json.dumps(valid(2)), out)
        check_not_in("K12/E-4 (and not the other row's)", "note 1", out)

        # ---- K19: --map ---------------------------------------------------------------------------------------------------------
        plan = place(root, text)
        code, out = run(root, "--map")
        check_eq("K19 --map prints the map the guard carries (one function)", (code, out.strip()), (0, AS.section_map_text(plan, "plan_rows")))
        check_in("K19 with each row's lines", f"TS-2 {spans['TS-2'][0]}-{spans['TS-2'][1]}", out)
        place(root, "{not json")
        code, out = run(root, "--map")
        check_eq("K19 a plan that is no JSON gets no map, a refusal with the door", (code, "Read" in out and "offset" in out), (2, True))
        check_eq("K19 --map with --set is a usage refusal", run(root, "--map", "--row", "TS-1", "--set", "note=x")[0], 2)

        # ---- K13: --put-row changes ONE row and nothing else ---------------------------------------------------------------------
        formats = (("indent=1", lambda t: t.encode("utf-8")),
                   ("compact, a row a line", lambda t: ('{\n "rows": [\n' + ",\n".join(json.dumps(r, separators=(",", ":")) for r in base)
                                                    + "\n ]\n}\n").encode("utf-8")),
                   ("CRLF and a byte-order mark", lambda t: b"\xef\xbb\xbf" + t.replace("\n", "\r\n").encode("utf-8")))
        for label, make in formats:
            plan = place(root, make(text))
            old = plan.read_bytes()
            old_rows = rows_of(plan)
            new = dict(old_rows[2], note="the replaced row", risk_rationale="a new reason")
            code, out = run(root, "--put-row", json.dumps(new))
            check_eq(f"K13 [{label}] --put-row exits 0", code, 0)
            now = plan.read_bytes()
            check_eq(f"K13 [{label}] the document, but for that one row, is what it was", rows_of(plan), old_rows[:2] + [new] + old_rows[3:])
            decoded_old, decoded_now = old.decode("utf-8-sig"), now.decode("utf-8-sig")
            start, end = PR.row_span(decoded_old, "TS-3")
            tail = len(decoded_old) - end
            check_eq(f"K13 [{label}] the bytes before the row are identical", decoded_now[:start], decoded_old[:start])
            check_eq(f"K13 [{label}] the bytes after the row are identical", decoded_now[len(decoded_now) - tail:], decoded_old[end:])
            check_eq(f"K13 [{label}] the byte-order mark is kept, or still absent", now.startswith(b"\xef\xbb\xbf"), old.startswith(b"\xef\xbb\xbf"))
            if "CRLF" in label:
                check_eq(f"K13 [{label}] no bare line feed was written", now.count(b"\n"), now.count(b"\r\n"))
            check_in(f"K13 [{label}] it prints the fields that changed as field: old -> new", 'TS-3.note: "note 3" -> "the replaced row"', out)
            check_in(f"K13 [{label}] and says how many rows it left", "4 other rows untouched", out)
            code, out = run(root, "--put-row", json.dumps(new))
            check_in(f"K13 [{label}] the same row again writes nothing", "already exactly that", out)
            check_eq(f"K13 [{label}] (the bytes stay)", plan.read_bytes(), now)
        row_file = root / "row.json"
        row_file.write_text(json.dumps(dict(base[0], note="from a file")), encoding="utf-8")
        plan = place(root, text)
        check_eq("K13 the row may come from a file", run(root, "--put-row", str(row_file))[0], 0)
        check_eq("K13 (and it is written)", rows_of(plan)[0]["note"], "from a file")

        # ---- K14: the plan check, before the replace ------------------------------------------------------------------------------
        plan = place(root, text)
        before = plan.read_bytes()
        code, out = run(root, "--put-row", json.dumps(dict(base[1], verification_depth="bad")))
        check_eq("K14 a row the plan check refuses is refused", code, 2)
        check_in("K14 the refusal names the row and the reason", "TS-2: invalid verification depth", out)
        check_eq("K14 and the file is byte for byte what it was", plan.read_bytes(), before)
        broken = [valid(1, risk_rationale=""), valid(2), valid(3)]                      # ANOTHER row was invalid before
        plan = place(root, pretty(broken))
        code, out = run(root, "--put-row", json.dumps(valid(2, note="right")))
        check_eq("K14 a right row is written although another row of the plan was already invalid", code, 0)
        check_in("K14 and the old error is printed as a WARN, not hidden", "WARN: the plan already had 1 error(s) outside row TS-2", out)
        check_in("K14 (naming it)", "TS-1: empty risk_rationale", out)
        check_eq("K14 (the row is in)", rows_of(plan)[1]["note"], "right")
        # F-1 (t-1286): an obligation's error is named by the OBLIGATION (`OB-1: ...`), not by the row - it is the row's own all the same
        ob_row = valid(2, schema_version=2, coverage_obligations=[{"obligation_id": "OB-1"}], note="mine")
        plan = place(root, pretty([valid(1), ob_row]))
        before = plan.read_bytes()
        code, out = run(root, "--put-row", json.dumps(dict(ob_row, note="changed")))
        check_eq("K14/F-1 a row whose own obligation is invalid (OB-1: ...) is refused, not passed with a WARN", code, 2)
        check_in("K14/F-1 the refusal names the row and the obligation's error", "row TS-2 would not pass the plan check: OB-1: missing behavior", out)
        check_not_in("K14/F-1 and says nothing of errors 'outside row TS-2'", "outside row TS-2", out)
        check_eq("K14/F-1 (the file is what it was)", plan.read_bytes(), before)
        plan = place(root, pretty([valid(1, schema_version=2, coverage_obligations=[{"obligation_id": "OB-1"}]), valid(3), valid(2)]))
        code, out = run(root, "--put-row", json.dumps(valid(2, note="right")))
        check_eq("K14/F-1 control: the same obligation error in ANOTHER row is a WARN and the right row is written",
                 (code, "outside row TS-2" in out, rows_of(plan)[2]["note"]), (0, True, "right"))
        # Q-4: the controller gate's require_v2, read from the story's state like the controller does
        plan = place(root, pretty([valid(1), valid(2)]))
        (root / "state").mkdir(exist_ok=True)
        (root / "state" / "controller.json").write_text(json.dumps({"coverage_contract_version": 2}), encoding="utf-8")
        before = plan.read_bytes()
        code, out = run(root, "--put-row", json.dumps(valid(2, note="v2 story")))
        check_eq("K14/Q-4 a story at coverage version 2: a row with no schema_version 2 is refused", code, 2)
        check_in("K14/Q-4 (naming the reason)", "TS-2: coverage schema version 2 required", out)
        check_eq("K14/Q-4 (nothing written)", plan.read_bytes(), before)
        (root / "state" / "controller.json").unlink()
        code, out = run(root, "--put-row", json.dumps(valid(2, note="v1 story")))
        check_eq("K14/Q-4 control: with no state of the story (version 1) the same row is written", (code, rows_of(plan)[1]["note"]), (0, "v1 story"))
        import planning_contract as PC
        was = PC.validate_plan
        try:
            two, two_x = [{"id": "A"}, {"id": "B"}], [{"id": "A", "x": 1}, {"id": "B"}]
            PC.validate_plan = lambda rows, require_v2=False: ["a new error of the whole plan"] if len(rows) == 2 and rows[0].get("x") else []
            check_in("K14 an error elsewhere that was NOT there before refuses the write",
                     "would add plan errors that were not there: a new error of the whole plan", PR._plan_check(two, two_x, "A"))
            PC.validate_plan = lambda rows, require_v2=False: ["B: an old error of another row"] if len(rows) == 2 else []
            check_eq("K14 (and an error elsewhere that was there before is no refusal)", PR._plan_check(two, two_x, "A"), "")
            seen = []
            PC.validate_plan = lambda rows, require_v2=False: seen.append(require_v2) or []
            PR._plan_check(two, two_x, "A", True)
            check_eq("K14/Q-4 the controller gate's require_v2 reaches every validate_plan call", (bool(seen), all(seen)), (True, True))
            PC.validate_plan = lambda rows, require_v2=False: (_ for _ in ()).throw(RuntimeError("boom"))
            check_in("K14 a plan check that cannot run is no pass", "could not run on the candidate (RuntimeError)", PR._plan_check([], [], "A"))
        finally:
            PC.validate_plan = was

        # ---- K15: bytes changed between the read and the write -----------------------------------------------------------------
        plan = place(root, text)
        raw = plan.read_bytes()
        rows = rows_of(plan)
        md = root / "work" / "test-plan.md"
        elsewhere = pretty([dict(r, note=r["note"] + " (edited by the role meanwhile)") for r in base]).encode("utf-8")
        was_check = PR._plan_check
        try:
            PR._plan_check = lambda before, after, rid, v2=False: plan.write_bytes(elsewhere) and ""          # the role's Edit lands before the write
            code = PR.put_row(plan, md, raw, raw.decode("utf-8"), rows, json.dumps(dict(base[2], note="mine")))
        finally:
            PR._plan_check = was_check
        check_eq("K15 bytes changed between the read and the write: refused", code, 2)
        check_eq("K15 and the other writer's bytes stand, nothing of ours is in the file", plan.read_bytes(), elsewhere)
        check_in("K15 the refusal says to read again", "the plan changed while this ran; read it again", PR._write_plan(plan, raw, "x"))
        plan = place(root, text)
        check_eq("K15 the control: the same call over untouched bytes writes", PR.put_row(plan, md, plan.read_bytes(), text, rows, json.dumps(dict(base[2], note="mine"))), 0)

        # ---- K16: an id the plan does not have; a row short of a field --------------------------------------------------------------
        plan = place(root, text)
        before = plan.read_bytes()
        code, out = run(root, "--put-row", json.dumps(valid(9)))
        check_eq("K16 an unknown id is refused, not appended", code, 2)
        check_in("K16 and the refusal points at --add-row", "to append a new row use `--add-row`", out)
        short = {k: v for k, v in base[1].items() if k != "note"}
        code, out = run(root, "--put-row", json.dumps(short))
        check_eq("K16 a row short of a field every other row carries is refused", code, 2)
        check_in("K16 and names the field", "carries note", out)
        code, out = run(root, "--put-row", "{not json")
        check_eq("K16 text that is no JSON is refused", code, 2)
        code, out = run(root, "--put-row", json.dumps({"note": "no id"}))
        check_in("K16 a row with no id is refused", "carries no `id`", out)
        code, out = run(root, "--put-row", json.dumps([1, 2]))
        check_eq("K16 a JSON that is not a row object is refused", code, 2)
        check_eq("K16 nothing was written by any of them", plan.read_bytes(), before)
        code, out = run(root, "--put-row", json.dumps(dict(base[1], id=2)))
        check_eq("K16 a row that changes the id is refused", code, 2)
        check_eq("K16 (nothing written)", plan.read_bytes(), before)

        # ---- K17: the same id on two rows is never picked --------------------------------------------------------------------------
        twice = [valid(1), valid(2), valid(2, note="the second TS-2")]
        plan = place(root, pretty(twice))
        before = plan.read_bytes()
        code, out = run(root, "--put-row", json.dumps(valid(2, note="x")))
        check_eq("K17 --put-row on an id that two rows carry is refused", code, 2)
        check_in("K17 and names both rows", "rows[1]", out)
        check_in("K17 (the second)", "rows[2]", out)
        code, out = run(root, "--row", "TS-2", "--set", "note=x")
        check_eq("K17 --set on such an id is refused too", code, 2)
        code, out = run(root, "--show", "--row", "TS-2")
        check_eq("K17 --show prints both, each under its own place", (code, "rows[1]" in out, "rows[2]" in out, "the second TS-2" in out), (0, True, True, True))
        check_eq("K17 nothing was written", plan.read_bytes(), before)
    finally:
        cleanup(root)


if __name__ == "__main__":
    main()
