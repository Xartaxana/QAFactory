"""Shared fixtures. Convention: every test builds its own data through these fixtures; nothing depends on
pre-existing records."""
import pytest

from inventory import InventoryStore


@pytest.fixture
def store() -> InventoryStore:
    return InventoryStore()


@pytest.fixture
def seeded_store(store: InventoryStore) -> InventoryStore:
    store.create("bolt", 10)
    store.create("nut", 25)
    return store
