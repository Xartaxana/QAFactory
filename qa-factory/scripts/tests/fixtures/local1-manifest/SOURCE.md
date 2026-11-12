# local1-manifest fixtures

Byte copies of real files of the LOCAL-1 run 3 (02-03.11.2026) on the mybooks stand (RN1-22, spec t-1699 node N2).
Nothing is edited: the files carry no machine path and no non-ASCII byte. `frag-4-b.json` keeps the real `\u0007`
escape inside `report_test_id` (the role's broken `\a` backslash path - part of the evidence).

| fixture | original (under `mybooks-stand/test-automation-framework/`) | sha256 of the original bytes |
|---|---|---|
| `frag-4-b.json` | `qa-factory/artifacts/LOCAL-1/work/manifest-fragments/S5-qa-automator-4-b.json` | `11d5e491034be9cb231d3d10d254126e7f3dcd9a6d2c9f0b2b513a2e9b39a2f8` |
| `frag-4-c.json` | `qa-factory/artifacts/LOCAL-1/work/manifest-fragments/S5-qa-automator-4-c.json` | `7c8b0f1656463ebc9ed3a72155696b45edd062401dc4cdcaecc92f1e28ed79fc` |
| `manifest-run3.json` | `qa-factory/artifacts/LOCAL-1/work/automation-manifest.json` | `75f5d7ad2d862b0ef3fc9807f5e0451bd0a68c5323ca1a32588e6412fa223bb1` |
| `add-to-cart.spec.ts` | `tests/api/cart/add-to-cart.spec.ts` | `4a9c11e29af38634c1c19230cb987969baec60593a016b88a46f0a84b69ccf0b` |

The sha256 values are of the original bytes as measured on the stand (CRLF line ends); git normalizes line ends on commit, so a
checkout can differ from the hash by the line ends only. No test reads these files by byte.

`frag-4-b.json` is the fragment that shrank `then_bindings` to 3 rows (a `tests[]` row copied with `generated_from`);
`frag-4-c.json` is the role's workaround that re-sent all 29 rows.
