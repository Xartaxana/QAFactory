# Coverage design

Use this reference in S1–S4 to turn bounded discovery into reviewable coverage obligations.
It defines design evidence; execution results remain in the existing run lifecycle.

<!-- roles: qa-scout -->
## Discovery handoff

Read the S0 requirement snapshot. Required sources are the task, an explicitly named
subject (even when it is not the parent), the immediate parent/feature and its relevant
requirements, normative sources, and relevant development tasks. For each relevant task,
read the description, acceptance criteria, links, every available page of comments, and
the original bytes of every attachment or inline medium. A task type never reduces this set.
Keep separate receipts for relevance assessment and full inspection.

Extract explicitly mentioned tracker links and keys from bodies, requirements, readable
comments, and materials. First read a mentioned ticket's description, acceptance criteria,
links, and quoting mention to assess relevance. It is relevant when it supplies the original
defect or incident, reproduction, expected behaviour, constraint, dependency contract, or
decision history that affects the change. Only then fetch and inspect its full material set,
recursively: materials of a ticket not judged relevant are neither downloaded nor inspected.
`not_relevant` needs a reason from read content; uncertain or inaccessible references remain
`unknown`/`unavailable` gaps. The person reviews every kept and left-out source first. Do not enumerate a parent
portfolio, all siblings, or all children without an explicit relation. Deduplicate by
canonical ref plus revision (canonical ref before revision) with a visited set that prevents
cycles without a depth cap.

Each inventory record carries `source_id`, `canonical_ref`, `relation`, `relevance`,
`relevance_reason`, `assessment_ref`, `discovered_from`, `relation_evidence`, `required`,
`status`, `revision` or `content_hash`, `snapshot_ref`, `fetched_at`, and
`exclusion_or_error`. A required source is `read` or explicitly `unavailable` before S1 is
complete; pending discovery cannot be accepted. An unavailable source blocks S1 until the
person accepts the gap; it then creates an oracle gap for affected requirements, never a
silent exclusion or fully-ready positive verdict. If a
role lacks tracker access, it emits a structured fetch request for the available adapter.

Inventory tests only in changed areas of every declared code/test repository, the current
diff (including developer-added tests), and the configured shared case store/TMS. Preserve
the existing TMS pagination contract. A search is `complete` only for its stated paths and
changed area; reaching a discovery limit makes it `partial`, never `not_found`.
`not_found` is the manifest's top-level `coverage_status`, never the status of one area.
Developer or CI mappings are search hints, not semantic coverage verdicts. A QA marker is
not required. Record candidate selectors, parameter IDs, assertion locations, tentative
requirement links, origin, and any possible result receipts without modifying the test.

<!-- roles: qa-requirements-tester, qa-test-strategist, qa-case-designer, qa-case-critic -->
## Coverage obligations

### The obligation record

Each v2 plan row retains its existing stable row ID and adds `schema_version: 2` and
`coverage_obligations[]`. One obligation is one observable assertion, though one test may
prove several obligations and several tests may jointly prove one obligation. Each entry
contains: `obligation_id`; `requirement_refs[]` as `{ref, revision}`; `behavior`;
`oracle_source_ref`; `oracle_status: resolved | unresolved`;
`applicable_scenarios[]` with selected positive/negative/boundary/state/interaction
variants and rationale; `observation_boundary`; mandatory `completion_condition`;
`coverage_links[]` with candidate/test ref, assertion refs, `proves[]`,
`does_not_prove[]`, assessment and reason; decision; remaining gap; planned check refs;
`execution_scope: current_task | recommended_regression`; and sufficiency-review author
dispatch, input hash, rationale, plus reviewer receipt when independent review is required.
New checks may use a planned assertion contract at Gate A; S5 later attaches real assertion
refs without changing the approved oracle. Candidate metadata comes from the context bundle:
kind (`test`, `suite`, or `helper`), repository/revision/path/selector, assertion ranges,
observation boundary, mocks, `proves`, and `does_not_prove`. Keep production locations only
in `implementation_refs`. Helpers, page objects, suites without expanded selectors, and
unknown selectors are not executable tests and do not count toward sufficient coverage.

<!-- roles: qa-test-strategist, qa-case-designer, qa-case-critic, qa-doc-scribe -->
### Evidence freshness

A reviewed assertion link is still only reviewed coverage until it has fresh execution
evidence; never merge evidence from two tests into one assertion claim. A ledger row that
reports a reviewed link as verified states an execution that never happened.

<!-- roles: qa-test-strategist, qa-case-designer, qa-case-critic -->
### Levels by execution boundary

Classify a check by execution boundary and retain channel, runtime, and framework separately:
`unit` is isolated code; `component` is a real module/component with external boundaries
substituted; `integration` uses real collaborating components or storage; `api` uses a
public service contract; `e2e-ui` is a user path through required real layers. An ASGI router
with mocked services is component with channel `api`; a real HTTP endpoint is api with an
explicit observation boundary. Before a plan row is accepted, an unknown candidate boundary
is a named gap rather than a plan level; plan levels remain the factory's closed vocabulary.
A directory, language, helper, or page object does not determine a level.

<!-- roles: qa-requirements-tester, qa-test-strategist, qa-case-designer, qa-case-critic -->
### The oracle

The oracle is requirements or an approved decision. Code and existing tests are observations
and candidates only. Questions describe observable behaviour, never an implementation choice.
For no-write obligations name every mutable entity/table/event and its observation method:
before/after state proves no persistent change, while a claim that no write was attempted
requires call or audit instrumentation. A missing harness driver is not proof that an allowed
client, CLI, or container cannot observe state. Draft cases can be reuse candidates but
cannot approve product behaviour.

<!-- roles: qa-test-strategist, qa-case-critic -->
### Observation contract

Every plan row is planned on `coverage-observation-v1` (code writes the `coverage_contract_revision` mark) and puts an
`observation_contract` inside each existing obligation. It records typed `claim_kind`, a
revision-bound `oracle_ref`, observed/planned/gap `surfaces`, references to existing controls,
the completion reference, partition-specific independent expectations, and source-conflict
decision IDs. No-write designs also record the ordered before-read → action → completion →
after-read sequence and a separate mutating positive control. A surface gap prevents a full
claim. Structural validation checks the joins; the independent reviewer still records which
source references and mutable surfaces were checked and which were excluded.

<!-- roles: qa-test-strategist -->
### Coverage delta

The same revised row records `coverage_delta.entries` as `reuse`, `strengthen`,
`replace_redundant`, or `gap`, plus before/after logical-case and executable-instance counts.
One instance ID is counted once even when its assertions support several obligation parts.
Any increase requires a revision-bound accepted scope-expansion decision. Prefer strengthening
an existing case; parameter rows and red/positive-control executions are real instances.

<!-- roles: qa-requirements-tester, qa-test-strategist, qa-case-designer, qa-case-critic -->
### Compound requirements and comparisons

Decompose a compound requirement into explicit obligation parts, each with its own status,
evidence and gap. A requirement is full only when every required part is sufficient; an
unknown amber part does not suppress independent green/red checks. Visual comparison declares
left/right values and origins, selected revision, unsaved editor state, add/remove direction,
rendered evidence, and the actual entrypoint/caller/callee chain. Shared assumptions have an
ID and dependent rows. For parity, define expected outcomes for each meaningful input
partition before comparing endpoints; equal 500s, authentication failures, or a common
unreachable route cannot pass parity. Declare allowed dynamic-field normalization. No-leak
checks inspect response payloads directly.

<!-- roles: qa-scout, qa-test-strategist, qa-case-designer, qa-case-critic -->
### Reading existing candidates

Read only the relevant assertions of discovered candidates. Assess each link as
`sufficient`, `partial`, `none`, or `unknown` with a reason. Names, markers, line/branch
percentages, configuration, or a previous green result do not establish semantic coverage.
For unit evidence, consider material branches, boundaries, errors, invariants, and side
effects in the changed logic. Prefer sufficient reuse, then minimal extension or
parameterization, then a new check for a demonstrated gap. A partial search forbids a claim
that no duplicate exists and must remain visible at Gate A.

<!-- roles: qa-test-strategist -->
### Order of work

Order ready current-task obligations by dependencies first, then critical, normal, and low
risk. Within one risk level use confirmed release-blocking status, lowest cost of sufficient
evidence, and stable obligation ID. Unknown impact or oracle is resolved or explicitly
excluded before scheduling. Keep blocked high-risk work visible while allowing independent
ready work to proceed. Budget limits never lower risk or hide gaps. S3 and S4 design only;
they do not launch tests or add agents.

<!-- roles: qa-test-strategist, qa-case-designer, qa-case-critic -->
## Manual evidence policy

Choose `evidence_policy: ui | api | cli | no_write | static` (one word, as text) during S3/S4
and bind it to each manual obligation. Evidence kinds, phases, actual-step capture, observation
boundary and what each item must prove go in `completion_condition`.

- UI/native visual change: before and after images plus actual steps; motion may use a
  trace/video with a checked final state.
- API/CLI: secret-free request or command, response/output and exit code, plus enough state
  to evaluate the oracle.
- Absence of a record or side effect: relevant before and after state and a confirmed
  completion boundary. A successful HTTP status alone is insufficient.
- Static state: after-only evidence is allowed only when before has no evidentiary value;
  record `before_not_applicable_reason` at design time.

Missing required evidence yields `inconclusive`, not pass. Capability absence is an
environment gap unless another allowed evidence form is sufficient. Do not weaken the
policy after execution to turn an outcome green, and never fabricate screenshots.

Before declaring `manual-human` or a missing capability, perform a bounded search of allowed
APIs, utilities, and project examples and record the policy result. Existing route
interception can inject a targeted failure only with teardown and network evidence; it never
authorizes arbitrary infrastructure mutation. Developer-owned component/unit coverage is
not duplicated in e2e merely because QA has read-only ownership; a real repository gap is a
proposal to its owner.

<!-- roles: qa-case-designer, qa-case-critic -->
## Design review

The author self-probe and required independent review ask whether fixtures precompute the
claimed calculation, mocks isolate the defect location, negative assertions bound the
forbidden effect through completion, configuration is mistaken for interaction, and the
combined assertions cover every material part of the obligation. The dispatch supplies
`semantic_review_rows` separately from the structural-validation receipt. Expand semantic
scope only for a dependency or newly discovered risk with its reason; do not rereview every
case by default. Review risky shared premises against their source, not just the plan.

Sensitivity records include `proof_kind: design_analysis | executed_red_probe`, obligation
ID, declared defect site, expected failure, and `observed_failure_ref` only for an executed
probe. Design analysis must never claim execution. A defect-site/observation-boundary
mismatch is partial with a named gap, so neither aggregate pass nor full coverage may hide it.
Bind findings to obligation IDs, source hash, author dispatch, and pinned case versions. On
repair, reread only changed rows and dependent links.
