"""B-414 (D-0029, D-0032): the environment record - what a person accepted ONCE as a property of this environment.

The error direction is toward ASKING: a record that cannot be read, a revoked row, a changed key, a gap with no key and a gap whose
cause is a file or the machine each cover nothing. The keys of the dispatch: E14 (the battery of inputs `covering` must keep on the
safe side), E5 (no key, nothing recorded under a placeholder), E8/E9/E10 (revoke, unreadable record, two live rows), E11 (the
covered words at 160/161) and M13 (the accept-always door is NEVER open for a file/machine fault, tested at the boundary of the two
classes).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     temp_dir, use_project)

sys.path.insert(0, str(SCRIPTS))

import environment_record as ER  # noqa: E402
import gate_brief  # noqa: E402

ARGV = ["python", "runner.py", "{report_path}", "<test-id>"]
CHECK = {"http": {"path": "/v1/config", "status": 200, "json_path": "features.f1", "equals": True}}
CASE_GAP = {"scope": "case", "kind": "feature_flag", "what": "sub-workflow states are enabled", "check": CHECK}
LEVEL_GAP = {"scope": "level", "contour": "web", "reason_class": "zero_tests", "exit_code": 0}


def cfg(url: str = "http://qa.invalid:8080", argv=None) -> dict:
    return {"environments": [{"name": "QA", "base_url": url, "frontend_url": "http://qa.invalid"}],
            "profiles": [{"profile_id": "web", "commands": {"one_test": {"argv": list(argv or ARGV), "cwd": "."}}}]}


def key_of(gap, config=None, stand="QA"):
    return ER.property_key(gap, config or cfg(), stand)


def level_key() -> dict:
    return key_of(LEVEL_GAP)


def case_key() -> dict:
    return key_of(CASE_GAP)


def row(key, at="2026-10-05T10:00:00+00:00", id="EP-1", **extra) -> dict:
    return dict({"id": id, "subject": key, "option": "accept", "words": "web: accept always", "at": at, "story": "T-1"}, **extra)


def part_keys() -> None:
    check_eq("a level key holds the contour, the digest of its command and the class of the failure",
             sorted(level_key()), ["argv_digest", "contour", "reason_class", "scope"])
    check_eq("a case key holds the stand, its definition, the kind and the digest of the check",
             sorted(case_key()), ["check_digest", "definition_sha", "environment", "precondition_kind", "scope"])
    check_eq("a key is the same for the same command (it is a digest, not a time)", level_key(), level_key())
    other = key_of(LEVEL_GAP, cfg(argv=ARGV + ["--x"]))
    check("another command is another key (E4)", other["argv_digest"] != level_key()["argv_digest"])
    check("a re-pointed stand is another key (E4: a new definition sha)",
          key_of(CASE_GAP, cfg(url="http://other.invalid"))["definition_sha"] != case_key()["definition_sha"])
    reordered = {"http": {"equals": True, "json_path": "features.f1", "status": 200, "path": "/v1/config"}}
    check_eq("the same check with another key order is the one covered positive (E14)",
             key_of(dict(CASE_GAP, check=reordered)), case_key())
    check("`equals` false against true is another key (E14)",
          key_of(dict(CASE_GAP, check={"http": dict(CHECK["http"], equals=False)})) != case_key())
    # E5 / E14: nothing is recorded under a placeholder, an empty definition or a prose check
    for label, got in (("a stand named `this stand`", key_of(CASE_GAP, stand="this stand")),
                       ("an empty stand name", key_of(CASE_GAP, stand="")),
                       ("a stand the config does not have (an empty definition sha)", key_of(CASE_GAP, stand="nowhere")),
                       ("a prose `none` check", key_of(dict(CASE_GAP, check={"none": "the superadmin holds it"}))),
                       ("a check no machine made (case_seeds)", key_of(dict(CASE_GAP, check={"case_seeds": "the case creates it"}))),
                       ("no kind", key_of(dict(CASE_GAP, kind=""))),
                       ("a level whose command the config does not hold", key_of(dict(LEVEL_GAP, contour="ghost"))),
                       ("no scope", key_of({"kind": "feature_flag", "check": CHECK})),
                       ("a gap that is not an object", ER.property_key(None, cfg(), "QA"))):
        check_eq(f"E5: {label} gives no key", got, None)


def part_integration_key() -> None:
    """GW1-16 (G-6 a), K16.13: a case's `{"integration": <name>}` is a check a machine made, keyed by the NAME - a word about a
    service holds on this stand while its keys change, and another name is another key."""
    jira = dict(CASE_GAP, kind="service", check={"integration": "jira-integration"})
    key = key_of(jira)
    check_eq("K16.13: an integration check has a key, of the same five fields as any case", sorted(key or {}),
             ["check_digest", "definition_sha", "environment", "precondition_kind", "scope"])
    check("K16.13: another name is another key", key_of(dict(jira, check={"integration": "stripe-keys"})) != key)
    check_eq("K16.13: the same name is the same key", key_of(dict(jira)), key)
    check_eq("K16.13: a stand the config does not have gives none", key_of(jira, stand="nowhere"), None)
    check_in("K16.13: the list of keyed checks holds it", "integration", ER.KEYED_CHECKS)


def part_m13_the_two_classes() -> None:
    """M13 / D-0032: the boundary of file-or-machine faults and configuration causes."""
    def why(**over):
        return ER.lasting(dict(LEVEL_GAP, **over), cfg(), "QA")["why"]
    check_eq("M13: a report that was not written (exit 4) is a FAULT: no key, `fault`", ER.lasting(dict(LEVEL_GAP, reason_class="no_file", exit_code=4), cfg(), "QA"),
             {"key": None, "why": "fault"})
    check_eq("M13: a report that was not written after a NORMAL exit is a fault too (nothing was written)", why(reason_class="no_file", exit_code=0), "fault")
    check_eq("M13: a report that cannot be parsed is a fault", why(reason_class="unparsable"), "fault")
    check_eq("M13: `zero_tests` with an error exit (a runner that failed, a missing dependency) is a fault", why(exit_code=1), "fault")
    check_eq("M13: `zero_tests` with an exit nobody recorded is a fault (the unknown is a fault)", why(exit_code=None), "fault")
    check_eq("M13: `zero_tests` after a bool is not an exit", why(exit_code=False), "fault")
    check_eq("M13 AT the boundary: `zero_tests` after a NORMAL exit is a configuration - keyed, no `why`",
             (why(exit_code=0), ER.property_key(LEVEL_GAP, cfg(), "QA") is not None), ("", True))
    check_eq("an unknown class has no key and is not called a fault", why(reason_class="mystery"), "no_key")
    check_in("the card's line names the fault and the door `accept`", "write `accept`", ER.fault_line("no_file"))
    check_in("and says it is a fault of the machine, not a property of the environment", "not a property of the environment", ER.fault_line("no_file"))


def part_covering() -> None:
    key = case_key()
    live = row(key)
    check_eq("a live row of the key covers it", ER.covering([live], key), live)
    check_eq("E14: a revoked row covers nothing", ER.covering([dict(live, revoked_at="2026-10-06T00:00:00+00:00")], key), None)
    check_eq("E14: a row with no subject covers nothing", ER.covering([{k: v for k, v in live.items() if k != "subject"}], key), None)
    check_eq("E14: a row with no option covers nothing", ER.covering([{k: v for k, v in live.items() if k != "option"}], key), None)
    check_eq("E14: an option other than `accept` covers nothing", ER.covering([dict(live, option="handed")], key), None)
    check_eq("E14: another definition sha covers nothing", ER.covering([live], dict(key, definition_sha="0" * 64)), None)
    check_eq("E14: a key with an empty field covers nothing", ER.covering([live], dict(key, environment="")), None)
    check_eq("E14: a key of another scope covers nothing", ER.covering([live], level_key()), None)
    check_eq("E14: a key with an extra field covers nothing", ER.covering([live], dict(key, extra="x")), None)
    check_eq("E14: no key, no cover", ER.covering([live], None), None)
    check_eq("E14: a non-dict row is passed over", ER.covering(["x", None, live], key), live)
    check_eq("E14: another reason class covers nothing (the level)",
             ER.covering([row(level_key())], dict(level_key(), reason_class="no_file")), None)
    older, newer = row(key, "2026-10-01T00:00:00+00:00", "EP-1"), row(key, "2026-10-02T00:00:00+00:00", "EP-2")
    check_eq("E10: two live rows of one key: the latest `at` wins", ER.covering([newer, older], key)["id"], "EP-2")
    check_eq("E10: on a tie the later row", ER.covering([row(key, id="EP-1"), row(key, id="EP-2")], key)["id"], "EP-2")
    check_eq("E10: an unreadable `at` is the oldest there is (a row with a real moment beats it)",
             ER.covering([row(key, "", "EP-1"), row(key, "x", "EP-2"), older], key)["id"], "EP-1")
    # the near miss: the same thing under another command / failure / address, so the card can say what changed
    near, why = ER.near_miss([row(level_key())], dict(level_key(), argv_digest="f" * 64))
    check_eq("near miss: the command changed", (near is not None, why), (True, "command"))
    near, why = ER.near_miss([row(level_key())], dict(level_key(), reason_class="no_file"))
    check_eq("near miss: another failure of the same command", (near is not None, why), (True, "reason"))
    near, why = ER.near_miss([row(key)], dict(key, definition_sha="0" * 64))
    check_eq("near miss: the stand's address changed", (near is not None, why), (True, "address"))
    check_eq("near miss: nothing near a key of another contour", ER.near_miss([row(level_key())], dict(level_key(), contour="api"))[1], "")
    check_eq("near miss: a revoked row is not near", ER.near_miss([row(key, revoked_at="x")], dict(key, definition_sha="0" * 64))[1], "")
    # current_key: what the SAME subject is NOW (C4 of stand_gaps.carried_change)
    check_eq("current_key of a level follows the command in the config", ER.current_key(level_key(), cfg(argv=ARGV + ["--x"]), "QA")["argv_digest"]
             != level_key()["argv_digest"], True)
    check_eq("current_key of a level whose command is gone is None", ER.current_key(level_key(), {"profiles": []}, "QA"), None)
    check_eq("current_key of a case follows the stand's definition", ER.current_key(case_key(), cfg(url="http://other.invalid"), "QA")["definition_sha"]
             != case_key()["definition_sha"], True)
    check_eq("current_key of a case whose stand is another name is built for THAT stand (so it covers nothing)",
             ER.current_key(case_key(), cfg(), "QA2"), None)


def part_file() -> None:
    root = temp_dir("qa-envrec-")
    try:
        check_eq("E1: no file is `([], '')`: the normal state before the first `accept always`", ER.load(root), ([], ""))
        check("E1: and loading wrote nothing", not ER.record_path(root).exists())
        key = case_key()
        got, problem, created = ER.record(root, key, "accept", "PC-1: accept always", "T-1", '"x"')
        check_eq("the first record creates the file and the row EP-1", (got["id"], problem, created), ("EP-1", "", True))
        check_eq("with the person's words whole", got["words"], "PC-1: accept always")
        again, problem, created = ER.record(root, key, "accept", "other words", "T-2")
        check_eq("a key already covered returns the live row and writes no second one (the earlier word stands)",
                 (again["id"], again["words"], created), ("EP-1", "PC-1: accept always", False))
        second, _p, _c = ER.record(root, level_key(), "accept", "web: accept always", "T-1")
        check_eq("ids count up and are never reused", second["id"], "EP-2")
        fresh = dict(level_key(), contour="api")          # a key no row holds, so a refusal is the input's and not a cover
        for label, args in (("an option other than `accept`", (fresh, "handed", "w", "T")),
                            ("an incomplete key", ({"scope": "case"}, "accept", "w", "T")),
                            ("no key", (None, "accept", "w", "T")), ("empty words", (fresh, "accept", "  ", "T"))):
            check_eq(f"record refuses {label}", ER.record(root, *args)[0], None)
        rows, problem = ER.load(root)
        check_eq("two rows on disk", ([r["id"] for r in rows], problem), (["EP-1", "EP-2"], ""))
        done, problem = ER.revoke(root, "EP-1", "ask again")
        check_eq("revoke marks the row, the words and the moment stay", (done["id"], bool(done["revoked_at"]), done["revoked_words"], problem), ("EP-1", True, "ask again", ""))
        check_eq("a revoked row covers nothing at once", ER.covering(ER.load(root)[0], key), None)
        check_in("E8: an unknown id is refused with `show` as the door", "`environment_record.py show`", ER.revoke(root, "EP-9", "w")[1])
        check_in("E8: an id already taken back says so", "already taken back", ER.revoke(root, "EP-1", "w")[1])
        check_eq("revoke refuses empty words", ER.revoke(root, "EP-2", " ")[0], None)
        # E9: an unreadable record is never written over
        path = ER.record_path(root)
        for label, text in (("not JSON", "{broken"), ("not an object", "[1]"), ("another schema version", '{"schema_version": 2, "properties": []}'),
                            ("no properties list", '{"schema_version": 1}')):
            path.write_text(text, encoding="utf-8")
            rows, problem = ER.load(root)
            check_eq(f"E9: {label}: no rows and a problem, no raise", (rows, bool(problem)), ([], True))
            got = ER.record(root, key, "accept", "words", "T")
            check_eq(f"E9: {label}: record refuses and writes nothing over it", (got[0], path.read_text(encoding="utf-8")), (None, text))
            check_eq(f"E9: {label}: revoke refuses and writes nothing over it", (ER.revoke(root, "EP-1", "w")[0], path.read_text(encoding="utf-8")), (None, text))
    finally:
        cleanup(root)


def part_covered_block_limits() -> None:
    """E11: the person's words in the covered block - 160 whole, 161 cut at a word with an ellipsis."""
    key = level_key()
    gap = {"id": "RP-web", "scope": "level", "contour": "web", "cases": ["TC-1"], "case_id": ""}

    def line(words: str) -> str:
        block = gate_brief._covered_block([dict(gap, property=row(key, words=words, about="the web tests"))], {"RP-web": "web"})
        return next(x for x in block if x.startswith("- web:"))
    whole = "w" * 160
    check_in("E11: 160 characters are shown whole", f'"{whole}"', line(whole))
    words = "word " * 40
    cut = line(words.strip())
    check_in("E11: 161 or more are cut at a word and marked", "…\"", cut)
    check_not_in("E11: the cut is not inside a word", "wor…", cut)
    block = "\n".join(gate_brief._covered_block([dict(gap, property=row(key, about="the web tests"))], {"RP-web": "web"}))
    check_in("the block says what cannot be checked here, with the date", "on this environment the web tests cannot be checked — you wrote on 2026-10-05", block)
    check_in("and offers the line that takes it back", "write `<name>: ask again` on a line of its own", block)
    check_not_in("and never the word profile or RP-", "profile", block)


def part_cli() -> None:
    root = temp_dir("qa-envrec-cli-")
    try:
        task_root = root / "qa-factory" / "artifacts" / "T-1"
        (task_root / "work" / "test-cases").mkdir(parents=True)
        (task_root / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "environment": "QA"}), encoding="utf-8")
        pre = [{"id": "PC-1", "kind": "feature_flag", "what": "sub-workflow states are enabled", "partitions": [], "check": CHECK,
                "remedy": {"kind": "flag", "where": "app/config.yaml:3", "change": "enabled: true"}}]
        (task_root / "work" / "test-cases" / "TC-007.md").write_text(
            "---\nid: TC-007\npreconditions: " + json.dumps(pre) + "\n---\n\n## When\n1. x\n", encoding="utf-8")
        config = cfg()
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        words = task_root / "state" / "words"
        words.mkdir(parents=True)
        (words / "w.txt").write_text("PC-1: accept always, the mocks stand in", encoding="utf-8")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))

        def run(*args):
            return run_script("environment_record.py", *args, cwd=root, env=env)
        done = run("show")
        check_eq("show of a project with no record: exit 0 and says so", (done.returncode, "no environment property" in done.stdout), (0, True))
        done = run("record", "--task", "T-1", "--case", "TC-007", "--gap", "PC-1", "--option", "accept", "--words-file", str(words / "w.txt"))
        check_eq("record --case: exit 0 and EP-1, in the record's own sentence", (done.returncode, "EP-1: on this environment" in done.stdout, "cannot be checked" in done.stdout),
                 (0, True, True))
        saved = json.loads(ER.record_path(root).read_text(encoding="utf-8"))["properties"][0]
        check_eq("the key was computed with NO probe, from the case's own precondition and the config",
                 saved["subject"], ER.property_key(dict(CASE_GAP), config, "QA"))
        check_eq("with the person's words verbatim and the story", (saved["words"], saved["story"]), ("PC-1: accept always, the mocks stand in", "T-1"))
        done = run("record", "--task", "T-1", "--case", "TC-007", "--gap", "PC-1", "--option", "accept", "--words-file", str(words / "w.txt"))
        check_in("the same record again says the earlier words stand", "already recorded", done.stdout)
        done = run("record", "--task", "T-1", "--case", "TC-007", "--gap", "PC-9", "--option", "accept", "--words-file", str(words / "w.txt"))
        check_eq("an unknown gap is refused with its reason on stderr, exit 2", (done.returncode, "declares no precondition PC-9" in done.stderr), (2, True))
        done = run("record", "--task", "T-1", "--contour", "web", "--reason", "no_file", "--option", "accept", "--words-file", str(words / "w.txt"))
        check_eq("M13: record --contour with a `no_file` reason is refused with the fault line and the door `accept`",
                 (done.returncode, "not a property of the environment" in done.stderr, "write `accept`" in done.stderr), (2, True, True))
        done = run("record", "--task", "T-1", "--contour", "web", "--reason", "zero_tests", "--exit-code", "4", "--option", "accept", "--words-file", str(words / "w.txt"))
        check_eq("M13: and a `zero_tests` after an error exit is refused the same way", (done.returncode, "not a property of the environment" in done.stderr), (2, True))
        done = run("record", "--task", "T-1", "--contour", "web", "--reason", "zero_tests", "--option", "accept", "--words-file", str(words / "w.txt"))
        check_eq("M13/FR-59: `zero_tests` with NO --exit-code is an unknown exit, a fault: refused with the fault line",
                 (done.returncode, "not a property of the environment" in done.stderr), (2, True))
        done = run("record", "--task", "T-1", "--contour", "web", "--reason", "zero_tests", "--exit-code", "0", "--option", "accept", "--words-file", str(words / "w.txt"))
        check_eq("M13: `zero_tests` after a normal exit (--exit-code 0) is a configuration: recorded as EP-2", (done.returncode, done.stdout.startswith("EP-2")), (0, True))
        done = run("record", "--task", "T-1", "--contour", "web", "--reason", "zero_tests", "--option", "accept")
        check_eq("no words file: refused with the door (person_words), exit 2, nothing written",
                 (done.returncode, "--words-file" in done.stderr), (2, True))
        done = run("record", "--task", "T-1", "--contour", "web", "--reason", "zero_tests", "--option", "accept", "--words-file", str(words / "nope.txt"))
        check_eq("a words file that does not exist is refused by person_words", (done.returncode, "no such file" in done.stderr), (2, True))
        (words / "empty.txt").write_text("  \n", encoding="utf-8")
        done = run("revoke", "--id", "EP-1", "--words-file", str(words / "empty.txt"))
        check_eq("revoke with an empty words file is refused", done.returncode, 2)
        done = run("revoke", "--id", "EP-9", "--words-file", str(words / "w.txt"))
        check_eq("E8: revoke of an unknown id: exit 2, `show` is the door", (done.returncode, "show" in done.stderr), (2, True))
        done = run("revoke", "--id", "EP-1", "--words-file", str(words / "w.txt"))
        check_eq("revoke: exit 0", done.returncode, 0)
        shown = json.loads(run("show", "--json").stdout)
        check_eq("show --json: both rows, the first taken back", [(r["id"], bool(r.get("revoked_at"))) for r in shown["properties"]], [("EP-1", True), ("EP-2", False)])
        check_in("show says which is live", "EP-2 (live)", run("show").stdout)
        ER.record_path(root).write_text("{broken", encoding="utf-8")
        done = run("show")
        check_eq("show of an unreadable record says so and exits 1", (done.returncode, "cannot be read" in done.stdout), (1, True))
        done = run("revoke", "--id", "EP-2", "--words-file", str(words / "w.txt"))
        check_eq("E9: revoke over an unreadable record is refused and the file is untouched", (done.returncode, ER.record_path(root).read_text(encoding="utf-8")), (2, "{broken"))
    finally:
        cleanup(root)


def part_shared_helpers() -> None:
    """T7 (C2-9): the file helpers take the path as a parameter (a second record, `work/gap-classes.json`, uses them) and the
    environment record's wrappers keep their old output."""
    ids = [{"id": "GC-1"}, {"id": "GC-7"}, {"id": "EP-9"}, {"id": "GC-x"}, {"id": None}]
    check_eq("T7 next_id counts the ids of ITS prefix only", (ER.next_id(ids, "GC-"), ER.next_id(ids, "EP-"), ER.next_id([], "GC-")),
             ("GC-8", "EP-10", "GC-1"))
    root = temp_dir("qa-envrec-helpers-")
    try:
        path = Path(root) / "work" / "gap-classes.json"
        check_eq("T7 an absent file is no rows and no problem", ER.load_rows(path, "classes", 1), ([], ""))
        check_eq("T7 write_rows writes", ER.write_rows(path, "classes", 1, [{"id": "GC-1", "words": "go on"}]), "")
        check_eq("T7 load_rows reads it back", ER.load_rows(path, "classes", 1)[0], [{"id": "GC-1", "words": "go on"}])
        check_in("T7 another list key is a problem named by the file", "no `properties` list", ER.load_rows(path, "properties", 1)[1])
        check_in("T7 another schema is a problem", "schema_version", ER.load_rows(path, "classes", 2)[1])
        row, problem = ER.revoke_row(path, "classes", 1, "GC-1", "changed my mind", "`x.py show`", now="2026-01-01T00:00:00+00:00", noun="class")
        check_eq("T7 revoke_row keeps the row and stamps it", (row["revoked_at"], row["revoked_words"], problem),
                 ("2026-01-01T00:00:00+00:00", "changed my mind", ""))
        check_in("T7 a second revoke names the door", "`x.py show` lists the live ones", ER.revoke_row(path, "classes", 1, "GC-1", "again", "`x.py show`")[1])
        check_in("T7 an unknown id names the noun and the door", "there is no class GC-9", ER.revoke_row(path, "classes", 1, "GC-9", "w", "`x.py show`", noun="class")[1])
        path.write_text("{broken", encoding="utf-8")
        check_in("T7 revoke over an unreadable file writes nothing", "nothing was written over it", ER.revoke_row(path, "classes", 1, "GC-1", "w", "`x.py show`")[1])
        check_eq("T7 the file is untouched", path.read_text(encoding="utf-8"), "{broken")
        check_in("T7 the environment record's own wrapper keeps its text", "there is no property EP-3 in " + ER.RECORD_REL,
                 ER.revoke(root, "EP-3", "w")[1])
    finally:
        cleanup(root)


def main() -> None:
    use_project(temp_dir("qa-envrec-proj-"))
    part_shared_helpers()
    part_keys()
    part_integration_key()
    part_m13_the_two_classes()
    part_covering()
    part_file()
    part_covered_block_limits()
    part_cli()
    finish("test_environment_record")


if __name__ == "__main__":
    main()
