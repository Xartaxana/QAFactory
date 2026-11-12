"""HF8-9 - an account of the stand, heard at a gate, goes into the project's config (r0107 S1b, hotfix-12586/8).

On TP1-12586 the gate asked for an account the person had already named, and the answer lived only in the story. The fact is
written by `project_decisions.py stand-account` through the writers the module already has (`upsert` + `resolve`), after every
check: a refusal has a door, writes nothing and leaves no open registry row.

K-9.2 `_set_pointer` walks a list by a decimal index inside its length, and nowhere else
K-9.3 two stands, the record goes to the second one; the first is untouched; the registry row is closed with the words whole
K-9.4 every refusal: exit 2, config.json byte for byte, no open row, the door named; the env-file scenarios (none named / named)
K-9.5 a role with another entry needs --replace; the same record again is exit 0 and writes nothing
K-9.6 a role with a space and a `/`: the pointer is escaped, `account_keys` and `resolve_actor` read it back

HF8-10 - the address of the stand's UI, `project_decisions.py stand-frontend`:
K-10.3 one stand: `--key` -> the block, read back by `frontend_of`; two stands: `--stand` + `--url` -> only that entry; same record unchanged
K-10.4 every refusal (key not in the file, not http, a login in the address, a bad api_path, another value without --replace, the form that
       does not fit the number of stands, an entry that already names its UI): exit 2, config.json byte for byte, no open row, no value
K-10.5 the interview text (`p2`) names `frontend_candidates` and `api_path`; a negative control for the helper

Runnable on its own: `python -B scripts/tests/test_project_decisions_stand_facts.py`.
"""
import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project_decisions as PD  # noqa: E402

WORDS = "The second user is a plain user, not an admin.\nHis login is QA_SECOND_USER_EMAIL and the password QA_SECOND_USER_PASSWORD."
USER, SECRET = "QA_SECOND_USER_EMAIL", "QA_SECOND_USER_PASSWORD"
ENV_LINES = "AUTH_USERNAME=sentinel-a\nAUTH_PASSWORD=sentinel-b\nQA_SECOND_USER_EMAIL=sentinel-c\nQA_SECOND_USER_PASSWORD=sentinel-d\n"


def base_config(env_file: str | None = "tests/.env", stands: int = 2) -> dict:
    environment = {"user_key": "AUTH_USERNAME", "secret_keys": ["AUTH_PASSWORD"]}
    if env_file:
        environment["env_file"] = env_file
    return {"environment": environment,
            "environments": [{"name": f"stand-{n}", "base_url": f"http://localhost:808{n}", "credentials_by_role":
                              {"default user": "AUTH_USERNAME / AUTH_PASSWORD"}, "safe_to_break": True} for n in range(1, stands + 1)],
            "default_environment": "stand-1"}


class Project:
    def __init__(self, config: dict | None = None, env: str | None = ENV_LINES):
        self.root = temp_dir("qa-stand-facts-").resolve()
        (self.root / "qa-factory").mkdir()
        (self.root / "tests").mkdir()
        self.config = self.root / "qa-factory" / "config.json"
        self.config.write_text(json.dumps(base_config() if config is None else config, indent=2) + "\n", encoding="utf-8")
        if env is not None:
            (self.root / "tests" / ".env").write_text(env, encoding="utf-8")
        self.words = self.root / "words.txt"
        self.words.write_text(WORDS, encoding="utf-8")

    def data(self) -> dict:
        return json.loads(self.config.read_text(encoding="utf-8"))

    def bytes(self) -> bytes:
        return self.config.read_bytes()

    def rows(self) -> list:
        backlog = self.root / "qa-factory" / "factory-backlog.md"
        return PD.parse_rows(backlog.read_text(encoding="utf-8")) if backlog.exists() else []

    def run(self, *flags, role: str = "Second user", user: str = USER, secret: str = SECRET, stand: str | None = "stand-2", env=None):
        args = ["--root", self.root, "stand-account", "--role", role, "--user-key", user, "--secret-key", secret,
                "--words-file", self.words]
        if stand is not None:
            args += ["--stand", stand]
        return run_script("project_decisions.py", *args, *flags, env=env)

    def done(self):
        cleanup(self.root)


def refused(label: str, project: Project, run, door: str) -> None:
    before = project.bytes()
    result = run()
    check_eq(f"K-9.4 {label}: exit 2", result.returncode, 2)
    check_eq(f"K-9.4 {label}: config.json byte for byte", project.bytes(), before)
    check_eq(f"K-9.4 {label}: no row in the registry (no open decision is left behind)", project.rows(), [])
    check_in(f"K-9.4 {label}: the door is named", door, result.stderr)
    check_eq(f"K-9.4 {label}: one line, no traceback", (len(result.stderr.strip().splitlines()), "Traceback" in result.stderr), (1, False))
    check_not_in(f"K-9.4 {label}: no value in the text", "sentinel-", result.stderr + result.stdout)


def k92_set_pointer_walks_a_list() -> None:
    doc = {"environments": [{"name": "a"}], "x": "text"}
    PD._set_pointer(doc, "/environments/0/credentials_by_role/Second user", "U_A / S_A")
    check_eq("K-9.2 an index inside the list writes there, creating the objects after it", doc["environments"][0]["credentials_by_role"],
             {"Second user": "U_A / S_A"})
    PD._set_pointer(doc, "/environments/0", {"name": "b"})
    check_eq("K-9.2 an index as the LAST step replaces the item", doc["environments"], [{"name": "b"}])
    for label, pointer in (("one beyond the length (1 of 1)", "/environments/1/x"), ("minus one", "/environments/-1/x"),
                           ("a name", "/environments/a/x"), ("a leading zero", "/environments/00/x"), ("a plus sign", "/environments/+0/x"),
                           ("the length as the last step", "/environments/1"), ("empty", "/environments//x"),
                           ("a huge number", "/environments/99999999999999999999/x"), ("through a text", "/x/y"),
                           ("a pointer with no slash", "environments/0/x")):
        before = copy.deepcopy(doc)
        try:
            PD._set_pointer(doc, pointer, "v")
            raised = False
        except ValueError:
            raised = True
        check_eq(f"K-9.2 {label}: ValueError, and no entry is created", (raised, doc), (True, before))
    old = {"a": {"b": 1}}
    PD._set_pointer(old, "/a/c/d", 2)
    check_eq("K-9.2 objects are created on the way as before", old, {"a": {"b": 1, "c": {"d": 2}}})


def k93_the_record_goes_to_the_named_stand() -> None:
    project = Project()
    try:
        before = project.data()
        result = project.run()
        check_eq("K-9.3 exit 0", result.returncode, 0)
        out = json.loads(result.stdout)
        check_eq("K-9.3 the output names the stand, the role, the keys and the decision",
                 (out["stand"], out["role"], out["keys"], out["decision"], out["unchanged"], out["names_checked"]),
                 ("stand-2", "Second user", [USER, SECRET], "DD-1", False, True))
        after = project.data()
        want = copy.deepcopy(before)
        want["environments"][1]["credentials_by_role"]["Second user"] = f"{USER} / {SECRET}"
        check_eq("K-9.3 only the named stand changed, by exactly that entry", after, want)
        check_eq("K-9.3 the first stand is byte for byte", json.dumps(after["environments"][0]), json.dumps(before["environments"][0]))
        rows = project.rows()
        check_eq("K-9.3 one row, closed", [(r["id"], r["status"]) for r in rows], [("DD-1", "closed")])
        check_eq("K-9.3 the row holds the person's words whole (a line break is one space in a cell)",
                 rows[0]["decision with witness"], " ".join(WORDS.split()))
        check_eq("K-9.3 and the pointer of the stand it wrote", rows[0]["field_refs"], "/environments/1/credentials_by_role/Second user")
        receipt = json.loads((project.root / "qa-factory" / "state" / "decision-transactions" / "DD-1.json").read_text(encoding="utf-8"))
        check_eq("K-9.3 the receipt is complete and carries the time and the config before the write (HF8-9: the revert keeps it)",
                 (receipt["status"], receipt["before"], bool(receipt["recorded_at"])), ("complete", before, True))
        check_not_in("K-9.3 no value in the registry", "sentinel-", (project.root / "qa-factory" / "factory-backlog.md").read_text(encoding="utf-8"))
        # one stand and no --stand: the only row
        solo = Project(base_config(stands=1))
        try:
            check_eq("K-9.3 one stand needs no --stand", solo.run(stand=None).returncode, 0)
            check_eq("K-9.3 ... and the role is on it", solo.data()["environments"][0]["credentials_by_role"]["Second user"], f"{USER} / {SECRET}")
        finally:
            solo.done()
    finally:
        project.done()


def k94_every_refusal_has_its_door() -> None:
    project = Project()
    try:
        refused("several stands and none named", project, lambda: project.run(stand=None), "--stand <name>")
        refused("an unknown stand", project, lambda: project.run(stand="nowhere"), "--stand <one of them>")
        for label, role in (("a comma", "a,b"), ("a bar", "a|b"), ("a backslash", "a\\b"), ("a line break", "a\nb")):
            refused(f"the role holds {label}", project, lambda role=role: project.run(role=role), "nothing was written")
        for label, role in (("default", "default"), ("env:", "env:X/Y"), ("created:", "created:bob")):
            refused(f"the reserved role {label}", project, lambda role=role: project.run(role=role), "reserved form")
        refused("an empty role", project, lambda: project.run(role="  "), "--role is empty")
        refused("a name that is not a name (an equals sign)", project, lambda: project.run(user="A_B=1"), "variable NAME")
        refused("a name that starts with a digit", project, lambda: project.run(secret="1_X"), "variable NAME")
        for label, user, secret in (("no underscore", "EMAIL", "PASSWORD"), ("lower case", "qa_user", "qa_password")):
            refused(f"a pair `account_keys` cannot read ({label})", project, lambda u=user, s=secret: project.run(user=u, secret=s),
                    "--as env:USER_KEY/SECRET_KEY")
        refused("a name the named env file does not hold", project, lambda: project.run(user="QA_NOWHERE_USER"), "add the name(s) to that file")
        check_eq("K-9.4 ... and it names the variable", "QA_NOWHERE_USER" in project.run(user="QA_NOWHERE_USER").stderr, True)
        refused("no such file as the words file", project, lambda: run_script(
            "project_decisions.py", "--root", project.root, "stand-account", "--stand", "stand-2", "--role", "r", "--user-key", USER,
            "--secret-key", SECRET, "--words-file", project.root / "missing.txt"), "no such file")
    finally:
        project.done()
    # no rows of environments[]: the door is "record the stand"
    for label, config in (("an empty list", {"environments": []}), ("no key", {"environment": {}}), ("a list of texts", {"environments": ["x"]})):
        project = Project(config)
        try:
            refused(f"no environments[] row ({label})", project, lambda project=project: project.run(stand=None), "Record it first")
        finally:
            project.done()
    # no config file at all
    project = Project()
    try:
        project.config.unlink()
        result = project.run()
        check_eq("K-9.4 no config.json: exit 2 with the door", (result.returncode, "Run /qa-factory:qa-onboarding first" in result.stderr), (2, True))
        check_eq("K-9.4 ... and none was created", project.config.exists(), False)
    finally:
        project.done()
    # credentials_by_role that is not an object
    config = base_config()
    config["environments"][1]["credentials_by_role"] = "text"
    project = Project(config)
    try:
        refused("a credentials_by_role that is not an object", project, lambda: project.run(), "repair it by hand")
    finally:
        project.done()
    # scenario 1: the config names no env file - the record goes in and says the names were not checked
    project = Project(base_config(env_file=None))
    try:
        result = project.run()
        check_eq("K-9.4 scenario 1: no env file named: the record is written", result.returncode, 0)
        out = json.loads(result.stdout)
        check_eq("K-9.4 scenario 1: and the output says the names were not checked", (out["names_checked"], out["note"]),
                 (False, "names not checked: the config names no env file"))
    finally:
        project.done()
    # scenario 2: the names only in the process environment, the named file lacking them
    project = Project(env="AUTH_USERNAME=1\n")
    try:
        refused("the named file lacks the names and the process has none", project, lambda: project.run(), "add the name(s) to that file")
        env = dict(os.environ, **{USER: "x", SECRET: "y"})
        result = project.run(env=env)
        check_eq("K-9.4 scenario 2: the names in the process environment are enough", result.returncode, 0)
        check_eq("K-9.4 scenario 2: and the record is there", project.data()["environments"][1]["credentials_by_role"]["Second user"],
                 f"{USER} / {SECRET}")
    finally:
        project.done()
    # a file that is not named in the config at all (`env_files` only) is still a named file
    config = base_config(env_file=None)
    config["environment"]["env_files"] = ["tests/.env"]
    project = Project(config, env="AUTH_USERNAME=1\n")
    try:
        refused("env_files names a file that lacks the names", project, lambda: project.run(), "add the name(s) to that file")
    finally:
        project.done()


def k95_replace_and_repeat() -> None:
    project = Project()
    try:
        check_eq("K-9.5 first record", project.run().returncode, 0)
        refused_before = project.bytes()
        again = project.run(user="AUTH_USERNAME", secret="AUTH_PASSWORD")
        check_eq("K-9.5 another entry for the role without --replace: exit 2 and the door", (again.returncode, "--replace" in again.stderr), (2, True))
        check_eq("K-9.5 ... nothing changed, no second row", (project.bytes(), len(project.rows())), (refused_before, 1))
        replaced = project.run("--replace", user="AUTH_USERNAME", secret="AUTH_PASSWORD")
        check_eq("K-9.5 with --replace: exit 0", replaced.returncode, 0)
        check_eq("K-9.5 ... the entry is replaced", project.data()["environments"][1]["credentials_by_role"]["Second user"], "AUTH_USERNAME / AUTH_PASSWORD")
        check_eq("K-9.5 ... in a second transaction", [(r["id"], r["status"]) for r in project.rows()], [("DD-1", "closed"), ("DD-2", "closed")])
        # OH3-40: the readers give the NEW pair back (the sign-in reads what the gate reads), and the refusal left the old one intact
        import gate_preflight as GP
        import manual_capture as MC
        cfg = project.data()
        roles = cfg["environments"][1]["credentials_by_role"]
        check_eq("OH3-40 after --replace `account_keys` gives the new pair", GP.account_keys(roles["Second user"]), ["AUTH_USERNAME", "AUTH_PASSWORD"])
        check_eq("OH3-40 after --replace `resolve_actor` gives the new pair",
                 MC.resolve_actor(cfg, cfg["environments"][1], "Second user", project.root)[:2], ("AUTH_USERNAME", "AUTH_PASSWORD"))
        check_eq("OH3-40 the refusal without --replace left the first pair to the readers",
                 GP.account_keys(json.loads(refused_before)["environments"][1]["credentials_by_role"]["Second user"]), [USER, SECRET])
        stored = project.bytes()
        same = project.run(user="AUTH_USERNAME", secret="AUTH_PASSWORD")
        out = json.loads(same.stdout)
        check_eq("K-9.5 the same record again: exit 0, unchanged", (same.returncode, out["unchanged"]), (0, True))
        check_eq("K-9.5 ... nothing written, no new row", (project.bytes(), len(project.rows())), (stored, 2))
        same_replace = project.run("--replace", user="AUTH_USERNAME", secret="AUTH_PASSWORD")
        check_eq("K-9.5 ... and with --replace too", (same_replace.returncode, json.loads(same_replace.stdout)["unchanged"], len(project.rows())), (0, True, 2))
    finally:
        project.done()


def k96_a_role_with_a_space_and_a_slash() -> None:
    import gate_preflight as GP
    import manual_capture as MC
    project = Project()
    try:
        role = "Read only/admin ~x"
        result = project.run(role=role)
        check_eq("K-9.6 a role with a space, a slash and a tilde is recorded", result.returncode, 0)
        rows = project.rows()
        check_eq("K-9.6 the pointer is escaped (`/` is ~1, `~` is ~0)", rows[0]["field_refs"], "/environments/1/credentials_by_role/Read only~1admin ~0x")
        cfg = project.data()
        roles = cfg["environments"][1]["credentials_by_role"]
        check_eq("K-9.6 the key in the config is the role as the person said it", role in roles, True)
        check_eq("K-9.6 `account_keys` reads the pair back", GP.account_keys(roles[role]), [USER, SECRET])
        check_eq("K-9.6 `resolve_actor` gets the pair for the role", MC.resolve_actor(cfg, cfg["environments"][1], role, project.root)[:2], (USER, SECRET))
    finally:
        project.done()


FRONT_ENV = ENV_LINES + "FRONTEND_URL=http://sentinel-front.example.test:5173\nJIRA_URL=https://sentinel-jira.example.test\nNOT_HTTP=ftp://sentinel-x\n"


def front(project: Project, *args, env=None):
    """`stand-frontend` with the words file of the project; `args` are the flags."""
    return run_script("project_decisions.py", "--root", project.root, "stand-frontend", "--words-file", project.words, *args, env=env)


def k103_the_address_is_read_back_by_the_one_reader() -> None:
    import env_probe as EP
    project = Project(base_config(stands=1), env=FRONT_ENV)
    try:
        before = project.data()
        result = front(project, "--key", "FRONTEND_URL", "--api-path", "/api/v1/config")
        check_eq("K-10.3 one stand: exit 0", result.returncode, 0)
        out = json.loads(result.stdout)
        check_eq("K-10.3 the output names the form, the stand, the key and the decision, never the address",
                 (out["form"], out["stand"], out["key"], out["decision"], out["unchanged"], "sentinel-" in result.stdout),
                 ("block", "stand-1", "FRONTEND_URL", "DD-1", False, False))
        cfg = project.data()
        check_eq("K-10.3 the block holds the key NAME and the path, and nothing else changed", cfg["environment"]["frontend"],
                 {"url_key": "FRONTEND_URL", "api_path": "/api/v1/config"})
        want = copy.deepcopy(before)
        want["environment"]["frontend"] = cfg["environment"]["frontend"]
        check_eq("K-10.3 ... exactly that entry", cfg, want)
        got = EP.frontend_of(cfg, "stand-1", root=project.root)
        check_eq("K-10.3 `frontend_of` reads it back: the address, the source, the path (the ONE reader, AR-13)",
                 (got["url"], got["source"], got["api_path"]), ("http://sentinel-front.example.test:5173", "environment.frontend.url_key", "/api/v1/config"))
        rows = project.rows()
        check_eq("K-10.3 one closed row with both pointers and the words whole", (rows[0]["status"], rows[0]["field_refs"],
                 rows[0]["decision with witness"]), ("closed", "/environment/frontend/api_path,/environment/frontend/url_key", " ".join(WORDS.split())))
        check_not_in("K-10.3 no value in the registry", "sentinel-", (project.root / "qa-factory" / "factory-backlog.md").read_text(encoding="utf-8"))
        # the same record again: unchanged; the key alone (no path) keeps the path; the stand named is checked
        stored = project.bytes()
        again = front(project, "--key", "FRONTEND_URL", "--stand", "stand-1")
        check_eq("K-10.3 the same record again (the path left out): exit 0, unchanged, nothing written, no new row",
                 (again.returncode, json.loads(again.stdout)["unchanged"], project.bytes(), len(project.rows())), (0, True, stored, 1))
        other = front(project, "--key", "JIRA_URL")
        check_eq("K-10.4 another key without --replace: exit 2 and the door; nothing changed",
                 (other.returncode, "--replace" in other.stderr, project.bytes()), (2, True, stored))
        replaced = front(project, "--key", "JIRA_URL", "--replace")
        check_eq("K-10.4 with --replace: the key is replaced and the path stays", project.data()["environment"]["frontend"],
                 {"url_key": "JIRA_URL", "api_path": "/api/v1/config"})
        check_eq("K-10.4 ... in a second transaction", (replaced.returncode, [r["id"] for r in project.rows()]), (0, ["DD-1", "DD-2"]))
    finally:
        project.done()
    # two stands: the block is not read there, so the form is the entry's address of the named stand
    project = Project(base_config(stands=2), env=FRONT_ENV)
    try:
        before = project.data()
        url = "http://sentinel-preview.example.test:5173"
        refused("several stands, --key", project, lambda: front(project, "--key", "FRONTEND_URL"), "environments[<name>].frontend.url")
        refused("several stands, --url and no --stand", project, lambda: front(project, "--url", url), "--stand <name>")
        refused("several stands, an unknown stand", project, lambda: front(project, "--url", url, "--stand", "nowhere"), "--stand <one of them>")
        result = front(project, "--url", url, "--stand", "stand-2", "--api-path", "/api/v1/config")
        check_eq("K-10.3 two stands, --stand and --url: exit 0", result.returncode, 0)
        out = json.loads(result.stdout)
        check_eq("K-10.3 ... the entry form, with the identity note, never the address",
                 (out["form"], out["stand"], "identity" in out["note"], "sentinel-" in result.stdout), ("entry", "stand-2", True, False))
        cfg = project.data()
        want = copy.deepcopy(before)
        want["environments"][1]["frontend"] = {"url": url, "api_path": "/api/v1/config"}
        check_eq("K-10.3 only the named stand's entry changed, by exactly that object", cfg, want)
        check_eq("K-10.3 the first stand is byte for byte", json.dumps(cfg["environments"][0]), json.dumps(before["environments"][0]))
        got = EP.frontend_of(cfg, "stand-2", root=project.root)
        check_eq("K-10.3 `frontend_of` reads it back for the named stand, and not for the other",
                 (got["url"], got["source"], EP.frontend_of(cfg, "stand-1", root=project.root)["url"]), (url, "environments[1].frontend.url", ""))
        check_eq("K-10.3 the pointer is the stand's own index", {r["field_refs"] for r in project.rows()},
                 {"/environments/1/frontend/api_path,/environments/1/frontend/url"})
        stored = project.bytes()
        same = front(project, "--url", url, "--stand", "stand-2")
        check_eq("K-10.3 the same address again: exit 0, unchanged, no new row",
                 (same.returncode, json.loads(same.stdout)["unchanged"], project.bytes(), len(project.rows())), (0, True, stored, 1))
        clash = front(project, "--url", "http://sentinel-other.example.test", "--stand", "stand-2")
        check_eq("K-10.4 another address without --replace: exit 2, the door, nothing changed, no value in the text",
                 (clash.returncode, "--replace" in clash.stderr, project.bytes(), "sentinel-" in clash.stderr), (2, True, stored, False))
    finally:
        project.done()


def k104_every_frontend_refusal_has_its_door() -> None:
    project = Project(base_config(stands=1), env=FRONT_ENV)
    try:
        key = lambda *a, **k: front(project, "--key", "FRONTEND_URL", *a, **k)      # noqa: E731
        refused("neither --key nor --url", project, lambda: front(project), "exactly one of --key")
        refused("both --key and --url", project, lambda: front(project, "--key", "FRONTEND_URL", "--url", "http://h.example.test"), "exactly one of --key")
        refused("--url at one stand (the form is a key NAME)", project, lambda: front(project, "--url", "http://h.example.test"),
                "repeat with --key <NAME>")
        refused("a key the env file does not hold", project, lambda: front(project, "--key", "QA_NOWHERE_URL"), "add the variable to that file")
        refused("a key whose value is not http", project, lambda: front(project, "--key", "NOT_HTTP"), "does not hold an http(s) address")
        for label, name in (("an equals sign", "A_B=1"), ("a digit first", "1_X"), ("a space", "A B"), ("empty after a flag", "")):
            refused(f"a key that is not a name ({label})", project, lambda name=name: front(project, "--key", name), "")
        for label, path in (("two slashes", "//x"), ("no slash", "api/x"), ("a backslash", "/\\x")):
            refused(f"an api_path of {label}", project, lambda path=path: key("--api-path", path), "api_path")
        refused("a --stand that is not the project's", project, lambda: key("--stand", "nowhere"), "--stand <one of them>")
        refused("no such file as the words file", project, lambda: run_script(
            "project_decisions.py", "--root", project.root, "stand-frontend", "--key", "FRONTEND_URL", "--words-file", project.root / "missing.txt"),
                "no such file")
    finally:
        project.done()
    # a stand entry that already names its UI: the block would never be read (the reader lets the entry win)
    config = base_config(stands=1)
    config["environments"][0]["frontend_url"] = "http://sentinel-own.example.test"
    project = Project(config, env=FRONT_ENV)
    try:
        refused("the only stand's own entry names a UI address", project, lambda: key_of(project), "change the address in that entry")
    finally:
        project.done()
    # the config names an env file that is not there; no config at all; an environment that is not an object
    config = base_config(stands=1, env_file="tests/gone.env")
    project = Project(config, env=FRONT_ENV)
    try:
        refused("the named env file is missing", project, lambda: key_of(project), "fix environment.env_file")
    finally:
        project.done()
    config = base_config(stands=1)
    config["environment"] = "text"
    project = Project(config, env=FRONT_ENV)
    try:
        refused("`environment` is not an object", project, lambda: key_of(project), "repair it by hand")
    finally:
        project.done()
    project = Project(env=FRONT_ENV)
    try:
        project.config.unlink()
        result = key_of(project)
        check_eq("K-10.4 no config.json: exit 2 with the door, none created", (result.returncode, "Run /qa-factory:qa-onboarding first" in result.stderr,
                                                                                project.config.exists()), (2, True, False))
    finally:
        project.done()
    # several stands: the address of the entry is checked as an address
    project = Project(base_config(stands=2), env=FRONT_ENV)
    try:
        for label, url, door in (("a login in the address", "http://user:sentinel-pw@h.example.test", "without a login"),
                                 ("an at sign in the host part", "http://sentinel-a@h.example.test", "without a login"),
                                 ("not http", "ftp://h.example.test", "http(s)"), ("no host", "http://", "with a host"),
                                 ("a space inside", "http://h .example.test", "with a host"), ("empty", "", "exactly one of --key"),
                                 ("not an address at all", "localhost:5173", "http(s)")):
            refused(f"--url: {label}", project, lambda url=url: front(project, "--url", url, "--stand", "stand-2"), door)
        refused("--url: an api_path of two slashes", project, lambda: front(project, "--url", "http://h.example.test", "--stand", "stand-2",
                                                                            "--api-path", "//x"), "api_path")
    finally:
        project.done()
    # the stand's `frontend` is not an object: repair by hand, nothing written
    config = base_config(stands=2)
    config["environments"][1]["frontend"] = "text"
    project = Project(config, env=FRONT_ENV)
    try:
        refused("the stand's `frontend` is not an object", project, lambda: front(project, "--url", "http://h.example.test", "--stand", "stand-2"),
                "repair it by hand")
    finally:
        project.done()
    # no environments[] at all: the block is the stand (zero rows is the block's form)
    project = Project({"environment": {"env_file": "tests/.env"}}, env=FRONT_ENV)
    try:
        ok = front(project, "--key", "FRONTEND_URL")
        check_eq("K-10.3 no environments[] row: the block is the stand, the key is recorded there",
                 (ok.returncode, project.data()["environment"]["frontend"]), (0, {"url_key": "FRONTEND_URL"}))
        refused_stand = front(project, "--key", "FRONTEND_URL", "--stand", "x")
        check_eq("K-10.4 ... and a named stand there is refused with the door", (refused_stand.returncode, "Record it first" in refused_stand.stderr), (2, True))
    finally:
        project.done()


def key_of(project: Project):
    return front(project, "--key", "FRONTEND_URL")


def k105_the_interview_text_names_the_candidates() -> None:
    p2 = (Path(__file__).resolve().parents[2] / "skills" / "qa-onboarding" / "phases" / "p2-interview.md").read_text(encoding="utf-8")

    def has(text: str, needle: str) -> bool:
        return needle in text
    for needle in ("frontend_candidates", "api_path"):
        check(f"K-10.5 p2 carries `{needle}`", has(p2, needle))
    check("K-10.5 negative control: the helper fails on a key that is absent", not has(p2, "frontend_candidates_nowhere_in_the_text"))


def k_r2_f2_the_frontend_key_is_looked_up_where_the_gate_looks() -> None:
    """Fix round 2, F2: `stand-frontend --key` reads the env files the gate reads (`env_files`, else `env_file`) and, with none
    named, records with `names not checked` (as `stand-account`), instead of refusing a key the gate would find."""
    # env_files only, no env_file: the key is in the listed file
    config = base_config(env_file=None, stands=1)
    config["environment"]["env_files"] = ["tests/.env"]
    project = Project(config, env=FRONT_ENV)
    try:
        out = key_of(project)
        check_eq("F2 `env_files` only: recorded, and the names were checked", (out.returncode, json.loads(out.stdout)["names_checked"]), (0, True))
    finally:
        project.done()
    # the 12586 shape: both keys; the gate reads `env_files`, so a key only in `env_file` is refused, and one in `env_files` is found
    config = base_config(env_file="tests/a.env", stands=1)
    config["environment"]["env_files"] = ["tests/b.env"]
    project = Project(config, env=FRONT_ENV)
    try:
        (project.root / "tests" / "a.env").write_text("FRONTEND_URL=http://sentinel-front.example.test\n", encoding="utf-8")
        (project.root / "tests" / "b.env").write_text("OTHER=sentinel-x\n", encoding="utf-8")
        refused("F2 the key is only in `env_file` while `env_files` is the list the gate reads", project, lambda: key_of(project), "tests/b.env")
        (project.root / "tests" / "b.env").write_text("FRONTEND_URL=http://sentinel-front.example.test\n", encoding="utf-8")
        ok = key_of(project)
        check_eq("F2 ... and found once the listed file holds it", ok.returncode, 0)
    finally:
        project.done()
    # no file named: records, says so, never reads a value
    project = Project(base_config(env_file=None, stands=1), env=FRONT_ENV)
    try:
        out = key_of(project)
        said = json.loads(out.stdout)
        check_eq("F2 no env file named: recorded with `names not checked`", (out.returncode, said["names_checked"], "names not checked" in said["note"],
                                                                         "sentinel-" in out.stdout), (0, False, True, False))
        check_eq("F2 ... the key is in the config", project.data()["environment"]["frontend"], {"url_key": "FRONTEND_URL"})
    finally:
        project.done()


def k_r2_f5_f6_f7_the_account_writer() -> None:
    import config_contract as CC
    # F5: the gate reads `default user` and `default_user` as one role; the writer must not make a twin of it
    project = Project()
    try:
        before = project.bytes()
        same = project.run(role="default_user", user="AUTH_USERNAME", secret="AUTH_PASSWORD", stand="stand-1")
        check_eq("F5 the same pair under another spelling of the role: exit 0, unchanged, the REAL key named",
                 (same.returncode, json.loads(same.stdout)["unchanged"], json.loads(same.stdout)["role"]), (0, True, "default user"))
        check_eq("F5 ... nothing written, no row", (project.bytes(), project.rows()), (before, []))
        other = project.run(role="Default-User", stand="stand-1")
        check_eq("F5 another pair under another spelling, no --replace: refused, the stand's own key is named",
                 (other.returncode, "default user" in other.stderr, "--replace" in other.stderr, project.bytes()), (2, True, True, before))
        done = project.run("--replace", role="Default-User", stand="stand-1")
        roles = project.data()["environments"][0]["credentials_by_role"]
        check_eq("F5 with --replace: the entry is replaced IN PLACE, no twin row", (done.returncode, roles), (0, {"default user": f"{USER} / {SECRET}"}))
    finally:
        project.done()
    config = base_config(stands=1)
    config["environments"][0]["credentials_by_role"] = {"Admin": "AUTH_USERNAME / AUTH_PASSWORD", "admin": f"{USER} / {SECRET}"}
    project = Project(config)
    try:
        before = project.bytes()
        two = project.run(role="ADMIN", stand=None)
        check_eq("F5 two keys of one normal form: refused, both named, nothing written",
                 (two.returncode, "Admin" in two.stderr and "admin" in two.stderr, project.bytes(), project.rows()), (2, True, before, []))
    finally:
        project.done()
    # F6: one name for both keys is not a pair
    project = Project()
    try:
        before = project.bytes()
        both = project.run(user=USER, secret=USER)
        check_eq("F6 --user-key equal to --secret-key: refused, both flags named, nothing written, no row",
                 (both.returncode, "--user-key" in both.stderr and "--secret-key" in both.stderr, project.bytes(), project.rows()), (2, True, before, []))
    finally:
        project.done()
    errors = CC.environments_account_errors([{"credentials_by_role": {"a": "QA_USER / QA_USER", "b": "QA_USER / QA_PASS"}}], ["QA_USER", "QA_PASS"])
    check_eq("F6 `--check-environment` reports a hand-written note that names one key twice (and only that one)",
             (len(errors), "QA_USER twice" in errors[0] if errors else False), (1, True))
    # F7: a BOM config passes the checks (`utf-8-sig`) and must pass `resolve` too, or an open row is left behind
    project = Project()
    try:
        project.config.write_bytes(b"\xef\xbb\xbf" + project.config.read_bytes())
        done = project.run()
        check_eq("F7 a config with a BOM: recorded, exit 0, the row closed (no open decision)", (done.returncode, [r["status"] for r in project.rows()]),
                 (0, ["closed"]))
        held = json.loads(project.config.read_text(encoding="utf-8-sig"))
        check_eq("F7 ... and the role is there", held["environments"][1]["credentials_by_role"]["Second user"], f"{USER} / {SECRET}")
    finally:
        project.done()


def main() -> None:
    for scenario in (k92_set_pointer_walks_a_list, k93_the_record_goes_to_the_named_stand, k94_every_refusal_has_its_door,
                     k95_replace_and_repeat, k96_a_role_with_a_space_and_a_slash, k103_the_address_is_read_back_by_the_one_reader,
                     k104_every_frontend_refusal_has_its_door, k105_the_interview_text_names_the_candidates,
                     k_r2_f2_the_frontend_key_is_looked_up_where_the_gate_looks, k_r2_f5_f6_f7_the_account_writer):
        scenario()
    finish("test_project_decisions_stand_facts")


if __name__ == "__main__":
    main()
