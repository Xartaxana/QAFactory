#!/usr/bin/env python3
"""role_load.py - the one measure of what a role reads before its first useful action (RC1-14, Part 1).

Keys (the spec's names; every one runs on a fixture tree built in a temp dir, never on the shipped numbers):
  K-S1  the `--json` object has exactly the documented fields; the layers are the closed list, in order
  K-S2  total_bytes is the sum of the non-null layers; tokens = ceil(total / 4) (4001 B -> 1001)
  K-S3  AT the threshold a role is `within`; one token BEYOND it is `over`
  K-S4  a missing charter is `bytes: null`, `measured: false`, reason "missing" - never 0 - and is listed in `unmeasured`
  K-S5  no project: the project's layers are unmeasured; a project with a 50,000 B CLAUDE.md counts 50,000
  K-S6  the static allowances and the brief ceiling are labelled, brief_sides is "per story"
  K-S7  story mode counts the story's own launch card, brief, ALL side files and form
  K-C1  story mode with no cost folder: control `not_measured`, no first-request number, the reason names the folder
  K-C2  a cost file with the agent's requests: gap 14.0 -> ok, AT 15.0 -> ok, 15.1 -> defect; the earliest request is the one
  K-C3  a collapsed ledger is `not_measured`, reason "request ledger collapsed"
  K-C4  host_base_tokens null is `not_calibrated`: the gap is printed and the verdict is never `ok`
  K-C5  no bound agent / a legacy row without cache fields / a row without a timestamp: `not_measured` or skipped, never a number
  K-M1  the CLI: an empty or path-shaped role, an unknown role, a missing story, another role's dispatch, a missing
        settings file are exit 2 with a message; an invalid-UTF-8 charter and a 2 MB charter are measured, not a crash
  K-M2  the readers: retro_numbers.rules_weight and cost_capture.first_request_lookup answer on the same shapes
  K-kind1  `first` is the pre-kinds formula: the common and role layers of every shipped role are the plain file bytes of the map's lists
  K-kind2  the automator's `repair` load is `first` minus the bytes of the three dropped sections (RC1-14 part 2, N1)
  K-kind3  an unknown kind is a RoleLoadError; `kind` None is `first`
  K-kind4  `story_load` with no kind takes the kind of the chosen dispatch's record (repair / rework / first)
  K10-a  (spec t-1765 node A4) a `<!-- kind: craft -->` line above a heading makes the section craft; unmarked is process; a marker in a
         code fence is no marker; a marker not above a heading is ignored and reported once per file; craft + process == tokens
  K10-b  the process ratchet: a missing row, a stale row, process above the row, process below the row ("lower to N"), the shipped
         file sound and dense, the old file without the key named and not a crash
Runnable on its own: `python scripts/tests/test_role_load.py`.
"""
import contextlib
import io
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import cost_capture as CC  # noqa: E402
import inject_context as IC  # noqa: E402
import role_load as RL  # noqa: E402
from content_size import content_bytes  # noqa: E402
from contract_slices import parse  # noqa: E402

NL = chr(10)
TMP = temp_dir("qa-factory-role-load-")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline=NL)
    return path


def settings_doc(threshold=25000, host_base=None, confirmed=None, ratchets=None) -> dict:
    return {"note": "t", "threshold_tokens": threshold, "threshold_confirmed_by": confirmed, "bytes_per_token": 4,
            "host_base_tokens": host_base, "allowances": {"packet": 5400, "launch": 2000},
            "control_tolerance_percent": 15, "ratchet_tokens": ratchets or {}, "ratchet_slack_tokens": 1000}


def plugin(name: str, charter_bytes: int = 4000, with_charter: bool = True, **kw) -> Path:
    """A plugin tree with one role `qa-a`: a charter, a common file, two own files and one project file."""
    root = TMP / name
    write(root / "references" / "common.md", "c" * 100)
    write(root / "references" / "own1.md", "a" * 300)
    write(root / "references" / "own2.md", "b" * 200)
    write(root / "references" / "inject-map.json", json.dumps({
        "common": ["plugin:references/common.md"],
        "roles": {"qa-a": ["plugin:references/own1.md", "plugin:references/own2.md", "project:qa-factory/strategy/s.md"]}}))
    write(root / "references" / "role-load.json", json.dumps(settings_doc(**kw)))
    if with_charter:
        write(root / "agents" / "qa-a.md", "x" * charter_bytes)
    return root


def put_settings(root: Path, **kw) -> None:
    write(root / "references" / "role-load.json", json.dumps(settings_doc(**kw)))


def by_name(load: dict) -> dict:
    return {layer["name"]: layer for layer in load["layers"]}


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = RL.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_shape_and_sums() -> None:
    root = plugin("shape")
    load = RL.static_load("qa-a", plugin_root=root)
    check_eq("K-S1: the fields of the object are exactly the documented set", set(load),
             {"role", "kind", "mode", "story", "dispatch", "layers", "total_bytes", "unmeasured", "tokens", "bytes_per_token",
              "threshold_tokens", "threshold_confirmed", "verdict", "craft_tokens", "process_tokens", "craft_notes"})
    check_eq("K-S1: the layers are the closed list, in order", [l["name"] for l in load["layers"]], list(RL.LAYER_NAMES))
    check_eq("K-S1: a layer has exactly the documented fields", {frozenset(l) for l in load["layers"]},
             {frozenset({"name", "bytes", "measured", "source", "reason"})})
    check_eq("K-S1: static mode carries no control and no story", ("control" in load, load["mode"], load["story"]), (False, "static", None))
    shipped = RL.static_load(RL.role_names()[0])
    code, out, _err = cli("--role", shipped["role"], "--json")
    check("K-S1: --json prints the same object the function returns", code == 0 and json.loads(out) == shipped)
    code, out, _err = cli("--all", "--json")
    check_eq("K-S1: --all --json is a list with one object per role of the shipped map",
             [o["role"] for o in json.loads(out)], RL.role_names())
    # K-S2
    check_eq("K-S2: 4001 B is 1001 tokens, 4000 B is 1000, 1 B is 1", (RL.tokens_of(4001, 4), RL.tokens_of(4000, 4), RL.tokens_of(1, 4)),
             (1001, 1000, 1))
    summed = sum(l["bytes"] for l in load["layers"] if l["bytes"] is not None)
    check_eq("K-S2: total_bytes is the sum of the layers whose bytes are not null", load["total_bytes"], summed)
    check_eq("K-S2: tokens is ceil(total_bytes / bytes_per_token)", load["tokens"], math.ceil(summed / 4))
    check_eq("K-S2: the charter is the file's content bytes", by_name(load)["charter"]["bytes"], 4000)
    check_eq("K-S2: the common layer and the role layer are their files' bytes",
             (by_name(load)["injection_common"]["bytes"], by_name(load)["injection_role"]["bytes"]), (100, 500))
    # K-S6
    layers = by_name(load)
    check_eq("K-S6: packet and launch are the allowances of role-load.json, labelled", [(layers[n]["bytes"], layers[n]["measured"], layers[n]["reason"]) for n in ("packet", "launch")],
             [(5400, False, "allowance"), (2000, False, "allowance")])
    import brief_pack
    check_eq("K-S6: the brief counts at brief_pack.BRIEF_MAX_BYTES, labelled a ceiling", (layers["brief"]["bytes"], layers["brief"]["reason"]),
             (brief_pack.BRIEF_MAX_BYTES, "ceiling"))
    check_eq("K-S6: the side files are not counted without a story", (layers["brief_sides"]["bytes"], layers["brief_sides"]["reason"]), (None, "per story"))
    check("K-S6: every allowance and ceiling is listed as not measured",
          {"packet", "launch", "brief", "brief_sides"} <= set(load["unmeasured"]), str(load["unmeasured"]))
    check_eq("K-S6: the handoff index is the running package's: a fixture tree's form is unmeasured, said so", layers["form"]["measured"], False)


def test_threshold_edge() -> None:
    root = plugin("edge")
    pad = (4 - RL.static_load("qa-a", plugin_root=root)["total_bytes"] % 4) % 4          # total a multiple of 4: the token edge is exact
    write(root / "agents" / "qa-a.md", "x" * (4000 + pad))
    load = RL.static_load("qa-a", plugin_root=root)
    tokens = load["tokens"]
    check_eq("K-S3: the fixture total sits exactly on a token edge", load["total_bytes"], tokens * 4)
    put_settings(root, threshold=tokens)
    check_eq("K-S3 AT: a role exactly at the threshold is within", RL.static_load("qa-a", plugin_root=root)["verdict"], "within")
    write(root / "agents" / "qa-a.md", "x" * (4000 + pad + 1))
    beyond = RL.static_load("qa-a", plugin_root=root)
    check_eq("K-S3 BEYOND: one byte more crosses the token edge, and the role is over", (beyond["tokens"], beyond["verdict"]), (tokens + 1, "over"))
    put_settings(root, threshold=tokens, confirmed="owner, 02.11.2026")
    check_eq("K-S3: threshold_confirmed follows threshold_confirmed_by", RL.static_load("qa-a", plugin_root=root)["threshold_confirmed"], True)
    put_settings(root, threshold=tokens, confirmed="  ")
    check_eq("K-S3: ... and a blank word is not a confirmation", RL.static_load("qa-a", plugin_root=root)["threshold_confirmed"], False)


def test_missing_and_project() -> None:
    root = plugin("nochar", with_charter=False)
    load = RL.static_load("qa-a", plugin_root=root)
    charter = by_name(load)["charter"]
    check_eq("K-S4: a missing charter is bytes null, measured false, reason missing",
             (charter["bytes"], charter["measured"], charter["reason"]), (None, False, "missing"))
    check("K-S4: ... and is listed in `unmeasured`", "charter" in load["unmeasured"])
    check_eq("K-S4: ... and total_bytes is the sum of the others, not a total with a 0 in it",
             load["total_bytes"], sum(l["bytes"] for l in load["layers"] if l["bytes"] is not None))
    # K-S5
    root = plugin("project")
    load = RL.static_load("qa-a", plugin_root=root)
    check_eq("K-S5: no project - the project's CLAUDE.md and project injection are unmeasured, bytes null",
             [(l["bytes"], l["measured"]) for l in load["layers"] if l["name"] in ("project_claude_md", "injection_project")],
             [(None, False), (None, False)])
    project = TMP / "proj"
    write(project / "CLAUDE.md", "k" * 50000)
    load = RL.static_load("qa-a", plugin_root=root, project=project)
    layers = by_name(load)
    check_eq("K-S5: a project with a 50,000 B CLAUDE.md counts 50,000 (the foreign-project case)", layers["project_claude_md"]["bytes"], 50000)
    check("K-S5: ... and the sum carries it: 50,000 B alone is 12,500 tokens of the total", load["tokens"] >= 12500, str(load["tokens"]))
    write(project / ".claude" / "CLAUDE.md", "j" * 10)
    check_eq("K-S5: .claude/CLAUDE.md is added to CLAUDE.md", by_name(RL.static_load("qa-a", plugin_root=root, project=project))["project_claude_md"]["bytes"], 50010)
    check_eq("K-S5: a project file the map names and the project lacks is 0 B, measured, and said",
             (layers["injection_project"]["bytes"], layers["injection_project"]["measured"], "not in the project" in layers["injection_project"]["reason"]),
             (0, True, True))
    write(project / "qa-factory" / "strategy" / "s.md", "s" * 700)
    check_eq("K-S5: ... and counts once the project has it", by_name(RL.static_load("qa-a", plugin_root=root, project=project))["injection_project"]["bytes"], 700)


def story_project(name: str, agent="abc", dispatch_role="qa-a") -> tuple:
    project = TMP / name
    task = project / "qa-factory" / "artifacts" / "T-1"
    write(task / "state" / "controller.json", json.dumps({"dispatches": {"D1": {"id": "D1", "role": dispatch_role, "agent_id": agent}}}))
    return project, task


def usage(first_total: int, parts=(0.6, 0.3, 0.1, 0.0)) -> dict:
    a, b, c = (int(first_total * p) for p in parts[:3])
    return {"requests": 1, "input": a, "output": 7, "cache_read": b, "cache_write_5m": c, "cache_write_1h": first_total - a - b - c}


def cost_file(project: Path, rows: list, name="s1.json") -> None:
    write(project / "qa-factory" / "state" / "cost" / name, json.dumps({"requests": rows}))


def row(stream: str, when: str, use: dict, request_id="r", session="s1") -> dict:
    return {"request_key": f"p:{session}:{request_id}:{stream}", "session_id": session, "request_id": request_id, "stream": stream,
            "timestamp": when, "usage": use}


def test_story_mode_and_control() -> None:
    root = plugin("story")
    project, task = story_project("p-story")
    write(task / "work" / "briefs" / "D1.md", "b" * 1000)
    write(task / "work" / "briefs" / "D1.launch.md", "l" * 321)
    write(task / "work" / "briefs" / "D1-files.md", "f" * 30)
    write(task / "work" / "briefs" / "D1-digests.md", "d" * 40)
    write(task / "work" / "briefs" / "D2-files.md", "z" * 9999)
    write(task / "work" / "handoffs" / "D1.yaml", "y" * 222)
    load = RL.story_load("qa-a", "T-1", project=project, plugin_root=root)
    layers = by_name(load)
    check_eq("K-S7: story mode counts the story's own brief, launch card, form and ALL side files of the dispatch (F-7)",
             (layers["brief"]["bytes"], layers["launch"]["bytes"], layers["form"]["bytes"], layers["brief_sides"]["bytes"]), (1000, 321, 222, 70))
    check_eq("K-S7: ... measured, not allowances; the dispatch is the role's last one",
             (layers["brief"]["measured"], layers["launch"]["measured"], load["dispatch"], load["mode"], load["story"]), (True, True, "D1", "story", "T-1"))
    check_eq("K-S7: the packet stays an allowance until one builder makes it", (layers["packet"]["bytes"], layers["packet"]["measured"]), (5400, False))
    check_eq("K-S7: the layers are still the closed list, in order", [l["name"] for l in load["layers"]], list(RL.LAYER_NAMES))
    # K-C1: no cost folder
    ctl = load["control"]
    check_eq("K-C1: no cost folder - not_measured, no first-request number", (ctl["verdict"], ctl["first_request_tokens"], ctl["gap_percent"]),
             ("not_measured", None, None))
    check_in("K-C1: ... and the reason names the folder", "qa-factory/state/cost/", ctl["reason"])
    # K-C2
    first_bytes = sum(layers[n]["bytes"] for n in RL.FIRST_REQUEST_LAYERS)
    base_tokens = RL.tokens_of(first_bytes, 4)
    cost_file(project, [row("agent-abc.jsonl", "2026-11-01T10:00:00Z", usage(10000), "r1"),
                        row("agent-abc.jsonl", "2026-11-01T10:05:00Z", usage(30000), "r2"),
                        row("agent-zzz.jsonl", "2026-11-01T09:00:00Z", usage(77777), "r0")])
    for predicted, verdict, label in ((8600, "ok", "gap 14.0"), (8500, "ok", "AT the tolerance, gap 15.0"), (8490, "defect", "BEYOND it, gap 15.1")):
        put_settings(root, host_base=predicted - base_tokens)
        ctl = RL.story_load("qa-a", "T-1", project=project, plugin_root=root)["control"]
        check_eq(f"K-C2: first 10,000 tokens, predicted {predicted} ({label})", (ctl["verdict"], ctl["first_request_tokens"], ctl["predicted_tokens"]),
                 (verdict, 10000, predicted))
    check_eq("K-C2: gap_percent is rounded to 0.1", ctl["gap_percent"], 15.1)
    put_settings(root, host_base=8600 - base_tokens)
    check_eq("K-C2: the gap printed for 14.0", RL.story_load("qa-a", "T-1", project=project, plugin_root=root)["control"]["gap_percent"], 14.0)
    # K-C4: host base null
    put_settings(root, host_base=None)
    ctl = RL.story_load("qa-a", "T-1", project=project, plugin_root=root)["control"]
    check("K-C4: host_base_tokens null is not_calibrated, the gap is printed with a base of 0, and it is never ok",
          ctl["verdict"] == "not_calibrated" and isinstance(ctl["gap_percent"], float) and ctl["predicted_tokens"] == base_tokens, str(ctl))
    # K-C6 (m-3): a first-request layer that could not be read is not 0 B - the control is not_measured, naming the layer
    nochar = plugin("nochar", with_charter=False, host_base=1000)
    ctl = RL.story_load("qa-a", "T-1", project=project, plugin_root=nochar)["control"]
    check("K-C6: a missing charter makes the control not_measured naming it, never a short prediction read as ok/defect",
          ctl["verdict"] == "not_measured" and "charter" in ctl["reason"] and ctl["predicted_tokens"] is None, str(ctl))
    # K-C3: a collapsed ledger
    collapsed, ctask = story_project("p-collapsed")
    cost_file(collapsed, [row("agent-abc.jsonl", "2026-11-01T10:00:00Z", usage(10000), "carry:agent-abc.jsonl:m")])
    put_settings(root, host_base=1000)
    ctl = RL.story_load("qa-a", "T-1", project=collapsed, plugin_root=root)["control"]
    check_eq("K-C3: a collapsed ledger is not_measured, reason 'request ledger collapsed'", (ctl["verdict"], ctl["reason"], ctl["first_request_tokens"]),
             ("not_measured", "request ledger collapsed", None))
    # K-C5: unbound agent; a legacy row; a row without a timestamp
    unbound, _t = story_project("p-unbound", agent="")
    ctl = RL.story_load("qa-a", "T-1", project=unbound, plugin_root=root)["control"]
    check_eq("K-C5: a dispatch with no bound agent is not_measured with that reason", (ctl["verdict"], ctl["reason"]),
             ("not_measured", "the dispatch has no bound agent"))
    legacy, _t = story_project("p-legacy")
    cost_file(legacy, [row("agent-abc.jsonl", "2026-11-01T10:00:00Z", {"input": 5000, "output": 9})])
    ctl = RL.story_load("qa-a", "T-1", project=legacy, plugin_root=root)["control"]
    check("K-C5: a legacy row with no cache fields is not_measured, never a number built from half a row",
          ctl["verdict"] == "not_measured" and "no cache fields" in ctl["reason"], str(ctl))
    stamp, _t = story_project("p-nostamp")
    cost_file(stamp, [row("agent-abc.jsonl", None, usage(10000), "r1")])
    ctl = RL.story_load("qa-a", "T-1", project=stamp, plugin_root=root)["control"]
    check_eq("K-C5: a row with no timestamp is skipped - no request left, not_measured", ctl["verdict"], "not_measured")
    # driver mode: the role is its own session
    driver, _t = story_project("p-driver")
    cost_file(driver, [row("orchestrator", "2026-11-01T10:00:00Z", usage(11000), "r1", session="abc"),
                       row("orchestrator", "2026-11-01T09:00:00Z", usage(99999), "r0", session="other")])
    ctl = RL.story_load("qa-a", "T-1", project=driver, plugin_root=root)["control"]
    check_eq("K-C5: driver mode - the orchestrator stream of the agent's own session is its first request", ctl["first_request_tokens"], 11000)
    # no dispatch of the role in the story
    other, _t = story_project("p-other", dispatch_role="qa-b")
    load = RL.story_load("qa-a", "T-1", project=other, plugin_root=root)
    check_eq("K-S7: no dispatch of the role - the per-story layers are unmeasured (null), the control not_measured",
             ([by_name(load)[n]["bytes"] for n in ("launch", "brief", "brief_sides", "form")], load["control"]["verdict"]),
             ([None, None, None, None], "not_measured"))


def test_slack_key() -> None:
    """RC1-14 B-1: `ratchet_slack_tokens` is a validated key of role-load.json, one place for the slack."""
    root = plugin("slackkey")
    check_eq("K-B1: the shipped settings carry the slack key", RL.settings()["ratchet_slack_tokens"], 1000)
    for bad in (-1, "1000", None, True):
        write(root / "references" / "role-load.json", json.dumps(dict(settings_doc(), ratchet_slack_tokens=bad)))
        try:
            RL.settings(root)
            raised = ""
        except RL.RoleLoadError as exc:
            raised = str(exc)
        check_in(f"K-B1: ratchet_slack_tokens {bad!r} is refused naming the key", "ratchet_slack_tokens", raised)
    write(root / "references" / "role-load.json", json.dumps(dict(settings_doc(), ratchet_slack_tokens=0)))
    check_eq("K-B1: a slack of 0 is legal (a tight ratchet)", RL.settings(root)["ratchet_slack_tokens"], 0)


def test_cli_adversarial() -> None:
    names = ", ".join(RL.role_names())
    for label, argv in (("an empty role", ["--role", ""]), ("a path-shaped role", ["--role", "../x"]), ("an unknown role", ["--role", "qa-nope"]),
                        ("no role at all", [])):
        code, out, err = cli(*argv)
        check(f"K-M1: {label} is exit 2 naming the roles of inject-map.json", code == 2 and "name a role of inject-map.json:" in err and names in err and not out,
              f"{code} {err!r}")
    code, _out, err = cli("--role", RL.role_names()[0], "--story", "NOPE")
    check("K-M1: --story NOPE is exit 2 'no story folder NOPE'", code == 2 and "no story folder NOPE" in err, err)
    code, _out, err = cli("--role", RL.role_names()[0], "--story", "../x")
    check("K-M1: a path-shaped story is the same exit 2", code == 2 and "no story folder ../x" in err, err)
    code, _out, err = cli("--role", RL.role_names()[0], "--dispatch", "D1")
    check("K-M1: --dispatch without --story is exit 2", code == 2 and "--story" in err, err)
    code, _out, err = cli("--all", "--role", RL.role_names()[0])
    check("K-M1: --all with --role is exit 2", code == 2, err)
    code, out, _err = cli("--all")
    check("K-M1: --all prints the table: one row per role and the allowance footnote", code == 0 and all(r in out for r in RL.role_names()) and "allowance" in out, out[:200])
    # another role's dispatch
    root = plugin("cli")
    project, _task = story_project("p-cli", dispatch_role="qa-b")
    try:
        RL.story_load("qa-a", "T-1", dispatch="D1", project=project, plugin_root=root)
        raised = ""
    except RL.RoleLoadError as exc:
        raised = str(exc)
    check("K-M1: a dispatch of another role is refused, naming both roles", "qa-b" in raised and "qa-a" in raised, raised)
    # an invalid-UTF-8 charter and a 2 MB charter
    bad = plugin("badbytes")
    raw = b"\xff\xfe\x00bad\xc3\x28" * 10
    (bad / "agents" / "qa-a.md").write_bytes(raw)
    load = RL.static_load("qa-a", plugin_root=bad)
    check_eq("K-M1: a charter with invalid UTF-8 is measured by its bytes, not a crash", by_name(load)["charter"]["bytes"], len(raw))
    big = plugin("big", charter_bytes=2 * 1024 * 1024, threshold=25000)
    load = RL.static_load("qa-a", plugin_root=big)
    check_eq("K-M1: a 2 MB charter is over the threshold, no crash", (load["verdict"], by_name(load)["charter"]["bytes"]), ("over", 2 * 1024 * 1024))
    # E6: the settings file
    nosettings = plugin("nosettings")
    (nosettings / "references" / "role-load.json").unlink()
    try:
        RL.static_load("qa-a", plugin_root=nosettings)
        raised = ""
    except RL.RoleLoadError as exc:
        raised = str(exc)
    check_in("K-M1/E6: a missing role-load.json is refused naming the file", "role-load.json could not be read", raised)
    write(nosettings / "references" / "role-load.json", json.dumps(dict(settings_doc(), threshold_tokens="25000")))
    try:
        RL.static_load("qa-a", plugin_root=nosettings)
        raised = ""
    except RL.RoleLoadError as exc:
        raised = str(exc)
    check("K-M1/E6: a threshold that is not a number is refused, not read as no threshold", "threshold_tokens" in raised, raised)


def test_readers() -> None:
    """K-M2: the first-request reader and the retro's rules weight."""
    project = TMP / "readers"
    cost_file(project, [row("agent-abc.jsonl", "2026-11-01T10:05:00Z", usage(2000), "later"),
                        row("agent-abc.jsonl", "2026-11-01T10:00:00Z", usage(1000), "earliest"),
                        row("orchestrator", "2026-11-01T08:00:00Z", usage(5), "orch", session="s1")])
    hit = CC.first_request_lookup(project, "abc")[0]
    check_eq("K-M2: the earliest request of the agent's stream, by timestamp, with its file", (hit["usage"]["requests"], hit["file"], hit["timestamp"]),
             (1, "s1.json", "2026-11-01T10:00:00Z"))
    check_eq("K-M2: the earliest by TIME, not by position", sum(hit["usage"][k] for k in ("input", "cache_read", "cache_write_5m", "cache_write_1h")), 1000)
    check_eq("K-M2: an agent with no request, an empty id and a project with no cost folder are None",
             (CC.first_request_lookup(project, "nobody")[0], CC.first_request_lookup(project, "")[0],
              CC.first_request_lookup(TMP / "empty", "abc")[0]),
             (None, None, None))
    import retro_numbers as RN
    weight = RN.rules_weight([{"role": "qa-scout", "requests": 10}, {"role": "qa-not-a-role", "requests": 5}], "claude-sonnet-4-5")
    scout = RL.static_load("qa-scout")
    layers = by_name(scout)
    mapped = layers["charter"]["bytes"] + layers["injection_role"]["bytes"] + layers["injection_common"]["bytes"] + layers["brief"]["bytes"]
    check_eq("K-M2: rules_weight prices the SUM of the four mapped layers of role_load (not total_bytes), one role, the unknown one left out",
             (list(weight["by_role"]), weight["by_role"]["qa-scout"]["bytes"], weight["tokens"]), (["qa-scout"], mapped, mapped * 10 // 4))
    check("K-M2: ... and total_bytes is more (the packet, launch and form are not priced there)", scout["total_bytes"] > mapped)


def test_kinds() -> None:
    """K-kind1..4: what a dispatch kind does to the measure."""
    imap = RL.load_imap()
    plain = lambda entries: sum(content_bytes(RL.PLUGIN_ROOT / e.split(":", 1)[1]) for e in entries if e.startswith("plugin:"))
    for role in RL.role_names():
        by = by_name(RL.static_load(role, "first"))
        want = (plain(imap["common"]), plain(imap["roles"][role]))
        check_eq(f"K-kind1: {role}: `first` common and role layers are the plain bytes of the map's lists (the pre-kinds formula)",
                 (by["injection_common"]["bytes"], by["injection_role"]["bytes"]), want)
    # K-kind2: the shipped row
    rel = "plugin:references/slices/qa-automator/execution-lifecycle.md"
    heads = imap["kinds"]["repair"]["qa-automator"]["drop_sections"][rel]
    text = (RL.PLUGIN_ROOT / rel.split(":", 1)[1]).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    found = {s.heading: s for s in parse(text)[1]}
    dropped = sum(len((NL.join([found[h].heading] + found[h].lines) + NL).encode("utf-8")) for h in heads)
    first, repair = RL.static_load("qa-automator", "first"), RL.static_load("qa-automator", "repair")
    check("K-kind2: the three dropped sections weigh something", dropped > 1000, str(dropped))
    check_eq("K-kind2: the automator's repair load is `first` minus the bytes of the three dropped sections",
             (repair["total_bytes"], by_name(repair)["injection_role"]["bytes"]),
             (first["total_bytes"] - dropped, by_name(first)["injection_role"]["bytes"] - dropped))
    check_eq("K-kind2: ... the other layers are untouched", [(l["name"], l["bytes"]) for l in repair["layers"] if l["name"] != "injection_role"],
             [(l["name"], l["bytes"]) for l in first["layers"] if l["name"] != "injection_role"])
    check_eq("K-kind2: a role with no `repair` row measures the same as `first`", RL.static_load("qa-scout", "repair")["total_bytes"],
             RL.static_load("qa-scout", "first")["total_bytes"])
    check_eq("K-kind2: the CLI --kind repair prints the repair measure", cli("--role", "qa-automator", "--kind", "repair", "--json")[0], 0)
    # K-kind3
    try:
        RL.static_load("qa-automator", "resume")
        refused = False
    except RL.RoleLoadError:
        refused = True
    check("K-kind3: an unknown kind is a RoleLoadError", refused)
    check_eq("K-kind3: kind None is `first`", RL.static_load("qa-automator")["kind"], "first")
    # K-kind4: a fixture package, three dispatch records
    root = plugin("kinds")
    imap_fix = json.loads((root / "references" / "inject-map.json").read_text(encoding="utf-8"))
    write(root / "references" / "own1.md", "## keep" + NL + "k" * 50 + NL + NL + "### Drop me" + NL + "d" * 200 + NL + NL + "## tail" + NL + "t" * 20 + NL)
    imap_fix["kinds"] = {"repair": {"qa-a": {"drop_sections": {"plugin:references/own1.md": ["### Drop me"]}}}}
    write(root / "references" / "inject-map.json", json.dumps(imap_fix))
    project = TMP / "p-kinds"
    task = project / "qa-factory" / "artifacts" / "T-1"
    records = {"D1": {"id": "D1", "role": "qa-a"},
               "D2": {"id": "D2", "role": "qa-a", "rework_of": "D1"},
               "D3": {"id": "D3", "role": "qa-a", "rework_of": "D1", "repair_cause": "test_defect"}}
    write(task / "state" / "controller.json", json.dumps({"dispatches": records}))
    got = {d: RL.story_load("qa-a", "T-1", dispatch=d, project=project, plugin_root=root) for d in records}
    check_eq("K-kind4: no --kind: the kind of each chosen record", {d: l["kind"] for d, l in got.items()},
             {"D1": "first", "D2": "rework", "D3": "repair"})
    check_eq("K-kind4: ... and the repair record is measured without the dropped section (its heading line and its 200 B line)",
             got["D1"]["total_bytes"] - got["D3"]["total_bytes"], len(("### Drop me" + NL + "d" * 200 + NL + NL).encode("utf-8")))
    check_eq("K-kind4: no --dispatch: the role's last record decides", RL.story_load("qa-a", "T-1", project=project, plugin_root=root)["kind"], "repair")
    check_eq("K-kind4: an explicit kind is measured as asked", RL.story_load("qa-a", "T-1", dispatch="D3", project=project, plugin_root=root, kind="first")["total_bytes"],
             got["D1"]["total_bytes"])
    check_eq("K-kind4: the hook's reader and the measure agree on every record", {d: IC.dispatch_kind(r) for d, r in records.items()},
             {d: l["kind"] for d, l in got.items()})
    write(task / "state" / "controller.json", json.dumps({"dispatches": {}}))
    check_eq("K-kind4: a story with no dispatch of the role is `first`", RL.story_load("qa-a", "T-1", project=project, plugin_root=root)["kind"], "first")


def test_craft_split() -> None:
    """K10-a: craft and process, by the marker above a heading (E-A5)."""
    marked = "lead" + NL + NL + "<!-- kind: craft -->" + NL + "## Craft" + NL + "c" * 40 + NL + NL + "## Rule" + NL + "p" * 40 + NL
    craft, ignored = RL.craft_split(marked)
    want = len(("<!-- kind: craft -->" + NL + "## Craft" + NL + "c" * 40 + NL + NL).encode("utf-8"))
    check_eq("K10-a: the marker line, its heading and its body are craft; the unmarked section after it is process", (craft, ignored), (want, 0))
    check_eq("K10-a: no marker at all - everything is process", RL.craft_split("## A" + NL + "x" * 30 + NL), (0, 0))
    check_eq("K10-a: an empty text is craft 0", RL.craft_split(""), (0, 0))
    child = "<!-- kind: craft -->" + NL + "## C" + NL + "a" + NL + "### Child" + NL + "b" + NL + "## Next" + NL + "n" + NL
    check_eq("K10-a: a deeper heading under a craft heading stays craft, the next `##` ends it",
             RL.craft_split(child)[0], len(("<!-- kind: craft -->" + NL + "## C" + NL + "a" + NL + "### Child" + NL + "b" + NL).encode("utf-8")))
    stacked = "<!-- kind: craft -->" + NL + "<!-- roles: all -->" + NL + "## C" + NL + "a"
    check_eq("K10-a: a roles marker between the kind marker and the heading is allowed", RL.craft_split(stacked), (len(stacked.encode("utf-8")), 0))
    fenced = "```" + NL + "<!-- kind: craft -->" + NL + "## not a heading" + NL + "```" + NL + "## Real" + NL + "x" + NL
    check_eq("K10-a: a marker inside a fenced code block is not a marker (and is not reported)", RL.craft_split(fenced), (0, 0))
    stray = "<!-- kind: craft -->" + NL + "some text" + NL + "## H" + NL + "x" + NL + "text <!-- kind: craft -->" + NL
    check_eq("K10-a: a marker with text before the heading, and one inside a text line, are ignored and counted", RL.craft_split(stray), (0, 2))
    check_eq("K10-a: a marker at the end of the file heads nothing: ignored", RL.craft_split("## H" + NL + "<!-- kind: craft -->" + NL), (0, 1))
    # t-1793 F4: a marked `###` under a craft `##` ends at its sibling, the parent stays craft
    tail = "## B" + NL + "d"
    nested = "<!-- kind: craft -->" + NL + "## A" + NL + "a" + NL + "<!-- kind: craft -->" + NL + "### A1" + NL + "b" + NL + "### A2" + NL + "c" + NL + tail
    check_eq("K10-a: a marked ### under a craft ## does not reset the parent: ### A2 is craft, ## B is process",
             RL.craft_split(nested), (len(nested.encode("utf-8")) - len(tail.encode("utf-8")), 0))
    # t-1793 F4: a ~~~ fence is a fence
    tilde = "<!-- kind: craft -->" + NL + "## A" + NL + "~~~" + NL + "## fake" + NL + "~~~" + NL + "body" + NL + tail
    check_eq("K10-a: a ~~~ fence hides a ## line: craft runs on to the real ## B",
             RL.craft_split(tilde), (len(tilde.encode("utf-8")) - len(tail.encode("utf-8")), 0))
    mixed = "<!-- kind: craft -->" + NL + "## A" + NL + "~~~" + NL + "```" + NL + "## fake" + NL + "~~~" + NL + tail
    check_eq("K10-a: a ``` line inside a ~~~ fence does not close it", RL.craft_split(mixed), (len(mixed.encode("utf-8")) - len(tail.encode("utf-8")), 0))
    # t-1793 F5: `kind: process` is a known marker and ends a craft section; its sub-headings stay process
    head = "<!-- kind: craft -->" + NL + "## A" + NL + "a" + NL
    proc = head + "<!-- kind: process -->" + NL + "## P" + NL + "p" + NL + "### Sub" + NL + "s" + NL + "## B" + NL + "d"
    check_eq("K10-a: a `kind: process` section after a craft one is process, with its sub-headings", RL.craft_split(proc), (len(head.encode("utf-8")), 0))
    deeper = "<!-- kind: craft -->" + NL + "## A" + NL + "a" + NL + "<!-- kind: process -->" + NL + "### Q" + NL + "q" + NL + "### R" + NL + "r"
    carved = "<!-- kind: process -->" + NL + "### Q" + NL + "q" + NL
    check_eq("K10-a: a `kind: process` ### under craft is process up to its sibling, which is craft again (the parent's kind)",
             RL.craft_split(deeper)[0], len(deeper.encode("utf-8")) - len(carved.encode("utf-8")))
    # t-1793 F6: an unknown kind value is not a marker: ignored, counted, never craft
    check_eq("K10-a: an unknown kind value is ignored and counted", RL.craft_split("<!-- kind: craftt -->" + NL + "## H" + NL + "x"), (0, 1))
    check_eq("K10-a: an unknown kind value on the heading line is ignored and counted", RL.craft_split("## H <!-- kind: crafty -->" + NL + "x"), (0, 1))
    # t-1793 F6: contract_slices.parse keeps a roles marker across a kind marker (both orders give the same slice)
    kind_first = "lead" + NL + "<!-- kind: craft -->" + NL + "<!-- roles: qa-a -->" + NL + "## H" + NL + "body"
    roles_first = "lead" + NL + "<!-- roles: qa-a -->" + NL + "<!-- kind: craft -->" + NL + "## H" + NL + "body"
    shape = lambda text: (lambda lead, secs: (lead, [(s.heading, s.roles, s.lines) for s in secs]))(*parse(text))
    check_eq("K10-a/F6: a roles marker above a kind marker is not lost: the section keeps its roles", parse(roles_first)[1][0].roles, ["qa-a"])
    check_eq("K10-a/F6: kind above roles and roles above kind give the same slice", shape(roles_first), shape(kind_first))
    check_eq("K10-a/F6: a roles marker above real text is still dropped (control)", parse("<!-- roles: qa-a -->" + NL + "text" + NL + "## H" + NL + "b")[1][0].roles, [])


def test_craft_in_load() -> None:
    """K10-a: craft_tokens + process_tokens == tokens, on a fixture and on every shipped role; one note per file."""
    root = plugin("craft-load")
    write(root / "references" / "own1.md", "<!-- kind: craft -->" + NL + "## Craft" + NL + "c" * 1000 + NL + "## Rule" + NL + "p" * 300 + NL)
    write(root / "agents" / "qa-a.md", "x" * 4000 + NL + "<!-- kind: craft -->" + NL + "stray" + NL)
    load = RL.static_load("qa-a", plugin_root=root)
    check_eq("K10-a: the craft is the marked section of the role file alone (the charter's stray marker is not craft)",
             load["craft_tokens"], RL.tokens_of(len(("<!-- kind: craft -->" + NL + "## Craft" + NL + "c" * 1000 + NL).encode("utf-8")), 4))
    check_eq("K10-a: craft + process is the token total", load["craft_tokens"] + load["process_tokens"], load["tokens"])
    check_eq("K10-a: the stray marker is reported once, naming the file",
             [n for n in load["craft_notes"] if "agents/qa-a.md" in n and "1 `<!-- kind: craft -->` marker(s)" in n].__len__(), 1)
    check_eq("K10-a: ... and nothing else is reported", len(load["craft_notes"]), 1)
    plain = RL.static_load("qa-a", plugin_root=plugin("craft-none"))
    check_eq("K10-a: no marker anywhere: craft 0, process is the whole", (plain["craft_tokens"], plain["process_tokens"]), (0, plain["tokens"]))
    for ld in json.loads(cli("--all", "--json")[1]):
        check_eq(f"K10-a: {ld['role']}: craft + process == tokens (the shipped numbers)", ld["craft_tokens"] + ld["process_tokens"], ld["tokens"])
    first = json.loads(cli("--all", "--json")[1])[0]            # the printer's role: the first of role_names(), read from the json, not a literal
    check_eq("K10-a: the json's first role is the printer's role", first["role"], RL.role_names()[0])
    shown = cli("--role", first["role"])[1]
    check_in("K10-a: the text printer shows the split with the json's own numbers",
             f"craft {first['craft_tokens']:,} + process {first['process_tokens']:,} tokens", shown)
    check_eq("K10-a (negative control): a craft number the json does not carry is not shown",
             f"craft {first['craft_tokens'] + 1:,} + process" in shown, False)


def test_process_ratchet() -> None:
    """K10-b: the process ratchet's judge, its settings keys and the shipped file."""
    measured = {"qa-a": 100, "qa-b": 50}
    roles = ["qa-a", "qa-b"]
    check_eq("K10-b: rows equal to the measure - nothing wrong", RL.process_ratchet_problems(measured, {"qa-a": 100, "qa-b": 50}, roles), [])
    problems = RL.process_ratchet_problems(measured, {"qa-a": 100}, roles)
    check("K10-b: a role with no row is named with the row to add", len(problems) == 1 and "no row for qa-b" in problems[0] and "add `qa-b: 50`" in problems[0], str(problems))
    problems = RL.process_ratchet_problems(measured, {"qa-a": 100, "qa-b": 50, "qa-gone": 7}, roles)
    check("K10-b: a row for a role with no file is stale", len(problems) == 1 and "stale row `qa-gone`" in problems[0], str(problems))
    problems = RL.process_ratchet_problems(measured, {"qa-a": 99, "qa-b": 50}, roles)
    check("K10-b: process one token ABOVE its row is a raise nobody named", len(problems) == 1 and "qa-a" in problems[0] and "over its shrink-only" in problems[0], str(problems))
    problems = RL.process_ratchet_problems(measured, {"qa-a": 101, "qa-b": 50}, roles)
    check("K10-b: a row one token ABOVE the process is red - lower to N (slack 0)", len(problems) == 1 and "lower to 100" in problems[0], str(problems))
    problems = RL.process_ratchet_problems(measured, None, roles)
    check("K10-b: an old file without the key is named, not a crash", len(problems) == 1 and "process_ratchet_tokens" in problems[0] and "no process ratchet" in problems[0], str(problems))
    problems = RL.process_ratchet_problems({}, {"qa-a": 0}, ["qa-a"])
    check_eq("K10-b: a role with no injected text has a row of 0 and nothing wrong", problems, [])
    # the settings reader
    root = plugin("pr-settings")
    old = RL.settings(root)
    check_eq("K10-b: settings() of an old file (no key): process_ratchet_tokens None, target not confirmed", (old["process_ratchet_tokens"], old["target_confirmed"]), (None, False))
    for bad in ([], {"qa-a": -1}, {"qa-a": "1"}, {"qa-a": True}):
        write(root / "references" / "role-load.json", json.dumps(dict(settings_doc(), process_ratchet_tokens=bad)))
        try:
            RL.settings(root)
            raised = ""
        except RL.RoleLoadError as exc:
            raised = str(exc)
        check_in(f"K10-b: process_ratchet_tokens {bad!r} is refused naming the key", "process_ratchet_tokens", raised)
    write(root / "references" / "role-load.json", json.dumps(dict(settings_doc(), process_ratchet_tokens={"qa-a": 0}, target_tokens=6000, target_confirmed_by="")))
    got = RL.settings(root)
    check_eq("K10-b: a row of 0, the target and an empty confirmation are legal; the target is not confirmed", (got["process_ratchet_tokens"], got["target_tokens"], got["target_confirmed"]), ({"qa-a": 0}, 6000, False))
    write(root / "references" / "role-load.json", json.dumps(dict(settings_doc(), target_tokens=6000, target_confirmed_by="owner, 04.11.2026")))
    check_eq("K10-b: target_confirmed follows target_confirmed_by", RL.settings(root)["target_confirmed"], True)
    # the shipped file: dense and tight at the first measurement
    shipped = RL.settings()["process_ratchet_tokens"]
    loads = {r: RL.static_load(r) for r in RL.role_names()}
    check_eq("K10-b: the shipped file is dense: one row per agents/*.md", sorted(shipped), RL.agent_roles())
    check_eq("K10-b: the shipped rows are tight and not exceeded (the audit's judge answers nothing)",
             RL.process_ratchet_problems({r: ld["process_tokens"] for r, ld in loads.items()}, shipped, RL.agent_roles()), [])


def test_a22_process_ratchet() -> None:
    """K10-c: audit A22 judges the process ratchet on a fixture tree (the text of each red), and names an old file's missing key."""
    import audit_factory as A
    root = plugin("a22-pr")
    load = RL.static_load("qa-a", plugin_root=root)
    process = load["process_tokens"]
    put = lambda rows, **kw: write(root / "references" / "role-load.json", json.dumps(dict(
        settings_doc(threshold=10 ** 6, ratchets={"qa-a": load["tokens"]}, **kw), **({} if rows is None else {"process_ratchet_tokens": rows}))))
    put({"qa-a": process})
    errors, _info = A._a22_findings(root)
    check_eq("K10-c: the row equal to the process load - A22 is green", [e for e in errors if "process" in e], [])
    put({"qa-a": process - 1})
    errors, _info = A._a22_findings(root)
    check("K10-c: process above the row - red, naming the role and the key", any("qa-a carries" in e and "over its shrink-only process ratchet" in e for e in errors), str(errors))
    put({"qa-a": process + 1})
    errors, _info = A._a22_findings(root)
    check("K10-c: process below the row - red, 'lower to N'", any(f"lower to {process}" in e for e in errors), str(errors))
    put({})
    errors, _info = A._a22_findings(root)
    check("K10-c: no row for the role - red, 'add `qa-a: N`'", any(f"add `qa-a: {process}`" in e for e in errors), str(errors))
    put({"qa-a": process, "qa-gone": 5})
    errors, _info = A._a22_findings(root)
    check("K10-c: a row for a role with no charter - red 'stale row'", any("stale row `qa-gone`" in e for e in errors), str(errors))
    put(None)
    errors, info = A._a22_findings(root)
    check_eq("K10-c: an old file (no key) in a synthetic tree is one info line, no error and no crash", ([e for e in errors if "process" in e], any("no process ratchet" in i for i in info)), ([], True))
    errors, _info = A._a22_findings(root, require_settings=True)
    check("K10-c: ... and in the tree that must have the key it is an error naming the key", any("process_ratchet_tokens" in e and "no process ratchet" in e for e in errors), str(errors))
    shipped_errors, _info = A._a22_findings(RL.PLUGIN_ROOT, require_settings=True)
    check_eq("K10-c: the shipped package is green on the first measurement", shipped_errors, [])


def test_newline_independent() -> None:
    """t-1765 X1 fix-5: the measure of a source does not depend on the checkout's line endings (AR-4). A CRLF copy of the charter,
    the common file and a role file measures the same tokens, craft and process as the LF copy; a lone CR is left as is."""
    charter = ("# qa-a" + NL + NL + "<!-- kind: craft -->" + NL + "## Where bugs hide" + NL + NL + "- a bug" + NL * 2 + "<!-- kind: process -->" + NL
               + "## Tools" + NL + "- a tool" + NL)
    crlf = charter.replace(NL, chr(13) + NL)
    lf_root, crlf_root = plugin("nl-lf"), plugin("nl-crlf")
    for root, text in ((lf_root, charter), (crlf_root, crlf)):
        (root / "agents" / "qa-a.md").write_bytes(text.encode("utf-8"))
        (root / "references" / "common.md").write_bytes(("line" + NL + "line" + NL).replace(NL, chr(13) + NL if text is crlf else NL).encode("utf-8"))
    lf, cr = RL.static_load("qa-a", plugin_root=lf_root), RL.static_load("qa-a", plugin_root=crlf_root)
    check_eq("K-NL: a CRLF copy measures the same total, tokens, craft and process as the LF copy",
             [cr[k] for k in ("total_bytes", "tokens", "craft_tokens", "process_tokens")], [lf[k] for k in ("total_bytes", "tokens", "craft_tokens", "process_tokens")])
    check("K-NL negative control: the raw bytes of the two copies DO differ (without normalisation the measures would)",
          len((crlf_root / "agents" / "qa-a.md").read_bytes()) > len((lf_root / "agents" / "qa-a.md").read_bytes()))
    mixed = (crlf_root / "agents" / "qa-a.md")
    head, tail = charter.split("<!-- kind: process -->", 1)
    mixed.write_bytes((head.replace(NL, chr(13) + NL) + "<!-- kind: process -->" + tail).encode("utf-8"))
    mixed_load = RL.static_load("qa-a", plugin_root=crlf_root)
    check_eq("K-NL edge: a source with mixed line endings measures the same bytes of charter as the LF copy",
             by_name(mixed_load)["charter"]["bytes"], by_name(lf)["charter"]["bytes"])
    lone = lf_root / "agents" / "qa-a.md"
    lone.write_bytes((charter + "a" + chr(13) + "b" + NL).encode("utf-8"))
    check_eq("K-NL edge: a lone CR is left as is (counted, one byte)",
             by_name(RL.static_load("qa-a", plugin_root=lf_root))["charter"]["bytes"], len(charter.encode("utf-8")) + 4)


try:
    test_newline_independent()
    test_craft_split()
    test_a22_process_ratchet()
    test_craft_in_load()
    test_process_ratchet()
    test_kinds()
    test_shape_and_sums()
    test_threshold_edge()
    test_missing_and_project()
    test_story_mode_and_control()
    test_slack_key()
    test_cli_adversarial()
    test_readers()
finally:
    cleanup(TMP)

finish("role_load (the one measure of a role's start load)")
