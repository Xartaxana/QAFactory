"""A stand gap as a card the person answers, not a reason code they have to decode.

TP1-15045 (22.09.2026): the manifest said `blocked_by_env` and one prose sentence, while
the role that wrote it had already found the file, the lines and the value to change
(`customer-config.yaml:304-311`, `features:subWorkflow enabled: false`). The person read a
status word; the one line that would have unblocked the partition never reached them. And
there was nothing they could answer except "accepted" — no way to say "run it where it works",
and no way to say "change it, I am telling you to".

One card per gap, the same shape at gate A (a case precondition this stand does not meet) and
at gate B (a manifest `unresolved[]` row, or a run report's `env_blocked`): the requirement and
the case it costs, what the test tries to do, what is missing, the exact change, and four
answers — `apply` (the factory makes the change on the person's word), `theirs`, `handed`,
`accept`. A gap the person has already answered shows the answer instead of the options, so a
decision is never asked for twice.

A credential is NAMED, never printed: a `credential` remedy carries the variable name and the
file it belongs in, and every line rendered here passes a scrubber first.

  stand_gaps.py --task TP1-15045 --gate A
  stand_gaps.py --task TP1-15045 --gate B --json
"""
import argparse
import functools
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract as C  # noqa: E402
import hooklib  # noqa: E402  (`read_json`, the one JSON reader)
from hooklib import sorted_paths  # noqa: E402

# Gate A asks before S5, gate B before S9: the stage a person's answer is recorded against, and the stage the gate's rehearsal
# asks "can it start" about. The ONE table: `gate_preflight` imports it from here (it already depends on this module, never the
# other way at load time, so no import cycle); B-309 (e) folded its private copy.
GATE_STAGE = {"A": "S5", "B": "S9"}
# The reasons of an `unresolved[]` row that describe the STAND, not the test or the ticket.
STAND_REASONS = ("blocked_by_env", C.HANDED_TO_PERSON)
# A `NAME=value` pair that reached a detail written by a role never leaves this module whole.
# `s5_precheck` refuses such a row on write; this is the second door, because a story in flight may
# still carry one written by an older build.
_ASSIGNED_VALUE_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\s*=\s*(?!<)(\S+)")
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_REQ_RE = re.compile(r"\bR-\d+[A-Za-z0-9-]*\b")
_HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)\s*$", re.MULTILINE)


def names_only(text) -> str:
    """The same sentence with every `NAME=value` pair reduced to the name."""
    return _ASSIGNED_VALUE_RE.sub(lambda m: f"{m.group(1)}=<value not printed>",
                                  " ".join(str(text or "").split()))


# The package's one JSON reader. This module's direction: whatever goes wrong while reading (absent, unreadable, not JSON, a
# path that is not a path) is `default`, None unless the caller passes its own.
_read_json = functools.partial(hooklib.read_json, errors=Exception)


def _case_texts(task_root: Path) -> dict:
    """{case id: text} for this story's cases, read once per call."""
    out = {}
    try:
        files = C.case_files(task_root)
    except Exception:
        files = C.case_glob(Path(task_root) / "work" / "test-cases", task_root)
    for path in files:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = re.search(r"^id:\s*(\S+)", text, re.MULTILINE)
        out[(found.group(1) if found else Path(path).stem).strip()] = text
    return out


def _front_matter(text: str) -> dict:
    front = _FRONT_MATTER_RE.match(text or "")
    if not front:
        return {}
    out = {}
    for line in front.group(1).splitlines():
        key, _, value = line.partition(":")
        if key and not key.startswith((" ", "\t")):
            out[key.strip()] = value.strip().strip("'\"")
    return out


def what_the_test_does(text: str) -> str:
    """One sentence of what this case tries to do — its title, else its first When step.

    Never invented: a case whose body code cannot read says so, because a card that guesses
    what the test does is worse than a card that admits it did not find it."""
    front = _front_matter(text)
    body = (text or "").split("\n---", 1)[-1]
    title = str(front.get("title") or "").strip()
    if not title:
        heading = _HEADING_RE.search(body)
        candidate = heading.group(1).strip() if heading else ""
        title = candidate if candidate and not candidate.lower().startswith(
            ("given", "when", "then", "preconditions")) else ""
    if title:
        return " ".join(title.split())[:160]
    when = re.search(r"^#{1,3}\s+When\b(.*?)(?=^#{1,3}\s|\Z)", body, re.DOTALL | re.MULTILINE)
    if when:
        for line in when.group(1).splitlines():
            step = re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", line).strip()
            if step:
                return " ".join(step.split())[:160]
    return "the case file records no title and no When step - open it"


def requirement_of(task_root: Path, case_id: str, text: str) -> str:
    """`R-3` — from the case's own front matter, else from the plan row it names."""
    front = _front_matter(text)
    for key in ("requirements", "requirement_ids", "requirement"):
        found = _REQ_RE.findall(str(front.get(key) or ""))
        if found:
            return ", ".join(dict.fromkeys(found))
    row_id = str(front.get("plan_row") or "").strip()
    if not row_id:
        return ""
    for row in _read_json(Path(task_root) / "work" / "test-plan.json", []) or []:
        if isinstance(row, dict) and str(row.get("id") or "") == row_id:
            refs = [str(r) for r in (row.get("requirement_ids") or []) if _REQ_RE.fullmatch(str(r))]
            if refs:
                return ", ".join(refs)
    try:
        for row in C.parse_plan(C.artifact(Path(task_root), "test-plan.md")):
            if str(row.get("ts") or "") == row_id and row.get("requirements"):
                return ", ".join(row["requirements"])
    except Exception:
        pass
    return ""


def project_of(task_root):
    """The project the story lives in (the nearest folder above it with `qa-factory/config.json`), or None."""
    for base in (Path(task_root).resolve(), *Path(task_root).resolve().parents):
        if (base / "qa-factory" / "config.json").is_file():
            return base
    return None


def stand_name(task_root: Path) -> str:
    """The stand this story runs against, by the name the project gave it."""
    config = _read_json((project_of(task_root) or Path(task_root)) / "qa-factory" / "config.json", {}) or {}
    pipeline = _read_json(Path(task_root) / "pipeline.json", {}) or {}
    chosen = str(pipeline.get("environment") or "").strip()
    environments = [e for e in (config.get("environments") or []) if isinstance(e, dict)]
    for entry in environments:
        if chosen and str(entry.get("name") or "") == chosen:
            return str(entry.get("name") or "")
    if len(environments) == 1:
        return str(environments[0].get("name") or "") or "this stand"
    return chosen or "this stand"


def declared_preconditions(task_root: Path) -> list:
    """Every precondition the story's cases declare, without touching the stand.

    The rehearsal is what decides whether a precondition is MET; this reads only what the
    designer wrote. Callers that must not open a socket — the pre-tool guard, which reaches
    for a gap's remedy while it decides one write — take this path."""
    rows = []
    try:
        import gate_preflight
    except Exception:
        return rows
    shared = gate_preflight.shared_precondition_ids(task_root)
    for case_id, text in _case_texts(Path(task_root)).items():
        raw = gate_preflight.case_preconditions_raw(text)
        if raw is None:
            continue
        items, errors = gate_preflight.parse_preconditions(raw)
        if errors:
            continue
        for item in items:
            pc_id = str(item.get("id") or "")
            rows.append({"id": gate_preflight.precondition_gap_id(case_id, pc_id, shared), "pc_id": pc_id, "case": case_id,
                         "kind": str(item.get("kind") or ""), "what": str(item.get("what") or ""),
                         "partitions": list(item.get("partitions") or []),
                         "check": item.get("check") if isinstance(item.get("check"), dict) else {},
                         "remedy": item.get("remedy") if isinstance(item.get("remedy"), dict) else {},
                         "state": "declared", "detail": ""})
    return rows


# What a rehearsal row of a stand gap carries on top of its card text, passed through to the gap unchanged (B-414 R2): the scope
# of the gap (one case, or every test of one execution contour), the contour and its cases, why the report could not be read,
# the precondition's own check, and the lasting key - `property_key` (None when `accept always` is not offered) with `lasting`,
# the reason there is none (`fault` | `no_key`). `understood`: what the factory's helper read of an unread report (B-416).
# `output_tail` (not in this list: made in `_gate_a_gaps`): the raw end of a run's output, for the conductor (`stand_gaps.py --json`,
# the driver state `shown_gaps`); never printed on a card.
_PASS_THROUGH = ("scope", "contour", "reason_class", "exit_code", "check", "kind", "property_key", "lasting", "pc_id",
                 "changed_since", "understood", "role", "fact", "options", "variant", "in_roster", "case_titles")
ROLE_SCOPES = ("role", "product_role")      # the two cards of project knowledge: the ONE home (gate_preflight and gate_brief read it; t-2142 PK0-4)
ROLE_NAMED, ROLE_TITLE = 3, 70              # cases a role card names with their titles (the `the test:` line AND the option/price lines), and the characters of a title


CASE_FILE_MISSING = "the case file was not found - open the story's cases"


def case_titles_of(task_root, cases) -> dict:
    """`{case id: what_the_test_does(its file)}` for the cases that have a file; a case with none is absent (its words are
    `CASE_FILE_MISSING` in `named_cases`). The data a covered role gap carries so that its line can explain each id (t-2142 PK0-9 B2)."""
    texts = _case_texts(Path(task_root))
    return {str(c): what_the_test_does(texts[str(c)]) for c in cases if texts.get(str(c))}


def named_cases(cases, titles: dict) -> str:
    """`TC-1 (title), TC-2 (title) and TC-3 (title), and K more`: up to `ROLE_NAMED` cases by id and title (a case with no title says its
    file was not found), then their number. The ONE list of the role card's `the test:` line and of the covered role line. Pure."""
    cases = [str(c) for c in cases or [] if c]
    named = [f"{c} ({_one(titles.get(c) or CASE_FILE_MISSING)})" for c in cases[:ROLE_NAMED]]
    more = f", and {len(cases) - ROLE_NAMED} more" if len(cases) > ROLE_NAMED else ""
    return (named[0] if len(named) == 1 else ", ".join(named[:-1]) + " and " + named[-1] if named else "") + more


def _role_card_words(row: dict, texts: dict, stand: str) -> tuple:
    """`(the_test, missing)` of a role card or a confirm card (t-2142 §3 (2), (6)): each case by its id and its TITLE (the first use of
    an id explains it, `what_the_test_does`), up to `ROLE_NAMED`, then their number; what is missing by the card's variant. Names only,
    no value, no key. Pure."""
    role, scope = str(row.get("role") or ""), row.get("scope")
    if scope == "product_role":
        return (str(row.get("what") or ""),
                f"your word that \"{role}\" is a role of the product; until then it stays marked as not confirmed")
    cases = [str(c) for c in (row.get("cases") or []) if c]
    listed = named_cases(cases, {c: what_the_test_does(texts[c]) for c in cases if texts.get(c)})
    the_test = f"{listed} sign{'s' if len(cases) == 1 else ''} in as \"{role}\""
    variant = row.get("variant")
    if variant == "twins":
        twins = ", ".join(f"\"{t}\"" for t in ((row.get("fact") or {}).get("twins") or []))
        missing = (f"the project's settings record two accounts the role \"{role}\" could mean on \"{stand}\" ({twins}), "
                   "so the factory cannot tell which")
    elif variant == "malformed":
        missing = (f"the project's settings hold an entry for \"{role}\" on \"{stand}\" that does not name two variables, "
                   "so the factory cannot sign in as it")
    else:
        missing = (f"an account for the role \"{role}\" on \"{stand}\": the project records none, so the factory cannot sign in as it; "
                   "the other cases of this story do not need it and are not held by it")
    return the_test, missing


def _one(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= ROLE_TITLE else text[:ROLE_TITLE].rsplit(" ", 1)[0].rstrip(",;:. ") + "…"


def _integration_row(row: dict) -> bool:
    """Is this rehearsal row about access to an integration: the `INT-*` row of the gate's own card (its `pc_id`) or a case's
    precondition whose check is `integration`. The prefix is `gate_preflight`'s, imported lazily as elsewhere in this file;
    an import that fails says no and the card keeps its old text."""
    check = row.get("check")
    if isinstance(check, dict) and "integration" in check:
        return True
    try:
        from gate_preflight import INTEGRATION_GAP_PREFIX
    except Exception:
        return False
    return str(row.get("pc_id") or "").startswith(INTEGRATION_GAP_PREFIX)


def _gate_a_gaps(task_root: Path, rows, texts=None, stand=None) -> list:
    """Rehearsal rows (or declared preconditions) as gate A gaps - the one mapping the open cards and the covered ones use."""
    texts = _case_texts(task_root) if texts is None else texts
    stand = stand_name(task_root) if stand is None else stand
    gaps = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        case_id = str(row.get("case") or "")
        text = texts.get(case_id, "")
        level = row.get("scope") == "level"
        cases = [str(c) for c in (row.get("cases") or []) if c]
        detail = str(row.get("detail") or "")
        what = str(row.get("what") or "")
        # GW1-31: a card about access to an integration reads "<name> (...) - access ... not set", never "env: " / "service: ".
        # Only the phrase: the row's `kind` is not changed (`property_key` of a recorded `accept always` stands on it)
        missing = f"{str(row.get('kind') or 'stand').replace('_', ' ')}: {what}" if what and not _integration_row(row) else \
            what or "the stand"
        # a row that records a process run (it carries `exit_code`) never prints that run's raw output on the card (B-306 c): the
        # tail goes to `output_tail` for the conductor. Key presence decides, not the value (a run that never started has None).
        ran = "exit_code" in row
        if detail and not ran:
            missing += f" - {detail}"
        # a level gap is a fact about the COMMAND, not about the stand (D-0023): "(on <stand>)" only for a case gap
        where = "(with the command recorded now)" if level else f"(on {stand})" if stand else ""
        gap = {"id": str(row["id"]), "gate": "A", "stage": GATE_STAGE["A"],
               "case": case_id, "case_id": case_id,
               "requirement": requirement_of(task_root, case_id, text),
               "partitions": [str(p) for p in (row.get("partitions") or [])],
               "the_test": ("every " + str(row.get("contour")) + " test of this story") if level else
                           what_the_test_does(text) if text else "the case file was not found - open the story's cases",
               "missing": f"{missing} {where}".strip(),
               "remedy": row.get("remedy") if isinstance(row.get("remedy"), dict) else {},
               "reason": "precondition", "owner": str(row.get("owner") or ""),
               "source": "case preconditions", "state": str(row.get("state") or ""), "stand": stand or ""}
        gap.update({key: row[key] for key in _PASS_THROUGH if key in row})
        if row.get("scope") in ROLE_SCOPES:         # t-2142 PK0-4: the role card and the confirm card speak by their cases' titles
            gap["the_test"], gap["missing"] = _role_card_words(row, texts, stand or "this stand")
        if ran and detail:
            gap["output_tail"] = names_only(detail)
        if cases:
            gap["cases"] = cases
        if isinstance(row.get("property"), dict):
            gap["property"] = row["property"]
        gaps.append(gap)
    return gaps


def _gate_a(task_root: Path, rehearsal, probe: bool) -> list:
    rows = None
    if isinstance(rehearsal, dict):
        rows = rehearsal.get("stand_gaps")
    elif probe:
        try:
            import gate_preflight
            rows = gate_preflight.run(task_root, "A").get("stand_gaps")
        except Exception:
            rows = None
    if rows is None:
        rows = declared_preconditions(task_root)
    return _gate_a_gaps(task_root, rows)


def covered_a(task_root, rehearsal) -> list:
    """The gate A gaps a rehearsal did NOT card because the environment record covers them (R7): each is a gap row with the
    live record row under `property`. [] when there is no rehearsal (the guard, `probe=False`) or none was covered."""
    rows = rehearsal.get("covered_gaps") if isinstance(rehearsal, dict) else None
    return _gate_a_gaps(Path(task_root), [r for r in rows or [] if isinstance(r, dict)]) if rows else []


def ran_red_of(row, manifest, runs) -> str:
    """`ran red: <reason, 60 chars>` for a `blocked_by_env` row whose instance RAN and FAILED, else "".

    t-219 (critic t-243, P20 / FR-10): a red parked as "blocked by the stand" must not read as a test that
    never got to run - the person who answers the card is the last reader who can say "that failure is the
    product's". The text is `acceptance.ran_red`'s, the one the window record prints; `runs` is
    `window_record._terminal_runs` (instance id -> (the latest terminal result row, ...)). The instances are the
    ones the row NAMES; a row that names none speaks of its case's instance only when the case has exactly
    ONE (the same rule `acceptance.blocked_instances` uses - code never guesses which test was meant). An
    instance that never ran gives no mark; several marks are listed once each, in the row's order."""
    if not runs or str(row.get("reason") or "") != "blocked_by_env":
        return ""
    try:
        import acceptance as AC
        tests = C.manifest_tests(manifest if isinstance(manifest, dict) else {})
        names = AC.blocked_row_names(row)
        groups = []
        if names:
            for name in names:
                owner = next((t for t in tests if name in C.instance_id_aliases(t)), None)
                groups.append(C.instance_id_aliases(owner) if owner else [name])
        else:
            case = str(row.get("case") or "")
            covering = [t for t in tests if any(C.case_matches(case, link) for link in C.manifest_test_links(t))]
            if len(covering) == 1:
                groups.append(C.instance_id_aliases(covering[0]))
        marks = []
        for ids in groups:
            last = next((runs[i] for i in ids if i in runs), None)
            if not last:
                continue
            mark = AC.ran_red({"status": C.result_status(last[0]), "reason": last[0].get("reason")})
            if mark and mark not in marks:
                marks.append(mark)
        return "; ".join(marks)
    except Exception:
        return ""


def _gate_b(task_root: Path) -> list:
    """The manifest's stand rows and the run report's environment blocks, as the same card.

    The case KEY is the gap id here (`workflows/TC-007` where two areas share a number), so
    the person's answer binds to the row it was written about."""
    texts = _case_texts(task_root)
    stand = stand_name(task_root)
    gaps, seen = [], set()
    runs = None  # the story's terminal runs, read once and only when a blocked row asks for them
    manifest = _read_json(Path(task_root) / "work" / "automation-manifest.json", {}) or {}
    rows = [(row, str(row.get("reason") or "")) for row in C.manifest_unresolved(manifest)]
    report = _read_json(C.artifact(Path(task_root), "run-report.json"), {}) or {}
    rows += [(row, "env_blocked") for row in (report.get("env_blocked") or [])
             if isinstance(row, dict)]
    for row, reason in rows:
        if reason not in STAND_REASONS and reason != "env_blocked":
            continue
        key = str(row.get("case") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        case_id = C.split_case_key(key)[1] or key
        text = texts.get(case_id, "")
        detail = " ".join(str(row.get("detail") or row.get("needs") or "").split())
        if reason == "blocked_by_env" and runs is None:
            try:
                import window_record
                runs = window_record._terminal_runs(Path(task_root))
            except Exception:
                runs = {}  # unreadable runs: no mark (the allowed error is the person seeing less, not a crash)
        gaps.append({"id": key, "gate": "B", "stage": GATE_STAGE["B"],
                     "case": key, "case_id": case_id,
                     "requirement": requirement_of(task_root, case_id, text),
                     "partitions": [],
                     "the_test": what_the_test_does(text) if text else
                                 "the case file was not found - open the story's cases",
                     "missing": (detail or "the row records no detail - that is the factory's "
                                 "gap, not yours") + (f" (on {stand})" if stand else ""),
                     "ran_red": ran_red_of(row, manifest, runs),
                     "remedy": row.get("remedy") if isinstance(row.get("remedy"), dict) else {},
                     "reason": reason, "owner": str(row.get("owner") or ""),
                     "source": "run report" if reason == "env_blocked" else "automation manifest",
                     "state": "open"})
    return gaps


def collect(task_root, gate: str = "A", rehearsal=None, probe: bool = True) -> list:
    """Every stand gap of one story at one gate. Reads only; writes nothing, ever.

    `rehearsal` is the result `gate_preflight.run` already produced, so a packet that shows
    both the rehearsal and the cards probes the stand once rather than twice. `probe=False`
    forbids the network entirely (the pre-tool guard)."""
    gate = str(gate or "A").upper()
    if gate not in GATE_STAGE:
        raise ValueError(f"gate must be one of: {', '.join(sorted(GATE_STAGE))}")
    task_root = Path(task_root)
    gaps = _gate_a(task_root, rehearsal, probe) if gate == "A" else _gate_b(task_root)
    # The story's own id travels with every gap: the command on the card is the one the person
    # can paste, and a card that says `--task <TICKET>` is a card they have to finish writing.
    ticket = str((_read_json(task_root / "pipeline.json", {}) or {}).get("ticket")
                 or task_root.name)
    for gap in gaps:
        gap["task"] = ticket
    return gaps


def decisions(task_root) -> dict:
    """The person's answers to this story's cards — one store, `stage_overrides[]`."""
    return C.stand_gap_decisions(_read_json(Path(task_root) / "pipeline.json", {}) or {})


# --- B-361 (D-0026): a stand-gap answer given at gate A reaches the gate B card under the case key ----------------------
#
# Gate A stores the person's `accept` under the PRECONDITION id (`stand gap: PC-1`, stage S5) and the gate B card looks
# for the CASE key, so the card asked again what the person had answered (FR-7) and the delivery check read the case as
# `env_undecided`. The driver now writes ONE more record when every stand gap of a case is accepted at gate A
# (`story_run.take_stand_gap_answers`): `stand gap: <case>`, stage S5 - a CARRIED record. This is the ONE view of it for
# the card (`gate_b_answers`) and the delivery check (`delivery_decisions`): a carried record settles the case only while
# nothing recorded since the answer says the world it was given for moved (`carried_change`). ERROR DIRECTION: toward
# asking - an unknown (a clock, a report, a block, a file that cannot be read) is a change, never a pass (FR-59, FR-41).
CARRY_STAGE = GATE_STAGE["A"]


def gap_cases(gap) -> list:
    """The cases a stand gap costs: its `cases` list when it has one - a LEVEL gap (`RP-<profile>`, no `case_id`) names
    several - else its `case_id`. THE one expansion every site of the carry (the driver's writer R1, the revoke R1b) uses
    (N6): keyed by `case_id` alone a level accept would carry nothing and `web: myself` after it would revoke nothing, a
    silent pass. Never contains an empty id."""
    if not isinstance(gap, dict):
        return []
    return [str(c) for c in (gap.get("cases") or [gap.get("case_id")]) if c]


def names_case(gap, case) -> bool:
    """D2-B2 (AR-13, AR-15): does this gap cost this case, by the identity match `contract.case_matches` (a gap spelled
    `TC-1` and a case spelled `web/TC-1` are one case; two areas never match)? A blank case names nothing (E-B1). An
    unreadable gap has no cases, so it names none - the carry is then not written and gate B asks again."""
    text = str(case or "").strip()
    return C.names_case(gap_cases(gap), text)


def _now() -> float:
    """The moment of reading, as the number `_moment` gives an answer (a seam for the tests)."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def _moment(value) -> float:
    """`contract`'s own order of two answers: an ISO stamp as a number, an empty or unreadable one the oldest there is."""
    return C._answer_moment(value)


def _bare(key) -> str:
    """The bare case id of a key: `check_delivery`'s own reader (F7: one definition - the records dropped here and the
    records `env_decision` matches must be the same set)."""
    import check_delivery
    return check_delivery._bare(key)


def _related_keys(key, decisions, cfg) -> list:
    """The keys of `decisions` other than `key` that are about the same case: exactly the records
    `check_delivery._decisions_for_case` hands `env_decision` (F7), found by identity so there is ONE predicate."""
    import check_delivery
    found = check_delivery._decisions_for_case(_bare(key), decisions, cfg)
    return [k for k, entry in decisions.items() if k != key and any(entry is hit for hit in found)]


def _named_cases(key, known, cfg) -> tuple:
    """`(the cases of the story a carried key names, whether it names more than one)` - THE one resolver of a carried key
    for both readers (critic t-537 F1, FR-10, FR-57). A bare number two AREAS share names two cases and is not guessed
    between: the card asks both and the delivery check says so by name. The cards' own placement (one gate B gap) comes
    after this and never overrides it."""
    matches = [k for k in known if C.case_matches(key, k, cfg=cfg)]
    areas = {C.split_case_key(k, cfg=cfg)[0] for k in matches} - {""}
    return matches, len(areas) > 1


def _ambiguity_words(key, matches, cfg) -> str:
    named = sorted({k for k in matches if C.split_case_key(k, cfg=cfg)[0]})
    return (f"the case number {key} matches more than one case: {', '.join(named) or key}; say which")


def _live_records(pipeline) -> list:
    """The stand-gap records `contract.stand_gap_decisions` reads - the ones `contract.stand_gap_live_entries` keeps (not
    revoked, with a gap id and a decision, and not put down by a later revoked record of the same id) - each with its
    position in `stage_overrides[]` (the contract's tie-break: equal stamps, the later record wins). In file order, as before:
    the one reader of which record lives is the contract's (AR-13, AR-15)."""
    return sorted(C.stand_gap_live_entries(pipeline), key=lambda record: record["pos"])


def _order(record) -> tuple:
    return (record["moment"], record["pos"])


def _carry_fields(entry) -> dict:
    """The typed fields of a RAW carried record the rules read besides the word: what the driver stored with it (`declared`:
    the precondition ids of the case then; `property`: the environment-record rows it rests on) and who wrote it (`by`)."""
    return {"declared": entry.get("declared"), "by": str(entry.get("by") or ""), "property": entry.get("property")}


def _case_context(task_root, extra=()) -> tuple:
    """(the keys of the story's case index, those keys plus `extra`, the project's case-id config). The index comes
    from `contract.case_index`, else from the authoring files; `extra` adds the keys the caller already knows are
    cases (a gate B gap's, a manifest row's), so that a story whose case files cannot be read does not turn a carried
    record into a plain one. The first list is the one an AMBIGUOUS bare id is judged against (two areas, one number)."""
    task_root = Path(task_root)
    try:
        cfg = C.case_config(task_root)
    except Exception:
        cfg = {}
    keys = []
    try:
        keys = [str(k) for k in C.case_index(task_root)]
    except Exception:
        try:
            import gate_brief
            keys = [str(k) for k in gate_brief.story_cases(task_root)[0]]
        except Exception:
            keys = []
    return keys, [k for k in dict.fromkeys(keys + [str(x) for x in extra if x])], cfg


def _is_carried(record, known, cfg) -> bool:
    """A carried record: stage S5 and a key that names a case of the story (never a precondition id such as `PC-1`)."""
    return record["stage"] == CARRY_STAGE and any(C.case_matches(record["key"], k, cfg=cfg) for k in known)


def _option_word(option) -> str:
    """The word a person gave for an option, from the data file; `in your own words` for an answer outside the list."""
    try:
        import gate_brief
        word = gate_brief.stand_gap_word_of().get(option)
    except Exception:
        word = None
    return word or "in your own words"


def _after(moment, answered) -> bool:
    """Is a recorded moment at or after the answer? Equality counts, and an unreadable moment counts: an unknown never
    settles (FR-59)."""
    return moment == float("-inf") or moment >= answered


def declared_ids(task_root, case, cfg=None, integration_ids=None) -> list:
    """Every stand gap id the case has at this moment, met or unmet, sorted: its preconditions, and the `INT-*` ids of the
    integrations the project's `required_by` ties it to (`integration_ids`, from `gate_preflight.integration_ids_of_case`, GW1-15).
    The driver stores it in the carry (`declared`) when it writes it, and C5 compares it with the same list read again - ONE reader
    for both. `integration_ids` None (not known, or not asked) adds none: the caller owns what that means (`_carried_reasons`
    asks again, the write goes on without them)."""
    return sorted({str(r.get("id")) for r in declared_preconditions(task_root)
                   if r.get("id") and (str(r.get("case")) == case or C.case_matches(str(r.get("case")), case, cfg=cfg))}
                  | {str(i) for i in (integration_ids or [])})


def _integration_ids(task_root, case, cfg=None):
    """`gate_preflight.integration_ids_of_case`, or None when it cannot be had (the module does not load, anything raises): None
    is "not known", never an empty list (AR-28). The one door both `declared_ids` callers use (the write and the rules)."""
    try:
        import gate_preflight
        return gate_preflight.integration_ids_of_case(task_root, case, cfg)
    except Exception:
        return None


ENV_BY = "environment-record"      # the `by` of an override the driver wrote from the environment record (R8(c), B-414)
PK_BY = "project-knowledge"        # the same, written from a row of the project-knowledge registry (a not-a-role answer, t-2142 PK0-9)
PK_RECORD = "project_knowledge"    # the `record` a covered gap's `property` names when it is a registry row (ENV rows carry none)


def _carried_reasons(task_root, case, answer, pipeline=None, only=None) -> list:
    """The changes since the answer, in words - an empty list when nothing recorded says the answer stopped covering the case.

    One function per rule (`RULES`, critic t-537 F10): `only` names the rules to run (None: every one). The two checks that
    stand before every rule - the clock of the answer and the word being an acceptance - always run."""
    task_root = Path(task_root)
    carried_at = _moment(answer.get("at"))
    if carried_at == float("-inf") or carried_at > _now():
        return ["the time of your answer is not readable, so I ask again"]
    if answer.get("option") != "accept":
        return [f"what you wrote at gate A ({_option_word(answer.get('option'))}) is not an acceptance, so it does not cover this case"]
    try:
        cfg = C.case_config(task_root)
    except Exception:
        cfg = {}
    if pipeline is None:
        pipeline = _read_json(task_root / "pipeline.json", {}) or {}
    integration_ids = _integration_ids(task_root, case, cfg)       # ONCE per call: it builds a rehearsal (rule CI reads it too)
    ids = set(declared_ids(task_root, case, cfg, integration_ids))
    gap_records = [r for r in _live_records(pipeline) if r["stage"] == CARRY_STAGE and r["key"] in ids]
    accepts = [r for r in gap_records if C.stand_gap_decisions({"stage_overrides": [r["entry"]]}).get(r["key"], {}).get("option") == "accept"]
    # F3: the person's word began to cover the case when the EARLIEST gap of it was accepted - a carry written when the last
    # gap was accepted, in a later answer, still covers what the person said first. Every rule below measures from there.
    answered = min([carried_at] + [r["moment"] for r in accepts])
    ctx = {"task_root": task_root, "case": case, "answer": answer, "pipeline": pipeline, "cfg": cfg, "ids": ids,
           "answered": answered, "integration_ids": integration_ids}
    reasons = []
    for name, rule in RULES:
        if only is None or name in only:
            reasons.extend(rule(ctx))
    return reasons


def _run_blocks(ctx) -> tuple:
    """`(blocks, unreadable)` of the story's run blocks, read once per check (C1 and C1u share it)."""
    if "blocks" not in ctx:
        import run_history as RH
        ctx["blocks"] = RH.read_run_blocks(ctx["task_root"])
    return ctx["blocks"]


def _c1(ctx) -> list:
    """C1: a test of the case ran red at or after the answer (a run with no clock behind it counts as after)."""
    task_root, case, cfg, answered = ctx["task_root"], ctx["case"], ctx["cfg"], ctx["answered"]
    import run_history as RH
    blocks, _unreadable = _run_blocks(ctx)
    reasons = []
    red = None
    import case_stamp as CS
    manifest = C.load_json(C.artifact(task_root, "automation-manifest.json"))
    index = CS.run_rows_of(task_root)
    for entry in C.manifest_tests(manifest):
        if not any(C.case_matches(link, case, cfg=cfg) for link in C.manifest_test_links(entry, cfg)):
            continue
        row = CS.red_run_for(entry, index)
        if row is None:
            continue
        attempt = str(row.get("attempt_id") or "")
        times = [b["time"] for b in blocks if attempt and b["attempt"] == attempt and b["time"] != RH._EPOCH]
        if not times or max(times).timestamp() >= answered:     # no clock behind the run: it counts as after
            red = row
            break
    if red is not None:
        import acceptance as AC
        mark = AC.ran_red({"status": C.result_status(red), "reason": red.get("reason")})
        reasons.append("a test of this case ran after your answer and failed" + (f" ({names_only(mark)})" if mark else ""))
    return reasons


def _c1u(ctx) -> list:
    """C1u: the runs cannot be read (the report, or a block stamped at or after the answer or not stamped)."""
    task_root, answered = ctx["task_root"], ctx["answered"]
    import run_history as RH
    _blocks, unreadable = _run_blocks(ctx)
    report = C.artifact(task_root, "run-report.json")
    unreadable_report = False
    if report.is_file():
        try:
            unreadable_report = not isinstance(json.loads(report.read_text(encoding="utf-8-sig")), dict)
        except (OSError, ValueError):
            unreadable_report = True
    if unreadable_report or any((RH._stamp_time(name) is None) or RH._stamp_time(name).timestamp() >= answered
                                for name in unreadable):
        return ["I could not read every test run made since your answer, so I cannot tell whether this case ran"]
    return []


def _c2(ctx) -> list:
    """C2: the build on the stand moved (or its confirmation was withdrawn) after the answer.

    B-414 (critic t-515 A3): an answer the driver wrote from the ENVIRONMENT RECORD (`by` == ENV_BY) is about the stand's
    configuration, so a changed commit or image is no change for it; a changed `stand_definition_sha` (the stand was re-pointed)
    and a `withdrawn` row still are."""
    task_root, answer, answered = ctx["task_root"], ctx["answer"], ctx["answered"]
    reasons = []
    import stand_identity as SI
    rows, problems = SI.confirmation_rows(task_root)
    if problems:
        reasons.append("I could not read every record of the build on the stand since your answer")
    else:
        base: dict = {}
        for row in rows:
            key = (row["environment_id"], row["profile_id"])
            if _moment(row.get("at")) < answered:
                base[key] = row
        for row in rows:                  # F2: with no row of the key before the answer, its FIRST row after it is the baseline
            base.setdefault((row["environment_id"], row["profile_id"]), row)
        for row in rows:
            if _moment(row.get("at")) < answered:
                continue
            key = (row["environment_id"], row["profile_id"])
            when = str(row.get("at") or "")[:10]
            if row.get("kind") == "withdrawn":
                reasons.append(f"the build on the stand changed after your answer (the confirmation was withdrawn, {when})")
                break
            before = base[key]
            if before is row:
                continue                  # the baseline itself is not a change (FR-41: only a recorded difference is)
            fields = (("revision", "the commit"), ("image", "the image"), ("stand_definition_sha", "the stand's address"))
            if answer.get("by") in (ENV_BY, PK_BY):      # PK0-9: a not-a-role answer is not about the build either
                fields = tuple(f for f in fields if f[0] == "stand_definition_sha")
            moved = [name for field, name in fields if row.get(field) != before.get(field)]
            if moved:
                reasons.append(f"the build on the stand changed after your answer ({' and '.join(moved)}, {when})")
                break
    return reasons


def _c3(ctx) -> list:
    """C3: a later word about one of the case's stand gaps at gate A (a live word other than accept, or a word taken back)."""
    pipeline, ids, answered = ctx["pipeline"], ctx["ids"], ctx["answered"]
    later = []
    for entry in pipeline.get("stage_overrides") or [] if isinstance(pipeline, dict) else []:
        if not isinstance(entry, dict) or str(entry.get("stage") or "") != CARRY_STAGE:
            continue
        if C.stand_gap_id(entry.get("match")) not in ids:
            continue
        if entry.get("revoked_at"):
            if _after(_moment(entry.get("revoked_at")), answered):
                later.append("at gate A you later took back your answer for one of its stand gaps")
            continue
        if not str(entry.get("decision") or "").strip() or not _after(_moment(entry.get("at")), answered):
            continue
        said = C.stand_gap_decisions({"stage_overrides": [entry]}).get(C.stand_gap_id(entry.get("match"))) or {}
        if said.get("option") != "accept":
            word = _option_word(said.get("option"))
            later.append("at gate A you later answered " + (f"`{word}`" if said.get("option") else word)
                         + " for one of its stand gaps")
    return list(dict.fromkeys(later))


def _c4(ctx) -> list:
    """C4 (B-414, critic t-515 A3): the environment property an answer rests on still holds.

    For a carry with a `property` list (the records of the environment it was written from) or `by` == ENV_BY: every named row
    must still be live, and `environment_record.covering` must find it under the key the SAME subject has NOW - so a record
    taken back (in another story, or by `ask again`), a command that changed, a stand that was re-pointed, a record that
    cannot be read, and a carry that names no record at all each reopen the case. A carry that never rested on the record
    (a person's own word) has no such rule. PK0-9: a property with `record` == PK_RECORD rests on the registry instead (its row
    live, the role still `not_needed`, the registry readable); the environment record is read only for a property that rests on it."""
    answer = ctx["answer"]
    props = answer.get("property") if isinstance(answer.get("property"), list) else []
    if not props and answer.get("by") not in (ENV_BY, PK_BY):
        return []
    why = "the recorded environment property no longer holds ({})"
    if not props:
        return [why.format("the answer names no record of it")]
    task_root = ctx["task_root"]
    project = project_of(task_root)
    if project is None:
        return [why.format("the project's own record cannot be found")]
    pk_props = [p for p in props if isinstance(p, dict) and p.get("record") == PK_RECORD]
    props = [p for p in props if not (isinstance(p, dict) and p.get("record") == PK_RECORD)]
    if pk_props:                      # PK0-9 (N4): a not-a-role answer rests on its registry row and on the role still being `not_needed`
        import project_knowledge as PK
        pk_rows, pk_problem = PK.load(project)
        if pk_problem:
            return [why.format("the record of earlier answers cannot be read")]
        for prop in pk_props:
            row = next((r for r in pk_rows if isinstance(r, dict) and str(r.get("id")) == str(prop.get("id"))), None)
            if row is None or row.get("revoked_at"):
                return [why.format("it was taken back")]
            element = str(prop.get("subject") or "").split("|", 2)[-1]
            if PK.state(project, PK.ROLES_KEY, "", element)["state"] != PK.NOT_NEEDED:
                return [why.format("the person's answer about the role has changed")]
    if not props:                     # the environment record is read only for a property that rests on it
        return []
    import environment_record as ER
    rows, problem = ER.load(project)
    if problem:
        return [why.format("the environment record cannot be read")]
    cfg = _read_json(project / "qa-factory" / "config.json", {}) or {}
    stand = stand_name(task_root)
    for prop in props:
        row = next((r for r in rows if isinstance(prop, dict) and str(r.get("id")) == str(prop.get("id"))), None)
        if row is None or row.get("revoked_at"):
            return [why.format("it was taken back")]
        if ER.covering([row], ER.current_key(row.get("subject"), cfg, stand)) is None:
            return [why.format("the command or the stand it was recorded for has changed")]
    return []


def _c5(ctx) -> list:
    """C5 (F6, D-0026 "a new case"): a precondition id the case declares NOW that the carry did not know when it was written
    (`declared`, the typed field the driver stores in the carry: every id the case declared then, met or unmet). An id IN the
    list with no accept was met at gate A (or is C3's, when it has a revoked or non-accept record) - never new.
    `declared` None (a carry written before the field existed, or whose field could not be stored): C5 does not fire. No such
    carry exists before the release that introduces the field; the allowed error for the rest is C3, C1, C1u and C2."""
    declared = ctx["answer"].get("declared")
    if isinstance(declared, list) and ctx["ids"] - {str(i) for i in declared}:
        return ["a new stand gap of this case appeared after your answer"]
    return []


def _ci(ctx) -> list:
    """CI (GW1-15): which stand integrations the case is tied to could not be read, so the ids C3 and C5 compare are not all
    known - an unknown is a change (FR-59, AR-28): ask again. `integration_ids_of_case` says None for it."""
    if ctx["integration_ids"] is None:
        return ["I could not read which stand integrations this case is tied to, so I ask again"]
    return []


# The rules of a carried answer, in the order their words are given. `only=` of `carried_change` names some of them.
RULES = (("C1", _c1), ("C1u", _c1u), ("C2", _c2), ("C3", _c3), ("C4", _c4), ("C5", _c5), ("CI", _ci))


def carried_change(task_root, case, answer, pipeline=None, only=None) -> str:
    """"" when a carried gate A answer still settles the case, else WHAT CHANGED since the person gave it, in words
    (every change that applies, joined). Never raises: a rule that cannot be evaluated is itself a change - ask again.

    The rules: the time of the answer is not readable (a stamp that is empty, unparseable or later than now); a test of
    the case ran red at or after the answer (C1; a run with no clock counts as after); the runs cannot be read (C1u: the
    report, or a block stamped at or after the answer or not stamped); the build on the stand moved or its confirmation
    was withdrawn (C2; a first row of a key after the answer is not a move - and for an answer written from the environment
    record only the stand's address counts, or the withdrawal); a later word of the person about one of the case's gate A
    stand gaps, or one taken back (C3); the environment property the answer rests on no longer holds (C4); a stand gap the
    case declares that no earlier accept covers (C5; the ids are the case's preconditions and, GW1-15, the `INT-*` of the
    integrations it is tied to); which integrations it is tied to could not be read (CI).
    Every rule measures from the EARLIEST accept of the case's gate A gaps (the carry's own `at` only when none is
    found), the clock guard from the carry's `at`. `answer` is `{option, words, at, by, property, declared, ...}`; a carried
    word other than `accept` settles nothing. `only`: the names of the rules to run (None: every one)."""
    try:
        return "; ".join(_carried_reasons(task_root, str(case), answer if isinstance(answer, dict) else {}, pipeline, only))
    except Exception:                         # the error's own name is not for the person to read (FR-6)
        return "I could not check what happened to this case since your answer, so I ask again"


def gate_b_answers(task_root, gaps=None, pipeline=None) -> tuple:
    """`({gate B gap id: {option, words, at, stage, gate, change}}, had_gate_a)` - the ONE view of what the person has
    answered about the gate B stand gaps, for the card (`gate_brief.stand_gap_cards`) and the command line.

    A gap's answer is the latest record of the person about it (the contract's order: the later `at`; equal stamps, the
    record later in `stage_overrides[]`): a record under its own key (gate B, `gate: "B"`), or a CARRIED record -
    stage S5, keyed by a case - re-keyed onto the gate B gap when exactly ONE gap matches it (`gate: "A"`; two areas
    that share a number are not guessed between, both are asked). `change` is `carried_change` for a gate A answer, ""
    for the person's own answer at gate B: a gate B answer is never second-guessed. `had_gate_a` is read from the RAW
    store - any S5 stand-gap record, revoked or not - so a story with none renders exactly as before."""
    task_root = Path(task_root)
    if pipeline is None:
        pipeline = _read_json(task_root / "pipeline.json", {}) or {}
    pipeline = pipeline if isinstance(pipeline, dict) else {}
    raw = pipeline.get("stage_overrides")
    had = any(isinstance(e, dict) and str(e.get("stage") or "") == CARRY_STAGE and C.stand_gap_id(e.get("match"))
              for e in (raw if isinstance(raw, list) else []))
    live = _live_records(pipeline)
    if gaps is None:
        gaps = collect(task_root, "B")
    gaps = [g for g in (gaps or []) if isinstance(g, dict) and str(g.get("id") or "")]
    if not live or not gaps:
        return {}, had
    _keys, known, cfg = _case_context(task_root, extra=[k for g in gaps for k in (g.get("id"), g.get("case_id"))])
    carried = [r for r in live if _is_carried(r, known, cfg)]
    on_gap: dict = {}                        # carried record position -> the one gate B gap it is re-keyed onto
    for record in carried:
        if _named_cases(record["key"], known, cfg)[1]:
            continue                         # a number two areas share: not guessed between (the same resolver as delivery)
        exact = [str(g["id"]) for g in gaps if str(g["id"]) == record["key"]]
        near = exact or [str(g["id"]) for g in gaps
                         if C.case_matches(record["key"], str(g.get("case_id") or _bare(g["id"])), cfg=cfg)]
        if len(near) == 1:
            on_gap[record["pos"]] = near[0]
    carried_at = {r["pos"] for r in carried}
    answers = {}
    for gap in gaps:
        gid = str(gap["id"])
        candidates = [r for r in live if r["key"] == gid and r["pos"] not in carried_at]
        candidates += [r for r in carried if on_gap.get(r["pos"]) == gid]
        if not candidates:
            continue
        win = max(candidates, key=_order)
        said = C.stand_gap_decisions({"stage_overrides": [win["entry"]]}).get(win["key"]) or {}
        answer = {"option": said.get("option", ""), "words": said.get("words", ""), "at": said.get("at", ""),
                  "stage": win["stage"], "gate": "A" if win["pos"] in carried_at else "B", "change": ""}
        if answer["gate"] == "A":
            answer.update(_carry_fields(win["entry"]))
            answer["change"] = carried_change(task_root, str(gap.get("case_id") or _bare(gid)), answer, pipeline)
        answers[gid] = answer
    return answers, had


def delivery_decisions(task_root, pipeline, manifest=None) -> tuple:
    """`(decisions, changed)` for the delivery check (`check_delivery.gather`): `contract.stand_gap_decisions` with the
    CARRIED records taken out, and each put back under its own key only when it still settles its case - the same
    rules `gate_b_answers` applies to the card, from the same helpers (FR-10).

    A carried record that a later record of the person about the same case follows (the contract's order, ties to the
    later in `stage_overrides[]`) is simply out: the later word is the one in force. A carried record that is the
    newest word takes the OLDER records about its case with it - the person's latest word is the one that counts - and
    stays only when `carried_change` is "" and its key names ONE case (`_named_cases`, the card's resolver, checked
    before anything is dropped: a number two areas share leaves the older words standing and `changed` names the
    ambiguity); otherwise the case is undecided and `changed` holds {bare case id: what changed}. Covers every carried
    record, also a case with no card."""
    decisions = C.stand_gap_decisions(pipeline)
    live = _live_records(pipeline)
    best: dict = {}
    for record in live:                       # the contract's own pick per key: the later moment, ties to the later position
        if record["key"] not in best or record["moment"] >= best[record["key"]]["moment"]:
            best[record["key"]] = record
    extra = [str(u.get("case") or "") for u in C.manifest_unresolved(manifest or {})]
    _keys, known, cfg = _case_context(task_root, extra=extra)
    changed: dict = {}
    for key, record in sorted(best.items(), key=lambda item: _order(item[1])):
        if not _is_carried(record, known, cfg):
            continue
        bare = _bare(key)
        related = _related_keys(key, decisions, cfg)
        decisions.pop(key, None)
        if any(_order(best[k]) > _order(record) for k in related if k in best):
            continue                          # a later word of the person about the case is the one in force
        matches, ambiguous = _named_cases(key, known, cfg)
        if ambiguous:                         # checked BEFORE the older words stand down, so they keep standing (F1)
            changed[bare] = _ambiguity_words(key, matches, cfg)
            continue
        for k in related:
            decisions.pop(k, None)            # the carried word is the newest: older words about the case stand down (FR-10)
        entry = C.stand_gap_decisions({"stage_overrides": [record["entry"]]}).get(key) or {}
        change = carried_change(task_root, bare, dict(entry, **_carry_fields(record["entry"])), pipeline)
        if change:
            changed[bare] = change
        else:
            decisions[key] = entry
    return decisions, changed


# --- B-414 (D-0029, D-0032): what the environment record covers at gate B, and how the driver carries it -------------------
#
# Gate A never cards a gap the record covers (`gate_preflight`); the driver then writes, in this story, the same records an
# `accept` from the person would have left - the gap's own override and the case-key carry - with `by` = ENV_BY and the record's
# rows under `property` (typed, like `declared`), so that gate B and the delivery check read ONE rule (`carried_change`, C4). A
# gate B row is COVERED only while that rule says so: the carry is the record's, nothing recorded since reopens it, and the row
# did not run red. ERROR DIRECTION: toward asking - an unreadable record, a taken-back row, a changed command or stand is a card.

def _label(gap) -> str:
    """The name a person writes for a gap and the card is headed by (a level: its contour)."""
    return str(gap.get("contour") or gap.get("id") or "") if gap.get("scope") == "level" else str(gap.get("id") or "")


def gate_b_split(task_root, gaps=None, pipeline=None) -> tuple:
    """`(the gate B gaps that are ASKED, the gaps the project's records cover)`: the covered ones are the environment record's LEVEL
    gaps and the registry's role gaps (a role the person said is not a product role; `_pk_covered`).

    A row is covered when ALL hold (R7, FR-10 - the delivery check reads the same rule): the story carries the record's override
    of the level gap (`by` == ENV_BY, read from the raw `stage_overrides`); the row's own carry rests on that record, is the
    newest word and still settles the case (`carried_change`, EVERY rule - C2 for the stand's address and C4 for the record
    itself included, so a record taken back in another story reopens the row); and the row did not run red. Any other row is
    asked, with B-361's words for what changed. A covered LEVEL row is shown in the covered block, never as a card; a covered
    CASE-level gap reaches gate B as the carry alone and is shown by B-361's view. The covered gaps are one per level gap:
    `{id, scope, contour, cases, property: <the record's row>}`."""
    task_root = Path(task_root)
    gaps = collect(task_root, "B") if gaps is None else list(gaps)
    pipeline = pipeline if isinstance(pipeline, dict) else (_read_json(task_root / "pipeline.json", {}) or {})
    live = [r for r in _live_records(pipeline) if r["stage"] == CARRY_STAGE]
    env_keys = {r["key"] for r in live if r["entry"].get("by") == ENV_BY}
    pk_keys = {r["key"] for r in live if r["entry"].get("by") == PK_BY}          # PK0-9 (N4): a not-a-role answer
    project = project_of(task_root)
    if (not env_keys and not pk_keys) or project is None or not gaps:
        return gaps, []
    import environment_record as ER
    import project_knowledge as PK
    rows, problem = ER.load(project)             # an unreadable record skips only ITS grouping (toward asking)
    if problem:
        rows, env_keys = [], set()
    pk_rows, pk_problem = PK.load(project)
    if pk_problem:
        pk_rows, pk_keys = [], set()
    answers, _had = gate_b_answers(task_root, gaps, pipeline)
    asked, groups, pk_groups = [], {}, {}
    for gap in gaps:
        answer = answers.get(str(gap.get("id"))) or {}
        settled = answer.get("option") == "accept" and answer.get("gate") == "A" and not answer.get("change") and not gap.get("ran_red")
        pk_prop = next((p for p in answer.get("property") or [] if isinstance(p, dict) and p.get("record") == PK_RECORD), None) \
            if answer.get("by") == PK_BY else None
        if pk_prop is not None:
            pk_row = next((r for r in pk_rows if isinstance(r, dict) and str(r.get("id")) == str(pk_prop.get("id"))
                           and not r.get("revoked_at")), None)
            gid = str(pk_prop.get("gap") or "")
            if settled and pk_row is not None and gid and gid in pk_keys:
                pk_groups.setdefault(gid, {"row": pk_row, "prop": pk_prop, "cases": []})["cases"].append(str(gap.get("case_id") or gap.get("id")))
            else:
                asked.append(gap)
            continue
        level = next((p for p in answer.get("property") or [] if isinstance(p, dict)
                      and (p.get("subject") or {}).get("scope") == "level"), None) if answer.get("by") == ENV_BY else None
        row = next((r for r in rows if level and str(r.get("id")) == str(level.get("id"))), None)
        key = f"RP-{level['subject'].get('contour')}" if level else ""
        if row is None or key not in env_keys or not settled:
            asked.append(gap)
            continue
        groups.setdefault(key, {"row": row, "cases": []})["cases"].append(str(gap.get("case_id") or gap.get("id")))
    covered = [{"id": key, "gate": "B", "stage": GATE_STAGE["B"], "scope": "level", "case_id": "", "case": "",
                "contour": str(g["row"]["subject"].get("contour")), "cases": g["cases"], "property": g["row"]}
               for key, g in groups.items()]
    return asked, covered + _pk_covered(task_root, pk_groups)


def pk_property(row: dict, gap_id: str, subject=None) -> dict:
    """The `property` of a covered role gap: the registry row with its `record`, its `subject` (`product.roles||<element>` unless given),
    the covered gap's id and the person's words and story out of its provenance. The ONE builder, for gate A (`_cover_not_needed`) and
    gate B (`_pk_covered`). Pure."""
    provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
    return dict(row, record=PK_RECORD, subject=subject or f"product.roles||{row.get('element')}", gap=gap_id,
                words=provenance.get("words", ""), story=provenance.get("story", ""))


def _pk_covered(task_root, pk_groups: dict) -> list:
    """The covered role gaps of gate B, one per `pk_groups` entry (`{gap id: {"row", "prop", "cases"}}`), each carrying the titles of
    its cases (`case_titles`) so that the covered line explains every id."""
    out = []
    for gid, g in pk_groups.items():
        out.append({"id": gid, "gate": "B", "stage": GATE_STAGE["B"], "scope": "role", "case_id": "", "case": "",
                    "cases": g["cases"], "case_titles": case_titles_of(task_root, g["cases"]),
                    "property": pk_property(g["row"], gid, g["prop"].get("subject"))})
    return out


def pk_property_of(gap) -> dict:
    """The registry row a covered gap rests on (`property.record` == PK_RECORD), or {} - the ONE dispatch of every reader of the
    covered road (t-2142 PK0-9): an environment-record row carries no `record`, and its road is unchanged."""
    row = gap.get("property") if isinstance(gap, dict) else None
    return row if isinstance(row, dict) and row.get("record") == PK_RECORD else {}


def covered_says(gap) -> str:
    """The sentence for what a covered gap says, as the person reads it. An environment-record row: the record's own
    (`environment_record.says`). A registry row (a role the person said is not a product role): the role, the story and the date
    of the answer and the cases that are reported as not run for it."""
    row = pk_property_of(gap)
    if not row:
        import environment_record as ER
        return ER.says(gap.get("property") if isinstance(gap.get("property"), dict) else {})
    element = " ".join(str(row.get("subject") or "").split("|", 2)[-1].split()) or str(gap.get("role") or "this role")
    when, story = str(row.get("at") or "")[:10], " ".join(str(row.get("story") or "").split())
    cases = [str(c) for c in gap.get("cases") or []]
    titles = gap.get("case_titles") if isinstance(gap.get("case_titles"), dict) else {}
    named = named_cases(cases, titles) if cases else "its cases"          # each id explained by its title (explained_ids, FR-6)
    return (f"\"{element}\" is not a role of this product (your answer" + (f" in {story}" if story else "")
            + (f" on {when}" if when else "") + f"), so {named} {'is' if len(cases) == 1 else 'are'} reported as not run")


def covered_entries(covered) -> list:
    """The entries `Driver.accepted_cases` and `write_carries` take for covered gaps: an `accept` the environment record gives,
    with the record's words and date in the line, and its row (`id`, `subject`) as the typed `property`. A registry row (PK0-9) gives
    `by` PK_BY, a line built by `covered_says`, and `property` with its `record`, `subject` and the covered gap's id."""
    out = []
    for gap in covered:
        row = gap.get("property") if isinstance(gap.get("property"), dict) else {}
        words = " ".join(str(row.get("words") or "").split())
        if pk_property_of(gap):
            out.append({"gap": gap, "option": "accept", "by": PK_BY, "line": f"{words} ({covered_says(gap)})",
                        "property": [{"id": str(row.get("id")), "record": PK_RECORD, "subject": row.get("subject"),
                                      "gap": str(row.get("gap") or gap.get("id"))}]})
            continue
        out.append({"gap": gap, "option": "accept", "by": ENV_BY,
                    "line": f"{words} (recorded for this environment on {str(row.get('at') or '')[:10]}, {row.get('id')})",
                    "property": [{"id": str(row.get("id")), "subject": row.get("subject")}]})
    return out


def words_args(words_file, text, name) -> list:
    """The person's line handed over by FILE (`--words-file`, FR-17: no new inline carrier). A file that cannot be made is a
    failed command for the caller to print (FR-3), never a raise."""
    try:
        return ["--words-file", str(words_file(text, name))]
    except Exception as exc:
        return ["--words-file", f"<{type(exc).__name__}: the words file could not be written>"]


def annotate_override(task_root, stage, match, fields) -> str:
    """Add typed `fields` to the live override of `match` that `waiver.py` just wrote (it has no flag for an extra field).
    '' when stored, else the name of what failed; the caller says so and the answer stands without the field."""
    path = Path(task_root) / "pipeline.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for override in data.get("stage_overrides") or []:
            if (isinstance(override, dict) and override.get("stage") == stage and override.get("match") == match
                    and not override.get("revoked_at")):
                override.update(fields)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as exc:
        return type(exc).__name__
    return ""


def write_environment_overrides(task_root, task, covered, gap_ids, run, words_file, say=print) -> set:
    """R8(c)(1): for each covered gap with no live override in this story, `waiver.py --stage S5 --block "stand gap: <id>"
    --by environment-record`, the record's words quoted, and its row stored with it. Returns the ids whose record FAILED.

    A gap whose id is shared with, or is the start of, another gate A gap id of the story gets NO override and one printed
    line (`waiver.split_overridden` reads the block by whole identifiers since GW1-1, but this guard stays: a gap id that is the start of another gap's id is also the start of a longer name a reader could take for it); its
    cases still go through the carry. `run(script, *args) -> (code, text)` is the driver's `py`."""
    pipeline = _read_json(Path(task_root) / "pipeline.json", {}) or {}
    live = {r["key"] for r in _live_records(pipeline) if r["stage"] == CARRY_STAGE}
    lowered = [str(i).lower() for i in gap_ids]
    failed = set()
    for gap, entry in zip(covered, covered_entries(covered)):
        gid = str(gap.get("id"))
        if gid in live:
            continue
        low = gid.lower()
        if lowered.count(low) > 1 or any(other != low and other.startswith(low) for other in lowered):
            say(f"gate A: {_label(gap)}: recorded for this environment, and applied through its cases only - its name is also the "
                "start of another stand gap's, so no answer is written for it as a whole")
            continue
        code, text = run("waiver.py", "--task", task, "--stage", CARRY_STAGE, "--block", f"{C.STAND_GAP_MATCH_PREFIX} {gid}",
                         *words_args(words_file, C.person_decision("accept", entry["line"]), "env-gap"), "--by", entry["by"])
        if code:
            failed.add(gid)
            say(f"gate A: {_label(gap)}: the answer recorded for this environment could not be written to this story "
                f"({' '.join(text.split())[-160:]}); the card is shown again at gate B")
            continue
        stored = annotate_override(task_root, CARRY_STAGE, f"{C.STAND_GAP_MATCH_PREFIX} {gid}", {"property": entry["property"]})
        if entry["by"] == PK_BY:
            said = f"not asked - {covered_says(gap)}"
        else:
            import environment_record as ER
            said = f"not asked - you recorded on {str(gap['property'].get('at') or '')[:10]} that {ER.says(gap['property'])}"
        say(f"gate A: {_label(gap)}: {said}" + (f" (the record could not be stored with the answer: {stored})" if stored else ""))
    return failed


def write_carries(task_root, task, gaps, entries, cases, decided, failed_cases, run, words_file, say=print) -> None:
    """B-361 R1 (extracted from `story_run.take_stand_gap_answers`, critic t-537 F9; B-414 R8(c)(2) calls it too): the CARRY
    - `stand gap: <case>`, stage S5 - for every case whose stand gaps are all accepted, so the gate B card and the delivery
    check find the answer under the case key.

    `gaps`: every gate A gap of the story, the covered ones included; `entries`: what this answer accepts or says
    (`{gap, option, line}` from the person's lines and the card pointers' doors, and `covered_entries`); `cases`: the result
    of `Driver.accepted_cases`; `decided`: the story's recorded options. Only `accept`; only when every stand gap of the case
    is accepted (by this answer or an earlier one), one entry of THIS answer is about it (i), its gap ids belong to it alone
    (ii: a LEVEL gap - no `case_id`, several `cases` - is never "shared with other cases"), no gap of it got another word here
    (iii), and none of its records failed (iv). With ENV_BY entries only the carry is the record's (`by`); the rows it rests
    on go with it as `property`, and `declared` stores the precondition ids of the case now (C5). Neither is raised (FR-3):
    what cannot be written is told, and gate B asks."""
    now_ids = {str(e["gap"].get("id")) for e in entries if e["option"] == "accept"}
    candidates = list(dict.fromkeys(list(cases) + [c for e in entries if e["option"] == "accept" for c in gap_cases(e["gap"])]))
    for case in candidates:
        owners = [g for g in gaps if names_case(g, case)]
        mine = [e for e in entries if e["option"] == "accept" and names_case(e["gap"], case)]
        if not mine or C.names_case(failed_cases, case) or not all(
                str(g.get("id")) in now_ids or (decided.get(str(g.get("id"))) or {}).get("option") == "accept" for g in owners):
            continue
        case_ids = {str(g.get("id")) for g in owners}
        if case_ids & {str(g.get("id")) for g in gaps if not names_case(g, case) and g.get("case_id")}:
            why = "its precondition id is shared with another case"
        elif any(e["option"] != "accept" and names_case(e["gap"], case) for e in entries):
            why = "another stand gap of the case was answered differently"
        else:
            why = ""
        if why:
            say(f"gate A: {case}: the answer is not carried to gate B ({why}); gate B will show its card again")
            continue
        earlier = len(case_ids - {str(e["gap"].get("id")) for e in mine})
        said = (C.person_decision("accept", " / ".join(dict.fromkeys(str(e["line"]) for e in mine)))
                + (f" ({earlier} other stand gap(s) of this case were accepted in an earlier answer)" if earlier else ""))
        from_record = [e for e in mine if e.get("by") in (ENV_BY, PK_BY)]
        # `--by` only when EVERY entry of the case rests on ONE record (PK0-9: environment record or registry); a mix has none, its
        # `property` still names both so `_c4` checks each by its own record
        by_all = {e.get("by") for e in from_record}
        by = ["--by", next(iter(by_all))] if from_record and len(from_record) == len(mine) and len(by_all) == 1 and not earlier else []
        match = f"{C.STAND_GAP_MATCH_PREFIX} {case}"
        code, text = run("waiver.py", "--task", task, "--stage", CARRY_STAGE, "--block", match,
                         *words_args(words_file, said, "carry"), *by)
        say(f"gate A: {case}: your answer is carried to gate B, so it is not asked again unless something changes"
            if not code else
            f"gate A: {case}: the answer could not be carried to gate B ({' '.join(text.split())[-160:]}); gate B will show its card again")
        if code:
            continue
        # the carry also records which preconditions the case declared NOW, met or unmet (`declared`, typed, sorted): C5 opens the
        # card again only for an id declared AFTER this moment; and the environment-record rows it rests on (`property`: C4)
        fields = {"declared": declared_ids(task_root, case, None, _integration_ids(task_root, case))}   # None: no INT-*, the write goes on
        props = [p for e in from_record for p in e.get("property") or []]
        if props:
            fields["property"] = props
        stored = annotate_override(task_root, CARRY_STAGE, match, fields)
        if stored:
            say(f"gate A: {case}: the list of its preconditions could not be stored with the answer ({stored}); "
                "gate B will not notice a precondition added later")


def revoke_environment_overrides(task_root, task, gap, run, words_file, say=print) -> list:
    """R8(d): take back THIS story's records that rest on one environment-record row - the gap's own override and the carries of
    its cases - with `waiver.py --revoke` (the entries stay, marked revoked). Returns the names taken back. Matches by the typed
    `property` ids, never by words; the record's own row is revoked by `environment_record.py`, not here."""
    row = gap.get("property") if isinstance(gap.get("property"), dict) else {}
    pipeline = _read_json(Path(task_root) / "pipeline.json", {}) or {}
    mine = {}
    for record in _live_records(pipeline):
        props = record["entry"].get("property") if isinstance(record["entry"].get("property"), list) else []
        if record["stage"] == CARRY_STAGE and any(isinstance(p, dict) and str(p.get("id")) == str(row.get("id")) for p in props):
            mine[record["key"]] = str(record["entry"].get("match"))
    done = []
    # PK0-9: the same road for a registry row, said in its own words - ONE source of the two wordings (D2)
    held, source = (("its entry in the record of earlier answers", "record of earlier answers") if pk_property_of(gap)
                    else ("its record for this environment", "environment record"))
    for key, match in mine.items():
        code, text = run("waiver.py", "--revoke", "--task", task, "--stage", CARRY_STAGE, "--block", match,
                         *words_args(words_file, f"the person asked for {_label(gap)} again: {held} ({row.get('id')}) is taken back",
                                     "env-revoke"))
        if code:
            say(f"gate A: {key}: the answer taken from the {source} could not be taken back "
                f"({' '.join(text.split())[-160:]})")
        else:
            done.append(key)
    return done


def level_applied(task_root, gap):
    """The cases of a LEVEL gap that an `accept as blocked` was already APPLIED to in this story (the question register's
    `answers_applied` rows, the reader the executor itself uses for `applied_before`), or None when that cannot be read. An
    answer given before the level covered every case applied to the first case only (E2): the card says so, and asks again."""
    try:
        import planning_contract as PC
        done = {str(r.get("id")) for r in PC._applied_records(Path(task_root)) if r.get("what") == "accept_as_blocked"}
    except Exception:
        return None
    return [c for c in gap_cases(gap) if any(C.case_matches(d, c) for d in done)]


def record_lasting(project, entry, story, say=print) -> None:
    """R8(b): put the `accept always` the person just wrote in the project's environment record - ONE row, their line whole,
    under the key of the gap (`property_key`, computed by the rehearsal). The caller has recorded the story's own answer
    already; a failure here is only SAID (the story's answer stands, the person is not asked again: FR-3)."""
    import environment_record as ER
    gap = entry["gap"]
    row, problem, created = ER.record(project, gap.get("property_key"), "accept", entry.get("line"), story, ER.about_of(gap))
    if row is None:
        say(f"gate {gap.get('gate') or 'A'}: {_label(gap)}: the story's answer is recorded; the environment record is not ({problem})")
    else:
        say(f"gate {gap.get('gate') or 'A'}: {_label(gap)}: recorded for this environment ({row['id']}): {ER.says(row)}"
            + ("" if created else " - it was already there; the earlier words stand"))


def fix_line(remedy) -> str:
    """`<where> -> <change>; restart <what>` — names only, never a value. `where_words` (a card that names a place in words, B-414 R3)
    is what the person reads; `where` stays the path-shaped key the apply guard and `remedy_path` read."""
    if not isinstance(remedy, dict) or C.remedy_errors(remedy):
        return ("no exact change was recorded with this block - that is the factory's gap, "
                "not yours; the role that wrote the row owes it")
    line = f"{str(remedy.get('where_words') or remedy.get('where')).strip()} -> {str(remedy.get('change')).strip()}"
    restart = str(remedy.get("restart") or "").strip()
    if restart:
        line += f"; restart {restart}"
    return names_only(line)


def render(gaps, decided=None, task_root=None, limit=None) -> str:
    """The cards, in the order the gaps came. An answered gap shows the answer, not the words to answer with.

    Not a renderer of its own (t-357, FR-10): `gate_brief.stand_gap_card_lines` is the ONE text of a stand-gap card at
    both gates - words a person answers with (`<case id>: <word>`, the list in `references/question-vocabulary.json`),
    never the script that records them. `task_root` links a card's case to its file; `limit` is how many cards are
    shown in full (None: all of them - this is also what the command line prints)."""
    import gate_brief
    lines = gate_brief.stand_gap_card_lines(task_root, list(gaps or []), decided, limit=limit) if gaps else []
    return "\n".join(lines) + ("\n" if lines else "")


# --- option (a): the one write P-00 lets through -------------------------------------------
#
# P-00 (the factory never modifies application code) is absolute, and stays absolute. What the
# person's recorded `apply` decision opens is exactly one file — the one that gap's own remedy
# names — and only until it has been used once. Everything else under `protected_app_paths`
# stays blocked, including a second file named by the same decision.
APPLY_LEDGER = ("state", "stand-gap-applies.json")


def remedy_path(remedy) -> str:
    """The FILE a remedy names: `customer-config.yaml:306-311` -> `customer-config.yaml`.

    A Windows drive letter is not a line range, so a colon at the second character, or one
    followed by a path separator, does not split."""
    where = str((remedy or {}).get("where") or "").strip().replace("\\", "/")
    if not where:
        return ""
    head, sep, tail = where.rpartition(":")
    if sep and len(head) > 1 and not tail.startswith("/"):
        where = head
    return where.strip()


def _candidates(rel: str, project_root, app_root) -> list:
    path = Path(rel)
    if path.is_absolute():
        return [path]
    return [Path(app_root) / rel, Path(project_root) / rel]


def apply_grant(target: str, project_root, app_root, artifact_root, *, norm=None) -> dict:
    """The recorded `apply` decision that names exactly this file, or {}.

    Reads the pipeline of every story under the artifact root, because a hook knows a path and
    not a story. Nothing here opens a socket: a gap's remedy comes from what the case or the
    manifest already declares (`probe=False`)."""
    if norm is None:
        def norm(value):
            try:
                return str(Path(value).resolve()).replace("\\", "/").lower()
            except Exception:
                return str(value).replace("\\", "/").lower()
    wanted = norm(target)
    try:
        pipelines = sorted_paths(Path(artifact_root).glob("*/pipeline.json"))
    except Exception:
        return {}
    for pipeline_path in pipelines:
        task_root = pipeline_path.parent
        pipeline = _read_json(pipeline_path, {}) or {}
        answers = {gid: a for gid, a in C.stand_gap_decisions(pipeline).items()
                   if a.get("option") == "apply"}
        if not answers:
            continue
        gaps, held = [], Counter()
        for gate in sorted(GATE_STAGE):
            try:
                found = collect(task_root, gate, probe=False)
            except Exception:
                continue
            gaps += found
            for gap in found:           # counted per gate: the ids of ONE gate's cards are what a person's word is read against
                held[(gate, str(gap.get("id")))] += 1
        twice = {gid for (_gate, gid), n in held.items() if n > 1}
        for gap in gaps:
            answer = answers.get(str(gap.get("id")))
            # an id two gaps of one gate hold names neither of them: no grant (R14 - the person's `apply` was about one)
            if not answer or str(gap.get("id")) in twice or C.remedy_errors(gap.get("remedy")):
                continue
            rel = remedy_path(gap["remedy"])
            if not rel:
                continue
            rel_norm = rel.replace("\\", "/").lower().lstrip("./")
            hit = any(norm(c) == wanted for c in _candidates(rel, project_root, app_root))
            if not hit and "/" in rel_norm and wanted.endswith("/" + rel_norm):
                hit = True
            if hit:
                return {"gap": str(gap["id"]),
                        "task": str(pipeline.get("ticket") or task_root.name),
                        "stage": gap.get("stage"), "file": rel, "words": answer.get("words"),
                        "at": answer.get("at"), "task_root": str(task_root)}
    return {}


def grant_key(grant: dict) -> str:
    """One decision, one write. A NEW decision carries a new `at`, so a person who says it
    again opens it again — the standing rule that a person's word passes any block."""
    return f"{grant.get('task')}|{grant.get('gap')}|{grant.get('at')}"


def grant_used(grant: dict, state_root) -> dict:
    ledger = _read_json(Path(state_root).joinpath(*APPLY_LEDGER), {}) or {}
    row = ledger.get(grant_key(grant))
    return row if isinstance(row, dict) else {}


def record_grant(grant: dict, state_root, target: str, tool: str = "") -> None:
    """Write the receipt. A ledger that cannot be written never blocks the write it was about
    to allow: the person's word is the authority, this file is only its memory."""
    from datetime import datetime, timezone
    path = Path(state_root).joinpath(*APPLY_LEDGER)
    ledger = _read_json(path, {}) or {}
    ledger[grant_key(grant)] = {"task": grant.get("task"), "gap": grant.get("gap"),
                                "file": grant.get("file"), "target": str(target), "tool": tool,
                                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                "decided_at": grant.get("at")}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def selftest() -> int:
    failures = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    remedy = {"kind": "flag", "where": "testproject1/config/customer-config.yaml:306-311",
              "change": "enabled: true", "restart": "testproject1, testproject1-ui"}
    gap = {"id": "PC-1", "gate": "A", "stage": "S5", "case": "TC-007", "case_id": "TC-007",
           "requirement": "R-3", "partitions": ["P-selfref"], "the_test": "creates a workflow",
           "missing": "feature flag: sub-workflow states are enabled", "remedy": remedy,
           "task": "TP1-15045"}
    import gate_brief
    words = gate_brief.stand_gap_words()
    card = render([gap])
    case("the card names the requirement and the case it costs",
         "Stand gap: TC-007 (P-selfref) — needs R-3" in card, True)
    case("the exact change is on the card",
         "306-311 -> enabled: true; restart testproject1" in card, True)
    case("all four answers are offered, each by its word from the data file",
         len(words) == len(C.STAND_GAP_OPTIONS) and all(f"- `{row['word']}` — {row['says']}" in card for row in words),
         True)
    case("and the form that records the answer is a line a person writes",
         "write a line of its own: `<case id or level name>: <word>`" in card, True)
    case("no script, flag, block id or internal option name reaches the card",
         any(bad in card for bad in ("waiver.py", "--block", "--decision", "--stage", "handed", "stand gap: PC-1")),
         False)
    answered = render([gap], {"PC-1": {"option": "apply", "words": "apply it",
                                       "at": "2026-09-23"}})
    case("an answered gap shows the answer, as the word",
         "answered: change (2026-09-23)" in answered, True)
    case("and stops asking", "To answer a stand gap" in answered, False)
    case("a value that reached a detail is not printed",
         names_only("set STAND_ADMIN_TOKEN=wJalrXUtnFEMI in the env file"),
         "set STAND_ADMIN_TOKEN=<value not printed> in the env file")
    case("a block with no recorded change says so and never offers to apply it",
         "no exact change was recorded" in render([dict(gap, remedy={})]), True)
    case("the file of a remedy is the part before the line range",
         remedy_path(remedy), "testproject1/config/customer-config.yaml")
    case("a windows path keeps its drive letter",
         remedy_path({"where": "C:/app/config.yaml"}), "C:/app/config.yaml")
    case("a variable name is a remedy with no file of its own",
         remedy_path({"where": "AUTH_CLIENT_ID"}), "AUTH_CLIENT_ID")
    # A `reporter` card (the gate A rehearsal, TP2-2553) points at the run command in
    # the factory's OWN configuration, so `apply` opens that file and never application code.
    case("a reporter card's apply opens the factory's own config",
         remedy_path({"where": "qa-factory/config.json:profiles[web].commands.one_test"}),
         "qa-factory/config.json")
    case("one decision, one write - the key carries the moment it was said",
         grant_key({"task": "T", "gap": "PC-1", "at": "2026-09-23T10:00:00+00:00"}),
         "T|PC-1|2026-09-23T10:00:00+00:00")
    if failures:
        print("STAND_GAPS SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("STAND_GAPS SELFTEST: no violations (card shape, four answers in words, names only, apply grant)")
    return 0


def parse_task_args(description: str, output_flag: str, output_help: str, gates):
    """The command line the two gate CLIs share (B-309 t-422; `gate_preflight.main` took a copy of this): the story by
    `--task` or `--task-root`, the `--gate`, `--selftest`, and the one flag that names the output form (`--json` here,
    `--text` there). `gates` is the caller's own list of gate letters."""
    from hooklib import exact_options
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--task", default=None)              # None is "not given": a given empty value is a refusal, never absent
    ap.add_argument("--task-root", dest="task_root", default=None)
    ap.add_argument("--gate", default="A", choices=gates)
    ap.add_argument(output_flag, action="store_true", help=output_help)
    ap.add_argument("--selftest", action="store_true")
    return exact_options(ap).parse_args()


def resolve_task_root(args, program: str):
    """The folder of the EXISTING story `--task` or `--task-root` names (CX1-18: `hooklib.story_cli`, the one rule); a
    refusal (neither flag, an empty value, a story that is not there, two flags naming different folders) is ONE
    `{"error": ...}` line on stderr and exit 2, written by the driver, so this never returns without a folder.
    `program` names the script in the refusal."""
    from hooklib import story_cli
    return story_cli(f"{program}.py", key=args.task, root=args.task_root)


def main() -> int:
    C.force_utf8()
    args = parse_task_args(__doc__.strip().splitlines()[0], "--json", "the gaps as data instead of cards",
                           sorted(GATE_STAGE))
    if args.selftest:
        return selftest()
    task_root = resolve_task_root(args, "stand_gaps")
    if task_root is None:
        return 2
    gaps = collect(task_root, args.gate)
    ticket = str((_read_json(task_root / "pipeline.json", {}) or {}).get("ticket")
                 or args.task or task_root.name)
    covered = []
    if gaps and args.gate == "B" and not args.json:
        try:
            gaps, covered = gate_b_split(task_root, gaps)      # B-414: a level the environment record covers is no card
        except Exception:
            covered = []
    if args.json:
        print(json.dumps(gaps, indent=2, ensure_ascii=False))
    elif (gaps or covered) and args.gate == "B":
        # B-361: gate B reads the view the packet reads (a gate A answer under the case key, with what changed since)
        import gate_brief
        try:
            answers, had_gate_a = gate_b_answers(task_root, gaps)
        except Exception:
            answers, had_gate_a = {k: v for k, v in decisions(task_root).items() if v.get("stage") != CARRY_STAGE}, False
        print("\n".join(gate_brief.stand_gap_card_lines(task_root, list(gaps), answers, limit=None, had_gate_a=had_gate_a,
                                                          covered=covered)), end="\n")
    elif gaps:
        print(render(gaps, decisions(task_root), task_root=task_root), end="")
    else:
        print(f"No stand gap at gate {args.gate} for {ticket}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
