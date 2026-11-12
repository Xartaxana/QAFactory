"""exploratory_findings.py - the ONE writer and the ONE reader of `work/exploratory-findings.jsonl`.

The register holds what the run saw and could not settle: an observation, an unresolved question, a coverage gap. It is
append-only, one JSON object per line, and an entry is never a product bug, a draft, a triage row or a ledger outcome:
nothing here adds to "proven", "verified" or "Checked by hand" (FR-18). Severity, priority, a bug word or a confirmation
is refused at any depth - a product bug goes through S7 triage and gate B.

    python scripts/exploratory_findings.py add|correct|withdraw|list|check --task-root <story folder> ...

What the role still decides: whether something is worth recording, which kind it is, why it is not a bug, and which
file proves it. Code only names the line (EX-<physical line number>), keeps the chain of a target linear (one active
line per target), measures the evidence hash and the window, and refuses what the register may not hold.

Honest boundary: the chain rule bounds what the SANCTIONED tools do. A role can still write any file through Bash;
read-only is a property of the tool and the prompt, not of the role. Two processes appending at once are not locked: a
duplicated id is detected by `read` (the id differs from the physical line number), not prevented.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C
import hooklib
import install_paths
from role_cli import RefusingParser, run_guarded

SCRIPT = "exploratory_findings.py"
SUBCOMMANDS = ("add", "correct", "withdraw", "list", "check")

OPS = ("add", "correct", "withdraw")
KINDS = ("observation", "unresolved_question", "coverage_gap")
STATUSES = ("unverified", "reproduced", "not_reproduced", "environment_event")
CAPTURE_LESS_STATUSES = ("unverified",)          # F-1: every other status comes only with captures (M3 `record`)
PERSON_CONFIRMED = "person_confirmed"            # the person's `intended` at gate B (a correction by the driver, never a role's word)
ORACLES = ("none", "documented_text_only", "owner_question", PERSON_CONFIRMED)
ROLE_ORACLES = tuple(oracle for oracle in ORACLES if oracle != PERSON_CONFIRMED)    # what a role is told it may write
PERSON_BY = "person"                              # `--by` of the person's word: `person` or `person:<name>`
ORACLE_DEFAULT = {"unresolved_question": "owner_question", "observation": "none", "coverage_gap": "none"}
METHODS = ("api", "ui", "log", "source_read")
WINDOWS = ("pre-gate-a", "s5-s8", "post-s8")
EVIDENCE_KIND = "exploratory_probe"

FIELDS = ("id", "op", "kind", "title", "statement", "refs", "evidence_kind", "probe", "verification_status",
          "oracle_status", "why_not_a_bug", "evidence_refs", "question", "owner_role", "missing_prerequisite",
          "corrects", "withdraws", "origin", "recorded_by", "recorded_at", "window")
# AR-22: fields the register records and nothing downstream reads. They are retro records, read by `exploratory_findings.py list`
# and by nobody else; declared terminal here so a producer without a reader is a named choice, not an accident. Every other field
# has a reader (the report block, the gate B lines, the investigation, the probe).
TERMINAL_FIELDS = ("evidence_kind", "probe.environment", "probe.safe_to_break")
EXCLUDED = ("severity", "priority", "bug", "triage_ref", "confirmation", "impact")
CODE_SET = ("id", "recorded_by", "recorded_at", "window", "evidence_kind")
REQUIRED_TEXT = ("title", "statement", "why_not_a_bug")
WITHDRAW_FIELDS = ("op", "withdraws", "origin")
PROBE_FIELDS = ("method", "runs", "reproduced", "environment", "safe_to_break")
REF_FIELDS = ("path", "sha256")
LINK_FIELDS = ("id", "reason")
ORIGIN_FIELDS = ("dispatch", "target")

MISSING_TEXT = {
    "title": "--title is required: name the finding in one line",
    "statement": "--statement is required: say what was seen, in the words of what was seen",
    "why_not_a_bug": "--why-not-a-bug is required: say why this is not a product bug",
}
BY_TEXT = "--by names who records: the dispatch id you run as, or `person:<name>`"
WINDOW_TEXT = ("the window of this finding cannot be read from pipeline.json; restore the file, then record "
               "(`--task-root` must name the story folder)")


# --- helpers ----------------------------------------------------------------------------------------------------------

def register_path(task_root) -> Path:
    return Path(task_root) / "work" / "exploratory-findings.jsonl"


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _list_text(values) -> str:
    return ", ".join(values)


def _walk_excluded(value, found: list) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in EXCLUDED:
                found.append(key)
            _walk_excluded(inner, found)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            _walk_excluded(inner, found)


def target_of(line: dict) -> str:
    """The investigation target a register line belongs to (`origin.target`), "" when it has none. Pure - the ONE target
    reader; `investigation` and the probe read a target through it (AR-13)."""
    origin = line.get("origin")
    return _text(origin.get("target")) if isinstance(origin, dict) else ""


def chains_of(lines) -> dict:
    """{target: [the lines of that target, in file order]} for the readable `lines` of the register - the ONE derivation of
    "the chain of a target" (a line with no target is in no chain). Pure."""
    out: dict = {}
    for line in lines:
        target = target_of(line)
        if target:
            out.setdefault(target, []).append(line)
    return out


# --- the one reader ---------------------------------------------------------------------------------------------------

def _scan(task_root) -> dict:
    path = register_path(task_root)
    data = path.read_bytes() if path.is_file() else b""
    lines, unreadable, chains, byid, key_of = [], [], {}, {}, {}
    parts = data.split(b"\n") if data else []
    if parts and parts[-1] == b"":
        parts.pop()
    for n, part in enumerate(parts, 1):
        why = ""
        line = None
        try:
            text = part.decode("utf-8")
        except UnicodeDecodeError:
            text, why = "", "not valid UTF-8"
        if not why:
            if not text.strip():
                why = "empty line"
            else:
                try:
                    line = json.loads(text)
                except ValueError:
                    why = "not valid JSON"
        if not why and not isinstance(line, dict):
            why = "not a JSON object"
        if not why and line.get("id") != f"EX-{n}":
            why = f"id is {line.get('id')!r}, expected EX-{n}"
        if not why and line.get("op") not in OPS:
            why = f"op is {line.get('op')!r}, expected one of {_list_text(OPS)}"
        if why:
            unreadable.append((n, why))
            continue
        line["_status"], line["_next"], line["_why"] = "active", "", ""
        ident, op = line["id"], line["op"]
        reference = line.get("corrects") if op == "correct" else line.get("withdraws") if op == "withdraw" else None
        reference = reference if isinstance(reference, dict) else {}
        reason = _text(reference.get("reason"))
        if op == "add":
            key = target_of(line) or ident
        else:
            key = target_of(line) or key_of.get(reference.get("id")) or _text(reference.get("id")) or ident
        key_of[ident] = key
        chain = chains.setdefault(key, {"active": None, "ids": []})
        chain["ids"].append(ident)
        previous = chain["active"]
        if op in ("add", "correct"):
            if previous is not None:
                previous["_status"], previous["_next"], previous["_why"] = "superseded", ident, reason
            chain["active"] = line
        else:
            if previous is not None:
                previous["_status"], previous["_next"], previous["_why"] = "withdrawn", ident, reason
            line["_status"] = "withdraw"
            line["_why"] = reason
            chain["active"] = None
        lines.append(line)
        byid[ident] = line
    return {"lines": lines, "unreadable": unreadable, "chains": chains, "byid": byid, "raw": data,
            "active": {key: chain["active"] for key, chain in chains.items() if chain["active"] is not None}}


def read(task_root) -> dict:
    """The register as it stands: every readable line (with the read-only marks `_status`, `_next`, `_why`), every
    damaged line as `(n, why)`, and `active` - one line per live chain key. Pure. No file, or 0 bytes, is the empty
    register; a damaged line is never dropped and never reported as "none". The chain of a target is `chains_of(lines)`.
    What the role still decides: nothing."""
    scan = _scan(task_root)
    return {"lines": scan["lines"], "unreadable": scan["unreadable"], "active": scan["active"]}


# --- the one writer ---------------------------------------------------------------------------------------------------

def _window(task_root) -> str:
    try:
        pipeline = json.loads((Path(task_root) / "pipeline.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pipeline = None
    if not isinstance(pipeline, dict):
        raise ValueError(WINDOW_TEXT)
    stages = pipeline.get("stages")
    s8 = stages.get("S8") if isinstance(stages, dict) else None
    if C.gate_answered(pipeline, "B") or (isinstance(s8, dict) and s8.get("status") == "done"):
        return "post-s8"
    if not C.gate_answered(pipeline, "A"):
        return "pre-gate-a"
    return "s5-s8"


def _closed(field: str, value, allowed) -> None:
    if value not in allowed:
        shown = "missing" if value is None else repr(value) if not isinstance(value, str) else f"`{value}`"
        raise ValueError(f"`{field}` is {shown}; expected one of {_list_text(allowed)}")


def _nested_keys(label: str, value, allowed) -> None:
    for key in value:
        if key not in allowed:
            raise ValueError(f"`{key}` is not a field of the findings register; the fields of `{label}` are "
                             f"{_list_text(allowed)}")


def _check_probe(probe) -> None:
    if probe is None:
        return
    if not isinstance(probe, dict):
        raise ValueError("`probe` is not an object; expected {method, runs, reproduced, environment, safe_to_break} or null")
    _nested_keys("probe", probe, PROBE_FIELDS)
    _closed("probe.method", probe.get("method"), METHODS)
    for count in ("runs", "reproduced"):
        value = probe.get(count)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"`probe.{count}` is {value!r}; expected a whole number of at least 0")
    if probe.get("safe_to_break") is not None:
        raise ValueError("`probe.safe_to_break` is set; expected null (the register never declares a probe safe)")


def _judge_refs(task_root, refs) -> list:
    """Each evidence ref gets its sha256 measured now when it is missing and names a file under the root, then is judged
    by `contract.evidence_ref_issue` - the one judge; its words are the refusal."""
    root = Path(task_root).resolve()
    out = []
    for ref in refs:
        if isinstance(ref, dict):
            _nested_keys("evidence_refs[]", ref, REF_FIELDS)
            ref = dict(ref)
            raw = _text(ref.get("path"))
            if raw and not ref.get("sha256") and not Path(raw).is_absolute():
                candidate = (root / raw).resolve()
                if candidate.is_relative_to(root) and candidate.is_file():
                    ref["sha256"] = install_paths.sha256_file(candidate)
        issue = C.evidence_ref_issue(task_root, ref, "evidence")
        if issue:
            raise ValueError(issue)
        out.append({"path": ref["path"], "sha256": ref["sha256"]})
    return out


def _link(line: dict, field: str, op: str) -> dict:
    link = line.get(field)
    if not isinstance(link, dict):
        raise ValueError(f"`{field}` is missing: a {op} line names the line it acts on, {{id, reason}}")
    _nested_keys(field, link, LINK_FIELDS)
    if not _text(link.get("reason")):
        raise ValueError(f"--reason is required: say why the line is {'corrected' if op == 'correct' else 'withdrawn'}")
    return {"id": _text(link.get("id")), "reason": link["reason"]}


def _origin(line: dict):
    origin = line.get("origin")
    if origin is None:
        return None
    if not isinstance(origin, dict):
        raise ValueError("`origin` is not an object; expected {dispatch, target}")
    _nested_keys("origin", origin, ORIGIN_FIELDS)
    if not _text(origin.get("dispatch")) or not _text(origin.get("target")):
        raise ValueError("`origin` needs both `dispatch` and `target`: leave --target out for a finding that has none")
    return {"dispatch": origin["dispatch"], "target": origin["target"]}


def append(task_root, line: dict, *, by: str) -> str:
    """Judge `line` and append it to the register; return its id. Every rule broken is a ValueError, and a refused call
    writes NOTHING (the torn-tail repair happens only after every check passed). The id is the physical line number, the
    window comes from pipeline.json, `recorded_by` is `by`, `evidence_kind` is `exploratory_probe` - all set by code.
    What the role still decides: kind, title, statement, why it is not a bug, refs, the question and its owner."""
    if not isinstance(line, dict):
        raise ValueError("a finding is an object; expected {kind, title, statement, why_not_a_bug, evidence_refs, ...}")
    # 1. excluded keys at ANY depth, then keys outside the field list
    found: list = []
    _walk_excluded(line, found)
    if found:
        raise ValueError(f"`{found[0]}` is not a field of the findings register: a product bug goes through S7 triage and "
                         "gate B; record the finding without the field")
    for key in line:
        if key not in FIELDS:
            raise ValueError(f"`{key}` is not a field of the findings register; its fields are {_list_text(FIELDS)}")
    # 2. closed lists
    op = line.get("op")
    _closed("op", op, OPS)
    if op == "withdraw":
        for key in line:
            if key not in WITHDRAW_FIELDS and key not in CODE_SET:
                raise ValueError(f"`{key}` is not carried by a withdraw line: a withdraw names only the line it retracts "
                                 "and the reason")
    else:
        for key in ("withdraws",) if op == "correct" else ("corrects", "withdraws"):
            if key in line:
                raise ValueError(f"`{key}` does not belong to {'an' if op == 'add' else 'a'} {op} line")
        _closed("kind", line.get("kind"), KINDS)
        probe = line.get("probe")
        _check_probe(probe)
        status = line.get("verification_status", "unverified")
        _closed("verification_status", status, STATUSES)
        if probe is None and status not in CAPTURE_LESS_STATUSES:
            raise ValueError(f"`verification_status` is `{status}`; a line with no probe may carry only "
                             f"{_list_text(CAPTURE_LESS_STATUSES)}: a status above that comes from captures "
                             "(`investigation_probe.py record`)")
        oracle = line.get("oracle_status", ORACLE_DEFAULT[line["kind"]])
        if oracle == "confirmed":
            raise ValueError("a confirmed oracle is a case check: it goes through the case and S7, not this register")
        _closed("oracle_status", oracle, ORACLES)
        who_said = _text(by)
        if oracle == PERSON_CONFIRMED and (op != "correct" or not (who_said == PERSON_BY or who_said.startswith(PERSON_BY + ":"))):
            raise ValueError("`person_confirmed` is recorded only on a person's word at gate B, as a correction of the line they "
                             f"answered, with `--by {PERSON_BY}`; a role records the oracle as `{ROLE_ORACLES[-1]}` and lets the "
                             "person confirm it")
    # 3. per-op / per-kind required fields
    if op != "withdraw":
        for field in REQUIRED_TEXT:
            if not _text(line.get(field)):
                raise ValueError(MISSING_TEXT[field])
        if line["kind"] == "unresolved_question" and not (_text(line.get("question")) and _text(line.get("owner_role"))):
            raise ValueError("an `unresolved_question` needs --question and --owner-role")
        if line["kind"] == "coverage_gap" and not _text(line.get("missing_prerequisite")):
            raise ValueError("a `coverage_gap` needs --missing-prerequisite")
        refs = line.get("refs", [])
        if not isinstance(refs, list) or not all(_text(item) for item in refs):
            raise ValueError("`refs` is not a list of ids; expected requirement and case ids such as R-1, TC-2 (may be empty)")
        if not isinstance(line.get("evidence_refs"), list) or not line["evidence_refs"]:
            raise ValueError("--evidence is required: at least one file under the story folder")
    # 4. evidence
    evidence = _judge_refs(task_root, line["evidence_refs"]) if op != "withdraw" else []
    # 5. the chain rule
    scan = _scan(task_root)
    origin = _origin(line)
    target = origin["target"] if origin else ""
    link = None
    if op == "add":
        chain = scan["chains"].get(target) if target else None
        if chain is not None:
            current = chain["active"]["id"] if chain["active"] is not None else chain["ids"][-1]
            raise ValueError(f"target {target} already has line {current}; use `correct` or `withdraw` of it "
                             f"(`{SCRIPT} list --task-root {task_root}` shows the active ids)")
    else:
        link = _link(line, "corrects" if op == "correct" else "withdraws", op)
        acted = scan["byid"].get(link["id"])
        if acted is None or acted["_status"] != "active":
            raise ValueError(f"{link['id'] or 'the named line'} is not an active line (unknown, superseded or withdrawn); "
                             f"`{SCRIPT} list --task-root {task_root}` shows the active ids")
        was = target_of(acted)
        if was != target:
            raise ValueError(f"{link['id']} belongs to target {was}; a correction keeps its target" if was else
                             f"{link['id']} belongs to no target; a correction keeps that: leave --target out")
    # 6. the typed counts of a CLI caller are refused in `main`; a probe reaches here only in-process (C-4)
    # 7. what code sets
    for key in CODE_SET:
        if key in line:
            raise ValueError(f"`{key}` is set by code; leave it out")
    who = _text(by)
    if not who:
        raise ValueError(BY_TEXT)
    window = _window(task_root)
    # 8. build, repair a torn tail, append ONE line
    path = register_path(task_root)
    raw = scan["raw"]
    newline = b"\n"
    ident = f"EX-{raw.count(newline) + (1 if raw and not raw.endswith(newline) else 0) + 1}"
    record: dict = {"id": ident, "op": op}
    if op == "withdraw":
        record["withdraws"] = link
    else:
        record.update(kind=line["kind"], title=line["title"], statement=line["statement"], refs=list(line.get("refs", [])),
                      evidence_kind=EVIDENCE_KIND, probe=line.get("probe"),
                      verification_status=line.get("verification_status", "unverified"),
                      oracle_status=line.get("oracle_status", ORACLE_DEFAULT[line["kind"]]),
                      why_not_a_bug=line["why_not_a_bug"], evidence_refs=evidence)
        for field in ("question", "owner_role", "missing_prerequisite"):
            if _text(line.get(field)):
                record[field] = line[field]
        if link is not None:
            record["corrects"] = link
    if origin:
        record["origin"] = origin
    record.update(recorded_by=who, recorded_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                  window=window)
    hooklib.append_jsonl_line(path, json.dumps(record, ensure_ascii=False))
    return ident


# --- the CLI ----------------------------------------------------------------------------------------------------------

def command_of(script: str, subcommands, argv) -> str:
    """`<script> <sub>` for the first argv word that is one of `subcommands`, else `script` - the registry key of a refusal
    for a CLI with subcommands. The ONE definition: `investigation.py` calls it too. Pure."""
    for token in argv:
        if token in subcommands:
            return f"{script} {token}"
    return script


def _command(argv) -> str:
    return command_of(SCRIPT, SUBCOMMANDS, argv)


def _parser(command: str) -> argparse.ArgumentParser:
    parser = RefusingParser(command=command, prog=SCRIPT, description=__doc__.split("\n\n")[0])
    subs = parser.add_subparsers(dest="sub", required=True, parser_class=RefusingParser)
    for name in SUBCOMMANDS:
        sub = subs.add_parser(name, command=f"{SCRIPT} {name}", help=f"{name} a finding" if name in OPS else name)
        sub.add_argument("--task-root", required=True, help="the story folder (holds pipeline.json and work/)")
        if name in ("list", "check"):
            continue
        sub.add_argument("--by", help=BY_TEXT)
        if name in ("correct", "withdraw"):
            sub.add_argument("--id", help="the ACTIVE line to act on, EX-n")
            sub.add_argument("--reason", help="why")
        if name == "withdraw":
            continue
        sub.add_argument("--kind", help=_list_text(KINDS))
        sub.add_argument("--title")
        sub.add_argument("--statement", help="what was seen, verbatim")
        sub.add_argument("--why-not-a-bug")
        sub.add_argument("--evidence", action="append", help="a file under the story folder (repeatable)")
        sub.add_argument("--refs", help="comma-separated R-n / TC-n ids")
        sub.add_argument("--question")
        sub.add_argument("--owner-role")
        sub.add_argument("--missing-prerequisite")
        sub.add_argument("--target", help="the investigation target id; one chain per target")
        sub.add_argument("--oracle-status", help=_list_text(ROLE_ORACLES))
        sub.add_argument("--verification-status", help="unverified (the rest comes from captures)")
        for hidden in ("--runs", "--reproduced") + tuple("--" + key.replace("_", "-") for key in EXCLUDED):
            sub.add_argument(hidden, help=argparse.SUPPRESS)
    return parser


def _line_from_args(args) -> dict:
    if args.runs is not None or args.reproduced is not None:
        raise ValueError("counts come from captures: `investigation_probe.py record`")
    line: dict = {"op": args.sub}
    for key in EXCLUDED:
        value = getattr(args, key)
        if value is not None:
            line[key] = value
    for field in ("kind", "title", "statement", "why_not_a_bug", "question", "owner_role", "missing_prerequisite",
                  "oracle_status", "verification_status"):
        value = getattr(args, field)
        if value is not None:
            line[field] = value
    if args.refs is not None:
        line["refs"] = [item.strip() for item in args.refs.split(",") if item.strip()]
    line["evidence_refs"] = [{"path": item} for item in args.evidence or []]
    if args.target:
        line["origin"] = {"dispatch": _text(args.by), "target": args.target}
    return line


def _run(argv) -> int:
    args = hooklib.exact_options(_parser(_command(argv))).parse_args(argv)
    task_root = hooklib.story_of(SCRIPT, root=args.task_root, key_flag=None)      # the story first: no phantom folder
    if args.sub == "list":
        state = _scan(task_root)
        shown = {"active": [], "superseded": [], "unreadable": [[n, why] for n, why in state["unreadable"]]}
        for line in state["lines"]:
            shown["active" if line["_status"] == "active" else "superseded"].append(line)
        print(json.dumps(shown, ensure_ascii=True))
        return 0
    if args.sub == "check":
        state = _scan(task_root)
        defects = [f"line {n}: the findings register line cannot be read ({why})" for n, why in state["unreadable"]]
        for line in state["active"].values():
            for ref in line.get("evidence_refs") or []:
                issue = C.evidence_ref_issue(task_root, ref, "evidence")
                if issue:
                    defects.append(f"{line['id']}: {issue}")
        if defects:
            for defect in defects:
                print(f"{SCRIPT} check: {defect}", file=sys.stderr)
            print(json.dumps({"ok": False, "defects": defects}, ensure_ascii=True))
            return 2
        print(json.dumps({"ok": True, "lines": len(state["lines"])}))
        return 0
    by = args.by
    if not _text(by) or _text(by).startswith("code:"):
        raise ValueError(BY_TEXT)
    if args.sub == "withdraw":
        line = {"op": "withdraw", "withdraws": {"id": args.id or "", "reason": args.reason or ""}}
    else:
        line = _line_from_args(args)
        if args.sub == "correct":
            line["corrects"] = {"id": args.id or "", "reason": args.reason or ""}
    if args.sub != "add":
        acted = _scan(task_root)["byid"].get(args.id or "")
        if acted is not None and acted.get("origin") is not None:
            line["origin"] = acted["origin"]
    ident = append(task_root, line, by=by)
    print(json.dumps({"id": ident, "path": str(register_path(task_root))}, ensure_ascii=True))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    return run_guarded(_command(argv), lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
