#!/usr/bin/env python3
"""The pure half of the one seam "no move" (conductor/1, C1-1; PROJECT.md P22, D-0039).

`story_run.Driver.no_move` is the ONE place the driver calls the conductor and reads its verdict. It turns the
verdict into a move (`continue` / `retry`) or into a closed question with prices. This module holds what needs no
driver, so a test can drive it with plain facts:

  * `MOVE_FACTS` - which of the conductor's `moves` (references/conductor-actions.json) are OPEN, from the facts the
    driver read. The filter is a gate: the allowed error is TOO FEW moves (the person can still answer in words), the
    forbidden error is a move whose precondition is false. A fact that is absent, `None` or unreadable removes every
    move that needs it; a predicate that raises removes its move.
  * `validate_options` - the conductor's `options` are authoritative; a verdict that breaks any rule is not used.
  * `fallback_options` / `render_question` - what code shows when there is no usable conductor answer: the `fallback`
    block, each option followed by the three price lines (references/human-questions.md, item 6).

Nothing here reads a person's words by phrase (FR-12): the only reading is a token, normalized by the caller's
`normalize` (the driver's `s0_normalize`)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402
import person_owned  # noqa: E402  (RN1-9: the one reader of the question classes)
import human_text  # noqa: E402  (the heading of the priced section: one source with the check that reads it)
from controller import ABANDONED, RETURNED, STOPPED  # noqa: E402  (the controller's own status names, never copies)

ACTIONS_FILE = "conductor-actions.json"
QUESTIONS_FILE = "question-prices.json"
VERDICTS_FILE = "delivery-verdict-kinds.json"
# The kinds whose next answer is the S1 review's: `record_review` records ANY words as the review, so a token answer to an
# option would be recorded as one. Until C1-3 gives it an executor it keeps today's behaviour byte for byte. The gates left
# this list in C1-4b: a gate's answer is an approval only as its own word (`Driver.gate_approval`), so a token of an option is
# never recorded as one and `approve` / `rework` / `retry` have executors (`Driver.take_seam_answer`).
EXCLUDED_KINDS = ("s1_review",)
# The words code itself executes (the three standing ones; `approve` and `rework` are executed by the gate road, each as its own
# move row), and the move each one is. A word is valid ONLY for its own move (D5): the
# last-resort question names them when the data file cannot be read, and a test holds them equal to the data.
TOKEN_MOVES = {"retry": "person_does", "go on": "go_on_as_is", "stop": "stop_here"}
# The pseudo-move of an option that offers back a word the ASKED question reads itself (`state["site_doors"]`, C1-3): not a row of
# `moves`, and valid only for a word of the site (`validate_options(site=)`).
SITE_DOOR = "site_door"
# A dispatch the controller still knows as a live one: running, or stopped with a checkpoint, or returned/abandoned
# without being accepted. "Running" is the literal the controller writes (C:338, :527); `superseded` and `stale`
# are not in this set, so every dispatch-tied move is removed for them (F5).
LIVE_STATUSES = frozenset({"running", *STOPPED, RETURNED, ABANDONED})
# A quoted span of the prose in any style: backticks, single or double quotes, the typographic pairs. An OPENING quote is not
# preceded by a word character and a CLOSING one is not followed by one, so the apostrophe of "the scout's" or "can't" never opens
# or closes a span (C1-5d1, t-698 A3).
QUOTED = re.compile(r"(?<!\w)(?:`([^`\n]+)`|'([^'\n]+)'|\"([^\"\n]+)\"|‘([^’\n]+)’|“([^”\n]+)”)(?!\w)")


def data() -> dict:
    """conductor-actions.json (one reader: hooklib), `{}` when it cannot be read."""
    found = hooklib.load_ref_json(ACTIONS_FILE)
    return found if isinstance(found, dict) else {}


def move_rows(spec: dict | None = None) -> dict:
    """`{move id: row}` of the `moves` block."""
    spec = data() if spec is None else spec
    return {str(row.get("id")): row for row in spec.get("moves") or [] if isinstance(row, dict) and row.get("id")}


def move_ids(spec: dict | None = None) -> list:
    return list(move_rows(spec))


# The data columns of a `moves` row that say HOW the move may be offered (t-1936 F2, AR-1: which move takes `args` and which is never
# an option is a data row, not a literal in code). `args`: "rework" (the closed list `check_args` checks) or null (an option for this
# move carries none). `offerable`: false means the move is never a person's choice, and `not_offered` says why.
ARGS_KINDS = ("rework",)
NOT_OFFERED_DEFAULT = "the move is never an option"


def move_columns(row: dict, strict: bool = True) -> tuple:
    """`(args, offerable, not_offered)` of one row of `moves`. BOTH worlds (E2.1): a missing `args` column reads `rework` for the row
    `rework_stage` and `None` for any other; a missing `offerable` reads true unless the row's token is `—` (today's rule). A value
    outside the columns' vocabulary (E2.2) is `DataUnreadable` naming the row - `strict=False` (the prompt's moves section, which must
    never fail to render) reads it on the safe side: no `args`, not offerable."""
    name = str(row.get("id"))
    args = row["args"] if "args" in row else ("rework" if name == "rework_stage" else None)
    if args is not None and not (isinstance(args, str) and args in ARGS_KINDS):
        if strict:
            raise DataUnreadable(f"moves.{name}.args: `{args}` is neither \"rework\" nor null")
        args = None
    offerable = row["offerable"] if "offerable" in row else str(row.get("token") or "") != "—"
    if not isinstance(offerable, bool):
        if strict:
            raise DataUnreadable(f"moves.{name}.offerable: `{offerable}` is not true or false")
        offerable = False
    why = row.get("not_offered")
    return args, offerable, ("" if offerable else (why.strip() if isinstance(why, str) and why.strip() else NOT_OFFERED_DEFAULT))


# --- which moves are open (F2) -------------------------------------------------------------------------------------
def rework_blockers(facts: dict) -> list:
    """The facts, in the order of `rework_stages`, `running`, `closed`, `attempts`, that keep a rework closed - an unread (`None`) fact
    among them: the ONE derivation of `_rework` (a rework is open when this list is empty) and of the sentence that says why it is not
    (`rework_closed_reason`)."""
    blocked = []
    if not facts.get("rework_stages"):
        blocked.append("rework_stages")
    if facts.get("running") is not False:
        blocked.append("running")
    if facts.get("closed") is not False:
        blocked.append("closed")
    if facts.get("attempts") != 0:
        blocked.append("attempts")
    return blocked


# Why a rework is closed, in the story's words (C2-7 §5.1): data of the code, keyed by the fact (the MOVE_FACTS precedent).
REWORK_CLOSED = {"rework_stages": "no stage before this gate has accepted work to send back",
                 "running": "a step of the story is still running",
                 "closed": "the story is closed",
                 "attempts": "a delivery attempt is already recorded"}
REWORK_UNREAD = "the factory could not read where the story stands"          # a fact that is not known is never told as a reason (FR-41)


def rework_closed_reason(facts: dict) -> str:
    """The words for the first fact that is KNOWN to keep a rework closed; when every blocker is a fact that could not be read, the
    sentence that says so - never a reason nobody established (FR-41, FR-59)."""
    known = {"rework_stages": facts.get("rework_stages") == [], "running": facts.get("running") is True, "closed": facts.get("closed") is True,
             "attempts": isinstance(facts.get("attempts"), int) and facts["attempts"] > 0}
    return next((REWORK_CLOSED[key] for key in rework_blockers(facts) if known[key]), REWORK_UNREAD)


def _rework(facts: dict) -> bool:
    return not rework_blockers(facts)


def _dispatch_live(facts: dict) -> bool:
    return facts.get("dispatch_status") in LIVE_STATUSES


def _resume(facts: dict) -> bool:
    return _dispatch_live(facts) and facts.get("session") is True


def _restart(facts: dict) -> bool:
    return _dispatch_live(facts) and facts.get("attempts") == 0


def _always(facts: dict) -> bool:
    return True


# Keyed by the move ids of conductor-actions.json (a test holds the two key sets equal); the table is code on purpose
# (FR-13, the GATE_REPAIRS precedent): a state precondition is a controller call, which no data file can carry. A move
# with no row here is REMOVED. `go_on_as_is` and `story_fact` have no state precondition in code: which block a person's
# word passes is the conductor's judgement. The run's standing decision (`no_trace`) removes none of them: no move here
# writes outward (FR-36).
def _approve_gate(facts: dict) -> bool:
    """`approve_gate`: at gate A or gate B only, and only while that gate has no current approved decision. A decision that
    cannot be read (`None`) removes the move: the safe direction is not offering an approval (FR-59)."""
    return facts.get("gate") in ("A", "B") and facts.get("gate_decided") is False


MOVE_FACTS = {
    "rework_stage": _rework,
    "approve_gate": _approve_gate,
    "resume_with_words": _resume,
    "release_and_restart": _restart,
    "go_on_as_is": lambda facts: facts.get("gate") == "",     # at a gate the one pass is `approve`: two moves never pass one gate
    "story_fact": _always,
    "stand_prepare": lambda facts: facts.get("stand_authorized") is True,
    "revoke_exclusion": lambda facts: facts.get("live_exclusions") is True,
    "person_does": _always,
    "stop_here": _always,
}


def open_moves(facts: dict, moves) -> list:
    """The ids of `moves` whose state precondition holds in `facts` (order kept, duplicates dropped)."""
    out = []
    for move in moves or []:
        check = MOVE_FACTS.get(str(move))
        if check is None or move in out:
            continue
        try:
            if check(facts if isinstance(facts, dict) else {}):
                out.append(move)
        except Exception:
            continue                      # a reader that raises removes the move (the safe direction)
    return out


CASES_IN_LIST = 60              # the ceiling of the case ids `rework_args_list` prints; the check always reads the whole scope
ARGS_KEYS = ("stage", "role", "cases", "rows", "cause")


class ArgsRefused(Exception):
    """The `args` of a `rework_stage` option break a rule of `rework_args_list` while the rest of the verdict is usable (C2-6 §4.2):
    the conductor is told the rule and the list once; the person is never asked about `args`."""

    def __init__(self, rule: str):
        super().__init__(rule)
        self.rule = rule


class ClassRefused(ArgsRefused):
    """A question to a person carries no class of the question classes (`person_owned.py`) or no `checked` (RN1-9, P22, FR-48). A subclass of
    `ArgsRefused` on purpose: `Driver._verdict_rule` already gives `again=True` for it, so the conductor is told once."""


def rework_args_list(facts: dict) -> str:
    """THE one rendering of the closed list of values an option's `args` may carry (t-722 §4.2 p.2): the moves section of the
    prompt and the refusal of bad `args` both print it. A fact that was not read prints as such, never as an empty list."""
    roles, scope, causes = facts.get("rework_roles"), facts.get("scope"), facts.get("causes")
    stages = facts.get("rework_stages") or []
    pairs = ("; ".join(f"{s} → " + " | ".join(dict.fromkeys(roles.get(s) or ["(no role read)"])) for s in stages)
             if isinstance(roles, dict) else "(not read)")
    if isinstance(scope, list):
        shown = ", ".join(scope[:CASES_IN_LIST]) + (f", … (+{len(scope) - CASES_IN_LIST} more: state/controller.json \"scope\")"
                                                    if len(scope) > CASES_IN_LIST else "")
    else:
        shown = "(not read)"
    return "\n".join([
        "- `rework_stage` — token `rework`; its option carries \"args\" from these values only:",
        f"  stage → role: {pairs}",
        f"  cases (S4 and later; one at least): the approved scope — {shown}",
        "  rows (S1-S3, instead of cases, or neither): ids of the plan's rows",
        "  cause: " + (" | ".join(causes) if isinstance(causes, (list, tuple)) else "(not read)")])


def check_args(args, facts: dict) -> tuple:
    """`(normalised args, "")` when `args` obeys the closed list, else `(None, <the rule it breaks>)` (t-722 §4.2 p.3). A fact that
    was not read (`None`) breaks the rule: no value is guessed (FR-59). `rows` are not judged here, the controller judges them."""
    if not isinstance(args, dict):
        return None, "the `rework` option carries no \"args\" object"
    roles, scope, causes = facts.get("rework_roles"), facts.get("scope"), facts.get("causes")
    if not (isinstance(roles, dict) and isinstance(scope, list) and isinstance(causes, (list, tuple))
            and isinstance(facts.get("rework_stages"), list)):
        return None, "what a rework may name could not be read, so its \"args\" cannot be checked"
    clean = lambda key: [str(v).strip() for v in (args.get(key) or []) if str(v).strip()] if isinstance(args.get(key) or [], list) else None
    stage, role, cause = (str(args.get(k) or "").strip() for k in ("stage", "role", "cause"))
    cases, rows = clean("cases"), clean("rows")
    if cases is None or rows is None:
        return None, "\"args\" cases / rows are not lists of ids"
    if stage not in facts["rework_stages"]:
        return None, f"\"args\" stage `{stage or 'none'}` is not a stage that can be sent back"
    if role not in (roles.get(stage) or []):
        return None, f"\"args\" role `{role or 'none'}` did no accepted work at {stage}"
    if cases and rows:
        return None, "\"args\" names cases and rows together; one of them only"
    if set(cases) - set(scope):
        return None, "\"args\" names a case outside the approved scope: " + ", ".join(sorted(set(cases) - set(scope)))
    if not cases and int(stage[1:]) >= 4:
        return None, f"\"args\" names no case, and {stage} needs at least one of the approved scope"
    if cause not in causes:
        return None, f"\"args\" cause `{cause or 'none'}` is not one of the causes listed"
    return {"stage": stage, "role": role, **({"cases": cases} if cases else {}), **({"rows": rows} if rows else {}), "cause": cause}, ""


def moves_section(spec: dict, open_ids: list, facts: dict, site=()) -> str:
    """The section of the conductor's prompt that says which rows of `moves` are open now. `site`: the answers the question
    ALREADY takes that are not a move's own token (a stand's name, `read`, `new text` ...): "## Answers this question already
    takes" lists them, and an option for one carries `move: site_door` (C1-3: the conductor may offer a closed question's own
    words back, never invent a word the site does not read)."""
    rows = move_rows(spec)
    lines = ["## Moves open here", "",
             "Code checked the state precondition of each row of `moves` in references/conductor-actions.json. Only these "
             "may be offered or taken now; the rest of each precondition is yours to judge:"]
    for move in open_ids:
        row = rows.get(move) or {}
        token = str(row.get("token") or "")
        args, offerable, _why = move_columns(row, strict=False)      # F2: the columns say which move takes "args" and which is never an option
        if not offerable:
            lines.append(f"- `{move}` — " + ("yours to run, never an option" if row.get("word") == "own"
                                              else "run on the person's own words, never an option"))
            continue
        if args == "rework":
            lines.append(rework_args_list(facts))        # C2-6: the row carries the closed list of the option's "args"
            continue
        lines.append(f"- `{move}`" + (f" — token `{token}`" if token and token != "—" else "") + "; option carries no \"args\"")
    if not open_ids:
        lines.append("- none")
    if site:
        lines += ["", "## Answers this question already takes", "",
                  "The question reads these words itself. Offer one of them back as an option with `move: site_door` and that token; "
                  "offer no other word of the question's own, and never one of them as another move:"]
        lines += [f"- `{token}`" for token in site]
    return "\n".join(lines)


# --- the conductor's options are authoritative (C1-2 C8) ---------------------------------------------------------------
def delivery_text(spec: dict, words: dict, delivery: str):
    """The `the story:` words of a `delivery` value: a non-verdict class of `price_classes.delivery`, or the head of a `words`
    key of delivery-verdict-kinds.json; None when it is neither. ONE resolution for the conductor's options, the fallback and
    the priced questions of the driver (the price-row helper)."""
    classes = (spec.get("price_classes") or {}).get("delivery") or {}
    if delivery in classes:
        return str(classes[delivery])
    if delivery in words:
        return "the delivery verdict will read: " + str((words[delivery] or {}).get("head") or delivery).removeprefix("Verdict:").strip()
    return None


def story_line(story, spec: dict, words: dict) -> str:
    """The `the story:` line of one option from the dict `{unverified, report, delivery}` ('' when it is not that dict)."""
    if not isinstance(story, dict):
        return ""
    delivery = str(story.get("delivery") or "").strip()
    delivery = delivery_text(spec, words, delivery) or delivery
    parts = [str(story.get(key) or "").strip() for key in ("unverified", "report")] + [delivery]
    return "; ".join(part for part in parts if part and part.lower() != "none")


def reserved_tokens(spec: dict, normalize) -> frozenset:
    """Every word a MOVE owns: the token of each row of `moves` (all of them, open or not) and of each `fallback` row, normalized
    (`stop` always). A site's own door may never be one of these (G7): the word would have two readings, and code does not guess
    which one the person meant (FR-12, FR-13)."""
    own = [str(row.get("token") or "") for row in move_rows(spec).values()] + list(TOKEN_MOVES)
    own += [str(token) for token in (spec.get("fallback") or {})]
    return frozenset(normalize(token) for token in own if token and token != "—")


def site_check(site, spec: dict, normalize) -> list:
    """The site's doors, normalized; `DataUnreadable` naming the door when one of them is a move's own word (a stand named `retry`,
    `go on`, `stop`, `restart` ...). The caller answers with the priced fallback and a finding that names the door."""
    doors = [normalize(str(token)) for token in site or ()]
    taken = reserved_tokens(spec, normalize)
    for token in doors:
        if token in taken:
            raise DataUnreadable(f"the door `{token}` of the question is also the word of a move of the factory, so one word "
                                 "would have two readings")
    return doors


def named_tokens(question: str, normalize) -> frozenset:
    """The quoted spans of the prose in any style (`QUOTED`), each normalized; a span named twice counts once. A span whose content
    is no token of the vocabulary (a file name, a stage) is in the set too: the caller keeps only the vocabulary (FR-12: tokens
    are compared, words are never read)."""
    return frozenset(normalize("".join(groups)) for groups in QUOTED.findall(question))


def prose_refusal(question: str, seen, spec: dict, normalize, site=()) -> str:
    """`""` when the prose `question` may be shown with options whose normalized tokens are `seen`, else the rule it breaks. The prose
    is refused when it is empty (as before) or names a token of the closed vocabulary - a move's own word (`reserved_tokens`
    covers every row of `moves`) or a door of the site - that is NOT among the options: a word no executor reads in this question
    is never shown to the person (FR-10). A prose that names fewer tokens than the options is shown as it is: `render_options`
    lists every token."""
    if not question.strip():
        return "the question is empty"
    extra = sorted((named_tokens(question, normalize) & (reserved_tokens(spec, normalize) | set(site))) - set(seen))
    if not extra:
        return ""
    names = ", ".join(f"`{token}`" for token in extra)
    return f"the question names {names}, which {'is' if len(extra) == 1 else 'are'} not one of its options"


CONDUCTOR_FOUND = "What the conductor found:"
CONDUCTOR_TEXT_LIMIT = 1200         # the `lead` limit of a person's text; a longer conductor text is cut and ends with the mark below
CONDUCTOR_CUT_MARK = "…"
UNOFFERED_GENERIC = "the conductor's own options for this question could not be used, so only the answers below are read"
UNOFFERED_CLOSED = "the factory cannot offer that move in the story's present state"


def unoffered_reason(token: str, spec: dict, normalize, facts) -> str:
    """The plain words for a vocabulary token the conductor's text quotes that the shown answers do not carry (E2.7): when the token
    belongs to a move whose state precondition does NOT hold in `facts`, that fact (a `rework` closed by the story's state says which);
    otherwise - the move is open, or the facts could not be read (FR-41: an unknown is never told as a reason) - that the conductor's
    own options could not be used."""
    move = next((mid for mid, row in move_rows(spec).items() if normalize(str(row.get("token") or "")) == token), "")
    if not move or not isinstance(facts, dict) or not facts or open_moves(facts, [move]):
        return UNOFFERED_GENERIC
    return ("sending a stage back is not open now: " + rework_closed_reason(facts)) if move == "rework_stage" else UNOFFERED_CLOSED


def conductor_found(text: str, offered, spec: dict, normalize, facts=None, site=()) -> tuple:
    """`(block, token_lines)` for a conductor `question` whose options were refused (t-1936 F2.2 (a), FR-9, AR-17): `block` is the fixed
    line `What the conductor found:` and the conductor's text VERBATIM, cut at `CONDUCTOR_TEXT_LIMIT` characters (the cut ends with the
    mark); `token_lines` is one code line per token of the closed vocabulary (a move's word, a door of the site) the WHOLE text quotes
    that is not among the `offered` normalized tokens: `` `<token>` is not offered here: <why> `` (FR-10); `offered` None (not known yet) gives
    no line. An empty text gives `("", [])` (today's behaviour). Tokens are compared, words are never read (FR-12)."""
    text = str(text or "").strip()
    if not text:
        return "", []
    shown = text if len(text) <= CONDUCTOR_TEXT_LIMIT else text[:CONDUCTOR_TEXT_LIMIT - len(CONDUCTOR_CUT_MARK)] + CONDUCTOR_CUT_MARK
    site = [normalize(str(door)) for door in site or ()]
    if offered is None:             # the answers shown are not known yet (a closed question of a site, the floor): no line is claimed (FR-41)
        return CONDUCTOR_FOUND + "\n" + shown, []
    extra = sorted((named_tokens(text, normalize) & (reserved_tokens(spec, normalize) | set(site))) - set(offered))
    return CONDUCTOR_FOUND + "\n" + shown, [f"`{token}` is not offered here: {unoffered_reason(token, spec, normalize, facts)}" for token in extra]


def conductor_lead(lead: str, text: str, offered, spec: dict, normalize, facts=None, site=()) -> str:
    """`lead` followed by the conductor's block (`conductor_found`) and its token lines, one paragraph; `lead` unchanged for an empty text."""
    block, lines = conductor_found(text, offered, spec, normalize, facts, site)
    if not block:
        return lead
    return "\n\n".join(part for part in (str(lead).rstrip(), "\n".join([block, *lines])) if part)


def validate_options(verdict: dict, open_ids: list, spec: dict, normalize, words: dict, site=(), facts=None, chosen=False, chosen_move="") -> tuple:
    """`(options, "")` when the verdict's options may be used, else `(None, <the rule it breaks>)`.

    t-1936 F2: the columns of the `moves` rows decide. A move whose `offerable` is false (`resume_with_words`, `story_fact`, `revoke_exclusion`)
    is refused with the row's `not_offered` text; an option with `args` on a move whose `args` column is null LOSES the key, stays an option
    and carries `args_dropped: True`; a bad column value raises `DataUnreadable` naming the row (the caller treats it as an unusable answer).

    Valid only when ALL hold: the action is `ask_person` or `stop`; a list of at least 2 dicts; every token non-empty and
    not "—"; the normalized tokens unique; every `move` is open; each token is its move's own token in conductor-actions.json
    (so a standing word is valid only for its own move, D5); the prose `question` is not empty and names, in any quote style, no
    token of the closed vocabulary that is not an option (`prose_refusal`); every option says what it does, and what it costs the factory and the person, and has the `story` dict.
    C2-6: the `rework` option (move `rework_stage`) carries "args" - `check_args` against `facts` (the driver's `no_move_facts`); a bad
    one raises `ArgsRefused` once the rest of the verdict is valid. `chosen` (a bool: this is a call for the person's choice) and `chosen_move` (that choice's move id): see the lone-option rule below.
    RN1-9: a question (`ask_person` or `stop`, not the lone chosen-rework option) also needs `why_person` (a question class of `person_owned.py`) and a
    non-empty `checked`, else `ClassRefused` (an `ArgsRefused`; a bad `args` too is carried in the same refusal). `site` (C1-3): the normalized answers the asked question reads itself. An option whose `move` is `site_door` is valid only when
    its token is one of them and is no move's own word (`reserved_tokens`): a closed question's words are offered back as they are,
    never a word it does not read, and never a word that would have two readings."""
    if verdict.get("action") not in ("ask_person", "stop"):
        return None, f"the action `{verdict.get('action')}` carries no question"
    options = verdict.get("options")
    # C2-6 (§L-5): at a call for the person's CHOICE (`chosen`) one option is a DECISION, not a question - the `rework` option with
    # "args" - and legal only when the person chose `rework` (§L-6 (b)): `chosen` is True and `chosen_move` is `rework_stage`.
    lone = bool(chosen) and verdict.get("action") == "ask_person"
    if not isinstance(options, list) or len(options) < (1 if lone else 2) or not all(isinstance(o, dict) for o in options):
        return None, "options: fewer than two, or not a list of objects"
    if len(options) == 1 and (str(options[0].get("move")) != "rework_stage" or chosen_move != "rework_stage"):
        return None, "one option is legal only as the `rework` option when the person chose `rework`; otherwise at least two are needed"
    rows, seen, out, args_rule = move_rows(spec), set(), [], ""
    for option in options:
        shown = str(option.get("token") or "").strip()
        token = normalize(shown)
        if not token or token == "—":
            return None, "an option has no token"
        if token in seen:
            return None, f"two options carry the token `{token}`"
        seen.add(token)
        move, args_kind = str(option.get("move") or ""), None       # a site door has no row: it takes no "args" either
        if move == SITE_DOOR:
            if token not in site or token in reserved_tokens(spec, normalize):
                return None, f"the option `{token}` names a door the question does not read, or one that is a move's own word"
        elif move not in open_ids or move not in rows:
            return None, f"the option `{token}` names the move `{move}`, which is not open here"
        else:
            args_kind, offerable, not_offered = move_columns(rows[move])          # F2: `DataUnreadable` naming the row on a bad column
            if not offerable:
                return None, f"the option `{token}` names the move `{move}`, which is never an option: {not_offered}"
            if not (own := normalize(str(rows[move].get("token") or ""))) or own == "—" or own != token:
                return None, f"the token `{token}` is not the token of the move `{move}`"
        says, factory, person = (str(option.get(key) or "").strip() for key in ("says", "factory", "person"))
        story = story_line(option.get("story"), spec, words)
        if not (says and factory and person and story):
            return None, f"the option `{token}` lacks its says / factory / person / story lines (story is a dict)"
        row = {"token": shown, "norm": token, "move": move, "says": says, "factory": factory, "person": person, "story": story}
        if args_kind == "rework":
            args, why = check_args(option.get("args"), facts or {})
            args_rule = args_rule or why
            if args:
                row["args"] = args
        elif "args" in option:
            row["args_dropped"] = True       # F2 (Fork 3-B): the key goes, the option stays; nothing else about the option is relaxed (E2.3)
        out.append(row)
    rule = prose_refusal(str(verdict.get("question") or ""), seen, spec, normalize, site)
    if rule:
        return None, rule
    # RN1-9: a QUESTION (not the lone chosen-rework decision, E-7) names a class and what was read. LAST on purpose: every malformed
    # verdict keeps its own refusal first (E-9); an unreadable class file gives "" (FR-59, E-3).
    class_rule = "" if (lone and len(options) == 1) else person_owned.question_rule(verdict.get("why_person"), verdict.get("checked"))
    if args_rule and class_rule:
        raise ClassRefused(args_rule + "; " + class_rule)
    if class_rule:
        raise ClassRefused(class_rule)
    if args_rule:
        raise ArgsRefused(args_rule)           # the rest of the verdict is usable: the conductor is told once (§4.2 p.4)
    return out, ""


# --- a stage closed by code with no role: the options of the question (conductor/2 C2-8, t-745) -----------------------------
# The CANDIDATE tokens of each `code_close.*` question, in the order they are shown (FR-13: closed variety is data here, the prices are
# the rows of question-prices.json). `code_close_offer` narrows them by the facts. `full retro` is the door of the SITE (the retro
# analyst does the retro after all); it is no move's word (`site_check` holds it apart from `reserved_tokens`). C2-3s adds the
# `code_close.role_open` row and its executors; this module only keeps the table.
CODE_CLOSE_OFFERS = {
    "code_close.stage": ("retry", "stop"),
    "code_close.factory_file": ("retry", "stop"),
    "code_close.closed_story": ("full retro", "go on", "retry", "stop"),
}
# The two blocks of an S9 record the factory can name from the STATE (never from a refusal's words, FR-12): the facts of `code_close`.
BLOCK_RUNNING = "still running"
BLOCK_NO_STAGE = "no accepted controller stage"
GO_ON_NOT_HERE = {"stage": "no word of yours passes what refused.", "factory_file": "the step would stay undone."}
GO_ON_PASSED = "your word for it is already recorded and this still refuses"
GO_ON_REFUSED = "your word could not be recorded against it"
GO_ON_UNKNOWN = "the factory could not establish what refused, so no word of yours can pass it"
RETRY_CANNOT = ("Trying again changes nothing here: this step is recorded only after the retro analyst's work or on your word.")
RETRO_CANNOT = {BLOCK_RUNNING: "Asking the retro analyst to do the retro would not help here: the other step marked as in progress "
                               "stays marked.",
                "": "Asking the retro analyst to do the retro is not offered here: the factory could not establish that it would help."}


def code_close_offer(key: str, facts: dict) -> tuple:
    """`(tokens, absent_lines)` of the question `key` (FR-42, human-questions.md item 6): the tokens offered, in the table's order, and
    one sentence for each option the question does NOT offer that a person might expect. `facts`: `block` (the waivable block the factory
    established from the state: `BLOCK_RUNNING`, `BLOCK_NO_STAGE` or `""`), `passed` / `refused` (the blocks the person's word already
    passed, or whose pass the writer refused), `idle_cap` (the deferred record was tried twice; changes the lead only).

    ERROR DIRECTION: too few options is the safe error; `go on` is offered only for a non-empty block that is in neither `passed` nor
    `refused` (FR-59: an unknown block gives no pass); `stop` is always offered, and `retry` joins it when the rules left it alone (one
    option is no question). `DataUnreadable` for a key the table does not hold.

    `code_close.behind` (B-20, AR-25: the close is refused because an EARLIER stage is not closed): the offer is decided by one fact,
    `awaits` (the earlier stage stands finished and waits for its consumer role's acceptance, which a word of the person can give).
    `go on` is offered exactly then; `retry` and `stop` always. The key is not a row of `CODE_CLOSE_OFFERS`: the S9 generic walk of
    that table (every key under every block) does not apply to it, its only fact is `awaits`."""
    facts = facts if isinstance(facts, dict) else {}
    if key == "code_close.behind":
        if facts.get("awaits"):
            return ["go on", "retry", "stop"], []
        return ["retry", "stop"], ["Going on as it is is not possible here: the earlier stage is not waiting for an acceptance that a word of "
                                   "yours could give."]
    if key not in CODE_CLOSE_OFFERS:
        raise DataUnreadable(f"CODE_CLOSE_OFFERS: no row for `{key}`")
    block = str(facts.get("block") or "")
    spent = [str(b) for b in list(facts.get("passed") or []) + list(facts.get("refused") or [])]
    tokens, absent = list(CODE_CLOSE_OFFERS[key]), []
    if key != "code_close.closed_story":
        absent.append("Going on as it is is not possible here: " + GO_ON_NOT_HERE["stage" if key == "code_close.stage" else "factory_file"])
        return tokens, absent
    if block == BLOCK_NO_STAGE:
        tokens.remove("retry")
        absent.append(RETRY_CANNOT)
    else:
        tokens.remove("full retro")
        absent.append(RETRO_CANNOT.get(block, RETRO_CANNOT[""]))
    if not block or block in spent:
        tokens.remove("go on")
        why = (GO_ON_UNKNOWN if not block else GO_ON_PASSED if block in [str(b) for b in facts.get("passed") or []] else GO_ON_REFUSED)
        absent.append(f"Going on as it is is not possible here: {why}.")
    if len(tokens) < 2:
        tokens.insert(0, "retry")
    return tokens, absent


# --- the fallback and the rendering ------------------------------------------------------------------------------------
class DataUnreadable(Exception):
    """The `fallback` or `price_classes` block of conductor-actions.json cannot be used: the caller renders the last resort."""


def _class_text(spec: dict, family: str, key: str, **slots) -> str:
    text = ((spec.get("price_classes") or {}).get(family) or {}).get(key)
    if not isinstance(text, str) or not text.strip():
        raise DataUnreadable(f"price_classes.{family}.{key}")
    try:
        return text.format_map({"role": "the role", "stages": "the stages", "what": "what is in the way, named above", **slots})
    except (KeyError, ValueError, IndexError):
        raise DataUnreadable(f"price_classes.{family}.{key}") from None


def fallback_options(spec: dict, words: dict, normalize, keep=None) -> list:
    """The standing options code shows when there is no conductor answer, from the `fallback` block (each row: says, factory,
    person, delivery class). `keep`: the tokens to show, in the block's order (default all). `DataUnreadable` when the block or a
    class it names is missing."""
    block = spec.get("fallback")
    if not isinstance(block, dict) or not block:
        raise DataUnreadable("fallback")
    out = []
    for token, row in block.items():
        if keep is not None and token not in keep:
            continue
        if token not in TOKEN_MOVES or not isinstance(row, dict) or not str(row.get("says") or "").strip():
            raise DataUnreadable(f"fallback.{token}")
        priced = price_row(spec, words, row, f"fallback.{token}")
        out.append({"token": token, "norm": normalize(token), "move": TOKEN_MOVES[token], "says": str(row["says"]).strip(),
                    **priced})
    if len(out) < 2:
        raise DataUnreadable("fallback: fewer than two options")
    return out


def price_row(spec: dict, words: dict, row: dict, where: str, **slots) -> dict:
    """`{factory, person, story}` - the three price lines of ONE row `{factory, person, delivery[, unverified]}`, each a key
    of `price_classes` (the slots `{role}`, `{what}`, `{stages}` filled from `slots`). THE one resolution of a price row: the
    fallback block and the priced questions (references/question-prices.json) both read it. `where` names the row for the
    reason of a `DataUnreadable` (a class or a delivery value that does not resolve)."""
    delivery = delivery_text(spec, words, str(row.get("delivery") or ""))
    if delivery is None:
        raise DataUnreadable(f"{where}.delivery")
    unverified = str(row.get("unverified") or "").strip()
    return {"factory": _class_text(spec, "factory", str(row.get("factory") or ""), **slots),
            "person": _class_text(spec, "person", str(row.get("person") or ""), **slots),
            "story": "; ".join(part for part in (unverified, delivery) if part)}


def load_question_prices() -> dict:
    """`{key: [row, ...]}` from references/question-prices.json - ONE loader (utf-8-sig, hooklib's reader), ONE top-level key
    `questions` that holds the priced options of every closed question, keyed by the site that raises it (`s1.gap`, `halt`,
    `fresh.ticket_changed`, `gate_A` ...). A row is `{answer, factory, person, delivery[, unverified]}`; `answer` is the
    option's id (its token, or a fixed id for an option with no token). `DataUnreadable` on ANY shape error: the file is absent
    or not JSON, the top level holds more or less than `questions`, a key holds no rows, a row lacks a text, two rows of one
    key share an `answer`. Whether a class or a delivery value resolves is `price_row`'s question, at render time."""
    found = hooklib.read_json(hooklib.ref(QUESTIONS_FILE), None)
    if not isinstance(found, dict) or set(found) != {"questions"} or not isinstance(found["questions"], dict):
        raise DataUnreadable(f"{QUESTIONS_FILE}: it is absent, not JSON, or its one top-level key is not `questions`")
    for key, rows in found["questions"].items():
        if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
            raise DataUnreadable(f"{QUESTIONS_FILE}: `{key}` holds no list of rows")
        for row in rows:
            if not all(isinstance(row.get(name), str) and row[name].strip() for name in ("answer", "factory", "person", "delivery")):
                raise DataUnreadable(f"{QUESTIONS_FILE}: a row of `{key}` lacks its answer / factory / person / delivery")
            if "unverified" in row and not isinstance(row["unverified"], str):
                raise DataUnreadable(f"{QUESTIONS_FILE}: a row of `{key}` has an `unverified` that is not text")
        if len({row["answer"] for row in rows}) != len(rows):
            raise DataUnreadable(f"{QUESTIONS_FILE}: `{key}` names one answer twice")
    return found["questions"]


def priced_options(key: str, options: list, spec: dict, words: dict, prices: dict | None = None) -> list:
    """The options of a closed question with their price lines. `options`: `[{answer, token|None, says[, slots]}]` from the
    site (the words stay in code: they carry names and paths); the prices come from the data row whose `answer` is the option's.
    Each result: `{token|None, says, factory, person, story}` (`token` is kept as the site wrote it, not normalized: the site's
    tokens are the factory's own fixed words, and the price check compares them case-insensitively). `DataUnreadable` when the
    key or a row is missing."""
    prices = load_question_prices() if prices is None else prices
    rows = {row["answer"]: row for row in prices.get(key) or []}
    if not rows:
        raise DataUnreadable(f"{QUESTIONS_FILE}: no rows for `{key}`")
    out = []
    for option in options:
        answer = str(option.get("answer") or "")
        if answer not in rows:
            raise DataUnreadable(f"{QUESTIONS_FILE}: `{key}` has no row for the answer `{answer}`")
        token = str(option.get("token") or "") or None
        out.append({"token": token, "says": str(option.get("says") or "").strip(),
                    **price_row(spec, words, rows[answer], f"{key}.{answer}", **(option.get("slots") or {}))})
    return out


def render_options(options: list, labels: list) -> str:
    """"## What each answer costs and does": per option `(a) \\`token\\` — says` (`(a) says` for an option with no token) and the
    three labelled lines (`labels` empty: the option lines alone - a question whose price data cannot be read still lists them)."""
    lines = [human_text.PRICED_HEADING, ""]
    for number, option in enumerate(options):
        mark = f"({chr(ord('a') + number)})"
        lines.append(f"{mark} `{option['token']}` — {option['says']}" if option.get("token") else f"{mark} {option['says']}")
        for label, key in zip(labels, ("factory", "person", "story")):
            lines.append(f"{label} {option[key]}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_question(lead: str, options: list, labels: list) -> str:
    """The lead, then the priced options (`render_options`)."""
    return str(lead).rstrip() + "\n\n" + render_options(options, labels)
