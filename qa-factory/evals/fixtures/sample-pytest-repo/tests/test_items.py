"""Existing coverage of the inventory API. Marker convention: `TC-NNN coverage:` in the docstring."""
import pytest

from inventory import NotFound, ValidationError


def test_create_returns_item_with_sequential_id(store):
    """TC-001 coverage: create assigns ids starting at 1."""
    first = store.create("bolt", 3)
    second = store.create("nut", 0)
    assert (first.id, second.id) == (1, 2)
    assert store.get(first.id).name == "bolt"


@pytest.mark.parametrize(
    "name, quantity, message",
    [
        ("", 1, "name is required"),
        ("x" * 65, 1, "longer than 64"),
        ("bolt", -1, "non-negative"),
    ],
)
def test_create_rejects_invalid_input(store, name, quantity, message):
    """TC-002 coverage: validation rules on create."""
    with pytest.raises(ValidationError, match=message):
        store.create(name, quantity)


def test_create_rejects_duplicate_name_case_insensitively(seeded_store):
    """TC-003 coverage: names are unique ignoring case."""
    with pytest.raises(ValidationError, match="already exists"):
        seeded_store.create("BOLT", 1)


def test_list_returns_items_ordered_by_id(seeded_store):
    """TC-004 coverage: list order."""
    assert [i.name for i in seeded_store.list()] == ["bolt", "nut"]


def test_delete_removes_item_and_get_raises(seeded_store):
    """TC-005 coverage: delete then get."""
    seeded_store.delete(1)
    with pytest.raises(NotFound):
        seeded_store.get(1)
