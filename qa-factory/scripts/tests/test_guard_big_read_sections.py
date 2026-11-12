#!/usr/bin/env python3
"""SC1-3 part 3: the read guard names the section reader, and its exemptions are exact places (spec t-1253 section 3 part 3,
section 4 E-5/E-7/E-10/E-11, section 11 B-2, M-2, M-6).

A whole `Read` of a file over the limit is refused, as before, and the refusal now carries a DOOR the caller can open:

  K19  `work/grounding.yaml` read whole: the refusal starts with the old prefix and carries the map of the table's sections
  K20  `work/test-plan.json` read whole: the same, with the plan's rows
  K21  E-5: a table or a plan that cannot be read gives the OLD text (no map), still a block; the door never raises, whatever fails
       (the map function, the registry reader)
  K22  E-7: a range read, a small file, the limit off, an exempt place, a path that is not there - all pass, and the map is never built
  K23  a role WITHOUT a shell is named no script, only the map and the range read (FR-2)
  K24  a role with a shell, and the conductor (no role, no running dispatch), are also given the command line; with a strategist
       dispatch running the conductor is given the no-shell text (m-5: the safe direction)
  K25  E-10: a registry without `read_by_section` (an older plugin copy), or none at all: the old text
  K26  the forms: s3.md and s4.md tell the role the files are read by section
  M-2  a map the file does not confirm (the independent parse disagrees) is left out of the refusal
  B-2  every exemption is an EXACT place: each one passes when big, and its look-alike is refused
        - the plugin's references/ (the template config.json, 30,135 B, is the trap), the project's .claude/, CLAUDE.md, AGENTS.md,
          readiness report (both worlds of the layout), a story's pipeline.json and work/requirements-readiness.json
        - NOT exempt now: a `templates/` folder of a product, a CLAUDE.md below the root, `tsconfig.json`, another `config.json`
  B-1  (t-1333) the plugin's `skills/` is an exact place too: in an INSTALLED plugin (`~/.claude/plugins/cache/...`) and in a
       `--plugin-dir` one the phase and onboarding files SKILL.md says to read whole (s0.md, p2-interview.md, p4-generate.md) pass;
       a `skills/` folder of the project is refused
  F-1  the directory entries are asked of `runtime_paths.contained` (the one containment predicate), and a sibling folder that only
       starts with the same letters is not inside
  F-2  the error direction of the exemption: an `artifact_root` that raises is "not exempt" - a big story pipeline.json is refused
  Q-B  `plugin_read_check` asks `runtime_paths.contained`: `<plugin>-old/` is outside the plugin, `references-old/` is not references/
  Q-A  the registry is read through `hooklib.load_ref_json`: `owned_artifacts` falls back to `OWNED_ARTIFACTS` whenever the answer is
       empty or not a registry (missing, broken, not an object, no `artifacts`), `artifact_rewrite_check` gives no opinion
  M-6 the project config: 29,999 / 30,000 bytes pass, 30,001 is refused with the old prefix and the key door (Grep -n + range read);
       a different spelling of its path (case, backslashes, `..`) is the same file; a range read passes. TEMPORAL: while
       `config_view.py` is not in the plugin no text names it; when it is, a caller with a shell is named `--keys`, a role without
       one is not. The four readers of a big config - the conductor (s1.md), onboarding (no role), qa-runner, qa-bug-reporter -
       each get one refusal and then the key door.

  DR-1..DR-3 (S6 1d, spec 5.1) a `.pdf` over the limit is read by a `pages` range within `max_pdf_pages` (AT 20 passes, 21 is refused),
       `limit`/`offset` bound no PDF, `pages` bounds nothing on another file (a bounded `limit` on a blob passes: named for the
       critic), and the call the listing of `branch_accounting.py --attachments` prints passes the guard as printed

  IM-1..IM-9, IM-g, IM-h (SC2-41) a picture is recognised by its first bytes (a data row, never the suffix) and judged by its own limit
       `read.max_image_bytes` (default 5,242,880 = the adapter's image download limit); the real 93,414 / 83,997 B screenshots pass whole,
       text keeps 30,000, AT/BEYOND the image limit, every doubt (table, open error) is the old refusal, and the refusal's door is run

Mutations (named, run by the integrator, one killing file each - this one):
  m51 big_read_check: `pages` is a range on any file                 -> DR-2
  m52 big_read_check: `limit` bounds a `.pdf` again                   -> DR-2
  m53 _pdf_range_ok: the number of pages is not checked               -> DR-1
  m71..m75 the picture branch (see `the_pictures`)                    -> IM-*

Negative control: `T028_NEGATIVE_CONTROL=1` adds ONE check for a key that is not in the text; the run must then end red.
"""
import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import artifact_sections as AS  # noqa: E402
import branch_accounting as BA  # noqa: E402
import guard_pre_tool as G  # noqa: E402
import hooklib  # noqa: E402
from test_artifact_sections import isolated_lines, pretty, write  # noqa: E402  (the fixtures of the map, not a second copy)
from test_grounding_section import FIXTURE, at  # noqa: E402

DASH = "—"
SCRIPT_NAMES = ("plan_row.py", "grounding_section.py", "With a shell")
SMALL_CAP = {"read": {"max_bytes": 400}}        # the fixtures are a few KB: a low limit makes them "big" without padding
NO_LIMIT = {"read": {"max_bytes": 0}}
STRATEGIST = "qa-test-strategist"               # no Bash
CRITIC = "qa-case-critic"                       # no Bash
RUNNER = "qa-runner"                            # Bash
REPORTER = "qa-bug-reporter"                    # Bash


def padded(path: Path, size: int) -> Path:
    """A JSON file of EXACTLY `size` bytes (a config with one padding string)."""
    body = '{"pad": "' + "x" * (size - len('{"pad": ""}')) + '"}'
    return write(path, body)


def plugin_copy(where: Path, with_config_view: bool) -> Path:
    """What the guard reads of a plugin: its agents (the roles' `tools:`), a references/ folder, and whether scripts/config_view.py
    is there (SC1-8's script, absent from the plugin until it merges)."""
    (where / "agents").mkdir(parents=True)
    for role in (RUNNER, REPORTER, CRITIC, STRATEGIST):
        shutil.copy(harness.PLUGIN_ROOT / "agents" / f"{role}.md", where / "agents" / f"{role}.md")
    (where / "references").mkdir()
    (where / "scripts").mkdir()
    if with_config_view:
        (where / "scripts" / "config_view.py").write_text("# stands for SC1-8's script\n", encoding="utf-8")
    return where


class Fixture:
    """One temp project, the story QA-1 in it, and the helpers that ask the guard about a whole read."""

    def __init__(self) -> None:
        self.root = temp_project("qa-bigread-sections-")
        use_project(self.root)
        self.story = self.root / "qa-factory" / "artifacts" / "QA-1"
        self.table = write(self.story / "work" / "grounding.yaml", FIXTURE)
        self.rows = [{"id": f"TS-{i}", "meta": {"id": "inner"}, "list": [1, 2, 3][: i % 3 + 1]} for i in range(1, 8)]
        self.plan_text = pretty(self.rows, lifecycle_actions=[{"a": 1}])
        self.plan = write(self.story / "work" / "test-plan.json", self.plan_text)
        self.config = self.root / "qa-factory" / "config.json"

    def ask(self, path, cfg=None, role=None, **tool_input):
        """The text the guard refuses a Read of `path` with, or None: through `logs_check`, the call the hook makes."""
        event = {"tool_name": "Read", "session_id": "sc1-3-p3", "cwd": str(self.root),
                 "tool_input": dict({"file_path": str(path)}, **tool_input)}
        if role:
            event["agent_type"] = role
        return G._blocked(G.logs_check, event, {} if cfg is None else cfg)

    def dispatch(self, role) -> None:
        state = self.story / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "controller.json").write_text(
            '{"dispatches": {"d1": {"role": "%s", "status": "running"}}}' % role, encoding="utf-8")

    def end_dispatch(self) -> None:
        (self.story / "state" / "controller.json").unlink()


def the_maps(fx: Fixture) -> None:
    text = fx.ask(fx.table, SMALL_CAP)
    size = fx.table.stat().st_size
    prefix = f"PRE-TOOL GUARD: reading {str(fx.table).replace(chr(92), '/')} whole is blocked {DASH} it is {size:,} bytes (the limit is 400)"
    check("K19 the table read whole is refused with the old prefix", bool(text) and text.startswith(prefix), repr((text or "")[:200]))
    check_in("K19 ... and the refusal carries the map", "This file is read by section. Its map (id: lines):", text)
    check_in("K19 ... the rows with the lines of the file", f"G-1 {at('  - id: G-1')}-{at('      over two lines' + chr(34))}", text)
    check_in("K19 ... the way to read one section", "`Read` `offset=<first line>` `limit=<last line - first line + 1>`", text)
    check_in("K19 ... and that the lines move after an Edit", "after your own Edit the lines below it move", text)
    check_not_in("K19 ... the old middle is replaced, not appended", "Grep -n <what you are looking for>", text)

    text = fx.ask(fx.plan, SMALL_CAP)
    size = fx.plan.stat().st_size
    check("K20 the plan read whole is refused with the old prefix",
          bool(text) and text.startswith(f"PRE-TOOL GUARD: reading {str(fx.plan).replace(chr(92), '/')} whole is blocked {DASH} it is {size:,} bytes"),
          repr((text or "")[:200]))
    expected = [f"TS-{i + 1} {a}-{b}" for i, (a, b) in enumerate(isolated_lines(fx.plan_text, len(fx.rows)))]
    check_in("K20 ... with the map of its rows, the lines the text itself shows", "rows: " + ", ".join(expected), text)
    check_in("K20 ... and the key ranges first", "keys: rows 2-", text)


OLD_DOOR = "Read the part you need: `Read` with `offset`/`limit`, after `Grep -n <what you are looking for>"


def the_broken(fx: Fixture) -> None:
    """K21: no map, still a block, still the old text."""
    old = OLD_DOOR
    write(fx.table, FIXTURE.replace("\n  - id: G-1", "\n\t- id: G-1", 1))
    text = fx.ask(fx.table, SMALL_CAP)
    check("K21 E-5 a table the one reader refuses: still a block", bool(text) and text.startswith("PRE-TOOL GUARD: reading "), repr(text))
    check_in("K21 ... with the old text", old, text)
    check_not_in("K21 ... and no map", "Its map", text)
    write(fx.table, FIXTURE)
    broken = write(fx.story / "work" / "other" / "work" / "test-plan.json", "{not json " + "x" * 600)
    text = fx.ask(broken, SMALL_CAP)
    check("K21 E-5 a plan that is no JSON: still a block, the old text, no map",
          bool(text) and old in text and "Its map" not in text, repr(text))
    with mock.patch.object(AS, "section_map_text", side_effect=RuntimeError("boom")):
        text = fx.ask(fx.table, SMALL_CAP)
    check("K21 the map function raising does not crash the guard: the block stays, with the old text",
          bool(text) and old in text and "Its map" not in text, repr(text))
    with mock.patch.object(hooklib, "load_ref_json", side_effect=RuntimeError("boom")):
        text = fx.ask(fx.table, SMALL_CAP)
    check("K21 the registry reader raising: the same", bool(text) and old in text and "Its map" not in text, repr(text))
    with mock.patch.object(AS, "section_map_text", return_value=""):
        text = fx.ask(fx.table, SMALL_CAP)
    check("K21 an empty map is the old text", bool(text) and old in text, repr(text))


def the_unconfirmed(fx: Fixture) -> None:
    """M-2: the guard prints no map the file does not confirm."""
    old = OLD_DOOR
    original = hooklib.read_json

    def lying(path, default=None, **kw):                      # the independent parse disagrees with the bytes the spans came from
        value = original(path, default, **kw)
        if str(path).endswith("test-plan.json") and isinstance(value, dict):
            value["rows"][2]["list"] = ["not what the file says"]
        return value
    with mock.patch.object(hooklib, "read_json", lying):
        text = fx.ask(fx.plan, SMALL_CAP)
    check("M-2 a row the independent parse does not give back: the refusal has no map and reads by windows",
          bool(text) and old in text and "Its map" not in text, repr(text))
    check_in("K19/20 the control: the same file, honestly read, has its map", "Its map", fx.ask(fx.plan, SMALL_CAP))


def the_passes(fx: Fixture, template: Path) -> None:
    built = []
    real = AS.section_map_text

    def counting(*args, **kw):
        built.append(args)
        return real(*args, **kw)
    with mock.patch.object(AS, "section_map_text", counting):
        for label, got in (
            ("a range read (offset)", fx.ask(fx.table, SMALL_CAP, offset=1)),
            ("a range read (limit)", fx.ask(fx.table, SMALL_CAP, limit=50)),
            ("the table under the default limit (a small file)", fx.ask(fx.table)),
            ("the plan under the default limit", fx.ask(fx.plan)),
            ("the limit off (max_bytes 0)", fx.ask(fx.table, NO_LIMIT)),
            ("an exempt place (the plugin's template)", fx.ask(template)),
            ("a path that is not there", fx.ask(fx.story / "work" / "nope.yaml", SMALL_CAP)),
        ):
            check_eq(f"K22 {label}: passes", got, None)
    check_eq("K22 ... and the map was never built for any of them", built, [])
    check("K22 the control: a whole read of the same file, over the limit, does build it",
          bool(fx.ask(fx.table, SMALL_CAP)))


def the_pdf_pages(fx: Fixture) -> None:
    """S6 1d, DR-1..DR-3 (spec 5.1): a `.pdf` over the limit is bounded by a `pages` range within `max_pdf_pages` and by nothing else
    (the tool ignored `limit` there: all 14 pages of 14 for `limit 1`); `pages` bounds nothing on another file. The error direction is
    a refusal with a door. The one reader of the range and the cap is the guard; `branch_accounting` prints by it."""
    blobs = fx.story / "work" / "blobs"
    pdf, upper, blob, png = (padded(blobs / name, 900) for name in ("d.pdf", "D.PDF", "blob", "m.png"))
    # DR-1: a range inside the limit passes, a range outside it is refused with the door `1-<N>`
    for pages in ("1-20", "3", "20-20", "5-24"):
        check_eq(f"DR-1 .pdf pages {pages!r} (at most 20 pages): passes", fx.ask(pdf, SMALL_CAP, pages=pages), None)
    for label, pages in (("1-21 (BEYOND 20 pages)", "1-21"), ("empty", ""), ("not a range", "abc"), ("reversed", "5-1"),
                         ("zero-based", "0"), ("a number, not text", 3), ("a list", [1, 2]), ("a sign", "-3"), ("a space", "1 - 3")):
        refused = fx.ask(pdf, SMALL_CAP, pages=pages)
        check(f"DR-1 .pdf pages {label}: refused, the door names the range 1-20", bool(refused) and "1-20" in refused, str(refused))
    check_in("DR-1 the refusal keeps the old prefix", "PRE-TOOL GUARD: reading", fx.ask(pdf, SMALL_CAP, pages="1-21") or "")
    check_not_in("DR-1 a PDF is not given the door of a range read by lines (the pair: another file is)", "Read the part you need",
                 fx.ask(pdf, SMALL_CAP) or "")
    check_in("DR-1 the pair: another file is", "Read the part you need", fx.ask(blob, SMALL_CAP) or "")
    # DR-2: `limit` and `offset` bound no PDF; a blob with no `.pdf` is bounded by `limit` as it was; `pages` bounds nothing there
    for label, path in (("`.pdf`", pdf), ("`.PDF`", upper)):
        check(f"DR-2 {label} with `limit 1`: refused", bool(fx.ask(path, SMALL_CAP, limit=1)))
        check(f"DR-2 {label} with `offset`: refused", bool(fx.ask(path, SMALL_CAP, offset=1)))
        check_eq(f"DR-2 {label} the pair: a range passes", fx.ask(path, SMALL_CAP, pages="1-3"), None)
    check("DR-2 a blob with no suffix and `pages 1-1`: refused (`pages` is no range on it)", bool(fx.ask(blob, SMALL_CAP, pages="1-1")))
    check_eq("DR-2 ... `pages` and `limit 3`: `limit` decides, as it did (named for the critic: spec 5.1's line on a blob)",
             fx.ask(blob, SMALL_CAP, pages="1-1", limit=3), None)
    check_eq("DR-2 a picture with `limit 1`: passes", fx.ask(png, SMALL_CAP, limit=1), None)
    check("DR-2 a picture whole: refused (the pair)", bool(fx.ask(png, SMALL_CAP)))
    check_eq("DR-2 cap 0: a PDF with no range passes", fx.ask(pdf, NO_LIMIT), None)
    check_eq("DR-2 a small PDF passes with no range", fx.ask(padded(blobs / "small.pdf", 100), SMALL_CAP), None)
    # the cap: `max_pdf_pages` is the one reader, a bad value is the default (AR-3)
    for value, wanted in ((20, 20), (1, 1), (0, 20), (-1, 20), ("x", 20), (None, 20), (True, 20), (2.5, 20)):
        check_eq(f"DR-3 big_read_pages({value!r})", G.big_read_pages({"read": {"max_pdf_pages": value}}), wanted)
    check_eq("DR-3 big_read_pages(no config / not an object)", (G.big_read_pages({}), G.big_read_pages(None), G.big_read_pages({"read": 3})), (20, 20, 20))
    # DR-3: the listing prints the call the guard lets through (AT the limit and BEYOND it), at the default and at 1 page
    inventory = {"schema_version": 1, "sources": [{"source_id": "SRC-QA-1", "canonical_ref": "https://jira.example/browse/QA-1", "relation": "task",
                                                  "relevance": "relevant", "status": "read",
                                                  "materials": {"attachments": {"count": 1, "status": "read", "items": [
                                                      {"attachment_id": "d", "filename": "d.pdf", "media_type": "application/pdf",
                                                       "status": "read", "local_ref": "blobs/d.pdf"}]}}}]}
    (fx.story / "work" / "source-inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    for pages_cap in (20, 1):
        cfg = {"read": {"max_bytes": 400, "max_pdf_pages": pages_cap}}
        fx.config.write_text(json.dumps(cfg), encoding="utf-8")
        printed = BA.attachment_lines(fx.story)[0]
        call = re.search(r"open: Read (.+) pages (\S+)$", printed)
        check(f"DR-3 max_pdf_pages {pages_cap}: the listing prints `pages 1-{pages_cap}`", bool(call) and call.group(2) == f"1-{pages_cap}", printed)
        check_eq(f"DR-3 max_pdf_pages {pages_cap}: the printed call passes the guard as printed (AT)",
                 fx.ask(call.group(1), cfg, pages=call.group(2)), None)
        check(f"DR-3 max_pdf_pages {pages_cap}: one page more is refused (BEYOND)",
              bool(fx.ask(call.group(1), cfg, pages=f"1-{pages_cap + 1}")))
    fx.config.unlink()


def the_doors(fx: Fixture) -> None:
    for role in (STRATEGIST, CRITIC):
        for what, path in (("the table", fx.table), ("the plan", fx.plan)):
            text = fx.ask(path, SMALL_CAP, role=role)
            check(f"K23 {role} (no Bash), {what}: the map is there", "Its map" in (text or ""), repr(text))
            for name in SCRIPT_NAMES:
                check_not_in(f"K23 ... and `{name}` is not named", name, text)
    text = fx.ask(fx.table, SMALL_CAP, role=RUNNER)
    check_in("K24 a role with Bash, the table: the command line", 'grounding_section.py" --task QA-1 --show <id> [--show ...] | --requirement <R-n>', text)
    check_in("K24 ... and the map too", "Its map", text)
    text = fx.ask(fx.plan, SMALL_CAP, role=RUNNER)
    check_in("K24 a role with Bash, the plan: the command line", 'plan_row.py" --task QA-1 --show --row <TS-n> [--row ...]', text)
    text = fx.ask(fx.table, SMALL_CAP)
    check_in("K24 the conductor (no role, no running dispatch): the command line", "grounding_section.py", text)
    text = fx.ask(fx.plan, SMALL_CAP)
    check_in("K24 ... for the plan too", "plan_row.py", text)
    fx.dispatch(STRATEGIST)
    try:
        text = fx.ask(fx.plan, SMALL_CAP)
        check("K24 m-5 the conductor while a strategist dispatch runs gets the no-shell text (the safe direction)",
              "Its map" in (text or "") and "plan_row.py" not in text, repr(text))
    finally:
        fx.end_dispatch()


def the_registry(fx: Fixture) -> None:
    real = hooklib.load_ref_json("artifact-writers.json")
    check("K25 the shipped registry names both files",
          [real["artifacts"][k].get("read_by_section") for k in ("work/grounding.yaml", "work/test-plan.json")] == ["grounding", "plan_rows"])
    check("K25 ... and plan_row.py is the plan's machinery, the two readers are nobody's co-writer",
          "plan_row.py" in real["artifacts"]["work/test-plan.json"]["machinery"]
          and not {"artifact_sections.py", "grounding_section.py"} & {m for e in real["artifacts"].values() for m in e.get("machinery", [])})
    older = {"artifacts": {k: {f: v for f, v in e.items() if f != "read_by_section"} for k, e in real["artifacts"].items()}}
    with mock.patch.object(hooklib, "load_ref_json", return_value=older):
        text = fx.ask(fx.table, SMALL_CAP)
    check("K25 E-10 a registry without `read_by_section`: the old text, no map",
          bool(text) and "Grep -n <what you are looking for>" in text and "Its map" not in text, repr(text))
    with mock.patch.object(hooklib, "load_ref_json", return_value={}):
        text = fx.ask(fx.plan, SMALL_CAP)
    check("K25 ... and with no registry at all", bool(text) and "Its map" not in text, repr(text))


def the_forms() -> None:
    phases = harness.PLUGIN_ROOT / "skills" / "qa-story" / "phases"
    s3 = (phases / "s3.md").read_text(encoding="utf-8")
    s4 = (phases / "s4.md").read_text(encoding="utf-8")
    check_in("K26 s3.md: the files are read by section", "read by section", s3)
    check_in("K26 s3.md: a section is changed whole", "in one `Edit`", s3)
    check_in("K26 s3.md names both files", "`work/grounding.yaml` and `work/test-plan.json` are read by section", s3)
    check_in("K26 s4.md: the plan is read by section", "`work/test-plan.json` is read by section", s4)
    if os.environ.get("T028_NEGATIVE_CONTROL"):
        check_in("negative control: a key that is not in the text", "this phrase is in no phase file", s3)


def exact_places(fx: Fixture, plugin: Path) -> None:
    """B-2: each exemption passes when big, and what only LOOKS like it is refused."""
    big = "x" * 900

    def put(path: Path) -> Path:
        return write(path, big)
    root = fx.root
    exempt = {
        "the plugin's references/ (any file below it)": put(plugin / "references" / "templates" / "big.md"),
        "the project's .claude/": put(root / ".claude" / "agents" / "big.md"),
        "the project's CLAUDE.md": put(root / "CLAUDE.md"),
        "the project's AGENTS.md": put(root / "AGENTS.md"),
        "the readiness report (state/)": put(root / "qa-factory" / "state" / "readiness.json"),
        "the readiness report (beside the config, the layout before)": put(root / "qa-factory" / "readiness.json"),
        "a story's pipeline.json": put(fx.story / "pipeline.json"),
        "a story's requirements-readiness.json": put(fx.story / "work" / "requirements-readiness.json"),
    }
    with mock.patch.object(G, "PLUGIN_ROOT", plugin):
        for label, path in exempt.items():
            check_eq(f"B-2 {label}: read whole when big", fx.ask(path, SMALL_CAP), None)
        lookalikes = {
            "a product's templates/ folder": put(root / "src" / "testproject1" / "templates" / "agents" / "core_prompts.py"),
            "a templates/ folder that is not the plugin's": put(root / "templates" / "retro.md"),
            "a CLAUDE.md below the root": put(root / "docs" / "CLAUDE.md"),
            "a .claude/ folder that is not the project's": put(root / "docs" / ".claude" / "big.md"),
            "tsconfig.json": put(root / "tsconfig.json"),
            "a config.json that is not the project's": put(root / "service" / "config.json"),
            "pipeline.json outside a story": put(root / "pipeline.json"),
            "pipeline.json deeper in a story": put(fx.story / "work" / "pipeline.json"),
            "a readiness.json of a story's work folder": put(fx.story / "work" / "readiness.json"),
            "a references/ folder that is not the plugin's": put(root / "references" / "big.md"),
        }
        for label, path in lookalikes.items():
            text = fx.ask(path, SMALL_CAP)
            check(f"B-2 {label}: refused when big", bool(text) and text.startswith("PRE-TOOL GUARD: reading "), repr(text))
            check_not_in(f"B-2 {label}: and it gets the generic door, not the config's", "project config", text)
        check_eq("B-2 the same look-alikes are not refused while small (the size check comes first)",
                 [fx.ask(p, {"read": {"max_bytes": 5000}}) for p in lookalikes.values()], [None] * len(lookalikes))


PHASES = (("qa-story", "s0.md"), ("qa-onboarding", "p2-interview.md"), ("qa-onboarding", "p4-generate.md"))


def the_plugin_skills(fx: Fixture, work: Path) -> None:
    """B-1 (t-1333): the phase files SKILL.md says to read whole stay readable whole - in an installed plugin AND in a
    `--plugin-dir` one - while a `skills/` folder of the project is refused. The real files, the default limit: they are 31-50 KB."""
    installed = plugin_copy(work / "home" / ".claude" / "plugins" / "cache" / "mkt" / "qa-factory" / "0.10.3", with_config_view=False)
    direct = plugin_copy(work / "plugin-dir-layout", with_config_view=False)
    for plugin, layout in ((installed, "installed (~/.claude/plugins/cache/...)"), (direct, "--plugin-dir (no .claude/ in the path)")):
        with mock.patch.object(G, "PLUGIN_ROOT", plugin):
            for skill, name in PHASES:
                copy = plugin / "skills" / skill / "phases" / name
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(harness.PLUGIN_ROOT / "skills" / skill / "phases" / name, copy)
                check(f"B-1 the copy of {name} is over the default limit ({copy.stat().st_size:,} B > 30,000)", copy.stat().st_size > 30000)
                check_eq(f"B-1 {layout}: {skill}/phases/{name} is read whole", fx.ask(copy), None)
            # the look-alikes: the PROJECT's skills/ folder (same files), and a sibling of the plugin's skills/ that only starts with it
            theirs = fx.root / "skills" / "qa-story" / "phases" / "s0.md"
            theirs.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(harness.PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s0.md", theirs)
            sibling = plugin / "skills-copy" / "s0.md"
            sibling.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(theirs, sibling)
            for label, path in (("a skills/ folder of the project", theirs), ("a folder beside the plugin's skills/ that only starts with it", sibling)):
                text = fx.ask(path)
                check(f"B-1 {layout}: {label} is refused when big", bool(text) and text.startswith("PRE-TOOL GUARD: reading "), repr(text))


def the_exemption_errors(fx: Fixture, plugin: Path) -> None:
    """F-1: the directory entries go through `runtime_paths.contained`, and a name that only starts like the place is not inside it.
    F-2: the error direction of `_big_read_exempt` - a layout that cannot be resolved is NOT exempt, so the refusal (with its door) stays."""
    import runtime_paths as RP
    inside = write(plugin / "references" / "templates" / "big2.md", "x" * 900)
    prefix_only = write(plugin / "references-old" / "big.md", "x" * 900)
    dot_prefix = write(fx.root / ".claude-old" / "big.md", "x" * 900)
    with mock.patch.object(G, "PLUGIN_ROOT", plugin):
        check_eq("F-1 a file inside references/ passes", fx.ask(inside, SMALL_CAP), None)
        for label, path in (("references-old/ (starts with `references`)", prefix_only), (".claude-old/ (starts with `.claude`)", dot_prefix)):
            text = fx.ask(path, SMALL_CAP)
            check(f"F-1 {label}: not inside, refused", bool(text) and text.startswith("PRE-TOOL GUARD: reading "), repr(text))
        with mock.patch.object(RP, "contained", return_value=False) as asked:
            text = fx.ask(inside, SMALL_CAP)
        check("F-1 the verdict on a directory is `runtime_paths.contained`'s: when it says no, the file is refused",
              bool(text) and text.startswith("PRE-TOOL GUARD: reading ") and asked.called, repr(text))
    # F-2: a big story pipeline.json is exempt while the artifact root resolves, and refused when it raises
    pipeline = write(fx.story / "pipeline.json", "x" * 900)
    check_eq("F-2 the control: the story's pipeline.json is read whole while the artifact root resolves", fx.ask(pipeline, SMALL_CAP), None)
    config = fx.root / "qa-factory" / "config.json"
    before = config.read_text(encoding="utf-8") if config.exists() else None
    try:
        write(config, '{"artifact_root": ""}')           # hooklib.artifact_root raises ValueError on it
        text = fx.ask(pipeline, SMALL_CAP)
        check("F-2 an artifact_root that raises: not exempt, the pipeline.json is refused (with its door), the guard does not crash",
              bool(text) and text.startswith("PRE-TOOL GUARD: reading ") and OLD_DOOR in text, repr(text))
    finally:
        if before is None:
            config.unlink()
        else:
            write(config, before)
    check_eq("F-2 ... and the same file passes again once the root resolves", fx.ask(pipeline, SMALL_CAP), None)


def the_plugin_read(work: Path) -> None:
    """Q-B: `plugin_read_check` asks `runtime_paths.contained` too: a folder that only starts like the plugin's name is outside it."""
    plugin = plugin_copy(work / "plugin-pr", with_config_view=False)
    (plugin / "references" / "templates").mkdir()
    old = plugin_copy(work / "plugin-pr-old", with_config_view=False)

    def asks(path, tool="Read"):
        key = "path" if tool == "Grep" else "file_path"
        event = {"tool_name": tool, "agent_id": "a301712c46df18269", "agent_type": "qa-factory:qa-automator",
                 "tool_input": {key: str(path), "pattern": "x"}}
        return G._blocked(G.plugin_read_check, event, {})
    with mock.patch.object(G, "PLUGIN_ROOT", plugin):
        text = asks(plugin / "scripts" / "run_suite.py")
        check("Q-B the control: a role's Read inside the plugin's scripts/ is refused",
              bool(text) and "inside the plugin is refused for a role" in text, repr(text))
        check_eq("Q-B a role's Read inside the plugin's references/ passes", asks(plugin / "references" / "templates" / "a.md"), None)
        check_eq("Q-B ... and a Grep over the references/ directory itself (no trailing slash)", asks(plugin / "references", "Grep"), None)
        check_eq("Q-B a folder that only starts with the plugin's name is outside it: passes", asks(old / "scripts" / "run_suite.py"), None)
        text = asks(plugin / "references-old" / "a.md")
        check("Q-B ... and references-old/ inside the plugin is not references/: refused",
              bool(text) and "inside the plugin is refused for a role" in text, repr(text))


def the_registry_reads(fx: Fixture) -> None:
    """Q-A: `owned_artifacts` and `artifact_rewrite_check` read the registry through `hooklib.load_ref_json`. An answer that is
    empty or no registry gives `owned_artifacts` its floor (`OWNED_ARTIFACTS`) and the rewrite check no opinion - never a crash."""
    real_owned = G.owned_artifacts()
    check("Q-A the control: the shipped registry gives more than the floor", real_owned != G.OWNED_ARTIFACTS and len(real_owned) > 0,
          f"{len(real_owned)} vs {len(G.OWNED_ARTIFACTS)}")
    target = write(fx.story / "work" / "understanding.md", "# understanding\nsome text\n")
    event = {"tool_name": "Write", "session_id": "sc1-3-p3", "cwd": str(fx.root), "tool_input": {"file_path": str(target)}}
    said = G._blocked(G.artifact_rewrite_check, event, {})
    check("Q-A the control: a Write over an existing understanding.md is refused by the registry's `rewrite`",
          bool(said) and "already exists" in said, repr(said))
    answers = (
        ("an empty answer (a missing or broken file)", {"return_value": {}}),
        ("a registry that is not an object", {"return_value": ["artifacts"]}),
        ("`artifacts` that is not an object", {"return_value": {"artifacts": ["x"]}}),
        ("a reader that raises", {"side_effect": RuntimeError("boom")}),
    )
    for label, kwargs in answers:
        with mock.patch.object(hooklib, "load_ref_json", **kwargs):
            owned = G.owned_artifacts()
            rewrite = G._blocked(G.artifact_rewrite_check, event, {})
        check_eq(f"Q-A {label}: owned_artifacts falls back to OWNED_ARTIFACTS", owned, dict(G.OWNED_ARTIFACTS))
        check_eq(f"Q-A {label}: the rewrite check has no opinion", rewrite, None)


def the_template_trap(fx: Fixture, template: Path) -> None:
    size = template.stat().st_size
    check(f"B-2 the trap: the plugin's own template config.json is over the default limit ({size:,} B > 30,000)", size > 30000)
    check_eq("B-2 ... and it is still read whole (an exact place under the plugin's references/)", fx.ask(template), None)


def the_project_config(fx: Fixture, plugin_a: Path, plugin_b: Path) -> None:
    prefix = "PRE-TOOL GUARD: reading "
    key_door = "This is the project config: it is read by key, not whole. `Grep -n \"<the key>\" "
    for size in (1, 29999, 30000):
        padded(fx.config, size)
        check_eq(f"M-6 a project config of {size:,} bytes is never refused", fx.ask(fx.config), None)
    padded(fx.config, 30001)
    text = fx.ask(fx.config)
    check("M-6 30,001 bytes: refused with the old prefix",
          bool(text) and text.startswith(prefix) and f"whole is blocked {DASH} it is 30,001 bytes (the limit is 30,000)" in text, repr((text or "")[:200]))
    check_in("M-6 ... and the key door (Grep -n, then a range read)", key_door, text)
    check_in("M-6 ... `Read` with `offset`/`limit` takes that part", "`Read` with `offset`/`limit` takes that part", text)
    check_eq("M-6 a range read of the same file passes", fx.ask(fx.config, offset=1, limit=40), None)
    root = fx.root
    spellings = [("a path with `..` in it", str(root) + "/qa-factory/../qa-factory/config.json")]
    if os.name == "nt":      # a case-blind file system: another case and backslashes are the same file
        spellings.append(("another case and backslashes", str(root).upper().replace("/", "\\") + "\\QA-Factory\\Config.json"))
    for label, spelling in spellings:
        text = fx.ask(spelling)
        check(f"M-6 {label}: the same file, refused", bool(text) and "project config" in text, repr(text))

    # TEMPORAL, world 1: the plugin has no config_view.py (a temp plugin copy; the guard reads its PLUGIN_ROOT at the call).
    # Both worlds are built here, so the keys hold before and after SC1-8 puts the script in the real plugin.
    check("M-6 world 1 is a plugin without config_view.py", not (plugin_a / "scripts" / "config_view.py").exists())
    with mock.patch.object(G, "PLUGIN_ROOT", plugin_a):
        for label, role in (("the conductor / onboarding (no role)", None), (RUNNER, RUNNER), (REPORTER, REPORTER), (CRITIC, CRITIC)):
            text = fx.ask(fx.config, role=role)
            check(f"M-6 world 1, {label}: one refusal, the key door", bool(text) and key_door in text, repr(text))
            check_not_in(f"M-6 world 1, {label}: and no script that is not there", "config_view", text)
    # TEMPORAL, world 2: the plugin has config_view.py
    with mock.patch.object(G, "PLUGIN_ROOT", plugin_b):
        for label, role in (("the conductor / onboarding (no role)", None), (RUNNER, RUNNER), (REPORTER, REPORTER)):
            text = fx.ask(fx.config, role=role)
            check(f"M-6 world 2, {label} (a shell): the key door and `config_view.py --keys`",
                  bool(text) and key_door in text and 'config_view.py" --keys' in text and "--get <key>" in text, repr(text))
        for role in (STRATEGIST, CRITIC):
            text = fx.ask(fx.config, role=role)
            check(f"M-6 world 2, {role} (no shell): the key door, no script name",
                  bool(text) and key_door in text and "config_view" not in text, repr(text))
    padded(fx.config, 29999)
    with mock.patch.object(G, "PLUGIN_ROOT", plugin_b):
        check_eq("M-6 world 2: a small config is never refused", fx.ask(fx.config), None)


PNG_HEAD = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])
# The two screenshots of the run are not committed: `synthetic_png` rebuilds a valid PNG of the same size from the recorded seed
# (fixtures/synthetic-derivations.json), so the test still reads a picture over the text limit that it has not made up by hand.
sys.path.insert(0, str(harness.FIXTURES))
import synthetic_corpus as SYN  # noqa: E402
SYN_BLOBS = {blob["name"]: blob for blob in SYN.derivations()["blobs"]}      # keyed by name: two blobs of one size cannot collapse


def syn_blob_bytes(size: int) -> bytes:
    """The rebuilt bytes of THE recorded blob of this size; two recorded blobs of one size are an error, not a silent pick."""
    found = [b for b in SYN_BLOBS.values() if b["size"] == size]
    assert len(found) == 1, f"{len(found)} recorded blobs of {size} bytes"
    return SYN.synthetic_png(found[0]["size"], found[0]["seed"])
REAL_93K = 93414      # screenshot-1.png
REAL_84K = 83997      # screenshot-3.png
PICTURE_DOOR = "This is a picture: it cannot be read in parts."


def blob_of(path: Path, head: bytes, size: int) -> Path:
    """A file of EXACTLY `size` bytes that starts with `head`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(head + b"\0" * (size - len(head)))
    return path


def the_pictures(fx: Fixture) -> None:
    """SC2-41 IM-1..IM-9, IM-g, IM-h: a picture is recognised by its first bytes and judged by its own limit, `read.max_image_bytes`
    (default 5,242,880 = the adapter's image download limit); text keeps the text limit. The branch only turns a refusal into a pass,
    and every doubt leaves the old refusal (with its door). Mutations (named, run by the integrator, one killing file - this one):
      m71 the picture branch ignores the image cap (any picture passes)      -> IM-4
      m72 `_is_picture` decides by suffix                                      -> IM-1 (no suffix), IM-2
      m73 `size <= image_cap` becomes `<`                                      -> IM-4
      m74 `big_read_image_cap` accepts 0 / a bool                              -> IM-6
      m75 `_is_picture` returns True on an exception                           -> IM-8"""
    blobs = fx.story / "work" / "blobs"
    # IM-1: the recorded screenshots (rebuilt synthetic PNGs of the real sizes), with NO suffix (live blobs have none), under the default config
    for label, size in (("screenshot-1 (93,414 B)", REAL_93K), ("screenshot-3 (83,997 B)", REAL_84K)):
        copy = blobs / f"im1-{size}"
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(syn_blob_bytes(size))
        check(f"IM-1 the recorded blob is over the text limit ({copy.stat().st_size:,} B > 30,000)", copy.stat().st_size > G.big_read_cap({}))
        check_eq(f"IM-1 {label}, no suffix, default config: a whole Read passes", fx.ask(copy), None)
    # IM-2: the signature decides, not the suffix; IM-3: a text file of the same size is refused as before
    fake = blob_of(blobs / "shot.png", b"not a pic", 93414)
    text = fx.ask(fake)
    check("IM-2 93,414 B named .png whose first bytes are not a picture: refused with the generic door",
          bool(text) and "Read the part you need" in text and PICTURE_DOOR not in text, repr(text))
    check("IM-3 a text file of 93,414 B: refused as before (the text economy is unchanged)",
          bool(fx.ask(padded(blobs / "big.json", 93414))))
    check_in("IM-3 ... with the generic door", "Read the part you need", fx.ask(blob_of(blobs / "t.txt", b"hello", 93414)) or "")
    # IM-4: AT and BEYOND the image limit
    cfg = {"read": {"max_bytes": 400, "max_image_bytes": 1000}}
    check_eq("IM-4 a PNG of exactly 1,000 B (the image limit) passes", fx.ask(blob_of(blobs / "p1000", PNG_HEAD, 1000), cfg), None)
    text = fx.ask(blob_of(blobs / "p1001", PNG_HEAD, 1001), cfg)
    check("IM-4 one byte over: refused with the picture door and the image limit in the prefix",
          bool(text) and PICTURE_DOOR in text and "it is 1,001 bytes (the limit is 1,000" in text and text.startswith("PRE-TOOL GUARD: reading "),
          repr(text))
    check_not_in("IM-4 ... and Grep -n is not the way forward", "Grep -n <what", text or "")
    check_eq("IM-4 a range read of the same picture still passes (the known loophole, unchanged)", fx.ask(blobs / "p1001", cfg, limit=1), None)
    # IM-5: an image limit below the text limit only widens, never refuses what the text rule passes
    low = {"read": {"max_bytes": 1000, "max_image_bytes": 10}}
    check_eq("IM-5 max_image_bytes < max_bytes: a 900 B picture passes", fx.ask(blob_of(blobs / "p900", PNG_HEAD, 900), low), None)
    check_eq("IM-5 ... and a 1,000 B one (the text limit)", fx.ask(blob_of(blobs / "p1000b", PNG_HEAD, 1000), low), None)
    text = fx.ask(blob_of(blobs / "p1001b", PNG_HEAD, 1001), low)
    check("IM-5 ... one byte over the text limit is refused, and the limit named is the larger one (1,000)",
          bool(text) and PICTURE_DOOR in text and "(the limit is 1,000" in text, repr(text))
    # IM-6: the one reader of the key; a bad value is the default, never "off"
    for value in ({}, None, {"read": 3}, 0, -1, "x", True, 2.5):
        cfg_bad = value if value in ({}, None) or isinstance(value, dict) else {"read": {"max_image_bytes": value}}
        check_eq(f"IM-6 big_read_image_cap({value!r}) is the default", G.big_read_image_cap(cfg_bad), 5242880)
    check_eq("IM-6 a positive whole number is taken", G.big_read_image_cap({"read": {"max_image_bytes": 7}}), 7)
    check_eq("IM-6 a config that is not an object", G.big_read_image_cap([1]), 5242880)
    # IM-7: the guard off (max_bytes 0) passes a picture of any size with no sniff
    with mock.patch.object(G, "_is_picture", side_effect=RuntimeError("must not be asked")) as sniff:
        check_eq("IM-7 max_bytes 0: a big picture passes", fx.ask(copy, NO_LIMIT), None)
        check_eq("IM-7 a small file passes", fx.ask(padded(blobs / "tiny.json", 100)), None)
        check_eq("IM-7 ... and a range read passes", fx.ask(fake, SMALL_CAP, limit=3), None)
        check_eq("IM-7 ... with no sniff in any of them", sniff.called, False)
    # IM-8: an unreadable signature table is "not a picture": the old refusal, nothing raises
    with mock.patch.object(BA, "picture_signatures", side_effect=BA.Unreadable("table damaged")):
        text = fx.ask(blobs / f"im1-{REAL_93K}")
    check("IM-8 the table unreadable: a real 93,414 B picture is refused with the generic door, the hook does not raise",
          bool(text) and "Read the part you need" in text and PICTURE_DOOR not in text, repr(text))
    with mock.patch.object(BA, "picture_signatures", side_effect=ImportError("gone")):
        check("IM-8 ... the same for any error of the reader", bool(fx.ask(blobs / f"im1-{REAL_93K}")))
    with mock.patch("builtins.open", side_effect=OSError("locked")):
        check("IM-8 a file that cannot be opened for the sniff (raced away, locked): `_is_picture` is False",
              G._is_picture(str(blobs / f"im1-{REAL_93K}")) is False)
    # IM-9: every signature row passes; a partial match, a short file and a non-picture do not
    for name, head in (("png", PNG_HEAD), ("jpeg", bytes([0xFF, 0xD8, 0xFF, 0xE0])), ("gif87a", b"GIF87a"), ("gif89a", b"GIF89a"),
                       ("webp", b"RIFF" + bytes(4) + b"WEBP")):
        check_eq(f"IM-9 {name} on a 2,000 B file under max_bytes 400: passes", fx.ask(blob_of(blobs / f"s-{name}", head, 2000), SMALL_CAP), None)
    check("IM-9 RIFF whose bytes 8-11 are not WEBP: refused", bool(fx.ask(blob_of(blobs / "riff", b"RIFF" + bytes(4) + b"WAVE", 2000), SMALL_CAP)))
    check("IM-9 a file shorter than any signature (3 B under max_bytes 1): refused",
          bool(fx.ask(blob_of(blobs / "short", PNG_HEAD[:3], 3), {"read": {"max_bytes": 1}})))
    for name, head in (("bmp", b"BM"), ("zip", b"PK\x03\x04"), ("tiff", b"II*\0"), ("svg", b"<svg xmlns"), ("pdf-blob", b"%PDF-1.4")):
        check(f"IM-9 {name}: not a listed picture, refused", bool(fx.ask(blob_of(blobs / f"n-{name}", head, 2000), SMALL_CAP)))
    check_eq("IM-9 an empty file passes at the first check (never reaches the sniff)", fx.ask(blob_of(blobs / "empty", b"", 0), SMALL_CAP), None)
    # IM-g: the door of a refused picture is opened by a test (FR-2)
    big = blob_of(blobs / "huge", PNG_HEAD, 1001)
    text = fx.ask(big, cfg, role="qa-scout")
    check("IM-g a role with a shell: the door names ticket_adapter.py inspect with cause too_large, not Grep -n",
          bool(text) and "ticket_adapter.py" in text and " inspect " in text and "--reason" in text and "too_large" in text
          and "Grep -n" not in text and "diff_pass" not in text and "--inspection-status unavailable" in text, repr(text))
    line = re.search(r"ticket_adapter\.py\" (inspect .*)$", text or "", re.M)
    check("IM-g the line is there to be run", bool(line), repr(text))
    if line:
        inventory = {"schema_version": 1, "sources": [{"source_id": "SRC-im", "canonical_ref": "https://jira.example.invalid/browse/IM-1",
                                                       "required": True, "relation": "task", "status": "read", "relevance": "relevant",
                                                       "inspection_status": "pending", "materials": {"attachments": {"status": "read", "count": 1, "items": [
                                                           {"attachment_id": "s1", "filename": "shot.png", "size": 1001, "status": "read",
                                                            "analysis_status": "pending"}]}}}]}
        target = fx.story / "work" / "im-inventory.json"
        target.write_text(json.dumps(inventory), encoding="utf-8")
        printed = line.group(1)
        for placeholder, value in (("<work/source-inventory.json>", target.as_posix()), ("<source id>", "SRC-im"), ("<attachment id>", "s1"),
                                   ("<path of the evidence you wrote>", "work/evidence-s1.md")):
            check_in(f"IM-g the printed line carries the placeholder {placeholder}", placeholder, printed)
            printed = printed.replace(placeholder, value)
        proc = harness.run_script("ticket_adapter.py", *shlex.split(printed))
        check_eq("IM-g the printed line, run as printed (placeholders filled), exits 0", (proc.returncode, proc.stderr[-300:]), (0, ""))
        row = json.loads(target.read_text(encoding="utf-8"))["sources"][0]["materials"]["attachments"]["items"][0]
        check_eq("IM-g ... and records the picture as unread with cause too_large", (row["analysis_status"], row.get("analysis_cause")),
                 ("unavailable", "too_large"))
    text = fx.ask(big, cfg, role=STRATEGIST)
    check("IM-g a role without a shell is named no script and told to name it in its findings",
          bool(text) and PICTURE_DOOR in text and "ticket_adapter" not in text and "With a shell" not in text
          and "findings" in text, repr(text))
    # IM-h: the guard's default equals the adapter's image download limit (the sibling pin: downloaded means readable)
    import ticket_light
    rules = ticket_light.load_fields_table()["attachment_policy"]["rules"]
    check_eq("IM-h DEFAULT_IMAGE_READ_BYTES equals the `image` rule's max_bytes of jira-fields.json",
             G.DEFAULT_IMAGE_READ_BYTES, next(r["max_bytes"] for r in rules if r.get("class") == "image"))
    check_eq("IM-h ... and the signature table gives the five formats of the `limit_1` suffixes", len(BA.picture_signatures()), 5)


def main() -> None:
    fx = Fixture()
    work = temp_dir("qa-bigread-plugin-")
    try:
        plugin_a = plugin_copy(work / "plugin-a", with_config_view=False)
        plugin_b = plugin_copy(work / "plugin-b", with_config_view=True)
        template = harness.PLUGIN_ROOT / "references" / "templates" / "config.json"
        with mock.patch.object(hooklib, "session_has_factory_activity", lambda *a, **k: True):   # the calls are a role's: in the guard's scope
            the_maps(fx)
            the_broken(fx)
            the_unconfirmed(fx)
            the_passes(fx, template)
            the_pdf_pages(fx)
            the_pictures(fx)
            the_doors(fx)
            the_registry(fx)
            the_forms()
            exact_places(fx, plugin_b)
            the_plugin_skills(fx, work)
            the_exemption_errors(fx, plugin_b)
            the_plugin_read(work)
            the_registry_reads(fx)
            the_template_trap(fx, template)
            the_project_config(fx, plugin_a, plugin_b)
    finally:
        cleanup(fx.root)
        cleanup(work)
    finish("test_guard_big_read_sections")


if __name__ == "__main__":
    main()
