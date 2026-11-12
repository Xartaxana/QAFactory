"""refusal_registry.py — A24: every refusal on the dispatch path, and how a person's word
passes it.

"A check stops a SILENT pass, never an informed one" has been this factory's rule since
0.7.4, and it was carried by memory: whoever added a refusal was expected to remember to give
it a way through. On TP1-15045 that memory failed in the one place it mattered most.
`stage_guard.rule_order` and `rule_gate_a` never read `pipeline.json.stage_overrides[]`, so
when the person answered "Go on", `waiver.py` recorded their words, printed OK, and the very
next dispatch was refused anyway — after which the factory offered the person a line to edit
inside the plugin. Nothing was red, because there was no check that a refusal HAS an override.

So the rule lives here instead of in prose. Each entry names one refusal, what it refuses, the
way a person's recorded word passes it, and the test that proves it. `--check` re-scans the
sources: a refusal in a scanned file with no entry fails the audit, so does an entry pointing
at a refusal that is gone, and so does an entry with no test.

  refusal_registry.py            # the registry as a table
  refusal_registry.py --check    # audit A24 (exit 1 on a finding)
  refusal_registry.py --sites    # what the scanner sees — start here for a new entry
  refusal_registry.py --json     # machine form of either

`override: ""` is not an omission. It is the honest record of a refusal a person's word
cannot pass, with the reason in `unpassable_because`, and `--check` prints those separately
so they stay decided rather than forgotten. A registry where every row carries the same
sentence would prove nothing.

A FAIL-CLOSED refusal is the one shape that needs more than that. It blocks because a check
did not RUN, so a word passing it would open the very hole it exists for — and that means a
defect inside the guard freezes the story where the person's word cannot reach it either.
Those entries carry `fail_closed: True`, `escalates_after: <n>` and `escalation`, and
`--check` fails an entry that has neither a pass nor an escalation.

SCOPE, and its limits. Scanned refusal by refusal: the three hook scripts that can end a
dispatch before the role does any work (`stage_guard.py`, `inject_context.py`,
`guard_pre_tool.py`). A refusal there is `deny(...)`, `block(...)`, or a raised
`StateConflict`/`ValueError` that reaches the CLI. `controller.py` and `stage_done.py` are
registered as `operation` entries instead of line by line: the controller's validator raises
in 160+ places across every operation, and a census of those is not a registry anyone would
read. For those, `--check` verifies that the symbol carrying a person's word through the
operation still exists. Two limits worth knowing: a refusal added under a message that
already has an entry is not caught (the key is the call, not the line), and a refusal that is
a bare `print(..., file=sys.stderr)` plus a non-zero return is invisible to the scanner —
that shape is why `stage_done.py` is an operation entry.
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hooklib import PLUGIN_ROOT  # noqa: E402

SCANNED = ("stage_guard.py", "inject_context.py", "guard_pre_tool.py")
REFUSAL_CALLS = ("deny", "block")
REFUSAL_RAISES = ("StateConflict", "ValueError")
KEY_CHARS = 90
QUOTE_HEAD_RE = re.compile(r"^[a-zA-Z]{0,2}(\"\"\"|'''|\"|')")

import person_words  # noqa: E402

WAIVER = ("`waiver.py --task <T> --stage <S> --block \"<part of the line>\" "
          "--words-file <file>` " + person_words.WHOLE_PART)

# `call` is the SOURCE TEXT of what the refusal is raised with, as `--sites` prints it, and
# an entry matches by prefix — long enough to be unambiguous, short enough to survive a
# reworded message tail.
REGISTRY: list[dict] = [
    # --- stage_guard.py — the dispatch rules themselves ----------------------------------
    {"id": "SG-resume-none", "file": "stage_guard.py", "function": "check_resume",
     "call": "{ticket}: resuming a dispatch is blocked",
     "refuses": "SendMessage while this story records no resumable agent_id — on a stage in "
               "pipeline.json or on a dispatch record in state/controller.json; when agents ARE "
               "recorded but every one belongs to a superseded or released dispatch, the refusal "
               "says how many agents and why none is resumable, not that none is recorded (CX1-9, M-2); "
               "a Codex receipt that names the recipient but is refused is a separate clause "
               "('a receipt names <target>, but dispatch <id> ...'), never counted as a recorded agent; "
               "a send_input with interrupt is judged by the same rule (CX1-9 fix round, t-1080); "
               "an agent whose work is all accepted on a stage that resumes its role (rework_mode: resume) "
               "is closed work, counted among the retired with the fact 'dispatch <id> is accepted; closed "
               "work goes back through the controller', and the door is the controller's, not a bind: "
               "`story_step.py finish --needs-author` while the S5 code critic runs, else `controller.py "
               "--operation rework` (HF8-15 (2))",
     "override": "",
     "unpassable_because": "there is no agent to resume and no word invents one. The message "
     "names both ways through: record the id the host's task notification returned (`agent_id` "
     "on the dispatch request, or `story_step.py bind ... --agent-id`), or take the retry packet "
     "`controller.py --operation recover` prints and dispatch it with Agent, where the stage "
     "rules apply. Until 0.7.19 nothing but `stage_done --agent-id` ever wrote an id and "
     "nobody called it, so this met every resume of a stopped role (TP2-2553). When every "
     "name the refusal carries is a retired agent, a vetoed receipt or one another story's receipt holds, the bind is not offered "
     "(it would re-invite what the filter retired): the new dispatch is the whole answer (DC1-16).",
     "test": "scripts/tests/test_stage_guard.py (stage_guard.py --selftest, rule 6)"},
    {"id": "SG-resume-unknown", "file": "stage_guard.py", "function": "check_resume",
     "call": "{ticket}: resuming '{names",
     "refuses": "SendMessage naming an agent id this story never ran (neither pipeline.json "
               "nor the controller's dispatch records know it), under any recipient alias "
               "(to, recipient, agent_id, host id/target): when several are named, every one "
               "must be recorded and the unrecorded ones are named in the refusal; an agent a "
               "superseded or released dispatch carried is not recorded for this purpose, and a "
               "Codex name that ANY receipt of another story, or of a retired dispatch, also "
               "answers to is not vouched for - the refusal prints the fact "
               "'(<target>: dispatch <id> is superseded|released_by_person)' (CX1-9, F-7); the tail names "
               "the door when a live dispatch of this story can take the id: `story_step.py bind` for a "
               "running dispatch or an unaccepted returned one, `story_step.py resume --agent-id` for a "
               "stopped one on a story the controller reads as open, and the new dispatch in Agent otherwise (DC1-16); "
               "a CLOSED author (all its records accepted, one on a stage with rework_mode: resume, no rework of its "
               "role waiting for a binding; HF8-15 (2)) is not recorded for this purpose and its tail names the "
               "controller's door instead: `story_step.py finish --needs-author` while the S5 code critic runs, "
               "else `controller.py --operation rework`, then its card goes to this agent",
     "override": "",
     "unpassable_because": "the id is recorded for no dispatch of this story, so passing the check "
     "would only move the failure into the host. The message names the door when a live dispatch can "
     "take the id (story_step.py bind, resume for a stopped one); otherwise a new dispatch is the answer. "
     "A retired agent or another story's name is never offered the bind.",
     "test": "scripts/tests/test_stage_guard.py (part_resume_no_recipient: unknown recipient "
     "under each alias, and beside a recorded one); scripts/tests/test_resume_story_isolation.py "
     "(a superseded or released agent, an ambiguous bare name, one receipt of two vetoing)"},
    {"id": "SG-resume-stopped", "file": "stage_guard.py", "function": "check_resume",
     "call": "stopped_text",
     "refuses": "SendMessage to an agent of this story whose only open dispatch is stopped (blocked/paused), while `resume` would open "
               "(SC2-17): the refusal names `story_step.py resume --task T --dispatch-id D` (with --agent-id when the record holds "
               "no agent); it is given only when the controller's own resume check passes for that request",
     "override": "",
     "unpassable_because": "one command opens it and is named in the text; a person's word has nothing to pass: a message after "
     "the resume carries that word",
     "test": "scripts/tests/test_resume_stopped.py"},
    {"id": "SG-resume-ambiguous", "file": "stage_guard.py", "function": "_unidentified_resume",
     "call": "resume story identity is missing or ambiguous",
     "refuses": "a Codex SendMessage that names a recipient but resolves to no story while the project "
               "has stories (FB-16, TP2-2406; the Claude host keeps ALLOW, its identity is as "
               "on main): the recipient's receipts (resolve_ticket step 1b; the agent path or its bare "
               "name), the dispatch text and the task_name slug named none - the single-running-story "
               "guess is withheld from a Codex resume - or the receipts of one recipient, or of two "
               "recipients, named two stories; the refusal names the recipient(s) and the door a "
               "Desktop followup_task (no task_id) can use: `story_step.py bind --task T "
               "--dispatch-id ID --agent-id <recipient>`, or an explicit task_id where the host "
               "carries one",
     "override": "",
     "unpassable_because": "a resume of an unidentified dispatch has no story to check it against; "
     "passing it would resume whichever story the host picked. The way through is a recorded "
     "binding for the recipient (the host writes it at spawn; `story_step.py bind --agent-id` "
     "records it for a driver run), the person's QA_FACTORY_TASK or an explicit task_id on the "
     "event; a project with no story at all is not refused.",
     "test": "scripts/tests/test_resume_story_isolation.py (a recipient bound to the pending "
     "story resolves it; an unbound recipient with stories on disk is refused and told "
     "`story_step.py bind`; no stories pass)"},
    {"id": "SG-probe-role", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "context diagnostic requires qa-scout without a task_id",
     "refuses": "a context-probe dispatch that is not the bounded qa-scout probe",
     "override": "",
     "unpassable_because": "qa-doctor's own probe, with no person waiting on it. A wider "
     "bypass of story ordering is precisely what the narrow probe exists to avoid.",
     "test": "scripts/tests/test_doctor_context.py"},
    {"id": "SG-probe-evidence", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "context diagnostic requires current allow/deny evidence",
     "refuses": "the same probe without fresh allow/deny evidence in this host session",
     "override": "",
     "unpassable_because": "the evidence IS the probe's result; accepting it without would "
     "make qa-doctor report a capability nobody observed.",
     "test": "scripts/tests/test_doctor_context.py"},
    {"id": "SG-ambiguous-task", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "task identity is missing or ambiguous",
     "refuses": "a dispatch in a project that runs stories, with nothing naming which one",
     "override": "`QA_FACTORY_TASK=<TICKET>` in the environment of the host — the person "
     "naming the story for a dispatch whose arguments cannot carry an id. The guard reads it "
     "as the last resort before this refusal, and only for a story that exists on disk. On "
     "Codex desktop the spawn `message` is an opaque encrypted string and the only readable "
     "carrier is `task_name`; when even its slug names no story, this variable is the word.",
     "unpassable_because": "",
     "test": "scripts/tests/test_stage_guard.py (stage_guard.py --selftest, fail-open cases), "
     "scripts/tests/test_codex_host.py"},
    {"id": "SG-explicit-no-story", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "the explicit task id names no story",
     "refuses": "a dispatch that DOES name its story, with no pipeline.json for that id under "
     "the artifact root the hook resolved",
     "override": "",
     "unpassable_because": "no word creates a pipeline.json, and this is not the person's "
     "defect to repair: the refusal prints the root it looked under and every story it did "
     "find, because the usual cause is the hook and the orchestrator resolving different "
     "project roots. Until 0.7.12 this answered `pass the explicit task_id` to a person who "
     "had just passed it (TP2-2556, two reinstalls).",
     "test": "scripts/tests/test_stage_guard.py, scripts/tests/test_codex_host.py"},
    {"id": "SG-explore-two", "file": "stage_guard.py", "function": "_check_exploration",
     "call": "exploration identity: two explorations named",
     "refuses": "a dispatch that carries two different exploration names (two label lines, or a label and an `explore:` id)",
     "override": "",
     "unpassable_because": "the call is malformed, the call's fault and not the story's (FR-46): no word picks one of two names. The "
     "door is in the text: dispatch again with the brief `explore_step.py brief` prints, which names exactly one exploration.",
     "test": "scripts/tests/test_exploration_identity.py (two_labels_refused)"},
    {"id": "SG-explore-name", "file": "stage_guard.py", "function": "_check_exploration",
     "call": "exploration identity: not an exploration name",
     "refuses": "a dispatch whose exploration label or `explore:` id is not a slug (a name is lowercase letters and digits joined by hyphens)",
     "override": "",
     "unpassable_because": "the call is malformed (FR-46): the name is the one `explore_step.py frame` printed as `slug:`; the door "
     "is the brief `explore_step.py brief` prints, whose first line carries it.",
     "test": "scripts/tests/test_exploration_identity.py (label_not_slug_refused)"},
    {"id": "SG-explore-missing", "file": "stage_guard.py", "function": "_check_exploration",
     "call": "exploration identity: no exploration `",
     "refuses": "a dispatch that names an exploration with no exploration state under qa-factory/explorations/<slug>/",
     "override": "the person's phrase: `explore_step.py frame \"<words>\"` creates the exploration, then the dispatch goes through "
     "(or the person's word names a different, existing one)",
     "unpassable_because": "",
     "test": "scripts/tests/test_exploration_identity.py (label_without_explore_json_refused)"},
    {"id": "SG-explore-both", "file": "stage_guard.py", "function": "_check_exploration",
     "call": "exploration identity: the dispatch names both a story and an exploration",
     "refuses": "a dispatch with an exploration label (or `explore:` id) AND a story task_id or a `Ticket:` line of a story that exists",
     "override": "",
     "unpassable_because": "the call is malformed (FR-46): a dispatch is a story's or an exploration's, never both, and no word merges "
     "them. The door is in the text: dispatch again, from `explore_step.py brief` for an exploration, from the story's own packet otherwise.",
     "test": "scripts/tests/test_exploration_identity.py (label_and_story_id_refused, label_and_ticket_line_refused)"},
    {"id": "SG-explore-role", "file": "stage_guard.py", "function": "_check_exploration",
     "call": "exploration identity: this role has no exploration step",
     "refuses": "an exploration dispatch to a factory role the exploration table does not name",
     "override": "",
     "unpassable_because": "the table names the roles with an exploration step (FR-39): no word gives another role one. The text lists "
     "them; dispatch one of them.",
     "test": "scripts/tests/test_exploration_identity.py (exploration_wrong_role_refused)"},
    {"id": "SG-unreadable-pipeline", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "{ticket}: unreadable pipeline",
     "refuses": "a dispatch whose pipeline.json cannot be parsed",
     "override": "",
     "unpassable_because": "the factory's own defect, not the person's: `controller.py "
     "--operation recover` repairs the state, and no answer makes an unreadable file readable.",
     "test": "scripts/tests/test_stage_guard.py (stage_guard.py --selftest)"},
    {"id": "SG-role-stage-unset", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "{role} is a role of {names} and no running dispatch",
     "refuses": "a dispatch to a role that stands on several stages when no running dispatch of that role in the story names "
     "which stage it works (a stage is never taken from the role's home stage by default: AR-28)",
     "override": "",
     "unpassable_because": "the stage is a fact the controller records, not a word: `story_step.py start --task <T> --stage <S> "
     "--role <role>` registers the dispatch, and the text prints that command (the call's fault, FR-46).",
     "test": "scripts/tests/test_stage_of_dispatch.py (the dispatch guard on a role of two stages)"},
    {"id": "SG-stage-rules", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "DV.compound(blocking, prefix=",
     "refuses": "rules 1 and 2 — a stage whose `requires` are not done, and a stage past gate "
               "A while gate A is not approved — EVERY such reason in one refusal, and (S6-S8) rule 3's "
               "open-manifest reason as a further item of the same refusal. One reason is the one sentence "
               "`{ticket}: <reason>`; several are `{ticket}:` and then the head `N problems - the request is "
               "refused whole, every one is listed:` with one numbered line each (`DV.compound`, the form "
               "the controller raises), so a router reads each reason as its own part",
     "override": WAIVER + " — `dispatch_errors()` filters every message through "
     "`waiver.split_overridden` and journals the pass as `gate_override`; the refusal itself "
     "ends with the ready command.",
     "test": "scripts/tests/test_gate_vocabulary.py, scripts/tests/test_stage_guard.py, "
     "scripts/tests/test_whole_list_sites.py"},
    {"id": "SG-tracker-route", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "{ticket}: {route}",
     "refuses": "an S1 qa-scout dispatch while readiness rates `ticket_adapter` anything but "
               "`ok` — a tracker reached only through the orchestrator's own MCP tool, agent "
               "or skill is not a route the scout has. On TP2-2553 that gap was rated "
               "`unknown`, S0's own fetch proved nothing about S1, and the first dispatch "
               "stalled: 2 h 54 min of hand-fetched tickets before planning began",
     "override": "`waiver.py --task <T> --stage S1 --block \"tracker route\" --words-file "
     "<file>` — the refusal carries that exact command, and the story then runs on "
     "whatever the configured route does reach. A project with no readiness.json is not "
     "refused at all, so nothing already in flight stops.",
     "unpassable_because": "",
     "test": "scripts/tests/test_stage_guard.py (stage_guard.py --selftest, tracker route)"},
    {"id": "SG-manifest-delivery", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "{ticket}: {message}",
     "refuses": "rules 3 and 4 — an S6/S7/S8 role while automation-manifest.json holds an "
               "unresolved case with no reason from the closed vocabulary, and (rule 4, commands only since t-1547) "
               "a delivery command while the delivery verdict is neither `yes` nor `after_checks`",
     "override": "rule 3: the person's word for a deferral is the gate waiver (`pipeline.json` `gate_waivers[]`, "
     "written by `waiver.py`, with their words) - the suffix of `deferred_by_decision:<gate>` is not, it names the gate "
     "that wrote the row. rule 4: the person says 'deliver with known gaps' at gate B (`approve` on the first line, then "
     "`deliver with known gaps: <reason>` on a line of its own, or the conductor's `--risks-file`) and `controller.py --operation "
     "gate-decision --gate B` records it and journals `deliver_with_risks` with their reason; when gate B is already recorded the "
     "refusal names `log_append.py --event deliver_with_risks --task <T> --reason-file <file>` (HF8-23).",
     "test": "scripts/tests/test_stage_guard.py (stage_guard.py --selftest, rules 3 and 4)"},
    {"id": "SG-gate-ordered", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "{ticket}: {message}",
     "refuses": "rule 4 for a ROLE (t-1547, GB-2) - the executor of a gate's order (S8 `gate_orders`: `qa-bug-reporter` "
               "for gate B, read by `hooklib.gate_orders`) while that gate has no recorded approving decision "
               "(`contract.gate_approved`): no `gates.B`, an empty or non-object record, declined, deferred, edit. "
               "The delivery verdict is not asked: a story whose checks say `no` files its bugs once the person chose them",
     "override": "the decision itself: `controller.py --task-root <T> --operation gate-decision --gate B --drafts "
     "\"<the refs they chose>\" --bugs ordered --words-file <file>` - the refusal carries that exact command",
     "unpassable_because": "",
     "test": "scripts/tests/test_gate_ordered_reporter.py"},
    {"id": "SG-manifest-unread", "file": "stage_guard.py", "function": "check_dispatch",
     "call": "{ticket}: {message}",   # no site of its own: the line is raised through SG-stage-rules' compound
     "refuses": "rule 3 on the S6/S7/S8 dispatch branch (`dispatch_errors`, so also `stage_guard.py --ticket --stage` and "
               "`controller.py --operation dispatch`) - a story whose pipeline.json does not record S5 as skipped by a policy "
               "while work/automation-manifest.json (or the flat legacy name, read only when work/ holds none) is ABSENT, or "
               "is there and cannot be read (not UTF-8, not JSON, not an object): the manifest is the thing the stage is "
               "judged against, and `read_json`'s `{}` used to read as 'no open items'. Two texts, told apart: 'is absent' / "
               "'could not be read'. A manifest read with zero items passes as before; so does an absent one when "
               "pipeline.json records S5 as skipped. The commit of test code does not take this branch (S5 commits tests "
               "before the manifest exists). It is one item of the combined refusal (SG-stage-rules) when the order or gate A "
               "reasons also stand",
     "override": WAIVER + " with `--block \"is absent\"` (or \"could not be read\", \"unresolved cases without a reason\"): "
     "the word does not create the manifest, it says 'go on without one' - S6-S8 then run on an empty manifest, informed. "
     "`dispatch_errors()` filters the line through `waiver.split_overridden` like rules 1 and 2 and journals the pass as "
     "`gate_override` (P13); the refusal ends with the ready command.",
     "unpassable_because": "",
     "test": "scripts/tests/test_stage_guard.py (part_manifest_not_read: present/absent/broken at S6, S7 and S8)"},
    {"id": "SG-command", "file": "stage_guard.py", "function": "check_command",
     "call": "{ticket}: {message}",
     "refuses": "the Bash side — a `git commit` of test code or a delivery command under "
               "rules 3 and 4, a commit or stash that does not name its paths (rules 5 and 7), "
               "and an untyped full-suite run while a dispatch is open. It no longer refuses a "
               "`run_suite.py` call that launches no test (--reparse-block, --recover, "
               "--detail, --help), a command that only mentions the runner, or an instance of "
               "a case that is in scope",
     "override": "rules 3 and 4 as in SG-manifest-delivery; rules 5 and 7 are passed by naming "
     "the paths, which is what the message asks for and costs one edit; the typed-runner rule "
     "is passed by the shape the message names, and never costs a rerun of a green test.",
     "test": "scripts/tests/test_stage_guard.py (stage_guard.py --selftest, rules 5 and 7)"},

    # --- inject_context.py — the second line on the Agent hook ---------------------------
    {"id": "IC-oversized-slice", "file": "inject_context.py", "function": "collect_blocks",
     "call": "required context {rel} exceeds budget",
     "refuses": "a dispatch whose injected context exceeds MAX_BLOCK_CHARS; the driver's `system_file` raises the same text as a Refusal to the conductor and writes the same denial line (RC1-14 step 5)",
     "override": "",
     "unpassable_because": "the factory's own defect: at a lower fuse this reached a role "
     "TRUNCATED and silently, which is why it is loud now. Its producer splits the file; "
     "nothing is wanted from the person.",
     "test": "scripts/tests/test_stages.py"},

    # --- guard_pre_tool.py — registered here by reading it ------
    {"id": "PT-direct-test-run", "file": "guard_pre_tool.py", "function": "runs_check",
     "call": "RUNS_MSG",
     "refuses": "a direct test launch (any form in launch-causes.json run_forms) instead of run_suite.py",
     "override": "",
     "unpassable_because": "economy, not risk. The sanctioned command in the message runs the "
     "same tests and leaves the evidence, so there is nothing to overrule.",
     "test": "scripts/tests/test_run_forms.py (and guard_pre_tool.py --selftest)"},
    {"id": "PT-git-config", "file": "guard_pre_tool.py", "function": "git_config_check",
     "call": "GIT_CONFIG_MSG",
     "refuses": "a write to git configuration from a role's shell",
     "override": "the person changes their own machine's configuration themselves — the "
     "message tells the role to report the blocker and let them decide.",
     "test": "scripts/tests/test_guard_command_text.py, scripts/tests/test_hook_lifecycle.py "
     "(guard_pre_tool.py --selftest)"},
    {"id": "PT-config-write", "file": "guard_pre_tool.py", "function": "config_write_check",
     "call": "CONFIG_WRITE_MSG.format(what=what)",
     "refuses": "a factory ROLE writing qa-factory/config.json (Write/Edit on it, or a shell write "
     "shape naming it) - the profile holds the command every window of the story runs; the "
     "orchestrator and the main session are never refused, and reading the file is never blocked",
     "override": "a person's word changes the profile through the orchestrator: it edits the profile "
     "itself and runs `launch_check.py --profile <id>` to prove the command. The role does not "
     "repair it: it reports `launch: <cause>` (or `launch: unknown`) with the evidence line, one "
     "line of the run's own error text, in its digest, and the point reaches the orchestrator.",
     "test": "scripts/tests/test_guard_write_owners.py"},
    {"id": "PT-logs", "file": "guard_pre_tool.py", "function": "logs_check",
     "call": "LOGS_MSG",
     "refuses": "reading an evidence run log heavier than guards.raw_log_free_bytes",
     "override": "",
     "unpassable_because": "the message names two cheaper routes to the same content: the "
     "summary's error_head and run_suite.py --detail.",
     "test": "scripts/tests/test_guard_dispatch_budget_and_logs.py"},
    {"id": "PT-big-read", "file": "guard_pre_tool.py", "function": "big_read_check",
     "call": "PRE-TOOL GUARD: reading {normalized} whole is blocked",
     "refuses": "reading a large file whole instead of by offset/limit, or a large .pdf without a pages range within "
     "config.read.max_pdf_pages (offset/limit do not bound a PDF), or a picture (by its first bytes) over "
     "config.read.max_image_bytes",
     "override": "",
     "unpassable_because": "the same read in a cheaper shape is in the message; no content "
     "is withheld; a file read by section gets the map of its sections in the message, the "
     "project config gets the key door; a picture over its limit is named with the record-it-unread door.",
     "test": "scripts/tests/test_hook_lifecycle.py (guard_pre_tool.py --selftest), "
     "scripts/tests/test_guard_big_read_sections.py"},
    {"id": "PT-command-size", "file": "guard_pre_tool.py", "function": "size_check",
     "call": "SIZE_MSG",
     "refuses": "a Bash or PowerShell command over 64 KB (MAX_COMMAND_CHARS), refused before any other "
                "guard reads it - every reader walks the whole text, so one hostile command cost the "
                "guards minutes, past any hook timeout (CX1-20 F-8); a command at the cap, and a tool "
                "that is no shell, are never refused",
     "override": "",
     "unpassable_because": "nothing passes it: the guard cannot judge text it does not read, and "
     "a person's word cannot make an unread command safe. The door is in the message: several "
     "commands, or the long text written to a file with the Write tool and named in the command.",
     "test": "scripts/tests/test_run_forms.py (key 21, the size cap)"},
    {"id": "PT-case-store", "file": "guard_pre_tool.py", "function": "case_store_check",
     "call": "PRE-TOOL GUARD: this project keeps its test cases in",
     "refuses": "writing a case outside the project's declared cases_root",
     "override": "the person changes `cases_root` in qa-factory/config.json — the store is "
     "the project's own decision and is already recorded there.",
     "test": "scripts/tests/test_case_store.py"},
    {"id": "PT-manifest-shrink", "file": "guard_pre_tool.py", "function": "manifest_write_check",
     "call": "PRE-TOOL GUARD: this manifest already holds",
     "refuses": "a whole-file manifest write that would drop entries already held",
     "override": "",
     "unpassable_because": "losing recorded entries is never what anyone meant; the message "
     "names the additive form of the same write.",
     "test": "scripts/tests/test_hook_lifecycle.py (guard_pre_tool.py --selftest)"},
    {"id": "PT-artifact-rewrite", "file": "guard_pre_tool.py", "function": "artifact_rewrite_check",
     "call": "PRE-TOOL GUARD: {name} already exists, and a Write replaces ",
     "refuses": "a whole-file Write over an artifact that already has content and whose entry in "
     "references/artifact-writers.json names how it is changed in place",
     "override": "",
     "unpassable_because": "nothing is being refused except the shape of the same write: the "
     "registry entry names the point edit, every role carries Edit, and the role's own content "
     "stays. A role that still cannot do it records that in its findings and halts — it never "
     "retries. Removing the `rewrite` field from an artifact's entry is how a maintainer exempts "
     "it: not a role's call, and not a person's, because no decision of theirs needs a rewrite.",
     "test": "scripts/tests/test_fixes_13797.py"},
    {"id": "PT-plan-rewrite", "file": "guard_pre_tool.py", "function": "plan_write_check",
     "call": "PRE-TOOL GUARD: this plan already holds {len(ids)} rows ({',",
     "refuses": "a whole-file Write over work/test-plan.json once it carries rows",
     "override": "",
     "unpassable_because": "`plan_row.py --set` changes a field, `--add-row` appends a row the role "
     "wrote, and Edit changes any line, so every change a rewrite could make is available without "
     "spending the file again; the first write of the plan is not refused at all. A role that "
     "still cannot do it records that in its findings and halts.",
     "test": "scripts/tests/test_fixes_13797.py"},
    {"id": "PT-plan-md-rewrite", "file": "guard_pre_tool.py", "function": "plan_write_check",
     "call": "PRE-TOOL GUARD: test-plan.md already exists and a Write repl",
     "refuses": "a whole-file Write over test-plan.md once it exists",
     "override": "",
     "unpassable_because": "this file is the role's own prose for the person, and Edit changes any "
     "part of it, including adding a row's line; a person asking for a different plan changes the "
     "plan, which is these same edits, never a rewrite of the file.",
     "test": "scripts/tests/test_fixes_13797.py"},
    {"id": "PT-handoff-rewrite", "file": "guard_pre_tool.py", "function": "handoff_write_check",
     "call": "PRE-TOOL GUARD: the handover form is filled through its values file",
     "refuses": "a whole-file Write over a handover form that already exists",
     "override": "",
     "unpassable_because": "the same write in the form the rule names loses nothing: the role's "
     "fields go into `<dispatch>.values.yaml` in one Write (or `--fix --values -` for a role with "
     "Bash), which the next check applies, and Edit changes one line while no values file waits. "
     "A rewrite drops what `--fix` just derived and costs a file of output that then sits in the "
     "role's context.",
     "test": "scripts/tests/test_guard_dispatch_budget_and_logs.py"},
    {"id": "PT-handoff-values", "file": "guard_pre_tool.py", "function": "handoff_values_check",
     "call": "PRE-TOOL GUARD: these handover values leave the form not ready",
     "refuses": "a Write of `<dispatch>.values.yaml` whose lines, merged into the form in memory, "
     "leave the form not ready (a word outside the list, a line that does not parse, an unknown "
     "path); the refusal is one block with the role's good lines kept and the lines to fix",
     "override": "",
     "unpassable_because": "nothing a role needs is behind it: the refusal carries every good "
     "line back and the lines to fix, so the next Write of the same file is the fix; a field the "
     "role cannot fill is said in `blocked.field` and `blocked.problem` in the same file, and a "
     "file that fills `blocked.problem` is never refused; a field only code can fill is not asked "
     "for, and any error inside the check lets the file land (`--fix` checks it again).",
     "test": "scripts/tests/test_guard_dispatch_budget_and_logs.py"},
    {"id": "PT-handoff-edit-pending", "file": "guard_pre_tool.py", "function": "handoff_write_check",
     "call": "PRE-TOOL GUARD: {waiting} is waiting to be applied to this form",
     "refuses": "an Edit of a handover form while its `<dispatch>.values.yaml` waits to be applied",
     "override": "",
     "unpassable_because": "the waiting file is applied over the form at the next check, so the "
     "edit would be lost; the same field goes into the values file (rewritten whole, with the "
     "field added), and a role with Bash can apply the file first with `--fix` and then Edit.",
     "test": "scripts/tests/test_guard_dispatch_budget_and_logs.py"},
    {"id": "PT-handoff-code-file", "file": "guard_pre_tool.py", "function": "handoff_write_check",
     "call": "PRE-TOOL GUARD: {name} is written by code",
     "refuses": "a Write of `<dispatch>.values.applied.yaml` or `<dispatch>.values.stale.yaml`, "
     "the traces code leaves of a values file it applied or set aside",
     "override": "",
     "unpassable_because": "nothing reads these names and a role has no use for them; the words "
     "the role means go into `<dispatch>.values.yaml`, which the refusal names.",
     "test": "scripts/tests/test_guard_dispatch_budget_and_logs.py"},
    {"id": "PT-owner", "file": "guard_pre_tool.py", "function": "owner_check",
     "call": "PRE-TOOL GUARD: {raw.rsplit",
     "refuses": "a repair of a role's artifact from outside that role, with no dispatch open",
     "override": "`controller.py --operation rework --stage <S> --role <role> --cases <ids> "
     "--reason \"...\" --brief` opens the dispatch that makes the write the role's own.",
     "test": "scripts/tests/test_hook_lifecycle.py (guard_pre_tool.py --selftest)"},
    {"id": "PT-window-file", "file": "guard_pre_tool.py", "function": "window_file_check",
     "call": "_window_refusal(WF, task_root, rel, owner, count)",
     "refuses": "a Write, Edit or NotebookEdit by an S5 window of a test file another window of the story claimed first and "
     "has not released (`state/window-files/`; a window sharing a case with the owner is the owner); the refusal names the owner's "
     "cases, the door and the conductor's command; from the second in a row it names the story's state, never a guard fault",
     "override": "the door is a new file in the same directory (a test in a new file is judged the same, P17); no waiting door. "
     "A person's word is recorded by the conductor as for any block, and the conductor frees the claim with "
     "`python window_files.py --task <task root> --release \"<window>\"`.",
     "test": "scripts/tests/test_guard_window_files.py"},
    {"id": "PT-external-writes", "file": "guard_pre_tool.py", "function": "writes_check",
     "call": "WRITES_MSG",
     "refuses": "a role writing to a tracker or a TMS from a shell",
     "override": "the proposal file plus gate B: the person approves the write there and "
     "`external_writes.py` performs it after the gate.",
     "test": "scripts/tests/test_external_writes.py, scripts/tests/test_publication_gates.py"},
    {"id": "PT-plugin-read", "file": "guard_pre_tool.py", "function": "plugin_read_check",
     "call": "PLUGIN_READ_MSG",
     "refuses": "a ROLE's Read, Grep or Glob inside the installed plugin (scripts, skills, agents, "
                "hooks) - the brief `work/briefs/<dispatch>.md` already names the files and every "
                "command with its argument shape; references/ stays readable; the orchestrator, the "
                "driver and the hooks are never a role and are untouched",
     "override": "",
     "unpassable_because": "nothing a role needs is behind it: `python <plugin>/scripts/<x>.py "
     "--help` runs through Bash and answers the interface, references/ carries every contract "
     "and template, and a script's internals are the factory's, not the role's - a role that "
     "believes it needs them reports that gap in its digest and the orchestrator, which the "
     "rule never touches, reads them.",
     "test": "scripts/tests/test_brief_pack.py (the guard section)"},
    {"id": "PT-human-word", "file": "guard_pre_tool.py", "function": "human_word_check",
     "call": "HUMAN_WORD_MSG",
     "refuses": "a ROLE running waiver.py --stage / accept-gap / review --record / "
                "stand_identity.py record|confirm|forget|unconfirm / environment_record.py record|revoke / report_adapt.py kind / "
                "waiver.py --carry-from (the copy of a person's words from another key, GW1-40)",
     "override": "",
     "unpassable_because": "this is the refusal that protects every other override. A role "
     "recording a person's word on their behalf is the factory excusing itself; the "
     "orchestrator records it, in the same turn, from what the person actually said. It "
     "matches the executable part of a command only, and says so in its own last line: "
     "quoting the call in a file a role writes is not running it (2026-09-23).",
     "test": "scripts/tests/test_guard_command_text.py, scripts/tests/test_hook_lifecycle.py "
     "(guard_pre_tool.py --selftest)"},
    {"id": "PT-stand-record-write", "file": "guard_pre_tool.py", "function": "stand_record_write_check",
     "call": "STAND_RECORD_MSG.format(what=what)",
     "refuses": "a factory ROLE writing the stand registry (qa-factory/records/stand-identity.json), "
                "the environment record (qa-factory/records/environment-properties.json), the report adaptations "
                "(qa-factory/records/report-adaptations.json) "
                "or a story's stand confirmations (qa-factory/artifacts/<story>/state/"
                "stand-confirmations.jsonl): Write/Edit on any of them, or a shell write shape naming "
                "it; the main session, the driver and the conductor are never refused; reading is "
                "never blocked",
     "override": "a person's word is recorded by the driver or the conductor with "
     "stand_identity.py record|confirm|forget|unconfirm or environment_record.py record|revoke; the role hands off as a halt in the digest's "
     "own form - the row `stand · blocked · <what is wrong, at most 80 characters>` - with the one "
     "evidence line in the handoff form's `blocked` section (handoff_help.py)",
     "test": "scripts/tests/test_guard_command_text.py"},
    {"id": "EG-digest-form", "kind": "operation", "file": "exit_gate.py",
     "function": "digest_errors", "guarantor": "split_overridden",
     "refuses": "a handoff whose final message is not the digest form - prose instead of a "
               "header, one line per item in scope and a path. The five roles of 2026-09-22 "
               "ended in 786-3,401 characters of prose each, and the orchestrator carried "
               "every one of them to the end of the story and compacted mid-S5",
     "override": WAIVER + " with the block text `digest` - `all_errors` splits it like every "
     "other gate error. A host that sends no transcript, a foreign agent, and the scope a "
     "halting digest never reached are not refused at all.",
     "test": "scripts/tests/test_role_digest.py"},
    {"id": "PT-unparsed-event", "file": "guard_pre_tool.py", "function": "main",
     "call": "PRE-TOOL GUARD: hook event could not be parsed",
     "refuses": "a hook event that cannot be parsed",
     "override": "", "fail_closed": True, "escalates_after": 2,
     "unpassable_because": "fail-closed on purpose — the app-boundary and secrets checks did "
     "not run, so the guard cannot know what it would be letting through.",
     "escalation": "the SECOND in a row on a different call is a diagnosis about the guard, "
     "not an answer about the call: `guard_pre_tool.escalate` names the factory as owner, "
     "writes a finding through `project_decisions.add_finding` and sends the story to "
     "`/qa-factory:qa-doctor` instead of repeating the refusal.",
     "test": "scripts/tests/test_hook_lifecycle.py (guard_pre_tool.py --selftest, escalation)"},
    {"id": "PT-walker-error", "file": "guard_pre_tool.py", "function": "walker_refusal",
     "call": "PRE-TOOL GUARD: ' + WALKER_DOOR",
     "refuses": "a shell command the command walker raised on (WalkerError, CX1-20 N-1): blocked with "
                "the door, never an exit 1 that the host reads as a non-blocking error",
     "override": "",
     "unpassable_because": "the fault is the guard's command reader, not the person's or the "
     "command's: no word makes an unread command judged. The message names the door (several "
     "simpler commands, or the text written to a file with the Write tool), and the SECOND in a "
     "row on a different call is counted like PT-unparsed-event (`escalate(\"PT-walker-error\", "
     "...)`): a diagnosis owned by the factory, never a repair asked of the person.",
     "test": "scripts/tests/test_run_forms.py (key 21, N-1: a walker exception blocks with exit 2)"},
    {"id": "SG-walker-error", "file": "stage_guard.py", "function": "check",
     "call": "hooklib.WALKER_DOOR.format(",
     "refuses": "a shell command the command walker raised on, inside the stage guard's `check` "
                "(CX1-20 N-1): a deny with the door, never the fail-open of an ordinary crash",
     "override": "",
     "unpassable_because": "the fault is the guard's command reader, not the person's or the "
     "command's: no word makes an unread command judged. The message names the door - several "
     "simpler commands, or the long text written to a file with the Write tool.",
     "test": "scripts/tests/test_stage_guard.py (N-1: a walker exception inside check is a deny)"},
    {"id": "PT-doctor-probe", "file": "guard_pre_tool.py", "function": "_guard",
     "call": "QA FACTORY DOCTOR: expected harmless deny probe",
     "refuses": "nothing real — qa-doctor's own probe expects this denial as its measurement",
     "override": "not applicable: the refusal IS the answer the probe asked for.",
     "test": "scripts/tests/test_doctor_access.py"},
    {"id": "PT-patch-unchecked", "file": "guard_pre_tool.py", "function": "_guard",
     "call": "PRE-TOOL GUARD: {exc}; patch was not checked",
     "refuses": "a Write/Edit whose content could not be checked",
     "override": "", "fail_closed": True, "escalates_after": 2,
     "unpassable_because": "fail-closed, same reason as PT-unparsed-event.",
     "escalation": "as PT-unparsed-event: the second in a row on a different call stops the "
     "story with a diagnosis owned by the factory, never with a repair asked of the person.",
     "test": "scripts/tests/test_hook_lifecycle.py (guard_pre_tool.py --selftest, escalation)"},

    # --- registered by operation, not line by line (see the module docstring) ------------
    {"id": "CTRL-dispatch", "kind": "operation", "file": "controller.py",
     "function": "apply(dispatch)", "guarantor": "_passed_by_person",
     "refuses": "a dispatch request the controller's validator rejects, and — the "
               "stage rules it runs BEFORE writing the receipt",
     "override": WAIVER + " — `_passed_by_person` runs `waiver.split_overridden` over that "
     "stage's errors, and a refusal now leaves no receipt behind for `next` to poll forever.",
     "test": "scripts/tests/test_gate_vocabulary.py, scripts/tests/test_controller_state.py"},
    {"id": "SS-needs-author", "kind": "operation", "file": "story_step.py",
     "function": "finish --needs-author", "guarantor": "_needs_author",
     "refuses": "the S5 critic's move 'its author's work is defective, send the author back' (HF8-15 (2)) when it is made with no reason or "
                "no cases, with an acceptance flag (`--complete`, `--unresolved`, `--ignore-handoff`, `--window`, `--output`), on another "
                "role or on the plan's critic, on a dispatch that is not open, on a closed story, over a case outside the critic's window, "
                "while the critic's worker is not proved returned (`host worker is still active`), or past what `dispatch` of the author "
                "refuses (the probe: the repair ceiling, the cause vocabulary, an author not accepted, cases of several windows); every one "
                "before anything is written, except a revision race",
     "override": "the move names its own door in each refusal: the form of the command, `rework --purpose s5_plan` for the plan, `story_step.py "
     "where` for a closed critic, `controller.py --operation release --dispatch <id> --words-file <the person's words>` for a worker that "
     "is gone, a person's words on `rework --words-file` for a closed story, and the repair ceiling's own door (`--cause` other than "
     "`test_defect`, or the person's `repair_doors` word) - a person's recorded word passes the ceiling exactly as it passes any dispatch",
     "test": "scripts/tests/test_needs_author.py"},
    {"id": "CTRL-s5-plan-order", "kind": "operation", "file": "controller.py",
     "function": "apply(dispatch)", "guarantor": "_s5_plan_problems",
     "refuses": "an S5 dispatch that breaks the plan order (SC1-14 B1b): a window with no plan, an unreadable or gapped plan, no accepted "
               "review of it, a blocked review, a plan changed after its review, a plan written for other cases, a window case the plan "
               "does not have, a fresh window whose scope splits the cases of one test of the plan (SC1-14 FJ-B (11): a test is written in "
               "one window), an author or critic dispatch that goes round a window grown after the plan review (SC1-14 FJ-C (12): the "
               "author reworks it with the new case first; and a fresh author dispatch over a window already written, whose door is the "
               "rework of that window), the driver on the plan form; a plan dispatch on the wrong stage or role, as a rework of a window, on a story "
               "that began on the earlier form, a critic before the author's plan, a second fresh plan, a look past the review cap",
     "override": "a person's word on S5, one per refusal and none a substring of another: `waiver.py --task <T> --stage S5 --block "
     "\"plan before windows\"` (the plan, its review or its fit is waved through; a blocker goes to the window as a remark), "
     "`\"plan form switch\"` (the story changes form: a plan on the earlier form, the driver on the plan form) and "
     "`\"plan review round\"` (one more look of the critic); the shape refusals (stage, role, parent, predecessor) are the call's "
     "and name their door",
     "test": "scripts/tests/test_s5_plan_controller.py, scripts/tests/test_s5_plan_windows.py"},
    {"id": "CTRL-s5-plan-accept", "kind": "operation", "file": "controller.py",
     "function": "apply(accept)", "guarantor": "_s5_plan_accept_problems",
     "refuses": "the accept of a plan dispatch (SC1-14 B1b): `stage_complete: true` (a plan never closes S5), an author's plan with a gap, a "
               "rework that changed a row no blocker names, a critic's review that cannot be read, contradicts itself, was stamped on "
               "other bytes than the plan now holds, or reuses a remark id of the chain; since FJ-C also a rework that changed a row "
               "that is neither a blocker row, a new case nor a test neighbour of a new or dropped case, and a narrow look whose scope "
               "misses a row that moved since the previous review (or, when the previous review cannot be read, misses any row of the plan)",
     "override": "the role mends it and the conductor returns it whole (`This is a repair, not a question for the person`); a "
     "person's words on a rework (`--words-file`) lift the row bound and the look scope, and the changed plan is then looked at again "
     "(E11); the look scope is also passed by the person's word `plan before windows` (`waiver.py --task <T> --stage S5 --block "
     "\"plan before windows\"`), and the pass is recorded in `state/passed-by-person.jsonl`; the look's door names the whole set of "
     "cases it must cover",
     "test": "scripts/tests/test_s5_plan_controller.py, scripts/tests/test_s5_grown_windows.py"},
    {"id": "CTRL-s5-grown-close", "kind": "operation", "file": "controller.py",
     "function": "apply(accept)", "guarantor": "_grown_close_problems",
     "refuses": "the accept of an S5 window record with `stage_complete: true` while a window that grew after the plan review has not "
               "been covered by both its author and its critic over all its cases (SC1-14 FJ-C (13)); a cut that cannot be read is not "
               "a pass",
     "override": "the author reworks the window with the new case (`rework --role qa-automator --cause ticket_changed`) and its critic "
     "reviews it over the whole window; or a person's word `plan before windows` (`waiver.py --task <T> --stage S5 --block "
     "\"plan before windows\"`)",
     "test": "scripts/tests/test_s5_grown_windows.py"},
    {"id": "EG-s5-plan-outputs", "kind": "operation", "file": "exit_gate.py",
     "function": "required_outputs_errors", "guarantor": "_s5_plan_dispatch",
     "refuses": "the end of a plan dispatch of S5 without its output: the author's `work/s5-plan.json`, the critic's handover form with a "
               "`remarks` section; the manifest and the evidence are the windows' and are not asked of a plan",
     "override": WAIVER + " with the block text `missing required output` - `all_errors` splits it like every other gate error.",
     "test": "scripts/tests/test_s5_plan_controller.py"},
    {"id": "EG-s3-regression", "kind": "operation", "file": "planning_contract.py",
     "function": "_detector_body", "guarantor": "_regression_findings",
     "refuses": "the end of S3 while the plan's `## Recommended regression` is absent or blank, mixes `No regression:` with a list, "
                "names a test the main branch does not hold (a test written in this run), names a file twice or under another item's "
                "folder, leaves an item out of every `Command:` line (or in two), runs the factory's scripts, names an absolute path, "
                "or has an item with no `stand:` (RG1-1, RG1-2, P24); a main branch git cannot name silences only the main-branch "
                "check, and a check that cannot run is a WARN, never a refusal",
     "override": WAIVER + " with the block text `<part of the line>` of the problem; the regression is a recommendation to the person "
                 "and never holds a delivery",
     "test": "scripts/tests/test_regression_scope.py"},
    {"id": "EG-s3-plan-target", "kind": "operation", "file": "planning_contract.py",
     "function": "_detector_body", "guarantor": "fit_target_findings",
     "refuses": "the end of S3 while a plan row's `fit: extend|param <test>`, or a `reuse` link's candidate id / test_ref path, names a test "
                "the project's working tree does not have: no such file, a folder, a path outside the tree (absolute, `..`, `~`, a link) "
                "or no name (TQ1-21); a working tree that cannot be found or a lookup that cannot tell is a WARN (S4 writes the case as "
                "new), never a refusal, and a check that cannot run is `UNREADABLE`, never a pass",
     "override": WAIVER + " with the block text `<part of the line>`; or the strategist names the test as it is in the working tree, or "
                 "plans `fit: new` with `fit_absent: \"<test>\"`",
     "test": "scripts/tests/test_fit_targets.py"},
    {"id": "EG-s3-requests", "kind": "operation", "file": "planning_contract.py",
     "function": "_detector_body", "guarantor": "_request_findings",
     "refuses": "the end of S3 while a request of work/flow-requests.json has a failure kind of perturbations.json (500, timeout) on no plan "
                "row (`requests`, with the R of its flow in `requirements`) and in no `request_homes` entry, or a `requests` / `request_homes` "
                "entry is malformed (RN1-6); an absent list says nothing (a story planned before it existed), an unreadable one is "
                "recomputed from the code and, when that fails too, is `UNREADABLE`, never `OK`",
     "override": WAIVER + " with the block text `<part of the line>` of the problem; the line itself names both doors: `requests` on a row, "
                 "or `request_homes` with a reason",
     "test": "scripts/tests/test_flow_requests.py"},
    {"id": "EG-text-end", "kind": "operation", "file": "exit_gate.py",
     "function": "main", "guarantor": "text_end_after_handback",
     "refuses": "the end of a turn of a role that has ALREADY handed its report back (the host's handback call is in its own transcript) "
                "and then ended in plain text (HF8-15 (1a)): the conductor has no return to take, and the story waits. Only the first stop; "
                "the host's own re-entry and the one-block fuse release it, and `finish` and the driver never see this record",
     "override": "the refusal names the door: the role calls the host's handback tool (its name is data, the host's report forms table) "
                 "with its digest line; the re-entry runs the other checks only and does not re-read this record, so the repair is seen by "
                 "the host's own return record; a person's word is not what it asks for - nothing a person decides "
                 "is refused here, and the second stop of the same input is released. Only a role with a running dispatch is refused",
     "test": "scripts/tests/test_exit_text_end.py"},
    {"id": "CS-conductor-wake", "kind": "operation", "file": "conductor_stop.py",
     "function": "decide", "guarantor": "wake_text",
     "refuses": "the end of a turn of the CONDUCTOR's session (Stop) while a dispatch of its own, still `running` in the controller and bound "
                "by `story_step`, has a role the host's own record says has returned (`dispatch_liveness` RETURNED over every non-terminal "
                "receipt of the dispatch; HF8-15 (1b)) - once per return, never for ALIVE or an unknown, never for another session's receipt, "
                "never in the driver's mode",
     "override": "the text names the move: `story_step.py finish --task T --dispatch-id D --digest -`, or `--needs-author`; a second Stop for the "
                 "same return (the key (session, dispatch, last_at) in `state/conductor-stop.json`, or the host's `stop_hook_active`) is "
                 "released, so a person's question is delayed by one conductor turn and never locked out",
     "test": "scripts/tests/test_conductor_stop.py"},
    {"id": "GS-gate-message-shown", "kind": "operation", "file": "gate_shown.py",
     "function": "decide", "guarantor": "missing",
     "refuses": "the end of a turn of the conductor's session (Stop) while gate A of a story whose message this session asked "
                "(state/gate-message.json, gate A not decided) has not been shown: the turn since the message was written carries not "
                "every card marker, Answer line and the approval line of work/gate-a-message.md - once per message bytes, never for "
                "another session's story, never in the driver's mode",
     "override": "the text names the move: print the file whole; a second Stop for the same message is released "
                 "(state/gate-shown.json) and filed as a gate_not_shown signal (a gate_unreadable one when the check could not "
                 "establish it)",
     "test": "scripts/tests/test_gate_shown.py"},
    {"id": "CTRL-decision", "kind": "operation", "file": "controller.py",
     "function": "apply(decision)", "guarantor": "check_decision",
     "refuses": "a gate decision whose scope, hashes or design reviews do not hold",
     "override": "`--operation gate-preflight` runs this same validation BEFORE the person is "
     "asked, so a refusal after their answer is a factory defect and never their repair; where "
     "one survives, the gate packet carries it and their word is recorded with " + WAIVER,
     "test": "scripts/tests/test_gate_vocabulary.py, scripts/tests/test_controller_lifecycle_gate.py"},
    {"id": "CTRL-executing", "kind": "operation", "file": "controller.py",
     "function": "apply(dispatch)", "guarantor": "_executing_refusal",
     "refuses": "a dispatch on a story whose gate B is decided and S8 is done while an order of that decision is still due (t-1509): "
                "anything but the executor of a due order (the bug reporter for `bugs`), a rework carrying a person's words, and the "
                "retro (S9) - which waits until every order is settled",
     "override": "the executor runs (`story_step.py start --task <T> --stage S8 --role qa-bug-reporter`); a person who calls an order "
     "off says so in `controller.py --operation settle_order --order <order> --outcome cancelled --words-file <file>`; new work on "
     "the story starts on a person's word in `controller.py --operation rework ... --words-file <file>`, which reopens it",
     "test": "scripts/tests/test_gate_b_orders.py"},
    {"id": "CTRL-settle-order", "kind": "operation", "file": "controller.py",
     "function": "apply(settle_order)", "guarantor": "_settle_order_refusal",
     "refuses": "a `settle_order` call (t-1509) that names no known order or outcome, marks `bugs` done by a word, marks an MR done with "
                "no record (`--ref`), cancels with neither a person's words nor a coded reason, carries a `--ref` over 2000 characters, "
                "or settles an order that is not due / a gate B that is not decided",
     "override": "each refusal names the call that passes: the order's own executor for `bugs` (the accepted reporter settles it), "
     "`--ref <MR link or id>` for an MR, `--words-file <file>` (the person's own words) or `--reason-code no_trace|delivered_without_mr "
     "--ref <the delivery step's record>` for a cancellation, `--operation next` for the state, `gate-decision --gate B` for an undecided gate",
     "test": "scripts/tests/test_gate_b_orders.py"},
    {"id": "CTRL-first-look-continue", "kind": "operation", "file": "controller.py",
     "function": "apply(first_look_continue)", "guarantor": "_hold_op_refusal",
     "refuses": "a `first_look_continue` call (t-2277 J-C10) that carries no words of the person, no `--source-head` text, a "
                "`--register-hash` that is not 64 hex characters, or comes on a story held for `s5_absent_side` (only the code arriving, "
                "or the person's `not ours` for the side, clears that hold) or stopped (the wait was ended); with no hold at all it only records",
     "override": "each refusal names the call that passes: `--words-file <file>` (the person's own words) with the two keys the driver "
     "takes from `first_look.py show --json`, `arrive` (relaunch with `--mr`, `--branch`, `--commit` or `--side <side>=real`) for the "
     "code (or the person's `not ours` answer about an absent side, which the driver carries out through `arrive` naming that side), "
     "`stop_waiting --words-file <file>` to end the wait, `rework --words-file <file>` of S0..held_from-1 for a stopped story",
     "test": "scripts/tests/test_awaiting_state.py"},
    {"id": "CTRL-next-blocked", "kind": "operation", "file": "waiver.py",
     "function": "run_stage", "guarantor": "route_release",
     "refuses": "not a message but an ANSWER that stops the story just as hard: "
               "`controller.py --operation next` replying `wait_existing_job` or "
               "`resume_checkpoint` for a dispatch nobody is working on. On TP1-15045 "
               "the person said \"it's dead, go on\", the word was recorded, and `next` kept "
               "answering `wait_existing_job` — A24 never caught it because 'wait' was not "
               "written down as a refusal",
     "override": "`waiver.py --task <T> --stage <S> --block \"wait_existing_job\" --words-file "
     "<file>` — `route_release` reads the dispatch id out of the block text (or takes the only "
     "running one) and passes the same words on to `controller.py --operation release "
     "--dispatch <id>` (a list-argv call, one line typed by code), then prints the controller's "
     "own answer as `block lifted`.",
     "test": "scripts/tests/test_refusal_registry.py, scripts/tests/test_stage_guard.py"},
    {"id": "WV-placeholder-block", "kind": "operation", "file": "waiver.py",
     "function": "record_refusals", "guarantor": "PLACEHOLDER_RE",
     "refuses": "recording a `--block` that still holds the form's placeholder (`probe gap: <case key>`, `RP-<profile>`): "
               "it names nothing, so the record would pass nothing and read as a decision (GW1-1). `*`, `stand gap:` and "
               "`protected test path:` keep their own branches; an old record with a placeholder stays on disk, passes nothing "
               "and can be revoked",
     "override": "the same `--block` with the real value in place of the placeholder; if the words name nothing the check shows, "
     "`waiver.py --task <T> --remark --stage <S> --words-file <file>` keeps them without a pass",
     "test": "scripts/tests/test_whole_identifier.py"},
    {"id": "WV-carry-source", "kind": "operation", "file": "waiver.py",
     "function": "run_carry", "guarantor": "run_carry",
     "refuses": "`waiver.py --carry-from <old key>` (GW1-40) naming a source that cannot be read as the earlier story: a key that is not one folder "
               "name (empty, a slash, a backslash, `..`), the key of the story itself, a `--carry-from-root` that is not a folder, no folder of that "
               "key under the root, an old `pipeline.json` that is missing, not JSON or not an object (an unknown source is never read as "
               "`nothing to carry`), or an old `stage_overrides` that is present and not a list. Nothing is written",
     "override": "the same command with the earlier story's key as its folder is named; `--carry-from-root <folder>` names the folder that holds "
     "it when it was moved by hand (`superseded/`); a source whose pipeline.json cannot be read is repaired first",
     "test": "scripts/tests/test_words_carry.py"},
    {"id": "WV-carry-target", "kind": "operation", "file": "waiver.py",
     "function": "run_carry", "guarantor": "EXIT_NO_PIPELINE",
     "refuses": "`waiver.py --carry-from` into a story that has no `pipeline.json` (words belong to a story that exists), or into a story whose "
               "`work/gap-classes.json` cannot be read (the kinds of gap are not written over it, and no word is carried either: a half carry "
               "would be a promise), or a `stage_overrides` of the new story that is present and not a list. Nothing is written",
     "override": "run the new key's S0 (`story_run.py --task <new key> ...`), then the same command; repair or remove the unreadable "
     "`work/gap-classes.json` of the new story, then the same command",
     "test": "scripts/tests/test_words_carry.py"},
    {"id": "WV-carry-form", "kind": "operation", "file": "waiver.py",
     "function": "main", "guarantor": "does not combine",
     "refuses": "`--carry-from` together with any other form (`--stage`, `--block`, `--revoke`, `--remark`, `--gate`, `--requirement`, `--decision`, "
               "`--text`, `--words-file`, `--list`, `--json`), `--carry-from-root` without `--carry-from`, or either without `--task`: the words "
               "are the earlier story's, so a words option riding along would be lost silently",
     "override": "`waiver.py --carry-from <old key> [--carry-from-root <folder>] --task <new key>` alone; a new word of the person is recorded "
     "by its own form",
     "test": "scripts/tests/test_words_carry.py"},
    {"id": "SD-stage-close", "kind": "operation", "file": "stage_done.py",
     "function": "run", "guarantor": "split_overridden",
     "refuses": "closing a stage whose exit checks still fail — the S1 source inventory, and "
               "lowering a stage the controller has already accepted",
     "override": WAIVER + " — `stage_done` splits its errors the same way and prints what the "
     "person passed instead of swallowing it.",
     "test": "scripts/tests/test_stages.py, scripts/tests/test_source_stage_integration.py"},
    {"id": "SD-managed-stage", "kind": "operation", "file": "stage_done.py",
     "function": "run", "guarantor": "split_overridden",
     "refuses": "`--status done` on a controller-managed task whose controller stage is not "
               "`completed`. The one it stopped dead was S0: no role runs preflight, so there "
               "is no dispatch to accept, and initializing the controller before closing S0 "
               "left the story unable to close it at all (0.7.7 review, finding A-F1)",
     "override": WAIVER + " with the block text `no accepted controller stage`; the refusal "
     "itself now names the remedy first — close S0 BEFORE `--operation initialize`, or record "
     "a `code_only` receipt for it — because the defect is the factory's ordering, never the "
     "person's to repair.",
     "test": "scripts/tests/test_s0_close_order.py"},
    {"id": "ON-close-first-reader", "kind": "operation", "file": "onboarding_notes.py",
     "function": "cmd_close", "guarantor": "onboarding_first_reader",
     "refuses": "`onboarding_notes.py close` while the config's first reader is not satisfied (OH3-29): `readiness.py` could not finish, a "
                "profile has no command that runs one test, `profiles` is empty or not a list, or the config is missing or not a JSON object. "
                "Not scanned line by line (the file is outside the hook scripts): registered here so the refusal has an owner",
     "override": "each problem line carries its own door: repair the profile and close again; or record the gap with the command in the line "
                 "(`project_decisions.py add` on the profile's own `field_refs` after a person was asked, `add-finding` with "
                 "`launch-<id>`, `no-test-framework` or `first-reader-crash` when nobody was); a config that is missing or not an object "
                 "is repaired, no record passes it",
     "test": "scripts/tests/test_onboarding_first_reader.py"},
]


def _key_text(node: ast.AST) -> str | None:
    """The scanner's key for one refusal: the source text of what it refuses WITH.

    Not the line number — every edit above it would move the entry — and not the rendered
    message, because half of them are f-strings the scanner cannot fill in."""
    args = getattr(node, "args", None)
    if not args:
        return None
    try:
        text = ast.unparse(args[0])
    except Exception:
        return None
    # Drop the string prefix and the opening quotes: which quote `ast.unparse` picks depends
    # on what the message happens to contain, so keying on them would make an entry go stale
    # the day someone adds an apostrophe.
    text = QUOTE_HEAD_RE.sub("", " ".join(text.split()))
    return text[:KEY_CHARS]


def _refusal_calls(tree: ast.AST) -> list:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in REFUSAL_CALLS:
            out.append(node)
        elif isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) \
                and isinstance(node.exc.func, ast.Name) and node.exc.func.id in REFUSAL_RAISES:
            out.append(node.exc)
    return out


def sites(plugin_root: Path | None = None, files=None) -> list:
    """Every refusal the scanner sees in SCANNED, as {file, function, call, line}.

    `files` (names relative to scripts/) widens or narrows the scan for a caller that needs
    the same scanner over another file set (the judgment census, t-1765); without it the
    scan is SCANNED, exactly as audit A24 reads it."""
    root = Path(plugin_root or PLUGIN_ROOT) / "scripts"
    found = []
    for name in (SCANNED if files is None else files):
        path = root / name
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        owner: dict = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for child in ast.walk(node):
                    owner.setdefault(id(child), node.name)
        for call in _refusal_calls(tree):
            key = _key_text(call)
            if key is None:
                continue
            found.append({"file": name, "function": owner.get(id(call), "<module>"),
                          "call": key, "line": getattr(call, "lineno", 0)})
    return sorted(found, key=lambda s: (s["file"], s["line"]))


def _covers(entry: dict, site: dict) -> bool:
    return (entry["file"] == site["file"] and entry["function"] == site["function"]
            and site["call"].startswith(str(entry["call"])))


def is_fail_closed(entry: dict) -> bool:
    """A refusal that blocks BECAUSE a check did not run, as opposed to one whose answer is
    simply not the person's to give. The flag is explicit; the phrase is the safety net for
    an entry added without it."""
    return bool(entry.get("fail_closed")) or "fail-closed" in str(
        entry.get("unpassable_because") or "")


def escalations() -> list:
    """The fail-closed refusals and how each stops being repeated."""
    return [e for e in REGISTRY if is_fail_closed(e)]


def findings(plugin_root: Path | None = None) -> list:
    """A24's violations: a refusal with no entry, an entry pointing at a refusal that is gone,
    an entry with no test named, and a fail-closed refusal with neither a pass nor an
    escalation. A missing override is NOT a violation on its own — see the docstring."""
    root = Path(plugin_root or PLUGIN_ROOT)
    scanned = sites(root)
    line_entries = [e for e in REGISTRY if e.get("kind") != "operation"]
    errors = []
    for site in scanned:
        if not any(_covers(e, site) for e in line_entries):
            errors.append(f"{site['file']}:{site['line']} ({site['function']}): the refusal "
                          f"`{site['call'][:60]}` is not in refusal_registry.REGISTRY — say what "
                          "it refuses, how a person's recorded word passes it (or why nothing "
                          "can), and the test that proves it")
    for entry in REGISTRY:
        if not str(entry.get("test") or "").strip():
            errors.append(f"{entry['id']}: registered with no test — the principle is proven by "
                          "a test, or it is prose again")
        # a refusal closed to a person's word BECAUSE a check did not run must have a
        # way to stop repeating itself. Without one, a defect in the guard freezes the story
        # and the person's word cannot move it either — the same dead end, one level down.
        if is_fail_closed(entry) and not str(entry.get("override") or "").strip():
            try:
                after = int(entry.get("escalates_after") or 0)
            except (TypeError, ValueError):
                after = 0
            if after < 2:
                errors.append(f"{entry['id']}: fail-closed with no way through and no "
                              "`escalates_after` — say after how many in a row it becomes a "
                              "diagnosis owned by the factory")
            elif not str(entry.get("escalation") or "").strip():
                errors.append(f"{entry['id']}: `escalates_after` with no `escalation` — name "
                              "what the factory does instead of repeating the refusal")
        if entry.get("kind") == "operation":
            path = root / "scripts" / entry["file"]
            guarantor = str(entry.get("guarantor") or "")
            if not path.is_file():
                errors.append(f"{entry['id']}: {entry['file']} is gone")
            elif guarantor and guarantor not in path.read_text(encoding="utf-8", errors="replace"):
                errors.append(f"{entry['id']}: {entry['file']} no longer carries "
                              f"`{guarantor}` — the way a person's word reaches this operation "
                              "was removed or renamed")
        elif not any(_covers(entry, s) for s in scanned):
            errors.append(f"{entry['id']}: nothing in {entry['file']}:{entry['function']} "
                          f"refuses with `{str(entry['call'])[:60]}` any more — the entry is stale")
    return errors


def unpassable() -> list:
    """The refusals a person's word cannot pass, with the reason. Reported, never hidden."""
    return [e for e in REGISTRY if not str(e.get("override") or "").strip()]


def report(check: str, errors: list) -> None:
    if errors:
        print(f"{check}: VIOLATIONS ({len(errors)})  owner: factory — nothing wanted from you")
        for e in errors:
            print(f"  - {e}")
    else:
        print(f"{check}: no violations")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="the factory's refusals and how a person's word passes them")
    ap.add_argument("--check", action="store_true", help="audit A24 (exit 1 on a finding)")
    ap.add_argument("--sites", action="store_true", help="what the scanner sees — for a new entry")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args()
    from contract import force_utf8
    force_utf8()

    if ns.sites:
        found = sites()
        print(json.dumps(found, indent=2, ensure_ascii=False) if ns.json else
              "\n".join(f"{s['file']}:{s['line']}  {s['function']}  {s['call']}" for s in found))
        sys.exit(0)
    if ns.check:
        errors = findings()
        if ns.json:
            print(json.dumps({"findings": errors,
                              "unpassable": [e["id"] for e in unpassable()]},
                             indent=2, ensure_ascii=False))
        else:
            report("A24 refusal registry", errors)
            blocked = unpassable()
            if blocked:
                print(f"  {len(blocked)} refusal(s) a person's word cannot pass, by design:")
                for e in blocked:
                    mark = (f" [escalates after {e['escalates_after']}]"
                            if is_fail_closed(e) and e.get("escalates_after") else "")
                    print(f"    {e['id']}: {e['refuses']}{mark}")
        sys.exit(1 if errors else 0)
    if ns.json:
        print(json.dumps(REGISTRY, indent=2, ensure_ascii=False))
        sys.exit(0)
    for entry in REGISTRY:
        print(f"{entry['id']}  {entry['file']}:{entry['function']}")
        print(f"  refuses : {entry['refuses']}")
        print("  passed  : " + (entry.get("override") or
                                "NOTHING — " + str(entry.get("unpassable_because") or "")))
        if entry.get("escalation"):
            print(f"  after {entry.get('escalates_after')}: {entry['escalation']}")
        print(f"  proven  : {entry['test']}")
    sys.exit(0)


if __name__ == "__main__":
    main()
