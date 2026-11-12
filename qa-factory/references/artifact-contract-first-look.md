# Artifact contract: the first look (`work/first-look.yaml`)

The first look is what a walker saw of the new version on the stand BEFORE the plan is made: per requirement of the register, did the stand
show it, contradict it, lack it, or could not be walked to. It is an OBSERVATION, never an oracle: a row says what the walker saw and where; it
does not say what is right. Whoever reads it weighs it (the strategist, the case designer, the person at the gate).

Who writes what. The walker writes the rows (a YAML file) and sends them with `first_look.py put --task-root <story> --file <rows.yaml>`; code
writes the record `work/first-look.yaml` and the attempt `state/first-look-attempt.json` (nobody else does, and you never edit them by hand).
`first_look.py show --task-root <story>` prints the record; `show --json` also carries `current_keys`.

## The rows you send

```yaml
rows:
  - req: R-1
    status: confirms
    why: Opened the cart: the Pay button is shown under the total.
    evidence:
      - work/evidence/manual/survey-R-1/a1/http-1.json
    quote: Pay button
    path:
      url: /cart
      steps:
        - open the cart
      locators:
        - what: Pay button
          selector: button#pay
          seen: yes
      api:
        - method: GET
          path: /v1/cart
          auth: account:user
          sample:
            request: GET /v1/cart
            status: 200
            response: '{"total": 12}'
          seen: yes
      data: []
      roles: []
      stand_needs: []
  - req: R-2
    status: missing
    blocked_by: product
    why: The cart has no discount field.
    evidence:
      - work/evidence/manual/survey-R-2/a1/look-1.txt
    quote: Total
gaps:
  - R-2: the stand may be an older build than the story.
```

- ONE row per requirement of the register (`work/requirements-register.md`, the `## Register` table): none missing, none twice, none for an
  id that is not in it. A requirement the stand does not show is a `missing` row, never an absent one.
- `status` is one of `confirms`, `contradicts`, `missing`, `unreachable`; `blocked_by` is one of `product` (the stand does not have it),
  `access` (no way in for the walker), `nature` (nothing a walker can observe, such as a build setting), and is required on `missing` and
  `unreachable`. The words are `references/first-look-statuses.json`.
- `evidence` lists capture files of THIS walk's attempt of THIS requirement (the item `R-n` of the survey walk; `walk_session.py look` and
  `step` print the paths), and `quote` is words copied from them as the capture holds them. Every cited path must hold the quote. Only a
  `blocked_by: nature` row may cite nothing. A quote that crosses a quotation mark or a line break of an HTTP capture, stands in a cut-off
  body or in a base64 body is refused: quote a fragment without such characters and describe the rest in `why`.
- `path` is where the requirement lives on the stand; every part is optional: `url`, `steps`, `locators` (`what`, `selector`, `seen: yes|no`),
  `api` routes (`method`, `path`, `auth: none|token|account:<role>`, `seen: yes|no`, and a `sample` of what the call SHOWED: `request`, `status`,
  `response` - an observation, never an expectation), `data`, `roles`, `stand_needs` (lists of lines). A route the code names and the walker did
  not call is `seen: no` with no `sample`.
- `gaps` are lines for what you could not establish.
- A word of yours for `walked_at`, `walk`, `stand`, `stand_build`, `source_head`, `register_hash` or `sides_met` is ignored: code writes them.

## What code writes

`walked_at`, `walk` (the dispatch id the attempt names), `stand` (the stand the attempt names), `stand_build` (`confirmed` only when the person's
word for this story and stand is a `deployed` word at the revision of the one implementation entry; otherwise `not_established`, which is
the usual case: the stand may be an older build), `source_head` (a map: repository id to the commit of its implementation entry, or
`unmeasured: <why>`), `register_hash` (sha256 of the register's requirements and statements), and `sides_met` (the sides of the story that are
not real, with their reality; written only when there is one).

A first look that was not walked is a record with `null: <reason>`, `rows: []` and one line in `gaps` (`first_look.py put --null <reason>`;
the reasons are `null_reasons` of the words file). It is a declared empty outcome, not an error. The record is STALE when the code heads or the
register differ from the ones it was walked on; a stale record never confirms anything.

## Refusals

A refusal lists every problem of the file at once, each with its door. Nothing is written on a refusal. If the walk is not open (the driver
opens it) record what you saw as a gap in your handover and halt.
