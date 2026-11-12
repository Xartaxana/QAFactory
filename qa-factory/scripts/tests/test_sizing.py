"""the story's size is computed by code, weighted per requirement by impact class.

Two real-data fixtures carry the actual weight: `fixtures/sizing-15045` is an unmodified copy
of TP1-15045's `requirements-register.md`, `context-manifest.json` and
`strategy/test-strategy.md` — the story whose register said "14 testable requirements" while
the old formula used 12, with no multiplier anywhere in the project's config to plug in.
`fixtures/sizing-15045-weighted` is the same story with a hand-added `impact` column (one
reasonable class per requirement, chosen from the register's own text — P0 for the two
persistence/no-write invariants and the two access-control facts, P1 for the regression and
contract requirements, P2 for default UI behavior, P3 for the three border-color cosmetics),
proving the module actually separates a P0 fact from a P3 fact sitting three rows apart in the
same register, which one multiplier for the whole story cannot do.
"""
import contextlib
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, FIXTURES, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, install_artifacts, run_script, temp_dir, temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))
import contract as C  # noqa: E402
import stage_done  # noqa: E402
import sizing  # noqa: E402
import sizing as S  # noqa: E402

REGISTER_HEAD = ("## Register\n\n"
                 "| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable |\n"
                 "|---|---|---|---|---|---|---|\n")
REGISTER_HEAD_IMPACT = ("## Register\n\n"
                        "| R | Requirement (one verifiable statement) | source | derived_from | verifiable | ac_ref | observable | impact |\n"
                        "|---|---|---|---|---|---|---|---|\n")


def write_sized_task(project: Path, name: str, rows: str, *, config_text: str = "{}", strategy_text=None,
                     head: str = REGISTER_HEAD) -> Path:
    """The files `sizing.compute` reads inside a temp project, in one place: the project's config JSON text, the strategy text
    (None: no strategy file at all) and `work/requirements-register.md` = `head` + `rows` under the task `name`. Returns the task
    folder. The caller owns the temp project and its cleanup (try/finally stays at the call site)."""
    (project / "qa-factory" / "config.json").write_text(config_text, encoding="utf-8")
    if strategy_text is not None:
        (project / "qa-factory" / "strategy").mkdir(parents=True, exist_ok=True)
        (project / "qa-factory" / "strategy" / "test-strategy.md").write_text(strategy_text, encoding="utf-8")
    task = project / "qa-factory" / "artifacts" / name
    (task / "work").mkdir(parents=True, exist_ok=True)
    (task / "work" / "requirements-register.md").write_text(head + rows, encoding="utf-8")
    return task


def main() -> int:
    # --- real data: TP1-15045 as the register stands today, no impact column ---
    project_15045 = FIXTURES / "sizing-15045" / "qa-factory"
    task_15045 = project_15045 / "stories" / "TP1-15045"
    result = sizing.compute(task_15045, project_15045.parent)

    check_eq("15045: 14 of 15 register rows count as verifiable", result["verifiable_count"], 14)
    check_eq("15045: R-15 is the one excluded (no verifiable AND no observable)",
             [u["r"] for u in result["unverifiable"]], ["R-15"])
    check_eq("15045: R-15's reason names both grounds",
             result["unverifiable"][0]["reason"], "verifiable: no; observable: none")
    check("15045: no impact column -> every requirement weight 1.0 or the surfaces "
          "escalation to 1.3, nothing higher",
          all(r["weight"] in (1.0, 1.3) for r in result["requirements"]))
    check_in("15045: the missing impact column is named, not silently defaulted",
             "no 'impact' column", result["reasoning"])
    check_eq("15045: config.impact_scale IS readable (project root auto-discovered from "
             "task_root)", any("no readable qa-factory/config.json" in l
                               for l in result["reasoning"]), False)

    by_r = {r["r"]: r for r in result["requirements"]}
    check_eq("15045: R-9 (AC-7, restore-validate) is the one requirement whose own check "
             "crosses UI/API", by_r["R-9"]["signal"], "surfaces:api-ui")
    check_eq("15045: R-9 steps up P2 -> P1 from the surfaces signal",
             (by_r["R-9"]["escalated_from"], by_r["R-9"]["escalated_to"]), ("P2", "P1"))
    check_eq("15045: every other requirement is untouched by the surfaces signal",
             [r["r"] for r in result["requirements"] if r["signal"]], ["R-9"])
    check_in("15045: the two implementation repos are noted, not weighted",
             "multi-repo change (2 repos: testproject1-backend, testproject1-ui)", result["reasoning"])

    # 13 requirements x 2.0 + R-9 at 2.6 = 28.6 -> floor 28; XL cap is 28, so no overage —
    # a bigger, honest number than the role's own "L" on this story (understanding.md said
    # size L against a formula that used 12 requirements while the register carried 14).
    # OH3-34 (critic B-1): an area names a surface ONLY through a path token; a kind word can only filter a path match. Of the fixture
    # strategy's nine P1 areas only "datasource create/index/query" holds a path-like token (a prose slash-list, m-4) and no row's
    # observable lies on it; "API integrations (GitLab, Jira, Confluence, MCP)" holds only the kind word `api`, which names where the
    # story's diff is, not a product area. So no row is placed in an area, nothing is bumped, and the budget is the old
    # 13 x 2.0 + R-9 at 2.6 (its own surfaces signal) = 28.6 -> 28: ('XL', 28, 0). The kind-word rule gave 30 / XXL / 2 by bumping
    # R-10..R-12 (the `/validate` dry-run, which is no integration). Derived from the rule, re-measured by the critic.
    check_eq("15045: no P1 area names a path any row is on, so no row is placed in an area",
             [r["r"] for r in result["requirements"] if r["area_match"]], [])
    check_eq("15045: computed budget with no area bump", result["computed_budget"], 28)
    check_eq("15045: XL, ceiling 28, no overage", (result["size"], result["cap"], result["overage"]), ("XL", 28, 0))
    check_eq("15045: eight of the nine P1 areas are said to name no surface (FR-41)",
             sum(1 for l in result["reasoning"] if l.startswith("P1 area «") and l.endswith("names no surface — no bump")), 8)
    check_eq("15045: sizing.json records the areas' state: read, one named, eight left to the role (B-2)",
             (result["areas"]["state"], result["areas"]["register_read"], len(result["areas"]["named"]), len(result["areas"]["no_surface"])),
             ("areas", True, 1, 8))

    # run() WRITES work/sizing.json, so it never runs against the tracked fixture directly
    # (harness.py's own GOOD/BAD workspace exists for the same reason) — a private copy first.
    project = temp_project()
    try:
        task = install_artifacts(project, task_15045, "TP1-15045")
        on_disk_only = sizing.run(task, project)
        written = json.loads((task / "work" / "sizing.json").read_text(encoding="utf-8"))
        check_eq("15045: run() writes work/sizing.json with the same computed_budget",
                 written["computed_budget"], on_disk_only["computed_budget"])
        # the private copy carries the register and manifest but no strategy file, so no area bump: the old 28.6 -> 28
        check_eq("15045: run() against a private copy without the strategy file sizes without the area bump",
                 on_disk_only["computed_budget"], 28)
        check_eq("15045: ... and records that the strategy was absent (an unknown, not 'no area matched')",
                 written["areas"], {"state": "no_file", "register_read": True, "named": [], "no_surface": []})
    finally:
        cleanup(project)

    # --- the same story, weighted: an impact column added by hand, one class per row ---
    project_weighted = FIXTURES / "sizing-15045-weighted" / "qa-factory"
    task_weighted = project_weighted / "stories" / "TP1-15045"
    weighted = sizing.compute(task_weighted, project_weighted.parent)
    by_r = {r["r"]: r for r in weighted["requirements"]}

    check_eq("weighted: a data-loss requirement gets the P0 weight",
             by_r["R-9"]["weight"], 1.6)
    check_eq("weighted: a cosmetic requirement gets the P3 weight",
             by_r["R-3"]["weight"], 0.6)
    check_eq("weighted: an access requirement gets the P0 weight",
             by_r["R-14"]["weight"], 1.6)
    check_eq("weighted: a P0 requirement whose own check also crosses UI/API is not "
             "escalated further (already at the top tier)",
             by_r["R-9"]["escalated_to"], None)
    # 6 rows x1.0 + 3 rows x0.6 + 5 rows x1.3 + 3 rows x1.6... — the exact arithmetic is
    # spelled out per row in the file; the assertion here is the shape it produces, not a
    # transcription of the sum, so this test breaks if the per-tier weight table changes,
    # not if someone re-derives the same total a different way.
    check("weighted: mixing P0 and P3 requirements produces a bigger budget than "
          "weighing every requirement the same",
          weighted["computed_budget"] > result["computed_budget"])
    check_eq("weighted: the heavier mix pushes the story past the XL cap",
             weighted["size"], "XXL")
    check("weighted: XXL still says what the person may do rather than blocking (the word passes it; no 'decompos')",
          any("Your word tests it as one story" in l and "decompos" not in l for l in weighted["reasoning"]))
    check("weighted: overage is shown, never silently trimmed",
          weighted["overage"] > 0 and weighted["recommended_budget"] == weighted["cap"])

    # --- tolerance: every one of the documented gaps still produces a result ---
    project = temp_project()
    try:
        empty_task = project / "qa-factory" / "artifacts" / "QA-EMPTY"
        empty = sizing.compute(empty_task, project)
        check_eq("no register at all -> XS/0, not an exception", empty["computed_budget"], 0)
        check_in("the missing register is named", "no work/requirements-register.md",
                 empty["reasoning"])

        write_sized_task(project, "QA-EMPTY",
                         "| R-1 | One requirement, nothing else in the story | ac | — | yes | AC-1 | diff:a.py:1 |\n")
        single = sizing.compute(empty_task, project)
        check_eq("a single-criterion story applies the 0.8 reducer",
                 [r["name"] for r in single["reducers_applied"]], ["single-criterion"])
        check_eq("2.0 x0.8 floors to 1", single["computed_budget"], 1)

        # A project with no strategy file and no ledger at all — the area bump and the
        # precedent check both stay silent about it rather than raising.
        check_in("no strategy file is named plainly",
                 "no qa-factory/strategy/test-strategy.md", single["reasoning"])
        check_in("an absent ledger is named plainly",
                 "estimation-ledger.jsonl is absent or empty", single["reasoning"])
    finally:
        cleanup(project)

    # --- size_override survives a re-run that supplies none (decision #7) ---
    project = temp_project()
    try:
        task = install_artifacts(project, FIXTURES / "sizing-15045" / "qa-factory" / "stories"
                                 / "TP1-15045", "TP1-15045")
        sizing.run(task, project, size_override="XL", size_override_reason="two independent surfaces")
        again = sizing.run(task, project)
        check_eq("a size_override set once is kept on the next plain run",
                 again["size_override"], "XL")
        cleared = sizing.run(task, project, size_override="")
        check_eq("an explicit empty override clears the earlier one",
                 cleared["size_override"], "")
    finally:
        cleanup(project)

    # --- defect-ticket cap ---
    project = temp_project()
    try:
        task = write_sized_task(
            project, "QA-BUG",
            "| R-1 | Save no longer 500s on a null title | ac | — | yes | AC-1 | diff:a.py:1 |\n"
            "| R-2 | The same fix does not affect the update path | derived | aspect:x | yes | — | diff:b.py:1 |\n")
        bug = sizing.compute(task, project, ticket_type="Bug")
        check_eq("a defect ticket caps the computed budget at 1 regardless of row count",
                 bug["computed_budget"], 1)
        check_in("the defect cap names the uncapped number it overrode",
                 "defect ticket — capped at 1 regression case", bug["reasoning"])
    finally:
        cleanup(project)

    # --- CLI wiring: --task through hooklib, --selftest, JSON on stdout ---
    proc = run_script("sizing.py", "--selftest")
    check_eq("sizing.py --selftest exits 0", proc.returncode, 0)
    check_in("the module's own selftest reports no violations", "no violations", proc.stdout)

    project = temp_project()
    try:
        install_artifacts(project, FIXTURES / "sizing-15045" / "qa-factory" / "stories"
                          / "TP1-15045", "TP1-15045")
        (project / "qa-factory" / "strategy").mkdir(parents=True, exist_ok=True)
        (project / "qa-factory" / "strategy" / "test-strategy.md").write_text(
            (FIXTURES / "sizing-15045" / "qa-factory" / "strategy" / "test-strategy.md")
            .read_text(encoding="utf-8"), encoding="utf-8")
        cfg = json.loads((project / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        real_cfg = json.loads((FIXTURES / "sizing-15045" / "qa-factory" / "config.json")
                              .read_text(encoding="utf-8"))
        cfg["impact_scale"] = real_cfg["impact_scale"]
        (project / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

        proc = run_script("sizing.py", "--task", "TP1-15045", cwd=project,
                          env={**__import__("os").environ, "CLAUDE_PROJECT_DIR": str(project)})
        check_eq("sizing.py --task exits 0 through hooklib project resolution",
                 proc.returncode, 0)
        payload = json.loads(proc.stdout)
        check_eq("the CLI's own computed_budget matches the library call",
                 payload["computed_budget"], result["computed_budget"])
        check("the CLI run left work/sizing.json on disk",
              (project / "qa-factory" / "artifacts" / "TP1-15045" / "work"
              / "sizing.json").is_file())
    finally:
        cleanup(project)

    # --- both ends of the size, under the names the dashboard reads -------------------------
    # TP1-15045: S9 wrote `forecast.size`, the Precedents block asked for
    # `size_initial`/`size_final`, and the block stood empty on every story.
    work = temp_project("qa-sizing-record-")
    try:
        task_root = work / "qa-factory" / "artifacts" / "T-1"
        (task_root / "work").mkdir(parents=True)
        (task_root / "work" / "sizing.json").write_text(
            json.dumps({"size": "XL", "size_override": "L",
                        "size_override_reason": "the UI checks share one popup fixture"}),
            encoding="utf-8")
        pipeline: dict = {}
        S.record_size(pipeline, "L", task_root)
        check_eq("the first call is the forecast", pipeline["size_initial"], "L")
        check_eq("and also the fact, until something changes it", pipeline["size_final"], "L")
        check_in("a size that is not the formula's says why", "one popup fixture",
                 pipeline["size_reason"])
        S.record_size(pipeline, "XL", task_root)
        check_eq("a later call never rewrites the forecast", pipeline["size_initial"], "L")
        check_eq("it moves the fact", pipeline["size_final"], "XL")
        check_in("and records the re-estimation", "L -> XL", pipeline["size_reason"])
        check_eq("every name is the one contract.py publishes",
                 sorted(k for k in pipeline if k.startswith("size")), sorted(C.SIZE_KEYS))
        agreed: dict = {}
        (task_root / "work" / "sizing.json").write_text(json.dumps({"size": "M"}), encoding="utf-8")
        S.record_size(agreed, "M", task_root)
        check("a size the formula agrees with needs no reason", "size_reason" not in agreed,
              str(agreed))
    finally:
        cleanup(work)

    size_at_the_s2_exit()
    g10_a_register_without_ac_ref_joins_by_the_observable_path()
    oh1_10_the_onboarding_form_is_what_sizing_reads()
    oh2_6_a_malformed_impact_scale_is_a_note_never_a_crash()
    oh2_2_sizing_names_the_state_the_strategy_file_is_in()
    oh3_34_the_register_is_read_through_the_one_reader()
    finish("SIZING")


# --- OH3-34: the register row is read by `contract.register_rows` (AR-13); the key `requirement` is no longer dead --------------
# The dead-key regression: the template's header is `Requirement (one verifiable statement)`, the old reader keyed the row by the
# whole lower-cased header, and `row.get("requirement")` was empty for every row of every real story (area_match null, the copy-only
# and logging-only reducers never fired). The fixtures here carry the REAL template header, never a plain `Requirement`.
TEMPLATE_REGISTER = SCRIPTS.parent / "references" / "templates" / "requirements-register.md"


def oh3_34_template_head() -> str:
    """The template's text up to its first row: front matter, comments, the `## Register` heading and the REAL header lines."""
    text = TEMPLATE_REGISTER.read_text(encoding="utf-8")
    return text[:text.index("| R-1 |")]


def oh3_34_row(i: int, requirement: str) -> str:
    return f"| R-{i} | {requirement} | story | — | yes | AC-{i} | diff:src/a{i}.py:1 | degraded | changed |\n"


def oh3_34_sized(requirements: list, strategy: str = "## Risk and impact scale\n\n**P1 areas.** budgets and spend tracking (src/a1.py)\n\n**P2 areas.** x\n") -> dict:
    project = temp_project("qa-oh334-")
    try:
        rows = "".join(oh3_34_row(i, text) for i, text in enumerate(requirements, 1))
        task = write_sized_task(project, "QA-1", rows, strategy_text=strategy, head=oh3_34_template_head())
        return S.compute(task, project)
    finally:
        cleanup(project)


def oh3_34_the_register_is_read_through_the_one_reader() -> None:
    head = oh3_34_template_head()
    check_in("K1 oh3-34: the fixture head is the real template header", "| R | Requirement (one verifiable statement) |", head)
    real = C.register_rows(head + oh3_34_row(1, "The budgets dashboard totals"))
    plain = C.register_rows("## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable |\n"
                            "|---|---|---|---|---|---|---|\n| R-1 | The budgets dashboard totals | story | - | yes | AC-1 | diff:a.py:1 |\n")
    check_eq("K1 oh3-34: register_rows carries `requirement` on the template header", [r["requirement"] for r in real],
             ["The budgets dashboard totals"])
    check_eq("K1 oh3-34: ... and on a plain `Requirement` header", [r["requirement"] for r in plain], ["The budgets dashboard totals"])
    path_work = temp_dir("qa-oh334-reg-")
    try:
        reg = Path(path_work) / "requirements-register.md"
        reg.write_text(head + oh3_34_row(1, "x"), encoding="utf-8")
        adapted = S.parse_register(reg)
        check("K1 oh3-34: parse_register (thin adapter) keeps `verifiable` and `impact` and finds the impact column",
              adapted["rows"][0].get("verifiable") == "yes" and adapted["rows"][0].get("impact") == "degraded" and adapted["has_impact"],
              str(adapted))
    finally:
        cleanup(path_work)

    # K2: three template rows, one in the P1 area -> area_match set for it, None for the two others
    sized = oh3_34_sized(["The budgets dashboard must total correctly", "Node border turns amber when modified",
                          "Restore is denied for a read-only user"])
    check_eq("K2 oh3-34: area_match is set for the row on the path the P1 area names and None for the two others",
             [r["area_match"] for r in sized["requirements"]], ["budgets and spend tracking (src/a1.py)", None, None])
    wordy = oh3_34_sized(["The budgets dashboard must total correctly", "Budgets spend tracking is listed"],
                         strategy="## Risk and impact scale\n\n**P1 areas.** budgets and spend tracking\n\n**P2 areas.** x\n")
    check_eq("K1 oh3-34: an area whose words fill the requirement text but which names no surface bumps nothing (word matching is gone)",
             [(r["area_match"], r["weight"]) for r in wordy["requirements"]], [(None, 1.0), (None, 1.0)])
    check_in("K1 oh3-34: and the reasoning says the area names no surface",
             "P1 area «budgets and spend tracking» names no surface — no bump", wordy["reasoning"])

    # K3: the copy-only reducer fires on two copy rows of the real template header
    copy = oh3_34_sized(["Button label reads Save", "Tooltip text is translated"])
    check("K3 oh3-34: the copy-only reducer fires on two copy rows", any(r["name"] == "copy-or-label-only" for r in copy["reducers_applied"]),
          str(copy["reducers_applied"]))

    # edges: an empty register, and a header with no Requirement column
    check_eq("edge oh3-34: a register table with no rows reads as no rows", C.register_rows(head), [])
    check_eq("edge oh3-34: no `## Register` table reads as no rows", C.register_rows("# nothing\n"), [])
    empty = oh3_34_sized([])
    check_eq("edge oh3-34: sizing over an empty register does not crash and counts nothing", empty["verifiable_count"], 0)

    # K6: a header with no Requirement column is refused naming the column (FR-11), never rows with an empty key
    nocol = "## Register\n\n| R | Statement | source |\n|---|---|---|\n| R-1 | x | story |\n"
    refused = ""
    try:
        C.register_rows(nocol)
    except ValueError as exc:
        refused = str(exc)
    check_in("K6 oh3-34: register_rows refuses a register with no Requirement column, naming it", "`Requirement` column", refused)
    project = temp_project("qa-oh334-nocol-")
    try:
        task = write_sized_task(project, "QA-1", "| R-1 | x | story |\n", head="## Register\n\n| R | Statement | source |\n|---|---|---|\n")
        out = S.compute(task, project)
        check("K6 oh3-34: sizing says so in `reasoning` instead of sizing silently",
              any("Requirement" in line and "requirements-register.md" in line for line in out["reasoning"]), str(out["reasoning"]))
    finally:
        cleanup(project)


def g10_a_register_without_ac_ref_joins_by_the_observable_path() -> None:
    """G1-0 (t-928, P23): a task with no AC has no `ac_ref`, so `requirement_signal` found no observables and the story-level
    signal never reached the requirement (a silent loss). The join key is `ac_ref` when the manifest holds it, else the file path of
    the row's `observable` cell. Over-signalling is the accepted direction: one file under two requirements lifts both."""
    manifest = {"observables": [
        {"path": "src/api/handler.py", "repo": "svc", "kind": "api", "requirement": "AC-1"},
        {"path": "src/db/migrations/001_add.sql", "repo": "svc", "kind": "db", "requirement": ""},
        {"path": "src/ui/view.ts", "repo": "web", "kind": "ui"}]}
    signals = S.diff_signals(manifest)
    check("setup: the story touches three surfaces and a migration", signals["surfaces_signal"] and signals["migration_signal"])
    by_ac = S.requirement_signal({"r": "R-1", "ac_ref": "AC-1", "observable": "-"}, signals)
    by_path = S.requirement_signal({"r": "R-2", "ac_ref": "", "observable": "diff:src/db/migrations/001_add.sql:7"}, signals)
    other = S.requirement_signal({"r": "R-3", "ac_ref": "", "observable": "current-code:src/db/migrations/001_add.sql:99"}, signals)
    check_eq("the row with an ac_ref joins by it, as before (the api observable of AC-1: the migration file shares its repo)",
             by_ac[0], "migration:svc")
    check_eq("no ac_ref: the file path of `diff:<path:line>` joins the manifest observable (the migration file's repo is svc)",
             by_path[0], "migration:svc")
    check_eq("... and `current-code:<path:line>` too: two requirements sharing one file BOTH get the signal (the over-signal direction)",
             other[0], "migration:svc")
    check_eq("neither an ac_ref nor an observable path -> no signal, and the note SAYS so (FR-41), never a silent loss",
             S.requirement_signal({"r": "R-4", "ac_ref": "", "observable": "-"}, signals),
             (None, "no per-requirement signal: no ac_ref and no observable path"))
    check_eq("a cell with only whitespace is the same absence, and the note is the same",
             S.requirement_signal({"r": "R-4", "ac_ref": "", "observable": "   "}, signals)[1],
             "no per-requirement signal: no ac_ref and no observable path")
    check_eq("a path no manifest observable holds -> the note says WHICH path nothing holds (not 'no observable path')",
             S.requirement_signal({"r": "R-5", "ac_ref": "", "observable": "diff:src/other.py:1"}, signals)[1],
             "no per-requirement signal: no ac_ref; no manifest observable holds src/other.py")
    check_eq("a story with no story-level signal says nothing (the note would be noise on every row)",
             S.requirement_signal({"r": "R-6", "ac_ref": "", "observable": "-"}, S.diff_signals({"observables": []})), (None, None))
    g10_the_register_forms_of_the_observable_cell()


def g10_the_register_forms_of_the_observable_cell() -> None:
    """M1 of t-984: the join reads the cell the way the register writes it (artifact-contract: `diff:<path>:<line>`, the S2 registers
    of a multi-repo story `diff:<repo>:<path>:<line>`, a cell in backticks) through `contract.strip_cell` / `observable_source`, and a
    row nothing joins to gets the TRUE reason. Expected values come from the documented forms (FR-58), not from the parser's output."""
    manifest = {"observables": [
        {"path": "src/api/handler.py", "repo": "testproject1-backend", "kind": "api", "requirement": "AC-1"},
        {"path": "db/migrations/001.sql", "repo": "testproject1-backend", "kind": "db", "requirement": ""},
        {"path": "src/ui/view.ts", "repo": "testproject1-ui", "kind": "ui"}]}
    signals = S.diff_signals(manifest)
    joined = "migration:testproject1-backend"
    for label, cell in (
            ("`diff:<path>:<line>`", "diff:db/migrations/001.sql:3"),
            ("`diff:<repo>:<path>:<line>` (the multi-repo register form)", "diff:testproject1-backend:db/migrations/001.sql:3"),
            ("the same in backticks", "`diff:testproject1-backend:db/migrations/001.sql:3`"),
            ("a repo-less cell in backticks", "`diff:db/migrations/001.sql:3`"),
            ("`current-code:<repo>:<path>:<line>`", "current-code:testproject1-backend:db/migrations/001.sql:12"),
            ("backslashes", "diff:db\\migrations\\001.sql:3"),
            ("no `:line` at all", "diff:testproject1-backend:db/migrations/001.sql")):
        check_eq(f"joins by the file: {label}", S.requirement_signal({"r": "R-1", "ac_ref": "", "observable": cell}, signals)[0], joined)
    check_eq("the repo of the cell is checked: the same file name in ANOTHER repo is not the place",
             S.requirement_signal({"r": "R-2", "ac_ref": "", "observable": "diff:testproject1-ui:db/migrations/001.sql:3"}, signals),
             (None, "no per-requirement signal: no ac_ref; no manifest observable holds testproject1-ui:db/migrations/001.sql"))
    check_eq("an ac_ref the manifest does not hold + no observable: the note says the ac_ref IS there and where it fails",
             S.requirement_signal({"r": "R-3", "ac_ref": "AC-9", "observable": "-"}, signals),
             (None, "no per-requirement signal: ac_ref AC-9 is in no manifest observable; no observable path"))
    check_eq("an ac_ref the manifest does not hold, but the cell names the file -> joins by the file (the second key)",
             S.requirement_signal({"r": "R-3", "ac_ref": "AC-9", "observable": "diff:testproject1-backend:db/migrations/001.sql:3"},
                                  signals)[0], joined)
    check_eq("an ac_ref the manifest does not hold + a path nothing holds: both causes named",
             S.requirement_signal({"r": "R-3", "ac_ref": "AC-9", "observable": "diff:x.py:1"}, signals)[1],
             "no per-requirement signal: ac_ref AC-9 is in no manifest observable; no manifest observable holds x.py")
    for label, cell, said in (
            ("a bare prefix", "diff:", "`diff:` names no path"),
            ("an empty repo", "diff::a.py:3", "`diff:` names no repo before the path `a.py`"),
            ("an empty path after a repo", "diff:testproject1-backend::3", "`diff:testproject1-backend:` names no path after the repo"),
            ("an expected contract (no file by definition)", "expected-contract:POST /validate",
             "the observable is an expected contract, not a file"),
            ("a cell of no known form", "see the ticket", "the observable cell `see the ticket` is neither diff:... nor current-code:...")):
        note = S.requirement_signal({"r": "R-4", "ac_ref": "", "observable": cell}, signals)[1]
        check_in(f"a malformed cell names the part that fails: {label}", said, note)
        check_not_in(f"... and never claims the path is absent when the cell has one: {label}", "no ac_ref and no observable path", note)


# --- OH1-10 (t-1161): the form onboarding writes is the form this module reads --------------------------------------
# No code writes `test-strategy.md`: phase 4 of qa-onboarding is PROSE the onboarding role follows (`onboard_apply.py` leaves the
# strategy documents to the role). So the contract between the generator and `parse_p1_areas` lives in that text, and these tests
# read it: the fenced template is extracted from p4-generate.md (not a frozen copy), filled with areas that are this test's own
# inputs (FR-58: no expected value comes from the parser), and fed to the real reader. The reader stops only at `**P2 areas.**` or at
# the end of the file (sizing.py, parse_p1_areas), which is why the template always writes the P2 label right after P1.
# Error direction (designer rule 1: a reader that used to see only hand-kept paragraphs now sees every onboarding's): an over-bump
# is accepted (a bigger budget, named in the reasoning, overridable at gate A); a bump from a word the team did not say, and a
# silent loss of an area the team named, are not.

P4_GENERATE = SCRIPTS.parent / "skills" / "qa-onboarding" / "phases" / "p4-generate.md"
OH110_MARKER = "[DEFERRED: risk areas not named]"
OH110_AFTER = "## Adapters and external writes\n\n- **Tickets** — Jira, reached through the direct API with a token.\n"
OH110_AREAS = ["budgets and spend tracking (a.py)", "workflow execution", "single sign-on (SSO) login (b.py)"]
OH110_NONE = ("No area stands out: the team named no part of the product as riskier than the rest "
              "(topic 4, batch p2-batch-4, 2026-10-20). Every requirement is weighed by its own impact class.")
OH110_ROWS = (
    "| R-1 | Budgets dashboard totals stay correct after edit | ac | — | yes | AC-1 | diff:a.py:1 | degraded |\n"
    "| R-2 | Login with single sign-on keeps the session | ac | — | yes | AC-2 | diff:b.py:1 | degraded |\n"
    "| R-3 | Tickets reached through the adapter are listed | ac | — | yes | AC-3 | diff:c.py:1 | degraded |\n")


def oh1_10_fenced_blocks(text: str) -> list:
    """Bodies of the fenced blocks of a markdown text. A fence line is a line whose stripped text starts with three backticks,
    fences pair in order, and a body is dedented by the indent of its opening fence (the template sits inside a bullet)."""
    blocks, opened, indent, body = [], False, 0, []
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if opened:
                blocks.append("\n".join(body))
                body = []
            else:
                indent = len(line) - len(line.lstrip())
            opened = not opened
        elif opened:
            body.append(line[indent:] if not line[:indent].strip() else line)
    return blocks


def oh1_10_generated_strategy(areas: str) -> str:
    """test-strategy.md as phase 4 step 2 writes it: the template from p4-generate.md with this test's areas in it, between the
    impact-class map and the next section."""
    holding = [b for b in oh1_10_fenced_blocks(P4_GENERATE.read_text(encoding="utf-8")) if "**P1 areas.**" in b]
    block = holding[0] if holding else ""
    block = block.replace("<area> · <area> · <area>", areas).replace("<batch id>", "p2-batch-4").replace("<YYYY-MM-DD>", "2026-10-20")
    return ("## Risk and impact scale\n\n| Impact | Priority | Severity |\n|---|---|---|\n| degraded | P2 | minor |\n\n"
            + block + "\n\n" + OH110_AFTER)


def oh1_10_sized(strategy_text, rows: str = OH110_ROWS, *, config_text=None, strategy_is_dir: bool = False) -> dict:
    """compute() over a temp project holding this strategy text (None: no strategy file at all) and three `degraded` rows. `config_text`
    replaces the config JSON (default: a well-formed `degraded` class); `strategy_is_dir` makes test-strategy.md a DIRECTORY (a file
    that exists and cannot be read)."""
    project = temp_project("qa-oh110-")
    try:
        task = write_sized_task(
            project, "QA-1", rows, strategy_text=strategy_text, head=REGISTER_HEAD_IMPACT,
            config_text=config_text or json.dumps({"impact_scale": {"degraded": {"priority": "P2", "severity": "minor"}}}))
        if strategy_is_dir:
            (project / "qa-factory" / "strategy" / "test-strategy.md").mkdir(parents=True)
        return S.compute(task, project)
    finally:
        cleanup(project)


def oh1_10_the_onboarding_form_is_what_sizing_reads() -> None:
    p4 = P4_GENERATE.read_text(encoding="utf-8")
    holding = [b for b in oh1_10_fenced_blocks(p4) if "**P1 areas.**" in b]
    check_eq("K1: p4-generate.md holds exactly ONE fenced block with the P1 label (a second label is a silent loss: the reader takes the first)",
             len(holding), 1)
    filled = oh1_10_generated_strategy(" · ".join(OH110_AREAS))
    check_eq("K2: the template of p4-generate.md, filled with the test's areas, parses to exactly those areas "
             "(no 'Not named by the team' phrase, no later section, no Source line)", S.parse_p1_areas(filled), OH110_AREAS)
    oh1_10_sizing_over_the_generated_form(filled)
    oh1_10_deferral_and_none_carry_no_label(p4)
    oh1_10_reader_edges()


def oh1_10_sizing_over_the_generated_form(filled: str) -> None:
    result = oh1_10_sized(filled)
    rows = {r["r"]: r for r in result["requirements"]}
    check_eq("K3: a row on the path (a.py) the first area names is raised to P1's weight and names the area",
             (rows["R-1"]["weight"], rows["R-1"]["area_match"]), (1.3, OH110_AREAS[0]))
    check_eq("K3: a row on the path (b.py) the last area names is raised too (the last phrase is read, not cut off)",
             (rows["R-2"]["weight"], rows["R-2"]["area_match"]), (1.3, OH110_AREAS[2]))
    check_eq("K3: a row on a path no area names is not raised, though its words (adapter, Tickets) sit in the section AFTER the P2 label (R1)",
             (rows["R-3"]["weight"], rows["R-3"]["area_match"]), (1.0, None))
    check_eq("K3: no strategy file at all -> every row at its own class weight (R6: absence never blocks)",
             sorted({r["weight"] for r in oh1_10_sized(None)["requirements"]}), [1.0])


def oh1_10_deferral_and_none_carry_no_label(p4: str) -> None:
    marker_lines = [ln for ln in p4.splitlines() if OH110_MARKER in ln]
    check("K4: p4-generate.md writes the deferral marker somewhere", len(marker_lines) >= 1)
    check("K4: no p4 line holding the marker also holds the P1 label (R1: the marker is not a phrase)",
          not any("**P1 areas.**" in ln for ln in marker_lines), str(marker_lines))
    deferred = oh1_10_sized(OH110_MARKER + "\n\n" + OH110_AFTER)
    check_eq("K4: the marker followed by sections parses to no area", S.parse_p1_areas(OH110_MARKER + "\n\n" + OH110_AFTER), [])
    check_in("K4: and sizing says the areas are deferred (R6; OH2-2: its own line, not the generic one)", "risk areas deferred", deferred["reasoning"])
    none_lines = [ln for ln in p4.splitlines() if "No area stands out:" in ln]
    check("K5: p4-generate.md writes the 'no area stands out' sentence", len(none_lines) >= 1)
    check("K5: its line holds no P1 label (R3: an answer is not a paragraph)", not any("**P1 areas.**" in ln for ln in none_lines))
    check_eq("K5: the sentence followed by sections parses to no area", S.parse_p1_areas(OH110_NONE + "\n\n" + OH110_AFTER), [])
    answered = oh1_10_sized(OH110_NONE + "\n\n" + OH110_AFTER)
    check_eq("K5: ... and bumps nothing", sorted({r["weight"] for r in answered["requirements"]}), [1.0])


def oh1_10_reader_edges() -> None:
    p2 = "\n\n**P2 areas.** x"
    check_eq("K6: a comma stays inside one phrase, `·` splits", S.parse_p1_areas("**P1 areas.** checkout · payments, refunds" + p2),
             ["checkout", "payments, refunds"])
    split = S.parse_p1_areas("**P1 areas.** ledger · payment reconciliation" + p2)
    check_eq("K6: an inner `·` splits one intended phrase into two", split, ["ledger", "payment reconciliation"])
    row = {"requirement": "Reconciliation totals match", "observable": "diff:src/payment/recon.py:4"}
    ledger_split = S.parse_p1_areas("**P1 areas.** ledger · src/payment/recon.py" + p2)
    check_eq("K6: the split is cosmetic for the bump (same row raised either way); it changes only the area named",
             (S.find_area_match(row, ledger_split, {}), S.find_area_match(row, ["ledger · src/payment/recon.py"], {})),
             ("src/payment/recon.py", "ledger · src/payment/recon.py"))
    check_eq("K6: two P1 labels with a P2 label between: the first one's phrases win and the second is lost",
             S.parse_p1_areas("**P1 areas.** alpha area\n\n**P2 areas.** x\n\n**P1 areas.** gamma area"), ["alpha area"])
    check_eq("K6: two P1 labels with NO P2 label between: the second is absorbed into the first one's last phrase",
             S.parse_p1_areas("**P1 areas.** alpha area **P1 areas.** gamma area"), ["alpha area **P1 areas.** gamma area"])
    sig = {"surfaces": ["ui"], "observables": [{"kind": "ui", "path": "a.tsx"}]}
    check_eq("K6: an area word in the requirement text matches nothing, even a word the area shares with it (the regression this kills)",
             S.find_area_match({"requirement": "SSO login for the Budgets page", "observable": "diff:a.tsx:1"}, ["SSO login", "Budgets"], {}), None)
    check_eq("K6: an area with no surface kind word and no path token matches nothing, and the reasoning says so",
             (S.find_area_match({"observable": "diff:a.tsx:1"}, ["Budgets"], sig), S.area_without_surface_lines(["Budgets"], sig)),
             (None, ["P1 area «Budgets» names no surface — no bump"]))
    check_eq("K6 B-1: a surface kind word alone names no surface and matches nothing, however well the row's kind fits",
             (S.find_area_match({"observable": "diff:a.tsx:1"}, ["Budgets", "the UI shell"], sig), S.area_without_surface_lines(["the UI shell"], sig)),
             (None, ["P1 area «the UI shell» names no surface — no bump"]))
    sig2 = {"surfaces": ["ui", "api"], "observables": [{"kind": "ui", "path": "a.tsx"}, {"kind": "api", "path": "b.py"}]}
    check_eq("K6 B-1: a kind word FILTERS a path match: the path and the kind agree -> match; the path is on a row of another kind -> none",
             [S.find_area_match({"observable": "diff:b.py:1"}, [area], sig2) for area in ("API b.py", "UI b.py", "b.py")],
             ["API b.py", None, "b.py"])
    check_eq("K6 B-1: ... and not a row of another kind, one the manifest does not hold, or an empty cell",
             [S.find_area_match({"observable": cell}, ["the UI a.tsx"], sig2) for cell in ("diff:b.py:1", "diff:zzz.tsx:1", "", "none")],
             [None, None, None, None])
    check_eq("K6 m-4: prose is no path token: `Node.js`, `e.g`, a version, a bare word; `.js` needs a directory",
             [S.area_surface_tokens(a, {})[1] for a in ("Node.js runtime", "billing, e.g. invoices", "v1.2 rollout", "Budgets", "Vue.js shell", "src/app.js")],
             [[], [], [], [], [], [("src", "app.js")]])
    check_eq("K6 m-4: a file with a known suffix is a token, in any case: `page.tsx`, `Page.TSX`, `src/a.py`",
             [S.area_surface_tokens(a, {})[1] for a in ("the page.tsx view", "the Page.TSX view", "x (src/a.py).")],
             [[("page.tsx",)], [("page.tsx",)], [("src", "a.py")]])
    check_eq("K6: a path token matches by path segments, case-insensitively: `Payment/Recon.py` is inside `src/payment/recon.py`, "
             "`pay` is not a segment of it, and a longer token than the path does not match",
             [S.find_area_match({"observable": "diff:src/payment/recon.py:4"}, [area], {})
              for area in ("x (Payment/Recon.py)", "x (src/pay)", "x (core/src/payment/recon.py)")],
             ["x (Payment/Recon.py)", None, None])
    check_eq("K6: two areas match one row -> the first in strategy order wins",
             S.find_area_match({"observable": "diff:a.tsx:1"}, ["the UI a.tsx", "a.tsx"], sig), "the UI a.tsx")
    umlaut = chr(0xDC) + "berweisungen"                                # a Latin word with a non-ASCII first letter
    check_eq("K6: a non-ASCII phrase parses whole (the match is by surface token, not by word)",
             S.parse_p1_areas("**P1 areas.** Budgets · " + umlaut + p2), ["Budgets", umlaut])
    cyrillic = "".join(map(chr, range(0x430, 0x436))) + " " + "".join(map(chr, range(0x436, 0x43C)))   # two Cyrillic words, built from code points
    check_eq("K6: a Cyrillic phrase names no surface, so it bumps nothing (a missed bump is the accepted cost)",
             S.find_area_match({"requirement": cyrillic + " is shown", "observable": "diff:a.tsx:1"}, [cyrillic], sig), None)
    check_eq("K6: an empty paragraph, and one holding only a period, read as no area",
             (S.parse_p1_areas("**P1 areas.**" + p2), S.parse_p1_areas("**P1 areas.** ." + p2)), ([], []))


# --- OH2-2 (b) (t-1196): sizing names the state the strategy file is in ---------------------------------------------------
# A reasoning line that says "no readable paragraph" for a team that ANSWERED "no area stands out", or for one that said "later",
# claims an absence that is not the case (FR-41, AR-28). Sizing now tells seven states apart; the generic line is kept only for the
# one it is true of. The state lines are reports: no weight depends on one (AR-2, K2-6). The two P4 literals the reader newly keys on
# (the deferral marker, the first words of the none sentence) are taken FROM p4-generate.md here (AR-22): a rename on either side fails.

OH22_LINES = {   # each state's own line, as a fragment no other state's line holds
    "no_file": "no qa-factory/strategy/test-strategy.md",
    "unreadable": "could not be read (",
    "deferred": "risk areas deferred:",
    "none_stands_out": "the team named no risk area",
    "label_empty": "label with no phrase after it",
    "not_asked": "topic 4 was not asked"}
OH22_STALE = "one of them is stale"
OH22_SECTION = "## Risk and impact scale\n\n| Impact | Priority | Severity |\n|---|---|---|\n| degraded | P2 | minor |\n\n"


def oh2_2_p4_literals() -> tuple:
    """(the distinct deferral markers for the risk areas, the none sentence) exactly as p4-generate.md writes them, placeholders filled."""
    p4 = P4_GENERATE.read_text(encoding="utf-8")
    markers = sorted(set(re.findall(r"\[DEFERRED:\s*risk areas[^\]]*\]", p4)))
    found = re.search(r'"(No area[^"]*)"', p4)
    sentence = re.sub(r"\s+", " ", found.group(1)) if found else ""
    return markers, sentence.replace("<batch id>", "p2-batch-4").replace("<YYYY-MM-DD>", "2026-10-20")


def oh2_2_state_lines(result: dict) -> list:
    """The states whose own line is in this result's reasoning."""
    return [state for state, fragment in OH22_LINES.items() if any(fragment in line for line in result["reasoning"])]


def oh2_2_sizing_names_the_state_the_strategy_file_is_in() -> None:
    markers, sentence = oh2_2_p4_literals()
    check_eq("K2-0: p4-generate.md writes the risk-areas deferral marker in ONE form", len(markers), 1)
    check("K2-0: ... and quotes the none sentence once, as a sentence", sentence.startswith("No area") and ":" in sentence, sentence)
    marker = markers[0] if markers else "(no marker in p4)"
    paragraph = oh1_10_generated_strategy(" · ".join(OH110_AREAS))
    cases = (   # (state, label, strategy text, strategy_is_dir)
        ("areas", "a P1 paragraph", paragraph, False),
        ("no_file", "no strategy file", None, False),
        ("unreadable", "a strategy path that cannot be read", None, True),
        ("deferred", "the deferral marker", marker + "\n\n" + OH110_AFTER, False),
        ("none_stands_out", "the none sentence", sentence + "\n\n" + OH110_AFTER, False),
        ("label_empty", "a P1 label with no phrase", "**P1 areas.** .\n\n**P2 areas.** x", False),
        ("none_stands_out", "the none sentence AND an empty P1 label (state 5 is decided before state 6)",
         sentence + "\n\n**P1 areas.** .\n\n**P2 areas.** x", False),
        ("not_asked", "a strategy with no area text", OH22_SECTION + OH110_AFTER, False),
        ("not_asked", "an empty file", "", False),
        ("not_asked", "the none sentence reworded to lower case", sentence.replace("No area", "no area", 1), False),
        ("not_asked", "the none sentence in the middle of a line (a quote, not the answer)", "Notes: " + sentence + "\n", False),
        ("deferred", "the marker inside a fence (a misread costs a line, never a weight)", "```\n" + marker + "\n```\n", False))
    weights = {}
    for state, label, text, is_dir in cases:
        result = oh1_10_sized(text, strategy_is_dir=is_dir)
        check_eq(f"K2: {label}: its own state line and no other", oh2_2_state_lines(result), [] if state == "areas" else [state])
        check_not_in(f"K2: {label}: no stale-pair line", OH22_STALE, result["reasoning"])
        weights[label] = [r["weight"] for r in result["requirements"]]
    check_eq("K2-6: the area paragraph bumps R-1 and R-2 (the one state with an effect)", weights["a P1 paragraph"], [1.3, 1.3, 1.0])
    check_eq("K2-6: every other state sizes the same register at the same weights (a state line never moves a weight, AR-2)",
             sorted({tuple(w) for label, w in weights.items() if label != "a P1 paragraph"}), [(1.0, 1.0, 1.0)])
    oh2_2_both_and_conflicts(marker, sentence, paragraph)
    oh2_2_the_state_function(marker, sentence)


def oh2_2_both_and_conflicts(marker: str, sentence: str, paragraph: str) -> None:
    both = oh1_10_sized(marker + "\n\n" + sentence + "\n\n" + OH110_AFTER)
    check_eq("K2-8: the marker AND the sentence: the deferral line prints, the none line does not", oh2_2_state_lines(both), ["deferred"])
    check_in("K2-8: ... and an extra line names the pair as stale", OH22_STALE, both["reasoning"])
    kept = oh1_10_sized(paragraph + "\n\n" + marker + "\n")
    check_eq("K2: a paragraph AND a marker (hand-edited): the areas win, no state line", oh2_2_state_lines(kept), [])
    check_eq("K2: ... and the human's areas still bump", [r["weight"] for r in kept["requirements"]], [1.3, 1.3, 1.0])
    root = temp_dir("qa-oh22-noroot-")
    try:
        (root / "work").mkdir()
        (root / "work" / "requirements-register.md").write_text(REGISTER_HEAD_IMPACT + OH110_ROWS, encoding="utf-8")
        orphan = S.compute(root, None)
        check_in("K2: no project root: today's line", "no project root found above the task", orphan["reasoning"])
        check_eq("K2: ... and no state line", oh2_2_state_lines(orphan), [])
    finally:
        cleanup(root)


def oh2_2_the_state_function(marker: str, sentence: str) -> None:
    """`strategy_area_state(project_root) -> (areas, state, lines)`; its first member is the areas (OH3-23 Q14: the dead reader is gone)."""
    project = temp_project("qa-oh22-state-")
    try:
        path = project / "qa-factory" / "strategy" / "test-strategy.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        areas, state, lines = S.strategy_area_state(project)
        check_eq("K2: no file -> ([], 'no_file', one line)", (areas, state, len(lines)), ([], "no_file", 1))
        path.write_text("**P1 areas.** checkout · payments\n\n**P2 areas.** x", encoding="utf-8")
        check_eq("K2: a paragraph -> its areas, state 'areas', no line", S.strategy_area_state(project), (["checkout", "payments"], "areas", []))
        check_eq("K2: the areas are the first member of strategy_area_state", S.strategy_area_state(project)[0], ["checkout", "payments"])
        path.write_text(marker + "\n" + sentence + "\n", encoding="utf-8")
        areas, state, lines = S.strategy_area_state(project)
        check_eq("K2-8: the pair -> state 'deferred' (the deferral first), its line and the stale line", (areas, state, len(lines)),
                 ([], "deferred", 2))
        path.unlink()
        path.mkdir()
        areas, state, lines = S.strategy_area_state(project)
        check_eq("K2: a path that exists and cannot be read -> ([], 'unreadable', one line)", (areas, state, len(lines)), ([], "unreadable", 1))
        check_eq("K2: no project root -> no areas, no state to name", S.strategy_area_state(None)[:2], ([], "no_root"))
        check_eq("K2: ... and its areas for None are []", S.strategy_area_state(None)[0], [])
    finally:
        cleanup(project)


# --- OH2-6 (a) (t-1196): a malformed impact_scale is a named note, never a crash ---------------------------------------------
# `classify_requirement` called `.get` on the class's entry; a string entry raised AttributeError and the whole sizing died, the
# very command that was to tell the person what is wrong. `validate_artifacts.py` reads the scale through `grammar.impact_scale`,
# which skips a non-dict; this module still reads its own copy (AR-13 is NOT kept for this fact: finding F-7, not this node).

def oh2_6_a_malformed_impact_scale_is_a_note_never_a_crash() -> None:
    for label, entry, kind in (("a string", '"P2"', "string"), ("a number", "3", "number"), ("null", "null", "null"),
                               ("a list", '["P1"]', "list"), ("a boolean", "true", "boolean")):
        try:
            result = oh1_10_sized(None, config_text='{"impact_scale": {"degraded": %s}}' % entry)
        except Exception as exc:  # noqa: BLE001 — the point of the case: a crash is a named failure, not a traceback
            check(f"K6a-1: an entry that is {label}: no exception", False, repr(exc))
            continue
        notes = [l for l in result["reasoning"] if "config.impact_scale['degraded']" in l]
        check_eq(f"K6a-1: an entry that is {label}: weight 1.0 (P2 default) on every row", sorted({r["weight"] for r in result["requirements"]}), [1.0])
        check_eq("K6a-1: ... one note per row", len(notes), 3)
        check_in(f"K6a-1: ... naming the class and the type ({kind})", f"config.impact_scale['degraded'] is a {kind} (", notes)
        check_in("K6a-1: ... and the weight that applies", "weight 1.0 (P2 default)", notes)
    nested = oh1_10_sized(None, config_text='{"impact_scale": {"degraded": {"priority": 3}}}')
    check_eq("K6a: an entry that is a map without a severity: the package's degraded row (P2, 1.0)",
             sorted({r["weight"] for r in nested["requirements"]}), [1.0])
    check_eq("K6a-5 (OH3-3): ... and now a note per row, naming what is missing",
             len([l for l in nested["reasoning"] if "config.impact_scale['degraded'] is a map without severity" in l]), 3)
    lines = {"absent": "config.impact_scale is absent", "empty": "config.impact_scale is empty", "not a map": ", not a map of classes"}
    for label, config, own in (("a string", '{"impact_scale": "x"}', "not a map"), ("a number", '{"impact_scale": 5}', "not a map"),
                               ("a list", '{"impact_scale": [1]}', "not a map"), ("absent", '{"sizing": {}}', "absent"),
                               ("an empty map", '{"impact_scale": {}}', "empty")):
        result = oh1_10_sized(None, config_text=config)
        said = [name for name, fragment in lines.items() if any(fragment in l for l in result["reasoning"])]
        check_eq(f"K6a-4: a whole impact_scale that is {label}: its own line and no other", said, [own])
        check_eq("K6a-4: ... and says what applies instead (OH3-3)",
                 len([l for l in result["reasoning"] if l.endswith("— the package's default classes apply")]), 1)
        check_eq("K6a-4: ... the package's classes weigh the `degraded` rows at 1.0", sorted({r["weight"] for r in result["requirements"]}), [1.0])
    typed = oh1_10_sized(None, config_text='{"impact_scale": "x"}')
    check_in("K6a-4: a string whole value names its type", "config.impact_scale is a string, not a map of classes", typed["reasoning"])


# --- the size is recorded where it is decided: the S2 exit (B-210, P9c) -----------------------------
# TP1-13797: `pipeline.json` kept `size: null` from S0 to the end while `work/sizing.json` held XXL.
# `stage_done --stage S2 --status done` records it, through `record_size`, and never stops the stage.

def _s2_story(sizing=None, size=None, raw=None):
    """A project whose story T-1 holds a pipeline (with `size`) and, when given, a sizing.json."""
    project = temp_project("qa-s2-size-")
    task = project / "qa-factory" / "artifacts" / "T-1"
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps({"ticket": "T-1", "stages": {}, "gates": {}, "size": size}),
                                        encoding="utf-8")
    if raw is not None:
        (task / "work" / "sizing.json").write_text(raw, encoding="utf-8")
    elif sizing is not None:
        (task / "work" / "sizing.json").write_text(json.dumps(sizing), encoding="utf-8")
    use_project(project)
    return project, task


def _s2(stage="S2", status="done", sets=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = stage_done.run("T-1", stage, status, "", "d", True, "", sets)
    return code, out.getvalue() + err.getvalue()


def _pipeline(task):
    return json.loads((task / "pipeline.json").read_text(encoding="utf-8"))


def size_at_the_s2_exit():
    # the role's override beats the formula's size; both ends of the size exist after it
    project, task = _s2_story({"size": "XL", "size_override": "L", "size_override_reason": "one shared popup fixture"})
    try:
        code, said = _s2()
        p = _pipeline(task)
        check_eq("S2 exit: the size_override is the size recorded (not the formula's)", p.get("size"), "L")
        check_eq("S2 exit: through record_size, so both ends exist", (p.get("size_initial"), p.get("size_final")), ("L", "L"))
        check_in("S2 exit: and says why it is not the formula's", "one shared popup fixture", p.get("size_reason", ""))
        check_in("S2 exit: the write is printed", 'pipeline.json: size = "L"; size_initial = "L"', said)
        check_eq("S2 exit: the stage closes", (code, p["stages"]["S2"]["status"]), (0, "done"))
    finally:
        cleanup(project)

    # no override: the formula's size
    project, task = _s2_story({"size": "M", "size_override": ""})
    try:
        _s2()
        check_eq("S2 exit: an empty override is no override, the formula's size is recorded", _pipeline(task).get("size"), "M")
    finally:
        cleanup(project)

    # a size already recorded (the person re-sized at gate A, or an earlier S2) is never overwritten
    project, task = _s2_story({"size": "XL", "size_override": "L"}, size="XXL")
    try:
        code, said = _s2()
        p = _pipeline(task)
        check_eq("S2 exit: a size already recorded is never overwritten", p.get("size"), "XXL")
        check("S2 exit: and no end of it is written either", "size_initial" not in p and "size_final" not in p, str(p))
        check_not_in("S2 exit: and nothing is printed about it", "size", said)
        check_eq("S2 exit: the stage closes", code, 0)
    finally:
        cleanup(project)

    # the explicit word of the SAME call wins over the computed value
    project, task = _s2_story({"size": "M"})
    try:
        code, said = _s2(sets={"size": "XL"})
        p = _pipeline(task)
        check_eq("S2 exit: `--set size=XL` on the same call beats sizing.json", (p.get("size"), p.get("size_initial")), ("XL", "XL"))
        check_in("S2 exit: and the re-sizing says it differs from the formula", "where the formula gave M", p.get("size_reason", ""))
    finally:
        cleanup(project)

    # sizing.json absent: one line, S2 closes, nothing written (P1)
    project, task = _s2_story(None)
    try:
        code, said = _s2()
        check_eq("S2 exit: no sizing.json, S2 still closes", (code, _pipeline(task)["stages"]["S2"]["status"]), (0, "done"))
        check_eq("S2 exit: nothing is written", _pipeline(task).get("size"), None)
        check_eq("S2 exit: one line says so", said.count("size not computed: no work/sizing.json"), 1)
    finally:
        cleanup(project)

    # sizing.json unreadable (broken JSON, not an object, empty, no size): printed, S2 closes
    for label, raw, expect in (("broken JSON", "{not json", "size not computed: work/sizing.json unreadable ("),
                               ("not an object", "[1, 2]", "size not computed: work/sizing.json unreadable ("),
                               ("no size in it", "{}", "size not computed: work/sizing.json holds no size")):
        project, task = _s2_story(raw=raw)
        try:
            code, said = _s2()
            check_eq(f"S2 exit: sizing.json {label}: S2 closes", (code, _pipeline(task)["stages"]["S2"]["status"]), (0, "done"))
            check_in(f"S2 exit: sizing.json {label}: printed", expect, said)
            check_eq(f"S2 exit: sizing.json {label}: nothing written", _pipeline(task).get("size"), None)
        finally:
            cleanup(project)

    # an override that is not one of the known sizes: not written, printed, S2 closes; no quiet fallback
    for label, sizing_json in (("override beyond the list", {"size": "M", "size_override": "XXXL"}),
                               ("lowercase override", {"size": "M", "size_override": "xl"}),
                               ("size beyond the list", {"size": "huge"})):
        project, task = _s2_story(sizing_json)
        try:
            code, said = _s2()
            check_eq(f"S2 exit: {label}: S2 closes", (code, _pipeline(task)["stages"]["S2"]["status"]), (0, "done"))
            check_eq(f"S2 exit: {label}: not written", _pipeline(task).get("size"), None)
            check_in(f"S2 exit: {label}: printed, with the allowed list", "not one of XS | S | M | L | XL | XXL", said)
        finally:
            cleanup(project)

    # only the S2 exit records it
    project, task = _s2_story({"size": "M"})
    try:
        _s2("S2", "running")
        _s2("S3", "done")
        check_eq("S2 running and another stage's exit record nothing", _pipeline(task).get("size"), None)
    finally:
        cleanup(project)


if __name__ == "__main__":
    main()
