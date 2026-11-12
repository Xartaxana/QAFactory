# Rules for building the factory

Every change to this factory must satisfy every rule in this file: a one-line fix, a new check, a
new refusal, a new field in a contract, a new question, a new measurement. This file is not for the
`qa-*` roles — it is for whoever changes the factory. Read it before the change and again before
calling it done. A change that breaks a rule here is not finished, however green the tests are.

**In a review**, answer each rule with a fact: which line satisfies it, or why it does not apply.
The `Check` line says what to look at. If a rule cannot be satisfied, say so in the change's own
words; never reword the rule.

**Adding a rule**: append the next free id to the section it belongs to, never renumber, never
delete — ids are cited from commits and plans. Every rule carries the failure that produced it, with
its measurement: a rule with no measured failure behind it is an opinion, and an agent cannot weigh
an opinion against the work in front of it. Keep the rule one imperative sentence.

This file lives in `design/` because nothing loads it (FR-44), so it is not capped and stays one
checklist. It is split only when a reader would want it split, and then the parts are listed here.

| Section | Rules |
|---|---|
| A. Refusals and doors | FR-1, FR-2, FR-3, FR-4, FR-5, FR-46, FR-48, FR-50, FR-57 |
| B. Text shown to a person | FR-6, FR-7, FR-8, FR-9, FR-10 |
| C. Contracts between code and roles | FR-11, FR-12, FR-13, FR-14, FR-15, FR-38, FR-39, FR-42, FR-49, FR-56 |
| D. Identity and evidence | FR-16, FR-17, FR-18, FR-40, FR-58, FR-59 |
| E. Delivery and reporting | FR-19, FR-20, FR-21, FR-22, FR-23, FR-35, FR-36, FR-37, FR-53 |
| F. Measurement and money | FR-24, FR-25, FR-26, FR-27, FR-28, FR-41, FR-51, FR-55 |
| G. Writing factory code | FR-29, FR-30, FR-31, FR-32, FR-33, FR-34, FR-43, FR-44, FR-45, FR-47, FR-52, FR-54 |

## A. Refusals and doors

**FR-1 — A refusal says what is wrong, what it expected, and how to satisfy it.** Any refusal — from
a script, a hook, a role, a gate, the controller — names the thing refused, what it expected instead,
and the command or field that produces it. "Refused", "invalid", "not allowed" alone is a dead end.
*Why:* refusals naming only the problem sent roles searching; once `role_cli.refuse()` printed what
to write and how to prove it from `role-commands.json`, roles stopped guessing. *Check:* read it as
the party receiving it — can they act without opening a script?

**FR-2 — The door a refusal names must be one the refused party can use.** A role's refusal names a
command that role may run; the orchestrator's names an orchestrator operation. The wrong party's door
looks like an answer and ends in a halt. A refusal never names a path or tool the refused party
cannot reach, and never leaves it without a move. *Why:* an S5 refusal told a role to record a person's
waiver, which only the orchestrator may do; the role halted correctly and a dispatch plus a conductor
call were spent; on 29.09 108 controller blocks still named a door no test had ever opened.
*Check:* the command appears in the receiving party's own permitted set, and a test opens it.

**FR-3 — A reason owned by the factory is reported to a person, never put to them as a choice.**
Nothing is asked of a person for our own defects; they are told, in a section that says so.
*Why:* the gate-B handoff contract says this, and a run still put 43 of its own bookkeeping lines to
the person under "what blocks delivery on the product side". *Check:* every reason reaching a person
carries an owner; only `product`, `person` and `environment` are phrased as decisions.

**FR-4 — A check stops a silent pass, never an informed one.** A person's word passes any block, and
the pass records the block, the words and who said them; when the block was the factory's own, the
pass is also filed as a factory finding in the person's words. *Why:* standing rule — gates, waivers
and `stage_overrides[]` exist to tell an informed pass from an absent check; on the driver, S0
promised "answer `go on`" and never read the answer, so the same block met the person again.
*Check:* the new check has a recorded route through it, that route writes down what it passed, and
a pass over a factory-owned block reaches `factory-backlog.md`.

**FR-5 — A stage may not require, to close, an artifact nothing in the factory can produce.** Some
command builds it, and the refusal names that command. *Why:* S5 completion demanded a window
acceptance record no person's word could create and no allowed command produced: three answers and a
halt before the gate learned to read a person's word like every other check. *Check:* for each new
completion requirement, name the command that produces it and the words that pass it.

**FR-46 — The class of a refusal says whose fault it is: the call's, or the story's.** A
malformed request and a story that is not ready are different answers and take different routes.
*Why:* the S5 completion gate raised `ValueError` - the class the controller uses for a request
built wrong - for a block about the story's own evidence, and that is how it ended up with no
route for a person's word at all; the walk of all 188 blocks
(`design/controller-blocks.md`) found the same class confusion nowhere else, because everything
else was already right. *Check:* a block about recorded state raises the state class; a block
about the request raises the request class, and the walk's route column agrees with it.

**FR-48 — The conductor is called for a problem, never to run a command, and settles the problem
itself before it asks a person.** Routine commands run from code, triggered by a stage transition or
by a question appearing; the conductor gets the problem, the evidence and the doors. Before any
question to a person the conductor investigates the problem itself: it reads what the code left
(records, logs, notes, the refusal's evidence) and resolves what it can. What the code recorded (a
cause, a verdict, a refusal) is evidence for the investigation, never the text of the question. A
person is asked only what only a person can know or decide - a class of
`references/person-owned.json` - and the question carries that class and what was read.
*Why:* before the driver the orchestrating model was 47.7 % of a story's cost (TP2-2553); on
the driver the conductor still held 76 sessions in one run, 21 of them ($9.01) spent parsing a
person's words, and 16 of 25 `ask_person` carried an empty question. On LOCAL-1 (02.11.2026) two
questions reached the person whose answers lay in the factory's own records: whether the probe tool
reads TypeScript, while the probe record showed the failure at the mutated line, and the UI address
of a stand the factory had just logged into. *Check:* every conductor call site names the problem
that triggered it; nothing the conductor does could be a fixed command; the driver refuses once a
conductor question without a class or without what was read (`no_move.validate_options`); a phase
line that tells the orchestrator to ask a person in reaction to a recorded state carries
`person-owned: <id>` (`test_conductor_investigates_first.py` K3/K4); the interactive road's
`waiver.py` word without a class is recorded and counted, not refused - that road holds on
discipline, and its detector is calibration check 38 (`person_owned.py --share`,
`words.unclassified`).

**FR-50 — Whatever the work needs from outside is tried by every route before a person is asked,
and then the person gets three answers.** For a READ: the tracker's API in a light form, SSH or
git for a repository, a browser where an API is closed — then the person: *not needed*, *here is
how to get it*, *here it is as text*. An LLM agent is NOT a read route: it compresses what it
returns and drops sections, attachments and comments without saying so; it is used only for WRITES,
and only where the project does its tracker writes that way (owner, 01.10, D-06). Text a person
pastes is a legitimate input for the story; it does not prove a fix to the route (FR-33). *Why:*
S1 of TP2-2553 took 2 h 54 min and about $12 because the Jira tool belonged to the
orchestrator's session, not the scout's process; the route ladder (API, local checkout, person
with three options) was added on 26.09 after the same class of failure; on TP1-15045 (01.10)
the REST read found 0 of 15 acceptance criteria because the code knew one heading and the ticket
used another, the road led to the tracker agent, the agent was not registered on the machine, and
the story stood on a text a person typed from the ticket (312 B of description, no attachments)
while one REST call carried the whole ticket — the agent is one more session, one more
compression and one more thing to be absent, where the API is one call. *Check:* the
refusal lists each route tried and why it failed; the question to the person offers the three
answers; no read path calls an agent (`grep ticket_by_agent` finds nothing; the snapshot's
provenance says `fetched` or `person_pasted`, never an agent).

**FR-57 — A ban is never bypassed, and never a dead end.** It holds regardless of state — no
exemption because the file already exists or a step already ran — and it is never passed by a
workaround: a heredoc, a helper script, another tool. Every ban names its door: the command that
does the legitimate version of the refused act, and the person's word, which the ban accepts and
records (FR-4). Where the role can judge, the door is the role's, not a question: an interrupted
artifact is continued by default — the role keeps the rows that parse, validate and were built on
the same inputs, repairs the stale ones, and sets the rest aside as `.superseded` only when
nothing is usable. A role that cannot judge and has no door files a finding and asks; it neither
stops silently nor works around. *Why:* roles worked around refusals with self-written scripts and
Python heredocs, and the pre-tool guard refused the same unparseable input twice in a row with no
finding filed (FB-6); on TP1-13877 a write interrupted by a network failure left
`test-plan.json` with 3 rows, the guard refused a write over it, and the only way on was a person
deleting the file by hand — a ban with no door. *Check:* for each ban, name its door and the words
that pass it; run the ban on an interrupted artifact — the role continues without asking a person,
and a person's "delete it and start again" still reaches a command that executes it.

## B. Text shown to a person

**FR-6 — Every text a person reads obeys `human-questions.md`.** Gate questions, the driver's
boundary questions, a role's halt, the report's "Factory defects" section, the closing S9 question.
*Why:* the rules used to live in the head of whoever wrote each question, so they held at one
boundary and failed at the next; two measured failures are recorded in that file. On TP1-13877
all six questions the driver recorded passed the text check with no problem found, among them a
login error and a Cloudflare HTML page relayed as-is: the check read the form, not the reader.
*Check:* the five required parts are present, and no filler stands where a question belongs; it
applies to every text a person reads, including a role's halt and a refusal the conductor relays,
and outgoing text is checked by code for form-field names, plugin paths, dispatch ids and internal
row ids in its body (a presence check, which FR-12 allows).

**FR-7 — A boundary a person has answered is never re-asked with the same text.** It either moves or
comes back changed, naming what the answer did not settle. *Why:* one `resolve_return` packet reached
the person three times unchanged because nothing filed the answer against the dispatch the refusal
named; later the same run asked "do you want to reopen this story?" twice with the reason already on
disk. *Check:* the answer path changes what `where` returns, or the question states what is missing.

**FR-8 — The person's words are carried to whatever can act on them.** Recording an answer is not
routing it. If the words are the only thing that can lift the block, they reach the executor the
refusal names, in full. *Why:* four conductor sessions journalled `"words": false` while 1,900
characters of the answer sat on disk, swallowed by a branch that logged them because the question's
stage was already `done` — $0.45 and two duplicate questions. *Check:* follow the answer from the
file to the command that consumes it, and name that command.

**FR-9 — Everything a person decides at a gate has an executor, and the decision is kept whole.** A
gate is a decision before the last stage, not the last stage. *Why:* a story closed on "gate B is
decided and S8 is done" while its own record said `retro_pending: true` — the bug proposal the gate
ordered and the full retro both had no executor; and `authorization_source` once kept 215 characters
of a decision whose readings lived only in stage overrides. *Check:* list what the decision can
order, and point at the step that performs each item.

**FR-10 — One packet shown to a person does not contradict itself.** Sections that can disagree are
computed from one source. *Why:* a gate-B packet opened with "Bugs found — none, so there is nothing
to file" and three screens down carried the report's own "its bug proposal is unfiled": the role knew
about the debt, the code did not, because it counted bugs only from failing tests. *Check:* the two
sections that could disagree read the same field.

## C. Contracts between code and roles

**FR-11 — If a contract requires a field from a role, the tool that role is told to use must be able
to produce it** — otherwise the field is not required. *Why:* nine instances stood
`not_verified:missing_sensitivity_proof` because the typed receipt comes from `red_sandbox.py
--probe` while the code critic is permitted `probe_by_code.py`, which does not produce it; that gap
alone held `delivery_ready: no` on a run where every case was green. *Check:* for each required
field, name the command in the role's own permitted set that emits it.

**FR-12 — A detector never reads a person's or a role's wording by a phrase list.** Code triggers on
the presence of words, a field or a state; what words mean is judged by the role that owns the
subject, or the conductor. *Why:* whether a person had ordered a bug was decided by
`re.search(r"bug draft|author the bug")` over their prose — an order the gate itself had asked for
was dropped in silence because it was phrased differently, and in another language it could not match
at all; the second alternative had never matched anything, its `\b` eaten into a literal 0x08 byte.
*Check:* the trigger reads a field or the presence of words; the meaning is decided by a role.

**FR-13 — Closed variety lives in data files, never in code; open variety is judged by a role.**
Vocabularies, phrasings, tool and rate tables are data; code reads them. Anything a new project can
bring — layouts, id formats, phrasings, sources, test frameworks — is judged by a role: code reports
what it found and does not decide. *Why:* standing design rule, and FR-12 is what breaks when it is
ignored; a table fails on a value it does not hold exactly as a list in code does — the contract
knows case ids only as `TC-\d+`, the project's strategy writes `TP1-13877_TC_001`, and on
TP1-13877 the automator spent about 35 calls reading factory code before it halted; the
automation layer knows only pytest markers. *Check:* the change adds no list of alternatives to a
source file that a data file could hold; and for every table, can a project bring a value it does
not hold? Then the table is a hint to a role, not a decision.

**FR-14 — A script's output shape is as much a contract as its arguments.** If a caller parses
stdout, nothing else goes to stdout. *Why:* `probe_by_code.py` printed one `binding: ...` line after
its JSON; `json.loads(stdout)` broke and every parsed field silently became `None`. *Check:* run the
script and parse its output the way its caller does.

**FR-15 — A path a role needs is given to it, not searched for.** *Why:* 11 `Read` misses in one run,
and the whole-file reads that follow a miss are the largest single line in a role's context budget.
*Check:* every path the work requires appears in `known_paths` or in the dispatch's own lines.

**FR-38 — A check that will judge a role's output states its requirement to the role before
the work, in the fields the role must fill.** *Why:* the detectors' rule for `verification_depth: low`
lived only in code; once the strategist's card named the required fields up front, S3 closed on the
first dispatch — 51 turns and $2.53, against 176 turns and $12.83 over four attempts without it.
*Check:* for each new check on a role's artifact, name where the role is told its requirement before
working.

**FR-39 — What the rules say a party may do, the guard permits.** *Why:*
`guard_pre_tool.py` refused writes to the `references` directory that the rules name as the one place
open to a role, because its allow-list compared a prefix without the separator. *Check:* for each
permission stated in a reference, a test exercises the guard on that exact path.

**FR-42 — For every state the other side can return, this side has a move or a refusal that
names who acts.** *Why:* `resolve_return` had no move at all and `closed` had no branch; each ended as
"the driver has no move for X" and became a question to a person, while the controller was already
naming the answer in both cases. *Check:* enumerate the other side's states from its own source and
match each to a branch. For the driver this is the owner's principle P22: a state the code has no move for goes
through the one seam `Driver.no_move`. `python -B scripts/audit_factory.py --no-move` (audit A27, run by
`scripts/tests/test_audit_rules.py`) finds three things outside the seam: a `Person` or `Stop` built there, a call of a
function that returns one, and a factory script run whose result is dropped or only printed. A site that stays carries
`# remains: <reason>` on its statement's first line or on the comment-only line above it. Today's sites are a shrink-only
baseline listed in `factory-rules-debt.md`.

**FR-49 — What a stage gathers travels in its handoff, whole.** The next stage never gathers it
again, and nothing collected is dropped between contracts; material nobody downstream reads is not
gathered. *Why:* a probe overwrote `source-inventory` and the person's words were lost; the ticket
snapshot written as `ticket-snapshot.md` never reached the scout's brief, which reads `.json`; four
merge requests with 17, 101 and 80 discussions were gathered on TP1-13797 and cited nowhere.
*Check:* for each field the change produces, name its reader downstream — or declare it terminal.

**FR-56 — A role is given only the tools its work needs.** *Why:* one tool schema is about 10K
tokens of every turn's context; the scout's fixed prompt is 36.7K tokens with Bash and about 25K
without, of which our own text is 7.1K. *Check:* every tool in a role's definition is named by a
step of its phase instructions.

## D. Identity and evidence

**FR-16 — An identifier is resolved through the tool that produces it, at the moment it is stored** —
not when it is read, and never from the author's spelling. *Why:* the manifest held the author's
`[malformed]` while pytest collected `[malformed-$[?(unterminated-True]`: 15 of 27 run rows never
joined, 16 obligations read "not proven" against a fully green execution, and the mismatch surfaced
only at S8, after the review window was accepted and the roles released. *Check:* the id is written
after a call to the tool that enumerates it.

**FR-17 — A tool that exists for a problem is wired everywhere that problem occurs.** A helper wired
into three of four sites has not been adopted. *Why:* `node_ids.py` was written for exactly the
mismatch in FR-16 after it burned a probe sandbox and two critic dispatches on another story — and
was wired into the runner, the sandbox and the probe, but not the manifest, which is where FR-16 then
happened. *Check:* grep for the problem, not for the helper, and list every site that has it.

**FR-18 — Evidence of execution is not evidence of coverage.** A green run says what was built, not
what was promised; "covered" is never written where "ran and passed" is meant. *Why:* ten of ten
cases green while the story's own AC7 was undelivered, and the report had to say so in prose because
no field did. *Check:* the new field's name says which of the two it carries.

**FR-40 — Every state the factory can record has a sanctioned way out.** *Why:* a row
entered `tests[]` and could leave only once every case it proved had moved to `unresolved[]`, so a
stale instance of an otherwise good case survived forever and the only route left was a waiver on a
defect. `manifest_put.py --fragment {retracted_instances}` is the door: a live role then retracted 8
rows and the manifest matched collection, 9 = 9. *Check:* name the command that reverses the state the
change introduces.

**FR-58 — Code is never an oracle.** An expected value comes from a requirement of any source — the
description, an acceptance criterion, a comment, an attachment, a linked ticket, a spec, a precedent a person confirmed — never from the implementation under test: a
test whose expectation was read out of the code can only pass. Where the requirements are silent,
the question goes to a person with *how it was before* the change and *how it is now*; until the
answer the expectation stays `unresolved` (reason `expectation_unconfirmed`), never a literal, and
a run that ends with it open reports a GAP (expectation unconfirmed, check not executed), neither
green nor red. A requirement derived only from a diff is a statement about behaviour that a
person confirms or rejects, and a before/now difference is always shown to the person ("is the
change intended?"). *Why:* on TP1-15045 (cmp2, 01.10) TC_015 expected a 403 that came from
nobody's requirement, and R-17 took its 403 from the implementation diff where the behaviour
before the refactoring was 400 — both tests could only agree with the code they were meant to
judge (owner, P20). *Check:* every Then of a case names its oracle (`then_oracles`: `requirement` (older name `ac`) / `spec`
/ `precedent` / `person` / `unknown` with its question), the plan's `oracle` and the case `basis` never name an
implementation-only requirement, an `unknown` Then binds as `unresolved: expectation_unconfirmed`
with the observed value and never asserts it, and the report carries the open ones under "Left
with you"; dated by `contract.ORACLE_CUTOFF` (cases created from 2026-10-02 on), earlier cases are
`legacy`.

**FR-59 — A gate does not decide on an unknown: it names what it could not establish and asks
whoever can know — or takes the safe default it declares, never a pass.** Every gate that judges
whether a run, a test, a stand or a proof is valid records the facts it read and where and how it
read them, records what it could not read and what it tried, and decides by a policy kept in data —
the project's registry, grown by the answers of the person and the roles. An unknown becomes a
question with closed answers to whoever can know: the person for the world and for intent, a role
for its own artifact; where nobody can answer, it becomes the gate's declared safe default (run
again, report a gap, refuse with a door). A person's word is a verdict of its own,
`person_confirmed`: bound to the facts it was given for, never shown as `matched`, void once they
move; a proven contradiction about the world the run uses is a question too. *Why:* 13 "false pass
/ gate lets through" findings in F08 + F11 (`plans/feature-fragility-2026-10-02.md`, table B rows
F08 and F11: 5 + 8); automation on uitest was `env_blocked` because code required `matched`
(B-257); the week's only escalation, t-023, was rejected three times over what "the same test"
means. *Check:* `python -B scripts/gate_registry.py --check` (audit A26, `references/gate-registry.json`):
every comparison of a verdict word in the package sits in a registered gate whose row names its
unknown branch; a row whose branch is `pass` fails; a gate not yet converted is a `debt` row naming
its backlog id, and the debt rows are listed in `factory-rules-debt.md`.

## E. Delivery and reporting

**FR-19 — Every blocking reason names its owner, and an unrecognised reason is a defect of the
classifier.** The default owner may not be `product`; a new reason family joins the owner vocabulary
in the same change. *Why:* of 76 blocking reasons 52 were labelled `product`, and 43 of those were
our own bookkeeping — 28 missing sensitivity receipts, 15 unjoined test names. `reason_owner()`
exists for this and simply did not know the two new phrasings. *Check:* the new reason text resolves
to a non-default owner, added to the vocabulary and not to a list of exceptions.

**FR-20 — The reason a delivery is not ready is stated in the task's own terms, first.** Our
bookkeeping goes in its own section below, marked as ours. *Why:* the one true reason — the filter
cannot be configured from the UI, so the ticket's AC7 is undelivered — was absent from the machine's
list entirely and reached the person last, in a role's prose. *Check:* the first blocking reason
names a requirement, a behaviour or a user, not a receipt.

**FR-21 — A skip because the product lacks what a requirement demands blocks delivery.** A
skip by our own decision does not. The two never share one word. *Why:* `TS-12` — P1,
`blocked-flow`, the UI half of AC7 — stood `skipped`, and `skipped` blocks nothing; three rows
skipped by deliberate decision carried the same word, so the verdict could not tell them apart.
*Check:* the skip vocabulary distinguishes the two, and the blocking set contains the second; the
third verdict, `after_checks` (ready once the person finishes the checks left with them), is never
reached while a failure or a product gap stands — `references/delivery-verdict-kinds.json` maps both
to `no`, and a kind the file does not hold is `no`.

**FR-22 — A discrepancy with a requirement has a road to a bug even when no test can fail.** *Why:*
AC7 was found at S2 and decided by a person at gate A with an explicit order to file a local
proposal; nothing filed one, because the only road ran S7 triage → S8 reporter and S7 had no
failures. The report itself had to say "its bug proposal is unfiled". *Check:* name the path from
"requirement unmet, no test possible" to a file under `bugs/`.

**FR-23 — Every step has a recordable completed state for the null outcome.** "Nothing goes out",
"nothing to file", "no failures to triage" are results. *Why:* the delivery step knows a branch,
commits, a push and a Draft MR; when the gate's decision forbade all four it could only stop and ask
— correctly, but there was nothing to ask. S7 by contrast closed itself by code with "no failures —
nothing to triage". *Check:* the step's states include the empty one, recorded, not escalated.

**FR-35 — A report never changes the meaning of a role's own verdict.** Each distinct verdict
keeps its own word. *Why:* the critic's 19 instances carried 11 `approved`, 5 `unverified` and 3
`rejected`; the ledger mapped every non-approved verdict to `review_rejected`, so the person read 8
rejections where the critic had rejected 3 and said "could not verify" about 5 — rejected work is
redone, unverified work is reviewed, and the cost is not the same. *Check:* each distinct source
verdict maps to its own reported state.

**FR-36 — A capability the run's standing decision forbids is neither probed nor advertised.**
*Why:* in a run whose standing rule was "never write to the tracker", the conductor spent a dispatch
asking the Jira agent for write permission and recorded `tracker_write: confirmed`; the gate-B packet
then opened with "Filing — channel `jira` … tracker write: confirmed", an invitation to do the
forbidden thing. *Check:* the probe reads the standing decision first, and the packet says the channel
is closed by the person's word instead of confirming it.

**FR-37 — Every path named in text a person or a role reads is the path the code writes.**
*Why:* gate A ordered a bug proposal "under `qa-factory/bugs`" while the factory's home for it is the
task root's `bugs/`; the role filed it correctly, and its own dedup note then read "`qa-factory/bugs/`
does not exist yet, so this is the first bug filed under it" — about a directory the bug is not in.
*Check:* the path in the text resolves through `runtime_paths.py`, not by hand.

**FR-53 — A comparison run leaves no trace in the project.** No merge request, no tracker comment
or subtask; bugs go to a Markdown file or the chat; the run works on a copy. *Why:* in a run whose
standing rule was "never write to the tracker", the conductor spent a dispatch asking for write
permission and the gate packet advertised "tracker write: confirmed" (FR-36). *Check:* the
experiment's `external_writes` is closed, and the run's record of outward writes is empty.

## F. Measurement and money

**FR-24 — A story's spend is the sessions its own journal names**, not every session that mentions
the ticket; a roll-up that cannot name its sessions says so instead of publishing a number. *Why:* a
retro opened with "Story spend: $1,911.43" against $128.57 in the driver's journal, because the
operator's own session — reading artifacts, measuring, fixing the factory on the same ticket — held
a `by_task` entry worth $1,804.55, and `by_role` named the operator's agent types with not one `qa-*`
role. *Check:* the session list comes from a record of what the factory launched.

**FR-25 — When two records of the same quantity disagree, the report names the authoritative one and
prints the gap.** Both may be legitimate; publishing one without saying which is not. *Why:* the
driver journal records what the CLI charged, the cost files price the transcript against a rate table
and mark themselves `provisional` / `tariff_confirmation: unconfirmed`; for one role session they
read $3.01 and $4.44. *Check:* the report states the method behind each figure.

**FR-26 — A measurement is not a finding until the raw evidence is read.** A count of refusals is not
a count of defects. *Why:* every count that was checked shrank — 43 automator rewrites to 3, 16
scout `usage` reads to 8, 5 `run_suite` crashes to 0, 11 `telemetry_hook` failures to 0, 19 plugin
reads to 6, 22 `Read` failures to 11. *Check:* the claim quotes an example from the raw record.

**FR-27 — A cache belongs to the run it measured, and a report says out loud when it used one.**
*Why:* `report_run.py --left-cache` defaulted to a cached measurement of `judge-off` and applied to
whatever `--left` named, so every comparison silently printed `judge-off` on the left: "driver2 $109.00
vs driver3 $128.53", where driver2 had cost $62.08. *Check:* the cache is keyed by its run, and the
output names it.

**FR-28 — A measurer is code and gets a test like any other code.** *Why:* three of one run's wrong
numbers came from our own measurers (FR-24, FR-26, FR-27), and two of the three were found by
accident rather than by a test. *Check:* the measurement change ships with a case that fails without
it.

**FR-41 — An unknown is never reported as a fact.** A measure with no evidence says
`unknown`, and the report prints that word. *Why:* `dispatch_liveness` has three kinds of evidence and
a driver run produces none of them, so every verdict was `unknown` and every verdict was reported as
"alive"; five of the first nine questions put to a person were "confirm this dispatch is dead".
*Check:* the reporting path has a distinct state for "no evidence", and it is printed.

**FR-51 — Work moved to a deterministic tool is judged by the LLM spend it removes.** The tool's own
cost is reported, not optimised. *Why:* standing design rule; on judge-on the tool cost $0.011 for 855
records while the story rose by $11, all of it on the model side — the only number that decides is
the model's. *Check:* the change reports the LLM spend of the affected stage before and after.

**FR-55 — Friction with our own code is measured on every run, and code that makes a role's stage
dearer than without it is a defect.** A turn is friction when our code returns a traceback, a hook
refusal, an argument-shape error, a validator refusal of our own artifact, or when the role writes
itself a helper script; the turn carries its full context cost. *Why:* S5 of TP1-15045 lost 127
of 1,668 calls (7.6 %) to our own hooks; across run 5 of TP1-13797 friction was 15.5 % of turns,
44.2 % for the code critic; about 40 % of the scout's turns went to finding the form our own
scripts expect. *Check:* the change reports `code_friction` for the affected role on a live run,
before and after.

## G. Writing factory code

**FR-29 — Code bearing escape sequences is never written through a heredoc, and no package file
carries a control byte.** Use an editor tool, or build the escape from `chr(92)`. *Why:* four times
in one run a `\b` was eaten into a literal backspace and a regex silently stopped matching; one of
them — the only road from a person's word to a bug file — had been dead since the day it was written.
*Check:* no file in the package contains 0x07, 0x08, 0x0b or 0x0c, and the regex matches in a test.

**FR-30 — The package is English**, including test fixtures; a person's own words quoted into a
project artifact are not the package. *Why:* `selftest.py --lang` enforces it, and a Russian string
seeded into a test to prove FR-12 broke the build. *Check:* `python selftest.py --lang`.

**FR-31 — A test that fails only under load is a defect of the test.** *Why:* `test_stand_lease.py`
read 37/38 inside the parallel selftest and 38/38 alone, while the machine was running a story; a
test that reports a defect that is not there costs the same attention as one that hides a defect that
is. *Check:* it passes under the parallel runner on a busy machine, or its wait is not wall-clock.

**FR-32 — Every fix goes to the root cause, with a test and a green selftest.** Never a bigger model,
a retry or a wider timeout; extra critic iterations are a missing self-check. *Why:* standing design
rule. *Check:* the change names the cause, carries a case that fails without it, and `selftest.py` is
green.

**FR-33 — A fix is proved by the factory doing the thing, not by a person doing it for the factory.**
Hand-relayed material is not an honest run: if a person pastes what a role should have gathered, the
fix is unproven and the artifact is decoration. *Why:* standing design rule — the fixes of one run
that counted were the five a live role exercised. *Check:* name the dispatch, the role and the
artifact that prove it.

**FR-34 — A red test against a requirement is a bug, not a blocker.** A discrepancy is the goal of
the work, not an obstacle; never re-read the requirement until the test agrees with the product.
*Why:* standing design rule. *Check:* the change cannot by itself turn a requirement discrepancy into
a blocked or waived row.

**FR-43 — A process someone reads while it runs writes line-buffered.** Anything whose log a person
or a watcher follows flushes per line. *Why:* the driver's own log ran up to 40 minutes behind the
run because stdout to a file is block-buffered; twice a stall was diagnosed that was not there, and
the state had to be reconstructed from `controller.json` instead of read. *Check:* the process is
started with `-u` or flushes at every progress line.

**FR-44 — Where a document lives is decided by who loads it.** `references/` is the definition
layer: injected to roles, capped per file because it is somebody's context, and inside the package
fingerprint a dispatch is bound to. A document nothing loads goes to `design/`, uncapped and outside
the fingerprint. *Why:* eighteen documents paid all three prices and earned none — three sat within
100 bytes of the cap (`controller-api.md` 11 997, `codex-scout-reliability-plan.md` 11 994,
`driver.md` 11 899), so the next paragraph anyone wrote would have broken the build over a limit
that protects a role from a file no role receives; and editing a design plan changed the fingerprint
that binds a dispatch, invalidating work already done. The directory is `design/` and not `docs/`
because this package's own `.gitignore` reserves `/docs/` for private planning that is **not** package
content — the first attempt put package content there and `--hygiene` caught it as untracked.
*Check:* `selftest.py --homes` — it holds the boundary in both directions, and the size cap is never
the reason a document is split.

**FR-45 — A validator writes nothing: not into the request, and not onto a copy the projection
rebuilds.** What it needs to record goes to a durable record of its own. *Why:* the record of a
block passed by a person's word was first written onto the projected dispatch, which is rebuilt
from the events and thrown away - so `window_passed_by_person` read empty in every run that used
it. Moving it into the event payload was worse: `event_store.commit` compares the payload of a
repeated idempotency key against the one it stored, so a validator that adds a field turns the
next replay of the SAME request into "idempotency key reused with different inputs" - proven by a
probe before it reached a run. It lives in `state/passed-by-person.jsonl` now. *Check:* replay the
same request with the same idempotency key after the validator ran, and read the record back.

**FR-47 — Code is an instrument a role calls, never a substitute for the role's judgment.** The role
runs the script itself, reads what it reports, and decides what is missing and how to fix it; when
the script meets something it was not built for, it says what it could not do and leaves the role a
move. *Why:* about 40 % of the scout's turns went to matching the form our own scripts expect
instead of understanding the story; the scout wrote 11 helper scripts and hit 12 tracebacks in one
S1; the code critic's friction reached 44.2 %; the driver sent every repair as `test_defect`
although the critic already wrote the real cause (B-007 closed it) — code decided what only the role knew. *Check:*
for every step the change moves into code, name what the role still decides, and run the script on
a project shaped differently from the fixture — it reports, it does not halt.

**FR-52 — The factory's roles run on Sonnet or Terra, never on Haiku; a fix that holds only on a
stronger model is not a fix.** *Why:* standing design rule (owner, 29.09); FR-32 already forbids
fixing by a bigger model, and this rule names the floor it protects. *Check:* the role files bind no
other model; a quality regression is fixed in the role's instructions or the code, not in its model
line.

**FR-54 — A change finds its siblings by the map.** Logic that has a twin in another stage is listed
in the SIBLING_MAP (`docs/SIBLING_MAP.md`, axis 5 — the stage twins) and `design/architecture.md` AR-19 with both sides' files; a change to one side names the other and either
changes it or says why not. *Why:* `node_ids.py` was wired into three of four sites and the fourth
produced FR-16; the repair cause is hard-coded identically at S4, S5 and S7; the "one question for
every stop" symmetry breaks at its edges — S0 ignores the person's word, S9 halts `--until end`.
*Check:* the commit names the axis and each twin site; a new twin joins the map in the same change.
