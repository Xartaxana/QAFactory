"""GW1-19: an unknown `pipeline.stop_after` is named to the person (it stops nothing), and a config with a BOM is read.

Keys of the battery: W-values W-status W-nostop W-bom W-broken W-limit W-one W-gate. The line comes from
`config_contract.stop_after_problem`; `readiness.check_config_schema` adds it to the note and `readiness --require` prints
the short form as its own WARN at every status of the capability (ok, not_configured, missing).
"""
import io
import json
import os
import re
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import config_contract as C  # noqa: E402
import controller  # noqa: E402
import hooklib  # noqa: E402
import readiness as R  # noqa: E402

CYR = "".join(chr(c) for c in (0x441, 0x442, 0x43E, 0x43F))   # four Cyrillic letters from code points: the package has no Cyrillic byte
BAD = ["gate_a", True, 1, [], {}, "GATE_A", ""]
GOOD = ["gate_A", "gate_B", None]


def ident(value) -> str:
    return json.dumps(value)


def cfg_with(value=None, absent: bool = False, **extra) -> dict:
    cfg = {"schema_version": 1, "pipeline": {} if absent else {"stop_after": value}}
    cfg.update(extra)
    return cfg


def put(root: Path, content) -> Path:
    path = root / "qa-factory" / "config.json"
    if path.is_dir():
        path.rmdir()
    if isinstance(content, (bytes, bytearray)):
        path.write_bytes(bytes(content))
    else:
        path.write_text(content, encoding="utf-8")
    return path


def template_cfg(root: Path, **pipeline) -> dict:
    cfg = json.loads((SCRIPTS.parent / "references" / "templates" / "config.json").read_text(encoding="utf-8"))
    cfg["tests_root"] = "tests"
    cfg["app_root"] = "."
    cfg["pipeline"] = dict(cfg.get("pipeline") or {}, **pipeline)
    return cfg


def cli(root: Path, *args):
    use_project(root)
    out, err = io.StringIO(), io.StringIO()
    saved, code = sys.argv, 0
    sys.argv = ["readiness.py", *args]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            R.main()
    except SystemExit as exc:
        code = 0 if exc.code is None else (exc.code if isinstance(exc.code, int) else 1)
    finally:
        sys.argv = saved
    return code, out.getvalue(), err.getvalue()


def values_and_limit() -> None:
    for v in BAD:
        line = C.stop_after_problem(cfg_with(v))
        check(f"W-values: {ident(v)} is named, with both words", "gate_A, gate_B" in line and "stops nothing" in line, line)
    for v in GOOD:
        check_eq(f"W-values: {ident(v)} is fine", C.stop_after_problem(cfg_with(v)), "")
    check_eq("W-values: no key", C.stop_after_problem(cfg_with(absent=True)), "")
    check_eq("W-values: no `pipeline` at all", C.stop_after_problem({"schema_version": 1}), "")
    check_eq("W-values: a config that is not an object", C.stop_after_problem([1]), "")
    pipe = C.stop_after_problem({"pipeline": "gate_A"})
    check("W-values: `pipeline` not an object is named", pipe.startswith("`pipeline` must be an object"), pipe)
    check_eq("W-values: ... the same for null (not an object)", C.stop_after_problem({"pipeline": None}).startswith("`pipeline`"), True)

    # W-limit: the JSON of the value is shown up to 80 characters; the verdict does not depend on the cut.
    at, beyond = "x" * 78, "x" * 79            # json.dumps adds two quotes: 80 and 81 characters
    line80, line81 = C.stop_after_problem(cfg_with(at)), C.stop_after_problem(cfg_with(beyond))
    check_in("W-limit: 80 characters are shown whole", ident(at), line80)
    check_not_in("W-limit: ... with no cut mark", "…", line80)
    check_in("W-limit: 81 characters are cut", "…", line81)
    check_not_in("W-limit: ... and the whole value is not there", ident(beyond), line81)
    check("W-limit: a long lookalike of a stop word is still named", bool(C.stop_after_problem(cfg_with("gate_A" + " " * 90))))
    deep: object = "x"
    for _ in range(50):
        deep = [deep]
    check("W-limit: a value nested 50 levels is named, not raised", bool(C.stop_after_problem(cfg_with(deep))))
    check_in("W-limit: ... (escapes, so any console prints it)", "\\u0441", C.stop_after_problem(cfg_with(CYR)))
    short = C.stop_after_problem(cfg_with("y" * 200), short=True)
    check("W-limit: the short form stays within 180 characters", 0 < len(short) <= 180, str(len(short)))
    check_in("W-limit: the short form names the effect", "will not stop after the gate", short)


def status_and_nostop(root: Path) -> None:
    base = template_cfg(root)
    ok_before = R.check_config_schema(base)
    check_eq("W-status: control - the template config is `ok`", ok_before["status"], "ok")
    for v in BAD:
        cfg = template_cfg(root, stop_after=v)
        got = R.check_config_schema(cfg)
        check_eq(f"W-status: {ident(v)} keeps the status", (got["status"], got["owner"]), (ok_before["status"], ok_before["owner"]))
        check_in(f"W-status: {ident(v)} adds the line", "stops nothing", got["note"])
        check_eq(f"W-status: {ident(v)} adds no `validate` error", C.validate(cfg), C.validate(base))
    stale = dict(template_cfg(root, stop_after="gate_a"), schema_version=0)
    got = R.check_config_schema(stale)
    check_eq("W-status: a stale schema keeps `missing` and gets the line too", got["status"], "missing")
    check_in("W-status: ... in its note", "stops nothing", got["note"])
    check_not_in("W-status: control - a fine value adds nothing", "stop_after", R.check_config_schema(template_cfg(root, stop_after="gate_A"))["note"])

    # W-nostop: the reader is unchanged - an unknown value is no stop, and `with_stop_after` is untouched.
    for v in BAD:
        put(root, json.dumps(template_cfg(root, stop_after=v)))
        use_project(root)
        check_eq(f"W-nostop: {ident(v)} is no stop", controller.stop_after(), None)
    for v in ("gate_A", "gate_B"):
        put(root, json.dumps(template_cfg(root, stop_after=v)))
        check_eq(f"W-nostop: control - {v} is a stop", controller.stop_after(), v)
    action = {"action": "run", "stage": "S5"}
    check_eq("W-nostop: `with_stop_after(action, None)` returns the action", controller.with_stop_after(action, None), action)
    check_eq("W-nostop: a stage past gate A stops", controller.with_stop_after(action, "gate_A")["action"], "stop")


def bom_and_broken(root: Path) -> None:
    plain = json.dumps(template_cfg(root, stop_after="gate_A"))
    put(root, plain)
    use_project(root)
    without = hooklib.load_config()
    put(root, b"\xef\xbb\xbf" + plain.encode("utf-8"))
    use_project(root)
    check_eq("W-bom: `load_config` reads the file with and without a BOM alike", hooklib.load_config(), without)
    check("W-bom: ... and it is not empty", bool(without))
    check_eq("W-bom: `stop_after()` of a BOM config", controller.stop_after(), "gate_A")

    cases = {"empty": b"", "broken json": b"{\"pipeline\": ", "a JSON list": b"[1, 2]", "not UTF-8": b"\xff\xfe\x00{",
             "a JSON number": b"3"}
    for name, raw in cases.items():
        put(root, raw)
        try:
            got = hooklib.load_config()
        except Exception as exc:  # noqa: BLE001
            got = repr(exc)
        check_eq(f"W-broken: {name} reads `{{}}`", got, {})
    path = root / "qa-factory" / "config.json"
    path.unlink()
    check_eq("W-broken: no file reads `{}`", hooklib.load_config(), {})
    path.mkdir()
    try:
        check_eq("W-broken: a directory instead of the file reads `{}`", hooklib.load_config(), {})
    finally:
        path.rmdir()
    # the neighbour that must keep raising: a broken config is not "artifacts in the default root"
    put(root, b"{\"artifact_root\": ")
    try:
        hooklib.artifact_root(root=root)
        raised = False
    except ValueError:
        raised = True
    check("W-broken: `artifact_root` still raises on a broken config (AR-28)", raised)
    put(root, b"\xef\xbb\xbf" + json.dumps({"artifact_root": "out"}).encode("utf-8"))
    check_eq("W-bom: `artifact_root` reads a BOM config", hooklib.artifact_root(root=root), (root / "out").resolve())


def one_list() -> None:
    check_eq("W-one: STOP_GATES keys are STOP_VALUES", tuple(controller.STOP_GATES), hooklib.STOP_VALUES)
    check("W-one: the controller uses the hooklib constant", controller.STOP_VALUES is hooklib.STOP_VALUES)
    form = re.compile(r"^\s*\w*STOP\w*\s*=\s*\(\s*\"gate_A\",\s*\"gate_B\"\s*\)", re.M)
    check("W-one: control - the form finds a planted second list", bool(form.search('X_STOP_VALUES = ("gate_A", "gate_B")\n')))
    hits = [p.name for p in sorted(SCRIPTS.glob("*.py")) if form.search(p.read_text(encoding="utf-8"))]
    check_eq("W-one: exactly one literal list of the stop values in scripts/", hits, ["hooklib.py"])


def gate_line(root: Path) -> None:
    long_value = "z" * 81
    for v, label in (("gate_a", "gate_a"), (long_value, "81 characters")):
        put(root, json.dumps(template_cfg(root, stop_after=v)))
        code, out, err = cli(root, "--require", "config_schema")
        warn = [ln for ln in out.splitlines() if ln.startswith("WARN") and "stop_after" in ln]
        check_eq(f"W-gate: {label} - exit 0 (a warning, never a blocker)", code, 0)
        check_eq(f"W-gate: {label} - one WARN line while the capability is `ok`", len(warn), 1)
        check(f"W-gate: {label} - the line is within 180 characters", all(len(ln) - 5 <= 180 for ln in warn), str(warn))
    # F-1: a not-ok config_schema carries a long note and gate A cuts every WARN to 180 characters, so the stop_after line is
    # its OWN short WARN at every status: not_configured (a top-level key missing) and missing (a stale schema) as well.
    not_configured = template_cfg(root, stop_after="gate_a")
    del not_configured["app_root"]
    stale = dict(template_cfg(root, stop_after="gate_a"), schema_version=0)
    for label, cfg, status in (("not_configured", not_configured, "not_configured"), ("missing", stale, "missing")):
        put(root, json.dumps(cfg))
        code, out, err = cli(root, "--require", "config_schema")
        warn = [ln for ln in out.splitlines() if ln.startswith("WARN") and "stop_after" in ln and "config_schema" not in ln]
        check_in(f"W-gate: {label} - control, the status is the one under test", f"config_schema: {status}", out + err)
        check_eq(f"W-gate: {label} - one separate stop_after WARN line", len(warn), 1)
        check(f"W-gate: {label} - the stop_after text is inside the first 180 characters of its WARN",
              bool(warn) and "will not stop after the gate" in warn[0][5:185], str(warn))
        check_eq(f"W-gate: {label} - exit code follows the status, not the line", code, 1 if status == "missing" else 0)
    put(root, json.dumps(template_cfg(root, stop_after="gate_A")))
    code, out, err = cli(root, "--require", "config_schema")
    check_not_in("W-gate: control - a fine value prints no stop_after line", "stop_after", out)
    put(root, json.dumps(template_cfg(root, stop_after=CYR)))
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONIOENCODING="ascii")
    p = run_script("readiness.py", "--require", "config_schema", env=env)
    check_eq("W-gate: Cyrillic value under PYTHONIOENCODING=ascii exits 0", p.returncode, 0)
    check_in("W-gate: ... and the WARN line is there", "WARN `pipeline.stop_after`", p.stdout)


def main() -> None:
    root = temp_project("qa-factory-stop-after-")
    try:
        values_and_limit()
        status_and_nostop(root)
        bom_and_broken(root)
        one_list()
        gate_line(root)
    finally:
        cleanup(root)
    finish("test_stop_after_config")


if __name__ == "__main__":
    main()
