"""readiness.py — capabilities, not one flag; --require names what is missing and who owns it."""
import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (  # noqa: E402
    PLUGIN_ROOT, check, check_eq, check_in, cleanup, finish, run_script, temp_project,
    use_project,
)

import readiness as R  # noqa: E402


def env_for(root: Path) -> dict:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    return env


def cli(root: Path, *args) -> SimpleNamespace:
    """readiness.py's own main(), in this process: same argv, same exit code, same streams.

    This file used to spawn 25 children of readiness.py — 37 s of a 660 s selftest, to compute
    the same document 25 times over. What the CLI itself promises (silence outside a factory
    project, a JSON document on stdout, exit 1 with the blocker on stderr) is still proven by
    real subprocesses; everything else asks the computation, and this is that computation with
    argv parsing and the exit code left in place, so no assertion below changed its meaning."""
    use_project(root)
    out, err = io.StringIO(), io.StringIO()
    saved_argv, code = sys.argv, 0
    sys.argv = ["readiness.py", *[str(a) for a in args]]
    try:
        with redirect_stdout(out), redirect_stderr(err):
            R.main()
    except SystemExit as exc:
        code = 0 if exc.code is None else (exc.code if isinstance(exc.code, int) else 1)
    finally:
        sys.argv = saved_argv
    return SimpleNamespace(returncode=code, stdout=out.getvalue(), stderr=err.getvalue())


def main() -> None:
    # 1. A project that was never onboarded: silent exit 0 — the plugin's hooks and CLIs fire
    #    in every repository, and must say nothing outside factory projects.
    #    CLI CONTRACT, kept as a real child: silence is a property of the process, not of a
    #    function — an import-time print or a stray warning only shows up in a real run.
    empty = temp_project("qa-factory-readiness-empty-")
    (empty / "qa-factory" / "config.json").unlink()
    try:
        p = run_script("readiness.py", "--json", env=env_for(empty))
        check_eq("no config.json -> exit 0", p.returncode, 0)
        check_eq("no config.json -> no output", (p.stdout + p.stderr).strip(), "")
    finally:
        cleanup(empty)

    root = temp_project("qa-factory-readiness-")
    try:
        # 2. The template config, as onboarding ships it.
        #    CLI CONTRACT, kept as a real child: --json must put a parseable document on
        #    stdout and nothing else, which only a real stdout proves.
        p = run_script("readiness.py", "--json", env=env_for(root))
        check_eq("--json exits 0", p.returncode, 0)
        data = json.loads(p.stdout)
        caps = data["capabilities"]
        template_keys = json.loads((PLUGIN_ROOT / "references" / "templates" / "readiness.json")
                                   .read_text(encoding="utf-8"))["capabilities"].keys()
        expected_capabilities = sorted(template_keys)
        check_eq("every capability of the template is computed", sorted(caps), expected_capabilities)
        for name, entry in caps.items():
            check(f"{name} carries status/owner/note",
                  all(k in entry for k in ("status", "owner", "note")), str(entry))

        check_eq("ticket_adapter `file` is ok out of the box", caps["ticket_adapter"]["status"], "ok")
        check_eq("tests_root that exists is ok", caps["test_repo"]["status"], "ok")
        check_eq("external_writes markdown is ok", caps["external_writes"]["status"], "ok")
        check_eq("schema_version 1 is ok", caps["config_schema"]["status"], "ok")
        check_eq("an unconfigured environment is unknown, not missing",
                 caps["environment"]["status"], "unknown")
        # A project that keeps no case library of its own is a legitimate answer, not a gap:
        # the factory then keeps cases per story, which is what every 0.4.0 config does.
        check_eq("an empty cases_root is not_configured, not missing",
                 caps["case_store"]["status"], "not_configured")

        # 3. --write puts the document where S0 and qa-doctor look for it.
        p = cli(root, "--write")
        written = root / "qa-factory" / "state" / "readiness.json"
        check("--write creates qa-factory/state/readiness.json (machine-local, regenerated)", written.exists(), p.stdout + p.stderr)
        check("...and leaves nothing beside the config (the old place)", not (root / "qa-factory" / "readiness.json").exists())
        check_eq("the written document parses",
                 sorted(json.loads(written.read_text(encoding="utf-8"))["capabilities"]),
                 expected_capabilities)

        # 4. --require passes on available capabilities and fails naming the owner otherwise.
        p = cli(root, "--require", "ticket_adapter,test_repo")
        check_eq("--require on available capabilities exits 0", p.returncode, 0)
        p = cli(root, "--require", "environment")
        check_eq("--require on an unknown (not missing) capability exits 0 with a warning", p.returncode, 0)
        check_in("--require prints the WARN line", "WARN environment", p.stdout)
        # a truly missing capability: tests_root that does not exist
        cfg_path0 = root / "qa-factory" / "config.json"
        cfg0 = json.loads(cfg_path0.read_text(encoding="utf-8"))
        saved_tests_root = cfg0.get("tests_root")
        cfg0["tests_root"] = "no-such-dir"
        cfg_path0.write_text(json.dumps(cfg0, indent=2), encoding="utf-8")
        # CLI CONTRACT, kept as a real child: the blocker must leave the process with exit 1
        # and the reason on stderr — that pair is what every caller of readiness.py reads.
        p = run_script("readiness.py", "--require", "test_repo", env=env_for(root))
        check_eq("--require on a missing capability exits 1", p.returncode, 1)
        check_in("--require names the capability", "test_repo", p.stderr)
        check_in("--require names the owner", "owner:", p.stderr)
        cfg0["tests_root"] = saved_tests_root
        cfg_path0.write_text(json.dumps(cfg0, indent=2), encoding="utf-8")
        p = cli(root, "--require", "teleportation")
        check_eq("--require rejects an unknown capability name", p.returncode, 1)

        # 5. A stale schema names the required version and the keys to add.
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["schema_version"] = 0
        del cfg["external_writes"]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        data = json.loads(cli(root, "--json").stdout)
        schema = data["capabilities"]["config_schema"]
        check_eq("a stale schema_version is missing", schema["status"], "missing")
        check_in("the note names the required version", "requires 1", schema["note"])
        check_in("the migration hint names the missing key", "external_writes",
                 ", ".join(schema.get("migration_hint") or []))

        # 5b. A key added to the template after this schema_version is optional: an install
        # written before it existed must not be told to re-onboard. Without this, shipping
        # one new top-level key turns config_schema `not_configured` everywhere and S0
        # refuses to start, because it --requires config_schema.
        cfg["schema_version"] = 1
        cfg["external_writes"] = {"bugs": "markdown", "cases": "markdown"}
        cfg.pop("factory_may_edit_strategy", None)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        data = json.loads(cli(root, "--json").stdout)
        check_eq("a config without the post-schema key is still ok",
                 data["capabilities"]["config_schema"]["status"], "ok")

        # 5c. `case_id_form` (B-013) is such a key: absent means the default form TC-{nnn}, so an
        # install written before it existed is not told to re-onboard, and a form the factory
        # cannot read is the case_id_form check's to report, never a reason for config_schema.
        cfg.pop("case_id_form", None)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        data = json.loads(cli(root, "--json").stdout)
        check_eq("a config without case_id_form is still ok", data["capabilities"]["config_schema"]["status"], "ok")
        check_eq("with the key absent the capability is ok, the default form",
                 (data["capabilities"]["case_id_form"]["status"], data["capabilities"]["case_id_form"]["note"]),
                 ("ok", "default TC-{nnn}"))
        cfg["case_id_form"] = "{ticket}_TC_"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        data = json.loads(cli(root, "--json").stdout)
        check_eq("an unreadable case_id_form does not turn config_schema", data["capabilities"]["config_schema"]["status"], "ok")
        check_eq("and it is the check's to report: missing, the user's",
                 (data["capabilities"]["case_id_form"]["status"], data["capabilities"]["case_id_form"]["owner"]),
                 ("missing", "user"))
        check("an unreadable form blocks nothing a story requires (--require test_repo,case_store)",
              cli(root, "--require", "test_repo,case_store").returncode == 0)
        cfg.pop("case_id_form", None)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        # 5e. `adapter_forms` (B-405/B-406): the ticket-key form and the delivery commands the gates read. The data answers
        # for every project that names nothing, so an empty vcs, a host the table lacks and a tracker it does not know are
        # `ok` with a note; `missing` is for a value nobody can read (the user's) or the table itself (the factory's).
        template = json.loads((PLUGIN_ROOT / "references" / "templates" / "readiness.json").read_text(encoding="utf-8"))
        check_eq("adapter_forms: the template row is shaped like case_id_form's",
                 (template["capabilities"]["adapter_forms"], template["capabilities"]["adapter_forms"] == template["capabilities"]["case_id_form"]),
                 ({"status": "unknown", "note": ""}, True))

        def forms_entry(ticket=None, vcs=None, **top) -> dict:
            changed = json.loads(json.dumps(cfg))
            changed["adapters"]["ticket"].update(ticket or {})
            changed["adapters"]["vcs"].update(vcs or {})
            changed.update(top)
            cfg_path.write_text(json.dumps(changed, indent=2), encoding="utf-8")
            return json.loads(cli(root, "--json").stdout)["capabilities"]["adapter_forms"]

        entry = forms_entry()
        check_eq("adapter_forms: a template config (empty vcs, `file` tracker) is ok, the factory's",
                 (entry["status"], entry["owner"]), ("ok", "factory"))
        check_in("adapter_forms: the note names the key form and where it comes from", "tracker kind `file`", entry["note"])
        check_in("adapter_forms: ... and the delivery commands the gate knows", "glab mr create", entry["note"])
        check_in("adapter_forms: an EMPTY vcs says the gate knows only the data defaults and names the key that adds more",
                 "only the data defaults", entry["note"])
        check_in("adapter_forms: ... naming adapters.vcs.delivery_commands", "adapters.vcs.delivery_commands", entry["note"])
        entry = forms_entry(vcs={"name": "gitlab"})
        check_eq("adapter_forms: a host the table holds has no such sentence", ("only the data defaults" in entry["note"], entry["status"]),
                 (False, "ok"))
        entry = forms_entry(vcs={"name": "glab"})
        check_eq("adapter_forms: the program alias is read as its host", "only the data defaults" in entry["note"], False)
        entry = forms_entry(vcs={"name": "bitbucket"})
        check_eq("adapter_forms: a host the table lacks is ok with the sentence (not missing)",
                 (entry["status"], "only the data defaults" in entry["note"]), ("ok", True))
        entry = forms_entry(ticket={"name": "linear"})
        check_eq("adapter_forms edge 3: an unknown tracker is ok, and the note says the Jira form is a guess",
                 (entry["status"], "a guess" in entry["note"], "adapters.ticket.key_pattern" in entry["note"]), ("ok", True, True))
        entry = forms_entry(ticket={"name": "github"}, vcs={"name": "github", "delivery_commands": ["bb pr create"]})
        check_eq("adapter_forms: a project's own command is listed with its source",
                 (entry["status"], "bb pr create" in entry["note"], "adapters.vcs.delivery_commands" in entry["note"],
                  "like #123" in entry["note"]), ("ok", True, True, True))
        entry = forms_entry(ticket={"name": "github", "key_pattern": "[A-Z]+-\\d+"})
        check_eq("adapter_forms edge 5: a key_pattern on a kind the table knows is ignored, said in words, ok",
                 (entry["status"], "ignored" in entry["note"]), ("ok", True))
        for label, ticket_row, vcs_row, needle in (
                ("an invalid key_pattern", {"name": "linear", "key_pattern": "([A-Z]+)-\\d+"}, {}, "adapters.ticket.key_pattern"),
                ("a key_pattern that does not compile", {"name": "linear", "key_pattern": "[A-Z"}, {}, "adapters.ticket.key_pattern"),
                ("a key_pattern that is not text", {"name": "linear", "key_pattern": 5}, {}, "adapters.ticket.key_pattern"),
                ("a one-word delivery command", {}, {"delivery_commands": ["git"]}, "adapters.vcs.delivery_commands"),
                ("a delivery command that is not text", {}, {"delivery_commands": [5]}, "adapters.vcs.delivery_commands")):
            entry = forms_entry(ticket=ticket_row, vcs=vcs_row)
            check_eq(f"adapter_forms: {label} is `missing`, the user's, naming the key",
                     (entry["status"], entry["owner"], needle in entry["note"], needle in entry["remedy"]["need"]),
                     ("missing", "user", True, True))
        check("adapter_forms: an unreadable value blocks nothing a story requires (--require test_repo,case_store)",
              cli(root, "--require", "test_repo,case_store").returncode == 0)
        entry = forms_entry(vcs={"name": "gitlab", "method": "mcp_tool"})
        check_eq("adapter_forms edge F14: an MCP route is `unknown` (the gate cannot see it), never missing",
                 (entry["status"], entry["owner"], "adapters.vcs.method is mcp_tool" in entry["note"]), ("unknown", "factory", True))
        check_eq("adapter_forms: agent and skill routes too",
                 [forms_entry(vcs={"method": m})["status"] for m in ("agent", "skill")], ["unknown", "unknown"])
        check_eq("adapter_forms: a `command` route is not unknown", forms_entry(vcs={"method": "command"})["status"], "ok")
        check_eq("adapter_forms: a config with no adapters at all is ok (the defaults), not a crash",
                 forms_entry(adapters={})["status"], "ok")
        saved_table = R.adapter_forms.TABLE_PATH
        R.adapter_forms.TABLE_PATH = root / "no-such-table.json"
        try:
            entry = R.check_adapter_forms(cfg)
        finally:
            R.adapter_forms.TABLE_PATH = saved_table
        check_eq("adapter_forms edge 12: a table that cannot be read is `missing`, the FACTORY's",
                 (entry["status"], entry["owner"], "adapter-forms.json" in entry["note"]), ("missing", "factory", True))
        check_in("adapter_forms edge 12: ... and the remedy says what still works (the floor)", "built-in floor", entry["remedy"]["blocks"])
        import re as regex   # `re` is imported further down in this function: a local name, so not usable here
        required = regex.findall(r"--require\s+\S+", (PLUGIN_ROOT / "skills" / "qa-story" / "phases" / "s0.md").read_text(encoding="utf-8"))
        check("adapter_forms: it is in no --require list of S0 (a capability, never a blocker)",
              any("ticket_adapter" in line for line in required) and not any("adapter_forms" in line for line in required), str(required))
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        # 5d. t-232 C8: the live config of a 0.7.x project (a blanked copy of its key shape) was
        # `not_configured` over `handoffs`, `prompts` and `retro`, which the old tuple never named.
        # The list is DATA now (references/config-keys.json, absent_means), derived into
        # OPTIONAL_TOP_KEYS; builder-rules p.9 - a project onboarded on 0.7.x works without re-onboarding.
        live_shape = json.loads((PLUGIN_ROOT / "scripts" / "tests" / "fixtures" / "config-live-shape.json")
                                .read_text(encoding="utf-8"))
        table = json.loads((PLUGIN_ROOT / "references" / "config-keys.json").read_text(encoding="utf-8"))
        absent_from_live = [k for k in json.loads((PLUGIN_ROOT / "references" / "templates" / "config.json")
                                                  .read_text(encoding="utf-8"))
                            if not k.endswith("_note") and k not in live_shape]
        check("C8 setup: the live-shaped config lacks handoffs, prompts and retro",
              {"handoffs", "prompts", "retro"} <= set(absent_from_live), str(absent_from_live))
        cfg_path.write_text(json.dumps(live_shape, indent=2), encoding="utf-8")
        schema = json.loads(cli(root, "--json").stdout)["capabilities"]["config_schema"]
        check_eq("C8: the live-shaped config is ok, not not_configured", schema["status"], "ok")
        check_eq("C8: OPTIONAL_TOP_KEYS is derived from the table's absent_means: default",
                 sorted(R.OPTIONAL_TOP_KEYS),
                 sorted(k for k, m in table["keys"].items() if "." not in k and m["absent_means"] == "default"))
        check("C8: every key the live-shaped config lacks is one the table calls default",
              all(table["keys"][k]["absent_means"] == "default" for k in absent_from_live))
        # a REQUIRED key missing stays not_configured and says which one
        short = dict(live_shape)
        del short["journal_path"]
        cfg_path.write_text(json.dumps(short, indent=2), encoding="utf-8")
        schema = json.loads(cli(root, "--json").stdout)["capabilities"]["config_schema"]
        check_eq("C8: a config missing a required key is not_configured", schema["status"], "not_configured")
        check("C8: ... and the note and the hint name the key",
              "journal_path" in schema["note"] and schema.get("migration_hint") == ["journal_path"], str(schema))
        # a schema other than this plugin's, or none, is named - not a crash
        for found, written in ((2, {**live_shape, "schema_version": 2}),
                               (None, {k: v for k, v in live_shape.items() if k != "schema_version"})):
            cfg_path.write_text(json.dumps(written, indent=2), encoding="utf-8")
            schema = json.loads(cli(root, "--json").stdout)["capabilities"]["config_schema"]
            check(f"schema_version {found!r} is named in the note and is `missing`, no crash",
                  schema["status"] == "missing" and repr(found) in schema["note"], str(schema))
        # an unreadable key table is unknown, never an empty list that passes everything (FR-41)
        real_keys = R.config_keys
        R.config_keys = lambda: (_ for _ in ()).throw(ValueError("references/config-keys.json is unreadable"))
        try:
            unreadable = R.check_config_schema(live_shape)
        finally:
            R.config_keys = real_keys
        check("C8: an unreadable key table makes config_schema unknown, naming the file",
              unreadable["status"] == "unknown" and "config-keys.json" in unreadable["note"], str(unreadable))
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        # 6. A tests_root that does not exist is a blocker owned by the user.
        cfg["schema_version"] = 1
        cfg["external_writes"] = {"bugs": "markdown", "cases": "markdown"}
        cfg["tests_root"] = "no/such/place"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        data = json.loads(cli(root, "--json").stdout)
        check_eq("a missing tests_root is 'missing'", data["capabilities"]["test_repo"]["status"], "missing")
        check_eq("and it is the user's to fix", data["capabilities"]["test_repo"]["owner"], "user")

        # 6b. The case store: a project's own library is a fact onboarding records, and the
        # one place it may not point is application code — the factory never writes there,
        # and a config key cannot grant what P-00 refuses.
        cfg["tests_root"] = "tests"
        cfg["cases_root"] = "docs/test-cases"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        data = json.loads(cli(root, "--json").stdout)
        check_eq("a cases_root that does not exist is 'missing'",
                 data["capabilities"]["case_store"]["status"], "missing")
        (root / "docs" / "test-cases").mkdir(parents=True, exist_ok=True)
        data = json.loads(cli(root, "--json").stdout)
        check_eq("a cases_root that exists is ok", data["capabilities"]["case_store"]["status"], "ok")
        cfg["app_root"] = "."
        cfg["protected_app_paths"] = ["docs"]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["case_store"]
        check_eq("a cases_root inside application code is refused", entry["status"], "missing")
        check_in("and the message names the protected path", "protected_app_path", entry["note"])
        cfg["protected_app_paths"] = []
        cfg["cases_root"] = ""
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        # 7. A non-markdown channel without a configured adapter is not configured.
        cfg["tests_root"] = "tests"
        cfg["external_writes"] = {"bugs": "jira", "cases": "markdown"}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        data = json.loads(cli(root, "--json").stdout)
        check_eq("a jira channel with a `file` ticket adapter is not_configured",
                 data["capabilities"]["external_writes"]["status"], "not_configured")

        # 7b. An agent-reached tracker needs the name to dispatch, or it is not configured.
        cfg["external_writes"] = {"bugs": "markdown", "cases": "markdown"}
        cfg["adapters"] = {"ticket": {"name": "jira", "status": "configured",
                                      "method": "agent", "invoke": ""}}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["ticket_adapter"]
        check_eq("an agent-reached tracker with no invoke is not_configured",
                 entry["status"], "not_configured")
        check_in("and the note names the key to fill", "invoke", entry["note"])

        cfg["adapters"]["ticket"]["invoke"] = "jira-assistant"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["ticket_adapter"]
        # Not a read route since 0.7.7: an assistant returns no attachments and cannot reach a
        # parent or a linked ticket, so the capability is `not_configured` with the remedy
        # (direct_api, onboarding) and the person owns it. Writing through an agent is unchanged.
        check_eq("with a name to dispatch it is not_configured, not ok", entry["status"], "not_configured")
        check_eq("and it is the person's to configure", entry["owner"], "user")
        check("and the note names the read route to configure", "direct_api" in entry["note"], entry["note"])

        # 7b-2. TP2-2553: the same answer for an MCP tool of the orchestrator's own
        # session. It used to be `unknown / orchestrator` — "S0 verifies it by fetching the
        # ticket once" — and S0's fetch did succeed, because the orchestrator held the tool.
        # qa-scout, dispatched at S1, held nothing: the dispatch stalled and 2 h 54 min went
        # on tickets fetched by hand. A route only the caller can use is not the role's route.
        cfg["adapters"] = {"ticket": {"name": "jira", "status": "configured",
                                      "method": "mcp_tool", "mcp_tool": "jira_get_issue"}}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["ticket_adapter"]
        check_eq("an mcp_tool tracker with no direct_api is not_configured, not unknown",
                 entry["status"], "not_configured")
        check_eq("and the person owns it, not the orchestrator", entry["owner"], "user")
        check_in("and the note names the tool it will not call", "jira_get_issue", entry["note"])
        check_in("and the read route to record", "adapters.ticket.direct_api", entry["note"])
        steps = " | ".join(entry["remedy"]["steps"])
        check_in("the remedy names the onboarding skill", "/qa-factory:qa-onboarding", steps)
        check_in("and the way a person's word passes it", 'waiver.py --stage S1 --block "tracker route"',
                 steps)
        check_eq("and says what it costs", entry["remedy"]["blocks"],
                 "S1 source collection by qa-scout")
        # It is a warning, not a halt: S0 keeps going and says it at the gate.
        check_eq("--require ticket_adapter warns and exits 0 on it",
                 cli(root, "--require", "ticket_adapter").returncode, 0)

        # 7c. The pilot bug (QAF adapter finding): a command adapter marked `configured` for a
        #     CLI that is not installed. `status` is the config's claim; PATH is the evidence.
        cfg["adapters"] = {"ticket": {"name": "jira", "status": "configured",
                                      "method": "command",
                                      "command": "dmtools-not-installed jira get {key}"}}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["ticket_adapter"]
        check_eq("a command adapter whose executable is not on PATH is missing",
                 entry["status"], "missing")
        check_in("and the note names the executable", "dmtools-not-installed", entry["note"])
        check_in("and says it was declared, not detected", "DECLARED", entry["note"])

        # --require blocks on it: this is the halt that used to happen in S0 instead.
        proc = cli(root, "--require", "ticket_adapter")
        check_eq("--require ticket_adapter fails on it", proc.returncode, 1)

        # The same config with a real executable is ok, and the note carries where it was found.
        cfg["adapters"]["ticket"]["command"] = "git log {key}"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["ticket_adapter"]
        check_eq("a command adapter whose executable exists is ok", entry["status"], "ok")
        check_in("and the note is evidence, not a restatement of the config", "found at",
                 entry["note"])

        # 7d. An agent-delivered write channel no longer reads as an unconfigured channel.
        cfg["adapters"] = {"ticket": {"name": "file", "status": "configured"}}
        cfg["external_writes"] = {"bugs": "markdown", "cases": "markdown",
                                  "channels": {"jira": {"method": "agent",
                                                        "invoke": "jira-assistant"}}}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["external_writes"]
        check_eq("a channels[] delivery map is not itself a channel", entry["status"], "ok")
    finally:
        cleanup(root)

    # 8. app_repo is evidence that application code is PRESENT, not that a path resolves.
    #    Regression for QAF-11: onboarding run inside a test-only repository left app_root "."
    #    (which always exists) and never asked where the application lives, and readiness
    #    called that `ok`.
    root = temp_project("qa-factory-readiness-apprepo-")
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

        def app_repo(c: dict) -> dict:
            cfg_path.write_text(json.dumps(c, indent=2), encoding="utf-8")
            return json.loads(cli(root, "--json").stdout)["capabilities"]["app_repo"]

        # 8a. The template default: app_root "." exists, but nothing marks code in it.
        entry = app_repo(cfg)
        check_eq("a bare app_root '.' is not evidence of application code",
                 entry["status"], "not_configured")
        check_eq("and it is the user's to answer", entry["owner"], "user")
        check_in("the note names the field that fixes it", "code_repos", entry["note"])

        # 8b. Unconfigured, not missing: a story is warned, not blocked.
        p = cli(root, "--require", "app_repo")
        check_eq("--require app_repo on an unconfigured app repo exits 0", p.returncode, 0)
        check_in("--require warns instead of blocking", "WARN app_repo", p.stdout)

        # 8c. Single-root project: app_root "." plus a protected path that exists.
        (root / "src").mkdir()
        cfg["protected_app_paths"] = ["src"]
        check_eq("app_root with a protected path on disk is ok", app_repo(cfg)["status"], "ok")

        # 8d. The same config pointed at a directory that is not there is a real blocker.
        cfg["protected_app_paths"] = ["no-such-src"]
        entry = app_repo(cfg)
        check_eq("protected paths that do not exist under app_root is 'missing'",
                 entry["status"], "missing")
        check_in("and the note names the path", "no-such-src", entry["note"])

        # 8e. Separate application checkout recorded by onboarding topic 1.
        (root / "vendor" / "testproject1").mkdir(parents=True)
        cfg["protected_app_paths"] = []
        cfg["code_repos"] = [{"name": "testproject1", "path": "vendor/testproject1", "default_branch": "main"}]
        entry = app_repo(cfg)
        check_eq("a code_repos path that exists is ok", entry["status"], "ok")
        check_in("the note names the repository", "testproject1", entry["note"])

        # 8f. A code_repos path nobody checked out is missing, not silently ok.
        cfg["code_repos"] = [{"name": "testproject1-ui", "path": "../no-such-checkout"}]
        cfg["app_root"] = "../no-such-root"
        check_eq("a code_repos path that does not exist is 'missing'",
                 app_repo(cfg)["status"], "missing")
    finally:
        cleanup(root)

    # 9. Direct Jira readiness is derived from a recent probe receipt whose settings and
    # named checks match config. Credentials alone never fabricate an available capability.
    root = temp_project("qa-factory-readiness-jira-direct-")
    old_user, old_secret = os.environ.get("QA_JIRA_USER"), os.environ.get("QA_JIRA_SECRET")
    os.environ["QA_JIRA_USER"] = "reader@example.invalid"
    os.environ["QA_JIRA_SECRET"] = "fixture-secret"
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["adapters"] = {"ticket": {"name": "jira", "direct_api": {
            "base_url": "https://jira.example.invalid", "api_version": "2",
            "auth_type": "basic_token", "username_ref": "QA_JIRA_USER",
            "secret_ref": "QA_JIRA_SECRET", "acceptance_criteria_fields": ["customfield_42"]}}}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        receipt_path = root / "qa-factory" / "state" / "integrations" / "jira-direct-probe.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt = {"schema_version": 1, "capability": "jira_direct_read", "status": "available",
                   "checked_at": datetime.now(timezone.utc).isoformat(),
                   "base_url": "https://jira.example.invalid", "api_version": "2",
                   "auth_type": "basic_token", "username_ref": "QA_JIRA_USER",
                   "secret_ref": "QA_JIRA_SECRET", "checks": [
                       {"name": "server_info", "status": "available"},
                       {"name": "authenticated_identity", "status": "available"},
                       {"name": "sample_issue", "status": "available"},
                       {"name": "paginated_comments", "status": "available"},
                       {"name": "attachment_original", "status": "not_applicable"}]}
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["jira_direct_api"]
        check_eq("matching recent direct Jira probe is ready", entry["status"], "ok")
        check_eq("readiness cites the direct probe receipt", entry.get("evidence_ref"),
                 "state/integrations/jira-direct-probe.json")

        # `method` names the WRITE channel; a usable direct_api is the READ route whatever it
        # says, so the same proof makes ticket_adapter ok on the 2553 config (mcp_tool).
        cfg["adapters"]["ticket"]["method"] = "mcp_tool"
        cfg["adapters"]["ticket"]["mcp_tool"] = "jira_get_issue"
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["ticket_adapter"]
        check_eq("an mcp_tool tracker with a proven direct_api is ok", entry["status"], "ok")
        cfg["adapters"]["ticket"].pop("method")
        cfg["adapters"]["ticket"].pop("mcp_tool")
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        receipt["checked_at"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["jira_direct_api"]
        check_eq("stale direct Jira probe returns unknown", entry["status"], "unknown")
        receipt["checked_at"] = datetime.now(timezone.utc).isoformat()
        receipt["base_url"] = "https://other.example.invalid"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["jira_direct_api"]
        check_eq("probe whose settings differ from config returns unknown", entry["status"], "unknown")

        # t-287 item 2: a recorded direct_api that lacks keys (the template's stub on an old config) is named by key,
        # with the SAME remedy as the other read-route gap (`ticket-read-route`: onboarding topic 7, or the person's word)
        route = R.session_route("jira", "direct_api", "")["remedy"]
        stub = {"custom_fields": [], "acceptance_headings": []}
        cfg["adapters"]["ticket"]["direct_api"] = stub
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        caps = json.loads(cli(root, "--json").stdout)["capabilities"]
        for name in ("jira_direct_api", "ticket_adapter"):
            entry = caps[name]
            check_eq(f"t-287 item 2: the template stub -> {name} is not_configured, owner user",
                     (entry["status"], entry["owner"]), ("not_configured", "user"))
            check_eq(f"t-287 item 2: {name} names every missing key by its full name",
                     [f"adapters.ticket.direct_api.{key}" in entry["note"] for key in ("base_url", "auth_type", "secret_ref", "username_ref")], [True] * 4)
            check_eq(f"t-287 item 2: {name} carries the `ticket-read-route` remedy", entry.get("remedy"), route)
        check_eq("t-287 item 2: the stub case no longer says only 'contract incomplete'", "lacks" in caps["jira_direct_api"]["note"], True)
        cfg["adapters"]["ticket"]["direct_api"] = {"base_url": "https://jira.example.invalid", "auth_type": "bearer"}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["jira_direct_api"]
        check_eq("t-287 item 2: a bearer config with no secret names `secret_ref` only",
                 [key for key in ("base_url", "auth_type", "secret_ref", "username_ref") if f"direct_api.{key}" in entry["note"]], ["secret_ref"])
        cfg["adapters"]["ticket"]["direct_api"] = {"base_url": "https://jira.example.invalid", "auth_type": "oauth", "secret_ref": "QA_JIRA_SECRET"}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["jira_direct_api"]
        check_eq("t-287 item 2: an auth_type that is neither basic_token nor bearer is named, and nothing else",
                 (entry["status"], "direct_api.auth_type" in entry["note"], "direct_api.base_url" in entry["note"]), ("not_configured", True, False))
        cfg["adapters"]["ticket"]["direct_api"] = {}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        entry = json.loads(cli(root, "--json").stdout)["capabilities"]["jira_direct_api"]
        check_eq("t-287 item 2 (unchanged): direct_api {} keeps its own sentence", (entry["status"], "required even with Jira Assistant" in entry["note"]), ("not_configured", True))
    finally:
        if old_user is None:
            os.environ.pop("QA_JIRA_USER", None)
        else:
            os.environ["QA_JIRA_USER"] = old_user
        if old_secret is None:
            os.environ.pop("QA_JIRA_SECRET", None)
        else:
            os.environ["QA_JIRA_SECRET"] = old_secret
        cleanup(root)

    # 9. An experiment (t-017 D3, B-003): `--no-trace` closes the two outward capabilities for the
    #    run and never calls the tracker-write probe. The control is the same project without the
    #    flag: the probe IS called and the channel with no adapter is a gap.
    import tracker_write
    root = temp_project("qa-factory-readiness-no-trace-")
    held_probe, probes = tracker_write.probe, []
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["external_writes"] = {"bugs": "jira", "cases": "markdown",
                                  "channels": {"jira": {"method": "agent", "invoke": "jira-assistant"}}}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        def fake_probe(*args, **kwargs):
            probes.append(kwargs.get("where"))
            return {"status": "unverified", "reason": "nobody asked", "ask": "may it create issues?",
                    "invoke": "jira-assistant"}
        tracker_write.probe = fake_probe
        caps = json.loads(cli(root, "--json").stdout)["capabilities"]
        check_eq("control: the tracker-write probe is called", probes, ["doctor"])
        check_eq("control: an unconfigured jira channel is a gap", caps["external_writes"]["status"], "not_configured")
        check("control: and its note is not the closed one", "closed for this run" not in caps["external_writes"]["note"])
        probes.clear()
        p = cli(root, "--json", "--no-trace")
        caps = json.loads(p.stdout)["capabilities"]
        check_eq("--no-trace: the tracker-write probe is not called", probes, [])
        for name in ("tracker_write", "external_writes"):
            check_eq(f"--no-trace: {name} is not_configured", caps[name]["status"], "not_configured")
            check_eq(f"--no-trace: {name} is not applicable", caps[name].get("applicable"), False)
            check_in(f"--no-trace: {name} says it is closed for this run",
                     "closed for this run: an experiment writes nothing outside the project", caps[name]["note"])
            check_eq(f"--no-trace: {name} is no defect", caps[name]["remedy"]["kind"], "not_a_defect")
        check_eq("--no-trace: every capability of the template is still computed",
                 sorted(caps), sorted(json.loads(cli(root, "--json").stdout)["capabilities"]))
        p = cli(root, "--require", "ticket_adapter,test_repo,config_schema", "--no-trace")
        check_eq("--no-trace --require: the S0 call still exits 0 on what the story needs", p.returncode, 0)
        p = cli(root, "--require", "tracker_write,external_writes", "--no-trace")
        check_eq("--no-trace --require of the closed two: a warning, never a block", p.returncode, 0)
    finally:
        tracker_write.probe = held_probe
        cleanup(root)

    # 10. t-232 F1 (Lead's decision after t-260): the tracker-write receipt is a probe cache in state/; the
    #     person's answer is carried in the approvals log. The doctor's row reads the receipt's own `answered`,
    #     else the log's latest line, else asks. Both worlds: an old receipt with `answered` and no log line.
    agent_cfg = {"external_writes": {"bugs": "jira", "cases": "markdown",
                                     "channels": {"jira": {"method": "agent", "invoke": "jira-assistant"}}}}
    root = temp_project("qa-factory-readiness-answer-")
    try:
        row = R.check_tracker_write(agent_cfg, root)
        check_eq("nothing recorded: the row is unknown and the orchestrator is asked", (row["status"], row["remedy"]["owner"]), (R.UNKNOWN, "orchestrator"))
        check_in("the verify text names the receipt where it lives and the log the answer is carried in",
                 "state/integrations/tracker-write.json and the answer recorded in qa-factory/records/onboarding-approvals.jsonl", row["remedy"]["verify"])
        tracker_write.record(agent_cfg, root, tracker_write.CONFIRMED, "jira-assistant answered: writes: yes")
        row = R.check_tracker_write(agent_cfg, root)
        check_eq("the person's answer recorded: the row is ok, citing the receipt", (row["status"], row.get("evidence_ref")),
                 (R.OK, "state/integrations/tracker-write.json"))
        os.unlink(tracker_write.receipt_path(root))
        check_eq("the receipt gone (a clone has no state/): the row is still ok, from the approvals log",
                 R.check_tracker_write(agent_cfg, root)["status"], R.OK)
    finally:
        cleanup(root)
    root = temp_project("qa-factory-readiness-answer-old-")
    try:
        receipt = tracker_write.receipt_path(root)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        fp = tracker_write.fingerprint(agent_cfg)
        receipt.write_text(json.dumps({"channel": "jira", "status": "unverified", "fingerprint": fp, "checked_at": "2026-09-01T10:00:00+00:00",
                                       "answered": {"status": "confirmed", "fingerprint": fp, "at": "2026-09-01T10:00:00+00:00",
                                                    "reason": "answered before the log existed"}}), encoding="utf-8")
        check_eq("an old receipt that carries `answered`, with no approvals log at all, keeps working: ok",
                 R.check_tracker_write(agent_cfg, root)["status"], R.OK)
        check_eq("...and reading it started no records/ folder", (root / "qa-factory" / "records").exists(), False)
        legacy = root / "qa-factory" / "state" / "onboarding-approvals.jsonl"
        legacy.write_text('{"schema_version": 1, "approval_ref": "x", "status": "approved"}\n', encoding="utf-8")
        os.unlink(receipt)
        check_in("an older project's log is named where it really is",
                 "qa-factory/state/onboarding-approvals.jsonl", R.check_tracker_write(agent_cfg, root)["remedy"]["verify"])
    finally:
        cleanup(root)

    # 11. t-264 (FR-37): the pointer a cut answer carries names the journal where THIS project keeps it.
    import brief_pack
    long_text = "x" * 20001
    root = temp_project("qa-factory-readiness-journal-")
    try:
        check_in("a fresh project: the layout's own place", "the whole text is in qa-factory/records/journal.jsonl]",
                 brief_pack.person_words_whole(long_text, root))
        (root / "qa-factory" / "state" / "journal.jsonl").write_text("{}\n", encoding="utf-8")
        check_in("an older project (the journal still in state/): the real path, not the layout's",
                 "the whole text is in qa-factory/state/journal.jsonl]", brief_pack.person_words_whole(long_text, root))
        (root / "qa-factory" / "records").mkdir()
        (root / "qa-factory" / "records" / "journal.jsonl").write_text("{}\n", encoding="utf-8")
        os.utime(root / "qa-factory" / "state" / "journal.jsonl", (1, 1))
        check_in("a move done (the newer copy is in records/): that one", "qa-factory/records/journal.jsonl]",
                 brief_pack.person_words_whole(long_text, root))
        check_in("no project given: the layout's own spelling", "the whole text is in qa-factory/records/journal.jsonl]",
                 brief_pack.person_words_whole(long_text))
    finally:
        cleanup(root)

    # 12. t-264: the texts a role or a person reads do not name the OLD place of a carried record as if it were the
    #     current one. A line that says it is the older layout ("an older project", "previous layout") may.
    import re
    old_spelling = re.compile(r"(?<![\w/.-])(?:qa-factory/)?state/(?:journal\.jsonl|estimation-ledger\.jsonl|coverage-map\.md|"
                              r"project-decisions\.json|onboarding-approvals\.jsonl|config-migrations)|qa-factory/readiness\.json")

    def stale_lines(text: str) -> list:
        return [ln.strip() for ln in text.splitlines() if old_spelling.search(ln) and not re.search(r"older project|previous layout", ln, re.I)]
    check_eq("the scan finds the old spelling: `qa-factory/state/journal.jsonl`, `state/estimation-ledger.jsonl`, `qa-factory/readiness.json`",
             [len(stale_lines(t)) for t in ("see `qa-factory/state/journal.jsonl`", "append to `state/estimation-ledger.jsonl`", "reads qa-factory/readiness.json")], [1, 1, 1])
    check_eq("...and lets a line through that names it as the older layout, or the new spelling",
             [stale_lines(t) for t in ("`records/journal.jsonl` (an older project: `state/journal.jsonl`)", "(previous layout) state/coverage-map.md",
                                       "`qa-factory/records/journal.jsonl`", "the `state/cost/` folder")], [[], [], [], []])
    fixed = ["agents/qa-bug-reporter.md", "agents/qa-retro-analyst.md", "references/artifact-contract.md", "references/common-rules.md",
             "references/templates/retro.md", "skills/qa-story/SKILL.md", "skills/qa-story/phases/s9.md",
             "skills/qa-onboarding/phases/p3-summary-gate.md", "INSTALL.md", "evals/plugin-eval-benchmark.json",
             "skills/qa-story/evals/evals.json", "references/stages.json", "references/artifact-writers.json"]
    texts = {rel: (PLUGIN_ROOT / rel).read_text(encoding="utf-8") for rel in fixed}
    check_eq("no text this task fixed names the old place of a record as the current one (file: line)",
             [f"{rel}: {ln[:90]}" for rel, text in texts.items() for ln in stale_lines(text)], [])
    check("the control: the same files DO carry the new spelling (the scan reads the real files)",
          all("records/journal.jsonl" in texts[rel] for rel in ("references/artifact-contract.md", "references/stages.json", "skills/qa-story/phases/s9.md")))

    # 13. The doctor resolves the Jira credential names the way the reader does: a name the
    # process lacks (or holds empty) is looked up in the project's configured env file, so the
    # two records of one fact no longer disagree ("not set in this session" while the reader
    # succeeds). Fixture values are made up; no value may reach the result.
    root = temp_project("qa-factory-readiness-jira-envfile-")
    names = ("QA_RDY_FILE_USER", "QA_RDY_FILE_SECRET")
    saved = {n: os.environ.pop(n, None) for n in names}
    saved_unreachable = R.host_unreachable
    R.host_unreachable = lambda _root, _url: None  # no network probe in a unit test
    try:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        direct = {"base_url": "https://jira.example.invalid", "api_version": "2",
                  "auth_type": "basic_token", "username_ref": names[0], "secret_ref": names[1]}
        cfg["adapters"] = {"ticket": {"name": "jira", "direct_api": direct}}
        (root / "creds.env").write_text(f"{names[0]}=file-user-value\n{names[1]}=file-secret-value\n",
                                        encoding="utf-8")

        def doctor(environment):
            c = dict(cfg)
            c.pop("environment", None)
            if environment is not None:
                c["environment"] = environment
            return R.check_jira_direct(c, root)

        gone = doctor(None)
        check_eq("no environment block, name nowhere -> missing as before", gone["status"], "missing")
        check_in("the missing message is unchanged", "not set in this session", json.dumps(gone))
        check_eq("an env file that does not exist -> missing as before",
                 doctor({"env_file": "absent.env"})["status"], "missing")

        from_file = doctor({"env_file": "creds.env"})
        check_eq("names only in the configured env file -> present", from_file["status"], "unknown")
        check("and the doctor does not claim they are unset", "not set in this session" not in json.dumps(from_file))
        check_in("it says in plain words where they were found", "configured env file", from_file["note"])
        check("no value of the file reaches the result",
              "file-user-value" not in json.dumps(from_file) and "file-secret-value" not in json.dumps(from_file))
        listed = doctor({"env_files": ["absent.env", "creds.env"]})
        check_eq("env_files are read too", listed["status"], "unknown")

        os.environ[names[1]] = "process-secret-value"
        try:
            os.environ[names[0]] = ""
            mixed = doctor({"env_file": "creds.env"})
            check_eq("an empty process value is filled from the file, a set one stays", mixed["status"], "unknown")
            check("a value from the process is never printed", "process-secret-value" not in json.dumps(mixed))
            os.environ[names[0]] = "process-user-value"
            plain = doctor(None)
            check_eq("both names in the process environment -> as today", plain["status"], "unknown")
            check("and nothing is said about an env file", "configured env file" not in plain["note"])
            check_eq("the result keeps the same keys whichever place the names came from",
                     sorted(from_file), sorted(plain))
        finally:
            os.environ.pop(names[0], None)
            os.environ.pop(names[1], None)
    finally:
        R.host_unreachable = saved_unreachable
        for n, v in saved.items():
            if v is not None:
                os.environ[n] = v
        cleanup(root)

    project_dependencies_capability()
    vcs_api_from_receipts()
    device_stand_environment()
    finish("test_readiness")


def device_stand_environment() -> None:
    """EP1-41c: `check_environment` of a project with a device stand (a row naming a `surface` whose table row is `hands: driver`).
    The false green it closes: a row with no address was read as an in-process stand and answered `ok` with nothing asked. The
    expectations come from the requirement (a device stand is asked, only a verdict `ok` is ok, an unknown is never ok, a config
    with no `surface` keeps its answers), not from the code."""
    import types
    from unittest.mock import patch

    import surfaces

    def fake(reply=None, raises=None, calls=None):
        module = types.ModuleType("device_stand")

        def probe(cfg, env_name, deep=False):
            if calls is not None:
                calls.append((env_name, deep))
            if raises is not None:
                raise raises
            return reply
        module.probe = probe
        return module

    row = {"name": "emulator", "surface": "android", "driver": {"url": "http://127.0.0.1:4723"}, "app": {"id": "com.example.app"}}
    ok_reply = {"verdict": "ok", "checks": [{"name": "devices", "state": "devices", "line": "one device is connected"}], "block": None}

    def refused(state, owner):
        return {"verdict": state, "checks": [], "block": {"probe_line": f"the device check says {state}", "remedy": "start the emulator",
                                                          "owner": owner, "do_not_retry": True, "cause": "device"}}
    root = Path(temp_project("qa-factory-readiness-device-"))
    try:
        cfg = {"environment": {}, "environments": [dict(row)]}
        # the false green, reproduced on a row with NO `surface`: still the in-process answer (the web pin)
        old = R.check_environment({"environment": {}, "environments": [{"name": "emulator"}]}, root)
        check_eq("web pin: a row with no `surface` and no address is still read as in-process, ok", old["status"], "ok")
        check_in("web pin: ...with the old note", "in-process environment(s)", old["note"])
        # a device stand with the same shape (no address, empty block): asked, and the fake decides
        calls: list = []
        with patch.dict(sys.modules, {"device_stand": fake(ok_reply, calls=calls)}):
            got = R.check_environment(cfg, root)
        check_eq("device: a live device stand is ok", got["status"], "ok")
        check("device: ...and its note is the device's, never `in-process`", "in-process" not in got["note"] and "emulator" in got["note"], got["note"])
        check_eq("device: ...asked read-only (deep=False) by its name", calls, [("emulator", False)])
        for label, reply, status, owner in (("no device", refused("no_device", "user"), "missing", "user"),
                                            ("a missing tool", refused("tool_missing", "user"), "missing", "user"),
                                            ("unreadable", refused("unreadable", "factory"), "unknown", "factory"),
                                            ("foreign", refused("foreign", "factory"), "unknown", "factory")):
            with patch.dict(sys.modules, {"device_stand": fake(reply)}):
                got = R.check_environment(cfg, root)
            check_eq(f"device {label}: {status} for {owner}, never ok", (got["status"], got["owner"]), (status, owner))
            check_in(f"device {label}: the note names the stand and the check's line", "emulator", got["note"])
            if status == "missing":
                check_eq(f"device {label}: the remedy is a human step that says how", (got["remedy"]["kind"], got["remedy"]["steps"]),
                         ("human_step", ["start the emulator"]))
        for label, module in (("a probe that raises", fake(raises=RuntimeError("boom"))), ("a reply that is no dict", fake("x")),
                              ("a reply with no verdict", fake({"checks": []})), ("a verdict that is not ok and no block", fake({"verdict": "no", "checks": []})),
                              ("no device_stand module", None)):
            with patch.dict(sys.modules, {"device_stand": module}):
                got = R.check_environment(cfg, root)
            check_eq(f"device unknown: {label} -> unknown, factory, not ok", (got["status"], got["owner"]), ("unknown", "factory"))
        # app.id empty: not_configured, and the probe is not asked
        calls = []
        with patch.dict(sys.modules, {"device_stand": fake(ok_reply, calls=calls)}):
            for empty in ({}, {"id": "  "}, None):
                got = R.check_environment({"environment": {}, "environments": [dict(row, app=empty)]}, root)
                check_eq(f"device: app {empty!r} -> not_configured", got["status"], "not_configured")
        check_eq("device: ...and the device was not asked about an application nobody named", calls, [])
        # a typo in `surface` and a broken table: unknown, never ok
        with patch.dict(sys.modules, {"device_stand": fake(ok_reply)}):
            got = R.check_environment({"environment": {}, "environments": [dict(row, surface="andriod")]}, root)
            check_eq("device: a typo in `surface` is unknown (config_contract names it), not ok", (got["status"], got["owner"]), ("unknown", "factory"))
            with patch.object(surfaces, "TABLE_PATH", Path(root) / "no-such-table.json"):
                got = R.check_environment(cfg, root)
            check_eq("device: an unreadable table is unknown, not ok", got["status"], "unknown")
        # a `surface` of another hands is no device stand: the old road, the device not asked
        calls = []
        with patch.dict(sys.modules, {"device_stand": fake(ok_reply, calls=calls)}):
            got = R.check_environment({"environment": {}, "environments": [{"name": "w", "surface": "web"}]}, root)
        check_eq("device: `surface: web` is not asked of the device (old road: in-process ok)", (got["status"], calls), ("ok", []))
        # the environment block is filled AND a device row exists: the device row is still asked (the block never answers for it)
        calls = []
        block = {"health_url": "http://127.0.0.1:9/health"}
        with patch.dict(sys.modules, {"device_stand": fake(refused("no_device", "user"), calls=calls)}):
            got = R.check_environment({"environment": dict(block), "environments": [dict(row)]}, root)
        check_eq("device: a filled block does not hide a missing device", (got["status"], calls), ("missing", [("emulator", False)]))
        check_in("device: ...and the note names the block's own answer too", "also:", got["note"])
        # two device stands: the wrong one answers, the live one is named
        two = {"environment": {}, "environments": [dict(row), dict(row, name="tablet", surface="ios")]}

        def by_name(cfg_, name, deep=False):
            return ok_reply if name == "emulator" else refused("no_device", "user")
        module = types.ModuleType("device_stand")
        module.probe = by_name
        with patch.dict(sys.modules, {"device_stand": module}):
            got = R.check_environment(two, root)
        check_eq("two device stands: the wrong one makes the capability missing", got["status"], "missing")
        check("two device stands: ...its note names it first and the live one after", got["note"].index("tablet") < got["note"].index("emulator"), got["note"])
        # a mixed project: the API stand goes the plain road over the REST of the rows, the device row is asked on its own
        mixed = {"environment": {"health_url": "http://x"}, "environments": [dict(row), {"name": "qa", "base_url": "http://localhost:9"}]}
        seen: list = []

        def plain(cfg_, root_, env_, stands_):
            seen.append([s["name"] for s in stands_])
            return R.cap("ok", "factory", "env_probe: alive")
        with patch.dict(sys.modules, {"device_stand": fake(ok_reply)}), patch.object(R, "_check_plain_environment", plain):
            got = R.check_environment(mixed, root)
        check_eq("mixed: the plain road sees the API stand only", seen, [["qa"]])
        check_eq("mixed: both live -> ok, the note names both", (got["status"], "emulator" in got["note"], "env_probe: alive" in got["note"]), ("ok", True, True))
        with patch.dict(sys.modules, {"device_stand": fake(refused("no_device", "user"))}), patch.object(R, "_check_plain_environment", plain):
            got = R.check_environment(mixed, root)
        check_eq("mixed: a missing device is missing although the API stand is alive", got["status"], "missing")
        check_in("mixed: ...and the live API stand is still named", "env_probe: alive", got["note"])
    finally:
        cleanup(root)


def vcs_api_from_receipts() -> None:
    """HF8-12, W-4: a merge request read through the API proves `vcs_api` in the regenerated readiness file, and an unknown
    never becomes `ok` (table of `vcs_evidence.api_capability`). One row of the table per check."""
    import shutil
    import subprocess
    import vcs_evidence as VE
    root = temp_project("qa-factory-readiness-vcsapi-")
    use_project(root)
    held_which, held_readiness, held_run, held_api = shutil.which, VE.readiness, subprocess.run, VE.api
    real_which = shutil.which
    shutil.which = lambda name, *a, **k: "glab" if name == "glab" else real_which(name, *a, **k)
    config = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))

    def clear():
        for old in (root / "qa-factory" / "state" / "host-receipts").glob("vcs-api-*.json"):
            old.unlink()

    def keep(host, error=None):
        VE.record_api_receipt(root, {"host": host, "status": "read", "api_authenticated": True} if not error
                              else {"host": host, "status": "unavailable", "error": error})

    def row(live=None):
        VE.readiness = (lambda cfg, root_: dict(live)) if live is not None else held_readiness
        return R.compute(config, root, probe_vcs=live is not None)["capabilities"]["vcs_api"]

    required = ["provider_api_operations", "required_mr_metadata_and_discussions"]
    try:
        entry = row()
        check_eq("compute: no receipt keeps the old unknown, required_for survives",
                 (entry["status"], "Run readiness.py --probe-vcs" in entry["note"], entry["required_for"]), ("unknown", True, required))
        keep("a.example.com")
        entry = row()
        check_eq("compute: receipt without probe gives ok, proved by the receipt, required_for survives",
                 (entry["status"], entry["owner"], entry.get("proved_by"), "`a.example.com`" in entry["note"], entry["required_for"]),
                 ("ok", "factory", "receipt", True, required))
        check("compute: ok carries no remedy and the note keeps the per-MR limit",
              "remedy" not in entry and "still needs its own read" in entry["note"], str(entry))
        keep("b.example.com", "unauthenticated")
        entry = row()
        check_eq("compute: ok on one host and denied on another is unknown, names the denied host and its code",
                 (entry["status"], "`b.example.com`" in entry["note"], "unauthenticated" in entry["note"], "`a.example.com`" in entry["note"]),
                 ("unknown", True, True, True))
        check_eq("compute: a denial and no live probe never gives ok (denied beside ok, required_for survives)",
                 (entry["status"] != "ok", entry["required_for"]), (True, required))
        clear()
        keep("b.example.com", "forbidden")
        check_eq("compute: denied alone is unknown", row()["status"], "unknown")

        clear()
        keep("a.example.com")
        for label, live, expect in (
                ("compute: live ok is the live answer as it is", {"status": "ok", "owner": "factory", "host": "a.example.com", "note": "L"}, ("ok", "L")),
                ("compute: live missing on the same host wins over the receipt",
                 {"status": "missing", "owner": "user", "host": "a.example.com", "note": "L"}, ("missing", "L")),
                ("compute: live missing on the same host, port and capitals do not make another host",
                 {"status": "missing", "owner": "user", "host": "A.Example.com", "note": "L"}, ("missing", "L"))):
            entry = row(live)
            check_eq(label, (entry["status"], entry["note"]), expect)
            check_eq(label + ": required_for survives", entry["required_for"], required)
        entry = row({"status": "missing", "owner": "user", "host": "other.example.com", "note": "L",
                     "remedy": {"kind": "human_step"}})
        check_eq("compute: live missing on another host stays missing, the note names the read, the remedy stays",
                 (entry["status"], entry["note"].startswith("L"), "`a.example.com` was read" in entry["note"], entry["remedy"]),
                 ("missing", True, True, {"kind": "human_step"}))
        entry = row({"status": "unknown", "owner": "factory", "host": "a.example.com", "note": "no route",
                     "remedy": {"kind": "human_step", "need": "vpn"}})
        check_eq("compute: asked and no answer stays unknown, remedy kept, note names the read",
                 (entry["status"], entry["remedy"], "`a.example.com` was read" in entry["note"], "no answer now" in entry["note"]),
                 ("unknown", {"kind": "human_step", "need": "vpn"}, True, True))
        entry = row({"status": "unknown", "owner": "orchestrator", "note": "connector"})
        check_eq("compute: could not ask, a receipt gives ok, proved by the receipt",
                 (entry["status"], entry.get("proved_by"), "no live probe" in entry["note"]), ("ok", "receipt", True))
        keep("b.example.com", "unauthenticated")
        entry = row({"status": "unknown", "owner": "orchestrator", "note": "connector"})
        check_eq("compute: could not ask with a fresh denial beside the read stays unknown", entry["status"], "unknown")
        clear()
        entry = row({"status": "unknown", "owner": "factory", "host": "a.example.com", "note": "no route"})
        check_eq("compute: asked, no answer, no receipt: the live answer as it is", (entry["status"], entry["note"]), ("unknown", "no route"))

        # the live probe itself writes the refusal it established, so the later regenerated file is not `ok`
        clear()
        keep("gitlab.example.com")
        config["adapters"]["vcs"]["name"] = "gitlab"
        (root / "qa-factory" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        keep("gitlab.example.com")
        check_eq("compute: before the refusal the receipt gives ok", row()["status"], "ok")

        def fake_run(argv, *a, **k):
            if argv[:3] == ["git", "remote", "get-url"]:
                return SimpleNamespace(stdout="https://gitlab.example.com/g/p.git\n", returncode=0)
            return held_run(argv, *a, **k)

        def refused(host, endpoint):
            raise VE.AccessError("unauthenticated")

        subprocess.run, VE.api = fake_run, refused
        try:
            live = held_readiness(config, root)
        finally:
            subprocess.run, VE.api = held_run, held_api
        check_eq("live denial writes denied, a later compute without the probe is not ok",
                 (live["status"], row()["status"]), ("missing", "unknown"))
    finally:
        shutil.which, VE.readiness = held_which, held_readiness
        cleanup(root)


def project_dependencies_capability() -> None:
    """RH1-4 4.4: the capability `project_dependencies` turns `dependency_drift.check` into a doctor line. K-4.4-*."""
    import subprocess
    import dependency_drift as DD
    root = temp_project("qa-factory-readiness-deps-")
    cmd = {"argv": ["poetry", "install"], "cwd": ".", "source": "table"}
    drifted = {"state": "differs", "lock": "poetry.lock", "checked": 2, "differs": [
        {"name": "testproject1-sdk-python", "installed": "0.1.700", "locked": "0.1.704", "direction": "older"}], "absent": [],
        "conditional": 0, "why": "x", "environment": {"source": "dir", "where": ".venv", "rejected": []}, "command": cmd}
    held, held_run, held_popen = DD.check, subprocess.run, subprocess.Popen
    started = []

    def forbidden(*a, **k):
        started.append(a)
        raise AssertionError("the doctor must not start a process for an install")

    def answering(result):
        DD.check = lambda *a, **k: dict(result)
        return R.check_project_dependencies({}, root)

    try:
        check("K-4.4: the capability is listed", "project_dependencies" in R.CAPABILITIES)
        subprocess.run, subprocess.Popen = forbidden, forbidden
        row = answering(drifted)
        check_eq("K-4.4-differs: a difference -> missing, owner user", (row["status"], row["owner"]), (R.MISSING, "user"))
        check_eq("K-4.4-differs: the note names the pair and the command",
                 row["note"], "installed testproject1-sdk-python 0.1.700, the lock says 0.1.704; the project's install command: `poetry install`")
        rem = row["remedy"]
        check_eq("K-4.4-differs: the remedy is a human step with the command verbatim, never autorun",
                 (rem["kind"], rem["autorun"], rem["owner"], rem["steps"]), ("human_step", False, "user", ["poetry install"]))
        check("K-4.4-differs: blocks and verify are stated", rem["blocks"] and rem["verify"] == "dependency_drift.py <project root> prints in_sync")
        check("K-4.4-noexec: no process was started to produce the line (the doctor prints, it does not install)", not started, started)
        folder = dict(drifted, command={"argv": ["poetry", "install"], "cwd": "svc", "source": "table"})
        check_eq("a command that runs in a folder says where", answering(folder)["remedy"]["steps"], ["in svc: poetry install"])
        row = answering(dict(drifted, state="missing_only", differs=[], absent=[{"name": "requests", "locked": "2.0.0"}]))
        check_eq("K-4.4-absent: missing_only -> missing, owner user", (row["status"], row["owner"]), (R.MISSING, "user"))
        row = answering(dict(drifted, command={"argv": [], "cwd": ".", "source": "none"}))
        check_eq("K-4.4-nocmd: no command -> the step says to record it at onboarding",
                 row["remedy"]["steps"], ["record the project's install command at onboarding"])
        check_in("K-4.4-nocmd: ...and the note says so in words", "record it at onboarding", row["note"])
        row = answering({"state": "unknown", "why": "no lock file the factory reads", "lock": "", "checked": 0, "command": cmd})
        check_eq("K-4.4-unknown: unknown -> unknown, owner factory (not the person's next step)", (row["status"], row["owner"]),
                 (R.UNKNOWN, "factory"))
        check("K-4.4-unknown: ...a remedy exists and asks the person for nothing", row["remedy"]["owner"] == "factory"
              and row["remedy"]["kind"] == "probe")
        row = answering({"state": "in_sync", "why": "all 3 packages", "lock": "poetry.lock", "checked": 3, "command": cmd})
        check_eq("K-4.4-sync: in_sync -> ok with checked", (row["status"], row["checked"]), (R.OK, 3))
        seen = []

        def by_profile(profile, *a, **k):
            seen.append(profile.get("profile_id"))
            return dict(drifted) if profile.get("profile_id") == "api" else dict(drifted, state="in_sync", differs=[])

        DD.check = lambda root_, profile=None, **k: by_profile(profile or {})
        cfg = {"profiles": [{"profile_id": "api", "commands": {"one_test": {"argv": ["pytest"], "kind": "test", "cwd": "."}}},
                            {"profile_id": "ui", "selected": False, "commands": {}},
                            {"profile_id": "web", "commands": {"one_test": {"argv": ["pytest"], "kind": "test", "cwd": "web"}}}]}
        row = R.check_project_dependencies(cfg, root)
        check_eq("Q1/F1: the doctor checks the selected profiles (a deselected one sits out; one with no key takes part), one per environment",
                 sorted(seen), ["api", "web"])
        check_eq("Q1: the worst result is the line (a difference in one environment is not hidden by a good one)",
                 (row["status"], row["note"].startswith("(api) installed testproject1-sdk-python")), (R.MISSING, True))
        DD.check = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        row = R.check_project_dependencies({}, root)
        check_eq("a reader that raises -> unknown, owner factory, no traceback", (row["status"], row["owner"]), (R.UNKNOWN, "factory"))
    finally:
        DD.check, subprocess.run, subprocess.Popen = held, held_run, held_popen
        cleanup(root)


if __name__ == "__main__":
    main()
