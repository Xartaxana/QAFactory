"""A ceiling on what one story may cost, in money or in tokens.

Until now nothing capped a story. Role budgets bound a dispatch, the turn budget bounds a
window, and between them a story could spend whatever it liked: one pilot's retro alone ate
a weekly limit, and the person learned of it from the provider rather than from the factory.
The ceiling lives in the project's own config, because what a story may cost is a business
number and not a factory opinion:

    "budget": {"story_usd": null, "story_tokens": null, "warn_at": [0.5, 0.8]}

Every field is optional and `null` means no ceiling — a project that sets nothing keeps
exactly the behaviour it had. Each threshold warns ONCE (the marker lives in
`state/budget/<task>.json`, project state, disposable); at 100% the line stops and asks.

The money it polices is read from the ONE price function (`task_price`, asked once), session by
session: the CLI's own charge where it is known, else the transcripts priced at the catalogue's
rates, never the larger of the two (`ceiling_figure`). When the project prices at its own rates,
the CLI's charge is put on those rates per session first, so the ceiling reads the same rates as
the price. When the two records differ for a session the notice says the figure is disputed, by
how much, and which record was compared.

It stops and asks; it does not decide. A person's word passes any block in this factory, so
the stop line names the call that records the answer:

    waiver.py --task <T> --stage <S> --block "story budget" --words-file <file>

(`<file>` holds their words as they were given, UTF-8: a command line cannot carry them whole
through cmd.exe), and from then on `check()` reports `overridden` with those words and the
story continues. The ceiling exists to make a runaway visible at the moment it happens, never to end
somebody's work on an arithmetic threshold.

  story_budget.py --task TP1-15045              # the notice, or nothing
  story_budget.py --task TP1-15045 --json
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402  (`read_json`, the one JSON reader)
from hooklib import artifacts_dir, require_project, state_dir  # noqa: E402
from person_words import door  # noqa: E402

DEFAULT_WARN_AT = (0.5, 0.8)


def limits(cfg: dict) -> dict:
    """{story_usd, story_tokens, warn_at} from config.budget, all optional, null = no cap."""
    block = (cfg or {}).get("budget") or {}
    def number(key):
        value = block.get(key)
        return float(value) if isinstance(value, (int, float)) and value > 0 else None
    warn = block.get("warn_at")
    marks = []
    if isinstance(warn, list):
        for item in warn:
            if isinstance(item, (int, float)) and 0 < float(item) < 1:
                marks.append(round(float(item), 4))
    return {"story_usd": number("story_usd"), "story_tokens": number("story_tokens"),
            "warn_at": sorted(set(marks)) or list(DEFAULT_WARN_AT)}


def read_config(root: Path) -> dict:
    """`root/config.json` as parsed, else {}. `root` is always a Path: its one caller, `check`, builds `base` itself, so
    `Path(root)` no longer needs a guard of its own (t-666 R1, E6)."""
    return hooklib.read_json(Path(root) / "config.json", {}, errors=Exception)


def marker_path(task: str, root: Path | None = None) -> Path:
    base = Path(root) if root is not None else state_dir()
    safe = "".join(c for c in str(task) if c.isalnum() or c in "-_")[:64] or "unknown"
    return base / "state" / "budget" / f"{safe}.json"


def read_marker(path: Path) -> dict:
    return hooklib.read_json(path, {}, kind=dict, errors=Exception)


def override(pipeline: dict) -> dict | None:
    """The person's recorded decision to carry on past the ceiling, whatever stage it was
    made at. `waiver.py --block "story budget"` writes it; `*` covers it as it covers
    every other block of that stage."""
    import contract
    for entry in contract.live_stage_overrides(pipeline):        # a revoked word acts nowhere, `*` included (GW1-1)
        match = str(entry.get("match") or "").lower()
        if match == "*" or "budget" in match:
            return entry
    return None


def ceiling_figure(price: dict) -> dict:
    """What the money ceiling polices, from `task_price`'s sessions (one call, no other reading).

    PER SESSION: the CLI's own charge (B) where it is known, else the transcripts' price (A) -
    never max(A, B). A double count in A (a sidechain request counted in two streams of a cost
    file, a capture that read a request twice) raises A above the truth, and a ceiling that took
    the larger figure would stop a story on the factory's own measurement defect, which is the
    wrong direction for a stop (P1 of the owner's principles: code reports, it does not halt the
    factory on what it cannot vouch for). B is what the CLI charged and has no parser of ours in
    it. Where B is not known (no journal names the session, the journal's totals fall, a
    per-call journal) A is the only figure and is used and SAID; a session known to neither is
    counted `unknown` and the figure is a floor. A session whose two records differ is DISPUTED:
    the ceiling uses B, and the figure says by how much A would differ and what A would make the
    total (`alt_usd`). `a_usd` here is the price used (`a_price_usd`: the project's own rate when
    it has one) and, when that is unknown, the list price.

    ONE RATE BASE. B is what the CLI charged at the catalogue's list rates and carries no rate
    information; the price is at the project's own rates when it has some (P18: a person's price
    replaces the catalogue's). A ceiling that compared list-price B with a price at the person's
    rates let a story at $26.14 read "87% of $20" (the recaptured cmp1 with a 1.5x override). So B is
    put on the price base per session, by the price function's own rule (`task_price.b_on_price_base`:
    `B * price / list` when the list price is above 0, B as it stands when it is 0 or unknown: then
    the session is named in `unscaled`, and the notice says so). Without project rates the price base
    IS the list price and every figure is what it was.

    Summed in Decimal from each figure's shortest spelling, never rounded: a total that is
    exactly the ceiling is exactly the ceiling."""
    import task_price as TP

    def dec(value):
        return Decimal(repr(float(value)))

    total = alt = gap = Decimal("0")
    by_cli = by_transcripts = unknown = disputed = 0
    unscaled, on_project = [], bool(price.get("rate_overrides"))
    for row in price.get("sessions") or []:
        if not isinstance(row, dict):
            continue
        b = row.get("b_usd")
        a_list = dec(row["a_usd"]) if row.get("a_usd") is not None else None
        a = dec(row["a_price_usd"]) if row.get("a_price_usd") is not None else a_list
        if a is not None and a != a_list:     # a price that is not the list price (or a price with no list price)
            on_project = True
        if b is not None:
            figure, scaled = TP.b_on_price_base(a_list, a, dec(b))
            other = a if a is not None else figure
            by_cli += 1
            if not scaled:
                unscaled.append(str(row.get("session")))
        elif a is not None:
            figure = other = a
            by_transcripts += 1
        else:
            unknown += 1
            continue
        if row.get("verdict") == "differs":
            disputed += 1
            gap += abs(figure - other)
        total += figure
        alt += other
    counted = by_cli + by_transcripts
    return {"usd": float(total) if counted else None, "alt_usd": float(alt) if counted else None,
            "sessions": counted, "by_cli": by_cli, "by_transcripts": by_transcripts,
            "unknown": unknown, "disputed": disputed, "gap_usd": float(gap),
            "on_project_rates": on_project, "unscaled": unscaled if on_project else []}


def figure_notes(figure: dict) -> str:
    """The sentences a notice adds about HOW the ceiling's figure was read, in plain words (FR-6):
    a disputed figure says which record was compared and what the other would make it; a session
    priced by the transcripts alone says so. Empty when the two records agree throughout."""
    notes = ""
    project = bool(figure.get("on_project_rates"))
    if project:
        notes += (" The price is at the project's own rates, and the CLI's own charge (which is at the catalogue's "
                  "list rates) is put on them session by session, so the figure is on the same rates as the price.")
    if figure.get("unscaled"):
        ids = figure["unscaled"]
        notes += (f" For {_plural(len(ids), 'session', 'sessions')} ({', '.join(str(s)[:8] for s in ids[:5])}"
                  f"{', and more' if len(ids) > 5 else ''}) it could not be put on them, because the transcripts at the "
                  f"catalogue's rates are $0 or unknown: the CLI's charge stands as it is for "
                  f"{'that session' if len(ids) == 1 else 'those sessions'}.")
    if figure.get("disputed"):
        notes += (f" The figure is disputed: for {_plural(figure['disputed'], 'session', 'sessions')} the CLI's own "
                  f"charge and the transcripts priced at the catalogue's rates differ, by ${figure['gap_usd']:,.2f} in "
                  f"all{' once both are on the project rates' if project else ''}. The ceiling is compared against the "
                  f"CLI's charge{' on those rates' if project else ''}; the transcripts would make it "
                  f"${figure['alt_usd']:,.2f}.")
    if figure.get("by_transcripts"):
        notes += (f" For {_plural(figure['by_transcripts'], 'session', 'sessions')} the CLI's own charge is unknown, "
                  "so the transcripts' price is used for them.")
    return notes


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def floor_percent(ratio) -> int:
    """The percentage a notice prints, FLOORED and never rounded: "100%" appears only at or over
    the limit. A story at 99.5% printed "at 100%" while `check` had not yet stopped it, and a
    person reads that line as "the ceiling is reached", which is the one thing the stop rule
    (at the limit = reached; one cent under = warn) keeps apart. Computed on the ratio's shortest
    decimal spelling, so 0.29 is 29 and not the 28 that 28.999999999999996 would floor to."""
    return int((Decimal(repr(float(ratio))) * 100).to_integral_value(rounding=ROUND_FLOOR))


def ratios(spend: dict, caps: dict) -> dict:
    out = {}
    if caps["story_usd"] and isinstance(spend.get("usd"), (int, float)):
        out["usd"] = spend["usd"] / caps["story_usd"]
    if caps["story_tokens"] and spend.get("tokens"):
        out["tokens"] = float(spend["tokens"]) / caps["story_tokens"]
    return out


def check(task: str, root: Path | None = None, task_root: Path | None = None) -> dict:
    """{capped, ratio, level, stop, notice, overridden, spend, limits}.

    `notice` is "" whenever there is nothing new to say — a threshold already warned about
    does not warn again, and a story with no ceiling never says anything at all."""
    result = {"task": task, "capped": False, "ratio": None, "level": None, "stop": False,
              "notice": "", "overridden": None, "spend": {}, "limits": {}}
    try:
        base = Path(root) if root is not None else state_dir()
        caps = limits(read_config(base))
        result["limits"] = caps
        if not caps["story_usd"] and not caps["story_tokens"]:
            return result  # no ceiling configured — nothing to police
        result["capped"] = True
        import retro_numbers
        # ONE `task_price` call (through `price_of`), the cost files read once: the ceiling reads
        # no transcript and no second copy of the journal. Its money is `ceiling_figure`'s, not
        # the price's: per session the CLI's charge where known, else the transcripts (R12, P6).
        docs = retro_numbers.all_cost_files(base)
        price = retro_numbers.price_of(task, base, docs)
        spend = retro_numbers.story_spend(task, base, price=price, docs=docs)
        figure = ceiling_figure(price)
        spend.update(usd=figure["usd"], ceiling=figure,
                     incomplete=bool(spend["incomplete"] or figure["unknown"]))
        result["spend"] = spend
        share = ratios(spend, caps)
        if not share:
            return result
        which = max(share, key=lambda k: share[k])
        ratio = share[which]
        result["ratio"] = round(ratio, 4)
        troot = Path(task_root) if task_root is not None else artifacts_dir(task)
        pipeline = hooklib.read_json(troot / "pipeline.json", {}, errors=Exception)
        passed = override(pipeline if isinstance(pipeline, dict) else {})
        result["overridden"] = passed
        marker = marker_path(task, base)
        seen = [float(x) for x in (read_marker(marker).get("notified") or [])
                if isinstance(x, (int, float))]
        crossed = [m for m in list(caps["warn_at"]) + [1.0] if ratio >= m and m not in seen]
        if not crossed:
            return result
        level = max(crossed)
        result["level"] = level
        result["stop"] = level >= 1.0 and not passed
        cap_value = caps["story_usd"] if which == "usd" else caps["story_tokens"]
        actual = spend.get("usd") if which == "usd" else spend.get("tokens")
        shown = f"${actual:,.2f} of ${cap_value:,.2f}" if which == "usd" \
            else f"{int(actual):,} of {int(cap_value):,} tokens"
        floor = " (a floor: some role usage was not captured)" if spend.get("incomplete") else ""
        how = figure_notes(figure) if which == "usd" else ""   # how the money figure was read
        if level >= 1.0:
            if passed:
                result["notice"] = (f"STORY BUDGET: {task} is past its ceiling — {shown}"
                                    f"{floor}.{how} You already passed this block: "
                                    f"\"{passed.get('decision')}\". Continuing.")
            else:
                result["notice"] = (
                    f"STORY BUDGET: {task} has reached its ceiling — {shown}{floor}.{how} "
                    f"Stop here and ask the person whether to go on. Their word continues "
                    "the story; record it with `" +
                    door(f"waiver.py --task {task} --stage <S> --block \"story budget\"") +
                    "`. This is a ceiling the project set, not a fault of the work.")
        else:
            result["notice"] = (f"STORY BUDGET: {task} is at {floor_percent(ratio)}% of "
                                f"its ceiling — {shown}{floor}.{how} Nothing to do; the stop and "
                                f"the question come at 100%.")
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(json.dumps({
                "task": task, "notified": sorted(set(seen + crossed)),
                "ratio": result["ratio"],
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}),
                encoding="utf-8")
        except Exception:
            pass  # a marker that cannot be written costs a repeated warning, never a story
        return result
    except Exception:
        return result  # a ceiling that cannot be computed never stops the work


STOP_EXIT = 3


def enforce(task: str, root: Path | None = None, task_root: Path | None = None) -> int:
    """Print whatever the ceiling has to say and return the exit code its caller must pass on.

    A notice printed on stderr with exit 0 is a notice an orchestrator does not act on: the
    ceiling was reached on a pilot and the only trace was one line nobody read (0.7.7
    review, D-F12). `STOP_EXIT` is the caller's signal to stop and ask; a threshold warning
    below the ceiling, and a ceiling the person has already passed by word, stay exit 0 —
    they are information, not a block."""
    state = check(task, root, task_root)
    notice = str(state.get("notice") or "").strip()
    if notice:
        print(notice)
    return STOP_EXIT if state.get("stop") else 0


def selftest() -> int:
    import tempfile
    failures: list = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    case("no ceiling by default", limits({})["story_usd"], None)
    case("and the shipped warning marks", limits({})["warn_at"], list(DEFAULT_WARN_AT))
    case("a configured ceiling is read",
         limits({"budget": {"story_usd": 10}})["story_usd"], 10.0)
    case("a nonsense threshold is dropped, not obeyed",
         limits({"budget": {"warn_at": [0.5, 3, -1]}})["warn_at"], [0.5])
    case("an override on any stage counts",
         (override({"stage_overrides": [{"stage": "S5", "match": "story budget",
                                         "decision": "go on"}]}) or {}).get("decision"), "go on")
    case("and a blanket one does too",
         bool(override({"stage_overrides": [{"stage": "S5", "match": "*", "decision": "yes"}]})),
         True)
    case("an override with no words is not an override",
         override({"stage_overrides": [{"stage": "S5", "match": "*", "decision": ""}]}), None)
    doubled = ceiling_figure({"sessions": [
        {"b_usd": 6.0, "a_usd": 12.0, "a_price_usd": 12.0, "verdict": "differs"},
        {"b_usd": None, "a_usd": 1.0, "a_price_usd": 1.0, "verdict": "one_record"},
        {"b_usd": None, "a_usd": None, "a_price_usd": None, "verdict": "unknown"}]})
    case("the ceiling reads the CLI's charge where known, never the larger of the two records",
         (doubled["usd"], doubled["alt_usd"]), (7.0, 13.0))
    case("a session known to neither is counted unknown, and one with no CLI charge uses the transcripts",
         (doubled["unknown"], doubled["by_cli"], doubled["by_transcripts"]), (1, 1, 1))

    with tempfile.TemporaryDirectory(prefix="qa-story-budget-") as td:
        base = Path(td) / "qa-factory"
        troot = base / "artifacts" / "QA-1"
        (base / "state" / "cost").mkdir(parents=True)
        troot.mkdir(parents=True)
        (troot / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")

        def set_spend(usd):
            # The story's sessions are the ones the driver's journal names (evidence, FR-24): one
            # role session whose running total is the spend. A `by_task` tag alone binds nothing.
            (troot / "state").mkdir(parents=True, exist_ok=True)
            (troot / "state" / "driver-runs.jsonl").write_text(json.dumps(
                {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "stage": "S1",
                 "session_id": "s-1", "num_turns": 3, "total_cost_usd": usd,
                 "ts": "2026-09-23T10:30:00+00:00"}) + "\n", encoding="utf-8")

        def set_cap(cap):
            (base / "config.json").write_text(json.dumps(
                {"budget": {"story_usd": cap, "warn_at": [0.5, 0.8]}}), encoding="utf-8")

        (base / "config.json").write_text("{}", encoding="utf-8")
        set_spend(50.0)
        case("with no ceiling configured nothing is said",
             check("QA-1", base, troot)["notice"], "")
        set_cap(10.0)
        set_spend(2.0)
        case("below the first mark nothing is said",
             check("QA-1", base, troot)["notice"], "")
        set_spend(6.0)
        first = check("QA-1", base, troot)
        case("the first threshold warns", "60% of" in first["notice"], True)
        case("and does not stop the story", first["stop"], False)
        case("the same threshold does not warn twice",
             check("QA-1", base, troot)["notice"], "")
        set_spend(9.0)
        case("the next threshold warns once",
             "90% of" in check("QA-1", base, troot)["notice"], True)
        set_spend(11.0)
        full = check("QA-1", base, troot)
        case("at the ceiling the story stops and asks", full["stop"], True)
        case("and the line names the way a person's word passes it",
             "--block \"story budget\"" in full["notice"], True)
        case("and never blames the work",
             "not a fault of the work" in full["notice"], True)

        (troot / "pipeline.json").write_text(json.dumps(
            {"ticket": "QA-1", "stage_overrides": [
                {"stage": "S5", "match": "story budget", "decision": "keep going, it is worth it"}]}),
            encoding="utf-8")
        marker_path("QA-1", base).unlink()
        passed = check("QA-1", base, troot)
        case("a recorded decision continues the story", passed["stop"], False)
        case("quoting the person", "keep going, it is worth it" in passed["notice"], True)
        case("and the caller is not stopped by an answered ceiling",
             enforce("QA-1", base, troot), 0)

        # The stop is an exit code, not a line on stderr: see D-F12 of the 0.7.7 review.
        (troot / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")
        marker_path("QA-1", base).unlink()
        case("an unanswered ceiling makes its caller stop",
             enforce("QA-1", base, troot), STOP_EXIT)

        # A token ceiling with no price recorded must still bite: the journal names the session
        # with no usable total, its cost file holds 10 tokens.
        (base / "config.json").write_text(json.dumps(
            {"budget": {"story_tokens": 5, "warn_at": [0.5]}}), encoding="utf-8")
        set_spend(None)
        (base / "state" / "cost" / "s-1.json").write_text(json.dumps(
            {"session_id": "s-1", "by_task": {"(no task)": {"tokens": 10, "cost": None}},
             "agents": []}), encoding="utf-8")
        marker_path("QA-1", base).unlink()
        (troot / "pipeline.json").write_text(json.dumps({"ticket": "QA-1"}), encoding="utf-8")
        tokens = check("QA-1", base, troot)
        case("a token ceiling works with no price at all", tokens["stop"], True)
        case("and reports tokens, not dollars", "tokens" in tokens["notice"], True)

    if failures:
        print("STORY_BUDGET SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("STORY_BUDGET SELFTEST: no violations (limits, thresholds once, stop, override)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--task", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.task:
        print("story_budget.py: --task is required", file=sys.stderr)
        return 2
    require_project("story_budget")
    state = check(args.task)
    if args.json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return STOP_EXIT if state.get("stop") else 0
    if state["notice"]:
        print(state["notice"])
    return STOP_EXIT if state.get("stop") else 0


if __name__ == "__main__":
    sys.exit(main())
