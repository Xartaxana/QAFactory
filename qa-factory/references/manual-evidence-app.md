# Manual evidence on a device stand

Read this only when your brief lists `manual_capture.py app`: the project describes a device stand (`environments[]` row with a
`surface` the factory drives through a device driver). A web or API case follows `manual-evidence.md` and never this file. The
record, `request.json`, `build`, the verdict rules and the attempt rules of `manual-evidence.md` are the same here; only the hands
differ. Nothing here was run on a real device by the factory's author: if the device behaves otherwise, say what you saw.

## Capture

`manual_capture.py app --task-root <T> --case <C> --steps-file <S> [--surface <id>] [--attempt aN] [--profile <id>]`

- One step per line, tokens split as a shell would (quote a selector or text that holds a space); blank lines and lines starting
  with `#` are ignored. The closed list is `app_steps` of `references/manual-capture-steps.json`: `launch`, `click <selector>`,
  `fill <selector> <text>`, `fill-account <selector> <actor> user|secret`, `drag <selector> dx dy`, `wait <ms>|<selector>`,
  `read <selector> [attr=<name>|text]`, `back`, `source [label]`, `log [label]`, `capture <pre_action|post_action|supporting> [label]`.
- There is no `goto`: a device has no address. `launch` brings the application under test (`app.id` of the stand's row) to the
  front; start with it. A word of the browser list (`goto`, `type`, `press`, `paste`, `fail_request`) is refused as no such step.
- A selector is `<strategy>=<value>`, cut at the FIRST `=`; the strategy is one of the list the refusal prints for the stand's
  platform (for example `accessibility id`, `id`, `xpath`). A selector with no listed strategy, or an empty value, is refused
  before the session exists. There is no CSS on a device.
- `source` stores the screen's element tree (XML) as a state file: look there for the text and ids the screen carries, and quote a
  Then from it when the picture does not say it. `log` stores the tail of the device log when the platform has one; otherwise it
  is refused and you say so in the limitation.
- You see the screen as on the web: the first 40 steps return `{step, outcome, screenshot, text}`; `text` is a short excerpt of
  the words on the screen after the step. A failed step has its own screenshot. A step fails when the element is not found
  within the wait, when the driver answers an error, or when the session is gone; a failed step stops the case.
- Do not use `--as`: a device has no sign-in by code (it is refused with this door). To sign in, type the account with
  `fill-account <selector> <actor> user|secret`; `<actor>` is a form of `--as` of `manual-evidence.md` (`default`, a role, `env:USER_KEY/SECRET_KEY`,
  `created:<name>`), the value is read by code and the file holds only names. From the first such step until the sign-in
  screen is gone no screen is saved, and a `capture` is refused. The project names an element only the sign-in screen has in
  `manual_capture.login.app.sign_in_selector` of its config; that element going away ends the window. Without it the window never closes in that session and a `capture` after it is refused naming that key: sign in in a
  separate attempt and capture in the next.
- Never put a credential in a steps file: a text matching `secret_content_patterns` is refused.

## Exit codes and the stand

- 0 every step ran; 1 a step failed (its evidence is saved; the summary's `failed` names it); 2 refused (stderr says what and how
  to fix it: no device stand, two device stands and no `--surface`, the application id empty, an unknown step, a bad selector,
  a secret in the file); 3 the stand could not be identified.
- Exit 3 on a device names its cause. `cause: device`: no device is attached, one is offline or unauthorized, or the driver
  server does not answer. Nothing in the case can fix it: put the case in `env_blocked[]` with the printed line and halt the
  block; do not `build` a blocked attempt; do not ask a person. `do_not_retry` means the same stand answers again.
- The factory identifies the stand around an attempt, as on the web. When it cannot, the block is the factory's to resolve with
  the person, not yours: you only halt the case.

## Build

After the captures, `manual_evidence.py build` as in `manual-evidence.md`. The policy of a device case is the same `ui` policy: a
pass needs the capture line `capture post_action completion` (a screenshot) and a quote for every Then of `request.json`;
`--then-quote` takes words copied from `text` or `source` of this attempt, `--then-seen` a Then only the picture shows.

## What is not here

- The factory does not confine the device's network to the stand: the capture records that as a limitation of the attempt.
  Say in `--limitation` when the check could have gone through another backend.
- No gestures beyond `drag`, no push notifications, no system dialogs of the operating system, no biometrics, no second device.
  A case that needs one is `inconclusive` with the limitation in your words, never a pass.
- A real device may answer slower than an emulator: use `wait <selector>` before a read instead of a long fixed `wait <ms>`.
