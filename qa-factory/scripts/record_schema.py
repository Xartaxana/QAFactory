"""Dependency-free validator for the schema keywords used by factory records.

The shipped document is standard JSON Schema. This reader deliberately rejects unknown
keywords so extending that document cannot silently weaken runtime validation.
"""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def schemas():
    return json.loads((Path(__file__).resolve().parents[1] / "references/record-schemas.json").read_text(encoding="utf-8"))["$defs"]


def _problems(schema, value, location):
    """Every problem of `value` against `schema`, in the order the checks run (C4-5 remainder, class K1: a record with two
    defects used to be refused for the first one and again for the second). Two stops stay, each for the invariant that no
    check runs on data it cannot read: an unsupported keyword is the SCHEMA's defect and raises on the spot (nothing about
    the value can be judged by it), and a value of the wrong type is told alone at its own location (a missing key, a
    length or a minimum of a value that is not that type means nothing) - its siblings are still checked."""
    allowed = {"type", "required", "properties", "items", "enum", "const", "minLength", "maxLength", "minItems", "minimum"}
    if set(schema) - allowed:
        raise ValueError("unsupported schema keywords: " + str(set(schema) - allowed))
    types = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}
    kind = schema.get("type")
    if kind and (not isinstance(value, types[kind]) or (kind in ("integer", "number") and isinstance(value, bool))):
        return [location + ": expected " + kind]
    problems = []
    if "const" in schema and value != schema["const"]:
        problems.append(location + ": wrong constant")
    if "enum" in schema and value not in schema["enum"]:
        from detector_verdict import one_of
        problems.append(location + ": unsupported value (one of " + one_of(schema["enum"]) + ")")
    problems += [location + ": missing " + key for key in schema.get("required", []) if key not in value]
    for key, rule in schema.get("properties", {}).items():
        if key in value:
            problems += _problems(rule, value[key], location + "." + key)
    if "items" in schema:
        for i, item in enumerate(value):
            problems += _problems(schema["items"], item, location + "[" + str(i) + "]")
    for key in ("minLength", "minItems"):
        if key in schema and len(value) < schema[key]:
            problems.append(location + ": too short")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        problems.append(location + ": too long")
    if "minimum" in schema and value < schema["minimum"]:
        problems.append(location + ": below minimum")
    return problems


def validate(schema, value, location="$" ):
    """Raise `ValueError` for the problems of `value`: ONE problem is its own sentence, unchanged; several are the combined
    refusal `detector_verdict.compound` writes (the same text as `Controller._raise_all`), every one listed."""
    problems = _problems(schema, value, location)
    if problems:
        from detector_verdict import compound
        raise ValueError(compound(problems))


def validate_record(kind, value):
    validate(schemas()[kind], value)
    return value
