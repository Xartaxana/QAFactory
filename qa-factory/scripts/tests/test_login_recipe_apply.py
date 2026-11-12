"""RN1-10 b fix round (t-1718): `onboard_apply.py --set-login-ui <recipe.json>` records `manual_capture.login.ui` through the
config's ONE writer, and the door of gate A's `not_proved` sign-in finding names that real command.

Keys: L-write (recorded, other keys kept, backup made) L-same (twice = no write) L-bad (a malformed recipe is refused naming
the field, config bytes unchanged) L-boundary (a row with `test_id` only, an `expand` by `test_id`, missing submit, empty name)
L-door (the command named by the gate's door is an option of onboard_apply's parser).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, run_script, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import config_contract as C  # noqa: E402
import gate_preflight as GP  # noqa: E402

GOOD = {"path": "/login", "expand": {"test_id": "more"}, "username": {"test_id": "user"},
        "password": {"role": "textbox", "name": "Password"}, "submit": {"role": "button", "name": "Sign in"},
        "landed": {"url_not": ["/login"], "session_cookie": "sid"}}


def project() -> Path:
    root = temp_dir("login-recipe-")
    (root / ".git").mkdir()
    config = {"schema_version": 1, "app_root": "src", "tests_root": "tests", "dod": "Done means reviewed and green",
              "manual_capture": {"note": "kept"}}
    C._write_config(root, None, config, "x", "test")
    return root


def cfg_path(root: Path) -> Path:
    return root / "qa-factory" / "config.json"


def put(root: Path, recipe) -> Path:
    path = root.parent / f"{root.name}-recipe.json"
    path.write_text(json.dumps(recipe), encoding="utf-8")
    return path


def cli(root: Path, recipe):
    return run_script("onboard_apply.py", "--root", root, "--set-login-ui", put(root, recipe))


root = project()
try:
    done = cli(root, GOOD)
    check_eq("L-write: exit 0", done.returncode, 0)
    saved = json.loads(cfg_path(root).read_text(encoding="utf-8"))
    check_eq("L-write: the recipe is recorded", saved["manual_capture"]["login"]["ui"], GOOD)
    check_eq("L-write: the other key of manual_capture is kept", saved["manual_capture"].get("note"), "kept")
    check_eq("L-write: another key is untouched", saved["app_root"], "src")
    check("L-write: the config it replaced is backed up", bool(list(root.rglob("config-migrations/*.json"))), str(done.stdout)[:200])

    before = cfg_path(root).read_bytes()
    again = cli(root, GOOD)
    check_eq("L-same: exit 0", again.returncode, 0)
    check_eq("L-same: bytes unchanged", cfg_path(root).read_bytes(), before)
    check_in("L-same: says nothing was written", '"changed": false', again.stdout)

    cases = {
        "not an object": ("[]", "recipe is not an object"),
        "path without slash": (dict(GOOD, path="login"), "`path`"),
        "missing submit": ({k: v for k, v in GOOD.items() if k != "submit"}, "`submit` is missing"),
        "empty name": (dict(GOOD, password={"role": "textbox", "name": " "}), "password"),
        "row is a string": (dict(GOOD, username="Email"), "username"),
        "expand is a list": (dict(GOOD, expand=["x"]), "expand"),
        "landed is a string": (dict(GOOD, landed="/x"), "landed"),
    }
    for name, (recipe, field) in cases.items():
        bad = cli(root, recipe)
        check(f"L-bad {name}: refused", bad.returncode != 0, bad.stderr[:200])
        check_in(f"L-bad {name}: names the field", field, bad.stderr)
        check_in(f"L-bad {name}: says the config is unchanged", "unchanged", bad.stderr)
        check_eq(f"L-bad {name}: config bytes unchanged", cfg_path(root).read_bytes(), before)

    other = cli(root, dict(GOOD, path="/other", username={"test_id": "u2"}))
    check_eq("L-boundary: a different valid recipe replaces the first", json.loads(
        cfg_path(root).read_text(encoding="utf-8"))["manual_capture"]["login"]["ui"]["path"], "/other")
    no_config = temp_dir("login-recipe-none-")
    none = cli(no_config, GOOD)
    check("L-boundary: no config yet is a refusal naming the cause", none.returncode != 0 and "no qa-factory/config.json" in none.stderr, none.stderr[:200])
    check_eq("L-boundary: and writes none", cfg_path(no_config).exists(), False)
    cleanup(no_config)
finally:
    cleanup(root)

# L-door: the command the gate's door names is an option of the parser it names.
# (a person's text may not name a script - t-357 - so the command lives in the onboarding phase the role reads.)
phase = (SCRIPTS.parent / "skills" / "qa-onboarding" / "phases" / "p1-discovery.md").read_text(encoding="utf-8")
found = re.search(r"scripts/(onboard_apply\.py)\\?\"? --root \. (--set-[\w-]+)", phase)
check("L-door: phase p1 names a script and an option", found is not None)
if found:
    check_eq("L-door: the script is onboard_apply.py", found.group(1), "onboard_apply.py")
    helped = run_script("onboard_apply.py", "--help")
    check_in("L-door: the option is in its parser", found.group(2), helped.stdout)
check_in("L-door: the gate's finding door names the known limit in words", "not probed", GP.SIGN_IN_RECIPE_DOOR)

finish("test_login_recipe_apply")
