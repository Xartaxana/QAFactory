#!/usr/bin/env python3
"""t-2277 FL-3: where the first look stands in the flow, the brief of its runner and the charter paragraph.

Nothing here walks a browser or calls a stand. The wiring is read from the shipped data (`references/stages.json`, `agents/qa-runner.md`) and
the briefs are built through `brief_pack.build` on a project folder made by hand: a register, a pipeline, a controller record holding the
dispatches, the attempt of the first look and the record of its survey walk, a config with a default account and role accounts. One test per
item of the FL-3 block of the spec; the names are the spec's (and J-18 for the accounts, AR-23 for "no first look").
Run: `python -B test_first_look_wiring.py` (exit code = failures) or pytest.
"""
import json
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import first_look as FL  # noqa: E402
import hooklib  # noqa: E402

TICKET, STAND, OTHER_STAND, WALK = "QA-9", "dev", "stage", "S3-first-look"
SECRETS = ("hunter2-admin-pass", "s3cret-default-pass", "admin@example.test", "default@example.test")
ENV_FILE = ("AUTH_USERNAME=default@example.test\nAUTH_PASSWORD=s3cret-default-pass\n"
            "ADMIN_USER=admin@example.test\nADMIN_PASS=hunter2-admin-pass\n")
PIPELINE = {"ticket": TICKET, "size": "S", "environment": STAND, "implementation_source": "diff", "stages": {"S0": {"status": "pending"}},
            "gates": {}, "halts": []}
STAGES = {s["id"]: s for s in hooklib.load_ref_json("stages.json")["stages"]}


class Project:
    """A project folder with one story at S3: register of two requirements, a controller record, config with accounts."""

    def __init__(self, base, walk=True, sides=None):
        self.root = Path(base)
        harness.mark_project(self.root)
        self.task = self.root / "qa-factory" / "artifacts" / TICKET
        (self.task / "work").mkdir(parents=True)
        (self.task / "state").mkdir()
        (self.task / "pipeline.json").write_text(json.dumps(dict(PIPELINE, **({"sides": sides} if sides else {}))), encoding="utf-8")
        rows = "".join(f"| {r} | {t} | task |\n" for r, t in (("R-1", "The cart shows a Pay button under the total."),
                                                          ("R-2", "A discount code field is shown in the cart.")))
        (self.task / "work" / "requirements-register.md").write_text(
            "# Requirements register\n\n## Register\n\n| ID | Requirement | Source |\n|---|---|---|\n" + rows, encoding="utf-8")
        (self.task / "work" / "context-manifest.json").write_text(
            json.dumps({"implementations": [{"repo_id": "product", "source_sha": "a" * 40, "diff_path": "work/impl-diff.txt"}]}), encoding="utf-8")
        (self.root / "harness").mkdir()
        (self.root / "harness" / ".env").write_text(ENV_FILE, encoding="utf-8")
        cfg_path = self.root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["environment"] = {**(cfg.get("environment") if isinstance(cfg.get("environment"), dict) else {}),
                              "env_file": "harness/.env", "user_key": "AUTH_USERNAME", "secret_keys": ["AUTH_PASSWORD"]}
        cfg["environments"] = [{"name": STAND, "credentials_by_role": {"admin": ".env: ADMIN_USER / ADMIN_PASS - the administrator"}},
                               {"name": OTHER_STAND, "credentials_by_role": {"viewer": ".env: VIEWER_USER / VIEWER_PASS - a read-only user"}}]
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        harness.use_project(self.root)
        self.dispatches = {"S3-qa-test-strategist-1": {"id": "S3-qa-test-strategist-1", "stage": "S3", "role": "qa-test-strategist",
                                                      "status": "running", "scope": []},
                           "S3-qa-runner-1": {"id": "S3-qa-runner-1", "stage": "S3", "role": "qa-runner", "status": "running",
                                              "scope": [], "purpose": "first_look"},
                           "S6-qa-runner-1": {"id": "S6-qa-runner-1", "stage": "S6", "role": "qa-runner", "status": "running",
                                              "scope": [], "purpose": "bind"}}
        self.save()
        if walk:
            self.open_walk()

    def save(self):
        (self.task / "state" / "controller.json").write_text(json.dumps({"scope": [], "revision": 1, "dispatches": self.dispatches}),
                                                             encoding="utf-8")

    def open_walk(self, profiles=None, actors=("guest", "default")):
        FL.begin(self.task, WALK, STAND)
        record = {"walk": WALK, "place": "survey", "stand": STAND, "actors": list(actors), "items": ["R-1", "R-2"], "attempts": {},
                  "profiles": {"ui": "prof-ui", "http": "prof-api"} if profiles is None else profiles}
        path = self.task / "state" / "walks" / f"{WALK}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")

    def brief(self, stage, role, dispatch):
        return brief_pack.build(TICKET, stage, role, dispatch, write=False)["markdown"]

    def first_look_brief(self):
        return self.brief("S3", "qa-runner", "S3-qa-runner-1")


def lines_of(text, start):
    return [line for line in text.splitlines() if line.startswith(start)]


def test_s3_has_optional_first_look_runner():
    s3 = STAGES["S3"]
    optional = s3.get("optional_dispatches") or []
    check_eq("s3_has_optional_first_look_runner: S3 names one optional dispatch, the runner with purpose first_look, before window 1",
             optional, [{"role": "qa-runner", "purpose": "first_look", "output": "work/first-look.yaml", "before": "window 1"}])
    check("s3_has_optional_first_look_runner: it is no stage role (the strategist and the critic stay the roles; no new stage)",
          "qa-runner" not in s3["roles"] and s3["role"] == "qa-test-strategist", str(s3["roles"]))
    check_eq("s3_has_optional_first_look_runner: the stage numbers are unchanged", list(STAGES), [f"S{n}" for n in range(10)])
    check_eq("s3_has_optional_first_look_runner: S3 still requires S2 and S4 requires S3",
             (STAGES["S3"]["requires"], STAGES["S4"]["requires"]), (["S2"], ["S3"]))
    check("s3_has_optional_first_look_runner: the purpose is one the controller accepts", FL and brief_pack.FIRST_LOOK_PURPOSE == "first_look"
          and '"first_look"' in (harness.SCRIPTS / "controller.py").read_text(encoding="utf-8"))
    check("s3_has_optional_first_look_runner: no other stage names an optional dispatch (t-2181 PC-9b: S1 names the reference walk, only)",
          {sid: st.get("optional_dispatches") for sid, st in STAGES.items() if sid != "S3" and st.get("optional_dispatches")}
          == {"S1": [{"role": "qa-runner", "purpose": "reference_walk", "output": "work/reference-snapshot.yaml"}]})


def test_first_look_yaml_is_input_of_s3_to_s7_and_critics():
    for sid in ("S3", "S4", "S5", "S6", "S7"):
        check(f"first_look_yaml_is_input_of_s3_to_s7_and_critics: {sid} lists work/first-look.yaml among its inputs",
              "work/first-look.yaml" in STAGES[sid]["inputs"], str(STAGES[sid]["inputs"]))
    check("first_look_yaml_is_input_of_s3_to_s7_and_critics: no stage lists it as an output (code writes it, no stage owns it)",
          not [sid for sid, st in STAGES.items() if "work/first-look.yaml" in st["outputs"]])
    check("first_look_yaml_is_input_of_s3_to_s7_and_critics: S2 and S8 do not list it", all(
        "work/first-look.yaml" not in STAGES[sid]["inputs"] for sid in ("S0", "S1", "S2", "S8", "S9")))
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp, walk=False)
        p.dispatches["S4-qa-case-critic-1"] = {"id": "S4-qa-case-critic-1", "stage": "S4", "role": "qa-case-critic", "status": "running", "scope": []}
        p.dispatches["S5-qa-code-critic-1"] = {"id": "S5-qa-code-critic-1", "stage": "S5", "role": "qa-code-critic", "status": "running", "scope": []}
        p.dispatches["S3-qa-case-critic-1"] = {"id": "S3-qa-case-critic-1", "stage": "S3", "role": "qa-case-critic", "status": "running", "scope": []}
        p.save()
        path = f"qa-factory/artifacts/{TICKET}/work/first-look.yaml"
        for stage, role in (("S3", "qa-test-strategist"), ("S3", "qa-case-critic"), ("S4", "qa-case-critic"), ("S5", "qa-code-critic")):
            text = p.brief(stage, role, f"{stage}-{role}-1")
            check(f"first_look_yaml_is_input_of_s3_to_s7_and_critics: the {role} brief at {stage} names the record's path", path in text,
                  text[-500:])


def test_runner_charter_names_survey_http_and_put():
    text = (harness.PLUGIN_ROOT / "agents" / "qa-runner.md").read_text(encoding="utf-8")
    # the charter shape allows six sections only, so the first look is a bullet of `## Techniques` (a craft section)
    match = re.search(r"<!-- kind: craft -->\n## Techniques\n.*?\n- \*\*First look\.\*\* (.*?)(?=\n- \*\*|\n\n|\Z)", text, re.S)
    check("runner_charter_names_survey_http_and_put: a `First look` bullet under the craft section Techniques", bool(match))
    body = match.group(1) if match else ""
    for name, needle in (("the survey walk", "survey"), ("the HTTP step", "an HTTP step"), ("the one write", "`first_look.py put`"),
                         ("access with the role", "`access` (with the role named)"), ("nature only for what screen and API do not show", "`nature`"),
                         ("the path map", "locators"), ("API routes with method and sign-in", "the sign-in they need"),
                         ("a quote without quotation marks or line breaks", "without quotation marks or line breaks"),
                         ("observations, not expectations", "never what you expect"), ("no test-design techniques", "no test-design techniques")):
        check_in(f"runner_charter_names_survey_http_and_put: the paragraph names {name}", needle, body)
    check_not_in("runner_charter_names_survey_http_and_put: it sends the walker to no account question", "ask the person", body)
    check_in("runner_charter_names_survey_http_and_put: the runner signs in only as a walk actor (F4)", "Sign in as whichever walk actor", body)
    check_not_in("runner_charter_names_survey_http_and_put: and promises no account the brief lists (F4)", "whichever account", body)
    check_not_in("runner_charter_names_survey_http_and_put: the `about` line of the case walk is as it was (F5)", "manual_evidence.py build --about", text)


def test_first_look_brief_names_walk_env_profiles_items_and_put():
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp, sides={"product": {"reality": "substituted"}})
        text = p.first_look_brief()
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the walk id and the stand", f"First look: walk {WALK} on stand {STAND}", text)
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the screen profile", "screen (test profile prof-ui)", text)
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the HTTP profile", "HTTP (test profile prof-api)", text)
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the walk's actors", "Walk actors: guest, default", text)
        for req in ("R-1", "R-2"):
            check(f"first_look_brief_names_walk_env_profiles_items_and_put: a line for {req} with its statement",
                  bool(lines_of(text, f"- {req}: ")), text[-800:])
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the path of the requirements' text",
                 f"qa-factory/artifacts/{TICKET}/work/requirements-register.md", text)
        for command in ("walk_session.py item", "walk_session.py step", "walk_session.py look", "walk_session.py done"):
            check_in(f"first_look_brief_names_walk_env_profiles_items_and_put: the command {command}", command, text)
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the HTTP step with its body file", "`http <METHOD> <path> [--body-file <file>]`", text)
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the write", "first_look.py put --task-root", text)
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the walk id is substituted into the commands",
                 f"--walk {WALK} --item <R-n>", text)
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the contract path",
                 "references/artifact-contract-first-look.md", text)
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the form's closed words", "status: confirms, contradicts, missing, unreachable", text)
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: the substituted side", "product (substituted)", text)
        check_not_in("first_look_brief_names_walk_env_profiles_items_and_put: the strategist's S3 lines are not in the runner's brief",
                     "Functions to walk", text)
        check_not_in("first_look_brief_names_walk_env_profiles_items_and_put: nor the walk brief of a case",
                     "### Item", text)
        check("first_look_brief_names_walk_env_profiles_items_and_put: the file list holds the register and not the strategist's inputs",
              "work/requirements-register.md" in text and "test-strategy.md" not in text
              and not [line for line in lines_of(text, "- ") if "first-look.yaml" in line], text[-900:])
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp)
        text = p.first_look_brief()
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: every side real is said so", "none - every side is real", text)
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp, walk=False)
        got = brief_pack.first_look_runner_lines(p.task)
        check("first_look_brief_names_walk_env_profiles_items_and_put: no attempt is a line saying no walk is open (AR-23)",
              len(got) == 1 and "no walk is open" in got[0] and "halt" in got[0], str(got))
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp, walk=False)
        p.open_walk(profiles={})
        text = "\n".join(brief_pack.first_look_runner_lines(p.task))
        check_in("first_look_brief_names_walk_env_profiles_items_and_put: a walk with no profile recorded says so", "none recorded in state/walks/", text)


def test_first_look_brief_only_for_first_look_purpose():
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp)
        with_attempt = {key: p.brief(stage, role, did) for key, (stage, role, did) in {
            "runner S6, another purpose": ("S6", "qa-runner", "S6-qa-runner-1"),
            "strategist S3": ("S3", "qa-test-strategist", "S3-qa-test-strategist-1")}.items()}
        (p.task / "state" / "first-look-attempt.json").unlink()
        for key, before in with_attempt.items():
            after = p.brief(*{"runner S6, another purpose": ("S6", "qa-runner", "S6-qa-runner-1"),
                              "strategist S3": ("S3", "qa-test-strategist", "S3-qa-test-strategist-1")}[key])
            check_eq(f"first_look_brief_only_for_first_look_purpose: the {key} brief is the same bytes with the first look's attempt present or absent",
                     before, after)
            check_not_in(f"first_look_brief_only_for_first_look_purpose: the {key} brief has no first-look runner lines", "First look: walk", before)
        p.open_walk()
        check_in("first_look_brief_only_for_first_look_purpose: the control - the purpose first_look brief does carry them",
                 "First look: walk", p.first_look_brief())
        p.dispatches["S3-qa-runner-1"]["purpose"] = "reference_walk"
        p.save()
        check_not_in("first_look_brief_only_for_first_look_purpose: the same dispatch with another purpose carries none",
                     "First look: walk", p.first_look_brief())
        p.dispatches["S3-qa-runner-1"].pop("purpose")
        p.save()
        check_not_in("first_look_brief_only_for_first_look_purpose: nor with no purpose at all", "First look: walk", p.first_look_brief())
        p.dispatches["S3-qa-runner-1"]["purpose"] = "first_look"
        p.dispatches["S3-qa-test-strategist-1"]["purpose"] = "first_look"
        p.save()
        check_not_in("first_look_brief_only_for_first_look_purpose: the purpose word on another role's dispatch changes nothing",
                     "First look: walk", p.brief("S3", "qa-test-strategist", "S3-qa-test-strategist-1"))


def test_first_look_brief_lists_known_role_accounts_without_secrets():
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp)
        text = p.first_look_brief()
        line = (lines_of(text, "Accounts the factory has on") or [""])[0]
        check_in("first_look_brief_lists_known_role_accounts_without_secrets: the stand's default account is named", "default", line)
        check_in("first_look_brief_lists_known_role_accounts_without_secrets: a role with an account on this stand is named", "admin", line)
        check_in("first_look_brief_lists_known_role_accounts_without_secrets: a role the stand holds no account for is named as having none",
                 "Roles with no account found: viewer", line)
        for secret in SECRETS:
            check_not_in(f"first_look_brief_lists_known_role_accounts_without_secrets: the value {secret[:6]}... is nowhere in the brief", secret, text)
        for key in ("AUTH_PASSWORD", "ADMIN_PASS", "ADMIN_USER", "AUTH_USERNAME"):
            check_not_in(f"first_look_brief_lists_known_role_accounts_without_secrets: the key name {key} is not printed", key, line)
        check_not_in("first_look_brief_lists_known_role_accounts_without_secrets: no account question is put to the runner", "ask the person", text)
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp)
        (p.root / "harness" / ".env").unlink()
        line = (lines_of(p.first_look_brief(), "Accounts the factory has on") or [""])[0]
        check("first_look_brief_lists_known_role_accounts_without_secrets: without the env file the default is not claimed", "default" not in line.split(": ")[1].split(".")[0],
              line)
        check_in("first_look_brief_lists_known_role_accounts_without_secrets: and the line is still there, never empty", "Accounts the factory has on", line)
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp)
        line = (lines_of(p.first_look_brief(), "Accounts the factory has on") or [""])[0]
        check_not_in("first_look_brief_lists_known_role_accounts_without_secrets: no `--as <name>` is promised for a listed account (F4)", "--as", line)
        check_in("first_look_brief_lists_known_role_accounts_without_secrets: the line says the walk signs in only as its actors (F4)",
                 "only as the walk actors", line)
        check_not_in("first_look_brief_lists_known_role_accounts_without_secrets: a readable registry says nothing of a problem (F8)",
                     "cannot be read", line)
        rec = p.root / "qa-factory" / "records" / "project-knowledge.json"
        rec.parent.mkdir(parents=True, exist_ok=True)
        rec.write_text("{broken", encoding="utf-8")
        line = (lines_of(p.first_look_brief(), "Accounts the factory has on") or [""])[0]
        check("first_look_brief_lists_known_role_accounts_without_secrets: an unreadable registry is said, with the narrowing (AR-23, F8)",
              "cannot be read" in line and "listed from the stand's accounts only" in line, line)
        check_in("first_look_brief_lists_known_role_accounts_without_secrets: the stand's own accounts are still listed", "admin", line)


def test_first_look_brief_names_no_run_report():
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp)
        text = p.first_look_brief()
        check_not_in("first_look_brief_names_no_run_report: the brief names no run report (B3)", "run-report.json", text)
        check_not_in("first_look_brief_names_no_run_report: nor the case walk's DoD (B3)", "Each verdict quotes a capture", text)
        check_not_in("first_look_brief_names_no_run_report: nor its goal", "Every manual-agent case walked live", text)
        check_not_in("first_look_brief_names_no_run_report: nor the zero-run refusal of the role-level card", "zero run", text)
        check_in("first_look_brief_names_no_run_report: the final message names the record's path", "\nwork/first-look.yaml\n", text)
        check("first_look_brief_names_no_run_report: the goal is the first look's, recorded with put",
              bool(lines_of(text, "goal: Survey the new version")) and "first_look.py put" in (lines_of(text, "DoD: ") or [""])[0], text[:900])
        check_in("first_look_brief_names_no_run_report: the ahead card says put checks the record", "The record is checked by `first_look.py put`", text)
        check_eq("first_look_brief_names_no_run_report: ONE command card in the brief", text.count("Every command is `python"), 1)
        other = p.brief("S6", "qa-runner", "S6-qa-runner-1")
        check_in("first_look_brief_names_no_run_report: the control - the S6 runner brief still names it", "run-report.json", other)


def test_brief_pack_reads_first_look_through_public_functions():
    src = (harness.SCRIPTS / "brief_pack.py").read_text(encoding="utf-8")
    check("brief_pack_reads_first_look_through_public_functions: no private call into first_look (AR-13)", not re.search(r"\bFL\._\w+", src))
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp)
        ids, why = FL.register_ids(p.task)
        check_eq("brief_pack_reads_first_look_through_public_functions: the ids in register order", (ids, why), (["R-1", "R-2"], ""))
        check_eq("brief_pack_reads_first_look_through_public_functions: no non-real side, none named", FL.sides_met(p.task), {})
        (p.task / "work" / "requirements-register.md").unlink()
        ids, why = FL.register_ids(p.task)
        check("brief_pack_reads_first_look_through_public_functions: an unreadable register is ([], why)", ids == [] and bool(why), why)
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp, sides={"product": {"reality": "substituted"}})
        check_eq("brief_pack_reads_first_look_through_public_functions: a substituted side is named", FL.sides_met(p.task), {"product": "substituted"})


def test_no_record_reads_no_first_look():
    with tempfile.TemporaryDirectory() as tmp:
        p = Project(tmp, walk=False)
        path = f"qa-factory/artifacts/{TICKET}/work/first-look.yaml"
        absent = brief_pack.file_lines(["work/first-look.yaml"], p.task, p.root)
        check_eq("no_record_reads_no_first_look: no record is exactly one line, reading no first look", (len(absent), absent[0].startswith(f"- {path}: no first look - ")),
                 (1, True))
        done = FL.put(p.task, None, "no_stand")
        check("no_record_reads_no_first_look: a null record is written", done["written"], str(done))
        null = brief_pack.file_lines(["work/first-look.yaml"], p.task, p.root)
        check_eq("no_record_reads_no_first_look: a null record reads no first look with its reason", null,
                 [f"- {path}: no first look - the stand was not walked (no stand)"])
        (p.task / "work" / "first-look.yaml").write_text("garbage: [\n", encoding="utf-8")
        broken = brief_pack.file_lines(["work/first-look.yaml"], p.task, p.root)
        check("no_record_reads_no_first_look: an unreadable record also reads no first look, never a pass",
              len(broken) == 1 and ": no first look - " in broken[0], str(broken))
        (p.task / "work" / "first-look.yaml").unlink()
        p.open_walk()
        (p.task / "work" / "evidence" / "manual" / "survey-R-1" / "a1").mkdir(parents=True)
        (p.task / "work" / "evidence" / "manual" / "survey-R-2" / "a1").mkdir(parents=True)
        record = ("walk: S3-first-look\nstand: dev\nstand_build: not_established\nsource_head:\n  product: " + "a" * 40 + "\nregister_hash: "
                  + FL.current_keys(p.task)[1] + "\nrows:\n  - req: R-1\n    status: confirms\n    why: looked\n  - req: R-2\n    status: missing\n"
                  "    blocked_by: product\n    why: looked\ngaps: []\n")
        (p.task / "work" / "first-look.yaml").write_text(record, encoding="utf-8")
        present = brief_pack.file_lines(["work/first-look.yaml"], p.task, p.root)
        check("no_record_reads_no_first_look: a current record is listed with its size and as an observation, not an oracle",
              len(present) == 1 and "the first look at the stand before the plan" in present[0] and "oracle" in present[0] and "STALE" not in present[0],
              str(present))
        (p.task / "work" / "first-look.yaml").write_text(record.replace("a" * 40, "b" * 40), encoding="utf-8")
        stale = brief_pack.file_lines(["work/first-look.yaml"], p.task, p.root)
        check("no_record_reads_no_first_look: a record walked on other code is STALE and confirms nothing",
              len(stale) == 1 and "STALE" in stale[0] and "confirms nothing" in stale[0], str(stale))
        check_not_in("no_record_reads_no_first_look: the input line names no script (the critics have no shell)", ".py", "".join(present + stale + absent + null))


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_first_look_wiring")


if __name__ == "__main__":
    main()
