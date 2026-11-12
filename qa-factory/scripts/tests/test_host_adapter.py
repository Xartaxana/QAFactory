"""The host's return forms are data with ONE reader: `host_adapter.report_forms` (HF1-5, OH3-13).

`references/host-report-forms.json` names the call a host returns a subagent's report with and the host's
acknowledgement row. A file that cannot be trusted gives (None, reason) - never an exception and never a default
in code - so that a caller takes no tool call for a handback and a probe stays unverified (AR-28).
"""
import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import PLUGIN_ROOT, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

import host_adapter as HA  # noqa: E402

FORMS_FILE = PLUGIN_ROOT / "references" / "host-report-forms.json"
TOOL = "SubagentHandback"


def string_constants(source: str) -> list:
    """Every string constant of a module, docstrings included: the census of AR-1 reads all of them."""
    return [n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def json_strings(value) -> list:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in json_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in json_strings(v)]
    return []


def main() -> None:
    # The shipped file, through the one reader.
    forms, why = HA.report_forms()
    check("the shipped forms file is read", forms is not None and why == "")
    claude = (forms or {}).get("claude") or {}
    check_eq("claude.handback_tool is the host's handback call", claude.get("handback_tool"), TOOL)
    check_eq("claude.handback_ack is the measured acknowledgement form", claude.get("handback_ack"),
             {"field": "success", "value": True})
    check_eq("the claude row carries exactly the five keys that have a reader (AR-22)", sorted(claude),
             ["finished_marker", "handback_ack", "handback_tool", "not_a_person_turn", "person_question_tools"])
    check_eq("claude.finished_marker is the sidecar the host keeps beside a transcript", claude.get("finished_marker"),
             {"file_suffix": ".meta.json", "field": "finished"})
    check_eq("codex.completion_event is the event that ends a turn", ((forms or {}).get("codex") or {}).get("completion_event"),
             "task_complete")
    raw = json.loads(FORMS_FILE.read_text(encoding="utf-8"))
    check_eq("the file holds a note, the launch-id row, the claude row and the codex row only (no answer_fields)",
             sorted(raw), ["claude", "codex", "launch_id_keys", "note"])
    check_eq("RN1-1 the launch-id row names the measured key first, then the two older ones (AR-22: each has a reader)",
             raw["launch_id_keys"], ["agentId", "agent_id", "id"])
    check_eq("the codex row carries exactly the one key that has a reader", sorted(raw["codex"]), ["completion_event"])
    note = raw["note"]
    check("the note names the real reader and both consumers",
          "host_adapter.report_forms()" in note and "host_probe" in note and "dispatch_liveness" in note
          and "host_probe.report_forms" not in note)

    # E2: a file that cannot be trusted gives (None, reason) and never raises.
    root = temp_dir("qa-report-forms-")
    try:
        def write(name, data):
            path = root / name
            if isinstance(data, bytes):
                path.write_bytes(data)
            else:
                path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
            return path

        good = write("good.json", {"claude": {"handback_tool": TOOL}})
        got, why = HA.report_forms(good)
        check("an explicit path is read (the test seam)", got == {"claude": {"handback_tool": TOOL}} and why == "")

        bad = {
            "absent": root / "no-such-file.json",
            "a directory": root,
            "invalid utf-8": write("bytes.json", b"\xff\xfe\x00{"),
            "not JSON": write("text.json", "handback_tool: SubagentHandback"),
            "empty file": write("empty.json", ""),
            "a list, not an object": write("list.json", [TOOL]),
            "a string, not an object": write("str.json", json.dumps(TOOL)),
            "null": write("null.json", "null"),
            "no claude row": write("noclaude.json", {"codex": {"completion_event": "task_complete"}}),
            "claude is a list": write("claudelist.json", {"claude": [TOOL]}),
            "handback_tool missing": write("missing.json", {"claude": {}}),
            "handback_tool empty": write("emptytool.json", {"claude": {"handback_tool": ""}}),
            "handback_tool blank": write("blank.json", {"claude": {"handback_tool": "   "}}),
            "handback_tool a list": write("toollist.json", {"claude": {"handback_tool": [TOOL]}}),
            "handback_tool a number": write("toolnum.json", {"claude": {"handback_tool": 7}}),
            "deeply nested": write("deep.json", "[" * 100000 + "]" * 100000),
        }
        for label, path in bad.items():
            try:
                got, why = HA.report_forms(path)
                ok = got is None and isinstance(why, str) and why != ""
            except Exception as error:  # noqa: BLE001 - the key is exactly that nothing escapes
                ok, why = False, "RAISED " + repr(error)
            check(f"{label}: no forms, with a reason, no exception", ok)

        # HF1-7: a host's whole set of rows, asked by host. A row missing or of the wrong type is no forms FOR THAT HOST.
        full = json.loads(FORMS_FILE.read_text(encoding="utf-8"))
        for host in ("claude", "codex"):
            got, why = HA.report_forms(host=host)
            check(f"host={host}: the shipped file is read whole", got is not None and why == "")
        ack = full["claude"]["handback_ack"]

        def variant(host, key, value):
            data = json.loads(json.dumps(full))
            if value is KeyError:
                data[host].pop(key, None)
            else:
                data[host][key] = value
            return write(f"v-{host}-{key}-{abs(hash(repr(value)))}.json", data)

        cases = [
            (("claude", "handback_ack", KeyError), "handback_ack missing"),
            (("claude", "handback_ack", [ack]), "handback_ack a list"),
            (("claude", "handback_ack", {"value": True}), "handback_ack without a field"),
            (("claude", "handback_ack", {"field": "", "value": True}), "handback_ack with an empty field"),
            (("claude", "handback_ack", {"field": "success"}), "handback_ack without a value"),
            (("claude", "handback_ack", {"field": "success", "value": None}), "handback_ack value null"),
            (("claude", "handback_ack", {"field": "success", "value": [True]}), "handback_ack value a list"),
            (("claude", "finished_marker", KeyError), "finished_marker missing"),
            (("claude", "finished_marker", ".meta.json"), "finished_marker a string"),
            (("claude", "finished_marker", {"field": "finished"}), "finished_marker without a file_suffix"),
            (("claude", "finished_marker", {"file_suffix": ".meta.json", "field": 7}), "finished_marker field a number"),
            (("claude", "handback_tool", KeyError), "handback_tool missing (host=claude)"),
            (("codex", "completion_event", KeyError), "completion_event missing"),
            (("codex", "completion_event", ["task_complete"]), "completion_event a list"),
            (("codex", "completion_event", "  "), "completion_event blank"),
            (("codex", "completion_event", 3), "completion_event a number"),
        ]
        for (host, key, value), label in cases:
            path = variant(host, key, value)
            try:
                got, why = HA.report_forms(path, host=host)
                ok = got is None and f"{host}.{key}" in why
                other = "codex" if host == "claude" else "claude"
                still, _ = HA.report_forms(path, host=other)
            except Exception as error:  # noqa: BLE001
                ok, still = False, "RAISED " + repr(error)
            check(f"{label}: no forms for that host, the reason names the row, no exception", ok)
            check(f"{label}: and the other host's rows still read", still is not None)
        check("host=None judges claude.handback_tool only: a malformed handback_ack does not take the probe's forms away",
              HA.report_forms(variant("claude", "handback_ack", [ack]))[0] is not None)
        for label, path in (("absent", root / "no-such-file.json"), ("not JSON", write("t.json", "x")), ("a list", write("l.json", "[]"))):
            check(f"host=claude, the file {label}: no forms, with a reason", HA.report_forms(path, host="claude")[0] is None
                  and HA.report_forms(path, host="claude")[1] != "")
        check("an unknown host has no reader: no forms, with a reason", HA.report_forms(host="nobody")[0] is None
              and HA.report_forms(host="nobody")[1] != "")

        # RN1-1: the launch id of the host's answer to `Agent`, ONE reader over the data row `launch_id_keys`.
        # K1 kills the mutation "reader returns response.get('agent_id') only".
        for label, response, want in (
                ("K1 the measured key `agentId`", {"isAsync": True, "status": "async_launched", "agentId": "add467ff"}, "add467ff"),
                ("K1 ... foreground form, the same key", {"status": "completed", "agentId": "fg-1", "content": []}, "fg-1"),
                ("K2 the older key `agent_id`", {"agent_id": "old-1"}, "old-1"),
                ("K2 the older key `id`", {"id": "old-2"}, "old-2"),
                ("several keys: the first in row order wins", {"id": "c", "agent_id": "b", "agentId": "a"}, "a"),
                ("an empty value counts as absent", {"agentId": "", "agent_id": "b"}, "b"),
                ("a blank value counts as absent", {"agentId": "  ", "id": "c"}, "c"),
                ("a number is no id", {"agentId": 17}, None),
                ("K3 no id key at all", {"status": "async_launched"}, None),
                ("a string answer carries none", json.dumps({"agentId": "x"}), None),
                ("a list answer carries none", ["x"], None),
                ("None carries none", None, None)):
            try:
                got = HA.launch_id_of(response)
            except Exception as error:  # noqa: BLE001
                got = "RAISED " + repr(error)
            check_eq(f"launch_id_of: {label}", got, want)
        # K4: a row that is missing or malformed is a REFUSAL naming the file and the key, never a hard-coded fallback.
        broken = {"row missing": {"claude": {"handback_tool": TOOL}},
                  "row an empty list": {"launch_id_keys": []},
                  "row a string": {"launch_id_keys": "agentId"},
                  "row holds a blank": {"launch_id_keys": ["agentId", " "]},
                  "row holds a number": {"launch_id_keys": [7]}}
        for label, data in broken.items():
            bad_file = write("launch-" + label.replace(" ", "-") + ".json", data)
            try:
                HA.launch_id_of({"agentId": "x"}, bad_file)
                refusal = "NO REFUSAL"
            except HA.LaunchIdRowRefused as error:
                refusal = str(error)
            except Exception as error:  # noqa: BLE001
                refusal = "WRONG EXCEPTION " + repr(error)
            check(f"K4 [{label}]: refused, naming the file and the row", bad_file.name in refusal and "launch_id_keys" in refusal, refusal)
        for label, path in (("absent file", root / "no-launch-file.json"), ("not JSON", write("launch-text.json", "x")),
                            ("a list", write("launch-list.json", "[]"))):
            try:
                HA.launch_id_of({"agentId": "x"}, path)
                refusal = "NO REFUSAL"
            except HA.LaunchIdRowRefused as error:
                refusal = str(error)
            check(f"K4 [{label}]: refused, naming the file and the row", path.name in refusal and "launch_id_keys" in refusal, refusal)
        custom = write("launch-custom.json", {"launch_id_keys": ["handle"]})
        check_eq("the keys come from the file, not from code: a copy with another row reads the other key",
                 (HA.launch_id_of({"handle": "h", "agentId": "a"}, custom), HA.launch_id_of({"agentId": "a"}, custom)), ("h", None))

        # The module path is the seam the probe tests use; a copy of the shipped file reads the same.
        copy = write("copy.json", FORMS_FILE.read_text(encoding="utf-8"))
        saved = HA.REPORT_FORMS_FILE
        HA.REPORT_FORMS_FILE = copy
        try:
            check_eq("report_forms() follows REPORT_FORMS_FILE", (HA.report_forms()[0] or {}).get("claude", {}).get(
                "handback_tool"), TOOL)
            HA.REPORT_FORMS_FILE = root / "gone.json"
            check_eq("and with the file gone it answers no forms", HA.report_forms()[0], None)
        finally:
            HA.REPORT_FORMS_FILE = saved
    finally:
        cleanup(root)

    # E1 / AR-1 / AR-5: the host's tool name is data. The census reads every string constant of the code that
    # uses and reads the forms; the positive controls prove the census can find the name where it is.
    census_target = {name: string_constants((PLUGIN_ROOT / "scripts" / name).read_text(encoding="utf-8"))
                     for name in ("host_probe.py", "host_adapter.py", "exit_gate.py")}
    for name, constants in census_target.items():
        check(f"no {TOOL} literal remains in {name} (any case)", not any(TOOL.lower() in c.lower() for c in constants))
    check("control: the census finds the literal in a module that holds it", TOOL in string_constants(f"x = '{TOOL}'"))
    check("control: the census reads docstrings too", TOOL in string_constants(f'def f():\n    "{TOOL}"\n'))
    check("control: the same census over the JSON file finds it", TOOL in json_strings(raw))

    finish("test_host_adapter")


if __name__ == "__main__":
    main()
