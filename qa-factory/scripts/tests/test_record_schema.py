"""record_schema.validate/validate_record: the dependency-free JSON-Schema-subset reader
for record-schemas.json. Per its docstring, unknown schema keywords are rejected on
purpose so a future schema edit cannot silently weaken runtime validation. Covers the
allowed-keyword fence plus every constraint kind (type, required, enum, const, min/max
length, minItems, minimum) on a synthetic schema, then the same checks against a real
record kind ("Decision") loaded from references/record-schemas.json.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import record_schema as RS  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, finish  # noqa: E402

# --- the keyword fence: extending the document must fail loud, not weaken validation ---
try:
    RS.validate({"type": "string", "pattern": "^x"}, "x")
    check("an unsupported schema keyword raises", False)
except ValueError as exc:
    check("an unsupported schema keyword raises ValueError naming it", "pattern" in str(exc))

# --- type / required / properties, nested ---
PERSON = {"type": "object", "required": ["name", "age"],
          "properties": {"name": {"type": "string", "minLength": 1},
                          "age": {"type": "integer", "minimum": 0}}}
RS.validate(PERSON, {"name": "Ann", "age": 5})  # does not raise

try:
    RS.validate(PERSON, {"age": 5})
    check("a missing required field raises", False)
except ValueError as exc:
    check_eq("...naming exactly which field is missing", str(exc), "$: missing name")

try:
    RS.validate(PERSON, {"name": "Ann", "age": "old"})
    check("a wrong-typed value raises", False)
except ValueError as exc:
    check("...naming the nested path and expected type", "$.age" in str(exc) and "integer" in str(exc))

try:
    RS.validate(PERSON, {"name": "Ann", "age": True})
    check("a bool is NOT accepted as an integer (bool is an int subclass in Python)", False)
except ValueError:
    check("a bool is NOT accepted as an integer (bool is an int subclass in Python)", True)

# --- enum / const ---
STATUS = {"type": "string", "enum": ["Open", "Closed"]}
RS.validate(STATUS, "Open")
try:
    RS.validate(STATUS, "Deleted")
    check("a value outside the enum raises", False)
except ValueError as exc:
    check("...as 'unsupported value'", "unsupported value" in str(exc))

VERSIONED = {"type": "object", "properties": {"schema_version": {"const": 2}}}
try:
    RS.validate(VERSIONED, {"schema_version": 1})
    check("the wrong const value raises", False)
except ValueError as exc:
    check("...as 'wrong constant'", "wrong constant" in str(exc))

# --- minLength / maxLength / minItems / minimum ---
BOUNDED = {"type": "object", "properties": {
    "id": {"type": "string", "minLength": 1, "maxLength": 5},
    "tags": {"type": "array", "minItems": 1, "items": {"type": "string"}},
    "count": {"type": "integer", "minimum": 1}}}
RS.validate(BOUNDED, {"id": "abc", "tags": ["x"], "count": 1})
for bad, why in (({"id": "", "tags": ["x"], "count": 1}, "too short"),
                  ({"id": "abcdef", "tags": ["x"], "count": 1}, "too long"),
                  ({"id": "a", "tags": [], "count": 1}, "too short"),
                  ({"id": "a", "tags": ["x"], "count": 0}, "below minimum")):
    try:
        RS.validate(BOUNDED, bad)
        check(f"a violation reported as {why!r} raises", False)
    except ValueError as exc:
        check(f"a violation reported as {why!r} raises", why in str(exc))

# --- items: every array element is validated against the same rule ---
try:
    RS.validate(BOUNDED, {"id": "a", "tags": ["ok", 5], "count": 1})
    check("a non-string item in a string array raises", False)
except ValueError as exc:
    check("...naming its index in the path", "$.tags[1]" in str(exc))

# --- a real record kind from references/record-schemas.json: Decision ---
DECISION_OK = {"id": "S5-160", "action": "waive block", "authorization_source": "human",
               "source_revision": "chat:2026-09-08", "status": "approved"}
RS.validate_record("Decision", DECISION_OK)  # does not raise
check_eq("validate_record returns the value unchanged on success", RS.validate_record("Decision", DECISION_OK), DECISION_OK)

for missing in ("id", "action", "authorization_source", "source_revision", "status"):
    incomplete = {k: v for k, v in DECISION_OK.items() if k != missing}
    try:
        RS.validate_record("Decision", incomplete)
        check(f"Decision without {missing!r} raises", False)
    except ValueError as exc:
        check(f"Decision without {missing!r} raises, naming the field", f"missing {missing}" in str(exc))

try:
    RS.validate_record("Decision", dict(DECISION_OK, status="maybe"))
    check("Decision.status outside {approved, declined, deferred} raises", False)
except ValueError as exc:
    check("Decision.status outside {approved, declined, deferred} raises", "unsupported value" in str(exc))

check("schemas() is cached (repeated calls return the identical dict object)",
      RS.schemas() is RS.schemas())

# --- t-1355 N2: a refused enum value is told its closed list ---
from detector_verdict import split_items  # noqa: E402
import friction  # noqa: E402

TWO_ENUMS = {"type": "object", "properties": {"s": {"enum": ["y", "x"]}, "t": {"enum": ["p"]}}}
try:
    RS.validate(TWO_ENUMS, {"s": "z", "t": "q"})
    enum_text = ""
except ValueError as exc:
    enum_text = str(exc)
check_eq("N2-R: an enum refusal prints the schema's list in its order",
         split_items(enum_text), ["$.s: unsupported value (one of y, x)", "$.t: unsupported value (one of p)"])
check_eq("N2: every multi-problem refusal is validator friction",
         friction.classify("record_schema.py: " + enum_text), "validator")
try:
    RS.validate({"enum": []}, "anything")
    empty_text = ""
except ValueError as exc:
    empty_text = str(exc)
check_eq("N2-R: an empty enum refuses every value and says so", empty_text,
         "$: unsupported value (one of (none: the list is empty))")
check("the pinned phrase stays", "unsupported value" in empty_text and "unsupported value" in enum_text)
try:
    RS.validate({"enum": [1, "a"]}, 2)
    mixed = ""
except ValueError as exc:
    mixed = str(exc)
check_eq("a non-string enum value is printed as JSON", mixed, "$: unsupported value (one of 1, a)")

finish("test_record_schema")
