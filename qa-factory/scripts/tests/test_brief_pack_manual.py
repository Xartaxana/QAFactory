#!/usr/bin/env python3
"""t-1540 HF5-5: the brief of a MANUAL runner block - the three commands of the manual half and the section `## The stand`.

The 12586 run's brief (S6-qa-runner-2, 4593 B) named no `manual_capture.py`, no stand address and no account: the runner found
them by searching. What is proved, on the run's own pieces (fixtures/run-12586-s6-brief/ = the dispatch record and the page
objects of its map; ../run-12586-stand-config/ = the stand config and env file HF5-2 took; ../run-12586-actors/ = the
preconditions HF5-3 took) and on REAL requests (`manual_evidence.prepare_to_file` on the manual-evidence scaffold - the
producer of `actors`, not a hand-written file; only the case id is renamed to the run's TC-010 / TC-012 / TC-014):

  K1  the joint: the manual block's brief holds `http://localhost:5173`, `"default user"`, `TC-014: PC-1 env
      QA_SECOND_USER_EMAIL` and `manual_capture.py ui`, the section stands right before `## Commands`, the brief is
      <= 6144 bytes, and no value of the env file is in it
  K2  an automated block (or a record with no kind) has no section and is byte for byte the manual brief without it
  K3  the section is never cut: 6144 bytes is no cut (AT), one byte less cuts a FILE and not a line of the section (BEYOND),
      a ceiling nothing can meet leaves the brief over it with the section whole; the limits 5/6 paths and 10/11 case lines
  K4  the edges: no stand selected, no roles, no frontend, an address with credentials, actors [] / refused / unreadable,
      an unreadable map or no map, a long reason
  K5  the card names `manual_capture.py ui|http --as` and `manual_evidence.py build` (the scripts the charter names)

  K6  (t-1550) `Env keys`: key NAMES only, capped at STAND_ROLES_MAX with `(+K more)`, an unreadable env file said; the pipeline
      names no environment: one `environments[]` entry is the stand, two or more give `- Stand: not named in pipeline.json`
Fix round t-1550 mutations -> killing key (this file): the manual commands back in the shared TOOLING["qa-runner"] -> K2 (and the
qa-runner hash of test_brief_pack_roles.py); `Env keys` without the env file's names -> K1; a value printed in `Env keys` -> K1/K6;
the cap removed -> K6; a bare "lists no other" for an unnamed multi-entry config -> K6.
Mutation -> killing key (this file): the section in an automated brief -> K2; the section moved into `files` (cut by the loop) -> K3;
`frontend_of` replaced by a second reader of `frontend_url` -> K1 (the address with credentials passes) and K4;
`request_actors` replaced by a second reader of request.json -> K4 (unreadable / refused lines); the 5/10 limits shifted -> K3;
the card line dropped -> K5.
"""
import json
import re
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
import scaffold as S  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import judge  # noqa: E402
import manual_evidence as ME  # noqa: E402
import test_manual_capture as TMC  # noqa: E402

FIX = HERE / "fixtures" / "run-12586-s6-brief"
STAND = HERE / "fixtures" / "run-12586-stand-config"
ACTORS = HERE / "fixtures" / "run-12586-actors"
TICKET = "TP1-12586"
DISPATCH_ID = "S6-qa-runner-2"
RUN_CASES = ("TC-010", "TC-012", "TC-014")
PRE_014 = (ACTORS / "TC-014.preconditions.txt").read_text(encoding="utf-8").strip()
PRE_012 = (ACTORS / "TC-012.preconditions.txt").read_text(encoding="utf-8").strip()
DISPATCH = json.loads((FIX / "dispatch.json").read_text(encoding="utf-8"))
UTILS = [line for line in (FIX / "utils-paths.txt").read_text(encoding="utf-8").splitlines() if line]
MAP_PATH = f"qa-factory/artifacts/{TICKET}/work/briefs/repo-map-4852b66ca7.md"
SECRET = "SENTINEL-PASSWORD-2c71e9"


def real_requests() -> dict:
    """{run case id: the request.json text the real producer wrote} - ui -> TC-010, impl (TC-012's preconditions) -> TC-012,
    api (TC-014's preconditions) -> TC-014. The producer is `prepare_to_file`; its answer is read back from the file."""
    t = S.make_task(manual=("ui", "api", "impl"), claims=True)
    out = {}
    try:
        pre = {"api": PRE_014, "impl": PRE_012}
        for key, line in pre.items():
            for path in (t.task / "state" / "case-versions" / S.CASES[key]).glob("*.md"):
                text = path.read_text(encoding="utf-8")
                path.write_text(re.sub(r"(?m)^preconditions:.*$", lambda _m: line, text), encoding="utf-8")
        ids = {"ui": TMC.OBLIGATIONS[S.CASES["ui"]], "api": TMC.OBLIGATIONS[S.CASES["api"]],
               "impl": ["OB-15"]}
        with t.patched():
            for key, name in (("ui", "TC-010"), ("impl", "TC-012"), ("api", "TC-014")):
                case = S.CASES[key]
                try:
                    ME.prepare_to_file(t.task, case, ids[key])
                except ValueError:
                    pass            # a refusal is written to the file too: the brief reads that file as well
                out[name] = ME.request_path(t.task, case).read_text(encoding="utf-8")
    finally:
        S.cleanup(t)
    return out


def story(cfg_edit=None, requests=None, dispatch=None, env=None, env_lines=None):
    """(project root, task root): the run's stand config and env file, a pipeline on `local-docker`, the controller state with the
    run's dispatch, and `requests` ({case: request text}) filed where `request_actors` reads them."""
    root = temp_project("qa-brief-manual-")
    harness.use_project(root)
    cfg = json.loads((STAND / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    if cfg_edit:
        cfg_edit(cfg)
    (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (root / "testproject1_test_harness").mkdir()
    text = (STAND / "testproject1_test_harness" / "env.fixture").read_text(encoding="utf-8").replace("AUTH_PASSWORD=x", f"AUTH_PASSWORD={SECRET}")
    (root / "testproject1_test_harness" / "env.fixture").write_text(text + (env_lines or ""), encoding="utf-8")
    task = root / "qa-factory" / "artifacts" / TICKET
    (task / "work").mkdir(parents=True)
    (task / "state").mkdir()
    pipeline = {"ticket": TICKET, "size": "XXL", "environment": "local-docker" if env is None else env,
                "implementation_source": "diff", "stages": {"S0": {"status": "done"}}, "gates": {}, "halts": []}
    if env == "":
        pipeline.pop("environment")         # the pipeline names no environment (F13)
    (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    record = dispatch if dispatch is not None else DISPATCH
    cases = list(record.get("manual_case_ids") or record.get("scope") or [])
    (task / "state" / "controller.json").write_text(json.dumps(
        {"scope": cases, "dispatches": {DISPATCH_ID: record}}), encoding="utf-8")
    import manual_capture as MC
    for case, body in (requests or {}).items():
        path = MC.case_root(task, case) / "request.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root, task


def repo_of(paths=UTILS, error=None, path=MAP_PATH) -> dict:
    if error:
        return {"error": error}
    return {"doc": {"utils": [{"path": p, "bytes": 1, "classes": [], "defs": []} for p in paths], "empty": not paths},
            "path": path, "written": False, "markdown": "# map\n\n" + "\n".join(f"- {p}" for p in paths)}


def brief(repo=None, **keep) -> dict:
    """brief_pack.build for the run's dispatch, the map replaced by `repo` (the real map is another key's)."""
    with patch.object(judge, "active", return_value=False), \
            patch.object(brief_pack, "repo_map_for", return_value=repo if repo is not None else repo_of()):
        return brief_pack.build(TICKET, "S6", "qa-runner", DISPATCH_ID, write=False, **keep)


def section(text: str, head: str) -> list:
    out, on = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            on = line == "## " + head
            continue
        if on:
            out.append(line)
    return out


def without_stand(text: str) -> str:
    return re.sub(r"\n## The stand\n\n.*?\n(?=\n## )", "", text, flags=re.S)


SECOND_PW = "SENTINEL-SECOND-PW-91b3d0"
SECOND_ENV = f"QA_SECOND_USER_EMAIL=second@example.test\nQA_SECOND_USER_PASSWORD={SECOND_PW}\n"


def k1_the_joint(requests):
    root, task = story(requests=requests, env_lines=SECOND_ENV)
    try:
        out = brief()
        text, stand = out["markdown"], section(out["markdown"], "The stand")
        print(f"MEASURED manual brief bytes={out['bytes']} section lines={len(stand)} cap={brief_pack.BRIEF_MAX_BYTES}")
        check_in("K1 the frontend's address", "http://localhost:5173", text)
        check_in("K1 the API address of the stand's own entry", "- API: http://localhost:8080", text)
        check_in('K1 the account the stand lists, as the role types it', '--as "default user"', text)
        check_in("K1 the default account", "--as default", text)
        check_in("K1 the case's account, from the REAL request (TC-014 names its actor by one key)",
                 "TC-014: PC-1 env QA_SECOND_USER_EMAIL", text)
        check_not_in("K1 TC-012 names a `none` precondition that is not an account: no line of its own", "TC-012:", "\n".join(stand))
        check_in("K1 the env key names: the role's pair and the case's key", "- Env keys: AUTH_USERNAME, AUTH_PASSWORD, QA_SECOND_USER_EMAIL", text)
        check_in("K1 t-1550: the second user's PASSWORD key name is in the brief too (the auto-actor refusal points here)",
                 "QA_SECOND_USER_PASSWORD", "\n".join(x for x in stand if x.startswith("- Env keys:")))
        check_not_in("K1 t-1550: ... and the value of that key, grep over the whole brief: 0", SECOND_PW, text)
        check_not_in("K1 t-1550: ... nor the second user's address", "second@example.test", text)
        check_in("K1 the page objects: five paths, then the count and the map", f"(+5 more: {MAP_PATH})", text)
        check_in("K1 ... in the map's order", ", ".join(UTILS[:5]), text)
        check_in("K1 the command of the browser capture", "manual_capture.py ui", text)
        check("K1 the section stands right before `## Commands`",
              text.find("## The stand") != -1 and text.find("## The stand") < text.find("## Commands")
              and text.index("## Commands") == text.index("\n## Commands") + 1
              and "## Read these files" in text[:text.find("## The stand")], text[:300])
        for value in (SECRET, "qa-user@example.test", "jira.example.test"):
            check_not_in(f"K1 no value of the env file in the brief ({value[:12]}...)", value, text)
        check_not_in("K1 the section carries no value of the env file but the frontend's address", "localhost:8080/v1", "\n".join(stand))
    finally:
        cleanup(root)


def k2_automated_block(requests):
    auto = {**DISPATCH, "execution_kind": "automation", "request_binding": {"purpose": "manual", "execution_kind": "automation"}}
    auto.pop("manual_case_ids")
    root, task = story(requests=requests, dispatch=auto)
    try:
        got = brief()["markdown"]
        check_not_in("K2 an automated block: no section", "## The stand", got)
        check_not_in("K2 ... and no stand line", "- Frontend:", got)
    finally:
        cleanup(root)
    legacy = {k: v for k, v in DISPATCH.items() if k not in ("execution_kind", "request_binding", "manual_case_ids")}
    root, task = story(requests=requests, dispatch=legacy)
    try:
        check_not_in("K2 a record with no kind: no section", "## The stand", brief()["markdown"])
    finally:
        cleanup(root)
    # the map's inline lines give way first when the section needs room (K3), so the comparison is on a map with no body
    bodyless = {**repo_of(), "markdown": ""}
    root, task = story(requests=requests)
    try:
        manual = brief(bodyless)["markdown"]
    finally:
        cleanup(root)
    check_in("K2 control: the manual brief of the comparison has its section", "## The stand", manual)
    root, task = story(requests=requests, dispatch={**DISPATCH, "execution_kind": "automation",
                                                    "request_binding": {"purpose": "manual", "execution_kind": "automation"}})
    try:
        again = brief(bodyless)["markdown"]
    finally:
        cleanup(root)
    import difflib
    # the manual brief WITH its commands is longer by the manual-only list: the section AND those lines are the whole difference
    check_in("K2 t-1550 F2 control: the manual brief carries the manual commands", "manual_capture.py ui", manual)
    for flag in ("--with-attempt aN", "--then-seen", "--then-unreached", "--completion <path>", "--limitation"):
        check_in(f"K2 HF8-19 F6b: the manual brief's build/rejudge lines name {flag}", flag, manual)
    check_not_in("K2 t-1550 F2: the automated qa-runner brief has no `manual_capture.py` (the manual-only list is not the shared one)",
                 "manual_capture.py", again)
    check_not_in("K2 t-1550 F2: ... nor `manual_evidence.py build`", "manual_evidence.py build", again)
    lines = [x for x in difflib.unified_diff(without_stand(manual).splitlines(), again.splitlines(), lineterm="", n=0)
             if x[:1] in "+-" and x[:3] not in ("+++", "---")]
    manual_only = [x for x in lines if x.startswith("-") and ("manual_capture.py" in x or "manual_evidence.py build" in x or "manual_evidence.py rejudge" in x or x.startswith("--masked"))]
    # t-1807: the lines X3 (exploration charter, cells, axis oracles) and B-A (side-file notes, SD head, finding command) add to the
    # manual brief and not to the automated one; exact lines, the charter line by its prefix (it carries the package path)
    x3_ba_lines = {
        "-## Not in the brief", "-",
        f"-- the digests of earlier roles - read qa-factory/artifacts/{TICKET}/work/briefs/S6-qa-runner-2-digests.md",
        f"-- 3 input file(s) - read qa-factory/artifacts/{TICKET}/work/briefs/S6-qa-runner-2-files.md",
        # FL-4: `work/first-look.yaml` is an optional input of the S6 runner; the manual brief counts it in the side file (3 -> 4 files),
        # the automated brief names it inline (the one-line "no first look" reading)
        f"-- 4 input file(s) - read qa-factory/artifacts/{TICKET}/work/briefs/S6-qa-runner-2-files.md",
        f"+- qa-factory/artifacts/{TICKET}/work/first-look.yaml: no first look - work/first-look.yaml does not exist: no first look was written for this story",
        "-- in the side file, see Not in the brief",
        "+- S0 done: no digest",
        "-- the stage declares no input file",
        f'+- work/automation-manifest.json: do not read whole - `manifest_view.py --task {TICKET} --window "<ids>" | --case <case id> | --summary`',
        f"+- qa-factory/artifacts/{TICKET}/state/story-case-links.json: not written yet — that is the path it will have, and nothing else is it",
        f"+- qa-factory/artifacts/{TICKET}/work/context-manifest.json: not written yet — that is the path it will have, and nothing else is it",
        f"+- qa-factory/artifacts/{TICKET}/work/s5-notes.md: not written yet — that is the path it will have, and nothing else is it",
        '-- exploratory_findings.py add --task-root <task root> --by S6-qa-runner-2 --kind observation|unresolved_question|coverage_gap --title "<t>" --statement "<what you saw>" --why-not-a-bug "<w>" [--evidence <captured file>]... [--question "<q>" --owner-role <r>] [--missing-prerequisite "<p>"] - a doubt that is not a violated oracle, recorded when you meet it',
    }
    # t-1812: the cells and the axis oracles are a SIDE FILE behind ONE pointer line (`-Exploration cells: <path> ...`)
    x3_ba = [x for x in lines if x in x3_ba_lines or x.startswith(("-Exploration charter: ", "-Exploration cells: ", "-Recorder grammar: "))]   # t-1957 E3.5: the fallback line (the path of the grammar)
    check_eq("K2 the exploration pointer is ONE line in the manual brief",
             len([x for x in x3_ba if x.startswith("-Exploration cells: ")]), 1)
    check_eq("K2 the manual brief without its section differs from the automated one by the manual-only command lines, the X3/B-A lines and nothing else",
             [x for x in lines if x not in manual_only and x not in x3_ba], [])
    check_not_in("K2 HF8-19: ... nor `manual_evidence.py rejudge`", "manual_evidence.py rejudge", again)
    check_not_in("K2 t-1550 F2: the shared qa-runner TOOLING list holds no manual command",
                 "manual_capture.py", "\n".join(brief_pack.TOOLING["qa-runner"]))


def k3_never_cut(requests):
    root, task = story(requests=requests)
    try:
        # N4: the FULL brief is the one built with room (the real ceiling already trims this fixture and says so); AT its budget
        # nothing is cut, ONE byte beyond something that is not the section is taken - and the brief SAYS what (E16).
        with patch.object(brief_pack, "BRIEF_MAX_BYTES", 64 * 1024):
            full = brief()
        size, stand_full = full["budget_bytes"], section(full["markdown"], "The stand")
        check_eq("K3 the roomy brief trims nothing", full["omitted"], [])
        with patch.object(brief_pack, "BRIEF_MAX_BYTES", size):
            at = brief()
        check_eq("K3 AT the ceiling: nothing is cut (the brief is the full one)", at["markdown"], full["markdown"])
        with patch.object(brief_pack, "BRIEF_MAX_BYTES", size - 1):
            beyond = brief()
        check_eq("K3 ONE byte beyond: the section is whole", section(beyond["markdown"], "The stand"), stand_full)
        check("K3 ... something else went instead, and `## Not in the brief` says what",
              bool(beyond["omitted"]) and "## Not in the brief" in beyond["markdown"], str(beyond["omitted"]))
        check("K3 ... and the brief fits", beyond["budget_bytes"] <= size - 1, str(beyond["budget_bytes"]))
        with patch.object(brief_pack, "BRIEF_MAX_BYTES", 300):
            squeezed = brief()
        check_eq("K3 a ceiling nothing meets: the section is whole", section(squeezed["markdown"], "The stand"), stand_full)
        check("K3 ... the brief goes out over the ceiling", squeezed["bytes"] > 300, str(squeezed["bytes"]))
        check_in("K3 ... with the card", "manual_capture.py ui", squeezed["markdown"])
    finally:
        cleanup(root)
    # the limits: 5/6 paths of the map
    root, task = story(requests=requests)
    try:
        five = "\n".join(section(brief(repo_of(UTILS[:5]))["markdown"], "The stand"))
        six = "\n".join(section(brief(repo_of(UTILS[:6]))["markdown"], "The stand"))
        check_not_in("K3 five page objects: no count", "more:", five.split("Page objects")[1])
        check_in("K3 six page objects: the sixth is counted with the map's path", f"(+1 more: {MAP_PATH})", six)
        check_not_in("K3 ... and not named", UTILS[5], six)
    finally:
        cleanup(root)
    # the limits: 10/11 case lines
    one = json.loads(requests["TC-014"])
    ids = [f"TC-{n:03d}" for n in range(100, 111)]
    reqs = {case: json.dumps(one) for case in ids}
    for count, more in ((10, False), (11, True)):
        root, task = story(requests=reqs, dispatch={**DISPATCH, "scope": ids[:count], "manual_case_ids": ids[:count]})
        try:
            lines = [x for x in section(brief()["markdown"], "The stand") if x.startswith("- Case actors:")]
        finally:
            cleanup(root)
        check_eq(f"K3 {count} cases with an account: {10 + (1 if more else 0)} case lines (ten, and the count of the rest)",
                 len(lines), 10 + (1 if more else 0))
        check_eq(f"K3 ... {'the 11th is counted' if more else 'no count line'}",
                 lines[-1] == "- Case actors: (+1 more)", more)


def k4_edges(requests):
    # no stand selected
    root, task = story(requests=requests, env="no-such-stand")
    try:
        stand = "\n".join(section(brief()["markdown"], "The stand"))
        check_in("K4 no stand selected: the line says so and why", "- Stand: not selected (the environment 'no-such-stand' is missing", stand)
        check_not_in("K4 ... no address is guessed", "- Frontend:", stand)
        check_in("K4 ... the cases' accounts do not depend on the stand", "TC-014: PC-1 env QA_SECOND_USER_EMAIL", stand)
    finally:
        cleanup(root)

    def no_roles(cfg):
        cfg["environments"][0].pop("credentials_by_role")
    root, task = story(requests=requests, cfg_edit=no_roles)
    try:
        stand = "\n".join(section(brief()["markdown"], "The stand"))
        check_in("K4 no roles: the default account and a plain line", "- Accounts: --as default; the stand lists no other", stand)
    finally:
        cleanup(root)

    def no_front(cfg):
        cfg["environments"][0].pop("frontend_url")
    root, task = story(requests=requests, cfg_edit=no_front)
    try:
        stand = "\n".join(section(brief()["markdown"], "The stand"))
        check_in("K4 no frontend address: said, with the door", "- Frontend: not configured (", stand)
        check_not_in("K4 ... no address in the line", "localhost:5173", stand)
    finally:
        cleanup(root)

    def userinfo(cfg):
        cfg["environments"][0]["frontend_url"] = "http://qa-user:SENTINEL-IN-URL@localhost:5173"
    root, task = story(requests=requests, cfg_edit=userinfo)
    try:
        text = brief()["markdown"]
        check_in("K4 an address with credentials is not an address", "- Frontend: not configured (the address carries credentials)", text)
        check_not_in("K4 ... and its credentials are nowhere in the brief", "SENTINEL-IN-URL", text)
    finally:
        cleanup(root)

    # actors: [] declared, a refused request, no request, an unreadable accounts line, an unreadable file
    base = json.loads(requests["TC-014"])
    empty = json.dumps(dict(base, actors=[]))
    refused = json.dumps({"refused": {"reason": "no obligation", "door": "ask"}})
    unreadable = json.dumps({k: v for k, v in dict(base, actors_unreadable="x" * 300 + " cut here").items() if k != "actors"})
    root, task = story(requests={"TC-010": empty, "TC-012": refused, "TC-014": "{not json"})
    try:
        stand = "\n".join(section(brief()["markdown"], "The stand"))
        check_in("K4 an unreadable request: a line for the case, with the file's name", "TC-014: actors could not be read (the request of TC-014 (request.json)", stand)
        check_not_in("K4 actors [] and a refused request: no line of their own", "TC-010:", stand)
        check_not_in("K4 ... a refused request: no line", "TC-012:", stand)
    finally:
        cleanup(root)
    root, task = story(requests={"TC-010": empty})
    try:
        stand = "\n".join(section(brief()["markdown"], "The stand"))
        check_in("K4 no case names an account: the section says so", "- Case actors: none named by the cases' requests", stand)
        check_in("K4 ... the env keys are the role's pair", "- Env keys: AUTH_USERNAME, AUTH_PASSWORD", stand)
    finally:
        cleanup(root)
    root, task = story(requests={"TC-014": unreadable})
    try:
        line = next(x for x in section(brief()["markdown"], "The stand") if "TC-014" in x)
        check("K4 an unreadable accounts line: the reason is cut at 80 characters",
              line.startswith("- Case actors: TC-014: actors could not be read (") and len(line.split("(", 1)[1]) <= 82, line)
    finally:
        cleanup(root)

    # the map
    root, task = story(requests=requests)
    try:
        check_in("K4 an empty map: the line says none matched, with the map",
                 f"- Page objects (repo map): none matched ({MAP_PATH})", brief(repo_of([]))["markdown"])
        check_in("K4 a map that could not be built: the line says so, the reason cut",
                 "- Page objects (repo map): the map could not be built (OSError: " + "y" * 50,
                 brief(repo_of(error="OSError: " + "y" * 200))["markdown"])
        with patch.object(brief_pack, "repo_map_for", return_value=None), patch.object(judge, "active", return_value=False):
            none = brief_pack.build(TICKET, "S6", "qa-runner", DISPATCH_ID, write=False)["markdown"]
        check_in("K4 no map asked: the line says so", "- Page objects (repo map): no map was built for this block", none)
    finally:
        cleanup(root)


def k5_card(requests):
    root, task = story(requests=requests)
    try:
        card = "\n".join(section(brief()["markdown"], "Commands"))      # the MANUAL block's card (t-1550 F2)
    finally:
        cleanup(root)
    for needle in ("manual_capture.py ui --task-root <task root> --case <C> --steps-file <S> [--as <account>] [--attempt aN]",
                   "manual_capture.py http --task-root <task root> --case <C> --method <M> --url <U> [--body-file <F>] [--as <account>]",
                   "manual_evidence.py build --task-root <task root> --case <C> --result pass|fail|inconclusive --actual",
                   "--masked", "[--limitation"):
        check_in(f"K5 the card carries `{needle[:48]}...`", needle, card)
    charter = (harness.PLUGIN_ROOT / "agents" / "qa-runner.md").read_text(encoding="utf-8")
    for script in ("manual_capture.py", "manual_evidence.py"):
        check(f"K5 the charter names {script} and the card carries it", script in charter and script in card)


def k8_device_card(requests):
    """EP1-41f (AR-11): the `app` command line and the pointer to references/manual-evidence-app.md are on the card of a project that
    describes a device stand, and only there; the web card is as it was; a table that cannot be read hands nothing (no crash)."""
    import surfaces

    def device(cfg):
        cfg["environments"][0]["surface"] = "android"
    cards = {}
    for name, edit in (("web", None), ("device", device)):
        root, task = story(cfg_edit=edit, requests=requests)
        try:
            cards[name] = section(brief()["markdown"], "Commands")
            if name == "device":
                with patch.object(surfaces, "rows", side_effect=ValueError("table broken")):
                    cards["broken table"] = section(brief()["markdown"], "Commands")
        finally:
            cleanup(root)
    check("K8 the web card has no `app` line", not any("manual_capture.py app" in line for line in cards["web"]))
    check("K8 ... and does not name the app reference", not any("manual-evidence-app.md" in line for line in cards["web"]))
    handed = [line for line in cards["device"] if "manual_capture.py app" in line]
    check_eq("K8 a device stand hands exactly one `app` line", len(handed), 1)
    check_in("K8 ... pointing at the app reference", "references/manual-evidence-app.md", handed[0] if handed else "")
    check_eq("K8 the rest of the device card is the web card", [line for line in cards["device"] if line not in handed], cards["web"])
    check_eq("K8 a table that cannot be read hands no `app` line and does not crash", cards["broken table"], cards["web"])


def stand_of(markdown: str) -> str:
    return "\n".join(section(markdown, "The stand"))


def k6_env_keys_and_the_unnamed_stand(requests):
    """t-1550 F3 (`Env keys`: names only, capped, an unreadable file said) and F13 (the pipeline names no environment)."""
    # the cap: STAND_ROLES_MAX names, the rest counted
    many = "".join(f"QA_EXTRA_SECRET_{n:02d}=SENTINEL-EXTRA-{n}\n" for n in range(12))
    root, task = story(requests=requests, env_lines=many)
    try:
        text = brief()["markdown"]
        line = next(x for x in section(text, "The stand") if x.startswith("- Env keys:"))
        names = line[len("- Env keys: "):].split(" (+")[0].split(", ")
        check_eq("K6 F3 the cap: STAND_ROLES_MAX names are shown", len(names), brief_pack.STAND_ROLES_MAX)
        check("K6 F3 ... and the rest is counted", re.search(r"\(\+\d+ more\)$", line) is not None, line)
        check_not_in("K6 F3 no value of the env file in the brief (grep of the sentinel values: 0)", "SENTINEL-EXTRA", text)
    finally:
        cleanup(root)
    # the file is configured and cannot be read: the line says so, never "none"
    root, task = story(requests=requests)
    try:
        env_path = root / "testproject1_test_harness" / "env.fixture"
        env_path.unlink()
        env_path.mkdir()
        line = next(x for x in section(brief()["markdown"], "The stand") if x.startswith("- Env keys:"))
        check_in("K6 F3 an unreadable env file: the line says so", "could not be read", line)
        check_in("K6 F3 ... the role's and the case's names are still there", "QA_SECOND_USER_EMAIL", line)
    finally:
        shutil.rmtree(root / "testproject1_test_harness", ignore_errors=True)
        cleanup(root)
    # F13: the pipeline names no environment. ONE entry in the config is the stand; two or more are not guessed between
    root, task = story(requests=requests, env="")
    try:
        stand = stand_of(brief()["markdown"])
        check_in("K6 F13 no name + one entry: that entry's accounts", '--as "default user"', stand)
        check_in("K6 F13 ... and its address", "- Frontend: http://localhost:5173", stand)
    finally:
        cleanup(root)

    def two(cfg):
        cfg["environments"].append(dict(cfg["environments"][0], name="other-stand"))
    root, task = story(requests=requests, env="", cfg_edit=two)
    try:
        stand = stand_of(brief()["markdown"])
        check_in("K6 F13 no name + two entries: the section says the stand is not named", "- Stand: not named in pipeline.json", stand)
        check_not_in("K6 F13 ... and never `the stand lists no other`", "lists no other", stand)
        check_in("K6 F13 ... the cases' accounts are still there", "TC-014: PC-1 env QA_SECOND_USER_EMAIL", stand)
    finally:
        cleanup(root)


def k7_a_role_without_a_pair(requests):
    """OH3-40 (t-506 7.2 p.4): a case that names a `stand_account` role the stand holds no pair for gets a line telling the role
    not to sign in as another account. Mutant: `_unpaired_actor_lines` always empty -> this function."""
    base = json.loads(requests["TC-014"])

    def asking(role, kind="stand_account"):
        return json.dumps(dict(base, actors=[{"id": "PC-1", "what": "an account", "check": {kind: role}}]))

    def one_key(cfg):
        cfg["environments"][0]["credentials_by_role"]["half"] = "AUTH_USERNAME"

    def actors_of(role, kind="stand_account", **story_args):
        root, task = story(requests={"TC-014": asking(role, kind)}, **story_args)
        try:
            return stand_of(brief()["markdown"])
        finally:
            cleanup(root)

    line = 'TC-014: role "ghost" has no recorded account. Do not sign in as another account in its place: say so in your digest, or ask for the pair.'
    stand = actors_of("ghost")
    check_in("K7 a role the stand does not list: its own line, after the case's", f'- Case actors: TC-014: PC-1 stand_account "ghost"\n- Case actors: {line}', stand)
    check_in("K7 a role with ONE key (not a pair): the same line", 'TC-014: role "half" has no recorded account.', actors_of("half", cfg_edit=one_key))
    for label, role, kind, args in (("a role with a pair", "default user", "stand_account", {}), ("`default`", "default", "stand_account", {}),
                                    ("a spelling of a held role", "Default_User", "stand_account", {}),
                                    ("an `env` check", "QA_SECOND_USER_EMAIL", "env", {}),
                                    ("no stand selected (unknown is not 'no account')", "ghost", "stand_account", {"env": "no-such-stand"})):
        check_not_in(f"K7 {label}: no such line", "has no recorded account", actors_of(role, kind, **args))
    root, task = story(requests={"TC-010": json.dumps(dict(base, actors=[]))})
    try:
        check_not_in("K7 no actors: no such line", "has no recorded account", stand_of(brief()["markdown"]))
    finally:
        cleanup(root)


def main():
    requests = real_requests()
    print("MEASURED real requests:", {c: json.loads(t).get("actors", "refused") for c, t in requests.items()})
    kinds = {c: [(a["id"], next(iter(a["check"]))) for a in json.loads(t).get("actors", [])] for c, t in requests.items()}
    check_eq("K1 the producer wrote TC-014's account (named by one key) and, for TC-012, no account precondition",
             (kinds["TC-014"], kinds["TC-012"]), ([("PC-1", "env")], []))
    k1_the_joint(requests)
    k2_automated_block(requests)
    k3_never_cut(requests)
    k4_edges(requests)
    k5_card(requests)
    k6_env_keys_and_the_unnamed_stand(requests)
    k7_a_role_without_a_pair(requests)
    k8_device_card(requests)
    finish("test_brief_pack_manual")


if __name__ == "__main__":
    main()
