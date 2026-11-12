# local1-playwright fixtures

Copies of what run 3 of LOCAL-1 (the MyBooks stand, 02-03.11.2026) wrote; nothing here is invented (PROJECT.md, "step moved to code
is checked against the reference"). The only change is the machine root, replaced by the token `{project_root}` (the test puts its
temp root in at load time); the sha256 below is of the ORIGINAL bytes, so a fixture with the token differs from it by that
substitution alone. `A` = `mybooks-stand/test-automation-framework/qa-factory/artifacts/LOCAL-1`; `T` = `mybooks-stand/test-automation-framework`.

| fixture | original | sha256 of the original | token |
|---|---|---|---|
| `ef39-repair_verify.junit.xml` | `A/evidence/runs/ef39dbfc032eb9587718/repair_verify-ef39dbfc032eb9587718-20261103-003000.junit.xml` | `24a697ba039b77534633fee57ba845a1662c8729b723ed15c03a82b749e99f6d` | none (byte-identical) |
| `ef39-run-block.json` | `A/work/run-blocks/20261102T233021115482Z-ef39dbfc032eb9587718.json` | `cdb413f04ddb53d0d028abd454fcb2386d3e80599b2c18aadf8414d4ef6b1d90` | one `evidence_refs` path |
| `16f0-initial.summary.json` | `A/evidence/runs/16f062e1e04674c1b12f/initial-16f062e1e04674c1b12f-20261103-001252.json` | `ccb72e97e795dc2d9c7d52fc903db4a92b4e9cb3df8adc3f1df08ecc4bb8d0cb` | the `--junit=` argument and two `evidence_refs` paths |
| `16f0-initial.log` | `A/evidence/runs/16f062e1e04674c1b12f/initial-16f062e1e04674c1b12f-20261103-001252.log` | `62c5e5f303742896186d260797fc7c305c4a4c137c6a02586710e6a51d0b4425` | none (byte-identical) |
| `manifest-run3.json` | `A/work/automation-manifest.json` | `75f5d7ad2d862b0ef3fc9807f5e0451bd0a68c5323ca1a32588e6412fa223bb1` | none (byte-identical) |
| `frag-4-b.json` | `A/work/manifest-fragments/S5-qa-automator-4-b.json` | `11d5e491034be9cb231d3d10d254126e7f3dcd9a6d2c9f0b2b513a2e9b39a2f8` | none (byte-identical; the real `\u0007` escape kept) |
| `frag-4-c.json` | `A/work/manifest-fragments/S5-qa-automator-4-c.json` | `7c8b0f1656463ebc9ed3a72155696b45edd062401dc4cdcaecc92f1e28ed79fc` | none (byte-identical) |
| `add-to-cart.spec.ts` | `T/tests/api/cart/add-to-cart.spec.ts` | `4a9c11e29af38634c1c19230cb987969baec60593a016b88a46f0a84b69ccf0b` | none (byte-identical) |

Second substitution (FR-30, the package is English: `selftest.py --lang` refuses any Cyrillic character): in `ef39-run-block.json`
and `16f0-initial.summary.json` the person's two words in `person_confirmation.words` are written as the JSON escapes of the same
characters (`\u0414\u0430`, `\u0442\u0435\u0441\u0442\u0438\u0440\u0443\u0439`); a JSON reader gets the identical string, only the
bytes differ.

Line endings: the originals of `add-to-cart.spec.ts`, `frag-4-b.json`, `frag-4-c.json` and `manifest-run3.json` are CRLF; the repository
normalises text to LF on commit (git warns at `add`), so the committed bytes of those four differ from the sha256 above by line endings
alone. No test reads a byte-level hash of them.

`frag-4-b.json` and `frag-4-c.json` are carried for node N2 (builder B2); N1 does not read them.

Note (t-1746): the committed `16f0-initial.log` is the one line the test reads (`Error: No tests found.`), NOT the byte-identical run log of the row above (that file was not on the branch or its history; its sha256 is not that of this file).
