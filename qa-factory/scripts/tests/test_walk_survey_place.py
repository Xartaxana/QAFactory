#!/usr/bin/env python3
"""t-2277 FL-1 A: the `survey` place of the walk session, `--env`, the walk record, and `capture_cited` (fake backend, no browser, no network).

`walk_session.py open --place survey [--env <name>]` is the first look at a story or a reference stand: its attempts go under
`work/evidence/manual/survey-<item>/aN/`, the stand lease is held for the session's life (no lease per request), it has no case verdict,
the close writes the timing. `--env` names an `environments[]` row EXACTLY and only that stand's hosts are reachable. The walk record
names `place`, `stand`, `profiles` and `attempts`; `capture_cited` ties a quote to the attempt that took it.
Existing places are not changed: `no_env_keeps_first_row` walks the first row with no `--env` in the argv.
Run: `python -B test_walk_survey_place.py` (exit code = failures) or pytest.
"""
import contextlib
import io
import json
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "fixtures" / "manual-evidence"))
import test_walk_places as P  # noqa: E402
import test_walk_session as W  # noqa: E402
from harness import finish  # noqa: E402

MC, WS = P.MC, P.WS
WALK, GO = P.WALK, P.GO
must, must_eq, must_in = P.must, P.must_eq, P.must_in
ITEM = "R-1"
LOCAL = "localhost"
SAMPLE = "preview"


@contextlib.contextmanager
def survey(items=(ITEM,), cfg=None, env=None, actors=("user",), start=True, place="survey"):
    """A rig whose walk is a `survey` walk (or another place) on the row `env` names."""
    rig = W.Rig(items=items, cfg=cfg)
    rig.walk = WS.Walk(rig.t.task, WALK, list(items), list(actors), place=place, env=env)
    try:
        with mock.patch.object(P.run_suite, "project_root", lambda: rig.t.project):
            if start:
                rig.walk.start()
            yield rig
    finally:
        WS.SEAMS["clock"] = None
        rig.done()


def record(rig, walk=WALK):
    return WS.read_record(rig.t.task, walk)


def looked(rig, item=ITEM):
    """The capture path of one `look` in the item's current attempt (a real recorder capture, listed in captures.jsonl)."""
    code, answer = rig.call("look", item=item)
    must_eq(f"a look of {item} is stored", (code, answer["status"]), (0, "ok"))
    return answer["look"]["captures"][0]


def cite(rig, path, quote, item=ITEM, walk=WALK, stand=""):
    return WS.capture_cited(rig.t.task, walk, item, path, quote, stand=stand)


def add_capture(rig, name, document, item=ITEM):
    """A capture file of the item's attempt as the recorder stores an HTTP capture (a JSON document), listed in its captures.jsonl."""
    attempt = rig.walk.item_rec[item]["attempt"]
    target = attempt.dir / name
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rel = target.relative_to(rig.t.task).as_posix()
    with (attempt.dir / "captures.jsonl").open("a", encoding="utf-8") as out:
        out.write(json.dumps({"kind": "http", "path": rel}) + "\n")
    return rel


# --- the place -------------------------------------------------------------------------------

def test_survey_attempts_under_survey_root():
    with survey() as rig:
        must_eq("survey is a place with the prefix `survey-`", (WS.PLACES[-1], WS.LANE_PREFIX["survey"]), ("survey", "survey-"))
        code, answer = rig.call("item", item=ITEM)
        must_eq("`item` opens a1 under survey-<item>", (code, answer["dir"]), (0, "work/evidence/manual/survey-R-1/a1"))
        code, answer = rig.step(GO, item=ITEM)
        must_eq("a step runs", (code, answer["status"]), (0, "done"))
        attempt = rig.walk.item_rec[ITEM]["attempt"]
        must_eq("the attempt's case is survey-R-1", attempt.case, "survey-R-1")
        must("the evidence is there and nothing sits under the bare id or a settle root",
             (attempt.dir / "steps.jsonl").is_file() and not MC.case_root(rig.t.task, ITEM).exists()
             and not MC.case_root(rig.t.task, "settle-R-1").exists())
        code, answer = rig.step(GO, item="R-9")
        must_eq("a new plain id is taken (lane_item_ok), as in a settle lane", (code, rig.walk.item_root("R-9").name), (0, "survey-R-9"))


def test_survey_has_no_case_verdict():
    with survey() as rig:
        code, answer = rig.call("verdict", item=ITEM, verdict={"thens": []})
        must_eq("a verdict is refused", (code, answer["status"]), (2, "refused"))
        must_in("the door names the commands that record a walk", "first_look.py put", answer["text"])
        must("and nothing was stored", not (rig.t.task / "work" / "walks").exists())
        must("the case record rules never ran: no attempt was opened by the refusal", ITEM not in rig.walk.item_rec)
        code, answer = rig.call("claim", item=ITEM, kind="book", instance="b1")
        must_eq("a claim is refused", (code, answer["status"]), (2, "refused"))
        must_in("the door names the commands that record a walk", "first_look.py put", answer["text"])
        must("and says nothing of a lease per request", "per request" not in answer["text"] and "--case settle-" not in answer["text"], answer["text"])


def test_survey_holds_lease_for_life():
    with survey(cfg=P.leased_cfg()) as rig:
        must("the survey walk holds the lease between requests", f"walk:{WALK}" in P.leases(rig) and not P.free(rig))
        rig.step(GO, item=ITEM)
        must("and after a request", f"walk:{WALK}" in P.leases(rig))
        rig.walk._shutdown("closed", "test", probe=False)
        must("its end frees the stand", P.free(rig))
        must_eq("idle_s applies to it (not exempt)", "survey" in (rig.walk.d.get("idle_places_exempt") or ()), False)


def test_survey_requests_take_no_page_lease():
    taken = []

    @contextlib.contextmanager
    def counting(self):
        taken.append(self.place)
        yield
    with survey(cfg=P.leased_cfg()) as rig, mock.patch.object(WS.Walk, "page_lease", counting):
        for op, fields in (("item", {"item": ITEM}), ("step", {"item": ITEM, "steps": GO}), ("look", {"item": ITEM}), ("final", {"item": ITEM})):
            code, answer = rig.call(op, **fields)
            must(f"survey {op} is answered, not stand_busy", code in (0, 1) and answer.get("status") != "stand_busy", str(answer)[:200])
        must_eq("close", rig.call("close")[0], 0)
        must_eq("no request of a survey walk asked for a lease of its own", taken, [])
    with survey(items=("p1",), place="settle") as rig, mock.patch.object(WS.Walk, "page_lease", counting):
        rig.step(GO, item="p1")
        must("a settle walk still does (the control of this test)", taken == ["settle"], str(taken))


def test_survey_item_door_names_put_commands():
    with survey() as rig:
        code, answer = rig.call("step", item="a/b", steps=GO)
        must_eq("an item that is no plain id is refused", code, 2)
        must("the door names both record commands", all(w in answer["text"] for w in ("first_look.py put", "reference_snapshot.py put")), answer["text"])
        must("and not the settle capture door", "--case settle-" not in answer["text"])
    with survey(start=False) as rig:
        bad = WS.request_problems(None, {"op": "open", "task_root": str(rig.t.task), "walk": WALK, "items": ["a b"], "actors": ["user"], "place": "survey"})
        must("an `open` with a bad id says what a survey id is", bool(bad) and "requirement id" in " ".join(bad), str(bad))
        good = WS.request_problems(None, {"op": "open", "task_root": str(rig.t.task), "walk": WALK, "items": ["R-1", "el.3"], "actors": ["user"], "place": "survey"})
        must_eq("`R-1` and an element id pass", good, [])


def test_survey_close_writes_timing():
    with survey() as rig:
        rig.step(GO, item=ITEM)
        must_eq("close", rig.call("close")[0], 0)
        lines = MC.jsonl_rows(rig.t.task / "work" / "walks" / WALK / "timing.jsonl")
        must_eq("the timing line names the place", [(r["item"], r["place"]) for r in lines], [(ITEM, "survey")])


# --- --env -----------------------------------------------------------------------------------

def test_env_by_exact_name():
    with survey(env=SAMPLE, actors=("guest",)) as rig:
        must_eq("the stand is the row of that name", rig.walk.stand["name"], SAMPLE)
        must_eq("the record names it", record(rig)["stand"], SAMPLE)


def test_env_case_variant_refused():
    with survey(env="Preview", actors=("guest",), start=False) as rig:
        try:
            rig.walk.start()
        except WS.ServerDead as dead:
            must_in("the refusal names the stands there are", f"{LOCAL}, {SAMPLE}", dead.reason)
        else:
            raise AssertionError("`Preview` is not `preview`")
        must("nothing was opened", not rig.made)
    for bad in ("PREVIEW", " preview", "preview ", ""):
        with survey(env=bad, actors=("guest",), start=False) as rig:
            must_in(f"{bad!r} is refused too", "is not in config.json", WS.env_row(rig.t.cfg, bad)[1])
            must(f"{bad!r} gives no row", not WS.env_row(rig.t.cfg, bad)[0])
    twice = {"environments": [{"name": "dev", "url": "http://a"}, {"name": "dev", "url": "http://b"}, {"name": "qa"}]}
    row, problem = WS.env_row(twice, "dev")
    must("a name that two rows carry picks no row", not row)
    must_in("the door names the duplicate and what to do", "`dev` names 2 rows", problem)
    must_in("and says to rename one", "rename one", problem)
    must_eq("a name of one row still resolves", WS.env_row(twice, "qa"), ({"name": "qa"}, ""))


def test_env_absent_name_refused():
    with survey(start=False) as rig:
        args = WS.build_parser().parse_args(["open", "--task-root", str(rig.t.task), "--walk", WALK, "--items", ITEM, "--actor", "user",
                                              "--place", "survey", "--env", "ghost"])
        spawned = []
        WS.SEAMS["spawn"] = lambda argv, log: spawned.append(argv)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = WS.open_walk(args, wait_s=0.2)
        must_eq("`open --env ghost` ends 2 before a process is spawned", (code, spawned), (2, []))
        must_in("and names the stands", f"there are: {LOCAL}, {SAMPLE}", out.getvalue() + err.getvalue())
        must_in("the refusal is the common shape (status refused)", '"status": "refused"', out.getvalue())
        WS.SEAMS["spawn"] = None
        spawned.clear()
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(WS.MC, "load_config", side_effect=OSError("locked")), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            args.env = "preview"
            WS.SEAMS["spawn"] = lambda argv, log: spawned.append(argv)
            try:
                WS.open_walk(args, wait_s=0.2)
            except OSError:
                raise AssertionError("an unreadable config must not crash `open`")
            finally:
                WS.SEAMS["spawn"] = None
        must_eq("an OSError from the config is left to the server's refusal: the spawn was reached", len(spawned), 1)
    with survey(env="ghost", actors=("guest",), start=False) as rig:
        try:
            rig.walk.start()
        except WS.ServerDead as dead:
            must_in("the server refuses it as well", "the stand `ghost` is not in config.json", dead.reason)
        else:
            raise AssertionError("a stand that is not there must stop the start")
        must_eq("the record says dead", record(rig)["state"], "dead")


def test_no_env_keeps_first_row():
    with survey(actors=("guest",), place="case", items=(W.CASE,)) as rig:
        must_eq("no `--env`: the first row of config.json", rig.walk.stand.get("name"), LOCAL)
        must_eq("and its hosts are those of the whole config, as before", rig.walk.hosts, set(MC.stand_hosts(rig.t.cfg, root=rig.t.project)))
    with survey(start=False, actors=("guest",)) as rig:
        seen = []
        WS.SEAMS["spawn"] = lambda argv, log: (seen.append(list(argv)), type("H", (), {"kill": lambda self: None})())[1]
        parse = WS.build_parser().parse_args
        base = ["open", "--task-root", str(rig.t.task), "--walk", WALK, "--items", W.CASE, "--actor", "user"]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            WS.open_walk(parse(base), wait_s=0.1)
            WS.open_walk(parse(base + ["--place", "survey", "--env", SAMPLE]), wait_s=0.1)
        WS.SEAMS["spawn"] = None
        must("a call without `--env` keeps the old argv", "--env" not in seen[0], str(seen[0]))
        must_eq("a call with it hands the name to the own process", seen[1][seen[1].index("--env") + 1], SAMPLE)
        must_eq("`serve` takes the flag", parse(["serve", "--task-root", "t", "--walk", "w", "--items", "i", "--actor", "a", "--env", "x"]).env, "x")


def test_env_hosts_are_the_named_stand_only():
    both = {}
    for name in (LOCAL, SAMPLE):
        with survey(env=name, actors=("guest",)) as rig:
            both[name] = set(rig.walk.hosts)
            must_eq(f"{name}: the browser may reach exactly the hosts of that row", sorted(rig.made[0].allowed), sorted(both[name]))
    must("each stand has hosts", all(both.values()), str(both))
    must("and the two sets share none: a host of the sample is no host of the walk, nor the reverse", not (both[LOCAL] & both[SAMPLE]), str(both))
    must("the sample's own host is the named one", any(h[1] == "stand.example.test" for h in both[SAMPLE]), str(both))


# --- the record --------------------------------------------------------------------------------

def test_walk_record_names_place_stand_profiles_attempts():
    with survey() as rig:
        must_eq("before any item: place and stand are named, no attempts", (record(rig)["place"], record(rig)["stand"], record(rig)["attempts"]),
                ("survey", LOCAL, {}))
        rig.step(GO, item=ITEM)
        rig.step(GO, item="R-2")
        rec = record(rig)
        must_eq("the profile of the UI is the walk's", rec["profiles"], {"ui": rig.walk.profile})
        must("and it is a profile id", bool(rec["profiles"]["ui"]), str(rec))
        must_eq("the attempt of every item opened", rec["attempts"], {ITEM: "a1", "R-2": "a1"})
    with survey(place="case", items=(W.CASE,)) as rig:
        must_eq("a case walk carries the same keys", (record(rig)["place"], record(rig)["stand"]), ("case", LOCAL))


# --- capture_cited -----------------------------------------------------------------------------

def test_capture_in_attempt_ok():
    with survey() as rig:
        path = looked(rig)
        must_eq("words of the capture of this attempt are cited", cite(rig, path, "button: Pay"), "")
        must_eq("with the stand named", cite(rig, path, "heading: Cart", stand=LOCAL), "")
        must_eq("a quote with a line break in it (squashed as the verdict's)", cite(rig, path, "heading: Cart button: Pay"), "")
        hello = "".join(chr(c) for c in (0x41f, 0x440, 0x438, 0x432, 0x435, 0x442)) + ", ok"      # non-ASCII text is stored as it is (ensure_ascii=False), so it is quoted as it is
        doc = add_capture(rig, "http-1.json", {"request": {"method": "GET", "url": "/v1/x"}, "response": {"status": 200, "body": hello}})
        must_eq("a stored HTTP document is quoted as it is stored", cite(rig, doc, hello), "")


def test_capture_of_other_item_refused():
    with survey() as rig:
        first = looked(rig)
        rig.step(GO, item="R-2")
        second = looked(rig, "R-2")
        why = cite(rig, second, "button: Pay", item=ITEM)
        must("a capture of another item holds nothing", why != "" and "another item" in why and "Door:" in why, why)
        must_eq("each item cites its own", (cite(rig, second, "button: Pay", item="R-2"), cite(rig, first, "button: Pay")), ("", ""))
        must("an item with no attempt is refused", cite(rig, first, "button: Pay", item="R-3") != "")


def test_capture_of_other_walk_refused():
    with survey() as rig:
        path = looked(rig)
        must("a walk that was never opened is refused", "no record" in cite(rig, path, "button: Pay", walk="S6-nobody"))
        must("a walk id that is no plain id is refused", "plain id" in cite(rig, path, "button: Pay", walk="../x"))
        other = {**record(rig), "walk": "S6-other", "attempts": {ITEM: "a2"}}
        WS.event_store.atomic_json(WS.record_path(rig.t.task, "S6-other"), other)
        why = cite(rig, path, "button: Pay", walk="S6-other")
        must("a walk whose attempt is another does not cite this walk's file", why != "" and "another walk" in why, why)


def test_capture_of_reference_walk_refused_for_first_look():
    with survey() as rig:
        path = looked(rig)
        for place in ("case", "settle", "control", None):
            WS.event_store.atomic_json(WS.record_path(rig.t.task, "S6-ref"), {**record(rig), "walk": "S6-ref", **({"place": place} if place else {"place": ""})})
            why = cite(rig, path, "button: Pay", walk="S6-ref")
            must(f"a {place} walk is no first look: refused", why != "" and "not a survey walk" in why, why)
        why = cite(rig, path, "button: Pay", stand=SAMPLE)
        must("a survey walk of one stand is no evidence of another", why != "" and f"`{LOCAL}`" in why and "Door:" in why, why)


def test_capture_of_earlier_attempt_refused():
    with survey() as rig:
        first = looked(rig)
        rig.walk._shutdown("closed", "test", probe=False)
        rig.walk = WS.Walk(rig.t.task, WALK, [ITEM], ["user"], place="survey", reopened=1)
        with mock.patch.object(P.run_suite, "project_root", lambda: rig.t.project):
            rig.walk.start()
            second = looked(rig)
        must_eq("a reopened walk is on a2", record(rig)["attempts"], {ITEM: "a2"})
        why = cite(rig, first, "button: Pay")
        must("a capture of an earlier attempt is refused", why != "" and "earlier attempt" in why, why)
        must_eq("the current attempt's is cited", cite(rig, second, "button: Pay"), "")


def test_walk_record_without_stand_refused():
    with survey() as rig:
        path = looked(rig)
        rec = record(rig)
        for label, changed in (("no stand key", {k: v for k, v in rec.items() if k != "stand"}), ("an empty stand", {**rec, "stand": ""}),
                               ("no attempts", {k: v for k, v in rec.items() if k != "attempts"}), ("attempts of the wrong shape", {**rec, "attempts": ["a1"]})):
            WS.event_store.atomic_json(WS.record_path(rig.t.task, WALK), changed)
            must(f"a record with {label} is refused", cite(rig, path, "button: Pay", stand=LOCAL) != "")
        WS.event_store.atomic_json(WS.record_path(rig.t.task, WALK), {k: v for k, v in rec.items() if k != "stand"})
        must_in("and the reason says the record names no stand", "names no stand", cite(rig, path, "button: Pay"))
        WS.record_path(rig.t.task, WALK).write_text("{not json", encoding="utf-8")
        must("an unreadable record is refused", cite(rig, path, "button: Pay") != "")


def test_quote_not_in_file_refused():
    with survey() as rig:
        path = looked(rig)
        for quote in ("a button nobody drew", "", "   ", "button: pay"):
            why = cite(rig, path, quote)
            must(f"{quote!r} is refused with a door", why != "" and "Door:" in why, why)


def test_path_outside_root_refused():
    with survey() as rig:
        path = looked(rig)
        outside = rig.t.task.parent / "elsewhere.txt"
        outside.write_text("button: Pay", encoding="utf-8")
        for bad in ("../elsewhere.txt", str(outside), "work/evidence/manual/survey-R-1/a1/../../../../../elsewhere.txt", "", "work/other.txt",
                    "work/evidence/manual/survey-R-1/a1/missing.txt", "work/evidence/manual/survey-R-1/a1", None):
            why = cite(rig, bad, "button: Pay")
            must(f"{bad!r} is refused", why != "", why)
        must_eq("the real one still passes", cite(rig, path, "button: Pay"), "")


def test_quote_across_escaped_char_refused():
    with survey() as rig:
        rig.step(GO, item=ITEM)
        doc = add_capture(rig, "http-2.json", {"response": {"status": 200, "body": 'he said "stop" now\nthen left', "image": "aGVsbG8gd29ybGQ="}})
        must_eq("a fragment without such characters is cited", cite(rig, doc, "he said"), "")
        for label, quote in (("a quotation mark", 'he said "stop" now'), ("a line break", "now\nthen left"), ("a decoded base64 body", "hello world")):
            why = cite(rig, doc, quote)
            must(f"a quote crossing {label} is refused with a door", why != "" and "Door:" in why, why)
        must_in("and says why for the escaped one", "escaped", cite(rig, doc, 'he said "stop" now'))
        cut = add_capture(rig, "http-3.json", {"response": {"status": 200, "truncated": True, "body": "the first bytes"}})
        why = cite(rig, cut, "the bytes beyond the cap")
        must("a quote past the cut part is refused and the reason says it is beyond", why != "" and "beyond the stored part" in why, why)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_walk_survey_place")


if __name__ == "__main__":
    main()
