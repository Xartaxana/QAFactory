# qa-story

Takes one ticket from "nobody has looked at this yet" to tested, reported and (if you say
so) merged — and asks you for a decision exactly twice.

## What it does

Ten stages, twelve specialist roles, two stops for you:

| Stage | What happens |
|---|---|
| S0 Preflight | Resolves the ticket and the environment, checks that the factory can actually run this story, and picks up where a previous session stopped. |
| S1 Context | Finds the ticket, the merge request, the diff, the tickets it names and the existing tests, and pins every requirement to something observable in the code. |
| S2 Understanding | Builds the requirements register, the contradiction matrix and a one-screen understanding brief; estimates the size. |
| S3 Plan | Writes the test plan — what is checked, what could break, how painful that would be, what gets automated and what a person does. **Then it stops: gate A.** |
| S4 Cases | Writes and reviews the test cases. |
| S5 Automation | Checks your working tree, cuts the story branch, writes the test code and reviews it. |
| S6 Run | Runs the feature's tests quietly and executes the agent-run manual cases one window per case, in turn. |
| S7 Triage | Gives every failure a verdict with evidence — application bug, test bug, environment, flaky — and repairs the test bugs. |
| S8 Results | Generates the checks ledger and the delivery verdict by code, writes the report. **Then it stops: gate B.** |
| S9 Retro | Folds what was learned into the project's documents, asks one optional question, and ends with a ten-line summary. |

## The two stops

**Gate A — after case design and review.** You get one message with paths to
`understanding.md` and `test-plan.md`; the latter embeds the exact reviewed cases. The
message also shows the bounded scope, risks, gaps, execution split, regression
recommendations, source revisions and proposed external actions. You approve or edit the
shown content and separately authorize any exact TMS case actions.

**Gate B — after the run.** You get the checks ledger first — every plan row and every test
in exactly one state, so nothing is invisible — then the code's own `delivery_ready: yes | after_checks | no`
with its reasons, then the report. You decide which bugs/results to publish, whether to open the MR,
what to do with each gap, and what
must not be committed. When the verdict is `no`, there is no "open the MR" option — only
"deliver with known gaps", and only with a reason, which lands in the MR as a banner.

Between those two gates the factory asks nothing. It either decides for itself and records
why, or it **halts** — stops on a concrete blocker and tells you exactly what is needed and
from whom.

## How to ask

- "qa this ticket: PROJ-412"
- "run qa-story PROJ-412 --mr 812 --env staging"
- "test story PROJ-412"
- `/qa-factory:qa-story PROJ-412 --branch feature/coupons --env local`

## Arguments

```
qa-story <ticket>
  --mr <url|id>        the merge request to test against
  --branch <name>      a branch to diff against the default branch
  --commit <sha>       a commit to diff
  --env <name>         which environment to test on (from your onboarding config)
  --ungrounded         requirements only, on the code the stand runs now
  --side <name>=<reality>   a part of the product and its reality (`real`, `substituted`, `absent`); `--side product=absent` is "not built yet"
  --reference <side>=<stand> the stand that stands in for a side
  --ticket-file <path> read the ticket from a markdown file instead of a tracker
```

Tell it where the change lives at launch. If it cannot find a diff, it stops and offers you
four options rather than hunting: give it the change, name the environment and repo where
the change already lives, go on with `--ungrounded` (the requirements only, on the code the
stand runs now), or answer `not built yet` (the code is not written: the tests are written
from the requirements and the story stops after them; `--side product=absent` says the same
at launch).

## Prerequisites

- The project has been onboarded — run `/qa-factory:qa-onboarding` once first.
- A git repository as the working directory, Python 3.10+ on `PATH`.
- The `qa-factory` plugin installed (see the package `INSTALL.md`).
- An environment you have told it about. The factory inspects the running version first
  and performs only authorized, necessary preparation; it does not rebuild by habit.

## What it will not do

- It never changes application code. It files bugs; your developers fix them.
- It never writes to a tracker or test-management system by itself — a script does that,
  after gate B, only for the channels your config names.
- It never runs a full regression suite. The regression you should run is a list with
  commands in the results brief.
- It never quarantines a flaky test on its own, never skips a check quietly, and never
  reports an empty run as a clean one.
- v0 covers functional testing only. Performance, security, accessibility, localization,
  compatibility and privacy are out of scope in this version.

## The optional judge

Off unless you turn it on. A project that sets `judge` in `qa-factory/config.json` sends some
of the small, repetitive judgments — is this requirement testable, does this case check its
plan row, which of these is to blame for a failing run — to a fast yes/no model instead of
spending a full model turn on each. It writes nothing, talks to nobody, and an answer it is
not sure about goes back to the role that would have made it anyway. Both gate messages end
with a `## Judge` block: what was asked, how much of it was decided, what it cost, and every
check of the factory's own it let through — one word from you brings any of them back. With
no `judge` in your config nothing is sent anywhere and no message mentions it.

## Where things land

Everything lives in your repository under `qa-factory/`: the story's artifacts in
`artifacts/<TICKET>/` (register, plan, cases, manifest, run report, triage, ledger, report,
retro), bugs in `bugs/`, the event journal and the dashboard in `state/`.

## Interrupted? Just run it again

`qa-story <ticket>` re-read from `pipeline.json` resumes where it stopped. It never re-asks
a decision you already gave — both gates are recorded verbatim in the journal.
