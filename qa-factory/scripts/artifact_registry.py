"""Logical artifact paths shared by writers, readers and migration tooling."""
import json
from functools import lru_cache
from pathlib import Path

REGISTRY = Path(__file__).resolve().parents[1] / "references/artifact-registry.json"


@lru_cache(maxsize=1)
def entries():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))["artifacts"]


def canonical(task_root, name):
    if not name or Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("artifact name must stay inside the task")
    rule = entries().get(name)
    return Path(task_root) / (rule["path"] if rule else "work/" + name)
