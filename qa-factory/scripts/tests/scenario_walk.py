#!/usr/bin/env python3
"""The scenario walker: a recorded SYNTHETIC story is walked stage by stage through the real doors of the package (TD-15.4).

Not a test (selftest runs `test_*.py`); a test file per story is `scenario_walk.run("<id>")`. A story is a folder of
`fixtures/stories/<id>/`: `story.json` (the walk), `expected.json` (what the run recorded, plus accepted amendments),
`variants.json` (one row per added case) and the recorded task root beside them (`state/`, `work/`, `pipeline.json`, ...).
`root` in story.json may name another folder (relative to the story folder) holding the recorded task root instead.

The walker asserts an OUTCOME KIND (accepted / refused, the question kind and its set of closed tokens, the decision, the
delivery word), never a text, an order, a time or a hash. A facet with no carrier is a NOTE line, never a PASS. One world is
built per story; every door that can write (all of them, measured: the exit gate writes advice and sizing, the gate brief and
the delivery assessment write their own files) runs on a COPY of it, so the shared world is the same bytes after the walk.

Also: `python -B scenario_walk.py --witness-for <path> [<path> ...]` names the test files that judge a changed path (A.6).
"""
import argparse
import ast
import atexit
import base64
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))

PACKAGE = harness.PLUGIN_ROOT
STORIES = harness.FIXTURES / "stories"
# The closed vocabularies of the walker (FR-13: closed variety is data, here in one place each).
# An amendment's `field` -> the facet that compares it.
AMEND_FACETS = {"outcome": "accepted", "decision": "decision", "delivery": "delivery", "question_kind": "question", "options": "question"}
DOORS = ("exit_gate", "joint", "start", "gate", "delivery")
OPS = ("del", "set", "replace_file", "words")
FACET_DOORS = {"accepted": ("exit_gate", "joint"), "refused": ("exit_gate", "joint"),
               "handed": ("exit_gate", "joint", "start"), "question": ("gate",), "decision": ("gate",),
               "delivery": ("delivery",)}
# What a door runs, for --witness-for: the modules whose import closure decides which scenario a changed script belongs to.
DOOR_MODULES = {"exit_gate": ["exit_gate"], "joint": ["validate_artifacts"], "start": ["story_step"],
                "gate": ["gate_brief", "question_register", "controller"], "delivery": ["check_delivery", "delivery_verdict"]}
NOT_PART_OF_ROOT = ("story.json", "expected.json", "variants.json", "README.txt", "variant-files", "handbacks")
# The one vocabulary of a gate decision and of a question kind: the walker's doors ANSWER in the right-hand tokens, and
# tools/story_capture.py WRITES expected.json through these same rows (it imports this module by path), so a recorded
# controller action and a recorded question kind can never be written in a form the doors do not return. A recorded action
# that is not a row here is refused by the tool by name; the door is a row.
APPROVE, REFUSED = "approve", "refused"
GATE_ACTIONS = {"approve": APPROVE, "approve_plan_and_cases": APPROVE, "approve_delivery": APPROVE}
QUESTION_KINDS = {"gate_a": "gate_a", "gate_b": "gate_b"}
# The start arguments a recorded dispatch event can carry: payload key -> story_step.py start flag.
START_ARGS = (("execution_kind", "--execution-kind"), ("purpose", "--purpose"), ("scope", "--scope"))
_TEMPS: list = []


class StoryError(ValueError):
    """A story file that cannot be used: the message names the file and the key."""


@dataclass
class Result:
    name: str
    kind: str          # "pass" | "fail" | "note"
    detail: str = ""


@dataclass
class Story:
    id: str
    task: str
    dir: Path
    root: Path
    walk: list
    not_walked: list
    expected: dict
    variants: list
    red_then: dict | None = None      # story.json `red_then`: {stage, facet, evidence} - the facet that carries a recorded red Then


@atexit.register
def _cleanup_temps() -> None:
    for path in _TEMPS:
        shutil.rmtree(path, ignore_errors=True)


def _read_json(path: Path, required: bool, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        if required:
            raise StoryError(f"{path.name}: the file is missing; expected the story folder to hold it") from None
        return default
    except ValueError as exc:
        raise StoryError(f"{path.name}: cannot be read as JSON ({' '.join(str(exc).split())})") from None


def load_story(story_id: str, base: Path | None = None) -> Story:
    folder = Path(base or STORIES) / story_id
    story = _read_json(folder / "story.json", True, None)
    if not isinstance(story, dict) or story.get("synthetic") is not True:
        raise StoryError("story.json: not synthetic; expected `synthetic: true` (a Jira corpus is never a story)")
    for key, kind in (("id", str), ("task", str), ("walk", list)):
        if not isinstance(story.get(key), kind) or not story.get(key):
            raise StoryError(f"story.json: {key} is missing or empty; expected a {kind.__name__}")
    expected = _read_json(folder / "expected.json", False, {})
    variants = _read_json(folder / "variants.json", False, [])
    if not isinstance(expected, dict) or not isinstance(variants, list):
        raise StoryError("expected.json / variants.json: expected an object and a list")
    root = (folder / story["root"]) if story.get("root") else folder
    return Story(story["id"], story["task"], folder, root, story["walk"], story.get("not_walked") or [], expected, variants,
                 story.get("red_then"))


def _new_project(prefix: str) -> Path:
    project = harness.mark_project(harness.temp_dir(prefix))
    _TEMPS.append(project)
    return project


@contextlib.contextmanager
def _pinned(task_root: Path):
    """The hook layer reads the project of THIS world for the length of the block (the pin controller's gate decision uses),
    and what the doors print goes nowhere: a red line is the walker's own."""
    import contract
    import hooklib
    contract.case_config_reset()     # the case-config memo belongs to ONE world: never the reading of the previous project
    with hooklib.selftest_root_restored(), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        hooklib.pin_project_root(task_root.parents[2])
        yield


def _reproject(task_root: Path) -> None:
    from controller import Controller
    with _pinned(task_root):
        controller = Controller(task_root)
        controller.project(controller.store.read())


def _copy_file(source, target):
    """`shutil.copy2` without its `copystat`: the bytes and the modification time (a door that compares file ages must see the
    recording's ages) are kept; the permission and flag calls, measured at two thirds of a 424-file copy on Windows, are not."""
    shutil.copyfile(source, target)
    stat = os.stat(source)
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    return target


def recorded_config(task_root: Path) -> bytes | None:
    """The project config the run recorded at its start (`state/config-at-start.json`, field `bytes_b64`), None when the root
    holds none or it does not decode to a JSON object."""
    try:
        raw = base64.b64decode(json.loads((task_root / "state" / "config-at-start.json").read_text(encoding="utf-8-sig"))["bytes_b64"])
        return raw if isinstance(json.loads(raw.decode("utf-8-sig")), dict) else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _carry_project_config(task_root: Path) -> None:
    """The recorded project config replaces the template one in the project of this world, BEFORE anything is projected: a
    project key such as `case_id_form` or `cases_root` is what makes the recorded case ids ids at all."""
    raw = recorded_config(task_root)
    if raw is not None:
        (task_root.parents[2] / "qa-factory" / "config.json").write_bytes(raw)


def build_world(story: Story) -> Path:
    """The recorded task root, copied ONCE into `<tmp>/project/qa-factory/artifacts/<task>/`, in a project that carries the
    recorded config (the template config when the story has none: `walk` says so in a NOTE); pipeline.json is projected
    from the events when the recording has none."""
    world = _new_project("qa-scenario-") / "qa-factory" / "artifacts" / story.task
    skip = shutil.ignore_patterns(*NOT_PART_OF_ROOT) if story.root == story.dir else None
    shutil.copytree(story.root, world, ignore=skip, copy_function=_copy_file)
    _carry_project_config(world)
    if not (world / "pipeline.json").is_file() and (world / "state" / "events.jsonl").is_file():
        _reproject(world)
    return world


def copy_world(world: Path, cut_before_seq: int | None = None) -> Path:
    """A throwaway copy for a door that writes; events cut before `cut_before_seq` when given (the world as it stood when
    that event had not yet happened), the projections rebuilt from what is left."""
    dest = _new_project("qa-scenario-copy-") / "qa-factory" / "artifacts" / world.name
    shutil.copytree(world, dest, copy_function=_copy_file)
    _carry_project_config(dest)
    if cut_before_seq is not None:
        events = dest / "state" / "events.jsonl"
        kept = [line for line in events.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line).get("sequence", 0) < cut_before_seq]
        events.write_text("\n".join(kept) + "\n", encoding="utf-8")
        for name in ("pipeline.json", "state/controller.json", "state/checkpoint.json"):
            (dest / name).unlink(missing_ok=True)
        _reproject(dest)
    return dest


def world_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(root).rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


# --- variants ---------------------------------------------------------------------------------

def _hold(doc, pointer: str):
    """(container, key) of a JSON pointer that exists in `doc`; KeyError when it does not."""
    parts = [p.replace("~1", "/").replace("~0", "~") for p in pointer.lstrip("/").split("/")] if pointer else []
    if not parts:
        raise KeyError(pointer)
    parent = doc
    for part in parts[:-1]:
        parent = parent[int(part)] if isinstance(parent, list) else parent[part]
    key = int(parts[-1]) if isinstance(parent, list) else parts[-1]
    if (isinstance(parent, list) and not -len(parent) <= key < len(parent)) or (isinstance(parent, dict) and key not in parent):
        raise KeyError(pointer)
    return parent, key


def apply_op(world: Path, variant: dict, story_dir: Path | None = None) -> str:
    """Apply one variant row to a COPY; "" when applied, else the failure word the walker prints."""
    op, target = variant.get("op"), Path(world) / str(variant.get("file", ""))
    if op not in OPS:
        return "op-unknown"
    if op != "replace_file" and not target.is_file():
        return "variant-file-absent"
    if op == "words":
        target.write_text(str(variant.get("value", "")), encoding="utf-8")
    elif op == "replace_file":
        source = Path(story_dir or ".") / str(variant.get("with", ""))
        if not source.is_file():
            return "variant-file-absent"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    else:
        doc = json.loads(target.read_text(encoding="utf-8-sig"))
        try:
            parent, key = _hold(doc, str(variant.get("pointer", "")))
        except (KeyError, IndexError, ValueError, TypeError):
            return "variant-pointer-absent"
        if op == "del":
            del parent[key]
        else:
            parent[key] = variant.get("value")
        target.write_text(json.dumps(doc), encoding="utf-8")
    return ""


# --- the doors ---------------------------------------------------------------------------------

def _outcome(errors: list) -> dict:
    """`parts` is the refusal as the door gave it (one string per refusal line); `errors` is the same text joined for printing."""
    parts = [str(e) for e in errors]
    return {"outcome": "refused" if errors else "accepted", "errors": " | ".join(parts), "parts": parts}


def door_exit_gate(story: Story, entry: dict, copy_root: Path) -> dict:
    """`exit_gate.all_errors(agent, task, digest, facts_text)` on a copy, the project pinned; the digest is the text the
    capture kept (`door.digest_file`, relative to the story folder), "" when the story names none."""
    import exit_gate
    name = entry["door"].get("digest_file")
    digest = (story.dir / name).read_text(encoding="utf-8") if name else ""
    # the stage and the dispatch the door judges are named to the detectors, as `story_step finish` does: on a finished world no
    # stage is running, and branch_accounting would answer UNREADABLE for a reason the walker made
    with _pinned(copy_root), exit_gate.holding_stage(entry.get("stage")), \
            exit_gate.holding_dispatch(_accepted_dispatch(copy_root, str(entry.get("stage")))):
        blocking, _passed = exit_gate.all_errors(entry["role"], story.task, digest, "")
    return _outcome(without_detectors(blocking, entry["door"].get("skip_detectors")))


def without_detectors(blocking: list, names) -> list:
    """The refusal lines minus those of the detectors a story declares NOT WALKED (`door.skip_detectors`, a detector script name
    each; the story's `not_walked` row says why): a check that reads a record outside the task root cannot be replayed."""
    prefixes = tuple(f"{name}:" for name in names or ())
    return [line for line in blocking if not str(line).startswith(prefixes)] if prefixes else list(blocking)


def door_joint(story: Story, entry: dict, copy_root: Path) -> dict:
    import validate_artifacts as VA
    door, errors, notes = entry["door"], [], []
    path = copy_root / door["file"]
    VA.check_phase_json(path, errors, notes)
    if door.get("check") == "triage_v0" and not errors:
        VA.check_triage_v0(path, json.loads(path.read_text(encoding="utf-8-sig")), errors, None)
    return _outcome(errors)


def _gate_of(entry: dict) -> str:
    return str(entry["door"].get("gate") or str(entry["stage"])[-1]).upper()


def _words_of(story: Story, entry: dict, root: Path) -> str:
    return (root / entry["door"]["words_file"]).read_text(encoding="utf-8")


def rendered_kind(text: str) -> str:
    """The question kind a RENDERED brief states: its own first heading, `# Gate A - <task>` / `# Gate B - <task>` (the one form
    `gate_brief.render` and `render_gate_b` open with), read through the vocabulary row; "" when the text carries none."""
    import re
    found = re.match(r"\s*#\s*Gate\s+([AB])\b", str(text))
    return (question_kind_of(f"gate_{found.group(1)}") or "") if found else ""


def question_problems(text: str, words: list) -> list:
    """What is wrong with a rendered question, as a list of sentences ([] when nothing): empty, a single line, the gate has no
    approval word at all, or the text names none of them. The door's own token set is the carrier of the closed words (FR-13)."""
    if not str(text).strip():
        return ["the question renders empty"]
    problems = []
    if len([line for line in str(text).splitlines() if line.strip()]) < 2:
        problems.append("the question renders a single line, no body")
    if not words:
        problems.append("the gate has no approval words")
    elif not any(word.lower() in str(text).lower() for word in words):
        problems.append(f"the rendered question names none of the approval words {words!r}")
    return problems


def door_question(story: Story, entry: dict, copy_root: Path) -> dict:
    """The pure road of the question: collect + render, the approval words and the register's ids. Never `Driver.gate`. The kind
    is READ from what the door rendered (its heading), never taken from the story's entry: a brief that stops saying which gate it
    is, or stops naming the gate's words, is a different answer (TD-15 critic B3)."""
    import gate_brief
    import question_register as QR
    gate = _gate_of(entry)
    with _pinned(copy_root):
        text = gate_brief.render(gate_brief.collect(story.task, copy_root.parent)) if gate == "A" \
            else gate_brief.render_gate_b(story.task, copy_root.parent)
        register = [str(q.get("id")) for q in QR.load(copy_root).get("questions") or []]
        words = list(gate_brief.approval_words(gate))
    return {"question_kind": rendered_kind(text), "options": sorted(set(words) | set(register)),
            "errors": " | ".join(question_problems(text, words))}


def door_decision(story: Story, entry: dict, copy_root: Path, words: str | None = None) -> dict:
    """The recorded words through the read-only parts of the decision road: build the request, check it; never write one."""
    import question_register as QR
    from controller import Controller
    gate = _gate_of(entry)
    words = _words_of(story, entry, copy_root) if words is None else words
    with _pinned(copy_root):
        try:
            controller = Controller(copy_root)
            request = controller.build_gate_decision(gate, words)
            problems = controller.check_decision(request)
        except Exception as exc:     # the road refuses with a StateConflict / ValueError: that is the outcome
            text = f"{type(exc).__name__}: {exc}"
            return {"decision": REFUSED, "errors": text, "parts": [text], "tokens": []}
        view = QR.gate_words_view(copy_root, words, QR.load(copy_root))
    tokens = sorted(view.get("recorded", []) + view.get("already", []))
    refused = bool(problems) or request.get("status") != "approved" or bool(view.get("unknown"))
    return {"decision": REFUSED if refused else APPROVE, "errors": " | ".join(problems), "parts": [str(p) for p in problems],
            "tokens": tokens}


def door_delivery(story: Story, entry: dict, copy_root: Path) -> dict:
    """`check_delivery.assess` re-derives the kinds from the root and calls `delivery_verdict.decide` itself (l.2468)."""
    import check_delivery
    import delivery_verdict as DV
    _doc, problem = DV.load_kinds()
    if problem:
        return {"delivery": "unknown", "errors": problem}
    with _pinned(copy_root):
        doc = check_delivery.assess(copy_root)
    kinds = sorted({str(r.get("kind")) for r in doc.get("reason_records") or [] if isinstance(r, dict)})
    return {"delivery": doc["delivery_verdict"], "reasons": kinds, "errors": ""}


def decision_of(action: str, status: str) -> str:
    """The token the decision door returns for a recorded decision event; KeyError (the action) when it is no row of GATE_ACTIONS."""
    token = GATE_ACTIONS[str(action)]
    return token if status == "approved" else REFUSED


def question_kind_of(recorded: str) -> str | None:
    """The question kind the question door returns for a recorded kind in any case; None when it is no row of QUESTION_KINDS."""
    return QUESTION_KINDS.get(str(recorded).lower())


def required_inputs(form_text: str) -> list:
    """The paths a handoff form names as required inputs, in form order: what the `handed` facet compares with."""
    import handoff
    rows = handoff.parse(form_text).data.get("inputs") or []
    return [str(r["path"]) for r in rows if isinstance(r, dict) and r.get("path") and str(r.get("required")).lower() == "true"]


def required_today(form_text: str, recorded: list) -> tuple:
    """(still, retired, why) of the `recorded` required paths of a code-written form, judged by TODAY's template of the form's
    `contract:` (the package's handoffs folder): a recorded form carries the template text of the package that printed it. `retired`
    = recorded as required that today's template no longer requires (a NOTE, not a failure); no readable template: all `still`."""
    import re
    import handoff
    try:
        contract = str(handoff.parse(form_text).data.get("contract"))
        rows = handoff.template(contract).data.get("inputs") or []
    except Exception as exc:
        return list(recorded), [], f"no template of today's package for the form's contract ({type(exc).__name__}): the recorded form judges"
    patterns = [re.compile(".+".join(re.escape(part) for part in re.split(r"<[^>]*>", str(r["path"]))))
                for r in rows if isinstance(r, dict) and r.get("path") and str(r.get("required")).lower() == "true"]
    still = [p for p in recorded if any(rx.fullmatch(p) for rx in patterns)]
    return still, [p for p in recorded if p not in still], ""


def _not_comparable(path: str, root: Path) -> str:
    """Why a path a form names is not a file to look for ("" when it is one): a template with placeholders, or a folder."""
    if "<" in path and ">" in path:
        return "a template path, not a file"
    if path.endswith("/") or (root / path).is_dir():
        return "a folder, not a file"
    return ""


def first_dispatch(world: Path, stage: str) -> dict | None:
    """The first RECORDED dispatch event of `stage` (the one a replayed `start` stands for), None when the run has none."""
    for line in (world / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line) if line.strip() else {}
        if event.get("type") == "dispatch" and (event.get("payload") or {}).get("stage") == stage:
            return event
    return None


def start_args(event: dict | None) -> list:
    """The `story_step start` flags a recorded dispatch event carries (START_ARGS rows present and non-empty); [] for none."""
    payload, argv = (event or {}).get("payload") or {}, []
    for key, flag in START_ARGS:
        value = payload.get(key)
        value = ",".join(str(v) for v in value if str(v).strip()) if isinstance(value, list) else str(value or "")
        if value:
            argv += [flag, value]
    return argv


def _accepted_dispatch(world: Path, stage: str) -> str:
    """The id of the last accepted dispatch of `stage`, from the recorded events."""
    stages, last = {}, ""
    for line in (world / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line) if line.strip() else {}
        payload = event.get("payload") or {}
        if event.get("type") == "dispatch":
            stages[payload.get("id")] = payload.get("stage")
        elif event.get("type") == "accept" and stages.get(payload.get("id")) == stage:
            last = payload["id"]
    return last


NOT_COMPARABLE = "not comparable:"


def accept_drift(world: Path, stage: str) -> tuple:
    """(moved, hashed) of the accept the `accepted` facet of `stage` replays: `hashed` is how many `evidence_refs` rows of the LAST
    accept of the stage's accepted dispatch carry a path and a sha256; `moved` the paths whose bytes in `world` differ from that
    hash (or are gone). The capture follows its own rewrites into the recorded hashes (tools/story_capture.py: the sha256 follow), so
    a recorded hash is compared as it stands. A cut world cuts the events only: a file here is the FINAL state of the run."""
    dispatch, refs = _accepted_dispatch(world, stage), []
    for line in (world / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line) if line.strip() else {}
        payload = event.get("payload") or {}
        if dispatch and event.get("type") == "accept" and payload.get("id") == dispatch:
            refs = payload.get("evidence_refs") or []
    pairs = [(str(r["path"]), str(r["sha256"])) for r in refs if isinstance(r, dict) and r.get("path") and r.get("sha256")]
    moved = [path for path, sha in pairs
             if not (world / path).is_file() or hashlib.sha256((world / path).read_bytes()).hexdigest() != sha]
    return moved, len(pairs)


def red_then_shape(story: Story) -> str:
    """"" when the story has no `red_then` or it is well formed and names a facet the walk holds (and does not list as not walked);
    else the sentence of the FAIL line of the story."""
    red = story.red_then
    if red is None:
        return ""
    if not isinstance(red, dict) or not all(isinstance(red.get(k), str) and red.get(k) for k in ("stage", "facet", "evidence")):
        return "red_then: expected an object with `stage`, `facet` and `evidence`, each a non-empty string"
    path = (story.dir / red["evidence"]).resolve()
    if Path(red["evidence"]).is_absolute() or not path.is_relative_to(story.dir.resolve()):
        return f"red_then: evidence {red['evidence']!r} is not a path inside the story folder"
    pair = (red["stage"], red["facet"])
    walked = any(e.get("stage") == pair[0] and pair[1] in (e.get("facets") or []) for e in story.walk)
    if not walked or any((n.get("stage"), n.get("facet")) == pair for n in story.not_walked):
        return f"red_then names {pair[0]}/{pair[1]}, which is not walked"
    return ""


def red_then_mark(story: Story) -> tuple:
    """(suffix, problem) of the facet `red_then` names: the evidence file must exist in the story folder and, when it is a triage file
    (a JSON object with a `triage` list), hold at least one row whose verdict is the red one. The red verdict word is the package's
    own constant `bug_records.APP_BUG` (a red Then judged a product failure) and the rows are read through `contract.triage_rows`."""
    import bug_records
    import contract
    evidence = story.red_then["evidence"]
    path = story.dir / evidence
    if not path.is_file():
        return "", f"red_then evidence {evidence} is absent from the story folder"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        return " (red then: evidence is not a triage file)", ""
    if not isinstance(data, dict) or not isinstance(data.get("triage"), list):
        return " (red then: evidence is not a triage file)", ""
    red = [row for row in contract.triage_rows(data) if row.get("verdict") == bug_records.APP_BUG]
    if not red:
        return "", f"red_then evidence {evidence} holds no row with the red verdict {bug_records.APP_BUG}"
    return f" (red then: {len(red)} rows)", ""


def door_handed(story: Story, entry: dict, copy_root: Path, world: Path) -> dict:
    """Hand-over: every REAL file the accepted dispatch's form names as required exists (and a .json one parses), and `story_step
    start` of the NEXT role, with the start arguments the recorded dispatch event carries, passes on a copy and leaves that
    role's form behind. A template path (placeholders) and a folder are listed in `notes`, never failed: they are not files."""
    problems, notes, nxt = [], [], entry.get("next") or entry["door"].get("next")
    dispatch = _accepted_dispatch(world, entry["stage"])
    form = copy_root / "work" / "handoffs" / f"{dispatch}.yaml"
    named, retired = [], []
    if not dispatch or not form.is_file():
        problems.append(f"no form of an accepted {entry['stage']} dispatch ({dispatch or 'none'})")
    else:
        form_text = form.read_text(encoding="utf-8")
        recorded = required_inputs(form_text)
        named, retired, template_why = required_today(form_text, recorded)
        if not recorded:
            notes.append(f"{form.name} -- the form names no required inputs")
        notes += [f"{path} -- the recorded form required it, today's template does not" for path in retired]
        notes += [template_why] if template_why and recorded else []
        for path in named:
            why = _not_comparable(path, copy_root)
            if why:
                notes.append(f"{path} -- not comparable: {why}")
            elif not (copy_root / path).is_file():
                problems.append(f"{path} is named by the form and absent")
            elif path.endswith(".json"):
                try:
                    json.loads((copy_root / path).read_text(encoding="utf-8-sig"))
                except ValueError:
                    problems.append(f"{path} does not parse")
    if not nxt:
        return {"carrier": False, "errors": "no `next` stage and role named for the start"}
    project = copy_root.parents[2]
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), QA_FACTORY_SKIP_DASHBOARD_REFRESH="1")
    argv = start_args(first_dispatch(world, nxt["stage"]))
    started = harness.run_script("story_step.py", "start", "--task", story.task, "--stage", nxt["stage"], "--role", nxt["role"],
                                 *argv, cwd=project, env=env)
    if started.returncode != 0 or "dispatched " not in started.stdout:
        problems.append(f"start of {nxt['role']} was refused: {_shown(started.stdout.strip(), tail=True)}")
    return {"carrier": True, "errors": " | ".join(problems), "handed": sorted(named + retired), "notes": notes}


# --- the walk ------------------------------------------------------------------------------------

def _shown(text, n: int = 200, tail: bool = False) -> str:
    """A refusal text as a FAIL line shows it: cut to `n` characters (the last `n` when `tail`), or WHOLE when SCENARIO_FULL=1."""
    text = str(text)
    if os.environ.get("SCENARIO_FULL") == "1":
        return text
    return text[-n:] if tail else text[:n]


def _compare(got: dict, exp: dict, keys: tuple) -> str:
    """The first difference between the door's answer and the expectation over `keys`, "" when none. A set key is compared as a set."""
    for key in keys:
        want, have = exp.get(key), got.get(key)
        if isinstance(want, list) or isinstance(have, list):
            want, have = sorted(want or []), sorted(have or [])
        if want != have:
            return f"{key}: expected {want!r}, got {have!r}" + (f" ({_shown(got['errors'])})" if got.get("errors") else "")
    return ""


def story_cut(entry: dict, facet: str) -> int | None:
    """`door.cut_before_seq` of a walk entry: one number for every facet, or a map facet -> seq (a facet the map omits is uncut;
    the variants of the entry read the key `variant`)."""
    cut = entry["door"].get("cut_before_seq")
    return cut.get(facet) if isinstance(cut, dict) else cut


def _cut_of(entry: dict, facet: str, world: Path) -> int | None:
    """The event the world is cut before for a facet: the story's `cut_before_seq`; for a `handed` facet that names none, the
    first recorded dispatch of the NEXT stage (the world as it stood before that start), None when the run has no such dispatch."""
    cut = story_cut(entry, facet)
    nxt = entry.get("next") or entry["door"].get("next")
    if cut is None and facet == "handed" and nxt:
        first = first_dispatch(world, nxt["stage"])
        cut = first.get("sequence") if first else None
    return cut


def _facet_copy(world: Path, cut: int | None, built: dict) -> Path:
    """A private copy for ONE facet. The world of a cut is built once per walk (`built`: copy, cut, re-projection) and never
    handed to a door; every facet of that cut gets its own copy of it, so no facet sees another's writes."""
    if cut is None:
        return copy_world(world)
    if cut not in built:
        built[cut] = copy_world(world, cut)
    return copy_world(built[cut])


def amendments_of(story: Story) -> tuple:
    """({(stage, field): row}, [problem]) of `expected.json` `amendments`: a row is a recorded decision that the run was wrong
    (A.2 of the TD-15 spec). A malformed row is a problem of the STORY, never a crash and never silently skipped."""
    rows, problems = {}, []
    stages = story.expected.get("stages") or {}
    for n, row in enumerate(story.expected.get("amendments") or []):
        if not isinstance(row, dict):
            problems.append(f"amendment #{n}: not an object")
            continue
        stage, field = row.get("stage"), row.get("field")
        label = f"amendment {stage}/{field}"
        names = row.get("names")
        if not stage or not field:
            problems.append(f"amendment #{n}: `stage` and `field` are both required")
        elif stage not in stages:
            problems.append(f"{label}: the stage is not in expected.json stages")
        elif field not in AMEND_FACETS:
            problems.append(f"{label}: `field` must be one of {', '.join(AMEND_FACETS)}")
        elif row.get("recorded") != stages[stage].get(field):
            problems.append(f"{label}: `recorded` {row.get('recorded')!r} is not what stages holds ({stages[stage].get(field)!r}); "
                            "the amendment was written against another record")
        elif not row.get("why") or not row.get("accepted_by"):
            problems.append(f"{label}: `why` and `accepted_by` are both required")
        elif "expected" not in row:
            problems.append(f"{label}: `expected` is required")
        elif names is not None and (row["expected"] != "refused" or not isinstance(names, list) or not names
                                    or not all(isinstance(s, str) and s for s in names)):
            problems.append(f"{label}: `names` is a non-empty list of strings and goes only with `expected: refused`")
        elif (stage, field) in rows:
            problems.append(f"{label}: two amendments for the same stage and field")
        else:
            rows[(stage, field)] = row
    return rows, problems


def _judge(got: dict, exp: dict, keys: tuple, amends: dict, stage: str) -> str:
    """The first difference between the door's answer and the expectation; with amendments, the expectation of an amended field
    is the row's `expected`, every one of its `names` must occur in the refusal AND every PART of the refusal must carry at least one
    of them (a refusal the amendment's author never read cannot hide behind it; one name per kind of refusal it accepts), and a
    field that now behaves as RECORDED fails (the row goes)."""
    if not amends:
        return _compare(got, exp, keys)
    for field in amends:      # first: the door behaves as RECORDED again, so the amendment is dead weight (never passes in both worlds)
        if not _compare(got, exp, (field,)):
            return f"amendment no longer needed: {stage}/{field}"
    want = dict(exp, **{field: row["expected"] for field, row in amends.items()})
    diff = _compare(got, want, keys)
    for row in amends.values():
        names = row.get("names")
        if diff or not names:
            continue
        parts = _refusal_parts(got)
        if not parts:
            diff = "refused with no text"
        for text in names:
            if not diff and text not in got.get("errors", ""):
                diff = f"names: {text!r} not in the refusal ({_shown(got.get('errors', ''))})"
        unnamed = next((p for p in parts if not any(name in p for name in names)), None)
        if not diff and unnamed is not None:
            diff = f"unnamed refusal part: {_shown(unnamed, 160)}"
    return diff


def _refusal_parts(got: dict) -> list:
    """The non-blank parts of the door's refusal. A door that gave no `parts` is read from its joined text, split where it was joined."""
    parts = got.get("parts")
    if parts is None:
        parts = str(got.get("errors") or "").split(" | ")
    return [str(p) for p in parts if str(p).strip()]


def _run_facet(story: Story, entry: dict, facet: str, world: Path, exp: dict, notes: list | None = None,
               built: dict | None = None, amends: dict | None = None) -> tuple:
    """(ok, detail) of one facet; the door always runs on a copy. Lines that are not a verdict go into `notes`.
    `amends` maps a field of this facet to its amendment row."""
    door, amends, stage = entry["door"], amends or {}, str(entry.get("stage"))
    copy_root = _facet_copy(world, _cut_of(entry, facet, world), {} if built is None else built)
    if facet in ("accepted", "refused"):
        got = (door_joint if door["kind"] == "joint" else door_exit_gate)(story, entry, copy_root)
        diff = _judge(got, exp, ("outcome",), amends, stage)
        if not diff and exp.get("names") and exp["names"] not in got["errors"]:
            diff = f"names: {exp['names']!r} not in the refusal ({_shown(got['errors'])})"
        return not diff, diff
    if facet == "handed":
        got = door_handed(story, entry, copy_root, world)
        if notes is not None:
            notes.extend(got.get("notes") or [])
        if not got["carrier"]:
            return None, got["errors"]
        missing = [p for p in exp.get("handed", []) if p not in got["handed"]]
        problems = got["errors"] or (f"the form does not name {missing}" if missing else "")
        return not problems, problems
    if facet == "question":
        got = door_question(story, entry, copy_root)
        keys = ("question_kind", "options") if "options" in exp else ("question_kind",)
        if "options" not in exp and notes is not None:    # the run's question carrier recorded the kind and no options (story_capture `expected`)
            notes.append("options not recorded")
        diff = _judge(got, exp, keys, amends, stage) or got["errors"]
    elif facet == "decision":
        got = door_decision(story, entry, copy_root)
        diff = _judge(got, exp, ("decision",) + (("tokens",) if "tokens" in exp else ()), amends, stage)
    else:
        got = door_delivery(story, entry, copy_root)
        diff = _judge(got, exp, ("delivery",) + (("reasons",) if "reasons" in exp else ()), amends, stage)   # N1: the SET of reason kinds too
    return not diff, diff


def _drift_gate(world: Path, entry: dict, name: str, notes: list) -> tuple:
    """(mark, NOTE Result or None) for an `accepted` facet: no recorded hashes is a NOTE beside the verdict; a moved file makes the
    facet a NOTE and no verdict, unless the walk entry says `final_state: true` (then the mark is ` (final state)`, the facet runs)."""
    moved, hashed = accept_drift(world, str(entry.get("stage")))
    if not hashed:
        notes.append("no recorded hashes")
    elif moved and not entry.get("final_state"):
        return "", Result(name, "note", f"{NOT_COMPARABLE} {', '.join(moved)} changed after the recorded accept")
    elif moved:
        return " (final state)", None
    return "", None


def walk(story: Story, world: Path) -> list:
    """Every facet of every walked stage, then the variants. Names are `<story>/<stage>/<facet>` so a red line says which
    case fell (P16)."""
    out, sid, built, held = [], story.id, {}, None
    if recorded_config(world) is None:
        out.append(Result(f"{sid}/world/config", "note", "the story records no project config (state/config-at-start.json): the "
                                                         "world carries the template config, so a project key such as case_id_form is its default"))
    amended, problems = amendments_of(story)
    out += [Result(f"{sid}/amendments", "fail", problem) for problem in problems]
    if problems:
        amended = {}         # a malformed row is the story's fault: nothing is amended until it is fixed
    red_shape = red_then_shape(story)
    if red_shape:
        out.append(Result(f"{sid}/red_then", "fail", red_shape))
    for entry in story.walk:
        stage = str(entry.get("stage"))
        exp = (story.expected.get("stages") or {}).get(stage)
        if exp is None:
            out.append(Result(f"{sid}/{stage}/expected-missing", "fail", "expected.json holds no entry for this stage; record one"))
            continue
        for facet in entry.get("facets") or []:
            name, kind = f"{sid}/{stage}/{facet}", (entry.get("door") or {}).get("kind")
            if kind not in DOORS or facet not in FACET_DOORS:
                out.append(Result(name, "fail", f"unknown door {kind!r} or facet; doors are {', '.join(DOORS)}"))
                continue
            if kind not in FACET_DOORS[facet]:
                out.append(Result(name, "note", f"no carrier -- the {kind} door does not carry a {facet} facet"))
                continue
            before, notes, final = held or world_hash(world), [], ""
            here = {f: row for (s, f), row in amended.items() if s == stage and AMEND_FACETS[f] == facet}
            if facet == "accepted":      # B4: a cut world holds the FINAL files; a file that moved after the accept is not judged unmarked
                final, skipped = _drift_gate(world, entry, name, notes)
                if skipped:
                    out.append(skipped)
                    continue
            try:
                ok, detail = _run_facet(story, entry, facet, world, exp, notes, built, here)
            except Exception as exc:         # a door that crashes is a red line naming the facet, not a traceback
                ok, detail = False, f"{type(exc).__name__}: {_shown(' '.join(str(exc).split()), 300)}"
            red = ""
            if ok and not red_shape and story.red_then and (stage, facet) == (story.red_then["stage"], story.red_then["facet"]):
                red, problem = red_then_mark(story)
                ok, detail = (False, problem) if problem else (ok, detail)
            if ok is None:
                out.append(Result(name, "note", f"no carrier -- {detail}"))
            else:
                refs = ", ".join(str(row.get("ref")) for row in here.values())
                out.append(Result(name + (final + (f" (amended: {refs})" if here else "") + red if ok else ""),
                                  "pass" if ok else "fail", detail))
            out += [Result(name, "note", note) for note in notes]
            held = world_hash(world)         # the bytes after this facet are the bytes before the next: hashed once, not twice
            if held != before:
                out.append(Result(f"{name}/world-changed", "fail", "the shared world changed under this facet"))
    for item in story.not_walked:
        count = f" ({item['count']} files, e.g. {', '.join(item.get('samples') or [])})" if item.get("count") else ""
        out.append(Result(f"{sid}/{item.get('stage')}/{item.get('facet')}", "note", f"not walked -- {item.get('why')}{count}"))
    out += _walk_variants(story, world, built)
    return out


def _walk_variants(story: Story, world: Path, built: dict | None = None) -> list:
    out = []
    for variant in story.variants:
        name = f"{story.id}/variant/{variant.get('id')}"
        entry = next((e for e in story.walk if e.get("stage") == variant.get("stage")), None)
        if entry is None:
            out.append(Result(f"{name}/stage-not-walked", "fail", f"stage {variant.get('stage')!r} is not in walk"))
            continue
        copy_root = _facet_copy(world, story_cut(entry, "variant"), {} if built is None else built)
        failure = apply_op(copy_root, variant, story.dir)
        if failure:
            out.append(Result(f"{name}/{failure}", "fail", f"{variant.get('op')} on {variant.get('file')}"))
            continue
        kind, expect = entry["door"]["kind"], dict(variant.get("expect") or {})
        try:
            if kind in ("exit_gate", "joint"):
                got = (door_joint if kind == "joint" else door_exit_gate)(story, entry, copy_root)
            elif kind == "gate":
                got = door_decision(story, entry, copy_root)
            else:
                got = door_delivery(story, entry, copy_root)
            diff = _compare(got, expect, tuple(k for k in expect if k != "names"))
            if not diff and expect.get("names") and expect["names"] not in got["errors"]:
                diff = f"names: {expect['names']!r} not in the refusal ({_shown(got['errors'])})"
        except Exception as exc:
            diff = f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}"
        out.append(Result(name, "pass" if not diff else "fail", diff))
    return out


def results_for(story_id: str, base: Path | None = None) -> list:
    """load + build + walk; a story that cannot load or a world that cannot be built is ONE fail and no stage check runs."""
    try:
        story = load_story(story_id, base)
    except StoryError as exc:
        return [Result(f"{story_id}/load", "fail", str(exc))]
    try:
        world = build_world(story)
    except Exception as exc:
        return [Result(f"{story.id}/world-build", "fail", f"{type(exc).__name__}: {' '.join(str(exc).split())[:300]}")]
    return walk(story, world)


def run(story_id: str, base: Path | None = None) -> None:
    for result in results_for(story_id, base):
        if result.kind == "note":
            print(f"NOTE {result.name}: {result.detail}")
        else:
            harness.check(result.name, result.kind == "pass", result.detail)
    harness.finish(f"scenario {story_id}")


# --- --witness-for ---------------------------------------------------------------------------------

def _imports_of(path: Path) -> set:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return set()
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


def _closure(seeds, scripts: Path) -> set:
    """The modules `seeds` import, transitively, inside `scripts/` (a name with no file is kept: it cannot be followed)."""
    seen, todo = set(), list(seeds)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        if (scripts / f"{name}.py").is_file():
            todo.extend(_imports_of(scripts / f"{name}.py") - seen)
    return seen


def _relative(path: str) -> str:
    text = str(path).replace("\\", "/")
    marker = "ai-packages/qa-factory/"
    return text.split(marker, 1)[1] if marker in text else text


def _scenarios(tests: Path, scripts: Path, door_modules: dict) -> dict:
    """{test_scenario_<id>.py: (story id, the module closure of its doors)} for every scenario test on disk."""
    out = {}
    for test in sorted(tests.glob("test_scenario_*.py")):
        suffix = test.stem[len("test_scenario_"):]
        folder = next((d for d in (tests / "fixtures" / "stories").glob("*") if d.name.replace("-", "_") == suffix), None)
        seeds = set()
        try:
            story = json.loads((folder / "story.json").read_text(encoding="utf-8-sig")) if folder else {}
        except ValueError:
            story = {}
        for entry in story.get("walk") or []:
            seeds.update(door_modules.get((entry.get("door") or {}).get("kind"), []))
            if "handed" in (entry.get("facets") or []):
                seeds.update(door_modules.get("start", []))
        out[test.name] = (folder.name if folder else suffix, _closure(seeds, scripts))
    return out


def witness_for(paths, package: Path | None = None, layers: dict | None = None, door_modules: dict | None = None) -> list:
    """One or more lines per changed path: the scenario tests whose doors reach it, the keep rows whose `covers` name it, or
    the statement that nothing does (then the whole scenario layer). A deleted path counts as changed; a data file is matched
    by `covers` and by a story folder alone."""
    package = Path(package or PACKAGE)
    scripts, tests = package / "scripts", package / "scripts" / "tests"
    door_modules = door_modules or DOOR_MODULES
    if layers is None:
        import selftest
        layers = selftest.test_layers()
    scenarios = _scenarios(tests, scripts, door_modules)
    lines = ["test-layers.json is absent: no keep row is consulted, only the imports of the scenario doors"] \
        if layers.get("absent") else []
    for given in paths:
        rel, hits = _relative(given), []
        absolute = Path(given) if Path(given).is_absolute() else package / rel
        if not absolute.exists():
            lines.append(f"{rel}: deleted or absent on disk, counted as changed")
        is_script = rel.startswith("scripts/") and rel.endswith(".py")
        if not is_script and not rel.startswith("scripts/tests/"):
            lines.append(f"{rel}: not a script of scripts/, matched by keep `covers` and story folders only")
        stem = Path(rel).stem
        for test, (story_id, closure) in scenarios.items():
            if (is_script and stem in closure and "/tests/" not in rel) or rel.endswith("tests/scenario_walk.py") \
                    or f"fixtures/stories/{story_id}/" in rel:
                hits.append(f"{rel}: scenario {test} (story {story_id})")
        candidates = {rel, rel[len("scripts/"):] if rel.startswith("scripts/") else rel}
        for name, row in sorted((layers.get("keep") or {}).items()):
            if candidates & set(row.get("covers") or []):
                hits.append(f"{rel}: keep {name} (layer {row.get('layer')}, covers it)")
        if hits:
            lines += hits
        else:
            lines.append(f"no scenario or keep row covers {rel}: run the whole scenario layer")
            lines += [f"{rel}: {test}" for test in scenarios] or [f"{rel}: no test_scenario_*.py exists yet"]
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scenario walker helpers.")
    parser.add_argument("--witness-for", nargs="+", metavar="PATH", required=True,
                        help="changed paths; prints the scenario tests and keep rows that judge each")
    args = parser.parse_args(argv)
    print("\n".join(witness_for(args.witness_for)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
