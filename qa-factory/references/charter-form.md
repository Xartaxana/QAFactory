# The form of a role charter

A role's `agents/<role>.md` is a charter: the experience of a tester at one stage, not a procedure. What the role is given,
what it owns, what it must not do and where it hands over are NOT in the charter; the brief carries them as the seven header
lines (`goal`, `DoD`, `given`, `owns`, `non-goals`, `handoff`, `questions`, rendered by `brief_pack.sd_head_lines` from
`references/brief-form.json`). The keys of the role's artifact and handoff form are on its key page and in the artifact
contract. The machine part of this form is `scripts/charter.py`; audit A19 judges a charter by `charter.charter_errors`.

## The six sections (this order, these headings)

| # | heading | kind | content |
|---|---|---|---|
| 1 | `## Outcome` | process | one or two sentences: what the role answers for as a whole (becomes the `goal:` line) |
| 2 | `## Good outcome` | process | the acceptor's DoD: an opening line naming the `tried` table of the handoff form as a witness, then 3 to 6 items `N. **<lead>.** <text>. Witness: <what the acceptor reads>.` (the leads become the `DoD:` line) |
| 3 | `## Where bugs hide at this stage` | craft | experience: where the work most often breaks, and why |
| 4 | `## Techniques` | craft | techniques by name, each with when to use it; no form keys, no rules that code checks |
| 5 | `## Tools` | process | scripts the role MAY call (never a required order); rules of form and economy; ends with a `<!-- gen:digest contract_slices.py -->` block |
| 6 | `## When to ask` | process | the one road a question takes for this stage |

A charter has at most 150 lines. A file whose headings or markers do not fit is refused by A19 with the sentence that says what is
wrong and what was expected.

## The `kind` marker

A line `<!-- kind: craft -->` or `<!-- kind: process -->` stands DIRECTLY above each `## ` heading (no blank line between).
Craft is counted by ONE reader, `role_load.craft_split` (its regexp is `role_load.KIND_MARKER`; `charter.py` imports it, never a
second copy). Craft is the bytes of sections 3 and 4 with their marker lines; everything else is process. A sentence that names a
field, a key, an order, a command or a saving of moves is process and belongs in section 5 or 6, even when it sounds like a
technique. If the craft share is under half, craft is ADDED (where bugs hide, techniques with when to use them); process text is
not re-marked as craft. A marker not above a heading marks nothing: it is reported (`charter.stray_markers`, A19 info), not an
error.

## Marker order in sliced files

A file under `references/` that carries both markers is read the same in either order: `contract_slices.parse` skips a `kind`
line (`KIND_LINE`) and keeps the pending `roles` marker, and `role_load.craft_split` skips a comment line between its marker and
the heading. The shipped convention is `kind` first, then `roles`, then the heading:

    <!-- kind: craft -->
    <!-- roles: qa-scout, qa-requirements-tester -->
    ## Heading

A charter has no `roles` marker.

## Where the form lives

This document is the human description (FR-44: it is read by whoever changes the factory, so it lives in `references/`). The machine
form is `CHARTER_SECTIONS` in `scripts/charter.py`. There is deliberately no template file under `agents/`: every `agents/*.md`
is loaded by the host as a role and walked by audits A19, A9 and A2b.
