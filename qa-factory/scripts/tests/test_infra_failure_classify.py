#!/usr/bin/env python3
"""classify: a part of test_infra_failure.py, split by tools/test_split.py (TD-11c). The shared helpers are in infra_failure_common."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402
sys.path.insert(0, str(harness.SCRIPTS))
import story_run_common as T  # noqa: E402
from infra_failure_common import (  # noqa: E402
    AUTH, LIMIT, LIMIT_NO_RESET, MALFORMED, S3_SAVED, TASK, calls, control, done, entry, infra_of, install,
    project_of, prompt_for, raised, scenario,
)


# --- K1 -----------------------------------------------------------------------------------------
def k1_classify():
    import hooklib
    import infra_failure as I
    rules, notes = I.rules()
    check_eq("K1: the shipped data file is read without a note", notes, [])
    check("K1: and carries the wire rows", {"not_logged_in", "usage_limit", "malformed_response"}
          <= {r["id"] for r in rules.get("failures", [])})
    call = {"is_error": True, "exit_code": 1, "stderr": ""}
    got = I.classify(dict(call, result=AUTH), rules)
    check_eq("K1: `Not logged in` is auth", (got["kind"], got["rule"]), ("auth", "not_logged_in"))
    got = I.classify(dict(call, result=LIMIT), rules)
    check_eq("K1: a usage limit is limit, with the reset as the service wrote it",
             (got["kind"], got["reset"]), ("limit", "2am (Europe/Madrid)"))
    check_eq("K1: a limit that names no reset has an empty one", I.classify(dict(call, result=LIMIT_NO_RESET), rules)["reset"], "")
    got = I.classify(dict(call, result=MALFORMED), rules)
    check_eq("K1: the Cloudflare page is transient and carries its retry word",
             (got["kind"], got["retry_code"]), ("transient", "service_unavailable"))
    check_eq("K1: the saved 13877 S3 file classifies the same", I.classify(S3_SAVED, rules)["kind"], "transient")
    fixture = harness.PLUGIN_ROOT.parents[1] / "experiments/TP1-13877/state/driver-runs/S3-qa-test-strategist-1.json"
    if fixture.is_file():  # only where the repository that made this test is around
        check_eq("K1: and the embedded text IS the fixture's", json.loads(fixture.read_text(encoding="utf-8")),
                 {k: S3_SAVED[k] for k in ("session_id", "result", "num_turns", "total_cost_usd", "duration_ms", "is_error", "exit_code", "stderr")})
    check_eq("K1: the words of a call that did not fail are never read (FR-12)",
             I.classify({"is_error": False, "exit_code": 0, "result": AUTH}, rules), None)
    check_eq("K1: a non-zero exit with is_error false is a failed call and is read",
             I.classify({"is_error": False, "exit_code": 1, "result": AUTH}, rules)["kind"], "auth")
    check_eq("K1: is_error with exit 0 is read as well",
             I.classify({"is_error": True, "exit_code": 0, "result": AUTH}, rules)["kind"], "auth")
    check_eq("K1: max turns is the role's own outcome, whatever the text says",
             I.classify(dict(call, result=AUTH, subtype="error_max_turns"), rules), None)
    check_eq("K1: an unmatched failure is unclassified", I.classify(dict(call, result="boom"), rules),
             {"kind": "unclassified", "rule": ""})
    check_eq("K1: an empty result is read from stderr",
             I.classify(dict(call, result="", stderr=AUTH), rules)["kind"], "auth")
    check_eq("K1: empty everywhere, still a failure: unclassified",
             I.classify(dict(call, result=""), rules)["kind"], "unclassified")

    real = hooklib.load_ref_json
    hooklib.load_ref_json = lambda name: {} if name == "driver-infra.json" else real(name)
    try:
        gone, notes = I.rules()
        check_eq("K1: with the data file absent the rules are empty", gone, {})
        check_in("K1: and one note says so", "references/driver-infra.json unreadable", notes)
        check_eq("K1: every failure is then unclassified", I.classify(dict(call, result=AUTH), gone)["kind"], "unclassified")
    finally:
        hooklib.load_ref_json = real
    bad = {"failures": [{"id": "broken", "kind": "auth", "pattern": "(unclosed"},
                        {"id": "fine", "kind": "auth", "pattern": "Not logged in"},
                        {"id": "odd", "kind": "sulk", "pattern": "x"}]}
    hooklib.load_ref_json = lambda name: bad if name == "driver-infra.json" else real(name)
    try:
        partial, notes = I.rules()
        check_eq("K1: a row whose regex does not compile is skipped, a row of an unknown kind too",
                 [r["id"] for r in partial["failures"]], ["fine"])
        check_eq("K1: each skip is named", sum("skipped" in n for n in notes), 2)
        check_eq("K1: and the other rows still match", I.classify(dict(call, result=AUTH), partial)["rule"], "fine")
    finally:
        hooklib.load_ref_json = real


def k11_unclassified_is_todays_path():
    root, task_root, env, driver, delays = project_of(control([entry("boom: something nobody has met", turns=4, session="sess-u")]))
    try:
        stop, result = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        check_eq("K11: no stop", stop, None)
        check_eq("K11: the caller gets the failure as before, and the classification with it",
                 (result["is_error"], result["result"], result["infra"]["kind"]), (True, "boom: something nobody has met", "unclassified"))
        check_eq("K11: the session is stored as before", driver.state["sessions"]["S1-qa-scout-1"], "sess-u")
        row = T.jsonl(task_root / "state/driver-runs.jsonl")[0]
        check_eq("K11: the journal says unclassified", (row["infra"], row["infra_rule"], row["retry"]), ("unclassified", "", 0))
        check_eq("K11: nothing was retried", (delays, len(calls(root))), ([], 1))
    finally:
        done(root)
    root, task_root, env = T.seed(TASK)
    try:
        install(root, control([entry("boom: something nobody has met", turns=4, session="sess-u")],
                              conductor={"action": "ask_person", "question": "Which stand should I use?", "did": "read"}))
        # t-261 (K11, critic t-244): two boundaries, not one. The first boundary's refusal is answered by the role's own
        # resume (t-217 §1: once per finding set); the SECOND is the person's - and the road is the person's own (the seam's since C1-5d2, below), not the
        # conductor's: the conductor stub above (`ask_person`) is never called. (The old pin of one boundary proved the
        # conductor road; since t-217 a second identical refusal is a fact the factory already knows - fork 3.)
        # t-828 (re-pinned to conductor/1 C1-5d2, t-698 sec. 12.2.1/12.2.2, sec. 13 F-d1): the refusal that survives the resume
        # limit is asked by the ONE seam `exit_limit` - the site's own question (kind `exit_limit`, key `exit.resume_limit`,
        # stage and dispatch as its fields), `call=False`: still no conductor call.
        out = T.run_driver(root, env, "--task", TASK, "--max-boundaries", "2")
        check_eq("K11: an unclassified failure still reaches the person (exit 3)", out.returncode, 3)
        asked = json.loads((task_root / "state/driver-state.json").read_text(encoding="utf-8")).get("asked") or {}
        check_eq("K11: and the question is of kind `exit_limit` (the seam's road after the t-217 resume, not the conductor's)",
                 asked.get("kind"), "exit_limit")
        check_eq("K11: about the stage and the dispatch of the refused role (the seam's fields)",
                 (asked.get("stage"), asked.get("dispatch")), ("S1", "S1-qa-scout-1"))
        check_eq("K11: the conductor stub was not called at all (its calls are in the stub's own log)", T.d2_conductor_calls(root), [])
    finally:
        done(root)


def k11_what_is_not_a_failure_is_never_read():
    root, task_root, env, driver, delays = project_of(control())
    try:
        ok_words = {"json": {"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-ok", "num_turns": 3,
                             "total_cost_usd": 0.1, "duration_ms": 5, "result": "The role quoted: " + AUTH}, "exit": 0}
        install(root, control([ok_words, {"json": {"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-e",
                                                   "num_turns": 1, "total_cost_usd": 0, "duration_ms": 5, "result": ""}, "exit": 0}]))
        stop, result = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        check_eq("K11: a successful call that quotes a login error is the role's result", (stop, result["result"].startswith("The role quoted")), (None, True))
        check_eq("K11: and the journal says null", T.jsonl(task_root / "state/driver-runs.jsonl")[-1]["infra"], None)
        stop, result = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        check_eq("K11: an empty successful result keeps today's path (F-9)", (stop, result["result"], result["is_error"]), (None, "", False))
        check_eq("K11: nothing was slept", delays, [])
    finally:
        done(root)


def k11_unparsable_and_stderr_only_output():
    root, task_root, env, driver, delays = project_of(control([{"raw": AUTH, "exit": 1}, {"json": {"type": "result", "is_error": True, "session_id": "s", "num_turns": 1, "result": ""}, "exit": 1, "stderr": AUTH}]))
    try:
        stop, _ = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
        check_eq("K11: text that is not JSON takes the fallback dict and is classified", infra_of(stop), "auth")
        stop, _ = raised(driver, "role", prompt_for(task_root), role="qa-scout", dispatch="S1-qa-scout-2", stage="S1")
        check_eq("K11: an empty result with the login error on stderr is auth too", infra_of(stop), "auth")
    finally:
        done(root)


# --- K12, K13 -------------------------------------------------------------------------------------
def k12_the_claude_child_environment():
    host = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:4001", "ANTHROPIC_AUTH_TOKEN": "tok", "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST": "1",
            "CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_HOST_AUTH_ENV_VAR": "MY_TOK", "MY_TOK": "secret",
            "ANTHROPIC_API_KEY": "key-1", "PYTHONIOENCODING": "cp1252", "FOO": "foo"}
    root, task_root, env = T.seed(TASK)
    try:
        install(root, control())
        for key in ("PYTHONUTF8",):
            env.pop(key, None)
        out = T.run_driver(root, env | host, "--task", TASK, "--max-boundaries", "1")
        T.eq("K12: the story runs", out.returncode, 0, out.stdout[-1000:] + out.stderr[-500:])
        seen = calls(root)[0]["env"]
        for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST", "CLAUDE_CODE_USE_BEDROCK",
                     "CLAUDE_CODE_HOST_AUTH_ENV_VAR", "MY_TOK"):
            check_eq(f"K12: the claude child does not see {name}", seen[name], None)
        check_eq("K12: an API key stays", seen["ANTHROPIC_API_KEY"], "key-1")
        check_eq("K12: UTF-8 mode", seen["PYTHONUTF8"], "1")
        check_eq("K12: and the encoding is the driver's, not the host's", seen["PYTHONIOENCODING"], "utf-8")
        check_eq("K12: an unrelated variable stays", seen["FOO"], "foo")
    finally:
        done(root)

    # the project's doors: keep passes a host variable through, remove adds a name
    root, task_root, env = T.seed(TASK)
    try:
        install(root, control())
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["driver"] = {"child_env": {"keep": ["ANTHROPIC_BASE_URL"], "remove": ["FOO", "ANTHROPIC_BASE_URL"]}}
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        out = T.run_driver(root, env | host, "--task", TASK, "--max-boundaries", "1")
        T.eq("K12: the story runs with a keep and a remove", out.returncode, 0, out.stdout[-1000:])
        seen = calls(root)[0]["env"]
        check_eq("K12: keep [ANTHROPIC_BASE_URL] is present in the child", seen["ANTHROPIC_BASE_URL"], "http://127.0.0.1:4001")
        check_eq("K12: remove [FOO] is gone", seen["FOO"], None)
        check_in("K12: a name in both keep and remove is kept, with a note", "`ANTHROPIC_BASE_URL` is in both keep and remove", out.stdout)
        check_eq("K12: the token is still removed: only the kept name is passed", seen["ANTHROPIC_AUTH_TOKEN"], None)
    finally:
        done(root)

    # the driver's own object: py() children keep the host's proxy and get UTF-8
    root, task_root, env, driver, delays = project_of(control())
    try:
        driver.env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:4001"
        check_eq("K12: a py() child keeps the host's BASE_URL (factory scripts may use a gateway on purpose)",
                 driver.env.get("ANTHROPIC_BASE_URL"), "http://127.0.0.1:4001")
        check_eq("K12: and has UTF-8", (driver.env.get("PYTHONUTF8"), driver.env.get("PYTHONIOENCODING")), ("1", "utf-8"))
        check_eq("K12: the object names what it removed from the claude child", isinstance(driver.env_removed, list), True)
    finally:
        done(root)


def k12_child_env_function():
    import infra_failure as I
    rules, _ = I.rules()
    base = {"ANTHROPIC_BASE_URL": "u", "CLAUDE_CODE_USE_VERTEX": "1", "CLAUDE_CODE_MESSAGING_TOKEN": "m", "CLAUDE_CODE_HOST_AUTH_ENV_VAR": "MY_TOK",
            "MY_TOK": "s", "ANTHROPIC_API_KEY": "k", "PATH": "p", "FOO": "f"}
    env, removed, notes = I.child_env(base, rules, {})
    check_eq("K12: the data list, the prefixes and the named variable go", sorted(removed),
             ["ANTHROPIC_BASE_URL", "CLAUDE_CODE_HOST_AUTH_ENV_VAR", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_USE_VERTEX", "MY_TOK"])
    check_eq("K12: what stays", sorted(env), ["ANTHROPIC_API_KEY", "FOO", "PATH"])
    check_eq("K12: removed_present lists only names that were there", "ANTHROPIC_AUTH_TOKEN" in removed, False)
    env, removed, notes = I.child_env(base, rules, {"child_env": {"keep": ["ANTHROPIC_BASE_URL", "MY_TOK"], "remove": ["FOO"]}})
    check_eq("K12: keep beats the data list, remove adds", ("ANTHROPIC_BASE_URL" in env, "MY_TOK" in env, "FOO" in env), (True, True, False))
    env, removed, notes = I.child_env(base, rules, {"child_env": {"keep": ["FOO"], "remove": ["FOO"]}})
    check_eq("K12: a name in keep and in the config's remove is kept", "FOO" in env, True)
    check_in("K12: and says so", "`FOO` is in both keep and remove; it is kept", notes)
    env, removed, notes = I.child_env(base, rules, {"child_env": {"keep": "ANTHROPIC_BASE_URL", "remove": [1, 2]}})
    check_eq("K12: a keep or remove that is not a list of names is ignored", ("ANTHROPIC_BASE_URL" in env, "FOO" in env), (False, True))
    check_eq("K12: with one note each", sum("ignored" in n for n in notes), 2)
    env, removed, notes = I.child_env(base, {}, {})
    check_eq("K12: with no rules nothing is removed", (env, removed, notes), (base, [], []))
    check_eq("K12: the base dict is not touched", "ANTHROPIC_BASE_URL" in base, True)


def k13_a_child_prints_in_utf8():
    root, task_root, env, driver, delays = project_of(control())
    try:
        script = root / "dash.py"
        script.write_text("import sys\nprint(chr(0x2014) + chr(0x2026))\n", encoding="utf-8")
        code, out = driver.py(str(script))
        check_eq("K13: a child that prints an em dash and an ellipsis is decoded as such", (code, out), (0, chr(0x2014) + chr(0x2026)))
    finally:
        done(root)


def f4_rows_carry_their_hosts():
    """CX1-15 F-4: a `codex_*` row is tried only for a call of its host. A role's text on Claude that says `401 unauthorized` (an
    API test's output) in a FAILED call is not a Codex login failure; the same text on a Codex call is; a caller naming no host
    tries the rows without `hosts` only (the rows there were before the key existed)."""
    import infra_failure as IF
    rules, notes = IF.rules()
    check_eq("F-4: the packaged data loads clean", notes, [])
    codex_rows = {r["id"]: r.get("hosts") for r in rules["failures"] if r["id"].startswith("codex_")}
    check_eq("F-4: the three codex rows are in the data, each for the codex host only", codex_rows,
             {"codex_not_logged_in": ["codex"], "codex_usage_limit": ["codex"], "codex_stream_broken": ["codex"]})
    text = {"is_error": True, "exit_code": 1, "result": "the API test got 401 unauthorized from the stand", "stderr": ""}
    check_eq("F-4: on Claude that text is unclassified", IF.classify(text, rules, "claude"), {"kind": "unclassified", "rule": ""})
    check_eq("F-4: with no host named it is unclassified too (the rows before `hosts`)", IF.classify(text, rules), {"kind": "unclassified", "rule": ""})
    check_eq("F-4: on Codex it is the login failure", (IF.classify(text, rules, "codex") or {}).get("rule"), "codex_not_logged_in")
    check_eq("F-4: a row without `hosts` still reads every host (the Claude login row on Codex)",
             (IF.classify(dict(text, result="Not logged in"), rules, "codex") or {}).get("rule"), "not_logged_in")
    import hooklib
    saved = hooklib.load_ref_json
    try:
        hooklib.load_ref_json = lambda name: {"failures": [dict(rules["failures"][0], id="x", hosts="codex"),
                                                           {"id": "ok", "kind": "auth", "pattern": "z"}]}
        good, bad_notes = IF.rules()
    finally:
        hooklib.load_ref_json = saved
    check_eq("F-4: a `hosts` that is no list is skipped with a note, the other rows still match",
             ([r["id"] for r in good["failures"]], any("`hosts` must be a non-empty list" in n for n in bad_notes)), (["ok"], True))


SCENARIOS = (
    f4_rows_carry_their_hosts,
    k1_classify,
    k11_unclassified_is_todays_path,
    k11_what_is_not_a_failure_is_never_read,
    k11_unparsable_and_stderr_only_output,
    k12_the_claude_child_environment,
    k12_child_env_function,
    k13_a_child_prints_in_utf8,
)


# split: runner piece 1
# `test_infra_failure.py k2_auth_stops_the_driver k5_transient_three_times` runs only those (a mutation
# control names the one scenario it targets); with no names, all of them run - the witness is that run.
for _fn in SCENARIOS:
    if not sys.argv[1:] or _fn.__name__ in sys.argv[1:]:
        scenario(_fn)


finish("test_infra_failure_classify")
