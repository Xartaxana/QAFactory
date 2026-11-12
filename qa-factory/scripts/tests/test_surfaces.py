#!/usr/bin/env python3
"""EP1-41a: the web lock (the pin), then the surfaces table and its one reader.

THE PIN (`fixtures/surface-web-pin/`). Taken on the untouched code, in the commit that precedes every line of
`surfaces.py`: what a web project's `manual_capture.py ui` / `http`, its `_blocked` refusals, its
`readiness.compute` environment and the data bytes of the capture steps give. The comparison is byte for byte; the browser
and the HTTP client are the fakes of `fixtures/manual-evidence/scaffold.py` (`MC.BACKEND_FACTORY`, `MC.HTTP`, `MC.PROBE`,
`MC.NOW` = the scaffold's one-second clock; the fake backend's step durations are its own constants). The pin changes only
by the word of Lead in a verdict (AR-20); `--write-pin` is the one way its files are made, never run to turn a red line green.
"""
import json
import shutil
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402

MC = S.MC
PIN = HERE / "fixtures" / "surface-web-pin"
PLUGIN = HERE.parents[1]
UI_URL = "http://localhost:5173/workflows/w1/diff"
UI_CASE, API_CASE = S.CASES["ui"], S.CASES["api"]
STEPS = f"goto {UI_URL}\ncapture pre_action initial\nclick \"button[aria-label='Zoom in']\"\ncapture post_action completion\n"


def _config(**over):
    cfg = S.config(**over)
    if "profiles" not in over:
        cfg["profiles"] = [*cfg["profiles"], {"profile_id": "api", "commands": {
            "one_test": {"argv": ["poetry", "run", "pytest", "<test-file>"], "cwd": "."}}}]
    return cfg


def _patch(browser=None, http=None, probes=None):
    MC.BACKEND_FACTORY = (lambda: browser) if browser is not None else None
    MC.MONOTONIC = browser.monotonic if browser is not None and hasattr(browser, "monotonic") else None
    MC.HTTP = http
    MC.PROBE = probes or (lambda spec: S.probe("api" if spec["argv"] == ["probe-api"] else "e2e-ui"))
    MC.NOW = S.Clock()


def _norm(text, task):
    """The temp project's path is the one thing that differs between two runs: replaced by a word."""
    project = str(task.project)
    for form in (project, project.replace("\\", "\\\\"), project.replace("\\", "/")):
        text = text.replace(form, "<PROJECT>")
    return text.replace("\r\n", "\n")


def _read(path):
    return Path(path).read_text(encoding="utf-8") if Path(path).is_file() else ""


def _ui(steps=STEPS, browser=None, probes=None, cfg=None):
    t = S.make_task(cfg=cfg or _config())
    steps_file = t.task / "steps.txt"
    steps_file.write_text(steps, encoding="utf-8")
    _patch(browser or S.FakeBrowser(), probes=probes)
    code, out, err = S.run(["ui", "--task-root", str(t.task), "--case", UI_CASE, "--steps-file", str(steps_file)])
    return t, code, out, err


def _unknown_probe(spec):
    return dict(S.probe(result="unknown"), evidence_refs=[], provenance={"technical_verification": False})


def capture_pin() -> dict:
    """{file name: text} of every web fact the pin holds. Nothing here reads the surfaces table."""
    out = {}
    t, code, stdout, stderr = _ui()
    try:
        folder = t.attempt_dir(UI_CASE)
        out["ui-exit.txt"] = f"{code}\n"
        out["ui-stdout.json"] = _norm(stdout, t)
        out["ui-stderr.txt"] = _norm(stderr, t)
        for name in ("steps.jsonl", "captures.jsonl", "probes.jsonl"):
            out[f"ui-{name}"] = _norm(_read(folder / name), t)
    finally:
        S.cleanup(t)
    t = S.make_task(manual=("api",), cfg=_config())
    try:
        get = "http://localhost:8080/v1/workflows/w1"
        http = S.FakeHttp({("POST", "http://localhost:8080/v1/local-auth/login"): S.ok_json({"access_token": S.TOKEN}),
                           ("GET", get): S.ok_json({"id": "w1"})})
        _patch(http=http)
        code, stdout, stderr = S.run(["http", "--task-root", str(t.task), "--case", API_CASE, "--method", "GET", "--url", get,
                                      "--phase", "pre_action", "--proves", "before state"])
        folder = t.attempt_dir(API_CASE)
        out["http-exit.txt"] = f"{code}\n"
        out["http-stdout.json"] = _norm(stdout, t)
        out["http-stderr.txt"] = _norm(stderr, t)
        out["http-probes.jsonl"] = _norm(_read(folder / "probes.jsonl"), t)
    finally:
        S.cleanup(t)
    # `_blocked`: every branch, stdout row and stderr; the http call with a probe that returns `unknown` also leaves env_blocked.json
    t = S.make_task(manual=("api",), cfg=_config())
    try:
        _patch(http=S.FakeHttp(), probes=_unknown_probe)
        code, stdout, stderr = S.run(["http", "--task-root", str(t.task), "--case", API_CASE, "--method", "GET",
                                      "--url", "http://localhost:8080/v1/x"])
        out["http-blocked-exit.txt"] = f"{code}\n"
        out["http-blocked-stdout.json"] = _norm(stdout, t)
        out["http-blocked-stderr.txt"] = _norm(stderr, t)
        out["http-blocked-env_blocked.json"] = _norm(_read(t.attempt_dir(API_CASE) / "env_blocked.json"), t)
    finally:
        S.cleanup(t)
    branches = {
        "build": dict(probes=lambda spec: dict(S.probe(result="mismatched"), observed_runtime_identity="d" * 40,
                                               provenance={"technical_verification": True, "source_linkage": "exact",
                                                           "deployed_source_revision": "d" * 40})),
        "stand": dict(probes=_unknown_probe),
        "login-user": dict(browser=S.FakeBrowser(urls=[S.SIGN_IN_URL], cookies_at=None, field_gone_at=None,
                                                 words="Please, sign in to continue. Sign In")),
        "login-factory": dict(browser=S.FakeBrowser(login_error=MC.StepFailed("no element matched within 30 s"))),
    }
    for name, kwargs in branches.items():
        t, code, stdout, stderr = _ui(**kwargs)
        try:
            out[f"blocked-{name}-exit.txt"] = f"{code}\n"
            out[f"blocked-{name}-stdout.json"] = _norm(stdout, t)
            out[f"blocked-{name}-stderr.txt"] = _norm(stderr, t)
        finally:
            S.cleanup(t)
    out["readiness-environment.json"] = json.dumps(readiness_environments(), indent=2, sort_keys=True) + "\n"
    out["data-bytes.json"] = json.dumps(data_blocks(), indent=2) + "\n"
    return out


def readiness_environments() -> dict:
    """`readiness.compute(...)["capabilities"]["environment"]` on three web configs, and whether `surfaces` is a key.
    Not byte for byte of the whole document: `compute` reads the clock, runs a process and may reach the network, so the
    process, `shutil.which` and the config's own-key check are replaced."""
    import readiness as R
    result = {}
    stands = {
        "url-row": {"environments": [{"name": "local", "base_url": "http://localhost:8080"}]},
        "in-process": {"environments": [{"name": "unit", "kind": "in-process"}]},
        "mixed-without-surface": {"environments": [{"name": "local", "base_url": "http://localhost:8080"},
                                                   {"name": "unit", "kind": "in-process"}]},
    }
    probe_answer = json.dumps({"liveness": {"verdict": "ok", "note": "up"}, "login": {"status": "ok"},
                               "keys": {"verdict": "ok"}, "layer1": []})
    for label, extra in stands.items():
        cfg = {"environment": {"env_file": "harness/.env", "user_key": "AUTH_USERNAME"}, **extra,
               "profiles": [{"profile_id": "e2e-ui", "capabilities": ["web"]}]}
        root = S.make_task(cfg=cfg).project
        try:
            fake = mock.Mock(return_value=mock.Mock(stdout=probe_answer, returncode=0))
            with mock.patch.object(R.subprocess, "run", fake), mock.patch.object(R.shutil, "which", return_value=None), \
                    mock.patch.object(R, "config_fails_own_probe", return_value=None):
                data = R.compute(cfg, root)
            result[label] = {"environment": data["capabilities"]["environment"], "has_surfaces_key": "surfaces" in data}
        finally:
            shutil.rmtree(root, ignore_errors=True)
    return result


def data_blocks() -> dict:
    """The data bytes the web road reads: the `steps` and `login` blocks of manual-capture-steps.json, and the two role-command rows."""
    steps = json.loads((PLUGIN / "references" / "manual-capture-steps.json").read_text(encoding="utf-8"))
    commands = json.loads((PLUGIN / "references" / "role-commands.json").read_text(encoding="utf-8"))
    rows = {k: v for k, v in _find(commands, ("manual_capture.py ui", "manual_capture.py http")).items()}
    return {"steps": steps["steps"], "login": steps["login"], "role_commands": rows}


def _find(node, names):
    found = {}
    if isinstance(node, dict):
        for key, value in node.items():
            if key in names:
                found[key] = value
            else:
                found.update(_find(value, names))
    return found


def web_pin():
    pinned = {p.name: p.read_text(encoding="utf-8") for p in sorted(PIN.glob("*"))} if PIN.is_dir() else {}
    check("web pin: the fixture folder exists and holds the files", len(pinned) >= 20, f"{len(pinned)} files")
    now = capture_pin()
    check_eq("web pin: the set of files is the pin's", sorted(now), sorted(pinned))
    for name in sorted(now):
        check(f"web pin: {name} is byte for byte the pin's", now[name] == pinned.get(name),
              f"\n--- now\n{now[name][:600]}\n--- pin\n{pinned.get(name, '')[:600]}")
    check_eq("web pin: the web readiness has no `surfaces` key on any of its three configs",
             [v["has_surfaces_key"] for v in json.loads(now["readiness-environment.json"]).values()], [False] * 3)


# ---- the table and its reader (written after the pin) -------------------------------------------------------------------

import contextlib  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402

sys.path.insert(0, str(PLUGIN / "scripts"))
import surfaces as SF  # noqa: E402

LANGUAGE_WORDS = re.compile(r"pytest|typescript|kotlin|java|python|gradle|gradlew|junit|testng|espresso|webdriverio", re.I)


def profile(pid="mobile", *caps, command=None):
    return {"profile_id": pid, "capabilities": list(caps),
            "commands": {"one_test": {"argv": command or ["./gradlew", "test"], "cwd": "."}}}


def stand(name, surface=None, **extra):
    row = {"name": name, **extra}
    if surface is not None:
        row["surface"] = surface
    return row


@contextlib.contextmanager
def counted(table_path=None):
    """`surfaces.rows` counted; the table may be pointed at another file. Yields the list of calls."""
    calls = []
    real = SF.rows

    def counting():
        calls.append(1)
        return real()
    held = SF.TABLE_PATH
    with mock.patch.object(SF, "rows", counting):
        if table_path is not None:
            SF.TABLE_PATH = table_path
        try:
            yield calls
        finally:
            SF.TABLE_PATH = held


def broken_table():
    folder = Path(tempfile.mkdtemp(prefix="qa-surfaces-"))
    path = folder / "surfaces.json"
    path.write_text("{ this is not json", encoding="utf-8")
    return folder, path


def table_data():
    data = SF.rows()
    check_eq("table: the Appium row of the driver block reads status, ready field, session path (read from a real tool, [5])",
             (data["drivers"]["appium"]["status_path"], data["drivers"]["appium"]["ready_field"],
              data["drivers"]["appium"]["session_path"]), ("/status", "value.ready", "/session"))
    check_eq("table: the session timeout follows the tool read at [5] (120 s)", data["drivers"]["appium"]["session_timeout_s"], 120)
    check_eq("table: the tool timeout is data", data["tool_timeout_s"], 10)
    rows_ = data["surfaces"]
    check_eq("table: the web and api rows carry no level and the device rows fit e2e-ui",
             [rows_["web"]["fits_levels"], rows_["api"]["fits_levels"], rows_["android"]["fits_levels"]], [[], [], ["e2e-ui"]])
    check_eq("table: host_os [] means any host (a list, not an absent key)", rows_["android"]["host_os"], [])
    check_eq("table: the device rows share the capability word `native`", {rows_["android"]["capability"], rows_["ios"]["capability"]}, {"native"})
    spec = MC.spec()["capture_surfaces"]
    check_eq("cross-check: capture_surfaces ui/http name the capability of the web/api rows, and are table_free",
             [(spec["ui"]["capabilities"], spec["http"]["capabilities"], spec["ui"]["table_free"], spec["http"]["table_free"])],
             [([rows_["web"]["capability"]], [rows_["api"]["capability"]], True, True)])
    check_eq("table: the free words are read through the capture's own reader", SF._table_free_words(), {"web", "api"})
    text = SF.TABLE_PATH.read_text(encoding="utf-8") + (PLUGIN / "scripts" / "surfaces.py").read_text(encoding="utf-8")
    check("AR-1: no test language, runner or adapter list in the table or its reader (positive control: `native` is there)",
          "native" in text and not re.search(r"read_test_adapters|framework_adapter|pytest|typescript|kotlin|java", text, re.I))


def declared():
    web = {"profiles": [profile("e2e-ui", "web"), profile("api", "api")], "environments": [stand("local")]}
    with counted() as calls:
        check_eq("web+api: nothing to say, and the table was not read", (SF.declared_surfaces(web), len(calls)), ({}, 0))
        check_eq("no profiles at all: nothing to say, table not read", (SF.declared_surfaces({}), len(calls)), ({}, 0))
        check_eq("a stand without `surface`: row_of is None and the table is not read", (SF.row_of({"name": "x"}), len(calls)), (None, 0))
        check_eq("stand_rows of a web project: [] without a read", (SF.stand_rows(web), len(calls)), ([], 0))
    with counted() as calls:
        check("positive control of the counter: a native profile reads the table", SF.declared_surfaces(
            {"profiles": [profile("m", "native")]}) != {} and len(calls) >= 1)
    desktop = SF.declared_surfaces({"profiles": [profile("d", "desktop")]})
    check_eq("desktop: the cases go to a person, in the table's words", (desktop["desktop"]["hands"], desktop["desktop"]["words"]),
             ("person", SF.rows()["surfaces"]["desktop"]["words"]))
    cli = SF.declared_surfaces({"profiles": [profile("c", "cli")]})
    check_eq("cli alone: words", (cli["cli"]["hands"], bool(cli["cli"]["words"])), ("person", True))
    check_eq("cli beside web: silent", SF.declared_surfaces({"profiles": [profile("c", "cli"), profile("w", "web")]}), {})
    check_eq("cli beside a native profile: silent (the native arm speaks)", sorted(SF.declared_surfaces(
        {"profiles": [profile("c", "cli"), profile("m", "native")]})), ["native"])
    check_eq("desktop beside web still speaks", sorted(SF.declared_surfaces({"profiles": [profile("d", "desktop"), profile("w", "web")]})), ["desktop"])
    gap = SF.declared_surfaces({"profiles": [profile("m", "native")], "environments": [stand("local")]})
    check_eq("native without a described device stand: said, as a person's", (sorted(gap), gap["native"]["hands"], gap["native"]["stand"]),
             (["native"], "person", None))
    check_in("... in the table's words", "no stand for an agent's hands is described", gap["native"]["words"])
    gradle = SF.declared_surfaces({"profiles": [profile("m", "native", command=["./gradlew", "test"])]})
    check_eq("a native profile whose command and tests are in any language: no language word in `surfaces` at all",
             LANGUAGE_WORDS.search(json.dumps(gradle)), None)
    check_eq("... nor in `unsupported`", LANGUAGE_WORDS.search(json.dumps(SF.unsupported({"profiles": [profile("m", "native", command=["gradlew", "test", "--tests", "LoginTest.kt"])]}))), None)
    with_stand = SF.declared_surfaces({"profiles": [profile("m", "native")], "environments": [stand("emulator", "android")]})
    check_eq("native with a described device stand: the agent holds the hands", (sorted(with_stand), with_stand["android"]["hands"],
                                                                            with_stand["android"]["stand"]), (["android"], "agent", "emulator"))
    ios = SF.declared_surfaces({"profiles": [profile("m", "native")], "environments": [stand("sim", "ios")]})
    check_in("the iOS row says what has not been run", "has not been run on a real project", ios["ios"]["words"])
    check_eq("unsupported: only what goes to a person", sorted(SF.unsupported({"profiles": [profile("m", "native"), profile("d", "desktop")],
                                                                                "environments": [stand("e", "android")]})), ["desktop"])
    unknown = SF.declared_surfaces({"profiles": [profile("x", "mobile-web")]})
    check_eq("a word the table lacks speaks (t-524 9.2, F-4): a person's, with the table's words and the word named",
             (sorted(unknown), unknown["mobile-web"]["hands"], unknown["mobile-web"]["stand"], "mobile-web" in unknown["mobile-web"]["words"]),
             (["mobile-web"], "person", None, True))
    check_eq("... and so does a project's own `mobile`, `android`, `appium`", sorted(SF.unsupported({"profiles": [profile("x", "mobile", "android", "appium")]})),
             ["android", "appium", "mobile"])
    check_eq("the catalogue words that are no place to test on (`not_surfaces`) stay silent, with or without a table-free word",
             (SF.declared_surfaces({"profiles": [profile("x", "unit", "event", "manual")]}),
              SF.declared_surfaces({"profiles": [profile("x", "unit", "web", "api", "manual")]})), ({}, {}))
    check_eq("an unknown word beside a native one: both are said", sorted(SF.unsupported({"profiles": [profile("x", "native", "kiosk")]})),
             ["kiosk", "native"])
    check_eq("an unknown word carries no language word", LANGUAGE_WORDS.search(json.dumps(unknown)), None)
    try:
        SF.row_of({"name": "e", "surface": "andriod"})
        check("a surface the table lacks is refused (a typo never becomes the web)", False)
    except ValueError as exc:
        check("a surface the table lacks is refused, naming the list", "Expected one of:" in str(exc) and "web" in str(exc), str(exc))
    for label, cfg in (("profiles is a dict", {"profiles": {"a": 1}}), ("profiles is a string", {"profiles": "web"}),
                       ("capabilities is a string", {"profiles": [{"profile_id": "p", "capabilities": "native"}]})):
        got = SF.declared_surfaces(cfg)
        check_eq(f"{label}: unknown, no crash, no `native` promise", (list(got), "not a list" in got.get("unknown", "")), (["unknown"], True))


def broken():
    folder, path = broken_table()
    try:
        import readiness as R
        with counted(path) as calls:
            native = {"profiles": [profile("m", "native")], "environments": [stand("e", "android")]}
            try:
                SF.declared_surfaces(native)
                check("a broken table with native: a ValueError", False)
            except ValueError as exc:
                check_in("a broken table with native: the error names the file and is the factory's", "factory defect", str(exc))
            doc = R.compute({**native, "environment": {}}, folder)
            check_eq("a broken table with native: readiness publishes `surfaces.unknown`, no crash, no silence",
                     list(doc.get("surfaces", {})), ["unknown"])
            check("... and it is not a pass: the text says the table cannot be read", "cannot be read" in doc["surfaces"]["unknown"])
            try:
                SF.declared_surfaces({"profiles": [profile("m", "native", "kiosk")]})
                check("a broken table with a native word and an unknown one: a ValueError", False)
            except ValueError:
                doc = R.compute({"profiles": [profile("m", "native", "kiosk")], "environment": {}}, folder)
                check_eq("a broken table with a native word and an unknown one stays `surfaces.unknown` (F-4)", list(doc.get("surfaces", {})), ["unknown"])
            import runtime_probe as RP
            check_eq("a broken table (F-9): a row that names a `surface` is a DEVICE stand for the probe (it stops, no container road); "
                     "a row with none reads no table and is not", (RP.is_device_stand(native, "e"), RP.is_device_stand(
                         {"environments": [stand("local", base_url="http://localhost:8080")]}, "local")), (True, False))
            before = len(calls)
            web = {"profiles": [profile("e2e-ui", "web")], "environments": [stand("local", base_url="http://localhost:8080")]}
            check_eq("a broken table with web: readiness has no `surfaces` and the table is not read",
                     ("surfaces" in R.compute({**web, "environment": {}}, folder), len(calls) - before), (False, 0))
            import gate_preflight
            keyed = gate_preflight.s5_profiles(web, folder, rows=[("QA-1_TC_001", {"level": "e2e-ui"})])
            check_eq("a broken table with web: s5_profiles keys the case to its profile and reads nothing",
                     (list(keyed), len(calls) - before), (["e2e-ui"], 0))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def web_lock_without_the_table():
    """The negative control: the table points at a broken file; the whole pin still holds and `surfaces.rows` was read 0 times."""
    folder, path = broken_table()
    try:
        with counted(path) as calls:
            now = capture_pin()
        pinned = {p.name: p.read_text(encoding="utf-8") for p in PIN.glob("*")}
        check_eq("negative control: ui, http, _blocked, readiness and the data bytes are the pin's with a broken table",
                 sorted(k for k in now if now[k] != pinned.get(k)), [])
        check_eq("negative control: `surfaces.rows` was read 0 times", len(calls), 0)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def stands():
    cfg = {"profiles": [profile("m", "native"), profile("e2e-ui", "web")],
           "environments": [stand("api-stand", base_url="http://x"), stand("emu", "android")]}
    check_eq("stand_for: the only device stand", SF.stand_for(cfg)["name"], "emu")
    two = {"environments": [stand("emu", "android"), stand("sim", "ios")]}
    for label, call in (("two without --surface", lambda: SF.stand_for(two)), ("none", lambda: SF.stand_for({"environments": [stand("a")]})),
                        ("an unknown id asked", lambda: SF.stand_for(two, "desktop"))):
        try:
            call()
            check(f"stand_for {label}: refused", False)
        except ValueError as exc:
            check(f"stand_for {label}: refused, with a door", "--surface" in str(exc) or "onboarding" in str(exc), str(exc))
    check_eq("stand_for: asked picks the one", SF.stand_for(two, "ios")["name"], "sim")
    with counted() as calls:
        check_eq("stand_of_profile: a project with no `surface` answers `selected`, table not read",
                 (SF.stand_of_profile({"environments": [stand("a")]}, "e2e-ui", "a"), len(calls)), ("a", 0))
    check_eq("stand_of_profile: the native profile gets the device stand", SF.stand_of_profile(cfg, "m", "api-stand"), "emu")
    check_eq("stand_of_profile: the web profile keeps the selected stand", SF.stand_of_profile(cfg, "e2e-ui", "api-stand"), "api-stand")
    check_eq("stand_of_profile: selected names the device stand, so the only other stand", SF.stand_of_profile(cfg, "e2e-ui", "emu"), "api-stand")
    many = {"profiles": [profile("android", "native")], "environments": [stand("e1", "android"), stand("e2", "android")]}
    check_eq("stand_of_profile: several fit and none is named by the profile id: nothing", SF.stand_of_profile(many, "android", ""), "")
    many["environments"][1]["surface"] = "android"
    many["environments"].append(stand("sim", "ios"))
    check_eq("stand_of_profile: a profile whose id equals the surface picks it", SF.stand_of_profile(
        {"profiles": [profile("ios", "native")], "environments": [stand("e1", "android"), stand("sim", "ios")]}, "ios", ""), "sim")


def profile_rows():
    """EP1-41f: `row_for_profile` (unknown -> None; table-free words -> None, table not read; first row in table order; a broken
    table is the module's ValueError), `profile_words` and `drives_device`, the one expression behind stand_of_profile."""
    cfg = {"profiles": [profile("e2e-ui", "web"), profile("api", "api", "web"), profile("m", "native"), profile("d", "desktop"),
                        profile("bare"), profile("both", "web", "desktop")],
           "environments": [stand("emu", "android")]}
    plain = {"profiles": cfg["profiles"], "environments": [stand("a")]}
    check_eq("profile_words: a declared profile's words, an unknown profile None, a profile with none an empty set",
             (SF.profile_words(cfg, "m"), SF.profile_words(cfg, "nope"), SF.profile_words(cfg, "bare"), SF.profile_words({}, "m")),
             ({"native"}, None, set(), None))
    check_eq("drives_device: a driver row holding a word", (SF.drives_device(SF.rows()["surfaces"], {"native"}),
                                                              SF.drives_device(SF.rows()["surfaces"], {"web", "desktop"})), (True, False))
    with counted() as calls:
        check_eq("row_for_profile: unknown profile -> None", SF.row_for_profile(cfg, "nope"), None)
        check_eq("row_for_profile: no capabilities -> None", SF.row_for_profile(cfg, "bare"), None)
        check_eq("row_for_profile: a web project (no `surface`), a table-free profile -> None and the table is not read",
                 (SF.row_for_profile(plain, "e2e-ui"), SF.row_for_profile(plain, "api"), len(calls)), (None, None, 0))
    row = SF.row_for_profile(cfg, "m")
    check_eq("row_for_profile: native -> the FIRST row in table order (android before ios), whose hands are the driver",
             (row, row["hands"]), (SF.rows()["surfaces"]["android"], "driver"))
    check_eq("row_for_profile: desktop -> hands none", SF.row_for_profile(cfg, "d")["hands"], "none")
    check_eq("row_for_profile: a desktop profile in a project with no `surface` still reads the table",
             SF.row_for_profile(plain, "d")["hands"], "none")
    mixed = {"profiles": cfg["profiles"] + [profile("nd", "native", "desktop"), profile("cn", "cli", "native"), profile("nn", "native", "native")],
             "environments": cfg["environments"]}
    check_eq("row_for_profile (F-12): words whose rows differ in `hands` -> None, never the first in table order",
             (SF.row_for_profile(cfg, "both"), SF.row_for_profile(mixed, "nd"), SF.row_for_profile(mixed, "cn")), (None, None, None))
    check_eq("row_for_profile (F-12): android and ios share `hands: driver`, so a native profile is still answered",
             (SF.row_for_profile(mixed, "nn")["hands"], SF.row_for_profile(mixed, "m")["hands"]), ("driver", "driver"))
    folder, path = broken_table()
    try:
        with counted(path) as calls:
            try:
                SF.row_for_profile(cfg, "m")
                check("row_for_profile: a broken table is refused", False)
            except ValueError as exc:
                check_in("row_for_profile: a broken table is the module's ValueError, factory-owned", "factory defect", str(exc))
            before = len(calls)
            check_eq("row_for_profile: a web profile with a broken table is None, no read, no error",
                     (SF.row_for_profile(plain, "e2e-ui"), len(calls) - before), (None, 0))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def manual_agent_pass():
    """EP1-41f (N-17): `_manual_agent_pass` leaves the obligations of a `hands: none` row as planned, with the table's words; every
    doubt (no profile, no config, an unknown profile, a broken table) is the old road; a web project never reads the table."""
    import tempfile
    import planning_contract as PC

    def ob(oid):
        return {"obligation_id": oid, "decision": "new", "execution_scope": "current_task", "oracle_status": "resolved",
                "requirement_refs": [{"ref": "R-1"}]}

    def run(cfg, profile_id, table=None):
        folder = Path(tempfile.mkdtemp())
        root = folder / "qa-factory" / "artifacts" / "T-1"
        root.mkdir(parents=True)
        if cfg is not None:
            (folder / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        row = {"id": "R1", "disposition": "manual-agent", "level": "e2e-ui", "coverage_obligations": [ob("OB-1"), ob("OB-2")]}
        if profile_id:
            row["execution_profile_id"] = profile_id
        lines = []
        try:
            with counted(table) as calls, mock.patch.object(PC, "_manual_cases_by_row", lambda r: ({}, "")):
                changed = PC._manual_agent_pass(root, [row], "W", lambda rid: rid, lines)
            return changed, lines, len(calls), row
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    device = {"profiles": [profile("e2e-ui", "web"), profile("d", "desktop")], "environments": [stand("a"), stand("emu", "android")]}
    changed, lines, reads, row = run(device, "d")
    words = SF.rows()["surfaces"]["desktop"]["words"]
    check_eq("pass: a desktop row stays as planned, once per obligation, with the table's words, and nothing changes",
             (changed, lines, [o["decision"] for o in row["coverage_obligations"]]),
             (False, [f"W: R1: OB-1 stays as planned - {words}", f"W: R1: OB-2 stays as planned - {words}"], ["new", "new"]))
    for label, cfg, pid in (("no execution_profile_id", device, ""), ("an unknown profile", device, "ghost"), ("no config.json", None, "d"),
                            ("a web profile on a device project", device, "e2e-ui")):
        changed, lines, reads, row = run(cfg, pid)
        check(f"pass: {label} takes the old road (no table words, no crash)", not any(words in x for x in lines), str(lines))
    web = {"profiles": [profile("e2e-ui", "web")], "environments": [stand("a")]}
    changed, lines, reads, row = run(web, "e2e-ui")
    check_eq("pass: a web project reads the table 0 times and takes the old road", (reads, any(words in x for x in lines)), (0, False))
    folder, path = broken_table()
    try:
        changed, lines, reads, row = run(device, "d", path)
        check("pass: a broken table is a line, not a crash, and the row is handled as before",
              any("table of test surfaces could not be read" in x for x in lines) and not any(words in x for x in lines), str(lines))
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def profiles_driven_by():
    """RN1-3 K-RN3-S1..S4: the profiles whose capabilities a table row of the given hands declares."""
    ui, api = {"profile_id": "ui", "capabilities": ["web"]}, {"profile_id": "api", "capabilities": ["api"]}
    check_eq("K-RN3-S1: a web profile is driven by a browser, an api profile is not",
             SF.profiles_driven_by({"profiles": [ui, api]}, "browser"), ["ui"])
    check_eq("K-RN3-S1: ... and the api profile by http", SF.profiles_driven_by({"profiles": [ui, api]}, "http"), ["api"])
    check_eq("K-RN3-S2: no profiles -> []", (SF.profiles_driven_by({}, "browser"), SF.profiles_driven_by({"profiles": "x"}, "browser"),
                                             SF.profiles_driven_by(None, "browser")), ([], [], []))
    check_eq("K-RN3-S3: capabilities that are a string, not a list -> that profile is skipped",
             SF.profiles_driven_by({"profiles": [{"profile_id": "ui", "capabilities": "web"}, {"profile_id": "x"}, "junk"]}, "browser"), [])
    folder, path = broken_table()
    try:
        path.write_text("{}", encoding="utf-8")
        held = SF.TABLE_PATH
        SF.TABLE_PATH = path
        try:
            try:
                SF.profiles_driven_by({"profiles": [ui]}, "browser")
                raised = False
            except ValueError:
                raised = True
        finally:
            SF.TABLE_PATH = held
        check("K-RN3-S4: a broken table is the module's ValueError, never an empty answer", raised)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main():
    if "--write-pin" in sys.argv:
        PIN.mkdir(parents=True, exist_ok=True)
        for name, text in capture_pin().items():
            (PIN / name).write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {len(list(PIN.glob('*')))} files to {PIN}")
        return
    web_pin()
    table_data()
    declared()
    broken()
    stands()
    profile_rows()
    manual_agent_pass()
    web_lock_without_the_table()
    profiles_driven_by()
    finish("test_surfaces")


if __name__ == "__main__":
    main()
