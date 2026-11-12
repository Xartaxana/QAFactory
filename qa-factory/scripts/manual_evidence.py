"""Validate current manual evidence, write immutable blocks, and export safe public copies."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grammar as G
from event_store import atomic_json
from profile_contract import (ACCEPTS, CONTENT_FILES_FALLBACK, SHORT_SHA, acceptable_provenance, no_changed_file, refusal_text,
                              say_refusal, shown_files, validate_runtime_provenance)
from profile_contract import refusal_words as refusal_sentences   # this module has a `refusal_words(exc)` of its own
from role_cli import command_from_argv, epilog, refuse, run_guarded
import hooklib
from detector_verdict import compound, one_of
from hooklib import sorted_paths

KINDS = {"image", "log", "request_response", "state", "trace", "other"}
# `pre_action` / `post_action` are the words a capture is written with: the state before the action under
# test and the state after it. `before` / `after` are the OLD spelling of the same two: records written before
# the rename still validate, and `build` never writes them (one "before" for the person is `before_change`).
# The words are NOT listed here (t-277 F9, FR-13): `references/manual-capture-steps.json` holds them and
# grammar.py loads them once; `baseline` is the validator's own word for a before-state capture (never a
# capture phase, so it is not in the data file).
PHASES = set(G.MANUAL_PHASE_WORDS) | set(G.MANUAL_PHASE_ALIASES) | {"baseline"}
PHASE_ALIAS = {new: old for old, new in G.MANUAL_PHASE_ALIASES.items()}
POLICIES = {"ui", "api", "cli", "no_write", "static"}
RESULTS = ("pass", "fail", "inconclusive")
BEFORE_SOURCES = {"claim", "not_recorded"}
SAFE_EXPORT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".txt", ".log",
                        ".json", ".xml", ".csv", ".pdf", ".bin"}
# HF8-19: the verdict of a manual check stands on a quote of the text the attempt captured, one per Then.
THEN_QUOTE_MAX = 300           # characters of one quote: the shortest part of the captured text that decides a Then
QUOTE_SUFFIXES = (".txt", ".log", ".json", ".xml", ".csv")   # the capture files a quote is searched in (a picture: --then-seen)
REJUDGE_SENTENCE = "re-judged from the captures of attempt {attempt}, the check was not run again: {reason}"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _iso(value):
    try:
        return bool(value and datetime.fromisoformat(str(value).replace("Z", "+00:00")).tzinfo)
    except (TypeError, ValueError):
        return False


def _safe_evidence_path(root, raw):
    root = Path(root).resolve()
    relative = Path(str(raw or ""))
    if not raw or relative.is_absolute() or relative.parts[0:1] not in [("work",), ("evidence",)]:
        raise ValueError("evidence path must be task-relative under work/evidence or evidence")
    if relative.parts[0] == "work" and relative.parts[0:2] != ("work", "evidence"):
        raise ValueError("work evidence path must be under work/evidence")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("evidence path cannot contain symlinks")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("missing or unsafe evidence path")
    return resolved


def _provenance_errors(before, after, record, story, where="") -> list:
    """The provenance rules of ONE attempt's two probes: the record's own (`where` empty) and each joined profile's
    (`other_profiles`, FB-12) go through this one function, so a second profile is never held to less (AR-19)."""
    errors = []
    for probe in (before, after):
        checked = validate_runtime_provenance(probe)
        local_source = record.get("runtime_required") is False and record.get("target_kind") == "local_source"
        # ONE predicate (t-300 N2 S10, FR-17): `matched`; a person's word bound to THIS story (`person_confirmed`: the
        # record then carries the sentence that says so, `build_record`); a probe that compared nothing; and the
        # local_source `not_applicable` beside it (X3). `unknown` is refused, with or without an image (Q18-B,
        # FR-59): the rule just under this loop still makes before and after name the SAME identity, so a rebuild
        # between the two probes - or a new confirmation - is refused.
        if probe.get("result") == "not_applicable" and not no_changed_file(probe) and not local_source:
            errors.append(where + "runtime not_applicable requires local_source with runtime_required false, or "
                          "a probe that says `reason_code: no_changed_file`")
        elif not (acceptable_provenance(probe, ACCEPTS, task=story)
                  or (checked["valid"] and checked["result"] == "not_applicable" and local_source)):
            errors.append(where + "runtime provenance must be matched, the person's word for this story (person_confirmed), "
                          "or a valid local not_applicable: " + refusal_text(probe, task=story))
    for key in ("profile_id", "environment_id", "expected_source_revision", "observed_runtime_identity"):
        if before.get(key) != after.get(key):
            errors.append(where + "runtime provenance changed during the attempt")
    return errors


def _other_profile_errors(record, root) -> list:
    """`other_profiles[]` (FB-12): the stands of the OTHER profiles one record carries beside its own - each pair of probes
    passes the rules of the record's own pair, names the record's expected source revision, is bound to a checkout
    revision a run of this story recorded for ITS profile, and no profile appears twice. A record with none has no key."""
    others = record.get("other_profiles")
    if others is None:
        return []
    if not isinstance(others, list) or not others or any(not isinstance(part, dict) for part in others):
        return ["other_profiles must be a nonempty array of objects"]
    from coverage_contract import recorded_checkout_revisions
    story = Path(str(root)).name
    main = record.get("runtime_before") if isinstance(record.get("runtime_before"), dict) else {}
    errors, seen = [], [main.get("profile_id")]
    for index, part in enumerate(others):
        where = f"other_profiles[{index}] ({part.get('attempt') or 'no attempt named'}): "
        before, after = part.get("runtime_before"), part.get("runtime_after")
        steps = part.get("steps_actual")
        if not isinstance(steps, list) or not steps or any(not isinstance(x, str) or not x for x in steps):
            errors.append(where + "steps_actual must be a nonempty string array")
        if not isinstance(before, dict) or not isinstance(after, dict):
            errors.append(where + "runtime_before and runtime_after provenance required")
            continue
        errors.extend(_provenance_errors(before, after, record, story, where))
        if before.get("profile_id") in seen:
            errors.append(where + "its stand profile is already in this record: one attempt per profile")
        seen.append(before.get("profile_id"))
        if before.get("expected_source_revision") != main.get("expected_source_revision"):
            errors.append(where + "it names another expected_source_revision than the record's own attempt: one "
                          "record is one source revision")
        for probe in (before, after):
            if probe.get("result") != "not_applicable" and probe.get("expected_source_revision") not in \
                    recorded_checkout_revisions(root, probe.get("profile_id")):
                errors.append(where + "its runtime proof binds a checkout revision no run of this story recorded for "
                              "its profile: run runtime_probe.py for that profile so its revision is on record")
    return errors


def _squash(text) -> str:
    """`text` with every run of whitespace (Unicode ones too) as one space, the ends cut: how a quote and a capture are compared."""
    return " ".join(str(text).split())


def _json_strings(value) -> list:
    """Every string VALUE of a parsed JSON document (a stack, not a recursion: a deep document is a document, not a crash)."""
    stack, out = [value], []
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return out


def _text_views(root, ref) -> list:
    """The texts of ONE capture file a quote may stand in: the file as it is, and for `.json` also each string value
    parsed (so a Cyrillic quote is found behind its `\\uXXXX` escapes). `[]` for a file that is no text capture or cannot
    be read (the hash check names an unreadable one; here it only means the quote is not found in it). Read with
    `errors="replace"`: the error goes toward NOT finding the quote, a false refusal that has a door."""
    suffix = Path(str(ref.get("path") or "")).suffix.lower()
    if suffix not in QUOTE_SUFFIXES:
        return []
    try:
        text = _safe_evidence_path(root, ref.get("path")).read_bytes().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return []
    views = [_squash(text)]
    if suffix == ".json":
        try:
            views.extend(_squash(value) for value in _json_strings(json.loads(text)))
        except (ValueError, RecursionError):
            pass
    return views


def _quote_in(root, ref, quote) -> bool:
    wanted = _squash(quote)
    return bool(wanted) and any(wanted in view for view in _text_views(root, ref))


def _cut_capture(root, ref, limitations=()) -> bool:
    """True when the capture `ref` was stored cut (a body above BODY_CAP): its JSON says `truncated: true`, or the record
    carries the capture tool's `body cut at` limitation. Only used to NAME why a quote is not found (E6): the stored bytes
    decide, a quote beyond the cut is never accepted, and a wrong guess here changes the words of the refusal, nothing else."""
    import manual_capture as MC       # F11: the opening words of the sentence are `manual_capture.CUT_WORDS`, not a copy
    if any(isinstance(x, str) and MC.CUT_WORDS in x for x in limitations or []):
        return True
    try:
        text = _safe_evidence_path(root, ref.get("path")).read_bytes().decode("utf-8", errors="replace")
        stack = [json.loads(text)]
    except (OSError, ValueError, RecursionError):
        return False
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get("truncated") is True:
                return True
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False


def _beyond_words(root, ref, limitations=()) -> str:
    """What a refusal of a quote that is not in the capture `ref` adds when the capture was stored cut: that the quote is beyond
    the stored part (E6). "" for a capture stored whole."""
    if not _cut_capture(root, ref, limitations):
        return ""
    return ": the quote is beyond the stored part (truncated); the capture holds only its first bytes"


OBSERVATION_FIELDS = ("step", "expected", "seen", "evidence", "quote")


def _observe_text(root, record, step) -> str:
    """The `observe_text` (the excerpt of the screen after the step, written by the capture tool) of step number `step` (1-based, the line
    of the attempt's `steps.jsonl`), or "" when the attempt's step rows hold none. The attempt is the record's own (a re-judge reads the
    attempt it re-judged)."""
    try:
        import manual_capture as MC
        attempt = record.get("rejudge_of") or record.get("attempt_id")
        folder = MC.case_root(Path(root).resolve(), str(record.get("case"))) / str(attempt)
        excerpt = folder / MC.OBSERVE_DIR / f"{step:03d}-excerpt.txt"      # F7: the capture tool writes it next to the picture
        if excerpt.is_file():
            return excerpt.read_text(encoding="utf-8")
        rows = _jsonl(folder / "steps.jsonl")        # an attempt made before F7 kept it in the step's own line
        return str(rows[step - 1].get("observe_text") or "")
    except (OSError, ValueError, IndexError, AttributeError, TypeError):
        return ""


def _observation_errors(record, root) -> list:
    """`observations[]` of a record that has the field (P26): every doubtful thing the runner saw, at ANY step, not only the Then
    verdicts. Each entry names the `step` (1..len(steps_actual)), what was `expected`, what was `seen`, the `evidence` (a capture
    of THIS record's attempt, as `evidence_refs` lists it) and a `quote` of at most THEN_QUOTE_MAX characters that stands in
    that capture's text - or, when the capture is a picture, in the `observe_text` code wrote for that step. Whitespace is the
    only thing normalised (`_squash`): case is not. The error goes toward refusing a good quote, never toward accepting a made-up
    one. `[]` is the declared empty outcome; an absent field is read as `[]` here (a record made before the rule, E14), and
    `build` / `rejudge` demand it for the records they write (`_declared_errors`). Code checks the words are THERE; whether they
    are a bug is the analyst's."""
    observations = record.get("observations")
    if observations is None:
        return []
    if not isinstance(observations, list) or any(not isinstance(entry, dict) for entry in observations):
        return ["observations must be an array of objects ([] when there is nothing to report)"]
    steps = record.get("steps_actual") if isinstance(record.get("steps_actual"), list) else []
    by_path = {str(ref.get("path")): ref for ref in record.get("evidence_refs") or [] if isinstance(ref, dict)}
    limitations = record.get("limitations") if isinstance(record.get("limitations"), list) else []
    errors = []
    for index, entry in enumerate(observations):
        where = f"observations[{index}]"
        absent = [key for key in OBSERVATION_FIELDS if entry.get(key) in (None, "")]
        problems = [f"{where}.{key} is missing" for key in absent]
        step = entry.get("step")
        if "step" not in absent and (not isinstance(step, int) or isinstance(step, bool) or not 1 <= step <= len(steps)):
            problems.append(f"{where}.step must be the number of a step of this attempt (1..{len(steps)})")
        for key in ("expected", "seen", "evidence", "quote"):
            if entry.get(key) not in (None, "") and (not isinstance(entry[key], str) or not _squash(entry[key])):
                problems.append(f"{where}.{key} must be words")
        if problems:
            errors.extend(problems)
            continue
        quote = _squash(entry["quote"])
        if len(quote) > THEN_QUOTE_MAX:
            errors.append(f"{where}.quote: at most {THEN_QUOTE_MAX} characters, the shortest part that shows it")
            continue
        ref = by_path.get(entry["evidence"].strip())
        if ref is None:
            errors.append(f"{where}.evidence is not a capture of this record's attempt (the path as evidence_refs lists it)")
        elif Path(str(ref.get("path"))).suffix.lower() in QUOTE_SUFFIXES:
            if not _quote_in(root, ref, quote):
                errors.append(f"the quote of {where} is not in {Path(str(ref.get('path'))).name}"
                              + _beyond_words(root, ref, limitations))
        else:
            excerpt = _squash(_observe_text(root, record, step))
            if not excerpt:
                errors.append(f"the quote of {where} cannot be checked: {Path(str(ref.get('path'))).name} is a picture and "
                              f"step {step} has no observe_text; name a text capture, or quote the words from the excerpt of a "
                              "step that has one")
            elif quote not in excerpt:
                errors.append(f"the quote of {where} is not in the excerpt (observe_text) of step {step}")
    return errors


def _declared_errors(record) -> list:
    """The rule for a record written NOW (`build`, `rejudge`): `observations` is declared, `[]` when the runner saw nothing doubtful
    (AR-23, FR-38). Records made before the rule have no field and are read as `[]` (E14); they are not asked again. (The recorder's
    surprise fields are NOT asked of a record written by hand: `write-block` adds them from the attempt's own files, `_hand_surprises`.)"""
    if "observations" in record:
        return []
    return ["declare observations: [] when you saw nothing doubtful (observations: [{step, expected, seen, evidence, quote}] "
            "otherwise)"]


def surprises_of(folder) -> list:
    """Every `surprise` line of `<folder>/surprises.jsonl` in file order; `[]` when the
    file is absent, empty or holds no such line. The ONE reader of the lines (AR-13): `build`, `rejudge`, `write-block` and
    `--with-attempt` ask it, and the capture tool is their only writer (AR-14). A line that is not JSON is skipped by the ONE tolerant
    reader (`manual_capture._surprise_rows`), and `detection_of` says the attempt was not fully watched (a damaged file never reads as `on`). Pure data, no judgment (AR-29)."""
    import manual_capture as MC
    try:
        rows, _ = MC._surprise_rows(folder)
    except OSError:
        return []
    return [row for row in rows if row.get("line") == "surprise" and isinstance(row.get("id"), str) and row["id"].strip()]


def detection_of(folder) -> str:
    """`on` | `partial: ...` | `absent: <why>`: how much of the attempt the detector WATCHED, read from the `detector` lines of
    `<folder>/surprises.jsonl` by the capture tool's own reader (`manual_capture._detection_of`, AR-13 - one reading for the
    summary of a call and for the record). A file that cannot be read is `absent`, never `on` (AR-28, E15)."""
    import manual_capture as MC
    try:
        return MC._detection_of(folder)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return f"absent: surprises.jsonl of the attempt cannot be read ({exc.__class__.__name__}): the detector's lines are lost"


def _detection_of_attempts(parts) -> str:
    """The one `surprise_detection` of a record built from several attempts (`--with-attempt`): `on` only when EVERY attempt was
    watched whole; otherwise `partial: attempt <a>: <its words>` for each attempt that was not (an unknown never becomes a pass,
    AR-28). One attempt: its own words."""
    parts = list(parts)
    if len(parts) == 1:
        return parts[0][1]
    if all(words == "on" for _, words in parts):
        return "on"
    return "partial: " + "; ".join(f"attempt {name}: {words}" for name, words in parts if words != "on")


def _surprise_evidence(task, refs) -> dict:
    """`{surprise id: path of the capture that holds its line}`: the `NNN-surprises.txt` captures of the record's evidence
    (`proves` has `surprises`), each line `surprise: <id> step ...`. A line no capture holds is not in the map (the entry then
    carries `evidence: ""`)."""
    found = {}
    for ref in refs:
        if not isinstance(ref, dict) or "surprises" not in (ref.get("proves") or []):
            continue
        try:
            text = (Path(task) / str(ref.get("path"))).read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        for line in text.splitlines():
            parts = line.split(" ", 2)
            if len(parts) > 2 and parts[0] == "surprise:":
                found.setdefault(parts[1], str(ref.get("path")))
    return found


def _surprise_fields(task, root, names, refs) -> dict:
    """The two fields every record written NOW carries (AR-23, AR-27): `surprises` - every line the attempts `names` (the main one
    first, then the joined ones) wrote, `[{id, step, kind, fact, evidence}]`, in the order of the files; `surprise_detection` -
    `detection_of`. `[]` is NOT 'nothing happened': the detection says whether anyone watched (E15). Code carries the lines;
    whether one is a bug is the analyst's (AR-29)."""
    lines = [(name, row) for name in names for row in surprises_of(Path(root) / name)]
    where = _surprise_evidence(task, refs)
    return {"surprises": [{"id": row["id"], "step": row.get("step"), "kind": row.get("kind"), "word": row.get("word"), "fact": row.get("fact"),
                           "evidence": where.get(row["id"], "")} for _, row in lines],
            "surprise_detection": _detection_of_attempts((name, detection_of(Path(root) / name)) for name in names)}


def _surprise_cite_errors(observations, known, attempts, door) -> list:
    """The `surprise` key of `observations[]` (an observation that cites a surprise line by id, so the line is not a target of its own):
    a non-empty string that is the id of a line of THIS record's attempts (`known`: every line of their `surprises.jsonl`).
    A cross-reference only - whether the cited line is a bug is the analyst's (AR-29). An id of an attempt the
    record does not hold is refused with `door` (`build`: `--with-attempt <attempt>`); `observations` that is no list of objects is
    `_observation_errors`' to say. Pure, never raises."""
    if not isinstance(observations, list):
        return []
    errors = []
    for index, entry in enumerate(observations):
        if not isinstance(entry, dict) or "surprise" not in entry:
            continue
        cited, where = entry["surprise"], f"observations[{index}].surprise"
        if not isinstance(cited, str) or not cited.strip():
            errors.append(f"{where} must be the id of a surprise line (for example a2-ui-S3), or the key left out")
        elif cited.strip() not in known:
            owner = cited.strip().partition("-")[0]
            if owner and owner not in attempts and re.fullmatch(r"a[0-9]+", owner):
                errors.append(f"{where} {cited.strip()!r} is a surprise of attempt {owner}, which this record does not hold. "
                              f"Door: {door.format(attempt=owner)}")
            else:
                errors.append(f"{where} {cited.strip()!r} is no surprise line of {', '.join(attempts)} "
                              f"(its ids: {', '.join(sorted(known)[:8]) or 'none - no surprise was written'}). Door: cite one of them, "
                              "or leave the `surprise` key out and quote the capture as for any observation")
    return errors


def _hand_surprises(task, record) -> tuple:
    """`(attempts, known ids, fields)` of a record handed to `write-block`: the attempts it names (`rejudge_of` or `attempt_id`, then
    its `other_profiles`), the ids of every line their `surprises.jsonl` hold, and the two fields `_surprise_fields` computes from
    those files - `None` when the attempt has no folder (a record whose files are not here: its own `surprises` are all there is
    to cite, and nothing is added). Pure data, never raises."""
    case, main = record.get("case"), record.get("rejudge_of") or record.get("attempt_id")
    own = [str(row.get("id")) for row in record.get("surprises") or [] if isinstance(row, dict)]
    try:
        import manual_capture as MC
        root = MC.case_root(Path(task), case)
        names = [str(main)] + [str(p.get("attempt")) for p in record.get("other_profiles") or [] if isinstance(p, dict)]
        if not isinstance(case, str) or not main or not (root / names[0]).is_dir():
            return [str(main)], set(own), None
        refs = record.get("evidence_refs") if isinstance(record.get("evidence_refs"), list) else []
        return names, {row["id"] for n in names for row in surprises_of(root / n)}, _surprise_fields(task, root, names, refs)
    except (OSError, ValueError, TypeError, AttributeError):
        return [str(main)], set(own), None


def _then_quote_errors(record, root) -> list:
    """`then_quotes[]` of a record that has them (a record made before HF8-19 has none and is not refused): every entry
    names a Then, a quote of at most THEN_QUOTE_MAX characters that stands in a text capture of THIS record's evidence (or
    a picture of it, `kind: seen`), or says `reached: false`. Re-read from the files at every validation, so a forged or
    moved quote does not hold a verdict (I1). Code checks that the quote is THERE; it never judges what it says."""
    quotes = record.get("then_quotes")
    if quotes is None:
        return []
    if not isinstance(quotes, list) or any(not isinstance(entry, dict) for entry in quotes):
        return ["then_quotes must be an array of objects"]
    by_path = {str(ref.get("path")): ref for ref in record.get("evidence_refs") or [] if isinstance(ref, dict)}
    errors, seen = [], set()
    for index, entry in enumerate(quotes):
        where = f"then_quotes[{index}]: "
        number = entry.get("then")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            errors.append(where + "`then` must be the number of a Then")
            continue
        if number in seen:
            errors.append(where + f"Then {number} appears twice")
        seen.add(number)
        if entry.get("reached") is False:
            if "quote" in entry:
                errors.append(where + f"Then {number} is unreached and carries no quote")
            continue
        quote = entry.get("quote")
        if not isinstance(quote, str) or not _squash(quote):
            errors.append(where + f"Then {number} has no quote")
            continue
        if len(_squash(quote)) > THEN_QUOTE_MAX:
            errors.append(where + f"Then {number}: quote at most {THEN_QUOTE_MAX} characters, the shortest part that decides")
        source = by_path.get(str(entry.get("source")))
        if entry.get("kind") == "text":
            if source is None or Path(str(source.get("path"))).suffix.lower() not in QUOTE_SUFFIXES:
                errors.append(where + f"Then {number}: its source is not a text capture of this record's attempt")
            elif not _quote_in(root, source, quote):
                errors.append(where + f"Then {number}: the quote is not in {Path(str(source.get('path'))).name}"
                              + _beyond_words(root, source, record.get("limitations") if isinstance(record.get("limitations"), list) else []))
        elif entry.get("kind") == "seen":
            if source is None or source.get("kind") != "image":
                errors.append(where + f"Then {number}: the picture it names is not an image of this record's attempt")
        else:
            errors.append(where + f"Then {number}: kind is text or seen")
    return errors


def _by_phase(refs) -> tuple:
    """`(phases, by_phase)` of the evidence refs: the rules speak the old two words, `pre_action` / `post_action` read as the same phases."""
    phases = set()
    by_phase = {phase: [] for phase in ("before", "after", "supporting", "baseline")}
    for ref in refs if isinstance(refs, list) else []:
        if isinstance(ref, dict) and ref.get("phase") in PHASES:
            phase = PHASE_ALIAS.get(ref["phase"], ref["phase"])
            phases.add(phase)
            by_phase[phase].append(ref)
    return phases, by_phase


def _result_errors(record, policy, phases, by_phase) -> list:
    """What the record's RESULT needs of its evidence - the ONE place of these rules: `validate` asks it of a record, `walk_rule_errors`
    asks it of a walk's verdict while the session lives (the same function, never a copy). FR-23: an `inconclusive` result is a
    recordable outcome under EVERY policy - the check could not be completed, so the phase rules (which describe a completed check) do
    not apply; what it needs is at least one evidence ref and a limitation that says what stopped it. pass and fail keep the full phase
    rules, and an inconclusive record is never coverage (coverage_contract: inconclusive != passed)."""
    errors = []
    judged = record.get("result") in {"pass", "fail"}
    if record.get("result") == "inconclusive" and not any(
            isinstance(x, str) and x.strip() for x in record.get("limitations") or []):
        errors.append("inconclusive requires a limitation: say in `limitations[]` what stopped the check "
                      "(`manual_evidence.py build --limitation \"<words>\"`)")
    if judged and policy == "ui" and not {"before", "after"}.issubset(phases):
        errors.append("ui requires pre_action and post_action evidence (the old before and after read the same)")
    elif judged and policy == "ui" and any(not any(r.get("kind") in {"image", "trace"} for r in by_phase[p])
                                           for p in ("before", "after")):
        errors.append("ui requires visual or trace evidence before and after")
    if judged and policy in {"api", "cli"}:
        all_refs = [r for values in by_phase.values() for r in values]
        if ("after" not in phases or not any(r.get("kind") in {"request_response", "log"} for r in all_refs)
                or not any(r.get("kind") == "state" for r in by_phase["after"])):
            errors.append("api/cli requires request/output and post_action state evidence")
    if judged and policy == "no_write":
        before_state = any(r.get("kind") == "state" for r in by_phase["before"])
        after_state = any(r.get("kind") == "state" for r in by_phase["after"])
        completion = any("completion" in [str(x).lower() for x in r.get("proves", [])]
                         for r in by_phase["after"])
        if not before_state or not after_state or not completion:
            errors.append("no_write requires before and after state evidence and completion proof: "
                          "evidence_refs entries with `kind: state` for both `phase: pre_action` and "
                          "`phase: post_action`, and \"completion\" in the post_action entry's `proves`")
    if judged and policy == "static" and (not record.get("before_not_applicable_reason") or "after" not in phases):
        errors.append("static requires explicit before reason and post_action evidence: set "
                      "`before_not_applicable_reason` and add an evidence_refs entry with `phase: post_action`")
    if record.get("result") == "pass" and not any(
            "completion" in [str(x).lower() for x in ref.get("proves", [])]
            for ref in by_phase["after"]):
        errors.append("pass requires post_action evidence proving completion: one evidence_refs entry with "
                      "`phase: post_action` must list \"completion\" in its `proves` array (the runner's "
                      "`capture post_action completion` line)")
    return errors


def validate(record, root):
    if not isinstance(record, dict):
        return ["manual evidence record must be an object"]
    errors = []
    if record.get("schema_version") != 2:
        errors.append("schema_version must be 2")
    for field in ("case", "case_version", "attempt_id", "dispatch_id", "source_revision",
                  "runtime_identity", "expected", "actual", "completion_condition"):
        if not record.get(field):
            errors.append(f"missing {field}")
    ids = record.get("obligation_ids")
    singular = record.get("obligation_id")
    if singular and ids is not None:
        errors.append("use singular obligation_id or obligation_ids, not both")
    ids = ids if ids is not None else ([singular] if singular else [])
    if (not isinstance(ids, list) or not ids or any(not isinstance(x, str) or not x for x in ids)
            or len(ids) != len(set(ids))):
        errors.append("nonempty unique obligation_id(s) required")
    hashes = record.get("obligation_hashes")
    if not isinstance(hashes, dict) or set(hashes) != set(ids) or any(not hashes.get(x) for x in ids):
        errors.append("obligation_hashes must exactly bind obligation_id(s)")
    steps = record.get("steps_actual")
    if not isinstance(steps, list) or not steps or any(not isinstance(x, str) or not x for x in steps):
        errors.append("steps_actual must be a nonempty string array")
    if not _iso(record.get("attempt_started_at")) or not _iso(record.get("attempt_ended_at")):
        errors.append("attempt timestamps must be timezone-aware ISO-8601")
    else:
        started = datetime.fromisoformat(record["attempt_started_at"].replace("Z", "+00:00"))
        ended = datetime.fromisoformat(record["attempt_ended_at"].replace("Z", "+00:00"))
        if ended < started:
            errors.append("attempt ended before it started")
    if record.get("result") not in RESULTS:
        errors.append("invalid result (one of " + one_of(RESULTS) + ")")
    policy = record.get("evidence_policy")
    if policy not in POLICIES:
        errors.append("invalid evidence_policy (one of " + one_of(POLICIES) + ")")
    if not isinstance(record.get("limitations"), list):
        errors.append("limitations must be an explicit array")
    before, after = record.get("runtime_before"), record.get("runtime_after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        errors.append("runtime_before and runtime_after provenance required")
    else:
        # the story this record belongs to: a person's word is bound to ONE story (X5)
        errors.extend(_provenance_errors(before, after, record, Path(str(root)).name))
    errors.extend(_other_profile_errors(record, root))
    errors.extend(_then_quote_errors(record, root))
    errors.extend(_observation_errors(record, root))
    # C11 (t-2181 PC-5a): the sides a walked case speaks about are sides of THIS story. Data only (names against the story's
    # record, read through `contract.story_sides`, AR-13); whether the case speaks about the right sides is the S6 acceptance's.
    if record.get("about") is not None:
        about = record["about"]
        if not isinstance(about, list) or any(not isinstance(x, str) or not x for x in about):
            errors.append("about must be an array of side names, e.g. [\"ui\"]. Door: write `about` as a list of the story's side "
                          "names, or leave it out")
        else:
            import contract as C
            from run_suite import story_pipeline     # the one reader of the story's record for a stamp (BOM-safe, absent vs unreadable)
            pipeline, unreadable = story_pipeline(Path(str(root)) / "pipeline.json")
            known = sorted(C.story_sides(pipeline))
            unknown = [name for name in about if name not in known]
            if unreadable and about:
                errors.append("about names " + ", ".join(repr(n) for n in about) + ", but the story's sides could not be read ("
                              + unreadable + "). Door: repair the story's pipeline.json, or leave `about` out")
            elif unknown:
                errors.append("about names " + ", ".join(repr(n) for n in unknown) + ", not a side of this story (its sides: "
                              + (", ".join(known) or "none read") + "). Door: name only those sides in `about`, or leave "
                              "`about` out when the case does not speak about a particular side")
    refs = record.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        errors.append("evidence_refs required")
        refs = []
    phases, by_phase = _by_phase(refs)
    for ref in refs:
        if not isinstance(ref, dict):
            errors.append("evidence ref must be an object")
            continue
        if ref.get("kind") not in KINDS:
            errors.append("invalid evidence kind")
        if ref.get("phase") not in PHASES:
            errors.append("invalid evidence phase: use " + " | ".join(G.MANUAL_PHASE_WORDS))
        elif PHASE_ALIAS.get(ref["phase"], ref["phase"]) == "baseline":
            errors.append("baseline evidence belongs only to an evidence_phase=baseline capture")
        if not _iso(ref.get("captured_at")):
            errors.append("evidence captured_at must be timezone-aware ISO-8601")
        if not isinstance(ref.get("proves"), list) or not ref.get("proves"):
            errors.append("evidence proves must be a nonempty array")
        if ref.get("kind") == "other" and not ref.get("format_description"):
            errors.append("other evidence requires format_description")
        if ref.get("mask_acknowledged") is not True:
            errors.append("evidence must acknowledge masking before public export")
        content_hash = ref.get("content_hash")
        if not isinstance(content_hash, str) or len(content_hash) != 64:
            errors.append("evidence content_hash required")
            continue
        try:
            path = _safe_evidence_path(root, ref.get("path"))
            if digest(path) != content_hash:
                errors.append("evidence hash mismatch")
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    errors.extend(_result_errors(record, policy, phases, by_phase))
    change = record.get("before_change")
    if change is not None:
        if not isinstance(change, dict) or change.get("source") not in BEFORE_SOURCES:
            errors.append("before_change must be {r, value, ref, source} with source claim | not_recorded")
        elif change["source"] == "claim" and not all(change.get(k) for k in ("r", "value", "ref")):
            errors.append("before_change from a claim needs r, value and ref (the register's `## Behaviour "
                          "claims` row)")
    if record.get("result") == "pass" and errors:
        errors.append("incomplete evidence cannot claim pass")
    return sorted(set(errors))


def person_sentences(probe) -> list:
    """The sentences code writes into `limitations[]` of a manual record whose stand identity is a PERSON'S WORD
    (`person_confirmed`, t-300 N2 S12): who confirmed it, when, and that the factory did not read it; and, when the word
    was `test deployed` (the confirmation names this story's commit), that the build under test is another one. Built from
    FIELDS of the probe record only (FR-12), the words from `refusals` of references/build-identity-methods.json (FR-13).
    Empty for any other record. ONE function: `build_record` writes them and `s7_pretriage.code_sentences` recognises them
    as code's, not the role's (a role's limitation is never mistaken for it, and it is never the role's)."""
    if not isinstance(probe, dict) or probe.get("result") != "person_confirmed":
        return []
    confirmation = probe.get("person_confirmation") if isinstance(probe.get("person_confirmation"), dict) else {}
    table = refusal_sentences()
    if confirmation.get("kind") == "content_accepted":
        # FB-8: ONE sentence for this kind, in place of the base sentence (the person named no build)
        return [say_refusal("person_content", table, words=str(confirmation.get("words") or "").strip(),
                            date=str(confirmation.get("at") or "")[:10],
                            files=shown_files(probe.get("accepted_files"), table) or CONTENT_FILES_FALLBACK)]
    out = [say_refusal("person_confirmed", table, words=str(confirmation.get("words") or "").strip(),
                       date=str(confirmation.get("at") or "")[:10])]
    if confirmation.get("story_revision"):
        out.append(say_refusal("person_tested", table,
                               tested=str(confirmation.get("revision") or probe.get("tested_build") or "")[:SHORT_SHA],
                               expected=str(confirmation.get("story_revision") or "")[:SHORT_SHA]))
    return out


def validate_record(record, task_root, policy=None):
    """Public reader API; planned policy cannot be substituted after capture."""
    if not isinstance(record, dict):
        return ["manual evidence record must be an object"]
    if record.get("evidence_phase") == "baseline":
        return validate_baseline_record(record, task_root)
    if policy is not None and record.get("evidence_policy") != policy:
        return ["evidence_policy does not match the planned obligation"]
    return validate(record, task_root)


def validate_baseline_record(record, task_root):
    """A manual before-state capture is not a manual verification result."""
    from baseline_contract import validate_baseline_request
    errors = []
    for field in ("case", "case_version", "dispatch_id", "source_revision", "steps_actual",
                  "runtime_before", "runtime_after", "baseline_contract", "capture_status"):
        if not record.get(field):
            errors.append(f"baseline missing {field}")
    if record.get("result") in {"pass", "fail"}:
        errors.append("baseline capture cannot carry a product pass/fail result")
    if record.get("capture_status") not in {"captured", "inconclusive"}:
        errors.append("baseline capture_status must be captured or inconclusive")
    contract = record.get("baseline_contract") or {}
    request = {"evidence_phase": "baseline", "baseline_contract": contract,
               "runtime_provenance": record.get("runtime_before")}
    errors.extend(validate_baseline_request(request))
    if contract.get("case_id") != record.get("case") or contract.get("case_version") != record.get("case_version"):
        errors.append("baseline contract case/version must match manual capture")
    if record.get("source_revision") != contract.get("baseline_revision"):
        errors.append("manual baseline source revision must match baseline revision")
    if not set(contract.get("capture_steps") or []).issubset(set(record.get("steps_actual") or [])):
        errors.append("manual baseline actual steps must include approved capture steps")
    for probe in (record.get("runtime_before") or {}, record.get("runtime_after") or {}):
        checked = validate_runtime_provenance(probe)
        if checked["result"] == "person_confirmed":
            # t-300 N2 S11: the baseline is a measured OLD build - the person's word that this story's build is on the
            # stand says nothing about the old one, so it never stands in (FR-58; the registry row keeps it code-proven)
            errors.append(say_refusal("baseline_person"))
        elif not checked["valid"] or checked["result"] not in {"matched", "not_applicable"}:
            errors.append("manual baseline runtime provenance is unverified")
        if probe.get("expected_source_revision") != contract.get("baseline_revision"):
            errors.append("manual baseline runtime must match baseline revision")
    if ((record.get("runtime_before") or {}).get("observed_runtime_identity") !=
            (record.get("runtime_after") or {}).get("observed_runtime_identity")):
        errors.append("manual baseline runtime identity changed during capture")
    refs = record.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        errors.append("baseline evidence_refs required")
    else:
        for ref in refs:
            if not isinstance(ref, dict) or ref.get("phase") != "baseline":
                errors.append("manual baseline evidence uses only baseline phase")
                continue
            try:
                path = _safe_evidence_path(task_root, ref.get("path"))
                if digest(path) != ref.get("content_hash"):
                    errors.append("baseline evidence hash mismatch")
            except (OSError, ValueError) as exc:
                errors.append(str(exc))
    return sorted(set(errors))


def write_baseline_receipt(task_root, record):
    """Persist manual capture separately so the S6 reducer cannot project it as coverage."""
    root = Path(task_root).resolve()
    errors = validate_baseline_record(record, root)
    if errors:
        raise ValueError("; ".join(errors))
    contract = record["baseline_contract"]
    refs = [{"path": ref["path"], "sha256": ref["content_hash"]} for ref in record["evidence_refs"]]
    receipt = {"schema_version": 1, "evidence_phase": "baseline", "status": record["capture_status"],
               "case_id": record["case"], "case_version": record["case_version"],
               "baseline_revision": contract["baseline_revision"],
               "verification_revision": contract["verification_revision"],
               "fixture_identity": contract["fixture_identity"],
               "gate_a_decision_ref": contract["gate_a_decision_ref"], "reason": contract["reason"],
               "capture_steps": contract["capture_steps"], "comparison_assertions": contract["comparison_assertions"],
               "source_revision": record["source_revision"], "runtime_identity": record["runtime_before"].get("observed_runtime_identity"),
               "attempt_id": record.get("attempt_id") or record["dispatch_id"],
               "captured_at": record.get("attempt_ended_at"), "execution_status": "manual_capture",
               "evidence_refs": refs, "gap": "" if record["capture_status"] == "captured" else "manual baseline capture inconclusive"}
    digest_key = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
    directory = root / "work" / "baseline-receipts"; directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"manual-{digest_key}.json"; text = json.dumps(receipt, indent=2) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError("manual baseline receipt identity conflict")
    else:
        atomic_json(path, receipt)
    return path


def _copy_atomic(source, target, expected):
    if target.parent.exists() and target.parent.is_symlink():
        raise ValueError("public evidence directory cannot be a symlink")
    target.parent.mkdir(parents=True, exist_ok=True)
    if digest(source) != expected:
        raise ValueError("source changed before public export")
    if target.exists():
        if target.is_symlink() or digest(target) != expected:
            raise ValueError("public export hash conflict")
        return
    temp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        with source.open("rb") as inp, temp.open("xb") as out:
            shutil.copyfileobj(inp, out)
            out.flush()
            os.fsync(out.fileno())
        if digest(source) != expected or digest(temp) != expected:
            raise ValueError("evidence changed during public export")
        os.replace(temp, target)
        if digest(target) != expected:
            raise ValueError("public evidence verification failed")
    finally:
        if temp.exists():
            temp.unlink()


def export_records(task_root, records):
    """Export only supplied current records; one failed artifact rejects its entire row."""
    root = Path(task_root).resolve()
    rows, errors = [], []
    for record in records or []:
        case = record.get("case") if isinstance(record, dict) else None
        issue = validate_record(record, root)
        if issue:
            errors.append({"case": case, "errors": issue})
            continue
        public = []
        try:
            for ref in record["evidence_refs"]:
                source = _safe_evidence_path(root, ref["path"])
                content_hash = ref["content_hash"]
                candidate_suffix = "".join(c for c in source.suffix.lower()
                                           if c.isalnum() or c == ".") or ".bin"
                suffix = candidate_suffix if candidate_suffix in SAFE_EXPORT_SUFFIXES else ".bin"
                target = root / "evidence" / f"{content_hash}{suffix}"
                _copy_atomic(source, target, content_hash)
                public.append({**ref, "path": target.relative_to(root).as_posix(), "sha256": content_hash})
        except (OSError, ValueError) as exc:
            errors.append({"case": case, "errors": [str(exc)]})
            continue
        rows.append({**record, "evidence_refs": public, "evidence_validated": True})
    return {"rows": rows, "errors": errors}


def _validate_current(task, record):
    from coverage_contract import validate_manual_current
    return validate_manual_current(task, record)


def _case_obligation_mapping(task, rows, case):
    """Resolve the approved case-to-obligation join from pinned case traceability."""
    import contract as C
    index = C.case_index(task)
    if case not in index:
        raise ValueError('manual request requires an indexed pinned case')
    case_fact = index[case]
    requirements = set(case_fact.get('requirements') or [])
    plan_row = case_fact.get('plan_row')
    if not requirements or not plan_row:
        return set()
    mapped = set()
    for row in rows:
        if plan_row and row.get('id') != plan_row:
            continue
        for obligation in row.get('coverage_obligations') or []:
            refs = {ref.get('ref') for ref in obligation.get('requirement_refs') or []
                    if isinstance(ref, dict)}
            if refs & requirements:
                mapped.add(obligation.get('obligation_id'))
    return {value for value in mapped if value}


def _legacy_evidence_gaps(task):
    """Inventory legacy blocks as gaps without rewriting or accepting their raw evidence."""
    gaps = []
    for path in sorted_paths((Path(task) / 'work' / 'manual-blocks').glob('*.json')):
        try:
            block = json.loads(path.read_text(encoding='utf-8-sig'))
            records = block.get('records') or block.get('manual_checks') or []
            if not isinstance(records, list):
                records = []
            for index, record in enumerate(records):
                if not isinstance(record, dict) or record.get('schema_version') != 2 or not record.get('obligation_hashes'):
                    gaps.append({'path': path.relative_to(task).as_posix(), 'record': index,
                                 'reason': 'legacy evidence lacks current schema or obligation binding'})
        except (OSError, ValueError, AttributeError):
            gaps.append({'path': path.relative_to(task).as_posix(), 'record': None,
                         'reason': 'legacy evidence block is unreadable'})
    return gaps


class Refused(ValueError):
    """A refusal with its two halves. `reason` is in words a person can read (the report quotes it, so no
    field name or row id the person has never seen); `door` is what ends it - the person's answer, or the
    orchestrator's operation - and is never a dead end (FR-1, FR-57). `str()` is both, for a role."""

    # F5(c) (B-15, FR-46): `walkable` is True ONLY for the factory's own preparation failures (a malformed plan row shape, a
    # tool crash after the scope checks); then the case still goes to the manual agent as an unprepared walk. The default is
    # False - every refusal the story owns (P20, gate A, an unpinned case, the scope) stays a refusal. `trace` is the last
    # lines of the traceback of a crash (C3), kept in the request file for the conductor.
    def __init__(self, reason, door, detail="", door_code="", walkable=False, trace=""):
        super().__init__(f"{reason} - {door}" + (f" [{detail}]" if detail else ""))
        self.reason, self.door, self.door_code = reason, door, door_code
        self.detail, self.walkable, self.trace = detail, bool(walkable), trace


TRACE_LINES = 20       # C3: how many last lines of a traceback the request file keeps


def _trace_tail() -> str:
    import traceback
    return "".join(traceback.format_exc().splitlines(True)[-TRACE_LINES:]).strip()


# t-263 D6 (FR-6): `reason` and `door` are what the report quotes to a person, so neither names an operation of
# ours. The operation the orchestrator runs for the door travels in its own machine field, `door_code`
# (`request.json` `refused.door_code`), which no report prints.
_REOPEN_CODE = "semantic_reopen"
_REOPEN = ("reopen gate A for this case so the plan is approved again with this check executable by hand; "
           "until then the case stands as not checked by hand")
# A path into the story's machine inputs, as an exception message carries it. A person cannot open it and does
# not need to: the sentence names the record's KIND (REPORT_FORBIDDEN `work/`).
_WORK_PATH_RE = re.compile(r"""[^\s'"()\[\]]*\bwork[\\/][^\s'"()\[\]]*""")
_RECORD_KINDS = (("test-plan", "the plan"), ("requirements-readiness", "the questions record"),
                 ("requirements-register", "the requirements register"), ("automation-manifest", "the automation manifest"),
                 ("run-report", "the run report"), ("evidence", "the evidence record"), ("test-cases", "a case file"),
                 ("source-inventory", "the source inventory"))


def _record_kind(path) -> str:
    text = str(path or "").replace("\\", "/").lower()
    return next((kind for key, kind in _RECORD_KINDS if key in text), "a record of the story")


def plain_words(text) -> str:
    """`text` with every path under work/ replaced by the kind of record it names (a sentence for a person)."""
    return _WORK_PATH_RE.sub(lambda found: _record_kind(found.group(0)), str(text))


def refusal_words(exc, case="") -> tuple:
    """(reason, door) of a refusal; any other ValueError (a controller block, a malformed plan) gets the
    words that name it - the case and the kind of record, never a path under work/ - and the one door every
    refusal here has."""
    if isinstance(exc, Refused):
        return exc.reason, exc.door
    what = (f"{_record_kind(exc.filename)} could not be read ({type(exc).__name__})"
            if isinstance(exc, OSError) and getattr(exc, "filename", None) else plain_words(exc))
    return (f"the check of {case or 'this case'} could not be prepared: {what}",
            "the plan is repaired or approved again at gate A; until then the case stands as not checked by hand")


def _question_rows(task):
    """{question id: register row with `status`} (`question_register.load`); None when the story has no
    readiness file or it cannot be read - then every implementation-only requirement stays unconfirmed."""
    try:
        import question_register as QR
        view = QR.load(task)
    except Exception:
        return None
    if not view.get("register_present"):
        return None
    return {q["id"]: q for q in view.get("questions", []) if isinstance(q, dict) and q.get("id")}


def expectation_gaps(task, case_fact) -> list:
    """What makes the expected result of a case unconfirmed (P20: code is never an oracle), as
    [(question id or "", words)] - empty when every covered requirement and every Then stands on a source.

    Two readers, both of t-245: a covered R in `contract.unconfirmed_implementation_only` (derived from the
    diff alone, no answered question) and a Then that `contract.resolve_then_oracle` reads as `open` or
    `invalid`. The error direction is toward refusing: no readiness file means no answer anywhere, and a
    case whose `then_oracles` cannot be read is refused too. A case with no `then_oracles` line at all (it
    predates the oracle rule) has no Then to read, and its covered R decides alone."""
    import contract as C
    gaps = []
    questions = _question_rows(task)
    register = C.read_text(C.artifact(task, "requirements-register.md"))
    if register:
        asked = C.claim_questions(register)
        unconfirmed = C.unconfirmed_requirements(register, questions)
        for r in case_fact.get("requirements") or []:
            if r in unconfirmed:
                qid = asked.get(r, "")
                gaps.append((qid, f"{r} exists only in the new code and " +
                             (f"its question {qid} is not answered" if qid else "no question about it is linked in the register")))
    text = C.read_text(Path(case_fact["path"])) if case_fact.get("path") else ""
    entries, problem = C.then_oracles_from_text(text)
    if entries is None and problem:
        gaps.append(("", f"the sources of the case's expected results cannot be read ({problem})"))
    thens, _ = C.question_thens_from_text(text)
    for entry in entries or []:
        ref = str(entry.get("ref") or "").strip()
        match = next((q for q in thens or [] if q.get("then") == entry.get("then")
                      and str(q.get("question") or "").strip() == ref), None)
        verdict = C.resolve_then_oracle(entry, (questions or {}).get(ref), match)
        if verdict["state"] in ("open", "invalid"):
            gaps.append((ref if verdict["source"] == "unknown" else "",
                         f"expected result {entry.get('then')} has no confirmed source ({verdict['why']})"))
    return gaps


def _walk_fields(rows, obligation_ids) -> dict:
    """TR3-10 E (AR-21, FR-49): what the walk changes, from the plan rows that own this case's obligations, in plan order -
    `{"walk_data": [...]}` and/or `{"walk_global": "..."}`, each key only when said. `walk_data` entries are concatenated as given;
    the distinct `walk_global` reasons are kept as given (joined by " | " only when rows differ). An absent field and
    `walk_data: []` are the same: not said, so no key (no constraint). The ONE statement, called by the prepared request AND the
    unprepared document, so a case through either door carries the fields whole."""
    owners = [row for row in rows if isinstance(row, dict) and any(isinstance(o, dict) and o.get('obligation_id') in obligation_ids
                                                                   for o in row.get('coverage_obligations') or [])]
    walk_data = [entry for row in owners if isinstance(row.get('walk_data'), list) for entry in row['walk_data']]
    reasons = list(dict.fromkeys(row['walk_global'] for row in owners if isinstance(row.get('walk_global'), str)))
    out = {}
    if walk_data:
        out['walk_data'] = walk_data
    if reasons:
        out['walk_global'] = ' | '.join(reasons)
    return out


def prepare_request(task, case, obligation_ids):
    """Resolve approved design before opening a browser; never invent observed steps.

    Every refusal is a `Refused`: words for the person and a door. The order protects one invariant: an
    unconfirmed expectation (P20) is refused BEFORE the scope checks, so an executable-looking obligation
    whose expected result nobody confirmed can never reach a runner."""
    import contract as C
    from controller import Controller
    from coverage_contract import plan_rows
    from planning_contract import validate_plan
    task = Path(task).resolve()
    controller = Controller(task)
    state = controller.state()
    controller._validate_gate_a_content_current(state)
    # C5: a re-recorded gate A leaves two approved records; the current one is the controller's own answer.
    decision = controller._current_gate_a(state)
    if not decision or not decision.get('id'):
        raise Refused("no gate A decision is current for this source revision", _REOPEN, door_code=_REOPEN_CODE)
    rows = plan_rows(task)
    errors = validate_plan(rows)
    shape_errors = []
    if errors:
        from coverage_contract import POLICY_SHAPE_ERROR, POLICY_TYPE_ERROR
        if not all(POLICY_SHAPE_ERROR in str(error) or POLICY_TYPE_ERROR in str(error) for error in errors):
            raise Refused("the approved plan does not pass its own checks, so no manual check can be taken from it",
                          "the plan is repaired and approved again at gate A; until then the case stands as not "
                          "checked by hand", '; '.join(errors))
        # F5(c) item 1: ONLY evidence-rule shape errors - the factory's own (the plan exit let a malformed rule through).
        # Every story-owned check below still runs for this case; the walkable refusal is raised after them.
        shape_errors = [str(error) for error in errors]
    pins = {p['case_id']: p['version'] for p in C.story_case_links(task)}
    if case not in pins:
        raise Refused(f"the case {case} is not among the cases pinned when the plan was approved",
                      "the case is added and gate A approves again; until then the case stands as not checked "
                      "by hand")
    try:
        case_fact = C.case_index(task)[case]
    except (KeyError, ValueError):
        case_fact = {}
    gaps = expectation_gaps(task, case_fact) if case_fact else []
    if gaps:
        ids = sorted({q for q, _ in gaps if q})
        raise Refused("expectation unconfirmed" + (" — " + ", ".join(ids) if ids else "") + ": " +
                      "; ".join(words for _, words in gaps) + ". What the right answer is has not been confirmed "
                      "by anyone, so checking the product against it would only repeat the code",
                      ("the person's answer to " + ", ".join(ids) + " at gate A (each question shows the "
                       "behaviour before and now)" if ids else "the person's answer: a question about it is raised "
                       "and answered at gate A") + "; until then the case stands as not checked by hand")
    obs = {o['obligation_id']: o for row in rows for o in row.get('coverage_obligations', [])}
    if not obligation_ids or any(oid not in obs for oid in obligation_ids):
        raise Refused("the obligations named for this case are not in the approved plan",
                      "name the obligations the plan lists for the case; until then the case stands as not "
                      "checked by hand")
    mapped = _case_obligation_mapping(task, rows, case)
    if not set(obligation_ids).issubset(mapped):
        raise Refused("the plan's obligations do not match the requirements the case says it covers",
                      "the case designer and the strategist agree on the covered requirements and gate A "
                      "approves again; until then the case stands as not checked by hand",
                      "manual obligations do not match the approved pinned case traceability")
    selected = [obs[oid] for oid in obligation_ids]
    for o in selected:
        if o.get('decision') != 'manual-agent':
            raise Refused(f"the approved plan still has this check as `{o.get('decision')}`, not as a check an agent "
                          "makes by hand", _REOPEN, "manual-agent request is outside approved executable scope",
                          door_code=_REOPEN_CODE)
        if o.get('execution_scope') != 'current_task':
            raise Refused("this check is only a recommendation for later, not part of this story's run",
                          "the person moves it into the story's scope at gate A",
                          "manual-agent request is outside approved executable scope")
        if o.get('oracle_status') != 'resolved':
            raise Refused("what the right answer is for this check has not been settled",
                          "the person answers the open question at gate A",
                          "manual-agent request is outside approved executable scope")
    # --- the walkable split (F5(c)): everything above is the story's own and refused as it always was ----------------------
    # POSITION INVARIANT: after every story-owned check, so a case outside the approved scope, with an unresolved or
    # unconfirmed expectation, unpinned or on a drifted gate A is never walked (P20, E5.6).
    from event_store import StateConflict
    walk_door = ("the plan is repaired and approved again at gate A; meanwhile the manual agent walks the case itself and "
                 "records what it observes, with no result")
    # M1 (t-1945): the plan check is whole-plan; only the shape errors of THIS case's own obligations unprepare it (an error
    # reads "<obligation id>: ..."). A malformed rule in another case's row leaves this case prepared normally.
    own = {str(o.get('obligation_id')) for o in selected}
    shape_errors = [e for e in shape_errors if e.split(":", 1)[0].strip() in own]
    bad = [o for o in selected if not isinstance(o.get('evidence_policy'), str)]
    if shape_errors or bad:
        raise Refused(f"the plan gives {case}'s check an evidence rule that is not one word", walk_door,
                      '; '.join(shape_errors) or "evidence_policy is not text for " + ", ".join(
                          str(o.get('obligation_id')) for o in bad), walkable=True)
    try:
        request = _request_tail(task, case, state, decision, obligation_ids, selected, obs, pins, case_fact, walk_door)
        request.update(_walk_fields(rows, obligation_ids))      # TR3-10 E: what the walk changes travels whole (AR-22, FR-49)
        return request
    except (Refused, StateConflict):
        raise
    except Exception as exc:        # F5(c) item 4: a crash of OUR preparation is the factory's, not the story's
        raise Refused(f"the check of {case} could not be prepared: {type(exc).__name__}: "
                      f"{' '.join(str(exc).split())[:160]}", walk_door, walkable=True, trace=_trace_tail()) from exc


def _request_tail(task, case, state, decision, obligation_ids, selected, obs, pins, case_fact, walk_door):
    """The tail of `prepare_request` (policy step through the actors): its crash is a walkable refusal (F5(c) item 4)."""
    from event_store import content_hash
    policies = {o.get('evidence_policy') for o in selected}
    conditions = {o.get('completion_condition') for o in selected}
    if len(policies) != 1 or not policies.issubset(POLICIES) or len(conditions) != 1 or not next(iter(conditions)):
        raise Refused("the checks of this case have different rules for what counts as evidence",
                      "the strategist gives them one evidence policy and one completion condition and gate A "
                      "approves again; meanwhile the manual agent walks the case itself and records what it observes, "
                      "with no result", "shared manual capture needs the same valid policy and completion condition",
                      walkable=True)
    policy = next(iter(policies))
    policy_contract = {'evidence_policy': policy, 'completion_condition': next(iter(conditions)),
                       'obligation_hashes': {oid: content_hash(obs[oid]) for oid in obligation_ids}}
    thens = _case_thens(case, case_fact)
    request = {'schema_version': 2, 'request_kind': 'manual_capture', 'case': case,
               'case_version': pins[case], 'obligation_ids': list(obligation_ids),
               'obligation_hashes': policy_contract['obligation_hashes'],
               'source_revision': state['source_revision'], 'controller_revision': state['revision'],
               'gate_a_decision_ref': decision['id'],
               'evidence_policy': policy, 'completion_condition': policy_contract['completion_condition'],
               'approved_policy_hash': content_hash(policy_contract),
               'expected': [o['behavior'] for o in selected],
               'thens': thens,
               'covers': list(case_fact.get('requirements') or []),
               'legacy_evidence_gaps': _legacy_evidence_gaps(task),
               'required_actual_fields': ['steps_actual', 'actual', 'evidence_refs', 'runtime_before',
                                         'runtime_after', 'attempt_started_at', 'attempt_ended_at']
                                        + (['then_quotes'] if thens else [])}
    reasons ={o.get('before_not_applicable_reason') for o in selected if o.get('before_not_applicable_reason')}
    if len(reasons) == 1:
        request['before_not_applicable_reason'] = next(iter(reasons))
    request['actors'], unreadable = _actor_preconditions(case_fact)
    if unreadable:
        request['actors_unreadable'] = unreadable
    return request


def _case_thens(case, case_fact) -> dict:
    """{"1": "<text of the case's first Then>", ...}: the requirement a manual verdict stands on, handed to the runner in
    `request.json` BEFORE the work (FR-38, AR-10); read through `traceability.case_thens`, the one reader of the case's
    `## Then` (AR-13). `{}` is the declared empty outcome: a case with no Then asks for no quote. A case file that cannot
    be read is NOT that outcome: silence would drop the quote requirement from a check that has Thens, so it is refused
    (the error goes toward refusing, with the door every refusal of `prepare` has)."""
    import contract as C
    import traceability as T
    path = case_fact.get('path') if isinstance(case_fact, dict) else None
    if not path:
        return {}
    if not C.read_text(Path(path)).strip():
        raise Refused(f"the case file of {case} could not be read, so what it expects is not known to the check",
                      "the case file is restored or the plan is approved again at gate A; until then the case stands "
                      "as not checked by hand")
    return {str(number): text for number, text in sorted(T.case_thens(Path(path)).items())}


ACTORS_UNREADABLE_CHARS = 200     # how much of the reason the case's accounts could not be read `actors_unreadable` keeps


def _actor_preconditions(case_fact) -> tuple:
    """([{"id", "what", "check"}], unreadable): the accounts the case's `preconditions:` line names - the preconditions
    of `kind: "account"`, each verbatim (the shape is `gate_preflight.parse_preconditions`', the only owner of it). `[]`
    is the declared empty outcome (a case with no preconditions, none of that kind, or no case file). A line that cannot
    be read is `[]` and the reason (cut at ACTORS_UNREADABLE_CHARS) - the request is still made (a failure to read the
    accounts is no reason to refuse the check, builder-rules 9): the capture then signs in as it always did."""
    import gate_preflight as GP
    path = case_fact.get('path') if isinstance(case_fact, dict) else None
    if not path:
        return [], ''
    try:
        raw = GP.case_preconditions_raw(Path(path).read_text(encoding='utf-8-sig'))
        items, errors = GP.parse_preconditions(raw)
    except (OSError, ValueError) as exc:
        return [], f"the case file could not be read ({exc.__class__.__name__})"[:ACTORS_UNREADABLE_CHARS]
    if errors:
        return [], ' '.join(str(errors[0]).split())[:ACTORS_UNREADABLE_CHARS]
    return [{'id': i.get('id'), 'what': i.get('what'), 'check': i.get('check')} for i in items
            if i.get('kind') == 'account'], ''


def request_actors(task, case) -> tuple:
    """(actors, why): the accounts the case's request names - the ONE reader of the field `actors` that `prepare_request`
    writes (axis 29). `([], "")` for a request made before the field existed, a refused request, no request file, or a
    case that names none; `([], <words>)` when the request cannot be read or its accounts could not be read
    (`actors_unreadable`): the caller says it once and goes on as if the case named none."""
    path = request_path(task, case)
    if not path.is_file():
        return [], ''
    try:
        request = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return [], f"the request of {case} ({path.name}) cannot be read"
    if not isinstance(request, dict) or isinstance(request.get('refused'), dict):
        return [], ''
    if request.get('actors_unreadable'):
        return [], f"the accounts of {case} could not be read from its case file ({str(request['actors_unreadable'])[:ACTORS_UNREADABLE_CHARS]})"
    actors = request.get('actors')
    if not isinstance(actors, list):
        return [], ''
    return [a for a in actors if isinstance(a, dict)], ''


def request_path(task, case) -> Path:
    import manual_capture as MC
    return MC.case_root(task, case) / "request.json"


def prepare_to_file(task, case, obligation_ids) -> dict:
    """`prepare_request`, with its answer kept where the runner and the report read it:
    `work/evidence/manual/<case>/request.json` holds the request, or `{"refused": {"reason", "door"}}` (C3,
    FR-49: the report says WHY a case was not checked by hand; both are words for a person, so neither names an
    operation of ours - that name is `Refused.door_code` on the exception, never in the file, t-263 D6). A
    refusal is written and then raised again,
    so a caller that only wants the file can catch the ValueError and read it."""
    path = request_path(task, case)
    try:
        request = prepare_request(task, case, obligation_ids)
    except ValueError as exc:
        reason, door = refusal_words(exc, case)
        path.parent.mkdir(parents=True, exist_ok=True)
        if getattr(exc, "walkable", False):        # F5(c): the factory's own failure - the case is walked unprepared
            atomic_json(path, _unprepared_document(task, case, obligation_ids, exc, reason, door))
        else:
            atomic_json(path, {"refused": {"reason": reason, "door": door}})
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, request)
    return request


def _unprepared_document(task, case, obligation_ids, exc, reason, door) -> dict:
    """The `request.json` of an unprepared case: `{"unprepared": {"reason", "door", "detail"?, "trace"?, "obligation_ids",
    "source_revision"?, "gate_a_decision_ref"?}, "case", "case_version"?, "thens"?, "covers"?, "walk_data"?, "walk_global"?}`. Each `?` key is written only
    when code could read it (a failure to read one is no reason to lose the case, builder-rules 9)."""
    marker = {"reason": reason, "door": door, "obligation_ids": list(obligation_ids)}
    if getattr(exc, "detail", ""):
        marker["detail"] = str(exc.detail)
    if getattr(exc, "trace", ""):
        marker["trace"] = str(exc.trace)
    doc = {"unprepared": marker, "case": case}
    try:
        from controller import Controller
        controller = Controller(Path(task).resolve())
        state = controller.state()
        if state.get("source_revision"):
            marker["source_revision"] = state["source_revision"]
        current = controller._current_gate_a(state)
        if current and current.get("id"):
            marker["gate_a_decision_ref"] = current["id"]
    except Exception:
        pass
    try:
        import contract as C
        pins = {p["case_id"]: p["version"] for p in C.story_case_links(task)}
        if case in pins:
            doc["case_version"] = pins[case]
        fact = C.case_index(task).get(case) or {}
        if fact.get("requirements"):
            doc["covers"] = list(fact["requirements"])
        thens = _case_thens(case, fact)
        if thens:
            doc["thens"] = thens
    except Exception:
        pass
    try:
        from coverage_contract import plan_rows
        doc.update(_walk_fields(plan_rows(Path(task).resolve()), obligation_ids))      # TR3-10 E F10: the walkable door carries them too
    except Exception:
        pass
    return doc


def unprepared_request(task, case):
    """The `unprepared` marker of the case's `request.json` (`{"reason", "obligation_ids", ...}`), or None: the ONE reader of
    that key (AR-13) - None for no file, an unreadable file, a prepared request or a `refused` one."""
    try:
        data = json.loads(request_path(task, case).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    marker = data.get("unprepared") if isinstance(data, dict) else None
    return marker if isinstance(marker, dict) else None


def unprepared_rows(report) -> list:
    """`[{case, obligation_ids, reason, observations, finding}]` from the `current_manual_checks` of a run report that carry
    `unprepared` - the ONE reader of unprepared rows (AR-13, F5(d)); `[]` when there are none."""
    out = []
    for row in (report or {}).get("current_manual_checks") or []:
        marker = row.get("unprepared") if isinstance(row, dict) else None
        if marker is None:
            continue
        entry = {"case": row.get("case"),
                 "obligation_ids": list(row.get("current_obligation_ids") or row.get("obligation_ids") or []),
                 "reason": str((marker.get("reason") if isinstance(marker, dict) else marker) or ""),
                 "observations": row.get("observations") or [], "finding": row.get("finding") or ""}
        if isinstance(marker, dict) and isinstance(marker.get("walked"), bool):
            # t-1955 N3: what `write_unprepared` derived from the recorder's files; a record made before it says nothing (AR-23)
            entry["walked"] = marker["walked"]
            if not marker["walked"]:
                entry["not_walked"] = str(marker.get("not_walked") or "")
        out.append(entry)
    return out


def _write_refused(task_root, case, reason, door) -> None:
    """`request.json` of the case as `{refused: {reason, door, trace}}`; a file that cannot be written changes nothing (the decision is returned)."""
    try:
        path = request_path(task_root, case)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(path, {"refused": {"reason": reason, "door": door, "trace": _trace_tail()}})
    except Exception:
        pass


def prepare_for_block(task_root, case) -> tuple:
    """([obligation ids], "", "") for a case the agent may check by hand, ([], the refusal in words, "") for a case the story
    refuses, (ids, "", <reason>) for a case the FACTORY failed to prepare (F5(c), the owner's word 05.11: the factory never
    stands - the case goes to the manual agent as an unprepared walk).

    THE one per-case prepare of a manual runner block (AR-15): the driver (`Driver.manual_prepare`) and
    `story_step.py start` both call it, so the runner finds `request.json` on either road. `prepare_to_file` is the one
    reader (the obligation ids come from `_case_obligation_mapping`): it writes `request.json`, either the request, an
    `unprepared` marker (a `Refused` with `walkable`), or `{refused: {reason, door}}`, and a refusal is a `ValueError`
    carrying its two halves. ERROR DIRECTION: a refusal the STORY owns (P20, gate A, scope, an unpinned case) and any
    failure outside `prepare_request` stay refusals - said, and written - so a case is never dispatched on a doubt; only
    the factory's own preparation failures are walked, and an unprepared walk never carries a result (FR-59)."""
    try:
        from coverage_contract import plan_rows
        ids = sorted(_case_obligation_mapping(task_root, plan_rows(task_root), case))
    except Exception:
        ids = []         # `prepare` then refuses it, naming the plan's obligations, and writes the refusal
    code = ""
    try:
        prepare_to_file(task_root, case, ids)
        return ids, "", ""
    except ValueError as exc:
        reason, door = refusal_words(exc)
        if getattr(exc, "walkable", False):
            if ids:
                return ids, "", reason
            # E5.10: no obligation ids -> not walkable (coverage could not attach it); `request.json` holds the unprepared
            # marker `prepare_to_file` wrote, so the file is rewritten to say the same as the decision: a refusal
            _write_refused(task_root, case, reason, door)
        # The person-facing words carry no operation (t-263 D6, FR-6); the caller's why does - it is read by the
        # orchestrator and the log, never shown to the person as a question - so the door stays usable (FR-2).
        code = str(getattr(exc, "door_code", "") or "")
    except Exception as exc:
        reason, door = refusal_words(ValueError(f"{type(exc).__name__}: {' '.join(str(exc).split())[:160]}"))
        _write_refused(task_root, case, reason, door)
    return [], f"{reason} — {door}" + (f" (operation: {code})" if code else ""), ""


def write_block(task, records, declared=False):
    """`declared` (the CLI's `write-block`, a record a role writes by hand NOW): every record declares `observations`, `[]` when
    none (`_declared_errors`). Off for the callers that write records made before the rule (E14)."""
    task = Path(task).resolve()
    if not isinstance(records, list) or not records:
        raise ValueError("manual block requires current records")
    issues = []
    for index, record in enumerate(records):
        where = "records[%d]: " % index
        if not isinstance(record, dict):
            issues.append(where + "manual block records must be objects")
            continue
        if "current_obligation_ids" in record:
            issues.append(where + "current_obligation_ids is reducer-owned and forbidden in writer input")
            continue
        if declared:
            issues.extend(where + issue for issue in _declared_errors(record))
            attempts, known, _ = _hand_surprises(task, record)
            issues.extend(where + issue for issue in _surprise_cite_errors(
                record.get("observations"), known, attempts, "a record written by hand holds the attempts it names; cite a surprise of "
                "one of them, or build the case again with `--with-attempt {attempt}`"))
        try:
            found = _validate_current(task, record)
        except ValueError as exc:
            found = [str(exc)]
        # F5(d): an unprepared walk's only "issue" is its constant (no result is bound); it is written, every other issue stays
        unprepared = record.get("unprepared") is not None
        if unprepared:
            from coverage_contract import UNPREPARED
            found = [issue for issue in found if issue != UNPREPARED]
        issues.extend(where + issue for issue in found)
        # the quote rule of `build` and `rejudge` holds for a record written by hand too (AR-19): when the case's request
        # lists Thens, a pass or fail names them through the one coverage function. An unprepared walk has no result and
        # asks no quote (F5(d)); a `result` on it is refused by `_validate_current` above (E5.9).
        numbers = [] if unprepared else _request_thens(task, record.get("case"))
        if numbers:
            issues.extend(where + problem + ". Door: " + QUOTE_DOOR for problem in
                          _then_coverage_problems(numbers, record.get("result"), record.get("then_quotes")))
    if issues:
        raise ValueError(compound(issues))
    if declared:        # a runner cannot drop a surprise line by leaving it out of the record it writes (P26): code carries them
        # a hand record that still carries the retired `surprises_ignored` is written without it, with or without an attempt folder
        # (nothing reads it, AR-22); a record without the key is unchanged
        stripped = [{k: v for k, v in record.items() if k != "surprises_ignored"} for record in records]
        records = [dict(rec, **fields) if (fields := _hand_surprises(task, record)[2]) else rec
                   for record, rec in zip(records, stripped)]
    for index, record in enumerate(records):        # t-1955 N3: a missing key is a refusal with a door, never a KeyError
        absent = [key for key in ("dispatch_id", "attempt_started_at", "attempt_ended_at", "source_revision")
                  if record.get(key) is None]
        if absent:
            raise ValueError(f"records[{index}] has no {', '.join(absent)}: a block binds to the running dispatch, the attempt's "
                             "times and the source revision. Door: write the record with `manual_evidence.py build` (or `unprepared` "
                             "for an unprepared case), which fills them")
    dispatches = {r["dispatch_id"] for r in records}
    starts = {r["attempt_started_at"] for r in records}
    ends = {r["attempt_ended_at"] for r in records}
    heads = {r["source_revision"] for r in records}
    if any(len(values) != 1 for values in (dispatches, starts, ends, heads)):
        raise ValueError("manual block records must share dispatch, attempt timestamps and head")
    payload = {"schema_version": 2, "dispatch_id": next(iter(dispatches)),
               "attempt_started_at": next(iter(starts)), "attempt_ended_at": next(iter(ends)),
               "head": next(iter(heads)), "manual_checks": records}
    # t-2181 PC-5a (B2): the same stamp as a run block, from the one function (`run_suite.proof_stamp`, AR-15); {} leaves the
    # payload - and so its identity key - as it was. The runner's `about` rides on each record.
    from run_suite import proof_stamp
    payload.update(proof_stamp(task))
    key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    payload["block_id"] = "manual-" + key[:20]
    path = task / "work" / "manual-blocks" / f"manual-{key}.json"
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != payload:
            raise ValueError("manual block identity conflict")
        return path
    atomic_json(path, payload)
    return path


# --------------------------------------------------------------------------------------------
# build: the record from the files `manual_capture.py` saved
# --------------------------------------------------------------------------------------------

def _jsonl(path: Path) -> list:
    if not path.is_file():
        return []
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            raise ValueError(f"{path.name} line {number} is not JSON: the capture tool writes that file and nobody "
                             "edits it. Capture again in a new attempt")
    return out


def before_change_for(register_text, covers) -> dict:
    """The ONE "before" a person is shown: the register's `## Behaviour claims` row of the first covered R
    that has one (`before`, `before_ref` verbatim; an `absent` / `unknown` before keeps its word and is its
    own reference), else `not_recorded` - the requirements say nothing about the old behaviour, and silence is
    never a value (P20). `not_recorded` never reads as "unchanged"."""
    import contract as C
    claims = {}
    for row in C.behaviour_claims(register_text or ""):
        claims.setdefault(row["r"], row)
    for r in covers or []:
        row = claims.get(r)
        if not row or not row.get("before"):
            continue
        value = row["before"]
        ref = "" if row.get("before_ref", "") in C.EMPTY_CELLS else row.get("before_ref", "")
        if not ref and value.lower() in (C.CLAIM_ABSENT, C.CLAIM_UNKNOWN):
            ref = value.lower()
        if ref:
            return {"r": r, "value": value, "ref": ref, "source": "claim"}
    return {"r": (covers or [None])[0], "value": None, "ref": None, "source": "not_recorded"}


def _moment(value):
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _running_dispatch(task, case) -> str:
    from controller import Controller
    running = [did for did, d in (Controller(task).state().get("dispatches") or {}).items()
               if isinstance(d, dict) and d.get("stage") == "S6" and d.get("status") == "running"
               and case in (d.get("scope") or [])]
    if not running:
        raise ValueError(f"no S6 dispatch is running with {case} in its scope, so a record has nothing to bind to. "
                         "The orchestrator opens the dispatch (story_step start); you do not: say so in your "
                         "findings and halt")
    if len(running) > 1:
        raise ValueError(f"{len(running)} running S6 dispatches hold {case} in their scope ({', '.join(sorted(running))}): "
                         "the record cannot tell which one it belongs to. Say so in your findings and halt")
    return running[0]


NOT_WALKED_MAX = 300      # the characters of `--not-walked` the record keeps


def _recorded_walks(task, case) -> list:
    """`[(attempt, steps rows, probes rows)]`, oldest first: the attempts of `case` that hold at least one recorder step. An attempt
    that is env_blocked is no walk (E3.10); nothing is read from the runner (E3.9, P26). Pure data, no judgment (AR-29)."""
    import manual_capture as MC
    root = MC.case_root(task, case)
    walks = []
    for name in MC.attempts_of(root):
        folder = root / name
        if MC.attempt_state(folder) == "env_blocked":
            continue
        steps = MC.jsonl_rows(folder / "steps.jsonl")
        if steps:
            walks.append((name, steps, MC.jsonl_rows(folder / "probes.jsonl")))
    return walks


def write_unprepared(task, case, observations, not_walked="") -> Path:
    """The record of an UNPREPARED case (the factory could not prepare it; `request.json` holds `unprepared`): what the runner saw,
    and whether anything was walked with the recorder - never a result (FR-59). ONE record through `write_block` (AR-14), bound to
    the running dispatch by `_running_dispatch` (AR-13). `walked` is DERIVED from the recorder's `steps.jsonl` files on disk, never taken
    from the runner (P26): the newest attempt that holds a step is the record's `attempt_id` (so its `surprise` lines travel with
    it); no such attempt means `not_walked` is required, and is refused when one exists. Raises `ValueError` with the door."""
    task = Path(task).resolve()
    marker = unprepared_request(task, case)
    if marker is None:
        import manual_capture as MC
        _load_request(task, MC.case_root(task, case), case)       # called for its refusal: a missing / refused request speaks in its own words
        raise ValueError(f"{case} was prepared (its request.json holds no `unprepared`): close it with `manual_evidence.py build`. "
                         "The `unprepared` command is for a case whose request.json says it was not prepared")
    if not isinstance(observations, list):
        raise ValueError("observations must be a list ([] when you saw nothing doubtful)")
    dispatch = _running_dispatch(task, case)
    walks = _recorded_walks(task, case)
    why = _squash(not_walked or "")
    if walks:
        name, steps, probes = walks[-1]
        if why:
            raise ValueError(f"{case} was walked (attempt {name} holds {len(steps)} step(s)): leave --not-walked out")
        moments = [_moment(row["at"]) for row in steps + probes if row.get("at")]
        started, ended = min(moments).isoformat(timespec="seconds"), max(moments).isoformat(timespec="seconds")
        flag = {"walked": True}
    else:
        if not why:
            raise ValueError(f"nothing of {case} was walked with the recorder: say why with --not-walked \"<why>\", or walk it first "
                             "(`manual_capture.py ...`)")
        name = ""
        started = ended = datetime.now(timezone.utc).isoformat(timespec="seconds")
        flag = {"walked": False, "not_walked": why if len(why) <= NOT_WALKED_MAX else why[:NOT_WALKED_MAX - 1] + "…"}
    revision = marker.get("source_revision")
    if not revision:
        from controller import Controller
        revision = Controller(task).state().get("source_revision")
    record = {"schema_version": 2, "case": case, "obligation_ids": list(marker.get("obligation_ids") or []),
              "unprepared": {"reason": marker.get("reason"), **flag}, "observations": observations,
              "dispatch_id": dispatch, "attempt_started_at": started, "attempt_ended_at": ended, "source_revision": revision}
    if name:
        record["attempt_id"] = name
    return write_block(task, [record], declared=True)


def _walk_observations(walk_record) -> list:
    """The observations of a walk's result record as the case record carries them (`OBSERVATION_FIELDS`): the record's `capture` is the
    record's `evidence`, a `surprise` citation travels. An observation `about: card` is a note on the app card, not on the case: it stays
    in the walk's result record for the card-notes reader and is not copied here. Code NEVER writes a citation the role did not make (P26,
    AR-29, t-2022 N3): an observation with no `quote` stays without, and the record's rule (`_observation_errors`) refuses it - at the
    verdict while the session lives (`walk_rule_errors`), with the door."""
    out = []
    for entry in walk_record.get("observations") or []:
        if not isinstance(entry, dict) or entry.get("about") == "card":
            continue
        row = {key: entry[key] for key in OBSERVATION_FIELDS if key != "evidence" and key in entry}
        row["evidence"] = entry.get("evidence") or entry.get("capture") or ""
        if entry.get("surprise"):
            row["surprise"] = entry["surprise"]
        out.append(row)
    return out


def walk_result(thens) -> str:
    """`result` of a walk as a PURE FOLD of the role's own per-Then words, never a judgment of code: `fail` if any Then is `fail`, else
    `inconclusive` if any is `inconclusive` or `unreached` (or there is no Then at all: no recorded words, no pass - AR-28), else `pass`."""
    words = [t.get("result") for t in thens]
    return ("fail" if "fail" in words else
            "inconclusive" if not words or any(w in ("inconclusive", "unreached") for w in words) else "pass")


def walk_rule_errors(task, case, walk_record) -> list:
    """The rules `record_from_walk` will meet, asked while the walk's session LIVES (t-2016 F2: a verdict that the build refuses after the
    session is gone is a lost case, because the role can no longer act). The SAME functions `validate` calls on the record - the
    observations (`_observation_errors`) and what the result needs of the evidence (`_result_errors`: phases, completion, limitation) - over
    a record made from the attempt's own files; never a copy of a rule. Not asked: what the build alone can know (the stand probes, the
    dispatch). A case with no `request.json` policy is asked the rules that do not depend on one. Errors only; `[]` = the build will not
    refuse on these (it may on others). ERROR DIRECTION: the limitations seen here are the captures' own and the walker's; the build adds
    code's sentences (`person_sentences`), so a refusal here can be one the build would not make - never the reverse."""
    import manual_capture as MC
    task = Path(task).resolve()
    root = MC.case_root(task, case)
    request = _read_json(root / "request.json")
    attempt = str(walk_record.get("attempt") or "")
    folder = root / attempt
    captures, steps = _jsonl(folder / "captures.jsonl"), _jsonl(folder / "steps.jsonl")
    refs = _evidence_refs([c for c in captures if all(k in c for k in ("path", "content_hash", "kind", "phase", "captured_at", "proves"))])
    thens = [t for t in walk_record.get("thens") or [] if isinstance(t, dict)]
    limitations = [c["limitation"] for c in captures if isinstance(c.get("limitation"), str) and c["limitation"].strip()]
    if walk_record.get("limitation"):
        limitations.append(str(walk_record["limitation"]))
    record = {"case": case, "attempt_id": attempt, "result": walk_result(thens), "limitations": limitations, "evidence_refs": refs,
              "steps_actual": [_step_line(s) for s in steps if isinstance(s, dict) and "step" in s and "outcome" in s],
              "observations": _walk_observations(walk_record),
              "before_not_applicable_reason": request.get("before_not_applicable_reason")}
    errors = _observation_errors(record, task)
    if not captures:          # the build's `_attempt_files` refuses it (t-2022 N1); the server takes one `look` first, so this is the door when it could not
        errors.append(f"attempt {attempt} of {case} holds no captures: take one - `look` (or `capture <phase> <label>`) in a step call, then give the verdict")
    errors += _surprise_cite_errors(record["observations"], {row["id"] for row in surprises_of(folder)}, [attempt],
                                    "a walk's observation cites a surprise line of its own attempt only")      # N2: the build asks it too
    if unprepared_request(task, case) is None:
        phases, by_phase = _by_phase(refs)
        errors += _result_errors(record, request.get("evidence_policy"), phases, by_phase)
    return sorted(set(errors))


def record_from_walk(task, case, walk_record) -> dict:
    """The case record of one walked item, reduced from its result record `work/walks/<W>/<item>.json` (spec 3.4): the walker judged each
    Then, code only carries the words (P27, AR-29). An UNPREPARED case goes to `write_unprepared` with the observations and never to
    `build_record`: no pass or fail from an unprepared walk (FR-59, E2.7). A prepared case calls `build_record(task, case, result, actual,
    masked=True, attempt=<the item's attempt>, quotes=<each pass/fail Then's own quote>, observations=<...>)`. `result` is a PURE FOLD of the
    role's own per-Then words, never a judgment of code: `fail` if any Then is `fail`, else `inconclusive` if any is `inconclusive` or
    `unreached` (or the record holds no Then at all: no recorded words, no pass - AR-28), else `pass`. `actual` is the record's own `actual`
    when the walker gave one, else the Thens' own words joined. `masked=True`: the recorder stores every capture masked (P26). A record
    `build_record` or `write_unprepared` refuses is RETURNED as `{"refused": <the refusal text>}`, never raised and never turned into a pass:
    the caller re-queues the case once (E2.8). Returns `build_record`'s answer, or `{"written": True, "unprepared": True, "case", "block"}`."""
    task = Path(task).resolve()
    thens = [t for t in walk_record.get("thens") or [] if isinstance(t, dict)]
    observations = _walk_observations(walk_record)
    try:
        if unprepared_request(task, case) is not None:
            walked = bool(_recorded_walks(task, case))
            path = write_unprepared(task, case, observations, not_walked="" if walked else "the walker ran no step for this case")
            return {"written": True, "unprepared": True, "case": case, "block": path.relative_to(task).as_posix()}
        result = walk_result(thens)
        quotes = [(("unreached", str(t["n"])) if t.get("result") == "unreached" else ("text", f"{t['n']}={t.get('quote') or ''}"))
                  for t in thens if t.get("result") in ("pass", "fail", "unreached")]
        said = "; ".join(f"Then {t['n']} {t.get('result')}" + (f": {t['quote']}" if t.get("quote") else "") for t in thens)
        actual = str(walk_record.get("actual") or "").strip() or said or str(walk_record.get("limitation") or "the walker recorded no result for any Then")
        return build_record(task, case, result, actual, masked=True,
                            limitations=[walk_record["limitation"]] if walk_record.get("limitation") else (),
                            attempt=walk_record.get("attempt") or None, quotes=quotes, observations=observations,
                            about=walk_record.get("about"))
    except ValueError as exc:
        return {"refused": str(exc)}


def _load_request(task, root, case) -> dict:
    """The case's `request.json` as `build` and `rejudge` both read it: the request, or a refusal that says what to do."""
    try:
        request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"{(root / 'request.json').relative_to(task).as_posix()} does not exist: `manual_evidence.py "
                         "prepare` writes it before the dispatch. Say so in your findings and halt")
    except ValueError:
        raise ValueError("request.json is not JSON: `manual_evidence.py prepare` writes it; capture nothing until it "
                         "is rewritten")
    if not isinstance(request, dict):
        raise ValueError("request.json is not an object: `manual_evidence.py prepare` writes it; capture nothing "
                         "until it is rewritten")
    if isinstance(request.get("refused"), dict):
        refused = request["refused"]
        raise ValueError(f"this case was not prepared: {refused.get('reason')} - {refused.get('door')}. It is "
                         "not yours to run; leave it out of your block")
    return request


def _check_words(result, actual) -> None:
    if result not in RESULTS:
        raise ValueError(f"--result {result!r} is none of pass | fail | inconclusive")
    if not str(actual or "").strip():
        raise ValueError("--actual is empty: say in the product's own words what you saw (the person reads it "
                         "beside what was expected)")


QUOTE_FLAGS = {"text": "--then-quote", "seen": "--then-seen", "unreached": "--then-unreached"}
QUOTE_DOOR = ("give `--then-quote \"<n>=<words>\"` for each Then, the words copied from the text the page or the response "
              "gave (a Then only the picture shows: `--then-seen \"<n>=<words>\"`; on a fail, a Then you never reached: "
              "`--then-unreached <n>`), or record `--result inconclusive` with `--limitation` saying what stopped the check")


def _then_quote_problems(task, request, result, quotes, refs) -> tuple:
    """(entries, problems) of the Then quotes a verdict stands on - the ONE function `build` and `rejudge` both ask (AR-19).

    `quotes` is a list of `(kind, raw)`: `("text", "<n>=<words>")` from `--then-quote`, `("seen", "<n>=<words>")` from
    `--then-seen`, `("unreached", "<n>")` from `--then-unreached`. `refs` are the evidence refs of the attempt: a quote
    must stand in one of ITS text captures (`QUOTE_SUFFIXES`), so a quote of another attempt, or of the `observe/` copy
    that is no capture, holds nothing (I1). A pass needs a quote for every Then of `request["thens"]`; a fail, for at
    least one (the one it failed on - a runner stops at the first Then that fails, and demanding words for the Thens it
    never reached would turn a true fail into an inconclusive: code changing the runner's word, FR-35); an inconclusive
    needs none. `entries` is what the record carries as `then_quotes`. A request with no `thens` key was made before this
    rule: nothing is required of it, and a quote the role gives anyway is still checked against the files.
    CODE NEVER JUDGES WHETHER A QUOTE CONTRADICTS ITS THEN (FR-12, FR-47): it checks that the words are there. A quote that
    is there and does not bear on the Then is the analyst's to find. The error goes only toward refusing a good quote."""
    thens = request.get("thens") if isinstance(request, dict) else None
    known = isinstance(thens, dict)
    numbers = sorted(int(key) for key in thens if str(key).isascii() and str(key).isdigit()) if known else []
    ref_list = [ref for ref in refs or [] if isinstance(ref, dict)]
    text_refs = [ref for ref in ref_list if Path(str(ref.get("path") or "")).suffix.lower() in QUOTE_SUFFIXES]
    pictures = [ref for ref in ref_list if ref.get("kind") == "image"
                and PHASE_ALIAS.get(ref.get("phase"), ref.get("phase")) == "after"]
    entries, problems, given = [], [], set()
    for kind, raw in quotes or []:
        flag = QUOTE_FLAGS[kind]
        head, equals, words = str(raw).partition("=")
        head = head.strip()
        if kind == "unreached" and equals:
            problems.append(f"{flag} {raw!r} is not just the number of the Then")
            continue
        if not (head.isascii() and head.isdigit()) or (kind != "unreached" and not equals):
            problems.append(f"{flag} {raw!r} is not <n>=<words>" if kind != "unreached" else f"{flag} {raw!r} is not a number")
            continue
        number = int(head)
        if known and number not in numbers:
            problems.append(f"Then {number} is not a Then of this case (its Thens: {', '.join(map(str, numbers)) or 'none'})")
            continue
        if number in given:
            problems.append(f"Then {number} is given twice")
            continue
        given.add(number)
        if kind == "unreached":
            entries.append({"then": number, "reached": False})
            continue
        words = _squash(words)
        if not words:
            problems.append(f"the quote for Then {number} is empty")
            continue
        if len(words) > THEN_QUOTE_MAX:
            problems.append(f"the quote for Then {number} is {len(words)} characters: quote at most {THEN_QUOTE_MAX} "
                            "characters, the shortest part that decides")
            continue
        if kind == "seen":
            if not pictures:
                problems.append(f"Then {number}: this attempt has no picture of the page after the action for "
                                f"{flag} to name (capture post_action as a picture)")
                continue
            source = str(pictures[-1].get("path"))
            entries.append({"then": number, "quote": words, "source": source, "seen_on": source, "kind": "seen"})
            continue
        source = next((str(ref.get("path")) for ref in text_refs if _quote_in(task, ref, words)), None)
        if source is None:
            held = ", ".join(Path(str(ref.get("path"))).name for ref in text_refs) or "no text capture"
            problems.append(f"the quote for Then {number} is not in the text this attempt captured ({held}): copy the "
                            "words as the capture holds them"
                            + ("; the quote is beyond the stored part (truncated) of a capture stored cut"
                               if any(_cut_capture(task, ref) for ref in text_refs) else ""))
            continue
        entries.append({"then": number, "quote": words, "source": source, "kind": "text"})
    if known:
        problems.extend(_then_coverage_problems(numbers, result, entries))
    return sorted(entries, key=lambda entry: entry["then"]), problems


def _then_coverage_problems(numbers, result, entries) -> list:
    """The coverage rule of the Then quotes, ONE function for `_then_quote_problems` (build, rejudge) and `write_block`
    (a record written by hand): a pass has a quote for every Then of the case and leaves none unreached; a fail has a
    quote for at least one. `entries` are the record's `then_quotes`; anything in it that is no object counts for nothing."""
    entries = [entry for entry in entries or [] if isinstance(entry, dict)]
    quoted = {entry.get("then") for entry in entries if "quote" in entry}
    problems = []
    if result == "pass":
        missing = [number for number in numbers if number not in quoted]
        if missing:
            problems.append("a pass stands on a quote for every Then of the case; none for Then "
                            + ", ".join(map(str, missing)))
        if any(entry.get("reached") is False for entry in entries):
            problems.append("a pass cannot leave a Then unreached")
    if result == "fail" and numbers and not quoted:
        problems.append("a fail stands on a quote for the Then it failed on; none was given")
    return problems


def _request_thens(task, case) -> list:
    """The numbers of the Thens `request.json` of this case lists, or [] when the request is absent, unreadable, or was made
    before the rule (no `thens` key): nothing is asked of such a record."""
    import manual_capture as MC
    if not isinstance(case, str):
        return []
    thens = _read_json(MC.case_root(task, case) / "request.json").get("thens")
    if not isinstance(thens, dict):
        return []
    return sorted(int(key) for key in thens if str(key).isascii() and str(key).isdigit())


def _quote_refusal(problems) -> ValueError:
    return ValueError("the Then quotes cannot be used: " + "; ".join(problems) + ". Door: " + QUOTE_DOOR)


def _step_line(step) -> str:
    return step["step"] + " -> " + step["outcome"] + (": " + step["detail"] if step.get("detail") else "")


def _attempt_files(folder: Path, name, case):
    """(captures, steps, probes, held, before, after) of one attempt's files, or the refusal a role can act on: nothing
    captured, two stands in one attempt, no probe at its start or end. `build` reads its own attempt and each joined one
    (`--with-attempt`) through this one function."""
    import manual_capture as MC
    live = sorted(p.parent.name for p in (folder / "sessions").glob("*/profile") if p.is_dir()) if (folder / "sessions").is_dir() else []
    if live:
        raise ValueError(f"attempt {name} of {case} still holds the live browser profile of {', '.join(live)} (its cookies are a "
                         "secret and must not stay beside a record): close the sessions first: `manual_capture.py session close "
                         f"--task-root <T> --case {case} --attempt {name}`, then build again")
    captures, steps, probes = (_jsonl(folder / f"{n}.jsonl") for n in ("captures", "steps", "probes"))
    if not captures:
        raise ValueError(f"attempt {name} of {case} holds no captures: capture first")
    held = MC.profiles_of(probes)
    if len(held) > 1:
        # One attempt is one stand identity (t-277 F4): a ui session and an api call in the same attempt would be
        # bracketed by two different probes, and `validate` would only say "provenance changed". Said here with both
        # names and the way out; `validate` keeps its own check as the backstop.
        raise ValueError(f"attempt {name} of {case} holds captures of two stands ({' and '.join(held)}): runtime "
                         "provenance changed during the attempt, so no record can say which build it saw. Capture "
                         "each profile as its own attempt (`manual_capture.py` opens the next one itself when you "
                         "leave --attempt out) and build with --attempt of the one that proves the case "
                         "(`--with-attempt` joins the others to it)")
    starts = [p for p in probes if p.get("when") == "start"]
    ends = [p for p in probes if p.get("when") == "end"]
    if not starts or not ends:
        raise ValueError(f"attempt {name} has no stand probe at its {'start' if not starts else 'end'}: the record "
                         "must say which build it saw. Capture again as a new attempt")
    return captures, steps, probes, held, starts[0]["probe"], ends[-1]["probe"]


def _evidence_refs(captures) -> list:
    return [{"path": c["path"], "content_hash": c["content_hash"], "kind": c["kind"], "phase": c["phase"],
             "captured_at": c["captured_at"], "proves": c["proves"], "mask_acknowledged": True} for c in captures]


def _joined_attempt(task, root, case, main_name, name, taken, expected) -> dict:
    """What `--with-attempt <name>` adds to the record of `main_name` (FB-12): the refs, the steps and the two probes of
    ANOTHER stand profile, from an attempt nobody built a record from. Refused, naming the attempt, when it is the main
    one, has no files, is already written or env_blocked, holds a profile the record already has (one profile is one
    attempt: that rule stays), or names another expected source revision than the main attempt's probes (`expected`)."""
    import manual_capture as MC
    if name == main_name:
        raise ValueError(f"--with-attempt {name} is the attempt {case} is built from: name the OTHER profile's attempt")
    if name not in MC.attempts_of(root):
        raise ValueError(f"--with-attempt {name} of {case} has no captured files: capture that profile first "
                         "(`manual_capture.py ui|http ...` opens the next attempt itself)")
    state = MC.attempt_state(root / name)
    if state != "open":
        raise ValueError(f"--with-attempt {name} of {case} is {state}: only an attempt no record was built from can be "
                         "joined. Capture that profile again as a new attempt and join that one")
    captures, steps, probes, held, before, after = _attempt_files(root / name, name, case)
    profile = held[0] if held else str(before.get("profile_id") or "")
    if profile in taken:
        raise ValueError(f"--with-attempt {name} of {case} holds the stand profile {profile}, which the record already "
                         "has: one profile is one attempt, so a second attempt of the same profile cannot join it. "
                         "Join an attempt of ANOTHER profile")
    if before.get("expected_source_revision") != expected or after.get("expected_source_revision") != expected:
        raise ValueError(f"--with-attempt {name} of {case} names another expected source revision than attempt "
                         f"{main_name} does: one record is one source revision, so build it from attempts made on the "
                         "same checkout, or capture the profile again after the stand is rebuilt")
    return {"profile": profile, "captures": captures, "steps": steps, "probes": probes,
            "part": {"attempt": name, "runtime_before": before, "runtime_after": after,
                     "steps_actual": [_step_line(s) for s in steps]}}


def build_record(task, case, result, actual, masked, limitations=(), attempt=None, quotes=(), with_attempts=(),
                 observations=(), about=None) -> dict:
    """Assemble the record of ONE case from `request.json` and the latest attempt's captured files, validate
    it, and write its block. Returns {"block", "record", ...}.

    Never changes `result` (FR-35, P1): the runner judged, and a `pass` the validator refuses is refused with
    the door - capture the post_action again, or say `inconclusive`. Never stamps `completion` (C7): the proof
    is the `proves` the runner's own `capture post_action completion` line wrote into captures.jsonl.

    `quotes` (HF8-19): the Then quotes the verdict stands on, `_then_quote_problems`. `with_attempts` (FB-12): the open
    attempts of OTHER stand profiles that join this record (`_joined_attempt`): one record, each profile with its own
    probes. `observations` (P26): everything doubtful the runner saw, `[{step, expected, seen, evidence, quote}]`, the record's
    `observations[]` (`_observation_errors`); `()` writes the declared empty outcome `[]`. An observation may carry
    `"surprise": "<id>"` (a line of `surprises.jsonl`, `_surprise_cite_errors`); the record carries `surprises`
    and `surprise_detection` (`_surprise_fields`, t-1765 X8-3). `about` (t-2181 PC-5a): the record-level list of the story's sides the walk
    speaks about, put on the record when it is not None (C11 checks the names; `validate_record` refuses a non-side)."""
    import manual_capture as MC
    task = Path(task).resolve()
    _check_words(result, actual)
    if not masked:
        raise ValueError("--masked is missing: say, once, that what the captures show is masked or generated "
                         "(common-rules.md, 'Data the project marked as real never reaches an artifact verbatim'); "
                         "if you cannot say it, capture again with a generated record and say what stopped you "
                         "in --limitation with --result inconclusive")
    root = MC.case_root(task, case)
    request = _load_request(task, root, case)
    names = MC.attempts_of(root)
    name = attempt or (names[-1] if names else "")
    if not name or name not in names:
        raise ValueError((f"attempt {name} of {case} has no captured files. " if name else f"nothing was captured for {case}. ") +
                         "Capture first: `manual_capture.py ui --steps-file ...` or `manual_capture.py http ...`")
    folder = root / name
    state = MC.attempt_state(folder)
    if state == "written":
        raise ValueError(f"attempt {name} of {case} is already written ({(folder / 'record.json').relative_to(task).as_posix()}): "
                         "a record is never rebuilt over the files it was built from. Capture again as a new "
                         f"attempt (--attempt a{MC.attempt_number(name) + 1}) and build with that --attempt")
    if state == "env_blocked":
        row = json.loads((folder / "env_blocked.json").read_text(encoding="utf-8"))
        # One message for both causes the capture writes env_blocked.json for: the stand's probe (the stand could not
        # be identified) and the login by code that did not land (`do_not_retry`); the probe line says which.
        why = ""
        if row.get("cause") == MC.LOGIN_UNKNOWN_CAUSE:
            # the login by code was not tried (nothing sent): the factory's gap, no gap of the stand and no halt
            raise ValueError(f"attempt {name} of {case} has no record: {row.get('probe_line')}. (the login by code was "
                             "not tried and nothing was sent: capture the case again as a new attempt, signing in "
                             "through fill-account steps; the block goes on)")
        if row.get("do_not_retry"):
            # a build the person must answer for (cause `build`, t-300 N2 X13) and a login that did not land say the
            # same thing about the door - no capture again while the cause stands - each with its own cause
            why = ((" (the stand does not hold this story's build, or nobody could say which one it holds: do "
                    if row.get("cause") == "build" else " (the login did not land: do ")
                   + "not capture it again before that - make no further capture of any kind in this block - and "
                   "halt the block)")
        raise ValueError(f"attempt {name} of {case} has no record: {row.get('probe_line')}. Put the case in "
                         f"env_blocked[] with that line and the remedy ({row.get('remedy')}); capture the case again "
                         "as a new attempt only when the cause is gone" + why)
    captures, steps, probes, held, before, after = _attempt_files(folder, name, case)
    taken = [held[0] if held else str(before.get("profile_id") or "")]
    joined = []
    for other in dict.fromkeys(with_attempts or []):
        part = _joined_attempt(task, root, case, name, other, taken, before.get("expected_source_revision"))
        taken.append(part["profile"])
        joined.append(part)
    every = [(captures, steps, probes)] + [(p["captures"], p["steps"], p["probes"]) for p in joined]
    moments = [_moment(x[key]) for group in every for rows, key in zip(group, ("captured_at", "at", "at"))
               for x in rows if x.get(key)]
    seen = []
    for text in [c.get("limitation") for group in every for c in group[0]] + list(limitations or []):
        if isinstance(text, str) and text.strip() and text not in seen:
            seen.append(text)
    for probe in (before, after):
        # t-300 N2 S12 (E8, FR-10/FR-35/FR-58): a record that stands on the PERSON'S WORD says so, in code's words, in
        # `limitations[]` - a reader of the record never takes it for a verified build. (The sentence of t-279 K-IMG,
        # "the stand was identified by the image it runs", is no longer written: `unknown` is not taken now; old
        # records that carry it are still told from a role's text, `s7_pretriage.code_sentences`.)
        for sentence in person_sentences(probe):
            if sentence not in seen:
                seen.append(sentence)
    register = ""
    try:
        import contract as C
        register = C.read_text(C.artifact(task, "requirements-register.md"))
    except Exception:
        register = ""
    refs = _evidence_refs(captures) + [ref for p in joined for ref in _evidence_refs(p["captures"])]
    entries, problems = _then_quote_problems(task, request, result, quotes, refs)
    if problems:
        raise _quote_refusal(problems)
    # t-1765 X8-3: the surprise lines of the main attempt and of each joined one travel in the record whole (AR-21, AR-27); a
    # citation in `observations[].surprise` is checked against the same lines (an id of an attempt this record does not hold: the
    # door is `--with-attempt`, E16)
    attempts = [name] + [p["part"]["attempt"] for p in joined]
    carried = _surprise_fields(task, root, attempts, refs)
    cited = _surprise_cite_errors(observations, {row["id"] for a in attempts for row in surprises_of(root / a)}, attempts,
                                  "join that attempt: `manual_evidence.py build ... --with-attempt {attempt}` (an open attempt of ANOTHER stand profile)")
    if cited:
        raise ValueError("the observations cannot be used: " + "; ".join(cited))
    record = {"schema_version": 2, "case": request["case"], "case_version": request["case_version"],
              "obligation_ids": request["obligation_ids"], "obligation_hashes": request["obligation_hashes"],
              "attempt_id": name, "dispatch_id": _running_dispatch(task, request["case"]),
              "source_revision": request["source_revision"],
              "runtime_identity": before.get("observed_runtime_identity"),
              "steps_actual": [_step_line(s) for s in steps],
              "expected": request["expected"], "actual": str(actual).strip(),
              "completion_condition": request["completion_condition"],
              "attempt_started_at": min(moments).isoformat(timespec="seconds"),
              "attempt_ended_at": max(moments).isoformat(timespec="seconds"),
              "result": result, "runtime_before": before, "runtime_after": after,
              "evidence_policy": request["evidence_policy"], "limitations": seen, "evidence_refs": refs,
              "gate_a_decision_ref": request["gate_a_decision_ref"],
              "approved_policy_hash": request["approved_policy_hash"],
              "before_change": before_change_for(register, request.get("covers") or []),
              "observations": list(observations or []), **carried}
    if request.get("before_not_applicable_reason"):
        record["before_not_applicable_reason"] = request["before_not_applicable_reason"]
    if about is not None:
        record["about"] = about
    if entries:
        record["then_quotes"] = entries
    if joined:
        record["other_profiles"] = [p["part"] for p in joined]
    door = ("capture the post_action again (a new attempt), or record `--result inconclusive` with `--limitation` "
            "saying what stopped the check" if result == "pass" else
            "capture what is missing again (a new attempt), or record `--result inconclusive` with `--limitation`")
    issues = validate_record(record, task, request.get("evidence_policy"))
    if issues:
        raise ValueError("the record cannot be written: " + "; ".join(issues) + f". Door: {door}")
    try:
        block = write_block(task, [record])
    except ValueError as exc:
        raise ValueError(f"the record cannot be written: {exc}. Door: {door}")
    atomic_json(folder / "record.json", record)
    for part in joined:          # the joined attempts are written too (`attempt_state`): nobody builds a second record from them
        atomic_json(root / part["part"]["attempt"] / "record.json", {"part_of": name})
    done = {"written": True, "case": record["case"], "attempt": name, "result": result,
            "block": block.relative_to(task).as_posix(), "before_change": record["before_change"],
            "evidence": [r["path"] for r in refs]}
    if joined:
        done["joined"] = [p["part"]["attempt"] for p in joined]
    if not isinstance(request.get("thens"), dict):
        done["notes"] = ["request.json of this case lists no Thens (it was made before the quote rule): no quote was asked for"]
    return done


def rejudge_sentence(of_attempt, reason) -> str:
    """The sentence code writes into `limitations[]` of a re-judged record: the check was NOT run again, the verdict is a new
    reading of an old attempt's captures, and why. ONE function (like `person_sentences`): `rejudge_record` writes it and
    a reader that must tell code's sentence from a role's recognises it by `REJUDGE_SENTENCE`'s fixed opening."""
    return REJUDGE_SENTENCE.format(attempt=of_attempt, reason=_squash(reason))


_REJUDGE_FILE = re.compile(r"rejudge-(\d+)\.json")


def _completion_ref(task, refs, completion):
    """The ONE evidence ref a re-judge `--completion <path>` names: a `post_action` capture of the attempt itself. A
    `supporting` capture never stands in for the completion (C7: the proof is a post_action capture the role names), and a
    path that is no evidence file of the attempt names nothing."""
    wanted = str(completion).strip().replace("\\", "/")
    try:
        absolute = Path(wanted)
        if absolute.is_absolute():
            wanted = absolute.resolve().relative_to(Path(task).resolve()).as_posix()
    except (OSError, ValueError):
        pass
    hits = [ref for ref in refs if str(ref.get("path")) == wanted]
    if len(hits) != 1:
        raise ValueError(f"--completion {completion!r} is no evidence file of that attempt: name the post_action capture "
                         "that proves the completion, by the path captures.jsonl holds")
    if PHASE_ALIAS.get(hits[0].get("phase"), hits[0].get("phase")) != "after":
        raise ValueError(f"--completion {completion!r} is a {hits[0].get('phase')} capture: only a post_action capture can "
                         "prove the completion. Capture the page after the action again as a new attempt")
    return hits[0]


def _later_record(root, of_attempt):
    """The newest attempt of the case after `of_attempt` that has a record of its own (a joined attempt, `part_of`, has
    none), or None. A re-judge of an older attempt must not take the place of a newer run (its verdict starts now and the
    reducer orders by start)."""
    import manual_capture as MC
    later = [name for name in MC.attempts_of(root) if MC.attempt_number(name) > MC.attempt_number(of_attempt)
             and MC.attempt_state(root / name) == "written"
             and not _read_json(root / name / "record.json").get("part_of")]
    return later[-1] if later else None


OBSERVATION_FILE_COMMANDS = ("build", "rejudge", "write-block", "unprepared")    # the commands that read `--observations-file`


def rejudge_record(task, case, of_attempt, result, actual, reason, quotes=(), completion=None, limitations=(),
                   observations=None) -> dict:
    """A new verdict on a WRITTEN attempt, without running the check again (HF8-19): a new record that copies the old
    one's evidence, probes and steps byte for byte and changes only `result`, `actual` and `then_quotes`, adds
    `rejudge_of`, `rejudge_reason` and a code sentence in `limitations[]`, and starts NOW (`attempt_started_at` is the
    clock: the reducer orders blocks by it, and the original's own time would tie with it). It is written as
    `<attempt>/rejudge-<k>.json`; `record.json` is never touched (I4). It goes through `validate_record` and
    `write_block` exactly as a built record does (I6): a changed file, a stale revision, a pass with no completion proof is
    refused, and nothing is relaxed because the check is not run again. A pass whose attempt never proved the completion
    names the proving capture with `--completion` (it goes into the COPY, and the ref says it was named at the re-judge)."""
    import manual_capture as MC
    task = Path(task).resolve()
    _check_words(result, actual)
    if not _squash(reason):
        raise ValueError("--reason is empty: say why the first verdict was wrong (the person reads it beside the result)")
    if MC.attempt_number(of_attempt) < 0:
        raise ValueError(f"--of-attempt {of_attempt!r} is not an attempt name. Expected a<number>, for example a9")
    given = [x.strip() for x in limitations or [] if isinstance(x, str) and x.strip()]
    if result == "inconclusive" and not given:
        raise ValueError("--limitation is missing: an inconclusive re-judge says, in your words, what stopped the check "
                         "(`manual_evidence.py rejudge --limitation \"<words>\"`); the sentence code adds about the re-judge "
                         "is not that")
    root = MC.case_root(task, case)
    request = _load_request(task, root, case)
    if of_attempt not in MC.attempts_of(root):
        raise ValueError(f"attempt {of_attempt} of {case} has no captured files, so there is nothing to judge again. "
                         "Capture first (`manual_capture.py ...`), then `build`")
    folder = root / of_attempt
    state = MC.attempt_state(folder)
    if state == "open":
        raise ValueError(f"attempt {of_attempt} of {case} has no record yet, so there is no verdict to change. Build it "
                         f"first (`manual_evidence.py build --attempt {of_attempt}`)")
    if state == "env_blocked":
        raise ValueError(f"attempt {of_attempt} of {case} has no record (the stand could not be verified): nothing to judge "
                         "again. Capture the case again as a new attempt once the cause is gone")
    try:
        base = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(f"the record of attempt {of_attempt} of {case} cannot be read. Capture the case again as a new attempt")
    if isinstance(base, dict) and base.get("part_of"):
        raise ValueError(f"attempt {of_attempt} of {case} is part of the record of {base['part_of']}: re-judge "
                         f"--of-attempt {base['part_of']}")
    if not isinstance(base, dict) or base.get("schema_version") != 2 or base.get("case") != case:
        raise ValueError(f"the record of attempt {of_attempt} is not a v2 record of {case}. Capture the case again as a "
                         "new attempt")
    newer = _later_record(root, of_attempt)
    if newer:
        raise ValueError(f"attempt {newer} of {case} is a later run with a record of its own: a re-judge of {of_attempt} "
                         f"would take its place. Re-judge the newer one (--of-attempt {newer}), or capture the case again")
    number = 1 + max([int(m.group(1)) for p in folder.glob("rejudge-*.json") for m in [_REJUDGE_FILE.fullmatch(p.name)] if m] or [0])
    new = json.loads(json.dumps(base))
    refs = new.get("evidence_refs") if isinstance(new.get("evidence_refs"), list) else []
    if completion:
        ref = _completion_ref(task, refs, completion)
        if "completion" not in [str(x).lower() for x in ref.get("proves") or []]:
            ref["proves"] = list(ref.get("proves") or []) + ["completion"]
            ref["completion_named_at_rejudge"] = True
    entries, problems = _then_quote_problems(task, request, result, quotes, refs)
    if problems:
        raise _quote_refusal(problems)
    moments = [_moment(base[key]) for key in ("attempt_started_at", "attempt_ended_at") if base.get(key)]
    moments += [_moment(row[key]) for p in folder.glob("rejudge-*.json") for row in [_read_json(p)]
                for key in ("attempt_started_at", "attempt_ended_at") if row.get(key)]
    now = max([datetime.now().astimezone().replace(microsecond=0)] + [m + timedelta(seconds=1) for m in moments])
    new.update({"result": result, "actual": str(actual).strip(), "rejudge_of": of_attempt,
                "rejudge_reason": _squash(reason), "attempt_id": f"{of_attempt}-r{number}",
                "dispatch_id": _running_dispatch(task, case),
                "attempt_started_at": now.isoformat(timespec="seconds"), "attempt_ended_at": now.isoformat(timespec="seconds")})
    if entries:
        new["then_quotes"] = entries
    else:
        new.pop("then_quotes", None)
    if observations is not None:      # F6: the runner's own list of this re-judge REPLACES the base's (`[]` is a list too)
        new["observations"] = observations
        # t-1765 X8-3: a citation names a line of the attempts the base record holds; a re-judge joins no attempt (nothing is run)
        held = [of_attempt] + [str(p.get("attempt")) for p in base.get("other_profiles") or [] if isinstance(p, dict)]
        cited = _surprise_cite_errors(observations, {row["id"] for a in held for row in surprises_of(root / a)}, held,
                                      "a re-judge keeps the attempts of the record it judges again; cite a surprise of one of them, "
                                      "or build the case again with `--with-attempt {attempt}`")
        if cited:
            raise ValueError("the observations cannot be used: " + "; ".join(cited))
    new.setdefault("observations", [])      # a record made before the rule reads as [] (E14); the new one declares it
    # t-1765 X8-3 (C6): the surprise fields of the base travel unchanged - nothing is run again, so nothing is recounted (AR-21); a base
    # made before the detector declares what is true of it
    new.setdefault("surprises", [])
    new.pop("surprises_ignored", None)      # a base written before X9 carries the retired count; nothing reads it (AR-22)
    new.setdefault("surprise_detection", "absent: the attempt was recorded before the detector wrote its lines")
    sentence = rejudge_sentence(of_attempt, reason)
    kept = [x for x in base.get("limitations") or [] if x != sentence]
    new["limitations"] = kept + [x for x in given if x not in kept] + [sentence]
    door = ("capture the case again as a new attempt"
            + (", or name the post_action capture that proves the completion with `--completion <path>`" if result == "pass" else "")
            + ", or record `--result inconclusive` with `--limitation`")
    issues = validate_record(new, task, request.get("evidence_policy"))
    if issues:
        raise ValueError("the re-judged record cannot be written: " + "; ".join(issues) + f". Door: {door}")
    try:
        block = write_block(task, [new])
    except ValueError as exc:
        raise ValueError(f"the re-judged record cannot be written: {exc}. Door: {door}")
    atomic_json(folder / f"rejudge-{number}.json", new)
    done = {"written": True, "rejudged": True, "case": case, "attempt": new["attempt_id"], "of_attempt": of_attempt,
            "result": result, "block": block.relative_to(task).as_posix(), "evidence": [r["path"] for r in refs]}
    if not isinstance(request.get("thens"), dict):
        done["notes"] = ["request.json of this case lists no Thens (it was made before the quote rule): no quote was asked for"]
    return done


def _read_json(path) -> dict:
    return hooklib.read_json(path, {}, kind=dict)  # absent, broken or not an object: {}


def main(argv=None):
    parser = argparse.ArgumentParser(epilog=epilog("manual_evidence.py"),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("prepare", "validate", "write-block", "write-baseline", "export",
                                            "build", "rejudge", "unprepared"))
    parser.add_argument("--task-root", required=True)
    parser.add_argument("--input", help="the JSON file of every command but `build` and `rejudge`")
    parser.add_argument("--output")
    parser.add_argument("--case", help="build: the case id as the dispatch scope spells it")
    parser.add_argument("--result", help="build: pass | fail | inconclusive - your own judgment, never changed")
    parser.add_argument("--actual", help="build: what you saw, in the product's words")
    parser.add_argument("--masked", action="store_true",
                        help="build: what the captures show is masked or generated (common-rules.md)")
    parser.add_argument("--limitation", action="append", help="build, rejudge: what stopped or narrowed the check")
    parser.add_argument("--attempt", help="build: a<number>; default the latest attempt")
    parser.add_argument("--then-quote", action="append", metavar="N=WORDS",
                        help="build, rejudge: the words of the captured text that decide Then N (repeat per Then; a pass "
                             "needs every Then, a fail the one it failed on)")
    parser.add_argument("--then-seen", action="append", metavar="N=WORDS",
                        help="build, rejudge: Then N is decided by what the picture after the action shows, not by text")
    parser.add_argument("--then-unreached", action="append", metavar="N",
                        help="build, rejudge: on a fail, Then N was never reached")
    parser.add_argument("--with-attempt", action="append", metavar="aN",
                        help="build: join the open attempt aN of ANOTHER stand profile to this record (repeat per profile)")
    parser.add_argument("--of-attempt", help="rejudge: the written attempt whose captures are read again")
    parser.add_argument("--reason", help="rejudge: why the first verdict was wrong, in words")
    parser.add_argument("--completion", help="rejudge: the post_action capture (its path) that proves the completion")
    parser.add_argument("--observations-file", help="build, rejudge, write-block, unprepared: a JSON list of observations "
                                                    "[{step, expected, seen, evidence, quote[, surprise]}]; absent = []")
    parser.add_argument("--about", action="append", metavar="SIDE",
                        help="build: a side of the story this walk speaks about (repeat per side); absent = the record has no `about`")
    parser.add_argument("--not-walked", help="unprepared: why nothing of the case was walked with the recorder (required when no "
                                             "attempt holds a step, refused when one does)")
    args = hooklib.exact_options(parser).parse_args(argv)
    quotes = ([("text", v) for v in args.then_quote or []] + [("seen", v) for v in args.then_seen or []]
              + [("unreached", v) for v in args.then_unreached or []])
    try:        # the story first (CX1-18): `prepare`/`build`/`write-block` create under a root that must exist
        hooklib.story_of("manual_evidence.py", root=args.task_root, key_flag=None)
    except ValueError as exc:       # this script's own channel (E-5)
        return refuse(f"manual_evidence.py {args.command}", str(exc))
    observations = []
    if args.observations_file and args.command not in OBSERVATION_FILE_COMMANDS:
        # F6 (t-1747): a flag that a command does not read is never dropped without a word (FR-4, AR-22)
        return refuse(f"manual_evidence.py {args.command}", f"--observations-file is read by {', '.join(OBSERVATION_FILE_COMMANDS)} "
                      f"only, and `{args.command}` would ignore it. Leave it out, or put the observations into the command that "
                      "writes the record")
    if args.observations_file:
        try:
            observations = json.loads(Path(args.observations_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return refuse(f"manual_evidence.py {args.command}", f"{args.observations_file} is not readable JSON ({exc}); it "
                          "holds a list: [{\"step\": 1, \"expected\": ..., \"seen\": ..., \"evidence\": ..., \"quote\": ...}]")
        if not isinstance(observations, list):
            return refuse(f"manual_evidence.py {args.command}", f"{args.observations_file} must hold a JSON list of "
                          "observations ([] when you saw nothing doubtful)")
    if args.about and args.command != "build":
        return refuse(f"manual_evidence.py {args.command}", f"--about is read by `build` only, and `{args.command}` would ignore it. "
                      "Leave it out (a re-judge keeps the `about` of the record it judges again)")
    if args.command == "build":
        missing = [flag for flag, value in (("--case", args.case), ("--result", args.result),
                                            ("--actual", args.actual)) if not value]
        if missing:
            return refuse("manual_evidence.py build", f"{', '.join(missing)} missing")
        done = build_record(args.task_root, args.case, args.result, args.actual, args.masked,
                            args.limitation or [], args.attempt, quotes, args.with_attempt or [], observations,
                            about=args.about)
        print(json.dumps(done))
        return 0
    if args.command == "unprepared":
        if not args.case:
            return refuse("manual_evidence.py unprepared", "--case missing")
        if args.not_walked is not None and not args.not_walked.strip():
            return refuse("manual_evidence.py unprepared", "--not-walked is blank: say why it was not walked, or leave it out when "
                          "the case was walked with the recorder")
        try:
            block = write_unprepared(args.task_root, args.case, observations, args.not_walked or "")
        except ValueError as exc:
            return refuse("manual_evidence.py unprepared", str(exc))
        print(json.dumps({"written": True, "case": args.case, "block": Path(block).relative_to(Path(args.task_root).resolve()).as_posix()}))
        return 0
    if args.command == "rejudge":
        missing = [flag for flag, value in (("--case", args.case), ("--of-attempt", args.of_attempt), ("--result", args.result),
                                            ("--actual", args.actual), ("--reason", args.reason)) if not value]
        if missing:
            return refuse("manual_evidence.py rejudge", f"{', '.join(missing)} missing")
        # `--masked` is the build's: the files a re-judge reads were captured and acknowledged then, and are copied as they were
        done = rejudge_record(args.task_root, args.case, args.of_attempt, args.result, args.actual, args.reason,
                              quotes, args.completion, args.limitation or [],
                              observations if args.observations_file else None)
        print(json.dumps(done))
        return 0
    if not args.input:
        return refuse(f"manual_evidence.py {args.command}", "--input is missing: the file holds the JSON this command reads")
    try:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"manual_evidence: {args.input} is not readable JSON: {exc}", file=sys.stderr)
        return 2
    if args.command == "prepare":
        missing = [k for k in ("case", "obligation_ids") if not (data or {}).get(k)]
        if missing:
            return refuse("manual_evidence.py prepare",
                          f"{args.input} carries no {', '.join(missing)}")
        # request.json is written either way (C3): the request, or the refusal in words with its door.
        result = prepare_to_file(args.task_root, data['case'], data['obligation_ids'])
        if args.output:
            atomic_json(args.output, result)
        print(json.dumps(result))
        return 0
    if args.command == "validate":
        errors = validate_record(data, args.task_root)
        print(json.dumps({"valid": not errors, "errors": errors}))
        return 0 if not errors else 1
    if args.command == "write-baseline":
        print(write_baseline_receipt(args.task_root, data))
        return 0
    records = data if isinstance(data, list) else data.get("manual_checks", [])
    if args.command == "write-block":
        # A refusal is an instruction, never a traceback: the runner of TP1-13797 spent
        # 96 turns and fourteen input files against `ValueError: manual block requires
        # current records`, because neither --help nor the error names the shape.
        try:
            if args.observations_file:
                if len(records) != 1 or not isinstance(records[0], dict):
                    raise ValueError("--observations-file names the observations of ONE record: this input holds "
                                     f"{len(records)}; put `observations` into each record of the block instead")
                records = [dict(records[0], observations=observations)]
            print(write_block(args.task_root, records, declared=True))
        except ValueError as exc:
            return refuse("manual_evidence.py write-block", str(exc))
    else:
        if not args.output:
            parser.error("export requires --output")
        if not records:
            # An export of nothing used to print the path and exit 0, so the role went on
            # believing its evidence was published.
            return refuse("manual_evidence.py export",
                          f"{args.input} carries no records, so there is nothing to export")
        result = export_records(args.task_root, records)
        atomic_json(args.output, result)
        print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(run_guarded(command_from_argv("manual_evidence.py"), main))
