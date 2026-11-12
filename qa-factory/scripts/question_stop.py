#!/usr/bin/env python3
"""The threshold for "stop and ask the whole batch", and the text of that batch (t-113 piece B1).

    over_threshold(task_root, config=None) -> {over, count, count_limit, share, share_limit, source, reasons, ...}
    blocking_stop(task_root) -> {stop, ids, unmarked, reasons}
    open_cards(task_root, card=None) -> [line]
    answer_block(task_root, whole=()) -> str
    batch_text(task_root, reason, card=None, previous_answer_at=None, priced="") -> str

TP1-13797 (cmp1): the register held five open questions and gate A printed six cards of eleven,
the rest cut silently. A stop that asks a person must carry EVERY open question, and it must say
how many questions is "too many" and whose number that is. Two conditions stop, either one (owner,
30.09): more than 6 open questions, OR more than a third of the requirements resting on open
questions. They are the factory's defaults (`references/question-thresholds.json`); a project sets
its own in `qa-factory/config.json` as `questions.stop_at: {count, share}`.

This module only COUNTS and RENDERS. It never judges a reading or a confidence (FR-47: the role
judges, and raises its own stop); it writes nothing (FR-45); it never refuses a project's bad number
- it falls back to the default for that field and says so (FR-4: a check stops a silent pass, never
an informed one; the person's word passes the threshold, and recording the pass is the driver's).

  * open is `question_register.is_open` (AR-13, the one definition): `open` or `named` (the id stands in the
    person's old words, no answer was recorded), and an answered, not-needed or deferred question whose row
    changed since the answer or whose `before` value is still missing - it is asked again and counted again.
  * a blocker is `question_register.open_blocker`: an open question that is not marked `major` or `minor`. One
    open blocker stops the story whatever the count (`blocking_stop`).
  * the share is exact: the limit is kept as a fraction ("1/3" in the data file) and compared with
    `fractions`, never floats - 2 of 6 requirements is NOT over a third, 3 of 6 is.
  * an unknown is never a fact (FR-41): with no register total, or no question naming the
    requirements it rests on, the share is None and the text says it could not be computed.
"""
from __future__ import annotations

import json
import math
import re
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import question_register as QR  # noqa: E402

THRESHOLDS_PATH = HERE.parent / "references" / "question-thresholds.json"
OPEN_STATUSES = QR.OPEN_STATUSES  # a reference: the definition lives in question_register; the filter itself is QR.is_open
MARKED_BLOCKER = "blocker"        # a severity the S2 role set on purpose; any other value on a blocking question is "unmarked"
BLOCKING = "blocking"  # the stop reason of an open blocker (question-vocabulary.json `stop_reasons`)
DEFAULT_LABEL = "the factory's default threshold"
PROJECT_LABEL = "this project's threshold"
SOURCE_DEFAULT = "factory default"
SOURCE_PROJECT = "project"
_FRACTION = re.compile(r"\s*([0-9]+)\s*/\s*([0-9]+)\s*")


class _Invalid(ValueError):
    """A threshold value this module cannot use; the text says why, in plain words."""


# --------------------------------------------------------------------------------------------
# the numbers
# --------------------------------------------------------------------------------------------

def _as_count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Invalid("it is not a number")
    if isinstance(value, float):
        if not math.isfinite(value) or value != int(value):
            raise _Invalid("it is not a whole number")
        value = int(value)
    if value < 0:
        raise _Invalid("it is negative")
    return value


def _as_share(value) -> tuple:
    """(exact Fraction, text) of a share limit: a number between 0 and 1, or "n/d" (d not 0).
    A decimal goes through its written form (0.3 is 3/10, not the binary neighbour of 0.3), so
    3 requirements of 10 is not over a limit of 0.3."""
    if isinstance(value, bool):
        raise _Invalid("it is not a number")
    try:
        if isinstance(value, str):
            found = _FRACTION.fullmatch(value)
            if not found:
                raise _Invalid("it is not a number and not a fraction written n/d")
            num, den = int(found.group(1)), int(found.group(2))
            if den == 0:
                raise _Invalid("its denominator is zero")
            share, text = Fraction(num, den), f"{num}/{den}"
        elif isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                raise _Invalid("it is not a finite number")
            share = Fraction(repr(value))
            text = f"{float(share) * 100:g}%"
        else:
            raise _Invalid("it is not a number and not a fraction written n/d")
    except (ValueError, OverflowError) as exc:
        if isinstance(exc, _Invalid):
            raise
        raise _Invalid("it cannot be read as a number") from exc
    if share < 0:
        raise _Invalid("it is negative")
    if share > 1:
        raise _Invalid("it is more than 1 (all of the requirements)")
    return share, text


def defaults() -> dict:
    """The factory's own thresholds and the plain words for the stop reasons, from the data file
    (FR-13). An unusable file is a package defect: it raises RuntimeError naming the file, the same
    way `question_register.vocabulary()` does - a project's number is never the reason."""
    try:
        data = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8-sig"))
        count = _as_count(data["count"])
        share, text = _as_share(data["share"])
        words = data.get("reason_words", {})
        if not (isinstance(words, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in words.items())):
            raise _Invalid("`reason_words` must map a reason to a text")
        return {"count": count, "share": share, "share_text": text, "reason_words": words}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"{THRESHOLDS_PATH} is unusable ({type(exc).__name__}: {exc}); it holds `count` (a whole "
                           "number), `share` (written n/d) and `reason_words` - restore it from the package") from exc


def _find_config(task_root: Path, warnings: list):
    """The onboarded project's config, found by its marker like the other readers do; None when
    there is none. A config that cannot be read is a warning and the defaults - never a refusal."""
    try:
        start = Path(task_root).resolve()
        for base in (start, *start.parents):
            candidate = base / "qa-factory" / "config.json"
            if candidate.is_file():
                try:
                    return json.loads(candidate.read_bytes().decode("utf-8-sig", errors="replace"))
                except (OSError, ValueError, RecursionError):
                    warnings.append("This project's settings file could not be read, so the factory's default "
                                    "thresholds for asking questions are used.")
                    return None
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def _limits(task_root, config, warnings: list) -> dict:
    """The limits in force: per field, the project's value when it is usable, else the default."""
    base = defaults()
    out = {"count": base["count"], "share": base["share"], "share_text": base["share_text"],
           "sources": {"count": SOURCE_DEFAULT, "share": SOURCE_DEFAULT}, "reason_words": base["reason_words"]}
    cfg = config if config is not None else _find_config(task_root, warnings)
    if cfg is None:
        return out
    if not isinstance(cfg, dict):
        warnings.append("This project's settings are not in the expected shape, so the factory's default "
                        "thresholds for asking questions are used.")
        return out
    section = cfg.get("questions")
    if section is None:
        return out
    stop_at = section.get("stop_at") if isinstance(section, dict) else section
    if stop_at is None:
        return out
    if not isinstance(stop_at, dict):
        warnings.append("This project's thresholds for asking questions are not in the expected shape "
                        "(`questions.stop_at` must hold a `count` and a `share`), so the factory's defaults are used.")
        return out
    if "count" in stop_at:
        try:
            out["count"], out["sources"]["count"] = _as_count(stop_at["count"]), SOURCE_PROJECT
        except _Invalid as exc:
            warnings.append(f"This project's limit for the number of open questions is {stop_at['count']!r}, but "
                            f"{exc}: the factory's default, {base['count']}, is used instead.")
    if "share" in stop_at:
        try:
            out["share"], out["share_text"] = _as_share(stop_at["share"])
            out["sources"]["share"] = SOURCE_PROJECT
        except _Invalid as exc:
            warnings.append(f"This project's limit for the share of requirements resting on open questions is "
                            f"{stop_at['share']!r}, but {exc}: the factory's default, {base['share_text']}, is "
                            "used instead.")
    return out


# --------------------------------------------------------------------------------------------
# the count
# --------------------------------------------------------------------------------------------

def _label(source: str) -> str:
    return PROJECT_LABEL if source == SOURCE_PROJECT else DEFAULT_LABEL


def _times(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _register_total(root: Path):
    """The register's requirement total as the S2 role wrote it (`register.total`), or None when it
    is absent or not a positive whole number. Never raises."""
    try:
        data = json.loads(root.joinpath(*QR.READINESS_REL).read_bytes().decode("utf-8-sig", errors="replace"))
        total = (data.get("register") or {}).get("total") if isinstance(data, dict) else None
    except (OSError, ValueError, RecursionError, AttributeError):
        return None
    if isinstance(total, bool) or not isinstance(total, int) or total <= 0:
        return None
    return total


def over_threshold(task_root, config=None) -> dict:
    """Count the open questions and the share of the register's requirements resting on them.

    `config` is the project's config (the parsed `qa-factory/config.json`); None means it is found
    from `task_root`. Returns
      over           True when count > count_limit OR share > share_limit (strictly greater)
      count          the number of questions the factory asks (`question_register.is_open`: no recorded answer, or
                     an answer on a row that changed since)
      count_limit    the limit in force (a whole number)
      share          |union of the requirements of those questions| / register total, as a float for
                     display; None when it cannot be computed (the decision never uses this float)
      share_limit    the limit in force, as a float for display; `share_limit_text` is its exact form
      source         "project" when any limit came from the project's config, else "factory default";
                     `sources` says it per field - a default is never presented as the project's number
      reasons        plain words, for a person: the two numbers, their limits and whose they are
      warnings       plain words: a project value that could not be used and what replaced it
    plus `requirements_open` and `requirements_total` (None when unknown).
    Never raises on the story's or the project's data; a broken package data file raises RuntimeError."""
    warnings: list = []
    limits = _limits(task_root, config, warnings)
    sources = limits["sources"]
    source = SOURCE_PROJECT if SOURCE_PROJECT in sources.values() else SOURCE_DEFAULT
    result = {"over": False, "count": 0, "count_limit": limits["count"], "share": None,
              "share_limit": float(limits["share"]), "share_limit_text": limits["share_text"],
              "source": source, "sources": dict(sources), "reasons": [], "warnings": warnings,
              "requirements_open": None, "requirements_total": None}
    root = Path(task_root)
    try:
        view = QR.load(root)
    except Exception as exc:  # the register is the story's own data: a failed read is a reason, not a crash
        result["reasons"].append("The question register could not be read "
                                 f"({type(exc).__name__}), so no question is counted and nothing is stopped on it.")
        return result
    if not view["register_present"]:
        result["reasons"].append("No question register was found for this story, so there is no question to count.")
        return result
    if not view["questions"] and view["problems"]:
        result["reasons"].append("The question register could not be read: " + view["problems"][0]
                                 + ". No question is counted and nothing is stopped on it.")
        return result
    questions = view["questions"]
    open_q = [q for q in questions if QR.is_open(q)]
    count = len(open_q)
    over_count = count > limits["count"]
    total = _register_total(root)
    carrying = [q for q in questions if isinstance(q.get("requirements"), list)]
    share_why = ""
    union: set = set()
    if total is None:
        share_why = "the register gives no total number of requirements"
    elif not carrying:
        share_why = "no question says which requirements it rests on"
    else:
        ignored = 0
        for q in open_q:
            for item in (q.get("requirements") if isinstance(q.get("requirements"), list) else []):
                if isinstance(item, str) and item.strip():
                    union.add(item.strip())
                else:
                    ignored += 1
        silent = sum(1 for q in open_q if not isinstance(q.get("requirements"), list))
        if ignored:
            warnings.append(f"{_times(ignored, 'entry')} in the lists of requirements were not texts and were not counted.")
        if silent:
            warnings.append(f"{_times(silent, 'open question')} name no requirements, so the share counts only the "
                            "questions that do and may be higher.")
        if len(union) > total:
            warnings.append(f"The open questions name {len(union)} requirements, more than the register's total of "
                            f"{total}: the register or the lists are wrong.")
    exact = None if share_why else Fraction(len(union), total)
    over_share = exact is not None and exact > limits["share"]
    result.update({"over": bool(over_count or over_share), "count": count,
                   "share": None if exact is None else float(exact),
                   "requirements_open": None if exact is None else len(union),
                   "requirements_total": total})
    reasons = result["reasons"]
    reasons.append(f"{_times(count, 'question')} {'is' if count == 1 else 'are'} open. The limit is "
                   f"{limits['count']} ({_label(sources['count'])})." + (" That is more than the limit." if over_count else ""))
    if exact is None:
        reasons.append(f"The share of requirements resting on open questions could not be computed ({share_why}), "
                       "so only the number of open questions decides.")
    else:
        reasons.append(f"{len(union)} of {_times(total, 'requirement')} ({float(exact) * 100:.0f}%) rest on an open "
                       f"question. The limit is {limits['share_text']} of the requirements ({_label(sources['share'])})."
                       + (" That is more than the limit." if over_share else ""))
    return result


# --------------------------------------------------------------------------------------------
# the blocking stop
# --------------------------------------------------------------------------------------------

def _unmarked(question) -> bool:
    """Is this an open blocker only because its `severity` is missing or unknown? The VERDICT (blocking or not) is
    `question_register.open_blocker`'s alone; this reads `severity` once more only to tell the person WHICH blockers
    the S2 role did not mark (H8): a question marked `blocker` blocks on purpose, any other value blocks because the
    factory asks rather than guesses (FR-59)."""
    return QR.open_blocker(question) and question.get("severity") != MARKED_BLOCKER


def blocking_stop(task_root) -> dict:
    """Is there an open blocking question? One of them stops the story, whatever the count (the owner's word, 24.10).

    Returns {"stop": bool, "ids": [id of every open blocker, register order], "unmarked": [the ids among them whose
    `severity` is none of blocker/major/minor], "reasons": [plain words - only when nothing can be stopped on: no
    register, an unreadable one]}. The verdict is `question_register.open_blocker` (AR-13): a missing or unknown severity
    blocks, an answer on a row that changed since does not hold, a deferred question is closed only while its record
    holds. A register that is absent or cannot be read stops nothing and says so (H22); an answers file that cannot be
    read leaves every question open, so it stops. Never raises on the story's data; writes nothing (FR-45)."""
    result = {"stop": False, "ids": [], "unmarked": [], "reasons": []}
    try:
        view = QR.load(Path(task_root))
    except Exception as exc:  # the register is the story's own data: a failed read is a reason, not a crash
        result["reasons"].append("The question register could not be read "
                                 f"({type(exc).__name__}), so no blocking question is counted and nothing is stopped on it.")
        return result
    if not view["register_present"]:
        result["reasons"].append("No question register was found for this story, so there is no blocking question to stop on.")
        return result
    if not view["questions"] and view["problems"]:
        result["reasons"].append("The question register could not be read: " + view["problems"][0]
                                 + ". No blocking question is counted and nothing is stopped on it.")
        return result
    blockers = [q for q in view["questions"] if QR.open_blocker(q)]
    result.update({"stop": bool(blockers), "ids": [q["id"] for q in blockers],
                   "unmarked": [q["id"] for q in blockers if _unmarked(q)]})
    return result


# --------------------------------------------------------------------------------------------
# the batch
# --------------------------------------------------------------------------------------------

def _plain_card(question: dict, index: int) -> list:
    """The card of last resort: the id and the question's own words. Used only when the renderer
    cannot be loaded or fails on one question - a question is never dropped for that."""
    return [f"- **{question['id']}** " + " ".join(str(question.get("question") or "").split())]


def _renderer(card):
    if card is not None:
        return card
    try:
        import gate_brief  # at call time: the gate's card is the one card the person already knows
        return gate_brief.question_card
    except Exception:
        return _plain_card


def _card_lines(render, question: dict, index: int) -> list:
    try:
        out = render(question, index)
    except Exception:
        out = _plain_card(question, index)
    lines = out.splitlines() if isinstance(out, str) else [str(x) for x in (out or [])]
    if not any(question["id"] in line for line in lines):
        lines = _plain_card(question, index) + lines  # the invariant: no open question is missing
    return lines


def _with_note(question: dict) -> dict:
    """The question as its card is rendered: a settled or deferred one that is asked again (its answer no longer holds)
    carries the gate's note saying why (`gate_brief.question_note`, the one writer of that text). A note that cannot be
    made leaves the card as it was - the question is still shown."""
    if question.get("status") in OPEN_STATUSES:
        return question
    try:
        import gate_brief
        note = gate_brief.question_note(question)
    except Exception:
        return question
    return dict(question, status_note=note) if note else question


def open_cards(task_root, card=None) -> list:
    """The card lines of every question the factory asks (`question_register.is_open`), in register order - the ONE place
    the stop's batch and the halt text of the driver take their cards from (AR-15). `card(question, index)` returns one
    card's lines; None means `gate_brief.question_card`, loaded now. A `named` question carries the line saying no
    answer was recorded for it; a question with no usable severity, the line saying the factory treats it as blocking
    (H8); one asked again because its answer no longer holds, the gate's note. [] when there is no register or nothing is
    open. A question is never dropped: a renderer that fails gives the plain card."""
    try:
        view = QR.load(Path(task_root))
    except Exception:
        return []
    render = _renderer(card)
    out: list = []
    for index, question in enumerate((q for q in view["questions"] if QR.is_open(q)), 1):
        out.extend(_card_lines(render, _with_note(question), index))
        if question.get("status") == "named":
            stray = QR.stray_line(question.get("id"), question.get("words"))   # a line of the person's that is no token is told as that (FR-10, F-6 of t-596)
            out.append(f"  - you named this question in your earlier words, on a line the factory did not read as an answer: \"{stray}\"." if stray
                       else "  - you named this question in your earlier words, but the factory recorded no answer for it.")
        if _unmarked(question):
            out.append("  - it is not said whether the work can go on without this answer, so the factory treats it as blocking.")
    return out


def _whole_line(whole) -> str:
    """The sentence naming the words that, as the WHOLE answer, are read as that word: "An answer that is only
    `stop` is read as that word." for one, "... only `go on`, or only `stop`, ..." for two; "" for none."""
    tokens = [f"only `{token}`" for token in whole]
    if not tokens:
        return ""
    return "An answer that is " + (tokens[0] if len(tokens) == 1 else ", or ".join(tokens) + ",") + " is read as that word."


def answer_block(task_root, whole=()) -> str:
    """The "how to answer" block, the one builder of it (AR-13): the three token forms, the own-words line and an
    example made of ids that are open. `whole` are the words read as that word when they are the whole answer: the stop
    of the questions offers `("go on", "stop")`, a halt only `("stop",)`, a text that offers none gives `()` and no such
    line. "" when no question is open or there is no register - there is nothing to answer by id."""
    try:
        open_q = [q for q in QR.load(Path(task_root))["questions"] if QR.is_open(q)]
    except Exception:
        return ""
    if not open_q:
        return ""
    lettered = next((q["id"] for q in open_q if q.get("readings_count")), "")
    other = next((q["id"] for q in open_q if q["id"] != lettered), "")
    out = ["## How to answer",
           "Write each answer on its own line, starting with the question's id exactly as shown "
           "(one answer per line, Latin letters, a plain colon):",
           "  <question id>: <the letter of the answer you choose>",
           "  <question id>: not needed",
           f"  <question id>: {QR.UNTIL_THE_REPORT}",
           f"(`{QR.UNTIL_THE_REPORT}` keeps the question open without asking it again; the report lists it for you.)",
           "or put your answer in your own words - the factory reads it as you wrote it. "
           "A question you leave unanswered is asked again."]
    out.extend(line for line in [_whole_line(whole)] if line)
    examples = ([f"`{lettered}: a`"] if lettered else []) + ([f"`{other}: not needed`"] if other else [])
    if examples:
        out.append("For example: " + " and ".join(examples) + ".")
    return "\n".join(out) + "\n"


def _reason_in_words(task_root, reason) -> list:
    """The reason the factory stops, in plain words. A closed reason code (`over_threshold`, `blocking`, ...) is
    turned into its words from the data file - a code never reaches a person - and the threshold's
    own numbers follow it, with whose number each one is."""
    text = " ".join(str(reason or "").split())
    if not text:
        return ["the factory needs an answer to the questions below before it can go on."]
    words = defaults()["reason_words"]
    if text not in words:
        return [text]
    lines = [words[text].rstrip(".") + "."]
    if text == "over_threshold":
        found = over_threshold(task_root)
        lines.extend(found["reasons"])
        lines.extend(found["warnings"])
    return lines


BLOCKING_NOTE = ("A question marked as blocking is settled only by a line with its id, or passed with `go on`; "
                 "words alone go to the role, and the question is asked again.")


def batch_text(task_root, reason, card=None, previous_answer_at=None, priced: str = "") -> str:
    """The whole batch for a person: every question the factory asks, as cards.

    Built from the register (`question_register.load`), never from a digest, so a question cannot
    be missing because a role forgot to list it, and there is no cap (the gate's own cut at six
    cards is what this replaces). A question is in it when `question_register.is_open` says so (FR-7, AR-13):
    `open`, `named` (no answer was recorded for it), and a settled or deferred one whose row changed since the
    answer - its card says so. A `with_designer` question and an answer that holds never are. "" when nothing is open.

    `reason`: plain words, or a closed stop-reason code (turned into words). `card(question, index)`
    returns the card's lines; None means `gate_brief.question_card`, loaded now (the cards are `open_cards`'). With
    `previous_answer_at` (any value, blank included) the text is a re-stop after a partial answer:
    only the still-open questions, under the line "still open after your answer of <time>", and it
    says what the answer settled, so it is not the same text again. `priced`: the rendered "what each answer costs and does"
    section, put above the answer block (it arrives rendered: this module reads no price data); with it the block also
    says that `go on` and `stop` alone are read as those words. For the reason `blocking` one line under the block says
    how a blocking question is settled."""
    try:
        view = QR.load(Path(task_root))
    except Exception:
        return ""
    open_q = [q for q in view["questions"] if QR.is_open(q)]
    cards = open_cards(task_root, card) if open_q else []
    if not cards:
        return ""
    settled = sum(1 for q in view["questions"] if QR.settled(q) or (q.get("status") == QR.DEFERRED and not QR.is_open(q)))
    out: list = []
    if previous_answer_at is None:
        out.append("The factory has read the story and written everything it could from it. It stopped before "
                   "going further because it needs your decision on the questions below; it has not guessed "
                   "an answer for any of them.")
    else:
        when = " ".join(str(previous_answer_at).split()) or "earlier"
        out.append(f"still open after your answer of {when}")
        out.append((f"Your answer settled {_times(settled, 'question')}, and they are not asked again. " if settled
                    else "Nothing in your answer settled these questions. ")
                   + "The questions below are still waiting for your decision; the factory has not guessed "
                   "an answer for any of them.")
    reason_lines = _reason_in_words(task_root, reason)
    out.append("")
    out.append("Why it stops: " + reason_lines[0])
    out.extend(reason_lines[1:])
    out.append("")
    out.append(f"{_times(len(open_q), 'question')} to decide - one batch, answer all of it in one go.")
    out.append("")
    out.extend(cards)
    if priced.strip():
        # What each way of answering costs, ABOVE the answer block (human_text.price_problems reads the body only). The driver
        # renders the lines from its price data and hands them in; this module reads no data file for them.
        out.append("")
        out.append(priced.strip())
    out.append("")
    out.append(answer_block(task_root, ("go on", "stop") if priced.strip() else ()).rstrip("\n"))
    if " ".join(str(reason or "").split()) == BLOCKING:
        out.append(BLOCKING_NOTE)
    return "\n".join(out) + "\n"


