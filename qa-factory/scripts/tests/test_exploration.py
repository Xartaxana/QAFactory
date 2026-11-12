#!/usr/bin/env python3
"""XT1-1: the core of an exploration - slug, root, state E0-E3, probes, the ONE frame packet, the lock, and the CLI over them.

Tests never touch the network: `readiness.check_jira_direct` and `project_inventory.build_inventory` are stubbed on their module
objects. Inputs with non-ASCII text are written as `\\u` escapes (FR-30: the package carries no Cyrillic).
"""
import contextlib
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, cleanup, finish, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import exploration as X  # noqa: E402
import explore_step  # noqa: E402
import human_text  # noqa: E402
import install_paths  # noqa: E402
import no_move as NM  # noqa: E402
import project_inventory  # noqa: E402
import readiness  # noqa: E402

SESSION = "sess-a"
OTHER = "sess-b"
GOOD = {"status": "ok", "owner": "factory", "note": "fine"}
MISSING = {"status": "missing", "owner": "user", "note": "the secret is gone",
           "remedy": {"kind": "human_step", "need": "the environment variable JIRA_TOKEN, which is not set in this session",
                      "steps": ["set JIRA_TOKEN in the local environment, then reopen the session"]}}
READY = {"repo_id": "MyBooks", "names": ["MyBooks"], "status": "ready", "reason": ""}
GONE = {"repo_id": "OldApp", "names": ["OldApp"], "status": "missing", "reason": "configured checkout is absent"}


def H(text: str) -> str:
    return "feature-" + hashlib.sha256(" ".join(text.split()).casefold().encode()).hexdigest()[:8]


@contextlib.contextmanager
def probes(jira=GOOD, repos=(READY,), calls=None):
    """The tracker check and the repository inventory replaced on their modules; `calls` counts the probes."""
    saved = (readiness.check_jira_direct, project_inventory.build_inventory)

    def tracker(cfg, root):
        if calls is not None:
            calls.append("tracker")
        if callable(jira):
            return jira()
        return jira
    readiness.check_jira_direct = tracker
    project_inventory.build_inventory = lambda cfg, root, selected=None: {"repositories": [dict(r) for r in repos]}
    try:
        yield
    finally:
        readiness.check_jira_direct, project_inventory.build_inventory = saved


def refused(call, *needles) -> bool:
    try:
        call()
    except X.ExplorationRefused as exc:
        return all(n in str(exc) for n in needles)
    return False


def tree(project: Path) -> set:
    return {p.relative_to(project).as_posix() for p in project.rglob("*")}


def words(project: Path, text: str, name="w.txt", raw: bytes | None = None) -> str:
    path = project / name
    path.write_bytes(raw if raw is not None else text.encode("utf-8"))
    return str(path)


def framed(project: Path, phrase="Add to Cart", **more) -> dict:
    return X.frame(project, phrase, more.get("stories", []), more.get("repos", []), more.get("jql"), SESSION)


def table_and_names() -> None:
    t = X.table()
    check("table_shape: the top-level keys are all there", all(k in t for k in ("label", "env_prefix", "question_key", "limits", "slug", "roles", "steps", "artifacts")))
    check("table_shape: every limit is a whole number above zero", all(isinstance(v, int) and v > 0 for v in t["limits"].values()))
    check_eq("table_shape: the limits the code reads", sorted(set(t["limits"]) & {"phrase_chars", "slug_chars", "slug_min_chars", "slug_suffix_max", "path_max", "path_reserve"}),
             ["path_max", "path_reserve", "phrase_chars", "slug_chars", "slug_min_chars", "slug_suffix_max"])
    check_eq("table_shape: the reserved device names are data", sorted(set(t["slug"]["reserved"]) & {"con", "nul", "com1", "com9", "lpt1", "lpt9"}),
             ["com1", "com9", "con", "lpt1", "lpt9", "nul"])
    check("table_shape: every step has statuses, inputs and ordered actions", all(
        row["statuses"] and row["actions"] and row["inputs"] and row["statuses"][0] == "pending" for row in t["steps"].values()))
    check("table_shape: every artifact row names a writer, readers and its empty outcome (AR-14, AR-23)", all(
        row.get("writer") and row.get("readers") and row.get("null_outcome") for row in t["artifacts"].values()), str(t["artifacts"].keys()))
    check_eq("table_shape: the question key is the one of the frame", (t["question_key"], t["label"], t["env_prefix"]), ("explore.frame", "Exploration:", "explore:"))
    check_eq("table_shape: every role works on steps the table has", sorted({s for steps in t["roles"].values() for s in steps} - set(t["steps"])), [])
    # basenames_disjoint: the exploration's file names never collide with a key of artifact-writers.json (m-3)
    writers = json.loads((harness.PLUGIN_ROOT / "references" / "artifact-writers.json").read_text(encoding="utf-8-sig"))["artifacts"]
    theirs = {k.rstrip("/").rsplit("/", 1)[-1] for k in writers}
    ours = {"explore.json", X.lock_path("x", Path("p")).name, "frame-packet.md", "requirement-hits.json", "feature-hits.json", "requirements.yaml",
            "feature-map.yaml", "coverage-matrix.yaml", "coverage-matrix.md"} | {k.rstrip("/").rsplit("/", 1)[-1] for k in t["artifacts"]}
    check_eq("basenames_disjoint: no exploration file name is a key of artifact-writers.json", sorted(ours & theirs), [])
    check("basenames_disjoint: positive control - the same scan finds a name that IS shared", bool({"pipeline.json"} & theirs))


def table_refusals() -> None:
    project = temp_project()
    try:
        before = tree(project)
        real = X.hooklib.load_ref_json
        for label, make in (("an empty table", lambda t: {}), ("no limits", lambda t: {k: v for k, v in t.items() if k != "limits"}),
                            ("no slug rules", lambda t: {k: v for k, v in t.items() if k != "slug"}),
                            ("a limit of zero", lambda t: {**t, "limits": {**t["limits"], "slug_chars": 0}})):
            good = real("exploration.json")
            X.hooklib.load_ref_json = lambda name, make=make, good=good: make(good) if name == "exploration.json" else real(name)
            try:
                with probes():
                    ok = refused(lambda: framed(project), "references/exploration.json is unreadable", "nothing was written")
            finally:
                X.hooklib.load_ref_json = real
            check(f"table_missing_refuses / table_key_missing_refuses: {label} is a refusal", ok)
        check_eq("table_missing_refuses: the project tree is unchanged", tree(project), before)
        good = real("exploration.json")
        X.hooklib.load_ref_json = lambda name: {**good, "limits": {k: v for k, v in good["limits"].items() if k != "slug_chars"}} if name == "exploration.json" else real(name)
        try:
            check("table_key_missing_refuses: an absent limit names `limits.<name>`", refused(lambda: X.limit("slug_chars"), "limits.slug_chars"))
        finally:
            X.hooklib.load_ref_json = real
    finally:
        cleanup(project)


def slugs() -> None:
    project = temp_project()
    try:
        battery = [("Add to Cart", "add-to-cart"), ("  add\nto   CART ", "add-to-cart"), ("Add to Cart!", "add-to-cart"), ("Add_to_Cart", "add-to-cart"),
                   ("../../etc", "etc"), ("Caf\u00e9 cr\u00e8me", "cafe-creme"), ("\"'", H("\"'")),
                   ("\u041a\u043e\u0440\u0437\u0438\u043d\u0430", H("\u041a\u043e\u0440\u0437\u0438\u043d\u0430")),
                   ("\u041a\u041e\u0420\u0417\u0418\u041d\u0410", H("\u041a\u043e\u0440\u0437\u0438\u043d\u0430")),
                   ("\u041a\u043e\u0440\u0437\u0438\u043d\u0430 2", H("\u041a\u043e\u0440\u0437\u0438\u043d\u0430 2")),
                   ("ab1", "ab1"), ("ab", H("ab")), ("abcd \u0430\u0431\u0432\u0433", "abcd"), ("abc \u0430\u0431\u0432\u0433", H("abc \u0430\u0431\u0432\u0433")),
                   ("CON", H("CON")), ("Nul", H("Nul")), ("com1", H("com1")), ("lpt9", H("lpt9")), ("com10", "com10"),
                   ("\U0001F6D2 cart", "cart"), ("a" * 48, "a" * 48), ("a" * 49, "a" * 48), ("a" * 47 + " b", "a" * 47), ("x\nExploration: other", "x-exploration-other")]
        for phrase, expected in battery:
            got, state = X.place(phrase, project)
            check_eq(f"slug_battery: {phrase[:20]!r}", got, expected)
            check(f"slug_battery: {got!r} is one safe path component", X.is_slug(got) and X.hooklib.is_one_component(got) and len(got) <= 48)
        check_eq("slug_battery: spacing, case and punctuation are one key",
                 len({X.slug_key(p) for p in ("Add to Cart", "  add\nto   CART ", "Add to Cart!", "Add_to_Cart")}), 1)
        check_eq("slug_battery: CON and the upper-case phrase are the hash form of the casefolded phrase (same slug)",
                 X.slug_key("CON"), X.slug_key("con"))
        for bad in ("../x", "CON", "con", "Add-To-Cart", "a" * 49, "", "a b", "a--b", "-a"):
            check(f"slug_battery: `{bad[:12]}` is no exploration name", not X.is_slug(bad))
        # slug_collision: the frame sequence of the spec
        with probes():
            seen = [framed(project, "a" * n)["slug"] for n in (50, 49, 51, 50)]
        check_eq("slug_collision: 50, 49, 51 and 50 again", seen, ["a" * 48, "a" * 46 + "-2", "a" * 46 + "-3", "a" * 48])
        check("slug_collision: a suffixed name is never over the limit", all(len(s) <= 48 for s in seen))
        # suffix_limit: 98 other-key folders -> -99 (AT); 99 -> refusal (BEYOND)
        full = temp_project()
        try:
            names = ["add-to-cart"] + [f"add-to-cart-{n}" for n in range(2, 99)]
            for n, name in enumerate(names):
                X._save(name, full, X._new_state(name, f"other feature {n}", [], [], "", []))
            check_eq("suffix_limit: 98 other-key folders hold the name and -2 ... -98", len(names), 98)
            check_eq("suffix_limit: the 99th (AT the limit) is free", X.place("Add to Cart", full), ("add-to-cart-99", "new"))
            X._save("add-to-cart-99", full, X._new_state("add-to-cart-99", "other feature 98", [], [], "", []))
            check("suffix_limit: 99 taken (BEYOND) is a refusal", refused(lambda: X.place("Add to Cart", full), "99 explorations already start"))
        finally:
            cleanup(full)
    finally:
        cleanup(project)


def budget_root_load() -> None:
    limits = X.table()["limits"]
    at = "x" * (limits["path_max"] - limits["path_reserve"])
    check_eq("path_budget_boundary: total at the budget passes", X.path_budget_problem(at, limits, True), "")
    check("path_budget_boundary: one over is refused, naming the folder length and the door",
          "is 141 characters long" in X.path_budget_problem(at + "x", limits, True) and "shorter folder" in X.path_budget_problem(at + "x", limits, True))
    check_eq("path_budget_boundary: not Windows -> never", X.path_budget_problem("x" * 5000, limits, False), "")
    project = temp_project()
    try:
        check_eq("root_and_exists: the root is under qa-factory/explorations", X.root("add-to-cart", project), project / "qa-factory" / "explorations" / "add-to-cart")
        check("root_and_exists: a non-slug is refused and no disk is touched", refused(lambda: X.root("../x", project), "not an exploration name") and not (project / "qa-factory" / "explorations").exists())
        check("root_and_exists: nothing framed -> exists is False", X.exists("add-to-cart", project) is False)
        check("load_refusals: absent -> the refusal that names frame", refused(lambda: X.load("add-to-cart", project), "no exploration", "explore_step.py frame"))
        folder = X.root("add-to-cart", project)
        folder.mkdir(parents=True)
        for label, content in (("not JSON", "{oops"), ("a list", "[]"), ("another schema", json.dumps({"schema_version": 7})),
                               ("a missing part", json.dumps({"schema_version": 1, "steps": {}}))):
            (folder / "explore.json").write_text(content, encoding="utf-8")
            check(f"load_refusals: {label} names the file and is never rewritten",
                  refused(lambda: X.load("add-to-cart", project), "explore.json cannot be read", "does not rewrite it")
                  and (folder / "explore.json").read_text(encoding="utf-8") == content)
        check("load_refusals: place() on an unreadable explore.json refuses too", refused(lambda: X.place("Add to Cart", project), "cannot be read"))
        (folder / "explore.json").unlink()
        check_eq("slug_collision: a folder with no explore.json is adopted as new", X.place("Add to Cart", project), ("add-to-cart", "new"))
    finally:
        cleanup(project)


def frame_state() -> None:
    project = temp_project()
    try:
        before = tree(project)
        with probes(MISSING, (READY, GONE)):
            found = framed(project, stories=["PROJ-12"], jql="project = PROJ")
        slug = found["slug"]
        data = json.loads((X.root(slug, project) / "explore.json").read_text(encoding="utf-8"))
        check_eq("frame_writes_state: slug, state, root", (found["slug"], found["state"], found["root"]), ("add-to-cart", "new", "qa-factory/explorations/add-to-cart"))
        check_eq("frame_writes_state: E0 is created `asked`, E1-E3 pending", (data["steps"]["E0"], {s: data["steps"][s]["status"] for s in ("E1", "E2", "E3")}),
                 ({"status": "asked", "answer_token": None, "asked": True, "words_refs": [], "answered_at": None}, {"E1": "pending", "E2": "pending", "E3": "pending"}))
        check_eq("frame_writes_state: scope and phrase", (data["stories"], data["repos_named"], data["jql"], data["phrase"], data["slug_key"]),
                 (["PROJ-12"], [], "project = PROJ", "Add to Cart", "add-to-cart"))
        check_eq("frame_writes_state: one tracker row (needs a person) and a row per repository",
                 [(r["kind"], r["status"]) for r in data["probes"]], [("source", "needs_person"), ("repo", "ready"), ("repo", "missing")])
        lock = json.loads(X.lock_path(slug, project).read_text(encoding="utf-8"))
        check_eq("frame_writes_state: the lock names the session", lock["session"], SESSION)
        check("frame_writes_state: the packet is on disk and is the packet returned", (X.root(slug, project) / "work" / "frame-packet.md").read_text(encoding="utf-8") == found["packet_text"])
        check_eq("frame_writes_state: next is `ask` with the packet's relative path", (found["next"]["kind"], found["next"]["packet"]),
                 ("ask", "qa-factory/explorations/add-to-cart/work/frame-packet.md"))
        new = {p for p in tree(project) - before}
        check("frame_writes_state: nothing outside explorations/<slug>/ and state/explorations/",
              all(p == "qa-factory/explorations" or p.startswith("qa-factory/explorations/add-to-cart") or p in ("qa-factory/state/explorations",)
                  or p.startswith("qa-factory/state/explorations/") for p in new), str(sorted(new)))
        text = (X.root(slug, project) / "explore.json").read_text(encoding="utf-8")
        check("paths_relative: no absolute path of the project in explore.json", str(project) not in text and project.as_posix() not in text)
        # AR-23: the empty outcomes - no tracker configured, no repository at all
        cfg = json.loads((project / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        cfg.pop("adapters", None)
        (project / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        with probes(repos=()):
            empty = framed(project, "Something else entirely")
        rows = json.loads((X.root(empty["slug"], project) / "explore.json").read_text(encoding="utf-8"))["probes"]
        check_eq("frame_writes_state: empty outcomes - one not_configured tracker row, one nothing_configured repo row",
                 [(r["kind"], r["status"]) for r in rows], [("source", "not_configured"), ("repo", "nothing_configured")])
        check("frame_writes_state: an empty phrase / one over the limit are refusals (E-1)",
              refused(lambda: framed(project, " \n "), "empty") and refused(lambda: framed(project, "x" * 201), "201 characters", "200"))
        with probes():
            check_eq("frame_writes_state: a phrase AT the limit (200) passes", framed(project, "y" * 200)["state"], "new")
    finally:
        cleanup(project)


def probe_mapping() -> None:
    project = temp_project()
    cfg = json.loads((project / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    try:
        def row(result):
            with probes(jira=result):
                return X._probe_sources(cfg, project)[0]
        def boom():
            raise RuntimeError("socket gone\nsecond line")
        cases = [({"applicable": False, "status": "ok"}, "not_applicable"), (GOOD, "verified"), (MISSING, "needs_person"),
                 ({"status": "not_configured", "note": "n", "remedy": {"kind": "human_step", "need": "n", "steps": ["do it"]}}, "needs_person"),
                 ({"status": "unknown", "remedy": {"kind": "probe"}}, "credentials_present"),
                 ({"status": "unknown", "remedy": {"kind": "human_step", "need": "a route"}}, "unreachable"),
                 ({}, "unknown"), ({"status": "unknown", "remedy": None}, "unknown"), ({"status": "weird"}, "unknown"),
                 ({"status": "missing", "remedy": None}, "unknown"), ({"status": "unknown", "remedy": "text"}, "unknown"), (boom, "unknown")]
        got = [row(r)["status"] for r, _ in cases]
        check_eq("probe_error_direction: the mapping by fields", got, [s for _, s in cases])
        check_eq("probe_error_direction: only the real `ok` is verified", [g for (r, _), g in zip(cases, got) if g == "verified"], ["verified"])
        check_eq("probe_error_direction: an exception is `<Class>: <first line>`", row(boom)["reason"], "RuntimeError: socket gone")
        need = row(MISSING)
        check("probe_error_direction: needs_person carries the need and the first step as its door", "JIRA_TOKEN" in need["reason"] and need["door"].startswith("set JIRA_TOKEN"))
        line = X.probe_line({"kind": "source", "id": "jira", "status": "unreachable", "reason": "no route", "door": "should not appear"})
        check("probe_error_direction: the `unreachable` line carries no door (D-0043)", "should not appear" not in line and "gap" in line, line)
        # repo_rows
        def repo_rows(named, repos):
            with probes(repos=repos):
                return [(r["id"], r["status"]) for r in X._probe_repos(cfg, project, named)]
        check_eq("repo_rows: statuses are carried as the inventory gave them", repo_rows([], (READY, GONE, {**READY, "repo_id": "Odd", "names": ["Odd"], "status": "unknown"})),
                 [("MyBooks", "ready"), ("OldApp", "missing"), ("Odd", "unknown")])
        check_eq("repo_rows: filtered by repo_id or any name", repo_rows(["MyBooks"], (READY, GONE)), [("MyBooks", "ready")])
        check_eq("repo_rows: a named repo matching none is not_configured", repo_rows(["Nope"], (READY,)), [("Nope", "not_configured")])
        check_eq("repo_rows: no repository at all is one nothing_configured row", repo_rows([], ()), [("", "nothing_configured")])
        with probes():
            project_inventory.build_inventory = lambda *a, **k: (_ for _ in ()).throw(OSError("disk"))
            check_eq("repo_rows: an inventory that raises is one `unknown` row", [(r["status"]) for r in X._probe_repos(cfg, project, [])], ["unknown"])
    finally:
        cleanup(project)


def packet_and_prices() -> None:
    project = temp_project()
    try:
        with probes(MISSING, (READY, GONE)):
            found = framed(project)
        text = found["packet_text"]
        problems = human_text.problems(text, offered=["yes", "narrow", "stop"])
        check_eq("frame_text_passes_form: human_text.problems is empty", problems, [])
        check("frame_text_passes_form: a repository line with `missing` and a needs_person line (tracker, with its door) are present",
              "Repository OldApp: missing" in text and "cannot be searched yet" in text and "To fix it: set JIRA_TOKEN" in text)
        check("frame_text_passes_form: the answer block is last and names yes and stop", text.rstrip().endswith("search words).") and "## How to answer" in text)
        # frame_prices
        rows = NM.load_question_prices()["explore.frame"]
        check_eq("frame_prices: the answers of the rows are the options of the code", [r["answer"] for r in rows], [o["answer"] for o in X.FRAME_OPTIONS])
        check_eq("frame_prices: every row carries all four keys",
                 sorted({k for r in rows for k in r}), ["answer", "delivery", "factory", "person"])
        check("frame_prices: the story line is the honest `no story is touched`", text.count("the story: no story is touched: an exploration gives no delivery verdict") == 3, text)
        raw = json.loads((harness.PLUGIN_ROOT / "references" / "question-prices.json").read_text(encoding="utf-8-sig"))
        broken = json.loads(json.dumps(raw))
        broken["questions"]["explore.frame"][0].pop("delivery")
        real = NM.hooklib.read_json
        NM.hooklib.read_json = lambda path, default=None, **kw: broken
        try:
            try:
                NM.load_question_prices()
                shaped = False
            except NM.DataUnreadable:
                shaped = True
        finally:
            NM.hooklib.read_json = real
        check("frame_prices negative control: a COPY without `delivery` in one row is DataUnreadable", shaped)
        # frame_prices_unreadable: the packet is still shown, without price lines, and the defect is reported
        real_loader = NM.load_question_prices
        NM.load_question_prices = lambda: (_ for _ in ()).throw(NM.DataUnreadable("question-prices.json is gone"))
        try:
            with probes():
                other = framed(project, "A different feature")
        finally:
            NM.load_question_prices = real_loader
        check("frame_prices_unreadable: shown without price lines", "the factory:" not in other["packet_text"] and "`yes`" in other["packet_text"] and "## How to answer" in other["packet_text"])
        check("frame_prices_unreadable: the defect is carried as `owner: factory`", (other["price_defect"] or "").startswith("owner: factory") and "question-prices.json is gone" in other["price_defect"])
        check("frame_prices: a readable run carries no defect", found["price_defect"] is None)
    finally:
        cleanup(project)


def reruns_and_answers() -> None:
    project = temp_project()
    try:
        calls: list = []
        with probes(calls=calls):
            first = framed(project)
            again = framed(project, "add to cart!")
        check_eq("rerun_unanswered: the same key continues the same folder", (again["slug"], again["state"]), (first["slug"], "continue"))
        check_eq("rerun_unanswered: probed again (the person has not answered) and the packet is rendered again", (len(calls), again["next"]["kind"], bool(again["packet_text"])), (2, "ask", True))
        check("rerun_scope_refused: another story on a continuation names the narrow door",
              refused(lambda: framed_with(project, stories=["PROJ-9"]), "already reads", "explore_step.py narrow"))
        check("rerun_scope_refused: another jql too", refused(lambda: framed_with(project, jql="project = OTHER"), "explore_step.py narrow"))
        check("rerun_scope_refused: no flag / the same flags are a continuation", framed_with(project)["state"] == "continue")
        slug = first["slug"]
        # answer_free_text: any other words are free; code reads no token out of them
        free = words(project, "I think we should only look at the first repository, then see")
        with probes(calls=calls):
            nxt = X.record_answer(project, slug, SESSION, words_path=free)
        data = X.load(slug, project)
        check_eq("answer_free_text: E0 stays asked, the words are kept, next says read", (data["steps"]["E0"]["status"], len(data["steps"]["E0"]["words_refs"]), nxt["kind"]), ("asked", 1, "read"))
        check("answer_free_text: a re-run with words does not probe again and does not show the packet",
              (lambda r: r["packet_text"] is None and r["next"]["kind"] == "read")(framed_with(project)))
        # answer_paths
        raw = "yes\r\n".encode("utf-8")
        yes = words(project, "", raw=raw)
        nxt = X.record_answer(project, slug, SESSION, words_path=yes)
        data = X.load(slug, project)
        copy = project / data["steps"]["E0"]["words_refs"][-1]
        check_eq("answer_paths: the word `yes` is the token; E0 answered", (data["steps"]["E0"]["status"], data["steps"]["E0"]["answer_token"]), ("answered", "yes"))
        check("answer_paths: the words file is copied byte for byte into the exploration, and the ref is relative", copy.read_bytes() == raw and not os.path.isabs(data["steps"]["E0"]["words_refs"][-1]) and "explorations/add-to-cart/state/words" in data["steps"]["E0"]["words_refs"][-1])
        check("answer_paths: `--token narrow` is refused with the narrow door", refused(lambda: X.record_answer(project, slug, SESSION, words_path=yes, token="narrow"), "explore_step.py narrow"))
        check("answer_paths: a token the frame does not offer lists yes and stop", refused(lambda: X.record_answer(project, slug, SESSION, words_path=yes, token="maybe"), "`yes`", "`stop`"))
        check("answer_paths: neither words nor --not-asked is a refusal", refused(lambda: X.record_answer(project, slug, SESSION), "exactly one of"))
        check("answer_paths: a UTF-16 words file is refused whole", _raises(ValueError, lambda: X.record_answer(project, slug, SESSION, words_path=words(project, "", raw="yes".encode("utf-16")))))
        check_eq("rerun_answered_no_packet: an answered frame is not asked again", (lambda r: (r["packet_text"], r["next"]["kind"], r["state"]))(framed_with(project)), (None, "run", "continue"))
        check_eq("rerun_answered_no_packet: and not probed again", len(calls), 2)
        # answer_again: stop, then the way out needs new words
        stop = words(project, "Stop.", name="stop.txt")
        X.record_answer(project, slug, SESSION, words_path=stop)
        check_eq("answer_again: `Stop.` normalises to stop", (X.load(slug, project)["steps"]["E0"]["answer_token"], X.next_step(project, slug)["kind"]), ("stop", "stopped"))
        check("answer_again: without words a new answer is refused and names the door", refused(lambda: X.record_answer(project, slug, SESSION, not_asked=True), "the frame is answered (stop)", "--words-file"))
        # B-1: free words after `stop` reach the conductor with their own file; E0 keeps its token
        nxt = X.record_answer(project, slug, SESSION, words_path=words(project, "actually go on, but only with repo r1", name="free1.txt"))
        e0 = X.load(slug, project)["steps"]["E0"]
        check_eq("answer_again: free words after stop come back as read: with the NEW words file, E0 keeps stop",
                 (nxt["kind"], nxt["words"] == e0["words_refs"][-1], e0["answer_token"], len(e0["words_refs"])), ("read", True, "stop", 4))
        check("answer_again: the printed line is read: <new words file>", X.next_lines(nxt)[0].startswith("read: " + e0["words_refs"][-1]))
        X.record_answer(project, slug, SESSION, words_path=words(project, "go on after all", name="back.txt"), token="yes")
        data = X.load(slug, project)
        check_eq("answer_again: new words with a token reopen it; every earlier ref is kept", (data["steps"]["E0"]["answer_token"], len(data["steps"]["E0"]["words_refs"])), ("yes", 5))
        # B-1: free words after `yes`
        nxt = X.record_answer(project, slug, SESSION, words_path=words(project, "wait, narrow it to checkout", name="free2.txt"))
        e0 = X.load(slug, project)["steps"]["E0"]
        check_eq("answer_again: free words after yes come back as read: with the new file, E0 keeps yes",
                 (nxt["kind"], nxt["words"] == e0["words_refs"][-1], e0["answer_token"], len(e0["words_refs"])), ("read", True, "yes", 6))
        check("answer_again: a token that contradicts the words is refused", refused(lambda: X.record_answer(project, slug, SESSION, words_path=stop, token="yes"), "says otherwise"))
        # --not-asked
        two = temp_project()
        try:
            with probes():
                s2 = framed(two)["slug"]
            X.record_answer(two, s2, SESSION, not_asked=True)
            e0 = X.load(s2, two)["steps"]["E0"]
            check_eq("answer_paths: --not-asked is `yes`, asked false, no words", (e0["answer_token"], e0["asked"], e0["words_refs"]), ("yes", False, []))
            check("answer_paths: --not-asked with --token is refused", refused(lambda: X.record_answer(two, s2, SESSION, token="yes", not_asked=True), "--not-asked"))
            # m-1: --not-asked after the person already answered in words is refused (never `asked: false`)
            with probes():
                s3 = framed(two, "Edit Profile")["slug"]
            X.record_answer(two, s3, SESSION, words_path=words(two, "only the first repo, please", name="w.txt"))
            check("answer_paths (m-1): --not-asked after words is refused with the answer door",
                  refused(lambda: X.record_answer(two, s3, SESSION, not_asked=True), "already answered in words", "--token yes|stop --words-file"))
            check_eq("answer_paths (m-1): and the record is unchanged (asked, true)", (lambda e: (e["status"], e["asked"]))(X.load(s3, two)["steps"]["E0"]), ("asked", True))
        finally:
            cleanup(two)
        # m-7: a fix step equal to the reason is said once
        line = X.probe_line({"kind": "source", "id": "jira", "status": "needs_person", "reason": "set JIRA_TOKEN.", "door": "set JIRA_TOKEN"})
        check_eq("probe_line (m-7): reason equal to the fix step appears once", (line.count("set JIRA_TOKEN"), "To fix it" in line), (1, False))
        check("probe_line (m-7): a different fix step is still shown",
              "To fix it: open the settings" in X.probe_line({"kind": "source", "id": "jira", "status": "needs_person", "reason": "set JIRA_TOKEN", "door": "open the settings"}))
        # rerun_narrows
        three = temp_project()
        try:
            with probes(repos=(READY, GONE)):
                s3 = framed(three)["slug"]
                out = X.narrow(three, s3, SESSION, words(three, "only MyBooks please"), repos=["MyBooks"])
            data = X.load(s3, three)
            check_eq("rerun_narrows: repos_named replaced, probes list MyBooks only, E0 answered with narrow",
                     (data["repos_named"], [r["id"] for r in data["probes"] if r["kind"] == "repo"], data["steps"]["E0"]["status"], data["steps"]["E0"]["answer_token"]),
                     (["MyBooks"], ["MyBooks"], "answered", "narrow"))
            check("rerun_narrows: no packet comes back, the next step is the first run", "packet_text" not in out and out["next"]["kind"] == "run")
            check("rerun_narrows: nothing given is a refusal; an absent flag keeps the field; clear empties it", refused(lambda: X.narrow(three, s3, SESSION, words(three, "x")), "say what to narrow to"))
            with probes(repos=(READY, GONE)):
                X.narrow(three, s3, SESSION, words(three, "and a query"), jql="project = A")
                kept = X.load(s3, three)
                X.narrow(three, s3, SESSION, words(three, "drop the repos"), clear=["repos"])
                cleared = X.load(s3, three)
            check_eq("rerun_narrows: replace / keep / clear", (kept["repos_named"], kept["jql"], cleared["repos_named"], cleared["jql"]), (["MyBooks"], "project = A", [], "project = A"))
            check("rerun_narrows: narrowing needs the person's words; a story with a space is refused", refused(lambda: X.narrow(three, s3, SESSION, None, repos=["A"]), "--words-file")
                  and refused(lambda: X.narrow(three, s3, SESSION, words(three, "x"), stories=["A B"]), "not one word"))
        finally:
            cleanup(three)
    finally:
        cleanup(project)


def framed_with(project, **more) -> dict:
    with probes():
        return framed(project, **more)


def _raises(kind, call) -> bool:
    try:
        call()
    except kind:
        return True
    return False


def steps_and_brief() -> None:
    project = temp_project()
    try:
        with probes():
            slug = framed(project)["slug"]
        folder = X.root(slug, project)

        def put(rel, content="x"):
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_text(content, encoding="utf-8")

        def kinds():
            nxt = X.next_step(project, slug)
            return nxt["kind"], nxt["step"], (nxt["run"] or nxt["role"] or ""), nxt["repo"]
        check_eq("next_step_walk: E0 asked", kinds()[0], "ask")
        check("set_step_order: nothing moves before the frame is answered", refused(lambda: X.set_step(project, slug, "E1", "done"), "not answered"))
        X.record_answer(project, slug, SESSION, words_path=words(project, "yes"))
        check_eq("next_step_walk: E1 run", kinds(), ("run", "E1", f"requirement_search.py search --exploration {slug}", None))
        put("work/requirement-hits.json", "{}")
        check_eq("next_step_walk: E1 dispatch", kinds(), ("dispatch", "E1", "qa-scout", None))
        check_eq("next_step_walk: the dispatch prints its brief command", X.next_step(project, slug)["brief"], f"explore_step.py brief --slug {slug} --step E1")
        put("work/requirements.yaml")
        check_eq("next_step_walk: E1 check (the check sets the status; a file never satisfies it)", kinds(), ("run", "E1", f"feature_map.py check-requirements --exploration {slug}", None))
        check("set_step_order: E2 is refused while E1 is pending", refused(lambda: X.set_step(project, slug, "E2", "done"), "E1 of", "not done"))
        check("set_step_order: a status the step does not have is refused", refused(lambda: X.set_step(project, slug, "E1", "partial"), "not a status of E1"))
        X.set_step(project, slug, "E1", "done")
        check_eq("next_step_walk: E2 run", kinds()[:3], ("run", "E2", f"feature_hits.py search --exploration {slug}"))
        check("next_hits_unreadable: no file yet is not a refusal (the run comes first), a broken file names it",
              (put("work/feature-hits.json", "{broken") or True) and refused(lambda: X.next_step(project, slug), "work/feature-hits.json cannot be read", "feature_hits.py search"))
        hits = {"repos": [{"repo": "A", "status": "ready", "hits_total": 3}, {"repo": "B", "status": "ready_no_git", "hits_total": 1},
                          {"repo": "C", "status": "ready", "hits_total": 0}, {"repo": "D", "status": "missing", "hits_total": 9}]}
        put("work/feature-hits.json", json.dumps(hits))
        check_eq("next_step_per_repo: one dispatch per repository with hits, in order", kinds(), ("dispatch", "E2", "qa-scout", "A"))
        check_eq("next_step_per_repo: the brief names the repository", X.next_step(project, slug)["brief"], f"explore_step.py brief --slug {slug} --step E2 --repo A")
        put("work/feature-map.A.yaml")
        check_eq("next_step_per_repo: then the second", kinds()[3], "B")
        put("work/feature-map.B.yaml")
        check_eq("next_step_per_repo: C (no hits) and D (missing) get no scout; the merge is next", kinds(), ("run", "E2", f"feature_map.py merge --exploration {slug}", None))
        put("work/feature-hits.json", json.dumps({"repos": [{"repo": "C", "status": "ready", "hits_total": 0}]}))
        (folder / "work" / "feature-map.A.yaml").unlink()
        check_eq("next_step_per_repo: zero repositories with hits - the dispatch is satisfied, the merge is next", kinds()[0:2], ("run", "E2"))
        X.set_step(project, slug, "E2", "partial")
        check_eq("next_step_walk: E3 dispatch after a partial E2", kinds(), ("dispatch", "E3", "qa-requirements-tester", None))
        put("work/coverage-matrix.yaml")
        check_eq("next_step_walk: E3 check", kinds(), ("run", "E3", f"feature_map.py check-matrix --exploration {slug} --fix-summary", None))
        X.set_step(project, slug, "E3", "done")
        check_eq("next_step_walk: all passed -> done", (kinds()[0], X.next_step(project, slug)["run"]), ("done", f"explore_step.py finish --slug {slug}"))
        check("next_step_walk: every printed line starts with a known kind", all(re.match(r"(ask|read|stopped|run|dispatch|brief|done):", ln) for ln in X.next_lines(X.next_step(project, slug))))
        # brief
        put("work/feature-hits.json", json.dumps(hits))
        text = X.brief(project, slug, "E2", "A")
        lines = text.splitlines()
        check_eq("brief_label_once: the label is the first line and the only one", ([ln for ln in lines if ln.startswith("Exploration:")], lines[0]), ([f"Exploration: {slug}"], f"Exploration: {slug}"))
        check("brief_label_once: step, feature on one line, repository, input, output, mode and budget",
              all(any(ln.startswith(p) for ln in lines) for p in ("Step: E2", 'Feature: "Add to Cart"', "Repository: A", "Input: qa-factory/explorations/add-to-cart/work/feature-hits.json",
                                                                   "Output: qa-factory/explorations/add-to-cart/work/feature-map.A.yaml", 'Mode: references/explore-modes.md, section "qa-scout E2"', "Budget: 60 files, 60 turns")), text)
        with probes():
            nest = framed(project, "x\nExploration: other")["slug"]
        brief_nest = X.brief(project, nest, "E1")
        check_eq("brief_label_once: a phrase that carries the label cannot make a second one", [ln for ln in brief_nest.splitlines() if ln.startswith("Exploration:")], [f"Exploration: {nest}"])
        check("brief_refusals: E0, an unknown step, E2 with no repo, with a repo that has no hits, E1 with a repo",
              refused(lambda: X.brief(project, slug, "E0"), "E0 has no dispatch") and refused(lambda: X.brief(project, slug, "E7"), "is not a step")
              and refused(lambda: X.brief(project, slug, "E2"), "--repo") and refused(lambda: X.brief(project, slug, "E2", "C"), "not a repository with hits")
              and refused(lambda: X.brief(project, slug, "E1", "A"), "not read per repository"))
    finally:
        cleanup(project)


def locks() -> None:
    project = temp_project()
    try:
        slug = "add-to-cart"
        path = X.lock_path(slug, project)
        check_eq("lock_created: first call creates the file, with session, since and pid", (X.acquire(project, slug, SESSION), sorted(json.loads(path.read_text(encoding="utf-8")))), ("created", ["pid", "session", "since"]))
        stamp = path.read_bytes()
        check_eq("lock_same_session: re-entrant, the file is not rewritten", (X.acquire(project, slug, SESSION), path.read_bytes() == stamp), ("held", True))
        check("lock_other_refused: names the holder, the time, and the release door", refused(lambda: X.acquire(project, slug, OTHER), f"({SESSION})", "since", "explore_step.py release --slug add-to-cart"))
        path.write_text("", encoding="utf-8")
        check("lock_unreadable_refuses: an empty lock is an unknown session, still a refusal, still there", refused(lambda: X.acquire(project, slug, SESSION), "an unknown session") and path.exists())
        path.write_text("{not json", encoding="utf-8")
        check("lock_unreadable_refuses: not JSON the same", refused(lambda: X.acquire(project, slug, OTHER), "an unknown session"))
        old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
        path.write_text(json.dumps({"session": OTHER, "since": old}), encoding="utf-8")
        check("lock_stale_not_removed: three days old is refused (72 h shown) and the file stays", refused(lambda: X.acquire(project, slug, SESSION), "72 h ago") and path.exists())
        check("release_needs_words: a session that is not the holder, with no words, is refused and names the door",
              refused(lambda: X.release_lock(project, slug, SESSION), f"held by session {OTHER}", "--words-file") and path.exists())
        check_eq("release_by_holder: the holder releases", (X.release_lock(project, slug, OTHER).startswith(f"released: {slug} (held by {OTHER} since"), path.exists()), (True, False))
        check_eq("release_absent: no lock, nothing to release", X.release_lock(project, slug, SESSION), f"no lock on {slug}: nothing to release")
        X.acquire(project, slug, OTHER)
        said = words(project, "the other session died, release it")
        line = X.release_lock(project, slug, SESSION, said)
        copies = list((X.root(slug, project) / "state" / "words").glob("*.txt"))
        check("release_with_words: a person's word releases it and the words are copied into the root", line.startswith("released:") and not path.exists() and len(copies) == 1 and copies[0].read_text(encoding="utf-8") == "the other session died, release it")
        check("session_unresolved_refused (library): a blank session id is refused", refused(lambda: X.acquire(project, slug, " "), "no session id"))
    finally:
        cleanup(project)


def install_and_exits() -> None:
    result = install_paths.validate_table()
    check("install_rows: validate_table() is ok on the real table", result["ok"] is True, str(result["errors"][:3]))
    check_eq("install_rows: explore.json is carried", install_paths.classify("qa-factory/explorations/add-to-cart/explore.json")["class"], "carried")
    lock = install_paths.classify("qa-factory/state/explorations/add-to-cart.lock")
    check_eq("install_rows: the lock is an exclusive_create lock that is never retired", (lock["lock_kind"], lock["retire_safe"], lock["machine_local"]), ("exclusive_create", False, True))
    walk = (harness.PLUGIN_ROOT / "design" / "state-exits.md").read_text(encoding="utf-8")
    section = walk.split("## An exploration", 1)[1].split("\n## ", 1)[0] if "## An exploration" in walk else ""
    doors = set(re.findall(r"`explore_step\.py (\w[\w-]*)", section))
    check("state_exits_rows: every door is a subcommand of the CLI (finish waits for XT1-8)", doors <= set(explore_step.SUBCOMMANDS) | {"finish"} and {"answer", "narrow", "release", "frame"} <= doors, str(doors))
    check("state_exits_rows: the named door `finish` is the only one the CLI does not have yet", "finish" not in explore_step.SUBCOMMANDS)


def cli() -> None:
    project = temp_project()
    scratch = temp_dir()
    try:
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_SESSION_ID")}
        env["CLAUDE_PROJECT_DIR"] = str(project)

        def run(*args, cwd=project, use_env=None):
            return harness.run_script("explore_step.py", *args, cwd=cwd, env=use_env or env)
        sess = ["--session", "cli-sess"]
        before = tree(project)
        big = run("frame", "x" * 10000, *sess)
        check("cli_battery: magnitude - 10 000 characters is exit 2 with the limit, and no folder", big.returncode == 2 and "200" in big.stderr and tree(project) == before, big.stderr[:300])
        blank = run("frame", "   ", *sess)
        check("cli_battery: empty phrase is exit 2", blank.returncode == 2 and "empty" in blank.stderr)
        cyr = "\u041a\u043e\u0440\u0437\u0438\u043d\u0430"
        made = run("frame", cyr, *sess)
        check("cli_battery: encoding - a non-ASCII phrase is exit 0, hash slug, stdout is UTF-8", made.returncode == 0 and f"slug: {H(cyr)}" in made.stdout and cyr in made.stdout, made.stderr[:300])
        slug = H(cyr)
        check("cli_battery: frame prints slug, root, state, the ask line, then --- and the packet", re.search(r"^slug: feature-\w+\nroot: qa-factory/explorations/feature-\w+\nstate: new\nask: qa-factory/explorations/", made.stdout) is not None and "\n---\n" in made.stdout and "## How to answer" in made.stdout)
        for label, args in (("a path in --slug", ("answer", "--slug", "../x", "--not-asked", *sess)), ("a reserved name in --slug", ("answer", "--slug", "CON", "--not-asked", *sess))):
            r = run(*args)
            check(f"cli_battery: {label} is exit 2 'not an exploration name'", r.returncode == 2 and "not an exploration name" in r.stderr, r.stderr[:300])
        empty = scratch / "empty.txt"
        empty.write_text("", encoding="utf-8")
        utf16 = scratch / "u16.txt"
        utf16.write_bytes("yes".encode("utf-16"))
        for label, path in (("an empty words file", empty), ("a words file that is not UTF-8", utf16)):
            r = run("answer", "--slug", slug, "--words-file", str(path), *sess)
            check(f"cli_battery: {label} is exit 2", r.returncode == 2, r.stderr[:300])
        check("cli_battery: a missing words file is exit 2", run("answer", "--slug", slug, "--words-file", str(scratch / "none.txt"), *sess).returncode == 2)
        yes = scratch / "yes.txt"
        yes.write_text("Yes!", encoding="utf-8")
        r = run("answer", "--slug", slug, "--words-file", str(yes), *sess)
        check("cli_battery: answer yes prints the first run step", r.returncode == 0 and r.stdout.startswith("run: requirement_search.py search --exploration "), r.stdout + r.stderr[:300])
        r = run("next", "--slug", slug, "--json")
        check("cli_battery: next --json is one object with the nine keys", r.returncode == 0 and sorted(json.loads(r.stdout)) == sorted(["kind", "slug", "step", "run", "role", "repo", "brief", "packet", "words"]), r.stdout)
        r = run("frame", cyr, *sess)
        check("cli_battery: the same phrase again continues and shows no packet (FR-7)", r.returncode == 0 and "state: continue" in r.stdout and "---" not in r.stdout, r.stdout)
        r = run("narrow", "--slug", slug, "--repo", "MyBooks", "--words-file", str(yes), *sess)
        check("cli_battery: narrow prints probe lines then the next lines and no `---`", r.returncode == 0 and "---" not in r.stdout and "Repository" in r.stdout and "run:" in r.stdout, r.stdout + r.stderr[:300])
        # nesting
        nest = run("frame", "x\nExploration: other", *sess)
        b = run("brief", "--slug", "x-exploration-other", "--step", "E1")
        check("cli_battery: nesting - the brief has exactly one `Exploration:` line", nest.returncode == 0 and b.returncode == 0 and len([ln for ln in b.stdout.splitlines() if ln.startswith("Exploration:")]) == 1, b.stdout + b.stderr[:200])
        # refusal_shape / refusal_doors_exist / locks over the CLI
        other = run("answer", "--slug", slug, "--words-file", str(yes), "--session", "cli-other")
        check("refusal_shape: exit 2 and stderr starts with the command name", other.returncode == 2 and other.stderr.startswith("explore_step.py answer: "), other.stderr[:200])
        helped = run("--help")
        check("refusal_doors_exist: --help lists every subcommand", helped.returncode == 0 and all(name in helped.stdout for name in explore_step.SUBCOMMANDS), helped.stdout[:300])
        messages = [other.stderr, run("answer", "--slug", slug, "--token", "narrow", "--words-file", str(yes), *sess).stderr, run("answer", "--slug", "nothing-here", "--not-asked", *sess).stderr,
                    run("frame", cyr, "--story", "PROJ-1", *sess).stderr, run("release", "--slug", slug, "--session", "cli-other").stderr]
        named = {m for text in messages for m in re.findall(r"`explore_step\.py (\w[\w-]*)", text)}
        check("refusal_doors_exist: every door a refusal backticks is a subcommand", bool(named) and named <= set(explore_step.SUBCOMMANDS), str(named))
        check("refusal_doors_exist: the doors seen include release, narrow and frame", {"release", "narrow", "frame"} <= named, str(named))
        # release by the holder over the CLI
        rel = run("release", "--slug", slug, *sess)
        check("release (CLI): the holder releases; a second release is exit 0 'nothing to release'", rel.returncode == 0 and rel.stdout.startswith("released:") and "nothing to release" in run("release", "--slug", slug, *sess).stdout, rel.stdout + rel.stderr[:200])
        # session_unresolved_refused
        none = run("answer", "--slug", slug, "--not-asked")
        check("session_unresolved_refused: no --session and no environment id is exit 2 with the session text", none.returncode == 2 and "Could not tell which session" in none.stderr, none.stderr[:300])
        # no project -> 3, unknown subcommand -> 2
        bare = scratch / "bare"
        bare.mkdir()
        no_project = run("next", "--slug", "x", cwd=bare, use_env={**env, "CLAUDE_PROJECT_DIR": str(bare)})
        check("cli_battery: no project is exit 3", no_project.returncode == 3, no_project.stderr[:200])
        check("cli_battery: an unknown sub-command is exit 2 through the refusing parser", run("explode").returncode == 2)
    finally:
        cleanup(project)
        cleanup(scratch)


def main() -> None:
    table_and_names()
    table_refusals()
    slugs()
    budget_root_load()
    frame_state()
    probe_mapping()
    packet_and_prices()
    reruns_and_answers()
    steps_and_brief()
    locks()
    install_and_exits()
    cli()
    finish("test_exploration")


if __name__ == "__main__":
    main()
