# Native Codex acceptance results — 2026-09-19

## 0.7.2 installed Windows-host findings

Native CLI 0.154.0 accepted the installed plugin but initially showed all 13 hooks as
awaiting trust. They were reviewed through `/hooks`; no trust bypass/config edit was used.
After review the hooks still failed before Python: PowerShell parsed the quoted launcher
as a string. The new Windows override invokes it with `&`, resolves the plugin environment
variable and explicitly preserves `$LASTEXITCODE`, including blocking exit 2.

Session `01a0bb12-b386-7a91-9e74-adf9a9854f76` verified real ALLOW execution and DENY rejection.
Code-mode inner exec IDs differ from transcript call IDs; the verifier now correlates the
session, one literal probe command and its actual host output. It rejects comments, foreign
sessions and unmatched outputs. Native context delivery then failed: observed tool names
concatenate `collaboration` and `spawn_agent`, and dispatch returns only a canonical task
path. The adapter now normalizes those names and binds that path to the child's own host
metadata, checking its parent identity before accepting delivery or terminal status.

After these repairs, all 10 native-adapter tests and all 13 reliability tests passed.
These include Windows shell execution, paths with spaces, stdin, exit codes, code-mode
correlation, cancellation and path-only child identity. Source install smoke also passed.
The repeated native context-delivery check is tracked below; these fixture results alone
do not certify injection, every lifecycle gate or Desktop parity. No project roles were
exported into the user's test harness; one CLI profile exists only in the isolated fixture.


The next live run exposed an opaque-message failure: after PreToolUse appended rules,
the child failed with an encrypted-content decoding error before producing a response.
No delivery marker was emitted because the hook input contained the opaque message.
Codex context now uses a separate SubagentStart additionalContext payload. The original
spawn input remains unchanged. A parent has one pending launch packet until the child
starts; role/identity checks prevent cross-child delivery. Concurrent running workers
remain supported. The diagnostic task name is qa_factory_context_probe.

## Final observed result

Session `01a0bb2e-0942-79b3-a8ba-086af33bc258` passed the real allow/deny probes
and delivered-context probe on Windows Codex CLI 0.154.0. Child
`01a0bb30-1d86-77d0-9567-0df747e6d442` returned the injected challenge and
completed naturally. `host_probe.py --check` reports both `status: verified` and
`injection: verified`. All 14 hooks were enabled through the native review UI.
The verifier retains an immutable transcript prefix: later host usage/completion
records may append without invalidating proof, while prefix tampering fails verification.

Full regression: `selftest.py --tests --limits --lang --wiring --hygiene` passed
79/79 checks (75 test modules and four package checks). No project-local role export
was performed during this update.

This proves essential enforcement and context delivery on the tested CLI build.
Live compaction/recovery, all artifact/exit gates, Desktop parity and the complete
Claude lifecycle matrix remain separate acceptance work. The pilot story remains
blocked at S1; its GitLab API authentication was not repaired, and SSH access does
not replace unread MR metadata or discussions. Do not claim accepted pilot S1 or
full cross-host parity from these results.
