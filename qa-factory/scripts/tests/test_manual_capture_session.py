#!/usr/bin/env python3
"""RN1-10 (a): `manual_capture.py --session <actor>`, `sign_in` and `session close` (K-S1 .. K-S8 of the spec t-1700).

The browser is a FAKE with a disk of its own: a `World` keeps the cookie jar of each persistent profile between two "processes"
(a new `SessionBrowser` per call, as the real one is a new Chromium per call), so what is proven here is the factory's part -
one attempt for the calls of a case, one profile per actor, the proof gate A left (`state/sign-in-probe.json`), the page the
last call ended on, the request that carries the profile's cookies, and the profile's deletion. The Playwright primitives
(`launch_persistent_context`, `context.request.fetch`) are proven only by a live run (FR-33).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_manual_capture as T  # noqa: E402  (it installs the TestProject1-form scaffold config)
import scaffold as S  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

MC = S.MC
UI, UI_CASE, LOCAL = T.UI, T.UI_CASE, T.LOCAL
USER, ADMIN = "session-user@example.test", "session-admin@example.test"
ENV_FILE = ("PROJECT_NAME=x\nAUTH_USERNAME=default@example.test\nAUTH_PASSWORD=pw-default\n"
            f"USER_EMAIL={USER}\nUSER_PASSWORD=pw-user\nADMIN_EMAIL={ADMIN}\nADMIN_PASSWORD=pw-admin\n")
VISIT = f"goto {UI}\ncapture pre_action initial\n"
OTHER = "http://localhost:5173/other/page"
VISIT_OTHER = f"goto {UI}\ngoto {OTHER}\ncapture pre_action initial\n"
LATER = f"goto {UI}\ncapture post_action completion\n"


class World:
    """The disk and the clock the fake processes share."""

    def __init__(self):
        self.profiles, self.backends, self.http, self.logins = {}, [], [], []
        self.now, self.lands, self.login_error = 0.0, True, None
        self.clock = S.Clock()


class SessionBrowser(S.FakeBrowser):
    def __init__(self, world):
        super().__init__(login_error=world.login_error)
        self.world, self.page_url, self.jar = world, "about:blank", {}
        world.backends.append(self)

    def monotonic(self):
        return self.world.now

    def pause(self, seconds):
        self.world.now += max(seconds, 1e-6)
        assert self.world.now < 10_000, "the landing loop never ended"

    def open(self, timeout_s, allowed_hosts, local_storage=None, element_wait_s=None, profile_dir=None):
        super().open(timeout_s, allowed_hosts, local_storage, element_wait_s)
        self.profile = str(profile_dir) if profile_dir is not None else None
        if profile_dir is not None:
            Path(profile_dir).mkdir(parents=True, exist_ok=True)
            self.jar = self.world.profiles.setdefault(self.profile, {})

    def login(self, recipe, credentials, frontend_url):
        result = super().login(recipe, credentials, frontend_url)       # raises a scripted login_error
        self.world.logins.append(credentials.username)
        self.page_url = S.HOME_URL if self.world.lands else S.SIGN_IN_URL
        if self.world.lands:
            self.jar[S.SESSION_COOKIE] = credentials.username
        return result

    def goto(self, url):
        self.page_url = url
        return super().goto(url)

    def click(self, selector):
        if selector == "#go":                    # the form's submit in a `fill-account` sign-in
            self.jar[S.SESSION_COOKIE] = "typed-by-the-agent"
            self.page_url = S.HOME_URL
        return super().click(selector)

    def current_url(self):
        return self.page_url

    def page_words(self, mode=None):
        return "Workflow diff page"

    def cookie_names(self):
        return {k for k, v in self.jar.items() if v}

    def field_visible(self, row):
        return not self.cookie_names()

    def http(self, method, url, headers, body, timeout_s):
        self.world.http.append({"url": url, "cookies": dict(self.jar), "headers": dict(headers)})
        return MC.HttpResult(200, [("Content-Type", "application/json")], b'{"ok": true}', 0.01)


def patch(world, http=None):
    MC.BACKEND_FACTORY = lambda: SessionBrowser(world)
    MC.MONOTONIC = lambda: world.now
    MC.HTTP = http
    MC.PROBE = lambda spec: S.probe("api" if spec["argv"] == ["probe-api"] else "e2e-ui")
    MC.NOW = world.clock


def config(**access):
    cfg = T._testproject1_form_config()
    env = cfg["environments"][0]
    env["credentials_by_role"] = {"user": ".env: USER_EMAIL / USER_PASSWORD - a user",
                                  "admin": ".env: ADMIN_EMAIL / ADMIN_PASSWORD - the admin"}
    if access:
        cfg["environment"]["access"] = access
    return cfg


def task(cfg=None, probed=("user", "admin")):
    t = S.make_task(cfg=cfg or config())
    (t.project / "harness" / ".env").write_text(ENV_FILE, encoding="utf-8")
    for actor in probed:
        prove(t, actor)
    return t


def prove(t, actor, outcome="ok", recipe_sha=None):
    """What gate A (B2) leaves: the row of one actor in `state/sign-in-probe.json`."""
    path = t.task / "state" / "sign-in-probe.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    sha = recipe_sha or MC.recipe_sha(MC.login_recipe(t.cfg, MC.spec(), "ui"))
    rows[actor] = {"outcome": outcome, "method": "ui_recipe", "recipe_sha": sha, "at": "2026-11-03T10:00:00+00:00"}
    path.write_text(json.dumps(rows), encoding="utf-8")


def ui(t, world, steps, actor="user", *extra, case=UI_CASE):
    patch(world)
    steps_file = t.task / "steps.txt"
    steps_file.write_text(steps, encoding="utf-8")
    return S.run(["ui", "--task-root", str(t.task), "--case", case, "--steps-file", str(steps_file), "--session", actor, *extra])


def http(t, world, actor="user", *extra, fake=None, case=UI_CASE):
    patch(world, fake)
    return S.run(["http", "--task-root", str(t.task), "--case", case, "--method", "GET", "--url", LOCAL + "/v1/x",
                  "--session", actor, "--profile", "e2e-ui", *extra])


def close(t, *extra, case=UI_CASE):
    return S.run(["session", "close", "--task-root", str(t.task), "--case", case, *extra])


def attempt_dir(t, name="a1", case=UI_CASE):
    return MC.case_root(t.task, case) / name


def out_json(out):
    return T.stdout_json(out)


# --------------------------------------------------------------------------------------------

def k_s1_one_attempt_one_profile_and_the_last_page():
    world, t = World(), task()
    code1, out1, err1 = ui(t, world, VISIT_OTHER)
    code2, out2, err2 = ui(t, world, LATER)
    check_eq("K-S1: both calls ran (exit 0)", (code1, code2), (0, 0))
    check_eq("K-S1: ONE attempt for the two calls", MC.attempts_of(MC.case_root(t.task, UI_CASE)), ["a1"])
    paths = [c["path"] for c in T.jsonl(attempt_dir(t) / "captures.jsonl")]
    check("K-S1: two evidence files, two ids", len(paths) == 2 and len(set(paths)) == 2, str(paths))
    check_eq("K-S1: one profile on disk", len(world.profiles), 1)
    check_eq("K-S1: the account signed in once, the second call reused the profile", world.logins, [USER])
    check_eq("K-S1: the second call began on the page the first one ended on (before its own goto)",
             world.backends[1].calls[:2], [("goto", OTHER), ("goto", UI)])
    check_eq("K-S1: the summary names the session", out_json(out2).get("session"), {"actor": "user", "signed_in": True})
    resume = [r for r in T.jsonl(attempt_dir(t) / "steps.jsonl") if r["step"].startswith("resume session")]
    check_eq("K-S1: the resume is a step of the record, said", len(resume), 1)
    state = json.loads((attempt_dir(t) / "sessions" / "user" / "state.json").read_text(encoding="utf-8"))
    check_not_in("K-S1: state.json holds no cookie value", USER, json.dumps(state))
    check_not_in("K-S1: and no password", "pw-user", json.dumps(state) + err1 + err2)
    S.cleanup(t)


def k_s2_two_actors_two_profiles():
    world, t = World(), task()
    ui(t, world, VISIT, "user")
    ui(t, world, VISIT, "admin")
    check_eq("K-S2: one attempt, two session folders", sorted(p.name for p in (attempt_dir(t) / "sessions").iterdir()),
             ["admin", "user"])
    jars = {Path(k).parent.name: v for k, v in world.profiles.items()}
    check_eq("K-S2: the user's cookie is the user's", jars["user"].get(S.SESSION_COOKIE), USER)
    check_eq("K-S2: the admin's cookie is the admin's, not mixed", jars["admin"].get(S.SESSION_COOKIE), ADMIN)
    check_eq("K-S2: two sign-ins, one per actor", world.logins, [USER, ADMIN])
    check_eq("K-S2: slugs are plain and distinct", (MC.actor_slug("user"), MC.actor_slug("User") != MC.actor_slug("user")),
             ("user", True))
    S.cleanup(t)


def k_s3_http_carries_the_profiles_cookies():
    world, t = World(), task()
    ui(t, world, VISIT)
    calls, original = [], MC.http_login_source
    MC.http_login_source = lambda *a, **k: calls.append(a) or original(*a, **k)
    fake = S.FakeHttp()
    try:
        code, out, err = http(t, world, "user", fake=fake)
    finally:
        MC.http_login_source = original
    sent = world.http[0] if world.http else {"cookies": {}, "headers": {"?": "no request"}}
    check_eq("K-S3: the request ran (exit 0)", code, 0)
    check_eq("K-S3: it carried the profile's cookie", sent["cookies"].get(S.SESSION_COOKIE), USER)
    check("K-S3: and no Authorization header", not any(k.lower() == "authorization" for k in sent["headers"]), str(sent))
    check_eq("K-S3: `http_login_source` was not called", calls, [])
    check_eq("K-S3: the factory's own HTTP client sent nothing", fake.calls, [])
    check_eq("K-S3: it joined the open attempt and the session", out_json(out).get("session"),
             {"actor": "user", "signed_in": True})
    S.cleanup(t)


def k_s4_no_known_http_sign_in_is_not_a_user_block():
    harness_command = config(kind="harness_command", command="npx playwright test tests/e2e/auth/login.spec.ts")
    world, t = World(), task(harness_command)
    code, out, err = http(t, world, "user")
    check_eq("K-S4: harness_command + proof `ok`: the request ran", code, 0)
    check("K-S4: no env_blocked.json", not (attempt_dir(t) / "env_blocked.json").exists())
    code, out, err = ui(t, world, VISIT, "admin")
    check_eq("K-S4: the ui call of a proved actor runs too", code, 0)
    # the refusals: nothing was opened, so no attempt folder exists for the case
    for label, build in (("no row", lambda t: None),
                         ("outcome failed", lambda t: prove(t, "user", "failed")),
                         ("another recipe's proof", lambda t: prove(t, "user", "ok", "0" * 64))):
        world2, t2 = World(), task(harness_command, probed=())
        build(t2)
        code, out, err = http(t2, world2, "user")
        check_eq(f"K-S4 [{label}]: refused (exit 2)", code, 2)
        check_in(f"K-S4 [{label}]: the refusal says the sign-in was not proved", "was not proved by the stand probe", err)
        check_in(f"K-S4 [{label}]: and gives the door", "gate_preflight.py --task", err)
        check(f"K-S4 [{label}]: nothing was opened (no attempt folder, no backend)",
              not MC.case_root(t2.task, UI_CASE).exists() and not world2.backends)
        S.cleanup(t2)
    world3, t3 = World(), task(probed=())
    (t3.task / "state" / "sign-in-probe.json").write_text("{broken", encoding="utf-8")
    code, out, err = ui(t3, world3, VISIT, "user")
    check_eq("K-S4: an unreadable proof file is no proof (exit 2)", code, 2)
    check_in("K-S4: and the refusal says unreadable, not `no row`", "unreadable", err)
    code, out, err = ui(t3, world3, "goto " + UI + '\nfill-account "#u" user user\nfill-account "#p" user secret\nclick "#go"\n')
    check_eq("K-S4: steps that sign in by `fill-account` need no proof", code, 0)
    check("K-S4: and the sign-in the agent made is recorded for the next call",
          json.loads((attempt_dir(t3) / "sessions" / "user" / "state.json").read_text(encoding="utf-8")).get("signed_in"))
    # K-S4b (t-1747 F1): the form sign-in is the proof of the next calls - no probe row, no second login
    code, out, err = ui(t3, world3, VISIT, "user")
    check_eq("K-S4b: a plain `ui --session` after a fill-account sign-in is accepted (exit 0)", code, 0)
    code, out, err = http(t3, world3, "user")
    check_eq("K-S4b: and so is `http --session --profile` (exit 2 before the fix)", code, 0)
    code, out, err = ui(t3, world3, VISIT, "other")
    check_eq("K-S4b BEYOND: another actor has no sign-in and is still refused (exit 2)", code, 2)
    code, out, err = ui(t3, world3, VISIT, "user", "--as", "default")
    check_eq("K-S4: --session with --as is refused (exit 2)", code, 2)
    check_in("K-S4: and says to leave --as out", "Leave `--as` out", err)
    for each in (t, t3):
        S.cleanup(each)


class Loc:
    def __init__(self, page, key):
        self.page, self.key = page, key

    def is_visible(self):
        return True

    def click(self):
        self.page.calls.append(("click", self.key))

    def fill(self, value):
        self.page.calls.append(("fill", self.key, value))


class Page:
    def __init__(self):
        self.calls = []

    def goto(self, url, timeout=None):
        self.calls.append(("goto", url))

    def wait_for_load_state(self, *a, **k):
        pass

    def get_by_text(self, text):
        return Loc(self, ("text", text))

    def get_by_role(self, role, name=None):
        return Loc(self, ("role", role, name))

    def get_by_test_id(self, test_id):
        return Loc(self, ("test_id", test_id))


def k_s5_a_field_row_is_a_test_id_or_a_role():
    backend = MC.PlaywrightBackend.__new__(MC.PlaywrightBackend)        # no Playwright needed: only the page's locators matter
    backend._page, backend._limit_ms, backend._Timeout, backend._Error = Page(), 1000, TimeoutError, OSError
    recipe = {"path": "/", "expand": {"test_id": "nav-login-button"}, "username": {"test_id": "login-email-input"},
              "password": {"test_id": "login-password-input"}, "submit": {"role": "button", "name": "Sign in"}}
    backend.login(recipe, MC.Credentials("u@x", "pw"), "http://localhost:5173")
    calls = backend._page.calls
    check("K-S5: the opener is found by test id", ("click", ("test_id", "nav-login-button")) in calls, str(calls))
    check("K-S5: the user field by test id", ("fill", ("test_id", "login-email-input"), "u@x") in calls, str(calls))
    check("K-S5: the password field by test id", ("fill", ("test_id", "login-password-input"), "pw") in calls, str(calls))
    check("K-S5: a role row still goes by role", ("click", ("role", "button", "Sign in")) in calls, str(calls))
    for label, bad in (("a row with neither", {"username": {"name": "Email"}}),
                       ("a row that is a string", {"submit": "go"}),
                       ("an empty test id", {"password": {"test_id": " "}})):
        t = S.make_task(cfg=S.config(manual_capture={"login": {"ui": T.ui_recipe(**bad)}}))
        code, out, err = T.ui_run(t, steps=T.STEPS_GOTO, browser=S.FakeBrowser())[:3]
        key = next(iter(bad))
        check_eq(f"K-S5 [{label}]: refused (exit 2)", code, 2)
        check_in(f"K-S5 [{label}]: the key is named", f"manual_capture.login.ui.{key}", err)
        check(f"K-S5 [{label}]: no attempt folder", not MC.case_root(t.task, UI_CASE).exists())
        S.cleanup(t)


def k_s6_session_close_deletes_the_profile_and_build_follows():
    world, t = World(), task()
    code, out, err = ui(t, world, T.UI_STEPS)
    profile = attempt_dir(t) / "sessions" / "user" / "profile"
    check("K-S6: the profile is on disk after the call", profile.is_dir())
    code, out, err = close(t)
    check_eq("K-S6: session close ran (exit 0)", code, 0)
    check_eq("K-S6: it names who it closed", out_json(out).get("closed"), ["user"])
    check("K-S6: the profile (the cookies) is gone", not profile.exists())
    state = json.loads((attempt_dir(t) / "sessions" / "user" / "state.json").read_text(encoding="utf-8"))
    check_eq("K-S6: state.json stays, with the sign-in marked closed", (state["signed_in"], state["last_url"]), (False, ""))
    check("K-S6: the closing is a line of steps.jsonl",
          any(r["command"] == "session" and r["step"] == "session close user" for r in T.jsonl(attempt_dir(t) / "steps.jsonl")))
    T.seed_runtime_records(t)
    bcode, bout, berr = T.build(t, UI_CASE, "--result", "pass", "--actual", "the scale grew", "--masked")
    check_eq("K-S6: `build` after the close builds the record", bcode, 0)
    check_eq("K-S6: nothing left to close is a refusal", close(t, "--attempt", "a9")[0], 2)
    t2 = task(probed=())
    check_eq("K-S6: a case with no session has nothing to close (exit 2)", close(t2)[0], 2)
    for each in (t, t2):
        S.cleanup(each)


def k_s7_a_proved_sign_in_that_no_longer_lands_is_the_stands():
    world, t = World(), task()
    world.lands = False
    code, out, err = ui(t, world, VISIT)
    row = (json.loads((attempt_dir(t) / "env_blocked.json").read_text(encoding="utf-8"))
           if (attempt_dir(t) / "env_blocked.json").is_file() else {})
    check_eq("K-S7: exit 3 (env_blocked)", code, 3)
    check_eq("K-S7: owner `environment`, cause `stand`, not retried", (row.get("owner"), row.get("cause"), row.get("do_not_retry")),
             ("environment", "stand", True))
    check("K-S7: and never `user`", row.get("owner") != "user")
    check_not_in("K-S7: the account is not in the line", "pw-user", json.dumps(row) + err)
    S.cleanup(t)
    world2, t2 = World(), task()
    world2.login_error = MC.StepFailed("no element matches the sign-in field")
    code, out, err = ui(t2, world2, VISIT)
    row = json.loads((attempt_dir(t2) / "env_blocked.json").read_text(encoding="utf-8"))
    check_eq("K-S7 control: a recipe that does not fit the page stays the factory's", (code, row.get("owner"), "cause" in row),
             (3, "factory", False))
    S.cleanup(t2)


def k_s8_http_without_session_is_as_it_was():
    cfg = T._testproject1_form_config()
    login = LOCAL + "/v1/local-auth/login"
    cfg["environment"]["access"] = {"kind": "local_login", "url": login}
    t = S.make_task(cfg=cfg)
    fake = S.FakeHttp({("POST", login): S.ok_json({"access_token": "TKN-1"}), ("GET", LOCAL + "/v1/x"): S.ok_json({"a": 1})})
    code, out, err = T.http_run(t, fake, "--method", "GET", "--url", LOCAL + "/v1/x")
    sent = fake.calls[-1][2] if fake.calls else {}
    check_eq("K-S8: exit 0", code, 0)
    check_eq("K-S8: the Bearer token of the factory's login is sent", sent.get("Authorization"), "Bearer TKN-1")
    check_not_in("K-S8: and the summary has no session", "session", json.dumps(out_json(out)))
    S.cleanup(t)


def e4_e5_the_last_page_and_the_observation_limit():
    world, t = World(), task()
    steps = VISIT + "".join("wait 1\n" for _ in range(41))
    code, out, err = ui(t, world, steps)
    rows = out_json(out).get("steps") or []
    check_eq("E5: the 40 observed steps carry a screenshot key (per call)", sum("screenshot" in r for r in rows), 40)
    check("E5: the one beyond them does not", rows and "screenshot" not in rows[-1], str(rows[-1:]))
    path = attempt_dir(t) / "sessions" / "user" / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["last_url"] = "http://evil.example.test/steal"
    path.write_text(json.dumps(state), encoding="utf-8")
    code, out, err = ui(t, world, VISIT)
    first = world.backends[-1].calls[0]
    check_eq("E4: a last page off the stand is never opened: the stand's address is", (first[0], first[1].startswith("http://localhost:5173")),
             ("goto", True))
    check_in("E4: and the limitation says so", "not on a stand host", " ".join(out_json(out).get("limitations") or []))
    S.cleanup(t)


def observe_text_is_kept_in_steps_jsonl():
    world, t = World(), task()
    code, out, err = ui(t, world, VISIT)
    rows = T.jsonl(attempt_dir(t) / "steps.jsonl")
    shown = {r["step"]: r.get("text") for r in out_json(out)["steps"]}
    kept = [r for r in rows if r["command"] == "ui" and r["step"].startswith("goto")]
    check("F7: steps.jsonl is never rewritten: no line carries `observe_text` (an append-only carrier)",
          not any("observe_text" in r for r in rows), str(rows))
    excerpt = attempt_dir(t) / MC.OBSERVE_DIR / f"{rows.index(kept[0]) + 1:03d}-excerpt.txt"
    check("F7: the excerpt the summary shows is in observe/<line>-excerpt.txt next to the picture", kept and shown.get(kept[0]["step"])
          and excerpt.is_file() and excerpt.read_text(encoding="utf-8") == shown[kept[0]["step"]], str(excerpt))
    import manual_evidence as ME
    check_eq("F7: the reader of a quote finds it there", ME._observe_text(t.task, {"case": UI_CASE, "attempt_id": "a1"},
                                                                          rows.index(kept[0]) + 1), shown[kept[0]["step"]])
    check_eq("F7 BEYOND: a step with no excerpt has no file and reads as empty",
             ME._observe_text(t.task, {"case": UI_CASE, "attempt_id": "a1"}, 99), "")
    # the lines are exactly what `Attempt.step` appended: appending a later step leaves every earlier byte as it was
    before = (attempt_dir(t) / "steps.jsonl").read_bytes()
    ui(t, world, VISIT)
    check("F7: a later call only appends to steps.jsonl", (attempt_dir(t, "a2") / "steps.jsonl").is_file() or
          (attempt_dir(t) / "steps.jsonl").read_bytes().startswith(before))
    S.cleanup(t)


def main():
    observe_text_is_kept_in_steps_jsonl()
    k_s1_one_attempt_one_profile_and_the_last_page()
    k_s2_two_actors_two_profiles()
    k_s3_http_carries_the_profiles_cookies()
    k_s4_no_known_http_sign_in_is_not_a_user_block()
    k_s5_a_field_row_is_a_test_id_or_a_role()
    k_s6_session_close_deletes_the_profile_and_build_follows()
    k_s7_a_proved_sign_in_that_no_longer_lands_is_the_stands()
    k_s8_http_without_session_is_as_it_was()
    e4_e5_the_last_page_and_the_observation_limit()
    finish("test_manual_capture_session")


if __name__ == "__main__":
    main()
