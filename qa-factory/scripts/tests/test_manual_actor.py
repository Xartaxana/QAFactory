#!/usr/bin/env python3
"""t-1526 HF5-3: the actor of a manual case - `--as`, the case's own account, an account a person put in the env file,
a user the story creates, the report line about created users.

Browser and HTTP are FAKES (scaffold); everything the factory owns is real: `prepare_request` (the producer of
`actors`), `request_actors`, `resolve_actor`, `read_login`, the template check, the redaction, the stores.
The "was" is the 12586 run (fixtures/run-12586-actors/): the preconditions of TC-014 (an actor named by ONE key) and
TC-012 (a `none` actor), the stand's `credentials_by_role`, and the request.json 0.10.4 wrote (no `actors`).
Mutation -> killing key (this file): an auto-actor for an `env` check with one name -> K1; substitution before the template
check or into the stored bytes -> K4; the password in `artifacts/<T>/state` -> K4; the first two keys of three -> K7;
`stand_login_problem` without the actors -> K8.
Fix round t-1550: the create answer recorded only after the limit check / the secret scan -> K12; the refusal of a hidden answer
without `created:<name>` -> K12; the report line reading another path than the store writes -> K10.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402
import test_manual_capture as TMC  # noqa: E402

MC = S.MC
import manual_evidence as M  # noqa: E402
import report_facts as RF  # noqa: E402
import runtime_paths as RP  # noqa: E402

FIX = HERE / "fixtures" / "run-12586-actors"
API_CASE, LOCAL = S.CASES["api"], TMC.LOCAL
LOGIN, GET = f"{LOCAL}/v1/local-auth/login", f"{LOCAL}/v1/projects"
PRE_014 = (FIX / "TC-014.preconditions.txt").read_text(encoding="utf-8").strip()
PRE_012 = (FIX / "TC-012.preconditions.txt").read_text(encoding="utf-8").strip()
ROLES = json.loads((FIX / "credentials_by_role.json").read_text(encoding="utf-8"))
SECOND_USER, SECOND_PW = "qa-second@example.test", "SENTINEL-SECOND-PW-8d21"
DOORS = ("--as env:USER_KEY/SECRET_KEY", "--as default")


def actor_task(roles="roles", pre=None, **cfg_over):
    cfg = S.config(**cfg_over)
    if roles == "roles":
        roles = ROLES
    if roles is not None:
        cfg["environments"][0] = dict(cfg["environments"][0], credentials_by_role=roles)
    t = S.make_task(manual=("api",), cfg=cfg)
    with (t.project / "harness" / ".env").open("a", encoding="utf-8") as env:
        env.write(f"QA_SECOND_USER_EMAIL={SECOND_USER}\nQA_SECOND_USER_PASSWORD={SECOND_PW}\n")
    if pre is not None:
        set_pre(t, pre)
    return t


def set_pre(t, line):
    for path in (t.task / "state" / "case-versions" / API_CASE).glob("*.md"):
        text = path.read_text(encoding="utf-8")
        path.write_text(re.sub(r"(?m)^preconditions:.*$", lambda _m: line, text), encoding="utf-8")


def prepare(t):
    with t.patched():
        return M.prepare_to_file(t.task, API_CASE, TMC.OBLIGATIONS[API_CASE])


def stand_http(extra=None):
    routes = {("POST", LOGIN): S.ok_json({"access_token": S.TOKEN}), ("GET", GET): S.ok_json({"ok": True})}
    routes.update(extra or {})
    return S.FakeHttp(routes)


def call(t, http, *args, method="GET", url=GET):
    return TMC.http_run(t, http, "--method", method, "--url", url, *args)


def steps_of(t):
    path = t.attempt_dir(API_CASE) / "steps.jsonl"
    return [json.loads(x)["step"] for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []


def refusal(label, code_out_err, *needles, doors=True):
    code, out, err = code_out_err
    check_eq(f"{label}: refused (exit 2)", code, 2)
    for needle in needles:
        check_in(f"{label}: says {needle!r}", needle, err)
    for door in DOORS if doors else ():
        check_in(f"{label}: names the door {door!r}", door, err)
    check_not_in(f"{label}: no password in the words", S.PASSWORD, err + out)
    return err


def k1_env_actor_with_one_name():
    t = actor_task(pre=PRE_014)
    try:
        request = prepare(t)
        check_eq("K1 the producer: `actors` are the kind=account preconditions, verbatim (PC-2/PC-3 are not accounts)",
                 [(a["id"], a["check"]) for a in request["actors"]], [("PC-1", {"env": "QA_SECOND_USER_EMAIL"})])
        check_eq("K1 the one reader gives the same", M.request_actors(t.task, API_CASE), (request["actors"], ""))
        http = stand_http()
        err = refusal("K1 no --as, an actor named by one key", call(t, http), "QA_SECOND_USER_EMAIL",
                      "--as env:QA_SECOND_USER_EMAIL/<password key>", "the user's and the password's key", "--as default",
                      doors=False)
        check_eq("K1 nothing was sent, no attempt was opened", (http.calls, (t.attempt_dir(API_CASE)).exists()), ([], False))
        code, out, err = call(t, http, "--as", "env:QA_SECOND_USER_EMAIL/QA_SECOND_USER_PASSWORD")
        check_eq("K1 --as env:U/S: ran", code, 0)
        body = json.loads(http.calls[0][3].decode("utf-8"))
        check_in("K1 the login body carries the second account", SECOND_USER, json.dumps(body))
        check_in("K1 the step line names the actor by its key, not its value", "login by code as env:QA_SECOND_USER_EMAIL", steps_of(t))
        check_not_in("K1 no value of the second account in any file or output", SECOND_PW, S.tree_text(t.task) + out + err)
        http2 = stand_http()
        code, out, err = call(t, http2, "--as", "default", "--attempt", "a1")
        check_in("K1 --as default (seeding under the admin): the default account signs in", S.USER, http2.calls[0][3].decode())
        check_in("K1 ... and the line says default", "login by code as default", steps_of(t))
    finally:
        S.cleanup(t)


def k2_none_actor_and_the_create_route():
    t = actor_task(pre=PRE_012)
    try:
        prepare(t)
        err = refusal("K2 a `none` actor, the stand lists a role", call(t, stand_http()), '--as "default user"',
                      "env:USER_KEY/SECRET_KEY")
        check_not_in("K2 a candidate exists: the create route is NOT named", "create-user endpoint", err)
    finally:
        S.cleanup(t)
    t = actor_task(roles=None, pre=PRE_012)
    try:
        prepare(t)
        err = refusal("K2 same case, no role at all", call(t, stand_http()), "create-user endpoint", "{generated_username}",
                      "never a global admin")
    finally:
        S.cleanup(t)
    t = actor_task(pre=PRE_014.replace('{"env": "QA_SECOND_USER_EMAIL"}', '{"stand_account": "default user"}'))
    try:
        prepare(t)
        http = stand_http()
        code, out, err = call(t, http)
        check_eq("K2 a case with two actors is not this test; one stand_account actor is signed in automatically", code, 0)
    finally:
        S.cleanup(t)
    two = ('preconditions: [{"id": "PC-1", "kind": "account", "what": "a", "check": {"stand_account": "default user"}}, '
           '{"id": "PC-2", "kind": "account", "what": "b", "check": {"env": "QA_SECOND_USER_EMAIL"}}]')
    t = actor_task(pre=two)
    try:
        prepare(t)
        refusal("K2 two accounts, no --as", call(t, stand_http()), "2 accounts", "PC-1", "PC-2")
    finally:
        S.cleanup(t)


def k3_role_and_auto_actor():
    stand_account = PRE_012.replace('{"none": "only one role (default user) is held by the stand; a person says whether a partial-admin account exists"}',
                                    '{"stand_account": "default user"}')
    check("K3 the fixture line was changed to a stand_account check", '"stand_account": "default user"' in stand_account)
    t = actor_task(pre=stand_account)
    try:
        prepare(t)
        http = stand_http()
        code, out, err = call(t, http)
        check_eq("K3 auto-actor: a stand_account on the stand's role, ran", code, 0)
        check_in("K3 AUTH_USERNAME / AUTH_PASSWORD signed in", S.USER, http.calls[0][3].decode())
        check_in("K3 the line names the role", "login by code as default user", steps_of(t))
        http2 = stand_http()
        code, out, err = call(t, http2, "--as", "default user", "--attempt", "a1")
        check_eq("K3 --as \"default user\" (a role with a space): ran", code, 0)
    finally:
        S.cleanup(t)


def k4_created_user():
    t = actor_task()
    try:
        users = f"{LOCAL}/v1/users"
        echo = lambda headers, body: S.ok_json({"echo": body.decode("utf-8")}, status=201)  # noqa: E731
        http = stand_http({("POST", users): echo})
        body = t.task / "user.json"
        body.write_text('{"email": "{generated_username}@example.test", "password": "{generated_password}"}', encoding="utf-8")
        code, out, err = call(t, http, "--as", "default", "--body-file", str(body), method="POST", url=users)
        summary = json.loads(out)
        check_eq("K4 create: ran", code, 0)
        name = summary["created_account"].split(":", 1)[1]
        check("K4 the name has the form qa-factory-<ticket>-<case>-<hex8>",
              re.fullmatch(r"qa-factory-tp1-15045-tp1-15045-tc-012-[0-9a-f]{8}", name) is not None, name)
        sent = http.calls[-1][3].decode("utf-8")
        check_in("K4 the SENT bytes carry the generated name", name + "@example.test", sent)
        check_not_in("K4 ... and no placeholder", "{generated_", sent)
        password = json.loads(sent)["password"]
        check_eq("K4 the password is token_urlsafe(18): 24 characters", len(password), 24)
        saved = json.loads((t.task / summary["captures"][0]["path"]).read_text(encoding="utf-8"))
        check_in("K4 the SAVED request keeps the placeholders", "{generated_password}", saved["request"]["body"])
        check_in("K4 the saved answer (which echoed the values) is redacted", "[redacted]", saved["response"]["body"])
        leak = S.tree_text(t.task) + out + err
        check_not_in("K4 grep of the password over the whole story folder and the output: 0", password, leak)
        local = RP.state_file(t.project, "created-accounts", "TP1-15045.json")
        held = json.loads(local.read_text(encoding="utf-8"))["accounts"]
        check_eq("K4 the machine-local file holds the pair", [(a["name"], a["password"]) for a in held], [(name, password)])
        story = json.loads((t.task / "state" / "created-accounts.json").read_text(encoding="utf-8"))["accounts"]
        check_eq("K4 the story folder holds the NAME, the case and the endpoint's path only",
                 [(a["name"], a["case"], a["endpoint"], sorted(a)) for a in story],
                 [(name, API_CASE, "/v1/users", ["at", "case", "endpoint", "name"])])
        # --as created:<name> signs in as it (K5)
        http2 = stand_http()
        code, out, err = call(t, http2, "--as", f"created:{name}", "--attempt", "a1")
        check_eq("K5 --as created:<name>: ran", code, 0)
        check_in("K5 the created user signed in", name, http2.calls[0][3].decode())
        check_in("K5 ... and the line says so", f"login by code as created:{name}", steps_of(t))
        refusal("K5 an unknown created user", call(t, stand_http(), "--as", "created:nobody"), "another machine")
        local.unlink()
        refusal("K5 the record gone: the value is NOT rebuilt from artifacts/", call(t, stand_http(), "--as", f"created:{name}"),
                "another machine")
        # not 2xx: nothing recorded
        t2 = actor_task()
        try:
            bad = stand_http({("POST", users): S.ok_json({"detail": "exists"}, status=400)})
            body2 = t2.task / "user.json"
            body2.write_text('{"password": "{generated_password}"}', encoding="utf-8")
            code, out, err = TMC.http_run(t2, bad, "--method", "POST", "--url", users, "--body-file", str(body2))
            check_eq("K4 a 400 answer: the step is ok (the call completed), no account recorded", (code, "created_account" in out), (0, False))
            check_in("K4 ... and the detail says so", "no account was recorded (status 400)", (t2.attempt_dir(API_CASE) / "steps.jsonl").read_text(encoding="utf-8"))
            check_eq("K4 ... no file anywhere", (RP.state_file(t2.project, "created-accounts").exists(),
                                                 (t2.task / "state" / "created-accounts.json").exists()), (False, False))
            check_eq("K4 a lone {generated_password} is still a pair: generated, sent", len(json.loads(bad.calls[-1][3])["password"]), 24)
            # the template check runs on the file AS WRITTEN: a placeholder after `password="` is no secret yet
            raw = t2.task / "raw.txt"
            raw.write_text('password="{generated_password}"', encoding="utf-8")
            code, out, err = TMC.http_run(t2, stand_http({("POST", users): S.ok_json({}, status=201)}), "--method", "POST",
                                          "--url", users, "--body-file", str(raw), "--attempt", "a1")
            check_eq("K4 substitution comes AFTER the template check (the generated value would match a pattern)", code, 0)
            for where, argv in (("--url", ["--method", "GET", "--url", f"{GET}?u={{generated_username}}"]),
                                ("--header", ["--method", "GET", "--url", GET, "--header", "X: {generated_password}"]),
                                ("--state-url", ["--method", "GET", "--url", GET, "--state-url", f"{GET}/{{generated_username}}"])):
                refusal(f"K4 a placeholder in {where}", TMC.http_run(t2, stand_http(), *argv),
                        "generated values go only into the request body", doors=False)
        finally:
            S.cleanup(t2)
    finally:
        S.cleanup(t)
    name, password = MC.generated_account("/x/TP1-15045", "area/TC_007")
    check("K4 generated_account: the slug rule (lower case, [^a-z0-9-] -> -)",
          re.fullmatch(r"qa-factory-tp1-15045-area-tc-007-[0-9a-f]{8}", name) is not None, name)


def k12_create_answers_that_cannot_be_judged_normally():
    """t-1550 F5/F6: a 2xx create answer is recorded at once - slow, or refused by the secret scan - so the role is never
    left with a user nobody can sign in as, and a refusal that hides the answer still names the user (no value)."""
    users, jwt = f"{LOCAL}/v1/users", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig"
    for label, answer, want_code in (("slower than the limit", S.ok_json({"id": "u1"}, status=201, elapsed=100000.0), 1),
                                     ("refused by the secret scan", S.ok_json({"token": jwt}, status=201), 2)):
        t = actor_task()
        try:
            http = stand_http({("POST", users): answer})
            body = t.task / "user.json"
            body.write_text('{"email": "{generated_username}@example.test", "password": "{generated_password}"}', encoding="utf-8")
            code, out, err = call(t, http, "--as", "default", "--body-file", str(body), method="POST", url=users)
            sent = json.loads(http.calls[-1][3].decode("utf-8"))
            name, password = sent["email"].split("@")[0], sent["password"]
            check_eq(f"K12 a 2xx create answer {label}: the exit", code, want_code)
            local = RP.state_file(t.project, "created-accounts", "TP1-15045.json")
            held = json.loads(local.read_text(encoding="utf-8"))["accounts"] if local.is_file() else []
            check_eq("K12 ... the machine-local pair is recorded", [(a["name"], a["password"]) for a in held], [(name, password)])
            story = (t.task / "state" / "created-accounts.json")
            check_eq("K12 ... and the story folder holds the name", story.is_file() and name in story.read_text(encoding="utf-8"), True)
            if want_code == 1:
                check_in("K12 F5 the step detail says the account was recorded and the answer was late",
                         f"account recorded as created:{name}; the answer came after the limit", "\n".join(steps_detail(t)))
            else:
                check_in("K12 F6 the refusal names the user that was created", f"created:{name}", err)
                check_in("K12 F6 ... and the door (`--as created:`, do not create another)", "do not create another", err)
            check_not_in(f"K12 {label}: grep of the password over the story folder and every output: 0", password,
                         S.tree_text(t.task) + out + err)
        finally:
            S.cleanup(t)


def steps_detail(t):
    path = t.attempt_dir(API_CASE) / "steps.jsonl"
    return [json.loads(x).get("detail", "") for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.is_file() else []


def k6_nothing_changes_without_actors():
    t = actor_task(pre="preconditions: []")
    try:
        request = prepare(t)
        check_eq("K6 a case with no account precondition: `actors` is the declared empty list", request.get("actors"), [])
        http = stand_http()
        code, out, err = call(t, http)
        check_eq("K6 ran as before", (code, steps_of(t), err), (0, [f"http GET {GET}"], ""))
        check_in("K6 the default account signed in", S.USER, http.calls[0][3].decode())
        check("K6 no `created_account` key, no `actors` side effect on stdout", "created_account" not in out)
    finally:
        S.cleanup(t)


def k7_refusals():
    t = actor_task(roles={"default user": ROLES["default user"], "three": "A_ONE / B_TWO / C_THREE in x",
                          "none": "NOT provisioned locally", "one": "ONLY_ONE in x", "swapped": "AUTH_PASSWORD / AUTH_USERNAME in x"})
    try:
        cfg, _root = MC.load_config(t.task)
        stand = cfg["environments"][0]
        for label, actor, needle in (("a role the stand does not list", "nobody", "is not an account this stand lists"),
                                     ("three names", "three", "names 3 keys"), ("no names", "none", "names 0 keys"),
                                     ("one name", "one", "names 1 keys"), ("empty", "", "--as is empty"),
                                     ("env: no slash", "env:A", "is not `env:USER_KEY/SECRET_KEY`"),
                                     ("env: empty half", "env:A/", "is not `env:USER_KEY/SECRET_KEY`"),
                                     ("env: empty first half", "env:/B", "is not `env:USER_KEY/SECRET_KEY`"),
                                     ("env: three parts", "env:A/B/C", "is not `env:USER_KEY/SECRET_KEY`"),
                                     ("env: a bad name", "env:1A/B", "is not `env:USER_KEY/SECRET_KEY`"),
                                     ("env: a space", "env:A B/C", "is not `env:USER_KEY/SECRET_KEY`"),
                                     ("created: empty", "created:", "another machine")):
            try:
                MC.resolve_actor(cfg, stand, actor, t.task)
                check(f"K7 {label}: refused", False)
            except ValueError as exc:
                text = str(exc)
                check_in(f"K7 {label}: says {needle!r}", needle, text)
                check(f"K7 {label}: names a door with its key", all(d.replace("--as ", "") in text or d in text for d in ("env:USER_KEY/SECRET_KEY", "default")), text)
        check_eq("K7 a role of two names is resolved as written", MC.resolve_actor(cfg, stand, "default user", t.task),
                 ("AUTH_USERNAME", "AUTH_PASSWORD", None, "default user"))
        check_eq("K7 the order of the note is kept (a password first is the known behaviour: the login then fails by name)",
                 MC.resolve_actor(cfg, stand, "swapped", t.task)[:2], ("AUTH_PASSWORD", "AUTH_USERNAME"))
        check_eq("K7 env:U/S", MC.resolve_actor(cfg, stand, "env:QA_X/QA_Y", t.task), ("QA_X", "QA_Y", None, "env:QA_X"))
        stand["credentials_by_role"]["default"] = "AUTH_USERNAME / AUTH_PASSWORD"
        try:
            MC.resolve_actor(cfg, stand, "nobody", t.task)
        except ValueError as exc:
            check_in("K7 a role named `default` is unreachable and the refusal says so", "reserved", str(exc))
        check_eq("K7 ... `default` is the stand's default, not that role", MC.resolve_actor(cfg, stand, "default", t.task)[3], "default")
        refusal("K7 a key not in the env file: by NAME, never the value",
                call(t, stand_http(), "--as", "env:NO_SUCH_U/NO_SUCH_S"), "NO_SUCH_U", doors=False)
        refusal("K7 a role the stand does not list, through the CLI", call(t, stand_http(), "--as", "nobody"), "`nobody`")
        refusal("K7 three names, through the CLI", call(t, stand_http(), "--as", "three"), "names 3 keys")
    finally:
        S.cleanup(t)
    cfg = S.config(manual_capture={"login": {"http": None, "ui": None}})
    t = S.make_task(manual=("api",), cfg=cfg)
    try:
        refusal("K7 login: null and --as", call(t, stand_http(), "--as", "default"), "need no login", "nothing to sign in", doors=False)
    finally:
        S.cleanup(t)


def k8_the_question_sees_the_actors():
    from story_run_common import d2_seed, driver_for
    import harness
    root, task_root, env = d2_seed("QA-9", environment="Local", pending=False)
    try:
        driver = driver_for(root, env, "QA-9")
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["environment"] = {"env_file": "account.env"}
        cfg["environments"] = [{"name": "Local", "base_url": "http://localhost:8080", "credentials_by_role": {
            "default user": ROLES["default user"], "ghost": "GHOST_USERNAME / GHOST_PASSWORD in x"}}]
        path.write_text(json.dumps(cfg), encoding="utf-8")
        (root / "account.env").write_text("AUTH_USERNAME=u\nAUTH_PASSWORD=p\n", encoding="utf-8")

        def request(case, check_):
            target = M.request_path(task_root, case)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"actors": [{"id": "PC-1", "what": "w", "check": check_}]}), encoding="utf-8")
        request("QA-9_TC_001", {"stand_account": "ghost"})
        kind, details = driver.stand_login_problem(["QA-9_TC_001"])
        check_eq("K8 a screen case whose actor's key is missing: `missing_key`", kind, "missing_key")
        check_in("K8 the details name the case and the account", "QA-9_TC_001", details)
        check_in("K8 ... and the key", "GHOST_USERNAME", details)
        check_eq("K8 no cases (an http-only block): nothing is asked", driver.stand_login_problem(), ("", ""))
        request("QA-9_TC_001", {"stand_account": "default user"})
        check_eq("K8 control: a listed account that is in the file is no problem", driver.stand_login_problem(["QA-9_TC_001"]), ("", ""))
        request("QA-9_TC_001", {"env": "QA_SECOND_USER_EMAIL"})
        check_eq("K8 an `env` actor whose key is not set: `missing_key`", driver.stand_login_problem(["QA-9_TC_001"])[0], "missing_key")
        check_eq("K8 a case with no request file adds nothing (the default account is read)",
                 driver.stand_login_problem(["QA-9_TC_404"]), ("", ""))
        import story_run
        import inspect
        source = inspect.getsource(story_run.Driver.stand_login_gate)
        check("K8 POSITION: the actors are checked only after `if not screens: return`",
              0 <= source.index("if not screens:") < source.index("stand_login_problem(screens)"))
    finally:
        harness.cleanup(root)


def k9_old_and_unreadable_requests():
    t = actor_task()
    try:
        target = M.request_path(t.task, API_CASE)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((FIX / "request-0.10.4-tc014.json").read_bytes())
        check_eq("K9 a request from 0.10.4 (no `actors`)", M.request_actors(t.task, API_CASE), ([], ""))
        target.write_text("{not json", encoding="utf-8")
        actors, why = M.request_actors(t.task, API_CASE)
        check_eq("K9 an unreadable request file: no actors, said", (actors, bool(why)), ([], True))
        target.write_text(json.dumps({"refused": {"reason": "r", "door": "d"}}), encoding="utf-8")
        check_eq("K9 a refused request is no actor", M.request_actors(t.task, API_CASE), ([], ""))
        check_eq("K9 no request file", M.request_actors(t.task, "NOPE_TC_1"), ([], ""))
        set_pre(t, "preconditions: [not json")
        request = prepare(t)
        check_eq("K9 an unreadable `preconditions:` line: the request is still made, `actors` is []", request["actors"], [])
        check("K9 ... with the reason, at most 200 characters", 0 < len(request["actors_unreadable"]) <= 200)
        http = stand_http()
        code, out, err = call(t, http)
        check_eq("K9 the capture goes on as if the case named none (default account) and says so once",
                 (code, err.count("could not be read")), (0, 1))
        check_in("K9 the default account signed in", S.USER, http.calls[0][3].decode())
    finally:
        S.cleanup(t)


def k10_report_line():
    t = S.make_task()
    try:
        state = t.task / "state"
        check_eq("K10 no file: no line", RF.created_accounts_line(t.task), "")
        for count in (1, 5, 6):
            rows = [{"name": f"qa-factory-x-{i}", "case": "C", "at": "t", "endpoint": "/v1/users"} for i in range(count)]
            (state / "created-accounts.json").write_text(json.dumps({"accounts": rows}), encoding="utf-8")
            line = RF.created_accounts_line(t.task)
            shown = line.count("qa-factory-x-")
            check_eq(f"K10 {count} created: {min(count, 5)} names shown" + (", the rest counted" if count > 5 else ""),
                     (shown, "+1 more" in line), (min(count, 5), count > 5))
            check_in(f"K10 {count}: says they are left in place", "they are left in place", line)
        (state / "created-accounts.json").write_text("{broken", encoding="utf-8")
        check_in("K10 a record that cannot be read is unknown, not none", "unknown", RF.created_accounts_line(t.task))
        (state / "created-accounts.json").write_text(json.dumps({"accounts": [{"name": "qa-factory-a"}]}), encoding="utf-8")
        check_in("K10 the line is in the block that lists the checks", "Users this story created on the stand: qa-factory-a",
                 RF.manual_checks_text(t.task))
        # TR3-10 A (F15): an `unconfirmed` row is no user the report may promise
        path = state / "created-accounts.json"
        row = lambda n, **x: {"name": n, "case": "C", "at": "t", "endpoint": "/v1/users", **x}      # noqa: E731
        path.write_text(json.dumps({"accounts": [row("qa-factory-ok"), row("qa-factory-bad", status="unconfirmed", reason="refused")]}), encoding="utf-8")
        line = RF.created_accounts_line(t.task)
        check_eq("K10 created_line_leaves_out_unconfirmed", ("qa-factory-ok" in line, "qa-factory-bad" in line, line.endswith("; 1 sign-up(s) not confirmed.")),
                 (True, False, True))
        path.write_text(json.dumps({"accounts": [row("qa-factory-bad", status="unconfirmed"), row("qa-factory-bad2", status="unconfirmed")]}),
                        encoding="utf-8")
        check_eq("K10 created_line_only_unconfirmed", RF.created_accounts_line(t.task),
                 "Users this story tried to create on the stand: none was confirmed (2 sign-up(s) not confirmed).")
        import manual_capture as MC
        MC.AccountDoubts(t.task).add("env:A/B", "the page said wrong password", "C")
        path.write_text(json.dumps({"accounts": [row("qa-factory-bad", status="unconfirmed", reason="the form came back")]}), encoding="utf-8")
        line = RF.unconfirmed_accounts_line(t.task)
        check_in("K10 unconfirmed_line_names_both_kinds: the created user and its reason", "qa-factory-bad (created: the form came back)", line)
        check_in("K10 unconfirmed_line_names_both_kinds: the given account and its why", "the stand's account env:A/B (given: the page said wrong password)", line)
        check_in("K10 the line is in the checks block", "Accounts the checks could not confirm", RF.manual_checks_text(t.task))
        MC.account_doubts_path(t.task).write_text("{broken", encoding="utf-8")
        check_eq("K10 unconfirmed_line_unreadable_is_unknown", RF.unconfirmed_accounts_line(t.task),
                 "Accounts the checks could not confirm: unknown - the record of them cannot be read.")
        MC.account_doubts_path(t.task).unlink()
        path.write_text(json.dumps({"accounts": [row("qa-factory-ok")]}), encoding="utf-8")
        check_eq("K10 no_unconfirmed_no_line", RF.unconfirmed_accounts_line(t.task), "")
    finally:
        S.cleanup(t)


def k27_3_the_role_is_read_through_one_reader():
    """GW1-27 K-27.3 (F-1): `default_user` (what the form teaches) and `default user` (what the stands write) are the same
    role for the gate, `resolve_actor`, `auto_actor` and `Driver.stand_login_problem` - and a doubt is a refusal.
    Mutants: `account_role` takes the first of two -> here; `resolve_actor` / the place of the stand search back to
    `in roles` -> here."""
    import gate_preflight as GP
    roles = {"default user": "AUTH_USERNAME / AUTH_PASSWORD", "Admin": "A_USER / A_PASS", "admin": "B_USER / B_PASS"}
    for label, asked, want in (("underscore", "default_user", "default user"), ("dash and case", "Default-User", "default user"),
                               ("edges trimmed", "  default user ", "default user"), ("exact beside a twin", "admin", "admin"),
                               ("exact, the other twin", "Admin", "Admin"), ("a twin by form only", "ADMIN", None),
                               ("a prefix", "adm", None), ("empty", "", None), ("blank", "   ", None), ("None", None, None),
                               ("a number", 7, None), ("reserved: default", "default", None), ("reserved: env:", "env:A/B", None)):
        check_eq(f"K-27.3 account_role: {label}", GP.account_role(roles, asked), want)
    check_eq("K-27.3 account_role: no roles", (GP.account_role({}, "x"), GP.account_role(None, "x")), (None, None))
    # F11: a text of separators only has an EMPTY normal form, and an empty form equals every other empty one: no match
    for label, held, asked in (("`_` against `-`", {"-": "A_B / C_D"}, "_"), ("`--` against the empty key", {"": "A_B / C_D"}, "--"),
                               ("`__` against `_`", {"_": "A_B / C_D"}, "__"), ("a blank key against blank text", {" ": "A_B / C_D"}, " _ ")):
        check_eq(f"K-27.3 account_role (separators only, F11): {label} is no match", GP.account_role(held, asked), None)
    check_eq("K-27.3 account_role: a role of separators asked exactly is still that key", GP.account_role({"_": "A_B / C_D"}, "_"), "_")
    check_eq("K-27.3 a reserved key is never reached by a looser spelling: `Default` is not the role `default`",
             GP.account_role({"default": "A_B / C_D"}, "Default"), None)
    cfg = {"environment": {}, "environments": [{"name": "Local", "credentials_by_role": roles}]}
    stand = cfg["environments"][0]
    check_eq("K-27.3 resolve_actor: the spelling of the form reaches the stand's role, the REAL key is the label",
             MC.resolve_actor(cfg, stand, "default_user", None), ("AUTH_USERNAME", "AUTH_PASSWORD", None, "default user"))
    check_eq("K-27.3 resolve_actor: the exact key beside a twin", MC.resolve_actor(cfg, stand, "admin", None)[3], "admin")
    try:
        MC.resolve_actor(cfg, stand, "ADMIN", None)
        check("K-27.3 resolve_actor: a twin is refused", False)
    except ValueError as exc:
        check_in("K-27.3 resolve_actor: the refusal lists the twins", "`Admin`, `admin`", str(exc))
        check_in("K-27.3 ... and the doors", "env:USER_KEY/SECRET_KEY", str(exc))
    try:
        MC.resolve_actor(cfg, stand, "nobody", None)
        check("K-27.3 resolve_actor: a wrong role is refused as before (no other account)", False)
    except ValueError as exc:
        check_in("K-27.3 resolve_actor: the old refusal", "is not an account this stand lists", str(exc))

    def auto(check_):
        held = MC._case_actors
        MC._case_actors = lambda task_root, case: [{"id": "PC-1", "what": "w", "check": check_}]
        try:
            return MC.auto_actor(cfg, stand, None, "C")
        except ValueError as exc:
            return "refused: " + str(exc)
        finally:
            MC._case_actors = held
    check_eq("K-27.3 auto_actor: `default_user` signs in as the role the stand writes", auto({"stand_account": "default_user"}), "default user")
    check_eq("K-27.3 auto_actor: `default` is `default`", auto({"stand_account": "default"}), "default")
    check_eq("K-27.3 auto_actor: ` default ` is trimmed", auto({"stand_account": " default "}), "default")
    check_in("K-27.3 auto_actor: a twin is a refusal naming it", "more than one role", auto({"stand_account": "ADMIN"}))
    check_in("K-27.3 auto_actor: a wrong role is the old refusal", "the stand lists no role `ghost`", auto({"stand_account": "ghost"}))

    from story_run_common import d2_seed, driver_for
    import harness
    root, task_root, env = d2_seed("QA-9", environment="Local", pending=False)
    try:
        driver = driver_for(root, env, "QA-9")
        path = root / "qa-factory" / "config.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config["environment"] = {"env_file": "account.env"}
        first = {"default user": ROLES["default user"], "Admin": "AUTH_USERNAME / AUTH_PASSWORD",
                 "admin": "AUTH_USERNAME / AUTH_PASSWORD"}
        config["environments"] = [{"name": "Local", "base_url": "http://localhost:8080", "credentials_by_role": first},
                                  {"name": "Other", "base_url": "http://other:8080",
                                   "credentials_by_role": {"ADMIN": "AUTH_USERNAME / AUTH_PASSWORD"}}]
        path.write_text(json.dumps(config), encoding="utf-8")
        (root / "account.env").write_text("AUTH_USERNAME=u\nAUTH_PASSWORD=p\n", encoding="utf-8")

        def request(check_):
            target = M.request_path(task_root, "QA-9_TC_001")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"actors": [{"id": "PC-1", "what": "w", "check": check_}]}), encoding="utf-8")
        request({"stand_account": "default_user"})
        check_eq("K-27.3 stand_login_problem: the gate's `met` (default_user for `default user`) is a login the sign-in reads",
                 driver.stand_login_problem(["QA-9_TC_001"]), ("", ""))
        request({"stand_account": " default "})
        check_eq("K-27.3 stand_login_problem: ` default ` is trimmed and needs no stand", driver.stand_login_problem(["QA-9_TC_001"]), ("", ""))
        request({"stand_account": "ghost"})
        check_eq("K-27.3 stand_login_problem: a wrong role is still `missing_key` (no sign-in under another account)",
                 driver.stand_login_problem(["QA-9_TC_001"])[0], "missing_key")
        request({"stand_account": "ADMIN"})
        kind, details = driver.stand_login_problem(["QA-9_TC_001"])
        check_eq("K-27.3 place 4: a twin on the first stand is a refusal - the search does not go on to the other stand",
                 kind, "missing_key")
        check_in("K-27.3 ... and the refusal is the resolver's, naming the twins", "could mean any of `Admin`, `admin`", details)
    finally:
        harness.cleanup(root)


def k40_the_login_reads_the_files_the_gate_reads():
    """OH3-40 (t-506 7, t-524 8): `read_login` reads `gate_preflight.configured_env_files` - `environment.env_files`, else
    `env_file` - from FILES only: the process environment never replaces a file value and a pair is never built from it (several files are layered, as in the gate).
    Mutants: read only `env_file` -> here (1); lay the process environment over the files -> here (5, 6); skip a path that is not
    a file -> here (8); `_env_values` no longer takes `export ` / a BOM -> here (4)."""
    import os
    import harness
    root = harness.temp_dir("qa-oh3-40-").resolve()

    def read(env, actor=None, process=None):
        held = {k: os.environ.get(k) for k in (process or {})}
        os.environ.update(process or {})
        try:
            got = MC.read_login({"environment": env}, root, actor=actor)
            return (got.username, got.password) if got is not None else None
        except MC.LoginMaterialMissing as exc:
            return ("refused", exc.part, str(exc))
        finally:
            for key, value in held.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def put(name, text, raw=False):
        (root / name).write_bytes(text if raw else text.encode("utf-8"))

    try:
        put(".env.local", "USER_EMAIL=local-user\nUSER_PASSWORD=local-pass\n")
        keys = {"user_key": "USER_EMAIL", "secret_keys": ["USER_PASSWORD"]}
        check_eq("OH3-40 1: only `env_files` with `.env.local`: the default login reads it",
                 read({**keys, "env_files": [".env.local"]}), ("local-user", "local-pass"))
        check_eq("OH3-40 1: ... and `--as env:USER/SECRET` reads it too",
                 read({**keys, "env_files": [".env.local"]}, actor="env:USER_EMAIL/USER_PASSWORD"), ("local-user", "local-pass"))
        put("account.env", "USER_EMAIL=old-user\nUSER_PASSWORD=old-pass\n")
        check_eq("OH3-40 1: only `env_file`: the old reading", read({**keys, "env_file": "account.env"}), ("old-user", "old-pass"))
        check_eq("OH3-40 3: both: `env_files` wins, as for the gate",
                 read({**keys, "env_file": "account.env", "env_files": [".env.local"]}), ("local-user", "local-pass"))
        check_eq("OH3-40 3: neither (`env_files: []`, no `env_file`): no login", read({**keys, "env_files": []}), None)
        check_eq("OH3-40 3: `env_files: []` with `env_file`: the old reading", read({**keys, "env_files": [], "env_file": "account.env"}),
                 ("old-user", "old-pass"))
        # 4 the shapes of a line the old reader took stay taken
        put("shaped.env", b"\xef\xbb\xbfexport USER_EMAIL=shaped-user\nexport USER_PASSWORD='shaped pass'\n=x\n", raw=True)
        check_eq("OH3-40 4: `export` and a BOM are read", read({**keys, "env_files": ["shaped.env"]}), ("shaped-user", "shaped pass"))
        # 5 the process environment never replaces a value of a file, and fills no key of a file
        check_eq("OH3-40 5: a key of the file is not replaced by the process environment",
                 read({**keys, "env_files": [".env.local"]}, process={"USER_EMAIL": "someone-else", "USER_PASSWORD": "other"}),
                 ("local-user", "local-pass"))
        put("half.env", "USER_EMAIL=half-user\n")
        got = read({**keys, "env_files": ["half.env"]}, process={"USER_PASSWORD": "from-process"})
        check_eq("OH3-40 6: the user in the file and the password only in the process: `key`, never a pair of two sources",
                 got[:2], ("refused", "key"))
        check_in("OH3-40 6: ... naming the key and the file, not a value", "USER_PASSWORD is not set in half.env", got[2])
        check_not_in("OH3-40 6: ... and no value", "from-process", got[2])
        put("empty.env", "USER_EMAIL=\nUSER_PASSWORD=\n")
        check_eq("OH3-40 6: empty values in the file are no login", read({**keys, "env_files": ["empty.env"]})[:2], ("refused", "key"))
        put("keyless.env", "OTHER=1\n")
        check_eq("OH3-40 6: a file with no key, the keys in the process: `key`, not `file`",
                 read({**keys, "env_files": ["keyless.env"]}, process={"USER_EMAIL": "p", "USER_PASSWORD": "p"})[:2], ("refused", "key"))
        # 7 several files: the later one wins; a missing one is skipped; none at all names every file
        put("late.env", "USER_EMAIL=late-user\n")
        check_eq("OH3-40 7: two files with one key: the later wins, the other key stays from the earlier",
                 read({**keys, "env_files": [".env.local", "late.env"]}), ("late-user", "local-pass"))
        put("blank-late.env", "USER_EMAIL=\n")
        check_eq("OH3-40 7: an empty value in a later file does not wipe the earlier one (the gate leaves empties out)",
                 read({**keys, "env_files": [".env.local", "blank-late.env"]}), ("local-user", "local-pass"))
        check_eq("OH3-40 7: one of two does not exist: the second is read", read({**keys, "env_files": ["nowhere.env", ".env.local"]}),
                 ("local-user", "local-pass"))
        got = read({**keys, "env_files": ["nowhere.env", "nowhere-2.env"]}, process={"USER_EMAIL": "p", "USER_PASSWORD": "p"})
        check_eq("OH3-40 7: none exists (the keys in the process): `file`", got[:2], ("refused", "file"))
        check_in("OH3-40 7: ... naming BOTH files", "nowhere.env, nowhere-2.env", got[2])
        check_eq("OH3-40 7: a file outside the root is read as `root / path`, as for the gate",
                 read({**keys, "env_files": ["../" + root.name + "/.env.local"]}), ("local-user", "local-pass"))
        # 8 a folder where a file should be
        (root / "folder.env").mkdir()
        got = read({**keys, "env_files": [".env.local", "folder.env"]})
        check_eq("OH3-40 8: a folder in the list: `unreadable`, not `file` and not skipped", got[:2], ("refused", "unreadable"))
        check_in("OH3-40 8: ... naming it", "folder.env", got[2])
        # 9 several files are layered as in the gate: a partial replacement in the later file is legal (never the process env)
        put("base.env", "USER_EMAIL=admin\nUSER_PASSWORD=adminpw\n")
        put("over.env", "USER_EMAIL=other\n")
        check_eq("OH3-40 9: `.env` + `.env.local` with one key: `other` / `adminpw`, as the gate reads them",
                 read({**keys, "env_files": ["base.env", "over.env"]}), ("other", "adminpw"))
        # 10 the brief names the key NAMES of the files the login reads (`_env_file_key_names`, t-561 F-12)
        import brief_pack
        names = lambda block, name="x": brief_pack._env_file_key_names(block, root)  # noqa: E731
        put("names-a.env", "ACCOUNT_SECRET=1\nPLAIN=1\n")
        put("names-b.env", "OTHER_PASSWORD=2\nACCOUNT_SECRET=3\n")
        check_eq("OH3-40 10: only `env_files`: its secret-looking names, never `none`",
                 names({"env_files": ["names-a.env"]}), (["ACCOUNT_SECRET"], "names-a.env"))
        check_eq("OH3-40 10: `env_files` wins over `env_file`, as for the gate",
                 names({"env_file": "names-b.env", "env_files": ["names-a.env"]})[0], ["ACCOUNT_SECRET"])
        check_eq("OH3-40 10: two files: the names of both, once each", names({"env_files": ["names-a.env", "names-b.env"]}),
                 (["ACCOUNT_SECRET", "OTHER_PASSWORD"], "names-a.env, names-b.env"))
        check_eq("OH3-40 10: one of two missing: the other is read", names({"env_files": ["nowhere.env", "names-a.env"]})[0],
                 ["ACCOUNT_SECRET"])
        check_eq("OH3-40 10: none exists: unreadable (None), not an empty list", names({"env_files": ["nowhere.env"]})[0], None)
        check_eq("OH3-40 10: none configured: nothing", names({}), ([], ""))
    finally:
        harness.cleanup(root)


def main():
    k40_the_login_reads_the_files_the_gate_reads()
    k27_3_the_role_is_read_through_one_reader()
    k1_env_actor_with_one_name()
    k2_none_actor_and_the_create_route()
    k3_role_and_auto_actor()
    k4_created_user()
    k12_create_answers_that_cannot_be_judged_normally()
    k6_nothing_changes_without_actors()
    k7_refusals()
    k8_the_question_sees_the_actors()
    k9_old_and_unreadable_requests()
    k10_report_line()
    finish("test_manual_actor")


if __name__ == "__main__":
    main()
