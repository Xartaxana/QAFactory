Source: attempt a4 of case TC-010 of the 12586 comparison run on the live stand (testproject1-dev-010),
qa-factory/artifacts/TP1-12586/work/evidence/manual/TC-010/a4/ - steps.jsonl and captures.jsonl, copied
byte for byte (they carry no account value, no .env value, no non-ASCII character; no replacements were needed).
The screenshot a4/001-failed-step.png is not copied: the test stubs the page and writes its own bytes.

What it shows (the "was" of the step-error node): the step `click "#project-selector"` failed with
"no element matched within 30 s" although the element was on the page; a Guided Tour dialog mask covered it.
The test drives the real PlaywrightBackend with a stub page that answers like that page and checks that the
step now says what covered the element.
