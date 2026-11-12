"""Close a stage: pipeline.json and the journal, in one call.

The orchestrator's bookkeeping was three tool calls per stage — an `Edit` of pipeline.json
(2.1K characters of input on average), a `log_append.py` command, and usually a `Read` to
confirm the edit landed. Measured on TP1-14336: 31 log_append calls, 24 pipeline edits,
10 reads of pipeline.json and 7 of journal.jsonl — about 72 of 472 requests producing
nothing but state, each one re-billing a context that reached 405K tokens. Worse, the two
writes were made by different hands, so a stage could be `done` in one file and unmentioned
in the other.

  stage_done.py --task QA-1 --stage S4 --status done --role qa-case-designer \
                --digest "qa-case-designer S4 done - test-cases/... - new=2 extend=2"
  stage_done.py --task QA-1 --stage S5 --status running --role qa-automator
  stage_done.py --task QA-1 --stage S7 --status done --digest "no failures to triage" --no-journal
  stage_done.py --task QA-1 --set size=L --set implementation_source=diff
  stage_done.py --task QA-1 --warn "S0 vcs_api: no token — `glab auth login`"
  stage_done.py --selftest

`started` is stamped the first time a stage is written and never overwritten; `finished` is
stamped on `done` and `halted`. The journal event is `accepted` for a stage that finished
with a role, `delegated` for one that started, and is skipped for a stage no role ran
(--no-journal, or no --role). Nothing else in this script decides anything: it writes the
two facts and prints what it wrote.
"""
import argparse
import hashlib
import json
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import console_io  # noqa: E402  (the one ASCII fallback)
import detector_verdict as DV  # noqa: E402  (`named`, `one_line`: the one wording of a list inside a line)
import hooklib  # noqa: E402  (`read_json`, the one JSON reader)
from hooklib import artifacts_dir, require_project  # noqa: E402
from person_words import door  # noqa: E402
import runtime_paths as RP  # noqa: E402

STATUSES = ("pending", "running", "done", "halted", "paused", "blocked", "incomplete", "skipped")
EXIT_BAD_ARGS = 2
EXIT_NO_PIPELINE = 4
# The stage IS closed when this code is returned: it says "the story reached its ceiling,
# ask the person", not "the transition failed". `story_budget.STOP_EXIT` is the same number.
STORY_BUDGET_EXIT = 3
# The two stages that stand immediately in front of a human gate.
GATE_STAGES = {"S4": "A", "S8": "B"}
# The head of the S3 exit's one line about the plan's question branches: a structural mark of this code's own output
# (not a phrase list, FR-12). ONE producer (`s3_branch_line`, its fallback line too) and ONE reader
# (`story_step.finish`, which keeps every line that starts with it whatever follows it, AR-21).
S3_REMARK_PREFIX = "S3 remarks:"
# No line of the remark package is longer than this many characters (a host that cuts a long `Read` line would
# lose findings in a file that promises every one); a longer finding wraps on indented lines, it is never cut.
S3_REMARK_LINE_MAX = 1000
# The rework `--reason` of the S3 remark line reaches the role whole through the brief (`brief_pack` shows 200).
S3_REMARK_REASON_MAX = 200


# --- the story facts no script could write -------------------------------------------------
#
# The skill forbids editing `pipeline.json` by hand, and then S0-S2 told the orchestrator to
# put `implementation_source`, `size`, `environment` / `environment_pending`, `parent_feature`
# and every `warnings[]` line INTO that file, because no script offered to. An instruction no
# script can carry out is an instruction carried out by hand — which is how a story ends up
# with `size: "L (large)"`, a `parent_feature` carrying the parent's title, or a warning that
# only ever existed in a message the person read an hour ago. These keys, and no others: a key
# outside this list is refused by name, because the refusal is the whole point of the list.
SETTABLE = {
    # closed lists, spelled as `references/artifact-contract-json.md` spells them
    "implementation_source": ("diff", "current-code", "ungrounded"),
    "size": ("XS", "S", "M", "L", "XL", "XXL"),
    "environment_pending": ("true", "false"),
    # t-017 D3 (B-003): an experiment run that leaves no trace in the project (P8, FR-53). `true`
    # is what `story_run.py --no-trace` records at S0, or accepts on a resume; `false` is the
    # way out (FR-40) for a story that was closed to outward writes by mistake.
    "no_trace": ("true", "false"),
    # The retro is always the full one (owner, 02.10.2026, B-271): a person's word does not shorten or
    # skip it. `numbers` / `skip` are read only from a story an older version recorded.
    "retro_mode": ("full",),
    # open values: a stand name comes from the project's config, a parent key from the ticket
    "environment": (),
    "parent_feature": (),
}
NULL_WORDS = ("null", "none", "")
# The attributes of one entry of `pipeline.sides.<name>` (the record's shape, `contract.story_sides` reads them).
SIDE_ATTRS = ("reality", "deliverable", "settles_by", "reference", "source", "at")


def coerce_value(key: str, raw: str):
    """One `--set key=value`, validated, or a ValueError naming what is allowed."""
    head, _, tail = key.partition(".")
    if head in ("sides", "sides_unknown") and key != "sides":
        # C17 (t-2181): the story's record of its sides. The SIDE NAME is open (AR-2); the attribute list is the record's
        # shape; the reality words are the data file's (AR-1) - a word it does not hold is refused, an unreadable file
        # refuses too (an unknown is never a pass, AR-28). `sides_unknown=` alone clears the mark (FR-40).
        text = str(raw).strip()
        if head == "sides_unknown":
            if tail == "" and text.lower() in NULL_WORDS:
                return None
            if tail in ("at", "why") and text:
                return text
            raise ValueError("`sides_unknown` is cleared with `--set sides_unknown=` and written as "
                             "`--set sides_unknown.at=<time>` and `--set sides_unknown.why=<words>`")
        name, _, attr = tail.partition(".")
        if not name or attr not in SIDE_ATTRS:
            raise ValueError(f"`{key}`: a side is set as `sides.<name>.<attribute>=<value>`, the attribute one of: "
                             + " | ".join(SIDE_ATTRS))
        if attr == "reality":
            from contract import side_realities   # the one reader of the data file (AR-13)
            words = side_realities().get("realities")
            if not isinstance(words, list) or not words:
                raise ValueError(f"`{key}`: the words a reality may take cannot be read from references/side-realities.json - "
                                 "repair that file (a change to the factory); nothing is recorded meanwhile")
            if text not in words:
                raise ValueError(f"`{key}` is one of: " + " | ".join(map(str, words)) + f" - not `{text}`. A side's reality "
                                 "is one of these words; a new word is a change to references/side-realities.json")
            return text
        if attr == "deliverable":
            if text.lower() not in ("true", "false"):
                raise ValueError(f"`{key}` is true or false - the two words, nothing else")
            return text.lower() == "true"
        if text.lower() in NULL_WORDS:
            return "" if attr == "settles_by" else None
        return text
    if key not in SETTABLE:
        raise ValueError(
            f"`{key}` is not a field this script writes. It writes exactly: "
            + ", ".join(sorted(SETTABLE)) + ", `sides.<name>.<attribute>`, `sides_unknown`, and `--warn \"<text>\"` for warnings[]. "
            "Everything else in pipeline.json is written by the script that owns it "
            "(stages here, gates and dispatches by controller.py, overrides and remarks by "
            "waiver.py). A person's word does not widen this list: a key outside the artifact "
            "contract is not a decision to be waived, it is a change to the contract.")
    value = str(raw).strip()
    allowed = SETTABLE[key]
    if key == "retro_mode" and value.lower() in ("numbers", "skip"):
        # before the generic check, so the door is named for exactly these two words (FR-1, FR-2, FR-57)
        raise ValueError(
            "`retro_mode` is always `full`: the retro is always the full one, and a person's word "
            "does not shorten or skip it (B-271). Keep their words as a remark - "
            f"`{door('waiver.py --task <T> --remark --stage S9')}` - the gate B packet and the "
            "MR's open items carry them, and the retro runs whole.")
    if key in ("environment_pending", "no_trace"):
        if value.lower() not in allowed:
            raise ValueError(f"`{key}` is true or false — the two words, nothing else")
        return value.lower() == "true"
    if value.lower() in NULL_WORDS:
        return None  # S0 writes `size: null` / `implementation_source: null` on purpose
    if allowed and value not in allowed:
        raise ValueError(f"`{key}` is one of: " + " | ".join(allowed) + f" — not `{value}`")
    if key == "parent_feature" and len(value.split()) > 1:
        raise ValueError("`parent_feature` is the parent's KEY alone (TP1-1847), never the "
                         "key with its title: the dashboard groups a feature's stories by this "
                         "value, and two spellings split one feature into two")
    return value


def apply_facts(pipeline: dict, sets: dict, warns: list, task_root=None) -> list:
    """Write the validated facts into the pipeline dict; return one line per change made."""
    written = []
    for key, value in sets.items():
        if key == "size" and task_root is not None:
            # One owner for the size fact: `sizing.py` computes it and records both ends of
            # it, so `size_initial`/`size_final` mean the same thing wherever they are read.
            from sizing import record_size
            written.extend(record_size(pipeline, value, task_root))
            continue
        *path, leaf = key.split(".")      # a dotted key (`sides.<name>.<attr>`) is a nested field, never a flat one
        node = pipeline
        for part in path:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        node[leaf] = value
        written.append(f"{key} = {json.dumps(value)}")
    warnings = pipeline.get("warnings") if isinstance(pipeline.get("warnings"), list) else []
    for text in warns:
        line = " ".join(str(text).split())
        if not line:
            continue
        # The same warning twice is the same fact twice in the gate A message.
        if line in warnings:
            written.append(f"warnings[]: already recorded — {line[:60]}")
            continue
        warnings.append(line)
        written.append(f"warnings[] += {line[:60]}")
    if warns or "warnings" not in pipeline:
        pipeline["warnings"] = warnings  # absent is not a legitimate value; empty is
    return written


def current_code_diff_refusal(sets: dict, task: str, task_root) -> str:
    """TR2-7 (B-8, FR-1, FR-2, FR-46, FR-38, AR-9, AR-13): `--set implementation_source=current-code` is refused at the S1 EXIT while a
    `work/impl-diff*.txt` with a non-blank line is on disk - the scout's file, so the scout hears it on its own exit instead of the
    conductor hearing it from the S3 entry (`grounding_table.source_state`, which stays the second net). `""` when the call does not set
    `current-code`, or no diff holds a line. Data only (presence and a non-blank line), never whether the diff is good (AR-29): the ONE
    reader of "a diff is recorded" is `runtime_probe.diff_recorded` (an absent file and a blank one are the same fact, nothing recorded).
    The fault is the story's recorded state, not a malformed call (FR-46); nothing is written."""
    if sets.get("implementation_source") != "current-code":
        return ""
    from runtime_probe import diff_recorded
    if not diff_recorded(Path(task_root)):
        return ""
    return ("stage_done: implementation_source `current-code` is refused: work/impl-diff*.txt holds content, and a story grounded in the "
            "current code writes no diff file. Expected: no diff file with `current-code`, or the source `diff` when the diff is real. "
            "Do: delete the file (`rm work/impl-diff.txt`), then repeat this command; or record the source the file proves: "
            f"`python \"${{CLAUDE_PLUGIN_ROOT}}/scripts/stage_done.py\" --task {task} --set implementation_source=diff`. "
            "Nothing was written.")


def parse_sets(items: list) -> dict:
    out = {}
    for item in items or []:
        key, sep, raw = str(item).partition("=")
        if not sep:
            raise ValueError(f"--set takes key=value, not `{item}`")
        out[key.strip()] = coerce_value(key.strip(), raw)
    return out


# --- the size `work/sizing.json` computed, recorded where it is decided ---------------------------
#
# TP1-13797 (cmp1): `pipeline.json` kept `size: null` from S0 to the end, the report printed "Fact:
# not recorded" for a size the factory had computed at S2, and the retro said forecast and fact were
# unknown. Nothing but the skill's phase text told anybody to call `--set size=`, and the driver never
# does. So the S2 exit records it, and the S9 exit records it for a story that closed S2 before this
# existed. Both report and never stop the story (P1): a size that cannot be computed is one printed line.
# The person's re-sizing (`--set size=`) is an explicit word and always wins; a size already recorded
# is never overwritten.

def record_computed_size(pipeline: dict, task_root: Path, lead: str) -> tuple:
    """(lines written, line to print): the size of `work/sizing.json` (`size_override` if the role set
    one, else `size`) recorded through `sizing.record_size` when the pipeline holds none. `lead` opens
    the printed line ("size not computed" at S2, "size not recorded" at S9). A size already recorded
    returns ([], "") - nothing written, nothing printed."""
    if pipeline.get("size"):
        return [], ""
    path = Path(task_root) / "work" / "sizing.json"
    if not path.is_file():
        return [], f"{lead}: no work/sizing.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("it is not a JSON object")
    except (OSError, ValueError) as exc:
        return [], f"{lead}: work/sizing.json unreadable ({type(exc).__name__}: {str(exc)[:120]})"
    override = str(data.get("size_override") or "").strip()
    field, value = ("size_override", override) if override else ("size", str(data.get("size") or "").strip())
    if not value:
        return [], f"{lead}: work/sizing.json holds no size"
    if value not in SETTABLE["size"]:
        return [], (f"{lead}: work/sizing.json {field} is {json.dumps(value)}, not one of "
                    + " | ".join(SETTABLE["size"]))
    from sizing import record_size
    return record_size(pipeline, value, task_root), ""


def save_size(path: Path, pipeline: dict, lead: str) -> None:
    """Record the computed size (see `record_computed_size`), persist it and print what happened."""
    written, said = record_computed_size(pipeline, path.parent, lead)
    if written:
        from event_store import atomic_json
        atomic_json(path, pipeline)
        print("pipeline.json: " + "; ".join(written))
    if said:
        print(said)


# --- the S9 exit: the report says what the factory recorded --------------------------------------
#
# The S9 exit is the last place a story can be stopped, and on cmp1 the report that reached the person
# said "No product bug is recorded" beside a BUG-1 in the story's folder. `report_facts.check` is pure
# (FR-45) and returns one FR-1 line per problem. A block that differs from a fresh render is NOT refused
# here: when it is the only problem the exit runs the rebuild itself, once (`rebuild_stale_report`; the
# skill road has no driver to run it, t-202 F4), and a refusal the factory's own
# code can repair is not a stop. What is refused is what the rebuild cannot settle by itself: damaged
# markers, gate B words without their block, an item with a missing part, an item that is only the
# factory's own bookkeeping, a report that is not there. Each is the factory's own report, so the door
# is the rebuild or the scribe's rework and never a question to the person (FR-3, FR-42).
REPORT_BLOCK = "report check"
# `report_facts.check` words a stale block as "... differs from a fresh render ..."; the test
# `the_stale_marker_is_the_one_report_facts_prints` pins it against a really stale report.
STALE_MARK = "differs from a fresh render"
STALE_NAME_RE = re.compile(r"block `([^`]+)` " + re.escape(STALE_MARK))


def report_problems(task: str, art: Path) -> dict:
    """{"refusals": [FR-1 lines], "notes": [lines to print and go on], "stale": [block names that differ
    from a fresh render], "crash": "<type>: <why>"}. Reads only; what to say about a stale block is the
    caller's (`s9_exit` knows whether it rebuilt it)."""
    out: dict = {"refusals": [], "notes": [], "stale": [], "crash": ""}
    try:
        import grammar as G
        import report_facts as RF
        import validate_artifacts as V
        path = art / RF.REPORT_NAME
        if path.is_file() and V.is_legacy_report(path):
            out["notes"].append(G.LEGACY_FACTS_LINE)
            return out
        notes: list = []
        found = RF.check(art, notes)
    except Exception as exc:
        out["crash"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return out
    out["notes"] += [str(n) for n in notes]
    for line in found:
        if STALE_MARK in line:
            named = STALE_NAME_RE.search(line)
            out["stale"].append(named.group(1) if named else "a block")
        else:
            out["refusals"].append(f"{REPORT_BLOCK}: {line}")
    return out


def file_finding(path: Path, pipeline: dict, text: str) -> None:
    """One factory finding through the same warn mechanism `--warn` uses (`apply_facts`, then persisted)."""
    try:
        written = apply_facts(pipeline, {}, [text], path.parent)
        from event_store import atomic_json
        atomic_json(path, pipeline)
        print("pipeline.json: " + "; ".join(written))
    except Exception as exc:
        print(f"factory finding not written: {type(exc).__name__}: {str(exc)[:120]}")


def rebuild_stale_report(task: str, art: Path, stale: list) -> dict:
    """The rebuild a stale block waits for, run once (the skill road has no driver to run it). Returns
    {"report": the report_problems of the re-check ({} when the write did not run), "lines": what to
    print}. Writes the report and its history, nothing else (FR-45 stays with `check`): `pipeline.json`
    is not an input of this write. A write that refuses or raises is one printed line and S9 goes on,
    as for a crash of the check: a stale block is the factory's own, never a stop (P1)."""
    door = f"`report_facts.py --task {task} --write`"
    names = ", ".join(f"`{n}`" for n in stale)
    try:
        import report_facts as RF
        result = RF.write(art)
    except Exception as exc:
        return {"report": {}, "lines": [f"report: block {names} is stale; the rebuild could not run: "
                                        f"{type(exc).__name__}: {str(exc)[:160]} - run {door} by hand"]}
    if not result.get("ok"):
        return {"report": {}, "lines": [f"report: block {names} is stale; the rebuild could not run:"]
                + [str(line) for line in result.get("lines") or []]}
    again = report_problems(task, art)
    lines = [str(line) for line in result.get("lines") or []]
    lines.insert(0, f"report: block {names} was stale; rebuilt now by {door}")
    return {"report": again, "lines": lines}


def refresh_stale_summary(art: Path) -> list:
    """The lines to print after the delivery summary was brought up to the report, once (RD1-20; the pattern of
    `rebuild_stale_report`): `[]` when the summary agrees with the report's "Left with you" section, or there is none to
    compare. The comparison lives in `delivery_summary.left_with_you_stale`, NOT in `report_facts.check`: the callers of the
    check write the report before the summary, so a refusal there would be false every time. A write that fails is one
    printed line and S9 closes (the summary is the factory's own, never a stop, P1)."""
    try:
        import delivery_summary as DS
        if not DS.left_with_you_stale(art):
            return []
        DS.write(art)
    except Exception as exc:
        return [f"report: the delivery summary is older than the report and could not be rewritten: "
                f"{type(exc).__name__}: {str(exc)[:160]} - run `delivery_summary.py --task-root {art}` by hand"]
    return ["report: the delivery summary quoted a different \"Left with you\" than the report; rewritten now"]


def s9_exit(task: str, path: Path, pipeline: dict) -> int:
    """The size, then the report check. 0 lets S9 close; EXIT_BAD_ARGS refuses it.

    HF8-22 (L-E): the refusal this exit prints is also LEFT where `waiver.py --block` reads it (`state/standing-refusal.json`, THE
    writer `waiver.write_standing`, the driver's own): on the skill road there is no driver to leave it, and a person's word
    recorded against `report check` read `unknown` ("cannot say the block is lifted"). A refusal records `{S9, the problems, the
    door `report check`}`; a close erases the record when it is S9's (`waiver.drop_standing`, another stage's is left). A record
    that cannot be written or erased is one printed line, never a change of the exit (FR-41)."""
    code, blocking = _s9_report_exit(task, path, pipeline)
    from waiver import drop_standing, write_standing
    try:
        if code and blocking:
            write_standing(task, "S9", blocking, [REPORT_BLOCK], root=path.parent)
        elif not code:
            drop_standing(task, "S9", root=path.parent)
    except OSError as exc:
        print(f"note: the record of the standing refusal could not be kept ({exc}); a word recorded against it reads "
              f"as not verified", file=sys.stderr)
    return code


def _s9_report_exit(task: str, path: Path, pipeline: dict) -> tuple:
    """`(exit code, the refusing lines)` of the S9 exit: the body of `s9_exit`."""
    save_size(path, pipeline, "size not recorded")
    found = report_problems(task, path.parent)
    if found["crash"]:
        # Our own crash is never the story's fault: said out loud, filed, and S9 closes.
        print(f"report check could not run: {found['crash']}")
        file_finding(path, pipeline, f"S9 report check could not run: {found['crash']}")
        return 0, []
    if found["stale"] and not found["refusals"]:
        # The skill road reaches this exit with nobody having run the rebuild: a stale block only (the
        # gate B words arrived after the scribe, a count moved) is rebuilt here, once, and S9 goes on.
        # With a refusal beside it nothing is written: the refusal is what the door is for, and a write
        # over damaged markers refuses itself.
        rebuilt = rebuild_stale_report(task, path.parent, found["stale"])
        for line in rebuilt["lines"]:
            print(line)
        found = rebuilt["report"] or dict(found, stale=[])
        if found.get("crash"):
            print(f"report check could not run: {found['crash']}")
            file_finding(path, pipeline, f"S9 report check could not run: {found['crash']}")
            return 0, []
        if found.get("stale"):   # the render does not settle: said, never a refusal
            print("report: block " + ", ".join(f"`{n}`" for n in found["stale"])
                  + " still differs from a fresh render after the rebuild; S9 goes on")
    else:
        for name in found["stale"]:
            print(f"report: block `{name}` is stale; it was not rebuilt because the report also has a problem "
                  f"the rebuild cannot settle (below)")
    for note in found["notes"]:
        print(note)
    from waiver import split_overridden
    blocking, passed = split_overridden(found["refusals"], pipeline, "S9")
    if blocking:
        print(f"stage_done: S9 closes the story, and test-report.md does not hold what the factory recorded "
              f"({len(blocking)} problem(s)):\n" + "\n".join("  - " + line for line in blocking)
              + f"\nExpected: a report whose code-owned blocks match the facts, with its gate B block once "
                f"gate B has words, and whose \"Left with you\" and \"Not proven\" items are well formed. "
                f"Doors: `report_facts.py --task {task} --write` rebuilds the code-owned blocks (the appendix included) "
                f"and S8 is never reopened for one of them; `story_step.py start --task {task} --stage S8 --role "
                f"qa-doc-scribe` sends the report back to the scribe only for a missing report, damaged markers or the "
                f"scribe's own \"Left with you\" items. Then record S9 again. This is the "
                f"factory's own report: do not put it to the person as a question. If a person decided to "
                f"close the story anyway, their recorded word passes it: `waiver.py --task {task} --stage S9 --block "
                f"\"{REPORT_BLOCK}\" --decision \"<their words>\"`.", file=sys.stderr)
        return EXIT_BAD_ARGS, blocking
    for line in refresh_stale_summary(path.parent):
        print(line)
    if passed:
        print("stage_done: closing S9 past " + f"{len(passed)} report check problem(s) on the person's word: "
              + "; ".join(dict.fromkeys(p["decision"] for p in passed)), file=sys.stderr)
        for p in passed:  # FR-4: a pass over the factory's own block is filed in the person's words
            file_finding(path, pipeline, f"S9 report check passed by the person's word "
                                         f"({' '.join(str(p['decision']).split())[:120]}): {p['error'][:160]}")
    return 0, []


def gate_rehearsal_errors(task_root: Path, gate: str) -> list:
    """The `factory_fixable` findings of the gate rehearsal, as plain error strings, each followed by its command when it has one.

    `gate_rehearsal_pairs` is the one reader; the finish path asks it directly, because the waiver matches a person's
    word against the error's text and a command (machine paths, flags) must never widen that match (EP1-24 F4)."""
    return [error + command for error, command in gate_rehearsal_pairs(task_root, gate)]


def gate_rehearsal_pairs(task_root: Path, gate: str) -> list:
    """The `factory_fixable` findings of the gate rehearsal as `(error text, command)` pairs; `command` is "" or ` [command: ...]`.

    Only that class: a `person_decides` finding is a question FOR the gate and must not stop
    the stage that carries it there, and a `factory_defect` is stated in the packet with the
    command that passes it. A rehearsal that cannot run at all never blocks a stage — an
    unavailable check is reported by `gate_preflight` itself, and a story in flight is not
    refused over a check this build does not have."""
    try:
        import gate_preflight
        result = gate_preflight.run(task_root, gate)
    except Exception as exc:
        print(f"stage_done: the gate {gate} rehearsal could not run ({type(exc).__name__}: "
              f"{exc}); the stage closes without it", file=sys.stderr)
        return []
    # The prefix is what the refusal's own door advises as the block word (`--block "gate
    # rehearsal"`): `split_overridden` matches a block word against the error's text, and a
    # finding's message never said it, so the person's word recorded under that door passed
    # nothing and S4 / S8 stayed refused (found in the legacy-2406 migration, W3-D).
    return [("gate rehearsal: " + f["message"] + (f" [fix: {f['fix']}]" if f.get("fix") else ""), _rehearsal_command(f))
            for f in result.get("findings") or []
            if f.get("class") == gate_preflight.FACTORY_FIXABLE]


COMMAND_CHECKS = ("s5_runtime_probe",)   # the checks whose finding's `argv` is a command for whoever closes the stage (EP1-24 F2)


def _rehearsal_command(finding: dict) -> str:
    """EP1-24 B3: the command a finding's typed `argv` field holds, as ` [command: ...]`, or "". A road with no driver
    has nobody to run a repair, and the refusal that says "the factory registers this itself" gave the role no way to.
    ONLY a check in `COMMAND_CHECKS` (F2): the reporter's `argv` is the helper's own line, ending `--by driver`, which a
    role is refused (PT-human-word) and a conductor would write as a false author. The argv goes through
    `runtime_probe.resolve_argv` first (the config's portable form means THIS machine's interpreter and plugin).
    INVARIANT (as `probe_move`): an argv that is not a list of strings, or still holds a `{token}` after that, is NOT
    shown - a command with a brace word in it is not one anybody can run - and the refusal keeps its reason without it;
    a finding with no `argv`, or of another check, is the same bytes as before."""
    argv = finding.get("argv")
    if finding.get("check") not in COMMAND_CHECKS:
        return ""
    if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
        return ""
    try:
        import runtime_probe
        import shlex
        resolved = [str(a) for a in runtime_probe.resolve_argv(argv)]
        if any(runtime_probe.UNKNOWN_TOKEN_RE.search(a) for a in resolved):
            return ""
        return f" [command: {shlex.join(resolved)}]"
    except Exception:
        return ""


def s3_remark_line(text: str) -> str:
    """The one spelling of the S3 remark head: every line of the S3 branch check (a finding or a "not checked") is made here,
    so `finish` keeps all of them by the one prefix (FR-41, AR-13, AR-28)."""
    return f"{S3_REMARK_PREFIX} {text}"


def s3_branch_line(task_root: Path) -> str:
    """The S3 exit's one printed line about the plan's question branches, or "" (nothing to say).

    Open-questions wiring (R1, R7): the strategist writes `question_refs` / `if_answered`, and the
    same pure check the gate rehearsal runs before gate A (`planning_contract.variant_errors`) is run
    here too, while the strategist's session is still the one that can repair the row. It REPORTS and
    never refuses: the rehearsal at the S4 exit refuses, as it does today, and a second refusal on the
    same fact would be a duplicate stop (FR-7). It writes into the plan and the register nothing (FR-45):
    the one file it writes is the derived package `state/findings/s3-remarks-*.md` (`_s3_remark_package`, E11),
    which holds EVERY finding at once, so one repair round names all of them. The cases do not exist yet
    at this stage, so only the plan's rows are read and every finding is the strategist's. A story with
    no `question_refs` / `if_answered` anywhere (one from before this contract) says nothing (builder
    rule 9); a plan or a register that cannot be read is ONE line and never an exception (P1). The line
    with findings opens with `S3_REMARK_PREFIX`, the package-less fallback too."""
    try:
        import planning_contract
        plan = planning_contract.story_plan_path(task_root)
        if plan is None:
            return s3_remark_line("question branches not checked: the story has no work/test-plan.json")
        plan_bytes = plan.read_bytes()
        rows = json.loads(plan_bytes.decode("utf-8-sig"))
        if isinstance(rows, dict):
            rows = rows.get("rows") or []
        created = planning_contract.plan_created(task_root)   # t-261 (O12): a plan dated on/after the cutoff
        if not isinstance(rows, list) or not planning_contract.has_branch_fields(rows, (), created):
            return ""
        import question_register
        view = question_register.load(task_root)
        questions = list(view.get("questions") or [])
        if not questions:
            why = ((view.get("problems") or [""])[0]
                   or ("the story has no work/requirements-readiness.json"
                       if not view.get("register_present") else "the register lists no question"))
            return s3_remark_line(f"question branches not checked: the register's questions could not be read ({why})")
        mode, coverage_version = planning_contract.story_contract_mode(task_root)
        found = planning_contract.variant_errors(rows, questions, (), plan_contract_mode=mode,
                                                 coverage_contract_version=coverage_version,
                                                 plan_created=created)
        # t-227b (F14), widened by RN1-2: every strategist branch kind in `S3_EXIT_KINDS` is REFUSED at the S3 exit by
        # `planning_contract.detector_main`, not reported here. A stage that closes anyway closed on a person's recorded word, and
        # a line telling the strategist to repair what that word passed would contradict the pass (FR-4, P13). A kind the exit
        # only WARNS about (`S3_WARN_KINDS`) is no remark round either: the S4 rehearsal, which sees the cases, is its refuser.
        found = [item for item in found if item.get("kind") not in planning_contract.S3_EXIT_KINDS + planning_contract.S3_WARN_KINDS]
    except Exception as exc:
        return s3_remark_line(f"question branches not checked ({type(exc).__name__}: {str(exc)[:160]})")
    if not found:
        return ""
    wheres = list(dict.fromkeys(item["where"] for item in found if item.get("where")))
    # E12: a row with no id is named in the package but never in `--rows` (the controller would refuse it as not in the plan)
    ids = [place for place in wheres if not _NO_ID_ROW.fullmatch(place)]
    rel, why, written = _s3_remark_package(task_root, found, plan_bytes, wheres)
    size, cap = _s3_over_cap(written) if rel else (0, 0)
    reason = _s3_reason(rel, bool(size)) if rel else "<the finding(s) above, within 200 characters>"
    # E2: the head names the first rows; the door's `--rows` names ALL of them, so it runs as printed (FR-2)
    command = (f"controller.py --task-root \"{task_root}\" --operation rework --stage S3 --role qa-test-strategist"
               + (f" --rows {','.join(ids)}" if ids else "") + f" --reason \"{reason}\" --brief")
    then = (f"`{command}`, then `story_step.py materialize`, and {rework_launch_text('S3')}. "
            "The gate rehearsal at the S4 exit stops on the same facts if they are left.")
    head = s3_remark_line(f"{len(found)} question-branch finding(s) the strategist can repair on "
                          f"{DV.named(wheres, where=rel or None) or 'the plan'}")
    if not rel:     # E5 / M6: the findings travel inline and the line still opens with the prefix (FR-41, AR-28)
        return (f"{head} (the remark package was not written: {why}): "
                + "; ".join(DV.one_line(item["message"]) for item in found) + " - one repair round: " + then)
    over = (f"The package is {size} bytes, over the whole-read limit {cap}: read it with Read offset/limit. "
            if size else "")
    return f"{head} - every one, with the plan rows to repair named: {rel}. {over}One repair round: {then}"


def rework_launch_text(stage: str) -> str:
    """How the card of a rework of `stage` is launched, by the stage's `rework_mode` (`contract.rework_mode`, the one
    reader): the S3 remark line and the refusal of `--status running` say it from here and carry no rule of their own.
    An unreadable value of the field is said as the reader's own sentence, never read as either mode (FR-1)."""
    try:
        import contract
        mode = contract.rework_mode(stage)
    except ValueError as exc:
        return f"launch it as the stage's rework_mode says, which cannot be read ({exc})"
    if mode == "fresh":
        return ("launch the card as a NEW agent (a fresh dispatch reads only the findings and the lines it needs; "
                "never SendMessage into the author's session)")
    return ("launch the card by resuming the stage's agent: SendMessage the delta to the agent id pipeline.json "
            "records for it")


_NO_ID_ROW = re.compile(r"row\[\d+\]")


def _s3_reason(rel: str, big: bool) -> str:
    """The rework `--reason` of the remark line: the package, and the narrowing (a fresh dispatch reads that file and
    the rows it names, not the whole plan), in `S3_REMARK_REASON_MAX` characters so the brief shows it whole. Past
    the ceiling (a very long ticket key) the narrowing goes and the package stays: the path is what cannot be left out."""
    full = (f"repair every finding in {rel}; read only it and the plan rows it names"
            + ("; it is over the read limit: Read offset/limit" if big else ""))
    return full if len(full) <= S3_REMARK_REASON_MAX else f"repair every finding in {rel}"


def _s3_over_cap(written: Path) -> tuple:
    """`(size, cap)` of the written package (`written`, the path `_s3_remark_package` returns) when it is over the
    whole-read limit (`guard_pre_tool.big_read_cap`, the ONE reader of it), else `(0, 0)`. A limit that cannot be read
    is `0`, "not checked": the number is never typed here."""
    try:
        import guard_pre_tool
        from hooklib import load_config
        cap = guard_pre_tool.big_read_cap(load_config())
        size = Path(written).stat().st_size
    except Exception:  # noqa: BLE001 - the error direction is "no added sentence"; the package itself is whole
        return 0, 0
    return (size, cap) if cap > 0 and size > cap else (0, 0)


def _story_rel(task_root: Path, sub: str) -> str:
    """A path of the story spelled from the project root, the way every path a role reads is spelled (FR-37, AR-8)."""
    return f"qa-factory/artifacts/{Path(task_root).name}/{sub}"


def _s3_remark_package(task_root: Path, found: list, plan_bytes: bytes, wheres: list) -> tuple:
    """`(project-relative path of the package, "", its path on disk)`, or `("", exception name, None)` when it could not
    be written. `wheres` is the caller's list of the places the findings name (computed once, in `s3_branch_line`).

    ONE file `state/findings/s3-remarks-<sha12>.md` holds EVERY finding whole (a finding longer than
    `S3_REMARK_LINE_MAX` wraps on indented lines, it is never cut) and the plan rows to repair by id; where a row sits
    in the plan is not computed here - the map is SC1-3's (`plan_row.py --show/--map`, `Grep -n` and `Read` windows).
    The name is the sha of the body WITHOUT its time, so the same plan bytes and findings are the same file (E6), and
    a file that is already there is kept (it may be open in a role's reader). It is a derived file in
    `state/findings/`, like `exit_gate.render_saved`; the plan and the register are not touched (FR-45, E11). The write
    is `install_paths._atomic_write` (temp beside, flushed, `os.replace`, the plan writer's own): a failure of any
    kind is the second value, and the caller prints the findings inline (AR-28)."""
    try:
        from install_paths import _atomic_write
        task = Path(task_root).name
        plan_rel = _story_rel(task_root, "work/test-plan.json")
        lines = ["## Findings"]
        for item in found:
            lines += textwrap.wrap(DV.one_line(item["message"]), width=S3_REMARK_LINE_MAX, initial_indent="- ",
                                   subsequent_indent="  ", break_long_words=True, break_on_hyphens=False) \
                or ["- (the finding has no message)"]
        lines += ["", "## Rows",
                  f"Plan rows to repair, by id, in {plan_rel}. A row's lines move after any edit, so find a row afresh: "
                  "`Grep -n` its quoted id in the plan, then `Read` with `offset`/`limit`; with a shell, "
                  f"`python \"${{CLAUDE_PLUGIN_ROOT}}/scripts/plan_row.py\" --task {task} --show --row <id>` prints a "
                  "row with its line numbers and `--map` lists every row."]
        lines += [f"- {place}: no id; locate it by its position in the plan's rows" if _NO_ID_ROW.fullmatch(place)
                  else f"- {place}" for place in wheres]
        lines += ["", f"Repair every finding above in {plan_rel}, then return your digest. Each finding names the field "
                      "and the value it expects; read only the plan rows named above."]
        head = f"# {len(found)} S3 question-branch finding(s), plan sha256 {hashlib.sha256(plan_bytes).hexdigest()[:12]}"
        body = "\n".join(lines) + "\n"
        name = "s3-remarks-" + hashlib.sha256((head + "\n" + body).encode("utf-8", "replace")).hexdigest()[:12] + ".md"
        target = Path(task_root) / "state" / "findings" / name
        if not target.is_file():
            _atomic_write(target, f"{head}, {now_iso()}\n{body}".encode("utf-8", "replace"))
        return _story_rel(task_root, f"state/findings/{name}"), "", target
    except Exception as exc:  # noqa: BLE001 - P1: the stage's exit never raises over a report
        return "", type(exc).__name__, None


def story_budget_stop(task: str) -> bool:
    """Has this story reached the ceiling its project set? A closed stage is where we ask.

    0.7.7 review, D-F12: the ceiling printed one line on stderr and exited 0, which is a
    line an orchestrator walks straight past — the pilot spent past its own ceiling without
    anyone being asked. The stage is already recorded when this runs: the stop is the
    question that follows it, never a lost transition. `story_budget` ships with another
    package and may not be installed yet, and no story is failed by a budget check that
    cannot run. The person's word passes it like every other block, inside `enforce`.
    """
    try:
        import story_budget
        return story_budget.enforce(task) != 0
    except Exception:
        return False


def _defer_refresh(store, task_root, stage: str) -> None:
    """Make the commit this call is about to make leave the dashboard and metrics for the story's next event.

    `--status running` is called twice for every dispatch (`story_step start` and `bind`) and the store's
    `after_commit` step re-rendered the dashboard and the metrics after each: about 57 s of a launch on a story
    copy (CX2-3 item 6). Only the RENDER is deferred (SC1-12): the transition is still written to `pipeline.json`
    and the journal under the lock, before this step would have run, and the next refresh (the stage's `done`, a
    controller commit, the cost hook) reads them from disk. Until then `state/dashboard-deferred.json` says the view is
    stale and how to refresh it now (FR-41, AR-28: a stale view is always named). A marker that cannot be written is one
    printed line and changes nothing else: the transition is already durable. Called AFTER every refusal of `run`
    (a refused call leaves no trace) and before the commit or the recover of the same transition (both run the step).
    The door in the reason names the story by its KEY (`--task <KEY>`), never a folder path: a story copied to another
    worktree carries this file along, and an absolute path in it would send `recover` to the OLD folder (t-304 N1, AR-4).
    A marker `controller.refresh_derived` left because the refresh FAILED (it carries `error`, or the held `file`) is
    kept as it stands: the view is already named stale, and the record of why is the one fact not to lose (t-1329 Q-2)."""
    marker = Path(task_root) / "state" / "dashboard-deferred.json"

    def failure_recorded() -> bool:
        held = hooklib.read_json(marker, {}, kind=dict)       # absent or unreadable: nothing to keep, our own marker is written
        return bool(held.get("error") or held.get("file"))

    def deferred():
        try:
            if failure_recorded():
                return
            from event_store import atomic_json
            atomic_json(marker, {"status": "deferred", "owner": "factory",
                                 "reason": f"stage {stage} running: the dashboard and metrics refresh at the story's next "
                                           f"recorded event; controller.py --task {Path(task_root).name} --operation recover "
                                           "refreshes them now"})
        except Exception as exc:  # noqa: BLE001 - the transition is durable; a marker is never worth failing it
            print(f"dashboard: deferral marker not written ({type(exc).__name__}: {exc})")

    store.after_commit = deferred


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- a stage that finished before it started -------------------------------------------------
#
# TP2-2553's "Run Timeline" carried S0 started at 13:20:00Z and finished at 11:42:43Z.
# `retro_numbers.span_seconds` clamped the negative span with `max(0, ...)`, so the retro
# printed a stage nobody could time as taking no time, and no validator anywhere said a word.
# A clock is a fact, not a decision: the record is still written, the reversal is stamped on it
# here, and every reader downstream names the stage and both stamps instead of reading a zero.
# It is never a block and never a question to the person — the clock is the factory's own.
CLOCK_PAIRS = (("stage_started", "stage_finished"), ("started", "finished"),
               ("started_at", "finished_at"))


def _clock_moment(value):
    """Epoch seconds or ISO-8601, whichever the writer stamped; None when neither parses."""
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _clock_text(value) -> str:
    """The stamp as a person can read it: an epoch is rendered, a written string is kept."""
    moment = _clock_moment(value)
    if isinstance(value, (int, float)) and moment is not None:
        return moment.isoformat(timespec="seconds")
    return str(value)


def clock_anomaly(entry) -> dict | None:
    """{started_at, finished_at} when a stage record finished before it started, else None.

    Both spellings of the pair are checked — the epoch one the controller writes and the ISO
    one this script writes — because a story carries whichever its stage went through."""
    if not isinstance(entry, dict):
        return None
    for start_key, end_key in CLOCK_PAIRS:
        start, end = _clock_moment(entry.get(start_key)), _clock_moment(entry.get(end_key))
        if start is not None and end is not None and end < start:
            return {"started_at": _clock_text(entry.get(start_key)),
                    "finished_at": _clock_text(entry.get(end_key))}
    return None


def clock_anomalies(pipeline) -> list:
    """[(stage, {started_at, finished_at})] over a whole pipeline.json, in stage order.

    Recomputed rather than read off `clock_anomaly` stamps, so a story written by an earlier
    0.7.x — which stamped nothing — is named by the same readers."""
    stages = (pipeline or {}).get("stages") if isinstance(pipeline, dict) else None
    if not isinstance(stages, dict):
        return []
    return [(str(sid), found) for sid, found in
            ((sid, clock_anomaly(entry)) for sid, entry in sorted(stages.items())) if found]


def read_pipeline(path: Path) -> dict:
    """The pipeline object in `path`, else {}. The `{}` is written here, in the `def`: `apply_stage` mutates the one it is given."""
    return hooklib.read_json(path, {}, kind=dict, errors=Exception)


def apply_stage(pipeline: dict, stage: str, status: str, role: str, digest: str,
                at: str, agent_id: str = "") -> dict:
    stages = pipeline.setdefault("stages", {})
    if not isinstance(stages, dict):
        stages = pipeline["stages"] = {}
    entry = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
    entry["status"] = status
    # A controller-managed stage is opened by a dispatch event, not by a `running` call here,
    # so the first call this script sees may be the halt. `started` then comes from the
    # dispatch clock; stamping it with `at` made a 17-minute S1 look like it began at its halt.
    opened = entry.get("stage_started")
    if isinstance(opened, (int, float)) and opened > 0 and "started" not in entry:
        entry["started"] = datetime.fromtimestamp(opened, timezone.utc).isoformat(timespec="seconds")
    entry.setdefault("started", at)
    if status in ("done", "halted", "skipped"):
        entry["finished"] = at
    else:
        entry.pop("finished", None)
    # halts[] is written here, in code: it was an instruction to the orchestrator, and a story
    # that halted three times carried `halts: []`.
    halts = pipeline.get("halts") if isinstance(pipeline.get("halts"), list) else []
    if status == "halted":
        halts.append({"stage": stage, "reason": digest or f"{role or stage} halted", "at": at,
                      "resolved": False})
    elif status in ("running", "done", "skipped"):
        for halt in halts:
            if isinstance(halt, dict) and halt.get("stage") == stage and not halt.get("resolved"):
                halt.update(resolved=True, resolved_at=at)
    pipeline["halts"] = halts
    entry["role"] = role or entry.get("role") or None
    if agent_id:
        # The dispatch's own id, so a follow-up can go back to THAT agent instead of
        # opening a fresh one: a critic confirming its own fix notes answers from the
        # review it already did (s5.md), for a fraction of a second review round.
        entry["agent_id"] = agent_id
    if digest:
        entry["digest"] = digest
    entry.setdefault("digest", "")
    # The transition is never refused over a clock (see CLOCK_PAIRS above): the record is
    # written, and a reversed pair rides along with it so the retro, validate_artifacts and
    # the story listing name the stage instead of printing a clamped zero.
    anomaly = clock_anomaly(entry)
    if anomaly:
        entry["clock_anomaly"] = anomaly
    else:
        entry.pop("clock_anomaly", None)
    stages[stage] = entry
    # The stage that finishes a story says so in the story's own file. Until 0.7.13 nothing
    # did, and TP2-2534 — gate B approved, S8 done, MR merged, suite green — still
    # read as a running story to every reader for two days (I-92). The rule is
    # `hooklib.story_closed`; this only records what it already reads, once.
    try:
        from controller import stamp_closure
        stamp_closure(pipeline, at=at)
    except Exception:
        pass  # a stamp that cannot be written never fails the transition it describes
    return pipeline


def journal_event(task: str, stage: str, status: str, role: str, digest: str) -> dict | None:
    """The one event this stage transition is worth. A stage with no role ran no dispatch,
    so there is nothing to accept or delegate."""
    if not role:
        return None
    if status == "running":
        return {"event": "delegated", "agent": role, "task": task}
    if status == "done":
        return {"event": "accepted", "agent": role, "task": task, "by": "qa-story",
                "notes": digest or f"{role} {stage} done"}
    if status == "halted":
        return {"event": "halt", "task": task,
                "reason": digest or f"{role} halted at {stage}", "agent": role}
    return None


def write_journal(spec: dict) -> str:
    import log_append
    record = log_append.build_record(spec)
    problems = log_append.validate(record)
    if problems:
        return "journal NOT written: " + "; ".join(problems)
    log_append.write([record])
    return ""


def print_boundary_notice(task: str, stage: str, status: str) -> str:
    """The one sanctioned place to ask for a new window is a closed stage.

    The window ran out one step before gate A and the person got a restart instruction
    instead of the gate question. `window_budget.boundary_notice` decides whether the
    remaining budget covers the next stage; it ships with another package and may not be
    installed yet, and a stage that is already closed on disk is never failed by a notice.
    """
    if status != "done":
        return ""
    try:
        from window_budget import boundary_notice
        notice = boundary_notice(task, stage)
    except Exception:
        return ""
    if isinstance(notice, str) and notice.strip():
        print(notice)
    else:
        notice = ""
    try:  # a closed stage starts the window's turn count afresh, like a compact does
        from turn_budget import reset as reset_turn_counter
        import window_budget as _wb
        sid = _wb.live_session()
        if sid:
            reset_turn_counter(sid, None, "stage_closed")
    except Exception:
        pass  # a reset that fails never blocks the stage from closing
    # The story's own ceiling used to be READ here and printed with exit 0, which is a stop
    # line an orchestrator walks straight past (0.7.7 review, D-F12). `story_budget_stop`
    # below now both prints it and returns the exit code, and each threshold warns once — so
    # this must not consume that marker first.
    return notice


def set_facts(task: str, sets: dict, warns: list) -> int:
    """`--set` / `--warn` with no stage transition to carry them: S0 records a warning the
    moment it learns it, S1 sets `implementation_source` before it accepts its dispatch."""
    require_project("stage_done")
    path = artifacts_dir(task) / "pipeline.json"
    pipeline = read_pipeline(path)
    if not pipeline:
        print(f"stage_done: no pipeline.json at {path} — S0 writes it before anything is "
              "recorded in it; this script never creates a story", file=sys.stderr)
        return EXIT_NO_PIPELINE
    refusal = current_code_diff_refusal(sets, task, path.parent)
    if refusal:
        print(refusal, file=sys.stderr)
        return EXIT_BAD_ARGS
    written = apply_facts(pipeline, sets, warns, path.parent)
    from event_store import atomic_json
    atomic_json(path, pipeline)
    print("pipeline.json: " + ("; ".join(written) if written else "nothing to write"))
    return 0


def reviewed_row_rule(author: str, author_role: str) -> str:
    """TR4-1 (F1, FR-38, AR-22): the ONE wording of the rule `reviewed_author_dispatch` applies - the brief line, both refusals and the
    handoff templates say it with this text (a template, which cannot call it, is pinned to it by a test)."""
    return (f"the LAST `inputs_read` row naming a {author_role} dispatch must be `path: work/handoffs/{author}.yaml` "
            f"(other {author_role} forms go above it; a review binds only that dispatch)")


def reviewed_author_dispatch(form, state, stage_def) -> str:
    """The id of the author's dispatch a stage critic's form says it REVIEWED (t-1815 F4): the last entry of `inputs_read` whose `path` is
    `work/handoffs/<id>.yaml` for an `<id>` that is a dispatch of this stage's author role in `state`; `""` when the form names none (the
    caller refuses, naming the field). Reads the form's declared input, never judges it: the binding is then compared with the author's last
    accepted dispatch by `acceptance.stage_acceptance_errors`, so a form that reviewed OLDER work is refused there."""
    roles = [str(r) for r in (stage_def or {}).get("roles") or []]
    stage = str((stage_def or {}).get("id") or "")
    rows = form.get("inputs_read") if isinstance(form, dict) else None
    dispatches = (state or {}).get("dispatches") or {}
    found = ""
    for row in rows if isinstance(rows, list) else []:
        path = str(row.get("path") or "").replace("\\", "/") if isinstance(row, dict) else ""
        match = re.fullmatch(r"(?:\./)?work/handoffs/([^/]+)\.yaml", path)
        d = dispatches.get(match.group(1)) if match else None
        if isinstance(d, dict) and roles and d.get("stage") == stage and d.get("role") == roles[0]:
            found = match.group(1)
    return found


def record_acceptance(task: str, stage: str, form: str, acceptor: str = "", verdict: str = "", quote: str = "") -> int:
    """`--acceptance <the stage critic's handoff form>`: append ONE round to `pipeline.json` `acceptance[<stage>]` (X2-5; THE writer, AR-14).
    Not a stage transition: the record is a fact the stage's close reads (`controller.validate`, `acceptance.stage_acceptance_refusal`).
    The record is built from the form's header verdict word and its `stage_acceptance` section, or, with `--acceptor driver --verdict
    accept --quote <the gap>`, from the conductor's own word; it is checked by `acceptance.stage_acceptance_errors` before it is written
    (form and binding only - what the verdict means is the critic's, never read here). The same record again writes nothing."""
    require_project("stage_done")
    path = artifacts_dir(task) / "pipeline.json"
    pipeline = read_pipeline(path)
    if not pipeline:
        print(f"stage_done: no pipeline.json at {path} - S0 writes it before any stage closes; this script never creates a story",
              file=sys.stderr)
        return EXIT_NO_PIPELINE
    import acceptance
    from controller import Controller
    stage_def = acceptance.stage_def_of(stage)
    if not stage_def.get("roles"):
        print(f"stage_done: {stage} has no roles in references/stages.json; a stage acceptance is recorded for a stage with `acceptance_by` (S2, S3, S4, S6)",
              file=sys.stderr)
        return EXIT_BAD_ARGS
    form_path = Path(form)
    if not form_path.is_absolute():
        form_path = path.parent / form
    state = Controller(path.parent).state()
    author = acceptance.stage_author_dispatch(state, stage_def)
    author_role = str(stage_def["roles"][0])
    from datetime import datetime as _datetime
    at = _datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    try:
        rel = form_path.resolve().relative_to(path.parent.resolve()).as_posix()
    except ValueError:
        print(f"stage_done: --acceptance {form!r} is not under the task root {path.parent}; expected work/handoffs/<dispatch>.yaml",
              file=sys.stderr)
        return EXIT_BAD_ARGS
    if (acceptor or verdict or quote) and acceptor != acceptance.DRIVER_ACCEPTOR:
        print("stage_done: --verdict and --quote go with --acceptor driver only; the stage critic's word comes from its form",
              file=sys.stderr)
        return EXIT_BAD_ARGS
    reviewed = ""
    if acceptor == acceptance.DRIVER_ACCEPTOR:
        if verdict != "accept" or not quote.strip():
            print("stage_done: --acceptor driver records an accept with the gap in words: --verdict accept --quote \"<the gap>\" "
                  "(a reject is the stage critic's word, from its form)", file=sys.stderr)
            return EXIT_BAD_ARGS
        record = {"stage": stage, "role": author_role, "acceptor": acceptance.DRIVER_ACCEPTOR, "reviewed_dispatch": author,
                  "verdict": "accept", "failure_class": None, "quote": quote.strip(),
                  "witness_paths": [rel] if form_path.is_file() else [], "at": at}
        problems = []
    else:
        if not form_path.is_file():
            print(f"stage_done: the stage critic's form {rel} does not exist; expected work/handoffs/<critic dispatch>.yaml", file=sys.stderr)
            return EXIT_BAD_ARGS
        import handoff
        try:
            data = handoff.parse(form_path.read_text(encoding="utf-8")).data
        except (OSError, ValueError) as exc:
            print(f"stage_done: the stage critic's form {rel} could not be read ({type(exc).__name__}: {exc})", file=sys.stderr)
            return EXIT_BAD_ARGS
        dispatch = (state.get("dispatches") or {}).get(form_path.stem)
        critic = str((dispatch or {}).get("role") or ((data or {}).get("header") or {}).get("role") or "")
        # X7-6: the form of a CONSUMER role (the failure analyst, a dispatch of the NEXT stage) accepts the author's stage; any other
        # dispatch of another stage is still refused. A clean `accept` carries no quote (legal for a consumer, `stage_acceptance_errors`).
        consumer = acceptance.consumer_of(stage)
        if isinstance(dispatch, dict) and dispatch.get("stage") != stage and not (consumer and dispatch.get("role") == consumer):
            print(f"stage_done: {form_path.stem} is a dispatch of {dispatch.get('stage')}, not of {stage}"
                  + (f" and not of {consumer}, which accepts {stage}" if consumer else ""), file=sys.stderr)
            return EXIT_BAD_ARGS
        # t-1815 F4: the record is bound to the dispatch the critic REVIEWED - the author's form its `inputs_read` names - never to the
        # author's CURRENT last dispatch (an `ok` given before a rework would otherwise close newer work nobody read). Unknown -> refusal.
        reviewed = reviewed_author_dispatch(data, state, stage_def)
        if not reviewed:
            if author:
                print(f"stage_done: the stage critic's form {rel} does not say which dispatch of {author_role} it reviewed: "
                      f"{reviewed_row_rule(author, author_role)}; your brief names the id on its `Reviewed dispatch:` line; "
                      f"then record it again", file=sys.stderr)
            else:
                print(f"stage_done: the stage critic's form {rel} does not say which dispatch of {author_role} it reviewed: no "
                      f"accepted dispatch of {author_role} exists at {stage} yet, so no review can be recorded; the conductor dispatches "
                      f"{author_role} first, then a new stage critic; meanwhile say in `unresolved` that there is nothing to review and "
                      f"name no path", file=sys.stderr)
            return EXIT_BAD_ARGS
        record, problems = acceptance.stage_acceptance_from_form(
            data, stage=stage, role=author_role, acceptor=critic, reviewed_dispatch=reviewed, witness_form=rel, at=at)
    if record is not None:
        problems = acceptance.stage_acceptance_errors(record, stage_def=stage_def, author_dispatch=author)
    if problems and reviewed and author and reviewed != author:
        problems.append(f"the last row of the form that names a dispatch of {author_role} is '{reviewed}'; {reviewed_row_rule(author, author_role)}")
    if problems:
        print("stage_done: the stage acceptance was not recorded: " + "; ".join(problems), file=sys.stderr)
        return EXIT_BAD_ARGS
    rounds = pipeline.setdefault("acceptance", {})
    if not isinstance(rounds, dict):
        rounds = pipeline["acceptance"] = {}
    held = rounds.get(stage) if isinstance(rounds.get(stage), list) else []
    last = acceptance.stage_acceptance(pipeline, stage)
    if last and {k: v for k, v in last.items() if k != "at"} == {k: v for k, v in record.items() if k != "at"}:
        print(f"pipeline.json: acceptance {stage} is already recorded (no change)")
        return 0
    rounds[stage] = held + [record]
    from event_store import atomic_json
    atomic_json(path, pipeline)
    print(f"pipeline.json: acceptance {stage} -> {record['verdict']} by {record['acceptor']} for {author}")
    return 0


def _append_journal(event):
    """Write the shared-journal line a committed stage transition owes (B-318), OUTSIDE the history lock.

    `log_append.write` takes the `.journal-writer` lock and dedupes on `source_event_id` under it: it is the
    one reader of that key, so nothing is re-read here. No `journal_record` on the event: no append (E-E3).
    A failure is one line on stderr and the event stays committed (E-E1): a projection never rolls back a fact.
    Residual (E-E2): a process that dies between the commit and this append leaves the line missing until the
    same transition is replayed (`stage_done` again recovers the event and appends); it can never leave two
    lines for one event, because the dedupe key is the event id."""
    if not event:
        return
    rec = (event.get("payload") or {}).get("journal_record")
    if not rec:
        return
    try:
        import log_append
        log_append.write([dict(rec, source_event_id=event["event_id"])])
    except Exception as exc:
        print(f"stage_done: the stage is recorded, but its journal line was not written "
              f"({type(exc).__name__}: {exc}); run the same stage_done command again to write it",
              file=sys.stderr)


def run(task: str, stage: str, status: str, role: str, digest: str, no_journal: bool,
        agent_id: str = "", sets: dict | None = None, warns: list | None = None,
        wait_seconds: float = 0.0, *, dispatch_id: str = "") -> int:
    """`wait_seconds`: how long the commit waits for an in-flight story writer. Chosen by `main`
    (the command line) and 0 for any other caller, so a hook that calls `run` never waits.

    `dispatch_id`: the controller dispatch the agent of `agent_id` runs (`story_step bind` names it). It
    rides in the transition's PAYLOAD only, and only when non-empty: `identity` and the idempotency key
    are unchanged, so a transition without it has the key it always had (the projection then puts the
    agent id on no dispatch)."""
    require_project("stage_done")
    path = artifacts_dir(task) / "pipeline.json"
    pipeline = read_pipeline(path)
    if not pipeline:
        print(f"stage_done: no pipeline.json at {path} — S0 writes it before any stage "
              "closes; this script never creates a story", file=sys.stderr)
        return EXIT_NO_PIPELINE
    # Before the stage checks: a warning or a size this call carries belongs to the state the
    # gate rehearsal below reads, and a refused stage must not swallow the fact it was given.
    refusal = current_code_diff_refusal(sets or {}, task, path.parent)
    if refusal:
        print(refusal, file=sys.stderr)
        return EXIT_BAD_ARGS
    facts_written = apply_facts(pipeline, sets or {}, warns or [], path.parent)
    if facts_written:
        from event_store import atomic_json as _atomic_json
        _atomic_json(path, pipeline)
        print("pipeline.json: " + "; ".join(facts_written))
    # Right after `apply_facts`, so the person's `--set size=` of this same call is already in the
    # pipeline and is never overwritten by the computed size (the explicit word beats the computed one).
    if stage == "S2" and status == "done":
        save_size(path, pipeline, "size not computed")
    if stage == "S1" and status == "done":
        from source_preflight import check_source_inventory
        source_check = check_source_inventory(path.parent, pipeline)
        from waiver import split_overridden
        blocking, passed = split_overridden(source_check["errors"], pipeline, "S1")
        if blocking:
            print("stage_done: S1 source inventory incomplete: " + "; ".join(blocking),
                  file=sys.stderr)
            return EXIT_BAD_ARGS
        if passed:
            print("stage_done: S1 continues past block(s) the person passed: " +
                  "; ".join(p["error"] for p in passed), file=sys.stderr)
        if source_check["gaps"]:
            print("stage_done: S1 continues with explicit source gap(s): " +
                  "; ".join(source_check["gaps"]), file=sys.stderr)
    # The stage in front of a gate does not close while the factory still owes itself a repair.
    # TP1-15045: S4 was closed, gate A was asked, and only then did the factory discover —
    # four times over — things it had known since the S4 exit. `factory_fixable` is exactly the
    # set it can repair by its own code without asking anybody, so it repairs them first and the
    # person is addressed once. Nothing here is the person's to mend: their word passes it the
    # way it passes every other block in this factory.
    if stage in GATE_STAGES and status == "done":
        pairs = gate_rehearsal_pairs(path.parent, GATE_STAGES[stage])
        from waiver import split_overridden
        # the waiver is matched on the error's own text; the command is added back to what is PRINTED (EP1-24 F4)
        blocking, passed = split_overridden([error for error, _command in pairs], pipeline, stage)
        commands = dict(pairs)
        blocking = [error + commands.get(error, "") for error in blocking]
        if blocking:
            gate = GATE_STAGES[stage]
            print(f"stage_done: {stage} stands in front of gate {gate}, and the rehearsal "
                  f"(`gate_preflight.py --task {task} --gate {gate}`) still has "
                  f"{len(blocking)} thing(s) the FACTORY has to repair before anyone is asked: "
                  + "; ".join(blocking[:4])
                  + ". Repair them, then close the stage. If a person decided to go to the gate "
                    "anyway: `" + door(f"waiver.py --task {task} --stage {stage} --block "
                                       "\"gate rehearsal\"") + "`.", file=sys.stderr)
            return EXIT_BAD_ARGS
        if passed:
            words = list(dict.fromkeys(p["decision"] for p in passed))
            print(f"stage_done: closing the stage past {len(passed)} rehearsal finding(s) on the "
                  "person's word: " + "; ".join(words), file=sys.stderr)
    # The retro is the last thing a story does, so a stage still `running` when it ends is a
    # tail nobody will ever come back to. TP2-2534 ended exactly so, and for two days
    # that tail made the stage guard count two running stories and refuse every dispatch of
    # the live one as ambiguous (I-92). This is the factory's own bookkeeping to repair, not
    # the person's: `recover` settles it in one command, and their word passes it like any
    # other block.
    if stage == "S9" and status in ("done", "skipped"):
        running = [name for name, entry in sorted((pipeline.get("stages") or {}).items())
                   if name != stage and isinstance(entry, dict) and entry.get("status") == "running"]
        from waiver import split_overridden
        blocking, passed = split_overridden([f"{name} is still running" for name in running],
                                            pipeline, stage)
        if blocking:
            print(f"stage_done: S9 closes the story, and {'; '.join(blocking)} — a finished "
                  f"story must not leave a stage anybody is still waiting on. Settle it with "
                  f"`controller.py --task-root {path.parent} --operation recover`, then record "
                  "S9 again. If a person decided to close it anyway: `" +
                  door(f"waiver.py --task {task} --stage S9 --block \"still running\"") + "`.",
                  file=sys.stderr)
            return EXIT_BAD_ARGS
        if passed:
            print("stage_done: closing S9 over a running stage on the person's word: " +
                  "; ".join(p["decision"] for p in passed), file=sys.stderr)
    # The report check stands AFTER the running-tail block (a story with a tail is refused for the tail
    # first: the report of a story still being worked is not the question) and BEFORE the journal
    # validation and every write below (a refused report never reaches the journal).
    if stage == "S9" and status in ("done", "skipped"):
        refused = s9_exit(task, path, pipeline)
        if refused:
            return refused
    at = now_iso()
    # Validate the journal before touching the pipeline. Previously a malformed
    # accepted event could leave the stage done while the journal rejected it.
    spec = None if no_journal else journal_event(task, stage, status, role, digest)
    record = None
    if spec:
        import log_append
        record = log_append.build_record(spec)
        problems = log_append.validate(record)
        if problems:
            print("stage_done: " + "; ".join(problems), file=sys.stderr)
            return 1
    from event_store import atomic_json, content_hash, EventCommitted
    # The controller's own store: after the commit (or the recover) releases the story lock it
    # refreshes the dashboard, which used to be rendered inside `project` below, under the lock.
    from controller import Controller
    controller = Controller(path.parent, wait_seconds=wait_seconds)
    store = controller.store
    events_before = store.read()
    managed = any(event.get("type") == "initialize" for event in events_before)
    # In controller-managed tasks a `done` projection is evidence of a prior accepted
    # dispatch, never an alternate way to complete S5 (or any other gated stage).
    if status == "done" and managed:
        from controller import Controller
        managed_state = Controller(path.parent).state()
        # X7-6 (E-B11): a stage judged by a CONSUMER closes by that record, never by the author's finish; with no `acceptance_by` nothing here.
        import acceptance as _acceptance
        owed = _acceptance.consumer_close_refusal(pipeline, managed_state, stage)
        if owed:
            from waiver import split_overridden as _split
            blocking, passed = _split([owed], pipeline, stage)
            if blocking:
                print("stage_done: " + owed + " Or a person's word: `" + door(f"waiver.py --task {task} --stage {stage} --block \""
                                                                             f"{_acceptance.STAGE_ACCEPTANCE_PHRASE}\"") + "`.", file=sys.stderr)
                return EXIT_BAD_ARGS
        if managed_state.get("stages", {}).get(stage, {}).get("status") != "completed":
            from waiver import split_overridden
            blocking, passed = split_overridden(
                [f"{stage} has no accepted controller stage"], pipeline, stage)
            if blocking:
                # TP1-15045 follow-up: the bare sentence left a Sonnet orchestrator with
                # nowhere to go on S0, which no role runs and which therefore can never be
                # `accept`ed. Every refusal in this factory names its remedy and the way a
                # person's word passes it; this one named neither.
                # The door is the controller's own `apply_door("accept")` (SC1-7, AR-13: one text): `story_step.py
                # finish`, which writes the whole request, with the id of the stage's ONLY open dispatch and a
                # `<one of: ...>` / `<no dispatch is running>` placeholder otherwise - never a guess (SC1-12, E3).
                from controller import apply_door
                accept_door = apply_door("accept", path.parent, "", {
                    did: entry for did, entry in (managed_state.get("dispatches") or {}).items()
                    if isinstance(entry, dict) and entry.get("stage") == stage})
                print(f"stage_done: {stage} is a controller-managed stage and the controller "
                      f"has not accepted it, so `--status done` would record a completion no "
                      f"evidence stands behind. A stage a ROLE ran is closed by accepting its "
                      "dispatch first. " + accept_door + " "
                      "A stage NO role runs (S0) is closed BEFORE `--operation initialize` — "
                      "see phases/s0.md §9 — or, once the task is already initialized, with a "
                      "`code_only` receipt. If a person decided to close it anyway: "
                      "`" + door(f"waiver.py --task {task} --stage {stage} --block \"no "
                                 "accepted controller stage\"") + "`.", file=sys.stderr)
                return EXIT_BAD_ARGS
            print("stage_done: closing a stage the controller has not accepted, on the "
                  "person's word: " + "; ".join(p["decision"] for p in passed), file=sys.stderr)
    # The other half of that rule, and the deadlock it cost. On TP1-15045 the plan had to
    # go back to the strategist, so the orchestrator ran `--status running` on an S3 the
    # controller had already accepted. The stage was lowered, `--status done` then refused it
    # for the rule above, and the story could move neither forward nor back one step before
    # gate A. Reworking an accepted stage never requires lowering it.
    bind_only = False
    if status == "running" and managed:
        from controller import Controller
        running_state = Controller(path.parent).state()
        if running_state.get("stages", {}).get(stage, {}).get("status") == "completed":
            # HF9-1: a REPAIR dispatch exists only after its stage was accepted, and its agent id is learned only
            # after the launch (`story_step.py bind`). A call that names a dispatch the controller holds `running`
            # ON THIS STAGE, with a non-blank agent id, is a bind and nothing else: it writes the agent id and
            # reopens nothing (the stage stays completed, no `rework` sub-state). Position: after every refusal
            # above and BEFORE the person's-word split below, so a recorded waiver "already accepted by the
            # controller" is neither read nor spent on a bind (a person's reopen word is never used up by it).
            # Every other `running` call on a completed stage - no dispatch id, an unknown or another stage's
            # one, an accepted or superseded one, a blank agent id - keeps the refusal below, byte for byte.
            named = running_state.get("dispatches", {}).get(dispatch_id) if dispatch_id else None
            if (isinstance(named, dict) and named.get("status") == "running" and named.get("stage") == stage
                    and isinstance(agent_id, str) and agent_id.strip()):
                bind_only = True
        if not bind_only and running_state.get("stages", {}).get(stage, {}).get("status") == "completed":
            from waiver import split_overridden
            blocking, passed = split_overridden(
                [f"{stage} is already accepted by the controller"], pipeline, stage)
            if blocking:
                print(f"stage_done: {stage} is already accepted by the controller, and "
                      "--status running would un-complete it — after that `--status done` "
                      "refuses the stage and the story can go neither forward nor back "
                      "(TP1-15045). Nothing has to be reopened to rework an accepted "
                      "stage: rework it with `controller.py --task-root <TASK_ROOT> --operation "
                      f"rework --stage {stage} --brief ...` (recorded as rework without lowering the stage), "
                      f"then `story_step.py materialize`, and {rework_launch_text(stage)} - how a "
                      "rework reaches its role is the stage's `rework_mode` in references/stages.json "
                      "(a long session resumed costs about twice per turn, B-070). A changed "
                      "plan is recorded with `controller.py --task-root <TASK_ROOT> "
                      "--operation revise_plan`. If a person decided to reopen it anyway: "
                      "`" + door(f"waiver.py --task {task} --stage {stage} --block "
                                 "\"already accepted by the controller\"") + "`.", file=sys.stderr)
                return EXIT_BAD_ARGS
            print("stage_done: reopening an accepted stage on the person's word: " +
                  "; ".join(p["decision"] for p in passed), file=sys.stderr)
    # The test repository's base is recorded here, once (B-207): after every refusal above, so a
    # refused S0 records nothing, and before the transition is written, so no exit below skips
    # it. It reports and never stops the story: any failure is one printed line and S0 closes
    # exactly as it would have.
    if stage == "S0" and status == "done":
        try:
            import test_repo_base
            from hooklib import load_config, project_root
            print(test_repo_base.s0_line(path.parent, project_root(), load_config()))
        except Exception as exc:
            print(f"test repository base not recorded: {type(exc).__name__}: {exc}")
    # The plan's question branches, said once while the strategist can still repair them (R1, R7). It
    # stands after every refusal above, like the S0 line: it reports and never stops the stage - the
    # rehearsal at the S4 exit is the one that refuses, and two stops on one fact would be a duplicate.
    if stage == "S3" and status == "done":
        line = s3_branch_line(path.parent)
        if line:
            try:
                print(line)
            except UnicodeEncodeError:  # a console that cannot spell a word of the plan: say it plainly
                print(console_io.ascii_only(line))
    # Every refusal above (SC1-1's S3 line included) is behind us; the commit or the recover below is next. A `running`
    # transition does not re-render the view it cannot have changed (SC1-12, E15-E20); every other status renders as ever.
    if status == "running":
        _defer_refresh(store, path.parent, stage)
    identity = {"task": task, "stage": stage, "status": status, "role": role,
                "digest": digest, "agent_id": agent_id}
    key = "stage:" + content_hash(identity)
    previous = events_before[-1] if events_before and events_before[-1]["idempotency_key"].startswith(key) else None
    # A later invalidation/transition permits the same status with a new receipt.
    if not previous:
        key += ":" + str(len(events_before))
    if bind_only:
        # Only the agent id: status, started/finished, halts[] and the digest of the accepted stage stay as they are.
        stages = pipeline.setdefault("stages", {})
        if not isinstance(stages.get(stage), dict):
            stages[stage] = {}
        stages[stage]["agent_id"] = agent_id.strip()
    else:
        apply_stage(pipeline, stage, status, role, digest, at, agent_id)
    # A durable event precedes both projections. Replaying it never runs an agent.
    payload = dict(identity, pipeline=pipeline, journal_record=record)
    if dispatch_id:
        payload["dispatch_id"] = dispatch_id
    if bind_only:
        payload["bind_only"] = True
    def project(events):
        event = next(e for e in reversed(events) if e["type"] == "stage_transition")
        projected = event["payload"]["pipeline"]
        # A stage transition owns the stage model and nothing else. Its payload is a whole
        # snapshot, so replaying an earlier one used to roll the rest of the story back with
        # it: `--set size=L` after that transition, a waiver's `stage_overrides[]`, a remark —
        # all written straight to the file by their own owners, all silently restored to what
        # they were when this stage closed. On disk is newer than any snapshot, so on disk wins.
        current = read_pipeline(path)
        for key in (*SETTABLE, "sides", "sides_unknown", "warnings", "stage_overrides", "gate_waivers", "remarks",
                    "acceptance"):
            if key in current:
                projected[key] = current[key]
        atomic_json(path, projected)
        controller.project(events)
    # The shared journal is written AFTER the history lock is released (B-318): `log_append.write` takes its own
    # `.journal-writer` lock, and no second lock is taken while the history lock is held. The projection above
    # runs under the history lock and never writes the journal.
    if previous:
        store.recover(project)
        _append_journal(previous)
        if bind_only:
            print(f"pipeline.json: {stage} agent bound (stage stays done)"
                  + (f" ({role})" if role else "") + f" at {at} (recovered existing event)")
        else:
            print(f"pipeline.json: {stage} -> {status} (recovered existing event)")
        print_boundary_notice(task, stage, status)
        if story_budget_stop(task):
            return STORY_BUDGET_EXIT
        return 0
    try:
        committed = store.commit("stage_transition", payload, key, expected_revision=len(events_before),
                                 project=project)
    except EventCommitted:
        # The event is in but a projection or a view failed after it: the journal line is still owed, once.
        # `log_append.write` dedupes on `source_event_id`, so a replay of the transition writes no second line.
        committed = next((e for e in reversed(store.read()) if e["idempotency_key"] == key), None)
        _append_journal(committed)
        raise
    _append_journal(committed)
    if bind_only:
        print(f"pipeline.json: {stage} agent bound (stage stays done)"
              + (f" ({role})" if role else "") + f" at {at}")
    else:
        print(f"pipeline.json: {stage} -> {status}"
              + (f" ({role})" if role else "") + f" at {at}")
    print_boundary_notice(task, stage, status)
    if story_budget_stop(task):
        return STORY_BUDGET_EXIT
    if no_journal:
        print("journal: skipped (--no-journal)")
        return 0
    spec = journal_event(task, stage, status, role, digest)
    if spec is None:
        print("journal: nothing to record — no role ran for this stage")
        return 0
    return 0


def selftest() -> int:
    import tempfile
    import hooklib
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    base = {"ticket": "QA-1", "stages": {}, "gates": {}}
    p = apply_stage(dict(base), "S1", "running", "qa-scout", "", "T1")
    case("a started stage is running", p["stages"]["S1"]["status"], "running")
    case("started is stamped", p["stages"]["S1"]["started"], "T1")
    case("nothing is finished yet", "finished" in p["stages"]["S1"], False)
    p = apply_stage(p, "S1", "done", "qa-scout", "one fact", "T2")
    case("started is never overwritten", p["stages"]["S1"]["started"], "T1")
    case("finished is stamped on done", p["stages"]["S1"]["finished"], "T2")
    case("the digest is kept", p["stages"]["S1"]["digest"], "one fact")
    p = apply_stage(p, "S1", "done", "qa-scout", "one fact", "T2", "a1b2c3")
    case("the dispatch id is kept for a follow-up", p["stages"]["S1"]["agent_id"], "a1b2c3")
    p = apply_stage(p, "S1", "done", "", "", "T3")
    case("a later write keeps the role", p["stages"]["S1"]["role"], "qa-scout")
    case("and keeps the digest it had", p["stages"]["S1"]["digest"], "one fact")

    case("running journals a delegation",
         (journal_event("QA-1", "S1", "running", "qa-scout", "") or {}).get("event"), "delegated")
    case("done journals an acceptance",
         (journal_event("QA-1", "S1", "done", "qa-scout", "d") or {}).get("event"), "accepted")
    case("halted journals a halt",
         (journal_event("QA-1", "S4", "halted", "qa-case-critic", "why") or {}).get("event"), "halt")
    case("a stage with no role journals nothing",
         journal_event("QA-1", "S7", "done", "", "no failures"), None)

    # --set is a whitelist, and the value of a whitelist is what it refuses.
    def refused(spec):
        try:
            parse_sets([spec])
            return ""
        except ValueError as exc:
            return str(exc)

    case("a closed list is checked", "XS | S | M | L | XL | XXL" in refused("size=large"), True)
    case("an unknown key names the ones that exist",
         "implementation_source" in refused("archived=true"), True)
    case("and says a word does not widen it",
         "not a decision to be waived" in refused("archived=true"), True)
    case("a source outside the contract is refused",
         "diff | current-code | ungrounded" in refused("implementation_source=guesswork"), True)
    case("a parent with its title is refused",
         "KEY alone" in refused('parent_feature=QA-1 "Attachments"'), True)
    case("true/false is not a string", parse_sets(["environment_pending=false"]),
         {"environment_pending": False})
    case("no_trace is a bool too", (parse_sets(["no_trace=true"]), parse_sets(["no_trace=false"])),
         ({"no_trace": True}, {"no_trace": False}))
    case("and `maybe` is refused by name", "`no_trace` is true or false" in refused("no_trace=maybe"), True)
    case("null clears a field S0 has not answered yet",
         parse_sets(["size=null", "environment=null"]), {"size": None, "environment": None})
    case("a stand name needs no closed list",
         parse_sets(["environment=staging-eu"]), {"environment": "staging-eu"})

    with tempfile.TemporaryDirectory(prefix="qa-stage-done-") as td:
        proj = Path(td)
        art = proj / "qa-factory" / "artifacts" / "QA-1"
        art.mkdir(parents=True)
        (proj / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        old = hooklib._PROJECT_ROOT_CACHE
        hooklib._PROJECT_ROOT_CACHE = proj
        print(f"SELFTEST ROOT: {hooklib.project_root()}")  # a hijacked root reads as line one
        try:
            case("no pipeline.json is a refusal, not a creation",
                 run("QA-1", "S1", "done", "qa-scout", "d", True), EXIT_NO_PIPELINE)
            case("and nothing was created",
                 (art / "pipeline.json").exists(), False)
            (art / "pipeline.json").write_text(json.dumps(base), encoding="utf-8")
            case("a real transition succeeds",
                 run("QA-1", "S1", "done", "qa-scout", "one fact", False), 0)
            written = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
            case("pipeline.json carries the stage", written["stages"]["S1"]["status"], "done")
            journal = RP.record(proj, "journal.jsonl")
            case("the journal carries the same transition", journal.is_file(), True)
            record = json.loads(journal.read_text(encoding="utf-8").strip().splitlines()[-1])
            case("as one accepted event", record["event"], "accepted")
            case("naming the role", record["agent"], "qa-scout")

            # The fields the phases used to ask for by hand.
            case("a fact on its own needs no stage",
                 set_facts("QA-1", {"size": "L"}, []), 0)
            written = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
            case("and lands in pipeline.json", written["size"], "L")
            case("warnings are appended, not replaced",
                 set_facts("QA-1", {}, ["S0 vcs_api: no token", "S0 vcs_api: no token"]), 0)
            written = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
            case("the same warning is recorded once", written["warnings"], ["S0 vcs_api: no token"])
            case("a stage transition carries facts too",
                 run("QA-1", "S1", "done", "qa-scout", "one fact", True,
                     "", {"implementation_source": "diff"}, ["S0 app_repo: unknown"]), 0)
            written = json.loads((art / "pipeline.json").read_text(encoding="utf-8"))
            case("the fact survives the transition's own write",
                 written["implementation_source"], "diff")
            case("and so does the warning it carried", len(written["warnings"]), 2)
            case("the size it already had is untouched", written["size"], "L")
        finally:
            hooklib._PROJECT_ROOT_CACHE = old

    if failures:
        print("STAGE_DONE SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("STAGE_DONE SELFTEST: no violations (stamping, digest, journal event, refusal)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="")
    ap.add_argument("--stage", default="")
    ap.add_argument("--status", default="done", choices=STATUSES)
    ap.add_argument("--role", default="")
    ap.add_argument("--digest", default="")
    ap.add_argument("--agent-id", dest="agent_id", default="",
                    help="the dispatch id from the task notification, so a follow-up can "
                         "resume THAT agent instead of starting a new one")
    ap.add_argument("--dispatch-id", dest="dispatch_id", default="",
                    help="with --agent-id: the controller dispatch that agent runs (`story_step bind` "
                         "passes it), so the dispatch record names its agent")
    ap.add_argument("--no-journal", action="store_true")
    ap.add_argument("--set", action="append", default=[], dest="sets", metavar="key=value",
                    help="one story fact of pipeline.json, repeatable: "
                         + ", ".join(sorted(SETTABLE)) + "; and the sides record: sides.<name>.<attribute> "
                         "(" + " | ".join(SIDE_ATTRS) + ") and sides_unknown (sides_unknown= clears it, "
                         "sides_unknown.at / sides_unknown.why write it). Nothing else.")
    ap.add_argument("--warn", action="append", default=[], dest="warns", metavar="TEXT",
                    help="append one line to pipeline.json warnings[], repeatable; a line "
                         "already there is not repeated")
    ap.add_argument("--acceptance", default="", metavar="FORM",
                    help="record the stage critic's verdict on --stage (S2-S4) from its handoff form work/handoffs/<dispatch>.yaml; "
                         "writes pipeline.json `acceptance`, no stage transition")
    ap.add_argument("--acceptor", default="", help="with --acceptance: `driver` records the conductor's accept-with-a-gap instead of the critic's word")
    ap.add_argument("--verdict", default="", help="with --acceptance --acceptor driver: `accept`")
    ap.add_argument("--quote", default="", help="with --acceptance --acceptor driver: the gap, in words")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.task:
        print("stage_done.py: --task is required", file=sys.stderr)
        return EXIT_BAD_ARGS
    if args.acceptance:
        if not args.stage:
            print("stage_done.py: --acceptance needs --stage (S2, S3 or S4)", file=sys.stderr)
            return EXIT_BAD_ARGS
        return record_acceptance(args.task, args.stage, args.acceptance, args.acceptor, args.verdict, args.quote)
    if args.acceptor or args.verdict or args.quote:
        print("stage_done.py: --acceptor, --verdict and --quote go with --acceptance only", file=sys.stderr)
        return EXIT_BAD_ARGS
    try:
        sets = parse_sets(args.sets)
    except ValueError as exc:
        print("stage_done: " + str(exc), file=sys.stderr)
        return EXIT_BAD_ARGS
    if not args.stage:
        # A fact on its own: S1 sets `implementation_source` at its exit, S0 records a warning
        # the moment the readiness script hands it one — neither is a stage transition.
        if not sets and not args.warns:
            print("stage_done.py: --stage is required, or --set/--warn on their own",
                  file=sys.stderr)
            return EXIT_BAD_ARGS
        return set_facts(args.task, sets, args.warns)
    import event_store
    return run(args.task, args.stage, args.status, args.role, args.digest, args.no_journal,
               args.agent_id, sets, args.warns, wait_seconds=event_store.LIFECYCLE_WAIT_SECONDS,
               dispatch_id=args.dispatch_id)


if __name__ == "__main__":
    sys.exit(main())
