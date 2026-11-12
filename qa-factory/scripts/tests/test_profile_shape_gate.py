"""OH3-26: the shape of `profiles[]` is a gate of the onboarding (`onboard_apply`).

Finding `20261029-onbording-pishet-profili-ne-toj-formy` N1: a profile of a foreign shape (`commands` a list) went through
the onboarding to `config.json` in silence, and every reader of `commands` then fell over. The gate runs
`profile_contract.validate_config` on the proposal: a NEW problem refuses before anything is sealed, recorded or written;
a problem the project's configuration already holds over the same row is shown and left (a reinstall is never locked).

(`test_profile_gate.py` is another subject - the project with no execution profile at gate A; this file is the shape gate.)

Keys: G-list G-text G-empty G-empty-line G-broken G-magnitude G-encoding G-crash G-headless G-apply G-final G-early
G-inherited G-new G-new-same-line G-command G-shape G-door; OH3-28: T-wiring T-manual.
Run: python -B scripts/tests/test_profile_shape_gate.py
"""
import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import (check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     temp_dir, temp_project, use_project)

use_project(temp_project("qa-shape-gate-audit-"))  # config_contract pulls audit_factory, which reads the hook layer

import config_contract as C  # noqa: E402
import onboard_apply as OA  # noqa: E402
import profile_contract as PC  # noqa: E402
import readiness  # noqa: E402

TEMPLATE = C.canonical_template()
SHAPE = json.loads((Path(__file__).resolve().parents[2] / "references" / "profile-shape.json").read_text(encoding="utf-8"))
# the profile of the report (finding N1): `commands` a list
REPORT = {"profile_id": "x", "commands": [{"kind": "one_test", "argv": ["x"]}]}
# the smallest profile an older test wrote: valid for the readers of a run, invalid for the validator
MINIMAL = {"profile_id": "web", "commands": {"one_test": {"argv": ["npx", "vitest", "run"], "cwd": "."}}}
CYR = "".join(chr(c) for c in (0x41f, 0x440, 0x43e, 0x444, 0x438, 0x43b, 0x44c))   # a profile named in another script


def config(**more) -> dict:
    cfg = copy.deepcopy(TEMPLATE)
    cfg["dod"] = "Done means reviewed and green"
    cfg["app_root"] = "."
    cfg.update(more)
    return cfg


def fresh() -> Path:
    root = temp_dir("qa-shape-gate-")
    (root / ".git").mkdir()
    return root


def installed(profiles, **more) -> Path:
    """A project whose configuration is on disk and holds `profiles`."""
    root = temp_project("qa-shape-gate-disk-")
    (root / "qa-factory" / "config.json").write_text(json.dumps(config(profiles=profiles, **more), indent=2), encoding="utf-8")
    return root


def proposal_file(root: Path, cfg: dict) -> Path:
    path = root.parent / (root.name + "-proposal.json")
    path.write_text(json.dumps({"proposed_config": cfg}), encoding="utf-8")
    return path


def files(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.stat().st_size for p in sorted(root.rglob("*")) if p.is_file()}


def run(root: Path, *args, env: dict | None = None):
    return run_script("onboard_apply.py", "--root", root, *args, cwd=root, env=dict(os.environ, **(env or {})))


def bullets(stderr: str) -> list:
    return [line for line in stderr.splitlines() if line.startswith("  - ")]


def g_list_and_text() -> None:
    root = fresh()
    try:
        before = files(root)
        out = root.parent / (root.name + "-sealed.json")
        found = run(root, "--proposal", proposal_file(root, config(profiles=[REPORT])), "--out", out)
        check_eq("G-list: a profile whose commands is a list refuses: exit 1", found.returncode, 1)
        check_in("G-list: stderr names the path", "profiles[0].commands", found.stderr)
        check_in("G-list: and the refusal prefix", "onboard_apply: refused:", found.stderr)
        check_eq("G-list: stdout is empty (FR-14)", found.stdout, "")
        check_eq("G-list: the project is as it was", files(root), before)
        check("G-list: and no sealed file was made", not out.exists())
        check_in("G-text (FR-1): the expected shape is said", "`commands` is an object keyed by command name", found.stderr)
        check_in("G-text (FR-15): the sample is named by its absolute path", str(OA.PROFILE_SHAPE), found.stderr)
        check("G-text: that file exists", OA.PROFILE_SHAPE.is_file())
        check_in("G-text (FR-2): the door of a deferral", "`profiles: []`", found.stderr)
        check_in("G-text: and the command that records it", "project_decisions.py add --field-ref /profiles", found.stderr)
    finally:
        cleanup(root)
    # lines: at 1, at 0 (G-empty below), and at 60 and beyond - every line is printed, none is cut
    for label, profiles in (("one", [dict(SHAPE["profile"], revision="")]),
                            ("sixty and more", [dict(REPORT, profile_id=f"p{i}", selector=1, roots=[]) for i in range(4)])):
        root = fresh()
        try:
            cfg = config(profiles=profiles)
            expected = PC.validate_config(cfg)
            found = run(root, "--proposal", proposal_file(root, cfg))
            check_eq(f"G-text: {label}: one stderr line per error of the validator", len(bullets(found.stderr)), len(expected))
            check(f"G-text: {label}: the count is what the case means", len(expected) == 1 if label == "one" else len(expected) >= 4, str(len(expected)))
        finally:
            cleanup(root)
    root = fresh()
    try:
        big = [dict(REPORT, profile_id=f"p{i}", roots=[], revision=1, capabilities="x", quality_gates=[1], extensions=[],
                    execution_prerequisites=[], selectors=[], reporter=[]) for i in range(200)]
        cfg = config(profiles=big)
        expected = PC.validate_config(cfg)
        found = run(root, "--proposal", proposal_file(root, cfg))
        check("G-magnitude: 200 bad profiles are 60+ errors", len(expected) >= 60, str(len(expected)))
        check_eq("G-magnitude: exit 1 and every line printed (no cut at 20, none at 60)", (found.returncode, len(bullets(found.stderr))),
                 (1, len(expected)))
    finally:
        cleanup(root)


def g_empty() -> None:
    for label, profiles in (("an empty list", []), ("null", None), ("no key", "absent")):
        root = fresh()
        try:
            cfg = config()
            if profiles == "absent":
                cfg.pop("profiles", None)
            else:
                cfg["profiles"] = profiles
            found = run(root, "--proposal", proposal_file(root, cfg))
            check_eq(f"G-empty: {label}: the plan goes through", found.returncode, 0)
            check_eq(f"G-empty: {label}: and blocks nothing", json.loads(found.stdout)["blocked"], None)
        finally:
            cleanup(root)
    root = fresh()
    try:
        text = run(root, "--proposal", proposal_file(root, config(profiles=[])), "--listing")
        check_in("G-empty-line: an empty profiles list is said in the summary", "No test profile will be written", text.stdout)
        check_not_in("G-empty-line: nothing is removed on a fresh project", "will be removed", text.stdout)
    finally:
        cleanup(root)
    root = installed([MINIMAL])
    try:
        text = run(root, "--proposal", proposal_file(root, config(profiles=[])), "--listing")
        check_eq("G-empty-line: the plan goes through", text.returncode, 0)
        check_in("G-empty-line: profiles on disk that the proposal drops are named", "These test profiles will be removed: web.", text.stdout)
        check_in("G-empty-line: and the empty list is said too", "No test profile will be written", text.stdout)
    finally:
        cleanup(root)
    root = fresh()
    try:
        text = run(root, "--proposal", proposal_file(root, config(profiles=[SHAPE["profile"]])), "--listing")
        check_not_in("G-empty-line control: a proposal WITH a profile does not say it", "No test profile will be written", text.stdout)
    finally:
        cleanup(root)


def g_broken() -> None:
    nested = json.loads("[" * 50 + "]" * 50)
    for label, profiles in (("a string", "x"), ("a number in the list", [1]), ("an empty object row", [{}]), ("an object", {}),
                            ("commands nested 50 deep", [dict(REPORT, commands=nested)])):
        root = fresh()
        try:
            found = run(root, "--proposal", proposal_file(root, config(profiles=profiles)))
            check_eq(f"G-broken: {label}: refused, exit 1", found.returncode, 1)
            check_not_in(f"G-broken: {label}: no traceback", "Traceback", found.stderr)
            check_in(f"G-broken: {label}: a problem is named", "problem(s) in the profiles", found.stderr)
        finally:
            cleanup(root)


def g_encoding() -> None:
    ascii_env = {"PYTHONIOENCODING": "ascii"}
    root = fresh()
    try:
        found = run(root, "--proposal", proposal_file(root, config(profiles=[dict(REPORT, profile_id=CYR)])), env=ascii_env)
        check_eq("G-encoding: a profile named in another script, console ascii: refused, exit 1", found.returncode, 1)
        check_not_in("G-encoding: no traceback", "Traceback", found.stderr)
    finally:
        cleanup(root)
    twin = dict(MINIMAL, profile_id=CYR)
    root = installed([twin, copy.deepcopy(twin)])      # a duplicate id is a line that carries the name
    try:
        found = run(root, "--listing", env=ascii_env)
        check_eq("G-encoding: an inherited line with the name, console ascii: the listing is shown, exit 0", found.returncode, 0)
        check("G-encoding: and the name is shown, raw (a stream a dependency put on UTF-8) or as an escape",
              CYR in found.stdout or "\\u041f" in found.stdout, found.stdout[-200:])
        check_not_in("G-encoding: no traceback", "Traceback", found.stderr)
    finally:
        cleanup(root)
    import io
    held = sys.stdout
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    try:
        shown = OA._printable("a " + CYR)
    finally:
        sys.stdout = held
    check_eq("G-encoding: on a console that cannot show it, the listing writes the name as an escape", shown, "a \\u041f\\u0440\\u043e\\u0444\\u0438\\u043b\\u044c")


def g_crash() -> None:
    held = OA.PC.validate_config

    def boom(_cfg):
        raise RuntimeError("the validator itself fell over")
    root = fresh()
    try:
        OA.PC.validate_config = boom
        found = OA._profile_problems(None, {})
        check_eq("G-crash: a validator that raises is one `new` line, never a pass", (len(found["new"]), found["inherited"]), (1, []))
        check_in("G-crash: it says it could not be checked, with the type", "RuntimeError", found["new"][0])
        made = OA.plan(root, {"proposed_config": config(profiles=[])}, context={"package_fingerprint": "f"}, date="2026-10-01")
        check_eq("G-crash: and the plan is blocked", (made["blocked"] or {}).get("reason"), "profile_shape")
    finally:
        OA.PC.validate_config = held
        cleanup(root)


def g_headless_apply_and_phases() -> None:
    root = fresh()
    try:
        found = run(root, "--proposal", proposal_file(root, config(profiles=[REPORT])), "--apply")
        check_eq("G-headless: --apply with no ref on a foreign shape: exit 1", found.returncode, 1)
        check("G-headless: no approval line, no configuration",
              not (root / OA.APPROVALS_REL).exists() and not (root / OA.CONFIG_REL).exists())
        early = run(root, "--proposal", proposal_file(root, config(profiles=[REPORT])), "--phase", "early")
        final = run(root, "--proposal", proposal_file(root, config(profiles=[REPORT])), "--phase", "final")
        check_eq("G-early: the first half refuses the same proposal", early.returncode, 1)
        check_eq("G-final: the second half writes no configuration and has no gate", (final.returncode, json.loads(final.stdout)["blocked"]),
                 (0, None))
        check_eq("G-final: in-process too (check_input False)", OA.plan(root, {"proposed_config": config(profiles=[REPORT])},
                 context={"package_fingerprint": "f"}, check_input=False)["profile_problems"], {"new": [], "inherited": [], "removed": []})
    finally:
        cleanup(root)
    root = fresh()
    try:
        before = files(root)
        for plan_ in ({"blocked": {"reason": "profile_shape", "message": "a problem"}, "nothing_to_do": False, "proposal": {}},
                      {"blocked": {"reason": "profile_shape", "message": "a problem"}, "nothing_to_do": True}):
            try:
                OA.apply(root, plan_, "ref")
                raised = ""
            except OA.ApplyRefused as exc:
                raised = str(exc)
            check_eq("G-apply: a library call round main does not go round the gate (nothing_to_do " + str(plan_["nothing_to_do"]) + ")",
                     raised, "a problem")
        check_eq("G-apply: nothing was written", files(root), before)
    finally:
        cleanup(root)


def g_inherited_and_new() -> None:
    root = installed([MINIMAL])
    try:
        before = files(root)
        found = run(root)            # the migration plan: the profile row is not changed by it
        made = json.loads(found.stdout)
        check_eq("G-inherited: a reinstall of a project with a minimal profile goes through", found.returncode, 0)
        check("G-inherited: its problems are inherited, none is new", bool(made["profile_problems"]["inherited"]) and made["profile_problems"]["new"] == [],
              str(made["profile_problems"]))
        check_eq("G-inherited: and nothing blocks", made["blocked"], None)
        listing = run(root, "--listing")
        check_in("G-inherited: the listing shows the group", "Your configuration already has these problems in `profiles`", listing.stdout)
        check_in("G-inherited: with every line", "profiles[0].roots.test", listing.stdout)
        check_not_in("G-inherited (FR-6): and no script name in the group", ".py", listing.stdout.split("Your configuration already has")[1].split("\n\n")[0])
        check_eq("G-inherited: the plan wrote nothing", files(root), before)
        # G-new: the proposal ADDS a bad profile next to the inherited one
        bad = proposal_file(root, config(profiles=[MINIMAL, REPORT]))
        refused = run(root, "--proposal", bad)
        check_eq("G-new: a new bad profile refuses", refused.returncode, 1)
        check_in("G-new: the new row is named", "profiles[1].commands", refused.stderr)
        check_not_in("G-new: the inherited rows are not in the refusal", "profiles[0]", refused.stderr)
    finally:
        cleanup(root)
    # the same line over ANOTHER row: the carrier changed, so it is new (critic F1)
    root = installed([{"profile_id": "a", "commands": {}}])
    try:
        replaced = run(root, "--proposal", proposal_file(root, config(profiles=[{"profile_id": "b", "commands": [{"kind": "test"}]}])))
        check_eq("G-new-same-line: another profile at the same index with the same words is NEW: refused", replaced.returncode, 1)
        check_in("G-new-same-line: the shared line is in the refusal", "profiles[0].commands: must contain named commands", replaced.stderr)
        same = run(root, "--proposal", proposal_file(root, config(profiles=[{"profile_id": "a", "commands": {}}])))
        check_eq("G-new-same-line control: the very same row is inherited and goes through", same.returncode, 0)
    finally:
        cleanup(root)
    # a row moved to another index is read as new (the error direction is the refusal)
    both = OA._profile_problems({"profiles": [MINIMAL, SHAPE["profile"]]}, {"profiles": [SHAPE["profile"], MINIMAL]})
    check_eq("G-new: a row moved to another index is new", (bool(both["new"]), both["inherited"]), (True, []))
    fresh_all = OA._profile_problems(None, {"profiles": [MINIMAL]})
    check_eq("G-new: with no configuration on disk everything is new", (bool(fresh_all["new"]), fresh_all["inherited"]), (True, []))
    # a line about ANOTHER row's fact (a duplicate id, an unknown profile) is inherited only while the profiles are all equal
    # (t-424, S2a-F5: the cross-row clause of `_carrier_same` had no key that differs only by it). The row the line names
    # is equal on both sides in each case below; only the profiles array around it differs.
    twin = dict(MINIMAL)
    dup_line = "profiles[1].profile_id: duplicate 'web'"
    cur_dup = {"profiles": [MINIMAL, twin]}
    held = OA._profile_problems(cur_dup, {"profiles": [MINIMAL, twin]})
    check_eq("G-cross-row control: the same two rows on both sides: the duplicate line is inherited",
             (dup_line in held["inherited"], dup_line in held["new"]), (True, False))
    grown = OA._profile_problems(cur_dup, {"profiles": [MINIMAL, twin, dict(MINIMAL, profile_id="other")]})
    check_eq("G-cross-row: a duplicate id, the row itself equal but a profile added next to it: the line is new",
             (dup_line in grown["inherited"], dup_line in grown["new"]), (False, True))
    repo = {"execution_profile_id": "gone", "repo_id": "r"}
    repo_line = "implementation_repos[0].execution_profile_id: unknown profile 'gone'"
    cur_repo = {"profiles": [MINIMAL], "implementation_repos": [repo]}
    held = OA._profile_problems(cur_repo, {"profiles": [MINIMAL], "implementation_repos": [repo]})
    check_eq("G-cross-row control: an unknown profile, nothing changed: the line is inherited",
             (repo_line in held["inherited"], repo_line in held["new"]), (True, False))
    grown = OA._profile_problems(cur_repo, {"profiles": [MINIMAL, dict(MINIMAL, profile_id="other")], "implementation_repos": [repo]})
    check_eq("G-cross-row: an unknown profile, the repo row equal but the profiles changed: the line is new",
             (repo_line in grown["inherited"], repo_line in grown["new"]), (False, True))


def g_command() -> None:
    root = installed([MINIMAL])
    try:
        question = "I propose to run the web tests as: `npx vitest run --reporter=junit`. Do it? yes / no"
        sealed = C.command_proposal(root, {"profile_id": "web"}, ["npx", "vitest", "run", "--reporter=junit"], question=question)
        path = proposal_file(root, {})
        path.write_text(json.dumps(sealed), encoding="utf-8")
        applied = run(root, "--proposal", path, "--apply")
        check_eq("G-command: --apply of a one-command proposal is refused the old way (the gate did not step in)", applied.returncode, 1)
        check_in("G-command: with the old words", "one approval changes one key", applied.stderr)
        bare = run(root, "--proposal", path)
        check_eq("G-command: a BARE plan of the sealed one-command proposal is refused by the gate (the row changed); no caller does this",
                 (bare.returncode, "problem(s) in the profiles" in bare.stderr), (1, True))
    finally:
        cleanup(root)


def g_shape_and_door() -> None:
    profile = SHAPE["profile"]
    full = {"profiles": [profile], "implementation_repos": [SHAPE["implementation_repo"]], "managed_dependencies": [SHAPE["managed_dependency"]]}
    check_eq("G-shape: the sample is valid, with the repository row and the dependency row", PC.validate_config(full), [])
    check_eq("G-shape (AR-22): and the readers of a run read it as runnable", readiness.check_execution_profile({"profiles": [profile]})["status"],
             readiness.OK)
    broken = copy.deepcopy(profile)
    del broken["commands"]["one_test"]["kind"]
    check("G-shape control: a sample without `kind` is not valid", bool(PC.validate_config({"profiles": [broken]})))
    # G-door: a bad profile with a repository row refuses; the proposal rewritten by the door's words goes through; the deferral records
    root = fresh()
    try:
        bad = config(profiles=[REPORT], implementation_repos=[dict(SHAPE["implementation_repo"], execution_profile_id="x")])
        refused = run(root, "--proposal", proposal_file(root, bad))
        check_eq("G-door: the bad profile with a repository row refuses", refused.returncode, 1)
        door = config(profiles=[], implementation_repos=[])
        opened = run(root, "--proposal", proposal_file(root, door), "--apply", "--no-probe")
        check_eq("G-door: the same proposal rewritten by the door's words is applied", opened.returncode, 0)
        recorded = run_script("project_decisions.py", "--root", root, "add", "--field-ref", "/profiles", "--essence", "profiles can wait",
                              "--asked", "when do you name the test command?", "--scope", "project", "--owner", "user",
                              "--trigger-type", "manual", "--trigger-value", "first story", cwd=root,
                              env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))
        check_eq("G-door: the deferral is recorded by the command the refusal names", recorded.returncode, 0)
    finally:
        cleanup(root)


def t_wiring() -> None:
    """OH3-28 (finding N3): the shape reaches whoever builds `proposal.json` BEFORE the work (AR-10, AR-8); the phase texts are rows of
    design/role-rules.json, the config note is checked here."""
    pkg = Path(__file__).resolve().parents[2]
    note = json.loads((pkg / "references" / "templates" / "config.json").read_text(encoding="utf-8"))["profiles_note"]
    check("T-wiring: the profiles_note says the object keyed by command name", "keyed by command name" in note and "selector/" not in note)
    check("T-wiring: the note names the sample too", "references/profile-shape.json" in note)
    old_note = json.loads((pkg / "references" / "config-keys.json").read_text(encoding="utf-8"))["notes"]["profiles_note"]["note_history"][-2]
    check("T-wiring control: the previous note text (`selector/`, no object) fails the same check",
          not ("keyed by command name" in old_note and "selector/" not in old_note))


if __name__ == "__main__":
    t_wiring()
    g_list_and_text()
    g_empty()
    g_broken()
    g_encoding()
    g_crash()
    g_headless_apply_and_phases()
    g_inherited_and_new()
    g_command()
    g_shape_and_door()
    finish("test_profile_shape_gate")
