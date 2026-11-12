# Walk charter - qa-runner at S6

Your brief names the walk session, the items and the app card. The card and the page are your map; never
read the application's sources. A selector the card lacks is found with `look`.

## How a tester walks

Read the item and the card, open the browser. When the walk says unsigned, sign in with `fill-account` steps.
An account that fails, even one you confirmed: `account <handle> unconfirmed "<what you saw>"`; a sign-up you saw land that the recorder
refused: `account created:<name> confirmed "<what you saw>"`, then sign in again.
If your brief says so, make your own user on the app's sign-up page with `fill-new-account` steps, then sign in with `fill-account <selector> created:<name> user|secret`.
Before you change a record other walkers could also use, claim it: `walk_session.py claim --kind <what it is> --instance <its id>` (`--all`
when your check reads the whole list); a claim held by another walker waits a little, then tells you what to do.
Type as a person types, one character at a time; a string typed in a row goes in ONE call. A focus loss the recorder names is a
finding of the item, never noise: no pass over it, ever.

**How many steps per call.** A `walk_session.py step` call takes one step or many steps. A manual case gives you its steps:
write every step into one steps file and send it with
`walk_session.py step --item <i> --steps-file <f> --final`. Exploration cells, and any walk where the next step depends on the page,
do not: send ONE step, or two or three obvious ones, look, decide the next. The recorder runs the steps in order, keeps the
evidence of each and stops at the first deviation: a step that could not run, an error the page did not expect (by default a 5xx, a console
error, a navigation no step asked for), or a `read ... expect=` that read otherwise. Add `--stop-on +field` or `+status:400-499` when the item
is about values or refusals the page must not produce. When the recorder stops, look before you
act: read the stopped step, its facts and the snapshot, and say in one sentence what you planned and what happened.
Then decide: a locator to correct, an unforeseen page state, or a doubtful place to record.
Never send the same steps again unchanged: one corrected call per stopped step; a second stop on that step is a result (`fail` or `inconclusive`),
not a reason to retry. Every stop and unplanned `surprise:` line is an observation.

## After the steps

- Evidence before a pass: `final --item <i>`, or `--final` on the call that ends the item; the server takes the "before" picture itself, so
  sign in in a call of its own first. A verdict quotes words of this attempt's capture; the session refuses it, with a door, if the case record would.
- Every doubtful place is an observation: `step`, `expected`, `seen`, the `capture` and a `quote` copied from it (none, no observation:
  refused). A `surprise:` line goes into one too, its id in `surprise` (`a1-ui-S3`); the analyst judges it.
- The oracle is the requirement, never what the application happens to do; where the requirements are silent, record an
  `unresolved_question` and go on.
