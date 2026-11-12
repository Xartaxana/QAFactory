---
key: QA-1
type: Story
status: In Review
parent: QA-EPIC-1 "Inventory tagging"
assignee: dev
merge_request: feature/qa-1
---

# Items can carry tags

As a warehouse operator I want to attach short tags to inventory items so that I can filter the list by tag.

## Acceptance criteria

1. `create(name, quantity, tags=[...])` accepts an optional list of tags; items created without tags have an empty list.
2. Tags are stored lowercase and without surrounding whitespace; duplicates within one item are collapsed.
3. An item may carry at most 5 tags; a sixth tag is rejected with a validation error.
4. `list(tag="x")` returns only the items carrying that tag, in id order; `list()` without a tag is unchanged.
5. A tag is 1–20 characters, letters, digits and hyphens only; anything else is rejected with a validation error.

## Comments

- **po** (2026-09-10): filtering by an unknown tag returns an empty list, not an error.
- **dev** (2026-09-11): implemented on `feature/qa-1`; the 5-tag limit is not in this MR yet, will follow.
