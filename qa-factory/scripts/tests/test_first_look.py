#!/usr/bin/env python3
"""t-2277 FL-2: the record of the first look, its attempt, its one writer and its one reader, the share and the `due` question.

`first_look.py` is checked on files built by hand (no browser, no network): a story folder with a register, a context manifest and a
pipeline; a survey walk record and the captures of its attempts as the recorder stores them (HTTP documents listed in `captures.jsonl`,
the form `walk_session.capture_cited` reads). One test per item of the FL-2 block of the spec; the names are the spec's.
Run: `python -B test_first_look.py` (exit code = failures) or pytest.
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness  # noqa: E402
from harness import check, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import first_look as FL  # noqa: E402
import grounding_table as GT  # noqa: E402
import manual_capture as MC  # noqa: E402
import stand_identity as SI  # noqa: E402
import walk_session as WS  # noqa: E402

HEAD_A, HEAD_B = "a" * 40, "b" * 40
WALK, STAND, PROFILE = "S3-first-look", "dev", "prof-ui"
BODY = "The cart page shows a Pay button and the total."
QUOTE = "Pay button"
PIPELINE = {"ticket": "QA-1", "environment": STAND, "environment_pending": False}


class Story:
    """A story folder with a register, a manifest, a pipeline and (on `walk()`) a survey walk with a capture per item."""

    def __init__(self, tmp, ids=("R-1", "R-2"), heads=(("product", HEAD_A),), pipeline=None):
        self.root = Path(tmp)
        self.task = self.root / "QA-1"
        (self.task / "work").mkdir(parents=True)
        self.set_register({r: f"The stand shows {r}." for r in ids})
        self.set_heads(heads)
        self.set_pipeline(PIPELINE if pipeline is None else pipeline)

    def set_register(self, texts: dict):
        rows = "".join(f"| {r} | {t} | task |\n" for r, t in texts.items())
        (self.task / "work" / "requirements-register.md").write_text(
            "# Requirements register\n\n## Register\n\n| ID | Requirement | Source |\n|---|---|---|\n" + rows, encoding="utf-8")

    def set_heads(self, heads):
        entries = [{"repo_id": name, "source_sha": sha, "diff_path": f"work/impl-diff-{name}.txt"} for name, sha in heads]
        (self.task / "work" / "context-manifest.json").write_text(json.dumps({"implementations": entries}), encoding="utf-8")

    def set_pipeline(self, pipeline: dict):
        (self.task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")

    def walk(self, items=("R-1", "R-2"), place="survey", wid=WALK, stand=STAND):
        record = {"walk": wid, "place": place, "stand": stand, "profiles": {"ui": PROFILE}, "attempts": {i: "a1" for i in items}}
        path = WS.record_path(self.task, wid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        return {i: self.capture(i) for i in items}

    def capture(self, item, body=BODY, name="http-1.json", attempt="a1"):
        """An HTTP capture of the item's attempt, as the recorder stores it, listed in the attempt's captures.jsonl."""
        folder = MC.case_root(self.task, f"survey-{item}") / attempt
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / name
        target.write_text(json.dumps({"request": {"method": "GET", "url": "/cart"}, "response": {"status": 200, "body": body}},
                                     ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rel = target.relative_to(self.task.resolve()).as_posix()
        with (folder / "captures.jsonl").open("a", encoding="utf-8") as out:
            out.write(json.dumps({"kind": "http", "path": rel}) + "\n")
        return rel

    def begin(self, dispatch=WALK):
        return FL.begin(self.task, dispatch, STAND)

    def ready(self):
        """The walk is opened and every item has a capture: what a walker's `put` needs."""
        caps = self.walk()
        self.begin()
        return caps

    def rows(self, caps, **status):
        """One whole row per register requirement (the status per id in `status`, else confirms) citing its own capture."""
        out = []
        for req in FL._register(self.task)[0]["ids"]:
            word = status.get(req.replace("-", "_"), "confirms")
            row = {"req": req, "status": word, "why": f"Opened the stand and looked for {req}."}
            if word in ("missing", "unreachable"):
                row["blocked_by"] = "product"
            if req in caps:
                row.update(evidence=[caps[req]], quote=QUOTE)
            out.append(row)
        return out

    def file(self, record, name="rows.yaml") -> Path:
        path = self.root / name
        path.write_text(GT.dump_yaml(record), encoding="utf-8")
        return path

    def put(self, rows, **extra):
        return FL.put(self.task, self.file({"rows": rows, **extra}))

    def snapshot(self) -> dict:
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in sorted(self.root.rglob("*")) if p.is_file()}

    def confirm(self, kind="deployed", revision=HEAD_A):
        SI.add_confirmation(self.root, self.task, task=self.task.name, environment_id=STAND, profile_id=PROFILE, kind=kind,
                            words="the build is on the stand", revision=revision, stand_definition_sha="c" * 64,
                            story_revision=revision if kind == "test_deployed" else "")


def written(story, done) -> bool:
    return bool(done["written"]) and FL._record_path(story.task).is_file()


def problems_text(done) -> str:
    return " | ".join(done["problems"])


# --- put: what code refuses ------------------------------------------------------------------------------------------

def test_put_refuses_word_outside_data():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        caps = s.ready()
        for label, change, needle in (("a status of no list", {"status": "works"}, "`status` is one of"),
                                      ("a blocked_by of no list", {"status": "missing", "blocked_by": "nobody"}, "`blocked_by` is one of"),
                                      ("a missing row with no blocked_by", {"status": "missing"}, "says what stopped it"),
                                      ("an unreachable row with no blocked_by", {"status": "unreachable"}, "says what stopped it")):
            rows = s.rows(caps)
            rows[0] = {k: v for k, v in rows[0].items() if k != "blocked_by"} | change
            done = s.put(rows)
            check(f"put_refuses_word_outside_data: {label} is refused, nothing written", not done["written"]
                  and not FL._record_path(s.task).exists(), problems_text(done))
            check_in(f"put_refuses_word_outside_data: {label} names the word list", needle, problems_text(done))
        done = s.put([{**r, "blocked_by": "nobody"} if r["req"] == "R-1" else r for r in s.rows(caps)])
        check_in("put_refuses_word_outside_data: the door names the closed list", "product, access, nature", problems_text(done))
        check("put_refuses_word_outside_data: an unknown key of a row is refused by name",
              "unknown key `mood`" in problems_text(s.put([{**r, "mood": "good"} for r in s.rows(caps)])))


def test_put_needs_one_row_per_register_req():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp, ids=("R-1", "R-2", "R-3"))
        caps = s.walk(items=("R-1", "R-2", "R-3"))
        s.begin()
        rows = s.rows(caps)
        done = s.put(rows[:1])
        check_in("put_needs_one_row_per_register_req: a missing requirement is named", "no row for R-2, R-3", problems_text(done))
        done = s.put(rows + [rows[0]])
        check_in("put_needs_one_row_per_register_req: a second row of one requirement is refused", "a second row for R-1", problems_text(done))
        check("put_needs_one_row_per_register_req: nothing was written", not FL._record_path(s.task).exists())
        check("put_needs_one_row_per_register_req: no rows at all is refused", not s.put([])["written"])
        done = s.put(rows)
        check_eq("put_needs_one_row_per_register_req: one row per requirement is written", (done["written"], done["rows"]), (True, 3))


def test_put_refuses_req_outside_register():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        caps = s.ready()
        rows = s.rows(caps)
        done = s.put(rows + [{"req": "R-9", "status": "missing", "blocked_by": "product", "why": "looked for it"}])
        check_in("put_refuses_req_outside_register: R-9 is not in the register", "R-9 is not in the register", problems_text(done))
        bad = s.put([{**rows[0], "req": "TC-1"}, rows[1]])
        check_in("put_refuses_req_outside_register: a req that is no R-n is refused", "`req` is a requirement id of the register", problems_text(bad))
        check("put_refuses_req_outside_register: nothing written", not FL._record_path(s.task).exists())


def test_put_needs_capture_except_nature():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        caps = s.ready()
        bare = lambda req, status, blocked: {"req": req, "status": status, "blocked_by": blocked, "why": "no way to see it"}  # noqa: E731
        done = s.put([{"req": "R-1", "status": "confirms", "why": "saw it"}, bare("R-2", "missing", "nature")])
        check_in("put_needs_capture_except_nature: a confirms row with no capture is refused", "cites a capture of this walk", problems_text(done))
        done = s.put([s.rows(caps)[0], bare("R-2", "missing", "product")])
        check_in("put_needs_capture_except_nature: a missing/product row with no capture is refused", "rows[1] (R-2)", problems_text(done))
        done = s.put([s.rows(caps)[0], bare("R-2", "unreachable", "access")])
        check("put_needs_capture_except_nature: an access row needs a capture too", not done["written"], problems_text(done))
        no_quote = [{k: v for k, v in r.items() if k != "quote"} for r in s.rows(caps)]
        check_in("put_needs_capture_except_nature: a capture with no quote is refused", "`quote` is words copied", problems_text(s.put(no_quote)))
        done = s.put([s.rows(caps)[0], bare("R-2", "missing", "nature")])
        check("put_needs_capture_except_nature: a nature row needs no capture", done["written"], problems_text(done))
        done = s.put([s.rows(caps)[0], bare("R-2", "missing", "nature") | {"evidence": [caps["R-1"]], "quote": QUOTE}])
        check("put_needs_capture_except_nature: a nature row that cites a capture of another item is still refused", not done["written"], problems_text(done))


def test_put_refuses_capture_of_other_walk():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        caps = s.ready()
        rows = s.rows(caps)
        rows[1]["evidence"] = [caps["R-1"]]
        done = s.put(rows)
        check_in("put_refuses_capture_of_other_walk: a capture of another item holds nothing", "another item", problems_text(done))
        rows = s.rows(caps)
        rows[0]["quote"] = "a button nobody drew"
        check_in("put_refuses_capture_of_other_walk: a quote not in the capture is refused", "is not in", problems_text(s.put(rows)))
        s.walk(place="case")
        check_in("put_refuses_capture_of_other_walk: the capture of a walk that is no survey walk is refused", "not a survey walk",
                 problems_text(s.put(s.rows(caps))))
        s.walk(stand="staging")
        check_in("put_refuses_capture_of_other_walk: the walk's stand is the attempt's: another stand is refused", "walked the stand `staging`",
                 problems_text(s.put(s.rows(caps))))
        s.walk()
        s.begin("S3-ghost")
        check_in("put_refuses_capture_of_other_walk: an attempt whose walk has no record cites nothing", "has no record", problems_text(s.put(s.rows(caps))))
        check("put_refuses_capture_of_other_walk: nothing was written", not FL._record_path(s.task).exists())


def test_put_accepts_http_capture():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        caps = s.walk()
        s.begin()
        listed = [json.loads(line) for line in (MC.case_root(s.task, "survey-R-1") / "a1" / "captures.jsonl").read_text(encoding="utf-8").splitlines()]
        check_eq("put_accepts_http_capture: the fixture is an HTTP line of captures.jsonl", [r["kind"] for r in listed], ["http"])
        text = (f"rows:\n  - req: R-1\n    status: confirms\n    why: GET /cart answered 200 and the body names the button.\n"
               f"    evidence:\n      - {caps['R-1']}\n    quote: {QUOTE}\n    path:\n      api:\n        - method: GET\n          path: /cart\n"
               f"          auth: none\n          sample:\n            status: 200\n            response: {QUOTE}\n          seen: yes\n"
               f"  - req: R-2\n    status: missing\n    blocked_by: nature\n    why: a build setting no request shows\n")
        path = s.root / "hand.yaml"
        path.write_text(text, encoding="utf-8")
        done = FL.put(s.task, path)
        check("put_accepts_http_capture: a hand-written file citing an HTTP capture is written", done["written"], problems_text(done))
        got = FL.read(s.task)
        row = got["rows"][0]
        check_eq("put_accepts_http_capture: the route is read back", (row["path"]["api"][0]["method"], row["path"]["api"][0]["seen"]), ("GET", "yes"))
        check_eq("put_accepts_http_capture: and the attempt reads written", FL.read_attempt(s.task)["outcome"], "written")


def test_put_ignores_role_sent_head_and_walk():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        caps = s.ready()
        done = s.put(s.rows(caps), walk="S3-evil", stand="prod", stand_build="confirmed", source_head={"product": "f" * 40},
                     register_hash="dead", sides_met={"product": "real"}, walked_at="1999-01-01T00:00:00+00:00")
        check("put_ignores_role_sent_head_and_walk: the record is written", done["written"], problems_text(done))
        check_eq("put_ignores_role_sent_head_and_walk: the ignored keys are named",
                 sorted(done["ignored"]), sorted(["walk", "stand", "stand_build", "source_head", "register_hash", "sides_met", "walked_at"]))
        got = FL.read(s.task)
        text, reg_hash = FL.current_keys(s.task)
        check_eq("put_ignores_role_sent_head_and_walk: the walk is the attempt's", got["walk"], WALK)
        check_eq("put_ignores_role_sent_head_and_walk: the heads are the measured ones", got["source_head"], {"product": HEAD_A})
        check_eq("put_ignores_role_sent_head_and_walk: the register hash is the measured one", got["register_hash"], reg_hash)
        check_eq("put_ignores_role_sent_head_and_walk: the stand build is not the role's word", got["stand_build"], "not_established")
        raw = FL._record_path(s.task).read_text(encoding="utf-8")
        check("put_ignores_role_sent_head_and_walk: the stand and the time are the code's, no sides_met on a real story",
              f'stand: "{STAND}"' in raw and "1999" not in raw and "sides_met" not in raw, raw[:300])


def test_put_without_attempt_refused():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        caps = s.walk()
        done = s.put(s.rows(caps))
        check_in("put_without_attempt_refused: no attempt, the walk is not open", "is not open", problems_text(done))
        check("put_without_attempt_refused: nothing written, no attempt invented", not FL._record_path(s.task).exists() and not FL._attempt_path(s.task).exists())
        s.begin()
        check("put_without_attempt_refused: once the driver has begun, the same file is written", s.put(s.rows(caps))["written"])


def test_put_null_needs_known_reason():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        for word in ("because", "", "NO_STAND", "no stand"):
            done = FL.put(s.task, None, word) if word else FL.put(s.task, None, "x")
            check(f"put_null_needs_known_reason: {word or 'x'!r} is refused", not done["written"] and not FL._record_path(s.task).exists())
        check_in("put_null_needs_known_reason: the door lists the declared words", "no_code_yet, empty_register, register_unreadable",
                 problems_text(FL.put(s.task, None, "because")))
        for reason in FL._words("null_reasons"):
            check(f"put_null_needs_known_reason: {reason} is declared and written", FL.put(s.task, None, reason)["written"])


def test_put_null_has_empty_rows_and_gap():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        done = FL.put(s.task, None, "no_stand")
        got = FL.read(s.task)
        check_eq("put_null_has_empty_rows_and_gap: written, null named, rows empty", (done["written"], got["null"], got["rows"]), (True, "no_stand", []))
        check("put_null_has_empty_rows_and_gap: one gap line names the reason", len(got["gaps"]) == 1 and "no stand" in got["gaps"][0], str(got["gaps"]))
        check("put_null_has_empty_rows_and_gap: it needs no attempt and leaves none", not FL._attempt_path(s.task).exists())
        s.ready()
        FL.put(s.task, None, "walk_not_opened")
        check_eq("put_null_has_empty_rows_and_gap: with an attempt the attempt stays as it was", FL.read_attempt(s.task)["outcome"], "walking")


def test_null_never_replaces_current_walked_record():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        caps = s.ready()
        check("null_never_replaces_current_walked_record: fixture: a walked record", s.put(s.rows(caps))["written"])
        pending = {**PIPELINE, "environment_pending": True}
        got = FL.due(s.task, pending, {})
        check_eq("null_never_replaces_current_walked_record: the stand goes pending, due names no_stand", got[:2], (False, "no_stand"))
        done = FL.put(s.task, None, got[1])
        check_in("null_never_replaces_current_walked_record: the null is refused with its door", "does not replace it", problems_text(done))
        after = FL.read(s.task)
        check_eq("null_never_replaces_current_walked_record: the walked record is intact", (len(after["rows"]), after["null"]), (2, ""))
        check_eq("null_never_replaces_current_walked_record: the stand is back, still no second paid walk", FL.due(s.task, PIPELINE, {})[0], False)
        s.set_heads((("product", HEAD_B),))
        check("null_never_replaces_current_walked_record: control: a stale walked record IS replaced", FL.put(s.task, None, "no_stand")["written"]
              and FL.read(s.task)["null"] == "no_stand")


def test_put_refuses_blocked_by_on_reachable_status():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        caps = s.ready()
        for status in ("confirms", "contradicts"):
            for word in ("access", "nature", "product"):
                rows = s.rows(caps)
                rows[0] = {"req": "R-1", "status": status, "blocked_by": word, "why": "Looked."}
                done = s.put(rows)
                check(f"put_refuses_blocked_by_on_reachable_status: {status} + {word} is refused", not done["written"]
                      and "`blocked_by` is only for missing / unreachable rows" in problems_text(done), problems_text(done))
        rows = s.rows(caps, R_1="missing")
        rows[0].update(blocked_by="nature")
        rows[0].pop("evidence"), rows[0].pop("quote")
        check("put_refuses_blocked_by_on_reachable_status: control: missing + nature with no capture is written", s.put(rows)["written"])


def test_put_refuses_when_register_changed_since_begin():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        caps = s.ready()
        s.set_register({"R-1": "The stand shows R-1.", "R-2": "The stand shows R-2.", "R-3": "The stand shows R-3."})
        done = s.put(s.rows(caps))
        check_in("put_refuses_when_register_changed_since_begin: an id added after begin is refused up front", "changed since this walk was opened",
                 problems_text(done))
        check_eq("put_refuses_when_register_changed_since_begin: one problem, the door is a new attempt", (len(done["problems"]), "first_look.py begin" in problems_text(done)), (1, True))
        check("put_refuses_when_register_changed_since_begin: nothing written", not FL._record_path(s.task).exists())
        s.begin()
        check("put_refuses_when_register_changed_since_begin: after the driver reopens, the whole register is walked", not s.put(s.rows(caps))["written"]
              and "R-3" in problems_text(s.put(s.rows(caps))))
        caps = s.walk(items=("R-1", "R-2", "R-3"))
        check("put_refuses_when_register_changed_since_begin: with its capture the new attempt writes", s.put(s.rows(caps))["written"])
        s2 = Story(tmp + "/b")
        caps2 = s2.ready()
        s2.set_heads((("product", HEAD_B),))
        check_in("put_refuses_when_register_changed_since_begin: a head moved is refused the same way", "changed since this walk was opened",
                 problems_text(s2.put(s2.rows(caps2))))


def test_api_route_row_shape():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp, ids=("R-1",))
        caps = s.walk(items=("R-1",))
        s.begin()

        def with_api(route):
            row = s.rows(caps)[0]
            row["path"] = {"url": "/cart", "steps": ["open the cart"], "api": route if isinstance(route, list) else [route]}
            return s.put([row])
        good = {"method": "GET", "path": "/v1/cart", "auth": "none", "seen": "yes", "sample": {"request": "GET /v1/cart", "status": 200, "response": "{}"}}
        for auth in ("none", "token", "account:user"):
            check(f"api_route_row_shape: auth {auth} is accepted", with_api({**good, "auth": auth})["written"])
        for label, route, needle in (("auth outside the list", {**good, "auth": "basic"}, ".auth is one of"),
                                     ("an empty account", {**good, "auth": "account:"}, ".auth is one of"),
                                     ("no method", {k: v for k, v in good.items() if k != "method"}, ".method is the text"),
                                     ("seen outside yes/no", {**good, "seen": "maybe"}, ".seen is one of"),
                                     ("a sample that expects", {**good, "sample": {"expected": "200"}}, "a sample is an observation"),
                                     ("a sample that is no mapping", {**good, "sample": "200"}, ".sample is a mapping"),
                                     ("an unknown key", {**good, "retries": 3}, "unknown key `retries`")):
            done = with_api(route)
            check_in(f"api_route_row_shape: {label} is refused", needle, problems_text(done))
        check("api_route_row_shape: a route with no sample is accepted (known and not seen)", with_api({k: v for k, v in good.items() if k != "sample"} | {"seen": "no"})["written"])
        row = s.rows(caps)[0]
        row["path"] = {"api": {"method": "GET"}}
        check_in("api_route_row_shape: api that is no list is refused", ".api is a list", problems_text(s.put([row])))
        row["path"] = {"locators": [{"what": "Pay", "selector": "#pay", "seen": "sometimes"}]}
        check_in("api_route_row_shape: a locator's seen is yes or no", ".seen is one of", problems_text(s.put([row])))


# --- read ------------------------------------------------------------------------------------------------------------

def _written_story(tmp, **kw):
    s = Story(tmp, **kw)
    caps = s.ready()
    done = s.put(s.rows(caps))
    check("fixture: a whole record is written", done["written"], problems_text(done))
    return s, caps


def test_read_is_stale_on_other_head():
    with tempfile.TemporaryDirectory() as tmp:
        s, _ = _written_story(tmp)
        check_eq("read_is_stale_on_other_head: the same head is fresh", FL.read(s.task)["stale"], False)
        s.set_heads((("product", HEAD_B),))
        check_eq("read_is_stale_on_other_head: another sha is stale", FL.read(s.task)["stale"], True)
        s.set_heads((("product", "unmeasured: no source_sha for repo product"),))
        check_eq("read_is_stale_on_other_head: `unmeasured` is a value, another one", FL.read(s.task)["stale"], True)
        s.set_heads((("product", HEAD_A),))
        check_eq("read_is_stale_on_other_head: back on the head, fresh", FL.read(s.task)["stale"], False)
        s.set_heads((("product", HEAD_A), ("api", HEAD_B)))
        check_eq("read_is_stale_on_other_head: another repository joined, stale", FL.read(s.task)["stale"], True)


def test_read_returns_source_head_map():
    with tempfile.TemporaryDirectory() as tmp:
        s, _ = _written_story(tmp, heads=(("product", HEAD_A), ("api", HEAD_B)))
        got = FL.read(s.task)
        check_eq("read_returns_source_head_map: the map of the record, one value per implementation entry", got["source_head"],
                 {"product": HEAD_A, "api": HEAD_B})
        check_eq("read_returns_source_head_map: the walk, the stand build and the rows are read", (got["walk"], got["stand_build"], len(got["rows"])),
                 (WALK, "not_established", 2))
        s2, _ = _written_story(tempfile.mkdtemp(dir=tmp), heads=(("product", "nonsense"),))
        check("read_returns_source_head_map: an unmeasured head is a value of the map", FL.read(s2.task)["source_head"]["product"].startswith("unmeasured:"))
        s3, _ = _written_story(tempfile.mkdtemp(dir=tmp), heads=())
        check_eq("read_returns_source_head_map: no implementation entry is an empty map, not stale", (FL.read(s3.task)["source_head"], FL.read(s3.task)["stale"]),
                 ({}, False))
        absent = Story(tempfile.mkdtemp(dir=tmp))
        got = FL.read(absent.task)
        check("read_returns_source_head_map: no record has a problem and no rows", bool(got["problem"]) and got["rows"] == [], str(got))


def test_stale_on_register_change():
    with tempfile.TemporaryDirectory() as tmp:
        s, _ = _written_story(tmp)
        s.set_register({"R-2": "The stand shows R-2.", "R-1": "The stand shows R-1."})
        check_eq("stale_on_register_change: the same register in another order is fresh", FL.read(s.task)["stale"], False)
        s.set_register({"R-1": "The stand shows R-1.", "R-2": "A different statement."})
        check_eq("stale_on_register_change: a changed statement is stale", FL.read(s.task)["stale"], True)
        s.set_register({"R-1": "The stand shows R-1.", "R-2": "The stand shows R-2.", "R-3": "Added after the walk."})
        check_eq("stale_on_register_change: a requirement added after the walk is stale", FL.read(s.task)["stale"], True)
        s.set_register({"R-1": "The stand shows R-1.", "R-2": "The stand shows R-2."})
        check_eq("stale_on_register_change: back to the walked register, fresh", FL.read(s.task)["stale"], False)
        (s.task / "work" / "requirements-register.md").unlink()
        got = FL.read(s.task)
        check("stale_on_register_change: a register that cannot be read leaves the record never current", got["stale"] and got["problem"], str(got["problem"]))


def test_state_classifies_the_record_once():
    """FL-4 fix round F6 (AR-15): `state` is the one classification the card and the briefs word."""
    with tempfile.TemporaryDirectory() as tmp:
        absent = Story(tempfile.mkdtemp(dir=tmp))
        got = FL.state(absent.task)
        check_eq("state: no record is `absent` (and read says so, no re-stat by a consumer)", (got["kind"], got["got"]["absent"]), ("absent", True))
        s, _ = _written_story(tempfile.mkdtemp(dir=tmp))
        check_eq("state: a current record is `ok`, absent False", (FL.state(s.task)["kind"], FL.read(s.task)["absent"]), ("ok", False))
        s.set_heads((("product", HEAD_B),))
        check_eq("state: other code is `stale`", FL.state(s.task)["kind"], "stale")
        s.set_heads((("product", HEAD_A),))
        (s.task / "work" / "first-look.yaml").write_text("garbage: [\n", encoding="utf-8")
        got = FL.state(s.task)
        check("state: a record that cannot be read is `unreadable`, never `absent`", got["kind"] == "unreadable" and not got["got"]["absent"], str(got["kind"]))
        n = Story(tempfile.mkdtemp(dir=tmp))
        FL.put(n.task, None, "no_stand")
        check_eq("state: a null record is `null`", FL.state(n.task)["kind"], "null")
        original = FL.read
        try:
            FL.read = lambda task_root: (_ for _ in ()).throw(ValueError("boom"))
            check_eq("state: a raising reader is `error`, not a raise", (FL.state(n.task)["kind"], FL.state(n.task)["error"]), ("error", "ValueError"))
        finally:
            FL.read = original


def test_brief_words_are_data_keys():
    """FL-4 fix round F1 (AR-1): the red statuses, the S7 filter and the confirmed build word are keys of the data file."""
    data = FL.data()
    check_eq("keys: red_statuses", data["red_statuses"], ["contradicts", "missing", "unreachable"])
    check("keys: red statuses are declared statuses", set(data["red_statuses"]) <= set(data["statuses"]))
    check_eq("keys: bug_candidate_blocked_by", data["bug_candidate_blocked_by"], {"unreachable": ["product"]})
    check("keys: the S7 filter names a declared status and declared blocked_by words", set(data["bug_candidate_blocked_by"]) <= set(data["statuses"])
          and all(set(v) <= set(data["blocked_by"]) for v in data["bug_candidate_blocked_by"].values()))
    check_eq("keys: stand_build_confirmed is the word `put` writes (the confirmed test below writes it)", data["stand_build_confirmed"], "confirmed")
    check_eq("readers: red_statuses / bug_candidate_blocked_by / stand_build_confirmed read the file",
             (FL.red_statuses(), FL.bug_candidate_blocked_by(), FL.stand_build_confirmed()),
             (data["red_statuses"], data["bug_candidate_blocked_by"], "confirmed"))
    original = FL.DATA_PATH
    try:
        FL.DATA_PATH = Path(tempfile.gettempdir()) / "no-such-first-look-statuses.json"
        check_eq("readers: an unreadable file is no words, never a guess",
                 (FL.red_statuses(), FL.bug_candidate_blocked_by(), FL.stand_build_confirmed()), ([], {}, ""))
    finally:
        FL.DATA_PATH = original


# --- share -----------------------------------------------------------------------------------------------------------

def _share_story(tmp, statuses, **kw):
    ids = tuple(f"R-{n}" for n in range(1, len(statuses) + 1))
    s = Story(tmp, ids=ids, **kw)
    caps = s.walk(items=ids)
    s.begin()
    rows = []
    for req, (status, blocked) in zip(ids, statuses):
        row = {"req": req, "status": status, "why": f"looked for {req}", "evidence": [caps[req]], "quote": QUOTE}
        if blocked:
            row["blocked_by"] = blocked
        rows.append(row)
    done = s.put(rows)
    check("fixture: the share record is written", done["written"], problems_text(done))
    return s


def test_share_excludes_access_and_nature():
    with tempfile.TemporaryDirectory() as tmp:
        s = _share_story(tmp, [("confirms", ""), ("contradicts", ""), ("missing", "product"), ("unreachable", "access"), ("missing", "nature")])
        got = FL.share(s.task, {})
        check_eq("share_excludes_access_and_nature: 5 rows, 2 of them out of the denominator", (got["reachable"], got["counted"]), (2, 3))
        check_eq("share_excludes_access_and_nature: the share is of the counted rows", got["share"], 66.7)
        check_eq("share_excludes_access_and_nature: 66.7 % is over the floor of 30", got["below"], False)
        check_eq("share_excludes_access_and_nature: a floor of 70 is above it", FL.share(s.task, {"first_look": {"reachable_floor_percent": 70}})["below"], True)
        out = _share_story(tempfile.mkdtemp(dir=tmp), [("unreachable", "product")] * 9 + [("confirms", "")] * 1)
        got = FL.share(out.task, {})
        check_eq("share_excludes_access_and_nature: a product block counts against the share", (got["reachable"], got["counted"], got["below"]), (1, 10, True))


def test_share_zero_counted_never_below():
    with tempfile.TemporaryDirectory() as tmp:
        s = _share_story(tmp, [("unreachable", "access"), ("missing", "nature")])
        got = FL.share(s.task, {"first_look": {"reachable_floor_percent": 100}})
        check_eq("share_zero_counted_never_below: nothing counted, no share, never below", (got["counted"], got["share"], got["below"]), (0, None, False))


def test_share_unreadable_never_below():
    with tempfile.TemporaryDirectory() as tmp:
        s = _share_story(tmp, [("missing", "product")] * 4)
        check_eq("share_unreadable_never_below: before the damage it is below", FL.share(s.task, {})["below"], True)
        for label, text in (("garbage", "::: not a record"), ("a list", "- one\n- two\n"), ("rows that are no list", "rows: 3\nsource_head:\n  product: x\n")):
            FL._record_path(s.task).write_text(text, encoding="utf-8")
            got = FL.share(s.task, {})
            check(f"share_unreadable_never_below: {label} is never below, with a problem", got["below"] is False and got["problem"], str(got))
        FL._record_path(s.task).unlink()
        got = FL.share(s.task, {})
        check("share_unreadable_never_below: an absent record is never below, with a problem", got["below"] is False and got["problem"], str(got))


def test_share_stale_never_below():
    with tempfile.TemporaryDirectory() as tmp:
        s = _share_story(tmp, [("missing", "product")] * 4)
        s.set_heads((("product", HEAD_B),))
        got = FL.share(s.task, {})
        check("share_stale_never_below: another head is never below, with a problem", got["below"] is False and "other code" in got["problem"], str(got))


def test_share_null_never_below():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        FL.put(s.task, None, "no_reachable_surface")
        got = FL.share(s.task, {"first_look": {"reachable_floor_percent": 100}})
        check("share_null_never_below: a null record is never below, and says it is null", got["below"] is False and "null: no_reachable_surface" in got["problem"], str(got))


def test_floor_default_30():
    for cfg in ({}, None, {"first_look": {}}, {"first_look": {"reachable_floor_percent": 101}}, {"first_look": {"reachable_floor_percent": -1}},
                {"first_look": {"reachable_floor_percent": "40"}}, {"first_look": {"reachable_floor_percent": True}},
                {"first_look": {"reachable_floor_percent": 30.5}}, {"first_look": "x"}):
        check_eq(f"floor_default_30: {cfg!r} reads 30", FL._floor(cfg), 30)
    template = json.loads((harness.PLUGIN_ROOT / "references" / "templates" / "config.json").read_text(encoding="utf-8"))
    check_eq("floor_default_30: the template carries 30", template["first_look"]["reachable_floor_percent"], 30)
    with tempfile.TemporaryDirectory() as tmp:
        s = _share_story(tmp, [("confirms", "")] * 3 + [("missing", "product")] * 7)
        check_eq("floor_default_30: exactly 30 % is not below the default", FL.share(s.task, {})["below"], False)
        s2 = _share_story(tempfile.mkdtemp(dir=tmp), [("confirms", "")] * 2 + [("missing", "product")] * 8)
        check_eq("floor_default_30: 20 % is below it", FL.share(s2.task, {})["below"], True)


def test_floor_from_config():
    for value in (0, 55, 100):
        check_eq(f"floor_from_config: {value} is read", FL._floor({"first_look": {"reachable_floor_percent": value}}), value)
    with tempfile.TemporaryDirectory() as tmp:
        s = _share_story(tmp, [("confirms", "")] * 2 + [("missing", "product")] * 8)
        cfg = lambda n: {"first_look": {"reachable_floor_percent": n}}  # noqa: E731
        check_eq("floor_from_config: 20 % against a floor of 20 is not below", FL.share(s.task, cfg(20))["below"], False)
        check_eq("floor_from_config: 20 % against a floor of 21 is below", FL.share(s.task, cfg(21))["below"], True)
        check_eq("floor_from_config: a floor of 0 is never below", FL.share(s.task, cfg(0))["below"], False)
        check_eq("floor_from_config: the share carries the floor it used", FL.share(s.task, cfg(21))["floor"], 21)
    keys = json.loads((harness.PLUGIN_ROOT / "references" / "config-keys.json").read_text(encoding="utf-8"))["keys"]
    check("floor_from_config: the key is declared (absent means default)", keys.get("first_look", {}).get("absent_means") == "default", str(keys.get("first_look")))


# --- due -------------------------------------------------------------------------------------------------------------

def test_due_false_when_parks_after_s5():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        pipeline = {**PIPELINE, "sides": {"product": {"reality": "absent", "deliverable": True}}}
        check_eq("due_false_when_parks_after_s5: a deliverable absent side", FL.due(s.task, pipeline, {})[:2], (False, "no_code_yet"))
        pipeline = {**PIPELINE, "sides": {"product": {"reality": "absent", "deliverable": False}}}
        check_eq("due_false_when_parks_after_s5: an absent side that is not the deliverable does not park", FL.due(s.task, pipeline, {})[0], True)
        pipeline = {**PIPELINE, "sides": {"product": {"reality": "substituted"}}}
        check_eq("due_false_when_parks_after_s5: a substituted side does not park", FL.due(s.task, pipeline, {})[0], True)


def test_due_false_on_empty_register():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp, ids=())
        got = FL.due(s.task, PIPELINE, {})
        check_eq("due_false_on_empty_register: a register with no row is declared empty", got[:2], (False, "empty_register"))
        (s.task / "work" / "requirements-register.md").write_text("# Requirements register\n\nno table here\n", encoding="utf-8")
        check_eq("due_false_on_empty_register: no table is unreadable, not empty", FL.due(s.task, PIPELINE, {})[:2], (False, "register_unreadable"))
        (s.task / "work" / "requirements-register.md").unlink()
        check_eq("due_false_on_empty_register: no file is unreadable", FL.due(s.task, PIPELINE, {})[:2], (False, "register_unreadable"))


def test_due_false_without_stand():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        for label, pipeline in (("no environment key", {"ticket": "QA-1"}), ("an empty name", {**PIPELINE, "environment": ""}),
                                ("a null name", {**PIPELINE, "environment": None}), ("an unconfirmed name", {**PIPELINE, "environment_pending": True})):
            check_eq(f"due_false_without_stand: {label}", FL.due(s.task, pipeline, {})[:2], (False, "no_stand"))
        check_eq("due_false_without_stand: a named confirmed stand is due", FL.due(s.task, PIPELINE, {})[0], True)


def test_due_false_when_attempt_on_same_head():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        check_eq("due_false_when_attempt_on_same_head: no attempt, due", FL.due(s.task, PIPELINE, {})[0], True)
        s.begin()
        for outcome in ("walking", "written", "nothing_written"):
            if outcome != "walking":
                FL.end(s.task, outcome)
            got = FL.due(s.task, PIPELINE, {})
            check_eq(f"due_false_when_attempt_on_same_head: a {outcome} attempt is not repeated, with no reason", got[:2], (False, ""))
        FL._attempt_path(s.task).write_text("{broken", encoding="utf-8")
        check_eq("due_false_when_attempt_on_same_head: an attempt that cannot be read is no attempt", FL.due(s.task, PIPELINE, {})[0], True)


def test_due_true_on_new_head_after_attempt():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        s.begin()
        FL.end(s.task, "written")
        s.set_heads((("product", HEAD_B),))
        check_eq("due_true_on_new_head_after_attempt: another head, due again", FL.due(s.task, PIPELINE, {})[0], True)
        s.set_heads((("product", HEAD_A),))
        check_eq("due_true_on_new_head_after_attempt: the walked head, not due", FL.due(s.task, PIPELINE, {})[0], False)
        s.set_register({"R-1": "The stand shows R-1.", "R-2": "Changed."})
        check_eq("due_true_on_new_head_after_attempt: another register, due again", FL.due(s.task, PIPELINE, {})[0], True)
        s.begin()
        check_eq("due_true_on_new_head_after_attempt: a new attempt starts its failures at 0", FL.read_attempt(s.task)["open_failures"], 0)


def test_due_retries_open_failed_once():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        s.begin()
        FL.end(s.task, "open_failed")
        got = FL.due(s.task, PIPELINE, {})
        check_eq("due_retries_open_failed_once: one failure to open, tried again", (got[0], got[1]), (True, ""))
        s.begin()
        check_eq("due_retries_open_failed_once: the same keys keep the count", FL.read_attempt(s.task)["open_failures"], 1)
        FL.end(s.task, "open_failed")
        got = FL.due(s.task, PIPELINE, {})
        check_eq("due_retries_open_failed_once: the second failure stops it and names the cause", got[:2], (False, "walk_not_opened"))
        check_in("due_retries_open_failed_once: the line says how often", "2 times", got[2])
        s.set_heads((("product", HEAD_B),))
        check_eq("due_retries_open_failed_once: new code is a new chance", FL.due(s.task, PIPELINE, {})[0], True)
        check_eq("due_retries_open_failed_once: the retry limit is data", FL.data()["open_retry_max"], 1)


def test_null_record_not_fresh_when_stand_appears():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp, pipeline={"ticket": "QA-1"})
        got = FL.due(s.task, {"ticket": "QA-1"}, {})
        check_eq("null_record_not_fresh_when_stand_appears: no stand now", got[:2], (False, "no_stand"))
        check("null_record_not_fresh_when_stand_appears: the null record is written", FL.put(s.task, None, got[1])["written"])
        check_eq("null_record_not_fresh_when_stand_appears: still not due while there is no stand", FL.due(s.task, {"ticket": "QA-1"}, {})[:2], (False, "no_stand"))
        check_eq("null_record_not_fresh_when_stand_appears: a stand appears, the null record is no attempt, due", FL.due(s.task, PIPELINE, {})[0], True)
        check_eq("null_record_not_fresh_when_stand_appears: and it is not stale: the keys did not move", FL.read(s.task)["stale"], False)


def test_due_writes_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        s.begin()
        FL.put(s.task, None, "no_stand")
        before = s.snapshot()
        for pipeline in (PIPELINE, {"ticket": "QA-1"}, {**PIPELINE, "sides": {"product": {"reality": "absent"}}}):
            FL.due(s.task, pipeline, {})
            FL.continued(s.task, pipeline)
            FL.current_keys(s.task)
            FL.read(s.task)
            FL.share(s.task, {})
        check("due_writes_nothing: not a byte of the story changed", s.snapshot() == before, str(set(s.snapshot()) ^ set(before)))
        (s.task / "work" / "requirements-register.md").unlink()
        before = s.snapshot()
        FL.due(s.task, PIPELINE, {})
        check("due_writes_nothing: nor with a register that cannot be read", s.snapshot() == before)


# --- the heads, the keys, the build ----------------------------------------------------------------------------------

def test_stand_build_confirmed_only_on_deployed_same_revision():
    with tempfile.TemporaryDirectory() as tmp:
        def build(story):
            return FL.read(story.task)["stand_build"]

        def fresh(sub, heads=(("product", HEAD_A),)):
            s = Story(tempfile.mkdtemp(dir=tmp), heads=heads)
            return s, s.ready()
        s, caps = fresh("none")
        s.put(s.rows(caps))
        check_eq("stand_build_confirmed_only_on_deployed_same_revision: no word of the person", build(s), "not_established")
        s, caps = fresh("ok")
        s.confirm("deployed", HEAD_A)
        s.put(s.rows(caps))
        check_eq("stand_build_confirmed_only_on_deployed_same_revision: a `deployed` word at the head", build(s), "confirmed")
        s, caps = fresh("other")
        s.confirm("deployed", HEAD_B)
        s.put(s.rows(caps))
        check_eq("stand_build_confirmed_only_on_deployed_same_revision: a `deployed` word at another revision", build(s), "not_established")
        s, caps = fresh("test_deployed")
        s.confirm("test_deployed", HEAD_A)
        s.put(s.rows(caps))
        check_eq("stand_build_confirmed_only_on_deployed_same_revision: `test_deployed` is not `deployed`", build(s), "not_established")
        s, caps = fresh("two", heads=(("product", HEAD_A), ("api", HEAD_B)))
        s.confirm("deployed", HEAD_A)
        s.put(s.rows(caps))
        check_eq("stand_build_confirmed_only_on_deployed_same_revision: two implementation entries are no one head", build(s), "not_established")
        s, caps = fresh("unmeasured", heads=(("product", "nonsense"),))
        s.confirm("deployed", HEAD_A)
        s.put(s.rows(caps))
        check_eq("stand_build_confirmed_only_on_deployed_same_revision: an unmeasured head confirms nothing", build(s), "not_established")


def test_current_keys_canonical_and_stable():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp, heads=(("product", HEAD_A), ("api", HEAD_B)))
        text, reg_hash = FL.current_keys(s.task)
        check_eq("current_keys_canonical_and_stable: the heads text is the canonical JSON of the map", text,
                 json.dumps({"api": HEAD_B, "product": HEAD_A}, sort_keys=True, separators=(",", ":")))
        check("current_keys_canonical_and_stable: the hash is a sha256", len(reg_hash) == 64 and set(reg_hash) <= set("0123456789abcdef"), reg_hash)
        check_eq("current_keys_canonical_and_stable: stable across calls", FL.current_keys(s.task), (text, reg_hash))
        s.set_heads((("api", HEAD_B), ("product", HEAD_A)))
        check_eq("current_keys_canonical_and_stable: the order of entries does not matter", FL.current_keys(s.task)[0], text)
        s.set_register({"R-2": "The stand shows R-2.", "R-1": "The stand shows R-1."})
        check_eq("current_keys_canonical_and_stable: nor the order of the rows", FL.current_keys(s.task)[1], reg_hash)
        s.set_register({"R-1": "The  stand shows\tR-1.", "R-2": "The stand shows R-2."})
        check_eq("current_keys_canonical_and_stable: nor the spacing of a statement", FL.current_keys(s.task)[1], reg_hash)
        s.set_register({"R-1": "The stand shows R-1.", "R-2": "Other."})
        check("current_keys_canonical_and_stable: a changed statement is another hash", FL.current_keys(s.task)[1] != reg_hash)
        s.set_heads((("product", "nonsense"),))
        check_in("current_keys_canonical_and_stable: an unmeasured head is part of the text", "unmeasured: ", FL.current_keys(s.task)[0])
        s.set_heads(())
        check_eq("current_keys_canonical_and_stable: no entry is the empty map", FL.current_keys(s.task)[0], "{}")
        (s.task / "work" / "requirements-register.md").unlink()
        check_eq("current_keys_canonical_and_stable: a register that cannot be read gives an empty hash", FL.current_keys(s.task)[1], "")
        bad = Story(tempfile.mkdtemp(dir=tmp))
        (bad.task / "work" / "context-manifest.json").write_text("{not json", encoding="utf-8")
        check_eq("current_keys_canonical_and_stable: a manifest that cannot be read is the empty map", FL.current_keys(bad.task)[0], "{}")


def test_continued_only_on_same_head_and_register():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        text, reg_hash = FL.current_keys(s.task)
        word = {"source_head": text, "register_hash": reg_hash, "words": "carry on"}
        check_eq("continued_only_on_same_head_and_register: the keys of now", FL.continued(s.task, {"first_look_continue": word}), True)
        check_eq("continued_only_on_same_head_and_register: no word", FL.continued(s.task, {}), False)
        check_eq("continued_only_on_same_head_and_register: a word that is no record", FL.continued(s.task, {"first_look_continue": "yes"}), False)
        s.set_heads((("product", HEAD_B),))
        check_eq("continued_only_on_same_head_and_register: another head, asked again", FL.continued(s.task, {"first_look_continue": word}), False)
        s.set_heads((("product", HEAD_A),))
        s.set_register({"R-1": "The stand shows R-1.", "R-2": "Changed."})
        check_eq("continued_only_on_same_head_and_register: another register, asked again", FL.continued(s.task, {"first_look_continue": word}), False)
        check_eq("continued_only_on_same_head_and_register: either key missing is no match",
                 (FL.continued(s.task, {"first_look_continue": {"source_head": text}}), FL.continued(s.task, {"first_look_continue": {"register_hash": reg_hash}})),
                 (False, False))
        (s.task / "work" / "requirements-register.md").unlink()
        check_eq("continued_only_on_same_head_and_register: an unreadable register never matches (even a word carrying an empty hash)",
                 FL.continued(s.task, {"first_look_continue": {"source_head": text, "register_hash": ""}}), False)


def test_sides_met_only_on_non_real_story():
    with tempfile.TemporaryDirectory() as tmp:
        def met(pipeline):
            s = Story(tempfile.mkdtemp(dir=tmp), pipeline=pipeline)
            caps = s.ready()
            done = s.put(s.rows(caps))
            check("fixture: written", done["written"], problems_text(done))
            record_text = FL._record_path(s.task).read_text(encoding="utf-8")
            return record_text, "sides_met" in record_text
        _, has = met(PIPELINE)
        check_eq("sides_met_only_on_non_real_story: a story with no `sides` record (the default real side) carries none", has, False)
        _, has = met({**PIPELINE, "sides": {"product": {"reality": "real"}}})
        check_eq("sides_met_only_on_non_real_story: every side real, none", has, False)
        text, has = met({**PIPELINE, "sides": {"product": {"reality": "real"}, "mail": {"reality": "substituted"}}})
        check("sides_met_only_on_non_real_story: a substituted side is named with its reality", has and "mail" in text and "substituted" in text and "product: \"real\"" not in text, text[:400])
        _, has = met({**PIPELINE, "sides": {"product": {"deliverable": True}}})
        check_eq("sides_met_only_on_non_real_story: a reality that cannot be read is not real", has, True)
        s = Story(tempfile.mkdtemp(dir=tmp), pipeline={**PIPELINE, "sides": {"mail": {"reality": "substituted"}}})
        FL.put(s.task, None, "no_stand")
        check("sides_met_only_on_non_real_story: a null record carries it too", "sides_met" in FL._record_path(s.task).read_text(encoding="utf-8"))


# --- the data, the attempt, the command line --------------------------------------------------------------------------

def test_statuses_file_is_the_one_home_of_the_words():
    data = FL.data()
    check_eq("statuses: the four statuses", data["statuses"], ["confirms", "contradicts", "missing", "unreachable"])
    check_eq("statuses: blocked_by", data["blocked_by"], ["product", "access", "nature"])
    check_eq("statuses: reachable", data["reachable"], ["confirms", "contradicts"])
    check_eq("statuses: the seven null reasons", data["null_reasons"], ["no_code_yet", "empty_register", "register_unreadable", "no_stand",
                                                                       "no_reachable_surface", "profile_not_chosen", "walk_not_opened"])
    check_eq("statuses: open_retry_max", data["open_retry_max"], 1)
    check("statuses: reachable words are statuses", set(data["reachable"]) <= set(data["statuses"]))
    source = (harness.SCRIPTS / "first_look.py").read_text(encoding="utf-8")
    for word in data["statuses"] + data["blocked_by"]:
        check(f"statuses: the word {word} is no literal in the code (AR-1)", f'"{word}"' not in source and f"'{word}'" not in source)
    for key in ("blocked_by_required_for", "share_excludes", "no_capture_needed", "attempt_settled"):
        check(f"statuses: {key} is data and its words are declared words", bool(data[key]) and set(data[key]) <= set(
            data["statuses"] + data["blocked_by"] + data["attempt_outcomes"]), str(data.get(key)))


def test_begin_end_attempt():
    with tempfile.TemporaryDirectory() as tmp:
        s = Story(tmp)
        row = s.begin("S3-x")
        check_eq("begin: walk is the dispatch, the outcome walking", (row["walk"], row["outcome"], row["env"], row["open_failures"]), ("S3-x", "walking", STAND, 0))
        check_eq("begin: the keys are current_keys'", (json.dumps(row["source_head"], sort_keys=True, separators=(",", ":")), row["register_hash"]),
                 FL.current_keys(s.task))
        check_eq("begin: the file reads back", FL.read_attempt(s.task), row)
        check("end: an outcome outside the list is refused, the attempt as it was", not FL.end(s.task, "done")["ok"] and FL.read_attempt(s.task) == row)
        check("end: `walking` is not an end", not FL.end(s.task, "walking")["ok"])
        check_eq("end: written", FL.end(s.task, "written")["attempt"]["outcome"], "written")
        with tempfile.TemporaryDirectory() as other:
            check("end: no attempt is refused with the door", "begin" in FL.end(Story(other).task, "written")["problem"])


def test_command_line():
    import contextlib
    import io
    root = harness.temp_project()
    try:
        task = root / "qa-factory" / "artifacts" / "QA-1"
        (task / "work").mkdir(parents=True)
        s = Story.__new__(Story)
        s.root, s.task = root, task
        s.set_register({"R-1": "The stand shows R-1."})
        s.set_heads((("product", HEAD_A),))
        s.set_pipeline(PIPELINE)
        caps = s.walk(items=("R-1",))

        def run(*argv):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = FL.main(list(argv))
            return code, out.getvalue(), err.getvalue()
        base = ["--task-root", str(task)]
        code, out, err = run("put", *base, "--null", "bogus")
        check("cli: an unknown null reason is a refusal with a code of 2 and no traceback", code == 2 and "Traceback" not in err and "no_stand" in err, err[-300:])
        code, out, err = run("begin", *base, "--dispatch", WALK, "--env", STAND)
        check_eq("cli: begin", code, 0)
        rows = s.file({"rows": s.rows(caps)})
        code, out, err = run("put", *base, "--file", str(rows))
        check("cli: put writes and prints the result", code == 0 and json.loads(out)["written"] is True, out + err)
        code, out, err = run("put", *base, "--file", str(rows), "--null", "no_stand")
        check("cli: --file and --null together is refused", code == 2 and "exactly one" in err, err[-300:])
        code, out, err = run("show", *base, "--json")
        shown = json.loads(out)
        check_eq("cli: show --json carries the record, the attempt and current_keys", (shown["record"]["walk"], shown["attempt"]["outcome"],
                 sorted(shown["current_keys"])), (WALK, "written", ["register_hash", "source_head"]))
        check_eq("cli: current_keys is the one producer's pair", (shown["current_keys"]["source_head"], shown["current_keys"]["register_hash"]),
                 FL.current_keys(task))
        code, out, err = run("show", *base)
        check("cli: show prints a line per row", code == 0 and "R-1 | confirms" in out, out)
        code, out, err = run("end", *base, "--outcome", "nothing_written")
        check("cli: end sets the outcome", code == 0 and json.loads(out)["outcome"] == "nothing_written", out + err)
        code, out, err = run("end", *base, "--outcome", "bogus")
        check("cli: a bad outcome is a refusal", code == 2 and "Traceback" not in err, err[-300:])
    finally:
        harness.cleanup(root)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    finish("test_first_look")


if __name__ == "__main__":
    main()
