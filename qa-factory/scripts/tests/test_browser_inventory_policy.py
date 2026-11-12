"""FB-38 (TP2-2406): an exact registered connector call is read-only; arbitrary JS is not.

The browser connector multiplexes reads and writes through one code-taking tool
(`mcp__cua_repl__js`), so its inventory read `await cua.getState();` was refused by
`host_adapter.role_policy` as arbitrary mutating JavaScript, and the runner could not find
its tab. `host_tools.read_only_calls` in the project config names the exact call forms that
are reads; nothing else on that tool, and nothing on an unregistered connector, passes.

`host_tools` is written by a person, so it is the guard's new permitting move: it errs only toward "not a
read". Whatever shape the block has - and an exception in a hook is a PASS (exit 1), so none may raise - a shape
that is not the documented one permits nothing, and the person is told which key it was. On `main` a STRING
`host_tools.read_only` permitted by substring (`"mcp__x__write_doc_all"` let `mcp__x__write_doc` through).
"""
import contextlib
import io
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, check_in, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import host_adapter as H  # noqa: E402

INVENTORY = r"\s*await\s+cua\.getState\(\s*\)\s*;?\s*"
CFG = {"schema_version": 2, "host_tools": {"read_only_calls": {"mcp__cua_repl__js": [INVENTORY]}}}
JS = "mcp__cua_repl__js"
WRITE = "mcp__x__write_doc"


def verdict(tool_input, cfg: dict = CFG, tool: str = JS) -> tuple:
    """(refused, what the guard printed to stderr as a warning). An exception here would be a test failure."""
    event = H.normalize({"host": "codex", "agent_type": "qa-runner", "tool_name": tool, "tool_input": tool_input})
    warned = io.StringIO()
    with patch("hooklib.block", side_effect=PermissionError), contextlib.redirect_stderr(warned):
        try:
            H.role_policy(event, cfg)
        except PermissionError:
            return True, warned.getvalue()
    return False, warned.getvalue()


def refused(code, cfg: dict = CFG, tool: str = JS) -> bool:
    return verdict({"code": code}, cfg, tool)[0]


def main() -> None:
    check_eq("inventory: the exact registered call passes", refused("await cua.getState();"), False)
    check_eq("inventory: whitespace and a missing semicolon are the same call",
             refused(" \nawait cua.getState( )\n"), False)
    check_eq("inventory: without the config entry the same call is still refused",
             refused("await cua.getState();", {"schema_version": 2}), True)
    for code in ('await cua.getState(); await fetch("https://example.test")',
                 'await cua.createBrowserTab("iab", "http://localhost:15173")',
                 'await cua["getState"]()', "cua.getState = evil; await cua.getState()",
                 "await cua.getState(evil())", 'await tab.playwright.evaluate("evil")',
                 "// await cua.getState();\nevil()", "await cua.getState(); evil()"):
        check_eq(f"inventory: other JavaScript is refused (a full match, never a search): {code!r}", refused(code), True)
    check_eq("inventory: the same code on an unregistered connector is refused",
             refused("await cua.getState();", tool="mcp__untrusted__js"), True)
    check_eq("inventory: the text may arrive in `input` too", verdict({"input": "await cua.getState();"})[0], False)
    check_eq("inventory: a tool registered by name still passes whole",
             refused("anything()", {"host_tools": {"read_only": [JS]}}), False)
    check_eq("inventory: a get/list operation name still passes without any config", refused("x", {"schema_version": 2}, "mcp__x__get_doc"), False)
    check_eq("inventory: a mutating one is refused without any config", refused("x", {"schema_version": 2}, WRITE), True)

    # E8, the class: a wrong shape grants nothing, raises nothing, and names its key
    bad_calls = {"a list": [INVENTORY], "a string": INVENTORY, "a number": 7, "true": True, "a list of one pattern": [[INVENTORY]]}
    for label, value in bad_calls.items():
        refused_, warning = verdict({"code": "await cua.getState();"}, {"host_tools": {"read_only_calls": value}})
        check_eq(f"E8: read_only_calls as {label} permits nothing", refused_, True)
        check_in(f"E8: and the warning names host_tools.read_only_calls ({label})", "host_tools.read_only_calls", warning)
    for label, value in (("a string", INVENTORY), ("a dict", {"p": INVENTORY}), ("a number", 5), ("None", None)):
        refused_, warning = verdict({"code": "await cua.getState();"}, {"host_tools": {"read_only_calls": {JS: value}}})
        check_eq(f"E8: a pattern list that is {label} classifies nothing", refused_, True)
    refused_, warning = verdict({"code": "await cua.getState();"}, {"host_tools": {"read_only_calls": {JS: [INVENTORY, 5, None]}}})
    check_eq("E8: a valid pattern beside entries that are not text still counts, and the others are named",
             (refused_, "not strings" in warning), (False, True))
    check_eq("E8: an invalid regex classifies nothing",
             refused("await cua.getState();", {"host_tools": {"read_only_calls": {JS: ["("]}}}), True)
    check_eq("E8: an invalid regex does not hide a valid one beside it",
             refused("await cua.getState();", {"host_tools": {"read_only_calls": {JS: ["(", INVENTORY]}}}), False)
    for label, host_tools in (("a list", ["mcp__x__write_doc"]), ("a string", "read_only"), ("a number", 3), ("true", True)):
        refused_, warning = verdict({"code": "x"}, {"host_tools": host_tools}, WRITE)
        check_eq(f"E8: host_tools as {label} permits nothing and raises nothing", refused_, True)
        check_in(f"E8: and the warning names host_tools ({label})", "host_tools must be an object", warning)
    for label, host_tools in (("None", None), ("absent", {}), ("empty", {"read_only": [], "read_only_calls": {}})):
        cfg = {"schema_version": 2} if host_tools is None else {"schema_version": 2, "host_tools": host_tools}
        refused_, warning = verdict({"code": "x"}, cfg, WRITE)
        check_eq(f"E8: host_tools {label}: nothing permitted, and no warning for a config that is merely absent", (refused_, warning), (True, ""))

    # F-6: host_tools.read_only is the same class - a STRING used to permit by substring, a number raised
    refused_, warning = verdict({"code": "x"}, {"host_tools": {"read_only": WRITE + "_all"}}, WRITE)
    check_eq("F-6: read_only as a STRING that contains the tool name permits nothing (it used to, by substring)", refused_, True)
    check_in("F-6: and the warning names host_tools.read_only", "host_tools.read_only must be a list", warning)
    check_eq("F-6: read_only as the exact tool name, as a string, permits nothing either",
             verdict({"code": "x"}, {"host_tools": {"read_only": WRITE}}, WRITE)[0], True)
    check_eq("F-6: read_only as a number permits nothing and raises nothing",
             verdict({"code": "x"}, {"host_tools": {"read_only": 5}}, WRITE)[0], True)
    check_eq("F-6: read_only as a dict permits nothing", verdict({"code": "x"}, {"host_tools": {"read_only": {WRITE: 1}}}, WRITE)[0], True)
    refused_, warning = verdict({"code": "x"}, {"host_tools": {"read_only": [5, None, WRITE]}}, WRITE)
    check_eq("F-6: a mixed list: the text entry still counts", refused_, False)
    check_in("F-6: and the entries that are not text are named", "not strings", warning)
    check_eq("F-6: a mixed list does not widen: another tool is still refused",
             verdict({"code": "x"}, {"host_tools": {"read_only": [5, None, WRITE]}}, "mcp__x__write_other")[0], True)
    check_eq("F-6: a proper list permits exactly its entries", [verdict({"code": "x"}, {"host_tools": {"read_only": [WRITE]}}, t)[0]
                                                                  for t in (WRITE, WRITE + "_all", "mcp__y__write_doc")], [False, True, True])

    # E10 / E11: the text of the call
    check_eq("E11: code and input both non-empty: not a read, though each alone would match",
             verdict({"code": "await cua.getState();", "input": "await cua.getState();"})[0], True)
    check_eq("E11: one empty, one matching: still a read", verdict({"code": "", "input": "await cua.getState();"})[0], False)
    check_eq("E10: code that is not text makes the text empty: an exact pattern does not match it",
             verdict({"code": {"a": "await cua.getState();"}})[0], True)
    check_eq("E10: code that is not text beside a matching input: not a read (the host may run the code)",
             verdict({"code": ["x"], "input": "await cua.getState();"})[0], True)
    check_eq("E10: a person's own pattern `.*` matches the empty text, as it matches everything",
             verdict({"code": {"a": 1}}, {"host_tools": {"read_only_calls": {JS: [".*"]}}})[0], False)
    check_eq("E10: no code at all: an exact pattern does not match", verdict({})[0], True)
    check_eq("E10: tool_input that is not an object is the empty text (normalize never lets one through; the reader holds anyway)",
             [H._read_only_call(JS, value, H._host_tools(CFG)) for value in ("await cua.getState();", None, ["x"])], [False] * 3)
    check_eq("E8: the accessor itself: a config that is not an object grants nothing",
             [H._host_tools(cfg) for cfg in (None, [], "x")], [{"read_only": [], "read_only_calls": {}}] * 3)
    finish("test_browser_inventory_policy")


if __name__ == "__main__":
    main()
