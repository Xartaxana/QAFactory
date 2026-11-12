"""The driver golden's own tests (t-301 N0, FR-28: a measurer is code and gets a test like any other code).

Keys K3-K15 and C1 of the spec, each with its negative control, on fixtures and temp dirs. No rig scenario is run here (the
real record is `driver_golden.py record`, minutes long); a tiny fixture package stands in for the driver, so the whole
cycle record -> compare -> reordered side effect -> compare red -> stability is exercised in seconds.

    python -B scripts/tests/test_driver_golden.py
"""

import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402
import driver_trace as T  # noqa: E402
import driver_golden as G  # noqa: E402

RULES = T.load_rules()


# --- K8: the normalisation rows, AT and BEYOND ----------------------------------------------------------------------
def norm(text, roots=(), plugin="", tmp=None, reg=None):
    reg = reg or T.Registry(RULES, str(plugin) if plugin else "", tmp if tmp is not None else tempfile.gettempdir())
    for root in roots:
        reg.add_root(root)
    return reg.normalise(text)


def k8_rows() -> None:
    check_eq("N5 AT: an ISO date-time with an offset", norm('"at": "2026-10-02T12:30:45+03:00"'), '"at": "<TS>"')
    check_eq("N5 AT: with fraction and Z", norm("2026-10-02T12:30:45.123Z"), "<TS>")
    check_eq("N5 BEYOND: a date alone is kept", norm("on 2026-10-02 only"), "on 2026-10-02 only")
    check_eq("N6 AT: duration_ms and created_at (a float) become <NUM>, num_turns stays",
             norm('{"duration_ms": 1234, "created_at": 17.5, "num_turns": 3}'),
             '{"duration_ms": "<NUM>", "created_at": "<NUM>", "num_turns": 3}')
    check_eq("N6 AT: the controller's epoch floats and measured seconds; BEYOND: a null stays null",
             norm('{"stage_started": 1790980965.5720136, "stage_finished": null, "wall_seconds": 12}'),
             '{"stage_started": "<NUM>", "stage_finished": null, "wall_seconds": "<NUM>"}')
    check_eq("N7 AT: ten digits", norm("driver-tmp\\gate-1700000000123.json"), "driver-tmp\\gate-<MS>.json")
    check_eq("N7 BEYOND: nine digits are kept", norm("driver-tmp/gate-170000000.json"), "driver-tmp/gate-170000000.json")
    u = "0123456789abcdef0123456789abcdef"
    check_eq("N8 AT: <name>.<32 hex>.tmp", norm(f"state/x.json.{u}.tmp"), "state/x.json.<UUID-1>.tmp")
    check_eq("N8 AT: recovery-<32 hex>.bin", norm(f"recovery-{u}.bin"), "recovery-<UUID-1>.bin")
    check_eq("N8 BEYOND: 31 hex is kept", norm(f"x.{u[:-1]}.tmp"), f"x.{u[:-1]}.tmp")
    check_eq("N8 BEYOND: 33 hex is kept", norm(f"x.{u}0.tmp"), f"x.{u}0.tmp")
    other = "fedcba9876543210fedcba9876543210"
    check_eq("N9 AT: event_id, then every later occurrence of the same token",
             norm(f'{{"event_id": "{u}"}} see {u}'), '{"event_id": "<UUID-1>"} see <UUID-1>')
    check_eq("N9 BEYOND: a 32-hex value under another key is kept", norm(f'{{"other": "{other}"}}'), f'{{"other": "{other}"}}')
    reg = T.Registry(RULES, "", tempfile.gettempdir())
    snap = T.digest_bytes(reg, b"ticket body", "ticket-snapshot.json")
    sha64 = "a" * 64
    check_eq("N10 AT: the snapshot's sha is <REV=snapshot>, another 64 hex is <REV-1>, src-1 is kept",
             reg.normalise(f'"source_revision": "{snap[0]}" "source_revision": "{hashlib.sha256(b"ticket body").hexdigest()}" '
                           f'"source_revision": "{sha64}" "source_revision": "src-1"'),
             '"source_revision": "<REV=snapshot>" "source_revision": "<REV=snapshot>" "source_revision": "<REV-1>" '
             '"source_revision": "src-1"')
    check_eq("N10 BEYOND: a 64-hex value under an unscoped key is kept", norm(f'"sha": "{sha64}"'), f'"sha": "{sha64}"')
    check_eq("N11 AT: loopback ports, numbered by first sight",
             norm("http://127.0.0.1:51234/x and localhost:51234 and 127.0.0.1:60000"),
             "http://127.0.0.1:<PORT-1>/x and localhost:<PORT-1> and 127.0.0.1:<PORT-2>")
    check_eq("N12 AT: an object's address", norm("<Foo object at 0x7F00AB12>"), "<Foo object at <ADDR>>")
    check_eq("N13 AT: a driver frame; BEYOND: a story_step frame is kept",
             norm('File "C:\\x\\scripts\\story_run.py", line 123, in run\nFile "C:\\x\\scripts\\story_step.py", line 9, in f'),
             'File "<DRIVER>", line <L>, in run\nFile "C:\\x\\scripts\\story_step.py", line 9, in f')
    check_eq("N14 AT: the progress line's clock and elapsed time", norm("since 21:15 (3 h 12 min)"), "since <HM> (<DUR>)")
    check_eq("N14 AT: 'started HH:MM' of the progress line too; BEYOND: another word before a time is kept",
             norm("the scout started 01:05, no proof; seen 01:05"), "the scout started <HM>, no proof; seen 01:05")
    check_eq("N21 AT: a pid under the key pid; BEYOND: a number under another key is kept",
             norm('{"pid": 13772, "port": 13772}'), '{"pid": "<PID>", "port": 13772}')
    check_eq("N23 AT: a date, a time and UTC; BEYOND: without UTC it is kept",
             norm("answered at 2026-10-02 23:02 UTC and at 2026-10-02 23:02"), "answered at <TS> UTC and at 2026-10-02 23:02")
    h64 = "b" * 64
    check_eq("N22 AT: packet_hash is <HASH-n>", norm(f'"packet_hash": "{h64}"'), '"packet_hash": "<HASH-1>"')
    check_eq("N15 AT: event_hash and previous_hash", norm(f'"event_hash": "{h64}", "previous_hash": "{h64}"'),
             '"event_hash": "<HASH-1>", "previous_hash": "<HASH-1>"')
    check_eq("N16 AT: input_hash and a manifest hash are <HASH-n>, equal values share a number",
             norm(f'"input_hash": "{h64}", "hash": "{h64}", "hash": "{"c" * 64}"'),
             '"input_hash": "<HASH-1>", "hash": "<HASH-1>", "hash": "<HASH-2>"')
    check_eq("N16 BEYOND: a hash under another key is kept", norm(f'"digest": "{h64}"'), f'"digest": "{h64}"')
    check_eq("N18 AT: question_sha is <HASH-n>; BEYOND: a 64-hex under `sha` is kept",
             norm(f'"question_sha": "{h64}" "sha": "{h64}"'), f'"question_sha": "<HASH-1>" "sha": "{h64}"')
    check_eq("N9 AT: an activity span's event_id keeps its :start/:end suffix, and the token is the same for both",
             norm(f'{{"event_id":"{u}:start"}} {{"event_id":"{u}:end"}}'),
             '{"event_id":"<UUID-1>:start"} {"event_id":"<UUID-1>:end"}')
    check_eq("N29 AT: the dashboard's feedback age; BEYOND: another bold label is kept",
             norm("<b>age days:</b> 0.06</div><div><b>age weeks:</b> 0.01</div><b>ripe:</b> no"),
             "<b>age days:</b> <NUM></div><div><b>age weeks:</b> <NUM></div><b>ripe:</b> no")
    check_eq("N30 AT: git log's Date line; BEYOND: another line with a date is kept",
             norm("Date:   Sat Oct 3 03:33:28 2026 +0200\nOn   Sat Oct 3 03:33:28 2026 +0200"),
             "Date:   <GITDATE>\nOn   Sat Oct 3 03:33:28 2026 +0200")
    check_eq("N31 AT: package_fingerprint, plain and inside an escaped JSON string; BEYOND: another key's 64-hex is kept",
             norm('{"package_fingerprint": "' + h64 + '", "x": "' + h64 + '"} {\\"package_fingerprint\\": \\"' + h64 + '\\"}'),
             '{"package_fingerprint": "<PKG-FP>", "x": "' + h64 + '"} {\\"package_fingerprint\\": \\"<PKG-FP>\\"}')
    row = '{"ts": "<TS>", "kind": "q", "stage": "S1", "dispatch": "", "bytes": 511, "details_file": false, "problems": []}'
    check_eq("N32 AT: the bytes of a driver-questions.jsonl row (the length of a text that holds a path)",
             norm(row), row.replace("511", "<N-BYTES>"))
    check_eq("N33 AT: brief_pack's printed size; BEYOND: another note keeps its number",
             norm("note: brief: qa-factory/artifacts/QA-9/work/briefs/S1.md (2,585 B)\nbrief: qa-factory/x.md (2,585 B)\nnote: wrote x (2,585 B)\n"),
             "note: brief: qa-factory/artifacts/QA-9/work/briefs/S1.md (<N-BYTES> B)\nbrief: qa-factory/x.md (<N-BYTES> B)\nnote: wrote x (2,585 B)\n")
    other_row = '{"dispatch": "x", "bytes": 511, "other": 1}'
    check_eq("N32 BEYOND: a `bytes` in another shape of row is kept", norm(other_row), other_row)
    reg_pid = T.Registry(RULES, "", tempfile.gettempdir())
    reg_pid.numbers["PID"] = {"4321": "0.1", "99": "0"}
    check_eq("N21/N24/N27 (F7): a pid of a process of this scenario is PID-<proc>, any other number is <PID>",
             reg_pid.normalise('{"pid": 4321} {"pid": 99} {"pid": 55555} x.4321.tmp command-4321.jsonl hook-777.jsonl'),
             '{"pid": "<PID-0.1>"} {"pid": "<PID-0>"} {"pid": "<PID>"} x.<PID-0.1>.tmp command-<PID-0.1>.jsonl hook-<PID>.jsonl')
    sha40 = "0123456789abcdef0123456789abcdef01234567"
    check_eq("N28 AT: a stream that is one git commit id, and every later occurrence of it; BEYOND: another 40-hex is kept",
             norm(sha40 + "\n") + "|" + norm("head " + sha40 + " and " + "f" * 40), "<GIT-1>\n|head " + sha40 + " and " + "f" * 40)
    other40 = "fedcba9876543210fedcba9876543210fedcba98"
    check_eq("N28 AT: a stream of bare ids (for-each-ref) and a `<id><TAB>ref` line (ls-remote, log); BEYOND: an id followed by words is kept",
             norm(f"{sha40}\n{other40}\n") + "|" + norm(f"{sha40}\trefs/heads/feat\n") + "|" + norm(f"{sha40} and words\n"),
             "<GIT-1>\n<GIT-2>\n|<GIT-1>\trefs/heads/feat\n|" + f"{sha40} and words\n")
    reg40 = T.Registry(RULES, "", tempfile.gettempdir())
    check_eq("N28 the registered id is replaced in a later text", (reg40.normalise(sha40 + "\n"), reg40.normalise(f"checkout {sha40} x")),
             ("<GIT-1>\n", "checkout <GIT-1> x"))
    check_eq("N28c AT: the 12-hex short form of a registered id is the same token; BEYOND: another 12-hex value is kept",
             (reg40.normalise("route: " + sha40[:12] + " is left out"), reg40.normalise("route: " + "f" * 12 + " is left out")),
             ("route: <GIT-1> is left out", "route: " + "f" * 12 + " is left out"))
    check_eq("N27 AT: telemetry file names by process id; BEYOND: another prefix is kept",
             norm("state\\telemetry\\command-28464.jsonl hook-35872.jsonl other-123.jsonl"),
             "state\\telemetry\\command-<PID>.jsonl hook-<PID>.jsonl other-123.jsonl")
    check_eq("N6 AT: age_days and age_weeks (elapsed time as a fraction)", norm('{"age_days": 0.005002928576388889, "age_weeks": 1e-05}'),
             '{"age_days": "<NUM>", "age_weeks": "<NUM>"}')
    check_eq("N24 AT: <name>.<pid>.tmp; BEYOND: nine digits are kept", norm("x.json.15820.tmp x.json.123456789.tmp"),
             "x.json.<PID>.tmp x.json.123456789.tmp")
    check_eq("N25 AT: a file whose whole text is an epoch time; BEYOND: an epoch inside other text is kept",
             norm("1790982219.3456092") + "|" + norm("at 1790982219.3456092 s"), "<EPOCH>|at 1790982219.3456092 s")
    check_eq("N26 AT: a 16-hex fingerprint; BEYOND: 17 hex is kept", norm('"fingerprint": "242021b0da65e628" "fingerprint": "' + "a" * 17 + '"'),
             '"fingerprint": "<HASH-1>" "fingerprint": "' + "a" * 17 + '"')
    check_eq("N19 AT: the dashboard's 'Generated <date> <hh:mm>' line", norm("Generated 2026-10-03 00:25 · testing"),
             "Generated <TS> · testing")
    check_eq("N19 BEYOND: a date and time elsewhere (no 'Generated') is kept", norm("seen 2026-10-03 00:25"), "seen 2026-10-03 00:25")
    tmp = tempfile.gettempdir()
    stale =tmp + os.sep + "qa-story-run-abcd1234" + os.sep + "fake_claude.py"
    check_eq("N17 AT: a stale temp dir of an earlier scenario", norm(stale), f"<TMP>{os.sep}qa-story-run-<STALE-ROOT>{os.sep}fake_claude.py")
    check_eq("N17 BEYOND: a temp dir name that is not 8 characters long is kept as a name",
             norm(tmp + os.sep + "qa-story-run-abcd123"), f"<TMP>{os.sep}qa-story-run-abcd123")


def k8_paths() -> None:
    a, b = harness.temp_dir("gold-a-"), harness.temp_dir("gold-b-")      # not `qa-` named: N17 would read them as stale roots
    try:
        check_eq("two roots give two tokens", norm(f"{a}|{b}", roots=[a, b]), "<ROOT-1>|<ROOT-2>")
        check_eq("a root registered twice stays one token", norm(f"{a}", roots=[a, a]), "<ROOT-1>")
        short = T._short_path(str(a))
        if short and short.lower() != str(a).lower():
            check_eq("one root, in the 8.3 and in the long spelling, is one token", norm(f"{a}|{short}", roots=[a]),
                     "<ROOT-1>|<ROOT-1>")
        else:
            print("note: this machine's temp dir has no distinct 8.3 spelling; the short-name case is not exercised")
        slashed = str(a).replace("\\", "/")
        check_eq("forward slashes", norm(slashed + "/x", roots=[a]), "<ROOT-1>/x")
        escaped = str(a).replace("\\", "\\\\")
        check_eq("JSON-escaped double backslashes", norm(escaped + "\\\\x", roots=[a]), "<ROOT-1>\\\\x")
        plugin = a / "pkg"
        check_eq("a path under both <PLUGIN> and the temp dir becomes <PLUGIN>", norm(str(plugin / "x.py"), plugin=plugin),
                 "<PLUGIN>" + os.sep + "x.py")
        sibling = a / "pkg2"
        check_eq("BEYOND: a sibling dir that only starts like the plugin dir is not the plugin",
                 norm(str(sibling / "x.py"), plugin=plugin), "<TMP>" + os.sep + a.name + os.sep + "pkg2" + os.sep + "x.py")
        check_eq("sys.executable is <PY>", norm(sys.executable + " -B x"), "<PY> -B x")
        name = a.name
        check_eq("a registered root's BARE directory name (the rig's task id) is its own token, whole word only",
                 norm(f'"task_id": "{name}" and {name}x and x{name}', roots=[a]), '"task_id": "<ROOT-1-NAME>" and ' + name + "x and x" + name)
        check_eq("BEYOND: a name that is not a registered root's is kept", norm("qa-t261-ctl-83qsh430", roots=[a]), "qa-t261-ctl-83qsh430")
    finally:
        harness.cleanup(a)
        harness.cleanup(b)


# --- K9: ASCII only, a Cyrillic word kept escaped ---------------------------------------------------------------------
def k9_ascii() -> None:
    word = "\u041f\u0440\u0438\u0432\u0435\u0442 \u043c\u0438\u0440"
    line = T.dumps({"kind": "write", "payload": {"text": word + "\n\x01"}, "seq": 1})
    check("K9 a record is ASCII with no raw control byte", all(ord(c) < 128 and (c >= " ") for c in line), line)
    check_eq("K9 the Cyrillic text round-trips exactly (escaped, not dropped)", json.loads(line)["payload"]["text"], word + "\n\x01")


# --- K4 / K3 / K11: order, stability, completeness ------------------------------------------------------------------
def k4_order() -> None:
    a, b, c = (T.dumps({"seq": i, "proc": "0", "kind": "write", "payload": {"path": p}}) for i, p in enumerate("abc"))
    check_eq("K4 equal streams are equal", T.compare_lines([a, b, c], [a, b, c]), None)
    swapped = T.compare_lines([a, b, c], [a, c, b])
    check("K4 control: a swapped pair fails, naming the first differing seq and both records",
          bool(swapped) and swapped["seq"] == 1 and swapped["golden"] == b and swapped["now"] == c, str(swapped))
    dup = T.compare_lines([a, b], [a, b, b])
    check("K4 control: a duplicated record fails (golden ends, now has one more)",
          bool(dup) and dup["seq"] == 2 and dup["golden"] is None and dup["now"] == b, str(dup))
    drop = T.compare_lines([a, b, c], [a, c])
    check("K4 control: a dropped record fails", bool(drop) and drop["seq"] == 1, str(drop))
    w1 = T.dumps({"seq": 0, "proc": "0", "kind": "write", "payload": {"path": "f", "bytes": 1}, "sha": "1" * 64})
    w2 = T.dumps({"seq": 1, "proc": "0", "kind": "write", "payload": {"path": "f", "bytes": 1}, "sha": "2" * 64})
    w1s, w2s = w1.replace('"seq":0', '"seq":1'), w2.replace('"seq":1', '"seq":0')
    check("K4 control: two writes of ONE path with different content, exchanged, differ (the order of a path's own writes is a "
          "trace, not noise)", T.compare_lines([w1, w2], [w2s, w1s]) is not None)
    check_eq("K4: the same two writes in the same order are equal", T.compare_lines([w1, w2], [w1, w2]), None)


def fake_run(name, finals, code=0):
    run = G.FileRun(name)
    run.code = code
    run.finals = finals
    return run


def k3_k11() -> None:
    first = {"s1": ['{"seq":0,"kind":"begin"}', '{"seq":1,"kind":"write","payload":{"x":"<TS>"}}']}
    second = {"s1": ['{"seq":0,"kind":"begin"}', '{"seq":1,"kind":"write","payload":{"x":"2026-10-02T10:00:00"}}']}
    unstable = G.stability_diffs({"f.py": fake_run("f.py", first)}, {"f.py": fake_run("f.py", second)}, None)
    check("K3 control: an un-normalised value is reported with its file, scenario and first differing seq",
          len(unstable) == 1 and unstable[0]["file"] == "f.py" and unstable[0]["scenario"] == "s1" and unstable[0]["seq"] == 1,
          str(unstable))
    check_eq("K3: two equal records are stable", G.stability_diffs({"f.py": fake_run("f.py", first)},
                                                                    {"f.py": fake_run("f.py", dict(first))}, None), [])
    empty = Path(tempfile.mkdtemp(prefix="qa-gold-empty-"))
    try:
        try:
            G.need_golden(empty)
            check("K11 an empty golden dir is a refusal", False, "no refusal")
        except G.Refusal as exc:
            check_in("K11 an empty golden dir says to record on the parent commit", "no golden recorded", str(exc))
            check_in("K11 and names the door", "record", str(exc))
        compared, equal, differ, problems = G.compare_runs({"f.py": fake_run("f.py", {"only_now": ["x"]})},
                                                           {"f": {"only_golden": ["x"]}}, None)
        check("K11 a scenario in the golden and not recorded, and one recorded and not in the golden, are both named",
              len(problems) == 2 and any("only_golden" in p for p in problems) and any("only_now" in p for p in problems),
              str(problems))
        check_eq("K11 and nothing was counted as compared", (compared, equal), (0, 0))
        compared, equal, differ, problems = G.compare_runs({"f.py": fake_run("f.py", {"s": ["a", "b"]})},
                                                           {"f": {"s": ["a", "b"]}}, None)
        check_eq("K11 control: matching scenarios compare equal", (compared, equal, len(differ), problems), (1, 1, 0, []))
    finally:
        harness.cleanup(empty)


# --- K10: caps ------------------------------------------------------------------------------------------------------
def k10_caps() -> None:
    lines = ["x" * 10, "y" * 5]
    check_eq("K10 AT the trace cap passes", T.check_caps("f::s", lines, {"trace_bytes": 17}), None)
    over = T.check_caps("f::s", lines, {"trace_bytes": 16})
    check("K10 BEYOND refuses, naming the scenario and its largest records", bool(over) and "f::s" in over and "seq 0" in over,
          str(over))
    root = harness.temp_dir("qa-gold-cap-")
    try:
        (root / "pipeline.json").write_text("a" * 20, encoding="utf-8")
        reg = T.Registry(RULES, "", tempfile.gettempdir())
        at = [p for p, _s in T.tree_records(reg, root, {"text_bytes": 20}) if p["path"] == "pipeline.json"][0]
        check("K10 AT the text cap keeps the text", at.get("text") == "a" * 20 and "text_omitted" not in at, str(at))
        (root / "pipeline.json").write_text("a" * 21, encoding="utf-8")
        beyond, sha = [(p, s) for p, s in T.tree_records(reg, root, {"text_bytes": 20}) if p["path"] == "pipeline.json"][0]
        check("K10 BEYOND keeps the sha and says text_omitted", "text" not in beyond and beyond.get("text_omitted") is True and bool(sha),
              str(beyond))
    finally:
        harness.cleanup(root)


# --- K12: the tree ---------------------------------------------------------------------------------------------------
def k12_tree() -> None:
    root = harness.temp_dir("qa-gold-tree-")
    try:
        (root / "pipeline.json").write_text('{"a": 1}', encoding="utf-8")
        (root / "other.txt").write_text("not kept as text", encoding="utf-8")
        blob = bytes([0, 159, 146, 150, 255])
        (root / "data.bin").write_bytes(blob)
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text("[core]", encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        (root / "remote.git" / "objects" / "4e").mkdir(parents=True)
        (root / "remote.git" / "objects" / "4e" / "abc").write_bytes(b"obj")
        (root / "remote2.git" / "objects" / "7d").mkdir(parents=True)
        (root / "gitlike").mkdir()
        (root / "gitlike" / "kept.txt").write_text("x", encoding="utf-8")
        reg = T.Registry(RULES, "", tempfile.gettempdir())
        recs = {p["path"]: (p, s) for p, s in T.tree_records(reg, root)}
        check("K12 a binary file is the raw sha and not text", recs["data.bin"][0]["binary"] is True
              and recs["data.bin"][1] == hashlib.sha256(blob).hexdigest() and "text" not in recs["data.bin"][0], str(recs["data.bin"]))
        check("K12 a kept file carries its text; another file does not", "text" in recs["pipeline.json"][0]
              and "text" not in recs["other.txt"][0])
        check("K12 .git, __pycache__ and a bare remote.git are recorded as present and not entered (their object names are shas)",
              recs[".git"][0].get("excluded") is True and recs["__pycache__"][0].get("excluded") is True
              and recs["remote.git"][0].get("excluded") is True and recs["remote2.git"][0].get("excluded") is True
              and "remote2.git/objects" not in recs and "gitlike/kept.txt" in recs and ".git/config" not in recs
              and "__pycache__/x.pyc" not in recs and "remote.git/objects" not in recs, str(sorted(recs)))
        before = [T.dumps({"p": p, "s": s}) for p, s in T.tree_records(reg, root)]
        (root / "data.bin").write_bytes(bytes([0, 159, 146, 150, 254]))
        after = [T.dumps({"p": p, "s": s}) for p, s in T.tree_records(reg, root)]
        check("K12 control: a one-byte change in a binary file fails compare", T.compare_lines(before, after) is not None)
        check_eq("K12 the order is by path", [p["path"] for p, _s in T.tree_records(reg, root)],
                 sorted(p["path"] for p, _s in T.tree_records(reg, root)))
        # two files that differ only by a normalised token (a process id in the name) tie on the path: the content breaks the tie,
        # so the order does not depend on which process id was the bigger number
        one, other = harness.temp_dir("gold-tie-a-"), harness.temp_dir("gold-tie-b-")
        try:
            for folder, (first, second) in ((one, ("AAA", "BBB")), (other, ("BBB", "AAA"))):
                (folder / "hook-100.jsonl").write_text(first, encoding="utf-8")
                (folder / "hook-200.jsonl").write_text(second, encoding="utf-8")
            a_recs = [(p["path"], s) for p, s in T.tree_records(T.Registry(RULES, "", tempfile.gettempdir()), one)]
            b_recs = [(p["path"], s) for p, s in T.tree_records(T.Registry(RULES, "", tempfile.gettempdir()), other)]
            check_eq("K12 two files tied on the normalised path are ordered by content, not by their real names", a_recs, b_recs)
            check_eq("K12 (they are two records)", [p for p, _s in a_recs], ["hook-<PID>.jsonl", "hook-<PID>.jsonl"])
        finally:
            harness.cleanup(one)
            harness.cleanup(other)
    finally:
        harness.cleanup(root)


# --- K5 K6 K7 K13: the recorder in a real child process ---------------------------------------------------------------
def hooked(script: str, files=None, env_extra=None, with_hook=True, args=None):
    work = harness.temp_dir("qa-gold-unit-")
    sink = work / "sink"
    (work / "s.py").write_text(script, encoding="utf-8")
    for rel, text in (files or {}).items():
        (work / rel).write_text(text, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith(T.PREFIX)}
    env.pop("PYTHONPATH", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if with_hook:
        env.update({"PYTHONPATH": str(T.SITE_DIR), T.ENV_SINK: str(sink), T.ENV_SPAWN: "0", T.ENV_DEFAULT: "_main",
                    T.ENV_FILE: "unit", T.ENV_MODULES: "story_run", T.ENV_PLUGIN: str(work / "pkg")})
    env.update(env_extra or {})
    done = subprocess.run([sys.executable, "-B", str(work / "s.py"), *(args or [])], cwd=str(work), env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=180)
    final = sink / "final" / "_main.jsonl"
    records = [json.loads(l) for l in final.read_text(encoding="utf-8").split("\n") if l] if final.is_file() else []
    return done, records, work, sink


def kinds(records) -> list:
    return [r["kind"] for r in records]


K5_SCRIPT = r'''
import os, shutil, socket, tempfile
d = tempfile.mkdtemp(prefix="k5-")
p = os.path.join(d, "a.txt")
open(p, "w").write("one")
with open(p, "a") as h:
    h.write("two")
os.rename(p, os.path.join(d, "b.txt"))
os.replace(os.path.join(d, "b.txt"), os.path.join(d, "c.txt"))
shutil.copyfile(os.path.join(d, "c.txt"), os.path.join(d, "copy.txt"))
shutil.move(os.path.join(d, "copy.txt"), os.path.join(d, "moved.txt"))
os.remove(os.path.join(d, "moved.txt"))
os.mkdir(os.path.join(d, "sub"))
os.rmdir(os.path.join(d, "sub"))
open(os.path.join(d, "c.txt")).read()
try:
    socket.create_connection(("127.0.0.1", 9), timeout=1)
except OSError:
    pass
shutil.rmtree(d)
'''


def k5_events() -> None:
    done, recs, work, _sink = hooked(K5_SCRIPT)
    try:
        check_eq("K5 the script itself exits 0", done.returncode, 0)
        have = set(kinds(recs))
        for kind in ("begin", "write", "rename", "remove", "rmdir", "copy", "net", "tree", "rmtree", "end"):
            check(f"K5 the audited call of kind {kind!r} yields its record", kind in have, f"kinds seen: {sorted(have)}")
        begin = recs[0]["payload"]
        check_eq("K5 the Python version is recorded in begin", begin["python"], "%d.%d" % sys.version_info[:2])
        writes = [r for r in recs if r["kind"] == "write"]
        check("K5 a write opened for appending is recorded as mode a, with its delta bytes",
              any(w["payload"]["mode"] == "a" and w["payload"]["bytes"] == 3 for w in writes), str(writes))
        renames = [r["payload"] for r in recs if r["kind"] == "rename"]
        check("K5 os.rename, os.replace and shutil.move are one record each (the move's own os.rename is absorbed)",
              len(renames) == 3, str(renames))
        check("K5 the tree of a registered root is recorded BEFORE its rmtree",
              kinds(recs).index("tree") < kinds(recs).index("rmtree"), str(kinds(recs)))
        check("K5 a connect to the loopback is a net record", any(r["payload"]["address"].startswith("127.0.0.1") for r in recs
                                                                  if r["kind"] == "net"))
        check("K5 the shutil.rmtree's own removals are not extra remove records",
              kinds(recs).count("remove") == 1 and kinds(recs).count("rmdir") == 1, str(kinds(recs)))
    finally:
        harness.cleanup(work)
    done, recs, work, sink = hooked("open('x.txt', 'w').write('1')\n", with_hook=False)
    try:
        check("K5 control: the recorder inactive (variable unset) gives zero records and no sink", not sink.exists() and not recs)
    finally:
        harness.cleanup(work)
    done, recs, work, _sink = hooked("open('s.py').read()\nopen('s.py', 'rb').read()\n")
    try:
        check_eq("K5 a read-only open yields no record", kinds(recs), ["begin", "end"])
    finally:
        harness.cleanup(work)


CHILD = "import sys\nopen(sys.argv[0] + '.out', 'w').write('child')\n"
K6_SCRIPT = r'''
import os, subprocess, sys
subprocess.run([sys.executable, "child.py"])
bare = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
subprocess.run([sys.executable, "child2.py"], env=bare)
subprocess.run([sys.executable, "chain.py"])
if len(sys.argv) > 1:
    subprocess.run([sys.executable, "-I", "child.py"])
'''
CHAIN = "import subprocess, sys\nsubprocess.run([sys.executable, 'child3.py'])\n"


def k6_children() -> None:
    files = {"child.py": CHILD, "child2.py": CHILD, "child3.py": CHILD, "chain.py": CHAIN}
    done, recs, work, _sink = hooked(K6_SCRIPT, files=files)
    try:
        check_eq("K6 the parent exits 0", done.returncode, 0)
        spawns = [r for r in recs if r["kind"] == "spawn" and r["proc"] == "0"]
        check_eq("K6 three spawns of the parent (inherited env, explicit env without PYTHONPATH, a 2-level chain)", len(spawns), 3)
        order = kinds(recs)
        first = order.index("spawn")
        check("K6 a child's stream sits between its spawn and its exit",
              order[first:first + 6] == ["spawn", "wait", "child", "write", "child_end", "exit"], str(order[first:first + 7]))
        procs = {r["proc"] for r in recs}
        check("K6 the chain is traced to the grandchild (proc 0.3.1)", "0.3.1" in procs and "0.1" in procs and "0.2" in procs,
              str(sorted(procs)))
        check("K6 no child is missing its recorder", "hook_missing" not in order)
    finally:
        harness.cleanup(work)
    done, recs, work, _sink = hooked(K6_SCRIPT, files=files, args=["with-isolated"])
    try:
        missing = [r for r in recs if r["kind"] == "hook_missing"]
        check("K6 control: a child started with -I has no recorder and is named", len(missing) == 1
              and missing[0]["payload"]["script"] == "child.py", str(missing))
        run = fake_run("f.py", {"_main": [T.dumps({"seq": i, **{k: v for k, v in r.items() if k != "seq"}})
                                           for i, r in enumerate(recs)]})
        G.validate(run, {"kind": "outside", "side": [], "inproc": []}, RULES)
        check("K6 control: the CLI's validation refuses the file naming the script (exit 2 in the CLI)",
              any("child.py" in p and "no recorder" in p for p in run.problems), str(run.problems))
    finally:
        harness.cleanup(work)


def k6_killed_child() -> None:
    script = ("import subprocess, sys\np = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
              "p.kill()\np.wait()\n")
    done, recs, work, _sink = hooked(script)
    try:
        check_eq("K6 a Python child the driver killed is recorded as killed (not a missing recorder), spawn then exit",
                 kinds(recs), ["begin", "spawn", "wait", "child_killed", "exit", "end"])
        killed = [r["payload"] for r in recs if r["kind"] == "child_killed"]
        check_eq("K6 and names the script (-c for an inline program)", [k["script"] for k in killed], ["-c"])
    finally:
        harness.cleanup(work)


def k4_wait_splice() -> None:
    """F4: the child's records are spliced where the parent WAITS, not where it spawned: what the parent did between Popen and
    communicate (B-268's in-flight marking) stays before the child, and moving it after communicate is a different trace."""
    child = "import sys\nopen(sys.argv[0] + '.out', 'w').write('child')\n"
    before = ("import subprocess, sys\np = subprocess.Popen([sys.executable, 'child.py'], stdout=subprocess.PIPE)\n"
              "open('between.txt', 'w').write('marked')\np.communicate()\n")
    after = ("import subprocess, sys\np = subprocess.Popen([sys.executable, 'child.py'], stdout=subprocess.PIPE)\n"
             "p.communicate()\nopen('between.txt', 'w').write('marked')\n")
    shapes = []
    for script in (before, after):
        done, recs, work, _sink = hooked(script, files={"child.py": child})
        try:
            check_eq("F4 the script exits 0", done.returncode, 0)
            shapes.append([(r["kind"], os.path.basename(r["payload"].get("path", ""))) for r in recs
                           if r["kind"] in ("spawn", "wait", "child", "child_end", "exit") or r["payload"].get("path", "").endswith("between.txt")])
        finally:
            harness.cleanup(work)
    check_eq("F4 a write between Popen and communicate sits BEFORE the wait record, and the child block follows the wait",
             [k for k, _p in shapes[0]], ["spawn", "write", "wait", "child", "child_end", "exit"])
    check_eq("F4 control: the same write after communicate sits after the child's exit",
             [k for k, _p in shapes[1]], ["spawn", "wait", "child", "child_end", "exit", "write"])
    check("F4 control: the two shapes differ (the moved write is a different trace)", shapes[0] != shapes[1])


def k8_codec_boundary() -> None:
    """FR-31 (t-374): a write's digest does not depend on whether the process had already imported the codec of the file's
    encoding. Opening a file with an encoding nothing has imported yet makes the interpreter read that codec's .pyc BETWEEN the
    write's `open` event and its content: a digest taken at that read-only open saw an empty file (it did, in a launch without
    a console and with a cp1252 locale, where the first text file imports cp1252)."""
    script = "f = open('c.txt', 'w', encoding='cp857')\nf.write('hello')\nf.close()\nopen('d.txt', 'w').write('hello')\n"
    done, recs, work, _sink = hooked(script)
    try:
        shas = {os.path.basename(r["payload"]["path"]): r["sha"] for r in recs if r["kind"] == "write"}
        expected = hashlib.sha256(b"hello").hexdigest()
        check_eq("FR-31 a write opened with a codec not imported yet is digested WITH its content", shas.get("c.txt"), expected)
        check_eq("FR-31 and a plain write after it", shas.get("d.txt"), expected)
        reader = ("open('x.txt', 'w').write('abc')\nopen('x.txt').read()\n")
        done, recs2, work2, _s2 = hooked(reader)
        try:
            check_eq("FR-31 a read of the very file that is pending still digests it first (the reader sees it)",
                     [r["sha"] for r in recs2 if r["kind"] == "write" and r["payload"]["path"].endswith("x.txt")],
                     [hashlib.sha256(b"abc").hexdigest()])
        finally:
            harness.cleanup(work2)
    finally:
        harness.cleanup(work)


def k7_pid_binding() -> None:
    """F7: a pid is `PID-<proc>`, bound to the process it names: the child's own id written by the parent and by the child
    is ONE token, and the parent's own id written where a child's belongs is another."""
    child = "import os\nopen('c.txt', 'w').write('{\"pid\": %d}' % os.getpid())\n"
    script = ("import os, subprocess, sys\np = subprocess.Popen([sys.executable, 'c.py'])\n"
              "open('marked.txt', 'w').write('{\"pid\": %d}' % p.pid)\np.wait()\n"
              "open('wrong.txt', 'w').write('{\"pid\": %d}' % os.getpid())\n")
    done, recs, work, _sink = hooked(script, files={"c.py": child})
    try:
        check_eq("F7 the script exits 0", done.returncode, 0)
        shas = {os.path.basename(r["payload"]["path"]): r["sha"] for r in recs if r["kind"] == "write" and r["payload"]["path"].endswith(".txt")}
        child_token = hashlib.sha256(b'{"pid": "<PID-0.1>"}').hexdigest()
        check_eq("F7 the child's pid written by the PARENT is PID-0.1", shas.get("marked.txt"), child_token)
        check_eq("F7 the child's own pid written by the CHILD is the same token", shas.get("c.txt"), child_token)
        check_eq("F7 control: the parent's own pid where a child's belongs is PID-0, a different token",
                 shas.get("wrong.txt"), hashlib.sha256(b'{"pid": "<PID-0>"}').hexdigest())
    finally:
        harness.cleanup(work)


def f3_the_swap() -> None:
    """F3: the probe's verdict needs the swapped pair ITSELF as the first difference against its control; a fingerprint-only
    difference, a dropped record or a different pair is `not the swap` (exit 1 in the CLI)."""
    def line(seq, kind, **payload):
        sha = payload.pop("sha", None)
        rec = {"seq": seq, "proc": "0", "kind": kind, "payload": payload}
        if sha:
            rec["sha"] = sha
        return T.dumps(rec)
    begin = line(0, "begin", file="f")
    write = lambda seq: line(seq, "write", path="<ROOT-1>\\state\\driver-runs\\S5-1.json", bytes=5, mode="w", sha="a" * 64)
    progress = lambda seq, text="[progress] x\n": line(seq, "stdout", text=text, stream="out")
    tail = lambda seq: line(seq, "end", outcome="returned")
    control = [begin, write(1), progress(2), tail(3)]
    swapped = [begin, progress(1, "[progress] before the write\n"), write(2), tail(3)]
    ok, why = G.is_the_swap(control, swapped, T.compare_lines(control, swapped)["seq"])
    check("F3 the swapped pair is the first difference: the probe's verdict", ok, why)
    fingerprint_only = [begin, line(1, "write", path="<ROOT-1>\\state\\driver-runs\\S5-1.json", bytes=5, mode="w", sha="b" * 64),
                        progress(2), tail(3)]
    ok, why = G.is_the_swap(control, fingerprint_only, T.compare_lines(control, fingerprint_only)["seq"])
    check("F3 control: a difference in the write's own sha (the fingerprint case) is NOT the swap", not ok, why)
    dropped = [begin, progress(1), tail(2)]
    ok, why = G.is_the_swap(control, dropped, T.compare_lines(control, dropped)["seq"])
    check("F3 control: a dropped record is NOT the swap", not ok, why)
    other_pair = [begin, write(1), line(2, "write", path="x", bytes=1, mode="w", sha="c" * 64), tail(3)]
    ok, why = G.is_the_swap(control, other_pair, T.compare_lines(control, other_pair)["seq"])
    check("F3 control: another pair at the first difference is NOT the swap", not ok, why)


def k7_stdout() -> None:
    driver = "def hello():\n    print('from the driver')\n"
    script = ("import contextlib, io, story_run\nstory_run.hello()\n"
              "with contextlib.redirect_stdout(io.StringIO()):\n    story_run.hello()\nprint('from the test')\n")
    done, recs, work, _sink = hooked(script, files={"story_run.py": driver})
    try:
        out = [r["payload"]["text"] for r in recs if r["kind"] == "stdout"]
        check_eq("K7 a print from a driver-module frame is recorded, also under redirect_stdout; one from a test frame is not",
                 out, ["from the driver\n", "from the driver\n"])
    finally:
        harness.cleanup(work)
    done, recs, work, _sink = hooked(script, files={"story_run.py": driver}, env_extra={T.ENV_MODULES: "nosuchmodule"})
    try:
        check_eq("K7 control: a module set that does not hold the driver gives no stdout record",
                 [r for r in recs if r["kind"] == "stdout"], [])
    finally:
        harness.cleanup(work)


def k13_fakes() -> None:
    driver = ("class Driver:\n    def __init__(self):\n        self.sleep = None\n\n"
              "    def run_role(self, what, role=''):\n        return what\n\n"
              "    def mark_in_flight(self, dispatch, pid, resume=''):\n        return None\n")
    script = ("import story_run\nd = story_run.Driver()\nd.run_role = lambda x, role='r': x\nd.run_role(5, role='qa')\n"
              "d.mark_in_flight = lambda dispatch, pid, resume='': None\nd.mark_in_flight('S5-1', 4321, '')\n"
              "d.data = {'k': 1}\nd.sleep = lambda s: None\nd.sleep(3)\n")
    done, recs, work, _sink = hooked(script, files={"story_run.py": driver})
    try:
        check_eq("K13 the script exits 0", done.returncode, 0)
        fakes = [r["payload"] for r in recs if r["kind"] == "fake_call"]
        check_eq("K13 a callable assigned under a Driver method name records fake_call, with its arguments; the pid argument of "
                 "mark_in_flight is a token (rules fake_arg_tokens)",
                 fakes, [{"name": "run_role", "args": ["5", "role=qa"]}, {"name": "mark_in_flight", "args": ["S5-1", "<PID>", ""]}])
        check("K13 control: a data attribute and `sleep` (not a class method) record nothing",
              [f["name"] for f in fakes] == ["run_role", "mark_in_flight"])
    finally:
        harness.cleanup(work)


def k_liveness() -> None:
    run = fake_run("f.py", {"_main": []})
    G.validate(run, {"kind": "outside", "side": [], "inproc": []}, RULES)
    check("E10 an empty stream from a recorder that did not run is refused, never equal to a short golden",
          any("no `begin`" in p for p in run.problems), str(run.problems))
    begin_end = [T.dumps({"seq": 0, "proc": "0", "kind": "begin", "payload": {}}),
                 T.dumps({"seq": 1, "proc": "0", "kind": "end", "payload": {"outcome": "returned"}})]
    run = fake_run("f.py", {"_main": begin_end})
    G.validate(run, {"kind": "outside", "side": [], "inproc": []}, RULES)
    check_eq("E10 control: a unit-only scenario (begin and end) is a valid short golden", run.problems, [])
    net = begin_end[:1] + [T.dumps({"seq": 1, "proc": "0", "kind": "net", "payload": {"address": "93.184.216.34:443"}})] + begin_end[1:]
    run = fake_run("f.py", {"_main": net})
    G.validate(run, {"kind": "outside", "side": [], "inproc": []}, RULES)
    check("E2 a connect to a non-loopback address refuses the record", any("offline-only" in p for p in run.problems), str(run.problems))


# --- K14, K15, K1, K2, C1 and the CLI battery, on a fixture package ----------------------------------------------------
SR_TEMPLATE = '''import os


class Driver:
    def __init__(self, root):
        self.root = root

    def go(self):
        a = os.path.join(self.root, "a.txt")
        b = os.path.join(self.root, "b.txt")
        FIRST
        SECOND
        print("[progress] done")
        STRAY

    def never_called(self):
        return "this line is never run"
'''

TEST_TEMPLATE = '''import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import story_run


def run_scenarios(side_by_side, in_process):
    recorder = sys.modules.get("driver_trace")
    for scenario in side_by_side + in_process:
        if recorder is not None:
            with recorder.scenario(scenario.__name__):
                scenario()
        else:
            scenario()


def s_write():
    root = tempfile.mkdtemp(prefix="gold-fix-")
    try:
        story_run.Driver(root).go()
        subprocess.run([sys.executable, "-c", "open(%r, 'w').write('child')" % os.path.join(root, "child.txt")])
    finally:
        shutil.rmtree(root)


def s_other():
    OTHER


run_scenarios([], [s_write, s_other])
TAIL
'''


def make_pkg(root: Path, order="ab", other="pass", tail="", stray=False) -> Path:
    scripts = root / "scripts"
    tests = scripts / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    write_a = 'open(a, "w").write("A")'
    write_b = 'open(b, "w").write("B")'
    first, second = (write_a, write_b) if order == "ab" else (write_b, write_a)
    stray_line = 'open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "stray.txt"), "w").write("x")' if stray else "pass"
    (scripts / "story_run.py").write_text(SR_TEMPLATE.replace("FIRST", first).replace("SECOND", second)
                                          .replace("STRAY", stray_line), encoding="utf-8")
    (tests / "test_story_run_fix.py").write_text(TEST_TEMPLATE.replace("OTHER", other).replace("TAIL", tail), encoding="utf-8")
    return root


def fixture_rules(root: Path, ceiling=120, exclude=None, drop_rows=(), name="rules.json") -> Path:
    rules = json.loads(json.dumps(RULES))
    rules["files"]["outside"] = []
    rules["ceiling_seconds"] = {"default": ceiling}
    rules["scenario_exclude"] = list(exclude or [])
    rules["rows"] = [r for r in rules["rows"] if r["id"] not in drop_rows]
    path = root / name
    path.write_text(json.dumps(rules), encoding="utf-8")
    return path


def cli(*argv) -> tuple:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = G.main([str(a) for a in argv])
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def fixture_cycle() -> None:
    work = harness.temp_dir("qa-gold-fix-")
    pkg = work / "pkg"
    golden = work / "golden"
    try:
        make_pkg(pkg)
        rules = fixture_rules(work)
        base = ["--package", pkg, "--golden-dir", golden, "--rules", rules]
        before = G.package_paths(pkg)
        code, out = cli("record", *base, "--jobs", 1, "--coverage")
        check_eq("K1 record exits 0 on the fixture package (jobs 1 is serial and accepted)", code, 0)
        check_in("K1 the summary line counts the scenarios", "scenarios recorded=2", out)
        files = sorted(p.name for p in (golden / "test_story_run_fix").glob("*.jsonl"))
        check_eq("K1 one trace per scenario (and none for _outside when it holds nothing)", files, ["s_other.jsonl", "s_write.jsonl"])
        manifest = json.loads((golden / "MANIFEST.json").read_text(encoding="utf-8"))
        check("K1 the MANIFEST holds the scenario list, the python minor, the package hash set",
              set(manifest["files"]["test_story_run_fix"]) == {"s_write", "s_other"} and manifest["python"] == G.python_minor()
              and "scripts/story_run.py" in manifest["package_files"], str(sorted(manifest)))
        blob = b"".join(p.read_bytes() for p in golden.rglob("*") if p.is_file())
        check("K9 every byte written under the golden dir is ASCII with no control byte but newline",
              all(b < 128 and (b >= 32 or b in (10, 13)) for b in blob))
        check_eq("K15 record left nothing in the package", G.package_paths(pkg), before)
        cov = json.loads((golden / "coverage-n0.json").read_text(encoding="utf-8"))
        check("C1 the coverage record lists the function no scenario called, with its function name",
              any(item["function"] == "Driver.never_called" for item in cov["never_run"]), str(cov["never_run"]))
        check("C1 control: a function the scenarios did call is not listed as never run",
              not any(item["function"] == "Driver.go" for item in cov["never_run"]), str(cov["never_run"]))
        write_trace = (golden / "test_story_run_fix" / "s_write.jsonl").read_text(encoding="utf-8").split("\n")
        kinds_seen = [json.loads(l)["kind"] for l in write_trace if l]
        check("K1 the trace has the ordered side effects: writes, the stdout line, the child's spawn and exit, the tree",
              {"write", "stdout", "spawn", "wait", "child", "child_end", "exit", "tree", "rmtree", "end"} <= set(kinds_seen),
              str(kinds_seen))

        code, out = cli("compare", *base)
        check_eq("K2 compare right after the record exits 0", code, 0)
        check_in("K2 and every compared scenario is equal", "compared=2 equal=2", out)
        code, out = cli("compare", *base, "--only", "test_story_run_fix.py::s_write")
        check_in("K2 --only FILE::SCENARIO compares just that scenario", "compared=1 equal=1", out)
        code, out = cli("stability", *base)
        check_eq("K3 stability: two records are byte-equal (exit 0)", code, 0)
        check_in("K3 and it prints the count", "2 unit traces, recorded twice, byte-equal", out)

        make_pkg(pkg, order="ba")
        code, out = cli("compare", *base)
        check_eq("K4 control: a reordered side effect (b written before a) makes compare exit 1", code, 1)
        check("K4 and names the scenario, the first differing seq and both records",
              "DIFFER test_story_run_fix.py::s_write at seq" in out and "golden:" in out and "now:" in out, out[:900])
        check_in("K2 the other scenario is still equal", "compared=2 equal=1", out)

        make_pkg(pkg)
        (pkg / "scripts" / "other_file.py").write_text("x = 1\n", encoding="utf-8")
        code, out = cli("compare", *base)
        check_eq("K14 control: a package file outside the allowed set changed makes compare refuse (exit 2)", code, 2)
        check_in("K14 and the refusal names the file", "scripts/other_file.py", out)
        (pkg / "scripts" / "other_file.py").unlink()
        (pkg / "scripts" / "tests" / "test_story_run_fix.py").write_text(
            (pkg / "scripts" / "tests" / "test_story_run_fix.py").read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        code, out = cli("compare", *base)
        check_eq("K14 control: a changed test file is outside the allowed set too", code, 2)
        make_pkg(pkg)
        (pkg / "design").mkdir()
        (pkg / "design" / "note.md").write_text("allowed\n", encoding="utf-8")
        code, out = cli("compare", *base)
        check("K14 a design/ file is inside the allowed set: compare runs and is equal", code == 0 and "design/note.md" in out, out[:500])
        (pkg / "design" / "note.md").unlink()
        (pkg / "design").rmdir()

        (golden / "test_story_run_fix" / "s_other.jsonl").unlink()
        code, out = cli("compare", *base)
        check_eq("K11 a scenario recorded now and absent from the golden refuses (exit 2)", code, 2)
        check("K11 naming it", "s_other" in out and "not in the golden" in out, out[:500])
    finally:
        harness.cleanup(work)


def fixture_exclusion_and_recorder() -> None:
    """E12: an excluded unit is listed with its reason, counted, kept out of the golden and never counted as equal; a row with
    no reason is a refusal. K14: a golden recorded by another recorder / other normalisation rows is refused."""
    work = harness.temp_dir("qa-gold-excl-")
    pkg = work / "pkg"
    golden = work / "golden"
    try:
        make_pkg(pkg)
        row = {"file": "test_story_run_fix.py", "scenario": "s_other", "reason": "unit-test exclusion"}
        rules = fixture_rules(work, exclude=[row])
        base = ["--package", pkg, "--golden-dir", golden, "--rules", rules]
        code, out = cli("record", *base)
        check_eq("E12 record with one unit excluded exits 0", code, 0)
        check("E12 the exclusion is listed with its reason and counted", "test_story_run_fix.py::s_other - unit-test exclusion" in out
              and "excluded=1" in out, out[-500:])
        check_eq("E12 its trace is not kept", sorted(p.name for p in (golden / "test_story_run_fix").glob("*.jsonl")), ["s_write.jsonl"])
        manifest = json.loads((golden / "MANIFEST.json").read_text(encoding="utf-8"))
        check_eq("E12 the MANIFEST lists it", manifest["excluded"], [{"unit": "test_story_run_fix.py::s_other", "reason": "unit-test exclusion"}])
        code, out = cli("compare", *base)
        check("E12 compare counts the excluded unit and does not count it as equal (compared=1 equal=1 excluded=1)",
              code == 0 and "compared=1 equal=1" in out and "excluded=1" in out, out[-400:])
        bad = fixture_rules(work, exclude=[{"file": "test_story_run_fix.py", "scenario": "s_other", "reason": " "}], name="rules-bad.json")
        code, out = cli("record", "--package", pkg, "--golden-dir", work / "golden-bad", "--rules", bad)
        check("E12 control: an exclusion with no reason is a refusal (exit 2)", code == 2 and "needs a file, a scenario and a reason" in out,
              out[-300:])
        # the rules in effect are part of the recorder: a golden compared under other rules is refused (F5, F6)
        fixture_rules(work, exclude=[row], ceiling=77, name="rules-other.json")
        code, out = cli("compare", "--package", pkg, "--golden-dir", golden, "--rules", work / "rules-other.json")
        check_eq("F5 control: the same package under other rules in effect is refused (exit 2)", code, 2)
        check_in("F5 and says the recorder or its rules changed", "re-record the golden", out)
        (pkg / "scripts" / "tests" / "fixtures").mkdir(parents=True, exist_ok=True)
        own = pkg / "scripts" / "tests" / "fixtures" / "driver-golden-rules.json"
        own.write_bytes(rules.read_bytes())
        code, out = cli("compare", *base)
        check("F5: --rules naming the package's own rules bytes is accepted (compare runs, exit 0)", code == 0, out[-500:])
        code, out = cli("compare", "--package", pkg, "--golden-dir", golden, "--rules", work / "rules-other.json")
        check_eq("F5 control: a --rules file whose bytes differ from the package's own file is refused (exit 2)", code, 2)
        check_in("F5 and names both files", "differs from the package's own", out)
        own.unlink()
        # the recorder changed under a golden: the hook installer / recorder is part of the recorder hash
        (pkg / "scripts" / "tests" / "driver_trace.py").write_text("# a different recorder\n", encoding="utf-8")
        code, out = cli("compare", *base)
        check_eq("K14 control: a changed recorder file makes compare refuse (exit 2)", code, 2)
        check_in("K14 and says to re-record", "re-record the golden", out)
        code, out = cli("record", *base, "--only", "test_story_run_fix.py")
        check_eq("K14 control: a slice on a changed recorder is refused too", code, 2)
        (pkg / "scripts" / "tests" / "driver_trace.py").unlink()
        (pkg / "scripts" / "tests" / "driver_golden.py").write_text("# a different CLI\n", encoding="utf-8")
        code, out = cli("compare", *base)
        check_eq("F6 control: a changed driver_golden.py (it shapes the test process's environment) makes compare refuse", code, 2)
    finally:
        os.environ.pop(T.ENV_RULES, None)
        harness.cleanup(work)


def same_bytes(dir_a: Path, dir_b: Path, pattern: str) -> bool:
    a = {p.relative_to(dir_a).as_posix(): p.read_bytes() for p in dir_a.rglob(pattern)}
    b = {p.relative_to(dir_b).as_posix(): p.read_bytes() for p in dir_b.rglob(pattern)}
    return bool(a) and a == b


def fixture_relocation() -> None:
    """F2/F8: the same bytes in another directory are the same trace where a value derives from the length of text that holds a
    path (row N32), and a golden compared from another root is refused naming both roots and the door."""
    work = harness.temp_dir("qa-gold-rel-")
    row_code = ('d = tempfile.mkdtemp(prefix="gold-rel-"); open(os.path.join(d, "driver-questions.jsonl"), "w").write('
                '\'{"dispatch": "", "bytes": %d, "details_file": false}\\n\' % len(os.path.dirname(os.path.abspath(__file__)))); '
                'shutil.rmtree(d)')
    near, far = work / "pkg-a", work / "a-much-longer-package-directory-name-b"
    try:
        for root in (near, far):
            make_pkg(root, other=row_code)
        rules = fixture_rules(work)
        without = fixture_rules(work, drop_rows=("N32",), name="rules-no-n32.json")
        for label, rule_file in (("with N32", rules), ("without N32", without)):
            goldens = []
            for root in (near, far):
                golden = work / f"golden-{label.replace(' ', '-')}-{root.name[:6]}"
                code, out = cli("record", "--package", root, "--golden-dir", golden, "--rules", rule_file)
                check_eq(f"F2 record {label} at {root.name[:12]} exits 0", code, 0)
                goldens.append(golden)
            equal = same_bytes(goldens[0], goldens[1], "*.jsonl")
            if label == "with N32":
                check("F2 the same bytes in another directory (a different path length) record the SAME traces with row N32", equal)
            else:
                check("F2 control: without row N32 the relocated copy records a DIFFERENT trace (the test can fail)", not equal)
            if label == "with N32":
                manifest = json.loads((goldens[0] / "MANIFEST.json").read_text(encoding="utf-8"))
                check("F2/F8 the MANIFEST records the package root and the commit field", G.same_root(manifest["package_root"], near)
                      and "package_commit" in manifest, str(sorted(manifest)))
                code, out = cli("compare", "--package", far, "--golden-dir", goldens[0], "--rules", rule_file)
                check_eq("F2 compare from another root is refused (exit 2)", code, 2)
                check("F2 naming both roots and the door", near.name in out and far.name in out and "freeze the package at" in out, out[:600])
    finally:
        os.environ.pop(T.ENV_RULES, None)
        harness.cleanup(work)


def fixture_fingerprint() -> None:
    """F1: a one-byte package change compares equal where nothing else moved, because package_fingerprint is a token; without
    row N31 the same change is a difference."""
    work = harness.temp_dir("qa-gold-fp-")
    fp_code = ('d = tempfile.mkdtemp(prefix="gold-fp-"); open(os.path.join(d, "controller.json"), "w").write('
               '\'{"package_fingerprint": "%s"}\' % __import__("hashlib").sha256(open(story_run.__file__, "rb").read()).hexdigest()); '
               'shutil.rmtree(d)')
    try:
        for label, drop in (("with N31", ()), ("without N31", ("N31",))):
            pkg = work / ("pkg-" + label.replace(" ", "-"))
            make_pkg(pkg, other=fp_code)
            rule_file = fixture_rules(work, drop_rows=drop, name=f"rules-{label.replace(' ', '-')}.json")
            golden = work / ("golden-" + label.replace(" ", "-"))
            base = ["--package", pkg, "--golden-dir", golden, "--rules", rule_file]
            code, out = cli("record", *base)
            check_eq(f"F1 record {label} exits 0", code, 0)
            (pkg / "scripts" / "story_run.py").write_bytes((pkg / "scripts" / "story_run.py").read_bytes() + b"# one byte more\n")
            code, out = cli("compare", *base)
            if label == "with N31":
                check("F1 a one-byte package change compares EQUAL where nothing else moved (the fingerprint is a token)",
                      code == 0 and "compared=2 equal=2" in out, out[-300:])
            else:
                check("F1 control: without row N31 the same change is a difference (exit 1)", code == 1 and "DIFFER" in out, out[-300:])
    finally:
        os.environ.pop(T.ENV_RULES, None)
        harness.cleanup(work)


def fixture_ambient_scrub() -> None:
    """A variable the driver sets itself is not inherited from the host shell (the Bash tool lacks it, the PowerShell tool has it:
    a golden recorded in one shell differed from a compare in the other)."""
    work = harness.temp_dir("qa-gold-amb-")
    pkg = work / "pkg"
    golden = work / "golden"
    held = os.environ.get("GIT_TERMINAL_PROMPT")
    try:
        make_pkg(pkg, other='d = tempfile.mkdtemp(prefix="gold-env-"); open(os.path.join(d, "v.txt"), "w").write(str(os.environ.get("GIT_TERMINAL_PROMPT"))); shutil.rmtree(d)')
        rules = fixture_rules(work)
        os.environ["GIT_TERMINAL_PROMPT"] = "0"
        code, out = cli("record", "--package", pkg, "--golden-dir", golden, "--rules", rules)
        check_eq("ambient: record exits 0 with the host variable set", code, 0)
        records = [json.loads(l) for l in (golden / "test_story_run_fix" / "s_other.jsonl").read_text(encoding="utf-8").split("\n") if l]
        seen = [r for r in records if r["kind"] == "write" and r["payload"]["path"].endswith("v.txt")]
        check("ambient: the scenario saw NO GIT_TERMINAL_PROMPT although the host shell has it (its file holds 'None')",
              len(seen) == 1 and seen[0]["sha"] == hashlib.sha256(b"None").hexdigest(), str(seen))
    finally:
        if held is None:
            os.environ.pop("GIT_TERMINAL_PROMPT", None)
        else:
            os.environ["GIT_TERMINAL_PROMPT"] = held
        os.environ.pop(T.ENV_RULES, None)
        harness.cleanup(work)


def fixture_slices() -> None:
    """The record in slices (a few files per call): the slices join ONE golden, a slice of another package state is refused,
    and a golden missing a file is incomplete for compare."""
    work = harness.temp_dir("qa-gold-slice-")
    pkg = work / "pkg"
    golden = work / "golden"
    try:
        make_pkg(pkg)
        tests = pkg / "scripts" / "tests"
        (tests / "test_story_run_fix2.py").write_text((tests / "test_story_run_fix.py").read_text(encoding="utf-8"), encoding="utf-8")
        rules = fixture_rules(work)
        base = ["--package", pkg, "--golden-dir", golden, "--rules", rules]
        code, out = cli("record", *base, "--only", "test_story_run_fix.py")
        check_eq("slice: recording the first file alone exits 0", code, 0)
        check_in("slice: and says it is a slice", "(a slice)", out)
        code, out = cli("compare", *base)
        check_eq("slice control: compare on a golden that lacks a test file refuses (exit 2)", code, 2)
        check_in("slice control: naming the file the golden does not have", "test_story_run_fix2.py", out)
        code, out = cli("record", *base, "--only", "test_story_run_fix2.py")
        check_eq("slice: the second file joins the same golden (exit 0)", code, 0)
        manifest = json.loads((golden / "MANIFEST.json").read_text(encoding="utf-8"))
        check_eq("slice: the MANIFEST lists both files", sorted(manifest["files"]), ["test_story_run_fix", "test_story_run_fix2"])
        code, out = cli("compare", *base)
        check("slice: compare of the joined golden is equal on every scenario", code == 0 and "compared=4 equal=4" in out, out[-400:])
        code, out = cli("record", *base, "--only", "test_story_run_fix2.py::s_write")
        check_eq("slice control: a record of one SCENARIO is refused (it would mix two recordings of a file)", code, 2)
        (pkg / "scripts" / "other_file.py").write_text("x = 1\n", encoding="utf-8")      # another package state (outside the allowed set)
        code, out = cli("record", *base, "--only", "test_story_run_fix2.py")
        check_eq("slice control: a slice recorded on another package state is refused (exit 2)", code, 2)
        check_in("slice control: and says to freeze one package state", "one package state", out)
        code, out = cli("record", *base, "--only", "test_story_run_fix.py,test_story_run_fix.py")
        check_eq("CLI battery: a file named twice in --only exits 2", code, 2)
    finally:
        os.environ.pop(T.ENV_RULES, None)
        harness.cleanup(work)


def fixture_refusals() -> None:
    work = harness.temp_dir("qa-gold-ref-")
    pkg = work / "pkg"
    golden = work / "golden"
    try:
        rules = fixture_rules(work, ceiling=6)
        base = ["--package", pkg, "--golden-dir", golden, "--rules", rules]
        make_pkg(pkg, other='print("FAIL the scenario is red")', tail="sys.exit(1)")
        code, out = cli("record", *base)
        check_eq("K1 control: a test file with a FAIL makes the record exit 2", code, 2)
        check("K1 and names the file and the FAIL line", "test_story_run_fix.py" in out and "FAIL the scenario is red" in out, out[:600])
        check("K1 and no golden is kept from a red record", not (golden / "MANIFEST.json").exists())

        make_pkg(pkg, other="time.sleep(60)")
        code, out = cli("record", *base)
        check_eq("E1 control: a scenario that hangs is killed at the ceiling and the record refuses (exit 2)", code, 2)
        check("E1 naming the file and the last scenario that began", "killed at its ceiling" in out and "s_other" in out, out[:600])

        make_pkg(pkg, other="t = threading.Thread(target=lambda: open('loose.txt', 'w').write('x'))\n    t.start()\n    t.join()")
        code, out = cli("record", *base)
        check_eq("E6 control: an event raised in a thread no scenario tagged refuses the record (exit 2)", code, 2)
        check_in("E6 and says so", "thread no scenario tagged", out)
        for stray in work.parent.glob("loose.txt"):
            pass

        make_pkg(pkg, stray=True)
        before = G.package_paths(pkg)
        code, out = cli("record", *base)
        check_eq("K15 control: a run that writes a stray file into the package is refused (exit 2)", code, 2)
        check_in("K15 and the refusal names the stray path", "stray.txt", out)
        for path in pkg.rglob("stray.txt"):
            path.unlink()
        check_eq("K15 (the fixture's stray file removed, the package is as it was)", G.package_paths(pkg), before)

        make_pkg(pkg)
        cli("record", *base)
        code, out = cli("compare", "--package", pkg, "--golden-dir", work / "nowhere", "--rules", rules)
        check_eq("K11 an absent golden dir refuses (exit 2)", code, 2)
        check_in("K11 and says to record on the parent commit", "no golden recorded", out)
        empty = work / "empty"
        empty.mkdir()
        code, out = cli("compare", "--package", pkg, "--golden-dir", empty, "--rules", rules)
        check_eq("K11 an empty golden dir refuses (exit 2)", code, 2)

        # the CLI battery (spec section 5)
        cases = [
            ("no mode", [], "no mode given"),
            ("two modes", ["record", "--compare"], "two modes"),
            ("--only empty", ["compare", "--only", ""], "--only is empty"),
            ("--only nosuch.py", ["compare", "--only", "nosuch.py"], "Known files"),
            ("--only f.py::", ["compare", "--only", "test_story_run_fix.py::"], "nothing after"),
            ("--only f.py::nosuch", ["compare", "--only", "test_story_run_fix.py::nosuch"], "s_write"),
            ("a scenario name with spaces", ["compare", "--only", "test_story_run_fix.py::s write"], "no scenario"),
            ("a non-ASCII scenario name", ["compare", "--only", "test_story_run_fix.py::\u0441\u0446\u0435\u043d\u0430\u0440\u0438\u0439"], "no scenario"),
            ("--jobs 0", ["compare", "--jobs", "0"], "--jobs 0"),
            ("an unknown probe", ["probe", "nosuch-probe"], "unknown probe"),
        ]
        for label, argv, needle in cases:
            code, out = cli(*argv, *base) if argv else cli(*base)
            check(f"CLI battery: {label} exits 2 and says what is wrong", code == 2 and needle in out, f"exit {code}: {out[:400]}")
        code, out = cli("compare", "--package", work, "--golden-dir", golden, "--rules", rules)
        check("CLI battery: --package at a directory with no scripts/story_run.py exits 2", code == 2 and "no scripts/story_run.py" in out, out[:300])
        code, out = cli("compare", "--package", pkg, "--rules", rules)
        check("CLI battery: no --golden-dir exits 2 and names the option", code == 2 and "--golden-dir" in out, out[:300])
    finally:
        os.environ.pop(T.ENV_RULES, None)
        harness.cleanup(work)


def main() -> None:
    k8_rows()
    k8_paths()
    k9_ascii()
    k4_order()
    k3_k11()
    k10_caps()
    k12_tree()
    k5_events()
    k6_children()
    k6_killed_child()
    k4_wait_splice()
    k8_codec_boundary()
    k7_pid_binding()
    f3_the_swap()
    k7_stdout()
    k13_fakes()
    k_liveness()
    fixture_cycle()
    fixture_exclusion_and_recorder()
    fixture_ambient_scrub()
    fixture_relocation()
    fixture_fingerprint()
    fixture_slices()
    fixture_refusals()
    finish("test_driver_golden")


if __name__ == "__main__":
    main()
