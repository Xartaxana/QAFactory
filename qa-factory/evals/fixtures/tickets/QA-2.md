---
key: QA-2
type: Story
status: In Review
parent: QA-EPIC-1 "Inventory tagging"
assignee: dev
merge_request: feature/qa-2
---

# Items can be archived

As a warehouse operator I want to archive inventory items I no longer stock so that the default list shows only live items.

An archived item keeps its id and its data. `list()` hides archived items unless it is called with `archived=True`; `get(id)` still returns an archived item.

## Comments

- **po** (2026-09-12): archiving an item that is already archived is not an error, it changes nothing.
- **dev** (2026-09-13): implemented on `feature/qa-2`; archiving also removes the item from every tag filter, which the description does not say.
