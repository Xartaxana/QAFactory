#!/usr/bin/env python3
"""SC1-7: a refusal names the field and the command that repairs it (keys K1-K15 of t-1245 section 5.1).

Run 12586 lost 27 scout and 19 tester results to refusals that named neither: an accept without --input was a traceback, a
hand-built accept had no idempotency_key, a batch item without "data" read «artifact must be an object» four times, a usage
line left the role to read --help. The ready command carries what the call gave and a `<...>` placeholder for what the
script cannot know (FR-59) - never a guessed value.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_dir, temp_project)

sys.path.insert(0, str(SCRIPTS))
import artifact_producer as AP  # noqa: E402
import brief_pack as BP  # noqa: E402
import context_bundle as CB  # noqa: E402
from controller import (INPUT_FILE_OPERATIONS, RETURNED, Controller, _cli_story_root, _keys_given,  # noqa: E402
                        apply_door)
from event_store import StateConflict  # noqa: E402

import test_controller_state as BASE  # noqa: E402


def listing(path: Path) -> list:
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


def refusal(call):
    """`(class name, text)` of what `call()` raises; ("", "") when it raises nothing."""
    try:
        call()
    except Exception as exc:       # noqa: BLE001 - the class is part of what is checked
        return type(exc).__name__, str(exc)
    return "", ""


def controller_with_scout(root: Path):
    controller = Controller(root)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    BASE.accept_stage(controller, root, "S0")
    controller.apply("dispatch", {"id": "S1-qa-scout-1", "stage": "S1", "role": "qa-scout", "scope": [],
                                  "input_hash": "s1", "budget": {"requests": 30}, "known_paths": {"root": str(root)},
                                  "idempotency_key": "d-scout"})
    return controller


def controller_keys(root: Path) -> None:
    c = controller_with_scout(root)
    scout = "S1-qa-scout-1"
    # K2: an accept with no idempotency_key names the field, the revision now, and the ready command
    kind, text = refusal(lambda: c.apply("accept", {"id": scout, "status": "accepted"}))
    revision = c.state()["revision"]
    check_eq("K2: the class is the request's (ValueError)", kind, "ValueError")
    check_in("K2: names idempotency_key", "idempotency_key", text)
    check_in("K2: names the current revision", f"(now {revision})", text)
    check_in("K2: names story_step.py finish with the running dispatch", f"story_step.py finish --task {root.name} --dispatch-id {scout}", text)
    check_not_in("K2: the old bare-key phrase is gone for this field", "missing a required field", text)
    kind, text = refusal(lambda: c.apply("initialize", {"scope": ["TC-1"]}))
    check("K2/E6: initialize has no revision to name", kind == "ValueError" and "expected_revision" not in text and "idempotency_key" in text, text)
    # K3: dispatch_id for id; an unknown id; an id that is not a string (E4)
    kind, text = refusal(lambda: c.apply("accept", {"dispatch_id": scout, "status": "accepted", "idempotency_key": "k3"}))
    check_eq("K3: the class stays StateConflict (the driver routes on it, E10)", kind, StateConflict.__name__)
    check("K3: says id is absent and lists the keys given",
          'unknown dispatch' in text and '"id" is absent' in text and "dispatch_id" in text and "idempotency_key" not in text.split("keys given:")[1].split(")")[0], text)
    kind, text = refusal(lambda: c.apply("accept", {"id": "nope", "status": "accepted", "idempotency_key": "k3b"}))
    check("K3: an unknown id is the one text of _unknown_dispatch, at the state class",
          kind == StateConflict.__name__ and text.startswith("unknown dispatch 'nope'; this story has ") and scout in text
          and text == Controller._unknown_dispatch("nope", c.state()["dispatches"])[1], f"{kind}: {text}")
    kind, text = refusal(lambda: c.apply("accept", {"id": ["a"], "status": "accepted", "idempotency_key": "k3c"}))
    check("K3/E4: a list for id is a refusal, never a TypeError", kind == StateConflict.__name__ and "unknown dispatch ['a']" in text, f"{kind}: {text}")
    # K4: the status field
    ref = BASE.evidence_ref(root, "k4.txt")
    kind, text = refusal(lambda: c.apply("accept", {"id": scout, "completion_status": "complete", "evidence_refs": [ref],
                                                    "idempotency_key": "k4"}))
    check("K4: names status, the four values in order, and the unread key",
          kind == "ValueError" and text.startswith("invalid completion status:") and '"status" is absent' in text
          and "accepted, blocked, incomplete, paused" in text and '"completion_status" is not read' in text, f"{kind}: {text}")
    kind, text = refusal(lambda: c.apply("accept", {"id": scout, "status": "done", "evidence_refs": [ref], "idempotency_key": "k4b"}))
    check("K4: a wrong value is shown, the same four values, nothing about an unread key",
          "'done'" in text and "accepted, blocked, incomplete, paused" in text and "is not read" not in text, text)
    # K5 (R8, the Lead's decision 27.10): `unresolved` without `reason` names both fields, what "reason" carries, and the door
    kind, text = refusal(lambda: c.apply("accept", {"id": scout, "status": "accepted", "evidence_refs": [ref],
                                                   "unresolved": ["TC-1"], "idempotency_key": "k5"}))
    check("K5: the class is the request's; names unresolved, reason, the accept-gap words, and the accept door",
          kind == "ValueError" and text.startswith('"unresolved" is given without "reason": "reason" carries why the work is accepted')
          and "accept-gap recorded them" in text and f"story_step.py finish --task {root.name} --dispatch-id {scout}" in text, f"{kind}: {text}")
    check("K5: the old bare sentence is gone", "needs an explicit reason" not in text, text)
    # K6: S1 with unavailable sources and no unresolved gap
    (root / "work").mkdir(exist_ok=True)
    (root / "work" / "source-inventory.json").write_text("{}", encoding="utf-8")
    c.source_inputs = lambda state=None: {"source_completeness": {"complete": False, "unavailable": ["SRC-9"], "pending": ["SRC-7"]}}
    kind, text = refusal(lambda: c.apply("accept", {"id": scout, "status": "accepted", "stage_complete": True,
                                                   "evidence_refs": [ref], "idempotency_key": "k6"}))
    check("K6: keeps the old phrase first, names the sources (pending too), unresolved and reason, and the door",
          kind == StateConflict.__name__ and text.startswith("S1 unavailable sources require explicit unresolved gap handoff")
          and "SRC-9" in text and "SRC-7" in text and '"unresolved"' in text and '"reason"' in text and "story_step.py finish" in text,
          f"{kind}: {text}")
    # S7-5: the door is the PERSON's accept-gap, then a plain finish - never a flag pair a caller types by hand (P13, FR-57)
    check("K6/S7-5: names ticket_adapter.py accept-gap with the inventory and the person's words file",
          "ticket_adapter.py accept-gap --output " in text and "work" in text and "source-inventory.json" in text
          and "--words-file <the file holding the person's own words>" in text, text)
    check("K6/S7-5: does not offer `finish --unresolved ... --reason ...` (a bypass of the person's word)",
          "--unresolved" not in text and "--reason" not in text, text)


def door_keys() -> None:
    story = Path("/stories/QA-1")
    # K7: the dispatch id is never a guess
    two = {"A": {"status": "running"}, "B": {"status": "running"}, "C": {"status": "accepted"}}
    check_in("K7: two running -> one of: A, B", "--dispatch-id <one of: A, B>", apply_door("accept", story, "", two))
    check_in("K7: one running -> its id", "--dispatch-id B", apply_door("accept", story, "", {"B": {"status": "running"}}))
    check_in("K7: none running -> a placeholder that says so", "<no dispatch is running>", apply_door("accept", story, "", {"C": {"status": "accepted"}}))
    check_in("K7: a named dispatch the story has wins over the running one", "--dispatch-id C", apply_door("accept", story, "C", two))
    # S7-4: a role's stop moves its dispatch to RETURNED, and that one is the conductor's normal accept target
    back = {"R": {"status": RETURNED}, "C": {"status": "accepted"}}
    check_in("K7/S7-4: one returned, none running -> the accept door names it", "--dispatch-id R", apply_door("accept", story, "", back))
    check_in("K7/S7-4: one running and one returned -> both are candidates",
             "--dispatch-id <one of: A, R>", apply_door("accept", story, "", {"A": {"status": "running"}, "R": {"status": RETURNED}}))
    check_in("K7/S7-4 (negative control): a checkpoint needs a running dispatch, a returned one is not offered",
             "--dispatch <no dispatch is running>", apply_door("checkpoint", story, "", back))
    check_in("K7/E2: no state known -> a placeholder, not an invented id", "<the dispatch id>", apply_door("accept", story))
    check_eq("E5: no story folder -> no door", apply_door("accept", None), "")
    check_in("the checkpoint door needs no --input", "--status blocked|paused|incomplete", apply_door("checkpoint", story, "B", two))
    check_in("an operation with no special door says where its fields are", "references/controller-api.md", apply_door("policy", story))
    # K8: the key list is cut at 12 and says so (E7)
    twelve = {f"k{i:02d}": 1 for i in range(12)}
    check_not_in("K8: 12 keys are all named, no cut", "more", _keys_given(twelve))
    check("K8: 13 keys name 12 and `and 1 more` (detector_verdict.named, the one list cut)",
          _keys_given(dict(twelve, k12=1)).endswith(" and 1 more") and "k12" not in _keys_given(dict(twelve, k12=1)), _keys_given(dict(twelve, k12=1)))
    check_eq("K8: no keys -> none", _keys_given({}), "none")


def cli_keys(root: Path) -> None:
    story = root / "qa-factory" / "artifacts" / "QA-9"
    (story / "work").mkdir(parents=True)
    (story / "pipeline.json").write_text(json.dumps({"ticket": "QA-9"}), encoding="utf-8")
    before = listing(root)
    out = run_script("controller.py", "--task-root", story, "--operation", "accept", cwd=root)
    check_eq("K1: accept without --input exits 2", out.returncode, 2)
    check_eq("K1: nothing on stdout", (out.stdout or "").strip(), "")
    check("K1: stderr is the JSON refusal naming story_step.py finish, no traceback",
          "Traceback" not in out.stderr and "story_step.py finish --task QA-9" in json.loads(out.stderr)["error"], out.stderr[-400:])
    check_eq("K1: not a byte written to the story folder", listing(root), before)
    out = run_script("controller.py", "--task-root", root / "missing", "--operation", "accept", cwd=root)
    text = json.loads(out.stderr)["error"] if out.stderr.startswith("{") else out.stderr
    check("E5: a missing folder and a missing --input are one refusal, with no door built on a folder that is not there",
          "Traceback" not in out.stderr and "--input" in text and "story_step.py finish" not in text, out.stderr[-400:])
    out = run_script("controller.py", "--task-root", story, "--operation", "checkpoint", "--dispatch", "x", "--status", "blocked",
                     "--reason", "r", "--build-only", cwd=root)
    check("checkpoint without --input is still flags-only (not refused for --input)", "takes its request from --input" not in (out.stderr or ""), out.stderr[-300:])
    # S7-1: the operations that never read --input (they take flags and the person's words) are not refused for it; the
    # request is the driver's closed-story path (story_run: run again / leave) and the doors controller.py prints
    words = story / "state" / "words"
    words.mkdir(parents=True)
    (words / "w.txt").write_text("run it again", encoding="utf-8")
    for op in ("reopen_story", "leave_unlaunched"):
        out = run_script("controller.py", "--task-root", story, "--operation", op, "--dispatch", "S6-x-1",
                         "--words-file", words / "w.txt", cwd=root)
        err = out.stderr or ""
        check(f"S7-1: {op} with --dispatch and --words-file is not refused for a missing --input (it has no --input)",
              "takes its request from --input" not in err and "Traceback" not in err and "initialize task before work" in err, err[-400:])
    # t-1509 (GB-1a): settle_order takes flags (--order, --outcome, --ref, --reason-code) and the person's words, never --input
    out = run_script("controller.py", "--task-root", story, "--operation", "settle_order", "--order", "mr", "--outcome", "cancelled",
                     "--words-file", words / "w.txt", cwd=root)
    err = out.stderr or ""
    check("GB-1a: settle_order with its flags is not refused for a missing --input (it has no --input)",
          "takes its request from --input" not in err and "Traceback" not in err and "initialize task before work" in err, err[-400:])
    # the class: exactly the operations that do `Path(a.input)` unguarded are refused whole, none with a traceback
    for op in INPUT_FILE_OPERATIONS:
        args = argparse.Namespace(task=None, task_root=story, operation=op, input=None)
        problems = _cli_story_root(args)[1]
        check(f"S7-1: {op} without --input is refused for it, naming --input", len(problems) == 1 and "takes its request from --input" in problems[0][1],
              str(problems))
    for op in ("checkpoint", "reopen_story", "leave_unlaunched", "settle_order"):
        problems = _cli_story_root(argparse.Namespace(task=None, task_root=story, operation=op, input=None))[1]
        check(f"S7-1 (negative control): {op} is not in the --input list", all("--input" not in text for _, text in problems), str(problems))
    out = run_script("controller.py", "--task-root", story, "--operation", "baseline-inputs", cwd=root)
    err = out.stderr or ""
    check_eq("S7-1: baseline-inputs without --input exits 2", out.returncode, 2)
    check("S7-1: ... with a refusal that names --input, not a traceback",
          "Traceback" not in err and "takes its request from --input" in json.loads(err)["error"], err[-400:])


def adapter_keys(root: Path) -> None:
    out = run_script("ticket_adapter.py", "peek", "X-1", cwd=root)
    check_eq("K9: peek without --output exits 2", out.returncode, 2)
    err = out.stderr or ""
    check_in("K9: the usage line is the old one", "usage: ticket_adapter.py peek <TICKET> --output <work/source-inventory.json>", err)
    check("K9: followed by the ready command with the call's ticket and a placeholder output",
          "\nready: ticket_adapter.py peek X-1 --output <" in err, err)
    out = run_script("ticket_adapter.py", "collect", "X-1", "--output", "f.json", cwd=root)
    ready = [line for line in (out.stderr or "").splitlines() if line.startswith("ready:")]
    check("K9: collect without --relation: ready carries X-1, --output f.json and a --relation placeholder",
          len(ready) == 1 and "X-1" in ready[0] and "--output f.json" in ready[0] and "--relation <" in ready[0], str(ready))
    outside = re.sub(r"<[^>]*>", "", ready[0] if ready else "")
    check("K9/E2: no path in the ready line that the call did not give",
          not [t for t in outside.split()[3:] if "/" in t or t.endswith(".json") and t != "f.json"], outside)


# Each row: the argv that earns a usage refusal, and text the repeated call must NOT meet (S7-9: the `ready:` line is a second
# carrier of the command's form, next to the `usage:` literal; a line that drops a flag the parser then demands is drift)
READY_ROWS = [
    ("peek",), ("peek", "X-1"), ("collect",), ("collect", "X-1", "--output", "f.json"), ("diff",), ("diff", "--old", "a.json"),
    ("freshness",), ("freshness", "X-1", "--decline", "--words-file", "w.txt"), ("review",),
    ("review", "--record", "--words-file", "w.txt"), ("review", "--late"), ("accept-gap",), ("accept-gap", "--output", "inv.json"),
    ("accept-gap", "--output", "inv.json", "--point", "P1", "--words-file", "w.txt"), ("refresh",), ("inspect",),
    ("inspect", "--output", "inv.json", "--source-id", "S1", "--media-url", "http://x"), ("probe",), ("receipts",), ("assess",),
    ("get",), ("--migrate-method",), (),
]


def ready_filled(ready: str, story: Path) -> list:
    """The argv of a `ready:` line, each `<...>` placeholder replaced by a fixture value of the kind it names."""
    def fixture(match):
        text = match.group(0)[1:-1]
        if text.startswith("one of: "):
            return text[len("one of: "):].split(" - ")[0].split(", ")[0]
        return {"TICKET": "X-1", "get|children": "get", "source id": "SRC-1"}.get(text) or (
            "w.txt" if "words" in text else story.as_posix() if "folder" in text else "fx.json")
    import shlex
    return shlex.split(re.sub(r"<[^>]*>", fixture, ready.split("ticket_adapter.py", 1)[1]))


def ready_roundtrip(root: Path) -> None:
    """S7-9: every `ready:` line of ticket_adapter, filled with fixtures and run again, gets past the usage check."""
    (root / "w.txt").write_text("the person's words", encoding="utf-8")
    story = root / "qa-factory" / "artifacts" / "X-1"       # a placeholder that names the story's folder gets one that exists
    story.mkdir(parents=True)
    (story / "pipeline.json").write_text(json.dumps({"ticket": "X-1"}), encoding="utf-8")
    env ={"CLAUDE_PROJECT_DIR": str(root), "PATH": __import__("os").environ.get("PATH", ""),
           "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    for argv in READY_ROWS:
        first = run_script("ticket_adapter.py", *argv, cwd=root, env=env)
        ready = [line for line in (first.stderr or "").splitlines() if line.startswith("ready:")]
        label = " ".join(argv) or "(no command)"
        check(f"S7-9: `{label}` earns a ready line", len(ready) == 1, (first.stderr or "")[-300:])
        if len(ready) != 1:
            continue
        again = run_script("ticket_adapter.py", *ready_filled(ready[0], story), cwd=root, env=env)
        text = (again.stdout or "") + (again.stderr or "")
        check(f"S7-9: the ready line of `{label}` is a call the parser takes", "ready:" not in text and ": error:" not in text
              and "Traceback" not in text, f"{ready[0]} -> {text[-300:]}")
        if "--point" in argv:      # the usage line says `--shown-text` is required for a point: the ready line carries it
            check("S7-9: accept-gap --point: the ready line carries --shown-text (and not without a point)",
                  "--shown-text" in ready[0] and "--shown-text" not in
                  "\n".join(l for l in run_script("ticket_adapter.py", "accept-gap", "--output", "inv.json", cwd=root, env=env).stderr.splitlines()
                            if l.startswith("ready:")), ready[0])


def bundle_keys(root: Path) -> None:
    impl = {"repo_id": "app"}
    manifest = {"ticket": "QA-2", "implementations": [impl], "changed_areas": ["src"], "constraints": [],
                "existing_coverage": [{"test": "t"}]}
    kind, text = refusal(lambda: CB.build(manifest, root))
    check("K10: a record without source_sha is named in the manifest's own path",
          kind == "ValueError" and "context-manifest.json implementations[0].source_sha: missing - the commit the diff was read at" in text
          and "$.source_revisions" not in text, f"{kind}: {text}")
    # E8 (the Lead's decision): neither field given names the manifest's own field, not the bundle's `$.source_revisions`
    problems = CB._manifest_source_problems({"ticket": "QA-2"})
    check("K10/E8: no implementations at all is ONE problem naming context-manifest.json implementations",
          len(problems) == 1 and problems[0].startswith("context-manifest.json implementations: missing - ")
          and "source_sha" in problems[0], str(problems))
    check_eq("K10/E8: an empty list is the same problem as an absent field",
             CB._manifest_source_problems({"ticket": "QA-2", "implementations": []}), problems)
    check_eq("K10/E8: a value that is not a list is left to the bundle schema (as before)",
             CB._manifest_source_problems({"ticket": "QA-2", "implementations": "x"}), [])
    kind, text = refusal(lambda: CB.build({"ticket": "QA-2"}, root))
    check("K10/E8: the build refusal names the manifest field and not `$.source_revisions`",
          kind == "ValueError" and "context-manifest.json implementations: missing - " in text and "source_revisions" not in text,
          f"{kind}: {text}")
    both = refusal(lambda: CB.build(dict(manifest, implementations=[{"repo_id": "a"}, {"source_sha": 5}]), root))[1]
    check("K10: all problems at once, each at its own index", "implementations[0].source_sha" in both and "implementations[1].source_sha" in both, both)
    # K12: the card's --root is the story folder: only there is work/source-inventory.json read
    story = root / "story"
    (story / "work").mkdir(parents=True)
    (story / "work" / "source-inventory.json").write_text(json.dumps({"schema_version": 1, "sources": []}), encoding="utf-8")
    full = dict(manifest, implementations=[{"repo_id": "app", "source_sha": "abc"}])
    check("K12: --root <task root> gives a bundle with source_inventory_ref", "source_inventory_ref" in CB.build(full, story))
    other = root / "elsewhere"
    other.mkdir()
    check("K12 (negative control): another --root silently has none", "source_inventory_ref" not in CB.build(full, other))
    # S7-6 (E13, the other half): under the card's `--root <task root>` a RELATIVE manifest path resolves against the task
    # root, not the project root. A project-relative path is then `missing` (a stale path, an incomplete grounding): the card
    # and the registry say so, and an absolute path or a task-relative one is `current`.
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (story / "work" / "note.txt").write_text("n\n", encoding="utf-8")
    paths = [{"path": "src/app.py"}, {"path": "work/note.txt"}, {"path": str(root / "src" / "app.py")}]
    built = CB.build(dict(full, known_paths=paths), story)
    states = [entry["status"] for entry in built["known_paths"]]
    check_eq("K12/S7-6: project-relative -> missing; task-relative -> current; absolute -> current", states, ["missing", "current", "current"])
    check("K12/S7-6: the missing path makes the grounding incomplete (stale_paths), visibly",
          built["grounding_complete"] is False and "stale_paths" in built["grounding_gaps"], str(built["grounding_gaps"]))
    scout_card = " ".join(BP.TOOLING["qa-scout"])
    registry = (SCRIPTS.parent / "references" / "role-commands.json").read_text(encoding="utf-8")
    check("K12/S7-6: the card and the registry both say where --root points a relative path",
          "relative known_paths path or diff_path resolves" in scout_card
          and "a relative known_paths path or diff_path in the manifest resolves" in registry, scout_card[-300:])
    out = run_script("context_bundle.py", "--manifest", "m.json", cwd=root)
    check("K10: a missing --output is a refusal through role_cli with the ready command and the card",
          out.returncode == 2 and "Ready: context_bundle.py --manifest m.json --output <" in out.stderr and "what to write:" in out.stderr, out.stderr[-500:])


def card_lines(role: str) -> list:
    return [line for line in BP.TOOLING[role] if line.split()[0] in ("ticket_adapter.py", "context_bundle.py", "artifact_producer.py")]


def materialize(line: str, story: Path) -> tuple:
    """The command of a card line as a role types it, `<...>` filled with fixtures; `[...]` kept, `a|b` -> a."""
    command = line.split(" - ")[0].replace("[", "").replace("]", "")
    command = re.sub(r"<([^>]*)>", lambda m: str(story) if m.group(1) == "task root" else "fx.json", command)
    tokens = [token.split("|")[0] for token in command.split()]
    return tokens[0], tokens[1:]


def card_keys(root: Path) -> None:
    sandbox = temp_dir("sc17-card-")      # no qa-factory/config.json: a read verb stops at "not configured", never the network
    try:
        story = sandbox / "qa-factory" / "artifacts" / "X-1"
        (story / "work").mkdir(parents=True)
        (story / "pipeline.json").write_text(json.dumps({"ticket": "X-1"}), encoding="utf-8")
        (sandbox / "fx.json").write_text(json.dumps({"artifacts": [{"kind": "triage", "path": "work/triage.json", "data": {"triage": []}}]}),
                                         encoding="utf-8")
        env = {"CLAUDE_PROJECT_DIR": str(sandbox), "PATH": __import__("os").environ.get("PATH", ""),
               "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}

        def parses(line: str) -> tuple:
            script, args = materialize(line.replace("<KEY>", "X-1"), story)
            out = run_script(script, *args, cwd=sandbox, env=env)
            text = (out.stdout or "") + (out.stderr or "")
            return "usage:" not in text and "Traceback" not in text, text[-300:]

        lines = card_lines("qa-scout") + card_lines("qa-requirements-tester")
        check("K11: the cards name the scripts under test", len(lines) >= 8, str(len(lines)))
        for line in lines:
            ok, text = parses(line)
            check(f"K11: the card line parses: {line.split(' - ')[0][:90]}", ok, text)
        ok, _ = parses("ticket_adapter.py peek <KEY> - the old card line")
        check("K11 (negative control): the old line `peek <KEY>` is refused as a usage error", not ok)
    finally:
        cleanup(sandbox)


def producer_keys(root: Path) -> None:
    kind, text = refusal(lambda: AP.validate_batch(None))
    result = AP.validate_batch(None)
    detail = result["errors"][0]["detail"]
    check("K13: an artifact sent alone names the batch form and validate --kind",
          '{"artifacts": [{"kind"' in detail and "validate --kind" in detail and not result["valid"], detail)
    bad = [{"kind": "readiness", "path": "work/requirements-readiness.json", "input": "f.json"}]
    result = AP.validate_batch(bad)
    check_eq("K13: an item without data names the key and the keys given",
             result["errors"][0]["detail"], 'artifacts[0]: no "data" (keys given: input, kind, path); "data" holds the artifact object itself')
    check_eq("K13: the code and the shape of the output are the old ones (FR-14)",
             sorted(result["errors"][0]) + sorted(result), ["artifact", "code", "detail", "errors", "repair_fingerprint", "valid"])
    check_eq("K13/E9: the same defect twice has the same fingerprint", AP.validate_batch(bad)["repair_fingerprint"], result["repair_fingerprint"])
    check_in("K13: a kind outside the set names the set", "one of bug, case, readiness, triage",
             AP.validate_batch([{"kind": "x", "path": "p", "data": {}}])["errors"][0]["detail"])
    ok = AP.validate_batch([{"kind": "triage", "path": "work/triage.json", "data": {"triage": []}}])
    check_eq("K13: a right batch is valid", ok["valid"], True)
    # K14: publish over an existing file names the flag and not the hash
    story = root / "qa-factory" / "artifacts" / "QA-4"
    (story / "work").mkdir(parents=True)
    (story / "pipeline.json").write_text(json.dumps({"ticket": "QA-4"}), encoding="utf-8")
    (story / "work" / "triage.json").write_text('{"triage": [], "old": 1}', encoding="utf-8")
    import hashlib
    current = hashlib.sha256((story / "work" / "triage.json").read_bytes()).hexdigest()
    kind, text = refusal(lambda: AP.publish(story, "triage", {"triage": []}, "work/triage.json"))
    check("K14: names --expected-hash and does not print the file's current sha256",
          kind == "ValueError" and "--expected-hash" in text and current not in text and "previous sha256" in text, f"{kind}: {text}")
    # S7-7 / S7-10 (axes 13 and 28): every role whose card names a producer command is a role of its registry entry, and every
    # card line of validate-batch carries the batch form (no role reads `--input <batch.json>` and guesses the shape)
    commands = json.loads((SCRIPTS.parent / "references" / "role-commands.json").read_text(encoding="utf-8"))["commands"]
    for verb in ("validate-batch", "publish"):
        lines = {role: [line for line in cards if line.startswith(f"artifact_producer.py {verb}")]
                 for role, cards in BP.TOOLING.items()}
        carded = sorted(role for role, found in lines.items() if found)
        check(f"S7-7: the roles whose card names {verb} are all roles of its registry entry",
              len(carded) >= 3 and set(carded) <= set(commands[f"artifact_producer.py {verb}"]["roles"]),
              f"{carded} vs {commands[f'artifact_producer.py {verb}']['roles']}")
        if verb == "validate-batch":
            check_eq("S7-10: the tester, the failure analyst and the bug reporter all carry the batch form",
                     sorted(role for role, found in lines.items() if found and '{"artifacts": [{"kind"' in found[0]),
                     carded)
    # K15: a missing --input is a role_cli refusal with the registry's card
    out = run_script("artifact_producer.py", "validate-batch", "--task-root", story, cwd=root)
    check("K15: validate-batch without --input: the card's `what to write`, not bare argparse",
          out.returncode == 2 and "what to write:" in out.stderr and "artifacts" in out.stderr and "--input is required" in out.stderr, out.stderr[-500:])


def main() -> int:
    door_keys()
    root = temp_project("sc17-ctl-")
    try:
        controller_keys(root)
    finally:
        cleanup(root)
    for keys in (cli_keys, adapter_keys, ready_roundtrip, bundle_keys, card_keys, producer_keys):
        root = temp_project("sc17-")
        try:
            keys(root)
        finally:
            cleanup(root)
    return finish("test_refusal_ready_commands")


if __name__ == "__main__":
    sys.exit(main())
