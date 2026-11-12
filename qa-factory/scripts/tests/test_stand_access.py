"""Three lines, three verdicts: is the stand answering, did we get in, are the keys there.

The run these tests are written from (23.09.2026, a second checkout of the same harness): a
stand behind an identity provider answered 302 without a token, four keys nobody read sat in
`secret_keys`, and one undivided verdict turned both facts into the guess "likely clears once
the auth credentials above are in place".
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (  # noqa: E402
    check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project,
)

import env_probe  # noqa: E402
import stand_access  # noqa: E402

# A fixture value, never a credential: the point of every check below is that it does not
# come out the other end.
PW = "not-a-real-value"


def local_stand(answer: list):
    """A real socket that answers with whatever `answer[0]` says. The probe runs in a child
    process wherever readiness or a role calls it, so a stubbed function proves nothing about
    a 302 that must not be followed."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - the stdlib's own spelling
            self.send_response(answer[0])
            if 300 <= answer[0] < 400:
                self.send_header("Location", "https://idp.example.invalid/login")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def write_config(root: Path, environment: dict) -> None:
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["environment"] = environment
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def env_for(root: Path) -> dict:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    return env


def the_login_kinds() -> None:
    values = {"AUTH_USERNAME": "admin@example.invalid", "AUTH_PASSWORD": PW,
              "AUTH_SERVER_URL": "https://idp.example.invalid", "AUTH_REALM_NAME": "testproject1",
              "AUTH_CLIENT_ID": "sdk", "API_TOKEN": "a-token-value"}
    real_open = stand_access._open
    asked = []

    def answer(code, body=""):
        def fake(url, method, data, headers, timeout):
            asked.append({"url": url, "method": method, "data": data, "headers": headers})
            return (code, body)
        return fake

    try:
        # A project that never recorded how it logs in is an ONBOARDING gap, not a refusal.
        receipt = stand_access.login({}, values)
        check_eq("no access block -> not_recorded", receipt["status"], "not_recorded")
        check_in("and the why names the gap, not the person",
                 "schema not recorded - onboarding gap", receipt["why"])
        check_eq("a stand that needs no login is skipped, not failed",
                 stand_access.login({"kind": "none"}, values)["status"], "skipped")

        # local_login: the shape this harness uses when the identity provider keys are empty.
        access = {"kind": "local_login", "url": "/v1/local-auth/login",
                  "user_key": "AUTH_USERNAME", "secret_key": "AUTH_PASSWORD"}
        stand_access._open = answer(200, json.dumps({"access_token": "jwt-value"}))
        receipt = stand_access.login(access, values, "http://stand.example:8080")
        check_eq("local_login with a token in the answer is ok", receipt["status"], "ok")
        check_eq("the receipt holds the user KEY, not the user", receipt["user_key"], "AUTH_USERNAME")
        check_eq("the login endpoint is glued to the stand's address", asked[-1]["url"],
                 "http://stand.example:8080/v1/local-auth/login")
        printed = json.dumps(receipt)
        check_not_in("no password reaches the receipt", PW, printed)
        check_not_in("no token reaches the receipt", "jwt-value", printed)

        stand_access._open = answer(401)
        receipt = stand_access.login(access, values, "http://stand.example:8080")
        check_eq("a refused login is failed", receipt["status"], "failed")
        check_eq("with the code the stand answered", receipt["code"], 401)

        stand_access._open = answer(200, "{}")
        check_eq("200 without any token field is not a proof of login",
                 stand_access.login(access, values, "http://stand.example:8080")["status"], "failed")

        receipt = stand_access.login(access, {"AUTH_USERNAME": "admin@example.invalid"},
                                     "http://stand.example:8080")
        check_eq("a login key that is not set is skipped, not failed", receipt["status"], "skipped")
        check_in("and the why names the key", "AUTH_PASSWORD", receipt["why"])

        # OH3-10: the body's field names are data in `access`, never a guess in code (FR-13).
        stand_access._open = answer(200, json.dumps({"access_token": "jwt-value"}))
        stand_access.login(access, values, "http://stand.example:8080")
        sent = json.loads(asked[-1]["data"].decode("utf-8"))
        check_eq("OH3-10: the default body still sends username and password", sent,
                 {"username": "admin@example.invalid", "password": PW})
        by_email = dict(access, user_field="email")
        receipt = stand_access.login(by_email, values, "http://stand.example:8080")
        sent = json.loads(asked[-1]["data"].decode("utf-8"))
        check_eq("OH3-10: user_field email sends email and the default password field", sent,
                 {"email": "admin@example.invalid", "password": PW})
        check_not_in("OH3-10: ... and no username key", "username", sent)
        check_eq("OH3-10: ... and the login is ok", receipt["status"], "ok")
        sent_both = dict(access, user_field="login", secret_field="pass")
        stand_access.login(sent_both, values, "http://stand.example:8080")
        check_eq("OH3-10: secret_field renames the secret's field", json.loads(asked[-1]["data"].decode("utf-8")),
                 {"login": "admin@example.invalid", "pass": PW})
        stand_access.login(dict(access, user_field="  ", secret_field=None), values, "http://stand.example:8080")
        check_eq("OH3-10: blank field names fall back to the defaults", sorted(json.loads(asked[-1]["data"].decode("utf-8"))),
                 ["password", "username"])
        # D3: two equal names would send ONE key and drop the user while the login read `ok`: nothing is sent at all
        sent_before = len(asked)
        for label, bad in (("equal names", dict(access, user_field="x", secret_field="x")),
                           ("the user's field equal to the default secret field", dict(access, user_field="password")),
                           ("a non-string name", dict(access, user_field=["email"])),
                           ("a name that is a value", dict(access, user_field="admin@example.invalid"))):
            receipt = stand_access.login(bad, values, "http://stand.example:8080")
            check_eq(f"OH3-10 D3: {label} is refused, never ok", receipt["status"], "not_recorded")
            check_not_in(f"OH3-10 D3: {label} - the refusal prints no credential", PW, json.dumps(receipt))
            check_not_in(f"OH3-10 D3: {label} - ... nor the user", "admin@example.invalid", json.dumps(receipt))
        check_eq("OH3-10 D3: ... and none of them sent a request", len(asked), sent_before)

        # D1 + D2: a 400/422 names the field NAMES the stand's answer complains about (the measured Test Project 1 422 shape)
        testproject1_422 = {"detail": [{"type": "missing", "loc": ["body", "email"], "msg": "Field required",
                                   "input": {"username": "admin@example.invalid", "password": PW}}]}
        for refused in (422, 400):
            stand_access._open = answer(refused, json.dumps(testproject1_422))
            receipt = stand_access.login(access, values, "http://stand.example:8080")
            printed = json.dumps(receipt)
            check_eq(f"OH3-10: a {refused} answer is failed", receipt["status"], "failed")
            check_in(f"OH3-10: the {refused} why names access.user_field", "access.user_field", receipt["why"])
            check_in("OH3-10: ... and access.secret_field", "access.secret_field", receipt["why"])
            check_in(f"OH3-10 D2: the {refused} why names the field the answer complains about (`email`)",
                     "complains about `email`", receipt["why"])
            check_not_in(f"OH3-10 D1: the {refused} why carries no literal default (today ...)", "today", receipt["why"])
            # FB-3: `email` is a field the first body did not carry -> a second body goes out with it; the why names both
            check_in(f"OH3-10: the {refused} why names the first pair that was tried",
                     f"tried the body fields `username` / `password` (HTTP {refused}); then", receipt["why"])
            check_in(f"OH3-10: the {refused} why names the fields of the LAST body that was sent", "`email` and `password`",
                     receipt["why"])
            check_not_in(f"OH3-10: the {refused} receipt never prints the password", PW, printed)
            check_not_in("OH3-10: ... nor the user", "admin@example.invalid", printed)
        receipt = stand_access.login(by_email, values, "http://stand.example:8080")
        check_in("OH3-10 D1: with user_field email the why names the sent fields `email` and `password`",
                 "`email` and `password`", receipt["why"])
        for label, body, expect in (
                ("errors[].field", {"errors": [{"field": "login", "message": "required"}]}, ["login"]),
                ("errors as a map of names", {"errors": {"login": ["required"], "password": ["too short"]}},
                 ["login", "password"]),
                ("violations[].field", {"violations": [{"field": "user"}]}, ["user"]),
                ("a loc of several levels", {"detail": [{"loc": ["body", "user", "mail"]}]}, ["mail"]),
                ("a place word alone is no field", {"detail": [{"loc": ["body"]}]}, []),
                ("a message string is no name", {"detail": "Invalid credentials, try again"}, []),
                ("a shape the row does not hold", {"problem": {"missing": "email"}}, [])):
            check_eq(f"OH3-10 D2: {label}", stand_access.complained_fields(json.dumps(body)), expect)
        check_eq("OH3-10 D2: an answer that is not JSON names nothing", stand_access.complained_fields("<html>422</html>"), [])
        check_eq("OH3-10 D2: a name that contains the user's value is dropped, not printed",
                 stand_access.complained_fields(json.dumps({"errors": {"admin": ["x"], "email": ["x"]}}), ("admin",)),
                 ["email"])
        check_eq("OH3-10 D2: a value-shaped key (an address) is not a field name",
                 stand_access.complained_fields(json.dumps({"errors": {"admin@example.invalid": ["x"]}})), [])
        check_eq("OH3-10 D2: at most the row's max_names come out",
                 len(stand_access.complained_fields(json.dumps({"errors": {f"f{i}": 1 for i in range(20)}}))),
                 stand_access._login_error_shapes()["max_names"])
        real_path = stand_access.LOGIN_ERROR_SHAPES_PATH
        try:
            stand_access.LOGIN_ERROR_SHAPES_PATH = real_path.with_name("no-such-shapes.json")
            check_eq("OH3-10 D2: an unreadable row names nothing (FR-59), the status is still reported",
                     stand_access.complained_fields(json.dumps(testproject1_422)), [])
        finally:
            stand_access.LOGIN_ERROR_SHAPES_PATH = real_path
        stand_access._open = answer(401)
        check_not_in("OH3-10: a 401 is a refused account, not a body-shape hint", "access.user_field",
                     stand_access.login(access, values, "http://stand.example:8080")["why"])
        stand_access._open = answer(401, json.dumps(testproject1_422))
        check_not_in("OH3-10: ... and a 401 body names no complained field either", "complains",
                     stand_access.login(access, values, "http://stand.example:8080")["why"])

        # oidc_password: one instance of an access scheme, not the design.
        stand_access._open = answer(200, json.dumps({"access_token": "jwt-value"}))
        oidc = {"kind": "oidc_password", "url": "AUTH_SERVER_URL", "realm_key": "AUTH_REALM_NAME",
                "client_id_key": "AUTH_CLIENT_ID", "user_key": "AUTH_USERNAME",
                "secret_key": "AUTH_PASSWORD"}
        receipt = stand_access.login(oidc, values)
        check_eq("a password grant with an access_token is ok", receipt["status"], "ok")
        check_eq("the token endpoint is built from the keys the project named", asked[-1]["url"],
                 "https://idp.example.invalid/realms/testproject1/protocol/openid-connect/token")
        check_in("the grant is a form, and the secret never leaves it",
                 "grant_type=password", asked[-1]["data"].decode("utf-8"))
        check_not_in("the secret is not in the receipt", PW, json.dumps(receipt))
        # A project that simply records its token endpoint is served without a realm at all.
        stand_access.login({"kind": "oidc_password", "url": "https://idp.example.invalid/oauth2/token",
                            "user_key": "AUTH_USERNAME", "secret_key": "AUTH_PASSWORD"}, values)
        check_eq("a recorded token endpoint is used as it stands", asked[-1]["url"],
                 "https://idp.example.invalid/oauth2/token")

        # bearer_env: the proof is that the stand accepts the token the project already holds.
        stand_access._open = answer(200, "{}")
        receipt = stand_access.login({"kind": "bearer_env", "token_key": "API_TOKEN"}, values,
                                     "http://stand.example:8080",
                                     health_url="http://stand.example:8080/v1/config")
        check_eq("bearer_env accepted by the stand is ok", receipt["status"], "ok")
        check_eq("the token is presented as a bearer", asked[-1]["headers"]["Authorization"],
                 "Bearer a-token-value")
        check_not_in("and its value stays out of the receipt", "a-token-value", json.dumps(receipt))
    finally:
        stand_access._open = real_open

    # harness_command: the project's own login command proves itself, and its output is never
    # shown — a login command routinely prints the token it just obtained.
    ok_cmd = (f'"{sys.executable}" -c "import os,sys;'
              'sys.exit(0 if os.environ.get(\'AUTH_PASSWORD\') else 9)"')
    receipt = stand_access.login({"kind": "harness_command", "command": ok_cmd,
                                  "user_key": "AUTH_USERNAME"}, values, timeout=30)
    check_eq("a harness login command that exits 0 is ok", receipt["status"], "ok")
    check_eq("and the receipt names the key, not the account", receipt["user_key"], "AUTH_USERNAME")
    bad_cmd = f'"{sys.executable}" -c "print(\'leaked-string\');raise SystemExit(3)"'
    receipt = stand_access.login({"kind": "harness_command", "command": bad_cmd}, values, timeout=30)
    check_eq("a harness login command that fails is failed", receipt["status"], "failed")
    check_in("the exit code is named", "3", receipt["why"])
    check_not_in("its output is not repeated", "leaked-string", json.dumps(receipt))
    receipt = stand_access.login({"kind": "harness_command", "command": "no-such-login-program"},
                                 values, timeout=5)
    check_eq("a command this machine does not have is failed", receipt["status"], "failed")
    check_in("and says so by name", "no-such-login-program", receipt["why"])
    check_eq("only the login's own keys can stop a story",
             stand_access.login_keys({"kind": "local_login", "user_key": "U", "secret_key": "S"}),
             ["U", "S"])
    check_eq("OH3-10: login_keys is unchanged by user_field / secret_field", stand_access.login_keys(
        {"kind": "local_login", "user_key": "U", "secret_key": "S", "user_field": "email", "secret_field": "pass"}),
        ["U", "S"])
    check_eq("a bearer stand's login key is the token", stand_access.login_keys(
        {"kind": "bearer_env", "token_key": "T"}), ["T"])
    check_eq("a stand without a login has none", stand_access.login_keys({"kind": "none"}), [])


def the_liveness_rule() -> None:
    real = env_probe._fetch
    try:
        env_probe._fetch = lambda url, timeout: 302
        result = env_probe.liveness("http://stand.example/v1/config", [], [])
        check_eq("a redirect is a live stand that wants a login, never a dead one",
                 result["verdict"], "wants_login")
        check_eq("and the code is reported as it came", result["code"], 302)
        check_eq("a code the project recorded as its norm is the same verdict",
                 env_probe.liveness("http://x/y", [], [302])["verdict"], "wants_login")
        env_probe._fetch = lambda url, timeout: 401
        check_eq("401 is a stand demanding a login", env_probe.liveness("http://x/y", [], [])["verdict"],
                 "wants_login")
        check("and env_probe.health calls it alive, so stand_health agrees",
              env_probe.health("http://x/y", [])[0])
        env_probe._fetch = lambda url, timeout: 200
        check_eq("200 is alive", env_probe.liveness("http://x/y", [], [])["verdict"], "alive")
        env_probe._fetch = lambda url, timeout: 500
        check_eq("5xx is dead", env_probe.liveness("http://x/y", [], [])["verdict"], "dead")
        env_probe._fetch = lambda url, timeout: 404
        result = env_probe.liveness("http://x/y", [], [])
        check_eq("a health path that is not there is dead", result["verdict"], "dead")
        check_in("and the note names the config key, not the person", "health_path", result["note"])

        def explode(url, timeout):
            raise OSError("no route to host")
        env_probe._fetch = explode
        check_eq("nothing answering is dead", env_probe.liveness("http://x/y", [], [])["verdict"], "dead")
        check_eq("no address at all is unchecked, never a verdict about the stand",
                 env_probe.liveness("", [], [])["verdict"], "unchecked")
    finally:
        env_probe._fetch = real


def the_three_lines() -> None:
    root = temp_project("qa-factory-env-probe-")
    real = env_probe._fetch
    try:
        (root / "tests" / ".env").write_text(
            "TESTPROJECT1_API_DOMAIN=http://stand.example:8080\nAUTH_USERNAME=admin@example.invalid\n"
            f"AUTH_PASSWORD={PW}\n", encoding="utf-8")
        base = {"env_file": "tests/.env", "base_url_key": "TESTPROJECT1_API_DOMAIN",
                "user_key": "AUTH_USERNAME", "secret_keys": ["AUTH_PASSWORD"],
                "health_path": "/v1/config"}
        write_config(root, base)
        env_probe._fetch = lambda url, timeout: 200

        # 1. A config from 0.7.x, with no access block at all: the login line says what is
        #    missing is a RECORD, and nothing is blocked by it.
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        result = env_probe.probe(cfg, root=root)
        lines = env_probe.verdict_lines(result)
        check_eq("the three lines come in the fixed order",
                 [line.split(":")[0] for line in lines], ["liveness", "login", "keys"])
        check_in("liveness first", "alive", lines[0])
        check_in("a config with no access block is not_recorded", "not_recorded", lines[1])
        check_in("and says whose gap it is", "onboarding gap", lines[1])
        check_eq("keys are ok when the config's own keys are set",
                 lines[2].split("—")[0].strip(), "keys: ok")
        check_eq("and nothing of this is Layer 1", result["layer1"], [])

        # 2. A key that is not the login's own: named with who needs it, and no halt.
        write_config(root, {**base, "secret_keys": ["AUTH_PASSWORD", "RP_API_KEY", "AWS_ACCESS_KEY"],
                            "integrations": [{"name": "reportportal", "keys": ["RP_API_KEY"],
                                              "owner": "user", "required_by": ["api"]}]})
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        result = env_probe.probe(cfg, root=root)
        keys_line = env_probe.verdict_lines(result)[2]
        check_in("a missing key is counted, not hidden", "2 missing", keys_line)
        check_in("an integration key names the area that needs it", "RP_API_KEY: needed by api",
                 keys_line)
        check_in("a key nobody in this story reads says exactly that",
                 f"AWS_ACCESS_KEY: needed by {env_probe.NOTHING_IN_STORY}", keys_line)
        check_eq("and neither of them is Layer 1", result["layer1"], [])

        # 2b. --task: a key no integration claims is looked for in the story's own cases, where
        #     a `preconditions` check already binds a variable to the case that needs it.
        case_dir = root / "qa-factory" / "artifacts" / "TP1-15045" / "work" / "test-cases"
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "TC-007.md").write_text(
            '---\nid: TC-007\ntask: TP1-15045\npreconditions: [{"id": "PC-1", "kind": "env", '
            '"what": "the report portal key is set", "check": {"env": "RP_API_KEY"}}]\n---\n'
            "## Given\nnothing\n", encoding="utf-8")
        write_config(root, {**base, "secret_keys": ["AUTH_PASSWORD", "RP_API_KEY"]})
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        keys_line = env_probe.verdict_lines(env_probe.probe(cfg, task="TP1-15045", root=root))[2]
        check_in("a key a case asks for names that case", "RP_API_KEY: needed by TC-007", keys_line)

        # 3. The login's own key IS Layer 1 — that is the whole of the first line's meaning.
        write_config(root, {**base, "user_key": "AUTH_USERNAME_MISSING"})
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        result = env_probe.probe(cfg, root=root)
        check_eq("a missing login key is Layer 1", len(result["layer1"]), 1)
        check_in("and the line says the login needs it", "the login needs it", result["layer1"][0])

        # 4. With a proven login no missing key can be Layer 1, whatever a stale config lists.
        real_login = stand_access.login
        try:
            stand_access.login = lambda *a, **k: {"status": "ok", "code": 200,
                                                  "user_key": "AUTH_USERNAME", "why": "proved"}
            write_config(root, {**base, "user_key": "AUTH_USERNAME_MISSING",
                                "access": {"kind": "local_login", "url": "/v1/local-auth/login",
                                           "user_key": "AUTH_USERNAME",
                                           "secret_key": "AUTH_PASSWORD"}})
            cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
            result = env_probe.probe(cfg, root=root)
            check_eq("login ok -> no missing key is Layer 1", result["layer1"], [])
            check_in("and the login line names the key it got in as", "ok as AUTH_USERNAME",
                     env_probe.verdict_lines(result)[1])
        finally:
            stand_access.login = real_login

        # 5. A stand that does not answer is Layer 1, and no login is attempted against it.
        def explode(url, timeout):
            raise OSError("connection refused")
        env_probe._fetch = explode
        write_config(root, base)
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        result = env_probe.probe(cfg, root=root)
        check_eq("a dead stand is Layer 1", len(result["layer1"]), 1)
        check_eq("and the login says nothing was tried", result["login"]["status"], "skipped")

        # 6. The CLI prints the three lines at column 0 and exits 0 on a non-login key. It runs
        #    in a child process, so it answers from a real socket.
        env_probe._fetch = lambda url, timeout: 200
        answer = [200]
        server, stand = local_stand(answer)
        (root / "tests" / ".env").write_text(
            f"TESTPROJECT1_API_DOMAIN={stand}\nAUTH_USERNAME=admin@example.invalid\n"
            f"AUTH_PASSWORD={PW}\n", encoding="utf-8")
        write_config(root, {**base, "secret_keys": ["AUTH_PASSWORD", "RP_API_KEY"]})
        proc = run_script("env_probe.py", "--project-root", root, "--no-login", env=env_for(root))
        check_eq("a key nothing in this story needs does not stop the story", proc.returncode, 0)
        printed = [line for line in proc.stdout.splitlines() if line[:1].strip()]
        check_eq("and the only lines at column 0 are the three verdicts, in order",
                 [line.split(":")[0] for line in printed], ["liveness", "login", "keys"])
        check_not_in("no secret is printed", PW, proc.stdout + proc.stderr)
        proc = run_script("env_probe.py", "--project-root", root, "--no-login", "--json",
                          env=env_for(root))
        payload = json.loads(proc.stdout)
        check_eq("--json carries the same four fields", sorted(payload),
                 ["keys", "layer1", "liveness", "login"])
        check_not_in("and no secret", PW, proc.stdout)
        server.shutdown()
        server.server_close()
    finally:
        env_probe._fetch = real
        cleanup(root)


def the_config_that_fails_its_own_probe() -> None:
    """readiness runs the probe in a child process, so this one answers with a real socket:
    a 302 that is not followed is exactly the fact the whole item is about."""
    import readiness
    answer = [200]
    server, stand = local_stand(answer)
    root = temp_project("qa-factory-env-readiness-")

    def verdict(environment: dict) -> dict:
        write_config(root, environment)
        return readiness.check_environment({"environment": environment}, root)

    try:
        (root / "tests" / ".env").write_text(
            f"TESTPROJECT1_API_DOMAIN={stand}\nAUTH_USERNAME=admin@example.invalid\n"
            f"AUTH_PASSWORD={PW}\n", encoding="utf-8")
        base = {"env_file": "tests/.env", "base_url_key": "TESTPROJECT1_API_DOMAIN",
                "user_key": "AUTH_USERNAME", "secret_keys": ["AUTH_PASSWORD"],
                "health_path": "/v1/config"}

        # A 0.7.x project whose keys are all there stays `ok` — nobody re-onboards for this.
        entry = verdict(base)
        check_eq("a working 0.7.x config without an access block stays ok", entry["status"], "ok")
        check_in("and the note carries all three verdicts", "login not_recorded", entry["note"])

        # The trap: keys inventoried out of the harness's code, absent from the env file.
        entry = verdict({**base, "secret_keys": ["AUTH_PASSWORD", "AUTH_CLIENT_SECRET"]})
        check_eq("a config that fails its own probe is missing", entry["status"], "missing")
        check_eq("and it is the factory's own defect", entry["owner"], "factory")
        check_in("the note quotes the key", "AUTH_CLIENT_SECRET", entry["note"])
        check_in("and names the file it is not in", "tests/.env", entry["note"])
        check_in("the remedy offers integrations[] with required_by",
                 "required_by", json.dumps(entry["remedy"]))

        # Keys the factory sets itself, and switches of this machine's own client.
        entry = verdict({**base, "secret_keys": ["AUTH_PASSWORD", "HEADLESS"],
                         "extra_keys": ["AWS_PROFILE"]})
        check_eq("HEADLESS in secret_keys is a finding", entry["status"], "missing")
        check_eq("owned by the factory that wrote it", entry["owner"], "factory")
        check_in("named", "HEADLESS", entry["note"])
        check_in("with the client switch beside it", "AWS_PROFILE", entry["note"])

        # A stand that wants a login and a project that never recorded how it logs in: a gap
        # of the factory's own, so the story is warned and never stopped.
        answer[0] = 302
        entry = verdict(base)
        check_eq("an unrecorded access scheme is unknown, not a blocker", entry["status"], "unknown")
        check_eq("and the factory owns the gap", entry["owner"], "factory")
        check_in("the note says what is not recorded", "access scheme not recorded", entry["note"])
        check_in("and quotes the code the stand answered, unfollowed", "302", entry["note"])

        # The same 302 with the scheme recorded is not a finding at all.
        answer[0] = 302
        recorded = {**base, "access": {"kind": "none", "unauth_status": [302]}}
        entry = verdict(recorded)
        check_eq("with the scheme recorded the same stand is ok", entry["status"], "ok")

        # And a stand nobody is listening on is still the blocker it always was.
        port = server.server_address[1]
        server.shutdown()
        entry = verdict(base)
        check_eq("a stand that does not answer is missing", entry["status"], "missing")
        check_eq("and that one is the person's", entry["owner"], "user")
        check(f"port {port} is named in the note", "127.0.0.1" in entry["note"], entry["note"])
    finally:
        server.server_close()
        cleanup(root)


def the_protection_page() -> None:
    """B-408 (AK7): a 401/403 that is a protection layer's page is not "the stand demands a login" and not "the account was
    refused". The verdict WORDS are unchanged (F6); the sentences stop claiming what was not shown, and no credential appears."""
    import http_client
    page = (b"<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head>"
            b"<body>Sorry, you have been blocked</body></html>")
    pairs = [("Server", "cloudflare"), ("CF-RAY", "8a1b"), ("Content-Type", "text/html")]
    answer = http_client.Answer(403, http_client.Headers(pairs), page, False, False, None, "http://x/y", 0.0,
                                http_client.classify(403, pairs, page))
    real_fetch, real_open = env_probe._fetch, stand_access._open
    try:
        env_probe._fetch = lambda url, timeout: answer
        result = env_probe.liveness("http://x/y", [], [])
        check_eq("AK7: the verdict word is unchanged: a protection page is still a live address that wants a login", (result["verdict"], result["code"]),
                 ("wants_login", 403))
        check_in("AK7: ... but the note names the title and does not say the STAND demands a login", "Attention Required! | Cloudflare", result["note"])
        check_not_in("AK7: ... no 'demands a login' claim", "demands a login", result["note"])
        env_probe._fetch = lambda url, timeout: 403
        check_in("AK7 control: a bare status (the old seam) keeps the old sentence", "demands a login", env_probe.liveness("http://x/y", [], [])["note"])
        ok_page = http_client.Answer(200, http_client.Headers([("Content-Type", "text/html")]), page, False, False, None, "http://x/y", 0.0,
                                     http_client.classify(200, [("Content-Type", "text/html")], page, expect="json"))
        env_probe._fetch = lambda url, timeout: ok_page
        result = env_probe.liveness("http://x/y", [], [])
        check_eq("AK7: a 200 HTML page is still alive", result["verdict"], "alive")
        check_in("AK7: ... and its note names the title", "Attention Required! | Cloudflare", result["note"])

        values = {"AUTH_USERNAME": "admin@example.invalid", "AUTH_PASSWORD": PW, "API_TOKEN": "a-token-value"}
        body = page.decode("utf-8").replace("blocked", f"blocked {PW} a-token-value admin@example.invalid")
        stand_access._open = lambda url, method, data, headers, timeout: (403, body)
        access = {"kind": "local_login", "url": "/v1/local-auth/login", "user_key": "AUTH_USERNAME", "secret_key": "AUTH_PASSWORD"}
        receipt = stand_access.login(access, values, "http://stand.example:8080")
        check_eq("AK7: the receipt words are unchanged: failed, with the code", (receipt["status"], receipt["code"]), ("failed", 403))
        check_in("AK7: the why says what answered, not that the account was refused", "Attention Required! | Cloudflare", receipt["why"])
        check_in("AK7: ... and that it could not be told who wrote it", "could not be told", receipt["why"])
        title_leak = body.replace("Attention Required! | Cloudflare", f"Denied for {PW}")
        stand_access._open = lambda url, method, data, headers, timeout: (403, title_leak)
        leaky = stand_access.login(access, values, "http://stand.example:8080")
        check("AK7: no credential value in what login returns, even from a title that carries one",
              PW not in json.dumps(leaky) and "a-token-value" not in json.dumps(leaky) and "<redacted>" in leaky["why"], json.dumps(leaky))
        stand_access._open = lambda url, method, data, headers, timeout: (403, "")
        check_not_in("AK7 control: an empty 403 body keeps the old sentence, no suffix", "the answer:",
                     stand_access.login(access, values, "http://stand.example:8080")["why"])
        stand_access._open = lambda url, method, data, headers, timeout: (401, '{"detail": "bad credentials"}')
        check_not_in("AK7 control: the stand's own JSON refusal keeps the old sentence", "the answer:",
                     stand_access.login(access, values, "http://stand.example:8080")["why"])
        stand_access._open = lambda url, method, data, headers, timeout: (403, body)
        bearer = stand_access.login({"kind": "bearer_env", "token_key": "API_TOKEN", "url": "http://stand.example/v1/me"}, values)
        check("AK7: a bearer stand behind a page says so, and the token is not in the sentence",
              "Attention Required! | Cloudflare" in bearer["why"] and "a-token-value" not in bearer["why"], bearer["why"])
    finally:
        env_probe._fetch, stand_access._open = real_fetch, real_open


def the_stalled_body() -> None:
    """B-408 F1: the status arrived and the body stalls. Liveness reads only the status: a 200 is still `alive` (the stand
    answered; it used to be `alive` because the body was never read), a 500 still `dead`. The login's own words are unchanged:
    a 2xx whose body never comes was always `NO ANSWER (TimeoutError)`; an error status was always its code."""
    from test_http_client import StallStub
    stall = StallStub(200)
    real = env_probe.HEALTH_TIMEOUT_S
    env_probe.HEALTH_TIMEOUT_S = 1
    try:
        result = env_probe.liveness(stall.url, [], [])
        check_eq("F1: a 200 whose body stalls is ALIVE (the old verdict word), with its code", (result["verdict"], result["code"]), ("alive", 200))
        check_not_in("F1: ... and the note does not claim that nothing answered", "NO ANSWER", result["note"])
        try:
            stand_access._open(stall.url, "GET", None, {}, 1)
            said = "returned"
        except TimeoutError:
            said = "TimeoutError"
        check_eq("F1: stand_access._open keeps raising the timeout of a stalled 2xx body", said, "TimeoutError")
        receipt = stand_access.login({"kind": "bearer_env", "token_key": "API_TOKEN", "url": stall.url}, {"API_TOKEN": "a-token-value"}, timeout=1)
        check_eq("F1: ... so the login's word stays `failed` ... NO ANSWER (TimeoutError)",
                 (receipt["status"], "NO ANSWER (TimeoutError)" in receipt["why"]), ("failed", True))
        stall.status = 500
        check_eq("F1: a 500 whose body stalls: liveness `dead` with its code, as before",
                 (env_probe.liveness(stall.url, [], [])["verdict"], env_probe.liveness(stall.url, [], [])["code"]), ("dead", 500))
        check_eq("F1: ... and stand_access._open returns the code with an empty body, as before", stand_access._open(stall.url, "GET", None, {}, 1), (500, ""))
    finally:
        env_probe.HEALTH_TIMEOUT_S = real
        stall.close()


def stand_answers_table() -> None:
    """RH1-7 N1: what an answer MEANS is a row of references/stand-answers.json, read by ONE reader; `liveness` keeps its
    verdict words. K-N1-1 .. K-N1-7."""
    import inspect
    import re
    import socket
    import tempfile
    import types
    import urllib.error

    def answer(code, kind=None):
        return types.SimpleNamespace(status=code, verdict={"kind": kind, "said": "a page titled X"} if kind else {})

    real = env_probe._fetch
    try:
        rows = [("C1", 200, None, "answered", "alive"), ("C1", 204, "ok", "answered", "alive"),
                ("C2", 200, "page", "page", "alive"), ("C3", 302, None, "redirect", "wants_login"),
                ("C4", 401, None, "login_demanded", "wants_login"), ("C4", 403, "service", "login_demanded", "wants_login"),
                ("C5", 401, "intermediary", "login_demanded_unowned", "wants_login"),
                ("C5", 403, "page", "login_demanded_unowned", "wants_login"),
                ("C6f", 404, "page", "path_missing", "dead"), ("C6", 404, None, "path_missing", "dead"),
                ("C7a", 429, "service", "throttled", "dead"), ("C7a", 429, "intermediary", "throttled", "dead"),
                ("C7c", 400, "intermediary", "refuses_unowned", "dead"), ("C7c", 414, "page", "refuses_unowned", "dead"),
                ("C7c", 431, "unclear", "refuses_unowned", "dead"),
                ("C7b", 422, "service", "refuses", "dead"), ("C7b2", 422, "ok", "refuses", "dead"),
                ("C7b2", 405, "empty", "refuses", "dead"), ("C7b2", 409, None, "refuses", "dead"),
                ("C8", 502, None, "upstream_dead", "dead"), ("C8", 504, "empty", "upstream_dead", "dead"),
                ("C9", 500, "service", "app_error", "dead"), ("C9", 500, "ok", "app_error", "dead"),
                ("C9b", 500, "empty", "app_error", "dead"), ("C9b", 500, "page", "app_error", "dead"),
                ("C9b", 500, None, "app_error", "dead"),
                ("C10", 150, None, "unknown_code", "dead"), ("C10", 600, None, "unknown_code", "dead")]
        for row_id, code, kind, means, verdict in rows:
            env_probe._fetch = lambda url, timeout, a=answer(code, kind): a
            got = env_probe.liveness("http://x/y", [], [])
            row = env_probe.answer_meaning(code, kind)
            check_eq(f"K-N1-1 {row_id}: HTTP {code} / kind {kind} -> {means}, {verdict}",
                     (row["id"], got["means"], got["verdict"], got["cause"], got["said_kind"]), (row_id, means, verdict, None, kind))
        # K-N1-3: a code no row covers is never alive; a status that is not an int is the same row
        for code in (150, 600, 0, True, "200", None, 2.5):
            env_probe._fetch = lambda url, timeout, c=code: c
            check_eq(f"K-N1-3 C10: {code!r} is dead, never alive", env_probe.liveness("http://x/y", [], [])["verdict"], "dead")

        # K-N1-2 (the existing pins of the_liveness_rule stay as they were) + the declared code still goes first
        env_probe._fetch = lambda url, timeout: answer(302, "page")
        check_eq("K-N1-2 a declared code is wants_login before any table row", env_probe.liveness("http://x/y", [302], [])["means"],
                 "declared")

        # K-N1-4 / E-F17: the table missing, an empty list, broken JSON
        saved_path = env_probe.STAND_ANSWERS_PATH
        folder = Path(tempfile.mkdtemp(prefix="qa-stand-answers-"))
        try:
            for label, content in (("missing", None), ("a list", "[]"), ("broken", "{ broken"), ("no codes", "{}")):
                target = folder / f"{label.replace(' ', '-')}.json"
                if content is not None:
                    target.write_text(content, encoding="utf-8")
                env_probe.STAND_ANSWERS_PATH = target
                env_probe.reload_stand_answers()
                check_eq(f"K-N1-4 E-F17 ({label}): the reader says unreadable, never raises", env_probe.stand_answers()["table"], "unreadable")
                env_probe._fetch = lambda url, timeout: 302
                check_eq(f"K-N1-4 ({label}): a declared code is still wants_login",
                         env_probe.liveness("http://x/y", [302], [])["verdict"], "wants_login")
                env_probe._fetch = lambda url, timeout: 200
                got = env_probe.liveness("http://x/y", [], [])
                check_eq(f"K-N1-4 ({label}): 200 is dead with means table_unreadable, never alive",
                         (got["verdict"], got["means"]), ("dead", "table_unreadable"))
        finally:
            env_probe.STAND_ANSWERS_PATH = saved_path
            env_probe.reload_stand_answers()
            import shutil
            shutil.rmtree(folder, ignore_errors=True)
        check_eq("K-N1-4 reload_stand_answers() restores the real table", env_probe.stand_answers()["table"], "ok")
        env_probe._fetch = lambda url, timeout: 200
        check_eq("K-N1-4 ... and 200 is alive again", env_probe.liveness("http://x/y", [], [])["verdict"], "alive")

        # K-N1-5 / K-N1-6: what no answer means; one unwrap level AT and BEYOND
        cause = lambda exc: env_probe.no_answer_cause(exc)["cause"]  # noqa: E731
        check_eq("K-N1-5 AT the unwrap level: URLError(ConnectionRefusedError()) -> nothing_listens",
                 cause(urllib.error.URLError(ConnectionRefusedError())), "nothing_listens")
        check_eq("K-N1-5 BEYOND it: URLError(URLError(ConnectionRefusedError())) -> no_answer (N6)",
                 cause(urllib.error.URLError(urllib.error.URLError(ConnectionRefusedError()))), "no_answer")
        check_eq("K-N1-6 URLError(socket.gaierror()) -> name_unresolved",
                 cause(urllib.error.URLError(socket.gaierror())), "name_unresolved")
        check_eq("K-N1-6 OSError(10065, ...) -> unreachable (the OSError fallback, N5)", cause(OSError(10065, "unreachable")), "unreachable")
        check_eq("K-N1-6 the bare exception itself (no wrapper) -> its own row", cause(ConnectionRefusedError()), "nothing_listens")
        check_eq("K-N1-6 TimeoutError -> timeout, a reset -> dropped",
                 (cause(TimeoutError()), cause(ConnectionResetError()), cause(ConnectionAbortedError())),
                 ("timeout", "dropped", "dropped"))
        check_eq("K-N1-6 URLError with a text reason is an OSError: unreachable", cause(urllib.error.URLError("no route")), "unreachable")
        check_eq("K-N1-6 anything else -> no_answer (N6)", cause(RuntimeError("boom")), "no_answer")
        # B2: a subclass takes the row of its most specific listed ancestor; a half-up API is not "host unreachable"
        import http.client
        import ssl

        class MyRefused(ConnectionRefusedError):
            pass

        class Stray(OSError):
            pass
        check_eq("K-N1-6 B2 RemoteDisconnected (wrapped and bare) -> dropped, never unreachable",
                 (cause(urllib.error.URLError(http.client.RemoteDisconnected("closed"))), cause(http.client.RemoteDisconnected("x"))),
                 ("dropped", "dropped"))
        check_eq("K-N1-6 B2 SSLCertVerificationError / SSLError -> tls_refused (wrapped and bare)",
                 (cause(urllib.error.URLError(ssl.SSLCertVerificationError())), cause(ssl.SSLError()),
                  cause(ssl.SSLCertVerificationError())), ("tls_refused",) * 3)
        check_eq("K-N1-6 B2 a user subclass of a listed class takes that row", cause(MyRefused()), "nothing_listens")
        check_eq("K-N1-6 B2 an OSError subclass no row lists stays unreachable (N5), a non-OSError stays N6",
                 (cause(Stray()), cause(KeyError("k"))), ("unreachable", "no_answer"))
        check("K-N1-6 B2 the TLS row says TLS, not the host", "TLS" in env_probe.no_answer_cause(ssl.SSLError())["direct"]["words"]
              and "unreachable" not in env_probe.no_answer_cause(ssl.SSLError())["direct"]["words"])

        def refused(url, timeout):
            raise urllib.error.URLError(ConnectionRefusedError())
        env_probe._fetch = refused
        got = env_probe.liveness("http://x/y", [], [])
        check_eq("K-N1-6 liveness: refused -> dead, cause nothing_listens, the note keeps its words",
                 (got["verdict"], got["cause"], got["means"], "NO ANSWER (URLError)" in got["note"]), ("dead", "nothing_listens", None, True))

        # K-N1-7: no code site compares a status after the change; the control finds the three in today's text
        body = inspect.getsource(env_probe.liveness)
        old_text = "    if 200 <= code < 300:\n    if code == 404:\n    if code in (401, 403):\n"
        pattern = re.compile(r"200 <= code|code == 404|in \(401, 403\)")
        check_eq("K-N1-7 liveness compares no status range, 404 or 401/403", len(pattern.findall(body)), 0)
        check_eq("K-N1-7 negative control: the same pattern over today's function text finds 3", len(pattern.findall(old_text)), 3)
    finally:
        env_probe._fetch = real


def the_token_walk() -> None:
    """EP1-31: `token_value` is the ONE walk of a login answer (top object, then `data`, then `result`; the names in
    TOKEN_FIELDS order), and `_token_in` is its yes/no."""
    cases = [
        ('{"access_token": "a"}', "a"), ('{"accessToken": "b"}', "b"), ('{"token": "c"}', "c"),
        ('{"data": {"token": "d"}}', "d"), ('{"result": {"jwt": "e"}}', "e"), ('{"data": {"access_token": "f"}, "token": "g"}', "g"),
        ('{"token": "  h  "}', "h"), ('{"access_token": "", "data": {"token": "i"}}', "i"),
        ('{"access_token": "j", "token": "k"}', "j"),
        ('{}', None), ('', None), ('{"data": 5}', None), ('{"data": {"x": "y"}}', None), ('[]', None), ('null', None),
        ('not json', None), ('{"data": {"data": {"token": "deep"}}}', None), ('{"token": ""}', None), ('{"token": null}', None),
    ]
    for body, want in cases:
        check_eq(f"token_value {body!r}", stand_access.token_value(body), want)
        check_eq(f"_token_in {body!r} agrees with token_value", stand_access._token_in(body), want is not None)
    check_eq("token_value(None) is None, not an exception", stand_access.token_value(None), None)


def the_login_ceiling() -> None:
    """RN1-3 K-RN3-T1..T7: the ceiling of a harness-command login is twice the recorded duration, inside [60, 300] s."""
    def rec(seconds):
        return {"login_probe": {"seconds": seconds}}
    check_eq("K-RN3-T1: recorded 80 s -> a 160 s ceiling", stand_access.command_timeout(rec(80), 8), 160)
    check_eq("K-RN3-T2: AT the floor (2 x 30 = 60) -> 60", stand_access.command_timeout(rec(30), 8), 60)
    check_eq("K-RN3-T2: BEYOND the floor (29.9) -> 60", stand_access.command_timeout(rec(29.9), 8), 60)
    check_eq("K-RN3-T2: just above the floor (30.5) -> 61", stand_access.command_timeout(rec(30.5), 8), 61)
    bad = [("0", rec(0)), ("-5", rec(-5)), ("'80'", rec("80")), ("True", rec(True)), ("NaN", rec(float("nan"))),
           ("Infinity", rec(float("inf"))), ("absent", {"login_probe": {}}), ("login_probe a string", {"login_probe": "x"}),
           ("empty access", {})]
    for label, access in bad:
        check_eq(f"K-RN3-T3: seconds {label} is no record -> the declared default 300", stand_access.command_timeout(access, 8), 300)
        check_eq(f"K-RN3-T3: seconds {label} -> recorded_seconds is None", stand_access.recorded_seconds(access), None)
    check_eq("K-RN3-T3: access that is not an object -> 300", stand_access.command_timeout(None, 8), 300)
    check_eq("K-RN3-T4: AT the cap (2 x 150 = 300) -> 300", stand_access.command_timeout(rec(150), 8), 300)
    check_eq("K-RN3-T4: BEYOND the cap (150.1) -> 300", stand_access.command_timeout(rec(150.1), 8), 300)
    check_eq("K-RN3-T4: 1000 s -> 300", stand_access.command_timeout(rec(1000), 8), 300)
    check_eq("K-RN3-T5: a caller's timeout above the wanted one is kept", stand_access.command_timeout(rec(10), 90), 90)
    check_eq("K-RN3-T5: ... and the cap binds the caller too", stand_access.command_timeout({}, 999), 300)

    def timed_out(*_a, **_k):
        raise stand_access.subprocess.TimeoutExpired(cmd="npx", timeout=1)
    real_run = stand_access.subprocess.run
    stand_access.subprocess.run = timed_out
    try:
        recorded = stand_access._harness_command({"command": "npx playwright test", "login_probe": {"seconds": 80}}, {}, 8)
        unrecorded = stand_access._harness_command({"command": "npx playwright test"}, {}, 8)
    finally:
        stand_access.subprocess.run = real_run
    check_eq("K-RN3-T6: a timeout stays `failed` and is marked as a timeout (F-5)", (recorded["status"], recorded.get("refusal")),
             ("failed", "timeout"))
    check_in("K-RN3-T6: ... the ceiling is named", "within 160s", recorded["why"])
    check_in("K-RN3-T6: ... and the recorded duration", "~80s", recorded["why"])
    check_in("K-RN3-T6: unrecorded - the declared default is named", "within 300s", unrecorded["why"])
    check_in("K-RN3-T6: ... and where the duration would be recorded", "login_probe.seconds", unrecorded["why"])
    check_not_in("K-RN3-T6: a timeout is no `seconds` source", "seconds", json.dumps({k: v for k, v in recorded.items() if k != "why"}))
    ok_cmd = f'"{sys.executable}" -c "raise SystemExit(0)"'
    done = stand_access.login({"kind": "harness_command", "command": ok_cmd}, {}, timeout=30)
    check("K-RN3-T7: an ok harness login carries its duration", done["status"] == "ok" and isinstance(done.get("seconds"), float)
          and done["seconds"] >= 0, str(done))
    bad_cmd = f'"{sys.executable}" -c "raise SystemExit(3)"'
    failed = stand_access.login({"kind": "harness_command", "command": bad_cmd}, {}, timeout=30)
    check("K-RN3-T7: a failing login carries no duration", failed["status"] == "failed" and "seconds" not in failed, str(failed))


def main() -> None:
    the_token_walk()
    stand_answers_table()
    the_login_kinds()
    the_protection_page()
    the_stalled_body()
    the_liveness_rule()
    the_three_lines()
    the_config_that_fails_its_own_probe()
    the_login_ceiling()
    finish("test_stand_access")


if __name__ == "__main__":
    main()
