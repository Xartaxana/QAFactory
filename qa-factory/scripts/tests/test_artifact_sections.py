#!/usr/bin/env python3
"""SC1-3 part 2: the map of the sections of a big artifact, and the rows of a plan found structurally.

The rule this file holds: a line range or a byte range the code names is exactly that element, and when the code cannot
establish it, there is NO map - never a map that points at other lines (spec t-1253 section 4: E-3, E-4, E-5, E-6, E-8, E-9,
M-2). Keys:

  K9   the rows of a plan are found by parsing, not by looking for `"id": "TS-3"`: an `id` after a nested object, an earlier
       row whose nested object carries the same `id`, an `id` inside a string, one line for the whole file, a byte-order mark,
       CRLF, a raw U+2028 inside a string, `items` / `plan` / a bare array, a non-object element, the same id twice
  K10  the size of the map: a map of exactly 4000 characters is returned whole (AT), one of 4001 is cut by elements (BEYOND)
  K11  the key ranges are never cut, however small the cap
  K12  the map of the grounding table: the ranges of rows, requirements (with the rows that name them), areas, claims, hunks
  K13  the runtime check (M-2): a table that cannot be read, a path the registry does not name, a file that changes while the map
       is built, a row the independent parse does not give back - each gives NO map (an empty string, never a raise)
  K14  `grounding_section.py --map` prints the same text; an unreadable table is refused with a door
  K18  the live table of a real story (a path in `SECTIONS_LIVE_WORK`, when set): the length of the map and the number of
       elements, printed, not asserted
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import artifact_sections as AS  # noqa: E402
import hooklib  # noqa: E402
import planning_contract as PC  # noqa: E402
from test_grounding_section import FIXTURE, at  # noqa: E402  (one fixture of the table, not a second copy of it)


def spans_text(text: str) -> list:
    return [(rid, text[start:end], first, last) for rid, start, end, first, last in AS.plan_row_spans(text)]


def gives_the_rows_back(text: str) -> bool:
    """Every span is exactly its row: parsed again, it is the row of the whole document at that place."""
    rows = AS.rows_of(json.loads(text.lstrip("\ufeff")))
    found = AS.plan_rows_indexed(text)[1]
    return all(json.loads(text[start:end]) == rows[index] for index, _, start, end, _, _ in found)


def pretty(rows: list, **top) -> str:
    return json.dumps({"rows": rows, **top}, ensure_ascii=False, indent=1) + "\n"


def isolated_lines(text: str, count: int) -> list:
    """The lines of the first `count` rows of an `indent=1` plan, read off the text itself: a row opens on a line that is exactly
    `  {` and closes on `  }` or `  },` (the independent carrier the map is compared with; the keys after the rows are not rows)."""
    lines = text.split("\n")
    opens = [i + 1 for i, line in enumerate(lines) if line == "  {"]
    closes = [i + 1 for i, line in enumerate(lines) if line in ("  }", "  },")]
    return list(zip(opens, closes))[:count]


def write(path: Path, data) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))      # bytes: write_text turns \n into CRLF on Windows
    return path


def map_entries(map_text: str, section: str) -> list:
    line = next((line for line in map_text.split("\n") if line.startswith(section + ": ")), "")
    return [part.strip() for part in line[len(section) + 2:].split(", ")] if line else []


def main() -> None:
    work = temp_dir("qa-sections-")
    try:
        # ---- K9: the rows of a plan --------------------------------------------------------------------------------------
        nested = '{"rows": [{"meta": {"x": 1}, "id": "TS-3", "a": 1}]}'
        check_eq("K9 an `id` that follows a nested object: the span is the ROW, not the nested object",
                 spans_text(nested), [("TS-3", '{"meta": {"x": 1}, "id": "TS-3", "a": 1}', 1, 1)])
        other = '{"rows": [{"id": "TS-1", "ref": {"id": "TS-3"}}, {"id": "TS-3", "a": 1}]}'
        check_eq("K9 an earlier row's nested object carries the target id: that is not a row, and TS-3 is the second row",
                 [(rid, body) for rid, body, _, _ in spans_text(other)],
                 [("TS-1", '{"id": "TS-1", "ref": {"id": "TS-3"}}'), ("TS-3", '{"id": "TS-3", "a": 1}')])
        instring = '{"rows": [{"note": "see \\"id\\": \\"TS-3\\" there", "id": "TS-3"}, {"id": "TS-4"}]}'
        check_eq("K9 an `id` written inside a string value is not a row", [rid for rid, *_ in spans_text(instring)], ["TS-3", "TS-4"])
        for label, text in (("nested before id", nested), ("earlier nested id", other), ("id in a string", instring)):
            check(f"K9 {label}: every span parses back to its row", gives_the_rows_back(text))

        one = '{"rows": [{"id": "TS-1"}, {"id": "TS-2"}]}'
        check_eq("K9 one line for the whole file: every row is on line 1 (so no line window isolates one)",
                 [(first, last) for *_, first, last in spans_text(one)], [(1, 1), (1, 1)])
        bom = "\ufeff" + pretty([{"id": "TS-1"}, {"id": "TS-2"}])
        plain = pretty([{"id": "TS-1"}, {"id": "TS-2"}])
        check_eq("K9 a byte-order mark does not move a line number",
                 [(r, f, l) for r, _, f, l in spans_text(bom)], [(r, f, l) for r, _, f, l in spans_text(plain)])
        check("K9 and the spans of a text that starts with the mark are its rows' bytes", gives_the_rows_back(bom))
        crlf = plain.replace("\n", "\r\n")
        check_eq("K9 CRLF: lines are counted by the line feed, the same numbers",
                 [(r, f, l) for r, _, f, l in spans_text(crlf)], [(r, f, l) for r, _, f, l in spans_text(plain)])
        raw_sep = '{\n "rows": [\n  {"id": "TS-1", "t": "a b\u0085c"},\n  {"id": "TS-2"}\n ]\n}\n'
        check_eq("K9 a raw U+2028 / U+0085 inside a string is not a line end: TS-2 is on line 4 (as `Read` counts)",
                 [(r, f, l) for r, _, f, l in spans_text(raw_sep)], [("TS-1", 3, 3), ("TS-2", 4, 4)])
        check_eq("K9 `items` is the rows key when `rows` is absent", [r for r, *_ in spans_text('{"items": [{"id": "A"}]}')], ["A"])
        check_eq("K9 `plan` is the rows key when neither `rows` nor `items` is a list",
                 [r for r, *_ in spans_text('{"rows": null, "plan": [{"id": "A"}]}')], ["A"])
        check_eq("K9 the order of the readers is rows, items, plan - not the order in the file",
                 [r for r, *_ in spans_text('{"plan": [{"id": "P"}], "items": [{"id": "I"}]}')], ["I"])
        check_eq("K9 a bare array is the rows", [r for r, *_ in spans_text('[{"id": "A"}, {"id": "B"}]')], ["A", "B"])
        check_eq("K9 a non-object element is skipped, and counts in the index of the next",
                 AS.plan_rows_indexed('{"rows": [7, {"id": "A"}]}')[1][0][:2], (1, "A"))
        check_eq("K9 the same id twice: both rows, each with its own bytes",
                 [(rid, body) for rid, body, _, _ in spans_text('{"rows": [{"id": "A", "n": 1}, {"id": "A", "n": 2}]}')],
                 [("A", '{"id": "A", "n": 1}'), ("A", '{"id": "A", "n": 2}')])
        check_eq("K9 no rows: nothing", AS.plan_row_spans('{"rows": []}'), [])
        refused = []
        for bad in ("", "not json", '{"rows": [{"id": "A"}', '"text"', '{"rows": [{"id": "A"} {"id": "B"}]}'):
            try:
                AS.plan_row_spans(bad)
                refused.append(False)
            except ValueError:
                refused.append(True)
        check("K9 a text that is no plan is a ValueError, never a guess", all(refused), repr(refused))

        # ---- the map of a plan: the lines are the lines of the text ----------------------------------------------------
        rows = [{"id": f"TS-{i}", "meta": {"id": "inner"}, "list": [1, 2, 3][: i % 3 + 1]} for i in range(1, 8)]
        text = pretty(rows, lifecycle_actions=[{"a": 1}])
        plan = write(work / "p1" / "work" / "test-plan.json", text)
        got = AS.section_map_text(plan, "plan_rows")
        expected = [f"TS-{i + 1} {a}-{b}" for i, (a, b) in enumerate(isolated_lines(text, len(rows)))]
        check_eq("K9 the map names each row with the lines the text itself shows (opens `  {`, closes `  }`)",
                 map_entries(got, "rows"), expected)
        check_in("K9 and the key ranges of the file come first", "keys: rows 2-", got)
        check_in("K9 the second top-level key is in them", "lifecycle_actions ", got)
        check_eq("K9 an empty plan names the empty section", AS.section_map_text(write(work / "p2" / "work" / "test-plan.json", '{"rows": []}'),
                                                                               "plan_rows").split("\n")[-1], "rows: none")
        shared = AS.section_map_text(write(work / "p3" / "work" / "test-plan.json", one), "plan_rows")
        check_in("K9 one line for the whole file: the map says so and gives no ranges", "rows share line 1: no line window isolates one row", shared)
        check_not_in("K9 and no row gets a range there", "TS-1 1-1", shared)
        # Q-1 (t-1286): rows that share only their BOUNDARY line (the `}, {` style) keep their ranges; a row with no line of its own does not
        joined = '{\n "rows": [\n  {\n   "id": "TS-1",\n   "a": 1\n  }, {\n   "id": "TS-2",\n   "a": 2\n  }\n ]\n}\n'
        got_joined = AS.section_map_text(write(work / "p3b" / "work" / "test-plan.json", joined), "plan_rows")
        check_eq("Q-1 the `}, {` style: the ranges of both rows are kept (they share line 6)", map_entries(got_joined, "rows"), ["TS-1 3-6", "TS-2 6-9"])
        check_not_in("Q-1 (and no 'share line' refusal)", "share line", got_joined)
        crowded = '{\n "rows": [\n  {\n   "id": "TS-1"\n  }, {"id": "TS-2"}, {\n   "id": "TS-3"\n  }\n ]\n}\n'
        got_crowded = AS.section_map_text(write(work / "p3c" / "work" / "test-plan.json", crowded), "plan_rows")
        check_in("Q-1 a row whose every line is shared (TS-2 on line 5 between two others): no ranges, the line named", "rows share line 5", got_crowded)
        dup = AS.section_map_text(write(work / "p4" / "work" / "test-plan.json", pretty([{"id": "A"}, {"id": "B"}, {"id": "A"}])), "plan_rows")
        check_eq("K9 the same id twice: both in the map", [e.split(" ")[0] for e in map_entries(dup, "rows")], ["A", "B", "A"])
        crlf_map = AS.section_map_text(write(work / "p5" / "work" / "test-plan.json", crlf.encode("utf-8")), "plan_rows")
        check_eq("K9 a CRLF file gives the map of its LF twin", crlf_map, AS.section_map_text(write(work / "p6" / "work" / "test-plan.json", plain), "plan_rows"))
        check_eq("K9 a file with a byte-order mark gives the map of the same file without it",
                 AS.section_map_text(write(work / "p7" / "work" / "test-plan.json", b"\xef\xbb\xbf" + plain.encode("utf-8")), "plan_rows"),
                 AS.section_map_text(write(work / "p8" / "work" / "test-plan.json", plain), "plan_rows"))

        # ---- K10: the size of the map: AT 4000, BEYOND 4001 --------------------------------------------------------------
        check_eq("K10 the size of a map is 4000 characters", AS.MAP_CHARS, 4000)

        def sized(count: int, pad: int) -> Path:
            ids = [f"TS-{i}" for i in range(1, count + 1)]
            ids[-1] += "x" * pad
            body = ",\n".join(json.dumps({"id": i}) for i in ids)
            return write(work / f"s{count}-{pad}" / "work" / "test-plan.json", '{\n "rows": [\n' + body + "\n ]\n}\n")

        count = 1
        while len(AS.section_map_text(sized(count, 0), "plan_rows", cap=10 ** 9)) <= 4000:
            count += 1
        count -= 1
        pad = 4000 - len(AS.section_map_text(sized(count, 0), "plan_rows", cap=10 ** 9))
        at_limit = AS.section_map_text(sized(count, pad), "plan_rows")
        check_eq("K10 AT the limit: a map of exactly 4000 characters is returned whole", len(at_limit), 4000)
        check_not_in("K10 and nothing is cut from it", "more", at_limit)
        full = AS.section_map_text(sized(count, pad + 1), "plan_rows", cap=10 ** 9)
        beyond = AS.section_map_text(sized(count, pad + 1), "plan_rows")
        check_eq("K10 BEYOND: the same map one character longer is 4001 before the cut", len(full), 4001)
        check("K10 and it IS cut, to at most 4000", len(beyond) <= 4000 and beyond != full, f"{len(beyond)}")
        kept = map_entries(beyond, "rows")
        left = int(beyond.split("... and ")[1].split(" more")[0])
        check_eq("K10 the cut is counted at the end: what is kept and what is left make the rows", len(kept) + left, count)
        check_in("K10 and it names the way to the rest", "more (rows); Grep -n \"<id>\" work/test-plan.json gives one's first line", beyond)
        check_eq("K10 what is kept is the FIRST entries, each whole (no half entry)",
                 kept, [f"TS-{i} {i + 2}-{i + 2}" for i in range(1, len(kept) + 1)])

        # ---- K11: the key ranges are never cut ---------------------------------------------------------------------------
        tiny = AS.section_map_text(plan, "plan_rows", cap=1)
        check_in("K11 with a cap of 1 the key ranges are still all there", "keys: rows 2-", tiny)
        check_in("K11 (the second key too)", "lifecycle_actions ", tiny)
        check_in("K11 and the omitted rows are counted", f"... and {len(rows)} more (rows)", tiny)

        # ---- K13: the runtime check of the plan map (M-2) -----------------------------------------------------------------
        check_eq("K13 an unknown kind: no map", AS.section_map_text(plan, "nothing"), "")
        check_eq("K13 a file that is absent: no map", AS.section_map_text(work / "absent.json", "plan_rows"), "")
        check_eq("K13 a file that is no JSON: no map, no raise", AS.section_map_text(write(work / "bad.json", "{not json"), "plan_rows"), "")
        original = hooklib.read_json
        try:
            def changing(path, default=None, **kw):             # the file changes between the read of the bytes and the parse
                value = original(path, default, **kw)
                write(Path(path), pretty([{"id": "TS-1"}]))
                return value
            hooklib.read_json = changing
            check_eq("K13 a plan that changes while the map is built: no map", AS.section_map_text(plan, "plan_rows"), "")
            write(plan, text)

            def lying(path, default=None, **kw):                # the independent parse disagrees with the bytes the spans came from
                value = original(path, default, **kw)
                value["rows"][2]["list"] = ["not what the file says"]
                return value
            hooklib.read_json = lying
            check_eq("K13 a row the independent parse does not give back: no map", AS.section_map_text(plan, "plan_rows"), "")
        finally:
            hooklib.read_json = original
            write(plan, text)
        check_in("K13 the control: the same file, honestly read, has its map", "TS-1 ", AS.section_map_text(plan, "plan_rows"))

        # ---- K12 / K13 / K14: the table ----------------------------------------------------------------------------------
        project = temp_project("qa-sections-g-")
        story = project / "qa-factory" / "artifacts" / "TP3-1"
        table = write(story / "work" / "grounding.yaml", FIXTURE)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project))
        try:
            gmap = AS.section_map_text(table, "grounding")
            check_in("K12 the header says what the numbers are", "1-based lines, the number `Read offset` takes", gmap)
            check_in("K12 the key ranges (the top-level key `rows` from its own line)", f"rows {at('rows:')}-{at('requirements:') - 1}", gmap)
            flow_row = '  - {id: G-3, hunks: [5e5e5e5e5e5e-1], label: "", requirements: [R-1, R-2], risks: [], question: "", reason: ""}'
            check_eq("K12 the rows, each with its lines", map_entries(gmap, "rows"),
                     [f"G-1 {at('  - id: G-1')}-{at('      over two lines' + chr(34))}",
                      f"G-2 {at('  - risks:')}-{at('      # the scalar' + chr(39) + 's own text, not a comment')}",
                      f"G-3 {at(flow_row)}-{at(flow_row)}"])
            reqs = next(line for line in gmap.split("\n") if line.startswith("requirements: "))
            r2 = f"R-2 {at('  - {r: R-2, state: unknown, hunks: [], where: ' + chr(34) * 2 + ', question: ' + chr(34) * 2 + '}')}"
            check_in("K12 a requirement carries the ids of the rows that name it",
                     f"R-1 {at('  - r: R-1')}-{at('    question: ' + chr(34) * 2, 3)} (rows G-1, G-3)", reqs)
            check_in("K12 (G-3 names R-2 as well)", r2 + "-" + r2.split(" ")[1] + " (rows G-3)", reqs)
            r3 = at('  - {r: R-3, state: unknown, hunks: [], where: "", question: ""}')
            check("K12 and a requirement no row names (R-3, the last) has no list after it", reqs.endswith(f"R-3 {r3}-{r3}"), reqs)
            check_eq("K12 the areas", map_entries(gmap, "areas")[0], f"B-1 {at('    - id: B-1')}-{at('      matters: ' + chr(34) * 2)}")
            claim = '  - {row: G-1, r: R-1, requirement: "x", now: "403"}'
            check_in("K12 the claims", f"claims: R-1 {at(claim)}-{at(claim)}", gmap)
            check_in("K12 a hunk by its full id and its short id", f"3f2a9c01b7de-1/H-1 {at('  - id: 3f2a9c01b7de-1')}-{at('    file: src/a.py')}", gmap)
            check_eq("K12 an element with no id is named by its place", map_entries(gmap, "orphans")[0].split(" ")[0], "orphans[0]")
            check_in("K12 a list of 0 keeps its name: base_slice is a key, not a section", "base_slice ", gmap)
            check("K12 the map is what the registry's reader says, and fits", 0 < len(gmap) <= AS.MAP_CHARS)
            small = AS.section_map_text(table, "grounding", cap=1)
            check_in("K11 the key ranges of the table are never cut either", "keys: schema_version 1-1", small)
            check_in("K11 (and the omitted elements are counted)", "more (rows, requirements, areas, claims, hunks, orphans, diff)", small)

            # K13: the table
            check_eq("K13 a file named grounding.yaml outside the story's work folder: no map",
                     AS.section_map_text(write(project / "stray" / "grounding.yaml", FIXTURE), "grounding"), "")
            check_eq("K13 a file in work/ that the registry does not call the table: no map",
                     AS.section_map_text(write(story / "work" / "notes.yaml", FIXTURE), "grounding"), "")
            write(table, FIXTURE.replace("\n  - id: G-1", "\n\t- id: G-1", 1))
            check_eq("K13 a table the one reader refuses (a tab): no map, no raise", AS.section_map_text(table, "grounding"), "")
            write(table, FIXTURE)
            read = PC.read_grounding
            try:
                def moving(task):
                    got = read(task)
                    write(table, FIXTURE + "\n# something added while the map was built\n")
                    return got
                PC.read_grounding = moving
                check_eq("K13 a table that changes while the map is built: no map", AS.section_map_text(table, "grounding"), "")
            finally:
                PC.read_grounding = read
                write(table, FIXTURE)
            check_in("K13 the control: the table, honestly read, has its map", "G-1 ", AS.section_map_text(table, "grounding"))

            # K14: the CLI
            def cli(*args):
                got = run_script("grounding_section.py", "--task", "TP3-1", "--task-root", story, *args, cwd=project, env=env)
                return got.returncode, got.stdout, got.stderr
            code, out, err = cli("--map")
            check_eq("K14 --map prints the map the guard's refusal will carry", (code, out.strip()), (0, AS.section_map_text(table, "grounding")))
            check_eq("K14 --map with --show is a usage error (one thing per call)", cli("--map", "--show", "G-1")[0], 2)
            write(table, FIXTURE.replace("schema_version: 1", "schema_version: 2", 1))
            code, out, err = cli("--map")
            check_eq("K14 an unreadable table is refused", (code, out), (2, ""))
            check_in("K14 with the reader's own words and a door", "Read", err)
            check_in("K14 (the words of the reader)", "schema_version", err)
            write(table, FIXTURE)
        finally:
            cleanup(project)

        # ---- K18: a live table (a measurement for the witness, not an assertion) ----------------------------------------
        live = os.environ.get("SECTIONS_LIVE_WORK", "")
        if live and (Path(live) / "grounding.yaml").is_file():
            for kind, name in (("plan_rows", "test-plan.json"), ("grounding", "grounding.yaml")):
                started = time.time()
                got = AS.section_map_text(Path(live) / name, kind)
                entries = sum(len(map_entries(got, s)) for s in ("rows", "requirements", "areas", "claims", "hunks", "orphans", "diff"))
                print(f"K18 live {name}: map {len(got)} chars, {entries} elements listed, {got.count(chr(10)) + 1} lines, {time.time() - started:.2f}s")
                print(f"K18 live {name}: ends with: {got.split(chr(10))[-1][:160]}")
                check(f"K18 the live {name} has a map", bool(got))
    finally:
        cleanup(work)
    finish("test_artifact_sections")


if __name__ == "__main__":
    main()
