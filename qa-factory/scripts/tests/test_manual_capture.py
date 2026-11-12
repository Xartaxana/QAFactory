#!/usr/bin/env python3
"""t-250 B2: `manual_capture.py` and the record `manual_evidence.py build` makes from its files.

The browser and the HTTP client are FAKES (scaffold.FakeBrowser / FakeHttp): nothing here launches Chromium,
starts a process or opens a socket. What is real is everything the factory owns - the host allow-list, the
timeout, the 2 MB cap, the redaction, the secret scan, the hashes, the captures.jsonl the record is built
from, `validate_record` and the controller-side `validate_manual_current` (on a task folder shaped like
cmp2's TP1-15045, cases TC_007 and TC_012 copied from it).

K3 (spec t-250): a fake `ui` run + `build --result pass` gives a record `validate` accepts, with
pre_action / post_action and `before_change.source: not_recorded` for R-7; the t-245 claim fixture (R-17)
gives `claim` with a `base:` reference. Controls: a tampered file is "evidence hash mismatch"; a
pre_action-only attempt cannot be a pass but can be inconclusive; `--phase before` is refused; a legacy
record written with before/after still validates.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

MC = S.MC
import manual_evidence as M  # noqa: E402

# EP1-28: a capture's profile is the PROJECT's own (`capture_profile`), no longer the literals `e2e-ui` and `api`. The shared
# scaffold's default config names one profile (`e2e-ui`) but registers probes for two, which is neither a TestProject1-form
# project (`api` + `e2e-ui` profiles) nor a one-profile one. Every importer of this file gets the Test Project 1 form: the second
# profile is added unless a test passes its own `profiles`. The scaffold file itself belongs to other nodes.
_SCAFFOLD_CONFIG = S.config


def _testproject1_form_config(**over):
    cfg = _SCAFFOLD_CONFIG(**over)
    if "profiles" not in over:
        cfg["profiles"] = [*cfg["profiles"], {"profile_id": "api", "commands": {
            "one_test": {"argv": ["poetry", "run", "pytest", "<test-file>"], "cwd": "."}}}]
    return cfg


S.config = _testproject1_form_config

UI = "http://localhost:5173/workflows/w1/diff"
VIEWPORT = ".react-flow__viewport"
UI_STEPS = f"""# TC_007: zoom, then drag, reading the viewport transform
goto {UI}
capture pre_action initial
click "button[aria-label='Zoom in']"
read {VIEWPORT} style=transform
drag ".react-flow__pane" 40 -25
capture post_action completion
"""
UI_CASE, API_CASE = S.CASES["ui"], S.CASES["api"]
LOCAL = "http://localhost:8080"


def patch_backends(browser=None, http=None, probes=None):
    MC.BACKEND_FACTORY = (lambda: browser) if browser is not None else None
    # the landing loop runs on the fake's own clock (it moves only when the loop pauses): a 100 s limit costs no time
    MC.MONOTONIC = browser.monotonic if browser is not None and hasattr(browser, "monotonic") else None
    MC.HTTP = http
    MC.PROBE = probes or (lambda spec: S.probe("api" if spec["argv"] == ["probe-api"] else "e2e-ui"))
    MC.NOW = S.Clock()


def ui_run(t, steps=UI_STEPS, browser=None, extra=(), case=UI_CASE):
    steps_file = t.task / "steps.txt"
    steps_file.write_text(steps, encoding="utf-8")
    browser = browser or S.FakeBrowser()
    patch_backends(browser)
    code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", case, "--steps-file", str(steps_file), *extra])
    return code, out, err, browser


def http_run(t, http, *args, case=API_CASE):
    patch_backends(http=http)
    return S.run(["http", "--task-root", str(t.task), "--case", case, *args])


OBLIGATIONS = {UI_CASE: ["OB-7"], API_CASE: ["OB-12"]}


AUTO_THEN_FLAGS = True     # test_manual_rejudge.py sets it False: the quote rule IS what that file tests


def then_flags(task, case, args):
    """HF8-19: the Then quotes a pass or a fail stands on, as the runner would give them, for the attempt `args` build.
    A Then is `--then-seen` when the attempt has a picture of the page after the action (a UI attempt), else
    `--then-quote` of the first words of its first text capture (an API attempt). Nothing when the attempt shows neither
    (the build then refuses for the reason the test is about); the case has no Then: nothing to quote."""
    try:
        thens = json.loads((MC.case_root(task, case) / "request.json").read_text(encoding="utf-8")).get("thens") or {}
        root = MC.case_root(task, case)
        names = MC.attempts_of(root)
        name = args[list(args).index("--attempt") + 1] if "--attempt" in args else (names[-1] if names else "")
        captures = M._attempt_files(root / name, name, case)[0]
        refs = M._evidence_refs(captures)
    except Exception:
        return []
    if not thens:
        return []
    if any(r.get("kind") == "image" and M.PHASE_ALIAS.get(r.get("phase"), r.get("phase")) == "after" for r in refs):
        return [x for n in sorted(thens, key=int) for x in ("--then-seen", f"{n}=the page after the action shows it")]
    for ref in refs:
        for view in M._text_views(task, ref):
            words = M._squash(view)[:40].strip()
            if words:
                return [x for n in sorted(thens, key=int) for x in ("--then-quote", f"{n}={words}")]
    return []


def build(t, case, *args, command="manual_evidence.py build"):
    """`manual_evidence.py build` as the runner calls it; the orchestrator's `prepare` has run before the
    dispatch, so the request is made here when the case has none yet. A pass or a fail with no `--then-*` flag of its
    own gets one quote per Then (`then_flags`): the quote rule is not what these tests are about."""
    with t.patched():
        if case in OBLIGATIONS and not (MC.case_root(t.task, case) / "request.json").exists():
            M.prepare_to_file(t.task, case, OBLIGATIONS[case])
        if AUTO_THEN_FLAGS and "--result" in args and args[list(args).index("--result") + 1] in ("pass", "fail") \
                and not any(str(a).startswith("--then-") for a in args):
            args = (*args, *then_flags(t.task, case, args))
        return S.run(["build", "--task-root", str(t.task), "--case", case, *args], main=M.main, command=command)


def jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def refused(label, argv, needle):
    code, out, err = S.run(argv)
    check_eq(f"{label}: refused (exit 2)", code, 2)
    check_in(f"{label}: and the refusal says {needle!r}", needle, err)
    return err


# --------------------------------------------------------------------------------------------

def case_ids_and_hosts():
    check_eq("case id `area/TC` is the directory `area__TC`", MC.case_dir_name("area/TP1-1_TC_001"),
             "area__TP1-1_TC_001")
    check_eq("a plain id is itself", MC.case_dir_name(UI_CASE), UI_CASE)
    for bad in ("", "  ", "..", "../x", "a/../b", "/abs", "\\abs", "C:\\x", "a//b", "a__b", ".hidden", "x.", "a b"):
        try:
            MC.case_dir_name(bad)
            check(f"case id {bad!r} is refused", False)
        except ValueError as exc:
            check(f"case id {bad!r} is refused, with what is expected", "Expected the case id" in str(exc), str(exc))
    cfg = S.config()
    allowed = ["http://localhost:8080/v1/x", "http://localhost:5173/", "HTTP://LOCALHOST:8080/", "https://stand.example.test/a"]
    for url in allowed:
        check(f"{url} is on a configured stand", MC.environment_of(url, cfg) is not None)
    for url in ("http://evil.example.test/", "http://localhost:9999/", "http://localhost:8080@evil.example.test/",
                "http://localhost.evil.example.test:8080/", "ftp://localhost:8080/", "file:///etc/passwd", "localhost:8080",
                "http://[::1]:8080/", "", "https://stand.example.test:444/"):
        try:
            MC.environment_of(url, cfg)
            check(f"{url!r} is outside the stands (host allow-list)", False)
        except ValueError as exc:
            check(f"{url!r} is refused naming the allowed hosts", "Allowed hosts: " in str(exc) and "localhost:8080" in str(exc),
                  str(exc))
    try:
        MC.environment_of("http://localhost:8080/", {"environments": []})
        check("no environments[] is refused", False)
    except ValueError as exc:
        check_in("no environments[] is refused, naming the key", "environments[]", str(exc))


def timeouts():
    env = {"measured": {"e2e_page_load_s": {"value": 70}}}
    check_eq("timeout = measured page load + 30 s", MC.timeout_for(env), 100)
    check_eq("a bare number is read too", MC.timeout_for({"measured": {"e2e_page_load_s": 12.5}}), 42.5)
    for label, value in (("absent", {}), ("zero", {"measured": {"e2e_page_load_s": {"value": 0}}}),
                         ("negative", {"measured": {"e2e_page_load_s": {"value": -5}}}),
                         ("a string", {"measured": {"e2e_page_load_s": {"value": "70"}}}),
                         ("a bool", {"measured": {"e2e_page_load_s": {"value": True}}}),
                         ("NaN", {"measured": {"e2e_page_load_s": {"value": float("nan")}}}),
                         ("infinite", {"measured": {"e2e_page_load_s": {"value": float("inf")}}}),
                         ("not an object", {"measured": "70"})):
        check_eq(f"timeout when the measured load is {label}: 180 s", MC.timeout_for(value), 180)


def ui_happy_path():
    t = S.make_task()
    try:
        accented = "caf\u00e9"
        code, out, err, browser = ui_run(t, steps=UI_STEPS + f"capture supporting {accented}\n",
                                         browser=S.FakeBrowser(reads={(VIEWPORT, "style=transform"): "matrix(1.2, 0, 0, 1.2, 10, 20) \u00e9\u4e2d"}))
        check_eq("ui: every step ran (exit 0)", code, 0)
        check("ui: stdout is ONE JSON object, ASCII-escaped", out.strip().startswith("{") and out.isascii() and json.loads(out), out[:200])
        summary = json.loads(out)
        check_eq("ui: attempt a1 of the case", (summary["case"], summary["attempt"]), (UI_CASE, "a1"))
        check_eq("ui: the browser opened with the measured limit (70 + 30) on the stand's hosts",
                 (browser.opened[0], ("http", "localhost", 5173) in [tuple(h) for h in browser.opened[1]]), (100, True))
        check_eq("ui: logged in by code, with the .env values the browser was handed",
                 browser.credentials_seen, (S.USER, S.PASSWORD))
        check("ui: the browser was closed", browser.closed)
        folder = t.attempt_dir(UI_CASE)
        captures = jsonl(folder / "captures.jsonl")
        check_eq("ui: captures are the screenshots and the read value, in the order they were taken",
                 [(c["kind"], c["phase"], c["proves"]) for c in captures],
                 [("image", "pre_action", ["initial"]), ("log", "supporting", [f"read {VIEWPORT} style=transform"]),
                  ("image", "post_action", ["completion"]), ("image", "supporting", [accented])])
        check("ui: every capture is hashed over the stored bytes",
              all(S.sha(t.task / c["path"]) == c["content_hash"] for c in captures))
        check("ui: paths are task-relative under work/evidence/manual/<case>/<attempt>/",
              all(c["path"].startswith(f"work/evidence/manual/{UI_CASE}/a1/") for c in captures), str(captures))
        read_file = t.task / captures[1]["path"]
        check_eq("ui: non-ASCII DOM text is stored as UTF-8", read_file.read_bytes().decode("utf-8"),
                 "matrix(1.2, 0, 0, 1.2, 10, 20) \u00e9\u4e2d")
        check_in("ui: stdout carries a non-ASCII label ASCII-escaped, never as raw bytes", "caf\\u00e9", out)
        check_in("ui: while captures.jsonl keeps it as UTF-8", accented, (folder / "captures.jsonl").read_text(encoding="utf-8"))
        steps = jsonl(folder / "steps.jsonl")
        check_eq("ui: one step line per step, plus the login", [s["outcome"] for s in steps], ["ok"] * 8)
        check_eq("ui: the first line is the login by code", steps[0]["step"], "login by code")
        probes = jsonl(folder / "probes.jsonl")
        check_eq("ui: the stand was probed at the start and at the end (profile e2e-ui)",
                 [(p["when"], p["profile"], p["probe"]["result"]) for p in probes],
                 [("start", "e2e-ui", "matched"), ("end", "e2e-ui", "matched")])
        leak = S.tree_text(t.task)
        check_not_in("ui: the password is in no saved byte", S.PASSWORD, leak)
        check_not_in("ui: nor on stdout or stderr", S.PASSWORD, out + err)
        # --- a second `ui` call is a NEW attempt: a rerun never mixes its captures with the first session's
        code, out, err, _ = ui_run(t)
        check_eq("ui: a second call without --attempt starts a1 -> a2", json.loads(out)["attempt"], "a2")
    finally:
        S.cleanup(t)


def ui_failures():
    t = S.make_task()
    try:
        code, out, err, browser = ui_run(t, browser=S.FakeBrowser(missing={"button#gone"}),
                                         steps=f"goto {UI}\nclick button#gone\ncapture post_action completion\n")
        summary = json.loads(out)
        check_eq("selector not found: exit 1 and the step is named", (code, summary["failed"]["outcome"], summary["failed"]["step"]),
                 (1, "failed", "click button#gone"))
        check_eq("selector not found: a `supporting` image of what was on screen, and nothing after it",
                 [(c["kind"], c["phase"]) for c in summary["captures"]], [("image", "supporting")])
        check_in("selector not found: the capture says which step failed", "failed step: click button#gone",
                 summary["captures"][0]["proves"][0])
        check_eq("selector not found: the remaining steps were NOT executed (a failed step stops the case)",
                 [s["outcome"] for s in summary["steps"]], ["ok", "ok", "failed"])
        check("selector not found: the stand was still probed at the end", "end" in
              [p["when"] for p in jsonl(t.attempt_dir(UI_CASE) / "probes.jsonl")])
        # -- the limit: AT passes, BEYOND is a timeout with a log ref and NO image
        for label, seconds, expect in (("AT the limit", 100, "ok"), ("just beyond the limit", 100.001, "timeout")):
            fresh = S.make_task()
            try:
                code, out, err, _ = ui_run(fresh, steps=f"goto {UI}\ncapture post_action completion\n",
                                           browser=S.FakeBrowser(elapsed={"goto": seconds}))
                summary = json.loads(out)
                kinds = [(c["kind"], c["phase"], c["proves"]) for c in summary["captures"]]
                if expect == "ok":
                    check_eq(f"timeout {label}: passes - the step is ok and the screenshot is taken",
                             (code, [s["outcome"] for s in summary["steps"]], [k[0] for k in kinds]),
                             (0, ["ok", "ok", "ok"], ["image"]))
                else:
                    check_eq(f"timeout {label}: a timeout line and a `timeout` log ref, and NO image",
                             (code, (summary["failed"] or {}).get("outcome"), kinds), (1, "timeout", [("log", "supporting", ["timeout"])]))
                    check_in(f"timeout {label}: the detail names the elapsed time and the limit", "the limit is 100 s",
                             (summary["failed"] or {}).get("detail", ""))
                    log = next(((fresh.task / c["path"]).read_text(encoding="utf-8") for c in summary["captures"]
                                if c["kind"] == "log"), "")
                    check_in(f"timeout {label}: the log file says the limit", "limit_s: 100", log)
            finally:
                S.cleanup(fresh)
        # a wait longer than the limit is a timeout without waiting (AT: a wait of exactly 100 s passes)
        fresh = S.make_task()
        try:
            code, out, _, browser = ui_run(fresh, steps=f"goto {UI}\nwait 100000\n")
            check_eq("wait 100000 ms with a 100 s limit is AT the limit: it runs", (code, ("wait_ms", 100000) in browser.calls), (0, True))
            code, out, _, browser = ui_run(fresh, steps=f"goto {UI}\nwait 100001\n")
            check_eq("wait 100001 ms is BEYOND: a timeout, and the browser never waited",
                     (code, json.loads(out)["failed"]["outcome"], ("wait_ms", 100001) in browser.calls), (1, "timeout", False))
        finally:
            S.cleanup(fresh)
    finally:
        S.cleanup(t)


def ui_refusals():
    t = S.make_task()
    try:
        base = ["ui", "--task-root", str(t.task), "--case", UI_CASE]
        steps = t.task / "steps.txt"
        patch_backends(S.FakeBrowser())

        def steps_refusal(label, text, needle):
            steps.write_text(text, encoding="utf-8")
            return refused(label, [*base, "--steps-file", str(steps)], needle)
        err = steps_refusal("unknown step", f"goto {UI}\nhover button\n", "unknown step 'hover'")
        check_in("unknown step: the refusal names the closed list", "capture <pre_action|post_action|supporting> [label]", err)
        err = steps_refusal("phase `before`", f"goto {UI}\ncapture before\n", "pre_action | post_action | supporting")
        check_in("phase `before`: and says what the old words became", "use pre_action and post_action", err)
        steps_refusal("an unknown phase", f"goto {UI}\ncapture middle\n", "capture phase 'middle'")
        steps_refusal("wrong arity", f"goto {UI}\nclick\n", "`click` takes <selector>")
        steps_refusal("drag with a word for a distance", f"goto {UI}\ndrag .pane left 3\n", "dx and dy whole numbers")
        steps_refusal("read with an unknown mode", f"goto {UI}\nread .a colour\n", "`read` takes")
        steps_refusal("an unbalanced quote", f"goto {UI}\nfill \"input a\n", "line 2")
        steps_refusal("an empty steps file", "", "holds no steps")
        steps_refusal("comments and blanks only", "# nothing\n\n   \n", "holds no steps")
        steps_refusal("no goto at all", "capture pre_action\n", "needs a `goto <url>` step")
        err = steps_refusal("a goto outside the stands", "goto http://evil.example.test/x\n", "Allowed hosts: ")
        check_in("a goto outside the stands: names the configured ones", "localhost:5173", err)
        steps_refusal("a goto with a user:password part", "goto http://localhost:5173@evil.example.test/\n", "Allowed hosts: ")
        steps_refusal("a credential typed into a fill", f"goto {UI}\nfill input 'password: \"abcdefgh12345678\"'\n",
                      "secret_content_patterns[1]")
        err = refused("a missing steps file", [*base, "--steps-file", str(t.task / "nope.txt")], "does not exist")
        (t.task / "latin1.txt").write_bytes(b"goto \xff\n")
        refused("a steps file that is not UTF-8", [*base, "--steps-file", str(t.task / "latin1.txt")], "not UTF-8")
        steps.write_text(f"goto {UI}\n", encoding="utf-8")
        for case, why in (("../x", "goes up a folder"), ("/abs", "absolute"), ("", "is empty")):
            refused(f"case {case!r}", ["ui", "--task-root", str(t.task), "--case", case, "--steps-file", str(steps)], why)
        refused("an attempt name that is not a<number>", [*base, "--steps-file", str(steps), "--attempt", "../a1"],
                "not an attempt name")
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--steps-file", str(steps)])
        check_eq("a missing --case is a refusal with the registered shape, not a usage error", code, 2)
        check_in("a missing --case: names the shape of the command", "what to write:", err)
        check("a refused call created no attempt folder", not (MC.case_root(t.task, UI_CASE)).exists())
    finally:
        S.cleanup(t)


def login_and_secrets():
    t = S.make_task()
    try:
        env = t.project / "harness" / ".env"
        # a missing key is refused by NAME, never by value
        env.write_text(f"AUTH_USERNAME={S.USER}\n", encoding="utf-8")
        err = refused("a missing password key", ["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file",
                                                 str(_write(t, f"goto {UI}\n"))], "AUTH_PASSWORD is not set")
        check_not_in("a missing key: the user name value is not printed either", S.USER, err)
        env.write_text(f"AUTH_PASSWORD={S.PASSWORD}\n", encoding="utf-8")
        err = refused("a missing user key", ["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file",
                                             str(_write(t, f"goto {UI}\n"))], "AUTH_USERNAME is not set")
        check_not_in("a missing key: the password value is not printed", S.PASSWORD, err)
        env.unlink()
        refused("a missing .env file", ["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file",
                                        str(_write(t, f"goto {UI}\n"))], "environment.env_file = harness/.env")
        check("the credentials object never prints its values", S.PASSWORD not in repr(MC.Credentials(S.USER, S.PASSWORD)))
    finally:
        S.cleanup(t)
    # config without a login file: no login is attempted, the session still runs
    t = S.make_task(cfg=S.config(environment={}))
    try:
        code, out, err, browser = ui_run(t, steps=f"goto {UI}\ncapture post_action completion\n")
        check_eq("no `environment.env_file` in config: no login, the session runs", (code, browser.credentials_seen), (0, None))
    finally:
        S.cleanup(t)
    # a value read from the page that matches a secret pattern is NOT saved; the step is refused by pattern index
    t = S.make_task()
    try:
        key = "-----BEGIN RSA PRIVATE KEY-----"
        code, out, err, browser = ui_run(t, browser=S.FakeBrowser(reads={".key": f"{key} MIIB"}),
                                         steps=f"goto {UI}\nread .key\ncapture post_action completion\n")
        summary = json.loads(out)
        check_eq("secret in a read value: exit 1, the step is `refused`, nothing after it ran",
                 (code, summary["failed"]["outcome"], len(summary["steps"])), (1, "refused", 3))
        check_in("secret in a read value: names the pattern index", "secret_content_patterns[0]", summary["failed"]["detail"])
        leak = S.tree_text(t.task)
        check_not_in("secret in a read value: the matched text is saved nowhere", "PRIVATE KEY", leak + out + err)
        check_eq("secret in a read value: no log file was written for it", summary["captures"], [])
        # a pattern that is not a valid expression is a refusal, never a silent no-scan
        bad = S.make_task(cfg=S.config(secret_content_patterns=["(unclosed"]))
        try:
            steps = _write(bad, f"goto {UI}\n")
            refused("an invalid secret pattern", ["ui", "--task-root", str(bad.task), "--case", UI_CASE,
                                                  "--steps-file", str(steps)], "secret_content_patterns[0]")
        finally:
            S.cleanup(bad)
    finally:
        S.cleanup(t)


def _write(t, text):
    path = t.task / "steps.txt"
    path.write_text(text, encoding="utf-8")
    return path


IMAGE = "image:sha256:" + "b" * 64


def image_probe(identity=IMAGE, result="unknown"):
    """What `runtime_probe.py` answers on a container with no sources (the uitest nginx): `unknown`, no evidence,
    and the image the container runs as its identity (t-279 K-IMG)."""
    return dict(S.probe(result=result, identity=identity), evidence_refs=[], provenance={"technical_verification": False})


def person_probe(profile="e2e-ui", identity=IMAGE, task=S.TICKET, **fields):
    """What `runtime_probe.py` answers when the PERSON said "deployed" for this story and this stand (t-300): the word
    with the facts it was given for (kind, story, revision = the expected one), the image it binds to as the identity,
    never `matched`, and an evidence file of its own (`write_evidence` writes one for a person's word)."""
    record = dict(S.probe(profile=profile, result="person_confirmed", identity=identity), evidence_refs=[f"probe/{profile}-pc"],
                  provenance={"technical_verification": False, "identity_kind": "person_confirmed"},
                  person_confirmation={"words": "yes, it is deployed", "at": "2026-10-02T11:00:00+00:00", "task": task,
                                       "kind": "deployed", "revision": S.SOURCE})
    record.update(fields)
    return record


def mismatched_probe(profile="e2e-ui", deployed="d" * 40, **fields):
    """A stand that PROVABLY runs another build (the sha rung's `mismatched`: no `error`, no `remedy`)."""
    return dict(S.probe(profile=profile, result="mismatched"), provenance={"technical_verification": True, "source_linkage": "exact",
                                                                            "deployed_source_revision": deployed}, **fields)


def n2_k8_a_capture_takes_the_persons_word_and_nothing_on_an_unknown():
    """K-N2.8 (t-300 N2, S9 - the capture half of Q18-B). The capture reads the stand through the ONE strict reader
    (`run_suite.probe_runtime`, called bare - t-279's `allow_image_identity` is gone): `matched`, `not_applicable` (no changed
    file) and the PERSON'S WORD for this story are taken and stored as the probe said them; an `unknown` is refused with or
    without an image; a word given for ANOTHER story is refused before the session is spent (F10); a stand that proves
    another build, and an `unknown` that asks the person, are `do_not_retry` with the BUILD door (X13, F5), while an
    `unknown` that asks nobody (docker was down) keeps "capture again"."""
    t = S.make_task()
    try:
        steps = _write(t, f"goto {UI}\ncapture post_action completion\n")
        patch_backends(S.FakeBrowser(), probes=lambda spec: person_probe())
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        check_eq("K-N2.8: a person's word for this story: the capture proceeds (exit 0, not env_blocked)", code, 0)
        check_eq("K-N2.8: and both probes are stored as the probe said them: `person_confirmed`, never `matched`",
                 [(p["probe"]["result"], p["probe"]["observed_runtime_identity"])
                  for p in jsonl(t.attempt_dir(UI_CASE) / "probes.jsonl")], [("person_confirmed", IMAGE)] * 2)
        check("K-N2.8: no env_blocked.json for that attempt", not (t.attempt_dir(UI_CASE) / "env_blocked.json").exists())
        # the default probe of this module IS the strict reader, called bare
        import run_suite
        held = run_suite.probe_runtime
        seen = []
        run_suite.probe_runtime = lambda spec, **kw: seen.append(kw) or person_probe()
        try:
            MC.PROBE = None
            S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        finally:
            run_suite.probe_runtime = held
        check_eq("K-N2.8: the capture's default probe is `probe_runtime` called bare (no image-identity switch exists any more)",
                 seen, [{}] * 2)
    finally:
        S.cleanup(t)

    def blocked(label, answer, steps_text=None):
        t = S.make_task()
        try:
            browser = S.FakeBrowser()
            steps = _write(t, steps_text or f"goto {UI}\ncapture post_action completion\n")
            patch_backends(browser, probes=lambda spec, a=answer: a)
            code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
            row = json.loads(out)["env_blocked"]
            check_eq(f"K-N2.8 {label}: exit 3, env_blocked, owner user, no browser opened (the session is not spent)",
                     (code, json.loads(out)["outcome"], row["owner"], browser.opened), (3, "env_blocked", "user", None))
            return row, err, t
        finally:
            S.cleanup(t)
    # what the real probe writes on a container with no sources it can compare: `unknown`, the image it runs, and the question
    row, err, _t = blocked("unknown + image (the K-IMG case, rewritten)", dict(image_probe(), asks_person="how"))
    check_eq("K-N2.8 U+image: refused (an unknown is taken by no token, Q18-B)", row["probe_line"].startswith("e2e-ui start: runtime probe returned unknown"), True)
    check_in("K-N2.8 U: the remedy names the person's decision file and the stage-entry question", "qa-factory/records/stand-identity.json", row["remedy"])
    check_in("K-N2.8 U: ...and the question", "build question of the stage entry", row["remedy"])
    check_not_in("K-N2.8 U: ...and never the Dockerfile lines the old remedy printed", "Dockerfile", row["remedy"] + err)
    row, err, _t = blocked("unknown, no image, asks nobody (docker was down)", dict(S.probe(result="unknown", identity="build-1"),
                                                                                  evidence_refs=[], provenance={"technical_verification": False}))
    check_eq("K-N2.8 F5: an `unknown` that asks nobody keeps `capture again`: no do_not_retry", (row.get("do_not_retry"), "capture again" in row["remedy"]),
             (None, True))
    row, err, _t = blocked("unknown that asks the person", dict(image_probe(), asks_person="how", error="which build the stand runs could not be read",
                                                               remedy="tell me how to read it"))
    check_eq("K-N2.8 F5/X13: an `unknown` that asks the person is do_not_retry, cause `build`", (row.get("do_not_retry"), row.get("cause")), (True, "build"))
    check_in("K-N2.8 F5: and the probe's own error is the line", "which build the stand runs could not be read", row["probe_line"])
    check_in("K-N2.8 X13: stderr names the BUILD halt, not the login one", "does not hold a build this story can be captured on", err)
    check_not_in("K-N2.8 X13: and never the login line", "login by code did not land", err)
    row, err, _t = blocked("a proven mismatch", mismatched_probe())
    check_eq("K-N2.8 X13: a stand that proves another build: do_not_retry, cause `build`", (row.get("do_not_retry"), row.get("cause")), (True, "build"))
    check_in("K-N2.8 MM: the line names both builds", "runtime probe returned mismatched: the stand runs " + "d" * 12 + " and this story is " + S.SOURCE,
             row["probe_line"])
    check_in("K-N2.8 MM: and the remedy is the person's door, with the halt", "answers `test deployed` at the build question of the stage entry", row["remedy"])
    row, err, _t = blocked("a content mismatch", dict(S.probe(result="mismatched"), differing_files=["src/a.vue"],
                                                      provenance={"technical_verification": True, "source_linkage": "verified_content",
                                                                  "deployed_source_revision": "content_mismatch"}))
    check_in("K-N2.8 CM: the line names the files", "the stand serves other content for src/a.vue", row["probe_line"])
    check_not_in("K-N2.8 CM: and offers no `test deployed`", "test deployed", row["probe_line"])
    check_not_in("K-N2.8 F1 (t-395): the REMEDY of a content mismatch never offers `test deployed` (a stand whose content differs "
                 "has no build to test as it is, R(cm))", "test deployed", row["remedy"])
    check_in("K-N2.8 F1: it says the person redeploys this story's build", "redeploys this story's build", row["remedy"])
    check_eq("K-N2.8 F1: and is still do_not_retry, cause build", (row.get("do_not_retry"), row.get("cause")), (True, "build"))
    twin, _e, _t = blocked("a proven mismatch (the sha twin of F1)", mismatched_probe())
    check_in("K-N2.8 F1 twin: a mismatch that names a COMMIT still offers `test deployed` in its remedy", "answers `test deployed`", twin["remedy"])
    row, err, _t = blocked("another story's word (F10)", person_probe(task="OTHER-9"))
    check_in("K-N2.8 F10: the line names both stories", "the person's word was given for story OTHER-9, and this is story " + S.TICKET, row["probe_line"])
    check_eq("K-N2.8 F2 (t-395): another story's word is do_not_retry, cause build - a second capture meets the same word",
             (row.get("do_not_retry"), row.get("cause")), (True, "build"))
    check_in("K-N2.8 F2: and the door is the person's word for THIS story", "for THIS story", row["remedy"])
    check_not_in("K-N2.8 F2: never `then capture again`", "then capture again", row["remedy"])
    check_in("K-N2.8 F2: stderr names the BUILD halt", "does not hold a build this story can be captured on", err)
    # F2 transient twin: an unknown that asks nobody (docker was down) keeps `capture again` and is NOT do_not_retry
    gone, err, _t = blocked("docker down (the F2 transient twin)", dict(S.probe(result="unknown", identity="build-1"), evidence_refs=[],
                                                                         provenance={"technical_verification": False}))
    check_eq("K-N2.8 F2 twin: no do_not_retry, and the door is `capture again`", (gone.get("do_not_retry"), "then capture again" in gone["remedy"]),
             (None, True))
    row, err, _t = blocked("a word with its revision missing (X6)", person_probe(person_confirmation={
        "words": "yes", "at": "2026-10-02T11:00:00+00:00", "task": S.TICKET, "kind": "deployed"}))
    check_in("K-N2.8 X6: the line says the word does not say what it was given for", "person_confirmation.revision is required", row["probe_line"])
    # the refused attempt is closed: a later capture on it is refused with the build door, never "capture again"
    t = S.make_task()
    try:
        steps = _write(t, f"goto {UI}\ncapture post_action completion\n")
        patch_backends(S.FakeBrowser(), probes=lambda spec: mismatched_probe())
        S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        try:
            MC.choose_attempt(MC.case_root(t.task, UI_CASE), "a1")
            raised = ""
        except ValueError as exc:
            raised = str(exc)
        check_in("K-N2.8 X13: a capture into that attempt is refused with the build cause", "the stand does not hold this story's build", raised)
        check_not_in("K-N2.8 X13: and never the login cause", "its test account", raised)
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
        check_eq("K-N2.8 X13: `build` has no record to make", code, 2)
        check_in("K-N2.8 X13: and says the stand does not hold this story's build, not that the login failed",
                 "the stand does not hold this story's build, or nobody could say which one it holds", err)
        check_not_in("K-N2.8 X13: ...never the login cause", "the login did not land", err)
    finally:
        S.cleanup(t)
    # a PERSON'S WORD builds a record: validate and the controller-side binding both take it, and the record SAYS so
    t = S.make_task()
    try:
        seed_runtime_records(t)
        steps = _write(t, f"goto {UI}\ncapture pre_action initial\ncapture post_action completion\n")
        patch_backends(S.FakeBrowser(), probes=lambda spec: person_probe())
        S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "the scale grew", "--masked")
        check_eq("K-N2.8: `build` writes the record on the person's word" + ("" if code == 0 else " | " + err[:400]), code, 0)
        record = json.loads((t.attempt_dir(UI_CASE) / "record.json").read_text(encoding="utf-8"))
        check_eq("K-N2.8: the probes keep the honest word", (record["runtime_before"]["result"], record["runtime_after"]["result"]),
                 ("person_confirmed", "person_confirmed"))
        check_in("K-N2.8 S12: and the record carries code's sentence", "the build was confirmed by the person (yes, it is deployed, 2026-10-02), "
                 "not read by the factory", record["limitations"])
        check_eq("K-N2.8: a `deployed` word adds no `test deployed` sentence", len([x for x in record["limitations"] if "build under test" in x]), 0)
        other = dict(record, runtime_after=person_probe(identity="image:sha256:" + "c" * 64))
        check_in("K-N2.8 control: another image at the end is refused (before == after)", "runtime provenance changed during the attempt",
                 "\n".join(M.validate_record(other, t.task)))
    finally:
        S.cleanup(t)
    # a stand that cannot be told from the first probe to the last is the record's refusal, not the capture's
    t = S.make_task()
    try:
        seed_runtime_records(t)
        steps = _write(t, f"goto {UI}\ncapture pre_action initial\ncapture post_action completion\n")
        calls = []

        def rebuilt(spec):
            calls.append(spec)
            return person_probe(identity="image:sha256:" + ("b" if len(calls) == 1 else "c") * 64)
        patch_backends(S.FakeBrowser(), probes=rebuilt)
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        check_eq("K-N2.8: the capture ran on the first image", code, 0)
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
        check_eq("K-N2.8 control: a rebuild between the two probes refuses the record", code, 2)
        check_in("K-N2.8 control: with the words of the identity rule", "runtime provenance changed during the attempt", err)
    finally:
        S.cleanup(t)


def n2_f6_the_remedies_and_the_cause_words_are_read_from_the_refusals_block():
    """F6 (t-395): the capture's remedies (`_stand_blocked`) and the build cause/door `choose_attempt` says are DATA - the
    `refusals` block of build-identity-methods.json (FR-13), one home. A changed block value changes the sentence."""
    import tempfile
    import shutil
    import profile_contract as P
    folder = Path(tempfile.mkdtemp(prefix="qa-f6-block-"))
    held = P.REFUSAL_DATA
    try:
        keys = ("remedy_other_build", "remedy_other_content", "remedy_unknown_asks", "remedy_other_story", "remedy_retry",
                "cause_build", "door_build")
        (folder / "methods.json").write_text(json.dumps({"refusals": {k: f"BLOCK[{k}] {{registry}}" for k in keys}}), encoding="utf-8")
        P.REFUSAL_DATA = folder / "methods.json"
        word = person_probe(task="OTHER-9")
        shapes = {"remedy_other_build": mismatched_probe(), "remedy_unknown_asks": dict(image_probe(), asks_person="how"),
                  "remedy_other_content": dict(S.probe(result="mismatched"), differing_files=["a.vue"],
                                               provenance={"technical_verification": True, "source_linkage": "verified_content",
                                                           "deployed_source_revision": "content_mismatch"}),
                  "remedy_retry": {"result": "unknown"}, "remedy_other_story": word}
        for key, record in shapes.items():
            row = MC._stand_blocked("e2e-ui", "start", record, "said", S.TICKET).row
            check_in(f"K-F6: `{key}` is read from the block (a changed value changes the sentence)", f"BLOCK[{key}]", row["remedy"])
        row = MC._stand_blocked("e2e-ui", "start", shapes["remedy_other_story"], "said", S.TICKET).row
        check_in("K-F6: and its {registry} slot is filled with the layout's own path", "qa-factory/records/stand-identity.json", row["remedy"])
        attempt = folder / "case"
        (attempt / "a1").mkdir(parents=True)
        (attempt / "a1" / "env_blocked.json").write_text(json.dumps({"probe_line": "x", "do_not_retry": True, "cause": "build"}), encoding="utf-8")
        try:
            MC.choose_attempt(attempt, "a1")
            said = ""
        except ValueError as exc:
            said = str(exc)
        check_in("K-F6: the build cause of choose_attempt is the block's", "BLOCK[cause_build]", said)
        check_in("K-F6: and so is its door", "BLOCK[door_build]", said)
        P.REFUSAL_DATA = held
        try:
            MC.choose_attempt(attempt, "a1")
            said = ""
        except ValueError as exc:
            said = str(exc)
        check_not_in("K-F6 (t-395 :242): with the shipped data the build cause never says `account or the stand is fixed` (the login's words)",
                     "account or the stand is fixed", said)
        check_in("K-F6: the shipped door is the person's answer for this story", "answered the build question for this story", said)
        (attempt / "a2").mkdir()
        (attempt / "a2" / "env_blocked.json").write_text(json.dumps({"probe_line": "x", "do_not_retry": True}), encoding="utf-8")
        try:
            MC.choose_attempt(attempt, "a2")
            said = ""
        except ValueError as exc:
            said = str(exc)
        check_in("K-F6 control: a LOGIN attempt keeps its own cause and door", "account or the stand is fixed", said)
    finally:
        P.REFUSAL_DATA = held
        shutil.rmtree(folder, ignore_errors=True)


def probes():
    cases = (("unmatched", lambda spec: S.probe(result="mismatched"), "runtime probe returned mismatched"),
             ("failed", lambda spec: (_ for _ in ()).throw(RuntimeError("runtime probe failed")), "RuntimeError: runtime probe failed"),
             ("unknown", lambda spec: {"result": "unknown"}, "runtime probe returned unknown: the probe gave no reason"),
             # E1: a record with no `result` is never a pass, and the line says it gave no reason (never the bare "unverified")
             ("no result", lambda spec: {}, "runtime probe returned no result: the probe gave no reason"))
    for label, probe, line in cases:
        t = S.make_task()
        try:
            browser = S.FakeBrowser()
            steps = _write(t, f"goto {UI}\ncapture post_action completion\n")
            patch_backends(browser, probes=probe)
            code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
            summary = json.loads(out)
            check_eq(f"probe {label}: exit 3 and the case is env_blocked", (code, summary["outcome"]), (3, "env_blocked"))
            check_in(f"probe {label}: with the probe line", line, summary["env_blocked"]["probe_line"])
            check_eq(f"probe {label}: the row names the case, a remedy and an owner",
                     (summary["env_blocked"]["id"], bool(summary["env_blocked"]["remedy"]),
                      summary["env_blocked"]["owner"] in ("user", "factory")), (UI_CASE, True, True))
            check_eq(f"probe {label}: no browser was opened and nothing was captured", (browser.opened, browser.calls), (None, []))
            check(f"probe {label}: the attempt holds env_blocked.json and no captures",
                  (t.attempt_dir(UI_CASE) / "env_blocked.json").is_file() and not (t.attempt_dir(UI_CASE) / "captures.jsonl").exists())
            code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
            check_eq(f"probe {label}: `build` has no record to make", code, 2)
            check_in(f"probe {label}: and says the attempt has no record, with the probe's own line", f"has no record: {summary['env_blocked']['probe_line']}", err)
            check_in(f"probe {label}: and the door is env_blocked[]", "env_blocked[]", err)
            check_not_in(f"probe {label}: and never says the login did not land (that is the other cause)", "the login did not land", err)
        finally:
            S.cleanup(t)
    # not_applicable counts as a pass: the session runs
    t = S.make_task()
    try:
        steps = _write(t, f"goto {UI}\ncapture post_action completion\n")
        no_file = dict(S.probe(result="not_applicable"), reason_code="no_changed_file")     # the probe says WHY (a FIELD)
        patch_backends(S.FakeBrowser(), probes=lambda spec: no_file)
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        check_eq("probe not_applicable (no_changed_file): counts as passed (the session runs)", code, 0)
        check_eq("probe not_applicable: and is stored as the probe said it",
                 [p["probe"]["result"] for p in jsonl(t.attempt_dir(UI_CASE) / "probes.jsonl")], ["not_applicable"] * 2)
    finally:
        S.cleanup(t)
    t = S.make_task()
    try:
        steps = _write(t, f"goto {UI}\ncapture post_action completion\n")
        patch_backends(S.FakeBrowser(), probes=lambda spec: S.probe(result="not_applicable"))
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        check_eq("probe not_applicable with NO reason_code (t-300 N2 S9, one predicate): env_blocked - a probe that does not say "
                 "why it compared nothing is not a pass", (code, json.loads(out)["outcome"]), (3, "env_blocked"))
        check_in("probe not_applicable with NO reason_code: and the line says what was expected", "runtime not_applicable requires",
                 json.loads(out)["env_blocked"]["probe_line"])
    finally:
        S.cleanup(t)
    n2_k8_a_capture_takes_the_persons_word_and_nothing_on_an_unknown()
    n2_f6_the_remedies_and_the_cause_words_are_read_from_the_refusals_block()
    # the stand answers at the start and is gone at the end: the captures stay, the attempt gets no record
    t = S.make_task()
    try:
        seen = []

        def second_fails(spec):
            seen.append(spec["argv"])
            if len(seen) == 2:
                raise RuntimeError("the stand went away")
            return S.probe()
        steps = _write(t, f"goto {UI}\ncapture post_action completion\n")
        patch_backends(S.FakeBrowser(), probes=second_fails)
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        check_eq("probe fails at the END: exit 3 and env_blocked", (code, json.loads(out)["outcome"]), (3, "env_blocked"))
        check("probe fails at the END: the attempt holds its captures AND env_blocked.json",
              (t.attempt_dir(UI_CASE) / "env_blocked.json").is_file() and (t.attempt_dir(UI_CASE) / "captures.jsonl").is_file())
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
        check_eq("probe fails at the END: no record can be built from that attempt",
                 (code, "has no record: runtime probe of e2e-ui end: RuntimeError: the stand went away" in err), (2, True))
    finally:
        S.cleanup(t)
    # no probe registered for the profile
    t = S.make_task(cfg=S.config(execution={"runtime_probes": {}}))
    try:
        steps = _write(t, f"goto {UI}\n")
        patch_backends(S.FakeBrowser())
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        row = json.loads(out)["env_blocked"]
        check_eq("no probe registered, no checkout recorded: exit 3, owner the user, do_not_retry, cause build (EP1-28)",
                 (code, row["owner"], row.get("do_not_retry"), row.get("cause")), (3, "user", True, "build"))
        check_in("no probe registered: the line says why none could be worked out", "no checkout of the application is recorded for profile e2e-ui",
                 row["probe_line"])
        check_in("no probe registered: the remedy names the door that is walkable",
                 "runtime_probe.py --suggest --write --no-container --profile e2e-ui", row["remedy"])
    finally:
        S.cleanup(t)


def browser_unavailable():
    t = S.make_task()
    try:
        steps = _write(t, f"goto {UI}\n")
        MC.BACKEND_FACTORY, MC.PROBE, MC.NOW = None, (lambda spec: S.probe()), S.Clock()
        real = MC.PlaywrightBackend

        class Missing:
            def __init__(self):
                raise MC.BrowserUnavailable("No module named 'playwright'")
        MC.PlaywrightBackend = Missing
        called = []
        original = MC._reexec_in_harness
        MC._reexec_in_harness = lambda cfg, root, argv: called.append(argv) or 0
        try:
            err = refused("Playwright missing in the harness interpreter", ["ui", "--task-root", str(t.task), "--case", UI_CASE,
                                                                            "--steps-file", str(steps), "--in-harness"],
                          "Playwright cannot be imported here")
            check_in("Playwright missing: the door is the install command for the Python that runs the factory",
                     "python -m pip install playwright, then python -m playwright install chromium", err)
            check_not_in("Playwright missing: no profile id and no tool of one project in the door", "poetry", err)
            code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
            check_eq("Playwright missing here: the call is re-run in the harness interpreter (once, flagged by the caller)",
                     (code, len(called)), (0, 1))
            check("Playwright missing here: the original arguments travel", "--steps-file" in called[0] and "--in-harness" not in called[0])
            check("no probe ran and nothing was captured before the browser was known to exist",
                  not (MC.case_root(t.task, UI_CASE)).exists())
        finally:
            MC.PlaywrightBackend, MC._reexec_in_harness = real, original
        argv, cwd = MC.harness_argv(S.config(), t.project)
        check_eq("the harness interpreter is the e2e-ui command up to pytest, then python", (argv, cwd), (["poetry", "run", "python"], t.project))
        try:
            MC.harness_argv(S.config(profiles=[]), t.project)
            check("no ui profile is refused", False)
        except ValueError as exc:
            check_in("no ui profile is refused, with the install door", "python -m playwright install chromium", str(exc))
            check_not_in("no ui profile is refused, without a profile id of one project", "e2e-ui", str(exc))
        node = S.config(profiles=[{"profile_id": "web", "capabilities": ["web"], "commands": {
            "one_test": {"argv": ["npx", "playwright", "test"], "cwd": "."}}}])
        try:
            MC.harness_argv(node, t.project)
            check("a node project has no pytest interpreter to derive", False)
        except ValueError as exc:
            check_in("a node project: the same walkable door (EP1-28 (7))", "python -m pip install playwright", str(exc))
        other = S.config(profiles=[{"profile_id": "browser-checks", "capabilities": ["web"], "commands": {
            "one_test": {"argv": ["uv", "run", "pytest", "<f>"], "cwd": "."}}}])
        check_eq("a profile with another id and pytest gives its interpreter (no literal id)", MC.harness_argv(other, t.project)[0],
                 ["uv", "run", "python"])
    finally:
        S.cleanup(t)


def http_captures():
    t = S.make_task(manual=("api",))
    try:
        get = f"{LOCAL}/v1/workflows/w1"
        post = f"{LOCAL}/v1/workflows/w1/validate"
        login = f"{LOCAL}/v1/local-auth/login"
        http = S.FakeHttp({("POST", login): S.ok_json({"access_token": S.TOKEN}),
                           ("GET", get): S.ok_json({"id": "w1", "config": "a: \u00e9"}, headers=[("Set-Cookie", "sid=SENTINEL-COOKIE-77")]),
                           ("POST", post): S.ok_json({"valid": True})})
        body = t.task / "body.json"
        body.write_text('{"yaml": "b: 1"}', encoding="utf-8")
        code, out, err = http_run(t, http, "--method", "GET", "--url", get, "--phase", "pre_action", "--proves", "before state")
        check_eq("http: a pre_action GET captured (exit 0)", code, 0)
        code, out, err = http_run(t, http, "--method", "POST", "--url", post, "--body-file", str(body), "--header",
                                  "X-Trace: t1", "--state-url", get, "--proves", "completion")
        summary = json.loads(out)
        check_eq("http: the POST and its state GET are one attempt with the first call (a1)", (code, summary["attempt"]), (0, "a1"))
        check_eq("http: the call is saved as request_response in post_action and proves completion; the state beside it",
                 [(c["kind"], c["phase"], c["proves"]) for c in summary["captures"]],
                 [("request_response", "post_action", ["completion"]), ("state", "post_action", ["state"])])
        folder = t.attempt_dir(API_CASE)
        saved = json.loads((t.task / summary["captures"][0]["path"]).read_text(encoding="utf-8"))
        check_eq("http: the login token was sent (by code) ...", http.calls[1][2]["Authorization"], "Bearer " + S.TOKEN)
        check_eq("http: ... and is stored as [redacted]", saved["request"]["headers"]["Authorization"], "[redacted]")
        check_eq("http: other headers are kept as sent", saved["request"]["headers"]["X-Trace"], "t1")
        state = json.loads((t.task / summary["captures"][1]["path"]).read_text(encoding="utf-8"))
        check_eq("http: Set-Cookie of a response is redacted", state["response"]["headers"]["Set-Cookie"], "[redacted]")
        check_eq("http: non-ASCII body text is stored as UTF-8", state["response"]["body"], '{"id": "w1", "config": "a: \u00e9"}')
        raw = (t.task / summary["captures"][1]["path"]).read_bytes()
        check("http: the file holds the character, not an escape", "\u00e9".encode("utf-8") in raw)
        leak = S.tree_text(t.task) + out + err
        for secret in (S.PASSWORD, S.TOKEN, "SENTINEL-COOKIE-77"):
            check_not_in(f"http: {secret[:15]}... is in no saved byte nor in stdout/stderr", secret, leak)
        probes = jsonl(folder / "probes.jsonl")
        check_eq("http: probed on the `api` profile at the start and at the end of each call",
                 [(p["profile"], p["when"]) for p in probes], [("api", "start"), ("api", "end")] * 2)
        check_eq("http: an explicit Authorization header means no login call",
                 len([c for c in http.calls if c[1] == login]), 2)
        http_run(t, http, "--method", "GET", "--url", get, "--header", "Authorization: Bearer mine", "--attempt", "a1")
        check_eq("http: with --header Authorization the login is not made for that call",
                 len([c for c in http.calls if c[1] == login]), 2)
    finally:
        S.cleanup(t)


def http_user_agent_and_foreign_answers():
    """B-408 (AK8, E4): the recorded request holds the factory's User-Agent (the evidence shows what was sent), the role's own
    User-Agent wins in any case, and an answer that is not shown to be the stand's own is named in the step's detail and in the
    login refusal instead of "the stand rejected the account"."""
    t = S.make_task(manual=("api",))
    try:
        get = f"{LOCAL}/v1/workflows/w1"
        login = f"{LOCAL}/v1/local-auth/login"
        page = (b"<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title></head><body>blocked</body></html>")
        cf = MC.HttpResult(403, [("Server", "cloudflare"), ("CF-RAY", "8a1b"), ("Content-Type", "text/html")], page, 0.05)
        http = S.FakeHttp({("POST", login): S.ok_json({"access_token": S.TOKEN}), ("GET", get): S.ok_json({"id": "w1"})})
        code, out, err = http_run(t, http, "--method", "GET", "--url", get, "--phase", "pre_action", "--proves", "before state")
        summary = json.loads(out)
        saved = json.loads((t.task / summary["captures"][0]["path"]).read_text(encoding="utf-8"))
        ua = saved["request"]["headers"].get("User-Agent", "")
        check("AK8: the recorded request holds the factory's User-Agent, as sent", ua.startswith("qa-factory/") and "python" not in ua.lower(), ua)
        check_eq("AK8: ... and it is what the client was given", http.calls[-1][2].get("User-Agent"), ua)
        for name in ("User-Agent", "user-agent"):
            code, out, err = http_run(t, http, "--method", "GET", "--url", get, "--header", f"{name}: role-agent/1", "--attempt", "a1")
            summary = json.loads(out)
            saved = json.loads((t.task / summary["captures"][0]["path"]).read_text(encoding="utf-8"))
            headers = {k.lower(): v for k, v in saved["request"]["headers"].items()}
            check_eq(f"AK8: the role's own `{name}` wins and is not doubled",
                     (headers.get("user-agent"), sum(1 for k in saved["request"]["headers"] if k.lower() == "user-agent")), ("role-agent/1", 1))
        http = S.FakeHttp({("POST", login): S.ok_json({"access_token": S.TOKEN}), ("GET", get): cf})
        code, out, err = http_run(t, http, "--method", "GET", "--url", get, "--phase", "post_action", "--attempt", "a1")
        steps = jsonl(t.attempt_dir(API_CASE) / "steps.jsonl")
        detail = steps[-1]["detail"]
        check_eq("AK8: a protection page keeps the step `ok` (the answer is saved) and the exit 0", (steps[-1]["outcome"], code), ("ok", 0))
        check("AK8: ... but the detail names what answered, not just a bare status",
              detail.startswith("status 403") and "not shown to be the stand's own" in detail and "Attention Required! | Cloudflare" in detail, detail)
        http = S.FakeHttp({("POST", login): S.ok_json({"detail": "no"}, status=401), ("GET", get): S.ok_json({})})
        code, out, err = http_run(t, http, "--method", "GET", "--url", get, "--attempt", "a1")
        check_in("AK8 control: the stand's own JSON refusal at login keeps the old sentence", "The stand rejected the account", out + err)
        http = S.FakeHttp({("POST", login): cf, ("GET", get): S.ok_json({})})
        code, out, err = http_run(t, http, "--method", "GET", "--url", get, "--attempt", "a1")
        check("AK8: a protection page at login does not say the stand rejected the account, and says it was not judged",
              "rejected the account" not in out + err and "was not judged" in out + err and "Attention Required! | Cloudflare" in out + err, (out + err)[-600:])
    finally:
        S.cleanup(t)
    # B-408 F1: a status that arrived with a body that never did is a TIMEOUT step (as it always was), not an empty body
    t = S.make_task(manual=("api",))
    try:
        get = f"{LOCAL}/v1/workflows/w1"
        login = f"{LOCAL}/v1/local-auth/login"
        stalled = MC.HttpResult(500, [("Content-Type", "text/html")], b"", 0.1, unreadable=True)
        http = S.FakeHttp({("POST", login): S.ok_json({"access_token": S.TOKEN}), ("GET", get): stalled})
        code, out, err = http_run(t, http, "--method", "GET", "--url", get, "--phase", "post_action")
        steps = jsonl(t.attempt_dir(API_CASE) / "steps.jsonl")
        check_eq("F1: an unreadable body ends the step as `timeout`, and what is saved is the timeout note, never a response",
                 (steps[-1]["outcome"], json.loads(out)["failed"]["outcome"], [c["kind"] for c in json.loads(out)["captures"]]),
                 ("timeout", "timeout", ["log"]))
    finally:
        S.cleanup(t)
    from test_http_client import StallStub
    stall = StallStub(500)
    try:
        result = MC.UrllibHttp().request("GET", stall.url, {}, None, 1)
        check_eq("F1: the real client keeps the status and says the body did not come", (result.status, result.body, result.unreadable),
                 (500, b"", True))
    finally:
        stall.close()
    # the real client, against a real socket: the User-Agent, no redirect followed, the error body kept
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("User-Agent", ""))
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:1/elsewhere")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(403)
            self.send_header("Server", "cloudflare")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        result = MC.UrllibHttp().request("GET", base + "/x", {}, None, 5)
        check_eq("UrllibHttp: the 403 keeps its status, headers and body", (result.status, dict(result.headers).get("Server"), result.body),
                 (403, "cloudflare", page))
        result = MC.UrllibHttp().request("GET", base + "/redirect", {}, None, 5)
        check_eq("UrllibHttp: a 302 is the answer, not followed", (result.status, dict(result.headers).get("Location")),
                 (302, "http://127.0.0.1:1/elsewhere"))
        MC.UrllibHttp().request("GET", base + "/x", {"User-Agent": "role-agent/1"}, None, 5)
        check("UrllibHttp: the User-Agent is the factory's, and the caller's own wins",
              seen[0].startswith("qa-factory/") and seen[-1] == "role-agent/1", str(seen))
    finally:
        server.shutdown()
        server.server_close()


def http_edges():
    t = S.make_task(manual=("api",))
    try:
        get = f"{LOCAL}/v1/workflows/w1"
        login = ("POST", f"{LOCAL}/v1/local-auth/login")
        token = S.ok_json({"access_token": S.TOKEN})
        cap = MC.BODY_CAP
        # --- the 2 MB cap: AT is whole, BEYOND is cut with a limitation; the hash is over the stored bytes
        for label, size, cut in (("AT 2 MB", cap, False), ("1 byte BEYOND 2 MB", cap + 1, True)):
            fresh = S.make_task(manual=("api",))
            try:
                payload = b"a" * size
                http = S.FakeHttp({login: token, ("GET", get): MC.HttpResult(200, [("Content-Type", "text/plain")], payload, 0.1)})
                code, out, err = http_run(fresh, http, "--method", "GET", "--url", get)
                summary = json.loads(out)
                stored = json.loads((fresh.task / summary["captures"][0]["path"]).read_text(encoding="utf-8"))["response"]
                check_eq(f"body {label}: stored_bytes / truncated", (stored["body_bytes_stored"], stored["truncated"]), (cap, cut))
                check_eq(f"body {label}: the limitation is recorded exactly when it was cut",
                         bool(summary["limitations"]), cut)
                entry = jsonl(fresh.attempt_dir(API_CASE) / "captures.jsonl")[0]
                check_eq(f"body {label}: the hash is over the stored file's bytes", entry["content_hash"],
                         S.sha(fresh.task / entry["path"]))
                check_eq(f"body {label}: the captures line carries the limitation iff cut", "limitation" in entry, cut)
            finally:
                S.cleanup(fresh)
        # a body that is not UTF-8 is stored base64; a cut inside a multi-byte character is trimmed, not broken
        fresh = S.make_task(manual=("api",))
        try:
            http = S.FakeHttp({login: token, ("GET", get): MC.HttpResult(200, [], b"\xff\xfe\x00bin", 0.1)})
            code, out, err = http_run(fresh, http, "--method", "GET", "--url", get)
            stored = json.loads((fresh.task / json.loads(out)["captures"][0]["path"]).read_text(encoding="utf-8"))["response"]
            check_eq("binary body: base64", stored["body_encoding"], "base64")
            edge = ("a" * (cap - 1) + "\u00e9").encode("utf-8")      # the 2-byte character straddles the cap
            http = S.FakeHttp({login: token, ("GET", get): MC.HttpResult(200, [], edge, 0.1)})
            code, out, err = http_run(fresh, http, "--method", "GET", "--url", get, "--attempt", "a1")
            stored = json.loads((fresh.task / json.loads(out)["captures"][0]["path"]).read_text(encoding="utf-8"))["response"]
            check_eq("a character cut by the cap: still UTF-8 text, the half character dropped",
                     (stored["body_encoding"], stored["truncated"], len(stored["body"])), ("utf-8", True, cap - 1))
        finally:
            S.cleanup(fresh)
        # --- the limit: AT passes, BEYOND is a `timeout` log ref and no response file
        for label, seconds in (("AT the limit", 100), ("just beyond the limit", 100.001)):
            fresh = S.make_task(manual=("api",))
            try:
                http = S.FakeHttp({login: token, ("GET", get): MC.HttpResult(200, [], b"{}", seconds)})
                code, out, err = http_run(fresh, http, "--method", "GET", "--url", get)
                summary = json.loads(out)
                kinds = [(c["kind"], c["proves"]) for c in summary["captures"]]
                if seconds <= 100:
                    check_eq(f"http timeout {label}: passes - a request_response is saved", (code, kinds),
                             (0, [("request_response", ["request and response"])]))
                else:
                    check_eq(f"http timeout {label}: exit 1, a `timeout` log ref and no response saved", (code, kinds),
                             (1, [("log", ["timeout"])]))
            finally:
                S.cleanup(fresh)
        # --- a secret in a response is not saved
        fresh = S.make_task(manual=("api",))
        try:
            http = S.FakeHttp({login: token, ("GET", get): S.ok_json({"note": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig"})})
            code, out, err = http_run(fresh, http, "--method", "GET", "--url", get)
            check_eq("secret in a response: refused by pattern index", (code, "secret_content_patterns[3]" in err), (2, True))
            check_not_in("secret in a response: the match is nowhere", "eyJhbGci", err + out + S.tree_text(fresh.task))
            check("secret in a response: no capture of that call exists", not (fresh.attempt_dir(API_CASE) / "captures.jsonl").exists())
        finally:
            S.cleanup(fresh)
        # --- refusals
        http = S.FakeHttp({login: token})
        refused("an unknown method", ["http", "--task-root", str(t.task), "--case", API_CASE, "--method", "FETCH", "--url", get],
                "--method 'FETCH' is none of GET, POST")
        patch_backends(http=http)
        err = refused("a host outside the stands", ["http", "--task-root", str(t.task), "--case", API_CASE, "--method", "GET",
                                                    "--url", "http://evil.example.test/v1/x"], "Allowed hosts: ")
        refused("a state URL outside the stands", ["http", "--task-root", str(t.task), "--case", API_CASE, "--method", "GET",
                                                   "--url", get, "--state-url", "http://evil.example.test/"], "Allowed hosts: ")
        err = refused("phase `before`", ["http", "--task-root", str(t.task), "--case", API_CASE, "--method", "GET", "--url", get,
                                         "--phase", "before"], "pre_action | post_action | supporting")
        check_in("phase `before`: says what the old words became", "the old words", err)
        refused("a header with no colon", ["http", "--task-root", str(t.task), "--case", API_CASE, "--method", "GET", "--url", get,
                                           "--header", "nocolon"], "is not `Name: value`")
        refused("a missing body file", ["http", "--task-root", str(t.task), "--case", API_CASE, "--method", "POST", "--url", get,
                                        "--body-file", str(t.task / "nope.json")], "cannot be read")
        refused("a secret in a header", ["http", "--task-root", str(t.task), "--case", API_CASE, "--method", "GET", "--url", get,
                                         "--header", "X-Debug: password=\"abcdefgh12345678\""], "secret_content_patterns[1]")
        refused("a case id with ..", ["http", "--task-root", str(t.task), "--case", "../x", "--method", "GET", "--url", get],
                "goes up a folder")
        check("the refusals sent nothing", http.calls == [])
        # a stand that rejects the login
        http = S.FakeHttp({login: S.ok_json({"detail": "no"}, status=401), ("GET", get): S.ok_json({})})
        patch_backends(http=http)
        err = refused("a login the stand rejects", ["http", "--task-root", str(t.task), "--case", API_CASE, "--method", "GET",
                                                    "--url", get], "did not give a token (status 401)")
        check_not_in("a login the stand rejects: the password is not in the refusal", S.PASSWORD, err)
    finally:
        S.cleanup(t)


def element_wait():
    """An element lookup has its own limit (default 30 s, config manual_capture.element_wait_s); the page-load
    limit stays for goto. AT passes, BEYOND is a failed step with its screenshot - never a 180 s wait."""
    for value in (None, 0, -3, True, "30", float("nan"), float("inf")):
        cfg = {} if value is None else {"manual_capture": {"element_wait_s": value}}
        check_eq(f"element wait with config {value!r}: 30 s", MC.element_wait_for(cfg), 30)
    check_eq("element wait from config: 7.5 s", MC.element_wait_for({"manual_capture": {"element_wait_s": 7.5}}), 7.5)
    check_eq("element wait: a config whose manual_capture is not an object", MC.element_wait_for({"manual_capture": "x"}), 30)
    cases = (("click", "click button#a", "click:button#a"), ("fill", "fill input#a hi", "fill:input#a"),
             ("drag", "drag .pane 1 2", "drag:.pane"), ("wait <selector>", "wait .late", "wait:.late"),
             ("read", "read .v", "read:.v"))
    for limit_label, cfg, limit in (("default 30 s", None, 30), ("configured 5 s", S.config(manual_capture={"element_wait_s": 5}), 5)):
        for label, step, key in cases:
            for where, seconds in (("AT", limit), ("just BEYOND", limit + 0.001)):
                t = S.make_task(cfg=cfg)
                try:
                    code, out, err, browser = ui_run(t, steps=f"goto {UI}\n{step}\ncapture post_action completion\n",
                                                     browser=S.FakeBrowser(elapsed={key: seconds}))
                    summary = json.loads(out)
                    check_eq(f"{label} {where} the element limit ({limit_label}): the browser was given {limit} s for elements",
                             browser.opened[3], limit)
                    if where == "AT":
                        check_eq(f"{label} AT the element limit ({limit_label}): passes", (code, (summary["failed"] or {}).get("outcome")), (0, None))
                    else:
                        check_eq(f"{label} just BEYOND the element limit ({limit_label}): a failed step with its screenshot, not a timeout",
                                 (code, summary["failed"]["outcome"], [(c["kind"], c["phase"]) for c in summary["captures"]]),
                                 (1, "failed", [("image", "supporting")]))
                        check_in(f"{label} just BEYOND ({limit_label}): the detail names the element limit", f"the step completed after the element limit (took {seconds:.2f} s, limit {limit:g} s)",
                                 summary["failed"]["detail"])
                finally:
                    S.cleanup(t)
            if cfg is not None:
                break          # the configured limit is shown on one step; the default is walked on every step word
    # goto keeps the page-load limit: 70 + 30 = 100 s, far above the 30 s element limit
    t = S.make_task()
    try:
        code, out, err, _ = ui_run(t, steps=f"goto {UI}\n", browser=S.FakeBrowser(elapsed={"goto": 60}))
        check_eq("goto of 60 s (above the element limit, under the page-load limit) passes", code, 0)
    finally:
        S.cleanup(t)


def limits():
    """Every other limit the code introduces, AT and BEYOND it."""
    cap = MC.BODY_CAP
    # --- a REQUEST body is stored under the same cap as a response body
    post = f"{LOCAL}/v1/workflows/w1/validate"
    login = ("POST", f"{LOCAL}/v1/local-auth/login")
    for label, size, cut in (("request body AT 2 MB", cap, False), ("request body 1 byte BEYOND 2 MB", cap + 1, True)):
        t = S.make_task(manual=("api",))
        try:
            body = t.task / "body.bin"
            body.write_bytes(b"b" * size)
            http = S.FakeHttp({login: S.ok_json({"access_token": S.TOKEN}), ("POST", post): S.ok_json({"valid": True})})
            code, out, err = http_run(t, http, "--method", "POST", "--url", post, "--body-file", str(body))
            summary = json.loads(out)
            stored = json.loads((t.task / summary["captures"][0]["path"]).read_text(encoding="utf-8"))["request"]
            check_eq(f"{label}: stored bytes / truncated", (stored["body_bytes_stored"], stored["truncated"]), (cap, cut))
            check_eq(f"{label}: the limitation says it was the request, exactly when cut",
                     [("request body cut" in x) for x in summary["limitations"]], [True] if cut else [])
            check_eq(f"{label}: the real call carried the WHOLE body", len(http.calls[-1][3]), size)
        finally:
            S.cleanup(t)
    # --- a DOM value read is stored under the cap too
    for label, size, cut in (("read value AT 2 MB", cap, False), ("read value 1 byte BEYOND 2 MB", cap + 1, True)):
        t = S.make_task()
        try:
            code, out, err, _ = ui_run(t, browser=S.FakeBrowser(reads={".big": "x" * size}),
                                       steps=f"goto {UI}\nread .big\ncapture post_action completion\n")
            summary = json.loads(out)
            log = next(c for c in summary["captures"] if c["kind"] == "log")
            check_eq(f"{label}: stored size", len((t.task / log["path"]).read_bytes()), cap)
            check_eq(f"{label}: limitation exactly when cut", bool(summary["limitations"]), cut)
        finally:
            S.cleanup(t)
    # --- the step line keeps SUMMARY_DETAIL_CHARS of a read value; the file keeps it whole
    for label, size, expect in (("read value AT 300 characters", 300, 300), ("read value 301 characters", 301, 303)):
        t = S.make_task()
        try:
            code, out, err, _ = ui_run(t, browser=S.FakeBrowser(reads={".v": "y" * size}), steps=f"goto {UI}\nread .v\n")
            line = [s for s in jsonl(t.attempt_dir(UI_CASE) / "steps.jsonl") if s["step"] == "read .v"][0]
            check_eq(f"{label}: the step line's detail is {expect} characters", len(line["detail"]), expect)
            check_eq(f"{label}: the value is whole in its file", len(next((t.attempt_dir(UI_CASE)).glob("*read*")).read_text(encoding="utf-8")), size)
        finally:
            S.cleanup(t)
    # --- the name part of an evidence file (`<phase>-<label>`) is cut at 40 characters; `proves` keeps the whole word
    t = S.make_task()
    try:
        fits, long = "w" * 28, "v" * 29           # "post_action-" is 12 characters: 12 + 28 = 40 is AT the limit
        code, out, err, _ = ui_run(t, steps=f"goto {UI}\ncapture post_action {fits}\ncapture post_action {long}\n")
        captures = json.loads(out)["captures"]
        names = [Path(c["path"]).stem.split("-", 1)[1] for c in captures]
        check_eq("file name AT 40 characters: kept whole", names[0], f"post_action-{fits}")
        check_eq("file name 1 character BEYOND 40: cut at 40", (len(names[1]), names[1]), (40, f"post_action-{'v' * 28}"))
        check_eq("the capture still proves the whole word", [c["proves"] for c in captures], [[fits], [long]])
    finally:
        S.cleanup(t)
    # --- an attempt number: a123456 (six digits) is the largest name; seven digits is refused (tested in attempts())
    t = S.make_task()
    try:
        root = MC.case_root(t.task, UI_CASE)
        check_eq("attempt a123456 (six digits) is a name", MC.choose_attempt(root, "a123456"), "a123456")
    finally:
        S.cleanup(t)


def attempts():
    t = S.make_task()
    try:
        root = MC.case_root(t.task, UI_CASE)
        check_eq("no attempt yet: the first is a1", MC.choose_attempt(root, None), "a1")
        (root / "a1").mkdir(parents=True)
        check_eq("an open attempt is continued", MC.choose_attempt(root, None), "a1")
        (root / "a1" / "record.json").write_text("{}", encoding="utf-8")
        check_eq("a written attempt is closed: the next is a2", MC.choose_attempt(root, None), "a2")
        try:
            MC.choose_attempt(root, "a1")
            check("capturing into a written attempt is refused", False)
        except ValueError as exc:
            check_in("capturing into a written attempt is refused, naming the door", "--attempt a2", str(exc))
        (root / "a2").mkdir()
        (root / "a2" / "env_blocked.json").write_text("{}", encoding="utf-8")
        check_eq("an env_blocked attempt is closed too: the next is a3", MC.choose_attempt(root, None), "a3")
        check_eq("an explicit new name is taken", MC.choose_attempt(root, "a7"), "a7")
        for bad in ("a", "1", "a1x", "A1", "a-1", "../a1", "a1234567"):
            try:
                MC.choose_attempt(root, bad)
                check(f"attempt name {bad!r} is refused", False)
            except ValueError:
                check(f"attempt name {bad!r} is refused", True)
    finally:
        S.cleanup(t)


def k3_records():
    """K3: capture -> build -> a record the validators accept; with the controls."""
    # --- ui, pass: pre_action / post_action, before_change not_recorded for R-7
    t = S.make_task()
    try:
        seed_runtime_records(t)
        code, out, err, _ = ui_run(t)
        check_eq("K3 ui: capture ran", code, 0)
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "the scale grew from 1 to 1.2 and the pane moved by 40 px", "--masked")
        check_eq("K3 ui: `build --result pass` writes the block", code, 0)
        done = json.loads(out)
        record = json.loads((t.attempt_dir(UI_CASE) / "record.json").read_text(encoding="utf-8"))
        check_eq("K3 ui: the validator accepts the record", M.validate_record(record, t.task), [])
        check_eq("K3 ui: the phases are pre_action and post_action (never the old words)",
                 sorted({r["phase"] for r in record["evidence_refs"]}), ["post_action", "pre_action", "supporting"])
        check_eq("K3 ui: before_change is not_recorded for R-7 (no claims section in the register)",
                 record["before_change"], {"r": "R-7", "value": None, "ref": None, "source": "not_recorded"})
        check_eq("K3 ui: the result is the runner's own", record["result"], "pass")
        check_eq("K3 ui: the completion proof is the runner's line, copied",
                 [r["proves"] for r in record["evidence_refs"] if r["phase"] == "post_action"], [["completion"]])
        check("K3 ui: masked is acknowledged on every ref", all(r["mask_acknowledged"] is True for r in record["evidence_refs"]))
        check_eq("K3 ui: the record binds the running S6 dispatch", record["dispatch_id"], "S6-qa-runner-1")
        check("K3 ui: the steps the runner took are the record's steps_actual",
              any(s.startswith("click button[aria-label='Zoom in'] -> ok") for s in record["steps_actual"]) or
              any("Zoom in" in s for s in record["steps_actual"]), str(record["steps_actual"]))
        check_eq("K3 ui: the block is on disk", (t.task / done["block"]).is_file(), True)
        check_eq("K3 ui: the runtime identity is the probe's", record["runtime_identity"], "build-1")
        with t.patched():
            from coverage_contract import validate_manual_current
            check_eq("K3 ui: the controller-side check (hashes, pins, source, dispatch) accepts it too",
                     validate_manual_current(t.task, record), [])
        check_eq("K3 ui: a leaf of the old words is the SAME record (legacy alias): before/after still validate",
                 M.validate_record(_legacy(record), t.task), [])
        # --- C10: the attempt is written; build again is refused, naming the attempt and the door
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "again", "--masked")
        check_eq("C10: build on a written attempt is refused", code, 2)
        check_in("C10: the refusal names the attempt", "attempt a1 of " + UI_CASE + " is already written", err)
        check_in("C10: and the door", "--attempt a2", err)
    finally:
        S.cleanup(t)
    # --- tampered file
    t = S.make_task()
    try:
        seed_runtime_records(t)
        ui_run(t)
        first = next(iter(jsonl(t.attempt_dir(UI_CASE) / "captures.jsonl")))
        (t.task / first["path"]).write_bytes(b"tampered")
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
        check_eq("K3 control: a tampered file refuses the record", code, 2)
        check_in("K3 control: ... as an evidence hash mismatch", "evidence hash mismatch", err)
        check("K3 control: no block was written", not (t.task / "work" / "manual-blocks").exists())
    finally:
        S.cleanup(t)
    # --- pre_action only: pass refused with the door, inconclusive accepted (and never changed to something else)
    t = S.make_task()
    try:
        seed_runtime_records(t)
        # a `read` gives the attempt a text capture, so the helper's Then quotes stand and the refusal is the validator's
        # (HF8-19: without any text the quote rule refuses first, and says so; that is test_manual_rejudge's point)
        ui_run(t, steps=f"goto {UI}\ncapture pre_action initial\nread {VIEWPORT} style=transform\n",
               browser=S.FakeBrowser(reads={(VIEWPORT, "style=transform"): "matrix(1, 0, 0, 1, 0, 0)"}))
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
        check_eq("K3 control: pre_action only, `pass` is refused", code, 2)
        check_in("K3 control: the validator's words", "ui requires pre_action and post_action evidence", err)
        check_in("K3 control: and the door is named", "capture the post_action again", err)
        check_in("K3 control: ... or inconclusive", "`--result inconclusive`", err)
        code, out, err = build(t, UI_CASE, "--result", "inconclusive", "--actual", "the pane never settled", "--masked")
        check_eq("K3 control: inconclusive WITHOUT a limitation is refused", code, 2)
        check_in("K3 control: it asks for the limitation", "inconclusive requires a limitation", err)
        code, out, err = build(t, UI_CASE, "--result", "inconclusive", "--actual", "the pane never settled", "--masked",
                               "--limitation", "no post_action screenshot: the canvas stayed on Loading")
        check_eq("K3 control: pre_action only, `inconclusive` with a limitation is accepted", code, 0)
        record = json.loads((t.attempt_dir(UI_CASE) / "record.json").read_text(encoding="utf-8"))
        check_eq("K3 control: and it is written as inconclusive (build never changes --result)",
                 (record["result"], record["limitations"]),
                 ("inconclusive", ["no post_action screenshot: the canvas stayed on Loading"]))
    finally:
        S.cleanup(t)
    # --- FR-23 beyond ui: an api attempt with only a pre_action request is a recordable inconclusive
    t = S.make_task(manual=("api",))
    try:
        seed_runtime_records(t)
        get = f"{LOCAL}/v1/workflows/w1"
        http = S.FakeHttp({("POST", f"{LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}), ("GET", get): S.ok_json({"id": "w1"})})
        http_run(t, http, "--method", "GET", "--url", get, "--phase", "pre_action")
        code, out, err = build(t, API_CASE, "--result", "pass", "--actual", "x", "--masked")
        check_eq("FR-23: an api pass with no post_action evidence is refused", code, 2)
        check_in("FR-23: by the api rule", "api/cli requires request/output and post_action state evidence", err)
        code, out, err = build(t, API_CASE, "--result", "inconclusive", "--actual", "the POST never answered", "--masked",
                               "--limitation", "the validate call timed out")
        check_eq("FR-23: the same attempt as `inconclusive` with a limitation is accepted under the api policy", code, 0)
    finally:
        S.cleanup(t)
    # --- api, pass: pre_action GET, post_action POST + state, the runner's completion line
    t = S.make_task(manual=("api",))
    try:
        seed_runtime_records(t)
        get, post = f"{LOCAL}/v1/workflows/w1", f"{LOCAL}/v1/workflows/w1/validate"
        http = S.FakeHttp({("POST", f"{LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}),
                           ("GET", get): S.ok_json({"id": "w1"}), ("POST", post): S.ok_json({"valid": True})})
        http_run(t, http, "--method", "GET", "--url", get, "--phase", "pre_action", "--state-url", get)
        http_run(t, http, "--method", "POST", "--url", post, "--state-url", get, "--proves", "completion")
        code, out, err = build(t, API_CASE, "--result", "pass", "--actual", "validate answered 200 and the workflow is unchanged", "--masked")
        check_eq("K3 api: a request_response + post_action state + completion builds a valid pass record", code, 0)
        record = json.loads((t.attempt_dir(API_CASE) / "record.json").read_text(encoding="utf-8"))
        check_eq("K3 api: one stand identity brackets the attempt (first start, last end)",
                 (record["runtime_before"]["profile_id"], record["runtime_after"]["profile_id"]), ("api", "api"))
        check_eq("K3 api: expected is the plan's behaviour for the obligation", record["expected"],
                 [t.row("TS-12")["coverage_obligations"][0]["behavior"]])
    finally:
        S.cleanup(t)
    # --- `--phase before` / `capture before` are refused (checked in ui_refusals / http_edges); the claim fixture:
    registers = S.make_task(claims=True)
    try:
        text = (registers.task / "work" / "requirements-register.md").read_text(encoding="utf-8")
        check_eq("K3 claim (t-245 R-17 fixture): before_change is the claim row, `base:` reference kept",
                 M.before_change_for(text, ["R-17"]),
                 {"r": "R-17", "value": "400", "ref": "base:b9c0c4e:workflow.py:989", "source": "claim"})
        check_eq("K3 claim: R-7 has no claim row: not_recorded", M.before_change_for(text, ["R-7"])["source"], "not_recorded")
        check_eq("K3 claim: the first covered R that has a claim wins", M.before_change_for(text, ["R-7", "R-17"])["r"], "R-17")
        check_eq("K3 claim: no covered R at all: not_recorded with r None", M.before_change_for(text, []),
                 {"r": None, "value": None, "ref": None, "source": "not_recorded"})
        absent = text + "| R-7 | absent | absent | a control | diff:+x:3 | yes | Q1 |\n"
        check_eq("K3 claim: an `absent` before keeps its word and is its own reference",
                 M.before_change_for(absent, ["R-7"]), {"r": "R-7", "value": "absent", "ref": "absent", "source": "claim"})
        check_eq("K3 claim: a row with an empty before is no claim", M.before_change_for(
            text + "| R-9 |  | — | x | y | no | Q1 |\n", ["R-9"])["source"], "not_recorded")
    finally:
        S.cleanup(registers)
    # --- the same claim through a whole build: the register row of the case's own R
    t = S.make_task(claims=True)
    try:
        seed_runtime_records(t)
        reg = t.task / "work" / "requirements-register.md"
        reg.write_text(reg.read_text(encoding="utf-8") + "| R-7 | 1.0 | base:b9c0c4e:DiffCanvas.tsx:12 | 1.2 | diff:+x:3 | yes | Q1 |\n", encoding="utf-8")
        ui_run(t)
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "grew", "--masked")
        record = json.loads((t.attempt_dir(UI_CASE) / "record.json").read_text(encoding="utf-8"))
        check_eq("K3 claim: a build of a case whose R has a claim row writes `claim` with the base reference",
                 (code, record["before_change"]),
                 (0, {"r": "R-7", "value": "1.0", "ref": "base:b9c0c4e:DiffCanvas.tsx:12", "source": "claim"}))
        check_eq("K3 claim: and the record validates", M.validate_record(record, t.task), [])
    finally:
        S.cleanup(t)
    # --- before_change in a record is checked when present, optional when absent (legacy)
    t = S.make_task()
    try:
        seed_runtime_records(t)
        ui_run(t)
        build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
        record = json.loads((t.attempt_dir(UI_CASE) / "record.json").read_text(encoding="utf-8"))
        gone = {k: v for k, v in record.items() if k != "before_change"}
        check_eq("a record with no before_change (legacy) validates", M.validate_record(gone, t.task), [])
        for label, change in (("an unknown source", {"r": "R-7", "value": None, "ref": None, "source": "guess"}),
                              ("a claim with no ref", {"r": "R-7", "value": "400", "ref": "", "source": "claim"}),
                              ("a string", "400")):
            check_in(f"before_change {label} is refused", "before_change must be" if label != "a claim with no ref" else
                     "before_change from a claim needs r, value and ref",
                     "\n".join(M.validate_record(dict(record, before_change=change), t.task)))
    finally:
        S.cleanup(t)


def _legacy(record):
    """The same record as an old runner wrote it: before / after in place of pre_action / post_action, no before_change."""
    old = {k: v for k, v in record.items() if k != "before_change"}
    old["evidence_refs"] = [dict(r, phase={"pre_action": "before", "post_action": "after"}.get(r["phase"], r["phase"]))
                            for r in record["evidence_refs"]]
    return old


def build_refusals():
    t = S.make_task()
    try:
        ui_run(t)
        for label, args, needle in (
                ("no --masked", ["--result", "pass", "--actual", "x"], "common-rules.md"),
                ("an empty --actual", ["--result", "pass", "--actual", "  ", "--masked"], "--actual is empty"),
                ("a bad --result", ["--result", "maybe", "--actual", "x", "--masked"], "none of pass | fail | inconclusive"),
                ("an unknown attempt", ["--result", "pass", "--actual", "x", "--masked", "--attempt", "a9"], "no captured files")):
            code, out, err = build(t, UI_CASE, *args)
            check_eq(f"build {label}: refused", code, 2)
            check_in(f"build {label}: says {needle!r}", needle, err)
        code, out, err = S.run(["build", "--task-root", str(t.task)], main=M.main, command="manual_evidence.py build")
        check_eq("build with no --case/--result/--actual: refused with the shape", code, 2)
        check_in("build: and names what is missing", "--case, --result, --actual missing", err)
        code, out, err = build(t, "never-captured", "--result", "pass", "--actual", "x", "--masked")
        check_in("build of a case that was never prepared: says prepare writes the request", "`manual_evidence.py prepare` writes it", err)
        (MC.case_root(t.task, "never-captured")).mkdir(parents=True)
        (MC.case_root(t.task, "never-captured") / "request.json").write_text(json.dumps({"case": "never-captured"}), encoding="utf-8")
        code, out, err = build(t, "never-captured", "--result", "pass", "--actual", "x", "--masked")
        check_in("build of a case nothing was captured for: says capture first", "nothing was captured", err)
        # no running dispatch for the case
        t.state(dispatch_status="accepted")
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
        check_in("build with no running S6 dispatch holding the case: refused naming who opens it",
                 "no S6 dispatch is running", err)
        t.state(scope=[API_CASE])
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
        check_in("build with a case outside the dispatch's scope: refused", "no S6 dispatch is running", err)
        # a refused request.json
        t.state()
        (MC.case_root(t.task, UI_CASE) / "request.json").write_text(json.dumps(
            {"refused": {"reason": "no gate A is current", "door": "gate A approves again"}}), encoding="utf-8")
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
        check_in("build of a case whose prepare was refused: says so, with the door", "no gate A is current - gate A approves again", err)
    finally:
        S.cleanup(t)


def seed_runtime_records(t):
    """The runs of this story that `runtime_probe.py` records (`evidence/runtime-provenance-*.json`, one per profile):
    `build` binds a probe to the checkout revision a run of THIS story recorded for the profile (t-271 F1). Written
    only for a profile the fixture holds no record of, so it is a no-op once the scaffold writes them itself."""
    folder = t.task / "evidence"
    folder.mkdir(exist_ok=True)
    held = set()
    for path in folder.glob("runtime-provenance-*.json"):
        held.add(json.loads(path.read_text(encoding="utf-8")).get("profile_id"))
    for profile in ("e2e-ui", "api"):
        if profile not in held:
            (folder / f"runtime-provenance-{profile}.json").write_text(
                json.dumps({"profile_id": profile, "expected_source_revision": S.SOURCE}), encoding="utf-8")


def one_profile_per_attempt():
    """t-277 F4 (critic t-275): `http` without --attempt joined the latest open attempt even when it held a `ui`
    session - the cleanup DELETE the runner is told to make after a ui case - and `build` then refused the pair as
    "provenance changed" (e2e-ui at the start, api at the end). One attempt is one profile now."""
    # --- choose_attempt_for: the rule on its own, with the edges
    t = S.make_task()
    try:
        root = MC.case_root(t.task, UI_CASE)

        def probes_of(attempt, *profiles, raw=()):
            folder = root / attempt
            folder.mkdir(parents=True, exist_ok=True)
            lines = [json.dumps({"when": "start", "profile": p, "probe": {}}) for p in profiles] + list(raw)
            (folder / "probes.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        check_eq("F4: no attempt yet: a1, no note", MC.choose_attempt_for(root, "api"), ("a1", ""))
        probes_of("a1")
        check_eq("F4: an open attempt nothing was probed in is joined (nothing contradicts)", MC.choose_attempt_for(root, "api"), ("a1", ""))
        probes_of("a1", "api")
        check_eq("F4: an open api attempt is joined by an api call (the same profile)", MC.choose_attempt_for(root, "api"), ("a1", ""))
        probes_of("a1", "api", raw=["not json", "[1]", json.dumps({"profile": 7})])
        check_eq("F4: a broken line or a row with no word for a profile is ignored", MC.attempt_profiles(root / "a1"), ["api"])
        probes_of("a1", "e2e-ui")
        check_eq("F4: an open ui attempt is NOT joined by an api call: a2, and the note says why",
                 MC.choose_attempt_for(root, "api"), ("a2", "attempt a2 opened: a1 holds e2e-ui captures"))
        probes_of("a1", "e2e-ui", "api")
        check_eq("F4: an attempt already holding two profiles (forced) is never joined, and both are named",
                 MC.choose_attempt_for(root, "api"), ("a2", "attempt a2 opened: a1 holds e2e-ui and api captures"))
        (root / "a1" / "record.json").write_text("{}", encoding="utf-8")
        check_eq("F4: a written attempt: the next, no note (the old rule)", MC.choose_attempt_for(root, "api"), ("a2", ""))
        check_eq("F4: the old function is unchanged for a caller that names no profile", MC.choose_attempt(root, None), "a2")
    finally:
        S.cleanup(t)
    # --- the cmp2 shape: ui TC_007 -> a1, a cleanup DELETE -> a2, build --attempt a1 validates
    t = S.make_task()
    try:
        seed_runtime_records(t)
        get = f"{LOCAL}/v1/workflows/w1"
        http = S.FakeHttp({("POST", f"{LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}),
                           ("DELETE", get): S.ok_json({"deleted": True}), ("GET", get): S.ok_json({"id": "w1"})})
        code, out, err, _ = ui_run(t)
        check_eq("F4: the ui session is a1 (e2e-ui)", (code, json.loads(out)["attempt"], MC.attempt_profiles(t.attempt_dir(UI_CASE))),
                 (0, "a1", ["e2e-ui"]))
        code, out, err = http_run(t, http, "--method", "DELETE", "--url", get, case=UI_CASE)
        summary = json.loads(out)
        check_eq("F4: the cleanup DELETE of the same case opens a2", (code, summary["attempt"]), (0, "a2"))
        check_eq("F4: and says it in ONE line (stderr; stdout stays one JSON object)", err.strip(), "attempt a2 opened: a1 holds e2e-ui captures")
        check_eq("F4: a1 kept its one profile, a2 holds api only",
                 (MC.attempt_profiles(t.attempt_dir(UI_CASE, "a1")), MC.attempt_profiles(t.attempt_dir(UI_CASE, "a2"))),
                 (["e2e-ui"], ["api"]))
        check("F4: a1 holds no capture of the DELETE",
              all(c["command"] == "ui" for c in jsonl(t.attempt_dir(UI_CASE, "a1") / "captures.jsonl")))
        code, out, err = http_run(t, http, "--method", "GET", "--url", get, case=UI_CASE)
        check_eq("F4 control: a second http call joins the open a2 (same profile), with no line", (json.loads(out)["attempt"], err.strip()), ("a2", ""))
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "grew", "--masked")
        check_eq("F4: build with no --attempt takes the latest (the cleanup a2): a ui record cannot be made of it", code, 2)
        check_in("F4: ... the validator says what the ui case lacks", "ui requires pre_action and post_action evidence", err)
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "the scale grew from 1 to 1.2", "--masked", "--attempt", "a1")
        check_eq("F4: build --attempt a1 --result pass writes the block", (code, json.loads(out)["attempt"]), (0, "a1"))
        record = json.loads((t.attempt_dir(UI_CASE) / "record.json").read_text(encoding="utf-8"))
        check_eq("F4: and the record validates", M.validate_record(record, t.task), [])
        check_eq("F4: its one stand identity is e2e-ui, start to end",
                 (record["runtime_before"]["profile_id"], record["runtime_after"]["profile_id"]), ("e2e-ui", "e2e-ui"))
        # the old check stays as the backstop: a record whose end probe is another profile is refused by validate
        torn = dict(record, runtime_after=dict(record["runtime_after"], profile_id="api"))
        check_in("F4 backstop: validate still refuses a record bracketed by two profiles",
                 "runtime provenance changed during the attempt", "\n".join(M.validate_record(torn, t.task)))
    finally:
        S.cleanup(t)
    # --- negative: both forced into one attempt with --attempt (the person's door) -> build names both and refuses
    t = S.make_task()
    try:
        seed_runtime_records(t)
        get = f"{LOCAL}/v1/workflows/w1"
        http = S.FakeHttp({("POST", f"{LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}),
                           ("DELETE", get): S.ok_json({"deleted": True})})
        ui_run(t)
        code, out, err = http_run(t, http, "--method", "DELETE", "--url", get, "--attempt", "a1", case=UI_CASE)
        check_eq("F4 negative: an explicit --attempt a1 is taken as written, with no note", (code, json.loads(out)["attempt"], err.strip()), (0, "a1", ""))
        check_eq("F4 negative: a1 now holds both profiles", MC.attempt_profiles(t.attempt_dir(UI_CASE)), ["e2e-ui", "api"])
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked", "--attempt", "a1")
        check_eq("F4 negative: build over the mixed attempt is refused", code, 2)
        check_in("F4 negative: with the old words (provenance changed)", "provenance changed", err)
        check_in("F4 negative: naming both profiles", "e2e-ui and api", err)
        check_in("F4 negative: and the way out", "its own attempt", err)
        check("F4 negative: no block and no record were written",
              not (t.task / "work" / "manual-blocks").exists() and not (t.attempt_dir(UI_CASE) / "record.json").exists())
    finally:
        S.cleanup(t)


# --------------------------------------------------------------------------------------------
# t-292: `login by code` proves the landing (K1..K14 of the spec)
# --------------------------------------------------------------------------------------------
# Measured 02.10 (experiments/cmp2-15045/rehearsal/11-login-probe.txt): after the submit the page stays on
# /auth/sign-in for about 3 s and then lands on its own; the factory said "ok" after `networkidle` and the role's next
# `goto` cut the login off. The fake (scaffold.FakeBrowser) scripts exactly that, on its own clock: it proves the
# factory's LOOP. The Playwright primitives (cookie_names, field_visible, page_words, pause) are proven only by a live
# capture on the stand, which the Lead runs after acceptance (FR-33).
STEPS_GOTO = f"goto {UI}\ncapture post_action completion\n"
LANDING_LIMIT = 100          # make_task's stand: measured page load 70 s + 30 s


def ui_recipe(landed="default", **over):
    """The factory's `ui` login recipe as a config override would carry it; `landed=None` drops the rule."""
    recipe = json.loads(json.dumps(MC.spec()["login"]["ui"]))
    recipe.update(over)
    if landed is None:
        recipe.pop("landed", None)
    elif landed != "default":
        recipe["landed"] = landed
    return recipe


def login_cfg(recipe="absent", **login):
    """A config whose `manual_capture.login` carries `ui` (a recipe or None) and whatever else is given."""
    kinds = dict(login)
    if recipe != "absent":
        kinds["ui"] = recipe
    return S.config(manual_capture={"login": kinds})


# The package proves a landing without a cookie (the sign-in field being gone); a project that names its session
# cookie in config gets the stronger proof. K1-K3 run with such a project config.
COOKIE_CFG = login_cfg(ui_recipe(landed={"url_not": ["/auth/sign-in", "openid-connect"], "session_cookie": S.SESSION_COOKIE}))


def landing_run(browser, cfg=None, steps=STEPS_GOTO, extra=()):
    t = S.make_task(cfg=cfg)
    code, out, err, _ = ui_run(t, steps=steps, browser=browser, extra=extra)
    return t, code, out, err


def login_step(t, case=UI_CASE):
    """The first line of the attempt's steps.jsonl (the login); a stand-in line when there is none, so that a broken
    loop is a red check and never a crash."""
    path = t.attempt_dir(case) / "steps.jsonl"
    rows = jsonl(path) if path.is_file() else []
    return rows[0] if rows else {"step": "", "outcome": "no steps.jsonl", "detail": ""}


def stdout_json(out):
    """The ONE JSON object a call printed, or {} when it printed none (the checks then say what is missing)."""
    try:
        return json.loads(out)
    except ValueError:
        return {}


def blocked_row(out):
    return stdout_json(out).get("env_blocked") or {}


def landing_late():
    """K1: the sign-in URL for three polls, then `/` with the cookie: the login is ok only AFTER the landing, and the
    steps file's first `goto` comes after the landing poll - never while the page is on the sign-in address."""
    browser = S.FakeBrowser(lands_at=3)
    t, code, out, err = landing_run(browser, cfg=COOKIE_CFG)
    try:
        check_eq("K1 late landing: exit 0", code, 0)
        first = login_step(t)
        check_eq("K1: steps.jsonl line 1 is `login by code`, ok", (first["step"], first["outcome"]), ("login by code", "ok"))
        check_in("K1: and says where it landed", "landed on / in ", first["detail"])
        check_in("K1: and what proved it (the cookie)", "cookie testproject1_access_token", first["detail"])
        landings = [i for i, e in enumerate(browser.events) if e[0] == "poll" and e[2] == S.HOME_URL]
        check("K1: the login was LOOKED AT before the steps ran (a landing poll exists)", bool(landings), str(browser.events))
        landing = landings[0] if landings else len(browser.events)
        gotos = [i for i, e in enumerate(browser.events) if e[0] == "goto"]
        check_eq("K1: the landing poll is poll 3 (three looks at the sign-in address before it)",
                 browser.events[landing][1] if landings else None, 3)
        check("K1: the first goto of the steps file runs after the landing poll", bool(gotos) and gotos[0] > landing, str(browser.events))
        check("K1: no goto at all while the page was on the sign-in address",
              all(e[0] != "goto" for e in browser.events[:landing]), str(browser.events[:landing]))
        check("K1: the loop paused between the looks (on the browser's own timer)",
              [e[0] for e in browser.events[:landing]].count("pause") == 3)
    finally:
        S.cleanup(t)


def landing_never():
    """K2: the page never leaves the sign-in address: exit 3, env_blocked owner `user`, do_not_retry, the account
    named by its NAMES, the page's words, no captures and no image, and `build` gives the env_blocked door."""
    words = "Please, sign in to continue. Sign In"
    browser = S.FakeBrowser(urls=[S.SIGN_IN_URL], cookies_at=None, field_gone_at=None, words=words)
    t, code, out, err = landing_run(browser, cfg=COOKIE_CFG)
    try:
        row = blocked_row(out)
        check_eq("K2 never lands: exit 3 and the outcome is env_blocked", (code, stdout_json(out).get("outcome")), (3, "env_blocked"))
        check_eq("K2: owner `user` (the stand or its test account) and do_not_retry", (row.get("owner"), row.get("do_not_retry")), ("user", True))
        step = login_step(t)
        check_eq("K2: steps.jsonl `login by code` is failed", (step["step"], step["outcome"]), ("login by code", "failed"))
        for needle in ("/auth/sign-in", words, "AUTH_USERNAME", "harness/.env", "within 100 s", "still on a sign-in address",
                       "no cookie testproject1_access_token", "names only"):
            check_in(f"K2: the detail holds {needle!r}", needle, step["detail"])
        check_eq("K2: the same line is the env_blocked probe line", row.get("probe_line"), "login by code: " + step["detail"])
        check_in("K2: the remedy names the account's keys and the file, and the way on", "AUTH_USERNAME / AUTH_PASSWORD in harness/.env", row.get("remedy", ""))
        check_in("K2: and says not to capture again before the cause is gone", "Do not capture this case again", row.get("remedy", ""))
        check_eq("K2: after the login the browser did nothing but close", ([c[0] for c in browser.calls], browser.closed), (["login"], True))
        check_not_in("K2: no goto, no screenshot", "screenshot", str(browser.calls))
        folder = t.attempt_dir(UI_CASE)
        check("K2: no captures.jsonl and no image", not (folder / "captures.jsonl").exists() and not list(folder.glob("*.png")))
        blocked_file = folder / "env_blocked.json"
        written = json.loads(blocked_file.read_text(encoding="utf-8")) if blocked_file.is_file() else {}
        check_eq("K2: env_blocked.json is written, with do_not_retry", (written.get("owner"), written.get("do_not_retry"), written.get("id")), ("user", True, UI_CASE))
        check_in("K2: stderr says the login did not land and not to capture again", "the login by code did not land", err)
        check_in("K2: ... and the door: env_blocked[] and the halt", "put it in env_blocked[] with this line and halt the block", err)
        check_eq("K2: the end probe still ran (the stand is identified)", [p["when"] for p in jsonl(folder / "probes.jsonl")], ["start", "end"])
        code, out, err = build(t, UI_CASE, "--result", "pass", "--actual", "x", "--masked")
        check_eq("K2: `build` has no record to make", code, 2)
        check_in("K2: and gives the env_blocked door", "env_blocked[]", err)
        check_not_in("K2: and does NOT say `capture first`", "capture first", err)
        check_in("K2: and says the login did not land and not to capture again", "do not capture it again", err)
    finally:
        S.cleanup(t)
    # control (negative form of K2): the same stand that lands has no env_blocked.json and no do_not_retry
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=1))
    try:
        check("K2 control: a login that lands writes no env_blocked.json", code == 0 and not (t.attempt_dir(UI_CASE) / "env_blocked.json").exists())
    finally:
        S.cleanup(t)
    # the end probe failing wins: the stand not being identified is the more basic cause (no do_not_retry on it)
    t = S.make_task()
    try:
        browser = S.FakeBrowser(urls=[S.SIGN_IN_URL], cookies_at=None, field_gone_at=None)
        seen = []

        def second_fails(spec):
            seen.append(1)
            if len(seen) == 2:
                raise RuntimeError("the stand went away")
            return S.probe()
        patch_backends(browser, probes=second_fails)
        steps = _write(t, STEPS_GOTO)
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        row = blocked_row(out)
        check_eq("K2 order: a failed end probe is reported as the stand not identified, not as the login",
                 (code, "do_not_retry" in row, "runtime probe" in row.get("probe_line", "")), (3, False, True))
    finally:
        S.cleanup(t)


def landing_proofs():
    """K3: the URL leaves the sign-in address but the cookie never comes: not landed. K4: no cookie named: the field
    being gone is the proof, and the field still visible to the limit is a failure."""
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=0, cookies_at=None), cfg=COOKIE_CFG)
    try:
        step = login_step(t)
        row = blocked_row(out)
        check_eq("K3 URL left, no cookie: exit 3, `user`", (code, row.get("owner")), (3, "user"))
        check_in("K3: the detail says which proof is missing", "no cookie testproject1_access_token", step["detail"])
        check_not_in("K3: and does not say the page is still on a sign-in address (the URL did leave)", "sign-in address", step["detail"])
    finally:
        S.cleanup(t)
    # the same stand with a cookie: lands (the control of K3)
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=0))
    try:
        check_eq("K3 control: URL and cookie together land", code, 0)
    finally:
        S.cleanup(t)
    # K4: no cookie named in the override
    no_cookie = login_cfg(ui_recipe(landed={"url_not": ["/auth/sign-in", "openid-connect"]}))
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=2, cookies_at=None), cfg=no_cookie)
    try:
        step = login_step(t)
        check_eq("K4 no cookie named, the field gone: ok", (code, step["outcome"]), (0, "ok"))
        check_in("K4: and the proof is the field", "the sign-in field is gone", step["detail"])
        check_not_in("K4: a named `landed` rule is not the weak proof", "weak proof", step["detail"])
    finally:
        S.cleanup(t)
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=0, field_gone_at=None, cookies_at=None), cfg=no_cookie)
    try:
        step = login_step(t)
        check_eq("K4 the field still visible to the limit: exit 3, failed", (code, step["outcome"]), (3, "failed"))
        check_in("K4: and the detail says so", "the sign-in field is still visible", step["detail"])
    finally:
        S.cleanup(t)
    # E1 / K8: an empty `url_not` is no URL condition - and never an ok on the URL alone
    empty = login_cfg(ui_recipe(landed={"url_not": [], "session_cookie": "testproject1_access_token"}))
    t, code, out, err = landing_run(S.FakeBrowser(urls=[S.SIGN_IN_URL, S.SIGN_IN_URL, S.HOME_URL], cookies_at=2), cfg=empty)
    try:
        check_eq("K8 `url_not: []` with a cookie named: ok when the cookie appears on a stand URL", (code, login_step(t)["outcome"]), (0, "ok"))
    finally:
        S.cleanup(t)
    t, code, out, err = landing_run(S.FakeBrowser(urls=[S.HOME_URL], cookies_at=None), cfg=empty)
    try:
        check_eq("K8 control: `url_not: []` and no cookie ever: failed (the URL alone never proves a login)", code, 3)
    finally:
        S.cleanup(t)


def landing_limit():
    """K5: AT the limit lands; one poll beyond fails; the last look is AT the limit and never later."""
    polls_to_limit = int(LANDING_LIMIT / MC.LANDING_POLL_S)
    for label, lands_at, expect in (("first true AT the limit (poll 400, 100 s)", polls_to_limit, 0),
                                    ("first true one poll beyond the limit (poll 401, 100.25 s)", polls_to_limit + 1, 3)):
        browser = S.FakeBrowser(lands_at=lands_at)
        t, code, out, err = landing_run(browser)
        try:
            check_eq(f"K5 {label}: exit {expect}", code, expect)
            check_eq(f"K5 {label}: nothing looked later than the limit", max(e[1] for e in browser.events if e[0] == "poll") * MC.LANDING_POLL_S <= LANDING_LIMIT, True)
        finally:
            S.cleanup(t)
    # the loop on its own: the failure's elapsed is at most the limit, and the last poll is AT it
    browser = S.FakeBrowser(lands_at=polls_to_limit + 1)
    patch_backends(browser)
    result = MC.await_landing(browser, ui_recipe(), set(MC.stand_hosts(S.config())), LANDING_LIMIT)
    check_eq("K5 loop: not landed, elapsed <= the limit", (result["landed"], result["elapsed_s"] <= LANDING_LIMIT), (False, True))
    check_eq("K5 loop: and the last poll was poll 400 (AT the limit)", browser.polls, polls_to_limit + 1)
    browser = S.FakeBrowser(lands_at=polls_to_limit)
    patch_backends(browser)
    result = MC.await_landing(browser, ui_recipe(), set(MC.stand_hosts(S.config())), LANDING_LIMIT)
    check_eq("K5 loop: landed AT the limit, elapsed 100.0", (result["landed"], result["elapsed_s"]), (True, 100.0))
    # a limit that is not a multiple of the poll: the last pause is the remainder, never more
    browser = S.FakeBrowser(lands_at=10_000)
    patch_backends(browser)
    result = MC.await_landing(browser, ui_recipe(), set(MC.stand_hosts(S.config())), 0.6)
    pauses = [round(e[1], 6) for e in browser.events if e[0] == "pause"]
    check_eq("K5 loop: a 0.6 s limit pauses 0.25, 0.25, 0.1 and looks last AT 0.6", (pauses, result["elapsed_s"]), ([0.25, 0.25, 0.1], 0.6))
    result = MC.await_landing(S.FakeBrowser(lands_at=10_000), ui_recipe(), set(MC.stand_hosts(S.config())), 0)
    check("K5 loop: a limit of 0 looks once and fails", result["landed"] is False)


def landing_secrets():
    """K6: no credential, no token and no auth code in any saved byte or on stdout/stderr - the words, the landed URL
    and the failing URL. AT and BEYOND the words limit; the unreadable words are said."""
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig"
    sentinel = "SENTINEL-CODE-1"
    # (a) landed on `/?code=...`: ok, and the code is nowhere
    browser = S.FakeBrowser(urls=[f"{S.HOME_URL}?code={sentinel}&state=s#frag"], lands_at=0)
    t, code, out, err = landing_run(browser)
    try:
        check_eq("K6 (a) landed on a URL with an auth code in its query: ok", code, 0)
        check_not_in("K6 (a): the code is in no saved byte, nor on stdout/stderr", sentinel, S.tree_text(t.task) + out + err)
        check_not_in("K6 (a): nor the fragment", "frag", S.tree_text(t.task) + out + err)
    finally:
        S.cleanup(t)
    # (b) not landed, on a URL with a code, the page's words hold the account and a token
    words = f"Wrong credentials for {S.USER} / {S.PASSWORD}. Sign In"
    browser = S.FakeBrowser(urls=[f"{S.SIGN_IN_URL}?code={sentinel}&state=s#frag"], cookies_at=None, field_gone_at=None, words=words)
    t, code, out, err = landing_run(browser)
    try:
        leak = S.tree_text(t.task) + out + err
        check_eq("K6 (b): not landed, exit 3", code, 3)
        for secret in (S.USER, S.PASSWORD, sentinel, "frag"):
            check_not_in(f"K6 (b): {secret[:12]}... is in no saved byte, nor on stdout/stderr", secret, leak)
        check_in("K6 (b): the account in the page's words became [redacted]", "[redacted]", login_step(t)["detail"])
        check_in("K6 (b): the failing URL is kept without its query", "http://localhost:5173/auth/sign-in,", login_step(t)["detail"])
    finally:
        S.cleanup(t)
    browser = S.FakeBrowser(urls=[S.SIGN_IN_URL], cookies_at=None, field_gone_at=None, words=f"token {jwt}")
    t, code, out, err = landing_run(browser)
    try:
        leak = S.tree_text(t.task) + out + err
        check_not_in("K6 (c): a JWT-shaped string in the words is nowhere", "eyJhbGci", leak)
        check_in("K6 (c): the words are not kept, and the pattern is named by its index", "(not kept: matches secret_content_patterns[3])", login_step(t)["detail"])
    finally:
        S.cleanup(t)
    # the words limit: AT 120 characters whole, 121 cut with `...`; empty words are said (FR-41)
    creds = MC.Credentials(S.USER, S.PASSWORD, "harness/.env", "AUTH_USERNAME", "AUTH_PASSWORD")
    cfg = S.config()

    def detail(words, error=""):
        return MC._login_failure_detail({"url": S.SIGN_IN_URL, "missing": ["still on a sign-in address"], "words": words, "error": error},
                                        LANDING_LIMIT, creds, cfg)
    check_in("K6 words AT 120 characters: whole, no cut mark", "\"" + "w" * 120 + "\"", detail("w" * 120))
    cut = detail("w" * 121)
    check_eq("K6 words 1 BEYOND 120: cut at 120 with `...`", ("\"" + "w" * 120 + "...\"" in cut, "w" * 121 in cut), (True, False))
    check_in("K6 no words at all: said, not omitted", "the page's words could not be read", detail(""))
    check_not_in("K6 no words: no empty quotes", "the page shows", detail(""))
    check_not_in("K6 the account's value replaced even when it is all the page says", S.USER, detail(S.USER))
    # the 300-character cut of the step line takes words, never the names
    long_line = MC._detail(detail("x" * 120, error="e" * 120))
    for needle in ("AUTH_USERNAME", "harness/.env"):
        check_in(f"K6 the step line's cut keeps {needle} (the names stand before the words)", needle, long_line)
    # the landed URL has no query or fragment, whatever it carried
    check_eq("K6 `_safe_url`: scheme://host/path only",
             MC._safe_url("http://user:pw@localhost:5173/a/b?code=X&y=1#f"), "http://localhost:5173/a/b")
    check_eq("K6 `_safe_url`: about:blank and chrome-error stay readable", (MC._safe_url("about:blank"), MC._safe_url("chrome-error://chromewebdata/?x=1")),
             ("about:blank", "chrome-error://chromewebdata/"))
    check_eq("K6 `_safe_url`: a bad port or nothing at all is empty, never a raise", (MC._safe_url("http://h:99999999/x"), MC._safe_url(""), MC._safe_url(None)), ("", "", ""))


def landing_recipe_refusals():
    """K7: a malformed `landed` is the CALL's fault: exit 2, the key named with its expected shape and default, and no
    attempt folder (a refusal like every other one). Control (K14): the default and a good override run."""
    cases = (("url_not is a string", {"url_not": "x"}, "manual_capture.login.ui.landed.url_not"),
             ("url_not holds an empty string", {"url_not": [""]}, "manual_capture.login.ui.landed.url_not"),
             ("url_not holds a number", {"url_not": [1]}, "manual_capture.login.ui.landed.url_not"),
             ("url_not is an object", {"url_not": {"a": 1}}, "manual_capture.login.ui.landed.url_not"),
             ("session_cookie is empty", {"session_cookie": ""}, "manual_capture.login.ui.landed.session_cookie"),
             ("session_cookie is a number", {"session_cookie": 5}, "manual_capture.login.ui.landed.session_cookie"),
             ("session_cookie is a list", {"session_cookie": ["a"]}, "manual_capture.login.ui.landed.session_cookie"))
    for label, landed, key in cases:
        t = S.make_task(cfg=login_cfg(ui_recipe(landed=landed)))
        try:
            browser = S.FakeBrowser()
            patch_backends(browser)
            steps = _write(t, STEPS_GOTO)
            code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
            check_eq(f"K7 {label}: refused (exit 2)", code, 2)
            check_in(f"K7 {label}: the key is named", key, err)
            check_in(f"K7 {label}: with the expected shape", "Expected ", err)
            check_in(f"K7 {label}: and the cure is named", "leave", err)
            check(f"K7 {label}: no attempt folder, no browser, no probe", not MC.case_root(t.task, UI_CASE).exists() and browser.opened is None)
        finally:
            S.cleanup(t)
    # the rule on its own: absent -> defaults; null cookie is none
    check_eq("K7 landing_rule: no `landed` at all", MC.landing_rule({}), ([], None))
    check_eq("K7 landing_rule: `landed` with a null cookie", MC.landing_rule({"landed": {"url_not": ["/x"], "session_cookie": None}}), (["/x"], None))
    check_eq("K7 landing_rule: the factory's own recipe", MC.landing_rule(ui_recipe()), (["/auth/sign-in", "openid-connect"], None))
    # a refusal on a project with NO login at all is the same refusal (the rule is read beside read_login, before anything)
    t = S.make_task(cfg=S.config(environment={}, manual_capture={"login": {"ui": ui_recipe(landed={"url_not": "x"})}}))
    try:
        patch_backends(S.FakeBrowser())
        steps = _write(t, STEPS_GOTO)
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        check_eq("K7: a malformed rule is refused even where no login file is named (nothing half-valid is kept)", code, 2)
    finally:
        S.cleanup(t)


def landing_off_stand():
    """K9 (Q5): a URL that is not http(s) on a configured stand host never lands, however gone the field is."""
    no_cookie = login_cfg(ui_recipe(landed={"url_not": ["/auth/sign-in"]}))
    for label, url in (("chrome-error", "chrome-error://chromewebdata/"), ("about:blank", "about:blank"),
                       ("another host", "http://evil.example.test/"), ("a stand host on the wrong port", "http://localhost:9999/"),
                       ("a URL with a user:password part", "http://u:p@localhost:5173/")):
        t, code, out, err = landing_run(S.FakeBrowser(urls=[url], lands_at=0), cfg=no_cookie)
        try:
            step = login_step(t)
            check_eq(f"K9 {label}: not landed at the limit (field gone, no cookie named)", (code, step["outcome"]), (3, "failed"))
            check_in(f"K9 {label}: and the detail says it is not a stand address", "not on a stand address", step["detail"])
        finally:
            S.cleanup(t)
    t, code, out, err = landing_run(S.FakeBrowser(urls=["http://localhost:5173/workflows/my"], lands_at=0), cfg=no_cookie)
    try:
        check_eq("K9 control: a stand URL with the field gone lands", code, 0)
    finally:
        S.cleanup(t)


def landing_errors():
    """K10 (E9): a primitive that raises is never a proof. Errors on polls 0-1 and a landing at poll 2: ok; errors to
    the limit: failed, and the detail names the error."""
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=2, errors_at={0, 1}))
    try:
        check_eq("K10 errors on polls 0 and 1, landing at poll 2: ok", (code, login_step(t)["outcome"]), (0, "ok"))
    finally:
        S.cleanup(t)
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=0, errors_at=set(range(1000))))
    try:
        step = login_step(t)
        check_eq("K10 errors to the limit: failed (an error is never a proof)", (code, step["outcome"]), (3, "failed"))
        check_in("K10: the detail names the error", "the last error was: Execution context was destroyed", step["detail"])
    finally:
        S.cleanup(t)
    # the browser cannot even wait: nothing more can be proven, and it is said at once (not a loop to the limit)
    browser = S.FakeBrowser(lands_at=10_000)
    browser.pause = lambda seconds: (_ for _ in ()).throw(MC.StepFailed("Target page, context or browser has been closed"))
    result = MC.await_landing(browser, ui_recipe(), set(MC.stand_hosts(S.config())), LANDING_LIMIT)
    check_eq("K10: a pause that fails ends the wait, with the error", (result["landed"], "has been closed" in result["error"], browser.polls), (False, True, 1))


def landing_data_and_overrides():
    """K11: the factory's default carries `landed`. K12 (Q6, Q7): a recipe is looked up per kind. Weak proof (E6)."""
    data = json.loads(MC.SPEC_PATH.read_text(encoding="utf-8"))
    check_eq("K11 default data: `login.ui.landed` is in the data file",
             data["login"]["ui"]["landed"], {"url_not": ["/auth/sign-in", "openid-connect"], "session_cookie": None})
    check_in("K11: and the file's note explains it", "`login.ui.landed` says how code proves the login landed", data["note"])
    spec_data = MC.spec()
    # the lookup, on its own
    only_ui = S.config(manual_capture={"login": {"ui": ui_recipe(path="/x")}})
    check_eq("K12 lookup: a config with only `ui` replaces `ui` whole", MC.login_recipe(only_ui, spec_data, "ui")["path"], "/x")
    check_eq("K12 lookup: ... and keeps the factory's `http`", MC.login_recipe(only_ui, spec_data, "http"), spec_data["login"]["http"])
    check_eq("K12 lookup: no override at all is the factory's recipe", MC.login_recipe(S.config(), spec_data, "ui"), spec_data["login"]["ui"])
    nulled = S.config(manual_capture={"login": {"ui": None}})
    check_eq("K12 lookup: a present null is no recipe", (MC.login_recipe(nulled, spec_data, "ui"), MC.login_declared_none(nulled, "ui")), ({}, True))
    check_eq("K12 lookup: an absent key is not `declared none`", (MC.login_declared_none(S.config(), "ui"), MC.login_declared_none(only_ui, "http")), (False, False))
    try:       # t-308 F3: it used to mean "no login" in silence
        MC.login_recipe(S.config(manual_capture={"login": {"ui": "x"}}), spec_data, "ui")
        check("K12 lookup: a recipe that is neither an object nor null is refused", False)
    except ValueError as exc:
        check_in("K12 lookup: a recipe that is neither an object nor null is refused, naming the key", "manual_capture.login.ui", str(exc))
    check_eq("K12 lookup: `manual_capture.login` that is not an object is the default", MC.login_recipe(S.config(manual_capture={"login": 5}), spec_data, "ui"), spec_data["login"]["ui"])
    # through the calls: only `ui` overridden -> the http login still goes to the factory's path
    t = S.make_task(cfg=only_ui, manual=("api",))
    try:
        get = f"{LOCAL}/v1/workflows/w1"
        http = S.FakeHttp({("POST", f"{LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}), ("GET", get): S.ok_json({"id": "w1"})})
        code, out, err = http_run(t, http, "--method", "GET", "--url", get)
        check_eq("K12: with only `ui` in config the http login still POSTs to the factory's /v1/local-auth/login", (code, http.calls[0][:2]), (0, ("POST", f"{LOCAL}/v1/local-auth/login")))
    finally:
        S.cleanup(t)
    t = S.make_task(cfg=S.config(manual_capture={"login": {"http": None}}), manual=("api",))
    try:
        get = f"{LOCAL}/v1/workflows/w1"
        http = S.FakeHttp({("GET", get): S.ok_json({"id": "w1"})})
        code, out, err = http_run(t, http, "--method", "GET", "--url", get)
        check_eq("K12: `login.http: null` makes no login call and sends no Authorization", (code, [c[:2] for c in http.calls], "Authorization" in http.calls[0][2]),
                 (0, [("GET", get)], False))
    finally:
        S.cleanup(t)
    # `login.ui: null` through a ui call: no login at all, the session runs
    browser = S.FakeBrowser()
    t, code, out, err = landing_run(browser, cfg=nulled)
    try:
        # HF5-4 (observation): the screen is saved after each passed step, so goto + capture is goto, one observation shot,
        # the capture's own shot, one observation shot
        check_eq("K12 `login.ui: null`: no login call, the session runs (the browser only went to the page)",
                 (code, browser.credentials_seen, [c[0] for c in browser.calls]),
                 (0, None, ["goto", "screenshot", "screenshot", "screenshot"]))
    finally:
        S.cleanup(t)
    # E6: an override with no `landed` is the weak proof - said in the detail and on stderr, never refused
    weak = login_cfg(ui_recipe(landed=None))
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=1, cookies_at=None), cfg=weak)
    try:
        step = login_step(t)
        check_eq("E6 an override with no `landed`: not refused, the login lands on the weaker proof", (code, step["outcome"]), (0, "ok"))
        check_in("E6: the detail says the proof is weak", "no landing rule in config, weak proof", step["detail"])
        check_in("E6: and the proof is the field", "the sign-in field is gone", step["detail"])
        check_in("E6: and stderr says it too", "weak proof", err)
    finally:
        S.cleanup(t)
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=1))
    try:
        check_eq("E6 control: the factory's default is never called weak", ("weak proof" in login_step(t)["detail"], "weak proof" in err), (False, False))
    finally:
        S.cleanup(t)
    # `landed: null` is absent (the weak proof, said); a `landed` that is not an object is refused (t-308 F3)
    null_landed = dict(ui_recipe(landed=None), landed=None)
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=1, cookies_at=None), cfg=login_cfg(null_landed))
    try:
        check_in("E6: `landed: null` is the weak proof, and said", "weak proof", login_step(t)["detail"])
    finally:
        S.cleanup(t)


def landing_before_submit():
    """K13 (Q3, E8): a login that fails BEFORE the submit (the page never loaded, a sign-in field was not found) takes the
    same path: exit 3, owner `factory`, do_not_retry, the step `failed`, nothing from the steps file."""
    browser = S.FakeBrowser(login_error=MC.StepFailed("no element matched within 30 s"))
    t, code, out, err = landing_run(browser)
    try:
        row = blocked_row(out)
        step = login_step(t)
        check_eq("K13 the login raises before the submit: exit 3, owner factory, do_not_retry", (code, row.get("owner"), row.get("do_not_retry")), (3, "factory", True))
        check_eq("K13: the step is `failed` and says why", (step["outcome"], "no element matched within 30 s" in step["detail"]), ("failed", True))
        check_eq("K13: nothing from the steps file ran (no landing loop either)", ([c[0] for c in browser.calls], browser.polls), (["login"], 0))
        check_in("K13: the line is the login's", "login by code: ", row.get("probe_line", ""))
    finally:
        S.cleanup(t)
    browser = S.FakeBrowser(login_error=MC.StepTimeout(100))
    t, code, out, err = landing_run(browser)
    try:
        check_eq("K13 a page load that timed out before the submit: owner factory too", (code, blocked_row(out).get("owner")), (3, "factory"))
    finally:
        S.cleanup(t)


def read_login_adversarial():
    """The adversarial inputs of `read_login` (spec section 6): it is a GATE now (the driver asks before a block is
    dispatched), so every awkward input stays on the safe side - missing - and `export` / BOM stay present."""
    t = S.make_task()
    try:
        env = t.project / "harness" / ".env"

        def read(text=None, **environment):
            if text is not None:
                env.write_bytes(text.encode("utf-8"))
            cfg = S.config(environment=dict({"env_file": "harness/.env", "user_key": "AUTH_USERNAME", "secret_keys": ["AUTH_PASSWORD"]}, **environment))
            try:
                return MC.read_login(cfg, t.project)
            except MC.LoginMaterialMissing as exc:
                check_not_in("read_login: a refusal never carries the password", S.PASSWORD, str(exc))
                return exc.part
        check_eq("a good file reads as the account", (lambda c: (c.username, c.password, c.env_file, c.user_key, c.password_key))(read(
            f"AUTH_USERNAME={S.USER}\nAUTH_PASSWORD={S.PASSWORD}\n")), (S.USER, S.PASSWORD, "harness/.env", "AUTH_USERNAME", "AUTH_PASSWORD"))
        check_eq("no `environment.env_file`: None, no login", MC.read_login(S.config(environment={}), t.project), None)
        check_eq("`AUTH_PASSWORD=` (empty): missing key", read(f"AUTH_USERNAME={S.USER}\nAUTH_PASSWORD=\n"), "key")
        check_eq("`AUTH_PASSWORD=\"\"` (quoted empty): missing key", read(f"AUTH_USERNAME={S.USER}\nAUTH_PASSWORD=\"\"\n"), "key")
        check_eq("`AUTH_PASSWORD=   ` (blanks only): missing key", read(f"AUTH_USERNAME={S.USER}\nAUTH_PASSWORD=   \n"), "key")
        check_eq("`# AUTH_PASSWORD=x` (commented out): missing key", read(f"AUTH_USERNAME={S.USER}\n# AUTH_PASSWORD={S.PASSWORD}\n"), "key")
        check_eq("a user key with no value: missing key", read(f"AUTH_PASSWORD={S.PASSWORD}\n"), "key")
        check_eq("`secret_keys: [\"\"]` and a line `=x`: missing key, never the stray value",
                 read(f"AUTH_USERNAME={S.USER}\n=x\nAUTH_PASSWORD={S.PASSWORD}\n", secret_keys=[""]), "key")
        check_eq("`secret_keys: []` falls back to AUTH_PASSWORD (as before)", read(f"AUTH_USERNAME={S.USER}\nAUTH_PASSWORD={S.PASSWORD}\n", secret_keys=[]).password, S.PASSWORD)
        for label, text in (("a BOM at the start", f"﻿AUTH_USERNAME={S.USER}\nAUTH_PASSWORD={S.PASSWORD}\n"),
                            ("`export` before a key", f"export AUTH_USERNAME={S.USER}\nexport AUTH_PASSWORD={S.PASSWORD}\n"),
                            ("CRLF line ends", f"AUTH_USERNAME={S.USER}\r\nAUTH_PASSWORD={S.PASSWORD}\r\n"),
                            ("quoted values", f"AUTH_USERNAME=\"{S.USER}\"\nAUTH_PASSWORD='{S.PASSWORD}'\n")):
            got = read(text)
            check_eq(f"{label}: reads as present", (getattr(got, "username", got), getattr(got, "password", got)), (S.USER, S.PASSWORD))
        check_eq("env_file naming a DIRECTORY: unreadable (it is there, it is not a file - t-308 F6)", read(env_file="harness"), "unreadable")
        real = MC._env_values
        MC._env_values = lambda path: (_ for _ in ()).throw(PermissionError("denied"))
        try:
            check_eq("a file that is there but cannot be read (no permission): unreadable, never `file`", read(
                f"AUTH_USERNAME={S.USER}\nAUTH_PASSWORD={S.PASSWORD}\n"), "unreadable")
        finally:
            MC._env_values = real
        check_eq("an absolute env_file that does not exist: missing file", read(env_file=str(t.project / "nowhere" / ".env")), "file")
        check_eq("a relative env_file resolved against the project root, not the cwd", read(env_file="harness/missing.env"), "file")
        # `LoginMaterialMissing` is still a ValueError: every caller that refused on one still does
        check("LoginMaterialMissing is a ValueError", issubclass(MC.LoginMaterialMissing, ValueError))
        # the refusal of the capture itself is unchanged for the old inputs (existing tests: login_and_secrets)
    finally:
        S.cleanup(t)


def t308_f1_a_login_declared_null_is_never_read():
    """t-308 F1: `manual_capture.login.<kind>: null` says that kind needs no login, and the driver's gate already says "no
    problem" for it - so the capture must not read (and refuse on) the env file either. ERROR DIRECTION: the gate and the
    capture agree; the capture never refuses on a file the gate skipped. Controls: the file present gives the same run;
    the key absent (the factory default) with the file missing is still refused; the OTHER kind still logs in."""
    missing = {"env_file": "harness/missing.env"}
    for label, environment in (("the env file is missing", missing), ("the env file is present", None)):
        cfg = S.config(environment=environment, manual_capture={"login": {"ui": None}}) if environment else S.config(manual_capture={"login": {"ui": None}})
        browser = S.FakeBrowser()
        t, code, out, err = landing_run(browser, cfg=cfg)
        try:
            # HF5-4 (observation): goto, its observation shot, the capture's shot, its observation shot
            check_eq(f"F1 ui `login.ui: null`, {label}: the session runs, no login is made",
                     (code, browser.credentials_seen, [c[0] for c in browser.calls]),
                     (0, None, ["goto", "screenshot", "screenshot", "screenshot"]))
        finally:
            S.cleanup(t)
    # control: the key absent and the file missing is still the refusal on the file (the default recipe needs the account)
    t, code, out, err = landing_run(S.FakeBrowser(), cfg=S.config(environment=missing))
    try:
        check_eq("F1 control: `login.ui` absent and the env file missing: refused on the file", code, 2)
        check_in("F1 control: and the refusal names the file", "does not exist", err)
    finally:
        S.cleanup(t)
    # http: a null `login.http` and a missing file - the request goes with no login call and no Authorization
    get = f"{LOCAL}/v1/workflows/w1"
    t = S.make_task(cfg=S.config(environment=missing, manual_capture={"login": {"http": None}}), manual=("api",))
    try:
        http = S.FakeHttp({("GET", get): S.ok_json({"id": "w1"})})
        code, out, err = http_run(t, http, "--method", "GET", "--url", get)
        check_eq("F1 http `login.http: null`, the env file missing: the request goes, no login call, no Authorization",
                 (code, [c[:2] for c in http.calls], "Authorization" in http.calls[0][2] if http.calls else None), (0, [("GET", get)], False))
    finally:
        S.cleanup(t)
    t = S.make_task(cfg=S.config(environment=missing), manual=("api",))
    try:
        code, out, err = http_run(t, S.FakeHttp({}), "--method", "GET", "--url", get)
        check_eq("F1 control: `login.http` absent and the env file missing: refused on the file", code, 2)
    finally:
        S.cleanup(t)
    # a null `ui` with a present `http`: the http leg still logs in
    t = S.make_task(cfg=S.config(manual_capture={"login": {"ui": None}}), manual=("api",))
    try:
        http = S.FakeHttp({("POST", f"{LOCAL}/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}), ("GET", get): S.ok_json({"id": "w1"})})
        code, out, err = http_run(t, http, "--method", "GET", "--url", get)
        check_eq("F1: a null `ui` does not switch the http login off", (code, http.calls[0][:2] if http.calls else None),
                 (0, ("POST", f"{LOCAL}/v1/local-auth/login")))
    finally:
        S.cleanup(t)


def t308_f2_an_explicit_attempt_of_a_login_that_did_not_land():
    """t-308 F2 (the Q2 invariant): an explicit `--attempt aN` of an attempt whose login did not land
    (env_blocked.json with do_not_retry) is refused with the door the runner has - the env_blocked line and the halt -
    and never with "capture again" while the cause stands. Control: an env_blocked attempt WITHOUT do_not_retry keeps the
    old text."""
    browser = S.FakeBrowser(urls=[S.SIGN_IN_URL], cookies_at=None, field_gone_at=None)
    t, code, out, err = landing_run(browser)
    try:
        check_eq("F2 setup: the login did not land (exit 3)", code, 3)
        code, out, err, _ = ui_run(t, browser=S.FakeBrowser(), extra=("--attempt", "a1"))
        check_eq("F2 `--attempt a1` of the do_not_retry attempt: refused (exit 2)", code, 2)
        check_in("F2: the refusal names `do_not_retry`", "do_not_retry", err)
        check_in("F2: and the env_blocked door", "env_blocked[]", err)
        check_in("F2: and the line the attempt holds", "login by code:", err)
        # the command's own epilogue (role-commands.json) says "do not capture again": the door never says "capture again with ..."
        check_not_in("F2: and never says to capture again", "capture again with", err.lower())
        check_not_in("F2: ... in any case", "Capture again", err)
        root = MC.case_root(t.task, UI_CASE)
        try:
            MC.choose_attempt(root, "a1")
            check("F2: choose_attempt refuses it", False)
        except ValueError as exc:
            check_not_in("F2: choose_attempt: no `--attempt a2` door either", "--attempt a2", str(exc))
        check_eq("F2: no explicit attempt: the next one is opened as before", MC.choose_attempt(root, None), "a2")
        # control: env_blocked WITHOUT do_not_retry keeps today's text (a probe failure heals by a new capture)
        (root / "a2").mkdir()
        (root / "a2" / "env_blocked.json").write_text(json.dumps({"id": UI_CASE, "probe_line": "p", "remedy": "r", "owner": "user"}), encoding="utf-8")
        try:
            MC.choose_attempt(root, "a2")
            check("F2 control: an env_blocked attempt with no do_not_retry is refused", False)
        except ValueError as exc:
            check_in("F2 control: ... with today's door", "Capture again with the next attempt (--attempt a3)", str(exc))
        (root / "a3").mkdir()
        (root / "a3" / "env_blocked.json").write_text("{not json", encoding="utf-8")
        try:
            MC.choose_attempt(root, "a3")
            check("F2 edge: a broken env_blocked.json is refused", False)
        except ValueError as exc:
            check_in("F2 edge: a broken env_blocked.json reads as a plain env_blocked attempt (today's text, no raise)", "--attempt a4", str(exc))
    finally:
        S.cleanup(t)


def t308_f3_a_recipe_that_is_not_an_object_is_refused():
    """t-308 F3 (the E2 class: a recipe defect is the call's, exit 2, naming the key, before any attempt exists): a present
    non-null `landed` that is not an object; a `login.<kind>` that is neither an object nor null. Negative controls:
    `landed: null` is absent (the weak proof, said), a `login` key left out is the factory's default."""
    for label, landed in (("a string", "testproject1_access_token"), ("a list", []), ("a number", 5), ("a boolean", False)):
        t = S.make_task(cfg=login_cfg(ui_recipe(landed=landed)))
        try:
            browser = S.FakeBrowser()
            patch_backends(browser)
            steps = _write(t, STEPS_GOTO)
            code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
            check_eq(f"F3 `landed` is {label}: refused (exit 2)", code, 2)
            check_in(f"F3 `landed` is {label}: the key is named", "manual_capture.login.ui.landed", err)
            check_not_in(f"F3 `landed` is {label}: and the message does not claim there is no rule in config", "no landing rule in config", err)
            check(f"F3 `landed` is {label}: no attempt folder, no browser", not MC.case_root(t.task, UI_CASE).exists() and browser.opened is None)
        finally:
            S.cleanup(t)
    for label, value in (("a string", "x"), ("a list", []), ("a number", 5)):
        t = S.make_task(cfg=login_cfg(value))
        try:
            browser = S.FakeBrowser()
            patch_backends(browser)
            steps = _write(t, STEPS_GOTO)
            code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
            check_eq(f"F3 `login.ui` is {label}: refused (exit 2)", code, 2)
            check_in(f"F3 `login.ui` is {label}: the key is named", "manual_capture.login.ui", err)
            check(f"F3 `login.ui` is {label}: no attempt folder, no browser", not MC.case_root(t.task, UI_CASE).exists() and browser.opened is None)
        finally:
            S.cleanup(t)
    get = f"{LOCAL}/v1/workflows/w1"
    t = S.make_task(cfg=S.config(manual_capture={"login": {"http": "x"}}), manual=("api",))
    try:
        http = S.FakeHttp({})
        code, out, err = http_run(t, http, "--method", "GET", "--url", get)
        check_eq("F3 `login.http` is a string: refused (exit 2), the key named, nothing sent, no attempt folder",
                 (code, "manual_capture.login.http" in err, http.calls, MC.case_root(t.task, API_CASE).exists()), (2, True, [], False))
    finally:
        S.cleanup(t)
    # negative controls: `landed: null` is absent; a key left out is the factory's default
    null_landed = dict(ui_recipe(landed=None), landed=None)
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=1, cookies_at=None), cfg=login_cfg(null_landed))
    try:
        check_eq("F3 control: `landed: null` runs on the weak proof", (code, "weak proof" in login_step(t)["detail"]), (0, True))
    finally:
        S.cleanup(t)
    t, code, out, err = landing_run(S.FakeBrowser(lands_at=1))
    try:
        check_eq("F3 control: `login.ui` absent is the factory default (strong proof)", (code, "weak proof" in login_step(t)["detail"]), (0, False))
    finally:
        S.cleanup(t)


REPO_APP = {"repo_id": "app", "local_path": "app", "role": "application", "execution_profile_id": "web"}
REPO_TESTS = {"repo_id": "tests", "local_path": "tests", "role": "tests", "execution_profile_id": "web"}


def web_config(repos=(REPO_APP, REPO_TESTS), **over):
    """The shape of a project with ONE profile (`web`, capabilities web and api), the application and its tests as two
    repositories of that profile, and NO runtime_probes entry: nothing here is named like any one project's."""
    profile = {"profile_id": "web", "capabilities": ["web", "api"],
               "commands": {"one_test": {"argv": ["npx", "playwright", "test", "<f>"], "cwd": "."}}}
    return S.config(profiles=[profile], execution={"runtime_probes": {}}, implementation_repos=[dict(r) for r in repos], **over)


def ep1_28_capture_profile():
    """EP1-28: the profile of a capture is the project's own, chosen before any attempt, browser or request exists."""
    cfg_web = web_config()
    for surface in ("ui", "http"):
        check_eq(f"profile {surface}: the one profile that lists the surface's word", MC.capture_profile(cfg_web, "x", "C", surface), "web")
    cfg_two = S.config()
    check_eq("profile: the two-profile form keeps its old answers (ui -> e2e-ui, http -> api)",
             (MC.capture_profile(cfg_two, "x", "C", "ui"), MC.capture_profile(cfg_two, "x", "C", "http")), ("e2e-ui", "api"))
    check_eq("profile: --profile naming a profile of config.json wins", MC.capture_profile(cfg_two, "x", "C", "ui", "api"), "api")
    for asked in ("nope", "WEB"):
        try:
            MC.capture_profile(cfg_web, "x", "C", "ui", asked)
            check(f"profile: --profile {asked!r} outside config.json is refused", False)
        except ValueError as exc:
            check_in(f"profile: --profile {asked!r} is refused, listing the profiles", "Expected one of: web", str(exc))
    # steps 3-6
    two_web = S.config(profiles=[{"profile_id": "a", "capabilities": ["web"]}, {"profile_id": "b", "capabilities": ["web"]}])
    try:
        MC.capture_profile(two_web, "x", "C", "ui")
        check("profile: two that fit and no plan is refused", False)
    except ValueError as exc:
        check_in("profile: ... naming both and the door --profile", "several test profiles fit this ui capture (a, b): name one with --profile", str(exc))
    import gate_preflight
    real = gate_preflight.stand_profiles
    try:
        gate_preflight.stand_profiles = lambda cfg, root, dispositions: {"b": {"cases": ["C"]}}
        check_eq("profile: two that fit: the profile the PLAN gives this case", MC.capture_profile(two_web, "x", "C", "ui"), "b")

        def broken(*a):
            raise RuntimeError("no plan")
        gate_preflight.stand_profiles = broken
        try:
            MC.capture_profile(two_web, "x", "C", "ui")
            check("profile: an unreadable plan leaves the refusal", False)
        except ValueError:
            check("profile: an unreadable plan leaves the refusal", True)
    finally:
        gate_preflight.stand_profiles = real
    check_eq("profile: none fits, ONE profile in the project: it", MC.capture_profile(S.config(profiles=[{"profile_id": "main"}]), "x", "C", "http"), "main")
    check_eq("profile: none fits, several, an older config's runtime_probes entry by the level word: that word",
             MC.capture_profile(S.config(profiles=[{"profile_id": "p"}, {"profile_id": "q"}]), "x", "C", "http"), "api")
    for label, cfg in (("absent", {}), ("not a list", {"profiles": "web"}), ("empty", {"profiles": []})):
        cfg = dict(cfg, execution={"runtime_probes": {}})
        try:
            MC.capture_profile(cfg, "x", "C", "ui")
            check(f"profile: profiles {label} and no entry by the level: refused", False)
        except ValueError as exc:
            check_in(f"profile: profiles {label}: the refusal names --profile and capabilities", "--profile <id>", str(exc))
            check_in(f"profile: profiles {label}: ... and the word that fits", "`web`", str(exc))
    # the position invariant: a refusal creates no attempt folder and opens no browser
    entry = {"argv": ["probe-b"], "cwd": ".", "timeout_s": 5}
    t = S.make_task(cfg=S.config(profiles=[{"profile_id": "a", "capabilities": ["web"]}, {"profile_id": "b", "capabilities": ["web"]}],
                                 execution={"runtime_probes": {"a": entry, "b": entry}}))
    try:
        steps = _write(t, f"goto {UI}\n")
        browser = S.FakeBrowser()
        patch_backends(browser, probes=lambda spec: S.probe("b"))
        err = refused("profile: an ambiguous ui capture", ["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)],
                      "name one with --profile")
        check_eq("profile: the refusal opened no browser and made no attempt folder", (browser.opened, MC.attempts_of(MC.case_root(t.task, UI_CASE))),
                 (None, []))
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps), "--profile", "b"])
        check_eq("profile: --profile b then runs the capture on b", (code, MC.attempt_profiles(t.attempt_dir(UI_CASE))), (0, ["b"]))
    finally:
        S.cleanup(t)


def ep1_28_default_probe():
    """EP1-28 (H-1, H-2, H-4, H-5): a stand with no registered probe gets the default one over the application's checkout."""
    seen = []

    def fake(spec):
        seen.append(spec)
        return S.probe("web")
    t = S.make_task(cfg=web_config())
    try:
        steps = _write(t, f"goto {UI}\ncapture post_action completion\n")
        patch_backends(S.FakeBrowser(), probes=fake)
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        check_eq("default probe: a project with one profile `web` and no entry captures (exit 0)", code, 0)
        check_eq("default probe: probed at the start and at the end as `web`",
                 [(r["when"], r["profile"]) for r in jsonl(t.attempt_dir(UI_CASE) / "probes.jsonl")], [("start", "web"), ("end", "web")])
        argv = seen[0]["argv"]
        check("default probe: the application's checkout (role application) and the stand are in its argv, no container",
              argv[argv.index("--checkout") + 1] == "app" and argv[argv.index("--environment") + 1] == "localhost"
              and "--container" not in argv and "--task" in argv, str(argv))
        check_eq("default probe: it is in memory only, the config on disk is untouched",
                 "runtime_probes" in json.dumps(json.loads((t.project / "qa-factory" / "config.json").read_text(encoding="utf-8"))
                                                .get("execution", {}).get("runtime_probes")), False)
    finally:
        S.cleanup(t)
    # the three causes of "no probe": said in the line, with the door (exit 3, nothing recorded)
    cases = (("two repositories with no role", web_config(repos=[{**REPO_APP, "role": ""}, {**REPO_TESTS, "role": ""}]),
              "2 implementation repositories for profile web (app, tests)"),
             ("the same role twice", web_config(repos=[{**REPO_APP, "role": "tests"}, REPO_TESTS]), "2 implementation repositories"),
             ("role case differs", web_config(repos=[{**REPO_APP, "role": "Application"}, REPO_TESTS]), "2 implementation repositories"),
             ("the application repository has no path", web_config(repos=[{**REPO_APP, "local_path": ""}, REPO_TESTS]),
              "the application repository app of profile web records no local_path"),
             ("no repository", web_config(repos=[]), "no checkout of the application is recorded for profile web"),
             ("two stands", web_config(), "this project names 2 stands (localhost, preview)"))
    for label, cfg, needle in cases:
        t = S.make_task(cfg=cfg)
        try:
            steps = _write(t, f"goto {UI}\n")
            patch_backends(S.FakeBrowser(), probes=fake)
            before = len(seen)
            if label == "two stands":
                import execution_request
                spec_, why = execution_request.stand_probe_spec(cfg, "web", "")
                check_eq("default probe: two stands and none named: no spec", spec_, None)
                check_in("default probe: ... and why", needle, why)
                continue
            code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
            row = json.loads(out)["env_blocked"]
            check_eq(f"default probe, {label}: exit 3, owner user, do_not_retry, cause build, no probe run",
                     (code, row["owner"], row.get("do_not_retry"), row.get("cause"), len(seen) - before), (3, "user", True, "build", 0))
            check_in(f"default probe, {label}: the line says why", needle, row["probe_line"])
            check_in(f"default probe, {label}: the remedy is a door the role can walk", "--no-container --profile web", row["remedy"])
        finally:
            S.cleanup(t)
    # H-4: a checkout that names no commit: no retry door, no question
    t = S.make_task(cfg=web_config())
    try:
        steps = _write(t, f"goto {UI}\n")
        norev = {"profile_id": "web", "timestamp": "2026-10-01T10:00:00+00:00", "environment_id": "localhost",
                 "expected_source_revision": "unknown", "observed_runtime_identity": "", "evidence_refs": [],
                 "provenance": {"technical_verification": False}, "result": "unknown", "error": "no expected revision",
                 "reason_code": "no_expected_revision", "checkout": "app"}
        patch_backends(S.FakeBrowser(), probes=lambda spec: norev)
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        row = json.loads(out)["env_blocked"]
        check_eq("no revision: exit 3, do_not_retry, cause build", (code, row.get("do_not_retry"), row.get("cause")), (3, True, "build"))
        check_in("no revision: the remedy names the checkout and the cure", "the checkout app is not a git repository or has no commit", row["remedy"])
        check_not_in("no revision: it never says capture again", "capture again", row["remedy"])
        no_field = dict(norev, reason_code="", asks_person="how")
        check_not_in("no revision: without the FIELD the words alone change nothing", "is not a git repository",
                     MC._stand_blocked("web", "start", no_field, "said").row["remedy"])
    finally:
        S.cleanup(t)


def ep1_28_other_profile():
    """EP1-28 (H-5): the build question of this stage was about ANOTHER profile than the one the capture chose."""
    import gate_preflight
    import stand_identity
    asks = {"profile_id": "e2e-ui", "timestamp": "2026-10-01T10:00:00+00:00", "environment_id": "localhost",
            "expected_source_revision": SOURCE_40, "observed_runtime_identity": "", "evidence_refs": [],
            "provenance": {"technical_verification": False}, "result": "unknown", "asks_person": "how", "error": "unreadable"}
    real = gate_preflight.stand_profiles
    t = S.make_task()
    try:
        attempt = MC.Attempt(t.task, UI_CASE, "a1", t.cfg)
        stand = {"name": "localhost"}
        for label, plan in (("the plan names this profile", {"e2e-ui": {"cases": [UI_CASE]}}), ("the plan is empty", {})):
            gate_preflight.stand_profiles = lambda cfg, root, dispositions, p=plan: p
            check_eq(f"other profile: {label}: no other-profile door", MC._other_profile_remedy(t.cfg, attempt, "e2e-ui", stand), None)
        gate_preflight.stand_profiles = lambda *a: (_ for _ in ()).throw(RuntimeError("x"))
        check_eq("other profile: an unreadable plan: no other-profile door", MC._other_profile_remedy(t.cfg, attempt, "e2e-ui", stand), None)
        gate_preflight.stand_profiles = lambda cfg, root, dispositions: {"api": {"cases": [API_CASE]}}
        halt = MC._other_profile_remedy(t.cfg, attempt, "e2e-ui", stand)
        check_in("other profile: no word on the plan profile: the conductor's door", "nobody was asked about this build", halt or "")
        check_in("other profile: ... and it names both profiles", "test profile api, not e2e-ui", halt or "")
        stand_identity.add_confirmation(t.project, t.task, task=S.TICKET, environment_id="localhost", profile_id="api", kind="deployed",
                                        words="deployed", revision=SOURCE_40, stand_definition_sha="d" * 64)
        use = MC._other_profile_remedy(t.cfg, attempt, "e2e-ui", stand)
        check_in("other profile: a word on the plan profile: capture again with --profile api", "capture again with --profile api", use or "")
        check_in("other profile: ... the choice stays the role's", "that choice is yours", use or "")
        # through the capture: the refusal of an `unknown` that asks the person carries the door; the code never picks --profile
        steps = _write(t, f"goto {UI}\n")
        patch_backends(S.FakeBrowser(), probes=lambda spec: asks)
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        row = json.loads(out)["env_blocked"]
        check_eq("other profile: through the capture: exit 3, do_not_retry, cause build", (code, row.get("do_not_retry"), row.get("cause")), (3, True, "build"))
        check_in("other profile: ... the remedy is the use door", "capture again with --profile api", row["remedy"])
        check_eq("other profile: the code did not capture by the plan's profile on its own", MC.attempt_profiles(t.attempt_dir(UI_CASE)), [])
        gate_preflight.stand_profiles = lambda cfg, root, dispositions: {"e2e-ui": {"cases": [UI_CASE]}}
        code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps)])
        check_in("other profile: the plan names this profile: the ordinary door stands", "the person answers the build question",
                 json.loads(out)["env_blocked"]["remedy"])
    finally:
        gate_preflight.stand_profiles = real
        S.cleanup(t)


SOURCE_40 = "c" * 40


_INPUT_ATTEMPTS = []


def _input_step(t, browser, line, spec_data=None, timeout_s=100, element_s=30):
    """One `_run_step` of a keyboard step on a scripted browser: (the steps.jsonl entry, the attempt)."""
    word, _, rest = line.partition(" ")
    import shlex
    _INPUT_ATTEMPTS.append(1)       # a folder of its own per step: the log files of one test never leak into the next
    attempt = MC.Attempt(t.task, UI_CASE, f"a{len(_INPUT_ATTEMPTS) + 10}", t.cfg)
    step = {"word": word, "args": shlex.split(rest), "line": line}
    return MC._run_step(browser, attempt, step, timeout_s, t.cfg, spec_data if spec_data is not None else {}, element_s)["entry"], attempt


def ep1_29_parse_and_data():
    """EP1-29 (t-506 3.3 + t-524 4): the closed limits are data; every one is tested AT and BEYOND."""
    data = MC.spec()
    kind = data["steps"]["type"]
    check_eq("EP1-29 data: the limits of `type` and the probe wait are pinned (a changed number is a decision, not a drift)",
             (kind["default_delay_ms"], kind["max_delay_ms"], kind["max_chars"], kind["settle_ms"], data["probe_wait_ms"]),
             (200, 2000, 200, 1500, 500))
    check_eq("EP1-29 data: the keys of `press`", data["steps"]["press"]["keys"],
             ["Backspace", "Delete", "Enter", "Tab", "Escape", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End",
              "Control+A", "Meta+A", "Control+V"])

    def problem(line):
        try:
            MC.parse_steps(f"goto {UI}\n{line}\n", data)
        except ValueError as exc:
            return str(exc)
        return ""
    for line in ('type input 12', 'type input 12 1', 'type input 12 2000', 'type input " "', "type input 'héllo \U0001F600'",
                 'type input "it\'s"', f'type input {"a" * 200}', 'paste input " "', 'press input Backspace', 'press input a',
                 'press input é', 'press input Control+A', 'press input Control+V'):
        check_eq(f"EP1-29 parse: accepted `{line[:40]}`", problem(line), "")
    for label, line, needle in (
            ("empty type text", 'type input ""', "press input Control+A"),
            ("empty paste text", 'paste input ""', "press input Backspace"),
            ("delay 0", "type input 12 0", "from 1 to 2000"), ("delay -1", "type input 12 -1", "from 1 to 2000"),
            ("delay beyond the max", "type input 12 2001", "from 1 to 2000"), ("delay a word", "type input 12 abc", "whole number"),
            ("delay a fraction", "type input 12 1.5", "whole number"), ("delay in another script", "type input 12 ٣", "whole number"),
            ("201 characters", f"type input {'a' * 201}", "with `fill`"), ("a longer text goes in with fill", f"type input {'a' * 201}", "at most 200"),
            ("a key outside the list", "press input Shift+A", "Backspace, Delete, Enter"), ("two characters", "press input ab", "one printable"),
            ("an empty key", 'press input ""', "one printable"), ("type with one argument", "type input", "`type` takes"),
            ("type with four arguments", "type input 12 5 6", "`type` takes"), ("press with one argument", "press input", "`press` takes")):
        check_in(f"EP1-29 parse: refused {label}", needle, problem(line))
    # a file that names a limit lower than the package's: the limit is read from the data it was given, not from a literal
    low = json.loads(json.dumps(data))
    low["steps"]["type"]["max_chars"] = 3
    check_eq("EP1-29 parse: max_chars is the data's (3 passes)", problem_with(low, "type input abc"), "")
    check_in("EP1-29 parse: max_chars is the data's (4 is refused)", "at most 3", problem_with(low, "type input abcd"))


def ep1_32_read_modes():
    """EP1-32 (t-506 6.3, 6.4 test 3): the modes of `read` at parse time; the states and the marker are the data's."""
    data = MC.spec()
    check_eq("EP1-32 data: the states and the marker are pinned", (data["read_states"], data["read_absent_marker"]),
             (["disabled", "enabled", "checked", "visible", "editable"], "<absent>"))
    for state in data["read_states"]:
        check_eq(f"EP1-32 parse: accepted `state={state}`", problem_with(data, f'read "#b" state={state}'), "")
    for line in ('read "#b"', 'read "#b" text', 'read "#b" attr=value', 'read "#b" style=color'):
        check_eq(f"EP1-32 parse: still accepted `{line}`", problem_with(data, line), "")
    for label, line in (("empty state", 'read "#b" state='), ("unknown state", 'read "#b" state=foo'),
                        ("state in capitals", 'read "#b" STATE=disabled'), ("state value in capitals", 'read "#b" state=Disabled'),
                        ("empty attr", 'read "#b" attr='), ("a mode no one knows", 'read "#b" foo')):
        check_in(f"EP1-32 parse: refused {label}", "`read` takes", problem_with(data, line))
    check_in("EP1-32 parse: the refusal of a state lists the states", "disabled, enabled, checked, visible, editable",
            problem_with(data, 'read "#b" state=foo'))
    # the list is the data's: a file that drops `editable` refuses it, one that adds `hidden` takes it
    changed = json.loads(json.dumps(data))
    changed["read_states"] = ["disabled", "hidden"]
    check_eq("EP1-32 parse: a state the data adds is accepted", problem_with(changed, 'read "#b" state=hidden'), "")
    check_in("EP1-32 parse: a state the data drops is refused", "disabled, hidden", problem_with(changed, 'read "#b" state=editable'))
    check_in("EP1-32 parse: data with no list refuses every state", "`read` takes",
             problem_with({k: v for k, v in data.items() if k != "read_states"}, 'read "#b" state=disabled'))
    # the marker is read from the data at the moment of the read (mutation: a literal in the code)
    class _Err(Exception):
        pass

    class _Element:
        first = None

        def get_attribute(self, name, timeout=None):
            return None

    class _Page:
        def locator(self, selector):
            element = _Element()
            element.first = element
            return element

    def absent_read():
        backend = MC.PlaywrightBackend.__new__(MC.PlaywrightBackend)
        backend._page, backend._Timeout, backend._Error, backend._element_ms = _Page(), _Err, _Err, 1000
        return backend.read("#b", "attr=x")
    original = MC.spec
    try:
        MC.spec = lambda: dict(original(), read_absent_marker="<none>")
        value, _ = absent_read()
        check_eq("EP1-32 read: the marker is the data's", value, "<none>")
        MC.spec = lambda: {k: v for k, v in original().items() if k != "read_absent_marker"}
        try:
            absent_read()
            check("EP1-32 read: data with no marker never reads absence as an empty string", False, "no failure")
        except MC.StepFailed as exc:
            check_in("EP1-32 read: data with no marker is a failed step that names the key", "read_absent_marker", str(exc))
    finally:
        MC.spec = original


def problem_with(data, line):
    try:
        MC.parse_steps(f"goto {UI}\n{line}\n", data)
    except ValueError as exc:
        return str(exc)
    return ""


def ep1_29_run():
    t = S.make_task()
    try:
        # the delay and the settle come from the data given, not from a literal (mutation: a literal 200 / 1500)
        changed = json.loads(json.dumps(MC.spec()))
        changed["steps"]["type"]["default_delay_ms"], changed["steps"]["type"]["settle_ms"] = 333, 7
        browser = S.FakeBrowser()
        entry, attempt = _input_step(t, browser, "type input 12", spec_data=changed)
        check_eq("EP1-29 type: the delay and the settle are the data's", browser.calls, [("type", "input", "12", 333, 7)])
        check_eq("EP1-29 type: ok, with the value after the wait", (entry["outcome"], entry["detail"]),
                 ("ok", 'typed 2 of 2; value "12" after 7 ms'))
        browser = S.FakeBrowser()
        _input_step(t, browser, "type input 12", spec_data={})
        check_eq("EP1-29 type: the package's own data when the caller gives none: 200 ms, 1500 ms", browser.calls,
                 [("type", "input", "12", 200, 1500)])
        browser = S.FakeBrowser()
        _input_step(t, browser, "type input 12 50")
        check_eq("EP1-29 type: an explicit delay wins", browser.calls[0][3], 50)
        # the page loses the focus after the first character: two rows, the second focus=no, the step is ok and names it
        browser = S.FakeBrowser()
        browser.typed = {"input": [{"n": 1, "value": "1", "focus": True}, {"n": 2, "value": "1", "focus": False},
                                   {"n": "settled", "value": "1", "focus": False}]}
        entry, attempt = _input_step(t, browser, "type input 12")
        check_eq("EP1-29 type: a lost focus is told, not judged (the step stays ok)", entry["outcome"], "ok")
        check_in("EP1-29 type: the detail names the value and the character", 'typed 2 of 2; value "1" after 1500 ms; focus lost after character 1',
                 entry["detail"])
        log = next(p for p in attempt.dir.glob("*type-input*")).read_text(encoding="utf-8")
        check_eq("EP1-29 type: one log line per character, then `settled`", log.splitlines(),
                 ["1\t1\tfocus=yes", "2\t1\tfocus=no", "settled\t1\tfocus=no"])
        # the value is lost only AFTER the wait: the last character looks fine, `settled` shows the loss
        browser = S.FakeBrowser()
        browser.typed = {"input": [{"n": 1, "value": "1", "focus": True}, {"n": 2, "value": "12", "focus": True},
                                   {"n": "settled", "value": "", "focus": True}]}
        entry, attempt = _input_step(t, browser, "type input 12")
        check_in("EP1-29 settle: the detail names the value AFTER the wait and the one before it",
                 'value "" after 1500 ms (it was "12" at the last character)', entry["detail"])
        check_in("EP1-29 settle: the log has the settled line", "settled\t\tfocus=yes", next(
            p for p in attempt.dir.glob("*type-input*")).read_text(encoding="utf-8").splitlines())
        # focus lost only at the settle
        browser = S.FakeBrowser()
        browser.typed = {"input": [{"n": 1, "value": "1", "focus": True}, {"n": "settled", "value": "1", "focus": False}]}
        entry, _ = _input_step(t, browser, "type input 1")
        check_in("EP1-29 settle: a focus lost only at the settle is named", "focus lost after the wait", entry["detail"])
        # the element is gone after a character: <gone>, focus=no, the typing went on, the step is ok
        browser = S.FakeBrowser()
        browser.typed = {"input": [{"n": 1, "value": "<gone>", "focus": False}, {"n": "settled", "value": "<gone>", "focus": False}]}
        entry, _ = _input_step(t, browser, "type input 1")
        check_eq("EP1-29 type: a vanished element is a value `<gone>`, the step is ok", entry["outcome"], "ok")
        check_in("EP1-29 type: and it is told", "no focus already at the reading after character 1", entry["detail"])
        # no element before the first character: failed, like fill
        entry, _ = _input_step(t, S.FakeBrowser(missing={"input"}), "type input 12")
        check_eq("EP1-29 type: no element is a failed step", entry["outcome"], "failed")
        # press and paste: one line, with focused_before
        browser = S.FakeBrowser()
        browser.pressed = {("input", "Backspace"): {"n": "Backspace", "value": "", "focus": True, "focused_before": False}}
        entry, attempt = _input_step(t, browser, "press input Backspace")
        check_in("EP1-29 press: the detail names the focus before", "focused before=no", entry["detail"])
        check_eq("EP1-29 press: the log line carries focused_before", next(
            p for p in attempt.dir.glob("*press-input*")).read_text(encoding="utf-8"), "Backspace\t\tfocus=yes\tfocused_before=no")
        browser = S.FakeBrowser()
        entry, attempt = _input_step(t, browser, "paste input 12")
        check_eq("EP1-29 paste: one call, one line (never a character at a time)", (browser.calls, len(next(
            p for p in attempt.dir.glob("*paste-input*")).read_text(encoding="utf-8").splitlines())), ([("paste", "input", "12")], 1))
        # the time: the element limit judges the focus only; the step limit judges the whole step (AT passes, BEYOND is a timeout)
        entry, _ = _input_step(t, S.FakeBrowser(elapsed={"type": 40, "focus": 0.1}), "type input 12", timeout_s=100, element_s=30)
        check_eq("EP1-29 type: 40 s of typing against a 30 s element limit is ok (the focus took 0.1 s)", entry["outcome"], "ok")
        entry, _ = _input_step(t, S.FakeBrowser(elapsed={"type": 100, "focus": 0.1}), "type input 12", timeout_s=100)
        check_eq("EP1-29 type: exactly the step limit passes", entry["outcome"], "ok")
        entry, _ = _input_step(t, S.FakeBrowser(elapsed={"type": 100.5, "focus": 0.1}), "type input 12", timeout_s=100)
        check_eq("EP1-29 type: beyond the step limit is a timeout (200 characters at 200 ms never hang the run)", entry["outcome"], "timeout")
        entry, _ = _input_step(t, S.FakeBrowser(elapsed={"type": 40, "focus": 31}), "type input 12", element_s=30)
        check_eq("EP1-29 type: a focus that took longer than the element limit is a failed step", entry["outcome"], "failed")
        # a value that matches a secret pattern is refused and nothing is kept
        browser = S.FakeBrowser()
        browser.typed = {"input": [{"n": 1, "value": 'password: "abcdefgh12345678"', "focus": True},
                                   {"n": "settled", "value": 'password: "abcdefgh12345678"', "focus": True}]}
        entry, attempt = _input_step(t, browser, "type input a")
        check_eq("EP1-29 type: a secret-looking value read back is refused", entry["outcome"], "refused")
        check_eq("EP1-29 type: and no file of it is kept", list(attempt.dir.glob("*type-input*")), [])
        check_not_in("EP1-29 type: and the refusal does not repeat the value", "abcdefgh", entry["detail"])
        # through the whole command: the words reach the backend and the case goes on to its capture
        code, out, err, browser = ui_run(t, steps=f"goto {UI}\ntype input 12\npress input Backspace\npaste input 9\n"
                                                  "capture post_action completion\n")
        check_eq("EP1-29 ui: a steps file with the three words runs (exit 0)", (code, {s["outcome"] for s in json.loads(out)["steps"]}),
                 (0, {"ok"}))
        check_eq("EP1-29 ui: and the backend got them in order", [c[0] for c in browser.calls if c[0] in ("type", "press", "paste")],
                 ["type", "press", "paste"])
    finally:
        S.cleanup(t)


STAND = ("http", "localhost", 5173)
API = "http://localhost:5173/api/x"


def _session(t, browser, text, cfg=None):
    """One whole step loop on a scripted browser (the stand host allowed): (rows, failed, attempt, summary)."""
    browser.allowed = {STAND}
    steps = MC.parse_steps(f"goto {UI}\n{text}\n", MC.spec())
    _INPUT_ATTEMPTS.append(1)
    cfg = cfg or t.cfg
    attempt = MC.Attempt(t.task, UI_CASE, f"a{len(_INPUT_ATTEMPTS) + 10}", cfg)
    rows, failed = MC._run_steps(browser, attempt, steps, 100, cfg, MC.spec(), 30, MC.SessionAccount())
    return rows, failed, attempt, MC._summary(attempt, UI_CASE, rows, 0, failed, {})


def _post_shots(attempt):
    return list(attempt.dir.glob("*post_action*.png"))


def _failure_log(attempt):
    return next(attempt.dir.glob("*fail-request*")).read_text(encoding="utf-8")


def ep1_30_parse_and_data():
    """EP1-30 (t-506 4.2 (1)(2) as amended): the status bounds are data; each is tested AT and BEYOND."""
    data = MC.spec()
    row = data["steps"]["fail_request"]
    check_eq("EP1-30 data: the bounds of `fail_request` are pinned (a changed number is a decision)",
             (row["args"], row["arity"], row["status_min"], row["status_max"], row["max_logged"]),
             ("<url_glob> <status|timeout>", [2, 2], 400, 599, 50))
    check_eq("EP1-30 data: `restore_request` takes one pattern", (data["steps"]["restore_request"]["arity"]), [1, 1])

    def problem(line, spec_data=data):
        return problem_with(spec_data, line)
    for line in ("fail_request **/api/x 400", "fail_request **/api/x 599", "fail_request **/api/x 500",
                 "fail_request **/api/x timeout", 'fail_request "http://localhost:5173/api/*" 503', "restore_request **/api/x"):
        check_eq(f"EP1-30 parse: accepted `{line}`", problem(line), "")
    for label, line, needle in (
            ("399 (not a failure)", "fail_request **/api/x 399", "from 400 to 599"), ("600", "fail_request **/api/x 600", "from 400 to 599"),
            ("200", "fail_request **/api/x 200", "from 400 to 599"), ("0", "fail_request **/api/x 0", "from 400 to 599"),
            ("a word", "fail_request **/api/x abc", "`timeout` or a whole number"), ("TIMEOUT in capitals", "fail_request **/api/x Timeout", "`timeout`"),
            ("a fraction", "fail_request **/api/x 500.5", "whole number"), ("negative", "fail_request **/api/x -500", "whole number"),
            ("another script", "fail_request **/api/x ٥٠٠", "whole number"), ("an empty pattern", 'fail_request "" 500', "not empty"),
            ("one argument", "fail_request **/api/x", "`fail_request` takes"), ("three arguments", "fail_request **/api/x 500 5", "`fail_request` takes"),
            ("restore with none", "restore_request", "`restore_request` takes"), ("restore with two", "restore_request a b", "`restore_request` takes")):
        check_in(f"EP1-30 parse: refused {label}", needle, problem(line))
    low = json.loads(json.dumps(data))
    low["steps"]["fail_request"]["status_min"], low["steps"]["fail_request"]["status_max"] = 500, 502
    check_eq("EP1-30 parse: the bounds are the data's (502 passes)", problem("fail_request **/api/x 502", low), "")
    check_in("EP1-30 parse: the bounds are the data's (503 and 499 are refused)", "from 500 to 502",
             problem("fail_request **/api/x 503", low) + problem("fail_request **/api/x 499", low))


def ep1_30_post_action_needs_a_hit():
    """t-524 5: no post_action screen while a declared failure never fired - active or restored, any of several."""
    t = S.make_task()
    try:
        # (1) a failure that caught nothing: refused, no screen, exit 1, the door named; the screen of the control run (a hit) exists
        rows, failed, attempt, summary = _session(t, S.FakeBrowser(), "fail_request **/api/x 500\ncapture post_action completion")
        check_eq("EP1-30 hits=0: the capture is refused", (rows[-1]["outcome"], failed["outcome"]), ("refused", "refused"))
        check_eq("EP1-30 hits=0: no post_action screen exists", _post_shots(attempt), [])
        for words in ("no request matched **/api/x in this session", "has not met the failure", "goto, click, wait",
                      "in a new attempt", "the page's server", "needs another level"):
            check_in(f"EP1-30 hits=0: the refusal says `{words}`", words, failed["detail"])
        code, out, err, _ = ui_run(t, steps=f"goto {UI}\nfail_request **/api/x 500\ncapture post_action completion\n")
        check_eq("EP1-30 hits=0: the whole command exits 1 (a failed step)", code, 1)
        check_eq("EP1-30 hits=0: and the summary row is refused", json.loads(out)["steps"][-1]["outcome"], "refused")
        # (2) fail X, restore X, capture: a LIFTED rule is out of what the capture checks (TR1-2); its empty result was told at the lifting
        rows, failed, attempt, summary = _session(t, S.FakeBrowser(),
                                                  "fail_request **/api/x 500\nrestore_request **/api/x\ncapture post_action completion")
        check_eq("TR1-2 fail, restore, capture: the capture passes (a lifted rule holds nothing)", (rows[-1]["outcome"], failed), ("ok", None))
        check_eq("TR1-2 fail, restore, capture: and the screen is taken", len(_post_shots(attempt)), 1)
        # (3) two failures, one of them with a hit: the refusal names the one with none, only that one
        browser = S.FakeBrowser()
        rows, failed, attempt, _ = _session(t, browser, "fail_request **/a 500\nfail_request **/b 500\ncapture pre_action before")
        browser.hit("**/a")
        steps = MC.parse_steps(f"goto {UI}\ncapture post_action completion\n", MC.spec())
        outcome = MC._run_step(browser, attempt, steps[1], 100, t.cfg, MC.spec(), 30)
        check_eq("EP1-30 two failures, one idle: refused", outcome["entry"]["outcome"], "refused")
        check_in("EP1-30 two failures, one idle: the refusal names the idle one", "no request matched **/b in this session", outcome["entry"]["detail"])
        check_not_in("EP1-30 two failures, one idle: and not the one that fired", "**/a", outcome["entry"]["detail"])
        # (4) a hit: the screen is taken and the count at the capture rides on the step line, the file and the summary
        browser = S.FakeBrowser()
        browser.on_call[("click", "#go")] = [("**/api/x", "GET", API)]
        rows, failed, attempt, summary = _session(t, browser, "fail_request **/api/x 500\nclick #go\ncapture post_action completion")
        check_eq("EP1-30 hits=1: the capture passes, with its screen", (failed, len(_post_shots(attempt))), (None, 1))
        check_eq("EP1-30 hits=1: the step line carries the count", rows[-1]["hits_at_capture"], {"**/api/x": 1})
        steps_log = [json.loads(x) for x in (attempt.dir / "steps.jsonl").read_text(encoding="utf-8").splitlines()]
        check_eq("EP1-30 hits=1: and so does steps.jsonl", steps_log[-1]["hits_at_capture"], {"**/api/x": 1})
        check_eq("EP1-30 hits=1: and the summary row", summary["steps"][-1]["hits_at_capture"], {"**/api/x": 1})
        check_in("EP1-30 hits=1: and the detail the record reads", 'hits_at_capture {"**/api/x": 1}', steps_log[-1]["detail"])
        check_not_in("EP1-30 hits=1: no `failures_without_hits` when every failure fired", "failures_without_hits", " ".join(summary))
        # (4b) a hit BEFORE the action (the goto), none by the action: the count does not grow - code reports, the role judges
        browser = S.FakeBrowser()
        browser.on_call[("goto", UI)] = [("**/api/x", "GET", API)]
        rows, failed, attempt, summary = _session(t, browser, f"fail_request **/api/x 500\ngoto {UI}\ncapture post_action completion")
        check_eq("EP1-30 an earlier hit: code does not judge the action (the screen is taken, the count reported)",
                 (failed, rows[-1]["hits_at_capture"]), (None, {"**/api/x": 1}))
        check_eq("EP1-30 a request sent BEFORE the declaration is no hit (the first goto)", browser.failing["**/api/x"]["hits"], 1)
        # (5) no failure declared: the step line is the old one
        rows, failed, attempt, summary = _session(t, S.FakeBrowser(), "capture post_action completion")
        check_eq("EP1-30 no failure: the step line is unchanged", (rows[-1]["detail"], "hits_at_capture" in rows[-1],
                                                                   "hits_at_capture" in summary["steps"][-1],
                                                                   "failures_without_hits" in summary), ("", False, False, False))
        # (6) the old-attempt case: the record of the failure not readable after a declaration is never a pass
        class Unreadable(S.FakeBrowser):
            def drain_failures(self):
                if self.failing:
                    raise RuntimeError("the route table is gone")
                return super().drain_failures()
        rows, failed, attempt, _ = _session(t, Unreadable(), "fail_request **/api/x 500\ncapture post_action completion")
        check_eq("EP1-30 an unreadable record after a declaration: refused, no screen", (rows[-1]["outcome"], _post_shots(attempt)), ("refused", []))
        check_in("EP1-30 an unreadable record: named as not established", "could not be established", failed["detail"])
        # a backend with no such record at all (the old fake): the capture passes as before
        class Old(S.FakeBrowser):
            drain_failures = None
        rows, failed, attempt, _ = _session(t, Old(), "capture post_action completion")
        check_eq("EP1-30 a backend with no failure record: unchanged", failed, None)
    finally:
        S.cleanup(t)


def ep1_30_restore_log_and_summary():
    t = S.make_task()
    try:
        # restore: the log of what was caught (METHOD url, no query), the failure, the count
        browser = S.FakeBrowser()
        browser.on_call[("click", "#go")] = [("**/api/x", "GET", API + "?token=abc"), ("**/api/x", "POST", API)]
        rows, failed, attempt, summary = _session(t, browser, "fail_request **/api/x 503\nclick #go\nrestore_request **/api/x")
        check_eq("EP1-30 restore: ok", failed, None)
        check_eq("EP1-30 restore: the log (no query, the count, the failure)", _failure_log(attempt).splitlines(),
                 ["pattern: **/api/x", "failure: 503", "requests failed: 2", "GET " + API, "POST " + API])
        check_eq("EP1-30 restore: the route is off", browser.failing["**/api/x"]["active"], False)
        check_eq("EP1-30 restore: nothing idle in the summary", "failures_without_hits" in summary, False)
        # restore of a pattern never failed, and of one already restored: failed, with the active ones named
        rows, failed, attempt, _ = _session(t, S.FakeBrowser(), "fail_request **/a 500\nrestore_request **/zzz")
        check_eq("EP1-30 restore of an unknown pattern: a failed step", failed["outcome"], "failed")
        rows, failed, attempt, _ = _session(t, S.FakeBrowser(), "fail_request **/a 500\nrestore_request **/a\nrestore_request **/a")
        check_eq("EP1-30 restore twice: the second is a failed step", failed["step"], "restore_request **/a")
        # a failure that caught nothing and was restored: a limitation of the attempt and a name in the summary
        rows, failed, attempt, summary = _session(t, S.FakeBrowser(), "fail_request **/api/x 500\nrestore_request **/api/x")
        check_eq("EP1-30 idle restore: `failures_without_hits` in the summary", summary["failures_without_hits"], ["**/api/x"])
        check_in("EP1-30 idle restore: and a limitation the record carries", "fail_request **/api/x matched no request in this session",
                 " ".join(summary["limitations"]))
        captures = [json.loads(x) for x in (attempt.dir / "captures.jsonl").read_text(encoding="utf-8").splitlines()]
        check_eq("EP1-30 idle restore: the limitation sits on the log capture (build copies it into the record)",
                 [c["kind"] for c in captures if c.get("limitation")], ["log"])
        # a failure never restored: its log is written when the session ends, with the idle one named too
        browser = S.FakeBrowser()
        browser.on_call[("click", "#go")] = [("**/a", "GET", API)]
        rows, failed, attempt, summary = _session(t, browser, "fail_request **/a 500\nfail_request **/b timeout\nclick #go")
        logs = sorted(p.read_text(encoding="utf-8").splitlines()[0] for p in attempt.dir.glob("*fail-request*"))
        check_eq("EP1-30 end of session: a log per failure still on", logs, ["pattern: **/a", "pattern: **/b"])
        check_eq("EP1-30 end of session: the idle one is named", summary["failures_without_hits"], ["**/b"])
        # the session ends on a failed step: the logs are still written
        rows, failed, attempt, summary = _session(t, S.FakeBrowser(missing={"#nope"}), "fail_request **/a 500\nclick #nope")
        check_eq("EP1-30 a failed step does not lose the log", (failed["outcome"], len(list(attempt.dir.glob("*fail-request*")))), ("failed", 1))
        # a repeat of the pattern while it is on: the old record is kept first, the new one starts from zero
        browser = S.FakeBrowser()
        browser.on_call[("click", "#go")] = [("**/a", "GET", API)]
        rows, failed, attempt, summary = _session(t, browser, "fail_request **/a 500\nclick #go\nfail_request **/a 404")
        check_eq("EP1-30 repeat: the new record starts at zero, with the last word", (browser.failing["**/a"]["hits"], browser.failing["**/a"]["how"]), (0, "404"))
        texts = sorted(p.read_text(encoding="utf-8") for p in attempt.dir.glob("*fail-request*"))
        check_eq("EP1-30 repeat: both records are kept (what the old one caught is not lost)", [("requests failed: 1" in x, "failure: 500" in x) for x in texts[1:]]
                 + [("requests failed: 0" in texts[0], "failure: 404" in texts[0])], [(True, True), (True, True)])
        # the cap: 50 lines AT the cap, none of `... and N more`; 51 hits: the counter is exact and the lines stop at the cap
        for hits, more in ((50, False), (51, True)):
            browser = S.FakeBrowser()
            browser.on_call[("click", "#go")] = [("**/a", "GET", f"{API}/{i}") for i in range(hits)]
            rows, failed, attempt, summary = _session(t, browser, "fail_request **/a 500\nclick #go\nrestore_request **/a")
            lines = _failure_log(attempt).splitlines()
            check_eq(f"EP1-30 {hits} requests: the count is exact", lines[2], f"requests failed: {hits}")
            check_eq(f"EP1-30 {hits} requests: 50 lines at most, `... and 1 more` only beyond the cap",
                     (len([x for x in lines if x.startswith("GET ")]), "... and 1 more" in lines), (50, more))
        # a URL that holds a secret: the line is counted, not kept
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkw.sig"
        browser = S.FakeBrowser()
        browser.on_call[("click", "#go")] = [("**/a", "GET", f"{API}/{jwt}"), ("**/a", "GET", API)]
        rows, failed, attempt, summary = _session(t, browser, "fail_request **/a 500\nclick #go\nrestore_request **/a")
        text = _failure_log(attempt)
        check_not_in("EP1-30 a secret in the URL: no bytes of it are kept", "eyJ", S.tree_text(attempt.dir))
        check_in("EP1-30 a secret in the URL: the count stays and the line is said to be withheld", "requests failed: 2", text)
        check_in("EP1-30 a secret in the URL: withheld, counted", "1 request line(s) not stored", text)
        check_in("EP1-30 a secret in the URL: the clean line is kept", "GET " + API, text.splitlines())
        # a pattern that cannot be scanned keeps no line at all
        broken = {**t.cfg, "secret_content_patterns": ["("]}
        browser = S.FakeBrowser()
        browser.on_call[("click", "#go")] = [("**/a", "GET", API)]
        rows, failed, attempt, _ = _session(t, browser, "fail_request **/a 500\nclick #go\nrestore_request **/a", cfg=broken)
        lines = _failure_log(attempt).splitlines()
        check_eq("EP1-30 a pattern that cannot be scanned keeps the count and no request line (less text, never a secret)",
                 (failed, [x for x in lines if x.startswith("GET ")], "1 request line(s) not stored" in " ".join(lines)),
                 (None, [], True))
    finally:
        S.cleanup(t)


def ep1_30_host_of_the_pattern():
    t = S.make_task()
    try:
        for label, glob, allowed in (("a pattern with no host", "**/api/x", True), ("a stand host", "http://localhost:5173/api/**", True),
                                     ("another host", "http://evil.example/api/x", False), ("a wildcard host", "http://*/api/x", False),
                                     ("a stand host on another port", "http://localhost:9/api/x", False),
                                     ("a host with credentials", "http://u:p@localhost:5173/x", False)):
            browser = S.FakeBrowser()
            rows, failed, attempt, _ = _session(t, browser, f'fail_request "{glob}" 500')
            check_eq(f"EP1-30 host: {label}", (failed is None, bool([c for c in browser.calls if c[0] == "fail_request"])), (allowed, allowed))
            if not allowed:
                check_eq(f"EP1-30 host: {label} is refused, not failed", rows[-1]["outcome"], "refused")
                check_in(f"EP1-30 host: {label}: the door lists the stand hosts", "http://localhost:5173", failed["detail"])
    finally:
        S.cleanup(t)


class _TypePage:
    """TR1-1: a stub of Playwright's page with one field `#qty`. `drops`: the page takes the focus away after the first character
    typed into the field (the keys that follow go to the body); `gone`: the field is detached from the page."""

    def __init__(self, drops, gone=False):
        self.value, self.focused, self.drops, self.gone, self.typed, self.focus_calls = "", False, drops, gone, 0, 0
        self.pending_drop = False       # the first character's reading is the last one that shows the focus
        self.keyboard = self

    def locator(self, selector):
        return _TypeLoc(self)

    def wait_for_timeout(self, ms):
        return None

    def type(self, char):
        if self.focused:
            self.value += char
            self.typed += 1
            if self.drops and self.typed == 1:
                self.pending_drop = True

    def press(self, key):
        self.pressed = getattr(self, "pressed", []) + [(key, self.focused)]       # the key lands only where the focus is

    def insert_text(self, text):
        if self.focused:
            self.value += text


class _TypeLoc:
    def __init__(self, page):
        self.page, self.first = page, self

    def focus(self, timeout=None):
        self.page.focus_calls += 1
        self.page.focused = True

    def input_value(self, timeout=None):
        return self.page.value

    def evaluate(self, script, arg=None, timeout=None):
        if script == MC.CONNECTED_JS:
            return not self.page.gone
        if script == MC.ACTIVE_JS:
            return "body"
        seen = self.page.focused
        if self.page.pending_drop:
            self.page.pending_drop, self.page.focused = False, False
        return seen


class _TypeBrowser(S.FakeBrowser):
    """The FakeBrowser whose `type_chars` is the REAL backend's, over a `_TypePage`; the surprise detector is on (it reads no events)."""

    def __init__(self, page):
        super().__init__()
        real = MC.PlaywrightBackend.__new__(MC.PlaywrightBackend)
        real._page, real._Error, real._Timeout, real._element_ms, real._limit_ms = page, Exception, TimeoutError, 30000, 180000
        self.real, self.page = real, page

    def event_mark(self):
        return 0

    def events_since(self, mark):
        return []

    def dead_listeners(self):
        return []

    def type_chars(self, selector, text, delay_ms, settle_ms=0, continued=False):
        self._call("type", selector, text, continued)
        try:
            return self.real.type_chars(selector, text, delay_ms, settle_ms, continued=continued)
        finally:
            self.focus_lost_before = self.real.focus_lost_before

    def press_key(self, selector, key, continued=False):
        self._call("press", selector, key)
        try:
            return self.real.press_key(selector, key, continued=continued)
        finally:
            self.focus_lost_before = self.real.focus_lost_before

    def paste_text(self, selector, text, continued=False):
        self._call("paste", selector, text)
        try:
            return self.real.paste_text(selector, text, continued=continued)
        finally:
            self.focus_lost_before = self.real.focus_lost_before

    def click(self, selector):
        self._call("click", selector)
        self.page.focused = True               # a person's click puts the focus into the field
        return 0.1


def tr1_1_type_goes_on_without_a_new_focus():
    """TR1-1: a `type` that follows a `type` on the same field with no step between does not set the focus again."""
    def walk(page, lines):
        t = S.make_task()
        try:
            browser = _TypeBrowser(page)
            attempt = MC.Attempt(t.task, UI_CASE, "a1", t.cfg)
            steps = MC.parse_steps(f"goto {UI}\n" + "\n".join(lines) + "\n", MC.spec())[1:]
            steps = [dict(s, n=i) for i, s in enumerate(steps, 1)]
            rows, failed = MC._run_steps(browser, attempt, steps, 100, t.cfg, {}, 30, MC.SessionAccount())
            return rows, failed, page
        finally:
            S.cleanup(t)
    rows, failed, page = walk(_TypePage(drops=True), ["type #qty 1", "type #qty 2"])
    check_eq("TR1-1 two calls on a page that drops focus: the field holds only '1'", page.value, "1")
    check_eq("TR1-1 ... the first call is ok, the second is not", [r["outcome"] for r in rows], ["ok", "failed"])
    check_eq("TR1-1 ... the focus was set once (the first call), never again", page.focus_calls, 1)
    check_in("TR1-1 ... the step says what had the focus", "focus lost before the call: keys went to body", rows[1]["detail"])
    check("TR1-1 ... and a `surprise:` line names it", any("surprise:" in s and "focus lost before the call" in s for s in rows[1].get("surprise", [])),
          str(rows[1].get("surprise")))
    check_eq("TR1-1 ... and the walk stops there", failed["step"], "type #qty 2")
    rows, failed, page = walk(_TypePage(drops=True), ["type #qty 12"])
    check_eq("TR1-1 one call `type 12` on that page: the field holds '1'", page.value, "1")
    check_in("TR1-1 ... the record says 'focus lost after character 1' as before", "focus lost after character 1", rows[0]["detail"])
    check_eq("TR1-1 ... and that call stays ok (a told loss, not judged)", rows[0]["outcome"], "ok")
    rows, failed, page = walk(_TypePage(drops=False), ["type #qty 1", "type #qty 2"])
    check_eq("TR1-1 two calls on a page that holds focus: '12', both ok, the focus set once", (page.value, [r["outcome"] for r in rows], page.focus_calls),
             ("12", ["ok", "ok"], 1))
    rows, failed, page = walk(_TypePage(drops=True), ["type #qty 1", "click #qty", "type #qty 2"])
    check_eq("TR1-1 `type` after a `click` on the same field has the focus again: '12', all ok", (page.value, [r["outcome"] for r in rows]),
             ("12", ["ok", "ok", "ok"]))
    check_eq("TR1-1 ... the second `type` was a first one (it set the focus: two in all)", page.focus_calls, 2)
    # B1: a passive step (data: `keeps_run`) is not an action - a person who types '1', looks and types '2' does not click again
    for passive in ("read #qty", "wait 100"):
        rows, failed, page = walk(_TypePage(drops=True), ["type #qty 1", passive, "type #qty 2"])
        check_eq(f"TR1-1 `{passive}` between on a page that drops focus: field '1', the second `type` not ok, one focus",
                 (page.value, [r["outcome"] for r in rows], page.focus_calls), ("1", ["ok", "ok", "failed"], 1))
        check("TR1-1 ... and a `surprise:` line names it", any("surprise:" in s and "focus lost before the call" in s for s in rows[2].get("surprise", [])),
              str(rows[2].get("surprise")))
        rows, failed, page = walk(_TypePage(drops=False), ["type #qty 1", passive, "type #qty 2"])
        check_eq(f"TR1-1 `{passive}` between on a page that holds focus: '12', all ok, one focus",
                 (page.value, [r["outcome"] for r in rows], page.focus_calls), ("12", ["ok", "ok", "ok"], 1))
    rows, failed, page = walk(_TypePage(drops=True), ["type #qty 1", "read #qty", "click #qty", "type #qty 2"])
    check_eq("TR1-1 an action (`click`) after the passive step resets the run: '12', all ok", (page.value, [r["outcome"] for r in rows]),
             ("12", ["ok", "ok", "ok", "ok"]))
    check("TR1-1 the `keeps_run` list is data on the `type` row", "read" in MC.spec()["steps"]["type"]["keeps_run"]
          and "click" not in MC.spec()["steps"]["type"]["keeps_run"], str(MC.spec()["steps"]["type"].get("keeps_run")))
    rows, failed, page = walk(_TypePage(drops=True), ["type #qty 1", "type #qty 2"])
    check_in("TR1-1 F9 the refusal names the door: a `click` on the field", "a `click` on the field is a person's new click", rows[1]["detail"])
    rows, failed, page = walk(_TypePage(drops=False), ["type #qty 1", "type #other 2"])
    check_eq("TR1-1 a `type` on a DIFFERENT field is a first `type`", page.focus_calls, 2)
    page = _TypePage(drops=False)
    t = S.make_task()
    try:
        browser = _TypeBrowser(page)
        attempt = MC.Attempt(t.task, UI_CASE, "a1", t.cfg)
        MC._run_step(browser, attempt, {"word": "type", "args": ["#qty", "1"], "line": "type #qty 1"}, 100, t.cfg, {})
        page.gone = True
        entry = MC._run_step(browser, attempt, {"word": "type", "args": ["#qty", "2"], "line": "type #qty 2"}, 100, t.cfg, {})["entry"]
        check_eq("TR1-1 a field gone before the second call: not ok, nothing typed", (entry["outcome"], page.value), ("failed", "1"))
        check_in("TR1-1 ... with that fact", "gone or detached before the call", entry["detail"])
        check_eq("TR1-1 ... and no log of the call (only the first call's)", len(list(attempt.dir.glob("*-type-*.txt"))), 1)
    finally:
        S.cleanup(t)


def tr1_2_press_paste_go_on_after_a_type():
    """TR1-2 (sibling of TR1-1, the Lead's decision): `press` / `paste` right after a `type` on the same field set no new focus, under the
    same rule and the same fact; a step between, or another field, makes them a first call."""
    def walk(page, lines):
        t = S.make_task()
        try:
            browser = _TypeBrowser(page)
            attempt = MC.Attempt(t.task, UI_CASE, "a1", t.cfg)
            steps = MC.parse_steps(f"goto {UI}\n" + "\n".join(lines) + "\n", MC.spec())[1:]
            steps = [dict(s, n=i) for i, s in enumerate(steps, 1)]
            rows, failed = MC._run_steps(browser, attempt, steps, 100, t.cfg, {}, 30, MC.SessionAccount())
            return rows, failed, page
        finally:
            S.cleanup(t)
    rows, failed, page = walk(_TypePage(drops=True), ["type #qty 1", "press #qty Enter"])
    check_eq("TR1-2 `press Enter` after a `type` on a page that dropped the focus: not ok, no new focus",
             ([r["outcome"] for r in rows], page.focus_calls), (["ok", "failed"], 1))
    check_in("TR1-2 ... the fact is the TR1-1 fact", "focus lost before the call: keys went to body", rows[1]["detail"])
    check("TR1-2 ... and a `surprise:` line names it", any("surprise:" in s and "focus lost before the call" in s for s in rows[1].get("surprise", [])),
          str(rows[1].get("surprise")))
    check_eq("TR1-2 ... the key landed where the focus was, not in the field", getattr(page, "pressed", []), [("Enter", False)])
    rows, failed, page = walk(_TypePage(drops=False), ["type #qty 1", "press #qty Enter"])
    check_eq("TR1-2 `press Enter` after a `type` on a page that holds the focus: ok, the focus set once (no new click)",
             ([r["outcome"] for r in rows], page.focus_calls), (["ok", "ok"], 1))
    rows, failed, page = walk(_TypePage(drops=False), ["type #qty 1", "paste #qty 2"])
    check_eq("TR1-2 `paste` after a `type`: ok, '12', the focus set once", (page.value, [r["outcome"] for r in rows], page.focus_calls),
             ("12", ["ok", "ok"], 1))
    rows, failed, page = walk(_TypePage(drops=True), ["type #qty 1", "paste #qty 2"])
    check_eq("TR1-2 `paste` after a `type` that dropped the focus: not ok, nothing pasted", ([r["outcome"] for r in rows], page.value),
             (["ok", "failed"], "1"))
    rows, failed, page = walk(_TypePage(drops=False), ["type #qty 1", "press #other Enter"])
    check_eq("TR1-2 a `press` on a DIFFERENT field is a first call: it sets its own focus (two in all)", page.focus_calls, 2)
    rows, failed, page = walk(_TypePage(drops=False), ["type #qty 1", "paste #other 2"])
    check_eq("TR1-2 a `paste` on a DIFFERENT field is a first call: it sets its own focus (two in all)", page.focus_calls, 2)
    rows, failed, page = walk(_TypePage(drops=True), ["type #qty 1", "read #qty", "press #qty Enter"])
    check_eq("TR1-2 a `read` between the `type` and the `press` is not an action: the press goes on, no new focus, not ok",
             ([r["outcome"] for r in rows], page.focus_calls), (["ok", "ok", "failed"], 1))
    rows, failed, page = walk(_TypePage(drops=True), ["type #qty 1", "click #qty", "press #qty Enter"])
    check_eq("TR1-2 a `click` between the `type` and the `press` makes the press a first call",
             ([r["outcome"] for r in rows], page.focus_calls), (["ok", "ok", "ok"], 2))
    rows, failed, page = walk(_TypePage(drops=False), ["press #qty Enter", "press #qty Enter"])
    check_eq("TR1-2 a `press` after a `press` (no `type`) is a first call each time", page.focus_calls, 2)


def tr1_2_failure_rule_forgotten():
    """TR1-2: a lifted rule is out of the closing capture and reports its empty result at once; a pattern with a single leading `*` gets a hint."""
    t = S.make_task()
    try:
        # (1) a rule that matched nothing, lifted: the restore answer carries the surprise line, the log says `requests failed: 0`, the capture passes
        rows, failed, attempt, summary = _session(t, S.FakeBrowser(), "fail_request **/api/x 500\nrestore_request **/api/x\ncapture post_action completion")
        check_eq("TR1-2 rule with no match, restore, capture post_action: all ok", (failed, [r["outcome"] for r in rows][1:]), (None, ["ok", "ok", "ok"]))
        check_in("TR1-2 the `restore_request` answer says the rule matched nothing", "surprise: fail_request **/api/x matched no request", rows[2]["detail"])
        check_in("TR1-2 the result of the lifted rule is written: `requests failed: 0`", "requests failed: 0", _failure_log(attempt))
        # (2) an ACTIVE rule with no match still refuses the capture, as before
        rows, failed, attempt, _ = _session(t, S.FakeBrowser(), "fail_request **/api/x 500\ncapture post_action completion")
        check_eq("TR1-2 an active rule with no match: the capture is refused", (rows[-1]["outcome"], _post_shots(attempt)), ("refused", []))
        # (2b) one lifted rule and one active with no match: only the active one is named
        rows, failed, attempt, _ = _session(t, S.FakeBrowser(), "fail_request **/a 500\nfail_request **/b 500\nrestore_request **/a\ncapture post_action completion")
        check_in("TR1-2 lifted and active: the refusal names the active one", "no request matched **/b in this session", failed["detail"])
        check_not_in("TR1-2 lifted and active: and not the lifted one", "**/a in this session", failed["detail"])
        # (3) the first look/read after the lifting repeats the line, once
        rows, failed, attempt, _ = _session(t, S.FakeBrowser(), "fail_request **/api/x 500\nrestore_request **/api/x\nread #x\nread #x")
        check_in("TR1-2 the first `read` after the lifting says the rule matched nothing", "surprise: fail_request **/api/x matched no request", rows[3]["detail"])
        check_not_in("TR1-2 the second `read` does not repeat it", "matched no request", rows[4]["detail"])
        # a rule that DID match: no such line anywhere
        browser = S.FakeBrowser()
        browser.on_call[("click", "#go")] = [("**/api/x", "GET", API)]
        rows, failed, attempt, _ = _session(t, browser, "fail_request **/api/x 500\nclick #go\nrestore_request **/api/x\nread #x")
        check_not_in("TR1-2 a rule that matched: no 'matched no request' line", "matched no request", " ".join(r["detail"] for r in rows))
        # (4) the pattern hint: a single leading `*` and no `**`, no scheme
        rows, failed, attempt, _ = _session(t, S.FakeBrowser(), "fail_request */api/cart 500")
        check_eq("TR1-2 `*/api/cart`: the step is ok (a hint, never a refusal)", (failed, rows[-1]["outcome"]), (None, "ok"))
        check_in("TR1-2 `*/api/cart`: the hint says `*` does not cross `/`", "does not cross `/`", rows[-1]["detail"])
        check_in("TR1-2 `*/api/cart`: and names the way to write it", "**/api/x", rows[-1]["detail"])
        check_in("F6 `*/api/cart`: the hint is a typed `told` line of the step row", "does not cross `/`", " ".join(rows[-1].get("told") or []))
        check_not_in("F6 `**/api/cart`: no `told` on the row", "does not cross", " ".join(
            _session(t, S.FakeBrowser(), "fail_request **/api/cart 500")[0][-1].get("told") or []))
        rows, failed, attempt, _ = _session(t, S.FakeBrowser(), "fail_request **/api/x 500\nrestore_request **/api/x\nread #x\nread #x")
        check_in("F6 `restore_request`: the line is `told` on the restore row", "matched no request", " ".join(rows[2].get("told") or []))
        check_in("F6 ... and on the first `read` after it", "matched no request", " ".join(rows[3].get("told") or []))
        check_eq("F6 ... and not on the second `read`", rows[4].get("told"), None)
        rows, failed, attempt, _ = _session(t, S.FakeBrowser(), "fail_request **/api/cart 500")
        check_not_in("TR1-2 `**/api/cart`: no hint", "hint:", rows[-1]["detail"])
        rows, failed, attempt, _ = _session(t, S.FakeBrowser(), 'fail_request "http://localhost:5173/api/*" 500')
        check_not_in("TR1-2 a pattern with a scheme: no hint", "hint:", rows[-1]["detail"])
    finally:
        S.cleanup(t)


class _CookieBrowser(S.FakeBrowser):
    """TR1-3: a scripted browser whose context holds `held` cookies; `end_session` is the backend's contract: (count, seconds)."""

    def __init__(self, held=0, **kw):
        super().__init__(**kw)
        self.held = held

    def end_session(self):
        self._call("end-session")
        count, self.held = self.held, 0
        return count, 0.1


class _CookieContext:
    """The browser context the REAL `end_session` talks to: a cookie list, `cookies()` and `clear_cookies()`."""

    def __init__(self, names):
        self.jar = [{"name": n, "value": "secret-" + n, "domain": "localhost", "path": "/"} for n in names]

    def cookies(self):
        return list(self.jar)

    def clear_cookies(self):
        self.jar = []

    def request_cookie_header(self):
        return "; ".join(f"{c['name']}={c['value']}" for c in self.jar)


def tr1_3_end_session():
    """TR1-3: `end-session` deletes the cookies of the actor's browser context, says how many, and is a said no-op when there are none."""
    data = MC.spec()
    check_eq("TR1-3 data: the step is a row of the browser list, no argument, and not a step of a device",
             (data["steps"]["end-session"]["arity"], "end-session" in data["app_steps"]), ([0, 0], False))
    # the REAL backend method on a stub context: signed in -> the next request carries no cookie; the page is not touched
    backend = MC.PlaywrightBackend.__new__(MC.PlaywrightBackend)
    backend._Timeout = backend._Error = RuntimeError
    backend._context = _CookieContext(["testproject1_access_token", "refresh"])
    check_in("TR1-3 signed in: a request of the page carries the session cookie", "testproject1_access_token=", backend._context.request_cookie_header())
    count, seconds = backend.end_session()
    check_eq("TR1-3 after sign-in, `end-session` deletes both cookies and counts them", (count, seconds >= 0), (2, True))
    check_eq("TR1-3 the next request of the page goes without a cookie", backend._context.request_cookie_header(), "")
    check_eq("TR1-3 twice in a row: the second deletes nothing and counts 0", backend.end_session()[0], 0)
    backend._context = _CookieContext([])
    check_eq("TR1-3 a guest (an empty context): 0, no error", backend.end_session()[0], 0)
    t = S.make_task()
    try:
        rows, failed, attempt, _ = _session(t, _CookieBrowser(held=3), "end-session")
        check_eq("TR1-3 step: ok, the answer names the count", (failed, rows[-1]["outcome"], "3 cookies deleted" in rows[-1]["detail"]), (None, "ok", True))
        check_not_in("TR1-3 step answer holds no cookie value", "secret", rows[-1]["detail"])
        browser = _CookieBrowser(held=1)
        rows, failed, attempt, _ = _session(t, browser, "end-session\nend-session")
        check_eq("TR1-3 twice in a row: the first deletes, the second says 0 cookies and is not a failure",
                 (failed, [r["outcome"] for r in rows][1:], "1 cookie deleted" in rows[1]["detail"], rows[2]["detail"].startswith("0 cookies")),
                 (None, ["ok", "ok"], True, True))
        rows, failed, attempt, _ = _session(t, _CookieBrowser(held=0), "end-session")
        check_eq("TR1-3 an actor with no cookies (a guest, not signed in): ok, and the answer SAYS 0 cookies",
                 (failed, rows[-1]["outcome"], rows[-1]["detail"].startswith("0 cookies")), (None, "ok", True))
        check_in("TR1-3 the recorded step is evidence like every step (the step row)", "end-session", rows[-1]["step"])
    finally:
        S.cleanup(t)
    # refusals: an argument, a device list; each says what is wrong, what was expected and a door
    for label, text in (("an argument", "end-session now"), ("two arguments", "end-session a b")):
        try:
            MC.parse_steps(f"goto {UI}\n{text}\n", data)
            check(f"TR1-3 {label}: refused", False)
        except ValueError as exc:
            check_in(f"TR1-3 {label}: says what is wrong and expected", "`end-session` takes no argument", str(exc))
            check_in(f"TR1-3 {label}: and the door", "write `end-session` alone on its line", str(exc))
    try:
        MC.parse_steps("end-session\n", data, words=MC.APP_WORDS)
        check("TR1-3 on a device: refused", False)
    except ValueError as exc:
        check_in("TR1-3 on a device: refused, naming the browser surface", "`end-session` is a step of the browser surface", str(exc))
        check_in("TR1-3 on a device: and the steps a device has", "launch", str(exc))
    # the requirement reaches the walker before the work (AR-10)
    commands = (Path(__file__).resolve().parent.parent.parent / "references" / "role-commands.json").read_text(encoding="utf-8")
    check_eq("TR1-3 role-commands.json names the step on the walker's card and on the `ui` card", commands.count("end-session"), 2)


def main():
    tr1_3_end_session()
    tr1_1_type_goes_on_without_a_new_focus()
    tr1_2_press_paste_go_on_after_a_type()
    tr1_2_failure_rule_forgotten()
    ep1_32_read_modes()
    ep1_30_parse_and_data()
    ep1_30_post_action_needs_a_hit()
    ep1_30_restore_log_and_summary()
    ep1_30_host_of_the_pattern()
    ep1_29_parse_and_data()
    ep1_29_run()
    ep1_28_capture_profile()
    ep1_28_default_probe()
    ep1_28_other_profile()
    case_ids_and_hosts()
    timeouts()
    ui_happy_path()
    ui_failures()
    ui_refusals()
    login_and_secrets()
    probes()
    browser_unavailable()
    http_captures()
    http_user_agent_and_foreign_answers()
    http_edges()
    element_wait()
    limits()
    attempts()
    one_profile_per_attempt()
    k3_records()
    build_refusals()
    landing_late()
    landing_never()
    landing_proofs()
    landing_limit()
    landing_secrets()
    landing_recipe_refusals()
    landing_off_stand()
    landing_errors()
    landing_data_and_overrides()
    landing_before_submit()
    read_login_adversarial()
    t308_f1_a_login_declared_null_is_never_read()
    t308_f2_an_explicit_attempt_of_a_login_that_did_not_land()
    t308_f3_a_recipe_that_is_not_an_object_is_refused()
    finish("test_manual_capture")


if __name__ == "__main__":
    main()
