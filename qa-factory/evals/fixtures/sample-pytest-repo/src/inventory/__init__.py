"""Tiny in-process inventory service used as the application under test in qa-factory fixtures.

It is deliberately small: an in-memory store with validation rules that tests can observe
through the public API only (create, get, list, delete). No HTTP layer — the "stand" is this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class ValidationError(ValueError):
    """Raised when an item violates a business rule."""


class NotFound(KeyError):
    """Raised when an item id does not exist."""


@dataclass
class Item:
    id: int
    name: str
    quantity: int
    tags: list[str] = field(default_factory=list)


class InventoryStore:
    """In-memory inventory. Names are unique and case-insensitive; quantity is a non-negative int."""

    def __init__(self) -> None:
        self._items: dict[int, Item] = {}
        self._next_id = 1

    def create(self, name: str, quantity: int = 0) -> Item:
        name = (name or "").strip()
        if not name:
            raise ValidationError("name is required")
        if len(name) > 64:
            raise ValidationError("name is longer than 64 characters")
        if any(i.name.lower() == name.lower() for i in self._items.values()):
            raise ValidationError(f"name '{name}' already exists")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 0:
            raise ValidationError("quantity must be a non-negative integer")
        item = Item(id=self._next_id, name=name, quantity=quantity)
        self._items[item.id] = item
        self._next_id += 1
        return item

    def get(self, item_id: int) -> Item:
        try:
            return self._items[item_id]
        except KeyError:
            raise NotFound(item_id) from None

    def list(self) -> list[Item]:
        return sorted(self._items.values(), key=lambda i: i.id)

    def delete(self, item_id: int) -> None:
        if item_id not in self._items:
            raise NotFound(item_id)
        del self._items[item_id]
