"""Two execution profiles over one test root never resolve to the first of them in silence (EP1-10).

An api and a ui profile both rooted at `tests/`: `_profile_for` let the first profile win every tie, so a ui row
whose manifest entry named no profile ran under the api command, and the gate-A reporter rehearsal proved the ui
profile with the first test under the shared root - an api test. Now the run is refused naming both profiles and
the door, a row that names its profile still runs, distinct roots still resolve by path, and the rehearsal picks no
test by path for a profile whose root another profile shares but says so and leaves the card.

The critic's amendments (HF1-0, C1-C4) are keys here too: rows that name two profiles get the "different profiles"
refusal; an unnamed row beside a named one under a shared root is refused, not run under the named profile; ONE
predicate (`profiles_owning`) reads `tests` and `./tests` as one root for the selector, the probe's cwd and the
rehearsal; probe_by_code's refusal names no `--profile` (it has none); `profile_id` written through
`manifest_put.py --fragment` reaches the selector; the onboarding text asks for distinct roots and one `-v`.

HF2-8 (EP1-16): the profile a manifest row names reaches the request builder from the mutation probe
(`build_request` -> `build_mine_request(profile_id=, profile_door=False)`), a profile the config does not hold is
refused naming the ids it holds - by the selector and by the probe's cwd, from ONE predicate (`known_profile`) - and an
explicit profile wins over a row's with a note.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (check,check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_project, use_project)

import execution_request as er  # noqa: E402
import onboarding_probe  # noqa: E402
import probe_by_code as pbc  # noqa: E402
import test_reporter_rehearsal as rehearsal_fixture  # noqa: E402


def profile_for(cfg, files, entries, **kwargs):
    try:
        return er._profile_for(cfg, files, "", entries, [], ["TC-1"], **kwargs), ""
    except er.MineRefusal as exc:
        return None, str(exc)


def two(api_root="tests", ui_root="tests", **ui_extra):
    return {"profiles": [{"profile_id": "api", "roots": {"test": api_root},
                          "commands": {"one_test": {"argv": ["pytest"], "cwd": "api-dir"}}},
                         {"profile_id": "ui", "roots": {"test": ui_root},
                          "commands": {"one_test": {"argv": ["pytest"], "cwd": "ui-dir"}}, **ui_extra}]}


def selector() -> None:
    shared = two()
    picked, why = profile_for(shared, ["tests/ui/test_login.py"], [{}])
    check_eq("a row under a root two profiles share is refused, not run under the first profile", picked, None)
    check_in("the refusal names both profiles", "profiles api, ui share the test root `tests`", why)
    check_in("and the door", "`profile_id`", why)
    check_in("and the other door, which run_suite --mine accepts", "--profile ID", why)
    picked, why = profile_for(shared, ["tests/ui/test_login.py"], [{"profile_id": "ui"}])
    check_eq("a row that names its profile runs under it", (picked, why), ("ui", ""))
    distinct = two("tests/api", "tests/ui")
    check_eq("distinct roots still resolve by path", profile_for(distinct, ["tests/ui/test_login.py"], [{}]), ("ui", ""))
    nested = {"profiles": [{"profile_id": "all", "roots": {"test": "tests"}},
                           {"profile_id": "ui", "roots": {"test": "tests/ui"}}]}
    check_eq("the longer root still wins over a shorter one", profile_for(nested, ["tests/ui/test_a.py"], [{}]), ("ui", ""))
    check_eq("and the shorter root takes what the longer one does not cover",
             profile_for(nested, ["tests/api/test_a.py"], [{}]), ("all", ""))
    deselected = two(selected=False)
    check_eq("a profile that is not selected shares nothing", profile_for(deselected, ["tests/test_a.py"], [{}]), ("api", ""))


def profile_named(cfg, files, wanted, entries, **kwargs):
    notes = kwargs.setdefault("notes", [])
    try:
        return er._profile_for(cfg, files, wanted, entries, [], ["TC-1"], **kwargs), "", notes
    except er.MineRefusal as exc:
        return None, str(exc), notes


def a_name_the_config_does_not_hold() -> None:
    """A-K6, A-E3, A-E4, A-E5, A-E6: a name is checked against the config's profiles (all of them), refused in the
    caller's own words, and never turned into a path pick or a first-profile pick."""
    shared = two()
    # A-K6: the flag (a caller with the `--profile` door) and the row (a caller without it)
    picked, why, _n = profile_named(shared, ["tests/t.py"], "ghost", [{}])
    check_eq("a profile config does not hold is refused naming the ids it holds (the flag)", picked, None)
    check_in("...it names the flag that carried the name", "--profile names the execution profile `ghost`", why)
    check_in("...the ids the config holds", "(profile_id there: api, ui)", why)
    check_in("...and the door the flag has", "pass one of them with --profile ID", why)
    check_not_in("...it is no gap of the onboarding", "gap of the onboarding", why)
    picked, why, _n = profile_named(shared, ["tests/t.py"], "ghost", [{}], profile_door=False)
    check_in("the same name from a caller with no flag is the manifest row's", "the manifest row names the execution profile `ghost`", why)
    check_in("...with the row door", "`profile_id` on the manifest row", why)
    check_not_in("...and no --profile", "--profile", why)
    picked, why, _n = profile_named(shared, ["tests/ui/t.py"], "", [{"profile_id": "ghost"}], profile_door=False)
    check_eq("a row that names a profile the config does not hold is refused, not run by its path", picked, None)
    check_in("...naming the row and the ids", "the manifest row names the execution profile `ghost`", why)
    check_in("...and the known ids", "api, ui", why)
    picked, why, _n = profile_named(two("tests/api", "tests/ui"), ["tests/ui/t.py"], "", [{"profile_id": "ghost"}],
                                    profile_door=False)
    check_eq("...also over distinct roots, where the path WOULD have said `ui` (never a silent fallback by path)",
             (picked, "`ghost`" in why), (None, True))
    picked, why, _n = profile_named({"profiles": []}, ["tests/t.py"], "api", [{}])
    check_in("a config with no profiles says so", "profile_id there: none", why)
    # A-E3: empty and null are absent
    for label, value in (("an empty string", ""), ("null", None)):
        picked, why, _n = profile_named(shared, ["tests/t.py"], "", [{"profile_id": value}])
        check_eq(f"{label} is no name: the shared root is refused as for an unnamed row", (picked, "share the test root" in why),
                 (None, True))
    check_eq("`known_profile('')` is False", er.known_profile(shared, ""), False)
    # A-E5: a profile that sits out is still a profile a caller can name
    out = two(selected=False)
    check_eq("a profile with `selected: false`, named outright, runs (the name is not cancelled in silence)",
             profile_named(out, ["tests/t.py"], "ui", [{}])[:2], ("ui", ""))
    check_eq("...and a row may name it", profile_named(out, ["tests/t.py"], "", [{"profile_id": "ui"}])[:2], ("ui", ""))
    # A-E6: the explicit name wins over the row's, and the note says so
    picked, why, notes = profile_named(shared, ["tests/t.py"], "api", [{"profile_id": "ui"}], profile_door=False)
    check_eq("an explicit profile against another profile in the row: the explicit one runs", (picked, why), ("api", ""))
    check_in("...with a note that names both", "the profile `api` (named by the caller) runs; the manifest names `ui`",
             " ".join(notes))
    picked, why, notes = profile_named(shared, ["tests/t.py"], "ui", [{"profile_id": "ui"}])
    check_eq("an explicit profile that agrees with the row: no note", (picked, notes), ("ui", []))
    # A-E4, the probe's cwd: the same predicate, the same words
    for cfg in (two(), two("tests/api", "tests/ui")):
        try:
            got = pbc._profile_cwd(cfg, "tests/ui/t.py", "ghost")
            text = ""
        except pbc.Refusal as exc:
            got, text = None, str(exc)
        check_eq("_profile_cwd: a profile the config does not hold is refused, not read as the path's owner",
                 got, None)
        check_in("...naming the row and the ids the config holds",
                 "the manifest row names the execution profile `ghost`, which qa-factory/config.json does not hold "
                 "(profile_id there: api, ui)", text)
        check_in("...in probe_by_code's closing words", ". Nothing was changed.", text)
        check_not_in("...with no --profile", "--profile", text)
    check_eq("_profile_cwd: a known profile still settles the path-owned directory",
             pbc._profile_cwd(two("tests/api", "tests/ui"), "tests/ui/t.py", "api"), "api-dir")


def named_rows() -> None:
    """C1: the door this fix introduces (`profile_id` on the row), used partially or twice, must not bring the class back."""
    shared = two()
    # probe input 1: rows naming api AND ui
    picked, why = profile_for(shared, ["tests/api/test_a.py", "tests/ui/test_b.py"],
                              [{"profile_id": "api", "file": "tests/api/test_a.py"},
                               {"profile_id": "ui", "file": "tests/ui/test_b.py"}])
    check_eq("rows naming two profiles are refused", picked, None)
    check_in("with the 'different profiles' refusal (api, ui)", "run under different profiles (api, ui)", why)
    check_in("and its door: one --mine per profile", "one `--mine` per profile", why)
    check_not_in("not told to name what they already named", "share the test root", why)
    distinct = two("tests/api", "tests/ui")
    picked, why = profile_for(distinct, ["tests/api/test_a.py", "tests/ui/test_b.py"],
                              [{"profile_id": "api"}, {"profile_id": "ui"}])
    check_in("two named profiles are refused over distinct roots too (the names, not the paths, disagree)",
             "run under different profiles", why)
    # probe input 2: ui row named, api row unnamed, one shared root
    picked, why = profile_for(shared, ["tests/api/test_a.py", "tests/ui/test_b.py"],
                              [{"profile_id": "ui", "file": "tests/ui/test_b.py", "instance_id": "test_b"},
                               {"file": "tests/api/test_a.py", "instance_id": "test_a"}])
    check_eq("an unnamed row beside a named one under a shared root is not run under the named profile", picked, None)
    check_in("the refusal names that row", "test_a", why)
    check_in("and its file", "tests/api/test_a.py", why)
    check_in("and says it names no profile", "names no profile", why)
    check_in("and the profiles that share the root", "profiles api, ui share", why)
    check_in("and the door", "(`profile_id`)", why)
    picked, why = profile_for(shared, ["tests/api/test_a.py"],
                              [{"profile_id": "ui"}, {"file": "tests/api/test_a.py"}], profile_door=False)
    check_not_in("a caller with no --profile is not offered it, in the partial-naming refusal", "--profile", why)
    check_eq("every row naming the same profile runs under it",
             profile_for(shared, ["tests/api/test_a.py", "tests/ui/test_b.py"],
                         [{"profile_id": "ui"}, {"profile": "ui"}]), ("ui", ""))
    check_eq("an unnamed row under a root only the named profile owns is the named profile's",
             profile_for(distinct, ["tests/ui/test_b.py", "tests/ui/test_c.py"],
                         [{"profile_id": "ui"}, {"file": "tests/ui/test_c.py"}]), ("ui", ""))


def one_predicate() -> None:
    """C2: `tests`, `./tests/`, `tests\\` and (Windows) `Tests` are one root for every reader."""
    for label, other in (("./tests", "./tests"), ("a trailing slash", "tests/"), ("a backslash", "tests\\"),
                         ("a doubled slash", "tests//"), ("a parent hop", "tests/ui/..")):
        cfg = two("tests", other)
        check_eq(f"profiles_owning: `tests` and `{other}` ({label}) are one root", er.profiles_owning(cfg, "tests/ui/t.py"),
                 ["api", "ui"])
        picked, why = profile_for(cfg, ["tests/ui/t.py"], [{}])
        check_eq(f"_profile_for refuses `tests` vs `{other}` ({label})", (picked, "share the test root" in why), (None, True))
    folded = er.profiles_owning(two("tests", "Tests"), "tests/t.py")
    check_eq("`Tests` vs `tests`: one root on Windows (case-folded), two on a case-sensitive file system",
             folded, ["api", "ui"] if os.name == "nt" else ["api"])
    check_eq("a path outside every root is owned by nobody", er.profiles_owning(two("tests/api", "tests/ui"), "src/x.py"), [])
    check_eq("an empty path is owned by nobody", er.profiles_owning(two(), ""), [])
    check_eq("a profile with no root owns nothing", er.profiles_owning({"profiles": [{"profile_id": "a"}]}, "tests/t.py"), [])
    # the probe's cwd reads the same predicate
    check_eq("_profile_cwd: on a shared root with different cwds the first profile's directory is NOT returned",
             _cwd_or_refusal(two(), "tests/ui/t.py"), "REFUSED")
    refused = _cwd_or_refusal(two(), "tests/ui/t.py", text=True)
    check_in("and the refusal names both profiles", "profiles api, ui share the test root", refused)
    check_in("and the manifest-row door", "`profile_id`", refused)
    check_not_in("and no --profile", "--profile", refused)
    check_eq("_profile_cwd: `./tests` vs `tests` is the same tie", _cwd_or_refusal(two("tests", "./tests"), "tests/t.py"), "REFUSED")
    check_eq("_profile_cwd: the profile the row names settles the shared root",
             pbc._profile_cwd(two(), "tests/t.py", "ui"), "ui-dir")
    same_cwd = two()
    same_cwd["profiles"][1]["commands"]["one_test"]["cwd"] = "api-dir"
    check_eq("_profile_cwd: profiles sharing a root AND a cwd give that cwd (no guess is made)",
             pbc._profile_cwd(same_cwd, "tests/t.py"), "api-dir")
    check_eq("_profile_cwd: distinct roots give the owner's cwd",
             pbc._profile_cwd(two("tests/api", "tests/ui"), "tests/ui/t.py"), "ui-dir")
    check_eq("_profile_cwd: a file no profile owns runs in '.'", pbc._profile_cwd(two("tests/api", "tests/ui"), "src/x.py"), ".")
    # `_test_path` is where `probe` meets it: the instance's manifest row carries the profile it names
    root = temp_project("qa-profile-cwd-")
    try:
        (root / "tests" / "t.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
        spec = {"file": "tests/t.py"}
        check_eq("_test_path: the manifest row's profile settles the shared root (its cwd)",
                 pbc._test_path(root, two(), spec, {"profile_id": "ui"})[1], (root / "ui-dir").resolve())
        try:
            pbc._test_path(root, two(), spec, {})
            outcome = "no refusal"
        except pbc.Refusal as exc:
            outcome = str(exc)
        check_in("_test_path: a row that names none is refused at the shared root", "share the test root of tests/t.py", outcome)
    finally:
        cleanup(root)


def _cwd_or_refusal(cfg, file, text=False):
    try:
        return pbc._profile_cwd(cfg, file)
    except pbc.Refusal as exc:
        return str(exc) if text else "REFUSED"


def probe_door() -> None:
    """C3 (FR-2): probe_by_code has no `--profile`; its refusal names the manifest-row door only."""
    rows = [{"node": "tests/ui/test_login.py::test_login", "entry": {}}]
    try:
        pbc._profile_of(two(), rows, "TC-1")
        text = ""
    except pbc.Refusal as exc:
        text = str(exc)
    check_in("probe_by_code: a shared root is refused", "profiles api, ui share the test root `tests`", text)
    check_in("naming the manifest-row door", "`profile_id`", text)
    check_not_in("and NOT --profile, which this tool does not accept", "--profile", text)
    check_in("with a full stop before the closing sentence", ". Nothing was changed.", text)
    check_not_in("and no doubled stop", "..", text)
    try:
        pbc._profile_of({"profiles": [{"profile_id": "a", "roots": {"test": "x"}},
                                      {"profile_id": "b", "roots": {"test": "y"}}]}, rows, "TC-1")
        text = ""
    except pbc.Refusal as exc:
        text = str(exc)
    check_in("the 'cannot tell' refusal of the same selector names the same door", "`profile_id` on the manifest row", text)
    check_not_in("and no --profile there either", "--profile", text)
    refused_for_run_suite = profile_for({"profiles": [{"profile_id": "a", "roots": {"test": "x"}},
                                                      {"profile_id": "b", "roots": {"test": "y"}}]}, ["z/t.py"], [{}])[1]
    check_in("run_suite --mine still gets --profile ID for it", "--profile ID", refused_for_run_suite)


def manifest_door() -> None:
    """C4: `profile_id` written through `manifest_put.py --fragment` is kept on the row and reaches the selector."""
    root = temp_project("qa-profile-door-")
    try:
        task = root / "qa-factory" / "artifacts" / "QA-1"
        task.mkdir(parents=True)
        fragment = root / "fragment.json"
        fragment.write_text(json.dumps({"tests": [
            {"case": "TC-1", "file": "tests/ui/test_login.py", "test_function": "test_login", "profile_id": "ui"}]}),
            encoding="utf-8")
        result = run_script("manifest_put.py", "--task", "QA-1", "--fragment", str(fragment), cwd=root,
                            env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
        check_eq("manifest_put takes a row that names its profile", result.returncode, 0)
        manifest = json.loads((task / "work" / "automation-manifest.json").read_text(encoding="utf-8"))
        rows, _files = er.manifest_rows(manifest, "TC-1")
        check_eq("the written row still names its profile", [r["entry"].get("profile_id") for r in rows], ["ui"])
        check_eq("and the selector takes it: the shared root is settled by the row",
                 profile_for(two(), ["tests/ui/test_login.py"], [r["entry"] for r in rows]), ("ui", ""))
    finally:
        cleanup(root)


def rehearsal() -> None:
    for shared_spelling in ("tests", "./tests", "tests/"):
        root = rehearsal_fixture.project("qa-shared-root-")
        try:
            cfg_path = root / "qa-factory" / "config.json"
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            web = cfg["profiles"][0]
            web["roots"] = {"test": "tests"}
            cfg["profiles"] = [web, {**json.loads(json.dumps(web)), "profile_id": "ui", "capabilities": ["web"],
                                     "roots": {"test": shared_spelling}}]
            cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
            use_project(root)
            r = rehearsal_fixture.rehearse(root)
            # the plan's one row needs `web` (capability api), so `web` is the profile rehearsed; `ui` is the one it shares with
            notes = " ".join(str(i.get("message") or "") for i in r.info)
            check_in(f"the rehearsal says the profile shares its root, and with whom (`ui` rooted at `{shared_spelling}`)",
                     "`web`: shares its test root `tests` with `ui`", notes)
            check_in("and names the one door", "gate_rehearsal.reporter_probe_test", notes)
            check("no profile is proven by the first test under the shared root",
                  "tests/test_a_first.py" not in notes, notes)
            cards = " ".join(str(f.get("message") or "") for f in r.findings)
            check_in("the card that asks the person stands, for `web`", "so I cannot tell which existing test belongs to `web`, and none was run to prove its report", cards)
            check("nothing was proven in silence", r.findings != [], "no card")
            tests_dir = r._profile_tests_dir(web, root)
            check_eq("_profiles_sharing_root: the other profile that owns the directory",
                     r._profiles_sharing_root(web, tests_dir, root), ["ui"])
            check_eq("_profiles_sharing_root: a profile with no test directory of its own shares nothing",
                     r._profiles_sharing_root(web, None, root), [])
        finally:
            cleanup(root)
    # a ui profile rooted BELOW the api root owns its own directory: nothing is shared, the first test is the api's
    root = rehearsal_fixture.project("qa-nested-root-")
    try:
        (root / "tests" / "ui").mkdir()
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        web = cfg["profiles"][0]
        web["roots"] = {"test": "tests"}
        ui = {**json.loads(json.dumps(web)), "profile_id": "ui", "roots": {"test": "tests/ui"}}
        cfg["profiles"] = [web, ui]
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        use_project(root)
        r = rehearsal_fixture.rehearse(root)
        check_eq("a nested root is nobody's tie: the outer profile shares nothing",
                 r._profiles_sharing_root(web, r._profile_tests_dir(web, root), root), [])
        check_eq("and the inner one owns its directory alone",
                 r._profiles_sharing_root(ui, r._profile_tests_dir(ui, root), root), [])
    finally:
        cleanup(root)


def sharing_is_the_one_predicates_answer() -> None:
    """t-075 (survivor t055-8, `_profiles_sharing_root` back to a resolved-path compare of each profile's root with the
    directory). `Path.resolve()` folds `tests`, `./tests`, `sub/../tests` and (an existing directory, on Windows) `TESTS`
    exactly as `_path_key` does, so those shapes cannot tell the two apart. Two others can: a profile that is NOT
    selected (`selected: false` - `profiles_owning` leaves it out, a compare of every configured profile does not) and a
    root spelled as the absolute path of the same directory (`_path_key` keeps it a different key). The key: the answer
    IS `execution_request.profiles_owning`'s, minus the profile itself, for every spelling; and the unselected one is
    named explicitly, as the shape a resolved compare gets wrong."""
    root = rehearsal_fixture.project("qa-sharing-predicate-")
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        web = cfg["profiles"][0]
        web["roots"] = {"test": "tests"}
        cfg["profiles"] = [web]
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        use_project(root)
        r = rehearsal_fixture.rehearse(root)
        tests_dir = r._profile_tests_dir(web, root)
        check("(setup) the directory exists and is the profile's own", tests_dir is not None)
        absolute = str((root / "tests").resolve())
        shapes = (("the same spelling", {"test": "tests"}, {}), ("`./tests`", {"test": "./tests"}, {}),
                  ("a root with `..` in it", {"test": "sub/../tests"}, {}), ("`TESTS`", {"test": "TESTS"}, {}),
                  ("a backslash spelling", {"test": "tests\\"}, {}),
                  ("the absolute path of the same directory", {"test": absolute}, {}),
                  ("a profile that is not selected", {"test": "tests"}, {"selected": False}),
                  ("a deeper root of another profile", {"test": "tests/ui"}, {}),
                  ("no root at all", {}, {}))
        for label, roots, extra in shapes:
            other = {**json.loads(json.dumps(web)), "profile_id": "ui", "roots": roots, **extra}
            r.config = dict(r.config, profiles=[web, other])
            expected = sorted(o for o in er.profiles_owning(r.config, "tests") if o != web["profile_id"])
            check_eq(f"_profiles_sharing_root, {label}: the answer is `profiles_owning`'s, the profile itself left out",
                     r._profiles_sharing_root(web, tests_dir, root), expected)
        r.config = dict(r.config, profiles=[web, {**json.loads(json.dumps(web)), "profile_id": "ui", "selected": False}])
        check_eq("an unselected profile over the same root shares nothing (a compare of every configured profile says `ui`)",
                 r._profiles_sharing_root(web, tests_dir, root), [])
        r.config = dict(r.config, profiles=[web, {**json.loads(json.dumps(web)), "profile_id": "ui", "roots": {"test": "./tests"}}])
        check_eq("control: the same profile selected over `./tests` is the one that shares",
                 r._profiles_sharing_root(web, tests_dir, root), ["ui"])
        if os.name == "nt":
            r.config = dict(r.config, profiles=[web, {**json.loads(json.dumps(web)), "profile_id": "ui", "roots": {"test": "TESTS"}}])
            check_eq("on Windows `TESTS` is the same directory as `tests`: shared",
                     r._profiles_sharing_root(web, tests_dir, root), ["ui"])
    finally:
        cleanup(root)


def build_request_and_the_judge_pass_the_rows_profile() -> None:
    """t-075 (the NO KEY row of t055 item 7, second half). `probe_by_code.build_request` takes the profile the manifest row
    names and picks the cwd with it (`_profile_cwd`), and `_run_and_judge` hands it the row's profile
    (`execution_request.entry_profile_id`). The request builder is a stand-in that records the `--cwd` it is given, so
    the key needs no project's tests, only the two seams. Without the argument the shared root is refused (control)."""
    root = temp_project("qa-profile-build-")
    saved_mine, saved_build = er.build_mine_request, pbc.build_request
    seen = {}

    def stand_in(_root, _cases, **kwargs):
        seen.update(cwd=kwargs.get("cwd"), profile_id=kwargs.get("profile_id"), profile_door=kwargs.get("profile_door"))
        return {"selected_instance_ids": ["test_x"], "input_fingerprint": "f" * 64}, [], None, None
    try:
        use_project(root)
        er.build_mine_request = stand_in
        spec = {"file": "tests/t.py", "node": "tests/t.py::test_x", "reader": "ast"}
        try:
            pbc.build_request(root, two(), "QA-1", "D-1", "TC-1", spec, "test_x", "invert", "r", "ui")
            named = ""
        except pbc.Refusal as exc:
            named = str(exc)
        check_eq("build_request: the profile the row names settles the shared root - its cwd is the request's",
                 (seen.get("cwd"), named), (str((root / "ui-dir").resolve()), ""))
        # EP1-16 (A-K1, A-K3): the profile the row names is the BUILDER's too, and the builder is told this caller has
        # no `--profile` door. Without them the builder refused a root it had been given the name for one line above.
        check_eq("build_request hands build_mine_request the row's profile (`ui`) and says it has no --profile door",
                 (seen.get("profile_id"), seen.get("profile_door")), ("ui", False))
        pbc.build_request(root, {"profiles": [two()["profiles"][0]]}, "QA-1", "D-1", "TC-1", spec, "test_x", "invert", "r")
        check_eq("(a one-profile project, no name: the builder gets none and still hears there is no --profile door)",
                 (seen.get("profile_id"), seen.get("profile_door")), ("", False))
        try:
            pbc.build_request(root, two(), "QA-1", "D-1", "TC-1", spec, "test_x", "invert", "r")
            outcome = "no refusal"
        except pbc.Refusal as exc:
            outcome = str(exc)
        check_in("build_request control: with no profile named the shared root is refused", "share the test root of tests/t.py",
                 outcome)

        calls = []

        def recorder(*args, **kwargs):
            calls.append(list(args) + list(kwargs.values()))
            raise RuntimeError("stop here")
        pbc.build_request = recorder
        task_root = root / "qa-factory" / "artifacts" / "QA-1"
        ctx = pbc.ProbeCtx("QA-1", "D-1", "test_x", "TC-1", spec, {"profile_id": "ui"}, root, two(), task_root, False,
                           "invert", task_root / "work" / "automation-manifest.json", root / "tests" / "t.py")
        record = {"notes": [], "expected_location": "tests/t.py:3"}
        pbc._run_and_judge(ctx, record, root / "oracle.json", "m" * 64, "o" * 64, 1)
        check_eq("_run_and_judge hands build_request the profile of the instance's manifest row",
                 (len(calls), calls[0][9] if calls else None), (1, "ui"))   # 10th positional = profile_id; s6_close follows as a keyword
        check_in("(the stand-in's stop is the record's note, nothing escapes)", "stop here", " ".join(record["notes"]))
    finally:
        er.build_mine_request, pbc.build_request = saved_mine, saved_build
        cleanup(root)


def onboarding() -> None:
    check_eq("the gate rehearsal picks no test by path for a shared root", rehearsal_fixture.gate_preflight.Rehearsal.SHARED_ROOT_PICKS_NOTHING, True)
    check_eq("the onboarding probe, which learns what a command writes, still takes any test under the root",
             onboarding_probe.ProbeRehearsal.SHARED_ROOT_PICKS_NOTHING, False)


def _one_root_cfg(**extra):
    return {"profiles": [{"profile_id": "api", "roots": {"test": "tests"}}], "app_root": ".", **extra}


def k_root_param() -> None:
    """EP1-12 K-root-param: `_in_test_root` reads a path the way `profiles_owning` does (one `_path_key`), and every input
    that is not a test under the root is False (the error direction is only toward 'the edit is refused')."""
    cfg = _one_root_cfg(protected_app_paths=["tests/fixtures"])
    for rel in ("tests/x.py", "./tests/x.py", "tests\\x.py", "tests/a/../x.py", "tests//a.py", "tests/a/b/c.py"):
        check_eq(f"K-root-param: `{rel}` is a test under `tests`", pbc._in_test_root(cfg, rel), True)
    windows = os.name == "nt"
    check_eq(f"K-root-param [os.name={os.name}]: `Tests/x.py` is under `tests` only where the file system folds the case",
             pbc._in_test_root(cfg, "Tests/x.py"), windows)
    for label, rel in (("a path that climbs out and back into the product", "tests/../src/app.py"),
                       ("a path that starts outside the project", "../tests/x.py"),
                       ("a path that climbs above the project", "tests/../../x.py"),
                       ("a root-name prefix only", "tests_evil/x.py"),
                       ("an empty path", ""), ("a blank path", "  "),
                       ("an absolute posix path (not a project-relative one)", "/tests/x.py"),
                       ("an absolute backslash path", "\\tests\\x.py"),
                       ("an absolute posix path with leading whitespace (F3)", " /tests/x.py"),
                       ("an absolute posix path with a leading tab (F3)", "\t/tests/x.py"),
                       ("an absolute backslash path with leading whitespace (F3)", " \\tests\\x.py"),
                       ("a drive-letter path with leading whitespace", " C:/tests/x.py"),
                       ("a drive-letter path", "C:/tests/x.py"), ("a drive-letter backslash path", "C:\\tests\\x.py"),
                       ("a protected path inside the test root", "tests/fixtures/x.py"),
                       ("the protected root itself", "tests/fixtures"),
                       ("a protected path in another case (never allowed on either file system)", "Tests/Fixtures/x.py"),
                       ("a protected path spelled through `..`", "tests/a/../fixtures/x.py"),
                       ("a protected path with a backslash", "tests\\fixtures\\x.py"),
                       ("the test root itself with a dot", "tests/..")):
        check_eq(f"K-root-param: {label} (`{rel}`) is False", pbc._in_test_root(cfg, rel), False)
    check_eq("K-root-param: `protected_app_paths: ['.']` protects everything",
             pbc._in_test_root(_one_root_cfg(protected_app_paths=["."]), "tests/x.py"), False)
    check_eq("K-root-param: no root at all is False", pbc._in_test_root({"profiles": []}, "tests/x.py"), False)
    check_eq("K-root-param: `tests_root` alone is a root", pbc._in_test_root({"tests_root": "tests"}, "tests/x.py"), True)
    check_eq("K-root-param: protected paths are read from `app_root`",
             pbc._in_test_root({"profiles": [{"roots": {"test": "backend/tests"}}], "app_root": "backend",
                                "protected_app_paths": ["tests/app"]}, "backend/tests/app/x.py"), False)
    check_eq("K-root-param: `path_under` of an empty key or an empty root is False",
             (er.path_under("", "tests"), er.path_under("tests", ""), er.path_under("tests", "tests"),
              er.path_under("tests/a", "tests"), er.path_under("testsa", "tests")), (False, False, True, True, False))


def k_same() -> None:
    """K-same: with one profile and no protected path, `_in_test_root` and `profiles_owning` answer alike on every
    project-relative spelling; they differ ONLY where `_in_test_root` is the stricter guard (an absolute path)."""
    cfg = _one_root_cfg()
    for rel in ("tests/x.py", "./tests/x.py", "tests\\x.py", "tests/a/../x.py", "tests", "tests_evil/x.py",
                "tests/../src/app.py", "../tests/x.py", "", "src/x.py", "Tests/x.py"):
        check_eq(f"K-same: `{rel}`", pbc._in_test_root(cfg, rel), bool(er.profiles_owning(cfg, rel)))
    check_eq("K-same: the one deliberate difference - an absolute path owns nothing for the guard, the owner reader cuts "
             "its slash", (pbc._in_test_root(cfg, "/tests/x.py"), er.profiles_owning(cfg, "/tests/x.py")), (False, ["api"]))


def k_rel_and_prefix() -> None:
    """K-rel, K-prefix: the gate's two 'is it inside' readings share `_rel_inside`; a directory outside `tests_root`
    is None for the collect prefix (never the whole collect), the directory itself is the whole collect."""
    import gate_preflight
    cls = gate_preflight.Rehearsal
    root = Path(rehearsal_fixture.temp_dir("qa-rel-"))
    try:
        base = root.resolve()
        check_eq("K-rel: inside", cls._root_rel(base / "tests" / "ui", root), "tests/ui")
        check_eq("K-rel: the root itself", cls._root_rel(base, root), ".")
        outside = Path(str(base) + "-elsewhere") / "tests"
        check_eq("K-rel: outside the root, the path as given", cls._root_rel(outside, root), str(outside))
        check_eq("K-rel: None is '.'", cls._root_rel(None, root), ".")
        check_eq("K-rel: `_rel_inside` inside / itself / outside / junk",
                 (cls._rel_inside(base / "a" / "b", base), cls._rel_inside(base, base), cls._rel_inside(outside, base),
                  cls._rel_inside(None, base)), ("a/b", ".", None, None))
        r = cls.__new__(cls)
        r.config = {"tests_root": "svc"}
        check_eq("K-prefix: a directory outside `tests_root` has no prefix (None, not '')",
                 r._node_prefix(base / "tests", root), None)
        check_eq("K-prefix: a directory below `tests_root`", r._node_prefix(base / "svc" / "ui", root), "ui")
        check_eq("K-prefix: the directory is `tests_root` itself: the whole collect (.)", r._node_prefix(base / "svc", root), ".")
        check_eq("K-prefix: no directory: the whole collect ('')", r._node_prefix(None, root), "")
    finally:
        cleanup(root)
    # the choice: a tests_dir outside `tests_root` is not served by the collect's first node
    root = rehearsal_fixture.project("qa-prefix-choice-")
    try:
        (root / "svc").mkdir()
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["tests_root"] = "svc"
        cfg["profiles"][0]["roots"] = {"test": "tests"}
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        use_project(root)
        r = rehearsal_fixture.rehearse(root)
        r.collect_stdout = "svc/test_other.py::test_other\n"
        profile = r.config["profiles"][0]
        ctx = gate_preflight.ReporterCtx("s5_reporter", "web", root, root.resolve(), ("python", "{report_path}", "<test-id>"),
                                         "junit-xml", "junit-xml", 30)
        chosen, how, _why, _counts = r._choose_test(ctx, {}, profile, {"cwd": "."}, True)
        check_eq("K-prefix: a profile directory outside `tests_root` is served by its own first test file, not the collect's node",
                 chosen, "tests/test_a_first.py")
        check_in("K-prefix: and says it came from the files", "the first test file", how)
        profile["roots"] = {"test": "svc"}
        (root / "svc" / "test_other.py").write_text("def test_other():\n    pass\n", encoding="utf-8")
        chosen, _how, _why, _counts = r._choose_test(ctx, {}, profile, {"cwd": "."}, True)
        check_eq("K-prefix: the directory is `tests_root`: the whole collect", chosen, "svc/test_other.py::test_other")
    finally:
        cleanup(root)


def k_unnamed() -> None:
    """K-unnamed [F-8]: an unnamed row beside a named one whose file lies under ANOTHER profile's root is refused with
    the door; under the named profile's root, or under no root, it runs as before."""
    cfg = two("tests/api", "tests/ui")
    named = {"profile_id": "api"}
    picked, why = profile_for(cfg, ["tests/api/a.py", "tests/ui/u.py"],
                              [dict(named, file="tests/api/a.py"), {"file": "tests/ui/u.py", "instance_id": "TC-2"}])
    check_eq("K-unnamed: a row under another profile's root is refused", picked, None)
    check_in("K-unnamed: the refusal names the row, the owner and the named profile",
             "the manifest row TC-2 names no profile, and its file tests/ui/u.py lies under the test root of `ui`", why)
    check_in("K-unnamed: ...and the other row's profile", "another row names `api`", why)
    check_in("K-unnamed: ...and both doors", "`profile_id`", why)
    check_in("K-unnamed: ...the flag door", "--profile ID", why)
    picked, why = profile_for(cfg, ["tests/api/a.py", "tests/ui/u.py"],
                              [dict(named, file="tests/api/a.py"), {"file": "tests/ui/u.py"}], profile_door=False)
    check_eq("K-unnamed: refused without the flag door too", picked, None)
    check_not_in("K-unnamed: ...and then names no --profile", "--profile", why)
    check_eq("K-unnamed: a row under the named profile's own root runs under it",
             profile_for(cfg, ["tests/api/b.py"], [dict(named, file="tests/api/a.py"), {"file": "tests/api/b.py"}]),
             ("api", ""))
    check_eq("K-unnamed: a row under no root runs under the named profile (as before)",
             profile_for(cfg, ["scripts/x.py"], [dict(named, file="tests/api/a.py"), {"file": "scripts/x.py"}]),
             ("api", ""))
    shared_why = profile_for(two(), ["tests/u.py"], [dict(named), {"file": "tests/u.py"}])[1]
    check_eq("K-unnamed: control, a root two profiles share still has its own refusal text",
             ("api, ui share, while another row names `api`" in shared_why, "lies under the test root of `" in shared_why),
             (True, False))


def main() -> None:
    k_root_param()
    k_same()
    k_rel_and_prefix()
    k_unnamed()
    selector()
    a_name_the_config_does_not_hold()
    named_rows()
    one_predicate()
    probe_door()
    manifest_door()
    rehearsal()
    sharing_is_the_one_predicates_answer()
    build_request_and_the_judge_pass_the_rows_profile()
    onboarding()
    finish("test_profile_shared_root")


if __name__ == "__main__":
    main()
