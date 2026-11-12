"""One brief per dispatch, built by code: the files to read, the commands, the person's words.

On TP1-13797 the automator spent 106 Grep/Read calls inside the plugin looking for how
`run_suite.py`, `manifest_put.py` and `s5_precheck.py` are called, and 137 more over the
test repository re-learning the same fixtures every window; the critic read the phase file
to find the probe command. None of that is judgment - it is a lookup, and a lookup is what
code does before the role starts:

    brief_pack.py --task T --stage S --role R --dispatch ID [--json] [--output PATH] [--dry-run]

    -> qa-factory/artifacts/<T>/work/briefs/<ID>.md   (<= 6 KB)

The brief carries, in this order:
  1. the scope of the dispatch and what earlier roles produced (pipeline.json digests,
     the accepted dispatches of this stage), then the exact files to read, task-relative,
     with sizes - derived from the stage's inputs in references/stages.json, the role's
     charter and the scope (case files, the tests of the window); for the code critic, in
     the head, the tests changed after a red run that still need its verdict;
  2. the tooling card of the role: every command with its argument shape and what it
     answers - run_suite.py --mine / --request / --detail, manifest_from_tests.py,
     probe_by_code.py, s5_precheck.py, manifest_put.py, the judge_* scripts only when
     judge.active();
  3. the person's standing instructions and gate decisions that concern this role
     (pipeline.json `warnings`, `gates`, `stage_overrides`, `halts` not `resolved`, and the questions the person
     decided, read from the answers file through question_register);
  4. for S5/S6 the repository map of the window (`repo_map.py`), linked, with its head
     inlined while the brief has room;
  5. the rule: do not search - read what is named; search only if the map is empty.

A section that would push the brief over 6 KB moves to a linked side file
(`work/briefs/<ID>-<section>.md`) instead of being cut. `story_step.py start` calls this
after the dispatch is registered; a failure here is a printed note there, never a refusal.
This script never reads the plugin's own scripts - the card is written from their
documented interfaces, and `--help` is the door a role uses for anything beyond it.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HERE =Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import charter  # noqa: E402
import config_contract  # noqa: E402
import hooklib  # noqa: E402
import question_register as QR  # noqa: E402
import runtime_paths as RP  # noqa: E402
from hooklib import sorted_paths  # noqa: E402
from host_adapter import CODEX_DESKTOP_TOOLS, role_has_bash  # noqa: E402

BRIEF_MAX_BYTES = 6 * 1024
SD_HEAD_MAX_BYTES = 1024    # t-1765 X1 fix-3: the seven SD header lines are FORM (outside the body budget) and have their own cap
SLICE_BYTES = 30_000  # guard_pre_tool's whole-read limit: above it the brief says "slice"
DIGEST_CHARS = 200
DISPATCH_DIGESTS = 4  # the latest dispatches of the same stage; the rest are in the side file
DECISION_CHARS = 400
DECISION_CHARS_MIN = 240
# The side file carries a person's answer whole up to this many characters (FR-8); the file the
# answers are read from (answers_of) is what a cut one points to: `RP.rel_text("journal.jsonl", project)`,
# the path where THIS project's journal really is (the layout's `records/`, or the old `state/`, FR-37).
PERSON_WORDS_MAX = 20000
MAP_INLINE_LINES = 14
PLAN_ROW_RE = re.compile(r"^\s*plan_row:\s*(\S+)", re.M)
STAGE_ORDER = [f"S{i}" for i in range(10)]
# The brief is a runtime packet under work/, written by the copy that is running: its own absolute
# path is what the role's Bash must use. `${CLAUDE_PLUGIN_ROOT}` in a brief was text nobody expanded
# (B-014, step 0: agent and brief text are not expanded, and a Bash tool's env carries whatever the
# host session had), so a role could run the scripts of another copy than the driver's.
SCRIPTS = HERE.as_posix()
# SC1-14 C2 / SC1-15: the S5 plan (`s5_plan.PLAN_REL`, spelled here because ROLE_FILES is data read at import). It is named to the
# two dispatches of the plan only; a window reads its slice of it, and an S5 history of the earlier form (`legacy`) reads neither.
PLAN_FILE = "work/s5-plan.json"
PLAN_ONLY = (PLAN_FILE,)
# The findings the S5 automator reads: ONE file, the one of the critic whose review sent its window back (`own_findings`, resolved at
# build time; the critic writes `work/test-code/critic-findings-<its dispatch>.md`, one per dispatch). A glob over the folder would
# name another window's findings beside it. ROLE_FILES holds this word, `_input_names` swaps it for the path or drops it.
OWN_FINDINGS = "work/test-code/critic-findings-<its critic's dispatch>.md"
# TR3-15: the advice the S5 critic reads is the file of the automator of ITS window (`advice_of`, resolved at build time), and the notes the
# next window must not rediscover are one file per dispatch beside the old single one (a glob, listed whole: notes are shared knowledge).
OWN_ADVICE = "work/advice-S5-<its automator's dispatch>.json"
NOTES_GLOB = "work/s5-notes/*.md"

# What the role reads beyond the stage's declared inputs (task-relative; `project:` is
# relative to qa-factory/; `plugin:` is relative to the plugin root of the copy that is running). A name ending in
# `/` is a directory. Derived from the Inputs tables of agents/*.md and the dispatch prompts of
# skills/qa-story/phases/s*.md. A `project:` or `plugin:` name is a DOOR (SC1-10): a document the role is not
# injected, or a template it must read, named with its path; `build` never trims a door line away.
ROLE_FILES = {
    "qa-scout": ["work/ticket-snapshot.json", "project:readiness.json", "project:strategy/project-profile.md"],
    "qa-requirements-tester": ["work/context-manifest.json", "work/impl-diff*.txt",
                               "plugin:references/templates/requirements-register.md",
                               "plugin:references/templates/understanding.md"],
    "qa-test-strategist": ["work/requirements-readiness.json", "understanding.md"],
    "qa-case-designer": ["work/context-manifest.json", "project:strategy/test-strategy.md"],
    "qa-case-critic": ["work/requirements-register.md", "understanding.md", "work/context-manifest.json"],
    "qa-automator": ["work/s5-notes.md", NOTES_GLOB, OWN_FINDINGS, PLAN_FILE],      # PLAN_FILE: the plan dispatch only; OWN_FINDINGS: its rework's critic
    "qa-code-critic": ["work/s5-notes.md", NOTES_GLOB, "work/automation-manifest.json", "work/test-code/", OWN_ADVICE, PLAN_FILE],
    "qa-runner": ["work/context-manifest.json", "work/s5-notes.md", NOTES_GLOB],
    "qa-failure-analyst": ["test-plan.md", "project:strategy/faq.md"],
    "qa-doc-scribe": ["work/bug-drafts/"],
    "qa-bug-reporter": ["work/bug-drafts/", "pipeline.json", "project:bugs/"],
    "qa-retro-analyst": ["work/retro-numbers.md", "work/retro-numbers.json", "work/context-manifest.json",
                         "project:strategy/test-strategy.md"],
}
# The readers of a `tried` table that are not a stage critic (t-1884 M-2, AR-22): (stage, role of the reader) -> ((stage, author), ...).
# The retro analyst reads the last S8 forms of the scribe and the bug reporter; the scribe's form is also linked from the gate B
# packet (`gate_brief`, "The long documents"). A form with no row here and no `acceptance_by` has no reader in the brief.
# The S9 form's `tried` is read by the NEXT story's retro (`prior_retro_lines`) and packed by qa-collect (collect-sets B16).
TRIED_READERS = {("S9", "qa-retro-analyst"): (("S8", "qa-doc-scribe"), ("S8", "qa-bug-reporter"))}
# Inputs the stage declares that this role does NOT read whole: the brief names the slice
# command instead of the file.
SLICE_INSTEAD = {
    "work/automation-manifest.json": "manifest_view.py --task <T> --window \"<ids>\" | --case <case id> | --summary",
    "work/test-plan.json": "manifest_view.py --task <T> --context --rows <TS ids> (the plan rows of your cases)",
}
# The context bundle is not in the table above (SC1-10): `file_lines` names it itself, ahead of SLICE_INSTEAD - its line
# view when that is current, else the JSON by the Grep/Read line below. No script is in either line, so the same
# text serves a role with a shell and a role without one.
# The view's own name is NOT spelled here: its one owner is `context_bundle.view_path` (AR-13), which `_bundle_view` asks.
BUNDLE_JSON = "work/context-bundle.json"
BUNDLE_BY_RANGES = "do not read whole - `Grep -n the case's requirement ids, then Read the range`"
# The same slices for a role with NO shell (TP2-2406 S4-6/S4-7, 14.10): `manifest_view.py` is a script, and the
# role guard (host_adapter.role_policy) lets a role without Bash run only one plain read command, so the S4 designer
# and critic obeyed the old line and were refused. The line names the FILE the script would have read and how to read
# part of it with the tools the role has; `{context}` is the story's S1 context manifest (what `manifest_view.py
# --context --rows` reads). A SLICE_INSTEAD name with no entry here would be a line that names no script, and the same
# line would serve both kinds of role.
SLICE_INSTEAD_NO_SHELL = {
    "work/automation-manifest.json": "do not read whole - `Grep -n` your case id in it, then Read the range "
                                     "(the conductor can cut a case, a window or the summary for you on request)",
    "work/test-plan.json": "do not read whole - `Grep -n` the TS ids of your cases in it, then Read the range; "
                           "the S1 observables of those rows are in {context}, Read it with offset/limit "
                           "(the conductor can cut either slice for you on request)",
}

# The tooling card, per role. Every line: `script args - what it answers`. The commands of
# the packages written in parallel (manifest_from_tests.py, probe_by_code.py) are named
# with the exact argument shapes their briefs fix.
RUN_MINE = ("run_suite.py --mine <case id>[,<case id>] [--purpose repair_verify] [--dispatch <ID>] "
            "[--node-id <file::func>] - the ordinary run of your open dispatch, the whole "
            "window in one pytest call; answer: a JSON summary {exit_code, execution_status, "
            "totals{passed,failures,errors,skipped}, failed[], error_head, summary_path} - the raw log "
            "stays in evidence/runs/<key>/ and is never read; status `reused`/`already_run` means "
            "nothing ran: read the summary")
# The door the run budget's `stand's version cannot be observed` answers name (run-budget.json):
# read-only, flags only, so it has no entry in role-commands.json - this card is where a role is told it.
STAND_PROBE = ("stand_health.py --probe --env <name> - is the stand answering (exit 0 healthy); the door when "
               "a run says the stand's version cannot be observed: `environment` in your digest, not your test")


def _flaky_cap() -> str:
    """How many FLAKY reruns the code allows a test, said as the analyst's card says it: the number
    is `contract.FLAKY_MIN_RERUNS`, one source (the code cap of execution_request is the same
    constant). Unreadable -> no number, never a copy of it."""
    try:
        import contract
        return f"up to {int(contract.FLAKY_MIN_RERUNS)}"
    except Exception:  # a card without the number is still true; a number copied here could drift
        return "a fixed number"
RUN_REQUEST = ("run_suite.py --request <work/requests/x.json> - a run that is not the ordinary one "
               "(`--template request` prints the skeleton, runs nothing); same answer shape")
RUN_DETAIL = ("run_suite.py --detail <test substring> --request <request.json> (or --task <T> --label "
              "<label>) - message and traceback of ONE failed test from the junitxml, no re-run")
MANIFEST_VIEW = "manifest_view.py --task <T> --window \"<ids>\" | --case <case id> | --summary - the manifest slice, never the file"
# t-2187 N6: the analyst's and the scribe's card line (the charter of the analyst names it); reads only, a hint, never a verdict
NEIGHBOURS = ("bug_neighbours.py --task-root <task root> - the failures, observations, rows and drafts that share a requirement, case, "
              "test file, code line or seen value; a hint, never a verdict")
PRECHECK = ("s5_precheck.py --task-root <task root> --dispatch <ID> [--json] - the check the stage runs on your "
            "handoff; answer: findings by family manifest|bindings|oracle|run_mapping|smell|environment, "
            "plus hints[] that never fail")
# The one sentence both plan cards say: the strategist's card with a shell (TOOLING) and the card of a role with none
# (TOOLING_NO_SHELL) differ only in what comes before and after it.
PLAN_WRITTEN_ONCE = ("written whole exactly once, when it first appears: after that a Write over it is "
                     "refused, because 59 whole rewrites of it cost 525,812 tokens of arguments on this story and "
                     "two booleans cost $16.53.")
# The S2 tester reads the implementation diff as EVERY changed line of EVERY hunk (the lesson of TP1-13797: a tester
# that skimmed the diff lost every requirement the code carries). `diff_pass` cuts a hunk at 40 changed lines unless told
# otherwise; this is the ceiling that says "otherwise". Above it `diff_pass` still names the range it left out
# ("read <path> lines a-b") - a generated file that large is read by range, never in silence.
DIFF_ALL_LINES = 100_000
TOOLING = {
    "qa-scout": [
        "ticket_adapter.py get|children|diff <KEY> [--json] [--ticket-file <path>] - the read cascade (diff takes --old <path> --new <path> in place of <KEY>)",
        "ticket_adapter.py peek <KEY> --output <task root>/work/source-inventory.json --summary - a mentioned ticket's first look, recorded in the inventory unassessed",
        "ticket_adapter.py assess --output <task root>/work/source-inventory.json --source-id <id> --relevance relevant|not_relevant|unknown --reason <reason> --assessment-ref <path> --summary - the verdict on a peeked source",
        "ticket_adapter.py collect <KEY> --output <task root>/work/source-inventory.json --relation task|subject|parent|normative|referenced --summary - the full read of a relevant source; --relation has no default",
        "ticket_adapter.py inspect --output <task root>/work/source-inventory.json --source-id <id> --attachment-id <id> --evidence-ref <path> --inspection-status read|partial|unavailable --summary - one attachment's receipt (external media: --media-url <url> [--local-ref <path>] in place of the attachment pair)",
        "ticket_adapter.py query --path <API path with its query> --output <task root>/work/source-inventory.json [--save <file>] - a GET of the configured tracker API you choose (a filter's search, a project's issues); the answer goes to a file, one summary line on stdout",
        "ticket_adapter.py record-source --output <task root>/work/source-inventory.json --ref <url|path> --file <file> --relation subject|parent|normative|referenced --summary - a text you read by another route becomes a source",
        "diff_pass.py --diff <work/impl-diff*.txt> [--files-only | --file <path>] - the changed files and hunks in one call, never the diff whole",
        "vcs_evidence.py --url <MR URL> --output qa-factory/artifacts/<T>/work/sources/<source id>/mr-<iid>.json - the merge request whole into the file, a summary on stdout; "
        "a file already at that path is the driver's receipt: Grep it, never collect again; its `status` says whether it was read; "
        "`mr-<iid>-git.md` next to it is the driver's partial route; record a new one with ticket_adapter.py inspect --output <inventory> "
        "--source-id <source id> --media-url <MR URL> --inspection-status read --local-ref sources/<source id>/mr-<iid>.json; never `glab mr view` into your context",
        "context_bundle.py --manifest <task root>/work/context-manifest.json --output <task root>/work/context-bundle.json --root <task root> - builds the bundle from your manifest; --root is where work/source-inventory.json is read and where a relative known_paths path or diff_path resolves (give absolute paths or paths relative to <task root>); a refusal names the manifest field",
        "context_bundle.py --validate <work/context-bundle.json> - the bundle's own validator, run before your digest",
        "env_probe.py --env <name> - the stand's liveness and login scheme, names only",
    ],
    "qa-requirements-tester": [
        f"diff_pass.py --diff <work/impl-diff*.txt> --files-only, then --file <path> --max-lines {DIFF_ALL_LINES} for EVERY file it lists, in every impl-diff - "
        "every changed line of every hunk, numbered in the new file (a removed line is numbered at its place in the new file, so a `diff:-<path>:<line>` reference carries that number); never Read a diff whole",
        "artifact_producer.py prepare --kind readiness --task-root <task root> - the readiness skeleton to fill",
        "artifact_producer.py validate-batch --task-root <task root> --input <batch.json> - checks the handoff as one unit; batch.json is {\"artifacts\": [{\"kind\": \"readiness\", \"path\": \"work/requirements-readiness.json\", \"data\": <the artifact object>}]}",
        "artifact_producer.py publish --kind readiness --task-root <task root> --path work/requirements-readiness.json --input <file> [--expected-hash <sha256>] - the atomic publication (--expected-hash only over a file that exists)",
        "sizing.py --task <T> - the size, computed by code from the register; never chosen by hand",
        # The charter names this script only as `${CLAUDE_PLUGIN_ROOT}/scripts/...`, which nobody expands (B-014, FR-15; K9).
        "branch_accounting.py --units [--unhomed] [--page <N>] --task <T> - every sentence of the story's own text, 200 to a page "
        "(`--unhomed`: those with no home yet); `--attachments --task <T>` lists the files of the story and its kept tickets with the call that opens each",
    ],
    # TP2-2406 S3-3 (15.10): this entry is read only by a strategist whose `tools:` line holds Bash (the card is
    # chosen by `role_has_bash`); the shipped strategist has none, so it reads TOOLING_NO_SHELL below, which names
    # Edit. The two commands stay for a strategist given a shell; they are not a door of the shipped role.
    "qa-test-strategist": [
        "planning_contract.py <task root>/work/test-plan.json --kind plan - the plan's validator; only invalid rows come back",
        "plan_row.py --task <T> --row <TS-n> --set <field>=<value> - ONE field of ONE row, in place; "
        "--add-row <json|file> appends ONE row you wrote (its own id, every field the other rows carry). "
        "The plan is " + PLAN_WRITTEN_ONCE + " test-plan.md is your words for the human: change its lines with Edit",
    ],
    # qa-case-designer and qa-case-critic: no entry - they have no shell, see TOOLING_NO_SHELL.
    "qa-automator": [
        RUN_MINE, RUN_REQUEST, RUN_DETAIL,
        "manifest_from_tests.py --task <T> --dispatch <ID> --file <test file> [--file ...] [--dry-run] [--json] - reads "
        "`@pytest.mark.qa(case=\"<case id>\", then=[1, 2], partition=\"tc003-zero-matches\", obligations=[\"TS-3-O1\"])` "
        "on your test functions (a parametrize id is the partition when none is given) and "
        "`@pytest.mark.qa_unresolved(case=\"<case id>\", reason=\"impossible\", detail=\"...\")` at module or function level, "
        "builds the manifest fragment (instances, covers, partitions, obligation_ids, case_version_links, then_bindings) "
        "and calls manifest_put.py once; answer: what it wrote. The marker also takes `shape=` and `note=`; "
        "the parameter-list module is found through the test file's import; `--file` is for what it cannot find",
        "manifest_put.py --task <T> --fragment <file.json> - the hand-written fragment door; merges by case and instance, never Write the manifest",
        PRECHECK, MANIFEST_VIEW, STAND_PROBE,
    ],
    "qa-code-critic": [
        "probe_by_code.py --task <T> --dispatch <ID> --test \"<file>::<test name>\" --instance <IID> [--oracle <file>::<function>] [--at <line>] [--release-copy <file>] [--json] - "
        "the default probe, every check of every new/changed test, one call per instance: with no --at it walks every check, and each check needs an entry in "
        "work/probe-models/<ID>.json; --at and --oracle "
        "select rows on the same road and need the entry too; --plan first: it prints the model file, the entry shape and the run count, and runs nothing; a plan of more than 3 rows runs in the background; "
        "`plan_unfinished`: the same call continues it; the live receipt is written only when every owed check is proved. <test name> is [Class::]<func>[<param>] for pytest, "
        "the method or title in any other language with an `assertion_probes` entry. "
        "It mutates the check, restores the "
        "file, writes work/probes/<IID>.json {verdict intended_failure|no_failure|wrong_location|incomplete, "
        "location, reason, failure_kind, evidence_ref} with a row per check; "
        "`incomplete`, and a refusal that names a factory data gap or a killed probe's unresolved copy, is `tooling` (say so in your digest), never a verdict on the test; "
        "`--release-copy <file>` alone drops that copy, only after the test's author has settled the file; "
        "a repeat on the same bytes and entries is answered already_probed and nothing runs",
        "red_sandbox.py --probe --request <mutations.json> --task-root <task root> --repo <root> [--dispatch <ID>] - only when you doubt the "
        "check looks at the product; it proves the one check it names, you name it with a `product` entry in the model file, "
        "the others stay owed; say why in the findings; "
        "two mutations of one file go in one request only as ONE combined replacement (B-314); incomplete|not_executed is `tooling`, "
        "never a verdict on the test",
        RUN_DETAIL, MANIFEST_VIEW, STAND_PROBE,
        "s5_precheck.py --task-root <task root> --dispatch <ID> --json - read-only: what code already checked; do not re-report it",
    ],
    "qa-runner": [
        RUN_MINE.replace("[--purpose repair_verify] ", ""), RUN_REQUEST,
        "run_suite.py --schedule <schedule.json> - several typed requests at or above the parallel threshold",
        RUN_DETAIL,
        "run_suite.py --recover <KEY> --task <T> - inspect one interrupted durable job; never relaunches it",
        "env_probe.py --env <name> - the stand before a block; a failed line is the `env_blocked[]` row's witness",
        STAND_PROBE,
        "manual_evidence.py prepare|validate|write-block --task-root <task root> --input <file> - the manual-agent block",
        "finalize_task.py <task root> - reduces every run block into work/run-report.json (positional argument, no flag)",
        MANIFEST_VIEW,
    ],
    "qa-failure-analyst": [
        "artifact_producer.py prepare --kind triage --task-root <task root> - the triage skeleton to fill",
        "artifact_producer.py validate-batch --task-root <task root> --input <batch.json> - checks the handoff as one unit; batch.json is {\"artifacts\": [{\"kind\": \"triage\", \"path\": \"work/triage.json\", \"data\": <the artifact object>}]}",
        "artifact_producer.py publish --kind triage --task-root <task root> --path work/triage.json --input <file> [--expected-hash <sha256>] - the publication (--expected-hash only over a file that exists)",
        RUN_REQUEST + "; FLAKY (S7 only): each isolated rerun of that ONE test is its own `purpose: flaky_diagnostic` "
        f"request, {_flaky_cap()} per test and code bytes; the next one is refused",
        RUN_DETAIL, MANIFEST_VIEW, STAND_PROBE,
        "red_sandbox.py --diagnostic --request <diag.json> --task-root <task root> --repo <root> [--dispatch <ID>] - ONE run of a "
        "test without its red assert ('One red, one triage'), in a copy; writes evidence/diagnostic-<label>.json, never your file; a second "
        "run of the same test and bytes is refused",
        # The charter names this script only as `${CLAUDE_PLUGIN_ROOT}/scripts/...`, which nobody expands (B-014): the card
        # is where the role finds the path and the form (F4, test_brief_pack_roles K9).
        "bug_snapshot.py --root <project> --input <snapshot.json> - persists bug evidence you already hold (references/metrics-contract.md); fetches nothing",
        "bug_records.py open-bugs --task-root <task root> --draft <draft.json> - the open bugs of the story's sources and, in `match`, the one your draft extends; reads only",
        NEIGHBOURS,
    ],
    "qa-doc-scribe": [
        "ledger.py <task root> - the checks ledger, by code, first",
        "traceability.py --task <T> --write | --render | --check - the R/TC roll-call; `--render` "
        "prints the appendix the report pastes, `--check` exits 1 on a requirement or case with no row",
        "report_facts.py --task <T> --write | --check - renders the code-owned blocks of test-report.md; `--check` must exit 0 before your handoff",
        NEIGHBOURS,
        "check_coverage.py --write - regenerates the coverage map",
        "check_delivery.py <task root> [--json] - the delivery verdict, by code",
        "delivery_summary.py --task-root <task root> [--open-items] - the factual delivery projection",
        MANIFEST_VIEW,
    ],
    "qa-bug-reporter": [
        "artifact_producer.py prepare --kind bug --task-root <task root> - the bug skeleton; the file goes to project bugs/",
        "artifact_producer.py validate-batch --task-root <task root> --input <batch.json> - checks every selected bug as one unit; batch.json is {\"artifacts\": [{\"kind\": \"bug\", \"path\": \"bugs/BUG-<id>.md\", \"data\": <the artifact object>}]}",
        "artifact_producer.py publish --kind bug --task-root <task root> --path bugs/BUG-<id>.md --input <file> [--expected-hash <sha256>] - the publication of each bug (--expected-hash only over a file that exists)",
        "external writes are NOT yours: a proposal file under work/proposals/ (external-writes.md); external_writes.py runs after gate B",
    ],
    "qa-retro-analyst": [
        "retro_numbers.py --task <T> - already run; every number is in work/retro-numbers.md and .json",
        "estimate_record.py --task <T> --facts <file> - the idempotent S9 estimate record",
        "project_decisions.py --root <project> add-finding - a finding for qa-factory/factory-backlog.md",
    ],
}

# The rows of the tooling card that only the PLAN dispatch of S5 (`purpose: s5_plan`) is handed (SC1-14 C2): added to TOOLING's rows
# for that dispatch, so the card of a window and of the earlier form is byte for byte what it was.
TOOLING_PLAN = {
    "qa-automator": [
        "s5_plan.py --task <T> --check - the exit check of the plan dispatch: names EVERY gap of work/s5-plan.json at once "
        "(`REJECT - N finding(s)` and exit 1, or `OK`); run it before your digest",
        "s5_plan.py --task <T> --window <N> [--out <file>] - the plan's slice for window N, as the controller will cut the windows (read-only)",
    ],
    "qa-code-critic": [
        "s5_plan.py --task <T> --check - what code already found in the plan; do not re-report it",
        "s5_plan.py --task <T> --window <N> [--out <file>] - the plan's slice for window N, as the controller will cut the windows (read-only)",
    ],
}

# The device row of the manual card; `<APP_DOC>` is filled with the plugin copy's ABSOLUTE path of the document when the card is built
# (AR-8, FR-15): a role in a project's cwd has no `references/`.
TOOLING_MANUAL_APP = {      # EP1-41f (AR-11): handed only when the project describes a device stand (`hands: driver`); the web card is as it was
    "qa-runner": [
        "manual_capture.py app --task-root <task root> --case <C> --steps-file <S> [--surface <id>] [--attempt aN] - the capture of one case on the "
        "device stand; the steps and the forms are in <APP_DOC> (read it first); no `--as`, no `goto`",
    ],
}
# The rows only the card of a MANUAL runner block is handed (HF5-5, t-1540; fix round t-1550 F2: the automated runner's card is
# byte for byte what it was, spec 5.5 item 3, FR-56/AR-11). references/manual-evidence.md has the forms; a manual block's brief
# also carries `## The stand` (manual_stand_lines): the stand's addresses and the account names.
TOOLING_MANUAL = {
    "qa-runner": [
        "manual_capture.py ui --task-root <task root> --case <C> --steps-file <S> [--as <account>] [--attempt aN] [--session <actor>]",
        "manual_capture.py http --task-root <task root> --case <C> --method <M> --url <U> [--body-file <F>] [--as <account>] [--attempt aN]",
        "manual_evidence.py build --task-root <task root> --case <C> --result pass|fail|inconclusive --actual \"<what you saw>\" --masked "
        "[--attempt aN] [--limitation \"<words>\"] [--then-quote|--then-seen \"<n>=<words>\"]... [--then-unreached <n>]... [--with-attempt aN]... [--observations-file <file>]",
        "manual_evidence.py rejudge --task-root <task root> --case <C> --of-attempt aN --result pass|fail|inconclusive --actual \"<what you saw>\" --reason \"<why>\" "
        "[--then-quote|--then-seen \"<n>=<words>\"]... [--then-unreached <n>]... [--completion <path>] [--limitation \"<words>\"]",
        "exploratory_findings.py add --task-root <task root> --by <ID> --kind observation|unresolved_question|coverage_gap --title \"<t>\" --statement \"<what you saw>\" "
        "--why-not-a-bug \"<w>\" [--evidence <captured file>]... [--question \"<q>\" --owner-role <r>] [--missing-prerequisite \"<p>\"] - a doubt that is not a violated oracle, "
        "recorded when you meet it",
    ],
}

def _has_device_stand(cfg: dict) -> bool:
    """True when an `environments[]` row names a `surface` whose row of references/surfaces.json is driven by a device driver. A
    project with no `surface` anywhere never reads the table (the web card does not change); a table that cannot be read says
    nothing here - the line is simply not handed, and the readiness check reports the table (`surfaces: unknown`)."""
    try:
        import surfaces
        return bool(surfaces.device_stands(cfg))
    except ValueError:
        return False


# The card of a role with NO shell (TP2-2406 S4-6/S4-7, 14.10; FR-2, FR-56): every entry of TOOLING above is a
# command, and a role without Bash is refused every one of them. Its head says what it can do; its lines say who runs
# what it would have run, so no line is a script to run. plan_row.py and planning_contract.py are helpers the
# strategist can do without: Edit changes a row (the rewrite guard's own refusal names it, skills/qa-story/phases/s3.md
# appends rows with it), and the plan is checked by code when it is saved (validate_artifacts.py) and again at the S3
# exit gate (references/stages.json detectors).
#
# ONE head for both hosts - the brief is built without knowing which host reads it: the Claude tools first, then
# `host_adapter.CODEX_DESKTOP_TOOLS` verbatim, the one text of what a Codex Desktop child has instead (no Read, Grep,
# Glob, Write or Edit exists there, and the card used to name only those).
NO_SHELL_HEAD = ("A role with no shell reads on Claude Code with Read, Grep and Glob and writes with Write and Edit. "
                 + CODEX_DESKTOP_TOOLS + " "
                 "The scripts of the plugin are run for you by the orchestrator and the exit gate; the plugin's "
                 "scripts are not read.")
TOOLING_NO_SHELL = {
    "qa-test-strategist": [
        "the plan is checked by code when you save it and again at the exit gate; only the invalid rows come back to you",
        "work/test-plan.json is " + PLAN_WRITTEN_ONCE + " Change a row, or append one you wrote, with Edit - "
        "one row's own lines at a time. "
        "test-plan.md is your words for the human: change its lines with Edit",
    ],
    "qa-case-designer": [
        "the pins of your cases and the roll-call are made by the orchestrator and the exit gate after you hand over; "
        "you write the case files",
    ],
    "qa-case-critic": [
        "your findings file is read by code at the exit gate (the roll-call); you run nothing",
    ],
}


# The rules the code will apply to this handoff, said to the role BEFORE the work instead of
# after it (factory rule FR-38). The cards are data - references/ahead-cards.json - so a check
# and the sentence that announces it are changed in one place, by whoever changes the check,
# with no Python edit (FR-13). A role with no card gets no such section.
def digest_template_lines(role: str, stage: str, dispatch_id: str, dispatch, path_override: str = "") -> list:
    """F11 (t-1701 D5-C): the section `## Your final message` - the digest form of THIS dispatch, its scope ids already rows.
    The ids come from the gate's own reader (`exit_gate._scope_of`, so the template and the gate never disagree on the scope)
    and the path from the stage's witness (`exit_gate.witness_gates()`); a `project:` witness is no task-relative path, so the
    path line is the placeholder. A role outside `role_digest.ROLE_ITEM`, or any failure, gives [] - a brief is never lost to it.
    Advice only: the gate's check does not read the template."""
    try:
        import exit_gate
        import role_digest
        if role not in role_digest.ROLE_ITEM:
            return []
        scope = exit_gate._scope_of(role, dispatch if isinstance(dispatch, dict) else None)
        path = str(exit_gate.witness_gates().get(role) or "")
        path = "" if path.startswith("project:") else path
        path = path_override or path       # a purpose whose handoff is another file names that file (the first look)
        body = role_digest.template(role, stage, dispatch_id, scope, path)
        return ["", "## Your final message", "", "Copy this, fill every `<...>`; nothing before the first line:",
                "```", *body.splitlines(), "```"]
    except Exception:
        return []


def ahead_card(role: str) -> str:
    """The card this role is handed, or "" when the table names none for it."""
    cards = hooklib.load_ref_json("ahead-cards.json").get("cards") or {}
    entry = cards.get(role)
    return str((entry or {}).get("text") or "").strip() if isinstance(entry, dict) else ""


# The roles that write a case id: the designer names the file and its `id:`, the automator copies
# the id into `case=`. Their cards and charters say "in the form your brief names", so the brief
# has to name it (B-013: on TP1-13877 the strategy wrote TP1-13877_TC_001 while every text
# the roles read said TC-NNN, and the automator spent about 35 calls reading factory code before it halted).
CASE_FORM_ROLES = ("qa-case-designer", "qa-automator")
CASE_FORM_NONE = "Case id form: TC-001 (the project records no form)"
CASE_FORM_PROBLEMS_SHOWN = 3
CASE_FORM_LINE_CHARS = 300


def _clip(text: str, limit: int) -> str:
    """One line of at most `limit` characters, the middle replaced by `...` (head and tail kept)."""
    one = " ".join(str(text).split())
    if len(one) <= limit:
        return one
    half = (limit - 3) // 2
    return one[:half] + "..." + one[-half:]


def case_form_lines(task: str, task_root: Path, role: str) -> list:
    """The `Case id form:` line of a designer/automator brief, and the config's own problems.

    The example is built for THIS story's ticket from the first form in force, so the role copies
    a shape instead of reading a template. A missing, empty or invalid key falls back to the
    default `TC-001` and says so; an invalid key also prints what is wrong with it. Never raises:
    a brief without the line is the old brief, and the brief is a courtesy (story_step prints a
    failure here as a note, never a refusal)."""
    if role not in CASE_FORM_ROLES:
        return []
    try:
        import case_forms
        import contract
        cfg = contract.case_config(task_root)
        configured = case_forms.forms(cfg)[:-1]  # the last form is always the default TC-{nnn}
        line = (f"Case id form: {case_forms.example(task, cfg)} (config.case_id_form; {configured[0]})"
                if configured else CASE_FORM_NONE)
        found = case_forms.problems(cfg)
    except Exception:
        return [CASE_FORM_NONE]
    # Each line is capped: the head is never shrunk, and a key is the project's free text (a 100 KB
    # value made a 102 KB brief when its problem was printed whole). The MIDDLE is cut, because a
    # problem sentence names the entry first and says what is wrong with it last.
    out = [_clip(line, CASE_FORM_LINE_CHARS)]
    for problem in found[:CASE_FORM_PROBLEMS_SHOWN]:
        out.append(_clip(f"- {problem}", CASE_FORM_LINE_CHARS))
    if found:
        more = len(found) - CASE_FORM_PROBLEMS_SHOWN
        out.append("- that entry is ignored, so the form above is the one in force"
                   + (f"; {more} more problem(s) are not shown" if more > 0 else ""))
    return out


# TP2-2406 S5, 17.10.2026: the qa-automator halted twice (`S5-qa-automator-1`, `-2`) on a NAME comparison. Its
# charter said "verify the branch the orchestrator recorded" and named no carrier; the only branch name in its inputs
# was the merge request's source branch in context-manifest.json, and the checkout (the one gate A approved) was on
# another branch at the same commit. The brief now STATES the recorded checkout and the implementation commit, so the
# role compares commits (an identity, FR-16) and never names (FR-15, FR-38). The roles told this are the roles whose
# injected lifecycle slice carries the section below (references/execution-lifecycle.md markers + inject-map.json),
# not a pair typed here; the line and that section say the same words (FR-10).
LIFECYCLE_DOC = "execution-lifecycle.md"
LIFECYCLE_SECTION = "Before the first write"
BRANCH_WHY_CHARS = 200                   # a record's `why` / `late_why` is free text; the head must stay bounded
NEVER_SWITCH = "never create or switch a branch"
ANCESTOR = "git merge-base --is-ancestor {} HEAD"
BRANCH_UNBUILT = ("Branch check: the line could not be built ({}); compare the implementation commit in "
                  f"context-manifest with `git rev-parse HEAD`, never a branch name; {NEVER_SWITCH}.")
BRANCH_NOTHING = ("Branch check: nothing was recorded - neither a branch at S0 nor an implementation commit; "
                  f"work on the checkout as it stands and say so in your digest; {NEVER_SWITCH}.")


def _lifecycle_roles() -> set:
    """The roles told the branch check: those injected `execution-lifecycle.md` (the inject map) whose slice of it
    carries the section "Before the first write" (contract_slices.parse / Section.wants on the source's markers) -
    the line and the contract text it repeats reach the same roles (FR-10, FR-13: a role added to the map or to
    the marker is told without a code change). An unreadable map or source is {} - the line is a courtesy, never
    a refusal."""
    try:
        import contract_slices
        roles = hooklib.load_ref_json("inject-map.json").get("roles")
        if not isinstance(roles, dict):
            return set()
        _lead, sections = contract_slices.parse(hooklib.ref(LIFECYCLE_DOC).read_text(encoding="utf-8"))
        carrying = [s for s in sections if s.title == LIFECYCLE_SECTION]
        return {role for role, paths in roles.items()
                if isinstance(paths, list) and any(isinstance(p, str) and p.endswith("/" + LIFECYCLE_DOC) for p in paths)
                and any(s.wants(role) for s in carrying)}
    except Exception:
        return set()


def _one_line(value) -> str:
    """A record's or manifest's text on one line: only the line breaks go (the line is ONE paragraph), the
    words stay as given - a branch is never shortened here (git bounds it)."""
    return re.sub(r"[\r\n]+", " ", "" if value is None else str(value)).strip()


def _sha12(value) -> str:
    return _one_line(value)[:12]   # a commit shorter than 12 characters is printed as given


def _implementation_clause(entries: list, head: str) -> str:
    """What the role compares: each implementation commit with HEAD. `head` is "" when S0 recorded none, and HEAD
    then means the role's own `git rev-parse HEAD`. A commit equal to HEAD is said to be HEAD; any other is owed a
    PROOF that HEAD carries its change - ancestry (the role's own `merge-base --is-ancestor`) proves it at once, but
    its failure is not the halt: a squash or a rebase leaves the change without the commit, and a commit of another
    repository is unknown to this one (exit 128). The role then proves the change by content against the entry's
    own checkout and halts only when the change is absent. brief_pack decides none of it and makes no git call. A
    shortened or differently spelled commit is never equal here, so the error goes toward the role's proof, not
    toward a pass (FR-59)."""
    rows = [(_one_line(e.get("commit")), _one_line(e.get("repo") or e.get("repo_id"))) for e in entries]
    single = len(rows) == 1

    def is_head(commit: str) -> bool:
        return bool(head) and commit.lower() == head.lower()

    owed = [commit for commit, _repo in rows if commit and not is_head(commit)]
    not_head = "is not this HEAD" if head else "is not known to be this HEAD"
    if single:
        commit, repo = rows[0]
        if not owed:
            return f"the implementation commit {_sha12(commit)} (context-manifest) is this HEAD"
        return (f"the implementation commit {_sha12(commit)} (context-manifest{', repository ' + repo if repo else ''}) "
                f"{not_head}{'' if head else ' (HEAD is your own `git rev-parse HEAD`)'}: HEAD must carry its change - "
                + _change_proof(owed, True))
    parts = [(f"{_sha12(commit)} ({repo or '?'}) {'is this HEAD' if is_head(commit) else not_head}") if commit
             else f"{repo or '?'}: no commit recorded" for commit, repo in rows]
    clause = "the implementation commits (context-manifest): " + "; ".join(parts)
    if owed:
        clause += (f". The commits that are not {'' if head else 'known to be '}HEAD"
                   f"{'' if head else ' (HEAD is your own `git rev-parse HEAD`)'}: HEAD must carry their change - "
                   + _change_proof(owed, False))
    return clause


def _change_proof(owed: list, single: bool) -> str:
    """The proof of a change, the same words in the line, the charter and the lifecycle slice: ancestry at once,
    content when ancestry fails, a halt only when the change is absent."""
    ancestry = " / ".join(f"`{ANCESTOR.format(commit)}`" for commit in owed)
    return (f"{ancestry} exit 0 proves it at once; when it does not (a squash, a rebase, or a commit this repository "
            f"does not know), prove it by content against {'that entry' if single else 'each entry'}'s own checkout; "
            f"halt only when {'the' if single else 'a'} change is absent")


def branch_check_line(task_root) -> str:
    """The `Branch check:` paragraph of an automator brief: the checkout the orchestrator recorded at S0
    (`state/test-repo-base.json`: branch and HEAD) and the implementation commit(s) of `work/context-manifest.json`,
    both read as files - NO git call; the role runs `git rev-parse HEAD` and compares commits, never branch names.
    The branch is DESCRIBED ("recorded checkout"), never asked for: the branch name proves nothing (I2).

    An unknown is named, never passed as a fact (FR-41, FR-59): no record, a record without a branch (git not ok,
    or ok with no HEAD), a manifest with no commit each get their own words. Never raises."""
    try:
        import handoff_check
        import test_repo_base
        record = test_repo_base.load(task_root)
        base_rel = f"state/{test_repo_base.FILE_NAME}"   # where the writer puts it, under the task root
        root = Path(task_root)
        entries = [e for e in handoff_check.implementation_entries(_load(root / "work" / "context-manifest.json"))
                   if isinstance(e, dict)]
        source = _one_line(_load(root / "pipeline.json").get("implementation_source")) or "unknown"
        git_state = _one_line(record.get("git")) if record else ""
        head = _one_line(record.get("head")) if git_state == "ok" else ""
        has_commit = any(_one_line(e.get("commit")) for e in entries)
        if head:
            branch = _one_line(record.get("branch"))
            if branch == "(detached)":
                where = f"recorded checkout: detached at {_sha12(head)} (recorded at S0 in {base_rel})"
            elif branch:
                where = f"recorded checkout `{branch}`@{_sha12(head)} (recorded at S0 in {base_rel})"
            else:
                where = f"recorded checkout: no branch, HEAD {_sha12(head)} (recorded at S0 in {base_rel}, which names no branch)"
            if record.get("late") is True:
                where += (f" (recorded late: "
                          f"{_clip(_one_line(record.get('late_why')), BRANCH_WHY_CHARS) or 'no reason recorded'})")
            if not has_commit:
                return (f"Branch check: {where}; the manifest names no implementation commit (source {source}), so "
                        f"there is no commit to prove: work on the checkout as it stands and say so in your digest; "
                        f"compare commits, never branch names; {NEVER_SWITCH}.")
        else:
            branch = ""
            if not has_commit:
                return BRANCH_NOTHING
            if record is None:
                why = f"{base_rel} is absent or unreadable"
            elif git_state == "ok":
                why = "git: ok, but the record names no HEAD"
            else:
                why = (f"git: {git_state or 'unknown'} - "
                       f"{_clip(_one_line(record.get('why')), BRANCH_WHY_CHARS) or 'no reason recorded'}")
            where = f"no branch was recorded at S0 ({why})"
        # The manifest's branch is the merge request's source branch (!57), a different name for the same commit:
        # said once, so the role never reads it as the branch to be on.
        others = list(dict.fromkeys(b for b in (_one_line(e.get("branch")) for e in entries) if b and b != branch))
        if len(others) == 1:
            aside = f"`{others[0]}` in the manifest is the merge request's source branch, not a branch to switch to. "
        elif others:
            aside = (", ".join(f"`{b}`" for b in others)
                     + " in the manifest are merge request source branches, not branches to switch to. ")
        else:
            aside = ""
        return (f"Branch check: {where}; {_implementation_clause(entries, head)}. {aside}"
                f"Compare commits, never branch names; {NEVER_SWITCH}.")
    except Exception as exc:
        return BRANCH_UNBUILT.format(type(exc).__name__)


# The tests that went red and later passed on changed code (B-194) are handed to the code critic
# in the head, which is never shrunk: the critic owes one verdict per pair, and a line that the
# trimming below could drop would be a pair nobody judges. The list is the detector's own
# (`s5_precheck.expectation_changes`, the one the pointer names), never a second reading of the runs.
EXPECTATION_ROLE = "qa-code-critic"
EXPECTATION_NAMES_SHOWN = 8
EXPECTATION_NAME_CHARS = 160   # a test name is the project's free text; the head must stay bounded
EXPECTATION_WHY_CHARS = 300
EXPECTATION_POINTER = "`s5_precheck.py --json` -> `expectation_changes`"
EXPECTATION_GONE = " (gone after its red run)"
EXPECTATION_COULD_NOT_JUDGE = "could_not_judge"  # a verdict word of handoffs/vocabulary.yaml
# The ONE road for that verdict, in the words the vocabulary, the rubric and the critic's charter use.
EXPECTATION_COULD_NOT_JUDGE_ROAD = "the conductor records the window as unresolved with the reason"


def _verdicts() -> list:
    """The closed list of critic verdicts (`handoffs/vocabulary.yaml`, FR-13). Unreadable -> [], so
    that no pair reads as judged on a list nobody could load (the error goes toward "still to judge")."""
    try:
        import handoff
        return handoff.allowed("expectation_change_verdicts")
    except Exception:
        return []


def expectation_change_lines(task_root: Path, role: str, dispatch_id: str) -> list:
    """The head line(s) of a code critic's brief about tests changed after a red run.

    Only for `qa-code-critic`; one call of the detector, read-only (FR-45). The line counts the
    OWED pairs that still need a verdict and names up to EXPECTATION_NAMES_SHOWN of them (the
    detector's own `function` key; an orphaned red - a test gone after its red run - says so in
    words); more than that: "and N more" and the pointer to the full list; pairs that already carry
    a record with a verdict are counted apart, not as work. Two more groups get a line of their own,
    never the "to judge" count: pairs a person's word passed at the S5 exit (visible, nothing to
    record - P13) and pairs the critic recorded `could_not_judge` for (the conductor's move). No owed
    pair in any of the three groups -> no line.
    A detector that could not measure gets ONE line saying so and why - never "none" (FR-41); the
    brief is built either way, because it is a courtesy and never a refusal."""
    if role != EXPECTATION_ROLE:
        return []
    try:
        import contract
        import s5_precheck
        manifest = _load(contract.artifact(task_root, "automation-manifest.json"))
        scope = s5_precheck.scope_cases(task_root, manifest, dispatch_id)
        found = s5_precheck.expectation_changes(task_root, scope, manifest)
        # which pairs a person's word passed at the S5 exit (the helper adds a reason to `unmeasured`
        # when it cannot tell, and then marks none: the pair stays "to judge")
        s5_precheck.word_passed_pairs(task_root, found, scope)
        owed = [p for p in found.get("pairs") or [] if isinstance(p, dict) and p.get("owed")]
        unmeasured = [str(w) for w in found.get("unmeasured") or [] if w]
    except Exception as exc:
        owed, unmeasured = [], [f"the measurement itself failed ({type(exc).__name__}: {exc})"]
    lines = []
    verdicts = _verdicts()
    judged_count = 0
    todo, by_word, unjudged = [], [], []
    for pair in owed:
        record = pair.get("record")
        said = str(record.get("critic_verdict") or "") if isinstance(record, dict) else ""
        if said == EXPECTATION_COULD_NOT_JUDGE and said in verdicts:
            unjudged.append(pair)  # the critic's word stands; the next move is the conductor's
        elif said in verdicts:
            judged_count += 1
        elif pair.get("passed_by_word") is True:
            by_word.append(pair)   # a person already answered: visible here, nothing to record
        else:
            todo.append(pair)

    def named(pairs: list) -> str:
        names = [_clip(str(p.get("function") or "?"), EXPECTATION_NAME_CHARS)
                 + (EXPECTATION_GONE if p.get("orphan") else "") for p in pairs[:EXPECTATION_NAMES_SHOWN]]
        more = len(pairs) - EXPECTATION_NAMES_SHOWN
        return ", ".join(names) + (f", and {more} more - the full list: {EXPECTATION_POINTER}" if more > 0 else "")

    if todo:
        names = named(todo)
        line = f"Tests changed after a red run - {len(todo)} to judge: " + names
        line += ("." if len(todo) > EXPECTATION_NAMES_SHOWN else
                 f". The full list, with its fields: {EXPECTATION_POINTER}.")
        line += (" Per pair: `function`, `red_attempt`, `green_attempt`, `red_evidence`, `orphan`, `record`. "
                 "Your verdict is one `critic_verdict` on that record, patched through "
                 f"`manifest_put.py --task {task_root.name} --fragment <file.json>` "
                 "(the record's `function` or `functions` and both attempts name it).")
        if judged_count:
            line += f" {judged_count} more already carry a verdict and are not in this count."
        lines.append(line)
    if by_word:
        lines.append(f"Tests changed after a red run - {len(by_word)} passed by a person's word - nothing to "
                     f"record: {named(by_word)}. Write a `test_defect` finding if the test was fitted to the code.")
    if unjudged:
        lines.append(f"Tests changed after a red run - {len(unjudged)} could not be judged - "
                     f"{EXPECTATION_COULD_NOT_JUDGE_ROAD}: {named(unjudged)}.")
    if unmeasured:
        lines.append("whether tests were changed after a red run could not be measured: "
                     + _clip("; ".join(unmeasured), EXPECTATION_WHY_CHARS))
    return lines


# The live checks the predicate requires, handed to the code critic in the head (same place and same
# reason as the expectation line above: the head is never shrunk). `work/probe-debt/<dispatch>.json` lists only an
# instance that already has a probe record, so an instance nobody has probed yet was missing from the
# critic's first view of what it owes; the charter sentence about that file stays as it is. The list is
# the predicate's own (`proof_level.proof_required`), never a second reading of the manifest's fields.
PROOF_ROLE = "qa-code-critic"
PROOF_NAMES_SHOWN = 8
PROOF_NAME_CHARS = 160   # a test name is the project's free text; the head must stay bounded
PROOF_WHY_CHARS = 300
PROOF_LIST = "work/automation-manifest.json"


def _proof_name(row: dict) -> str:
    """`<file>::<instance id>` of a manifest row - the two things `probe_by_code.py --test/--instance`
    are given; the id alone when the row names no file, `?` when it carries no identity."""
    import contract
    import proof_level
    iid = contract.test_instance_id(row) or "?"
    file = proof_level.test_file_of(row)
    return _clip(f"{file}::{iid}" if file else iid, PROOF_NAME_CHARS)


def proof_required_lines(task_root: Path, role: str, dispatch_id: str) -> list:
    """The head line of a code critic's brief about the live checks the predicate requires.

    Only for `qa-code-critic`; read-only (FR-45). Counts the instances in the dispatch's scope that
    `proof_level.proof_required` demands a check of and that reach no valid receipt
    (`proof_level.reached`), and names up to PROOF_NAMES_SHOWN of them with the stored novelty word
    (a legacy row that stores none gets no word); more than that: "and N more" and where the full
    list is. Instances that are required and already reached a receipt are counted apart
    ("K already receipted"), never as work. A row the predicate raised on is listed as "could not be
    judged" and the rest still are; a receipt that cannot be read leaves its row owed (the error goes
    toward "still to check"). No instance owed -> no line, also when every required one is receipted:
    the same rule as `expectation_change_lines` (nothing is owed).
    A manifest that is absent or cannot be read, or a measurement that failed, gets ONE line saying
    so and why - never "none" (FR-41); the brief is built either way, because it is a courtesy and
    never a refusal."""
    if role != PROOF_ROLE:
        return []
    cannot = "The live checks the predicate requires could not be listed: "
    try:
        import contract
        import proof_level
        import s5_precheck
        path = contract.artifact(task_root, "automation-manifest.json")
        try:
            manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return [cannot + f"{PROOF_LIST} is not there."]
        except (OSError, ValueError) as exc:
            return [cannot + f"{PROOF_LIST} cannot be read ({type(exc).__name__})."]
        if not isinstance(manifest, dict):
            return [cannot + f"{PROOF_LIST} is not a JSON object."]
        scope = {str(c).rsplit("/", 1)[-1] for c in s5_precheck.scope_cases(task_root, manifest, dispatch_id)}
        cfg = contract.case_config()
        owed, receipted = [], 0
        for row in contract.manifest_tests(manifest):
            if not set(contract.manifest_test_links(row, cfg)) & scope:
                continue
            name = _proof_name(row)
            try:
                required = proof_level.proof_required(row, manifest)
            except Exception as exc:   # one row the predicate cannot judge never hides the others
                owed.append(f"{name} - could not be judged ({_clip(f'{type(exc).__name__}: {exc}', 120)})")
                continue
            if not required:
                continue
            try:
                if proof_level.reached(row, manifest, task_root)["level"] is not None:
                    receipted += 1
                    continue
            except Exception:   # a receipt nobody could read proves nothing: the row stays owed
                pass
            try:
                word = proof_level.novelty_of(row)[0]
            except Exception:
                word = None
            owed.append(name + (f" ({word})" if word else ""))
    except Exception as exc:
        return [cannot + _clip(f"the measurement itself failed ({type(exc).__name__}: {exc})", PROOF_WHY_CHARS)]
    if not owed:
        return []
    count = len(owed)
    line = (f"Live checks the predicate requires - {count} instance{'' if count == 1 else 's'} "
            f"(new or changed tests)" + (f", {receipted} already receipted" if receipted else "") + ": "
            + ", ".join(owed[:PROOF_NAMES_SHOWN]))
    if count > PROOF_NAMES_SHOWN:
        line += f", and {count - PROOF_NAMES_SHOWN} more - the full list: {PROOF_LIST} (`novelty` per row)"
    try:
        import probe_debt
        debt = probe_debt.debt_rel(dispatch_id)       # TR3-15: the debt file of THIS critic dispatch (the one spelling), never another window's
    except Exception:   # a brief line never stops a brief
        debt = "work/probe-debt/<your dispatch id>.json"
    return [line + f". Each needs a receipt: run its check and record it, or leave it in {debt} "
                   "for the conductor."]


# --- the sides of the story and what a test assumes about them (t-2181 PC-8, AR-10, AR-13) ------------------------------
# Data and provenance only: which sides a Then speaks about, whether a placeholder is reasonable and what a code critic may
# accept are the roles' judgment (AR-29). The record is read through `contract.story_sides`, the rows through
# `contract.manifest_provisional`, the pending rows through `acceptance.pending_rows` - this file filters nothing of its own.
SIDES_ROLES = ("qa-automator", "qa-code-critic")    # who is handed the side lines at S5
SIDES_AUTHOR = "qa-automator"                       # who is also handed the fields to fill and the bind round
SIDES_SHOWN = 6                                     # side lines one brief lists; the rest is `+N more`
SIDE_LINE_CHARS = 160
SIDE_KNOWLEDGE_MARK = "[knowledge:{}]"              # a DATA token on a side line that came from the registry, for counting later
PROVISIONAL_SHOWN = 6                               # rows of one kind a bind brief lists (open or back to open)
PENDING_SHOWN = 6                                   # pending rows a bind brief lists
PROVISIONAL_LINE_CHARS = 200
BIND_PURPOSE = "bind"                               # a word of `controller.PURPOSES` (its home, AR-1); a test pins the membership
# The bind procedure is paid by a bind round only, so it lives here and not in the charter (J-15, Q11).
BIND_HEAD = ("Bind round - the code arrived: only what is listed here is yours to settle; what is not listed is not yours. Run each open "
             "row's tests on the real side: the marked line unchanged is `settled_matched`, edited `settled_edited`; drop a real side's "
             "substitutes.")


def _purpose_word(dispatch) -> str:
    """The purpose a dispatch was started with, read as `controller.s5_part_of` reads it: from `request_binding` when the record has
    that key (the top of a record is overwritten by a checkpoint), else from `purpose`."""
    if not isinstance(dispatch, dict):
        return ""
    if "request_binding" in dispatch:
        binding = dispatch["request_binding"]
        return str(binding.get("purpose") or "") if isinstance(binding, dict) else ""
    return str(dispatch.get("purpose") or "")


def _sides_stamp(pipeline) -> dict:
    """The ONE condition "this story has sides to tell" (S13, AR-13, AR-28): `run_suite.proof_stamp`, the rule the execution blocks are
    stamped by. `{}` = no record, every side real, nothing unknown - the brief says nothing. `sides_met` = a readable record;
    `sides_unknown` = the record is unreadable (a non-dict `pipeline.sides`) or the story says so: no side then counts as real.
    Never raises: a courtesy, not a gate."""
    try:
        import run_suite
        return run_suite.proof_stamp(pipeline)
    except Exception:
        return {}


def side_lines(pipeline, cfg=None, env_name=None) -> list:
    """The lines that tell a role the sides of its story: `contract.story_sides`, the one reader (AR-13). `[]` for a story that has no
    sides to tell (`_sides_stamp`) - the brief of such a story is byte-identical to what it was. An unreadable or unknown record is ONE
    line (no side counts as real), never silence (AR-28) and never the reader's default side. A line carries `[knowledge:<registry_key>]`
    only when the side came from the project knowledge registry (`source: registry`) AND its row names the `registry_key`: no key is
    invented. At most `SIDES_SHOWN` sides, then `+N more`. Never raises: a courtesy, not a gate."""
    stamp = _sides_stamp(pipeline)
    if not stamp:
        return []
    out = []
    if stamp.get("sides_unknown"):
        out.append(_clip(f"The project's record of the sides could not be read ({stamp['sides_unknown']}): no side counts as real.",
                         SIDE_LINE_CHARS * 2))
    if "sides_met" not in stamp:
        return out      # the reader's default side beside an unknown is a guess: it is not listed
    try:
        import contract
        sides = contract.story_sides(pipeline, cfg, env_name)
    except Exception:
        return out
    if not isinstance(sides, dict) or not sides:
        return out
    out.append("Sides of this story (its record, read by code): an absent side cannot be run against; a substituted side runs only "
               "against its substitute, which proves nothing about the side.")
    for name, row in list(sides.items())[:SIDES_SHOWN]:
        row = row if isinstance(row, dict) else {}
        text = f"- {name}: {row.get('reality') or 'unknown (not read as real)'}"
        if row.get("deliverable") is False:
            text += ", not this story's to deliver"
        if row.get("settles_by"):
            text += f", settles by {row['settles_by']}"
        if row.get("reference"):
            text += f", the older version is {row['reference']}"
        text = _clip(text, SIDE_LINE_CHARS)
        key = str(row.get("registry_key") or "").strip()
        if row.get("source") == "registry" and key:
            text += " " + SIDE_KNOWLEDGE_MARK.format(key)
        out.append(text)
    if len(sides) > SIDES_SHOWN:
        out.append(f"+{len(sides) - SIDES_SHOWN} more sides: pipeline.json `sides`")
    return out


def provisional_lines(task_root: Path, pipeline, dispatch, role: str, dispatch_id: str = "") -> list:
    """The automator's lines about what it may assume and must declare (AR-10: the check's requirement reaches the role before the
    work, in the fields it fills). Only for `qa-automator`; `[]` unless the story has sides to tell (`_sides_stamp`), or
    `provisional[]` rows already exist, or the dispatch is a bind round - an all-real story's brief names none of these fields.

    A bind round (`purpose` = `BIND_PURPOSE`, the S5 round after code arrived) adds `_bind_lines`: the procedure and only what the
    dispatch must act on. An empty list is said, never silence (FR-41); a bind round whose rows fail to be read says so (the except
    is narrow). An ordinary window never raises."""
    if role != SIDES_AUTHOR:
        return []
    bind = _purpose_word(dispatch) == BIND_PURPOSE
    manifest, why = _read_manifest(task_root)
    try:
        import contract
        rows = contract.manifest_provisional(manifest)["rows"] if manifest else []
        out = _assumption_lines(pipeline) if (_sides_stamp(pipeline) or rows or bind) else []
        if not bind:
            return out
        return out + _bind_lines(pipeline, manifest, why, rows, _dispatch_scope(task_root, dispatch_id))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ImportError) as exc:
        # narrow on purpose: a bind round whose rows could not be listed SAYS so (FR-41); an ordinary window loses only a reminder
        return [BIND_HEAD, f"The rows could not be listed ({type(exc).__name__}): work/automation-manifest.json holds them."] if bind else []
    except Exception:   # an ordinary window: the fields are a courtesy, never a reason to lose the brief
        if bind:
            raise
        return []


def _read_manifest(task_root: Path) -> tuple:
    """(the automation manifest as a dict, "") or (None, why it could not be read)."""
    import contract
    try:
        manifest = json.loads(contract.artifact(task_root, "automation-manifest.json").read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None, "work/automation-manifest.json is not there"
    except (OSError, ValueError) as exc:
        return None, f"work/automation-manifest.json cannot be read ({type(exc).__name__})"
    if not isinstance(manifest, dict):
        return None, "work/automation-manifest.json is not a JSON object"
    return manifest, ""


def _bind_failure(why: str) -> list:
    return [f"Open rows and pending instances could not be listed: {why}."] if why else []


def _dispatch_scope(task_root: Path, dispatch_id: str):
    """The cases the dispatch was scoped to, or None (not readable: the whole story) - `s5_precheck.dispatch_scope`, the reader the
    exit check judges by."""
    import s5_precheck
    return s5_precheck.dispatch_scope(task_root, dispatch_id)


def _assumption_lines(pipeline) -> list:
    """The two lines of the third route and of the declaration (the kinds and the reality words from their data files)."""
    import contract
    kinds = contract.provisional_kinds()
    return [_clip("Assumptions: where a side is not real, a selector or a contract you cannot ground is a third route - a `provisional[]` row "
                  f"(kind: {' | '.join(kinds) if kinds else 'the kinds file could not be read'}) with the marker `qa-provisional: P-n` at the "
                  "project's single home for it, never in a test body; name the row in `tests[].provisional`. A provisional value is never "
                  "a Then's expected value.", HEAD_LINE_CHARS * 2),
            _clip("Declare how each test meets each side it touches in `tests[].sides` ("
                  + (" | ".join(contract.side_realities().get("realities") or []) or "the words file could not be read")
                  + "; an absent side is written and collected, not run, and listed `pending_implementation` with its instance ids) and "
                  "which sides each Then speaks about in `then_bindings[].about`.", HEAD_LINE_CHARS)]


def _bind_lines(pipeline, manifest, why: str, rows: list, scope) -> list:
    """The bind round (§3.2 step 5): the procedure and ONLY what the dispatch must act on - the rows of its scope (`dependents`, the
    exit check's own rule `s5_precheck._row_in_scope`) that are `open` on a side that is real now (a `kept_by_decision` row stays kept, even on a side that
    became real: owner word W3, 11.11.2026); an open row on a side that is still not real waits and is counted; the pending rows of its
    scope, split by `acceptance.pending_instances(..., sides=)` into the instances to run and the ones an absent side still excuses.
    An empty list is said, never silence (FR-41)."""
    import acceptance
    import contract
    import s5_precheck
    out = [BIND_HEAD]
    if manifest is None:
        return out + _bind_failure(why)
    sides = contract.story_sides(pipeline)
    ctx = SimpleNamespace(scope_cases=None if not scope else [str(c) for c in scope], cfg=contract.case_config())

    def real(row) -> bool:
        return str((sides.get(str(row.get("settles_on") or "")) or {}).get("reality") or "") == "real"

    here = [r for r in rows if s5_precheck._row_in_scope(ctx, r)]
    def status(row) -> str:
        return str(row.get("status") or "")

    mine = [r for r in here if status(r) == "open" and real(r)]      # a kept_by_decision row stays kept (owner word W3), it is not reopened
    waiting = sorted({str(r.get("settles_on") or "?") for r in here if status(r) == "open" and not real(r)})
    waiting_n = sum(1 for r in here if status(r) == "open" and not real(r))
    for row in mine[:PROVISIONAL_SHOWN]:
        home = row.get("home") if isinstance(row.get("home"), dict) else {}
        out.append(_clip(f"- open {row.get('id')} ({row.get('kind') or '?'}) on {row.get('settles_on') or '?'}: {row.get('what') or ''}"
                         + (f" - home {home['file']}" if home.get("file") else ""), PROVISIONAL_LINE_CHARS))
    if len(mine) > PROVISIONAL_SHOWN:
        out.append(f"+{len(mine) - PROVISIONAL_SHOWN} more rows to settle: work/automation-manifest.json `provisional`")
    if not mine:
        out.append("- no open provisional row whose side is real")
    if waiting_n:
        out.append(f"- {waiting_n} open row(s) still waiting for {', '.join(waiting)} (not real yet): leave them")
    pending = [r for r in acceptance.pending_rows(manifest) if ctx.scope_cases is None or s5_precheck._scope_has(ctx, r.get("case"))]
    for row in pending[:PENDING_SHOWN]:
        names = [str(i).strip() for i in row["instance_ids"] if str(i or "").strip()]
        excused = acceptance.pending_instances(manifest, [{"instance_id": n} for n in names], None, sides)
        run = [n for n in names if n not in excused]
        key = contract.case_key(str(row.get("case") or ""), str(row.get("area") or ""))
        text = (f"- pending row {key}: " + (f"run {', '.join(run)}; once every instance ran on real sides retract the row with "
                f"`retracted_unresolved: [\"{key}\"]`" if run else "leave it"))
        if excused:
            text += f"; still waiting for an absent side: {', '.join(n for n in names if n in excused)}"
        out.append(_clip(text, PROVISIONAL_LINE_CHARS * 2))
    if len(pending) > PENDING_SHOWN:
        out.append(f"+{len(pending) - PENDING_SHOWN} more pending rows: work/automation-manifest.json `unresolved`")
    if not pending:
        out.append("- no pending instance")
    return out


def _log_of_attempt(task_root: Path, project, attempt: str) -> str:
    """The log path of one run attempt, or `""`: the run block `work/run-blocks/*-<attempt>.json` names its summary file
    (`evidence[].summary`, a path under the project), and that file holds `log`. Any step that cannot be read gives `""`."""
    for block_path in sorted((task_root / "work" / "run-blocks").glob(f"*-{attempt}.json"))[:1]:
        evidence = _load(block_path).get("evidence")
        summary = next((e.get("summary") for e in evidence if isinstance(e, dict) and e.get("summary")), "") \
            if isinstance(evidence, list) else ""
        return str(_load(Path(project) / str(summary)).get("log") or "") if summary and project is not None else ""
    return ""


def base_log_lines(task_root: Path, role: str, dispatch_id: str) -> list:
    """The head lines that hand the code critic the run of each instance in its scope (TQ1-18 F-5, AR-8): the attempt id and the
    log path of its CURRENT run row (`case_stamp.run_row_for`, the one join), so that `base_outcome {outcome, run}` is
    read from a log nobody has to search for. One line per instance, at most PROOF_NAMES_SHOWN, then "and N more". An instance with
    no current run row gets no line; none of the scope with one gets ONE line saying so (FR-41); a log path that cannot be read
    leaves the attempt id and says so. Only for `qa-code-critic`; read-only (FR-45); a failure is one line, never a refusal."""
    if role != PROOF_ROLE:
        return []
    try:
        import case_stamp as CS
        import contract
        import s5_precheck
        manifest = _load(contract.artifact(task_root, "automation-manifest.json"))
        if not manifest:
            return []                       # `proof_required_lines` already says the manifest is not there
        scope = {str(c).rsplit("/", 1)[-1] for c in s5_precheck.scope_cases(task_root, manifest, dispatch_id)}
        cfg = contract.case_config()
        live = [row for row in contract.manifest_tests(manifest) if set(contract.manifest_test_links(row, cfg)) & scope]
        if not live:
            return []
        report = contract.load_json(contract.artifact(task_root, "run-report.json"))
        index = CS.run_rows_index(contract.current_instance_results(report), live, cfg)
        project = s5_precheck._project_of(task_root)
        found = []
        for row in live:
            current = CS.run_row_for(row, index)
            attempt = str((current or {}).get("attempt_id") or "").strip()
            if attempt:
                log = _log_of_attempt(task_root, project, attempt)
                found.append(f"`{_proof_name(row)}`: run `{attempt}`, " + (f"log `{log}`" if log else "its log path could not be read "
                             f"(open `work/run-blocks/*-{attempt}.json`, `evidence[].summary`, key `log`)"))
        if not found:
            return ["Run logs of your scope: the run report holds no current row with an attempt id for these instances - nothing to "
                    "record a `base_outcome` from."]
        lines = [f"Run log of {line}" for line in found[:PROOF_NAMES_SHOWN]]
        return lines + ([f"... and {len(found) - PROOF_NAMES_SHOWN} more: `work/run-blocks/`"] if len(found) > PROOF_NAMES_SHOWN else [])
    except Exception as exc:                # a courtesy line never fails the brief; the failure is named
        return [f"The run logs of your scope could not be listed ({type(exc).__name__}): `work/run-blocks/` holds them."]


# --- reading the story ----------------------------------------------------------------------

def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _stages() -> dict:
    return {s["id"]: s for s in (hooklib.load_ref_json("stages.json").get("stages") or [])}


def _short(text, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


def _size(path: Path) -> str:
    try:
        n = path.stat().st_size
    except OSError:
        return "absent"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _dir_note(path: Path) -> str:
    try:
        files = [p for p in path.rglob("*") if p.is_file()]
    except OSError:
        return "absent"
    return f"{len(files)} files"


def _resolve(name: str, task_root: Path, project: Path) -> tuple:
    """(display path, absolute path) for a task-relative, `project:` or `plugin:` name."""
    if name.startswith("plugin:"):
        # A file of the plugin copy that is RUNNING, named by its absolute path - the same reason `SCRIPTS` is (B-014): a
        # role told "the plugin root" has nowhere to look it up, and a path of another copy is another generation.
        path = (HERE.parent / name[len("plugin:"):]).as_posix()
        return path, Path(path)
    if name.startswith("project:"):
        # `project:readiness.json` and `project:state/journal.jsonl` are the data files' spellings
        # (stages.json); the layout says where those files really are (t-232 section 8).
        rel = RP.project_alias(project, name[len("project:"):])
        if rel.startswith("strategy/"):
            # A project's own strategy document (`strategy_documents[]`) is the document its roles read, wherever it
            # lives: the injection decides that by config_contract.strategy_document, and so does this door (F1,
            # AR-13) - else the brief says "not written yet" about a file the role was always injected.
            own = config_contract.strategy_document(hooklib.load_config() or {}, Path(rel).name)
            if own:
                return own, project / own
        return "qa-factory/" + rel, project / "qa-factory" / rel
    return f"qa-factory/artifacts/{task_root.name}/" + name, task_root / name


def _bundle_view(task_root: Path):
    """(display path, path) of the context bundle's line view when it is CURRENT, else None.

    The one reader of the question is `context_bundle.view_status` (current|stale|absent). The error direction is
    declared: anything but `current` - a stale view, a missing function (an older context_bundle), an exception of any
    kind, a view that vanished between the check and the stat - is None, and the brief then names the JSON. A view
    that describes other bytes than the JSON on disk is never named to a role (FR-59)."""
    try:
        import context_bundle
        json_path = task_root / BUNDLE_JSON
        if context_bundle.view_status(json_path) != "current":
            return None
        # The view's name is its writer's (AR-13): asked, never spelled here. A module older than A2 has no `view_path`.
        display, path = _resolve(context_bundle.view_path(json_path).relative_to(task_root).as_posix(), task_root, task_root)
        path.stat()
        return display, path
    except Exception:  # noqa: BLE001 - the brief is always built; "cannot tell" is "not current"
        return None


def file_lines(names: list, task_root: Path, project: Path, shell: bool = True) -> list:
    """`- path (size)` for every existing file; a glob expands; a directory counts files.

    `shell` is whether the role has Bash: a role without it is told the file to read, never the script."""
    out, seen = [], set()
    for name in names:
        if name == BUNDLE_JSON:
            # BEFORE the SLICE_INSTEAD branch, and the name is never a table entry: the bundle gets exactly one of two lines,
            # and neither ever points a role at a view that describes other bytes than the JSON on disk.
            view = _bundle_view(task_root)
            if view:
                line = (f"- {view[0]} ({_size(view[1])}) - the bundle, one line per fact, source and candidate; the JSON "
                        f"({BUNDLE_JSON}) is the record for any field the view does not show")
                if view[1].stat().st_size > SLICE_BYTES:
                    line += " - slice it: `Grep -n` first, then Read with offset/limit"
                out.append(line)
            else:
                out.append(f"- {BUNDLE_JSON}: {BUNDLE_BY_RANGES}")
            continue
        if name in SLICE_INSTEAD:
            if not shell and name in SLICE_INSTEAD_NO_SHELL:
                context = _resolve("work/context-manifest.json", task_root, project)[0]
                out.append(f"- {_resolve(name, task_root, project)[0]}: "
                           + SLICE_INSTEAD_NO_SHELL[name].replace("{context}", context))
            else:
                out.append(f"- {name}: do not read whole - `{SLICE_INSTEAD[name].replace('<T>', task_root.name)}`")
            continue
        display, path = _resolve(name, task_root, project)
        if name == FIRST_LOOK_FILE:
            # t-2277 FL-3 (AR-23): the first look is an optional input - an absent or `null` record reads "no first look", one line
            out.append(first_look_input_line(task_root, display, _size(path) if path.is_file() else ""))
            continue
        candidates = [path]
        if "*" in path.name:
            candidates = sorted_paths(path.parent.glob(path.name)) if path.parent.is_dir() else []
        listed = False
        for candidate in candidates:
            if candidate in seen:
                listed = True
                continue
            seen.add(candidate)
            shown = display if "*" not in display else display.rsplit("/", 1)[0] + "/" + candidate.name
            if name.endswith("/") or candidate.is_dir():
                if candidate.is_dir():
                    out.append(f"- {shown.rstrip('/')}/ ({_dir_note(candidate)})")
                    listed = True
                continue
            if not candidate.is_file():
                continue
            listed = True
            size = candidate.stat().st_size
            if candidate.name.startswith("impl-diff"):
                # The implementation is a required source, not a place to grep: the S2 tester of
                # TP1-13797 (driver run 3) read "slice it" as "skim it", never opened the
                # diff and lost every requirement the code carries.
                if shell:
                    # A role with a shell reads it through diff_pass: every changed line of every hunk (SC1-10).
                    note = (" - required source: run `diff_pass.py --diff <this file> --files-only`, then `--file <path> "
                            f"--max-lines {DIFF_ALL_LINES}` for every file it lists - every changed line of every hunk; "
                            "never Read this diff whole")
                else:
                    # A role without one is never named a script (K1/K2): the text of before.
                    note = (" - required source: read EVERY hunk, whole, in slices (Read with offset/limit, "
                            "<= 400 lines each); `Grep -n` alone is not reading it")
            else:
                note = " - slice it: `Grep -n` first, then Read with offset/limit" if size > SLICE_BYTES else ""
            out.append(f"- {shown} ({_size(candidate)}){note}")
        if not listed:
            # A declared input that is not there is still a path the role must not guess at
            # (FR-15). Dropping it silently is what sent roles hunting: of run 5's 644 reads
            # **129 missed**, and the three most-missed paths were an earlier stage's plan and
            # manifest, tried at both levels - `test-plan.md` 8 times and `work/test-plan.md` 5,
            # the same file. The line says the exact path and that nothing has written it.
            out.append(f"- {display}: not written yet — that is the path it will have, "
                       "and nothing else is it")
    return out


def case_paths(task_root: Path, scope: list) -> list:
    """Task-relative paths of the scoped cases: the authoring copy when it is inside the
    task, else the pinned version (`state/case-versions/...`)."""
    import contract
    links = {str(link.get("case_id")): link for link in contract.story_case_links(task_root)}
    out = []
    for cid in scope:
        bare = str(cid).rsplit("/", 1)[-1]
        link = links.get(cid) or links.get(bare)
        chosen = None
        if link:
            source = str((link.get("store_provenance") or {}).get("source_path") or "")
            prefix = f"qa-factory/artifacts/{task_root.name}/"
            if source.startswith(prefix) and (task_root / source[len(prefix):]).is_file():
                chosen = source[len(prefix):]
            elif link.get("path") and (task_root / str(link["path"])).is_file():
                chosen = str(link["path"])
        if chosen is None:
            for path in contract.case_files(task_root):
                if contract.case_id(path) == bare:
                    try:
                        chosen = path.resolve().relative_to(task_root.resolve()).as_posix()
                    except ValueError:
                        chosen = None
                    break
        if chosen:
            out.append(chosen)
    return out


MATERIAL_READERS = {
    "qa-requirements-tester": "the precedent's own words: requirements, and the traps its review found",
    "qa-test-strategist": "the precedent's risks and what its tests had to cover",
    "qa-automator": "the precedent's tests and fixtures, to reuse instead of inventing",
    "qa-code-critic": "what the precedent's review asked for, so this review asks no less",
}


def _left_out(task_root: Path) -> tuple:
    """(live exclusions, a problem line or ""): the person's list of sources not to read (B-231). No record
    is ([], ""); a record that cannot be read is ([], the line that says so) - the brief is a courtesy and
    never a refusal, but it must not look like there is no list."""
    try:
        import source_exclusions as SE
    except ImportError:
        return [], ""
    try:
        return SE.live(task_root), ""
    except SE.ExclusionRecordError as exc:
        return [], (f"- the person's list of sources not to read exists and cannot be read ({exc}): read no "
                    "source that may be on it, and say so in your handoff")


def left_out_lines(task_root: Path) -> list:
    """One line per live exclusion for a role that is handed collected material, carrying the sentence for
    edge 6 (t-172 C7): a requirement that reaches the role only through a source the person left out has no
    other carrier, so it says what to do with it HERE."""
    live, problem = _left_out(task_root)
    if problem:
        return [problem]
    import source_exclusions as SE
    return [f"- Left out by the person's word before the run - not a source, precedent or existing coverage: "
            f"{e.get('as_written')} (\"{SE.clip(e.get('reason') or '')}\"). A requirement that reaches you "
            "only through it is not a requirement of this story: name it as an open question for the person."
            for e in live]


REFERENCES_SHOWN = 20           # reference rows one brief lists; the rest read "+K more"
REFERENCES_FILE = "work/ticket-references.json"
_EM_DASH = chr(0x2014)


def reference_gap_lines(task_root: Path) -> list:
    """One line per row of `work/ticket-references.json` (S0's list of everything the story's text points at,
    t-267) whose status is not `fetched`: `<ref> - <status>: <why>`, at most REFERENCES_SHOWN of them, then
    `+K more`. Said next to the person's exclusions, because the scout must see what was NOT read as plainly as
    what the person left out: a reference that the text carries and nobody read is a gap, not an absence (FR-41).
    A row with no status is listed too (it is not `fetched`). No file, or one that cannot be read: [] - a story
    whose S0 ran before the file existed is briefed as it always was (temporal)."""
    document = _load(task_root / REFERENCES_FILE)
    rows = document.get("rows")
    if not isinstance(rows, list):
        return []
    gaps = [row for row in rows if isinstance(row, dict) and str(row.get("status") or "") != "fetched"]
    out = []
    for row in gaps[:REFERENCES_SHOWN]:
        # t-373 F6 (B-256 c): a merge request whose repository name two attached repositories share is not tied to either;
        # the row carries the line that says so and how to settle it (`ticket_light.take_attached`), and that line is
        # what the scout reads - not a bare `not_fetched: not read yet`.
        refusal = " ".join(str(row.get("refusal") or "").split()) if row.get("repo") == "ambiguous" else ""
        if refusal:
            out.append(f"- {REFERENCES_FILE}: {row.get('ref')} {_EM_DASH} {refusal}")
            continue
        status = str(row.get("status") or "")
        head, _sep, why = status.partition(":")
        if not why.strip() and str(row.get("reason") or "").strip():
            why = str(row["reason"])          # `unproven` carries its reason in its own field (no tracker read at S0)
        if not why.strip():
            origins = ", ".join(str(o) for o in row.get("origins") or []) or "the ticket"
            why = (f"a {row.get('kind') or 'reference'} named in {origins}"
                   + ("; no route of the factory reads it, so it is the person's to paste or to say it is not needed"
                      if head == "person" else "; no status was recorded for it"))
        out.append(f"- {REFERENCES_FILE}: {row.get('ref')} {_EM_DASH} {head.strip() or 'unknown'}: {why.strip()}")
    if len(gaps) > REFERENCES_SHOWN:
        out.append(f"- {REFERENCES_FILE}: +{len(gaps) - REFERENCES_SHOWN} more not read (all of them are in the file)")
    return out


INVENTORY_FILE = "work/source-inventory.json"


def reads_skipped_lines(task_root: Path) -> list:
    """One line per entry of `reads_skipped` in `work/source-inventory.json` (t-280 F8, FR-41): an optional
    read S0 could not make (a 5xx after the retries, a timeout, a 404 on the endpoint) and said so. The scout
    must not take "no remote links in the ticket" for "the remote links were not read", nor an empty field
    catalogue for an instance without fields. `/remotelink` -> "remote links were not read: <why>";
    `/field` -> "the field catalogue was not read: <why> - custom fields are matched by id only"; any other
    call is named as it is. No inventory, no key (a story whose S0 ran before the key existed), an empty
    list or a malformed entry: nothing - the brief is as it always was (temporal)."""
    entries = _load(task_root / INVENTORY_FILE).get("reads_skipped")
    if not isinstance(entries, list):
        return []
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        call = str(entry.get("call") or "").strip()
        why = " ".join(str(entry.get("why") or "").split()) or "no reason was recorded"
        if call == "/remotelink":
            out.append(f"- {INVENTORY_FILE}: remote links were not read: {why}")
        elif call == "/field":
            out.append(f"- {INVENTORY_FILE}: the field catalogue was not read: {why} {_EM_DASH} "
                       "custom fields are matched by id only")
        elif call:
            out.append(f"- {INVENTORY_FILE}: {call} was not read: {why}")
    return out


def snapshot_mask_lines(task_root: Path) -> list:
    """The ticket snapshot's own links that the person left out. The brief names `work/ticket-snapshot.json`
    and the scout reads it FIRST; its `links.merge_request` is the first remote-link merge request of the
    ticket, which reaches the scout as "the ticket's MR" (t-172 C7: the snapshot itself stays byte for byte
    what the adapter printed, because its hash is the story's `source_revision`). So the brief says, in the
    person's words, which of those links to leave alone."""
    live, _problem = _left_out(task_root)
    if not live:
        return []
    import source_exclusions as SE
    links = (_load(task_root / "work" / "ticket-snapshot.json").get("links") or {})
    if not isinstance(links, dict):
        return []
    seen, out = set(), []
    values = [links.get("merge_request"), links.get("branch")] + [
        (row or {}).get("url") for row in (links.get("remote_links") or []) if isinstance(row, dict)]
    for value in values:
        if not isinstance(value, str) or not value.strip() or value in seen:
            continue
        seen.add(value)
        for exclusion in live:
            if any(SE.matches(exclusion, **{field: value}) for field in ("url", "branch", "sha")):
                out.append(f"- work/ticket-snapshot.json links {value}: left out by the person's word before the "
                           f"run (\"{SE.clip(exclusion.get('reason') or '')}\") - it is not \"the ticket's "
                           "merge request\"; do not read, collect or cite it")
                break
    return out


TICKET_VIEW = "work/ticket-view.md"
TICKET_RAW_READABLE = "work/ticket-raw/issue.pretty.json"


def ticket_view_lines(task_root: Path, project: Path) -> list:
    """The two files S0's REST read leaves next to the snapshot (t-267), named in the scout's brief:
    `work/ticket-view.md`, the ticket as a role reads it (title, description whole, the criteria, one
    line per comment, id first), and `work/ticket-raw/issue.pretty.json`, everything the tracker said,
    pretty-printed so it can be sliced - "readable, not injected": it is in no role's context unless the
    role goes and greps it (F23). A file that is not there gets no line: a story whose S0 ran before the
    files existed (temporal) is briefed as it always was."""
    out = []
    display, path = _resolve(TICKET_VIEW, task_root, project)
    if path.is_file():
        out.append(f"- {display} ({_size(path)}) - the ticket as you read it: title, description, acceptance "
                   "criteria, and one line per comment (id first; a newline inside a text is written `\\n`). "
                   "Read this, not the JSON")
    display, path = _resolve(TICKET_RAW_READABLE, task_root, project)
    if path.is_file():
        out.append(f"- {display} ({_size(path)}) - readable, not injected: everything the tracker said, "
                   "pretty-printed; `Grep -n` it for a field the view does not carry, never read it whole")
    return out


def _excluded_files(task_root: Path) -> set:
    """Resolved paths of every file that is the `local_ref` of an excluded inventory item, with its `.md`
    digest (and, for a digest, its `.json` receipt): none of them is material for a role. An excluded item
    is normally never fetched; one that is on disk anyway keeps its bytes (the record never lies), but no
    brief hands them on."""
    inventory = _load(task_root / "work" / "source-inventory.json")
    refs = []
    for source in inventory.get("sources") or []:
        for block in ((source.get("materials") or {}).values() if isinstance(source, dict) else []):
            for item in (block.get("items") or []) if isinstance(block, dict) else []:
                if isinstance(item, dict) and item.get("status") == "excluded" and item.get("local_ref"):
                    refs.append(str(item["local_ref"]).replace("\\", "/"))
    skipped = set()
    for ref in refs:
        # A local_ref is written relative to `work/` (`sources/<SRC>/mr-1924.json`); the forms that start at the
        # story or at the project are read too.
        story = f"qa-factory/artifacts/{task_root.name}/"
        if ref.startswith(story):
            ref = ref[len(story):]                  # now relative to the story: `work/sources/...`
        elif not ref.startswith("work/"):
            ref = "work/" + ref
        base = task_root / ref
        for path in (base, base.with_suffix(".md"), base.with_suffix(".json")):
            skipped.add(path.resolve())
    return skipped


def source_material(task: str, task_root: Path, role: str) -> list:
    """What S1 actually COLLECTED for a source, handed to the roles that use it.

    TP1-13797, 26.09: the factory collected four merge requests of the precedent ticket through
    its own authenticated route (17, 101 and 80 discussions, revisions pinned) and not one brief
    named them — grep over all twelve briefs of that run found none. Downstream, nothing cited
    them: the register and the plan quote the ticket text and a local test file, and
    `object_attributes` — the precedent's sharpest lesson — appears in no artifact of the story.
    Collected and not delivered is the same as not collected, only paid for.

    B-231: what the person left out before the run is never handed on, and the cap of eight lines is applied
    AFTER that skip - an excluded file must not take the slot of a real one. The roles that get material are
    also told, in a line per exclusion, what was left out."""
    why = MATERIAL_READERS.get(role)
    if not why:
        return []
    told = left_out_lines(task_root)
    folder = task_root / "work" / "sources"
    if not folder.is_dir():
        return told
    skipped = _excluded_files(task_root) if told else set()
    out = []
    for path in sorted_paths(folder.rglob("*")):
        # `raw.json` / `raw-comments-<n>.json` beside a ticket.json are the tracker's own answer, kept
        # whole by S1 (t-267, F23: "named in no brief"): never handed on as collected material.
        if not path.is_file() or path.name in ("ticket.json", "raw.json") or path.name.startswith("raw-comments-"):
            continue
        if path.suffix not in (".json", ".md", ".txt"):
            continue
        if path.resolve() in skipped:
            continue
        # An API receipt is evidence, not reading: the precedent's four came back at 79 KB, 183 KB,
        # 965 KB and 3.8 MB. When code wrote the digest beside it, that is what a role is handed.
        if path.suffix == ".json" and path.with_suffix(".md").is_file():
            continue
        rel = path.relative_to(task_root).as_posix()
        if "/assessment" in rel:
            continue
        kind = ("merge request" if path.name.startswith("mr-") else
                "material the person supplied" if path.name.startswith("pasted-") else "material")
        out.append(f"- qa-factory/artifacts/{task}/{rel} ({_size(path)}) - collected {kind}: {why}")
    return told + out[:8]


def scope_tests(task_root: Path, scope: list) -> list:
    """Project-relative test files the manifest already names for the scoped cases."""
    manifest = _load(task_root / "work" / "automation-manifest.json")
    wanted = {str(c).rsplit("/", 1)[-1] for c in scope}
    files = []
    for entry in manifest.get("tests") or []:
        if not isinstance(entry, dict):
            continue
        covers = {str(c).rsplit("/", 1)[-1] for c in (entry.get("covers") or [entry.get("case")]) if c}
        if covers & wanted and entry.get("file") and entry["file"] not in files:
            files.append(str(entry["file"]))
    return files


def digests(pipeline: dict, controller: dict, stage: str, dispatch_id: str) -> tuple:
    """(shown, full): each earlier stage's digest, then this stage's own dispatches - the
    latest few inline, every one of them in the side file."""
    shown, full = [], []
    stages = pipeline.get("stages") or {}
    for sid in STAGE_ORDER:
        if sid >= stage:
            break
        entry = stages.get(sid) or {}
        if not isinstance(entry, dict) or not entry.get("status"):
            continue
        digest = entry.get("digest") or entry.get("reason") or ""
        full.append(f"- {sid} {entry.get('status')}: {digest or 'no digest'}")
        shown.append(f"- {sid} {entry.get('status')}: {_short(digest, DIGEST_CHARS) or 'no digest'}")
    same = []
    for did, d in (controller.get("dispatches") or {}).items():
        if not isinstance(d, dict) or d.get("stage") != stage or did == dispatch_id:
            continue
        if d.get("status") not in ("accepted", "running", "returned_unaccepted", "blocked"):
            continue
        scope = ", ".join(str(c) for c in (d.get("scope") or [])[:8])
        digest = d.get("returned_digest") or d.get("reason") or ""
        same.append((f"- {did} ({d.get('status')}; {scope or 'story scope'}): {digest or 'no digest'}",
                     f"- {did} ({d.get('status')}; {scope or 'story scope'}): {_short(digest, DIGEST_CHARS) or 'no digest'}"))
    full += [pair[0] for pair in same]
    shown += [pair[1] for pair in same[-DISPATCH_DIGESTS:]]
    if len(same) > DISPATCH_DIGESTS:
        shown.append(f"- {len(same) - DISPATCH_DIGESTS} earlier dispatch(es) of {stage} are in the side file")
    return shown, full


def answers_of(task: str, project: Path | None) -> list:
    """The person's answers recorded for this story (`human_answer` events of the project
    journal), oldest first, deduplicated. The driver records the S1 source review and the
    gaps this way; without them a later role sees only gates and warnings and the standing
    words (never write to the tracker, Draft only, a branch suffix) reach it by luck."""
    if project is None:
        return []
    path = RP.record(project, "journal.jsonl")
    if not path.is_file():
        return []
    seen, out = set(), []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("event") != "human_answer" or record.get("task") != task:
                continue
            words = str(record.get("notes") or record.get("reason") or "").strip()
            if words and words not in seen:
                seen.add(words)
                out.append(words)
    except OSError:
        return []
    return out


def person_words_whole(words: str, project: Path | None = None, holder: str = "") -> str:
    """The person's answer as the side file `<dispatch>-decisions.md` carries it: WHOLE (FR-8).
    No per-line cap applies to it (cmp2 15045: a field vocabulary the person wrote reached the
    strategist cut mid-sentence); only a text over PERSON_WORDS_MAX is cut, and the cut says so and
    names the file that holds the whole text - the journal, or `holder` when the words live in another
    carrier (a question's answer: the answers file) - never a silent cut. CRLF becomes LF, so one
    answer does not carry two kinds of line end."""
    text = str(words).replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= PERSON_WORDS_MAX:
        return text
    return (text[:PERSON_WORDS_MAX]
            + f" [cut: {len(text) - PERSON_WORDS_MAX} more characters, the whole text is in "
              f"{holder or RP.rel_text('journal.jsonl', project)}]")


UNREAD_ANSWERS_LINE = ("- the recorded answers could not be read in full, so an answer may be missing from this list; "
                       "a question that looks unanswered is asked again, not guessed")
# A pointer stands where the words would be too long for one line of the brief (DECISION_CHARS): the whole
# text is in the side file, never half of it in the brief (FR-8).
WORDS_BY_REFERENCE = "the person's words: the whole text is in <decisions>"


def _plain_words(words) -> str:
    """Words as the brief compares them: LF line ends, the ends stripped."""
    return str(words or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def question_answer_lines(task_root, project: Path | None = None) -> tuple:
    """([(full, shown, minimal)], said): one line per question the person decided - answered, not needed, or kept
    open until the report - read ONLY through `QR.answers_for_brief` (AR-13: the answers file is the carrier, not the
    journal). A decision that no longer holds (the row changed since, `with_designer`, open) has no line: the
    question is asked again. `shown` keeps the words when the line fits DECISION_CHARS and points at the side file
    when it does not; `minimal` is the id and the letter, no words; the same words under several questions are
    carried once (`said` is those texts, for `decisions` to drop the journal copies of them). One line, first, says
    the answers could not be read when the store reports it (a broken line, a non-object line, an unreadable file)."""
    view = QR.answers_for_brief(task_root)
    holder = f"qa-factory/artifacts/{Path(task_root).name}/" + "/".join(QR.ANSWERS_REL)
    entries, said, first = [], [], {}
    if view["unreadable"]:
        entries.append((UNREAD_ANSWERS_LINE, UNREAD_ANSWERS_LINE, UNREAD_ANSWERS_LINE))
    for item in view["answers"]:
        qid, where = item["id"], QR.where_words(item["where"])
        if item["status"] == QR.DEFERRED:
            head, short = f"{qid} kept open until the report ({where}); do not ask it again", f"{qid} kept open until the report; do not ask it again"
        elif item["status"] == "not_needed":
            head, short = f"{qid} not needed ({where})", f"{qid} not needed"
        elif item["reading"]:
            quoted = f' - "{item["reading_text"]}"' if item["reading_text"] else ""
            head, short = f"{qid} answered {where}: reading {item['reading']}{quoted}", f"{qid} answered: reading {item['reading']}"
        else:
            head, short = f"{qid} answered {where}, in the person's own words", f"{qid} answered in the person's own words"
        key = _plain_words(item["words"])
        if not key:
            clause = "the person's words: not recorded"
        elif key in first:
            clause = f"the person's words: the same text as under {first[key]}"
        else:
            first[key] = qid
            said.append(key)
            clause = "the person's words: " + person_words_whole(key, project, holder)
        full = f"- {head}; {clause}"
        fits = len(" ".join(full.split())) <= DECISION_CHARS
        shown = " ".join(full.split()) if fits else f"- {head}; {WORDS_BY_REFERENCE}"
        entries.append((full, shown, f"- {short}"))
    return entries, said


def _carried_by(note: str, said: list) -> bool:
    """Is this journal note a person's answer whose WORDS a question line already carries? The note is a short
    label (`S3 question stop: `) and then the words; no other text of the person is hidden by dropping it."""
    text = _plain_words(note)
    for words in said:
        if words and text.endswith(words):
            rest = text[:len(text) - len(words)]
            if not rest.strip() or (rest.endswith(": ") and "\n" not in rest and len(rest) <= 120):
                return True
    return False


def decisions(pipeline: dict, stage: str, role: str, task: str = "", project: Path | None = None,
              task_root=None) -> tuple:
    """(shown, minimal, full) lines of the person's words that concern this dispatch: the
    gate decision and the warnings first, the waivers of this stage after them, then the
    answers the person gave earlier in this story - the journal's, and with `task_root` the
    questions the person decided (`question_answer_lines`). Without `task_root` the register is not read."""
    gate_lines, warning_lines, override_lines, halt_lines, full = [], [], [], [], []
    answer_lines = []
    asked, said = question_answer_lines(task_root, project) if task_root is not None else ([], [])
    for words in answers_of(task, project):
        if _carried_by(words, said):
            continue
        line = f"- answer: {person_words_whole(words, project)}"
        full.append(line)
        answer_lines.append((_short(line, DECISION_CHARS), _short(line, DECISION_CHARS_MIN)))
    for full_line, shown_line, minimal_line in asked:
        full.append(full_line)
        answer_lines.append((shown_line, minimal_line))
    gates = pipeline.get("gates") or {}
    wanted = ["A"] if stage >= "S5" else []
    if stage == "S9" or role == "qa-bug-reporter":
        wanted.append("B")
    for gate in wanted:
        record = gates.get(gate) or {}
        words = record.get("authorization_source") or record.get("words") or ""
        if words:
            head = f"- gate {gate} ({record.get('status') or record.get('decision') or '?'}): "
            full.append(head + str(words))
            gate_lines.append((head + _short(words, DECISION_CHARS), head + _short(words, DECISION_CHARS_MIN)))
    import gate_brief
    for warning in pipeline.get("warnings") or []:
        # A `vcs_api` / `host_hooks` / `base_slice` line whose status is `unknown` is not shown at gate A (OH1-11); the report
        # names it. The label tells the scribe which lines those are: `not established:` (it reads the same filter as gate A).
        label = "not established" if gate_brief._not_established([warning])[1] else "standing"
        full.append(f"- {label}: {warning}")
        warning_lines.append((f"- {label}: {_short(warning, DECISION_CHARS)}",
                              f"- {label}: {_short(warning, DECISION_CHARS_MIN)}"))
    others = 0
    import contract
    for entry in contract.live_stage_overrides(pipeline):      # a revoked word is not handed to the role as a standing instruction (GW1-1)
        line = f"- {entry.get('stage')} block \"{entry.get('match')}\" -> {entry.get('decision')}"
        full.append(line)
        if entry.get("stage") in (stage, "*"):
            override_lines.append((_short(line, DECISION_CHARS), _short(line, DECISION_CHARS_MIN)))
        else:
            others += 1
    for halt in pipeline.get("halts") or []:
        # Open by `resolved`, as `stage_done` writes it and `archive_task`, `stage_guard` and `retro_numbers` read it (AR-13):
        # a halt the story already lifted is no line of the brief, and one with no `resolved` is open (FR-59).
        if isinstance(halt, dict) and not halt.get("resolved"):
            line = f"- open halt {halt.get('stage') or ''}: {halt.get('reason') or halt.get('message') or json.dumps(halt)[:200]}"
            full.append(line)
            halt_lines.append((_short(line, DECISION_CHARS), _short(line, DECISION_CHARS_MIN)))
    shown = [pair[0] for pair in gate_lines + warning_lines + override_lines + halt_lines + answer_lines]
    # PC2-6 K1 (AR-24, FR-8): a waiver of THIS stage keeps its own line at level 1, in the order `shown` uses; a count line in its
    # place would be the person's words traded for bytes. The whole text of every decision is in the side file either way.
    minimal = [pair[1] for pair in gate_lines + warning_lines + override_lines + halt_lines + answer_lines]
    if any(line.endswith("...") for line in shown) or others:
        # A shortened decision is a pointer, never the decision: the whole text is one file away.
        shown.append("- every decision in full: <decisions>")
    if others:
        shown.append(f"- {others} recorded decision(s) of other stages are in the side file")
    return shown, minimal, full


def judge_lines(role: str, shell: bool = True, dispatch_id: str = "") -> list:
    """The brief lines about the judge's file for `role`; `dispatch_id` fills the `{dispatch}` of a per-dispatch file name (the S5 code critic's
    `work/judge-code-<its dispatch>.json`, TR3-15: a critic names only its own)."""
    try:
        import judge
        if not judge.active():
            return []
        from story_step import JUDGE_GUIDANCE, PRE_WORK
    except Exception:
        return []
    lines = []
    if role in JUDGE_GUIDANCE:
        lines.append("- " + JUDGE_GUIDANCE[role].replace("<plugin>/scripts/", "").replace("{dispatch}", dispatch_id))
    for script, _argv, output in PRE_WORK.get(role, []):
        output = output.replace("{dispatch}", dispatch_id)
        if script and shell:
            lines.append(f"- {script} already ran at dispatch; its file is {output}")
        elif script:  # a role with no shell is not handed a script name, only the file
            lines.append(f"- the judge's file for you was made at dispatch: {output}")
    return lines


def window_line(controller_obj, stage: str, scope: list) -> str:
    """`window 2 of 3, surface other` from stage-scope, or '' when nothing is derived."""
    try:
        derived = controller_obj.stage_scope(stage)
        for w in derived.get("windows") or []:
            if set(map(str, w.get("scope") or [])) == set(map(str, scope)):
                extra = ", handed to the person" if w.get("handed") else ""
                return f" - window {w.get('index')} of {len(derived['windows'])}, surface {w.get('surface')}{extra}"
    except Exception:
        pass
    return ""


def repo_map_for(task: str, task_root: Path, project: Path, scope: list, write: bool) -> dict | None:
    """The repository map of the window: written by repo_map.py, or built in memory."""
    if not scope:
        return None
    try:
        import repo_map
        doc = repo_map.build(task_root, project, hooklib.load_config() or {}, list(scope))
        path = repo_map.write_map(task_root, doc) if write else None
        rel = f"qa-factory/artifacts/{task}/work/briefs/repo-map-{doc['hash']}.md"
        return {"doc": doc, "path": rel, "written": bool(path), "markdown": repo_map.render(doc)}
    except Exception as exc:  # the map is a courtesy; the brief still names the files
        return {"error": f"{type(exc).__name__}: {exc}"}


BLAST_LINE_MAX = 300
BLAST_REASON_MAX = 80
BLAST_FAILED = "Blast radius index: could not be built ({}) - the driver's S3 preparation builds it."


def blast_radius_line(task: str, task_root: Path, write: bool) -> str:
    """The one line of an S3 brief about `work/blast-radius.json` (G1-2): the index `blast_radius.py` builds from the implementation
    diff, with its counts and the first thing it could not measure. `write` False (`--dry-run`, `--output`) builds nothing: the line
    says what is on disk. At most 300 characters, one line, never raises - unlike `repo_map_for` a failure is NAMED in the line (the
    role must not read "no line" as "no radius"); the driver's S3 preparation builds the file when this call could not."""
    try:
        import blast_radius as BR
        doc, how = BR.ensure(task_root, mode="link", write=write)       # a dry run asks the same question the real brief would (no retry states)
        if how == "off_diff":
            word = BR.GT.source_state(task_root)[0].partition(":")[2] or "absent"
            return f"Blast radius index: none - the implementation source is {word}."
        if doc is None:
            return f"Blast radius index: {how} - not built in this run."
        s = BR.summary(doc)
        rel = f"qa-factory/artifacts/{task}/work"
        labelled = BR.GT.table_path(task_root).exists()
        tail = (f" Label the areas in {rel}/grounding.yaml (blast_radius.areas)." if labelled else " Read it before labelling.")
        head = f"Blast radius index (code; {how}): {rel}/{BR.BLAST_FILE} - {s.areas} areas in {s.repos} repositories; unmeasured: {s.unmeasured}"
        room = max(0, min(BLAST_REASON_MAX, BLAST_LINE_MAX - len(head) - len(tail) - 4))
        reason = f" ({s.first[:room]})" if s.unmeasured and s.first and room else ""
        return (head + reason + "." + tail)[:BLAST_LINE_MAX]
    except Exception as exc:
        what = getattr(exc, "text", "") or str(exc)
        return BLAST_FAILED.format(f"{type(exc).__name__}: {' '.join(str(what).split())[:120]}")[:BLAST_LINE_MAX]


def s3_labelling_vocabulary_lines(dispatch) -> list:
    """The S3 window-1 (labelling) brief's closed words (OH3-14, FR-15/AR-8): the labels and the requirement states of
    `work/grounding.yaml`, from the ONE line builder `handoff.grounding_vocabulary_line` (the driver's own dispatch line in `story_run.py` is
    still built by hand, queued to conductor/1). The role cannot read the vocabulary file - the pre-tool guard refuses a role the plugin - so the brief carries the words.
    `[]` for every dispatch that is not window 1 (`controller.s3_window_of`: error direction only toward the exit window); never raises."""
    try:
        from controller import s3_window_of
        import handoff
        if s3_window_of(dispatch) != "labelling":
            return []
        return ["Closed words of work/grounding.yaml, given here (there is no file to read for them): " + handoff.grounding_vocabulary_line()]
    except Exception as exc:   # a courtesy line must not fail the brief; the failure is named, never a blank
        return [f"Closed words of work/grounding.yaml: could not be built ({type(exc).__name__})."]


# --- the S5 plan and its windows (SC1-14 C2 = SC1-15) ----------------------------------------------------

CODE_FILE_BYTES = 28_000      # the side file of code: under the guard's whole-read cap, with room (E15)
EXCERPT_LINES = 60            # code lines of one excerpt; the rest is named, not cut in silence
HEAD_LINE_CHARS = 400         # one added head line; the head is never shrunk, so what is added is bounded
RUBRIC = "plugin:references/code-review-rubric.md"


def _sp():
    import s5_plan
    return s5_plan


def _s5_kind(task_root: Path, state: dict, dispatch: dict) -> tuple:
    """`(kind, why, state)` of an S5 dispatch of a plan role: `plan` (the plan dispatch, `controller.s5_part_of`), `window` (a window of
    a story on the plan form, `s5_plan.mode` = planned), `legacy` (the earlier form: the brief is what it was; so is a dispatch the
    controller's file does not hold), `unknown` (the form could not be read: the brief says so, because a window briefed as the earlier
    form on a planned story would never hear of its plan, FR-59). `state` is `state/controller.json`, the file this brief already
    reads its dispatch from (the controller's projection)."""
    if not dispatch:
        return "legacy", "no record of this dispatch", state
    try:
        from controller import s5_part_of
        if s5_part_of(dispatch) == "plan":
            return "plan", "", state
        form, why = _sp().mode(task_root, state)
    except Exception as exc:  # noqa: BLE001
        return "unknown", f"{type(exc).__name__}: {_short(exc, 100)}", state
    return ("window" if form == "planned" else "legacy"), why, state


def _plan_cap() -> tuple:
    """`(the guard's whole-read cap in bytes | None, why not)`: asked of `guard_pre_tool.big_read_cap`, its one reader. None = could
    not be read (E39: the plan is then named whole and the line says the cap was not checked)."""
    try:
        import guard_pre_tool
        return int(guard_pre_tool.big_read_cap(hooklib.load_config() or {})), ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {_short(exc, 80)}"


def _rel(task: str, name: str) -> str:
    return f"qa-factory/artifacts/{task}/{name}"


def plan_dispatch_lines(task_root: Path, task: str, dispatch_id: str, role: str, state, write: bool, project: Path) -> dict:
    """What the PLAN dispatch of S5 reads (step 1): `{head, files, sides}`. The plan itself - or, when it is over the guard's whole-read
    cap, the parts of it as the windows will cut it (`s5_plan.window_slice`, one side file per window, each written whole and
    named with its size; E39); the cap not readable -> the plan whole and the line says it was not checked. The critic is also
    named its review form, the rubric's «On the plan», and on a re-look the number its new remarks start after (the chain's last PR-n).
    `sides` is `{file name under work/briefs: text}`, written by the caller only for a real brief."""
    plan_path = task_root / PLAN_FILE
    head, files, sides = [], [], {}
    author = role == "qa-automator"
    what = ("the plan you write: the skeleton is there; you fill tests, remainders, fixtures, refactor" if author
            else "the plan you review")
    if author:
        head.append("Your work is the plan, not the code: fill work/s5-plan.json (one row of your digest per case). Cases with the "
                    "same setup and action are one parameterized test (test-code-patterns.md «Executable shape»); a test kept apart "
                    "says why in `apart_reason`. `s5_plan.py --check` is the exit check; its hints are advice, not repairs")
    else:
        head.append("Your work is the plan review, not the code: judge work/s5-plan.json against the cases and fill your review form "
                    "(verdict, remarks PR-n)")
        rows, why = _sp().hint_rows(task_root)
        if why:
            head.append(f"grouping hints not computed ({_short(why, 80)})")
        elif rows:
            head.append(f"`s5_plan.py --check` prints {len(rows)} grouping hint(s): tests at one level in one file that each prove "
                        "one case. Judge whether they share setup and action and whether each `apart_reason` holds (rubric «On the "
                        "plan»); a test left unmerged is a remark, never a blocker on its own")
    size = plan_path.stat().st_size if plan_path.is_file() else None
    cap, cap_why = _plan_cap()
    if size is None:
        files.append(f"- {_rel(task, PLAN_FILE)}: not written yet - that is the path it will have, and nothing else is it")
    elif cap is None or cap <= 0 or size <= cap:
        note = "" if cap is not None else (f" - not checked against the guard's read cap (it could not be read: {cap_why}); "
                                           "if it is large, read it by ranges: `Grep -n` first, then Read with offset/limit")
        files.append(f"- {_rel(task, PLAN_FILE)} ({size} B) - {what}{note}")
    else:
        sp = _sp()
        try:
            first = sp.window_slice(task_root, n=1, state=state)
            parts = [(n, sp.render_slice(sp.window_slice(task_root, n=n, state=state))) for n in first["windows"]]
            if not parts:
                raise ValueError("the plan has no window")
        except Exception as exc:  # noqa: BLE001 - slices that cannot be cut are named; the plan is then named whole
            files.append(f"- {_rel(task, PLAN_FILE)} ({size} B) - {what}; it is over the guard's whole-read cap of {cap} B and its "
                         f"slices by window could not be cut ({_short(exc, 100)}): read it by ranges, `Grep -n` first, then Read "
                         "with offset/limit")
        else:
            files.append(f"- {PLAN_FILE} is {size} B, over the guard's whole-read cap of {cap} B, so its path is not named; read the "
                         f"parts of the plan as the windows will cut it ({what}):")
            for n, text in parts:
                name = f"{dispatch_id}-plan-w{n}.md"
                sides[name] = text
                big = len(text.encode("utf-8"))
                files.append(f"  - {_rel(task, 'work/briefs/' + name)} ({big} B) - window {n}"
                             + ("" if write else " (not written in this run)")
                             + (" - still over the cap: read it by ranges" if big > cap else ""))
    if not author:
        files.append(f"- {_rel(task, 'work/handoffs/' + dispatch_id + '.yaml')} - your review form (`start` writes it right after this "
                     "brief; `finish` stamps the plan you read)")
        rubric = file_lines([RUBRIC], task_root, project, True)
        files += [line + " - read its section «On the plan» (`Grep -n` it)" for line in rubric]
        last = _last_remark_number(task_root, state)
        if last is not None:
            head.append(f"This is a re-look: number your new remarks after the chain's last PR-n (PR-{last}), so no id repeats")
    return {"head": head, "files": files, "sides": sides}


def _last_remark_number(task_root: Path, state):
    """The highest n of the PR-n ids in the chain of plan reviews, when a critic dispatch of the plan was already accepted (this
    brief is then a re-look): an int (0 when its remarks carry no PR-n); None when there is no earlier review. An unreadable chain
    reads as None (the brief is built; the accept of the review refuses a repeated id on its own)."""
    try:
        chain = _sp().reviews(task_root, state)
    except Exception:  # noqa: BLE001
        return None
    if not chain:
        return None
    best = 0
    for element in chain:
        for remark in element.get("remarks") or []:
            found = re.match(r"PR-(\d+)$", str(remark.get("id") or ""))
            best = max(best, int(found.group(1))) if found else best
    return best


def plan_lines(task_root: Path, task: str, dispatch_id: str, scope: list, state, write: bool) -> dict:
    """What a WINDOW of the plan form is handed of the plan (step 2): `{head, files, sides, piece, plan}`. The slice of the plan for
    the dispatch's cases (`s5_plan.window_slice`: requirements, rows, tests, the critic's remarks for these cases) is a side file
    `work/briefs/<id>-plan.md`; the head gets ONE line with the counts - `N tests planned, M remarks for this window`, or, with no
    test, `no tests planned for this window: write the remainders` (E41) - and ONE more only when the window is over its cap or
    grew (the sentences are `s5_plan.render_slice`'s own, read from its text: one wording). A slice that cannot be cut is named in
    the head and the plan is named whole (AR-28)."""
    sp = _sp()
    rel = _rel(task, f"work/briefs/{dispatch_id}-plan.md")
    try:
        plan = sp.load(task_root)
        piece = sp.window_slice(task_root, cases=list(scope), state=state)
        text = sp.render_slice(piece)
    except Exception as exc:  # noqa: BLE001
        return {"head": [f"Plan slice: could not be cut ({_short(exc, 160)}); the plan is {PLAN_FILE} - read the rows of your cases "
                         "by ranges"],
                "files": [f"- {_rel(task, PLAN_FILE)} ({_size(task_root / PLAN_FILE)}) - the plan; slice it: `Grep -n` your case ids, then "
                          "Read with offset/limit"], "sides": {}, "piece": None, "plan": None}
    tests, remarks = len(piece["tests"]), len(piece["remarks"])
    counts = (f"{tests} tests planned, {remarks} remarks for this window" if tests
              else f"no tests planned for this window: write the remainders; {remarks} remarks for this window")
    head = [f"Plan slice {rel}: {counts}."]
    notes = [line for line in text.splitlines() if line.startswith(("This window holds", "This window grew"))]
    if notes:
        head.append(_short(" ".join(notes), HEAD_LINE_CHARS))
    files = [f"- {rel}{'' if write else ' (not written in this run)'} - the plan for your cases: requirements, rows, tests, and the "
             "remarks for them (the plan review's and the case critic's concerns)"]
    return {"head": head, "files": files, "sides": {f"{dispatch_id}-plan.md": text}, "piece": piece, "plan": plan}


def _row_field_lines() -> list:
    """The fields a `tests[]` row of the manifest owes, rendered from their ONE carrier `window_record.REQUIRED_ROW_FIELDS` (axis 28,
    AR-13) in the words of `manifest_from_tests._legend_line`: no list of names is spelled here."""
    try:
        import window_record as WR
        out = []
        for name, spec in WR.REQUIRED_ROW_FIELDS.items():
            if spec.filled_by == "automator":
                out.append(f"- {name}: {spec.what}" + (f" (one of: {', '.join(spec.values)})" if spec.values else ""))
            else:
                out.append(f"- {name}: {spec.what}; written by the marker, not by hand: {spec.origin_door}")
        return out
    except Exception as exc:  # noqa: BLE001
        return [f"- the row fields could not be read ({type(exc).__name__}); `manifest_from_tests.py` prints them after its write"]


def _marker_form_lines() -> list:
    """The form of the `qa` marker a test of the window carries, rendered from its ONE carrier `manifest_from_tests` (the marker names
    in `references/case-markers.json`, `QA_KWARGS`, `UNRESOLVED_KWARGS`, `SHAPES`; AR-13): no key is spelled here, so a key added there
    reaches the role with no edit in this file. Before this the role learned the form from the refusals of the script, one per round
    (EP1-25, TP1-12586: three rounds, and the second window repeated the first one's third). Anything unreadable gives one line
    with the door, never a missing brief. The last line is the code check's, not the marker's (TQ1-16): a `sleep` in a fixture of
    a `conftest.py` the window changed is refused by `s5_precheck` like one in a test, and the role learned that from the refusal."""
    tail = ["- `consolidates` is not a marker key: the script writes it",
            "- the parameter-list module is found through the test file's import; `--file` is for what it cannot find",
            "- wait for a condition, not seconds; fixtures in conftest are the window's code too"]
    try:
        import manifest_from_tests as MFT
        qa, unresolved = MFT.MARK_QA, MFT.MARK_UNRESOLVED
        return [f"- `@pytest.mark.{qa}(...)` takes these keys and no other: {', '.join(f'`{k}`' for k in MFT.QA_KWARGS)}; `case` is required, "
                f"`shape` is one of {', '.join(MFT.SHAPES)}",
                f"- example: `@pytest.mark.{qa}(case=\"<case id>\", then=[1, 2], partition=\"<partition id>\", shape=\"<the planned shape>\")` "
                "- `then` are the numbers of the case's Then clauses this test asserts",
                f"- `@pytest.mark.{unresolved}(...)` takes: {', '.join(f'`{k}`' for k in MFT.UNRESOLVED_KWARGS)}"] + tail
    except Exception as exc:  # noqa: BLE001
        return [f"- the marker form could not be read ({type(exc).__name__}); `manifest_from_tests.py --help` prints the keys it takes"] + tail


def window_code_file(project: Path, plan, tests: list, label: str = "", task_root=None) -> tuple:
    """`(markdown, omitted)`: the code a window will touch, for its side file `work/briefs/<id>-code.md` (step 2). For every test of the
    window: the body of the test it `extends` (`probe_by_code.parse_node`/`locate`, `.py` only), the definitions of the fixtures it
    `uses` (the plan's own `fixtures[]` file, the test's file, then the conftest chain of its directory up to the project root), and
    ONE neighbouring test per test file (the nearest test function of the file; when the file lacks the test, its first; no file or
    no function, the first test function of the directory). An excerpt is at most `EXCERPT_LINES` code lines and names what it left
    out; the file is at most `CODE_FILE_BYTES`: 28 000 passes whole, 28 001 drops excerpts from the END and lists them as
    `file:lines` in `omitted` and under a heading. What is not found or not checked is a line, never silence (E16). The fields of
    a manifest row are rendered from their carrier (axis 28). With `task_root` the header also names, per fixture the window uses,
    the instances of earlier windows that hold a receipt and reach it (`_CodeCollector.invalidates`, HF8-18): a heads-up, no ban;
    what could not be read is a line under "Not found, not checked", and a window with no such fixture has no section."""
    sp = _sp()
    ctx = _CodeCollector(project, sp, plan)
    for test in tests:
        ctx.one_test(test)
    shared = _shared_fixture_map(ctx, tests, task_root) if task_root is not None else {}
    return _fit_code_file(ctx.excerpts, ctx.notes, label, shared, ctx.helper_lines(tests))


HELPER_NAMES = 60             # names of the helpers a window is told exist; the rest is counted, never cut in silence


def _names_by_module(modules: list, cap: int, more: str) -> list:
    """The ONE formatter of `path: names` (AR-13): one line `` `path`: `a`, `b` `` per module of `modules` ([(path, [names])]),
    at most `cap` names in all in the order given, then, when names were left, a last line `(+N more: <more>)` - the count is
    never cut in silence (FR-41). The window's helper section (`_CodeCollector.helper_lines`) and the manual stand's `Helpers` line
    both go through it. A module line starts with a backtick, the count line with `(+`."""
    out, left = [], cap
    total = sum(len(names) for _path, names in modules)
    for path, names in modules:
        if left <= 0:
            break
        out.append(f"`{path}`: " + ", ".join(f"`{n}`" for n in names[:left]))
        left -= len(names[:left])
    return out + ([f"(+{total - cap} more: {more})"] if total > cap else [])


def _shared_fixture_map(ctx, tests: list, task_root) -> dict:
    """`ctx.invalidates` over the task's automation manifest. An absent manifest (the first window) is silence; a manifest that
    cannot be read - not JSON, or JSON that is not an object - is ONE line in `ctx.notes`, not silence (AR-28, FR-41)."""
    unlisted = "the instances an edit of a shared fixture would make stale are not listed"
    try:
        import contract
        path = contract.artifact(Path(task_root), "automation-manifest.json")
        if not path.is_file():
            return {}
        try:
            manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            ctx.notes.append(f"the manifest cannot be read ({type(exc).__name__}): {unlisted}")
            return {}
        if not isinstance(manifest, dict):
            ctx.notes.append(f"the manifest cannot be read (it holds {type(manifest).__name__}, not an object): {unlisted}")
            return {}
        return ctx.invalidates(tests, Path(task_root), manifest)
    except Exception as exc:  # noqa: BLE001  (AR-28: named, never silence)
        ctx.notes.append(f"the instances an edit of a shared fixture would make stale could not be listed ({type(exc).__name__})")
        return {}


class _CodeCollector:
    """The excerpts and notes of `window_code_file` (fix Y, F-13: split out of the function, no change of behaviour)."""

    def __init__(self, project: Path, sp, plan):
        self.project, self.sp = project, sp
        self.notes, self.excerpts, self.seen, self.cache, self.done_files = [], [], set(), {}, set()
        self.fixture_files: list = []         # the files a `uses` fixture was found in (their imports are helpers too, F-8)
        self.fixtures = {str(r.get("name")): r for r in sp._rows(plan, "fixtures")}

    def read(self, rel):
        """`(path, lines, tree, why)` of a project file, parsed once; `why` says what failed."""
        import ast
        if rel not in self.cache:
            path, why = self.sp._project_file(self.project, rel)
            out = (None, None, None, why or "no such file under the project")
            if path is not None:
                try:
                    text = path.read_text(encoding="utf-8-sig")
                    out = (path, text.splitlines(), ast.parse(text), "")
                except (OSError, ValueError, SyntaxError) as exc:
                    out = (path, None, None, f"cannot be parsed ({_short(exc, 60)})")
            self.cache[rel] = out
        return self.cache[rel]

    def helper_lines(self, tests: list) -> list:
        """The lines of the header section `## Helpers that already exist` (TQ1-19): the functions and the public methods of the
        project modules the window's test files, and the files of the fixtures they `use`, import (`copy_detector.imported_files`:
        the SAME reader the exit gate compares against, relative imports and the conftest chain included; names by
        `repo_map._defs`), `<module>: <names>`; at most `HELPER_NAMES` names, then `(+N more: repo map)`. A file that is not
        written yet is NAMED, never read as "no helper" (FR-41); no module found in files that were read is one line that says
        so; a failure to read is one line with the door - the role reads this BEFORE it writes a helper (FR-38)."""
        try:
            import copy_detector as CD
            import repo_map
            seen, modules, unread = set(), [], []
            files = [f for f in dict.fromkeys([str(t.get("file") or "").replace("\\", "/") for t in tests if isinstance(t, dict)]
                                              + self.fixture_files) if f]
            for tfile in files:
                path, _lines, tree, _why = self.read(tfile)
                if tree is None:
                    unread.append(tfile)
                    continue
                for module in CD.imported_files(self.project, path):
                    try:
                        rel = module.resolve().relative_to(self.project.resolve()).as_posix()
                    except (OSError, ValueError):
                        continue            # a module outside the project is not read
                    if rel in seen or rel == tfile:
                        continue
                    seen.add(rel)
                    _classes, defs = repo_map._defs(module.read_text(encoding="utf-8-sig", errors="replace"))
                    names = [d for d in dict.fromkeys(defs) if not d.startswith("_")]
                    if names:
                        modules.append((rel, names))
            tail = ([f"- not read (not written yet, or not parsed): {', '.join(f'`{f}`' for f in unread[:4])}"
                     + (f" (+{len(unread) - 4} more)" if len(unread) > 4 else "")
                     + "; their imports are not listed - `repo_map.py` lists the project's utilities"] if unread else [])
            if not modules:
                return tail or ["- no helper module found in the imports of this window"]
            return ["- " + line for line in _names_by_module(modules, HELPER_NAMES, "repo map")] + tail
        except Exception as exc:  # noqa: BLE001 - a courtesy section must not fail the brief; the failure is named
            return [f"- the helpers could not be listed ({type(exc).__name__}); `repo_map.py` lists the project's utilities"]

    def add(self, title, rel, lines, node):
        first = min([node.lineno] + [d.lineno for d in node.decorator_list])
        last = node.end_lineno
        if (rel, first, last) in self.seen:
            return
        self.seen.add((rel, first, last))
        code, pointer = lines[first - 1:last], ""
        if len(code) > EXCERPT_LINES:
            code, shown = code[:EXCERPT_LINES], first + EXCERPT_LINES - 1
            pointer = f"(cut: lines {shown + 1}-{last} of {rel} are not shown; Read it with offset/limit)"
            last = shown
        self.excerpts.append({"title": title, "where": f"{rel}:{first}-{last}", "code": code, "pointer": pointer})

    def one_test(self, test: dict) -> None:
        from pathlib import PurePosixPath
        tid, tfile = str(test.get("id")), str(test.get("file") or "").replace("\\", "/")
        here = PurePosixPath(tfile).parent if tfile else PurePosixPath(".")
        self.extends(test, tid)
        self.fixture_excerpts(test, tid, tfile, here)
        if tfile and tfile not in self.done_files:
            self.done_files.add(tfile)
            self.neighbour(test, tid, tfile, here)

    def extends(self, test: dict, tid: str) -> None:
        import probe_by_code as PB
        extends = str(test.get("extends") or "").strip().replace("\\", "/")
        if not extends:
            return
        if not extends.split("::", 1)[0].endswith(".py"):
            self.notes.append(f"{tid} extends {extends}: not a Python file, so its body is not extracted (not checked)")
            return
        try:
            spec = PB.parse_node(extends, self.project)
            _p, lines, tree, why = self.read(spec["file"])
            if tree is None:
                self.notes.append(f"{tid} extends {extends}: not found ({why})")
            else:
                self.add(f"{tid}: {extends} (the test you extend)", spec["file"], lines, PB.locate(tree, spec["chain"], spec["function"]))
        except PB.Refusal as exc:
            self.notes.append(f"{tid} extends {extends}: not found ({_short(exc, 100)})")

    def fixture_excerpts(self, test: dict, tid: str, tfile: str, here) -> None:
        """The definitions of the fixtures the test `uses`: the plan's own file, the test's file, then the conftest chain upward."""
        for name in [str(u) for u in test.get("uses") or [] if isinstance(u, str)]:
            row = self.fixtures.get(name) or {}
            if row.get("new") is True:
                self.notes.append(f"fixture {name}: new, to be written in {row.get('file') or 'a file of the plan'} by this plan")
                continue
            places = self.fixture_places(row, tfile, here)
            if not any(self.fixture_in(place, name, tid) for place in places):
                self.notes.append(f"fixture {name}: not found in {', '.join(places)}")

    def fixture_places(self, row: dict, tfile: str, here) -> list:
        """Where a fixture of a test is looked for, in order: the plan's own file, the test's file, the conftest chain upward."""
        conftests, step = [], here
        while True:
            conftests.append("conftest.py" if str(step) == "." else (step / "conftest.py").as_posix())
            if str(step) == "." or step.parent == step:
                break
            step = step.parent
        return [p for p in dict.fromkeys(([str(row["file"])] if row.get("file") else []) + ([tfile] if tfile else []) + conftests)]

    def fixture_node(self, place: str, name: str):
        """`(lines, node)` of the fixture `name` defined in `place`, or None."""
        import ast
        _p, lines, tree, _why = self.read(place)
        node = next((n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
                     and any("fixture" in ast.unparse(d) for d in n.decorator_list)), None) if tree is not None else None
        return None if node is None else (lines, node)

    def fixture_in(self, place: str, name: str, tid: str) -> bool:
        found = self.fixture_node(place, name)
        if found is None:
            return False
        self.add(f"fixture {name} (used by {tid})", place, lines=found[0], node=found[1])
        if place not in self.fixture_files:
            self.fixture_files.append(place)
        return True

    def invalidates(self, tests: list, task_root: Path, manifest) -> dict:
        """`{"<fixture> (<file>)": [instance ids]}` - for each EXISTING fixture (not `new: true`) the window's tests `use`, the
        instances of the manifest that are not this window's own, hold a receipt of a live check (`proof_level._receipt_variants`,
        the one reader of which receipts a row reaches) and reach that very fixture (`s5_precheck._fixture_closure`, the one reader of
        what a test reaches). A heads-up: editing the fixture makes those live checks stale. An instance with no receipt, a fixture
        the plan introduces, a window that uses none and a manifest with no rows give nothing (empty, not unknown). What cannot be
        read is ONE line in `notes` (AR-28) - a closure that raises names its instance, an unreadable manifest is the caller's line."""
        import contract
        rows = contract.manifest_tests(manifest if isinstance(manifest, dict) else {})
        if not rows:
            return {}
        wanted = self.wanted_fixtures(tests)
        if not wanted:
            return {}
        own = {(str(t.get("file") or "").replace("\\", "/"), contract.function_name(str(t.get("function") or t.get("id") or "")))
               for t in tests}
        reached = self.reached_by_receipted(rows, manifest, task_root, own)
        out = {}
        for (name, place) in wanted:
            ids = list(dict.fromkeys(reached.get((name, place), [])))
            if ids:
                out[f"{name} ({place})"] = ids
        return out

    def wanted_fixtures(self, tests: list) -> list:
        """`[(fixture name, the file that defines it)]` of the EXISTING fixtures the window uses, in order, resolved once. The file is
        spelled the way `_fixture_closure` spells it (`posixpath.normpath`: `./tests/x.py` and `tests\\x.py` are `tests/x.py`)."""
        import posixpath
        from pathlib import PurePosixPath
        wanted: dict = {}
        for test in tests:
            tfile = str(test.get("file") or "").replace("\\", "/")
            here = PurePosixPath(tfile).parent if tfile else PurePosixPath(".")
            for name in [str(u) for u in test.get("uses") or [] if isinstance(u, str)]:
                row = self.fixtures.get(name) or {}
                if row.get("new") is True:
                    continue
                place = next((p for p in self.fixture_places(row, tfile, here) if self.fixture_node(p, name) is not None), None)
                if place is not None:
                    wanted.setdefault((name, posixpath.normpath(place.replace("\\", "/"))), None)
        return list(wanted)

    def reached_by_receipted(self, rows: list, manifest, task_root: Path, own: set) -> dict:
        """`{(fixture alias, file): [instance ids]}` of the rows that are not `own`, hold a receipt and reach the fixture. What cannot
        be read - a file that does not parse, a test the file lacks, a closure that raises, a conftest that does not parse (the notes of
        `_fixture_closure`) - is folded into ONE line in `notes` (AR-28)."""
        import contract
        import posixpath
        import proof_level
        import s5_precheck
        reached, broken, closure_notes, parsed_files = {}, [], [], {}
        for entry in rows:
            file = proof_level.test_file_of(entry)
            function = contract.function_name(contract.test_instance_id(entry))
            if not file or not function or (file, function) in own or not proof_level._receipt_variants(entry, manifest, task_root):
                continue
            try:
                if file not in parsed_files:
                    parsed_files[file] = s5_precheck.read_python(self.project / file)[0]
                parsed = parsed_files[file]
                node = parsed.functions.get(function) if parsed is not None else None
                if node is None:        # a file that does not parse, or a test the file does not hold: what it reaches is UNKNOWN
                    broken.append(contract.test_instance_id(entry))
                    continue
                closure, found_notes = s5_precheck._fixture_closure(parsed, node, self.project)
            except Exception:  # noqa: BLE001
                broken.append(contract.test_instance_id(entry))
                continue
            closure_notes += [str(n) for n in found_notes]
            for owner, fixture, rel, is_fixture in closure:
                if is_fixture:
                    where = posixpath.normpath(str(rel or file).replace("\\", "/"))
                    reached.setdefault((s5_precheck._fixture_alias(fixture), where), []).append(contract.test_instance_id(entry))
        closure_notes = list(dict.fromkeys(closure_notes))
        if broken or closure_notes:
            what = ([f"the fixtures {broken[0]}{f' and {len(broken) - 1} more' if len(broken) > 1 else ''} reach could not be read"]
                    if broken else []) + ([_short(closure_notes[0], 160) + (f" (+{len(closure_notes) - 1} more)" if len(closure_notes) > 1 else "")]
                                          if closure_notes else [])
            self.notes.append("; ".join(what) + ": the instances an edit of a shared fixture would make stale may be incomplete")
        return reached

    def neighbour(self, test: dict, tid: str, tfile: str, here) -> None:
        """ONE neighbouring test per test file: the nearest test function of the file; the file with no other test, the first test
        of the directory."""
        import ast
        _p, lines, tree, _why = self.read(tfile)
        tests_in = sorted([n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and n.name.startswith("test")], key=lambda n: n.lineno) if tree is not None else []
        mine = next((n for n in tests_in if n.name == str(test.get("function"))), None)
        others = [n for n in tests_in if n is not mine]
        if others:
            near = min(others, key=lambda n: (abs(n.lineno - mine.lineno), n.lineno)) if mine is not None else others[0]
            self.add(f"{near.name} (a neighbouring test in {tfile})", tfile, lines, near)
        elif not tests_in and not self.first_of_directory(here):
            self.notes.append(f"{tid}: no neighbouring test found near {tfile} (checked: the file and its directory)")

    def first_of_directory(self, here) -> bool:
        """Add the first test function of the first `test_*.py` of the directory that has one; whether one was found."""
        import ast
        for sibling in sorted((self.project / here).glob("test_*.py")) if (self.project / here).is_dir() else []:
            rel = (here / sibling.name).as_posix() if str(here) != "." else sibling.name
            _p, lines, tree, _why = self.read(rel)
            first = next((n for n in sorted(ast.walk(tree), key=lambda n: getattr(n, "lineno", 0))
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")), None) \
                if tree is not None else None
            if first is not None:
                self.add(f"{first.name} (the first test of the directory {here})", rel, lines, first)
                return True
        return False


SHARED_FIXTURE_INSTANCES = 20    # instances named per shared fixture; one more is `(+N more)`
SHARED_SECTION_BYTES = 6000      # the whole section `## If you change a shared fixture`, in bytes (HF8-18 B3)
SHARED_TAIL_RESERVE = 80         # kept free inside it for the line `(+K more fixtures not listed)`


def _shared_fixture_lines(shared: dict) -> list:
    """The header section `## If you change a shared fixture` (HF8-18): per fixture, the instances of earlier windows whose live
    check an edit of it makes stale. At most `SHARED_FIXTURE_INSTANCES` names, then `(+N more)`. No fixture, no section. Said as a
    consequence, not a ban: the factory proves them again at S6.

    The section has a BYTE budget, `SHARED_SECTION_BYTES`, because the header is never cut by the cap fitter (the long names of a
    real story - 48 to 70 characters, times 20 fixtures - would take the whole file): each fixture gets an even share of what is left,
    names are cut from the END of its list and the cut is `(+N more)`; a fixture that cannot show even one name inside its share, and
    every one after it, is the last line `(+K more fixtures not listed)`. The section never exceeds the budget."""
    if not shared:
        return []
    out = ["", "## If you change a shared fixture", "",
           "Changing a fixture below makes these live checks stale; the factory proves them again at S6 (no ban, only what to expect).", ""]
    used, keys = sum(len(line.encode("utf-8")) + 1 for line in out), list(shared)
    budget = SHARED_SECTION_BYTES - SHARED_TAIL_RESERVE
    for pos, key in enumerate(keys):
        share, ids = (budget - used) // (len(keys) - pos), shared[key]
        for count in range(min(len(ids), SHARED_FIXTURE_INSTANCES), 0, -1):
            more = len(ids) - count
            line = f"- `{key}` -> " + ", ".join(f"`{i}`" for i in ids[:count]) + (f" (+{more} more)" if more > 0 else "")
            if len(line.encode("utf-8")) + 1 <= share:
                out.append(line)
                used += len(line.encode("utf-8")) + 1
                break
        else:
            out.append(f"- (+{len(keys) - pos} more fixtures not listed)")
            break
    return out


def _fit_code_file(excerpts: list, notes: list, label: str, shared: dict | None = None, helpers: list | None = None) -> tuple:
    """The cap fitter of `window_code_file`: the file whole when it fits `CODE_FILE_BYTES`, else excerpts dropped from the END and
    listed in `omitted`; even the bare file over the cap names fewer and says how many more. The header (the marker form, the fields,
    the shared-fixture section) is rendered whole and never cut; the section is held to `SHARED_SECTION_BYTES` by
    `_shared_fixture_lines`, so the excerpts that stay are what the cap leaves of the rest, and `omitted` counts the others. `helpers` (lines) is a header section too, after the fields, never cut by the cap; none given, no section."""
    fields = _row_field_lines()
    form = _marker_form_lines()      # in the header, before the fields: the cap drops excerpts from the end and never this
    heads_up = _shared_fixture_lines(shared or {})

    def render(shown, omitted):
        out = [f"# Code you will touch - {label}", "",
               "Built by code from the plan's tests of this window: the tests you extend, the fixtures they use and one neighbouring test per "
               "file. Read it before searching the repository.", "", "## Marker form (what `manifest_from_tests.py` reads from your tests)", ""] \
            + form + ["", "## Fields every tests[] row of the manifest owes", ""] + fields + heads_up
        if helpers:
            out += ["", "## Helpers that already exist", "", "Call or extend one of these before you write a second: a copy of "
                    "an existing helper or fixture, under other names, is refused at the exit.", ""] + helpers
        if notes:
            out += ["", "## Not found, not checked", ""] + [f"- {note}" for note in notes]
        for item in shown:
            out += ["", f"## {item['title']}", f"`{item['where']}`", "```python"] + item["code"] + ["```"]
            out += [item["pointer"]] if item["pointer"] else []
        if omitted:
            out += ["", f"## Left out ({len(omitted)} excerpts; {CODE_FILE_BYTES} B is the limit of this file): read these by range", ""] \
                + [f"- {w}" for w in omitted]
        return "\n".join(out) + "\n"

    shown, omitted = list(excerpts), []
    text = render(shown, omitted)
    while len(text.encode("utf-8")) > CODE_FILE_BYTES and shown:
        omitted.insert(0, shown.pop()["where"])
        text = render(shown, omitted)
    keep = len(omitted)
    while len(text.encode("utf-8")) > CODE_FILE_BYTES and keep > 0:      # even the bare file is over: name fewer, say how many more
        keep -= 1
        text = render([], omitted[:keep] + [f"... and {len(omitted) - keep} more"])
    return text, omitted


def _resumed(dispatch: dict, stage: str, role: str, state) -> bool:
    """Is this dispatch the REWORK of a role that is RESUMED (step 3)? It names its parent, carries the host's `agent_id` (the packet
    carries it only at `resume`), the stage's `rework_mode` (`contract.rework_mode`, the one reader) is `resume`, and the parent is the
    same role's. Anything unreadable is a fresh agent: the full brief serves it. An `agent_id` that `bind` set on the RECORD (it carries
    `agent_bound_seq`) is the id of a FRESH agent the conductor launched, not the parent's: it is no resume (SC1-14 F-3; the same rule as
    `story_step._resumed_lines`)."""
    try:
        import contract
        parent = ((state or {}).get("dispatches") or {}).get(str(dispatch.get("rework_of") or "")) or {}
        agent = contract.request_agent_id(dispatch)
        return bool(dispatch.get("rework_of") and agent
                    and contract.rework_mode(stage) == "resume" and parent.get("role") == role)
    except Exception:  # noqa: BLE001
        return False


def delta_lines(task_root: Path, task: str, dispatch_id: str, dispatch: dict, state, role: str, scope: list, piece, brief_rel: str) -> str:
    """The delta of a resumed role (step 3), the text of `work/briefs/<id>-delta.md`: the fallback line first (a resumed agent with no
    context reads the full brief, E4); the findings of the round - the reason and cause of this rework and the path and id of the
    OTHER role's last form on these cases (the critic's review for the author, the author's form for the critic); for a window, the
    remarks of the window that have no `plan_remarks` row in the parent's form (`s5_plan.remark_rows_missing`); for the plan, the
    blockers of the chain. There is NO "inputs changed" section: nothing records the sha256 of a dispatch's inputs at its start, so
    it could only say "not checked" in every delta (fix Y, F-12; a baseline, if ever wanted, is a finding in `speed-cost`)."""
    sp = _sp()
    from controller import DISCOUNTED, s5_part_of
    kind = s5_part_of(dispatch)
    parent = str(dispatch.get("rework_of"))
    out = [f"# Delta - {dispatch_id} (a rework of {parent})", "",
           f"You are resumed: read this, not the whole brief. If you do not hold the work of {parent}, read the full brief first: {brief_rel}", "",
           "## The findings of this round", "",
           f"- cause {dispatch.get('repair_cause') or 'unnamed'}: {_short(dispatch.get('reason'), 400) or 'no reason recorded'}"]
    dispatches = (state or {}).get("dispatches") or {}
    other = "qa-code-critic" if role == "qa-automator" else "qa-automator"
    mine = set(scope)
    form = None
    for record in dispatches.values():
        if (isinstance(record, dict) and record.get("stage") == "S5" and record.get("role") == other and s5_part_of(record) == kind
                and record.get("status") not in DISCOUNTED and mine & {str(c) for c in record.get("scope") or []}
                and (task_root / "work" / "handoffs" / f"{record.get('id')}.yaml").is_file()):
            form = record
    if form:
        out.append(f"- the {'critic' if other == 'qa-code-critic' else 'author'}'s form on these cases: "
                   f"{_rel(task, 'work/handoffs/' + str(form['id']) + '.yaml')} (dispatch {form['id']})")
    else:
        rerun = (f"`s5_plan.py --task {task} --check`" if kind == "plan"
                 else f"`s5_precheck.py --task-root <task root> --dispatch {dispatch_id} --json`")
        out.append(f"- no form of the {'critic' if other == 'qa-code-critic' else 'author'} on these cases is on disk; what code finds "
                   f"is not stored: run {rerun} for it")
    out += _delta_tail(task_root, parent, sp, kind, role, piece, state)
    return "\n".join(out) + "\n"


def _delta_tail(task_root: Path, parent: str, sp, kind: str, role: str, piece, state) -> list:
    """The kind-specific sections of the delta: the review blockers of a plan, or the remarks of a window with no row."""
    out = []
    if kind == "plan":
        try:
            blockers = [r for r in sp.remarks_of(task_root, state) if r.get("kind") == "blocker"]
        except Exception as exc:  # noqa: BLE001
            blockers, note = [], f"not checked: the review chain cannot be read ({_short(exc, 100)})"
            out += ["", "## Blockers of the plan review", "", f"- {note}"]
        else:
            out += ["", "## Blockers of the plan review", ""]
            out += [f"- {r['id']} [{r['kind']}] {', '.join(f'{k} {r[k]}' for k in ('case', 'test', 'then') if r.get(k)) or 'the whole plan'}: "
                    f"{_short(r['problem'], 200)} Expected: {_short(r['expected'], 160)} Fix: {_short(r['fix'], 160)}"
                    for r in blockers] or ["- none"]
    elif role == "qa-automator" and piece is not None:
        out += ["", "## Remarks of this window with no `plan_remarks` row", ""]
        try:
            import handoff_check     # the one reader of a form: the form plus its waiting values file (F-7)
            rows = handoff_check.form_view(task_root / "work" / "handoffs" / f"{parent}.yaml").data.get("plan_remarks")
            absent = sp.remark_rows_missing(piece["remarks"], rows)
        except (OSError, ValueError) as exc:
            out.append(f"- not checked: the form of {parent} cannot be read ({_short(exc, 100)})")
        else:
            by_id = {r["id"]: r for r in piece["remarks"]}
            out += [f"- {i} [{by_id[i]['kind']}]: {_short(by_id[i]['problem'], 200)} Expected: {_short(by_id[i]['expected'], 160)}"
                    for i in absent if i in by_id] or ["- none"]
    return out


# --- the stand of a manual block (HF5-5, t-1540) ---------------------------------------------

STAND_HEAD = "The stand"
STAND_WHY_CHARS = 80        # how much of a reason a line of the section keeps
STAND_ROLES_MAX = 8         # account names (roles, then env keys) shown in a line; the rest is counted
STAND_PATHS_MAX = 5         # page-object paths of the repo map named in the section
STAND_HELPER_NAMES = 8      # helper names (functions and public methods of the map's utilities) named in the section; the rest is counted
STAND_CASE_LINES_MAX = 10   # `Case actors:` lines; the rest is counted


def _stand_short(text, limit: int = STAND_WHY_CHARS) -> str:
    return " ".join(str(text or "").split())[:limit]


def _stand_names(names: list, limit: int = STAND_ROLES_MAX) -> str:
    return ", ".join(names[:limit]) + (f" (+{len(names) - limit} more)" if len(names) > limit else "")


def _case_actor_text(case: str, actor: dict) -> str:
    """`<case>: <PC id> env KEY | stand_account "<role>" | none`, or "" for a precondition whose check no machine reads."""
    check = actor.get("check")
    if not isinstance(check, dict) or not check:
        return ""
    kind, value = next(iter(check.items()))
    if kind == "env":
        return f"{case}: {actor.get('id')} env {value}"
    if kind == "stand_account":
        return f'{case}: {actor.get("id")} stand_account "{value}"'
    if kind == "none":
        return f"{case}: {actor.get('id')} none"
    return ""


def _record_kind(dispatch: dict) -> str:
    """`manual` / `automation` / "" - the half a dispatch record ran: the controller's own reader (`Controller._record_kind`, the
    request the record was committed with, then its field), so the brief and the driver never disagree on which half this is."""
    try:
        from controller import Controller
        return str(Controller._record_kind(dispatch))
    except Exception:
        return str(dispatch.get("execution_kind") or "")


def _stand_pick(cfg: dict, env_name: str) -> tuple:
    """(entry | None, name, said): the `environments[]` row the block runs on. A named stand: its row. NO name (the pipeline
    names none): the config's ONE row is the stand (the `inherited` rule of `env_probe.selected_probe_config`); two or more rows
    are not guessed between - `said` is the line that tells the role so (F13)."""
    rows = [r for r in cfg.get("environments") or [] if isinstance(r, dict)]
    if env_name:
        named = [r for r in rows if str(r.get("name") or "") == env_name]
        return (named[0] if len(named) == 1 else None), env_name, ""
    if len(rows) == 1:
        return rows[0], str(rows[0].get("name") or ""), ""
    if rows:
        return None, "", "- Stand: not named in pipeline.json"
    return None, "", ""


def _env_file_key_names(block: dict, project: Path) -> tuple:
    """(names | None, rel): the key NAMES of the stand's env file that look like an account or a secret
    (`env_probe.SECRET_NAME`) - never a value, and not the process environment. None: the file is configured and cannot be read."""
    import env_probe as EP
    import gate_preflight as GP
    import manual_capture as MC
    files = GP.configured_env_files(block, project)[0]      # the files the login reads: `env_file` and `env_files`
    if not files:
        return [], ""
    rel = MC._file_names(files, Path(project))
    there = [p for p in files if Path(p).exists()]
    if not there:
        return None, rel
    try:
        return list(dict.fromkeys(k for p in there for k in EP.parse_env_file(p) if EP.SECRET_NAME.search(k))), rel
    except OSError:
        return None, rel


def _stand_address_lines(cfg: dict, project: Path, name: str, entry, block: dict, base: str) -> list:
    """`- API:` and `- Frontend:` of the selected stand (addresses; the env file's values only for the frontend's own address)."""
    import env_probe as EP
    import http_client
    import manual_capture as MC
    out = []
    try:
        values, _from, fatal = EP.load_env(block, project)
    except OSError as exc:
        values, fatal = {}, f"the env file could not be read ({exc.__class__.__name__})"
    if base:
        out.append(f"- API: {http_client.safe_url(base)}")
    else:
        key = str(block.get("base_url_key") or "").strip()
        out.append(f"- API: the value of {key} in {block.get('env_file')} (not printed)" if key and values.get(key)
                   else "- API: not configured (no base_url on the stand's entry and no base_url_key value in the env file)")
    found = EP.frontend_of(cfg, name, values if not fatal else {}, entry=entry, root=project)
    url = found.get("url") or ""
    if url and MC.host_key(url) is not None:
        out.append(f"- Frontend: {http_client.safe_url(url)}")
    else:
        note = ("the address carries credentials" if url else (found.get("notes") or [EP.frontend_door(cfg)["none"]])[0])
        out.append(f"- Frontend: not configured ({_stand_short(note, 120)})")
    return out


def _unpaired_actor_lines(entry, cases_actors: list) -> list:
    """One line for each `stand_account` role of a case that the stand holds no pair for (OH3-40): the role is not one of the
    stand's `credentials_by_role` (`GP.account_role` reads it, the one reader of a role name), or its note does not name exactly
    two keys (`GP.account_keys`). The line tells the role not to sign in as another account in its place - what the runner of a
    case does when its account is missing. `default` has the stand's own two keys and needs no row; an `env` check names its
    keys itself; neither gets a line. No stand row (`entry` is not a dict: none selected, or two and no name) and no actors:
    nothing is said - the `Stand:` line already says why, and an unknown stand is not a stand with no account (FR-59).
    `cases_actors` is a list of `(case, actor)`."""
    import gate_preflight as GP
    if not isinstance(entry, dict):
        return []
    roles = entry.get("credentials_by_role") if isinstance(entry.get("credentials_by_role"), dict) else {}
    out = []
    for case, actor in cases_actors:
        check = actor.get("check") if isinstance(actor, dict) else None
        if not isinstance(check, dict) or next(iter(check), None) != "stand_account":
            continue
        role = str(check["stand_account"]).strip()
        if role == "default":
            continue
        real = GP.account_role(roles, role)
        if real is None or len(GP.account_keys(roles[real])) != 2:
            out.append(f'{case}: role "{role}" has no recorded account. Do not sign in as another account in its place: '
                       "say so in your digest, or ask for the pair.")
    return out


def _case_actor_lines(task_root: Path, scope: list, entry=None) -> tuple:
    """(lines, env keys): who each case's request names (`manual_evidence.request_actors`, the one reader); the keys are the
    NAMES of the `env` checks. A case whose field cannot be read is a line that says so. A role the stand holds no pair for gets
    its own line after the case's (`_unpaired_actor_lines`)."""
    import manual_evidence as ME
    cases, keys = [], []
    for case in scope:
        try:
            actors, said = ME.request_actors(task_root, case)
        except Exception as exc:        # a courtesy line: the brief is still built
            actors, said = [], f"{exc.__class__.__name__}"
        if said:
            cases.append(f"{case}: actors could not be read ({_stand_short(said)})")
            continue
        for actor in actors:
            text = _case_actor_text(case, actor)
            if text:
                cases.append(text)
                check = actor.get("check") or {}
                keys += [str(check["env"])] if next(iter(check), None) == "env" else []
                cases += _unpaired_actor_lines(entry, [(case, actor)])
    return cases, keys


def _repo_stand_lines(repo) -> list:
    if not repo:
        return ["- Page objects (repo map): no map was built for this block"]
    if repo.get("error"):
        return [f"- Page objects (repo map): the map could not be built ({_stand_short(repo['error'])})"]
    paths = [str(u.get("path")) for u in (repo.get("doc") or {}).get("utils") or [] if isinstance(u, dict) and u.get("path")]
    left = len(paths) - STAND_PATHS_MAX
    return ["- Page objects (repo map): " + (", ".join(paths[:STAND_PATHS_MAX]) + (f" (+{left} more: {repo.get('path')})" if left > 0 else "")
                                            if paths else f"none matched ({repo.get('path')})")] + _repo_helper_lines(repo)


def _repo_helper_lines(repo: dict) -> list:
    """`- Helpers (repo map): ...` (SC2-38): the NAMES of the functions and public methods of the map's utilities, in the map's
    rank order, at most `STAND_HELPER_NAMES`, then `(+N more: <map path>)`. No line when there is nothing to name (a map with no
    utilities, a non-Python utility, no `defs`): the `Page objects` line above already says why. Never raises; a name that is not a
    string or is private is skipped; names only (AR-7: the role decides how to use them)."""
    try:
        modules = []
        for util in (repo.get("doc") or {}).get("utils") or []:
            defs = util.get("defs") if isinstance(util, dict) else None
            names = (list(dict.fromkeys(n for n in defs if isinstance(n, str) and n and not n.startswith("_")))
                     if isinstance(defs, list) else [])
            if names and util.get("path"):
                modules.append((str(util["path"]), names))
        lines = _names_by_module(modules, STAND_HELPER_NAMES, str(repo.get("path")))
        if not lines:
            return []
        more = lines.pop() if lines[-1].startswith("(+") else ""
        return ["- Helpers (repo map): " + "; ".join(lines) + (f" {more}" if more else "")]
    except Exception:  # noqa: BLE001 - a courtesy line: the brief is still built
        return []


def manual_stand_lines(task_root: Path, project: Path, cfg: dict, scope: list, env_name: str = "", repo: dict | None = None) -> list:
    """The lines of `## The stand` in the brief of a MANUAL runner block: where the stand is, which accounts the role may sign in
    as (roles, and the NAMES of the env file's secret-looking keys: a role gives the pair to `--as env:USER/SECRET`), which cases
    name an account, and the page objects of the repo map. NAMES and addresses only - no value of the env file but the
    frontend's address (`env_probe.frontend_of`, the one reader, AR-13; an address with credentials in it is `not configured`),
    the API address only when the config's own entry carries it. The case accounts are `manual_evidence.request_actors`'
    (the one reader of the request's `actors`). Never raises: a part that cannot be read is a line that says so, not an absent one.
    `scope` is the block's cases; `repo` the dict `repo_map_for` returns (None: no map was asked)."""
    import env_probe as EP
    import gate_preflight as GP
    cfg = cfg if isinstance(cfg, dict) else {}
    entry, name, said = _stand_pick(cfg, env_name)
    block, base, why, _source = EP.selected_probe_config(cfg, name)
    why = why or ""
    out, keys = [], []
    if said or why:
        out.append(said or f"- Stand: not selected ({_stand_short(why, 160)})")
    else:
        out += _stand_address_lines(cfg, project, name, entry, block, base)
        roles = entry.get("credentials_by_role") if isinstance(entry, dict) else None
        roles = roles if isinstance(roles, dict) else {}
        shown = [f'--as "{r}"' for r in roles]
        out.append("- Accounts: --as default; " + (_stand_names(shown) + " (names only)" if shown else "the stand lists no other"))
        keys = [k for note in roles.values() for k in GP.account_keys(note)]
    cases, case_keys = _case_actor_lines(task_root, scope, None if (said or why) else entry)
    if not (said or why):
        file_keys, rel = _env_file_key_names(block, project)
        keys = list(dict.fromkeys(keys + case_keys + (file_keys or [])))
        out.append("- Env keys: " + (_stand_names(keys) if keys else "none named by the stand's roles, the cases or the env file")
                   + ("" if file_keys is not None else f" (the env file {rel} could not be read)"))
    out += [f"- Case actors: {line}" for line in cases[:STAND_CASE_LINES_MAX]]
    if len(cases) > STAND_CASE_LINES_MAX:
        out.append(f"- Case actors: (+{len(cases) - STAND_CASE_LINES_MAX} more)")
    if not cases:
        out.append("- Case actors: none named by the cases' requests")
    return out + _repo_stand_lines(repo)


# --- the stand a case of S4 may name (GW1-16) -----------------------------------------------

S4_STAND_ROLES = ("qa-case-designer", "qa-case-critic")
S4_INTEGRATIONS_MAX = 15       # integration lines of the S4 brief; the rest is counted and the door named
S4_REQUIRED_BY_CHARS = 80      # how much of `required_by` a line keeps


def s4_stand_lines(cfg: dict | None, role: str, env_name: str = "") -> list:
    """The lines of the S4 brief of the case designer and the case critic that give them the NAMES a case may declare (GW1-16, FR-11,
    FR-38): the integrations the project records for the selected stand, as `{"integration": "<name>"}` takes them, and the stand's
    account roles, as `{"stand_account": ...}` takes them (GW1-27, F-2 b). A name and what the project says of who needs it - never
    a key, where the code reads it, an alternative set, an owner or whether a key is set. In the head, which is never shrunk.

    Only a row with keys that is in scope on this stand (`env_probe.integration_readiness` is not `not_required`) is listed, and a
    name once (the check reads every row of that name): a name the gate would answer with a question to the person is not offered
    to the role. No integrations and no config: no lines - silence is lawful, nothing asks. Never raises: the brief is a courtesy."""
    if role not in S4_STAND_ROLES:
        return []
    try:
        import env_probe as EP
        import gate_preflight as GP
        cfg = hooklib.load_config() if cfg is None else cfg     # None: the project's own config, read here so a failure stays inside the try
        cfg = cfg if isinstance(cfg, dict) else {}
        entry, stand, _said = _stand_pick(cfg, str(env_name or ""))
        environment = cfg.get("environment") if isinstance(cfg.get("environment"), dict) else {}
        rows = environment.get("integrations") if isinstance(environment.get("integrations"), list) else []
        listed: dict = {}
        for spec in rows:
            name = str(spec.get("name") or "").strip() if isinstance(spec, dict) else ""
            if not name or name in listed or not GP.integration_row_keys(spec):
                continue
            if EP.integration_readiness(spec, {}, stand).get("status") == "not_required":
                continue
            listed[name] = "; ".join(GP.required_by_entries(spec))
        out = []
        if listed:
            out.append('Stand integrations (declare one a case needs as a precondition with check {"integration": "<name>"}):')
            for name, words in list(listed.items())[:S4_INTEGRATIONS_MAX]:
                out.append(f"- {name}: {_clip(words, S4_REQUIRED_BY_CHARS)}" if words else f"- {name}")
            if len(listed) > S4_INTEGRATIONS_MAX:
                out.append(f"- and {len(listed) - S4_INTEGRATIONS_MAX} more in qa-factory/config.json, environment.integrations")
        roles = entry.get("credentials_by_role") if isinstance(entry, dict) else None
        if isinstance(roles, dict) and roles:
            out.append('Stand accounts (for check {"stand_account": ...}): ' + _stand_names([str(r) for r in roles]))
        return out
    except Exception:
        return []


S3_ROSTER_MAX = 15            # roster lines of the S3 brief; the rest is counted and the registry named
S3_ROSTER_WHY_CHARS = 120     # how much of an unreadable registry's reason the first line keeps
S3_ROSTER_MARK = "[knowledge:product.roles]"      # a DATA token on every roster line, for counting later; not prose for the role
S3_ROSTER_FILE = "qa-factory/records/project-knowledge.json"
S3_ROSTER_NAME = ("Name every role this story's plan checks in the optional handoff section product_roles (role, sign_in, where in the "
                  "requirements) - also one not listed here; leave it out or write [] when the checks need no particular role.")
S3_ROSTER_NONE = ("Product roles: none recorded yet (a project learns them story by story). Name every role this story's plan checks in "
                  "the optional handoff section product_roles; leave it out or write [] when none.")


def _s3_roster_line(element: dict, stand: str) -> str:
    """One roster element as a line: the role, whether it has an account on the stand (not said when no stand is chosen), and where the
    registry learned it - the person's word with the story, the project's settings, or a role's notice the person has not confirmed."""
    name = _clip(element.get("role") or "?", 60)
    story = _clip(element.get("story") or "", 40)
    facts, source = [], ""
    if element.get("sign_in") == "none":
        facts.append("no sign-in")
    elif element.get("account") is True:
        facts.append(f"an account on {stand}")
    elif element.get("account") is False:
        facts.append(f"no account on {stand} yet")
    if element.get("state") == "noticed_unconfirmed":
        facts.append((f"noticed in {story}" if story else "noticed by a role") + ", not confirmed by the person")
    elif element.get("source") == "person":
        source = " (the person" + (f", {story}" if story else "") + ")"
    elif element.get("source") == "legacy_config":
        source = " (the project's settings)"
    body = ("; ".join(facts) + source).strip()
    return f"- {name}" + (f": {body}" if body else "") + f" {S3_ROSTER_MARK}"


S3_ROSTER_NONE_CRITIC = f"Product roles: none recorded yet (a project learns them story by story). {S3_ROSTER_MARK}"


def s3_roster_lines(task_root, cfg, env_name, audience: str = "strategist") -> list:
    """The lines of the S3 brief that hand the strategist the product's roles and which of them have an account on the chosen stand
    (t-2142 PK0-2, AR-10, AR-13): `project_knowledge.roster`, the one reader. Data and provenance only - which roles THIS story's checks
    need is the strategist's judgment (AR-29), and a role the roster lacks goes into its optional `product_roles` section.

    At most `S3_ROSTER_MAX` roles, then `+N more` naming the registry; the roles the person removed on one line; an empty roster, no
    stand and an unreadable registry each say so (an empty list is a declared outcome, never "no role is needed"). A role line carries
    `S3_ROSTER_MARK`. `audience="critic"` (the S4 case critic): the same data lines, with the header and the empty-roster line of a reader that
    only checks (no instruction to name roles in `product_roles`, no "your judgment" of the strategist). Never raises and never blocks the
    brief: any failure is no lines."""
    critic = audience == "critic"
    try:
        import project_knowledge as PK
        root = RP.project_for_task(task_root)
        cfg = hooklib.load_config() if cfg is None else cfg
        cfg = cfg if isinstance(cfg, dict) else {}
        _entry, stand, _said = _stand_pick(cfg, str(env_name or ""))
        got = PK.roster(root, cfg, stand)
        elements, removed, problem = got["elements"], got["removed"], str(got.get("problem") or "")
        out = []
        if problem:
            out.append(f"Product roles: the record of earlier answers cannot be read ({_clip(problem, S3_ROSTER_WHY_CHARS)}); "
                       "listed from the stand's accounts only.")
        elif elements:
            out.append(f"Product roles ({S3_ROSTER_FILE} and the stand's accounts)"
                       + (":" if critic else ". Which roles this story's checks need is your judgment:"))
        else:
            out.append(S3_ROSTER_NONE_CRITIC if critic else S3_ROSTER_NONE)
        if elements:
            out += [_s3_roster_line(e, stand) for e in elements[:S3_ROSTER_MAX]]
            if len(elements) > S3_ROSTER_MAX:
                out.append(f"+{len(elements) - S3_ROSTER_MAX} more: {S3_ROSTER_FILE}")
        if not stand:
            out.append("Stand: not chosen yet - which roles have an account is not shown.")
        if removed:
            more = f"; +{len(removed) - S3_ROSTER_MAX} more: {S3_ROSTER_FILE}" if len(removed) > S3_ROSTER_MAX else ""
            out.append("Removed by the person: " + ", ".join(
                _clip(r.get("role") or "?", 60) + (f" ({_clip(r['story'], 40)})" if r.get("story") else "")
                for r in removed[:S3_ROSTER_MAX]) + (more or "."))
        if (elements or problem) and not critic:
            out.append(S3_ROSTER_NAME)
        return out
    except Exception:
        return []


def s4_case_budget_line(task_root, role: str) -> list:
    """The ONE line of the S4 brief of the case designer and the case critic that states the case budget of the S3 plan (TQ1-27, FR-38):
    `branch_accounting.plan_case_budget`, the one reader. Absent (until SC5-6 writes it) it says "not set". Never raises: a courtesy."""
    if role not in S4_STAND_ROLES:
        return []
    try:
        import branch_accounting as BA
        n = BA.plan_case_budget(task_root)
        if n is None:
            return ["- Plan case budget: not set for this story"]
        return [f"- Plan case budget: {n} cases for this story (the S3 plan); over it, the case critic's round says why each extra case "
                "stays (`Over the plan case budget:`)"]
    except Exception:
        return []


# --- the approach the project recorded at onboarding (TQ1-11) -------------------------------

APPROACH_ROLES = ("qa-test-strategist", "qa-automator", "qa-code-critic")
APPROACH_LINE_CHARS = 300    # one line of the approach block; longer is cut with " ..." (the reader opens the file)
APPROACH_DOCS_MAX = 6        # strategy documents named by file name; the rest counted
APPROACH_RULES_DOC = "strategy/framework-rules.md"
APPROACH_KEY_WORDS = (("recorded", "recorded"), ("unknown", "unknown"), ("none", "none"), ("not_recorded", "not recorded"))
APPROACH_SHORT_BYTES = 200   # the one-line forms below never exceed this (pinned AT and BEYOND by test_brief_pack)
APPROACH_NOTHING = ("- Project approach: nothing recorded at onboarding (no strategy/framework-rules.md, no config.json test_data, "
                    "no strategy documents); onboarding topic 3 records it; follow the existing tests' fixtures")
APPROACH_ONE_LINE = ("- Project approach (cut for room): code rules strategy/framework-rules.md, data qa-factory/config.json `test_data`, "
                     "documents qa-factory/strategy/; read them, name a deviation with its reason")
NO_FORM_LINE = ("Your final message: the three-part digest shape in your rules (`## Your handover`); the exit gate refuses any "
                "other shape.")      # N4 (R5, E17): a brief with no template still points at the shape, so a role never has none
APPROACH_POINTER = "- Project approach: not shown, the brief is full; see qa-factory/config.json `test_data` and qa-factory/strategy/"


def _approach_injected(role: str) -> bool:
    """Is the code-rules document already injected into this role's prompt? Read from the inject map (data, FR-13)."""
    try:
        paths = (hooklib.load_ref_json("inject-map.json").get("roles") or {}).get(role)
        return isinstance(paths, list) and any(isinstance(p, str) and p.endswith(APPROACH_RULES_DOC) for p in paths)
    except Exception:
        return False


def _approach_code_rules(role: str, task_root: Path, project: Path) -> tuple:
    """-> (line, recorded)"""
    display, path = _resolve("project:" + APPROACH_RULES_DOC, task_root, project)
    if not path.is_file():
        return (f"- code rules: {display}: not recorded - onboarded before this file existed, or onboarding wrote none; "
                "follow test data below and the existing tests' fixtures"), False
    return f"- code rules: {display} ({_size(path)})" + (", already in your prompt" if _approach_injected(role) else ""), True


def _approach_test_data(config) -> tuple:
    """-> (line, recorded): `recorded` is False only when the block is absent or no key of it holds a value."""
    head = "- test data: qa-factory/config.json "
    got = config_contract.test_data_states(config)
    if got["state"] == "absent":
        return head + "has no test_data block - not recorded (onboarding topic 3)", False
    if got["state"] == "malformed":
        return head + "test_data is not an object - not read", True
    groups: dict = {}
    shared = ""
    for name, status in got["keys"]:
        if name == "shared_records":
            shared = status
        else:
            groups.setdefault(status, []).append(name)
    parts = [f"{word}: {', '.join(groups[status])}" for status, word in APPROACH_KEY_WORDS if groups.get(status)]
    said = {"none": "none - every test creates its own", "not_recorded": "not recorded"}.get(shared, shared or "not recorded")
    return (head + '`test_data` (Grep -n "test_data") - ' + "; ".join(parts + [f"shared_records: {said}"]),
            any(status == "recorded" for _name, status in got["keys"]))


def _approach_documents(project: Path, config) -> tuple:
    """-> (line, recorded)"""
    try:
        names = sorted(p.name for p in (project / "qa-factory" / "strategy").glob("*.md") if p.is_file())
    except OSError:
        names = []
    shown = ", ".join(names[:APPROACH_DOCS_MAX]) + (f" (+{len(names) - APPROACH_DOCS_MAX} more)" if len(names) > APPROACH_DOCS_MAX else "")
    own = [str(d.get("path")) for d in (config.get("strategy_documents") if isinstance(config, dict) else None) or []
           if isinstance(d, dict) and d.get("path")]
    return ("- strategy documents: qa-factory/strategy/ " + (shown if names else "holds none")
            + (f"; the project's own: {', '.join(own)}" if own else "")), bool(names or own)


def project_approach_lines(role: str, project: Path, task_root: Path) -> list:
    """The full form of `approach_forms` (the three-line block, or the one line when nothing is recorded)."""
    return approach_forms(role, project, task_root)[2]


def approach_forms(role: str, project: Path, task_root: Path) -> dict:
    """The head lines of the S3 strategist, the automator and the code critic that NAME the approach the project recorded at
    onboarding - the code rules document, the state of each `test_data` key, the strategy documents - by path and state, never
    by content (the owner's word 24.10.2026; FR-15, AR-8). One config read (`read_config_file`) feeds both the test-data and the
    documents lines; the rules path goes through `_resolve` (AR-13). A missing document or block is said by name ("not
    recorded"): an old project is not refused (builder-rules 9); a line is cut at APPROACH_LINE_CHARS. Never raises: the
    brief is a courtesy.

    -> {2: the full block, 1: its one-line form, 0: the pointer line, -1: nothing}: the brief ceiling cuts the block FIRST, level
    by level, before the map, the digests or anything of the person's words (`build`, AR-24). A project with NOTHING recorded (no rules document, no `test_data`
    key with a value, no strategy document) gets ONE line (APPROACH_NOTHING) at levels 2 and 1: the block never costs its three
    lines for nothing."""
    if role not in APPROACH_ROLES:
        return {2: [], 1: [], 0: [], -1: []}
    try:
        try:
            config = config_contract.read_config_file(project)
            unreadable = ""
        except config_contract.ConfigUnreadable:
            config, unreadable = None, "- test data: qa-factory/config.json could not be read; no approach to data is on record for this run"
        rules, rules_on = _approach_code_rules(role, task_root, project)
        data, data_on = (unreadable, True) if unreadable else _approach_test_data(config)
        docs, docs_on = _approach_documents(project, config)
        if not (rules_on or data_on or docs_on):
            return {2: [APPROACH_NOTHING], 1: [APPROACH_NOTHING], 0: [APPROACH_POINTER], -1: []}
        lines = ["Project approach (recorded at onboarding; read it, it is not copied here; a deviation is named with its reason):",
                 rules, data, docs]
        return {2: [line if len(line) <= APPROACH_LINE_CHARS else line[:APPROACH_LINE_CHARS - 4] + " ..." for line in lines],
                1: [APPROACH_ONE_LINE], 0: [APPROACH_POINTER], -1: []}
    except Exception as exc:
        said = f"- Project approach: not read ({type(exc).__name__}), a defect of the factory"
        return {2: [said], 1: [said], 0: [APPROACH_POINTER], -1: []}


def s4_p1_area_lines(task_root: Path, stage: str, role: str) -> list:
    """The body of the S4 brief's `## P1 areas` section for the case designer and the case critic (OH3-34): the P1 areas of the
    strategy that sizing placed requirements in (the ids whose `area_match` equals the area), and each area code could NOT place
    (it names no path), left to the role's judgment. Read from `work/sizing.json` (producer `sizing.py`: `requirements`, `areas`;
    AR-22). Empty outcomes are declared (AR-23) and an unknown is never worded as a negative (FR-41, AR-28): no readable sizing ->
    "sizing not recorded"; no areas read -> "code placed none"; "no requirement falls in a P1 area" ONLY when the register was read,
    at least one area named a surface and none matched. Another stage or role: []."""
    if stage != "S4" or role not in S4_STAND_ROLES:
        return []
    data = _load(task_root / "work" / "sizing.json")
    reqs = data.get("requirements")
    areas = data.get("areas")
    if not isinstance(reqs, list) or not isinstance(areas, dict):
        return ["- sizing not recorded: work/sizing.json is absent, holds no requirements or does not record the areas, so which requirements fall in a P1 area is unknown"]
    by_area: dict = {}
    for item in reqs:
        area = item.get("area_match") if isinstance(item, dict) else None
        if area and item.get("r"):
            by_area.setdefault(str(area), []).append(str(item["r"]))
    out = [f"- {area}: {', '.join(ids)}" for area, ids in by_area.items()]
    named, no_surface = areas.get("named") or [], areas.get("no_surface") or []
    out += [f"- {area}: names no path, so code could not place requirements in it; judge them against it yourself" for area in no_surface]
    if not out and not (named or no_surface):
        out.append(f"- the strategy names no P1 areas (state: {areas.get('state')}), so code placed none")
    elif not by_area and named and areas.get("register_read"):
        out.append("- no requirement of this story falls in a P1 area" + (" that names a path" if no_surface else ""))
    elif not by_area and named and not areas.get("register_read"):
        out.append("- the register was not read, so which requirements fall in a P1 area is unknown")
    return out


CANDIDATE_LINE_MAX = 5     # entries named with their place; the rest only by id (the head grows by ONE line, never more)


def candidate_defect_line(task_root: Path) -> str:
    """ONE line naming the register's candidate defects (`bug:candidate-defect`, G2-15) for the strategist (S3) and the
    automator (S5 plan and window): `Suspect places (candidate defects): R-13 CartPage.tsx:65; R-16 place in the code not
    named.` The only reader is `contract.candidate_defects`. At most CANDIDATE_LINE_MAX entries carry their place, any more are
    named by id with the register as the place to read (none is dropped silently). No candidate, no register, an unreadable one:
    "" and no line."""
    try:
        import contract
        found = contract.candidate_defects(contract.read_text(contract.artifact(task_root, "requirements-register.md")))
    except Exception:
        return ""
    if not found:
        return ""
    shown = [f"{c['r']} {c['file']}:{c['line']}" if c.get("file") else f"{c['r']} place in the code not named"
             for c in found[:CANDIDATE_LINE_MAX]]
    line = "Suspect places (candidate defects): " + "; ".join(shown)
    rest = [c["r"] for c in found[CANDIDATE_LINE_MAX:]]
    if rest:
        line += f", and {', '.join(rest)} in work/requirements-register.md"
    return line + "."


FIT_LINES_MAX = 8          # plan rows given with their test path in the head; the rest go to a side file (TQ1-21)
FIT_ABSENT_CHARS = 160     # how much of a row's `fit_absent` a brief line keeps
FIT_BRIEF_ROLES = {"S4": ("qa-case-designer", "qa-case-critic"), "S5": ("qa-automator",)}
FIT_HEAD = "Existing tests the plan builds on (resolved on the working tree by code - read them at these paths, never search):"


def _fit_row_line(PC, task_root: Path, ctx, row: dict, word: str, noun: str):
    """The head line of ONE plan row (see `fit_target_lines`), or None for a row with nothing to say. A shown target is clipped to
    FIT_ABSENT_CHARS; the path of an `exists` file is never clipped (it comes from the tree)."""
    rid = str(row.get("id") or "?")
    found = PC.fit_target(task_root, row, ctx=ctx) if word and word != "new" else None
    new = f"write the {noun} as new; the page objects and helpers it needs are part of it"
    if found:
        state, target = found["state"], _short(found["target"], FIT_ABSENT_CHARS)
        shown, file = f"{found['word']} {target}", _short(found["file"] or found["target"], FIT_ABSENT_CHARS)
        if state == "exists":
            return f"- {rid}: {found['word']} {found['path']}" + (f"::{found['selector']}" if found["selector"] else "") + " (in the working tree)"
        if state == "unknown":
            return f"- {rid}: {shown} - not verified ({_one_line(found['why'])}): {new}"
        what = {"absent": f"no file at {file}", "folder": f"{file} is a folder", "outside": f"{file} is outside the working tree",
                "unnamed": "it names no test file"}.get(state, state)
        return f"- {rid}: {shown} - NOT in the working tree ({what}): {new}"
    if word == "new" and row.get("disposition") == "automate" and isinstance(row.get("fit_absent"), str) and row["fit_absent"].strip():
        return (f"- {rid}: new - S3: the test it was to build on is not in the working tree "
                f"(\"{_short(row['fit_absent'], FIT_ABSENT_CHARS)}\"): the page objects and helpers it needs are part of this {noun}")
    return None


def fit_target_lines(task: str, task_root: Path, stage: str, role: str, dispatch: dict, plan_rows, dispatch_id: str = "") -> tuple:
    """TQ1-21: `(head lines, side file text)` giving the S4 designer and case critic and the S5 automator the PATH of the test each plan
    row builds on (`fit: extend|param <test>`), resolved on the project's working tree by `planning_contract.fit_target` (fresh at brief
    time, never the S3 verdict), and, for a `new` row, the support-layer hint `fit_absent`. A target that is absent or not verified is
    said to be written as NEW work, its page objects and helpers in scope. S4 reads `dispatch["plan_rows"]` when it has them, else every
    row of `work/test-plan.json`; S5 reads the rows `build` found in the scope's case files. More than FIT_LINES_MAX lines: the head keeps
    the first FIT_LINES_MAX and one line naming the rest and the side file `<dispatch>-targets.md`, which holds all. No plan, no row with
    a target or a `fit_absent`, another stage or role: `([], "")`. An unreadable plan: ONE "not read" line (FR-59). Never raises."""
    if role not in FIT_BRIEF_ROLES.get(stage, ()):
        return [], ""
    noun = "case" if stage == "S4" else "test"
    try:
        dispatch = dispatch if isinstance(dispatch, dict) else {}
        wanted = [str(row) for row in ((dispatch.get("plan_rows") if stage == "S4" else plan_rows) or [])]
        if stage == "S5" and not wanted:
            return [], ""
        path = task_root / "work" / "test-plan.json"
        if not path.is_file():
            return [], ""
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            return [f"Existing tests the plan builds on: not read ({type(exc).__name__}); do not search for them - ask the conductor."], ""
        rows = data.get("rows") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return ["Existing tests the plan builds on: not read (work/test-plan.json holds no list of rows); "
                    "do not search for them - ask the conductor."], ""
        chosen = [row for row in rows if isinstance(row, dict) and (not wanted or str(row.get("id")) in wanted)]
        import planning_contract as PC
        ctx, entries = None, []
        for row in chosen:
            word, _target = PC.split_fit(row.get("fit"))
            if word and word != "new":
                ctx = ctx or PC.target_context(task_root)
            line = _fit_row_line(PC, task_root, ctx, row, word, noun)
            if line:
                entries.append((str(row.get("id") or "?"), line))
        if not entries:
            return [], ""
        shown = [line for _rid, line in entries[:FIT_LINES_MAX]]
        side = ""
        if len(entries) > FIT_LINES_MAX:
            rest = [rid for rid, _line in entries[FIT_LINES_MAX:]]
            shown.append(f"- and {len(rest)} more: {', '.join(rest)} - "
                         + _rel(task, f"work/briefs/{dispatch_id or str(dispatch.get('id') or '<dispatch>')}-targets.md"))
            side = "\n".join([FIT_HEAD, ""] + [line for _rid, line in entries]) + "\n"
        return [FIT_HEAD] + shown, side
    except Exception as exc:  # noqa: BLE001  (a courtesy of the brief, FR-59: said, never silent and never a guess)
        return [f"Existing tests the plan builds on: not read ({type(exc).__name__}); do not search for them - ask the conductor."], ""


def main_coverage_line(task_root: Path) -> str:
    """RG1-3: ONE line for the scout (S1) and the strategist (S3): the test files the diff touches that are already on the main
    branch are existing coverage, not part of this change. Naming the ref is how the role tells them from the story's own tests
    (14857: a test written in the run was listed as regression). The ref is `regression_scope.main_ref`, local reads only; the
    main branch unknown, or anything failing: "" and no line (an unknown is never said as a fact, FR-41)."""
    try:
        import regression_scope
        import runtime_paths
        project = runtime_paths.project_for_task(task_root)
        ref, _why = regression_scope.main_ref(project, regression_scope.project_config(project))
    except Exception:
        return ""
    return f"Test files of the diff already on {ref} are existing coverage, not part of this change." if ref else ""


def user_path_failure_lines(task_root: Path, write: bool = True) -> list:
    """The S2 brief lines naming the places of the code that swallow a failure (G2-14): `user_path_failures.lines` of
    `user_path_failures.find`, the full list written to work/user-path-failures.json when `write`. The tester judges whether a
    place is on a user path. Never raises: a failure is ONE line `not measured: ..., a defect of the factory`, distinct from
    "no match" (P1, the brief is a courtesy)."""
    try:
        import user_path_failures as UPF
        found = UPF.find(task_root)
        if write:
            UPF.write_list(task_root, found)
        return UPF.lines(found)
    except Exception as exc:  # noqa: BLE001
        print(f"brief_pack: user_path_failures failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return ["User-path failures: not measured: user_path_failures.py, a defect of the factory"]


TIMEOUT_ROLE = "qa-automator"
TIMEOUT_PROFILES_SHOWN = 3
TIMEOUT_WHY_CHARS = 120


def _timeout_entry(project, profile: dict) -> str:
    """`<profile id>: <what the project sets>` for one profile's `one_test` command, or "" when it has none. pytest is read through
    `execution_request.pytest_timeout_setting` (the one reader, AR-13); any other runner is said not to be read."""
    import execution_request as ER
    import profile_contract as PC
    spec, problem = PC.profile_command(profile, "one_test")
    argv, argv_problem = PC.command_argv(spec)
    name = str(profile.get("profile_id") or "unknown profile")
    if problem or argv_problem or not argv:
        return ""
    if not ER.is_pytest_command(argv):
        import launch_check
        runner = launch_check.runner_identity(argv)["form_id"] or str(argv[0])
        return f"{name}: not read for this runner ({runner})"
    cwd = Path(str(spec.get("cwd") or "."))
    got = ER.pytest_timeout_setting(cwd if cwd.is_absolute() else Path(project) / cwd, argv, project)
    if got["state"] == "configured":
        return f"{name}: {got['limit_s']:g} s set in {got['source']} (applies when pytest-timeout is installed)"
    if got["state"] == "disabled":
        return f"{name}: none configured ({got['why']})"
    if got["state"] == "unreadable":
        why = got["why"] if len(got["why"]) <= TIMEOUT_WHY_CHARS else got["why"][:TIMEOUT_WHY_CHARS] + "..."
        return f"{name}: could not be read ({why})"
    return f"{name}: none configured"


def test_timeout_line(project, role: str, cfg: dict | None = None) -> str:
    """The ONE brief line naming the project's per-test timeout for the automator (RH2-9, FR-38): per selected profile (at most
    TIMEOUT_PROFILES_SHOWN, then `(+K more profiles)`) what its pytest `one_test` command will apply, or `none configured`, or why it
    could not be read, or that the runner is not read. "" for another role and for a project with no profile command. Never
    raises: a failure is ONE line saying so (the brief is a courtesy, P1)."""
    if role != TIMEOUT_ROLE:
        return ""
    try:
        import profile_contract as PC
        cfg = hooklib.load_config() if cfg is None else cfg
        profiles = PC.selected_profiles(cfg or {})
        entries = [e for e in (_timeout_entry(project, p) for p in profiles[:TIMEOUT_PROFILES_SHOWN]) if e]
        if len(profiles) > TIMEOUT_PROFILES_SHOWN:
            entries.append(f"(+{len(profiles) - TIMEOUT_PROFILES_SHOWN} more profiles)")
        if not entries:
            return ""
        return ("Per-test timeout: " + "; ".join(entries) + " - a test the limit kills is reported as `timeout`: it is your "
                "test's to fit or mark, never the stand's.")
    except Exception as exc:  # noqa: BLE001
        print(f"brief_pack: test_timeout_line failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return f"Per-test timeout: not measured ({type(exc).__name__}), a defect of the factory"


PREFIX_REQ = "Flow requests: "
MAX_REQUEST_LINES = 12      # request lines of the S3 head (6 KB ceiling: the head is never shrunk); the rest is counted, the file is whole
SITE_FILES_SHOWN = 3        # other files a request line names (`also in A.tsx, B.tsx`); the rest is counted
FUNCTIONS_SHOWN = 8         # functions the S3 head names to walk; the rest is counted, the register's function table is whole
PREFIX_WALK = "Functions to walk: "


def _site_note(entry: dict, names: bool) -> str:
    """` (also in <file>[, <file>, <file>][, +K more])` - the other FILES that make this request (a failed request is felt per page) -
    at most SITE_FILES_SHOWN basenames, the rest counted; only the first site's own file: ` (+N more sites in this file)`; `names` False
    (the head is over its room): the old ` (+N more sites)`."""
    also = entry.get("also_at") or []
    if not also:
        return ""
    if not names:
        return f" (+{len(also)} more sites)"
    first = str(entry.get("path") or "")
    other = list(dict.fromkeys(str(a).rsplit(":", 1)[0] for a in also))
    other = [f for f in other if f != first]
    if not other:
        return f" (+{len(also)} more sites in this file)"
    shown = ", ".join(f.replace("\\", "/").rsplit("/", 1)[-1] for f in other[:SITE_FILES_SHOWN])
    return f" (also in {shown}" + (f", +{len(other) - SITE_FILES_SHOWN} more" if len(other) > SITE_FILES_SHOWN else "") + ")"


def request_lines(found: dict, task: str) -> list:
    """The S3 brief lines of a `user_path_failures.flow_requests` result: one per request up to MAX_REQUEST_LINES, `N more, the list is
    in <file>` beyond them (the cut is named, the file is whole), one `not measured: <reason>` per reason, and - only when there is at
    least one request - ONE closing line: each request gets a plan row that fails it with every kind of the perturbation table, the
    oracle the table gives, the R whose flow sends it in `requirements`; or a `request_homes` entry with a reason (RN1-6, AR-26).
    A request line names the other files that make it; when the request lines would pass half of BRIEF_MAX_BYTES the names are
    cut first and the counts return - the lines themselves are never shrunk (the head is never shrunk)."""
    import user_path_failures as UPF
    path = f"qa-factory/artifacts/{task}/{UPF.REQ_LIST_FILE}"
    requests = found.get("requests") or []
    out: list = []
    for names in (True, False):
        out = [f"{PREFIX_REQ}{UPF.request_key(r)} - {r['path']}:{r['line']}{_site_note(r, names)}" for r in requests[:MAX_REQUEST_LINES]]
        if len(requests) > MAX_REQUEST_LINES:
            out.append(f"{PREFIX_REQ}{len(requests) - MAX_REQUEST_LINES} more, the list is in {path}")
        out += [f"{PREFIX_REQ}not measured: {reason}" for reason in found.get("unmeasured") or []]
        if requests:
            kinds, oracle, problem = UPF.failure_axis()
            if problem:
                out.append(f"{PREFIX_REQ}not measured: {problem}, a defect of the factory")
            else:
                out.append(f"{PREFIX_REQ}each one gets a plan row that fails it - {' and '.join(kinds)} - with the oracle \"{oracle}\"; name it in the "
                           f"row's `requests`, and the R whose flow sends it in the row's `requirements`, or in `request_homes` with a reason. The list "
                           f"is what code found: a request you see in the code that it misses goes in a row too. A row closes the request only "
                           f"for the pages it names: another page that makes the same request needs its own row or a stated reason. File: {path}")
        if sum(len(line.encode("utf-8")) + 1 for line in out) <= BRIEF_MAX_BYTES // 2:
            break
    return out


def walk_lines(task_root: Path) -> list:
    """The S3 brief line naming the functions of the register's function table (`sizing.functions_of`, THE reader of that table, called as
    `sizing.compute` calls it): `Functions to walk: <name> (R-1, R-2); ...` up to FUNCTIONS_SHOWN, `(+K more: the register's function table)`
    beyond them, then what a walk is. No table (`read` False) or no counted function: no line. Never raises: a failure is ONE line saying
    it was not measured (P1, the brief is a courtesy). The line reports; no code check judges it (the role walks, or says why not)."""
    try:
        import sizing
        register = sizing.parse_register(Path(task_root) / "work" / "requirements-register.md")
        if not register["found"]:
            return []
        verifiable, unverifiable = sizing._split_rows(register["rows"])
        fx = sizing.functions_of(sizing._read_text(Path(task_root) / "work" / "requirements-register.md"), verifiable,
                                 [u["r"] for u in unverifiable])
        functions = fx["functions"] if fx["read"] else []
        if not functions:
            return []
        named = "; ".join(f"{sizing.clip_name(f['name'])} ({', '.join(f['requirements'])})" for f in functions[:FUNCTIONS_SHOWN])
        more = f"; (+{len(functions) - FUNCTIONS_SHOWN} more: the register's {sizing.FUNCTIONS_HEADING})" if len(functions) > FUNCTIONS_SHOWN else ""
        return [f"{PREFIX_WALK}{named}{more} - each gets a row that walks it as a person does (start, see the result, change, undo; real "
                f"input) and records every oddity, named in the row's `walks`, or a `walk_homes` entry with a reason."]
    except Exception as exc:  # noqa: BLE001
        print(f"brief_pack: walk_lines failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return [f"{PREFIX_WALK}not measured: sizing.functions_of, a defect of the factory"]


# TR3-10 E (FR-38, AR-10): the strategist is told BEFORE the work that a manual-agent row may say what its walk changes. Optional: a
# row that says nothing is no constraint. Emitted ONCE in the S3 head, after the flow request lines (so it shows even when they fail).
WALK_DATA_LINE = ("Walk data: a manual-agent row may carry `walk_data` - a list of {kind, exclusive: true|false, changes} for each record "
                  "the walk changes that other checks read - and `walk_global` - a reason when the walk touches what every check sees; "
                  "leave both out when the walk changes nothing others read.")


def flow_request_lines(task_root: Path, task: str, write: bool = True) -> list:
    """The S3 brief lines naming the requests of the flow (`request_lines` of `user_path_failures.flow_requests`), the full list written to
    work/flow-requests.json when `write`. The strategist plans a row that fails each; the S3 exit refuses what is left. Never raises:
    a failure is ONE line `not measured: ..., a defect of the factory` (P1, the brief is a courtesy)."""
    try:
        import user_path_failures as UPF
        found = UPF.flow_requests(task_root)
        if write:
            UPF.write_requests(task_root, found)
        return request_lines(found, task)
    except Exception as exc:  # noqa: BLE001
        print(f"brief_pack: flow_requests failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return ["Flow requests: not measured: user_path_failures.py, a defect of the factory"]


PREFIX_EXPLORE = "Exploration cells"
CHARTER_FILE = "explore-charter.md"
TRIED_REL = "work/evidence/manual/<case>/tried.md"


def exploration_cell_lines(task_root: Path) -> tuple:
    """`(lines, usable)`: the cells of the perturbation table and the axis oracles as the lines of the exploration side file
    (`user_path_failures.exploration_cells`: one line per request x axis, one per field or action axis). `usable` is False when the table
    has no axis at all (the lines are then ONE sentence that says so, which stays in the brief). A request list that is absent or empty
    prints `not measured: <reason>`, never "no requests" (FR-41); a request with no pattern is a gap line, never a cell."""
    import user_path_failures as UPF
    found = UPF.exploration_cells(task_root)
    if not found["axes"]:
        return [f"{PREFIX_EXPLORE}: references/{found['problem'] or 'perturbations.json has no usable axis'}"], False
    out = [f"{PREFIX_EXPLORE} (references/perturbations.json):"]
    gaps = False
    for axis in found["axes"]:
        kinds = " | ".join(k["id"] for k in axis["kinds"])
        if axis["applies_to"] != "requests":
            out.append(f"- {axis['id']} x {axis['subject'] or 'every ' + axis['applies_to'] + ' of the flow you meet'} x {kinds}")
            continue
        seen, rows = [], []
        for cell in (c for c in found["cells"] if c["axis"] == axis["id"]):
            if cell["request"] not in seen:
                seen.append(cell["request"])
                rows.append(cell)
        for cell in rows[:MAX_REQUEST_LINES]:
            out.append(f"- {axis['id']} x {cell['request']} ({cell['at']}) x {kinds} - fail_request \"{cell['glob']}\" <kind>")
        if len(rows) > MAX_REQUEST_LINES:
            out.append(f"- {axis['id']}: {len(rows) - MAX_REQUEST_LINES} more requests: {UPF.REQ_LIST_FILE}")
        if not rows:
            out.append(f"- {axis['id']} - not measured: " + "; ".join(found["unmeasured"] or ["no cell could be counted"]))
        elif found["unmeasured"] and not gaps:
            gaps = True
            out += [f"- gap: {reason}" for reason in found["unmeasured"]]
    if found["problem"]:
        out.append(f"{PREFIX_EXPLORE}: references/perturbations.json: {found['problem']}")
    out.append("Axis oracles: " + "; ".join(f"{a['id']} - {a['oracle']}" for a in found["axes"]))
    return out, True


def exploration_lines(task_root: Path, task: str, dispatch_id: str = "", briefs_dir=None, write: bool = False) -> list:
    """The head lines of the FIRST manual window of S6 (spec t-1765 X3): the path of the exploration charter and ONE pointer line to the
    side file `<dispatch>-cells.md` that holds the cells and the axis oracles (`exploration_cell_lines`; reference data read once, so it
    does not weigh on the ceiling). Empty once any case folder of the story holds a `tried.md` (the window that explores has run: a
    data rule, no judgment). `write` with `briefs_dir`: the side file is written now, and a failed write turns the pointer into a dash
    with the reason (AR-23), never the cells inline; without `write` the pointer says the file is not written in this run. A table with
    no axis is ONE sentence in the brief itself. The charter is data: its PATH is printed, not its text. Never raises."""
    try:
        if any((task_root / "work" / "evidence" / "manual").glob("*/tried.md")):
            return []
        charter_path = (HERE.parent / "references" / CHARTER_FILE).as_posix()
        out = [f"Exploration charter: {charter_path} - read it before your first capture; your table: {TRIED_REL}"]
        body, usable = exploration_cell_lines(task_root)
        if not usable:
            return out + body
        name = f"{dispatch_id}-cells.md"
        rel = f"qa-factory/artifacts/{task}/work/briefs/{name}"
        what = f"{sum(1 for x in body if x.startswith('- '))} line(s) of cells, then the axis oracles"
        if write and briefs_dir is not None:
            try:
                Path(briefs_dir).mkdir(parents=True, exist_ok=True)
                (Path(briefs_dir) / name).write_text("# Exploration cells - " + (dispatch_id or task) + "\n\n" + "\n".join(body) + "\n",
                                                     encoding="utf-8")
            except OSError as exc:
                return out + [f"{PREFIX_EXPLORE}: — not written ({type(exc).__name__}: {str(exc)[:60]}); rebuild the brief"]
            return out + [f"{PREFIX_EXPLORE}: {rel} - {what}; read it before your first capture"]
        return out + [f"{PREFIX_EXPLORE}: {rel} (not written in this run) - {what}"]
    except Exception as exc:  # noqa: BLE001
        print(f"brief_pack: exploration_lines failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return [f"{PREFIX_EXPLORE}: not measured: user_path_failures.py, a defect of the factory"]


# --- the seven header lines of a charter role (spec t-1765 section 3.4) ---------------------------------

def brief_form() -> dict:
    """references/brief-form.json: the ONE reader of the form of the seven header lines. {} when unreadable (the lines then
    print the em dash and say so, never vanish)."""
    return hooklib.load_ref_json("brief-form.json")


def own_findings(task_root: Path, controller: dict, dispatch: dict) -> str:
    """The task-relative findings file of the critic that reviewed THIS S5 author dispatch's window, or "" (t-1937 TR3-5).
    The critic is the last `qa-code-critic` dispatch of stage S5 created before this one whose scope shares a case with it (windows
    run side by side with disjoint scopes, so a shared case is the same window); never "the newest file on disk". Its file is
    `work/test-code/critic-findings-<critic>.md`; absent, the one file of a story from before (`critic-findings.md`) while that exists.
    No critic, an empty scope or no file: "" - the brief then names no findings, never another window's. Never raises."""
    try:
        mine = {str(c) for c in (dispatch.get("scope") or [])}
        found = ""
        for key, other in ((controller.get("dispatches") if isinstance(controller, dict) else None) or {}).items():
            if not isinstance(other, dict):
                continue
            if str(other.get("id") or key) == str(dispatch.get("id") or ""):
                break                       # only the critics created BEFORE this dispatch
            if other.get("stage") == "S5" and other.get("role") == "qa-code-critic" \
                    and mine & {str(c) for c in (other.get("scope") or [])}:
                found = str(other.get("id") or key)
        if not found:
            return ""
        import findings_path
        return findings_path.resolve(task_root, found)
    except Exception:  # noqa: BLE001 - a brief line never stops a brief
        return ""


def notes_names(task_root: Path) -> list:
    """The per-dispatch notes files that exist (`work/s5-notes/<dispatch>.md`, name order), task-relative: where `NOTES_GLOB` stands in a
    role's files the brief names each of them (shared knowledge, every window reads all); none exist: nothing is added, so a story with no
    notes has the brief it had. Never raises."""
    try:
        return [f"work/s5-notes/{p.name}" for p in sorted_paths((Path(task_root) / "work" / "s5-notes").glob("*.md")) if p.is_file()]
    except OSError:
        return []


def advice_of(task_root: Path, controller: dict, dispatch: dict) -> str:
    """The task-relative advice file the S5 code critic `dispatch` reads (t-1937 TR3-15; AR-13, the one reader): the file of the LATEST
    ACCEPTED automator window dispatch created before it whose scope shares a case with it (`work/advice-S5-<automator>.json`), never
    another window's. That file absent: the old single `work/advice-S5.json` when it exists and the story has ONE window
    (`findings_path.one_window`: with two or more, the old name could be a neighbour's, so it answers nothing). Neither exists: the
    automator's own path when one was found (the brief's absence line then names the right file), else the old name (the story from
    before, as today). Never raises."""
    old = "work/advice-S5.json"
    try:
        import dispatch_identity
        import exit_gate
        import findings_path
        from controller import s5_part_of
        from probe_debt import bare_case_id          # the one normaliser of a scope's case id (the window readers share it)
        mine = {bare_case_id(c) for c in (dispatch.get("scope") or [])}
        found = ""
        for other in dispatch_identity.records((controller.get("dispatches") if isinstance(controller, dict) else None) or {}):
            if other["id"] == str(dispatch.get("id") or ""):
                break                       # only the automators created BEFORE this critic
            if (other.get("stage") == "S5" and other.get("role") == "qa-automator" and other.get("status") == "accepted"
                    and s5_part_of(other) != "plan" and mine & {bare_case_id(c) for c in (other.get("scope") or [])}):
                found = other["id"]
        own = exit_gate.advice_rel("S5", found) if found else ""
        if own and (Path(task_root) / own).is_file():
            return own
        if (Path(task_root) / old).is_file() and findings_path.one_window(task_root):
            return old
        return own or old
    except Exception:  # noqa: BLE001 - a brief line never stops a brief
        return old


def _input_names(stage_def: dict, role: str, s5_kind: str, findings: str = "", advice: str = "") -> list:
    """The input file names of one dispatch: the stage's inputs and the role's files, without the plan files a window or a
    plan dispatch does not read as such. ONE formula for the file list and for the `given:` line. `findings`: the path
    `own_findings` resolved, put where `OWN_FINDINGS` stands; "" drops the word (no critic has reviewed this window yet).
    `advice`: the path `advice_of` resolved, put where `OWN_ADVICE` stands; "" drops the word."""
    swap = {OWN_FINDINGS: findings, OWN_ADVICE: advice}
    names = [swap[n] if n in swap else n for n in list(stage_def.get("inputs") or []) + list(ROLE_FILES.get(role, []))]
    names = [n for n in names if n]
    if s5_kind != "plan":
        names = [n for n in names if n not in PLAN_ONLY]       # a window reads its slice, the earlier form no plan at all
    elif PLAN_FILE in names:
        names.remove(PLAN_FILE)                                # the plan dispatch's own lines (plan_files) name it, or its parts
    return names


def stage_critic_names(stage_def: dict, role: str, task_root: Path) -> list:
    """X2-1: the extra files of the stage critic's brief, for the role that ACCEPTS the stage (`stage_def["acceptance_by"] == role`):
    the artifact under acceptance (the stage's `outputs`), the advice file of the stage (`work/advice-<stage>.json`, named whether or
    not it exists: an absent file prints the absence line of `file_lines`) and the handoff form of the author's last accepted dispatch
    (where its `tried` table is). [] for any other role or a stage with no `acceptance_by`: that brief does not change."""
    if not role or stage_def.get("acceptance_by") != role:
        return []
    stage = str(stage_def.get("id") or "")
    names = [n for n in (stage_def.get("outputs") or []) if isinstance(n, str) and not n.startswith("project:")]
    names.append(f"work/advice-{stage}.json")
    roles = stage_def.get("roles") or []
    form = last_accepted_form(task_root, stage, roles[0]) if roles else ""
    if form:
        names.append(form)
    return names


def reviewed_dispatch(stage: str, role: str, state: dict, pipeline: dict) -> tuple:
    """TR4-12 (2), AR-13: THE reader of "which dispatch does `role` review at `stage`": `(target stage, author's dispatch id, stage_critic)`.
    `("", "", False)` for a role that reviews nothing; `stage_critic` is True when the role judges its OWN stage's author (S2-S4), where
    an empty id still gets the "none yet" brief line; for a consumer an empty id means nothing awaits it. The brief line and the form
    prefill (`story_step._author_argv`) both ask it, so they never name different dispatches. Reads only."""
    import acceptance
    stages = _stages()
    own = stages.get(stage) or {}
    roles = [str(r) for r in own.get("roles") or []]
    if own.get("acceptance_by") == role and roles and roles[0] != role:
        return stage, str(acceptance.stage_author_dispatch(state, own) or ""), True
    target = next((sid for sid, sd in stages.items() if sd.get("acceptance_by") == role and sd.get("roles")
                   and role not in sd["roles"]), "")
    if not target:
        return "", "", False
    return target, str(acceptance.awaits_acceptance(state, target, pipeline) or ""), False


def reviewed_dispatch_id(stage: str, role: str, state: dict, pipeline: dict) -> str:
    """The id `reviewed_dispatch` names, `""` when there is none (the form keeps its placeholder, the brief says so)."""
    return reviewed_dispatch(stage, role, state, pipeline)[1]


def reviewed_dispatch_lines(stage: str, role: str, state: dict, pipeline: dict) -> list:
    """TR4-1 (FR-38, AR-10): the line that hands the role the path of the row of the author's dispatch it reviews, BEFORE the work, in
    the field it must fill (`inputs_read` of its form) - the same value `stage_done.py --acceptance` refuses a form without. [] for a role
    that reviews no author's dispatch. A stage critic (`acceptance_by` is a role of its own stage that is not the author) reviews the
    author of ITS stage; a consumer (the analyst for S6, the scribe for S7) reviews the author of the stage that awaits it. The id is read
    by the readers `stage_done` compares with (`acceptance.stage_author_dispatch`, `acceptance.awaits_acceptance`: the author's last
    accepted dispatch of the current life; never `[0]` by hand), so with several author dispatches the ONE is named. No such dispatch yet:
    one line says so and who acts (never an empty value). A consumer with nothing awaiting it reviews nothing: []. Reads only."""
    stages = _stages()
    target, author, critic = reviewed_dispatch(stage, role, state, pipeline)
    if not target or (not author and not critic):
        return []
    author_role = str((stages.get(target) or {}).get("roles", [""])[0])
    if author:
        from stage_done import reviewed_row_rule      # the one wording of the rule the check applies (AR-22)
        return [f"Reviewed dispatch: {reviewed_row_rule(author, author_role)}."]
    return [f"Reviewed dispatch: none yet - no accepted dispatch of {author_role} exists at {target}, so there is nothing to review; "
            "say so in `unresolved` and do not name a path (the conductor dispatches the author first)."]


def last_accepted_form(task_root: Path, stage: str, role: str) -> str:
    """`work/handoffs/<id>.yaml` of the LAST accepted dispatch of `role` at `stage` (where its `tried` table is), "" when there is none.
    The one reader of that question (AR-13): the stage critic's brief, the readers of `TRIED_READERS` and the gate B packet ask it."""
    state = _load(task_root / "state" / "controller.json")
    found = ""
    for d in ((state.get("dispatches") if isinstance(state, dict) else None) or {}).values():
        if isinstance(d, dict) and d.get("stage") == stage and d.get("role") == role and d.get("status") == "accepted":
            found = f"work/handoffs/{d.get('id')}.yaml"
    return found


def tried_reader_names(stage_def: dict, role: str, task_root: Path) -> list:
    """M-2 (t-1884): the forms whose `tried` table has a reader that is not a stage critic - the brief of `role` at that stage names the
    last accepted form of each author in `TRIED_READERS`. [] for any other role."""
    names = []
    for stage, author in TRIED_READERS.get((str(stage_def.get("id") or ""), role), ()):
        form = last_accepted_form(task_root, stage, author)
        if form:
            names.append(form)
    return names


def prior_retro_lines(task_root: Path, project: Path) -> list:
    """X9 (F-6 a): the reader of the S9 `tried` table in the NEXT story - `[]` or ONE line naming the last accepted retro form of the
    project's most recently active OTHER story and what its `tried` table holds (where that retro looked for the causes of its
    story's misses). Data only: whether a place it searched is worth searching again is the retro analyst's call (AR-29). The other
    story folders come from `config_contract.siblings` (this story and `_archive` are never among them), the form from
    `last_accepted_form`, the order from `archive_task.last_activity` (None sorts oldest, a tie goes to the later folder name), the form
    from `handoff_check.form_view`, the display path from `_resolve`: no second reader (AR-13). `[]` when no other story has an accepted
    S9 retro form - the line is ABSENT, never a placeholder (AR-23). A form that cannot be read is named, never "nothing found" (AR-28).
    Never raises."""
    try:
        import archive_task
        oldest = datetime.min.replace(tzinfo=timezone.utc)
        found = []
        for other in config_contract.siblings(task_root):
            form = last_accepted_form(other, "S9", "qa-retro-analyst")
            if form:
                found.append((archive_task.last_activity(_load(other / "pipeline.json")) or oldest, other.name, other, form))
        if not found:
            return []
        _, _, other, form = max(found, key=lambda f: (f[0], f[1]))
        display = _resolve(form, other, project)[0]
        head = f"Last retro of this project ({other.name}): {display}"
        try:
            import handoff_check
            data = handoff_check.form_view(other / form).data
            if not (isinstance(data, dict) and "tried" in data):
                why = "the form is not a mapping with a `tried` table"
            elif not isinstance(data["tried"], list):
                why = "`tried` is not a list"      # FR-41: a malformed table is unknown, never "empty"
            else:
                why = ""
        except (OSError, ValueError) as exc:
            data, why = {}, str(exc)
        if why:
            return [f"{head} cannot be read ({_short(why, 100)}); where it looked is not known"]
        rows = data["tried"]
        if rows:
            return [f"{head} ({_size(other / form)}) - its `tried` table has {len(rows)} row(s): where that retro looked for the causes "
                    "of its story's misses"]
        return [f"{head} - its `tried` table is empty ({_short(data.get('tried_note'), 100) or 'no tried_note'})"]
    except Exception as exc:  # noqa: BLE001 - a brief line never stops a brief
        return [f"Last retro of this project: could not be looked up ({_short(exc, 100)}); where it looked is not known"]


def _form_line(key: str, value: str, whole: str, form: dict, keep: str = "") -> str:
    """`<key>: <value><keep>`, or `<key>: — (<reason>)` for no data. A value over `line_chars` is cut so that value + ` ... (whole: <where>)` + keep fit."""
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    if not value:
        reason = (form.get("empty") or {}).get(key) or "references/brief-form.json could not be read"
        return f"{key}: — ({reason})"
    limit = form.get("line_chars") if isinstance(form.get("line_chars"), int) else 300
    if len(value) + len(keep) > limit:
        tail = f" ... (whole: {whole})"
        value = value[:max(limit - len(tail) - len(keep), 0)].rstrip() + tail
    return f"{key}: {value}{keep}"


def measured_bytes(text: str, roots=None) -> int:
    """The bytes of `text` as the BUDGET counts them: every checkout-dependent absolute root (the plugin root, which also holds the
    scripts directory) is replaced by a fixed 8-character token first, so the same brief weighs the same on any machine (AR-4); the
    brief TEXT itself keeps the real paths (AR-8). `roots` defaults to the plugin root; an empty root is skipped, a longer root goes
    before a shorter one that is its prefix, and both separators are replaced."""
    found = [HERE.parent.as_posix()] if roots is None else list(roots)
    spelled = {r for root in found if root for r in (str(root).replace("\\", "/").rstrip("/"), str(root).replace("/", "\\").rstrip("\\")) if r}
    for root in sorted(spelled, key=len, reverse=True):
        text = text.replace(root, "<plugin>")
    return len(text.encode("utf-8"))


def head_bytes(lines: list) -> int:
    """The bytes the SD head lines take in the brief (each line and its newline), measured as the budget measures them."""
    return sum(measured_bytes(line) + 1 for line in lines)


def sd_head_lines(task_root: Path, stage: str, role: str, dispatch_id: str, names: list, stage_def: dict, plan_road: bool = True,
                  first_look: bool = False) -> list:
    """The seven header lines (goal, DoD, given, owns, non-goals, handoff, questions) and a blank line, for a role whose
    agent file in THIS copy is a charter; [] for any other role (its brief stays byte for byte). A line with no data prints
    the em dash and the reason (AR-23). Reads only; the data is assembled, nothing is judged."""
    try:
        text = (HERE.parent / "agents" / f"{role}.md").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    if not charter.is_charter(text):
        return []
    form = brief_form()
    mine = (form.get("roles") or {}).get(role) or {}
    registry = hooklib.load_ref_json("artifact-writers.json").get("artifacts") or {}
    owned = [n for n in stage_def.get("outputs") or []
             if isinstance(registry.get(n), dict) and registry[n].get("writer") == f"{role} (the role)"]
    if not plan_road:       # G4b (AR-22): a brief that does not write the S5 plan (legacy, unknown, a window) names no plan file in `owns`
        owned = [n for n in owned if n != PLAN_FILE]
    handoff_rel = f"work/handoffs/{dispatch_id}.yaml"
    import handoff
    contract = handoff.contract_of(stage, role)
    leads = charter.dod_leads(text)
    where = f"agents/{role}.md"
    def lines_for(kept: list, shown: int) -> list:
        given = ", ".join(names[:shown]) + (f" ... and {len(names) - shown} more" if shown < len(names) else "")
        values = {
            "goal": _form_line("goal", charter.outcome_text(text), f"{where} ## Outcome", form),
            "DoD": _form_line("DoD", "; ".join(kept), f"{where} ## Good outcome", form,
                              keep=f"; witness: per item and the tried table, {where} ## Good outcome") if kept
                   else _form_line("DoD", "", "", form),
        }
        if first_look:      # the charter's goal and DoD are the case walk's; the first look has its own (FR-10: one packet, one handoff)
            values["goal"] = _form_line("goal", FIRST_LOOK_GOAL, f"{where} ## First look", form)
            values["DoD"] = _form_line("DoD", FIRST_LOOK_DOD, f"{where} ## First look", form)
        values |= {
            "given": _form_line("given", given if names else "", "## Read these files", form),
            "owns": _form_line("owns", ", ".join(owned + [handoff_rel]) if owned else "", "references/artifact-writers.json", form),
            "non-goals": _form_line("non-goals", mine.get("non_goals"), "references/brief-form.json", form),
            "handoff": _form_line("handoff", f"`{handoff_rel}` (keys: `handoffs/{contract}.yaml`, tried among them)" if contract else "",
                                  "handoffs/index.yaml", form),
            "questions": _form_line("questions", mine.get("questions"), "references/brief-form.json", form),
        }
        order = form.get("order") if isinstance(form.get("order"), list) and form.get("order") else list(values)
        return [values[key] for key in order if key in values]

    # SD_HEAD_MAX_BYTES is a HARD cap (t-1765 X1 fix-4, F3): over it the DoD leads are cut first, from the end (down to one; the
    # `witness: ... tried` suffix stays), then the `given` names from the end (`... and N more`). A head still over the cap is
    # rendered as it is with a last line naming its size - never silently outside the budget; `build` marks the brief too.
    # The cap counts the head as the brief carries it: the lines and the blank line after them.
    kept, shown = list(leads), len(names)
    lines = lines_for(kept, shown)
    while len(kept) > 1 and head_bytes(lines + [""]) > SD_HEAD_MAX_BYTES:
        kept.pop()
        lines = lines_for(kept, shown)
    while shown > 1 and head_bytes(lines + [""]) > SD_HEAD_MAX_BYTES:
        shown -= 1
        lines = lines_for(kept, shown)
    if lines and head_bytes(lines + [""]) > SD_HEAD_MAX_BYTES:
        lines = lines + [f"head: — (head over cap: {head_bytes(lines + [''])} budget B)"]
    return lines + [""] if lines else []


# --- the walk brief (spec t-1957 section 3.3, N3) --------------------------------------------

WALK_RULE = ("Do not read the application's sources: the app card and the page are your map; a selector the card lacks is found "
             "with `look`")
WALK_COMMANDS = (
    "walk_session.py step --task-root <task root> --walk <WALK> --item <i> (--steps-file <file> | --line \"<step>\") [--stop-on <rules>] [--final] [--as <actor>] - the steps of an item, one or many",
    "walk_session.py look --task-root <task root> --walk <WALK> --item <i> [--selector <css>] - the page as it is now",
    "walk_session.py final --task-root <task root> --walk <WALK> --item <i> - the closing snapshot a pass needs",
    "walk_session.py item --task-root <task root> --walk <WALK> --item <i> - starts the attempt of an item",
    "walk_session.py verdict --task-root <task root> --walk <WALK> --item <i> --file <verdict.json> - the verdict of an item",
    "walk_session.py done --task-root <task root> --walk <WALK> - ends your work",
)
MANUAL_EVIDENCE_REL = "manual-evidence.md"


def command_card_lines(task: str, walk: str, commands, tail: str) -> list:
    """The one command card of a walk (F7): `Every command is ...` with `<task root>` and `<WALK>` named, then one bullet per command with
    both placeholders substituted. The walk brief's card and the first look's head are both this."""
    base = f"qa-factory/artifacts/{task}"
    return [f"Every command is `python \"{SCRIPTS}/<script>\"`, run from the project root; `<task root>` = {base}; `<WALK>` = {walk}{tail}"] + [
        "- " + line.replace("<task root>", base).replace("<WALK>", walk) for line in commands]


def walk_record(task_root: Path, dispatch_id: str) -> dict:
    """The walk session's record `state/walks/<dispatch>.json`; {} when absent or unreadable (the fallback road). Never raises."""
    if not dispatch_id:
        return {}
    try:
        rec = hooklib.read_json(task_root / "state" / "walks" / f"{dispatch_id}.json", {}, kind=dict)
    except Exception:  # noqa: BLE001 - a courtesy reader
        return {}
    return rec if isinstance(rec, dict) and rec.get("items") else {}


def _case_sections(text: str) -> dict:
    """{lower-case heading: [lines]} of the `## ` sections of a case file (the one section reader, `traceability._sections`)."""
    import traceability
    return {head.strip()[3:].strip().lower(): body for head, body in traceability._sections(text) if head}


def _section_text(lines: list) -> str:
    return "\n".join(lines).strip()


def _case_file_of(task_root: Path, item: str) -> str:
    """The task-relative path of the case file of `item`, or "" (the walk brief and `case_teardown` both look it up here)."""
    # `case_paths` already resolved THIS item (authoring copy, else the pinned `state/case-versions/<case>/cv_<hash>.md`, whose file name
    # is no case id): its one answer is the file; re-deriving the id from the file name loses every pinned case
    found = case_paths(task_root, [item])
    return found[0] if found else ""


def case_teardown(task_root: Path, item: str) -> str:
    """The text of the `## Teardown` section of the case file of `item`: the carrier the walk brief shows as `Teardown:` and the walk server
    asks for in a verdict. "" = none named (also: the case file is not found or cannot be read - the brief says so in its own line)."""
    try:
        rel = _case_file_of(Path(task_root), str(item))
        text = (Path(task_root) / rel).read_text(encoding="utf-8", errors="replace") if rel else ""
    except Exception:  # noqa: BLE001 - a courtesy reader: no carrier is "none named"
        return ""
    return _section_text(_case_sections(text).get("teardown") or [])


def walk_brief_lines(task_root: Path, task: str, dispatch_id: str, record: dict) -> list:
    """The head lines of a walk dispatch (spec t-1957 3.3): `Walk:`, `App card:`, each item (Given, steps, Thens VERBATIM, teardown).
    Data only: the case files are read, nothing is judged. An item whose case is not found or holds no Then is named in its own
    line, never an empty list (AR-23). Never raises."""
    try:
        import traceability
        actors = [str(a) for a in record.get("actors") or [] if str(a).strip()]
        handles = ", ".join(actors) if actors else "guest"
        if record.get("signed_in"):
            signed = f"yes on {record.get('landed_on') or 'the landing page'}"
        else:
            signed = "no: sign in with fill-account"
        items = [str(i) for i in record.get("items") or []]
        out = [f"Walk: {dispatch_id}, account(s) {handles}, signed in: {signed}",
               f"App card: qa-factory/artifacts/{task}/work/app-card.md",
               f"Items ({len(items)}): " + ", ".join(items)]
        for item in items:
            rel = _case_file_of(task_root, item)
            out += ["", f"### Item {item}"]
            if not rel:
                out += ["Case file: not found in this story - the item has no Given, steps or Thens; say so in its verdict"]
                continue
            path = task_root / rel
            try:
                sections = _case_sections(path.read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                out += [f"Case file: {rel} could not be read ({type(exc).__name__})"]
                continue
            out.append(f"Case file: qa-factory/artifacts/{task}/{rel}")
            given = _section_text(sections.get("given") or [])
            steps = _section_text(sections.get("when") or sections.get("steps") or [])
            out += ["Given:", given or "- none written", "Steps:", steps or "- none written"]
            thens = traceability.case_thens(path)
            if thens:
                out += ["Thens (verbatim):"] + [f"{n}. {text}" for n, text in sorted(thens.items())]
            else:
                out += [f"Thens: NONE FOUND in {rel} - a defect of the case, not an empty list; give no pass, name it in the verdict"]
            tear = _section_text(sections.get("teardown") or [])
            out.append(f"Teardown: {tear}" if tear else "Teardown: none named")
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"brief_pack: walk_brief_lines failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return [f"Walk: {dispatch_id} - the walk lines could not be built ({type(exc).__name__}); read the case files of the scope"]


def fallback_grammar_line() -> str:
    """E3.5: the brief of a manual dispatch with no walk session names the recorder grammar by PATH (it is no longer injected)."""
    return f"Recorder grammar: {(HERE.parent / 'references' / MANUAL_EVIDENCE_REL).as_posix()}"


# --- the first look (t-2277 FL-3) ------------------------------------------------------------

FIRST_LOOK_FILE = "work/first-look.yaml"      # the record `first_look.py put` writes; its name is spelled by stages.json too (the inputs of S3-S7)
FIRST_LOOK_PURPOSE = "first_look"             # the purpose of the optional qa-runner dispatch of S3 (`controller.PURPOSES`)
FIRST_LOOK_CONTRACT = "artifact-contract-first-look.md"
FIRST_LOOK_REQ_MAX = 20                       # requirement lines of the runner's brief; the rest is counted and the register named
FIRST_LOOK_REQ_CHARS = 70                     # how much of a requirement's statement a line keeps
FIRST_LOOK_ROLES_MAX = 8                      # account / role names named in one line
FIRST_LOOK_VERBS = ("item", "step", "look", "done")     # the walk commands the first look uses: ONE table, WALK_COMMANDS (F7)
FIRST_LOOK_STEP_NOTE = "; for a requirement with no screen the step is `http <METHOD> <path> [--body-file <file>]`"
FIRST_LOOK_PUT = "first_look.py put --task-root <task root> --file <rows.yaml> - your rows, once: the record of the first look"
FIRST_LOOK_COMMANDS = tuple(
    line.replace("<i>", "<R-n>") + (FIRST_LOOK_STEP_NOTE if verb == "step" else "")
    for verb in FIRST_LOOK_VERBS for line in WALK_COMMANDS if line.split()[1] == verb) + (FIRST_LOOK_PUT,)
FIRST_LOOK_GOAL = ("Survey the new version on the stand once, before any plan exists: per requirement of the register, what the stand shows, "
                   "in one record sent with `first_look.py put`")
FIRST_LOOK_DOD = ("One row per requirement of the register, each with a status, where you looked and a quote of a capture of this walk; "
                  "`first_look.py put` checks the record when you send it and refuses with the row and the field")
FIRST_LOOK_AHEAD = "The record is checked by `first_look.py put` when you send it: it refuses with the row and the field."


def first_look_input_line(task_root: Path, display: str, size: str = "") -> str:
    """The file line of `work/first-look.yaml` as an INPUT of S3-S7 and of the two critics' briefs (AR-21, AR-23). The record is read
    through `first_look.read` (the one reader); no record, an unreadable one and a `null` one are ONE reading, "no first look", with
    the reason - never an empty line or a guess that the stand was walked. A stale record says so (it confirms nothing). No script is
    named: the roles that read this line may have no shell."""
    try:
        import first_look as FL
        got = FL.read(task_root)
        if got["problem"] and not got["rows"] and not got["null"] and not got["stale"]:
            return f"- {display}: no first look - {_clip(got['problem'], 160)}"
        if got["null"]:
            return f"- {display}: no first look - the stand was not walked ({got['null'].replace('_', ' ')})"
        if got["stale"]:
            return (f"- {display} ({size}): the first look is STALE - it was walked on other code or another register than the current "
                    "ones; it confirms nothing, read it as history")
        return (f"- {display} ({size}): the first look at the stand before the plan - per requirement what the walker saw "
                "(status, where, a quoted capture); an observation, never an oracle")
    except Exception as exc:  # noqa: BLE001 - a courtesy line: the brief is always built
        return f"- {display}: no first look - the record could not be read ({type(exc).__name__})"


def _first_look_accounts(task_root: Path, stand: str, opened: list) -> str:
    """The line naming the accounts the factory already has on `stand`, by ROLE (names only - no key, no value, no file), from the ONE
    reader of that list (`first_look.walk_actors`, t-2277 FL-5 m1: the driver opens the walk from the same call): which of them are OPEN
    in this walk (`opened`, the walk record's actors; only these are named for `--as`), which exist but are NOT opened (a requirement that
    needs one is `unreachable`, `blocked_by: access`, and its why names the account), and the roles that have none anywhere. Never raises."""
    try:
        import first_look as FL
        import walk_session as WS
        root = RP.project_for_task(task_root)
        got = FL.walk_actors(root, hooklib.load_config() or {}, stand, WS.data()["max_actors"])
        have, none, problem = got["accounts"], got["none"], got["problem"]
        shown = _stand_names(have, FIRST_LOOK_ROLES_MAX) if have else "none found"
        left = [a for a in have if a not in opened]
        text = f"Accounts the factory has on {stand or 'the stand'} (names only): {shown}. You sign in only as the walk actors above."
        if left:        # the walk holds at most `max_actors`: an account that exists but is not open is named, never dropped silently
            text += (f" Known but NOT opened in this walk: {_stand_names(left, FIRST_LOOK_ROLES_MAX)} - a requirement that needs one of them is "
                     "`unreachable` with `blocked_by: access`, and its `why` names that account.")
        if problem:     # AR-23: an unreadable registry narrows the roles to the stand's accounts - say so
            text += f" The record of earlier answers cannot be read ({_clip(problem, 80)}): listed from the stand's accounts only."
        if none:
            text += (" Roles with no account found: " + _stand_names(none, FIRST_LOOK_ROLES_MAX)
                     + " - `access` with the role's name is also for these.")
        return text
    except Exception as exc:  # noqa: BLE001 - a courtesy line
        return f"Accounts the factory has: not read ({type(exc).__name__}); say so in `gaps`."


def first_look_runner_lines(task_root) -> list:
    """The head lines of the brief of the S3 `qa-runner` dispatch of purpose `first_look` (t-2277 FL-3, AR-8, AR-10, AR-21): the walk
    and the stand, the test profiles of the walk (screen / HTTP), the requirements of the register with the path of their text, the walk
    commands and the `http` step, `first_look.py put`, the contract path with the form's closed words, the sides of the story that are
    not real, and the accounts the factory has by role (names only). Data only (AR-29): which path to take, which account a requirement
    needs and what the stand shows are the runner's judgment. Never raises; no open walk (no attempt file) is a line that says so
    (AR-23), the same door `first_look.py put` gives."""
    try:
        import first_look as FL
        import grounding_table as GT
        import walk_session as WS
        task_root = Path(task_root)
        task = task_root.name
        base = f"qa-factory/artifacts/{task}"
        attempt = FL.read_attempt(task_root)
        walk, stand = str(attempt.get("walk") or ""), str(attempt.get("env") or "")
        if not walk:
            return ["First look: no walk is open for this story (state/first-look-attempt.json names none); the driver opens it "
                    "(`first_look.py begin`) - record what you saw as a gap in your handover and halt"]
        record = WS.read_record(task_root, walk)
        profiles = record.get("profiles") if isinstance(record.get("profiles"), dict) else {}
        surfaces = [f"{word} (test profile {profiles[key]})" for key, word in (("ui", "screen"), ("http", "HTTP")) if profiles.get(key)]
        actors = [str(a) for a in record.get("actors") or [] if str(a).strip()]
        out = [f"First look: walk {walk} on stand {stand}, a survey walk that is already open; its items are the requirements (R-n).",
               "Surfaces of the walk: " + (", ".join(surfaces) if surfaces else
                                           f"none recorded in state/walks/{walk}.json - say so in `gaps` and take the path that works"),
               "Walk actors: " + (", ".join(actors) if actors else "not recorded in the walk")
               + ("; as an account actor you sign in with `--as <name>` (only these are open in this walk)" if [a for a in actors if a != "guest"]
                  else ""),
               _first_look_accounts(task_root, stand, actors)]
        ids, why = FL.register_ids(task_root)       # the one reader of the ids and their order (AR-13); the texts come from the register reader
        if ids:
            texts = GT.register_info(task_root).texts
            out.append(f"Requirements ({len(ids)}), the text of each in {base}/work/requirements-register.md (the `## Register` table); "
                       "one row per requirement, none left out:")
            out += [f"- {r}: {_clip(texts.get(r, ''), FIRST_LOOK_REQ_CHARS)}" for r in ids[:FIRST_LOOK_REQ_MAX]]
            if len(ids) > FIRST_LOOK_REQ_MAX:
                out.append(f"- +{len(ids) - FIRST_LOOK_REQ_MAX} more: the register above")
        else:
            out.append("Requirements: the register holds none or cannot be read"
                       + (f" ({_clip(why, 120)})" if why else "") + "; record that as a gap and halt")
        out += command_card_lines(task, walk, FIRST_LOOK_COMMANDS, ". `--help` of a script is allowed:")
        words = FL.data()
        out.append(f"Form and words: {(HERE.parent / 'references' / FIRST_LOOK_CONTRACT).as_posix()}. status: "
                   f"{', '.join(map(str, words.get('statuses') or []))}; blocked_by: {', '.join(map(str, words.get('blocked_by') or []))}.")
        met = FL.sides_met(task_root)
        out.append("Sides of the story that are not real: " + ", ".join(f"{name} ({reality})" for name, reality in met.items())
                   + " - code stamps them on the record; name them in `why` where a row speaks about one." if met
                   else "Sides of the story that are not real: none - every side is real.")
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"brief_pack: first_look_runner_lines failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return [f"First look: the brief lines could not be built ({type(exc).__name__}); read the walk record state/walks/ and "
                "references/artifact-contract-first-look.md"]


# --- the first look reaches its consumers (t-2277 FL-4) --------------------------------------

FIRST_LOOK_LINES_MAX = 12                     # first-look lines one brief carries; the rest is `+N more: work/first-look.yaml`
FIRST_LOOK_LINE_CHARS = 180                   # one line, marker included (the head is never shrunk, so what is added is bounded)
FIRST_LOOK_MARK = "[first-look:{}]"           # a DATA token on every line that is about one requirement, for counting later; not prose for the role
FIRST_LOOK_NONE = "First look: there was no first look at the stand for this story."
# (stage, role) -> the kind of lines. Every closed word (the statuses, the red ones, the S7 `blocked_by` filter, the confirmed stand build)
# is read from `references/first-look-statuses.json` through `first_look.py` (AR-1): none is held here.
FIRST_LOOK_KIND = {("S3", "qa-test-strategist"): "s3", ("S3", "qa-case-critic"): "s3", ("S4", "qa-case-designer"): "s4",
                   ("S4", "qa-case-critic"): "s4_critic", ("S5", "qa-automator"): "s5", ("S5", "qa-code-critic"): "s5_critic",
                   ("S6", "qa-runner"): "s6", ("S7", "qa-failure-analyst"): "s7"}
FIRST_LOOK_AUTHOR_KINDS = {"s4": ("screen", "step", "api", "sample"), "s5": ("locator", "api", "sample", "data")}
FIRST_LOOK_HEADS = {
    "s3": "First look (work/first-look.yaml: the walker looked at the stand before this plan; an observation, never an expected value)",
    "s4": "First look - the paths the walker took on the stand, per requirement (an observation, never an expected value; a Then comes "
          "from the requirements):",
    "s5": "First look - what the walker saw on the stand BEFORE your own discovery (an observation, never an expected value). A selector or "
          "route it saw missing is only a provisional `placeholder_locator` row (`tests[].provisional`, assumed_from `first_look:R-n`), "
          "never a settled one:",
    "s7": "First look - rows where the stand did not show what a requirement says (an observation, never a verdict): for each, decide whether "
          "an executed check exists; if none does, whether it is a bug candidate (FR-22):",
}
FIRST_LOOK_CRITIC_RULES = {
    "s4_critic": "Case steps that diverge from the path the walker took, with no reason named, are a finding (a step cites its row "
                 "as `first_look:R-n`).",
    "s5_critic": "A selector or route rediscovered or guessed where the first look saw it is a finding.",
}


def _fl_mark(req) -> str:
    import first_look as FL
    text = str(req or "").strip()
    return FIRST_LOOK_MARK.format(text if FL.REQ_ID.fullmatch(text) else "?")


def _fl_line(row: dict, body: str) -> str:
    """`- R-n <status>[ (blocked_by)]: <body> [first-look:R-n]` - the marker is never clipped away."""
    import app_card as AC
    mark = _fl_mark(row.get("req"))
    head = "- " + AC.first_look_head(row)
    text = f"{head}: {body}" if body else head
    room = FIRST_LOOK_LINE_CHARS - len(mark) - 1
    return (text if len(text) <= room else text[:room - 3] + "...") + " " + mark


def _fl_state(task_root) -> tuple:
    """`("rows", record)` or `("line", [the one line saying why there is no usable record])`: no record, a `null` one (its reason), an
    unreadable one (its reason) and a STALE one (it confirms nothing) are each ONE line, never silence (AR-23, AR-28)."""
    try:
        import first_look as FL
        state = FL.state(task_root)     # the one classification (AR-15); this function only words it
    except Exception as exc:  # noqa: BLE001 - a courtesy block: the brief is always built
        return "line", [f"First look: the record could not be read ({type(exc).__name__}); treat the stand as not walked."]
    kind, got = state["kind"], state["got"]
    if kind == "error":
        return "line", [f"First look: the record could not be read ({state['error']}); treat the stand as not walked."]
    if kind == "null":
        return "line", [f"First look: there was no first look - the stand was not walked ({got['null'].replace('_', ' ')})."]
    if kind == "stale":
        return "line", [f"First look: STALE - walked on other code or another register than the current ones; it confirms nothing, read "
                        f"{FIRST_LOOK_FILE} as history" + (f" ({_clip(got['problem'], 80)})." if got["problem"] else ".")]
    if kind == "absent":
        return "line", [FIRST_LOOK_NONE]
    if kind == "unreadable":
        return "line", [f"First look: the record cannot be read ({_clip(got['problem'], 120)}); treat the stand as not walked."]
    return "rows", got


def _fl_counts(rows: list) -> str:
    import first_look as FL
    words = [str(w) for w in FL.data().get("statuses") or []]
    count = {w: sum(1 for r in rows if r.get("status") == w) for w in words}
    other = len(rows) - sum(count.values())
    return ", ".join([f"{n} {w}" for w, n in count.items()] + ([f"{other} other"] if other else [])) or "no row"


def _fl_red_rows(rows: list, kind: str) -> list:
    """The rows the S3 and S7 lines list: a status of the data file's `red_statuses`; at S7 a row whose status the data file's
    `bug_candidate_blocked_by` maps only when its `blocked_by` is one of the mapped words. No word is held here (AR-1)."""
    import first_look as FL
    red, narrowed = FL.red_statuses(), FL.bug_candidate_blocked_by()
    return [r for r in rows if r.get("status") in red
            and not (kind == "s7" and r.get("status") in narrowed and str(r.get("blocked_by") or "") not in narrowed[r.get("status")])]


def _fl_body(kind: str, task_root, got: dict) -> list:
    import app_card as AC
    rows, path = got["rows"], f"qa-factory/artifacts/{Path(task_root).name}/{FIRST_LOOK_FILE}"
    if kind == "s6":
        return [f"First look: the width was walked on the stand ({len(rows)} requirement(s): {_fl_counts(rows)}); do not repeat the survey - "
                f"go deep, starting from its observations in {path}. Your cases are still walked step by step: a first-look row is an "
                f"observation, never evidence that a case ran."]
    if kind in ("s4_critic", "s5_critic"):
        return [f"First look: the walker's record is {path} (an observation of the stand, never an expected value).",
                FIRST_LOOK_CRITIC_RULES[kind]]
    if kind in FIRST_LOOK_AUTHOR_KINDS:
        wanted, lines = FIRST_LOOK_AUTHOR_KINDS[kind], [FIRST_LOOK_HEADS[kind]]
        for row in rows:
            items = [text for item_kind, text in AC.first_look_path_items(row) if item_kind in wanted]
            if items:
                lines.append(_fl_line(row, "; ".join(items)))
        return lines + ([] if len(lines) > 1 else ["- no row of the record names such a path."])
    lines = [f"{FIRST_LOOK_HEADS[kind]}: {len(rows)} requirement(s) - {_fl_counts(rows)}." if kind == "s3" else FIRST_LOOK_HEADS[kind]]
    if kind == "s3":
        import first_look as FL
        if not FL.stand_build_confirmed() or got.get("stand_build") != FL.stand_build_confirmed():
            lines.append("The stand's build is not established (nobody confirmed which revision is deployed there): a missing or "
                         "contradicting row may be an old build.")
        met = FL.sides_met(task_root)
        if met:
            lines.append("Sides of the story that are not real: " + ", ".join(f"{name} ({reality})" for name, reality in met.items()) + ".")
    red = _fl_red_rows(rows, kind)
    for row in red:
        why = AC.scrub(str(row.get("why") or "")) or "no reason written"
        evidence = row.get("evidence") if isinstance(row.get("evidence"), list) else []
        lines.append(_fl_line(row, why + (f"; evidence {AC.scrub(str(evidence[0]))}" if kind == "s7" and evidence else "")))
    import first_look as FL
    return lines + ([] if red else [f"- no row has a red status ({', '.join(FL.red_statuses())})."])


def first_look_lines(task_root, stage: str, role: str) -> list:
    """The head lines that carry the first look to the role that reads it at `stage` (t-2277 FL-4, AR-8, AR-10, AR-13, AR-21, AR-29):
    S3 the strategist and the plan's reviewer (counts by status, the red rows with their reason, the sides that are not real, the stand
    build when it is not established), S4 the case designer (the path of each requirement) and the case critic (the record's path and the
    rule on a diverging step), S5 the automator (locators, routes and data seen, before its own discovery) and the code critic (the path
    and the rule on a rediscovered selector), S6 the runner (the width was walked) and S7 the failure analyst (the red rows). `[]` for any
    other pair - and for S3 and the critics when `stages.json` names no such role at the stage (a reviewer is never invented).

    Read through `first_look.read` and `app_card.first_look_path_items` (the one reader and the one reading of a path). Data only: no
    line carries a value of the record as an expected one (FR-58, P20) - the record's `why`, quote and evidence are the walker's words, the
    data values and samples are prefixed `seen:`, and no key of a row but the form's own is read. A line about one requirement carries
    `[first-look:R-n]` (counting data). At most FIRST_LOOK_LINES_MAX lines, then `+N more: work/first-look.yaml`. No record, a `null` one,
    an unreadable one and a stale one are ONE line each. Never raises; the code never refuses a role for a hint it did not use (AR-29)."""
    kind = FIRST_LOOK_KIND.get((stage, role))
    try:
        if kind is None or role not in ((_stages().get(stage) or {}).get("roles") or []):
            return []
        state, got = _fl_state(task_root)
        if state == "line":
            return list(got)
        lines = _fl_body(kind, task_root, got)
        if len(lines) > FIRST_LOOK_LINES_MAX:
            lines = lines[:FIRST_LOOK_LINES_MAX] + [f"+{len(lines) - FIRST_LOOK_LINES_MAX} more: {FIRST_LOOK_FILE}"]
        return lines
    except Exception as exc:  # noqa: BLE001 - a courtesy block: the brief is always built
        print(f"brief_pack: first_look_lines failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return [f"First look: the lines could not be built ({type(exc).__name__}); read {FIRST_LOOK_FILE} if it exists."]


def case_critic_roster_lines(task_root, pipeline) -> list:
    """The product's roles for the S4 case critic (t-2277 FL-4): the lines `s3_roster_lines` gives the strategist (`project_knowledge.roster`,
    the one reader, AR-13), each role line with `[knowledge:product.roles]`, WITHOUT the strategist's instruction to name roles in its
    `product_roles` section. An empty roster is one marked line. Never raises; any failure is no lines."""
    try:
        return s3_roster_lines(task_root, None, (pipeline or {}).get("environment"), audience="critic")
    except Exception:
        return []


# --- assembling ----------------------------------------------------------------------------

def build(task: str, stage: str, role: str, dispatch_id: str, write: bool = True,
          output: Path | None = None) -> dict:
    task_root = hooklib.story_root(task, "brief_pack")   # a brief is built for a story that EXISTS; S0 makes the folder
    project = hooklib.project_root()
    pipeline = _load(task_root / "pipeline.json")
    controller = _load(task_root / "state" / "controller.json")
    dispatch = (controller.get("dispatches") or {}).get(dispatch_id) or {}
    scope = [str(c) for c in (dispatch.get("scope") or controller.get("scope") or [])]
    stage_def = _stages().get(stage) or {}
    # t-2277 FL-3: the optional S3 dispatch of the runner that looks at the stand before the plan. Every gate below that is keyed on
    # this word leaves the brief of any other dispatch exactly as it was.
    first_look = role == "qa-runner" and str(dispatch.get("purpose") or "") == FIRST_LOOK_PURPOSE
    briefs_dir = task_root / "work" / "briefs"
    brief_rel = f"qa-factory/artifacts/{task}/work/briefs/{dispatch_id}.md"

    # 1. the header and the digests
    head = [f"# Brief - {dispatch_id} - {role} at {stage}, {task}", ""]
    controller_obj = None
    try:
        from controller import Controller
        controller_obj = Controller(task_root)
    except Exception:
        controller_obj = None
    scope_text = ", ".join(scope) if scope else "the story scope"
    # SC1-14 C2: which S5 dispatch this is. `legacy` (and every other stage or role) is the brief as it was, byte for byte.
    s5_kind, s5_why, s5_state = "", "", None
    from controller import S5_PLAN_ROLES      # the one list of the plan's roles (no import cycle: nothing imports brief_pack at top level)
    if stage == "S5" and role in S5_PLAN_ROLES:
        s5_kind, s5_why, s5_state = _s5_kind(task_root, controller, dispatch)
    win = (window_line(controller_obj, stage, scope)
           if controller_obj and stage in ("S5", "S6") and s5_kind != "plan" else "")      # the plan's scope is all cases, not a window
    head.append(f"Scope: {scope_text}{win}. Environment: {pipeline.get('environment') or '?'}; "
                f"size {pipeline.get('size') or '?'}; source {pipeline.get('implementation_source') or '?'}.")
    if role in _lifecycle_roles():
        # Right after the scope and BEFORE any quoted role claim (the repair line below): the Factory's own
        # statement of the recorded checkout comes first, so a role's earlier halt is never the brief's only
        # branch word. The head is never shrunk: under the 6 KB ceiling the inline map header gives way first.
        head.append(branch_check_line(task_root))
    if stage in ("S1", "S3") and not first_look and (coverage := main_coverage_line(task_root)):
        head.append(coverage)     # RG1-3: the main branch's tests are existing coverage
    if stage == "S3" and not first_look:      # the first look is no plan: it gets none of the strategist's lines (and writes no flow-requests file)
        # G1-2: the index of the implementation diff the strategist labels (the head is never shrunk, like the line above).
        head.append(blast_radius_line(task, task_root, write and output is None))
        head += s3_labelling_vocabulary_lines(dispatch)
        if candidate_defect_line(task_root):
            head.append(candidate_defect_line(task_root))
        head += flow_request_lines(task_root, task, write and output is None)      # RN1-6: the head is never shrunk
        head.append(WALK_DATA_LINE)                                                # TR3-10 E: once, whatever the flow requests did
        head += walk_lines(task_root)                                              # RN1-6: a walk per function
        if role == "qa-test-strategist":       # the stage critic stands on S3 too and gets no roster (FR-56, AR-11)
            head += s3_roster_lines(task_root, None, pipeline.get("environment"))  # PK0-2: the product's roles; the head is never shrunk
    if stage == "S2":
        head += user_path_failure_lines(task_root, write and output is None)       # G2-14: the head is never shrunk
    if dispatch.get("read_first"):
        head.append(f"Read first, before anything else: {', '.join(map(str, dispatch['read_first']))}.")
    if dispatch.get("repair_cause") or dispatch.get("parent_retry"):
        head.append(f"This is a repair dispatch - cause {dispatch.get('repair_cause') or 'unnamed'}"
                    + (f": {_short(dispatch.get('reason'), 200)}" if dispatch.get("reason") else "") + ".")
    if dispatch.get("rework_of"):
        # TP2-2406 S3-3, 15.10.2026: a rework packet named TS-1..TS-4 and TS-8 and the brief of that
        # dispatch held none of them (FR-49: what the packet says reaches the role). Only for a rework: a
        # normal S4 designer dispatch carries EVERY plan row and its brief is unchanged.
        head.append(f"Rework of {dispatch['rework_of']}.")
        if dispatch.get("plan_rows"):
            head.append("Plan rows of this dispatch: " + ", ".join(str(row) for row in dispatch["plan_rows"]) + ".")
    if dispatch.get("purpose"):
        head.append(f"Purpose: {_short(dispatch['purpose'], 300)}")
    if first_look:
        head += first_look_runner_lines(task_root)      # t-2277 FL-3: in the head, which is never shrunk
    # SC1-14 C2 / SC1-15: the plan (its dispatch), or its slice (a window of the plan form). At most two lines added to the head.
    side_files, plan_files, piece, plan_doc = {}, [], None, None
    if s5_kind == "plan":
        got = plan_dispatch_lines(task_root, task, dispatch_id, role, s5_state, write and output is None, project)
        head += got["head"]
        head += [line for line in [candidate_defect_line(task_root)] if line]    # G2-15: ONE line, however many candidates
        plan_files, side_files = got["files"], dict(got["sides"])
    elif s5_kind == "window":
        got = plan_lines(task_root, task, dispatch_id, scope, s5_state, write and output is None)
        head += got["head"]
        head += [line for line in [candidate_defect_line(task_root)] if line]
        plan_files, side_files, piece, plan_doc = got["files"], dict(got["sides"]), got["piece"], got["plan"]
    elif s5_kind == "unknown":
        head.append(f"Plan form: could not be established ({s5_why}); this brief names no plan or slice - ask the conductor whether S5 "
                    f"has a plan ({PLAN_FILE}) before you write")
    # In the head on purpose: the head is never shrunk, and the card and the charter both defer to this line.
    head += case_form_lines(task, task_root, role)
    if stage == "S4":
        head += s4_stand_lines(None, role, str(pipeline.get("environment") or ""))
        head += s4_case_budget_line(task_root, role)
    head += reviewed_dispatch_lines(stage, role, controller, pipeline)      # TR4-1: the row path the stage check needs, before the work
    head += expectation_change_lines(task_root, role, dispatch_id)
    head += proof_required_lines(task_root, role, dispatch_id)
    head += base_log_lines(task_root, role, dispatch_id)
    if stage == "S5" and role in SIDES_ROLES:
        # t-2181 PC-8: the sides of the story (the code critic gets the SAME lines from the same call), then the automator's fields and, on
        # a bind round, its open rows. [] on an all-real story: that brief is as it was. The head is never shrunk; every part is capped.
        head += side_lines(pipeline)
        head += provisional_lines(task_root, pipeline, dispatch, role, dispatch_id)
    if not first_look:
        # t-2277 FL-4 (after PC-8: the build order of §4.4 row h): the case critic's roles, then what the first look saw for the role that
        # reads it at this stage. [] for every other stage and role; the head is never shrunk, and every part is capped.
        if stage == "S4" and role == "qa-case-critic":
            head += case_critic_roster_lines(task_root, pipeline)
        head += first_look_lines(task_root, stage, role)
    # X9 (F-6 a): the project's last retro looked here. In the head (never shrunk by the ceiling); no other role or stage changes.
    if stage == "S9" and role == "qa-retro-analyst":
        head += prior_retro_lines(task_root, project)
    # TQ1-11: every stage of the three roles (S3 strategist, S5 automator, critic). NOT in `head`: it is the first thing the
    # ceiling cuts (render's `approach` level), before the map, the digests or any of the person's words (AR-24).
    approach = approach_forms(role, project, task_root)
    head += [line for line in [test_timeout_line(project, role)] if line] if stage in ("S5", "S7") else []

    digest_lines, digest_full = digests(pipeline, controller, stage, dispatch_id)

    # 2. the files
    cases = case_paths(task_root, scope) if stage in ("S4", "S5", "S6", "S7") and scope else []
    rows = []
    for rel in cases:
        try:
            rows += [r for r in PLAN_ROW_RE.findall((task_root / rel).read_text(encoding="utf-8", errors="replace"))
                     if r not in rows]
        except OSError:
            pass
    fit_lines, fit_side = fit_target_lines(task, task_root, stage, role, dispatch, rows, dispatch_id)     # TQ1-21: the tests the plan builds on, as paths
    head += fit_lines
    if fit_side:
        side_files[f"{dispatch_id}-targets.md"] = fit_side
    own_file = own_findings(task_root, controller, dict(dispatch, id=dispatch_id)) if stage == "S5" and role == "qa-automator" else ""
    own_advice = advice_of(task_root, controller, dict(dispatch, id=dispatch_id)) if stage == "S5" and role == "qa-code-critic" else ""
    names = [n for name in _input_names(stage_def, role, s5_kind, own_file, own_advice)
             for n in (notes_names(task_root) if name == NOTES_GLOB else [name])]
    if first_look:
        names = ["work/requirements-register.md"]       # the runner WRITES the first look: S3's other inputs are the strategist's, not its
    if stage == "S5" and role == "qa-code-critic":
        # t-1937 TR3-5: findings go one file per critic dispatch; the path is GIVEN (FR-15), the role never builds or searches it.
        # A file line (not a head line): the head is never shrunk and the critic's brief sits at the ceiling; the form skeleton carries it too.
        import findings_path
        names.append(findings_path.per_dispatch(dispatch_id))
    names += [n for n in stage_critic_names(stage_def, role, task_root) if n not in names]      # X2-1: the stage critic's own files
    names += [n for n in tried_reader_names(stage_def, role, task_root) if n not in names]      # t-1884 M-2: the forms the retro reads
    # The seven header lines of a charter role go right after the title, so the note of a brief over the 30 KB limit (render)
    # stays first after it and `Scope:` follows them. Invariant: placed AFTER the filters of `names` (only now are they final),
    # and the head is never cut below them; a role whose file is not a charter gets [] and an unchanged brief.
    sd_head = sd_head_lines(task_root, stage, role, dispatch_id, names, stage_def, plan_road=s5_kind == "plan", first_look=first_look)
    head[2:2] = sd_head
    walking = False       # t-1957 N3: a manual dispatch with a walk session gets the thin walk brief
    if role == "qa-runner" and _record_kind(dispatch) == "manual" and not first_look:
        walk_rec = walk_record(task_root, dispatch_id)
        walking = bool(walk_rec)
        # after `sd_head_lines` (head[2:2] above): the charter header lines stay; the first lane alone gets the cells (exploration_lines
        # is empty once any case folder holds a tried.md), so they are neither dropped nor repeated in later lanes
        head += walk_brief_lines(task_root, task, dispatch_id, walk_rec) if walking else [fallback_grammar_line()]
        head += exploration_lines(task_root, task, dispatch_id, briefs_dir, write and output is None)   # t-1765 X3: the first manual window explores; the head is never shrunk
    shell = role_has_bash(role)   # the one reader of the question: host_adapter.role_has_bash, which the guard also asks
    files = file_lines(names, task_root, project, shell)
    # PC2-6 B6: the category of a line that is NOT an ordinary named input, set where the line is built (never read back from its
    # text); the last resort pops by it. The RENDERED order of `files` is unchanged: only the pop priority uses the tags.
    kind_of = {}
    if stage == "S5" and role == "qa-automator" and not own_file:
        # the glob that stood here named every window's findings; with no critic of this window yet the role is told so, not left to hunt
        none_yet = "- critic findings: none yet - no critic has reviewed this dispatch's window, so there is no findings file to read"
        files.append(none_yet)
        kind_of[none_yet] = "none_yet"
    if "work/ticket-snapshot.json" in names:
        # Right under the snapshot's own line, where the scout reads it first, and the last to be trimmed.
        # The person's exclusions, then what the story's text points at and nobody read (t-267): both are "not read".
        masks = snapshot_mask_lines(task_root) + reference_gap_lines(task_root) + reads_skipped_lines(task_root)
        spot = next((i for i, line in enumerate(files) if "work/ticket-snapshot.json" in line), None)
        if masks and spot is not None:
            files[spot + 1:spot + 1] = masks
        # After the masks (which stay directly under the snapshot): the view the role reads, and the raw
        # it may grep.
        view = ticket_view_lines(task_root, project)
        if view and spot is not None:
            files[spot + 1 + len(masks):spot + 1 + len(masks)] = view
    if rows:
        only = f" - only the rows {', '.join(rows[:8])}: `Grep -n` the id, then Read the range"
        files = [line.split(" - slice it:")[0] + only if "test-plan.md" in line and "slice it" in line else line
                 for line in files]
    for rel in cases[:8]:
        files.append(f"- qa-factory/artifacts/{task}/{rel} ({_size(task_root / rel)})")
        kind_of[files[-1]] = "case"
    if len(cases) > 8:
        files.append(f"- ... and {len(cases) - 8} more case files of the scope, same folder")
        kind_of[files[-1]] = "case"
    tests = scope_tests(task_root, scope) if role in ("qa-code-critic", "qa-runner", "qa-failure-analyst") else []
    for rel in tests[:6]:
        files.append(f"- {rel} ({_size(project / rel)}) - the test file of the window")
        kind_of[files[-1]] = "test"
    source = source_material(task, task_root, role)
    kind_of.update({line: "source" for line in source})
    files += source
    if s5_kind == "window" and role == "qa-automator" and piece is not None:
        code_text, _left = window_code_file(project, plan_doc, piece["tests"], dispatch_id, task_root)
        side_files[f"{dispatch_id}-code.md"] = code_text
        plan_files = plan_files + [f"- {_rel(task, f'work/briefs/{dispatch_id}-code.md')}"
                                   f"{'' if write and output is None else ' (not written in this run)'} - the code you will touch: the "
                                   "tests you extend, the fixtures, a neighbouring test per file, the fields of a manifest row"]
    if s5_kind in ("plan", "window") and _resumed(dispatch, stage, role, s5_state):
        side_files[f"{dispatch_id}-delta.md"] = delta_lines(task_root, task, dispatch_id, dispatch, s5_state, role, scope, piece, brief_rel)
    files = plan_files + files          # first: the trimming below takes from the end
    files = list(dict.fromkeys(files))

    # 3. the card
    if shell:
        card = [f"Every command is `python \"{SCRIPTS}/<script>\"`, run from the project root; `<task root>` = "
                f"qa-factory/artifacts/{task}. `--help` of a script is allowed and answers what this card does not; "
                f"the plugin's scripts are not read."]
        lines = TOOLING.get(role, [])
    else:
        # TP2-2406 S4-6/S4-7: the card above is python commands; a role without Bash gets who runs them.
        card = [NO_SHELL_HEAD]
        lines = TOOLING_NO_SHELL.get(role, [])
    if shell and s5_kind == "plan":
        lines = list(lines) + TOOLING_PLAN.get(role, [])
    if shell and _record_kind(dispatch) == "manual" and not first_look:
        lines = list(lines) + TOOLING_MANUAL.get(role, [])
        if TOOLING_MANUAL_APP.get(role) and _has_device_stand(hooklib.load_config() or {}):
            doc = (HERE.parent / "references" / "manual-evidence-app.md").as_posix()
            lines += [line.replace("<APP_DOC>", doc) for line in TOOLING_MANUAL_APP[role]]
    card += ["- " + line.replace("<T>", task).replace("<ID>", dispatch_id) for line in lines]
    card += judge_lines(role, shell, dispatch_id)
    if walking:     # t-1957 N3: only the walk commands - no manifest line, no env_probe, no finalize_task (code does those)
        card = command_card_lines(task, dispatch_id, WALK_COMMANDS, ". `--help` of a script is allowed.")
    if first_look:      # t-2277 FL-3: the commands are in the head (`first_look_runner_lines`), with the walk and the stand they are about
        card = ["The commands of this dispatch are the lines under `Every command is` in the head above; `--help` of a script is allowed."]
    # The first look hands in ONE record, `first_look.py put` - its handoff is not a run report (FR-10, AR-10): its own ahead card and path.
    ahead = FIRST_LOOK_AHEAD if first_look else ahead_card(role)
    digest_form = digest_template_lines(role, stage, dispatch_id, dispatch, FIRST_LOOK_FILE if first_look else "")

    # 4. the person's words
    shown, minimal, full = decisions(pipeline, stage, role, task, project, task_root)

    # 5. the map
    repo = repo_map_for(task, task_root, project, scope, write and output is None) if stage in ("S5", "S6") and not walking else None

    # 5a. HF5-5: the stand of a MANUAL runner block, between the files and the card. Built here, rendered in `render` itself and
    # never in `files`/`card`: the trimming below takes files (and, first, the map and the words) - an address or an account name
    # is not lost to make room for a file. An automated block has no section: its brief is as it was.
    stand = []
    if _record_kind(dispatch) == "manual" and not walking and not first_look:       # the app card holds the stand of a walk
        stand = manual_stand_lines(task_root, project, hooklib.load_config() or {},
                                   [str(c) for c in dispatch.get("manual_case_ids") or scope],
                                   str(pipeline.get("environment") or ""), repo)

    p1_areas = s4_p1_area_lines(task_root, stage, role)     # OH3-34: the S4 designer's and case critic's `## P1 areas` section

    # S1 (RN1-5, t-1685 N1-1) searches the application and test repositories by its own procedure; every other stage keeps main's string
    rule = (("Read what is named above with `offset`/`limit`; the application and test repositories are yours to search, "
             "as your procedure says; never the plugin - the card above is what it would tell you")
            if stage == "S1" else
            ("Do not search: read what is named above with `offset`/`limit`; search the repository only when the "
             "map is empty, and never the plugin - the card above is what it would tell you"))
    rule += ", and `--help` is the door." if shell else "."
    if walking:
        rule = WALK_RULE + "."
        files, trimmed_files = [], []

    trimmed_files = []      # the lines the last resort took off `files`, in their original order (N4: they go to <ID>-files.md)
    map_body = repo["markdown"].splitlines()[2:] if repo and not repo.get("error") else []

    def render(inline_map: int, dec_level: int, inline_digests: bool, side: dict, ap_level: int = 2, note: str = "",
               over_line: str = "") -> tuple:
        """-> (text, omitted). RC1-14 N4, the order is the priority: the head, the person's words (never cut), `Not in the brief`,
        then what gives first-to-last from the bottom up (the map is the first under the knife); the digest template is the LAST
        section and outside the budget (F-4). `omitted` is one line per thing the ceiling took out (E16): no silent trim.
        `over_line` (PC2-6) is the one line that says the brief stays over its budget: the FIRST line of `Not in the brief`, which
        it opens when nothing else did; it is not in `omitted`, and the caller never measures a text that carries it as a budget."""
        omitted = []
        if repo and inline_map == 0 and map_body:
            omitted.append(f"- the repository map head - read {repo['path']}")
        if ap_level < 2 and approach[2] and approach[2] != [APPROACH_NOTHING] and approach[ap_level] != approach[2]:
            omitted.append("- the project approach in full - read qa-factory/config.json (`test_data`) and qa-factory/strategy/")
        if not inline_digests and digest_full:
            omitted.append(f"- the digests of earlier roles - read {side['digests']}")
        if full and dec_level < 2:
            omitted.append(f"- every decision in full - read {side['decisions']}")
        if trimmed_files:
            omitted.append(f"- {len(trimmed_files)} input file(s) - read qa-factory/artifacts/{task}/work/briefs/{dispatch_id}-files.md")
        parts = list(head[:2]) + ([note, ""] if note else []) + list(head[2:])
        parts += ["", "## The person's words that concern you", ""]
        if not full:
            parts.append("- none recorded: no warning, no gate decision and no waiver touches this stage")
        elif dec_level == 2:
            parts += [line.replace("<decisions>", side["decisions"]) for line in shown]
        elif dec_level == 1:
            parts += minimal       # PC2-6 O-c: the pointer to the side file is `Not in the brief`'s line, once
        else:       # only the probe of `over_ceiling` asks for it: no brief is built at this level (N4, F-3)
            parts.append(f"- {len(full)} recorded decision(s): {side['decisions']}")
        if omitted or over_line:
            parts += ["", "## Not in the brief", ""] + ([over_line] if over_line else []) + omitted
        if approach[ap_level]:
            parts += [""] + approach[ap_level]
        parts += ["", "## What earlier roles produced", ""]
        if inline_digests or not digest_full:
            parts += digest_lines or ["- nothing yet: this is the first stage with a role"]
        else:
            parts.append("- in the side file, see Not in the brief")
        if not walking:
            parts += ["", "## Read these files", ""] + (files or ["- the stage declares no input file"])
        if stand:
            parts += ["", f"## {STAND_HEAD}", ""] + stand
        if p1_areas:
            parts += ["", "## P1 areas", ""] + p1_areas
        parts += ["", "## Commands", ""] + card
        if ahead:
            parts += ["", "## The rules code will apply to your handoff", "", ahead]
        if repo:
            parts += ["", "## Repository map of the window", ""]
            if repo.get("error"):
                parts.append(f"- the map could not be built ({repo['error']}); search is allowed for this window")
            else:
                parts.append(f"- full map: {repo['path']}" + ("" if repo["written"] else " (not written in this run)"))
                if repo["doc"].get("empty"):
                    parts.append("- the map is EMPTY: searching the repository is the right move for this window")
                if inline_map:
                    body = repo["markdown"].splitlines()
                    parts += body[2:2 + inline_map]
        parts += ["", "## Rule", "", rule]
        # F-4 (D5-C, t-1755 B2): the digest template is the LAST section and outside the budget (`form_cost`), so it can never evict
        # the person's words; with no template (E17, R5) the last line points at the digest shape every role's rules carry.
        parts += digest_form if digest_form else ["", NO_FORM_LINE]
        return "\n".join(parts + [""]), omitted

    side = {"digests": f"qa-factory/artifacts/{task}/work/briefs/{dispatch_id}-digests.md",
            "decisions": f"qa-factory/artifacts/{task}/work/briefs/{dispatch_id}-decisions.md"}
    sides_needed = {}
    # From the fullest brief down: the map's head goes first, then the digests move to
    # their side file, then the person's words shrink to the gate and the warnings, then
    # they move too. The card and the file list are the last to give.
    # TQ1-11: the project-approach block goes BEFORE all of that (full -> one line -> a pointer line); the person's words and the
    # gate A line are the last to give (AR-24).
    # The pointer line itself costs bytes, so it is the last of the block to go - and it goes (level -1) before any of the words
    # or the gate A line is shortened.
    attempts = [(MAP_INLINE_LINES, 2, True, 2), (MAP_INLINE_LINES, 2, True, 1), (MAP_INLINE_LINES, 2, True, 0), (0, 2, True, 0),
                (0, 2, True, -1), (0, 2, False, -1), (0, 1, False, -1)]      # N4: level 0 (words as a pointer only) is gone (F-3)
    # N4: the budget does NOT count the digest template (F-4): it is a door like the card and goes last, whatever the ceiling.
    form_cost = measured_bytes("\n".join(digest_form)) + (1 if digest_form else 0)

    # t-1765 X1 fix-3/4: the SD head is form too, up to its own HARD cap SD_HEAD_MAX_BYTES; what it weighs beyond the cap counts
    # against the body (never outside the budget) and is reported in `over_ceiling`. 0 for a non-charter role.
    sd_cost = min(head_bytes(sd_head), SD_HEAD_MAX_BYTES)

    def budget_of(body: str) -> int:
        return measured_bytes(body) - form_cost - sd_cost       # path-independent (AR-4): the one measure for the number and the trim

    text, omitted, chosen = "", [], attempts[-1]
    truncated = any("<decisions>" in line for line in shown)
    before = None       # the render of the attempt before this one (PC2-6 O-d)
    for chosen in attempts:
        inline_map, dec_level, inline_dig, ap_level = chosen
        text, omitted = render(inline_map, dec_level, inline_dig, side, ap_level)
        if dec_level == 1 and before is not None and budget_of(text) >= budget_of(before[0]):
            # PC2-6 O-d (AR-24): the words rung is taken only when it makes the brief strictly smaller; a rung that costs the
            # person's words and saves nothing is not taken, and the last resort below pops files from the form that is kept.
            text, omitted, chosen = before
            inline_map, dec_level, inline_dig, ap_level = chosen
        sides_needed = {"decisions": bool(full) and (dec_level < 2 or truncated),
                        "digests": not inline_dig and bool(digest_full)}
        if budget_of(text) <= BRIEF_MAX_BYTES:
            break
        before = (text, omitted, chosen)
    if budget_of(text) > BRIEF_MAX_BYTES:
        # the last resort: the card is the one thing that cannot go, the file list is trimmed from its end - and a DOOR never
        # goes (SC1-10). A door is a line of a `project:`/`plugin:` name in ROLE_FILES: a document the role is no longer
        # injected, or a template it must read; trimmed away, the role would not know it exists (FR-2). The doors are
        # computed from the same `file_lines` that produced `files`, so each door line matches its entry byte for byte.
        # Only doors left -> the loop ends and the brief goes out over the ceiling: a long brief is a cost, a lost door a defect.
        # `## The stand` (HF5-5) is a door of the same kind and is never in `files`: it is rendered, not trimmed (test_brief_pack_manual K3).
        # The person's words are NOT a door to trim: they stay at their kept level (1, or 2 when level 1 is not strictly smaller) and the brief goes over (F-3, AR-24).
        doors = set(file_lines([n for n in ROLE_FILES.get(role, []) if n.startswith(("project:", "plugin:"))],
                               task_root, project, shell))
        # t-1776: the S5 plan-slice lines (`plan_files`: the plan and its window slices) are doors too: the slice is what the automator acts on, so they are never trimmed.
        # CI fix G4b (FR-2): the plan critic's review form line and its rubric pointer (`... read its section «On the plan»`) are doors as well: the form
        # is where the critic writes, and the pointer is the ONLY place that names the section, so a role without them would not know they exist.
        doors |= {line for line in plan_files if "s5-plan.json" in line or "-plan-w" in line
                  or " - your review form" in line or "«On the plan»" in line}
        # t-1765 CI fix C: the automation manifest's line carries its door (`manifest_view.py`, never a whole read), so it is a door
        # too: the optional tail (the other input files) goes first, this line stays whatever the head weighs (FR-2).
        doors |= {line for line in files if "work/automation-manifest.json" in line}
        # PC2-6 O-d: `chosen` is the words form the ladder KEPT (level 1, or level 2 when level 1 was not strictly smaller).
        # PC2-6 B6: the POP PRIORITY (first to last): the "critic findings: none yet" line, the source material, the other named
        # inputs (their masks with them), the case files ("... and N more" first, then the last case first), the window's test file
        # (CI fix G8: the file the critic reads and probes goes last and still yields when nothing else is left). The RENDERED
        # order of `files` never changes, so a brief that pops nothing is byte-identical and `trimmed_files` keeps that order.
        priority = ("none_yet", "source", "named", "case", "test")
        rendered_order = list(files)
        while budget_of(text) > BRIEF_MAX_BYTES:
            last = next((i for kind in priority for i in range(len(files) - 1, -1, -1)
                         if files[i] not in doors and kind_of.get(files[i], "named") == kind), None)
            if last is None:
                break
            files.pop(last)
            trimmed_files = [line for line in rendered_order if line not in files]
            text, omitted = render(*chosen[:3], side, chosen[3])
    over_ceiling = []
    over_line = ""
    budget_bytes = budget_of(text)      # PC2-6 B1: measured on the render WITHOUT the over line, which is outside the budget
    if budget_bytes > BRIEF_MAX_BYTES:
        # Which part kept the brief over: the words (at their shortest kept form) and/or the doors and the card.
        probe = budget_of(render(chosen[0], 0, chosen[2], side, chosen[3])[0])
        if full and chosen[1] >= 1 and budget_bytes > probe:
            over_ceiling.append("words at level 1")
        if probe > BRIEF_MAX_BYTES or not over_ceiling:
            over_ceiling.append("doors only")
        # PC2-6 (AR-22, FR-4): the brief stays over after every cut and SAYS so, first line of `Not in the brief`. No size of the
        # brief in it (no fixed point); a run that writes no side file says so, as the code-file line does.
        over_line = (f"- the brief stays over its {BRIEF_MAX_BYTES} B budget after every cut ({', '.join(over_ceiling)}): "
                     "what it names is here whole or one named file away"
                     + ("" if write and output is None else " (side files not written in this run)"))
        text, omitted = render(*chosen[:3], side, chosen[3], over_line=over_line)
    if head_bytes(sd_head) > SD_HEAD_MAX_BYTES:
        over_ceiling.append("sd head")      # fix-4: the head is over its hard cap even after every cut (its overflow is in the budget)
    if len(text.encode("utf-8")) > SLICE_BYTES:
        # E15b: over the guard's whole-read limit (SLICE_BYTES) the role is told, first, to read the brief by range. The line carries
        # its own size, so the size is iterated to a fixed point (a few rounds: the digits of the number are the only moving part).
        size = len(text.encode("utf-8"))
        for _ in range(4):
            note = (f"This brief is {size} B, over the 30 KB whole-read limit: read it by range (offset/limit), "
                    "the person's words first")
            text, omitted = render(*chosen[:3], side, chosen[3], note, over_line)
            if len(text.encode("utf-8")) == size:
                break
            size = len(text.encode("utf-8"))
        over_ceiling.append("over SLICE_BYTES")
    if trimmed_files:
        side_files[f"{dispatch_id}-files.md"] = "# Input files not in the brief - " + dispatch_id + "\n\n" + "\n".join(trimmed_files) + "\n"

    written = []
    if write:
        target = output or (briefs_dir / f"{dispatch_id}.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written.append(str(target))
        if output is None:
            if sides_needed.get("decisions"):
                p = briefs_dir / f"{dispatch_id}-decisions.md"
                p.write_text("# The person's words - " + dispatch_id + "\n\n" + "\n".join(full) + "\n", encoding="utf-8")
                written.append(str(p))
            if sides_needed.get("digests"):
                p = briefs_dir / f"{dispatch_id}-digests.md"
                p.write_text("# Digests - " + dispatch_id + "\n\n" + "\n".join(digest_full) + "\n", encoding="utf-8")
                written.append(str(p))
            for name, body in side_files.items():       # the plan's slices, the window's plan slice and code, a resumed role's delta
                p = briefs_dir / name
                p.write_text(body, encoding="utf-8")
                written.append(str(p))
    return {"task": task, "stage": stage, "role": role, "dispatch": dispatch_id, "scope": scope,
            "path": brief_rel if output is None else str(output), "bytes": len(text.encode("utf-8")),
            "budget_bytes": budget_bytes, "omitted": omitted, "over_ceiling": over_ceiling,
            "files": files, "sides": sides_needed, "written": written,
            "repo_map": (repo or {}).get("path"), "markdown": text}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--task", required=True)
    ap.add_argument("--stage", required=True)
    ap.add_argument("--role", required=True)
    ap.add_argument("--dispatch", required=True, help="the dispatch id story_step registered")
    ap.add_argument("--json", action="store_true", help="print the brief and its facts as JSON")
    ap.add_argument("--output", help="write the brief here instead of work/briefs/<ID>.md (side files are not written)")
    ap.add_argument("--dry-run", action="store_true", help="build, write nothing")
    ns = ap.parse_args()
    hooklib.require_project("brief_pack")
    try:
        result = build(ns.task, ns.stage, ns.role, ns.dispatch, write=not ns.dry_run,
                       output=Path(ns.output) if ns.output else None)
    except hooklib.StoryRootError as exc:       # a story that is not there: the call's fault, one line, nothing written
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 2
    if ns.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0
    sides = [k for k, v in result["sides"].items() if v]
    over = [r for r in result["over_ceiling"] if r in ("words at level 1", "doors only")]      # the budget reasons, not sd head / SLICE
    print(f"brief: {result['path']} ({result['bytes']:,} B"
          + (f", {result['budget_bytes']:,} budget B against the ceiling" if result["budget_bytes"] != result["bytes"] else "")
          + (f", over the {BRIEF_MAX_BYTES} budget B ceiling after every cut: {', '.join(over)}" if over else "")      # PC2-6: the conductor's note
          + (f", side files: {', '.join(sides)}" if sides else "")
          + (", not written" if ns.dry_run else "") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
