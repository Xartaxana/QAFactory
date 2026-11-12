"""`config_sha` from the execution-relevant configuration of ONE profile (execution-probes/2 EP2-1, spec t-143).

TP1-14857 on 0.10.2: job 0117fd1e re-ran TC-005 because `environments[0].frontend_url` was added to
qa-factory/config.json - a key no test launch reads - and `config_sha` hashed the whole file. Now the project config
named by the spec's `project_config` is hashed as a projection (references/config-projection.json): the run's profile
row, `run`, `execution`, the `environment` pointers, the selected stand's name and address, `tests_root`; every other
config file whole. The fixtures are the two committed versions of the project's config (29b05362, ff4fc62e) and the
bytes the receipts hold (4dfdc97c: ff4fc62e minus the one `frontend_url` line).

Keys (spec §6): K-W1..K-W3 the witness, K-A1/K-A2 the edge battery, K-B1/K-B2, K-D1 domain separation, K-E1..K-E8
refusals and no fallback, K-F1 the rule file, K-S1 shape, K-R1/K-R2 order, K-P1, K-M1/K-M2 the `_match` words, K-X1,
K-G1 the regression guard for future execution-relevant keys.

K-G1 is a regression guard, NOT a proof: it sees the access patterns `<recv>.get("<key>")`, `(<recv> or {}).get(...)`,
`<recv>["<key>"]`, `_setting(<expr>, "<section>", "<key>")` and `effective_config(<expr>).get("<key>")` over a table
of receiver variables per launch-path file. It does not see indirect reads: helpers that take the config under
another name, derived variables, files the launch writes, environment variables.
"""
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

import config_contract  # noqa: E402
import execution_fingerprint as F  # noqa: E402
import execution_request as er  # noqa: E402
import hooklib  # noqa: E402
import profile_contract  # noqa: E402
from detector_verdict import split_items  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]
FIX = Path(__file__).resolve().parent / "fixtures" / "config-projection"
LIVE = Path(__file__).resolve().parent / "fixtures" / "config-live-shape.json"
PROV = {"result": "not_applicable", "profile_id": "api", "environment_id": "local-docker",
        "expected_source_revision": "abc", "timestamp": "2026-10-27T00:00:00Z", "evidence_refs": []}
LINE = {1: "qa-factory/config.json is not a JSON object, so no projection can be built",
        5: "qa-factory/config.json nests deeper than the fingerprint can hash, so no projection can be built",
        6: "project_config must be one of the config_files",
        7: "the fingerprint rule set references/config-projection.json is not readable, or not of the documented shape"}
POLICY_REVISION = "config-projection-1"
R9 = ("classify `%s` in references/config-projection.json: projected (and rename policy_revision) or decision_only "
      "with its reason, and update the dependency trace (spec §A)")


class Project:
    """One temp project: the config lives at ONE path, so two versions of it differ only by their bytes."""

    def __init__(self, root):
        self.root = root
        self.cfg = root / "qa-factory" / "config.json"
        self.cfg.parent.mkdir(parents=True)
        self.test = root / "test_one.py"
        self.test.write_text("def test_one():\n    assert True\n", encoding="utf-8")

    def put(self, data):
        self.cfg.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode("utf-8"))

    def spec(self, profile="api", env="local-docker", project=True, **over):
        out = {"source_revision": "abc", "test_files": [str(self.test)], "config_files": [str(self.cfg)],
               "dependency_files": [], "runtime_provenance": dict(PROV, profile_id=profile, environment_id=env),
               "profile_id": profile}
        if project:
            out["project_config"] = str(self.cfg)
        out.update(over)
        return out

    def fp(self, data, **kw):
        self.put(data)
        return F.build(self.spec(**kw))

    def refusal(self, data, **kw):
        """`(kind, items)`: ("ok", []) when built, ("ValueError", the compound's lines); any other exception escapes."""
        if data is not None:
            self.put(data)
        try:
            F.build(self.spec(**kw))
            return "ok", []
        except ValueError as exc:
            text = str(exc)
            return "ValueError", split_items(text) or [text]


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def edits(a, b, path=""):
    """The smallest changed subtrees between two JSON values: an added/removed key is one edit, a leaf another."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            where = (path + "." if path else "") + key
            out += [where] if (key in a) != (key in b) else edits(a[key], b[key], where)
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [e for i, (x, y) in enumerate(zip(a, b)) for e in edits(x, y, "%s[%d]" % (path, i))]
    return [] if a == b else [path]


def row(cfg, pid):
    return next(p for p in cfg["profiles"] if p.get("profile_id") == pid)


def job_of(request, job_id):
    return {"job_id": job_id, "status": "completed", "freshness": "fresh", "execution_status": "passed",
            "request": request, "updated_at": "2026-10-27T00:44:00Z"}


def request_of(built, codes):
    return {"purpose": "initial", "profile_id": "api", "selected_instance_ids": sorted(codes),
            "command": {"selector_args": {i: ["tests/test_x.py::" + i] for i in codes}},
            "input_fingerprint": built["input_fingerprint"],
            "fingerprint_components": dict(built["fingerprint_components"]),
            "instance_contracts": {i: {"instance_code_sha": c, "instance_content_sha": c} for i, c in codes.items()}}


# --- K-G1: the guard over the launch path's config reads ------------------------------------------------------------
WHOLE = {"cfg": "", "load_config()": ""}
RECEIVERS = {
    "run_suite.py": WHOLE, "execution_request.py": WHOLE, "execution_scheduler.py": WHOLE,
    "runtime_probe.py": WHOLE, "execution_fingerprint.py": WHOLE,
    "test_locations.py": {"cfg": "", "ctx.cfg": "", "self.cfg": ""},
    # env_probe: `full_cfg` is the whole config, `cfg` the `environment` block (load_env, selected_probe_config)
    "env_probe.py": {"full_cfg": "", "cfg": "environment."},
    # test_files.py is a facade over test_locations and reporters.py takes no config: zero hits expected (a hit is
    # itself the finding: a new receiver to add to this table)
    "test_files.py": WHOLE, "reporters.py": WHOLE,
}


def config_reads(name, text):
    """`[(key, line)]` the access patterns find in one file, `key` top-level or `environment.<key>`."""
    found = []
    for recv, prefix in RECEIVERS[name].items():
        r = re.escape(recv)
        for pat in (r"(?<![\w.])" + r + r"\.get\(\s*\"([^\"]+)\"",
                    r"\(\s*" + r + r"\s+or\s+\{\}\s*\)\.get\(\s*\"([^\"]+)\"",
                    r"(?<![\w.])" + r + r"\[\s*\"([^\"]+)\"\s*\]"):
            found += [(prefix + m.group(1), text.count("\n", 0, m.start()) + 1) for m in re.finditer(pat, text)]
    for pat in (r"_setting\([^,()]+(?:\([^()]*\))?,\s*\"([^\"]+)\",\s*\"[^\"]+\"",
                r"effective_config\([^()]*\)\.get\(\s*\"([^\"]+)\""):
        found += [(m.group(1), text.count("\n", 0, m.start()) + 1) for m in re.finditer(pat, text)]
    return found


def classified(key, rules):
    top, _, child = key.partition(".")
    rule = rules["projection"].get(top)
    if not child:
        return rule is not None or top in rules["decision_only"]
    if rule is not None and child not in rule["minus"]:
        return True
    return key in rules["decision_only"]


def guard(texts, rules):
    """The R9 failure messages over `{file name: source text}`; empty when every key found is classified."""
    return [R9 % key + " (%s:%d)" % (name, line) for name, text in texts.items()
            for key, line in config_reads(name, text) if not classified(key, rules)]


def disjoint(rules):
    """The R2 keyspace rule: a decision-only `<top>.<child>` under a projected `<top>` is in its `minus` (or, for
    entry_by_name, not `name` nor an address key); a decision-only `<top>` is not projected."""
    bad = []
    for path in rules["decision_only"]:
        top, _, child = path.partition(".")
        rule = rules["projection"].get(top)
        if rule is None:
            continue
        if not child:
            bad.append(path)
        elif rule["keep"] == "entry_by_name":
            if child in ("name",) + tuple(F.STAND_ADDRESS_KEYS):
                bad.append(path)
        elif child not in rule["minus"]:
            bad.append(path)
    return bad


def mine_through_the_delivery_site(work):
    """K-B1 at the delivery site (critic t-150 F-1): `build_mine_request` on two on-disk project configs that differ
    only by `environments[0].frontend_url` gives one `config_sha`, and not the whole-file one of the same records."""
    import os
    from harness import use_project
    (work / "tests").mkdir(parents=True)
    (work / "tests" / "test_b.py").write_text("def test_alpha():\n    assert 1 == 1\n", encoding="utf-8")
    (work / "fake").mkdir()
    (work / "fake" / "pytest").write_text("# never started\n", encoding="utf-8")
    probe = {"argv": [sys.executable, "-c", "pass"], "cwd": ".", "timeout_s": 30}
    cfg = {"profiles": [{"profile_id": "api", "selected": True, "roots": {"test": "tests"},
                         "commands": {"one_test": {"argv": [sys.executable, str(work / "fake" / "pytest"), "<test-file>"],
                                                   "cwd": "."}},
                         "reporter": {"kind": "pytest"}, "selectors": {"verified": True}}],
           "execution": {"runtime_probes": {"api": probe}},
           "environments": [{"name": "local-docker", "base_url": "http://localhost:8080"}]}
    task = work / "qa-factory" / "artifacts" / "EP21-1"
    for name, value in (("work/automation-manifest.json",
                         {"tests": [{"case": "TC-005", "file": "tests/test_b.py", "selector": "test_alpha"}]}),
                        ("state/controller.json",
                         {"schema_version": "2", "revision": "1", "source_revision": "source-1",
                          "dispatches": {"S6-qa-runner-1": {"id": "S6-qa-runner-1", "stage": "S6", "role": "qa-runner",
                                                            "status": "running", "scope": ["TC-005"],
                                                            "budget": {"requests": 150}}}}),
                        ("pipeline.json", {"stages": {"S6": {"status": "running"}}})):
        (task / name).parent.mkdir(parents=True, exist_ok=True)
        (task / name).write_text(json.dumps(value), encoding="utf-8")
    (work / "qa-factory" / "state").mkdir(parents=True, exist_ok=True)
    seen = dict(PROV, expected_source_revision="source-1")
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    built = []
    try:
        use_project(work)
        for frontend in (None, "http://localhost:5173"):
            disk = copy.deepcopy(cfg)
            if frontend:
                disk["environments"][0]["frontend_url"] = frontend
            (work / "qa-factory" / "config.json").write_text(json.dumps(disk), encoding="utf-8")
            request = er.build_mine_request(work, ["TC-005"], cfg=disk, task="EP21-1", probe=lambda spec: dict(seen))[0]
            built.append(request)
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
        hooklib._PROJECT_ROOT_CACHE = None
    shas = [r["fingerprint_components"]["config_sha"] for r in built]
    whole = F.content_hash(sorted([r for r in built[1]["fingerprint_files"] if r["kind"] == "config_files"],
                                  key=lambda r: r["path"]))
    check("K-B1 build_mine_request: the frontend_url edit leaves config_sha equal at the delivery site",
          shas[0] == shas[1], shas)
    check("K-B1 build_mine_request: and that config_sha is the projection's, not the whole-file one",
          shas[1] != whole, (shas, whole))


def main() -> None:
    root = temp_dir("qa-config-projection-")
    try:
        p = Project(root)
        rules = F.projection_rules()
        ff, c4, c29 = load("config-ff4fc62e.json"), load("config-4dfdc97c.json"), load("config-29b05362.json")

        def csha(data, **kw):
            return p.fp(data, **kw)["fingerprint_components"]["config_sha"]

        # --- the fixtures are the receipts' bytes ----------------------------------------------------------------
        # --- K-W1 the witness ------------------------------------------------------------------------------------
        check_eq("K-W1 4dfdc97c -> 1be851c5 is exactly one edit", edits(c4, ff), ["environments[0].frontend_url"])
        check_eq("K-W1 29b05362 -> ff4fc62e is exactly three edits", edits(c29, ff),
                 ["environment.access.user_field", "environments[0].frontend_url", "execution.runtime_probes.api"])
        check_eq("K-W1 equal projection for api across 4dfdc97c -> 1be851c5",
                 F.config_projection(c4, "api", "local-docker", rules), F.config_projection(ff, "api", "local-docker", rules))
        check_eq("K-W1 equal config_sha for api across 4dfdc97c -> 1be851c5 (E1a)", csha(c4), csha(ff))
        check_eq("K-W1 equal config_sha for api across 29b05362 -> ff4fc62e (E1)", csha(c29), csha(ff))
        check("K-W1 control: the whole-file config_sha does move across 4dfdc97c -> 1be851c5",
              csha(c4, project=False) != csha(ff, project=False))

        # --- K-W2 / K-B1 / K-M1 through _match ----------------------------------------------------------------------
        policy, _ = er.load_run_budget()
        now = {"TC-001": "a04683", "TC-002": "9747e6", "TC-003": "d393e5", "TC-004": "4add9f", "TC-005": "1a6b26"}
        was = {"TC-001": "691e57", "TC-002": "ed0e3c", "TC-003": "56140d", "TC-004": "623e17"}
        req_0117 = request_of(p.fp(ff), now)
        job_1a6f = job_of(request_of(p.fp(c4), {"TC-005": "1a6b26"}), "1a6f06f9")
        job_b94 = job_of(request_of(p.fp(c4), was), "b94cbd84")
        # b94cbd84 ran an earlier version of the test file (test_content_sha 09dd68 -> 99508e in the receipts)
        job_b94["request"]["fingerprint_components"]["test_content_sha"] = "09dd68" + "0" * 58
        job_b94["request"]["input_fingerprint"] = F.content_hash(job_b94["request"]["fingerprint_components"])
        check_eq("K-W2 a 1a6f06f9-shaped job over 4dfdc97c covers TC-005 of the 0117fd1e request",
                 er.covered(job_1a6f, req_0117, "TC-005", policy=policy), (True, ""))
        for case in sorted(was):
            ok, why = er.covered(job_b94, req_0117, case, policy=policy)
            check("K-W2 the b94cbd84-shaped job: %s re-runs because its own bytes differ" % case,
                  not ok and why.startswith("instance bytes differ"), why)
        recorded = copy.deepcopy(job_1a6f)
        legacy = p.fp(c4, project=False)
        recorded["request"]["fingerprint_components"].update(config_sha=legacy["fingerprint_components"]["config_sha"],
                                                             policy_revision="unknown")
        recorded["request"]["input_fingerprint"] = F.content_hash(recorded["request"]["fingerprint_components"])
        ok, why = er.covered(recorded, req_0117, "TC-005", policy=policy)
        check("K-W2 the job as recorded (unknown, whole file) answers config_sha changed, the first run under the new "
              "rules (E14)", not ok and why.startswith("config_sha changed (") and "first run under the new rules" in why,
              why)
        check("K-D1 a pre-change receipt and a projected request never match", not ok)
        per = {"TC-005": er.covering([job_1a6f], req_0117, "TC-005", policy=policy)}
        check("K-B1 the 0117fd1e-shaped request after the frontend_url edit is covered for TC-005",
              per["TC-005"]["covered"] and per["TC-005"]["outcome"] == "passed", per)
        answer = er.budget_answer(policy, per, ["TC-005"], "S6")
        # budget_answer carries no `block` key; its own words are what the role reads
        check("K-B1 nothing is launched: the green result stands (status `reused`, words 'Already run ... same bytes')",
              answer["status"] == "reused" and answer["words"].startswith("Already run: 1 test(s) passed")
              and "over these same bytes" in answer["words"], answer)
        mine_through_the_delivery_site(root / "mine")
        moved = copy.deepcopy(ff)
        moved["run"]["reporter"] = "junit"
        ok, why = er.covered(job_1a6f, request_of(p.fp(moved), now), "TC-005", policy=policy)
        check("K-M1 changed run.reporter -> config_sha changed (the execution-relevant configuration of this profile ...)",
              not ok and why.startswith("config_sha changed (the execution-relevant configuration of this profile"), why)

        # --- K-A1 / K-A2 the battery (config_sha and input_fingerprint) --------------------------------------------
        base = p.fp(ff)

        def same(label, change, profile="api"):
            cfg = copy.deepcopy(ff)
            change(cfg)
            got, ref = p.fp(cfg, profile=profile), (base if profile == "api" else p.fp(ff, profile=profile))
            check("K-A1 equal: " + label,
                  got["fingerprint_components"]["config_sha"] == ref["fingerprint_components"]["config_sha"]
                  and got["input_fingerprint"] == ref["input_fingerprint"])

        def moves(label, change):
            cfg = copy.deepcopy(ff)
            change(cfg)
            got = p.fp(cfg)
            check("K-A1 moves: " + label,
                  got["fingerprint_components"]["config_sha"] != base["fingerprint_components"]["config_sha"]
                  and got["input_fingerprint"] != base["input_fingerprint"])

        env0 = lambda c: c["environments"][0]  # noqa: E731
        same("K-A2 / E2 frontend_url edited, profile ui", lambda c: env0(c).update(frontend_url="http://x:1"), "ui")
        same("E2 frontend_url edited, profile api", lambda c: env0(c).update(frontend_url="http://x:1"))
        for key in ("dod", "budget", "dispatch", "judge", "adapters", "sandbox"):
            same("E3 %s edited" % key, lambda c, key=key: c.update({key: {"edited": True}}))
        same("E3 a nested note edited", lambda c: c["environment"].update(note="other words"))
        same("E3 a *_note edited", lambda c: c.update(run_reporter_note="other words"))
        same("E3 a note inside the profile row", lambda c: row(c, "api").update(note="x", roots_note="y"))
        one = lambda c: row(c, "api")["commands"]["one_test"]  # noqa: E731
        moves("E4 one_test.argv", lambda c: one(c)["argv"].append("-x"))
        moves("E4 one_test.cwd", lambda c: one(c).update(cwd="sub"))
        moves("E4 reporter.kind", lambda c: row(c, "api")["reporter"].update(kind="junit"))
        moves("E4 roots.test", lambda c: row(c, "api")["roots"].update(test="other"))
        moves("E4 selectors", lambda c: row(c, "api").update(selectors={"x": 1}))
        moves("E4 adapter_id", lambda c: row(c, "api").update(adapter_id="unittest"))
        moves("E4 execution_prerequisites", lambda c: row(c, "api")["execution_prerequisites"].update(runtime="3.13"))
        moves("E4 dependency_ids", lambda c: row(c, "api").update(dependency_ids=["db"]))
        same("E5 profiles[ui] edited, request for api", lambda c: row(c, "ui")["commands"]["one_test"]["argv"].append("-x"))
        for key in ("reporter", "report_path", "dependency_files", "levels", "parallel"):
            moves("E6 run.%s" % key, lambda c, key=key: c["run"].update({key: "edited"}))
        for key in ("parallel", "verify_node_ids", "non_runtime_files"):
            moves("E6 execution.%s" % key, lambda c, key=key: c["execution"].update({key: "edited"}))
        for key in ("env_file", "env_files", "base_url_key", "user_key", "secret_keys", "extra_keys"):
            moves("E7 environment.%s" % key, lambda c, key=key: c["environment"].update({key: "edited"}))
        for key in ("base_url", "api_url", "api_base_url"):
            moves("E7 environments[selected].%s" % key, lambda c, key=key: env0(c).update({key: "http://other:9"}))
        moves("E7 tests_root", lambda c: c.update(tests_root="tests"))
        same("E8 a new top-level key", lambda c: c.update(foo={"bar": 1}))
        moves("E9 the selected stand renamed", lambda c: env0(c).update(name="renamed"))
        same("E10 execution.s5_window_cases", lambda c: c["execution"].update(s5_window_cases=99))
        same("E10 execution.runtime_probes", lambda c: c["execution"].update(runtime_probes={}))
        same("E10 environment.access.*", lambda c: c["environment"]["access"].update(user_field="x"))
        for key in ("health_url", "health_path", "health_expect", "frontend", "integrations"):
            same("E10 environment.%s" % key, lambda c, key=key: c["environment"].update({key: "edited"}))
        for key in ("bring_up", "default", "frontend", "health_url", "credentials_by_role", "safe_to_break"):
            same("E10 environments[].%s" % key, lambda c, key=key: env0(c).update({key: "edited"}))
        # EP1-41c: the five keys of a device stand are classified decision_only (R9) and no one of them moves config_sha
        for key in ("surface", "driver", "device", "app", "device_probe"):
            same("E10 EP1-41c environments[].%s" % key, lambda c, key=key: env0(c).update({key: {"edited": 1}}))
            check("E10 EP1-41c environments.%s is classified decision_only with a reason" % key,
                  bool(str(rules["decision_only"].get("environments." + key) or "").strip()), key)
        reformatted = json.dumps(dict(reversed(list(ff.items()))), indent=4).replace("\n", "\r\n")
        p.put(b"\xef\xbb\xbf" + reformatted.encode("utf-8"))
        check_eq("K-A1 E16 key order, whitespace, CRLF and a BOM do not move config_sha",
                 F.build(p.spec())["fingerprint_components"]["config_sha"], base["fingerprint_components"]["config_sha"])

        # --- K-D1 domain separation -----------------------------------------------------------------------------------
        for name, cfg in (("29b05362", c29), ("ff4fc62e", ff), ("4dfdc97c", c4)):
            check("K-D1 %s: the projected config_sha differs from the whole-file one of the same bytes" % name,
                  csha(cfg) != csha(cfg, project=False))

        # --- K-E1..K-E4 the contract's lines and line 1 ----------------------------------------------------------------
        for label, data in (("a non-JSON file", b"{not json"), ("an empty file", b""), ("a list", b"[]")):
            check_eq("K-E1 %s -> line 1" % label, p.refusal(data), ("ValueError", [LINE[1]]))
        check_eq("K-E2 profiles a string -> the contract's line", p.refusal({"profiles": "x"}),
                 ("ValueError", profile_contract.validate_config({"profiles": "x"})))
        bad_row = {"profiles": ["s", {"profile_id": "api"}]}
        check_eq("K-E3 a profiles row that is a string -> the contract's line, only that row",
                 p.refusal(bad_row), ("ValueError", profile_contract.validate_config({"profiles": ["s"]})))
        check_eq("K-E4 environment a string -> the contract's line", p.refusal({"environment": "s"}),
                 ("ValueError", config_contract.environment_errors("s")))
        missing = p.spec()
        del missing["profile_id"]
        p.put({"environment": "s"})
        try:
            F.build(missing)
            got = []
        except ValueError as exc:
            got = split_items(str(exc)) or [str(exc)]
        check_eq("K-E4 with profile_id missing: only the missing-key line (the group did not run)", got,
                 ["fingerprint specification missing profile_id"])

        # --- K-E5 line 6 and line 7 ---------------------------------------------------------------------------------
        p.put(ff)
        for label, value in (("a path not among config_files", str(root / "other.json")), ("7", 7), ("null", None),
                             ("a NUL byte (m-31: POSIX raises, Windows resolves to nothing given)", "a\x00b")):
            check_eq("K-E5 project_config %s -> line 6, ValueError only" % label,
                     p.refusal(None, project_config=value), ("ValueError", [LINE[6]]))
        real_ref = hooklib.ref
        broken = root / "rules"
        broken.mkdir()
        (broken / "list.json").write_text(json.dumps(dict(rules, projection=[])), encoding="utf-8")
        (broken / "empty.json").write_text(json.dumps(dict(rules, policy_revision="")), encoding="utf-8")
        try:
            for label, name in (("absent", "absent.json"), ("projection a list", "list.json"),
                                ("policy_revision empty", "empty.json")):
                hooklib.ref = lambda rel, name=name: broken / name
                check_eq("K-E5 the rule file %s -> line 7" % label, p.refusal(None), ("ValueError", [LINE[7]]))
                check_eq("K-R1 line 7 also without project_config", p.refusal(None, project=False),
                         ("ValueError", [LINE[7]]))
                check_eq("K-R1 line 7 comes before line 6", p.refusal(None, project_config=7), ("ValueError", [LINE[7]]))
        finally:
            hooklib.ref = real_ref

        # --- K-E6 no arbitrary catch, no fallback, no new requirement ------------------------------------------------
        real_projection = F.config_projection

        def raising(*_args):
            raise KeyError("boom")
        F.config_projection = raising
        try:
            try:
                p.fp(ff)
                escaped = "nothing"
            except KeyError:
                escaped = "KeyError"
            check_eq("K-E6 a KeyError inside config_projection propagates out of build (E17c)", escaped, "KeyError")
        finally:
            F.config_projection = real_projection
        for label, change, key, want in (("run a string", {"run": "x"}, "run", "x"),
                                         ("execution a number", {"execution": 7}, "execution", 7),
                                         ("profiles null", {"profiles": None}, "profiles", None),
                                         ("environment null", {"environment": None}, "environment", None)):
            cfg = dict(ff, **change)
            check_eq("K-E6 %s is projected as found, no refusal (E17a)" % label, p.refusal(cfg), ("ok", []))
            check_eq("K-E6 %s: the projected value" % label,
                     F.config_projection(cfg, "api", "local-docker", rules)[1]["projection"][key], want)
        no_envs = {k: v for k, v in ff.items() if k != "environments"}
        check_eq("K-E6 no environments[] projects, no refusal (E17b)", p.refusal(no_envs), ("ok", []))
        check_eq("K-E6 and its environments is null",
                 F.config_projection(no_envs, "api", "local-docker", rules)[1]["projection"]["environments"], None)
        check_eq("K-E6 the live-shape fixture projects, no refusal (E17b)",
                 p.refusal(json.loads(LIVE.read_text(encoding="utf-8")), env="local"), ("ok", []))
        bare = dict(ff, environments=[{"name": "local-docker", "bring_up": "x"}])
        check_eq("K-E6 an address-less entry projects as {name}",
                 F.config_projection(bare, "api", "local-docker", rules)[1]["projection"]["environments"],
                 {"name": "local-docker"})
        by_api = dict(ff, environments=[{"name": "local-docker", "api_url": "http://a:1", "frontend_url": "f"}])
        check_eq("K-E6 an api_url stand projects as {name, api_url}",
                 F.config_projection(by_api, "api", "local-docker", rules)[1]["projection"]["environments"],
                 {"name": "local-docker", "api_url": "http://a:1"})
        check("K-E6 the api_url value moves config_sha",
              csha(by_api) != csha(dict(ff, environments=[{"name": "local-docker", "api_url": "http://b:2"}])))
        p.put(ff)
        check_eq("K-E6 runtime_provenance 'zz' with project_config: exactly the provenance line (E17g)",
                 p.refusal(None, runtime_provenance="zz"), ("ValueError", ["runtime_provenance must be an object"]))
        absent = p.spec()
        del absent["runtime_provenance"]
        try:
            F.build(absent)
            got = []
        except ValueError as exc:
            got = split_items(str(exc)) or [str(exc)]
        check_eq("K-E6 runtime_provenance absent: exactly the missing-key line", got,
                 ["fingerprint specification missing runtime_provenance"])

        # --- K-E7 depth -------------------------------------------------------------------------------------------
        check_eq("K-E7 a config nested 100000 deep -> line 1, no traceback (E17e)",
                 p.refusal(b'{"run": ' + b"[" * 100000 + b"]" * 100000 + b"}"), ("ValueError", [LINE[1]]))
        real_hash = F.content_hash

        def deep(value):
            if isinstance(value, list) and any(isinstance(i, dict) and "projection" in i for i in value):
                raise RecursionError("too deep")
            return real_hash(value)
        p.put(ff)
        whole_before = F.build(p.spec(project=False))
        F.content_hash = deep
        try:
            check_eq("K-E7 the R1 list that cannot be hashed -> line 5, not hashed whole (E17f)", p.refusal(None),
                     ("ValueError", [LINE[5]]))
            check_eq("K-E7 the wrapper discriminates: a spec without project_config builds the same fingerprint",
                     F.build(p.spec(project=False)), whole_before)
        finally:
            F.content_hash = real_hash
        real_parts = F._projection_parts

        def recursing(*_args):
            raise RecursionError("elsewhere")
        F._projection_parts = recursing
        try:
            try:
                p.fp(ff)
                escaped = "nothing"
            except RecursionError:
                escaped = "RecursionError"
            check_eq("K-E7 a RecursionError anywhere else propagates out of build (E17c)", escaped, "RecursionError")
        finally:
            F._projection_parts = real_parts

        # --- K-E8 duplicates ----------------------------------------------------------------------------------------
        first, second = dict(row(ff, "api"), revision="first"), dict(row(ff, "api"), revision="second")
        dup = dict(ff, profiles=[first, second])
        check_eq("K-E8 two rows with the run's profile_id: the first row, no refusal",
                 (p.refusal(dup), F.config_projection(dup, "api", "local-docker", rules)[1]["projection"]["profiles"]["revision"]),
                 (("ok", []), "first"))
        two = dict(ff, environments=[ff["environments"][0], dict(ff["environments"][0])])
        check_eq("K-E8 two stand entries of the selected name: environments null, no refusal",
                 (p.refusal(two), F.config_projection(two, "api", "local-docker", rules)[1]["projection"]["environments"]),
                 (("ok", []), None))

        # --- K-B2 no profiles row -----------------------------------------------------------------------------------
        legacy_cfg = {k: v for k, v in ff.items() if k != "profiles"}
        check_eq("K-B2 a legacy config with no profiles builds, profiles null",
                 (p.refusal(legacy_cfg), F.config_projection(legacy_cfg, "api", "local-docker", rules)[1]["projection"]["profiles"]),
                 (("ok", []), None))
        check_eq("K-B2 a profile the file lacks builds, profiles null", p.refusal(ff, profile="nosuch"), ("ok", []))

        # --- K-F1 the rule file --------------------------------------------------------------------------------------
        check_eq("K-F1 the rules are read through hooklib.read_json(hooklib.ref(...))", rules,
                 hooklib.read_json(hooklib.ref("config-projection.json"), default=None, kind=dict))
        check_eq("K-F1 the policy_revision is pinned", rules["policy_revision"], POLICY_REVISION)
        payload = F.config_projection(ff, "api", "local-docker", rules)[1]
        check_eq("K-F1 absolute pin of P on ff4fc62e: its four keys and the rule set's policy_revision (t-150 F-2)",
                 (sorted(payload), payload["policy_revision"]),
                 (["environment_id", "policy_revision", "profile_id", "projection"], "config-projection-1"))
        check_eq("K-F1 / K-G1 projection and decision_only are disjoint under the R2 keyspace rule", disjoint(rules), [])

        # --- K-S1 shape / K-X1 the other components ---------------------------------------------------------------
        built, whole = p.fp(ff), p.fp(ff, project=False)
        check_eq("K-S1 build returns the same three keys", sorted(built),
                 ["fingerprint_components", "fingerprint_files", "input_fingerprint"])
        check_eq("K-S1 the six component names", sorted(built["fingerprint_components"]),
                 sorted(["source_sha", "test_content_sha", "config_sha", "dependency_sha", "runtime_sha", "policy_revision"]))
        check("K-S1 fingerprint_files records stay {path, sha256, kind}, the project one with its raw sha",
              all(sorted(r) == ["kind", "path", "sha256"] for r in built["fingerprint_files"])
              and built["fingerprint_files"] == whole["fingerprint_files"])
        check_eq("K-S1 policy_revision is the rule file's, with or without project_config",
                 (built["fingerprint_components"]["policy_revision"], whole["fingerprint_components"]["policy_revision"]),
                 (POLICY_REVISION, POLICY_REVISION))
        for key in ("source_sha", "test_content_sha", "dependency_sha", "runtime_sha"):
            check_eq("K-X1 %s is the same with and without the projection (E15)" % key,
                     built["fingerprint_components"][key], whole["fingerprint_components"][key])
        records = sorted([r for r in whole["fingerprint_files"] if r["kind"] == "config_files"], key=lambda r: r["path"])
        check_eq("K-S1 / E18 without project_config config_sha is the pile formula over the records",
                 whole["fingerprint_components"]["config_sha"], F.content_hash(records))

        # --- K-R1 / K-R2 order -----------------------------------------------------------------------------------------
        check_eq("K-R1 SPEC_REQUIRED keeps its order, profile_id last", F.SPEC_REQUIRED[-1], "profile_id")
        p.put(ff)
        _, items = p.refusal(None, profile_id="", policy_revision="x", runtime_provenance="zz", test_files=[])
        check_eq("K-R1 keys, K-R2, E13, provenance, file lists - in that order, no projection line", items,
                 ["profile_id must be a non-empty string", "policy_revision is the factory's, not the specification's",
                  "runtime_provenance must be an object", "test and configuration inputs must be explicit"])
        no_source = p.spec(profile_id=7)
        del no_source["source_revision"]
        try:
            F.build(no_source)
            got = []
        except ValueError as exc:
            got = split_items(str(exc)) or [str(exc)]
        check_eq("K-R2 profile_id not a string: its line right after the absent-key lines", got,
                 ["fingerprint specification missing source_revision", "profile_id must be a non-empty string"])
        check_eq("K-R2 profile_id empty -> its line, ValueError only", p.refusal(None, profile_id=""),
                 ("ValueError", ["profile_id must be a non-empty string"]))
        check_eq("K-R1 E13 a spec carrying policy_revision is refused by name", p.refusal(None, policy_revision="mine"),
                 ("ValueError", ["policy_revision is the factory's, not the specification's"]))
        check_eq("K-R1 line 6 stops before the read (line 1 is not told)",
                 p.refusal(b"{not json", project_config=7), ("ValueError", [LINE[6]]))
        check_eq("K-R1 lines 2-4 are listed together, in order",
                 p.refusal({"profiles": "x", "environment": "s"}),
                 ("ValueError", ["profiles: must be an array", "environment must be an object"]))
        check_eq("K-R1 project_config absent: no projection line", p.refusal(b"{not json", project=False), ("ok", []))

        # --- K-W3 the Windows path form -------------------------------------------------------------------------------
        p.put(ff)
        resolved = str(p.cfg.resolve())
        posix = p.fp(ff, project_config=p.cfg.as_posix(), config_files=[resolved])
        check("K-W3 a project_config in another spelling of the same path projects (E11b)",
              posix["fingerprint_components"]["config_sha"] == base["fingerprint_components"]["config_sha"]
              and posix["fingerprint_components"]["config_sha"] != whole["fingerprint_components"]["config_sha"])

        # --- K-P1 / K-M2 -----------------------------------------------------------------------------------------------
        # --- K-G1 the regression guard -----------------------------------------------------------------------------
        texts = {name: (SCRIPTS / name).read_text(encoding="utf-8") for name in RECEIVERS}
        check_eq("K-G1 every config key the launch path reads is classified in the rule file", guard(texts, rules), [])
        for name in ("test_files.py", "reporters.py"):
            check_eq("K-G1 %s carries no config receiver (its delegate is read instead)" % name,
                     config_reads(name, texts[name]), [])
    finally:
        cleanup(root)
    finish("test_config_projection")


if __name__ == "__main__":
    main()
