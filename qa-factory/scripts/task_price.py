"""The price of a task: ONE function that prices it from two independent records and checks them
against each other. Import-only (no command line): the dashboard, the retro and the budget ceiling
read it, so a story has one price on every page (FR-10).

The two records:
  A  the token usage of each session, from its cost file (`state/cost/<session>.json`), re-priced
     at READ time by `cost_capture.revalue_document` at the catalogue's LIST price (`cfg={}`: no
     project rate), so A and B share a rate base. Produced by our parser and our rate table.
  B  what the CLI itself charged for the session, from the driver's journal (`driver_journal.
     root_charged`). A Claude row holds no tokens and no model id, so B carries no rate information there; a
     Codex row holds both (`usage`, `model`) and the price the driver worked out from them (`cost_basis` says
     how), a number the CLI did not report: B reads it as it reads any running total.
What they share is only the API's per-request usage. Agreement proves that our parser found every
request once, that the same sessions were meant, and that the list price is the CLI's. It is not an
invoice: on a subscription both are list-price proxies.

The check is PER SESSION, never on the sums: +$0.10 on one session and -$0.10 on another must not
cancel. A session agrees when |A - B| <= TOLERANCE_USD (the cheapest real request on cmp1 is
$0.0105, so one request missed on either side always trips it). Money is summed in Decimal, never
rounded before summing, and left unrounded in the output: a page rounds to cents once, at display.

Error direction (this function is a gate on the measurers, FR-28): the allowed error is a false
alarm (`differs` or `not_cross_checked` when the records are in fact fine). Forbidden: `agrees` while
any comparable session differs, or while nothing was compared. The reused equality, `==` of two
floats, was never a gate; the tolerance is one named constant.

Output (a contract, FR-14). Always present: status, sessions, by_agent, totals, differ, one_record,
unknown, in_progress, catalogue_revision, finding, compared, rows_without_session, rate_overrides.
Present when at least one session has a record, absent when none has: price_low_usd, price_high_usd.
There is NO single `price_usd`: a range is printed ONLY while status is `differs`, otherwise low ==
high. See `task_price` for the rules. Each row of `by_agent` carries its share of the same pair
(`price_low_usd`, `price_high_usd`, None when nothing of the row is known) and the rows add up to the
task's pair exactly (P18); a row also carries `remote_usd`, the remote calls' receipts.

Sessions of a task (FR-24: evidence only, never a mention of the ticket, a `by_task` tag or a
marker): the sessions the driver's journal names (whole), the requests of a story activity segment
of the task, the requests a chat binding of the task names. A session named by a journal of ANOTHER
task is that task's, never this one's. A request that the evidence binds to TWO tasks is counted
under neither, and the finding names it and the tasks.
"""
import json
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cost_capture as CC  # noqa: E402
import driver_journal as DJ  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

TOLERANCE_USD = Decimal("0.001")   # per session; below the cheapest real request ($0.0105, cmp1)

AGREES, DIFFERS, NOT_CROSS_CHECKED, INCOMPLETE = "agrees", "differs", "not_cross_checked", "incomplete"
SINGLE_SOURCE_WORDS = "single source (chat): nothing to cross-check against"   # one wording for the page and the retro (FR-10)
V_AGREES, V_DIFFERS, V_ONE_RECORD, V_UNKNOWN, V_IN_PROGRESS = (
    "agrees", "differs", "one_record", "unknown", "in_progress")

ZERO = Decimal("0")
CENT = Decimal("0.01")


# ------------------------------------------------------------------------------- small helpers

def _usd(value) -> str:
    """$x.xx, rounded half up ONCE, at display."""
    return "$" + str(Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP))


def _float(value):
    return None if value is None else float(value)


def _dec(value):
    """A journal figure (a float) as a Decimal of its shortest spelling, so 1.001 is 1.001 and
    not 1.00099999999999988; None stays None."""
    return None if value is None else Decimal(repr(float(value)))


def _short(session) -> str:
    return str(session)[:8]


MAX_NAMED = 5   # agents named in the "usage was not read" sentence; the rest are "and more" (tested at 5 and at 6)


def _plural(n, one, many) -> str:
    return f"{n} {one if n == 1 else many}"


def unread_agent_calls(agent) -> int:
    """The tool calls of an agent whose usage was never read (tokens 0), else 0. The ONE predicate for "an agent that ran
    but has no cost": 0 means NOT a gap - the agent has tokens, or it was idle (no tool calls: E-C5) (AR-15; `task_price`
    and `retro_numbers.story_spend` both ask it)."""
    if not isinstance(agent, dict) or agent.get("tokens"):
        return 0
    tools = agent.get("tools")
    return int(sum(n for n in tools.values() if isinstance(n, (int, float)))) if isinstance(tools, dict) else 0


def tolerance_words() -> str:
    """The per-session tolerance (`TOLERANCE_USD`) in words, for every page that states the check. One
    source: a page that typed "a tenth of a cent" would go on saying it after the constant moved."""
    cents = TOLERANCE_USD * 100
    known = {Decimal("0.1"): "a tenth of a cent", Decimal("0.5"): "half a cent", Decimal("1"): "one cent"}
    return known.get(cents, f"{format(cents.normalize(), 'f')} cents")


# Why the CLI's charge of a session is unknown, in plain words (FR-6). Keyed by the reader's own codes
# (`driver_journal.WHY_*`); the retro's table of reasons reads this one, not a copy.
WHY_WORDS = {
    DJ.WHY_NO_TOTAL: "the journal holds no usable cost figure for it",
    DJ.WHY_FALLS: "its figure falls between calls, so it is one call's cost and not the session's",
    DJ.WHY_SEVERAL_JOURNALS: "several task journals name it, so this one holds only part of it",
    DJ.WHY_PER_CALL_ROOT: ("the project's journals record each call's cost and not a running total, "
                           "so a session with several rows cannot be priced"),
}


# ------------------------------------------------------------- the price base (one rate base per page)

def price_base_factor(a, ap):
    """`ap / a`: what puts a figure that is at the catalogue's list rates (the CLI's charge) on the
    price base of a session whose transcripts read `a` at list price and `ap` at the price used.
    None when there is nothing to scale by: the price IS the list price (`ap` unknown or equal to
    `a`), or the list price is 0 or unknown (`a`), where the charge cannot be scaled and stands as it
    is. The ONE place this arithmetic lives: the range, the ceiling, the share and the dispatch
    costs all call it."""
    if ap is None or a is None or a <= ZERO or ap == a:
        return None
    return ap / a


def b_on_price_base(a, ap, b) -> tuple:
    """(B on the price base, scaled) for one session: `b * ap / a` when it can be scaled (a > 0), `b` as
    it stands otherwise (`scaled` False: a is 0 or unknown while a price exists). With no price
    base (`ap` None) B is the session's only figure and is as it stands (`scaled` True: nothing
    was left unscaled). `b` None stays None."""
    if b is None:
        return None, True
    if ap is None:
        return b, True
    if a is not None and a > ZERO:
        return (b if ap == a else b * ap / a), True
    return b, False


def session_factors(answer) -> tuple:
    """({session: factor}, [sessions left unscaled]) read from the rows of a `task_price` answer:
    a session with a factor has its CLI charge put on the price base by `b * factor`; an unscaled
    one has a price and a charge and no list price to scale by. Sessions at list price are in
    neither (their charge already is on the price base)."""
    factors, unscaled = {}, []
    for row in (answer or {}).get("sessions") or []:
        if not isinstance(row, dict) or not row.get("session"):
            continue
        a, ap, b = _dec(row.get("a_usd")), _dec(row.get("a_price_usd")), _dec(row.get("b_usd"))
        factor = price_base_factor(a, ap)
        if factor is not None:
            factors[row["session"]] = factor
        elif ap is not None and b is not None and (a is None or a <= ZERO):
            unscaled.append(row["session"])
    return factors, unscaled


def project_rates_applied(answer) -> bool:
    """True when the price of an answer is at the project's own rates: a model priced by its
    `rate_overrides` entry, or a price that differs from the list price the records were compared at."""
    if not isinstance(answer, dict):
        return False
    if answer.get("rate_overrides"):
        return True
    totals = answer.get("totals") if isinstance(answer.get("totals"), dict) else {}
    a, ap = totals.get("a"), totals.get("a_price")
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (a, ap)) and abs(a - ap) > 1e-9


# ----------------------------------------------------------------------- cents that add up (display)

def _cents_of(value) -> int:
    """Whole cents of a figure, rounded half up ONCE (the rounding every page prints)."""
    return int((Decimal(repr(float(value))) if not isinstance(value, Decimal) else value)
               .quantize(CENT, rounding=ROUND_HALF_UP) * 100)


def usd_from_cents(cents) -> str:
    return "$" + format(Decimal(int(cents)).scaleb(-2), ",.2f")


SAME_FIGURE = Decimal("0.000000001")   # two figures of one row closer than this are the same figure (Decimal sums
#                                        split over rows differ at the 16th digit once they are floats)


def display_cents(columns, targets=None, not_below=None) -> list:
    """The cents a table prints for each figure of each column, chosen so that the printed cents of
    every column ADD UP to that column's printed total (the largest-remainder method): rows that each
    round correctly can still sum a cent away from the total printed under them, and a heading that
    says "adds up exactly" is then false on the page.

    `columns`: a list of columns, each a list (one entry per row) of Decimal | float | None (None is an
    unknown figure: it has no cents and is left out of the sum). `targets`: per column the exact figure
    whose rounding the column must reach (the printed total), or None for the column's own exact
    sum. `not_below`: {column: earlier column} for a range's high end: its cents are never below the
    low end's of the same row (two independent roundings could print "from $1.62 to $1.61"). Returns
    the columns of whole cents (int | None).

    Two figures of one row that are the same figure (equal within `SAME_FIGURE`) in an earlier and a
    later column print the same cents (a row whose two records agree must not print a cent apart, nor
    a row whose range is of nothing print a range), as long as the later column can still reach its
    target that way; when it cannot, that column is rounded on its own and keeps its sum (and, then
    only, loses the two guarantees). With one row the row equals the total; columns are otherwise
    rounded independently of each other (a range's low and high each add up to their own end)."""
    def dec(value):
        if value is None or isinstance(value, bool):
            return None
        return value if isinstance(value, Decimal) else Decimal(repr(float(value)))

    def same(x, y):
        return x is not None and y is not None and abs(x - y) < SAME_FIGURE

    out = []
    for k, column in enumerate(columns):
        values = [dec(v) for v in column]
        known = [i for i, v in enumerate(values) if v is not None]
        result = [None] * len(values)
        if not known:
            out.append(result)
            continue
        target_value = (targets[k] if targets is not None and k < len(targets) else None)
        target = (_cents_of(target_value) if target_value is not None
                  else _cents_of(sum((values[i] for i in known), ZERO)))
        scaled = {i: values[i] * 100 for i in known}
        base = {i: int(scaled[i].to_integral_value(rounding="ROUND_FLOOR")) for i in known}
        rest = {i: scaled[i] - base[i] for i in known}

        def assign(cells, need, lower=None):
            """floor + 1 for `need` of the cells, the largest remainders first (the index breaks a tie), each cell
            at least its `lower` bound when it has one; None when `need` cannot be reached by adding at most one
            cent to a cell."""
            lower = lower or {}
            start = {i: max(base[i], lower.get(i, base[i])) for i in cells}
            if any(start[i] > base[i] + 1 for i in cells):
                return None
            room = sorted((i for i in cells if start[i] == base[i]), key=lambda i: (-rest[i], i))
            extra = need - (sum(start.values()) - sum(base[i] for i in cells))
            if extra < 0 or extra > len(room):
                return None
            chosen = dict(start)
            for i in room[:extra]:
                chosen[i] += 1
            return chosen

        locked, lower = {}, {}
        for i in known:
            for j in range(k):
                if out[j][i] is not None and same(dec(columns[j][i]), values[i]):
                    locked[i] = out[j][i]
                    break
            else:
                j = (not_below or {}).get(k)
                if j is not None and out[j][i] is not None and dec(columns[j][i]) is not None \
                        and values[i] > dec(columns[j][i]):
                    lower[i] = out[j][i]
        free = [i for i in known if i not in locked]
        rest_target = target - sum(locked.values())
        chosen = assign(free, rest_target - sum(base[i] for i in free), lower)
        if chosen is not None:
            chosen.update(locked)
        else:
            chosen = assign(known, target - sum(base.values()))
        if chosen is None:          # a target that is further than a cent a row from the exact sum
            chosen = {i: base[i] for i in known}
        for i in known:
            result[i] = chosen[i]
        out.append(result)
    return out


def _project_cost_cfg(root) -> dict:
    """The project's `cost` block of qa-factory/config.json; {} when unreadable, absent or not an object. The file is
    read by `cost_capture.project_cost_block`, the ONE reader of it (AR-13)."""
    try:
        cost = CC.project_cost_block(root)
    except TypeError:
        return {}
    return cost if isinstance(cost, dict) else {}


def _read_cost_docs(root) -> dict:
    """{session id: cost file} of root/qa-factory/state/cost/*.json; an unreadable file is not a
    record (and is never $0)."""
    docs = {}
    folder = Path(root) / "qa-factory" / "state" / "cost"
    try:
        files = sorted_paths(folder.glob("*.json"))
    except OSError:
        return docs
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict):
            docs[path.stem] = doc
    return docs


def _docs_from(sessions) -> dict:
    """The cost files a caller already loaded: {session: doc}, or a list of docs naming their
    `session_id`. A doc with no id cannot be bound and is left out."""
    docs = {}
    if isinstance(sessions, dict):
        for key, doc in sessions.items():
            if isinstance(doc, dict):
                docs[str(key)] = doc
    else:
        for doc in sessions or []:
            if isinstance(doc, dict) and isinstance(doc.get("session_id"), str) and doc["session_id"]:
                docs[doc["session_id"]] = doc
    return docs


def _prices_differ_from_list(cfg) -> bool:
    return bool(isinstance(cfg, dict) and (cfg.get("rate_overrides") or cfg.get("model_prices")))


# ------------------------------------------------------------------ which requests are the task's

def _request_rows(doc) -> list:
    rows = doc.get("requests") if isinstance(doc, dict) else None
    return rows if isinstance(rows, list) else []


def _binding_indexes(rows, binding) -> set:
    """The request rows a chat binding names. `requests` as a LIST names them by request_key or
    request_id; otherwise `first_request` .. `last_request` (inclusive, ledger order) among the
    main chain's rows. Anything the binding cannot resolve binds nothing."""
    wanted = binding.get("requests")
    if isinstance(wanted, list):
        names = {str(w) for w in wanted}
        return {i for i, r in enumerate(rows)
                if isinstance(r, dict) and (r.get("request_key") in names or r.get("request_id") in names)}
    main = [i for i, r in enumerate(rows) if isinstance(r, dict) and r.get("stream") == "orchestrator"]
    first = next((i for i in main if binding.get("first_request") in (rows[i].get("request_key"), rows[i].get("request_id"))), None)
    last = next((i for i in reversed(main) if binding.get("last_request") in (rows[i].get("request_key"), rows[i].get("request_id"))), None)
    if first is None or last is None or first > last:
        return set()
    return {i for i in main if first <= i <= last}


def _own_requests(doc, task) -> tuple:
    """(activity indexes, chat indexes, contested) of the requests of a cost file that evidence
    binds to `task`: its story activity segments (`by_activity[*]` of type story naming the task,
    the request's own `activity_id`), and its chat bindings. Not a `by_task` tag, not a marker.

    A request that the evidence binds to TWO OR MORE DIFFERENT tasks (two chat bindings, or a story
    segment of one task and a chat binding of another) is nobody's: it leaves both index sets and
    is returned in `contested` as {index: sorted tasks}. Invariant: a request is never counted
    under two tasks, and never silently dropped (the caller names it). The SAME task naming a
    request twice (its segment and its chat binding) is one claim, not a conflict."""
    rows = _request_rows(doc)
    activities = doc.get("by_activity") if isinstance(doc.get("by_activity"), dict) else {}
    story = {aid: a["task"] for aid, a in activities.items()
             if isinstance(a, dict) and a.get("type") == "story" and isinstance(a.get("task"), str) and a["task"]}
    claims = {}   # request index -> {task: {"act"| "chat"}}
    for i, r in enumerate(rows):
        if isinstance(r, dict) and r.get("activity_id") in story:
            claims.setdefault(i, {}).setdefault(story[r["activity_id"]], set()).add("act")
    for binding in doc.get("chat_bindings") if isinstance(doc.get("chat_bindings"), list) else []:
        if isinstance(binding, dict) and isinstance(binding.get("task"), str) and binding["task"]:
            for i in _binding_indexes(rows, binding):
                claims.setdefault(i, {}).setdefault(binding["task"], set()).add("chat")
    act, chat, contested = set(), set(), {}
    for i, by_task in claims.items():
        if task not in by_task:
            continue
        if len(by_task) > 1:
            contested[i] = sorted(by_task)
            continue
        if "act" in by_task[task]:
            act.add(i)
        if "chat" in by_task[task]:
            chat.add(i)
    return act, chat, contested


def _add_contested_money(total, doc, indexes, catalogue, cfg, price_differs) -> None:
    """Add to `total` what the transcripts say the requests at `indexes` of `doc` cost: at the
    catalogue's list rates (`list`) and at the price used (`price`: the project's own rates when it has
    some, else the same figure); a request that cannot be priced is counted in `unpriced` and adds
    nothing (never $0 presented as its cost). Only record A can speak for them: a contested request
    sits in a session no driver journal names, and the CLI's charge is per session."""
    rows_l = _request_rows(CC.revalue_document(doc, {}, catalogue))
    rows_p = _request_rows(CC.revalue_document(doc, cfg, catalogue)) if price_differs else rows_l
    for i in indexes:
        parts = []
        for rows in (rows_l, rows_p):
            valuation = rows[i].get("valuation") if i < len(rows) and isinstance(rows[i], dict) else None
            try:
                parts.append(Decimal(str(valuation.get("subtotal_usd", "0")))
                             if isinstance(valuation, dict) and valuation.get("pricing_coverage") == "complete" else None)
            except InvalidOperation:
                parts.append(None)
        if parts[0] is None:
            total["unpriced"] += 1
            continue
        total["list"] += parts[0]
        total["price"] += parts[1] if parts[1] is not None else parts[0]


def _request_name(doc, index) -> str:
    row = _request_rows(doc)[index]
    return str((row.get("request_id") or row.get("request_key") or f"row {index}") if isinstance(row, dict) else f"row {index}")


def _agent_type(doc, stream) -> str:
    for agent in doc.get("agents") if isinstance(doc.get("agents"), list) else []:
        if isinstance(agent, dict) and agent.get("file") == stream and agent.get("agent"):
            return str(agent["agent"])
    return str(stream or "").removesuffix(".jsonl")


def _request_label(doc, row, session_label, chat_set, index) -> str:
    """One agent per request. A subagent file inside a session: its `agentType`; the main chain:
    the session's own label (the journal's role, the orchestrator, or the person's chat)."""
    stream = row.get("stream") if isinstance(row, dict) else None
    if stream and stream != "orchestrator":
        return DJ.agent_label({"source": "subagent", "agent_type": _agent_type(doc, stream)})
    if index in chat_set:
        return DJ.agent_label({"source": "chat"})
    return session_label


# ---------------------------------------------------------------------------------------- record A

def _sum_rows(rows, indexes) -> tuple:
    """(total | None, why, {index: Decimal}) of the re-priced request rows `indexes`. None (never
    $0) when there is no request, or when any one request is not completely priced: a known part
    of a session is not the session."""
    if not indexes:
        return None, "the cost file holds no request of it", {}
    total, parts, reasons = ZERO, {}, []
    for i in sorted(indexes):
        valuation = rows[i].get("valuation") if isinstance(rows[i], dict) else None
        if not isinstance(valuation, dict) or valuation.get("pricing_coverage") != "complete":
            provenance = (valuation or {}).get("rate_provenance") if isinstance(valuation, dict) else None
            reason = provenance.get("reason") if isinstance(provenance, dict) else None
            if not reason and isinstance(valuation, dict) and valuation.get("missing_rate_categories"):
                reason = "no rate for: " + ", ".join(valuation["missing_rate_categories"])
            model = rows[i].get("model_id") if isinstance(rows[i], dict) else None
            if (isinstance(provenance, dict) and provenance.get("kind") == "unpriced" and reason
                    and isinstance(valuation, dict) and valuation.get("missing_rate_categories")
                    and isinstance(model, str) and model):
                reason = f"rate unknown for {model}: {reason}"   # FR-41: the unknown is named, with the model
            reasons.append(reason or "a request could not be priced")
            continue
        try:
            part = Decimal(str(valuation.get("subtotal_usd", "0")))
        except InvalidOperation:
            reasons.append("a request carries an unreadable price")
            continue
        parts[i] = part
        total += part
    if reasons:
        return None, "the transcripts could not be priced: " + "; ".join(sorted(set(reasons))), {}
    return total, "", parts


def _receipt(call):
    """The USD a remote call's receipt states (`usage_status` available with a `cost_usd`), as a
    Decimal; None when the call has no usable receipt (pending, unavailable, no cost, or a cost that
    is not a finite non-negative number): its cost is then unknown, never $0."""
    value = call.get("cost_usd")
    if call.get("usage_status") != "available" or value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() and amount >= ZERO else None


def external_forms_line(docs) -> str:
    """The line printed under a price: which external-agent forms its cost files counted calls for
    ("external calls counted for: testproject1, acme"), and, when a cost file names a `forms_problem`, the
    problem after a dash (the price is then already a range). A call of an agent whose form is in no
    row is indistinguishable from any shell command, so this list is the only way to see it is not
    counted (FR-41). A cost file with no `recognized_forms` (captured before the list existed) adds
    nothing; no file with one gives "" and the surface prints nothing."""
    forms, problems = _forms_facts(docs)
    if not forms:
        return ""
    line = "external calls counted for: " + ", ".join(forms)
    return line + " — " + "; ".join(problems) if problems else line


def _forms_facts(docs) -> tuple:
    """([recognized form ids], [forms problems]) over cost files, each once, in first-seen order: what
    the files' `external_reconciliation` says about the external-agent forms their calls were counted
    for. A file with no such field (captured before it existed) adds nothing."""
    forms, problems = {}, {}
    for doc in docs:
        found = doc.get("external_reconciliation") if isinstance(doc, dict) else None
        if not isinstance(found, dict):
            continue
        if isinstance(found.get("recognized_forms"), list):
            forms.update(dict.fromkeys(str(form) for form in found["recognized_forms"]))
        if found.get("forms_problem"):
            problems[str(found["forms_problem"])] = None
    return list(forms), list(problems)


def _calls_of_task(doc, scope, whole) -> list:
    """The remote calls (`external_calls`, with or without a receipt: the caller tells them apart
    by `_receipt`) that belong to the task's part of a session: all of them for a session the
    journal names whole; for a part of a session (a segment, a chat) only those observed inside the
    time span of the task's own requests. A call with no readable time is bound to no part: its
    `task` field is a marker, never evidence (FR-24)."""
    calls = [c for c in (doc.get("external_calls") if isinstance(doc.get("external_calls"), list) else [])
             if isinstance(c, dict)]
    if whole:
        return calls
    rows = _request_rows(doc)
    stamps = [t for t in (DJ.parse_ts(rows[i].get("timestamp")) for i in scope if isinstance(rows[i], dict)) if t]
    if not stamps:
        return []
    low, high = min(stamps), max(stamps)
    inside = []
    for call in calls:
        seen = DJ.parse_ts(call.get("observed_at"))   # one normalisation: a naive time is read as UTC
        if seen is not None and low <= seen <= high:
            inside.append(call)
    return inside


def _double_counted(rows) -> bool:
    """True when one request id is held by more than one stream of the file: a sidechain request
    counted in the main file and again in its agent file (E10)."""
    streams = {}
    for row in rows:
        if isinstance(row, dict) and row.get("request_id") and not str(row["request_id"]).startswith("carry:"):
            streams.setdefault(row["request_id"], set()).add(row.get("stream"))
    return any(len(s) > 1 for s in streams.values())


# ------------------------------------------------------------------------------------ the journal

def _rows_without_session(root, task) -> int:
    """Rows of the task's own driver journal that name no session the reader could bind: a call
    whose output was not JSON is journalled with `session_id: ""`, and its money is in neither
    record. A `delivery` row is no call at all and never counts, and neither does a `launched` row (t-363 B2):
    it is the START of a call whose end row follows it, with no session and no money of its own - counting it
    made every driver story's price `incomplete`."""
    count = 0
    for name, path in DJ._journal_paths(root):
        if name != task:
            continue
        for row in DJ.read_rows(path):
            if row.get("kind") in ("delivery", "launched"):
                continue
            sid = row.get("session_id")
            if not (isinstance(sid, str) and sid and DJ.REPLACEMENT_CHAR not in sid):
                count += 1
    return count


def _money_words(total, price_differs) -> str:
    """The money of a set of requests, in words: the transcripts' figure at the catalogue's list
    rates (and at the project's own rates when they differ); requests no record could price are
    said apart, the figure is then at least that much. The one wording shared by the contested
    sentence and the open-parent sentences (AR-15)."""
    money = _usd(total["list"])
    if price_differs and total["price"] != total["list"]:
        money += f" at the catalogue's list rates and {_usd(total['price'])} at the project's own rates"
    else:
        money += " at the catalogue's list rates"
    more = (f", and {_plural(total['unpriced'], 'request', 'requests')} could not be priced, so it is at least that much"
            if total["unpriced"] else "")
    return money + more


def _by_activity(doc) -> dict:
    by = doc.get("by_activity") if isinstance(doc, dict) else None
    return by if isinstance(by, dict) else {}


def _open_parent_rows(doc, act) -> tuple:
    """(open_rows, kept_rows): indexes of the request rows of `doc` made STRICTLY after the earliest
    row of `act` (the task's own story rows) that are bound to a non-story activity which may hold the
    story's money. open_rows: the activity is still `open`. kept_rows: the activity's
    `stop_resumed_segments` (a window opened when a story stopped, closed by the activity's own end)
    holds the row's segment. A row with no readable time counts: the allowed error is a false alarm,
    never a silent pass. `act` empty or without a readable time gives ([], [])."""
    rows = _request_rows(doc)
    by = _by_activity(doc)
    stamps = [t for t in (DJ.parse_ts(rows[i].get("timestamp")) for i in sorted(act)
                          if i < len(rows) and isinstance(rows[i], dict)) if t]
    if not stamps:
        return [], []
    first = min(stamps)
    open_rows, kept_rows = [], []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        a = by.get(r.get("activity_id"))
        if not isinstance(a, dict) or a.get("type") == "story":
            continue
        t = DJ.parse_ts(r.get("timestamp"))
        if t is not None and t <= first:
            continue
        if a.get("status") == "open":
            open_rows.append(i)
        else:
            held = a.get("stop_resumed_segments")
            if isinstance(held, list) and r.get("activity_segment_id") in held:
                kept_rows.append(i)
    return open_rows, kept_rows


def _parent_sentences(sid, doc, act, catalogue, cfg, price_differs) -> list:
    """The reasons (one sentence per list) that a session not named by a journal holds money after the
    story began that may be the story's but is bound to another activity. The money is named, never
    added to the price (the price is what is known). The recapture door is named only for a cost
    file captured before the stop-resumed rule (no `stop_resumed_parent` marker): only there does a
    recapture change the binding."""
    open_rows, kept_rows = _open_parent_rows(doc, act)
    rows, by = _request_rows(doc), _by_activity(doc)
    marked = isinstance(doc.get("attribution_provenance"), dict) \
        and bool(doc["attribution_provenance"].get("stop_resumed_parent"))
    out = []
    for indexes, kept in ((open_rows, False), (kept_rows, True)):
        if not indexes:
            continue
        total = {"list": ZERO, "price": ZERO, "unpriced": 0}
        _add_contested_money(total, doc, indexes, catalogue, cfg, price_differs)
        kinds = sorted({str((by.get(rows[i].get("activity_id")) or {}).get("type") or "other") for i in indexes})
        kind = " or ".join(kinds)
        n = len(indexes)
        head = (f"{_plural(n, 'request', 'requests')} of session {_short(sid)}, made after this story "
                f"began there, {'is' if n == 1 else 'are'} bound to a ")
        # The wording never claims a cause the cost file cannot show: it does not record which story
        # opened a window, nor whether an open activity began before or after this story.
        if kept:
            out.append(head + f"{kind} window opened while this story ran, which ended with the {kind}'s own end; "
                       f"the part before the {kind} was run again may be this story's: "
                       f"{_money_words(total, price_differs)}. This is a defect of the factory's measurement; "
                       "the price is what is known.")
            continue
        head += f"{kind} activity that was never closed and {'is' if n == 1 else 'are'} not in this price: " \
                f"{_money_words(total, price_differs)}. "
        if marked:
            out.append(head + f"Either this story ended without stopping at the end of a response while the {kind} "
                       f"activity stayed open, or the {kind} began after the story; the factory cannot tell whose "
                       "work this was; this is a defect of the factory's measurement, and the price is what is known.")
        else:
            out.append(head + "The file was captured before 0.10.3: if the story was stopped at the end of a "
                       f"response, `cost_capture.py --recapture --session {sid}` binds them again; until then "
                       "the price is what is known.")
    return out


def _contested_sentence(total, price_differs) -> str:
    """What the contested requests cost, in words: the transcripts' figure at the catalogue's list
    rates (and at the project's own rates when they differ), and that it is in no task's price. The
    CLI has no charge for them. Requests no record could price are said apart: the figure is then at
    least that much."""
    if total["list"] <= ZERO and total["unpriced"]:
        return ("The transcripts could not price them, so their money is unknown and is in no task's price "
                "(the CLI has no charge for them: no driver journal names their sessions).")
    money = _money_words(total, price_differs)
    return (f"Their money is in no task's price: the transcripts put it at {money} "
            "(the CLI has no charge for them: no driver journal names their sessions).")


def _stage_of(rows) -> str:
    for row in rows:
        stage = row.get("stage")
        if isinstance(stage, str) and stage.strip():
            return stage.strip()
    return ""


# ------------------------------------------------------------------------- rows by agent, checks

def _partition_reasons(buckets, a_total, a_price_total) -> list:
    """Why the rows by agent are not a partition of the task's requests: the sum of each money
    column over the rows must equal the total it is a split of (exact, in Decimal)."""
    reasons = []
    rows_a = sum((b["a"] for b in buckets.values()), ZERO)
    rows_price = sum((b["a_price"] for b in buckets.values()), ZERO)
    if rows_a != a_total:
        reasons.append(f"the rows by agent add up to {_usd(rows_a)} in the transcripts' column, "
                       f"the total is {_usd(a_total)}")
    if rows_price != a_price_total:
        reasons.append(f"the rows by agent add up to {_usd(rows_price)} at the price used, "
                       f"the total is {_usd(a_price_total)}")
    return reasons


def _price_pair_reasons(buckets, low, high, ranged) -> list:
    """Why the rows' price pair is not a split of the task's pair (P18): the rows' `low` column
    and `high` column must each add up to the task's figure, exact in Decimal. While the check
    fails the pair is a range (`ranged`), otherwise one figure (the point column, both times)."""
    lo_key, hi_key = ("lo", "hi") if ranged else ("pt", "pt")
    reasons = []
    rows_low = sum((b[lo_key] for b in buckets.values()), ZERO)
    rows_high = sum((b[hi_key] for b in buckets.values()), ZERO)
    if rows_low != low:
        reasons.append(f"the rows by agent add up to {_usd(rows_low)} in the low price, the task's low price is {_usd(low)}")
    if rows_high != high:
        reasons.append(f"the rows by agent add up to {_usd(rows_high)} in the high price, the task's high price is {_usd(high)}")
    return reasons


def _split(parts, total, target):
    """{index: share} of `target` over the request rows `parts` ({index: amount}, adding up to
    `total`), in proportion to the amounts; the shares add up to `target` EXACTLY (the last row
    takes the remainder, so no rounding is lost). None when `total` is 0: nothing to be
    proportional to, the caller puts `target` on the session's own row."""
    if total <= ZERO or not parts:
        return None
    if target == total:
        return dict(parts)
    out, used, order = {}, ZERO, sorted(parts)
    for i in order[:-1]:
        out[i] = target * parts[i] / total
        used += out[i]
    out[order[-1]] = target - used
    return out


def _session_range(a, ap, b) -> tuple:
    """(low, high, scaled) of ONE session on ONE rate base. `a` the transcripts at list price, `ap`
    at the price used (the project's override when it has one, else the same as `a`), `b` what the
    CLI charged. B carries no rate information, so it is put on the price base as B * ap / a
    before it meets `ap` (`b_on_price_base`, the one place that arithmetic lives); with `a` 0 or
    unknown it cannot be scaled and is used as is (`scaled` False). A session with one figure gives
    it as both ends. None, None when no figure."""
    if ap is not None and b is not None:
        b_on_price, scaled = b_on_price_base(a, ap, b)
        return min(ap, b_on_price), max(ap, b_on_price), scaled
    figure = ap if ap is not None else b
    return figure, figure, True


def _bucket(buckets, label) -> dict:
    return buckets.setdefault(label, {"agent": label, "sessions": set(), "a": ZERO, "a_price": ZERO,
                                      "b": ZERO, "a_known": 0, "a_price_known": 0, "b_known": 0,
                                      "b_unknown": 0, "a_unknown": 0, "differing": 0,
                                      "remote_calls": 0, "remote_usd": ZERO, "remote_receipts": 0,
                                      "lo": ZERO, "hi": ZERO, "pt": ZERO, "price_known": False})


def _empty_result(task, revision, reason, finding_extra=()) -> dict:
    finding = " ".join([reason, *finding_extra]).strip()
    return {"status": INCOMPLETE, "sessions": [], "by_agent": [],
            "totals": {"a": 0.0, "b": 0.0, "a_comparable": 0.0, "b_comparable": 0.0, "a_price": 0.0},
            "differ": [], "one_record": [], "unknown": [], "in_progress": [],
            "catalogue_revision": revision, "finding": finding, "compared": f"nothing was compared: {reason}",
            "rows_without_session": 0, "rate_overrides": [], "not_estimated_agents": [], "single_source": False}


# --------------------------------------------------------------------------------- the function

def task_price(root, task, sessions=None, driver=None, catalogue=None, cfg=None) -> dict:
    """The price of `task` from two records, and the check of one against the other.

    `sessions`: the cost files already loaded ({session: doc} or a list of docs); else read from
    `root` (qa-factory/state/cost/*.json). Always passed through `revalue_document`, never read at
    their pinned money. `driver`: the `parse_driver_runs` result; else read from `root`. Values
    passed in win: nothing is read from disk for them. `cfg`: the project's `cost` block (else
    read from `root`'s config.json); `catalogue`: the parsed model-rates.json (else the bundled).
    `root` None with nothing passed -> incomplete with the reason.

    status (R7; precedence differs > incomplete > not_cross_checked > agrees):
      differs            any comparable session (both records known, not in progress) differs
      incomplete         no session has a record; or a session is in neither record; or a journal
                         row of the task names no session (its money is in neither record); or the
                         rows by agent do not add up to the total; or an agent of the task ran (it has
                         tool calls) but its usage was not read (tokens 0): its cost is not estimated and the
                         price is at least the figure shown (`not_estimated_agents`, `differs` still wins)
      not_cross_checked  no comparable session (orchestrator-mode story, chat, falls, live)
      agrees             every session has a record, at least one is comparable, none differs
    price_low_usd / price_high_usd: the price is A re-priced WITH the project's `rate_overrides`
    (the person's correction IS the price; the check still compares list-price A with B) over the
    task's sessions, a session with one record contributing its one figure, plus the receipts of
    remote calls that left one. While status is `differs` the range is built on ONE rate base, per
    session: B is put on the price base (B * A_price / A; with A 0 or unknown, B as is), low is the
    sum over sessions of min(A_price, B on the price base), high the sum of max; a session with one
    record adds its figure to BOTH ends. Otherwise low == high (every session at its price).
    Keys are absent when no session has a record. Each row by agent carries its share of the same
    pair, and the shares add up to the task's pair, or the status is `incomplete` with the reason.

    `not_estimated_agents`: always present, `[{"agent", "session", "tools": n}]` (n = tool calls), `[]` when
    every agent of the task has usage or did nothing. `price_low_usd` / `price_high_usd` keep their types.

    Per-session verdict: agrees | differs | one_record | unknown | in_progress. A session with a
    transcript touched inside RECAPTURE_LIVE_WINDOW_S is in_progress: in no comparison, still
    priced by its known figure(s)."""
    catalogue = catalogue if isinstance(catalogue, dict) and catalogue else CC.load_catalogue()
    revision = catalogue.get("catalogue_revision")
    if not isinstance(task, str) or not task.strip():
        return _empty_result(task, revision, "No task id was given.")
    if root is None and sessions is None and driver is None:
        return _empty_result(task, revision, "No project root was given and no cost files or journal "
                                              "were passed in, so there is nothing to read.")
    if cfg is None:
        cfg = _project_cost_cfg(root) if root is not None else {}
    cfg = cfg if isinstance(cfg, dict) else {}
    price_differs = _prices_differ_from_list(cfg)
    idle_s = CC.final_idle_s(cfg, [])   # the window "still being written": one word for the page and the retro

    docs = _docs_from(sessions) if sessions is not None else (_read_cost_docs(root) if root is not None else {})
    driver_passed = driver is not None
    if driver_passed:
        first = driver[0] if isinstance(driver, (tuple, list)) and driver else driver
        by_session = first if isinstance(first, dict) else {}
    elif root is not None:
        by_session = DJ.parse_driver_runs(root)[0]
    else:
        by_session = {}
    charged, unknown_why = DJ.root_charged(by_session)
    why_b = dict(unknown_why)
    # Rows of the task's own journal that name no session are counted from the ROOT's journal file
    # whenever a root is given, even when the parsed journal was passed in (the dashboard passes
    # it): a passed-in result cannot hold them, the file can. Invariant: the check is off only when
    # there is nowhere to read them from (no root), and the finding then says so.
    sessionless = _rows_without_session(root, task) if root is not None else 0

    # ---- which sessions are the task's (R5), by evidence only
    members = {}
    contested = []   # (session, request name, tasks) claimed by two tasks: nobody's
    contested_usd = {"list": ZERO, "price": ZERO, "unpriced": 0}   # what the transcripts say those requests cost
    for sid, entry in by_session.items():
        if isinstance(entry, dict) and entry.get("task") == task:
            members[sid] = {"entry": entry, "doc": docs.get(sid), "act": set(), "chat": set()}
    for sid, doc in sorted(docs.items()):
        if sid in by_session:
            continue
        act, chat, clash = _own_requests(doc, task)
        contested.extend((sid, _request_name(doc, i), tasks) for i, tasks in sorted(clash.items()))
        if clash:
            _add_contested_money(contested_usd, doc, sorted(clash), catalogue, cfg, price_differs)
        if act or chat:
            members[sid] = {"entry": None, "doc": doc, "act": act, "chat": chat}

    buckets, session_rows = {}, []
    models_at_project_rate, models_at_family_rate, override_only = set(), set(), {}
    remote_calls, remote_receipts, dup_sessions, rates_fell_back = {}, {}, set(), 0
    sums = {"a": ZERO, "b": ZERO, "a_cmp": ZERO, "b_cmp": ZERO, "a_price": ZERO, "lo": ZERO, "hi": ZERO, "pt": ZERO}
    unscaled = []   # sessions whose B could not be put on the price base (A is 0 or unknown)
    facts = {}
    parent_reasons = []   # money bound to another activity after the story began (never added to the price)

    for sid in sorted(members):
        member, doc, entry = members[sid], members[sid]["doc"], members[sid]["entry"]
        journal_rows = entry["rows"] if entry else []
        if entry:
            label, stage = DJ.agent_label(journal_rows), _stage_of(journal_rows)
        else:
            label = DJ.agent_label({"source": "chat" if (member["chat"] and not member["act"]) else "orchestrator"})
            stage = ""
        a = a_price = None
        a_why, per_list, per_price, scope = "", {}, {}, []
        if doc is None:
            a_why = "no cost file for this session"
        else:
            rows_l = _request_rows(CC.revalue_document(doc, {}, catalogue))
            rows_p = _request_rows(CC.revalue_document(doc, cfg, catalogue)) if price_differs else rows_l
            scope = sorted(range(len(rows_l)) if entry else member["act"] | member["chat"])
            if not rows_l:
                a_why = "the cost file holds no request ledger"
            else:
                a, a_why, per_list = _sum_rows(rows_l, scope)
                a_price, _why_p, per_price = _sum_rows(rows_p, scope)
                if price_differs:
                    if a_price is None and a is not None:
                        a_price, per_price, rates_fell_back = a, dict(per_list), rates_fell_back + 1
                    for i in scope:
                        kind = ((rows_p[i].get("valuation") or {}).get("rate_provenance") or {}).get("kind") \
                            if isinstance(rows_p[i], dict) else None
                        model = rows_p[i].get("model_id") if isinstance(rows_p[i], dict) else None
                        listed = isinstance(rows_l[i], dict) and isinstance(rows_l[i].get("valuation"), dict) \
                            and rows_l[i]["valuation"].get("pricing_coverage") == "complete"
                        if kind == "project_override" and model:
                            models_at_project_rate.add(model)
                            if not listed:
                                override_only.setdefault(sid, set()).add(model)
                        elif kind == "legacy_project_override" and model:
                            models_at_family_rate.add(model)
                    if a is None and a_price is not None:
                        # The catalogue cannot price it, the project's own rate can: say THAT, not
                        # the list-price reason ("unknown to rate_overrides") and not "the CLI's
                        # charge alone" (F7: the price is the project's rate).
                        if override_only.get(sid):
                            a_why = ("the catalogue does not list " + ", ".join(sorted(override_only[sid])) +
                                     "; priced at the project's own rate for " + ", ".join(sorted(override_only[sid])))
                        else:
                            a_why = "the catalogue does not list the model; priced at the project's family rate"
                if _double_counted(rows_l):
                    dup_sessions.add(sid)
            for call in _calls_of_task(doc, scope, bool(entry)):
                remote_label = DJ.agent_label({"source": "remote", "consumer_agent": call.get("consumer_agent")})
                receipt = _receipt(call)
                if receipt is None:
                    remote_calls.setdefault(remote_label, []).append((sid, call))
                else:
                    remote_receipts.setdefault(remote_label, []).append((sid, receipt))
        if a is None and a_price is None and not a_why:
            a_why = "no cost file for this session"
        if not entry and doc is not None:
            parent_reasons.extend(_parent_sentences(sid, doc, member["act"], catalogue, cfg, price_differs))

        if entry:
            b, b_why = _dec(charged.get(sid)), ""
            if b is None:
                code = why_b.get(sid, DJ.WHY_NO_TOTAL)
                b_why = "the CLI's charge is unknown: " + WHY_WORDS.get(code, code)
        else:
            b, b_why = None, "no driver journal names this session"

        age = None
        if doc is not None:
            _size, age = CC.transcript_footprint(doc.get("transcript"))
        # "Still being written": inside the pass's own window always; inside the project's idle limit
        # (`cost.usage_final_after_idle_min`) unless the driver's line carries a recorded charge, which proves the
        # process ended (a line with a price is written when the CLI exits). One stat, not `session_settled`.
        live = age is not None and (age < CC.RECAPTURE_LIVE_WINDOW_S
                                    or (age < idle_s and not (entry and b is not None)))

        if a is None and b is None and a_price is None:
            verdict, why = V_UNKNOWN, f"{a_why}; {b_why}"
        elif live:
            verdict, why = V_IN_PROGRESS, f"the transcript changed {int(age)} s ago: the session is still being written"
        elif a is None or b is None:
            verdict = V_ONE_RECORD
            why = a_why if a is None else b_why
        elif abs(a - b) <= TOLERANCE_USD:
            verdict, why = V_AGREES, ""
        else:
            verdict = V_DIFFERS
            why = f"the transcripts at catalogue rates say {_usd(a)}, the CLI charged {_usd(b)}"
            if sid in dup_sessions:
                why += "; one request id is counted in two streams of the cost file"

        row = {"session": sid, "agent": label, "stage": stage, "a_usd": _float(a), "b_usd": _float(b),
               "a_price_usd": _float(a_price), "verdict": verdict, "why": why}
        session_rows.append(row)
        facts[sid] = {"a": a, "b": b, "a_price": a_price, "entry": entry, "journal": bool(entry)}

        # ---- rows by agent
        home = _bucket(buckets, label)
        home["sessions"].add(sid)
        if b is not None:
            home["b"] += b
            home["b_known"] += 1
        else:
            home["b_unknown"] += 1
        home["differing"] += 1 if verdict == V_DIFFERS else 0
        if a is None:
            home["a_unknown"] += 1
        for column, parts in (("a", per_list if a is not None else {}),
                              ("a_price", per_price if a_price is not None else {})):
            for i, amount in parts.items():
                owner = _bucket(buckets, _request_label(doc, _request_rows(doc)[i], label, member["chat"], i))
                owner["sessions"].add(sid)
                owner[column] += amount
                owner[column + "_known"] = 1

        # ---- sums
        if a is not None:
            sums["a"] += a
        if a_price is not None:
            sums["a_price"] += a_price
        if b is not None:
            sums["b"] += b
        if verdict in (V_AGREES, V_DIFFERS):
            sums["a_cmp"] += a
            sums["b_cmp"] += b
        # The session's price figure (A at the price used, else B alone) and its range on ONE rate
        # base; `lo`/`hi` are used while the check fails, `pt` otherwise. Each is also split over the
        # rows by agent: the request rows in proportion to their price, a B-only session on its own row.
        low, high, scaled = _session_range(a, a_price, b)
        if low is not None:
            sums["lo"] += low
            sums["hi"] += high
            sums["pt"] += a_price if a_price is not None else b
            home["price_known"] = True
            if a_price is None:
                home["lo"] += low
                home["hi"] += high
                home["pt"] += b
            else:
                for key, target in (("lo", low), ("hi", high)):
                    shares = _split(per_price, a_price, target)
                    if shares is None:
                        home[key] += target
                    for i, share in (shares or {}).items():
                        owner = _bucket(buckets, _request_label(doc, _request_rows(doc)[i], label, member["chat"], i))
                        owner[key] += share
                        owner["price_known"] = True
                for i, amount in per_price.items():
                    owner = _bucket(buckets, _request_label(doc, _request_rows(doc)[i], label, member["chat"], i))
                    owner["pt"] += amount
                    owner["price_known"] = True
            if a_price is not None and b is not None and not scaled:
                unscaled.append(sid)

    # remote calls: a call with a receipt is in the price and in its row; one with no receipt keeps a
    # row whose cost is UNKNOWN (never $0, never dropped). Both add the same amount to both ends.
    remote_usd = ZERO
    for remote_label, calls in sorted(remote_calls.items()):
        bucket = _bucket(buckets, remote_label)
        bucket["sessions"] |= {sid for sid, _call in calls}
        bucket["remote_calls"] = len(calls)
    for remote_label, receipts in sorted(remote_receipts.items()):
        bucket = _bucket(buckets, remote_label)
        bucket["sessions"] |= {sid for sid, _amount in receipts}
        amount = sum((value for _sid, value in receipts), ZERO)
        bucket["remote_usd"] += amount
        bucket["remote_receipts"] = len(receipts)
        for key in ("lo", "hi", "pt"):
            bucket[key] += amount
        bucket["price_known"] = True
        remote_usd += amount
    remote_total = sum(b["remote_calls"] for b in buckets.values())
    receipts_total = sum(b["remote_receipts"] for b in buckets.values())

    by_verdict = lambda v: [dict(r) for r in session_rows if r["verdict"] == v]  # noqa: E731
    differ, one_record, unknown, in_progress = (by_verdict(V_DIFFERS), by_verdict(V_ONE_RECORD),
                                                by_verdict(V_UNKNOWN), by_verdict(V_IN_PROGRESS))
    comparable = [r for r in session_rows if r["verdict"] in (V_AGREES, V_DIFFERS)]
    has_record = any(f["a"] is not None or f["b"] is not None or f["a_price"] is not None for f in facts.values())

    # The price pair: a RANGE only while a comparable session differs (status `differs`), else one
    # figure. Receipts of remote calls are the same amount at both ends.
    ranged = bool(differ)
    price_low = (sums["lo"] if ranged else sums["pt"]) + remote_usd
    price_high = (sums["hi"] if ranged else sums["pt"]) + remote_usd
    partition = _partition_reasons(buckets, sums["a"], sums["a_price"])
    if has_record:
        partition += _price_pair_reasons(buckets, price_low, price_high, ranged)
    incomplete_reasons = []
    if not has_record:
        incomplete_reasons.append("No session of this task has a record.")
    if unknown:
        incomplete_reasons.append(
            f"{_plural(len(unknown), 'session is', 'sessions are')} in neither record (" +
            "; ".join(f"{_short(r['session'])} ({r['agent']}): {r['why']}" for r in unknown[:5]) +
            ("; and more" if len(unknown) > 5 else "") + ")." )
    if sessionless:
        incomplete_reasons.append(
            f"The driver's journal holds {_plural(sessionless, 'call', 'calls')} with no session id (the call's "
            f"output was not JSON): the money of {'it' if sessionless == 1 else 'them'} is in neither record.")
    if partition:
        incomplete_reasons.append("The rows by agent are not a split of the total: " + "; ".join(partition) +
                                  ". This is a defect of the factory's measurement.")
    incomplete_reasons.extend(parent_reasons)
    # An agent that ran (it has tool calls) but whose usage was never read (tokens 0) has a cost that is in
    # neither record: the price is a floor, never one exact figure (CD1-13, AR-28). Only an agent of THIS task:
    # its own `task`, or any agent of a session the driver's journal binds whole to the task. An idle agent
    # (no tool calls) is not a gap (E-C5). `incomplete` yields to `differs` below, as for every other reason.
    not_estimated = []
    for sid in sorted(members):
        member_doc = members[sid]["doc"]
        for agent in (member_doc.get("agents") if isinstance(member_doc, dict) else None) or []:
            calls = unread_agent_calls(agent)
            if calls > 0 and (members[sid]["entry"] is not None or agent.get("task") == task):
                not_estimated.append({"agent": str(agent.get("agent") or agent.get("file") or "?"),
                                      "session": sid, "tools": int(calls)})
    if not_estimated:
        names = ", ".join(r["agent"] for r in not_estimated[:MAX_NAMED]) + (", and more" if len(not_estimated) > MAX_NAMED else "")
        incomplete_reasons.append(
            f"{_plural(len(not_estimated), 'agent', 'agents')} of this task ran but "
            f"{'its' if len(not_estimated) == 1 else 'their'} usage was not read ({names}): "
            f"{'its' if len(not_estimated) == 1 else 'their'} cost is not estimated, so the price is at least the figure shown.")
    # A cost file whose external-agent forms had a problem (unreadable data, a refused row) cannot say
    # which calls of an outside agent were never looked for: the price is what is known, never one
    # figure (E-D3, FR-41). `external_reconciliation.complete` is NOT read: a pending call is said below.
    forms_problems = _forms_facts(m["doc"] for m in members.values())[1]
    if forms_problems:
        incomplete_reasons.append("Calls of an external agent may be missing from this price, because " +
                                  "; ".join(forms_problems) + ".")

    if forms_problems:
        status = INCOMPLETE
    elif differ:
        status = DIFFERS
    elif incomplete_reasons:
        status = INCOMPLETE
    elif not comparable:
        status = NOT_CROSS_CHECKED
    else:
        status = AGREES

    # ---- finding: plain words, the factory's own defects said as such (FR-3, FR-6)
    finding = []
    if differ:
        biggest = max(differ, key=lambda r: (abs(Decimal(repr(r["a_usd"])) - Decimal(repr(r["b_usd"]))), r["session"]))
        gap = sum((abs(Decimal(repr(r["a_usd"])) - Decimal(repr(r["b_usd"]))) for r in differ), ZERO)
        finding.append(f"For {len(differ)} of {_plural(len(comparable), 'session', 'sessions')} the transcripts at catalogue rates "
                       f"and the CLI's own charge differ.")
        finding.append(f"The largest is {_short(biggest['session'])} ({biggest['agent']}"
                       f"{', ' + biggest['stage'] if biggest['stage'] else ''}): transcripts "
                       f"{_usd(Decimal(repr(biggest['a_usd'])))}, CLI {_usd(Decimal(repr(biggest['b_usd'])))}.")
        finding.append(f"The total difference over these sessions is {_usd(gap)}.")
        lower = sum(1 for r in differ if r["a_usd"] < r["b_usd"])
        if lower == len(differ):
            finding.append("In all of them the transcripts are the lower figure.")
        elif lower == 0:
            finding.append("In all of them the transcripts are the higher figure.")
        finding.append("This is a defect of the factory's measurement, not a fact about the story.")
    finding.extend(incomplete_reasons)
    cli_unknown = [r for r in one_record if r["b_usd"] is None and r["a_usd"] is not None and facts[r["session"]]["journal"]]
    if cli_unknown:
        reasons = {}
        for r in cli_unknown:
            reasons[r["why"].split(": ", 1)[-1]] = reasons.get(r["why"].split(": ", 1)[-1], 0) + 1
        finding.append(f"The CLI's own charge is unknown for {_plural(len(cli_unknown), 'session', 'sessions')} (" +
                       "; ".join(f"{n} because {why}" for why, n in sorted(reasons.items())) +
                       "); their price comes from the transcripts alone.")
    # A session the transcripts could not price at list price but the project's own rate did (a_price
    # known) is NOT "the CLI's charge alone": its price is the project's rate.
    no_a = [r for r in one_record if r["a_usd"] is None and r["b_usd"] is not None and r["a_price_usd"] is None]
    if no_a:
        finding.append(f"The transcripts could not be priced for {_plural(len(no_a), 'session', 'sessions')} "
                       f"({'; '.join(sorted({r['why'] for r in no_a}))}); their price is the CLI's charge alone.")
    if override_only:
        models = sorted({m for found in override_only.values() for m in found})
        only = [r for r in one_record if r["session"] in override_only and r["a_usd"] is None and r["a_price_usd"] is not None]
        if only:
            finding.append(f"For {_plural(len(only), 'session', 'sessions')} the catalogue does not list the model, so the "
                           f"check cannot compare {'it' if len(only) == 1 else 'them'}: priced at the project's own rate for "
                           + ", ".join(models) + ".")
    if in_progress:
        finding.append(f"{_plural(len(in_progress), 'session is', 'sessions are')} still being written and "
                       f"{'was' if len(in_progress) == 1 else 'were'} not compared.")
    if driver_passed and root is None:
        finding.append("Rows of the driver's journal that name no session were not looked for: the journal "
                       "was passed in already read and no project root was given to read the journal file from.")
    if contested:
        named = "; ".join(f"{req} of {_short(sid)} ({' and '.join(tasks)})" for sid, req, tasks in contested[:5])
        finding.append(f"{_plural(len(contested), 'request is', 'requests are')} bound to more than one task by the evidence "
                       f"and {'is' if len(contested) == 1 else 'are'} counted under none of them: " + named +
                       ("; and more" if len(contested) > 5 else "") + ". " + _contested_sentence(contested_usd, price_differs))
    if ranged and price_differs and unscaled:
        finding.append(f"For {_plural(len(unscaled), 'session', 'sessions')} ({', '.join(_short(s) for s in unscaled[:5])}"
                       f"{', and more' if len(unscaled) > 5 else ''}) the CLI's charge is used as it stands in the range: "
                       f"the transcripts at list price are $0 or unknown, so it cannot be put on the project's rate.")
    if models_at_project_rate:
        finding.append("Priced at the project's own rates: " + ", ".join(sorted(models_at_project_rate)) +
                       ". The check compares catalogue list prices, which are what the CLI charges.")
    if models_at_family_rate:
        finding.append("Priced at the project's family rate because the catalogue does not list the model: " +
                       ", ".join(sorted(models_at_family_rate)) + ".")
    if rates_fell_back:
        finding.append(f"For {_plural(rates_fell_back, 'session', 'sessions')} the project's own rates could not "
                       f"price every request, so the catalogue's list price was used.")
    if receipts_total:
        finding.append(f"{_plural(receipts_total, 'remote agent call', 'remote agent calls')} left a receipt of "
                       f"{_usd(remote_usd)}, which is in the price.")
    if remote_total:
        finding.append(f"{_plural(remote_total, 'remote agent call', 'remote agent calls')} left no receipt: "
                       f"{'its' if remote_total == 1 else 'their'} cost is unknown and is not in the price.")
    warning = DJ.label_data_warning()   # a broken agent-label table: one line, never an exception
    if warning:
        finding.append(warning)

    journal_named = sum(1 for f in facts.values() if f["journal"])
    if not has_record:
        compared = "nothing was compared: no session of this task has a record"
    elif journal_named:
        compared = (f"the CLI's own charge for the {_plural(journal_named, 'session', 'sessions')} the driver's journal names; "
                    f"{len(one_record)} priced from one record")
    else:
        compared = (f"nothing was compared: the driver's journal names no session of this task; "
                    f"{len(one_record)} priced from one record")
    if remote_total:
        compared += ("; the price covers the model sessions and the remote calls with a receipt only" if receipts_total
                     else "; the price covers the model sessions only")

    by_agent = []
    lo_key, hi_key = ("lo", "hi") if ranged else ("pt", "pt")
    for bucket in buckets.values():
        by_agent.append({
            "agent": bucket["agent"], "sessions": len(bucket["sessions"]),
            "a_usd": _float(bucket["a"]) if bucket["a_known"] else None,
            "a_price_usd": _float(bucket["a_price"]) if bucket["a_price_known"] else None,
            "b_usd": _float(bucket["b"]) if bucket["b_known"] else None,
            "price_low_usd": _float(bucket[lo_key]) if bucket["price_known"] else None,
            "price_high_usd": _float(bucket[hi_key]) if bucket["price_known"] else None,
            "remote_usd": _float(bucket["remote_usd"]) if bucket["remote_receipts"] else None,
            "b_unknown": bucket["b_unknown"], "a_unknown": bucket["a_unknown"],
            "differing_sessions": bucket["differing"], "remote_calls": bucket["remote_calls"]})
    by_agent.sort(key=lambda r: (-max(r["a_usd"] or 0.0, r["b_usd"] or 0.0, r["remote_usd"] or 0.0), r["agent"]))

    result = {
        "status": status, "sessions": session_rows, "by_agent": by_agent,
        "totals": {"a": float(sums["a"]), "b": float(sums["b"]), "a_comparable": float(sums["a_cmp"]),
                   "b_comparable": float(sums["b_cmp"]), "a_price": float(sums["a_price"])},
        "differ": differ, "one_record": one_record, "unknown": unknown, "in_progress": in_progress,
        "catalogue_revision": revision, "finding": " ".join(finding), "compared": compared,
        "rows_without_session": sessionless, "rate_overrides": sorted(models_at_project_rate),
        "not_estimated_agents": not_estimated,
        "external_forms_line": external_forms_line(m["doc"] for m in members.values()),
        # Information, not a finding: the chat is the only record and there is nothing to check it against. Never
        # true while a session is still written, when the CLI's charge is unknown, with nothing recorded, or while known
        # money is missing from the price (a remote call with no receipt, a request counted under no task): information
        # never hides a gap (P18, AR-27), so those fall back to the old `skip`.
        "single_source": (status == NOT_CROSS_CHECKED and journal_named == 0 and not in_progress and not cli_unknown
                          and not remote_total and not contested)}
    if has_record:
        result["price_low_usd"], result["price_high_usd"] = float(price_low), float(price_high)
    return result
