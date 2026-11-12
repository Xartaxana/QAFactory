"""OH3-31: a role's proposal gets the template keys it lacks, with the template's values, and the person sees them.

EP1-22's sibling on the onboarding side: `onboard_apply.plan` used to seal the proposal exactly as the role wrote it, so a
config written by a role that forgot `secret_file_patterns` (a guard key: audit A20, the secret scan) was valid for
`C.validate` and installed without it. `config_contract.fill_proposal` now fills every absent template key at the one
place the proposal is sealed, BEFORE `proposal_hash` and the listing, so "yes" covers what is written; a key flagged
`project_fact` in config-keys.json (roots, commands, stands, adapters: facts no default can know) is never invented, and
the listing names it as not filled.

Keys of the battery: C-fresh (apply and readiness halves) C-listing C-keep C-facts C-hash C-command C-final C-empty C-broken
C-magnitude C-gate, through the command line; F-4 (a foreign `conflicts` / `added` is a named refusal) and F-2 / F-5 (a foreign
`capabilities` / `dependency_ids` read `unknown`, never `ready`, never raise: the round-2 fixes of part 2).
"""
import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import config_contract as C  # noqa: E402
import human_text  # noqa: E402

TEMPLATE = C.canonical_template()
FACTS = ["app_root", "protected_app_paths", "tests_root", "code_repos", "test_command_templates", "environment",
         "environments", "adapters", "pre_commit_commands", "dod"]


def absent(name: str, key: str, keys) -> bool:
    """Membership, not substring: `code_repos` is a key and `code_repos_note` is another."""
    return check(name, key not in list(keys), f"{key!r} is among {sorted(keys)[:8]}...")


def project(prefix: str) -> Path:
    root = temp_dir(prefix)
    (root / ".git").mkdir()
    return root


def write(root: Path, name: str, data: dict) -> Path:
    path = root.parent / f"{root.name}-{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def cli(root: Path, *args):
    return run_script("onboard_apply.py", "--root", root, *args)


def minimal() -> dict:
    """What a role that wrote only what it discovered holds: the facts of the project, no guard key, no default."""
    return {"schema_version": 1, "app_root": "src", "tests_root": "tests", "dod": "Done means reviewed and green"}


def sealed(root: Path, config: dict, name: str = "p") -> dict:
    out = root.parent / f"{root.name}-{name}-out.json"
    done = cli(root, "--proposal", write(root, name, {"proposed_config": config}), "--out", out)
    check(f"{name}: the plan runs (exit 0)", done.returncode == 0, done.stderr[-400:])
    return json.loads(out.read_text(encoding="utf-8"))


def fresh_and_listing_and_facts() -> None:
    root = project("qa-fill-fresh-")
    try:
        proposal = write(root, "min", {"proposed_config": minimal()})
        out = root.parent / (root.name + "-min-out.json")
        listing = cli(root, "--proposal", proposal, "--out", out, "--listing")
        check("C-listing: the listing runs (exit 0)", listing.returncode == 0, listing.stderr[-400:])
        made = json.loads(out.read_text(encoding="utf-8"))
        added = [r["path"] for r in made["added"]]
        check_in("C-listing: `--out` holds the filled guard key in `added`", "/secret_file_patterns", added)
        check_in("C-listing: ... and a default section", "/budget", added)
        check_in("C-listing: the listing names the added keys", "secret_file_patterns", listing.stdout)
        check_in("C-listing: ... in the added-keys line", "setting(s) this version added", listing.stdout)
        check_eq("C-fresh: the sealed config holds the template value of the key the role left out",
                 made["proposed_config"]["secret_file_patterns"], TEMPLATE["secret_file_patterns"])
        check_eq("C-fresh: the role's own values are untouched",
                 (made["proposed_config"]["app_root"], made["proposed_config"]["tests_root"], made["proposed_config"]["dod"]),
                 ("src", "tests", "Done means reviewed and green"))
        # C-facts: the facts the role did not name are not invented
        for key in ("protected_app_paths", "code_repos", "test_command_templates", "environment", "environments", "adapters",
                    "pre_commit_commands"):
            absent(f"C-facts: {key} is not written", key, made["proposed_config"])
        absent("C-facts: ... and has no `added` row", "/adapters", added)
        check_in("C-facts: the listing names what was not filled", "were not filled in", listing.stdout)
        line = [ln.strip() for ln in listing.stdout.splitlines() if "were not filled in" in ln][0]
        check_eq("C-facts (FR-6): the new line breaks no rule of the person's text but the how-to-answer block a whole question owes",
                 [p["rule"] for p in human_text.problems(line)], ["no_how_to_answer"])
        for key in ("adapters", "environments", "code_repos"):
            check_in(f"C-facts: the listing names {key}", key, listing.stdout.split("were not filled in", 1)[1].splitlines()[0])
        check_eq("C-facts: the pure function names the same facts, in the template's order",
                 C.not_filled(made["proposed_config"]), [k for k in TEMPLATE if k in FACTS and k not in minimal()])
        check_eq("C-facts: ... and nothing for a config that holds them all", C.not_filled(copy.deepcopy(TEMPLATE)), [])
        check_eq("C-facts: ... nor for no configuration", C.not_filled(None), [])
        # a proposal with NO app_root does not get the template's "."
        bare = sealed(root, {"schema_version": 1, "dod": "x"}, "bare")
        absent("C-facts: no app_root in the proposal -> `app_root: \".\"` is NOT written", "app_root", bare["proposed_config"])
        check_in("C-facts: ... and the listing's words name it", "app_root",
                 cli(root, "--proposal", root.parent / f"{root.name}-bare.json", "--listing").stdout)
        # C-fresh, apply half. Decision Q1 (by recommendation, until the Lead's word): the rows `fill_proposal` adds carry
        # `absent_means: default`, so a proposal that omits a non-fact key is not read as an open question and installs.
        done = cli(root, "--proposal", proposal, "--apply")
        check("Q1: the apply of a proposal that lacked a `required` default key passes",
              done.returncode == 0 and (root / "qa-factory" / "config.json").exists(), done.stderr[-600:])
        check_eq("Q1: no filled row is an open question", C.unanswered_pointers(made), [])
        check("Q1: every filled row says `default`", all(r["absent_means"] == "default" for r in made["added"]))
        # a project fact is still not written, so it is still named (not invented); the plan refuses nothing for it
        check_eq("Q1: a project fact stays out of the written config",
                 sorted(k for k in FACTS if k in json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))),
                 sorted(k for k in FACTS if k in minimal()))
    finally:
        cleanup(root)


def keep() -> None:
    root = project("qa-fill-keep-")
    try:
        config = minimal()
        config.update({"secret_file_patterns": ["only-mine"], "case_id_form": None, "cases_root": "", "profiles": [],
                       "sizing": 7})
        made = sealed(root, config, "keep")
        got = made["proposed_config"]
        check_eq("C-keep: the project's own value stays", got["secret_file_patterns"], ["only-mine"])
        check_eq("C-keep: null stays null", got["case_id_form"], None)
        check_eq("C-keep: an empty string stays", got["cases_root"], "")
        check_eq("C-keep: an empty list stays", got["profiles"], [])
        check_eq("C-keep: a scalar over a group stays whole", got["sizing"], 7)
        check_in("C-keep: ... and is a conflict, as in migration_plan", "/sizing", [c["path"] for c in made["conflicts"]])
        for path in ("/secret_file_patterns", "/case_id_form", "/cases_root", "/profiles", "/sizing"):
            absent(f"C-keep: {path} has no `added` row", path, [r["path"] for r in made["added"]])
        # a scalar over a project-fact group is still named, never replaced
        odd = copy.deepcopy(minimal())
        odd["adapters"] = "none"
        made = sealed(root, odd, "odd")
        check_eq("C-keep: a scalar over a fact group stays whole", made["proposed_config"]["adapters"], "none")
        check_in("C-keep: ... and is a conflict", "/adapters", [c["path"] for c in made["conflicts"]])
        # a project fact that is present is not filled inside either
        poor = copy.deepcopy(minimal())
        poor["adapters"] = {"ticket": {"name": "jira"}}
        made = sealed(root, poor, "poor")
        check_eq("C-facts: a present fact is kept as the role wrote it (nothing invented under it)",
                 made["proposed_config"]["adapters"], {"ticket": {"name": "jira"}})
        # the notes of the template are the factory's text: filled like any default
        check_in("C-keep: a note the role left out is filled", "app_root_note", list(made["proposed_config"]))
    finally:
        cleanup(root)


def hashed() -> None:
    root = project("qa-fill-hash-")
    try:
        # a role's config that lacks only keys whose absence means `default` (and no fact is missing): it applies after the fill
        base = {k: v for k, v in copy.deepcopy(TEMPLATE).items() if k not in ("cases_root", "budget", "telemetry")}
        first = sealed(root, base, "h1")
        check_eq("C-hash: the filled keys are in `added`", [r["path"] for r in first["added"]], ["/cases_root", "/budget", "/telemetry"])
        check_eq("C-hash: ... and in the sealed config", (first["proposed_config"]["cases_root"], first["proposed_config"]["budget"]),
                 (TEMPLATE["cases_root"], TEMPLATE["budget"]))
        check_eq("C-hash: `not_filled` is not a field of the proposal", [k for k in first if "filled" in k], [])
        # the sealed file itself, with its listing, goes through plan again: same hash, `added` rows not doubled
        again = root.parent / (root.name + "-again-out.json")
        done = cli(root, "--proposal", root.parent / f"{root.name}-h1-out.json", "--out", again)
        check("C-hash: the sealed file is planned again (exit 0)", done.returncode == 0, done.stderr[-400:])
        third = json.loads(again.read_text(encoding="utf-8"))
        check_eq("C-hash: its hash is unchanged", third["proposal_hash"], first["proposal_hash"])
        check_eq("C-hash: its `added` rows are not repeated", len(third["added"]), len(first["added"]))
        # an approval for exactly this summary applies
        ref = "onboarding:t-fill"
        C.record_approval(root, first, ref, "test: the person's yes")
        done = cli(root, "--proposal", root.parent / f"{root.name}-h1-out.json", "--apply", "--approval-ref", ref)
        check("C-hash: --apply --approval-ref on the sealed file passes", done.returncode == 0, done.stderr[-600:])
        written = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        check_eq("C-fresh: the config on disk carries the filled keys", (written["cases_root"], written["budget"]),
                 (TEMPLATE["cases_root"], TEMPLATE["budget"]))
    finally:
        cleanup(root)


def command_final_empty() -> None:
    cmd = {"proposed_config": minimal(), "listing": {"kind": "command", "target": {"profile_id": "x"}}}
    filled = C.fill_proposal(copy.deepcopy(cmd))
    check_eq("C-command: the proposal of one command is not filled (no `added`)", filled.get("added"), None)
    check_eq("C-command: ... and its config is as it was", filled["proposed_config"], minimal())

    root = project("qa-fill-final-")
    try:
        done = cli(root, "--proposal", write(root, "fin", {"proposed_config": minimal()}), "--phase", "final", "--out",
                   root.parent / (root.name + "-fin-out.json"))
        made = json.loads((root.parent / (root.name + "-fin-out.json")).read_text(encoding="utf-8"))
        check("C-final: --phase final runs", done.returncode == 0, done.stderr[-400:])
        check_eq("C-final: nothing is filled", (made.get("added"), "secret_file_patterns" in made["proposed_config"]), (None, False))

        empty = cli(root, "--proposal", write(root, "empty", {"proposed_config": {}}))
        check("C-empty: `proposed_config: {}` is an exit 0 or a named refusal, never a traceback",
              empty.returncode in (0, 1, 2) and "Traceback" not in empty.stderr, empty.stderr[-400:])
        missing = cli(root, "--proposal", write(root, "none", {"input_hash": ""}))
        check_eq("C-empty: no `proposed_config` is the old refusal", missing.returncode != 0 and "no proposed_config" in missing.stderr, True)
        check_not_in("C-empty: ... without a traceback", "Traceback", missing.stderr)
        check_eq("C-empty: fill_proposal of a proposal with no config object changes nothing",
                 C.fill_proposal({"proposed_config": None}), {"proposed_config": None})
    finally:
        cleanup(root)


def table_rows() -> None:
    """The flag is data (AR-1): a table of its own decides which keys are project facts."""
    own = {"keys": {"a": {"project_fact": True}, "b": {}}}
    out = C.fill_proposal({"proposed_config": {}}, template={"a": 1, "b": 2, "c": 3}, keys=own)
    check_eq("a table of its own decides: the flagged key is left, the others filled",
             (out["proposed_config"], [r["path"] for r in out["added"]]), ({"b": 2, "c": 3}, ["/b", "/c"]))


def row_edges() -> None:
    """t-436: what a proposal ALREADY holds is not written twice, and a flag set to false is no flag (own template and own table)."""
    template = {"sizing": {"a": 1}, "b": 2, "c": 3}
    # a conflict the migration plan already put on the proposal for this path is not repeated by the fill
    held = {"path": "/sizing", "current": 7, "question": "the migration plan's own words"}
    out = C.fill_proposal({"proposed_config": {"sizing": 7}, "conflicts": [dict(held)]}, template=template, keys={})
    check_eq("F-5 the conflict row for a path is kept once, in the migration plan's words", out["conflicts"], [held])
    check_eq("F-5 ... the scalar is kept whole", out["proposed_config"]["sizing"], 7)
    again = C.fill_proposal(out, template=template, keys={})
    check_eq("F-5 ... and a second fill of the same proposal does not add it again", again["conflicts"], [held])
    fresh = C.fill_proposal({"proposed_config": {"sizing": 7}}, template=template, keys={})
    check_eq("F-5 ... control: with no row held, the fill writes exactly one, for that path",
             [c["path"] for c in fresh["conflicts"]], ["/sizing"])
    # an `added` row the proposal already holds is not repeated, and the row it holds stays as it is
    row = {"path": "/b", "since": "0.1.0", "absent_means": "default"}
    out = C.fill_proposal({"proposed_config": {"sizing": {"a": 1}}, "added": [dict(row)]}, template=template, keys={})
    check_eq("C-hash (t-436) a row already in `added` is kept as it is and not repeated; the other key gets its row",
             [(r["path"], r.get("since")) for r in out["added"]], [("/b", "0.1.0"), ("/c", "unknown")])
    check_eq("C-hash (t-436) ... both keys are in the config", sorted(out["proposed_config"]), ["b", "c", "sizing"])
    # `project_fact` is a flag when it is true; false is the same as no flag, and only a true one keeps a key out
    table = {"keys": {"a": {"project_fact": False}, "b": {"project_fact": True}, "c": {"project_fact": None}, "d": {}}}
    template = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}
    check_eq("C-facts (t-436) only a key flagged true is a project fact", C._project_facts(template, table), {"b"})
    out = C.fill_proposal({"proposed_config": {}}, template=template, keys=table)
    check_eq("C-facts (t-436) a key flagged false is filled like any default; the true one is left to the person",
             (out["proposed_config"], [r["path"] for r in out["added"]]), ({"a": 1, "c": 3, "d": 4, "e": 5}, ["/a", "/c", "/d", "/e"]))
    check_eq("C-facts (t-436) ... and `not_filled` names only the true one", C.not_filled({}, template=template, keys=table), ["b"])


def readiness(root: Path):
    return run_script("readiness.py", "--require", "config_schema", env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))


def fresh_readiness() -> None:
    """C-fresh, readiness half: after the apply of a minimal proposal the filled key is there, so `config_schema` names only
    the project facts that were not filled (never the guard key the fill wrote)."""
    root = project("qa-fill-ready-")
    try:
        done = cli(root, "--proposal", write(root, "min", {"proposed_config": minimal()}), "--apply")
        check("C-fresh: the apply passes (exit 0)", done.returncode == 0, done.stderr[-400:])
        got = readiness(root)
        check("C-fresh: readiness does not refuse (exit 0)", got.returncode == 0, got.stderr[-400:])
        line = [ln for ln in got.stdout.splitlines() if ln.startswith("WARN config_schema")]
        check_eq("C-fresh: config_schema is one WARN line", len(line), 1)
        text = line[0] if line else ""
        check_in("C-fresh: it is `not_configured` (facts missing), not a refusal", "config_schema: not_configured", text)
        check_in("C-fresh: it names a project fact that was not filled", "protected_app_paths", text)
        check_not_in("C-fresh: ... and not the guard key the fill wrote", "secret_file_patterns", text)
    finally:
        cleanup(root)


def broken() -> None:
    """C-broken: a hostile proposed_config is a listing or a named refusal, never a traceback, under an ascii console."""
    cyr = "".join(chr(c) for c in (0x442, 0x435, 0x441, 0x442))
    deep = "x"
    for _ in range(50):
        deep = {"k": deep}
    root = project("qa-fill-broken-")
    try:
        env = dict(os.environ, PYTHONIOENCODING="ascii")
        for label, config in (("environment: 1", dict(minimal(), environment=1)),
                              ("depth 50", dict(minimal(), sizing=deep, dod=deep)),
                              ("Cyrillic value", dict(minimal(), dod=cyr, tests_root=cyr))):
            done = run_script("onboard_apply.py", "--root", root, "--proposal", write(root, "bad", {"proposed_config": config}),
                              "--listing", env=env)
            check(f"C-broken: {label} - exit 0 or a named refusal, no traceback",
                  done.returncode in (0, 1, 2) and "Traceback" not in done.stderr, done.stderr[-400:])
    finally:
        cleanup(root)


def magnitude() -> None:
    """C-magnitude: a template of 500 keys fills 500 rows and the listing line names every one (no cut, FR-8)."""
    import onboard_apply as OA
    template = {f"key{i}": i for i in range(500)}
    out = C.fill_proposal({"proposed_config": {}}, template=template, keys={})
    check_eq("C-magnitude: 500 keys -> 500 `added` rows", len(out["added"]), 500)
    check_eq("C-magnitude: ... and 500 keys in the config", len(out["proposed_config"]), 500)
    line = [ln for ln in OA._config_lines(out) if "setting(s) this version added" in ln][0]
    check("C-magnitude: the listing names the first and the last, with no cut mark",
          "key0," in line and line.rstrip().endswith("key499") and "more" not in line, line[-120:])
    check_eq("C-magnitude: every name is in the line", sum(f"key{i}" in line for i in range(500)), 500)


def gate() -> None:
    """C-gate: the fill does not mask a bad profile - the profile gate still refuses (exit 1) and names the problem."""
    root = project("qa-fill-gate-")
    try:
        good = cli(root, "--proposal", write(root, "ok", {"proposed_config": minimal()}), "--apply")
        check("C-gate: control - the same proposal without a profile applies", good.returncode == 0, good.stderr[-400:])
    finally:
        cleanup(root)
    root = project("qa-fill-gate2-")
    try:
        bad = dict(minimal(), profiles=[{"profile_id": "p1", "commands": "not-an-object"}])
        done = cli(root, "--proposal", write(root, "bad", {"proposed_config": bad}), "--apply")
        check_eq("C-gate: a bad profile is refused (exit 1)", done.returncode, 1)
        check_in("C-gate: ... by name, with no traceback", "refused", done.stderr)
        check_not_in("C-gate: ... without a traceback", "Traceback", done.stderr)
        check("C-gate: ... and nothing was installed", not (root / "qa-factory" / "config.json").exists())
    finally:
        cleanup(root)


FOREIGN_ROWS = [("conflicts-number", {"conflicts": 5}), ("conflicts-string", {"conflicts": "x"}),
                ("conflicts-strings", {"conflicts": ["x"]}), ("conflicts-object", {"conflicts": {"a": 1}}),
                ("added-number", {"added": 5}), ("added-string", {"added": "x"}), ("added-strings", {"added": ["x"]}),
                ("added-no-path", {"added": [{"since": 1}]}), ("added-path-list", {"added": [{"path": []}]}),
                ("conflicts-zero", {"conflicts": 0}), ("added-false", {"added": False})]


def foreign_rows() -> None:
    """F-4: a foreign `conflicts` / `added` in a proposal is a named refusal (exit 1) from the command line, never a traceback."""
    root = project("qa-fill-foreign-")
    try:
        for label, fields in FOREIGN_ROWS:
            done = cli(root, "--proposal", write(root, "f", dict({"proposed_config": minimal()}, **fields)), "--listing")
            check_eq(f"F-4[{label}]: exit 1", done.returncode, 1)
            check(f"F-4[{label}]: it names the field, no traceback",
                  "Traceback" not in done.stderr and f"`{next(iter(fields))}`" in done.stderr, done.stderr[-300:])
        fine = cli(root, "--proposal", write(root, "g", dict({"proposed_config": minimal()}, conflicts=[], added=None)), "--listing")
        check_eq("F-4: control - `conflicts: []` and `added: null` are fine", fine.returncode, 0)
    finally:
        cleanup(root)


def foreign_capabilities_and_dependencies() -> None:
    """F-2 and F-5: a falsy or foreign `capabilities` reads `unknown`, never `ready`; a foreign `dependency_ids` is a gap, not
    a TypeError (AR-28)."""
    import profile_contract as PC
    root = project("qa-fill-readiness-")
    try:
        def cfg(**fields):
            profile = {"profile_id": "api", "adapter_id": "native", "capabilities": ["web"],
                       "commands": {"one_test": {"kind": "test", "scope": "selected", "argv": [sys.executable, "{selector}"], "cwd": "."}},
                       **fields}
            return {"supported_capabilities": ["web"], "adapter_capabilities": {"native": ["web"]}, "profiles": [profile]}
        check_eq("F-2: control - a complete profile is ready", PC.profile_readiness(cfg(), root=root)["api"]["status"], "ready")
        for label, value in (("empty-object", {}), ("zero", 0), ("empty-string", ""), ("false", False),
                             ("number", 5), ("object", {"a": 1})):
            got = PC.profile_readiness(cfg(capabilities=value), root=root)["api"]
            check_eq(f"F-2[{label}]: not ready", got["status"], "unknown")
        # `[]` and an absent key keep the reading two neighbour tests pin (a profile of commands only is ready); whether an empty
        # declaration should read `unknown` is the Lead's word, queued - this row only holds the reading as it is
        absent_profile = cfg()
        del absent_profile["profiles"][0]["capabilities"]
        check_eq("F-2[absent]: unchanged (ready), queued for the Lead", PC.profile_readiness(absent_profile, root=root)["api"]["status"], "ready")
        check_eq("F-2[empty-list]: unchanged (ready), queued for the Lead", PC.profile_readiness(cfg(capabilities=[]), root=root)["api"]["status"], "ready")
        for label, value in (("number", 5), ("nested-list", [[]]), ("object", {"a": 1}), ("string", "dep")):
            try:
                got = PC.profile_readiness(dict(cfg(dependency_ids=value), managed_dependencies=[]), root=root)["api"]
            except Exception as exc:  # noqa: BLE001 - the key is that nothing is raised
                check(f"F-5[{label}]: does not raise", False, repr(exc))
                continue
            check(f"F-5[{label}]: not ready, and a gap names the dependency", got["status"] != "ready"
                  and any("dependency_id" in g for g in got["gaps"]), str(got))
        for label, deps in (("number", 5), ("with-list", [[], {"dependency_id": []}, {"dependency_id": 5}])):
            try:
                PC.profile_readiness(dict(cfg(dependency_ids=["x"]), managed_dependencies=deps), root=root)
            except Exception as exc:  # noqa: BLE001
                check(f"F-5[managed_dependencies-{label}]: does not raise", False, repr(exc))
                continue
            check(f"F-5[managed_dependencies-{label}]: does not raise", True)
    finally:
        cleanup(root)


fresh_and_listing_and_facts()
keep()
hashed()
command_final_empty()
table_rows()
row_edges()
fresh_readiness()
broken()
magnitude()
gate()
foreign_rows()
foreign_capabilities_and_dependencies()
finish("test_config_fill")
