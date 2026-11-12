# Exploration charter - qa-runner at S6

Read with your brief: its `Exploration cells:` line names the file of the cells this charter talks about (read it before your
first capture; a dash in place of the file says why there is none), its `## The stand` section is where you
are, and the case of your window is the carrier of everything you find. You still run the case first; the charter adds what a
user's world does to the same flow.

<!-- kind: process -->
## Outcome

You try to break the story's flow the way the world breaks it for a user - a dependency fails, a field is keyed one character at a
time, the page is reloaded in the middle of a save - and you leave a `tried` table that says, for every cell you took, what the
requirements expect, what you saw and which captured file shows it.

<!-- kind: process -->
## Good outcome

The tier above accepts the window by these points, each with its witness:
1. The case of the window is judged first, by its own Thens, as the rest of your role says. No cell changes that verdict.
2. Every cell of `Exploration cells:` is one row of `work/evidence/manual/<case>/tried.md`: taken (outcome `held` or `violated`, with
   the evidence path) or `not tried` with the reason in words (a tool cannot do it, the stand refused, the cell does not apply - why).
   A field you met on the page is a cell too, one row per field and kind.
3. Every row names its hypothesis, its oracle and the observation that would refute it, written BEFORE the capture of that cell.
   The oracle quotes a requirement (`R-n`, the words); where the requirements are silent it is the axis oracle of your brief, and the
   row says `oracle: axis, requirements silent` - that row also carries a question (point 5).
4. Every `violated` row is an entry of the record's `observations[]` - `{step, expected, seen, evidence, quote}`, the quote copied
   from a capture of THIS attempt - so the analyst at S7 judges it. You never call it a bug; you never leave it in prose only.
5. Every doubt that is not a violated oracle - an intent you cannot tell, a cell you could not reach - is recorded the moment you meet
   it, with `exploratory_findings.py add`, not collected at the end.
6. "Nothing broke" is an outcome only with the table: an empty `observations[]` and an empty register with no `tried` rows is
   not a clean result, it is an unexplored flow, and it is returned.

| tried.md column | what it holds |
|---|---|
| cell | `<axis> x <request or field> x <kind>` as the brief spells it |
| hypothesis | `H-n`: the breakage you expect, one sentence |
| oracle | `R-n: "<quoted words>"`, or `axis, requirements silent` |
| refuted by | what you would see if the product is right |
| outcome | `held` / `violated` / `not tried: <why>` |
| seen | what the capture shows, in the product's words |
| evidence | the capture path under `work/evidence/manual/<case>/<attempt>/`, and `#obs<n>` or `EX-n` when there is one |

<!-- kind: craft -->
## Techniques

- **Start from the first look.** The first look walked the width (each requirement once, before the plan); you go deep from its observations (a `contradicts` or `missing` row, a locator it did not see, an odd answer) and do not repeat its pass. Its rows are observations, not oracles.
- **Hypotheses before the route.** Write the `H-n` of a cell - breakage, oracle, refuting observation - before you capture it. A
  hypothesis without a refuting observation cannot fail; rewrite it until it can.
- **Perturbation matrix.** The brief's cells are the matrix (`references/perturbations.json`: axes, kinds, axis oracles). Take every
  request cell; for the fields, take every input field of the flow you meet with every kind of `keyboard_input`.
- **One cell per call, with a control.** Fail ONE request per `ui` call or `walk_session.py step` call, so a broken page is attributable. Look at the same step with
  no failure first: a page that looks the same without the failure says nothing about it.
- **Fail first, then act.** `fail_request` acts from its line on: put it before the `goto` or the action that sends the request, then
  capture `post_action`. A failure that never fired is named in `failures_without_hits`, and its `post_action` capture is refused -
  that cell is `not tried: the request was not sent` until you find the action that sends it.
- **Vary the start on odd input.** When a field behaves oddly, try the same keys from another start state: empty and filled, selected and erased, a previous value, a different stock; write the start in the row.
- **The sign-in cell.** Sign in through the page in the SAME `--session` as the guest state you built (`fill-account` types the
  account's login and password); the failed run puts `fail_request` on the merge request's glob before the sign-in submit. If the
  page offers no guest state or no sign-in, the row is `not tried: <what the page does not offer>`.

- **A `surprise:` line is the recorder's eyes, yours to answer.** Whatever you make of it, it goes into the `seen` of a cell, and into
  an observation with `"surprise": "<id>"` when it might be a defect - only the observation reaches the analyst (code never reads
  `tried.md`: a line named only in a cell still becomes a triage target `<case>#sur-<id>`, and the analyst judges it from the line
  alone). A line you cite is judged inside your observation, with the quote taken from `NNN-surprises.txt`. There is no "noise"
  without a line the analyst has judged: if you think it is noise, say why in the `seen` and let the judgment stand.
- **See for yourself.** After an action whose result you doubt, `look` (a selector when you know the element) and read the tree
  before you write what the page shows: a disabled control, a missing row, an error boundary's words are in the tree, not in the
  excerpt.

The rest of the craft - where these bugs hide, boundary values, state transitions, and the guess of a breakage before the route (its "Hypothesis before the route") -
is in the runner's own charter (`agents/qa-runner.md`); this file keeps the matrix and the form of the table.

<!-- kind: process -->
## Tools

- `manual_capture.py ui --task-root <T> --case <C> --steps-file <S> --session <actor>`: the calls of the case join its open attempt,
  so the case and its cells share one attempt and one record. Steps you use here: `fill <sel> <text>` (clears the field, then keys
  the text one character at a time as a person does; the log has `cleared`, `n value focus=yes|no` per character, then `settled`;
  `fill --whole <sel> <text>` sets the value at once, for a field that must take it whole or a text too long to key in the step's
  time, and the step says `input: whole`), `type <sel> <text> [<delay_ms>]` (the same keying, but it appends and does not clear),
  `press <sel> <key>` (`Control+A`, then `Backspace`, empties a field), `paste <sel> <text>`, `fail_request <url_glob>
  <status|timeout>`, `restore_request <url_glob>`, `goto <url>` (the same address reloads), `read`, `capture pre_action|post_action
  <label>`.
- `look [<sel>]` is how you see the page for yourself: the page's accessibility tree (or the element's, with a selector) goes into
  the evidence as a state file, its first line says `form: aria` or `form: text (<why>)`, and you may quote it. The whole tree is
  stored only when you ask for it with a bare `look`; narrow it with a selector when the file says `[cut: ...]`. It is refused in
  the sign-in window. On a device `look` is `source` and takes no selector.
- `watch <sel> [<label>]` keeps reading the text of one element after every later step of the call (at most five); a change on a
  step that is not an action becomes a `surprise` line. Put it on the thing your hypothesis is about (a badge, a total, a message)
  before the step that should change it.
- After every step the recorder may print `surprise: <id> step <n> (<word>) <kind>: <fact>`: facts it saw that nobody asked about (a
  request during typing, a 4xx or 5xx, a request that failed outright (`failed`), a console error, a page that landed elsewhere, a
  field that shows less than was typed, a watched text that changed, a host outside the stand). The recorder only reports; it never
  calls anything a bug. Ids look like
  `a2-ui-S3`. The summary says `surprise_detection`: `on`, `partial: ...` or `absent: ...`; anything but `on` means the page was not
  fully watched, so no line is not "nothing happened".
- What `fail_request` can and cannot do: browser requests to a stand host only; a status 400-599 with an empty JSON body, or a
  dropped request (`timeout` fails at once - it is not a slow answer); a request sent by the page's server is not seen.
- The glob of a request is printed in its cell line (the side file named by the brief's `Exploration cells:` line): copy it whole. It
  matches the full URL on any stand host, with or without a query string; a pattern you shorten by hand may not match, and the call
  then says `failures_without_hits`.
- `manual_evidence.py build ... --observations-file <file.json>`: the record, with the `violated` rows as `observations[]`.
- `exploratory_findings.py add --task-root <T> --by <your dispatch id> --kind observation|unresolved_question|coverage_gap --title ...
  --statement ... --why-not-a-bug ... --evidence <captured file>` (`--question` and `--owner-role` for a question,
  `--missing-prerequisite` for a gap).

<!-- kind: process -->
## When to ask

- The requirements are silent on what a failure or an odd value should do: record an `unresolved_question` (owner `person`, oracle
  `owner_question`) at once and go on with the next cell. Nothing in this charter stops the window.
- A cell the tools cannot do, or a request you know of that is not in your cells: a `coverage_gap` naming what is missing, and the row
  `not tried: <the gap>`. Never adapt the cell into something it is not.
- A call that ends `env_blocked` (exit 3): the refusals of your role apply. If the case's attempt is blocked, capture the case
  again in a new attempt without the cell that broke the stand, and say so in that cell's row and in a `coverage_gap`.
