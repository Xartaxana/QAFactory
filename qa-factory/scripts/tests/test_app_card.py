#!/usr/bin/env python3
"""t-1957 N3 (first part): the app card `app_card.py build --task-root T` -> `work/app-card.md` (AR-8, AR-11, AR-13, AR-23).

Keys: sections in order, each a line or `not known: <why>`; no profile / no sign-in proof / empty or malformed sources are lines,
never a refusal; no secret value of ANY input is printed (a password-like and a token-like value planted in each); the card is
cut at 8 000 B by its entry routes, tested AT and BEYOND the limit; the first line says the card is no oracle; the file is
rebuilt only when its inputs change; walkers' notes and the created users' NAMES are carried; a path with spaces and
non-ASCII characters works.

Mutations this file kills: a section dropped or reordered | a value printed (any planted one) | the cut takes another section
or does not name N and the file | the card rewritten on equal inputs | the first line changed.

Run: python -B scripts/tests/test_app_card.py    or    python -m pytest scripts/tests/test_app_card.py -q
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import app_card as AC  # noqa: E402

PW = "Hunt3r2-Pl4nted!Pw"                       # a password-like value
TOKEN = "ghp_Pl4ntedT0kenValue0123456789abcdef"  # a token-like value
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwbGFudGVkIn0.c2lnbmF0dXJl"
PLANTED = (PW, TOKEN, JWT, "Pl4ntedEnvPw", "Pl4ntedProbeTok", "Pl4ntedCreatedPw", "Pl4ntedNotePw", "Pl4ntedQueryTok")

PROFILE = f"""# Project profile

- **What this product is** — a bookshop.
- **Components and entry points** — UI at /books, API at /api/books.
  Admin screen at /admin (password: {PW}).
- **Test data** — accounts by role: admin, reader (token={TOKEN}).
  Seeds: none.
- **Environments** — local.
"""


def make(base: Path, *, profile=PROFILE, config=None, name="story " + chr(0xE9) + chr(0x4E2D) + " 1"):
    """A project with config.json (and a profile) and a story folder; returns the story's folder."""
    project = base / "proj ü"
    (project / "qa-factory" / "strategy").mkdir(parents=True)
    cfg = config if config is not None else {
        "environment": {"env_file": "qa-factory/env.local", "user_key": "AUTH_USERNAME", "secret_keys": ["AUTH_PASSWORD"]},
        "environments": [{"name": "local", "base_url": "http://localhost:8000", "frontend": {"url": "http://localhost:5173"},
                          "credentials_by_role": {"admin": "ADMIN_USER / ADMIN_PASS", "reader": f"READER_USER / READER_PASS password={PW}"}}],
        "test_data": {"seeds": "none", "admin_password": "Pl4ntedEnvPw", "accounts_by_role": {"admin": "x", "reader": "y"},
                      "note": f"use {TOKEN} for imports"}}
    if config != "absent":
        (project / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (project / "qa-factory" / "env.local").write_text("AUTH_USERNAME=u1\nAUTH_PASSWORD=Pl4ntedEnvPw\nSECRET_TOKEN=Pl4ntedProbeTok\n",
                                                      encoding="utf-8")
    if profile is not None:
        (project / "qa-factory" / "strategy" / "project-profile.md").write_text(profile, encoding="utf-8")
    task = project / "qa-factory" / "artifacts" / name
    (task / "work").mkdir(parents=True)
    (task / "state").mkdir()
    return task


def write_requests(task: Path, n: int, url="https://x.test/api/books/{id}?token=Pl4ntedQueryTok"):
    rows = [{"method": "GET", "url_template": url.replace("books", f"books{i}"), "source": "code", "path": f"src/api{i}.ts", "line": i + 1}
            for i in range(n)]
    (task / "work" / "flow-requests.json").write_text(json.dumps({"schema_version": 1, "requests": rows}), encoding="utf-8")


def card_of(task: Path) -> str:
    return (task / "work" / "app-card.md").read_text(encoding="utf-8")


def headers(text: str) -> list:
    return [x[3:] for x in text.splitlines() if x.startswith("## ")]


def body(text: str, section: str) -> str:
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line[3:] == section
            continue
        if inside and not line.startswith("inputs: "):
            out.append(line)
    return "\n".join(out)


def test_sections_in_order_with_not_known(tmp_path):
    task = make(tmp_path)
    line = AC.build(task)
    text = card_of(task)
    assert line.startswith("app-card: written") and "\n" not in line
    assert headers(text) == list(AC.SECTIONS)
    assert "not known:" in body(text, "Page objects") and "not known:" in body(text, "Notes from walkers")
    assert "work/flow-requests.json" in body(text, "Entry routes")        # no request file: said, not silent
    for section in AC.SECTIONS:
        assert body(text, section).strip(), section                        # every section holds a line or `not known`
    assert "http://localhost:5173" in body(text, "Stand")


def test_no_profile_says_so_e31(tmp_path):
    task = make(tmp_path, profile=None)
    AC.build(task)
    text = card_of(task)
    assert "not known: no strategy/project-profile.md (onboarding)" in body(text, "Test data")
    assert "no strategy/project-profile.md (onboarding)" in body(text, "Entry routes")
    assert headers(text) == list(AC.SECTIONS)


def test_no_sign_in_proof_e32(tmp_path):
    task = make(tmp_path)
    AC.build(task)
    assert AC.NOT_PROVEN in body(card_of(task), "Sign-in")


def test_sign_in_proof_is_named(tmp_path):
    import manual_capture as MC
    task = make(tmp_path)
    cfg = json.loads((task.parents[1] / "config.json").read_text(encoding="utf-8"))
    row = {"outcome": "ok", "recipe_sha": MC.recipe_sha(MC.login_recipe(cfg, MC.spec(), "ui")), "token": "Pl4ntedProbeTok"}
    (task / "state" / "sign-in-probe.json").write_text(json.dumps({"default": row}), encoding="utf-8")
    AC.build(task)
    text = card_of(task)
    assert "Sign-in: proven at gate A for default" in body(text, "Sign-in") and AC.NOT_PROVEN not in text
    assert "Pl4ntedProbeTok" not in text


def test_no_secret_values(tmp_path):
    task = make(tmp_path)
    write_requests(task, 3)
    (task / "work" / "app-card-notes.jsonl").write_text(
        json.dumps({"about": "card", "note": f"the admin password is {JWT} and token={TOKEN}, pw: Pl4ntedNotePw"}) + "\n", encoding="utf-8")
    (task / "state" / "created-accounts.json").write_text(
        json.dumps({"accounts": [{"name": "qa-user-1", "password": "Pl4ntedCreatedPw", "case": "c1"}]}), encoding="utf-8")
    (task / "state" / "sign-in-probe.json").write_text(json.dumps({"default": {"outcome": "failed", "token": "Pl4ntedProbeTok"}}), encoding="utf-8")
    AC.build(task)
    text = card_of(task)
    for value in PLANTED:
        assert value not in text, value
    assert headers(text) == list(AC.SECTIONS)
    assert "admin_password" in text and "(value not printed)" in text      # the key NAME stays, the value does not


def test_scrub_forms():
    for raw in (f"password: {PW}", f"pwd={PW}", f"the secret is {PW}", f"Bearer {TOKEN}", f"https://u:{PW}@host/x", JWT, TOKEN,
                '{"api_key": "Pl4ntedNotePw"}'):
        out = AC.scrub(raw)
        assert PW not in out and TOKEN not in out and JWT not in out and "Pl4ntedNotePw" not in out, (raw, out)
    assert AC.scrub("/api/books/{id} on src/pages/LoginPage2.ts") == "/api/books/{id} on src/pages/LoginPage2.ts"


def test_cut_at_limit_names_rest(tmp_path, monkeypatch):
    task = make(tmp_path)
    write_requests(task, 400)
    AC.build(task)
    real = card_of(task)
    assert len(real.encode("utf-8")) <= AC.CARD_MAX_BYTES
    assert "more: work/flow-requests.json" in body(real, "Entry routes")   # beyond the real limit: cut, names the file
    # AT the limit: a limit equal to the whole card's size cuts nothing; one byte less cuts, and names N
    monkeypatch.setattr(AC, "CARD_MAX_BYTES", 10 ** 9)
    write_requests(task, 12)
    AC.build(task)
    whole = card_of(task)
    size = len(whole.encode("utf-8"))
    assert "more:" not in whole and whole.count("GET ") == 12
    monkeypatch.setattr(AC, "CARD_MAX_BYTES", size)
    AC.build(task)
    assert card_of(task) == whole.replace(f"inputs: {whole.splitlines()[-1][8:]}", f"inputs: {card_of(task).splitlines()[-1][8:]}")
    monkeypatch.setattr(AC, "CARD_MAX_BYTES", size - 1)
    AC.build(task)
    cut = card_of(task)
    assert len(cut.encode("utf-8")) <= size - 1 and "GET " in cut
    shown = cut.count("GET ")
    assert shown < 12 and f"- +{12 - shown} more: work/flow-requests.json" in body(cut, "Entry routes")
    for section in AC.SECTIONS[2:]:                                          # nothing else is the part that is cut
        assert body(cut, section) == body(whole, section), section
    assert body(cut, "Stand") == body(whole, "Stand")


def test_cut_keeps_the_card_under_the_real_limit_with_many_requests(tmp_path):
    task = make(tmp_path)
    write_requests(task, 3000)
    AC.build(task)
    text = card_of(task)
    assert len(text.encode("utf-8")) <= AC.CARD_MAX_BYTES
    shown = text.count("GET ")
    assert f"- +{3000 - shown} more: work/flow-requests.json" in text
    assert headers(text) == list(AC.SECTIONS)


def test_first_line_says_no_oracle(tmp_path):
    task = make(tmp_path)
    AC.build(task)
    assert card_of(task).splitlines()[0] == "routes and data to walk with; expectations come only from the case's Thens"


def test_hash_rebuild_only_on_change(tmp_path):
    task = make(tmp_path)
    assert AC.build(task).startswith("app-card: written")
    path = task / "work" / "app-card.md"
    os.utime(path, (1_000_000_000, 1_000_000_000))
    before = path.read_bytes()
    assert AC.build(task).startswith("app-card: unchanged")
    assert path.read_bytes() == before and path.stat().st_mtime == 1_000_000_000      # not rewritten
    write_requests(task, 2)                                                             # an input changed
    assert AC.build(task).startswith("app-card: written")
    assert path.read_bytes() != before and path.stat().st_mtime != 1_000_000_000
    assert AC.build(task).startswith("app-card: unchanged")


def test_walker_notes_included(tmp_path):
    task = make(tmp_path)
    rows = [{"about": "card", "note": "the Sign in button is under More options"},
            {"about": "page", "note": "not about the card"},
            "not json at all", {"about": "card", "text": "orders page needs a reload after save"}]
    lines = [r if isinstance(r, str) else json.dumps(r) for r in rows]
    (task / "work" / "app-card-notes.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    AC.build(task)
    notes = body(card_of(task), "Notes from walkers")
    assert "Sign in button is under More options" in notes and "orders page needs a reload" in notes
    assert "not about the card" not in notes and "1 unreadable line(s)" in notes
    many = [json.dumps({"about": "card", "note": f"note number {i}"}) for i in range(AC.NOTE_LINES + 5)]
    (task / "work" / "app-card-notes.jsonl").write_text("\n".join(many) + "\n", encoding="utf-8")
    AC.build(task)
    notes = body(card_of(task), "Notes from walkers")
    assert f"note number {AC.NOTE_LINES + 4}" in notes and "note number 0" not in notes and "(+5 older notes: work/app-card-notes.jsonl)" in notes


def test_created_handles_names_only(tmp_path):
    task = make(tmp_path)
    (task / "state" / "created-accounts.json").write_text(json.dumps({"accounts": [
        {"name": "qa-factory-story-c1-ab12cd34", "password": "Pl4ntedCreatedPw", "case": "c1", "endpoint": "/users"}]}), encoding="utf-8")
    AC.build(task)
    accounts = body(card_of(task), "Accounts")
    assert "qa-factory-story-c1-ab12cd34" in accounts and "created:<username>" in accounts
    assert "Pl4ntedCreatedPw" not in card_of(task)
    assert "ADMIN_USER" in accounts and "keys AUTH_USERNAME / AUTH_PASSWORD" in accounts   # names of keys, not their values
    assert "u1" not in accounts.replace("AUTH_USERNAME", "")


def test_empty_and_absent_inputs_never_refuse(tmp_path):
    bare = tmp_path / "bare story"
    bare.mkdir()
    line = AC.build(bare)                                              # no project, no source file at all
    text = card_of(bare)
    assert line.startswith("app-card: written") and headers(text) == list(AC.SECTIONS)
    assert "no qa-factory/config.json above the task root" in body(text, "Stand")
    assert AC.build(tmp_path / "nowhere").startswith("app-card: not written")        # not a folder: a line, no exception
    task = make(tmp_path / "second")
    (task / "work" / "flow-requests.json").write_text(json.dumps({"requests": []}), encoding="utf-8")
    AC.build(task)
    assert "work/flow-requests.json lists no request" in body(card_of(task), "Entry routes")


def test_malformed_sources_cost_one_section(tmp_path):
    task = make(tmp_path)
    (task / "work" / "flow-requests.json").write_text("{not json", encoding="utf-8")
    (task / "state" / "sign-in-probe.json").write_text("[1, 2", encoding="utf-8")
    (task / "state" / "created-accounts.json").write_text("{broken", encoding="utf-8")
    (task / "work" / "app-card-notes.jsonl").write_text("{nope\n[1]\n", encoding="utf-8")
    AC.build(task)
    text = card_of(task)
    assert headers(text) == list(AC.SECTIONS)
    assert "is not a JSON object with a list `requests`" in body(text, "Entry routes")
    assert "has no readable note" in body(text, "Notes from walkers")
    assert "http://localhost:5173" in body(text, "Stand") and AC.NOT_PROVEN in body(text, "Sign-in")
    assert "cannot be read" in body(text, "Accounts")                     # the created-users record: unknown, never none
    bad = make(tmp_path / "other", config="absent")
    (bad.parents[1] / "config.json").write_text("[1]", encoding="utf-8")
    AC.build(bad)
    assert "cannot be read as a JSON object" in body(card_of(bad), "Stand")


def test_repo_map_page_objects_are_named(tmp_path):
    task = make(tmp_path)
    (task / "work" / "briefs").mkdir()
    (task / "work" / "briefs" / "repo-map-abc.md").write_text(
        "# Repo map\n\n## Existing tests of the area\n\n- `t/test_x.py` (1 tests)\n\n## Utils, page objects and test data, ranked\n\n"
        "- `pages/books_page.py` (1,200 B): BooksPage, open, add\n- `pages/login.py` (300 B): LoginPage\n\n## How a test is written\n",
        encoding="utf-8")
    AC.build(task)
    pages = body(card_of(task), "Page objects")
    assert "pages/books_page.py" in pages and "pages/login.py" in pages and "t/test_x.py" not in pages


REGISTER = "# Requirements register\n\n## Register\n\n| ID | Requirement | Source |\n|---|---|---|\n| R-1 | The cart shows a Pay button. | task |\n"


def write_first_look(task: Path, rows: list, **extra):
    """The record of the first look, current for the story's register (the one writer `grounding_table.write_yaml`)."""
    import first_look as FL
    import grounding_table as GT
    (task / "work" / "requirements-register.md").write_text(REGISTER, encoding="utf-8")
    heads, reg_hash = FL.current_keys(task)
    record = {"walk": "S3-first-look", "stand": "local", "stand_build": "not_established", "register_hash": reg_hash, "rows": rows, "gaps": []}
    if json.loads(heads):
        record["source_head"] = json.loads(heads)
    record.update(extra)
    GT.write_yaml(task / "work" / "first-look.yaml", record)


def fl_row(n: int, **extra):
    row = {"req": f"R-{n}", "status": "confirms", "why": "looked", "path": {"url": f"/cart{n}", "steps": ["open the cart"],
           "locators": [{"what": "Pay button", "selector": "button#pay", "seen": "yes"}],
           "api": [{"method": "GET", "path": "/api/cart", "auth": "none", "seen": "yes",
                    "sample": {"request": "GET /api/cart", "status": "200", "response": "total 12"}}],
           "data": ["12 EUR"], "roles": ["admin"]}}
    row.update(extra)
    return row


def test_first_look_section(tmp_path):
    task = make(tmp_path)
    AC.build(task)
    text = card_of(task)
    assert headers(text) == list(AC.SECTIONS) and AC.SECTIONS.index("First look") == AC.SECTIONS.index("Entry routes") + 1
    assert body(text, "First look").strip() == "not known: there was no first look"            # no record: ONE line (AR-23)
    row = fl_row(1)
    row["path"]["data"] = [f"password: {PW}"]
    row["path"]["roles"] = ["admin"]
    del row["path"]["steps"]
    write_first_look(task, [row, {"req": "R-2", "status": "missing", "blocked_by": "product", "why": "not on the page", "expected": "EXPECTED-VAL"}])
    AC.build(task)
    text = card_of(task)
    section = body(text, "First look")
    assert headers(text) == list(AC.SECTIONS)
    for needle in ("- R-1 confirms", "screen /cart1", "locator Pay button: button#pay (seen yes)", "api GET /api/cart (auth none, seen yes)",
                   "sample seen: GET /api/cart | 200 | total 12", "data seen: password: [not printed]", "roles seen: admin", "- R-2 missing (product)"):
        assert needle in section, needle
    assert "EXPECTED-VAL" not in text and "not on the page" not in text and PW not in text      # an observation: no expectation, no secret
    assert section.count("total 12") == section.count("seen: GET /api/cart | 200 | total 12")
    (task / "work" / "first-look.yaml").write_text("garbage: [\n", encoding="utf-8")
    AC.build(task)
    assert "not known: the first look cannot be read" in body(card_of(task), "First look")
    import first_look as FL
    (task / "work" / "first-look.yaml").unlink()
    FL.put(task, None, "no_stand")
    AC.build(task)
    assert "not known: there was no first look: the stand was not walked (no stand)" in body(card_of(task), "First look")
    write_first_look(task, [fl_row(1)], register_hash="0" * 64)
    AC.build(task)
    stale = body(card_of(task), "First look")
    assert "STALE" in stale and "R-1" not in stale and "screen" not in stale                     # a stale record confirms nothing


def test_first_look_card_keeps_long_selectors_and_hides_tokens(tmp_path):
    """FL-4 fix round F2: a 30+ character data-testid reaches the card whole; a token-shaped value and a `token=` pair do not."""
    task = make(tmp_path)
    long_id = "checkout-submit-button-v2-0123456789"
    row = fl_row(1)
    row["path"]["locators"] = [{"what": "Pay button", "selector": f'[data-testid="{long_id}"]', "seen": "yes"}]
    row["path"]["steps"] = [f"click {long_id}", "send token=abcdef0123456789abcdef0123456789"]
    row["path"]["data"] = ["order a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"]
    write_first_look(task, [row])
    AC.build(task)
    section = body(card_of(task), "First look")
    assert f'locator Pay button: [data-testid="{long_id}"] (seen yes)' in section and f"step click {long_id}" in section
    assert "abcdef0123456789abcdef0123456789" not in section                        # a `token=` pair is still hidden in a step
    assert "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6" not in section and "data seen: order [not printed]" in section   # a value is still scrubbed with tokens


def test_first_look_input_changes_hash(tmp_path):
    task = make(tmp_path)
    assert AC.build(task).startswith("app-card: written")
    assert AC.build(task).startswith("app-card: unchanged")
    write_first_look(task, [fl_row(1)])
    assert AC.build(task).startswith("app-card: written")                                        # the record is an input
    assert AC.build(task).startswith("app-card: unchanged")
    write_first_look(task, [fl_row(1, status="contradicts")])
    assert AC.build(task).startswith("app-card: written") and "R-1 contradicts" in card_of(task)
    assert AC.build(task).startswith("app-card: unchanged")
    (task / "work" / "requirements-register.md").write_text(REGISTER + "| R-2 | A second requirement. | task |\n", encoding="utf-8")
    assert AC.build(task).startswith("app-card: written") and "STALE" in body(card_of(task), "First look")    # the verdict "stale" is an input too


def test_first_look_section_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(AC, "CARD_MAX_BYTES", 10 ** 9)
    task = make(tmp_path)
    write_first_look(task, [fl_row(n) for n in range(1, AC.FIRST_LOOK_REQ_MAX + 1)])
    AC.build(task)
    section = body(card_of(task), "First look")
    assert sum(1 for x in section.splitlines() if x.startswith("- R-")) == 20 and "+" not in "".join(x for x in section.splitlines() if x.startswith("- +"))
    write_first_look(task, [fl_row(n) for n in range(1, AC.FIRST_LOOK_REQ_MAX + 6)])             # BEYOND the cap: 25 requirements
    AC.build(task)
    section = body(card_of(task), "First look")
    assert sum(1 for x in section.splitlines() if x.startswith("- R-")) == 20 and "- +5: work/first-look.yaml" in section
    one = fl_row(1)
    one["path"]["data"] = [f"value {i}" for i in range(AC.FIRST_LOOK_REQ_LINES)]             # head + 4 items + 8 data = 14 lines for one requirement
    write_first_look(task, [one])
    AC.build(task)
    lines = body(card_of(task), "First look").splitlines()
    shown = [x for x in lines if not x.startswith("  - +")]
    assert len(shown) == AC.FIRST_LOOK_REQ_LINES and "  - +" in "".join(lines)               # 8 lines, then the pointer
    rest = [x for x in lines if x.startswith("  - +")]
    assert rest == [f"  - +{14 - AC.FIRST_LOOK_REQ_LINES}: work/first-look.yaml"] or rest[0].endswith("work/first-look.yaml")
    exact = fl_row(1)
    exact["path"] = {"url": "/a", "steps": ["s1", "s2", "s3", "s4", "s5", "s6"]}                # AT the cap: head + url + 6 steps = 8 lines exactly
    write_first_look(task, [exact])
    AC.build(task)
    assert not [x for x in body(card_of(task), "First look").splitlines() if "+" in x and "work/first-look.yaml" in x]
    long = fl_row(1)
    long["path"]["data"] = ["y" * 900]
    write_first_look(task, [long])
    AC.build(task)
    assert max(len(x) for x in body(card_of(task), "First look").splitlines()) <= AC.FIRST_LOOK_LINE_CHARS


def test_first_look_gives_way_before_routes(tmp_path, monkeypatch):
    task = make(tmp_path)
    write_requests(task, 12)
    write_first_look(task, [fl_row(n) for n in range(1, 6)])
    monkeypatch.setattr(AC, "CARD_MAX_BYTES", 10 ** 9)
    AC.build(task)
    whole = card_of(task)
    size = len(whole.encode("utf-8"))
    assert whole.count("x.test/api/books") == 12 and "more: work/flow-requests.json" not in whole and "screen /cart1" in whole
    monkeypatch.setattr(AC, "CARD_MAX_BYTES", size)                                              # AT the limit: nothing gives way
    AC.build(task)
    assert "screen /cart1" in card_of(task) and AC.FIRST_LOOK_POINTER not in card_of(task)
    monkeypatch.setattr(AC, "CARD_MAX_BYTES", size - 1)                                          # one byte over: the First look section first
    AC.build(task)
    cut = card_of(task)
    assert AC.FIRST_LOOK_POINTER in body(cut, "First look") and "screen /cart1" not in cut
    assert cut.count("x.test/api/books") == 12 and "more: work/flow-requests.json" not in cut         # every route is still there
    pointer_size = len(cut.encode("utf-8"))
    monkeypatch.setattr(AC, "CARD_MAX_BYTES", pointer_size - 1)                                  # beyond that the routes give way
    AC.build(task)
    deeper = card_of(task)
    assert AC.FIRST_LOOK_POINTER in body(deeper, "First look") and "more: work/flow-requests.json" in body(deeper, "Entry routes")
    assert len(deeper.encode("utf-8")) <= pointer_size - 1 and headers(deeper) == list(AC.SECTIONS)


def test_cli_prints_one_line_and_exits_zero(tmp_path, capsys):
    task = make(tmp_path)
    assert AC.main(["build", "--task-root", str(task)]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and out.startswith("app-card: written work/app-card.md")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
