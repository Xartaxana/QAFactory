#!/usr/bin/env python3
"""driver_journal.py: the one reader of artifacts/<task>/state/driver-runs.jsonl.

Seen on four real driver runs of TP1-13797 (30.09): in cmp1 a session's `total_cost_usd` is a
running total, in three others it falls inside a session (driver3 session 29240aa1: $0.78, $9.51,
$3.39, $0.19) because it is the cost of one call. The reader is used in a gate role (binding a
session to a task, pricing it), so its error direction is fixed: it may fail to bind or say
"unknown", it never binds a session the journal does not literally name and never returns a wrong
number. One named check per edge; the journals are synthetic and live in temp directories.

Edge labels follow docs/tasks/specs/t-111-dashboard-driver-binding.md: C1 falling totals (and the
per-root rule), C2/E7 increments and pair costs, C3 kinds, E4 a session named by several
journals, E8 never-bound rows, E9 timestamps, E10 BOM, E13 where journals live, E14 nothing there.
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import driver_journal as J  # noqa: E402
import hooklib  # noqa: E402

CLOSE = 1e-9


def row(session, total, dispatch="d1", kind="role", role="qa-scout", ts="2026-09-30T10:00:00+00:00",
        turns=1, **extra):
    out = {"kind": kind, "role": role, "dispatch": dispatch, "session_id": session,
           "num_turns": turns, "total_cost_usd": total}
    if ts is not None:
        out["ts"] = ts
    out.update(extra)
    return out


def conductor(session, total, ts="2026-09-30T10:00:00+00:00", turns=1):
    return row(session, total, dispatch="", kind="conductor", role="", ts=ts, turns=turns)


def make_root(journals, bom=False):
    """A root whose artifacts/<task>/state/driver-runs.jsonl hold `journals` (task -> rows, raw
    str lines or raw bytes lines). No config file: the artifact root is the default
    qa-factory/artifacts."""
    root = temp_dir("driver-journal-")
    for task, lines in journals.items():
        state = root / "qa-factory" / "artifacts" / task / "state"
        state.mkdir(parents=True)
        data = b""
        for ln in lines:
            data += ln if isinstance(ln, bytes) else (ln if isinstance(ln, str) else json.dumps(ln)).encode("utf-8")
            data += b"\n"
        (state / "driver-runs.jsonl").write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return root


def read(journals, **kw):
    root = make_root(journals, **kw)
    try:
        return J.parse_driver_runs(root)
    finally:
        cleanup(root)


def close(a, b):
    return a is not None and b is not None and abs(a - b) < CLOSE


def costs(session, rows):
    return {p["dispatch"]: p["cost"] for p in J.pair_records(session, rows)}


def entry(rows, journals=("T1",)):
    """A by_session entry as parse_driver_runs builds it, for the pricing functions."""
    return {"task": journals[0], "rows": rows, "journals": list(journals), "no_timestamps": False,
            "multi_journal": len(journals) > 1}


# ---------------------------------------------------------------- E7: unusable totals
for label, bad in [("bool True", True), ("bool False", False), ("NaN", float("nan")),
                   ("infinity", float("inf")), ("minus infinity", float("-inf")), ("negative", -0.01),
                   ("string 1.0", "1.0"), ("None", None), ("list", [1.0]), ("huge int", 10 ** 400)]:
    check(f"E7 usable_total excludes {label}, never coerces it", J.usable_total(bad) is None)
    check(f"E7 driver_charged of a session with only {label} is unknown", J.driver_charged([row("s", bad)]) is None)
    check(f"E7 driver_charged skips {label} and keeps the last usable total",
          J.driver_charged([row("s", 1.0), row("s", bad)]) == 1.0)
check_eq("E7 an int total is usable and returned as a float", J.usable_total(2), 2.0)
check_eq("E7 zero is a usable total", J.usable_total(0), 0.0)

# ---------------------------------------------------------------- C1: a falling session
per_call = [row("s", 0.78), row("s", 9.51), row("s", 3.39), row("s", 0.19)]   # driver3 29240aa1
check("C1 a falling session has an UNKNOWN driver record, not the last row's $0.19",
      J.driver_charged(per_call) is None)
check("C1 total_falls sees the fall", J.total_falls(per_call))
check("C1 every pair of a falling session is unknown money (a per-call increment is not money)",
      all(p["cost"] is None for p in J.pair_records("s", per_call + [row("s", 5.0, dispatch="d2")])))
running = [row("s", 0.45), row("s", 1.32), row("s", 1.32), row("s", 1.38)]
check("C1 equal consecutive totals are not a fall; the record is the last row", J.driver_charged(running) == 1.38)
check("C1 a fall separated by an unusable row is still a fall",
      J.driver_charged([row("s", 3.0), row("s", "x"), row("s", 1.0)]) is None)
by_session, _ = read({"T1": [row("a", 3.0), row("b", 9.0), row("a", 1.0)]})
check("C1 a fall in session a, with session b's higher total written between, is a fall in a only",
      J.driver_charged(by_session["a"]["rows"]) is None and J.driver_charged(by_session["b"]["rows"]) == 9.0)
by_session, _ = read({"T1": per_call + [row("ok", 1.0), row("ok", 2.0)]
                      + [row("z", 4.0), row("z", 2.0)]})
check_eq("C1 falling_sessions lists exactly the falling sessions, sorted", J.falling_sessions(by_session), ["s", "z"])
check_eq("C1 a running-total session next to them still has its own record by driver_charged",
         J.driver_charged(by_session["ok"]["rows"]), 2.0)

# ---------------------------------------------------------------- C1: the per-root rule
# One session falls, so the whole root is per-call: rising multi-row sessions are unknown, a
# single-row session keeps its value.
mixed_root = {"T1": per_call + [row("rise", 1.0), row("rise", 2.0), row("one", 5.0), row("none", None)]}
by_session, _ = read(mixed_root)
charged, unknown = J.root_charged(by_session)
check_eq("C1 root rule: the falling session is unknown", charged["s"], None)
check_eq("C1 root rule: a multi-row session that only rises is unknown when another session falls",
         charged["rise"], None)
check_eq("C1 root rule: a single-row session keeps its value under a per-call root", charged["one"], 5.0)
check_eq("C1 root rule: a session with no usable total is unknown", charged["none"], None)
check_eq("C1 root rule: every session is a key of `charged`", sorted(charged), ["none", "one", "rise", "s"])
check_eq("C1 root rule: `unknown` lists the sessions priced None with the reason, sorted by id",
         unknown, [("none", J.WHY_NO_TOTAL), ("rise", J.WHY_PER_CALL_ROOT), ("s", J.WHY_FALLS)])
check_eq("C1 the four reasons are the four plain phrases",
         (J.WHY_FALLS, J.WHY_SEVERAL_JOURNALS, J.WHY_PER_CALL_ROOT, J.WHY_NO_TOTAL),
         ("falls", "named by several journals", "several rows under a root where totals are per call",
          "no usable total"))
check("C1 root rule: a fall does not need to be under the same task - it is the root that counts",
      J.root_charged(read({"T1": per_call, "T2": [row("rise", 1.0), row("rise", 2.0)]})[0])[0]["rise"] is None)
by_session, _ = read({"T1": [row("rise", 1.0), row("rise", 2.0), row("one", 5.0), row("run", 0.45), row("run", 1.38)]})
charged, unknown = J.root_charged(by_session)
check_eq("C1 a root with no falling session is priced as before: last usable total per session",
         charged, {"one": 5.0, "rise": 2.0, "run": 1.38})
check_eq("C1 a root with no falling session has nothing unknown", unknown, [])
check_eq("C1 an empty root prices nothing", J.root_charged({}), ({}, []))
by_session, _ = read({"T1": [row("g", 1.0), row("g", 2.0)]})
check("C1 the fall in another READ (another root) does not reach this one",
      J.root_charged(read({"T1": per_call})[0])[0]["s"] is None and J.root_charged(by_session)[0]["g"] == 2.0)
by_session, _ = read({"T1": [row("x", 3.0), row("x", 1.0), row("x", 2.0)]})
check_eq("C1 a falling session is reported as 'falls', not as a per-call-root member",
         J.root_charged(by_session)[1], [("x", J.WHY_FALLS)])
by_session, _ = read({"T1": [row("a", 1.0), row("a", "bad"), row("b", 3.0), row("b", 1.0)]})
check_eq("C1 a session with ONE usable row (a second row unusable) keeps its value under a per-call root",
         J.root_charged(by_session)[0]["a"], 1.0)

# ---------------------------------------------------------------- C2/E7: increments and pairs
abab = [row("s", 1.0, dispatch="A"), row("s", 1.5, dispatch="B"), row("s", 2.0, dispatch="A")]
pairs = costs("s", abab)
check("C2 A 1.0 / B 1.5 / A 2.0: pair A costs 1.5 (its two increments, never 2.0 - 0)", close(pairs["A"], 1.5))
check("C2 A 1.0 / B 1.5 / A 2.0: pair B costs 0.5", close(pairs["B"], 0.5))
check("C2 A 1.0 / B 1.5 / A 2.0: the pair costs sum to the charged total 2.0, no money created",
      close(sum(pairs.values()), 2.0) and J.driver_charged(abab) == 2.0)
check("C2 row increments of the case are 1.0, 0.5, 0.5", [round(x, 9) for x in J.row_increments(abab)] == [1.0, 0.5, 0.5])
long = [row("s", t, dispatch=d, turns=n) for t, d, n in
        [(0.3, "A", 2), (0.35, "B", 1), (1.1, "A", 4), (1.1, "C", 3), (2.7, "B", 5), (2.9, "A", 1)]]
check("C2 increments of a session with a known record add up to its charged total",
      close(math.fsum(J.row_increments(long)), J.driver_charged(long)))
check("C2 the pair costs of that session add up to its charged total",
      close(sum(costs("s", long).values()), J.driver_charged(long)))
check("C2 a pair with equal totals costs 0.0, not unknown", costs("s", long)["C"] == 0.0)
check_eq("C2 a pair's turns are the sum of its rows' num_turns",
         {p["dispatch"]: p["turns"] for p in J.pair_records("s", long)}, {"A": 7, "B": 6, "C": 3})
check_eq("C2 pairs come in order of first appearance", [p["dispatch"] for p in J.pair_records("s", long)],
         ["A", "B", "C"])
fell = J.row_increments([row("s", 2.0), row("s", 1.5), row("s", 1.7)])
check("E7 a negative increment is None in row_increments, never a negative dollar",
      fell[0] == 2.0 and fell[1] is None and all(x is None or x >= 0 for x in fell))
check("E7 after a fall the next increment is measured from the fallen total, not the old maximum",
      close(fell[2], 0.2))
check_eq("E7 an unusable total makes that row's increment None, and the row AFTER it too: what the "
         "unusable row cost is unknown and must not land inside the next increment",
         J.row_increments([row("s", 1.0), row("s", "1.0"), row("s", 2.0)]), [1.0, None, None])
check_eq("E7 the row after that one is measured from the last usable total again",
         J.row_increments([row("s", 1.0), row("s", "1.0"), row("s", 2.0), row("s", 3.5)]),
         [1.0, None, None, 1.5])
check_eq("E7 an unusable FIRST row makes the second row's increment None too (the first row's cost is unknown)",
         J.row_increments([row("s", None), row("s", 2.0)]), [None, None])
check_eq("E7 two unusable rows in a row: the row after both is None",
         J.row_increments([row("s", 1.0), row("s", None), row("s", True), row("s", 2.0)]), [1.0, None, None, None])
unusable_pair = costs("s", [row("s", 1.0, dispatch="A"), row("s", None, dispatch="B"), row("s", 2.0, dispatch="A")])
check("E7 A 1.0 / B unusable / A 2.0: pair B is None AND pair A is None (B's spend cannot be told from A's)",
      unusable_pair["B"] is None and unusable_pair["A"] is None)
check_eq("E7 ... and the session's charged total stays the last usable total",
         J.driver_charged([row("s", 1.0, dispatch="A"), row("s", None, dispatch="B"), row("s", 2.0, dispatch="A")]), 2.0)
mixed_pairs = costs("s", [row("s", 1.0, dispatch="A"), row("s", 2.0, dispatch="A"), row("s", None, dispatch="B"),
                          row("s", 3.0, dispatch="C"), row("s", 4.0, dispatch="D")])
check("E7 a pair holding no unusable row and no row right after one is still priced (A 2.0, D 1.0)",
      close(mixed_pairs["A"], 2.0) and close(mixed_pairs["D"], 1.0))
check("E7 the pair of the unusable row and the pair of the row right after it are None",
      mixed_pairs["B"] is None and mixed_pairs["C"] is None)
check("E7 a session with no usable total prices no pair", all(c is None for c in costs("s", [row("s", None)]).values()))
check("C2 a first row is measured from zero", close(J.row_increments([row("s", 0.7)])[0], 0.7))

# ---------------------------------------------------------------- C2, C3: conductor, kinds
cond_pairs = J.pair_records("c", [conductor("c", 0.3, turns=5), conductor("c", 0.5, turns=8)])
check_eq("C2 a conductor row's pair key is (session, '')", [(p["session"], p["dispatch"]) for p in cond_pairs],
         [("c", "")])
check("C2 the conductor pair is the conductor, its turns and cost summed over its rows",
      cond_pairs[0]["role"] == "conductor" and cond_pairs[0]["turns"] == 13 and close(cond_pairs[0]["cost"], 0.5))
check("C2 an absent or null dispatch is the pair key ''", J.pair_key({}) == "" and J.pair_key({"dispatch": None}) == "")
ticket = {"kind": "ticket", "role": "jira-agent", "dispatch": "", "session_id": "t", "total_cost_usd": 0.2}
check_eq("C3 a ticket session is a record named by its kind, never the conductor", J.record_label([ticket]),
         ("ticket", False))
check("C3 a kind that is not conductor and has no role row is not 'conductor'",
      all(J.record_label([{"kind": k}])[0] != "conductor" for k in ("ticket", "delivery", "Conductor", "conductors")))
check_eq("C3 only kind == 'conductor' is the conductor", J.record_label([{"kind": "conductor"}]), ("conductor", False))
check_eq("C3 a role row names the record", J.record_label([row("s", 1.0, role="qa-runner")]), ("qa-runner", False))
check_eq("C3 mixed roles: the first wins and mixed is said",
         J.record_label([row("s", 1.0, role="qa-a"), row("s", 2.0, role="qa-b")]), ("qa-a", True))
check_eq("C3 a row naming no kind is no record", J.record_label([{"session_id": "x"}]), (None, False))
check_eq("C3 driver_role keeps today's behaviour: a ticket alone is None", J.driver_role([ticket]), (None, False))
check_eq("C3 driver_role keeps today's behaviour: conductor rows only", J.driver_role([conductor("c", 1.0)]),
         ("conductor", False))
check_eq("C3 the ticket pair record carries the kind as its role",
         J.pair_records("t", [ticket])[0]["role"], "ticket")

# ---------------------------------------------------------------- E4, E9: binding
by_session, spread = read({"T1": [row("s", 1.0, ts="2026-09-30T12:00:00+00:00")],
                           "T2": [row("s", 1.0, ts="2026-09-30T11:00:00+00:00")]})
check_eq("E4 a session named by two journals goes to the task with the earliest ts", by_session["s"]["task"], "T2")
check_eq("E4 the result reports how many journals name the session", spread["s"], 2)
check_eq("E4 the result lists the journals", by_session["s"]["journals"], ["T1", "T2"])
check("E9 with timestamps the result does not say 'no timestamps'", by_session["s"]["no_timestamps"] is False)
by_session, _ = read({"T1": [row("s", 1.0, ts="2026-09-30T10:00:00+00:00")], "T2": [row("s", 1.0, ts=None)]})
check_eq("E9 a row with NO ts under T2 never beats a row with a ts under T1", by_session["s"]["task"], "T1")
by_session, _ = read({"T1": [row("s", 1.0, ts=None)], "T2": [row("s", 1.0, ts="2026-09-30T10:00:00+00:00")]})
check_eq("E9 ... in the other name order too (T2 has the only ts)", by_session["s"]["task"], "T2")
for label, bad_ts in [("garbage", "not a time"), ("empty", ""), ("integer", 20260930), ("None", None),
                      ("list", ["2026-09-30"]), ("year 0", "0000-01-01T00:00:00+00:00")]:
    by_session, _ = read({"A": [row("s", 1.0, ts=bad_ts)], "B": [row("s", 1.0, ts="2026-09-30T10:00:00+00:00")]})
    check_eq(f"E9 an unparseable ts ({label}) under A never beats a parseable ts under B", by_session["s"]["task"], "B")
by_session, _ = read({"B": [row("s", 1.0, ts=None)], "A": [row("s", 1.0, ts="garbage")]})
check_eq("E9 no candidate with a ts: the lexicographically first task name", by_session["s"]["task"], "A")
check("E9 ... and the result says 'no timestamps'", by_session["s"]["no_timestamps"] is True)
by_session, _ = read({"T1": [row("s", 1.0, ts="2026-09-30T10:00:00")],
                      "T2": [row("s", 1.0, ts="2026-09-30T09:30:00+00:00")]})
check_eq("E9 a naive time is read as UTC: 10:00 naive is later than 09:30+00:00", by_session["s"]["task"], "T2")
by_session, _ = read({"T1": [row("s", 1.0, ts="2026-09-30T09:00:00")],
                      "T2": [row("s", 1.0, ts="2026-09-30T11:00:00+03:00")]})
check_eq("E9 an aware offset is converted: 11:00+03:00 (08:00 UTC) beats 09:00 naive although it sorts later as text",
         by_session["s"]["task"], "T2")
by_session, _ = read({"T1": [row("s", 1.0, ts="2026-09-30T10:00:00Z")], "T2": [row("s", 1.0, ts="2026-09-30T09:59:59Z")]})
check_eq("E9 a 'Z' suffix parses as UTC", by_session["s"]["task"], "T2")
by_session, _ = read({"T2": [row("s", 1.0, ts="2026-09-30T10:00:00+00:00")],
                      "T1": [row("s", 1.0, ts="2026-09-30T13:00:00+03:00")]})
check_eq("E9 the same instant written in two zones: the first task name wins, deterministically",
         by_session["s"]["task"], "T1")
by_session, _ = read({"T1": [row("s", 1.0, ts="2026-09-30T12:00:00+00:00"),
                             row("s", 2.0, ts="2026-09-30T08:00:00+00:00")],
                      "T2": [row("s", 1.0, ts="2026-09-30T10:00:00+00:00")]})
check_eq("E9 a task is judged by its EARLIEST parseable row, not its first row", by_session["s"]["task"], "T1")
check_eq("E4 the chosen task's rows are returned in file order", [r["total_cost_usd"] for r in by_session["s"]["rows"]],
         [1.0, 2.0])
by_session, spread = read({"T1": [row("s", 1.0)]})
check("E9 a session named by one journal: spread 1, no 'no timestamps' note even with no ts",
      spread["s"] == 1 and read({"T1": [row("s", 1.0, ts=None)]})[0]["s"]["no_timestamps"] is False)

# ---------------------------------------------------------------- E4: a session named by several journals
by_session, _ = read({"T1": [row("s", 1.0, ts="2026-09-30T10:00:00+00:00")],
                      "T2": [row("s", 3.0, ts="2026-09-30T11:00:00+00:00")]})
check("E4 a session named by two journals carries multi_journal True", by_session["s"]["multi_journal"] is True)
check_eq("E4 entry_charged of it is None, not the $1.00 of the journal it was bound to (T2 holds $3.00)",
         J.entry_charged(by_session["s"]), None)
check_eq("E4 root_charged prices it None and says why",
         J.root_charged(by_session), ({"s": None}, [("s", J.WHY_SEVERAL_JOURNALS)]))
check_eq("E4 the same rows with one journal price normally through entry_charged",
         J.entry_charged(entry([row("s", 1.0)])), 1.0)
check_eq("E4 an entry with two journals but no multi_journal key is still None (the journals list decides)",
         J.entry_charged({"rows": [row("s", 1.0)], "journals": ["T1", "T2"]}), None)
check_eq("E4 an entry with no journals key at all prices from its rows", J.entry_charged({"rows": [row("s", 2.0)]}), 2.0)
check_eq("E4 a falling session named by one journal is None through entry_charged too",
         J.entry_charged(entry(per_call)), None)
by_session, _ = read({"T1": [row("s", 1.0), row("o", 4.0)], "T2": [row("s", 3.0)]})
check("E4 a session named by one journal has multi_journal False", by_session["o"]["multi_journal"] is False)
check_eq("E4 root_charged: only the multi-journal session is unknown", J.root_charged(by_session),
         ({"o": 4.0, "s": None}, [("s", J.WHY_SEVERAL_JOURNALS)]))

# ---------------------------------------------------------------- E8: never bound
junk = [
    {"kind": "delivery", "outcome": "nothing_outward"},
    row("", 1.0), row(None, 1.0), row(123, 1.0), row(1.5, 1.0), row(True, 1.0), row(["x"], 1.0), row({"a": 1}, 1.0),
    "{broken json", "[1, 2, 3]", '"a string"', "42", "null", "true", "", "   ",
    row("ok", 1.0),
]
by_session, spread = read({"T1": junk})
check_eq("E8 only the row with a non-empty string session_id is bound", sorted(by_session), ["ok"])
check_eq("E8 the spread of the survivor is 1", spread, {"ok": 1})
by_session, _ = read({"T1": [row(123, 1.0)]})
check("E8 an integer id is NOT converted to the string a file could carry", "123" not in by_session and by_session == {})
by_session, spread = read({"T1": [row("Abc", 1.0)], "T2": [row("abc", 1.0), row("abc ", 2.0), row(" abc", 3.0)]})
check_eq("E8 ids differing by case or by whitespace are different ids, none merged",
         sorted(by_session), [" abc", "Abc", "abc", "abc "])
check_eq("E8 ... so none is named by two journals", sorted(spread.values()), [1, 1, 1, 1])
by_session, _ = read({"T1": [row("s", 1.0), "not json", row("s", 2.0)]})
check_eq("E8 a broken line between two rows does not lose either", len(by_session["s"]["rows"]), 2)
by_session, _ = read({"T1": [json.dumps(row("s", 1.0), ensure_ascii=False).replace('"qa-scout"', '"qa' + chr(0x2028) + 'scout"'),
                             row("s", 2.0)]})
check_eq("E8 a row holding U+2028 in a string is kept whole (no splitlines)", len(by_session["s"]["rows"]), 2)
by_session, _ = read({"T1": [row("s", 1.0)]})
check("E8 the returned row is the journal's own dict, nothing added or coerced",
      by_session["s"]["rows"][0]["total_cost_usd"] == 1.0 and "task" not in by_session["s"]["rows"][0])
# The file is read with a replacing decoder: two different undecodable ids would become ONE id.
FFFD = chr(0xFFFD)   # written as a code point: no odd character in the source
by_session, spread = read({"T1": [row("ok", 1.0), row("a" + FFFD + "b", 1.0), row(FFFD, 2.0), row("x" + FFFD, 3.0)]})
check_eq("E8 an id holding U+FFFD is never bound (skipped like a row with no id)", sorted(by_session), ["ok"])
raw_a = json.dumps(row("XX", 1.0)).encode("utf-8").replace(b'"XX"', b'"x\xff"')
raw_b = json.dumps(row("XX", 2.0)).encode("utf-8").replace(b'"XX"', b'"x\xfe"')
check("E8 the fixture really holds two different undecodable ids", raw_a != raw_b and b"\xff" in raw_a and b"\xfe" in raw_b)
by_session, spread = read({"T1": [raw_a, row("y", 1.0)], "T2": [raw_b]})
check_eq("E8 two different undecodable ids do not merge into one bound session, nor bind at all",
         (sorted(by_session), spread), (["y"], {"y": 1}))
e_acute_id = "caf" + chr(0xE9)
by_session, _ = read({"T1": [row(e_acute_id, 1.0)]})
check_eq("E8 a valid non-ASCII id (no U+FFFD) is still bound", sorted(by_session), [e_acute_id])

# ---------------------------------------------------------------- E10: BOM
by_session, _ = read({"T1": [row("first", 1.0), row("second", 2.0)]}, bom=True)
check_eq("E10 a journal with a UTF-8 BOM keeps its FIRST row", sorted(by_session), ["first", "second"])
by_session, _ = read({"T1": [row("first", 1.0)]}, bom=False)
check_eq("E10 the same journal without a BOM reads the same", sorted(by_session), ["first"])

# ---------------------------------------------------------------- E14: nothing there
bare = temp_dir("driver-journal-bare-")
try:
    check_eq("E14 a root that does not exist reads as empty", J.parse_driver_runs(bare / "nope"), ({}, {}))
    check_eq("E14 a root with no artifacts folder reads as empty", J.parse_driver_runs(bare), ({}, {}))
    (bare / "qa-factory" / "artifacts").mkdir(parents=True)
    check_eq("E14 an artifacts folder holding nothing reads as empty", J.parse_driver_runs(bare), ({}, {}))
    (bare / "qa-factory" / "artifacts" / "T1").mkdir()
    check_eq("E14 a story folder with no state folder reads as empty", J.parse_driver_runs(bare), ({}, {}))
    (bare / "qa-factory" / "artifacts" / "T1" / "state" / "driver-runs.jsonl").mkdir(parents=True)
    check_eq("E14 a journal path that is a directory reads as empty, no exception", J.parse_driver_runs(bare), ({}, {}))
    (bare / "qa-factory" / "config.json").write_text('{"artifact_root": ""}', encoding="utf-8")
    check_eq("E14 a config the artifact root cannot be read from reads as empty, no exception",
             J.parse_driver_runs(bare), ({}, {}))
    (bare / "qa-factory" / "config.json").write_text("{not json", encoding="utf-8")
    check_eq("E14 a config that is not JSON reads as empty, no exception", J.parse_driver_runs(bare), ({}, {}))
    (bare / "qa-factory" / "config.json").write_bytes(b'{"artifact_root": "\xff\xfe"}')
    check_eq("E14 a config that is not valid utf-8 reads as empty, no exception", J.parse_driver_runs(bare), ({}, {}))
    (bare / "qa-factory" / "config.json").unlink()
    (bare / "qa-factory" / "config.json").mkdir()
    check_eq("E14 a config path that is a directory (OSError) reads as empty, no exception",
             J.parse_driver_runs(bare), ({}, {}))
finally:
    cleanup(bare)
check_eq("E14 an empty journal file reads as empty", read({"T1": []}), ({}, {}))
check_eq("E14 a journal of only blank lines reads as empty", read({"T1": ["", "  ", ""]}), ({}, {}))
check_eq("E14 a journal of only a delivery row and junk reads as empty",
         read({"T1": [{"kind": "delivery"}, "{x"]}), ({}, {}))
check_eq("E14 no rows: charged unknown, no pairs, no falling, nothing to price",
         (J.driver_charged([]), J.pair_records("s", []), J.total_falls([]), J.falling_sessions({}),
          J.root_charged({})), (None, [], False, [], ({}, [])))

# What `_journal_paths` catches: OSError and ValueError (a config or a folder it cannot read). What
# it does NOT catch: an ImportError (a broken install) and a programming error (TypeError,
# AttributeError): those are not "no journal", they must reach the caller.
journal_root = make_root({"T1": [row("s", 1.0)]})
real_artifact_root = hooklib.artifact_root
real_module = sys.modules["hooklib"]
try:
    def raising(exc):
        def fake(*args, **kwargs):
            raise exc
        return fake

    for label, exc in [("OSError", PermissionError("denied")), ("ValueError", ValueError("bad config"))]:
        hooklib.artifact_root = raising(exc)
        check_eq(f"E14 a {label} while resolving the artifact root is 'no journal'",
                 J.parse_driver_runs(journal_root), ({}, {}))
    for label, exc in [("TypeError", TypeError("a bug")), ("AttributeError", AttributeError("a bug")),
                       ("KeyError", KeyError("a bug"))]:
        hooklib.artifact_root = raising(exc)
        try:
            J.parse_driver_runs(journal_root)
            got = "swallowed"
        except type(exc):
            got = "propagated"
        check_eq(f"E14 a {label} while resolving the artifact root is NOT read as 'no journal'", got, "propagated")
    hooklib.artifact_root = real_artifact_root
    sys.modules["hooklib"] = None      # makes `import hooklib` raise ImportError
    try:
        J.parse_driver_runs(journal_root)
        got = "swallowed"
    except ImportError:
        got = "propagated"
    check_eq("E14 an ImportError of hooklib is NOT read as 'no journal'", got, "propagated")
finally:
    hooklib.artifact_root = real_artifact_root
    sys.modules["hooklib"] = real_module
    cleanup(journal_root)

# ---------------------------------------------------------------- E13: where journals live
root = temp_dir("driver-journal-depth-")
try:
    art = root / "qa-factory" / "artifacts"
    for rel, sid in [("T1/state", "depth1"), ("T1/sub/state", "too-deep"), ("archive/T2/state", "archived-deeper"),
                     ("T3", "not-in-state"), ("T4/state/inner", "inner-state")]:
        (art / rel).mkdir(parents=True)
        (art / rel / "driver-runs.jsonl").write_text(json.dumps(row(sid, 1.0)) + "\n", encoding="utf-8")
    (art / "loose-file.jsonl").write_text(json.dumps(row("loose", 1.0)) + "\n", encoding="utf-8")
    (art / "T1" / "state" / "driver-runs.jsonl.bak").write_text(json.dumps(row("bak", 1.0)) + "\n", encoding="utf-8")
    found, _ = J.parse_driver_runs(root)
    check_eq("E13 only artifacts/<T>/state/driver-runs.jsonl at depth 1 is read", sorted(found), ["depth1"])
    check_eq("E13 the task is the folder name", found["depth1"]["task"], "T1")
    (root / "qa-factory" / "config.json").write_text(json.dumps({"artifact_root": "elsewhere"}), encoding="utf-8")
    (root / "elsewhere" / "T9" / "state").mkdir(parents=True)
    (root / "elsewhere" / "T9" / "state" / "driver-runs.jsonl").write_text(json.dumps(row("moved", 1.0)) + "\n",
                                                                           encoding="utf-8")
    check_eq("E13 a configured artifact root is honoured, as everywhere else", sorted(J.parse_driver_runs(root)[0]),
             ["moved"])
finally:
    cleanup(root)

# ---------------------------------------------------------------- the real shape, end to end
root = make_root({"T1": [row("r", 0.45, dispatch="S1-scout", ts="2026-09-30T03:49:37+00:00", turns=18),
                         row("r", 1.32, dispatch="S1-scout", ts="2026-09-30T03:56:25+00:00", turns=31),
                         conductor("c", 0.32, ts="2026-09-30T03:58:24+00:00", turns=5),
                         row("r", 1.38, dispatch="S1-scout", ts="2026-09-30T03:59:11+00:00", turns=2),
                         {"ts": "2026-09-30T04:10:00+00:00", "kind": "delivery", "session_id": None,
                          "total_cost_usd": None}]})
try:
    found, spread = J.parse_driver_runs(root)
    check_eq("real shape: two sessions bound, the delivery row skipped", sorted(found), ["c", "r"])
    check("real shape: a resumed session is charged its last total, never the sum",
          J.driver_charged(found["r"]["rows"]) == 1.38)
    check_eq("real shape: a resumed session is one pair of 51 turns",
             [(p["dispatch"], p["turns"], round(p["cost"], 9)) for p in J.pair_records("r", found["r"]["rows"])],
             [("S1-scout", 51, 1.38)])
    check_eq("real shape: the root has no falling session, so root_charged prices both",
             J.root_charged(found), ({"c": 0.32, "r": 1.38}, []))
finally:
    cleanup(root)

# ---------------------------------------------------------------- agent_label: ONE name per record
# The price function and the dashboard group money by agent through this helper only (t-137, P7).
ticket_row = row("s", 0.3, kind="ticket", role="jira", dispatch="", ts=None)
check_eq("L1 a ticket call is the scout's row, not its own and not the conductor's", J.agent_label([ticket_row]), "qa-scout")
check_eq("L1 ... whatever `role` the ticket row carries (it names the tool to invoke, not a role)",
         J.agent_label([row("s", 0.3, kind="ticket", role="qa-runner")]), "qa-scout")
check_eq("L1 a single row is accepted as well as a list", J.agent_label(ticket_row), "qa-scout")
# CHANGED in t-166 (F6): the data-fetching kinds and agent types are DATA (references/agent-labels.json, FR-13), not a
# frozenset in code; this check used to pin `J.DATA_FETCH_KINDS == frozenset({"ticket"})`.
_kinds, _types, _warn = J.label_data()
check("L1 the data-fetching kinds are data the helper reads, not a constant in code (DATA_FETCH_KINDS is gone)",
      not hasattr(J, "DATA_FETCH_KINDS") and _kinds == frozenset({"ticket"}) and _warn == "", str((_kinds, _warn)))
check("L1 ... and the same table names the data-fetching agent types (jira-assistant, jira-rw-assistant-cli)",
      {"jira-assistant", "jira-rw-assistant-cli"} <= _types, str(_types))
check_eq("L2 a conductor call is `conductor`", J.agent_label([conductor("c", 1.0)]), "conductor")
check_eq("L2 a role row is its role's name", J.agent_label([row("s", 1.0, role="qa-runner")]), "qa-runner")
check_eq("L2 it agrees with record_label for a role and for the conductor",
         [J.agent_label(r) for r in ([row("s", 1.0, role="qa-a")], [conductor("c", 1.0)])],
         [J.record_label(r)[0] for r in ([row("s", 1.0, role="qa-a")], [conductor("c", 1.0)])])
check_eq("L2 a role row wins over a ticket row of the same session", J.agent_label([ticket_row, row("s", 1.0, role="qa-a")]), "qa-a")
check_eq("L3 a kind outside the data-fetching set keeps its own name, never guessed into a role",
         J.agent_label([{"kind": "delivery"}]), "delivery")
check_eq("L3 a record naming no kind is `unlabelled`, never None", J.agent_label([{"session_id": "x"}]), "unlabelled")
check_eq("L3 nothing at all is `unlabelled` too", [J.agent_label([]), J.agent_label(None), J.agent_label([5, "x"])],
         ["unlabelled"] * 3)
check_eq("L3 a blank kind is no kind", J.agent_label([{"kind": "  "}]), "unlabelled")
check_eq("L4 a subagent file inside a session is its agentType",
         J.agent_label({"source": "subagent", "agent_type": "qa-helper"}), "qa-helper")
check_eq("L4 an orchestrator-mode main chain is `orchestrator`", J.agent_label({"source": "orchestrator"}), "orchestrator")
check_eq("L4 a chat session bound to a task is the person's chat", J.agent_label({"source": "chat"}), "person's chat")
# CHANGED in t-166 (F6): `jira-assistant` fetches data, so it is the scout's row; this check used to expect
# "jira-assistant (remote)". A consumer that is not a data-fetching agent keeps `<consumer_agent> (remote)`.
check_eq("L4 a remote call of a consumer that is not a data-fetching agent is `<consumer_agent> (remote)`",
         J.agent_label({"source": "remote", "consumer_agent": "testproject1-helper"}), "testproject1-helper (remote)")
check_eq("L4 a remote call whose consumer is a data-fetching agent is the scout's",
         [J.agent_label({"source": "remote", "consumer_agent": n}) for n in ("jira-assistant", "jira-rw-assistant-cli")],
         ["qa-scout", "qa-scout"])
check_eq("L4 a data-fetching subagent type inside a session is the scout's too",
         J.agent_label({"source": "subagent", "agent_type": "jira-rw-assistant-cli"}), "qa-scout")
check_eq("L4 edge: names are matched EXACTLY, the case is part of the name (Jira-Assistant, ' jira-assistant' trimmed only)",
         [J.agent_label({"source": "remote", "consumer_agent": "Jira-Assistant"}),
          J.agent_label({"source": "subagent", "agent_type": "JIRA-ASSISTANT"}),
          J.agent_label({"source": "subagent", "agent_type": " jira-assistant "})],
         ["Jira-Assistant (remote)", "JIRA-ASSISTANT", "qa-scout"])
check_eq("L4 a remote call naming no consumer still has a row",
         J.agent_label({"source": "remote"}), "unlabelled (remote)")
check_eq("L4 a subagent with no type still has a row", J.agent_label({"source": "subagent"}), "unlabelled")
check_eq("L4 an unknown source is `unlabelled`", J.agent_label({"source": "nobody"}), "unlabelled")

# The table is DATA (FR-13): a project's new fetching agent is one line there, and a broken table never raises.
_work = temp_dir("agent-labels-")
_saved = J.LABELS_PATH
_table = _work / "labels.json"
try:
    _table.write_text(json.dumps({"data_fetch_kinds": ["weblookup"], "data_fetch_agent_types": ["my-fetcher"]}), encoding="utf-8")
    J.LABELS_PATH = _table
    check_eq("L5 a table that lists a new kind and a new agent type makes them the scout's, nothing else changes",
             [J.agent_label([row("s", 0.1, kind="weblookup", role="")]), J.agent_label([row("s", 0.1, kind="ticket", role="")]),
              J.agent_label({"source": "remote", "consumer_agent": "my-fetcher"}),
              J.agent_label({"source": "remote", "consumer_agent": "jira-assistant"})],
             ["qa-scout", "ticket", "qa-scout", "jira-assistant (remote)"])
    check_eq("L5 ... and a role row still wins over a data-fetching kind",
             J.agent_label([row("s", 0.1, kind="weblookup", role=""), row("s", 0.2, role="qa-a")]), "qa-a")
    _table.write_text(json.dumps({"data_fetch_kinds": [], "data_fetch_agent_types": []}), encoding="utf-8")
    check_eq("L5 the table is re-read when the file changes (no stale cache): now `ticket` keeps its own name",
             J.agent_label([row("s", 0.1, kind="ticket", role="")]), "ticket")
    for why, body in (("missing", None), ("not JSON", "{ not json"), ("not an object", "[1, 2]"),
                      ("a key missing", json.dumps({"data_fetch_kinds": ["ticket"]})),
                      ("a key that is not a list", json.dumps({"data_fetch_kinds": "ticket", "data_fetch_agent_types": []})),
                      ("an entry that is not a string", json.dumps({"data_fetch_kinds": [], "data_fetch_agent_types": [3]}))):
        broken = _work / f"broken-{len(why)}.json"
        if body is not None:
            broken.write_text(body, encoding="utf-8")
        J.LABELS_PATH = broken
        try:
            labels = [J.agent_label([row("s", 0.1, kind="ticket", role="")]),
                      J.agent_label({"source": "remote", "consumer_agent": "jira-assistant"}),
                      J.agent_label({"source": "subagent", "agent_type": "jira-assistant"})]
            warning = J.label_data_warning()
        except Exception as exc:   # the contract is: never an exception
            labels, warning = [repr(exc)], ""
        check_eq(f"L5 edge: the table is {why}: every name keeps its own label, never an exception",
                 labels, ["ticket", "jira-assistant (remote)", "jira-assistant"])
        check(f"L5 ... and there is ONE warning line that names the table ({why})",
              warning.startswith("The agent-label table ") and "\n" not in warning and broken.name in warning, warning)
finally:
    J.LABELS_PATH = _saved
check_eq("L5 the real table is back: no warning, `ticket` is the scout's", (J.label_data_warning(), J.agent_label([ticket_row])), ("", "qa-scout"))
cleanup(_work)

# ---------------------------------------------------------------- B2 (t-363, B-253 g): the launch is journalled BEFORE the call
# On 02.10 the driver died silently at 05:38 in the middle of a role and `driver-runs.jsonl` held nothing of that launch:
# the row was written only after the call ended. A `launched` row (a new KIND of the same file, the same writer as the
# end row) now stands before the process starts. Every reader of the file must keep its numbers, and a `launched` row
# with no end row after it reads as a call that was running when the driver died - never as a completed one.
import io
import os
import contextlib

import story_run_common as SRC  # noqa: E402

B2_STUB = SRC.RECEIPT + r'''
import json, os, sys
from pathlib import Path
sys.stdin.buffer.read()
def seen(name):
    path = Path(os.environ[name])
    return path.read_text(encoding="utf-8") if path.exists() else None
Path(os.environ["B2_SNAPSHOT"]).write_text(json.dumps({"journal": seen("B2_JOURNAL"), "state": seen("B2_STATE")}), encoding="utf-8")
write_receipt("sess-b2")
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "session_id": "sess-b2", "num_turns": 3,
                  "total_cost_usd": 0.5, "duration_ms": 1000, "result": "done"}))
'''


def b2_driver(task):
    root, task_root, env = SRC.seed(task)
    stub = root / "b2_claude.py"
    stub.write_text(B2_STUB, encoding="utf-8")
    env["STORY_RUN_CLAUDE"] = str(stub)
    os.environ.update(B2_SNAPSHOT=str(root / "b2-snapshot.json"), B2_JOURNAL=str(task_root / "state" / "driver-runs.jsonl"),
                      B2_STATE=str(task_root / "state" / "driver-state.json"))
    return root, task_root, SRC.driver_for(root, env, task)


def b2_rows(task_root):
    """Every row of the file, the launch rows included - read directly, not through `story_run_common.jsonl`, which the
    other story-runner tests count CALLS with."""
    path = task_root / "state" / "driver-runs.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


b2_task = "QA-9"
b2_root, b2_task_root, b2_driver_obj = b2_driver(b2_task)
try:
    result = b2_driver_obj.run_claude("role", "do the work", role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
    snapshot = json.loads((b2_root / "b2-snapshot.json").read_text(encoding="utf-8"))
    while_running = [json.loads(line) for line in (snapshot["journal"] or "").splitlines() if line.strip()]
    check_eq("B2 the journal holds ONE row while the role's process runs, and it is the launch (the stub read the file itself)",
             [(r.get("kind"), r.get("call"), r.get("dispatch_id"), r.get("stage")) for r in while_running],
             [("launched", "role", "S1-qa-scout-1", "S1")])
    launched = while_running[0]
    check("B2 the launch row carries `started_at` and the model, and no pid, session, cost, exit code or `dispatch` (nothing a reader binds by)",
          launched.get("started_at") and launched.get("model") == "sonnet"
          and not {"pid", "session_id", "total_cost_usd", "exit_code", "dispatch"} & set(launched), str(launched))
    check("B2 while the role runs `in_flight` already names its process (the pid carrier; the row does not repeat it)",
          json.loads(snapshot["state"]).get("in_flight", {}).get("S1-qa-scout-1", {}).get("pid"), str(snapshot["state"])[:200])
    rows = b2_rows(b2_task_root)
    check_eq("B2 after the call: the launch row, then the end row (a new row, never a rewrite)",
             [(r["kind"], r.get("session_id")) for r in rows], [("launched", None), ("role", "sess-b2")])
    check("B2 the end row is what it always was: the cost, the turns, the exit code", rows[1]["total_cost_usd"] == 0.5 and rows[1]["num_turns"] == 3
          and rows[1]["exit_code"] == 0 and rows[1]["dispatch"] == "S1-qa-scout-1", str(rows[1]))
    # the conductor's call is journalled the same way, with no dispatch
    b2_driver_obj.run_claude("conductor", "what now", stage="S1")
    check_eq("B2 a conductor call is `launched` too, with an empty dispatch id",
             [(r["kind"], r.get("call"), r.get("dispatch_id")) for r in b2_rows(b2_task_root)[2:]],
             [("launched", "conductor", ""), ("conductor", None, None)])
    # a journal that cannot be written never stops the call (P1): the launch is said in one line
    real_journal = b2_driver_obj.journal_run
    calls = []

    def failing_launch(record):
        calls.append(record["kind"])
        if record["kind"] == "launched":
            raise OSError("disk full")
        return real_journal(record)

    b2_driver_obj.journal_run = failing_launch
    said = io.StringIO()
    with contextlib.redirect_stdout(said):
        b2_driver_obj.run_claude("role", "again", role="qa-scout", dispatch="S1-qa-scout-2", stage="S1")
    b2_driver_obj.journal_run = real_journal
    check("B2 a launch that cannot be journalled is one line, and the call still runs and journals its end",
          calls == ["launched", "role"] and "could not be journalled" in said.getvalue(), f"{calls} {said.getvalue()}")
finally:
    cleanup(b2_root)

# --- a driver killed between the two rows leaves the launch and no end row
b2_root, b2_task_root, b2_driver_obj = b2_driver(b2_task)
try:
    real_journal = b2_driver_obj.journal_run

    def killed_at_the_end(record):
        if record["kind"] != "launched":
            raise KeyboardInterrupt("the driver was killed")
        return real_journal(record)

    b2_driver_obj.journal_run = killed_at_the_end
    try:
        b2_driver_obj.run_claude("role", "do the work", role="qa-scout", dispatch="S1-qa-scout-1", stage="S1")
    except KeyboardInterrupt:
        pass
    rows = b2_rows(b2_task_root)
    check_eq("B2 a driver killed between the two rows leaves the `launched` row and NO end row",
             [(r["kind"], r.get("dispatch_id")) for r in rows], [("launched", "S1-qa-scout-1")])
    import dispatch_liveness as DL
    import retro_numbers as RN
    check_eq("B2 that row is not an ended call: the liveness reader finds no end for the dispatch",
             DL.driver_session_end(b2_root, b2_task, "S1-qa-scout-1"), None)
    check_eq("B2 ... it is no session, no role session of the retro and no resume", (J.parse_driver_runs(b2_root)[0],
             RN.driver_rows(b2_task_root), RN.resume_metrics(b2_task_root)["count"]), ({}, [], 0))
finally:
    cleanup(b2_root)


# --- every reader keeps its numbers: the same journal with and without the launch rows
def b2_readers(root, task):
    import dispatch_liveness as DL
    import retro_numbers as RN
    import story_progress as SP
    troot =root / "qa-factory" / "artifacts" / task
    by_session, _spread = J.parse_driver_runs(root)
    price = {"status": "agrees", "price_low_usd": 1.0, "price_high_usd": 1.0, "totals": {"b": 1.0}}
    return {"sessions": {sid: (e["task"], e["rows"]) for sid, e in sorted(by_session.items())},
            "charged": J.root_charged(by_session),
            "resumes": RN.resume_metrics(troot),
            "role_rows": RN.driver_rows(troot, by_session),
            "journal_sessions": RN.journal_sessions(troot),
            "ended": {d: DL.driver_session_end(root, task, d) for d in ("S1-qa-scout-1", "S3-qa-test-strategist-1")},
            "dispatches_named": SP._spend(root, None, task, price, SP._jsonl(troot / "state" / "driver-runs.jsonl"))["dispatches"]}


def b2_launch(call, dispatch, stage, role="", ts="2026-09-30T10:00:00+00:00"):
    return {"ts": ts, "kind": "launched", "call": call, "role": role, "dispatch_id": dispatch, "stage": stage,
            "started_at": ts, "model": "sonnet", "retry": 0}


plain = [row("a", 0.40, dispatch="S1-qa-scout-1", stage="S1", exit_code=0, resumed=False, ts="2026-09-30T10:00:00+00:00", turns=18),
         row("a", 0.90, dispatch="S1-qa-scout-1", stage="S1", exit_code=0, resumed=True, resume_reason="the refusal named a field",
             duration_ms=61000, ts="2026-09-30T10:05:00+00:00", turns=7),
         conductor("c", 0.30, ts="2026-09-30T10:07:00+00:00"),
         row("b", 1.10, dispatch="S3-qa-test-strategist-1", stage="S3", role="qa-test-strategist", exit_code=0, resumed=False,
             ts="2026-09-30T10:20:00+00:00", turns=11),
         {"ts": "2026-09-30T11:00:00+00:00", "kind": "delivery", "session_id": None, "total_cost_usd": None}]
with_launches = [b2_launch("role", "S1-qa-scout-1", "S1", "qa-scout", "2026-09-30T09:59:59+00:00"), plain[0],
                 b2_launch("role", "S1-qa-scout-1", "S1", "qa-scout", "2026-09-30T10:04:59+00:00"), plain[1],
                 b2_launch("conductor", "", "S1", "", "2026-09-30T10:06:59+00:00"), plain[2],
                 b2_launch("role", "S3-qa-test-strategist-1", "S3", "qa-test-strategist", "2026-09-30T10:19:59+00:00"), plain[3], plain[4],
                 b2_launch("role", "S3-qa-test-strategist-1", "S3", "qa-test-strategist", "2026-09-30T10:30:00+00:00")]   # died: no end row
b2_a = make_root({"T1": plain})
b2_b = make_root({"T1": with_launches})
try:
    before, after = b2_readers(b2_a, "T1"), b2_readers(b2_b, "T1")
    for name in before:
        check_eq(f"B2 reader `{name}` keeps its numbers when launch rows are interleaved (and a last one has no end row)",
                 after[name], before[name])
    check("B2 control: the readers read something (a reader that read nothing would agree with anything)",
          before["resumes"]["count"] == 1 and len(before["role_rows"]) == 3 and set(before["sessions"]) == {"a", "b", "c"}
          and before["ended"]["S1-qa-scout-1"] is not None, str(before)[:300])
    import task_price as TP
    check_eq("B2 task_price's count of journal rows that name no session is the same with and without the launch rows "
             "(the price says `incomplete` for a non-zero count: a launch row is not a call whose money is lost)",
             TP._rows_without_session(b2_b, "T1"), TP._rows_without_session(b2_a, "T1"))
finally:
    cleanup(b2_a)
    cleanup(b2_b)

# --- FR-43: the driver starts line-buffered, and a stream with no `reconfigure` is skipped without a word
import story_run  # noqa: E402

b2_root, b2_task_root, _env = SRC.seed("QA-9")
try:
    class Raw(io.BytesIO):
        def close(self):                       # keep the buffer readable after the wrapper is dropped
            pass

    wrapped_out = io.TextIOWrapper(Raw(), encoding="ascii", line_buffering=False)
    wrapped_err = io.TextIOWrapper(Raw(), encoding="ascii", line_buffering=False)
    saved_streams, saved_argv = (sys.stdout, sys.stderr), sys.argv
    sys.stdout, sys.stderr = wrapped_out, wrapped_err
    sys.argv = ["story_run.py", "--task", "QA-9", "--project", str(b2_root), "--dry-run"]
    try:
        code = story_run.main()
        got = (wrapped_out.line_buffering, wrapped_err.line_buffering, wrapped_out.encoding)
    finally:
        sys.stdout, sys.stderr = saved_streams
        sys.argv = saved_argv
    check_eq("B2 FR-43: main() makes stdout and stderr line-buffered (and keeps utf-8) before anything is printed",
             (code, got), (0, (True, True, "utf-8")))
    plain_out, plain_err = io.StringIO(), io.StringIO()            # no `reconfigure` at all
    sys.stdout, sys.stderr = plain_out, plain_err
    sys.argv = ["story_run.py", "--task", "QA-9", "--project", str(b2_root), "--dry-run"]
    try:
        code = story_run.main()
    finally:
        sys.stdout, sys.stderr = saved_streams
        sys.argv = saved_argv
    check_eq("B2 FR-43 edge: a stdout with no `reconfigure` is skipped silently - the run goes on and prints",
             (code, "would:" in plain_out.getvalue() or "claude command shape" in plain_out.getvalue()), (0, True))
finally:
    cleanup(b2_root)

# ---------------------------------------------------------------- CX1-15 F-1 (t-1135, critic t-1133): one meaning of `total_cost_usd`
# A Codex row writes the thread's RUNNING total in `total_cost_usd` (the meaning the reader gives it in every row of
# every host) and the call's own price in `call_cost_usd`, a key the reader does not know and must ignore. The two
# calls of the critic's probe: $0.30 (a short first call), then $0.45 (the resume with the person's words).
cx_first = row("thr-1", 0.30, call_cost_usd=0.30, host="codex", cost_basis="estimate")
cx_second = row("thr-1", 0.75, call_cost_usd=0.45, host="codex", cost_basis="estimate", resumed=True)
cx_charged, cx_unknown = J.root_charged({"thr-1": entry([cx_first, cx_second])})
check_eq("CX1-15 F-1: two Codex calls of one thread ($0.30, $0.45) are $0.75 - the running total, not the last call's price",
         (cx_charged, cx_unknown), ({"thr-1": 0.75}, []))
check("CX1-15 F-1: and their increments are the two calls' prices ([0.30, 0.45]), not [0.30, 0.15]",
      all(close(a, b) for a, b in zip(J.row_increments([cx_first, cx_second]), [0.30, 0.45])), repr(J.row_increments([cx_first, cx_second])))
# a FALLING call price: the third call is cheaper than the one before it; the total still rises, so nothing reads as unknown
cx_cheap = row("thr-1", 0.85, call_cost_usd=0.10, host="codex", resumed=True)
cx_charged, cx_unknown = J.root_charged({"thr-1": entry([cx_first, cx_second, cx_cheap])})
check_eq("CX1-15 F-1: a call that costs less than the one before it (0.45 then 0.10) is not 'falls': the thread is $0.85",
         (cx_charged, cx_unknown), ({"thr-1": 0.85}, []))
# an unpriced call (`total_cost_usd` unchanged, `call_cost_usd` None) adds nothing and breaks nothing
cx_unpriced = row("thr-1", 0.85, call_cost_usd=None, host="codex", resumed=True)
check_eq("CX1-15 F-1: an unpriced call repeats the thread's total and its increment is 0",
         (J.root_charged({"thr-1": entry([cx_first, cx_second, cx_cheap, cx_unpriced])})[0],
          close(J.row_increments([cx_first, cx_second, cx_cheap, cx_unpriced])[-1], 0.0)), ({"thr-1": 0.85}, True))
# the unknown key is ignored by the reader: the same rows without it read the same
bare = [{k: v for k, v in r.items() if k != "call_cost_usd"} for r in (cx_first, cx_second, cx_cheap)]
check_eq("CX1-15 F-1 conflicting pair: `call_cost_usd` is an unknown key to the reader - rows without it read the same",
         J.root_charged({"thr-1": entry(bare)}), J.root_charged({"thr-1": entry([cx_first, cx_second, cx_cheap])}))

finish("driver_journal")
