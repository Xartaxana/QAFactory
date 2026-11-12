"""Project readiness BY CAPABILITY, not by one flag (design section 4, S0).

"The factory is installed" answers nothing useful. What S0 needs to know is which of the
capabilities a story actually depends on are available RIGHT NOW, and for each
missing one, who has to provide it. That is what this script computes into
<project>/qa-factory/state/readiness.json (beside the config until the two-folder layout, t-232):

  ticket_adapter    config.adapters.ticket is set and reachable BY THE ROLE that reads it
                    (adapters-read.md), or `file`; a tracker reached only through the
                    orchestrator's own session (mcp_tool, agent, skill) is `not_configured`
  test_repo         config.tests_root exists on disk
  case_store        config.cases_root exists and is outside the application code;
                    `not_configured` (not a failure) when the project keeps no case library
  case_id_form      config.case_id_form is empty (the default TC-{nnn}) or a readable template;
                    `missing`/user naming the problem when it is not (never in a --require set)
  adapter_forms     the ticket-key form and the delivery commands the gates read
                    (references/adapter-forms.json plus adapters.ticket.key_pattern and
                    adapters.vcs.delivery_commands): `ok` with a note naming them and where each comes
                    from; `missing` when a project value or the table cannot be read; `unknown` when the
                    version-control route is a session tool the delivery gate cannot see (never in a
                    --require set)
  app_repo          application code is actually present: a code_repos[] path that exists,
                    or an app_root whose protected_app_paths are on disk
  vcs               git is on PATH and the project has a remote
  environment       env_probe.py agrees the stand is usable; `unknown` when none configured
  external_writes   every channel is `markdown`, or its adapter is configured
  config_schema     config.schema_version == hooklib.REQUIRED_SCHEMA_VERSION

Status vocabulary: ok · missing · not_configured · unknown. Every non-ok capability
carries an owner (user | factory) — a halt that does not say whose problem it is just
moves the confusion downstream.

CLI:
  readiness.py                       print a one-line-per-capability summary
  readiness.py --json                print readiness.json to stdout
  readiness.py --write               write <project>/qa-factory/state/readiness.json
  readiness.py --require a,b         exit 1 listing what is missing and who owns it

No qa-factory/config.json (the project was never onboarded) -> silent exit 0: the plugin's
hooks fire in every repository on the machine and must stay quiet outside factory projects.
"""
import argparse
import json
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hooklib import (  # noqa: E402
    REQUIRED_SCHEMA_VERSION, PLUGIN_ROOT, config_path, load_config, project_root, ref,
)
from profile_contract import (  # noqa: E402
    implementation_repo_readiness, one_test_argv, profile_readiness,
    validate_config as validate_profile_config,
)
from config_contract import config_keys, effective_config, stop_after_problem, validate as validate_config_contract  # noqa: E402
from project_inventory import build_inventory  # noqa: E402
import adapter_forms  # noqa: E402
import case_forms  # noqa: E402
import detector_verdict as DV  # noqa: E402
import runtime_paths as RP  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

CAPABILITIES = ["ticket_adapter", "jira_direct_api", "test_repo", "case_store", "case_id_form", "adapter_forms", "app_repo",
                "vcs", "environment", "external_writes", "config_schema", "vcs_api", "host_hooks", "tracker_write",
                "project_dependencies"]
OK = "ok"
MISSING = "missing"
NOT_CONFIGURED = "not_configured"
UNKNOWN = "unknown"

MARKDOWN_CHANNELS = {"markdown"}
BUILTIN_TICKET_ADAPTERS = {"file"}  # needs nothing external: a local markdown ticket file


def cap(status: str, owner: str, note: str, **extra) -> dict:
    """One capability's verdict, and — when it is not `ok` — what to do about it.

    `note` is prose: a person can read it, no caller can act on it. That is why the doctor
    printed "check existing glab host credentials/environment" as a project's single next
    action and a person went looking at keys that were never the problem. `remedy` is the
    machine-readable half, and it is complete only when someone who has never seen this
    factory could carry it out without asking a second question:

      kind     probe        a read-only check the factory can run itself (autorun allowed)
               human_step   something only a person can do
               not_a_defect this state is fine and needs nobody
      need     what is missing, in a person's words, with no factory vocabulary
      obtain   for anything the person does not already hold (a token, an access, an account):
               what to get, WHERE, and the minimal rights. A step that needs something the
               person has not got, without saying where it comes from, is not a step.
      steps    ordered, each executable as written; routes the factory can try itself come
               FIRST, so a person is asked only for what is actually left to them
      blocks   the cost of doing nothing AND what still works — an overstated cost is as
               much a lie as an understated one, and it is the expensive kind
      verify   who establishes that it worked

    `not_configured` that is a legitimate answer carries `kind: not_a_defect`, so a report can
    tell "nothing to do here" from "nobody has looked yet"."""
    out = {"status": status, "owner": owner, "note": note}
    out.update(extra)
    if status != OK and "remedy" not in out:
        out["remedy"] = {"kind": "human_step", "autorun": False, "owner": owner,
                         "need": note, "steps": [note],
                         "blocks": "named at gate A when a story needs this capability",
                         "verify": "re-run readiness.py"}
    return out


def _resolve(root: Path, raw: str) -> Path:
    p = Path(str(raw or "."))
    return p if p.is_absolute() else root / p


def executable_of(command: str) -> str:
    """The program a command template would actually run: its first token, unquoted.
    `dmtools jira get {key}` -> `dmtools`."""
    try:
        parts = shlex.split(str(command or ""), posix=False)
    except ValueError:
        parts = str(command or "").split()
    return parts[0].strip('"').strip("'") if parts else ""


def probe_executable(command: str, root: Path) -> str | None:
    """Where the command's program actually is, or None. PATH first (shutil.which applies
    PATHEXT on Windows, so a `.cmd` shim is found), then the project root for a command
    given as a relative path."""
    exe = executable_of(command)
    if not exe:
        return None
    found = shutil.which(exe)
    if found:
        return found
    candidate = _resolve(root, exe)
    return str(candidate) if candidate.is_file() else None


def host_unreachable(root: Path, url: str) -> dict | None:
    """Nothing may be said about credentials for a host this machine cannot reach.

    One dropped VPN used to surface as several unrelated red capability rows, each blaming a
    different set of credentials and each owned by the person.

    Called only once recorded evidence has come up empty: a fresh receipt outranks a live
    socket probe (it is proof the host answered minutes ago), and a network question asked
    before the real one costs every healthy run a probe it does not need."""
    import reachability
    host, port = reachability.host_of(url)
    if not host:
        return None
    route = reachability.probe(host, port)
    if route["status"] != "unreachable":
        return None
    return cap(UNKNOWN, "factory",
               f"no network route to `{host}` ({route.get('detail')}) — access is NOT verified and "
               "NOT denied, because nothing was asked of the host. The credentials on this machine "
               "were never in question.",
               gap_id="jira-direct-api",
               remedy={"kind": "human_step", "autorun": False, "owner": "user",
                       "need": f"a network route to `{host}`",
                       "steps": ["turn the corporate VPN on if it is off — that is the usual cause",
                                 f"if the VPN is already on, `{host}` is down or blocked for this "
                                 "machine: report it rather than changing anything locally"],
                       "blocks": "reading the ticket through the direct API while it lasts; local "
                                 "work is unaffected",
                       "verify": "say the word and the probe runs again"})


def check_jira_direct(cfg, root):
    """Readiness of original-file access is independent of an assistant being configured."""
    import os
    entry = ((cfg.get("adapters") or {}).get("ticket") or {})
    if str(entry.get("name") or entry.get("kind") or "").lower() != "jira":
        return cap(OK, "factory", "direct Jira API is not required for this tracker", applicable=False)
    direct = entry.get("direct_api") or {}
    if not direct:
        return cap(NOT_CONFIGURED, "user", "Direct Jira API is required even with Jira Assistant; "
                   "configure a local secret reference for original attachments", gap_id="jira-direct-api")
    required = ["base_url", "auth_type", "secret_ref"]
    if direct.get("auth_type") == "basic_token":
        required.append("username_ref")
    if any(not direct.get(k) for k in required) or direct.get("auth_type") not in {"basic_token", "bearer"}:
        # t-287 item 2: name the keys (a template stub on an old config lacks all of them) and give the SAME remedy
        # the other read-route gap gives (`ticket-read-route`, `session_route`): the onboarding door, or the word
        missing = [f"adapters.ticket.direct_api.{k}" for k in required if not direct.get(k)]
        if direct.get("auth_type") and direct.get("auth_type") not in {"basic_token", "bearer"}:
            missing.append("adapters.ticket.direct_api.auth_type (basic_token or bearer)")
        if not direct.get("auth_type"):
            missing.append("adapters.ticket.direct_api.username_ref (when auth_type is basic_token)")
        route = session_route("jira", "direct_api", "")
        return cap(NOT_CONFIGURED, "user",
                   "direct Jira API connection contract incomplete: it lacks " + ", ".join(missing),
                   gap_id="jira-direct-api", remedy=route["remedy"])
    # The reader (`source_inventory.JiraClient`) fills a name the process lacks from the project's
    # configured env file; the doctor asks through the SAME resolver, or it reports "not set in
    # this session" about a credential the reader is using fine - two records of one fact.
    # Values are never kept: only the names that came from the file are remembered.
    from source_inventory import runtime_credential_values
    resolved, from_file = None, []
    for field in ("secret_ref", "username_ref"):
        ref_value = direct.get(field)
        if ref_value:
            name = str(ref_value).removeprefix("env:")
            if not os.environ.get(name):
                if resolved is None:
                    resolved = runtime_credential_values(cfg, root)
                if resolved.get(name):
                    from_file.append(name)
                    continue
                return cap(MISSING, "user", "direct Jira API secret reference unavailable; use secure local setup",
                           gap_id="jira-direct-api",
                           remedy={"kind": "human_step", "autorun": False, "owner": "user",
                                   "need": f"the environment variable `{name}`, which is not set in this session",
                                   "steps": [f"set `{name}` in the local process environment or an approved "
                                             "secret launcher, then reopen the session "
                                             "(references/jira-direct-access.md)"],
                                   "blocks": "reading the ticket and its original attachments directly; a "
                                             "configured tracker assistant is a separate route",
                                   "verify": "readiness.py re-reads the environment on every run"})
    def with_source(result: dict) -> dict:
        if from_file:
            result["note"] += (" The credential " + ", ".join(f"`{n}`" for n in from_file) +
                               " was found in the project's configured env file, not in this "
                               "session's process environment.")
        return result

    receipt_path = root / "qa-factory/state/integrations/jira-direct-probe.json"
    if receipt_path.is_file():
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
            checked = datetime.fromisoformat(receipt["checked_at"].replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - checked).total_seconds()
            same = all(str(receipt.get(key) or "").removeprefix("env:").rstrip("/") ==
                       str(direct.get(key) or "").removeprefix("env:").rstrip("/")
                       for key in ("base_url", "auth_type", "secret_ref", "username_ref"))
            checks = {c.get("name"): c for c in receipt.get("checks", []) if isinstance(c, dict)}
            proven = (all(checks.get(key, {}).get("status") == "available"
                          for key in ("authenticated_identity", "sample_issue", "paginated_comments"))
                      and checks.get("attachment_original", {}).get("status") in {"available", "not_applicable"})
            same = same and str(receipt.get("api_version")) == str(direct.get("api_version", "2"))
            if same and proven and 0 <= age <= 86400 and receipt.get("status") == "available":
                return with_source(cap(OK, "factory", "Direct Jira read access verified; write permissions are separate",
                                       evidence_ref="state/integrations/jira-direct-probe.json",
                                       checked_at=receipt["checked_at"]))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    # Only now, with no fresh receipt to go on, is it worth asking whether the host is even
    # reachable — and only to explain the gap, never to overrule recorded evidence.
    unreachable = host_unreachable(root, direct.get("base_url"))
    if unreachable:
        return with_source(unreachable)
    return with_source(cap(UNKNOWN, "factory",
               "Credentials present; the read-only probe has not run (or its receipt is over 24h old). "
               "It verifies identity, comments and an original attachment. Write permissions are separate "
               "and unverified.",
               gap_id="jira-direct-api",
               remedy={
                   "kind": "probe", "autorun": True, "owner": "factory",
                   "need": "one read-only call to Jira with the credentials already on this machine",
                   "command": "ticket_adapter.py probe <TICKET> --output "
                              "qa-factory/state/integrations/jira-direct-probe.json --json",
                   "needs_sample_ticket": True,
                   "why": "the probe writes the receipt this capability reads; without it the status "
                          "stays unknown forever, however good the credentials are",
                   "blocks": "nothing yet — S0 runs the same probe when a story starts. Unverified "
                             "here only means nobody has looked.",
                   "verify": "readiness.py re-reads the receipt; ok means identity, comments and an "
                             "original attachment were all reachable",
               }))


def session_route(name: str, method: str, target: str) -> dict:
    """A tracker reached through the ORCHESTRATOR's session — an MCP tool, an agent, a skill.

    It is one answer for all three because they fail in the same place. On TP2-2553 the
    project reached Jira through an MCP tool of the orchestrator's session; this row said
    `unknown`, owner `orchestrator`, "S0 verifies it by fetching the ticket once" — and S0's
    fetch duly succeeded, because the orchestrator did hold that tool. Then S1 was dispatched
    and qa-scout had nothing: a subagent carries none of its caller's session tools, gets no
    attachment bytes, and cannot reach the parent, a normative source or a mentioned key that
    way. The dispatch stalled and the orchestrator fetched every ticket by hand — 2 h 54 min
    and about twelve dollars before planning began.

    So the orchestrator's own route is no longer evidence for a capability S1 needs. The read
    route is `adapters.ticket.direct_api`, which `ticket_adapter.py` uses whatever `method`
    says (0.7.9); `method` keeps naming the WRITE channel, which is unaffected."""
    return cap(NOT_CONFIGURED, "user",
               f"adapter `{name}` is reached through the session {method} "
               f"`{target or '<unnamed>'}` — the orchestrator's route, and not the S1 role's: a "
               "subagent holds none of its caller's session tools, receives no attachment "
               "bytes, and cannot reach the parent, the normative sources or a mentioned key "
               "through one. The role reads through adapters.ticket.direct_api "
               "(references/jira-direct-access.md shows the shape); this "
               f"{method} stays a perfectly good WRITE channel",
               gap_id="ticket-read-route",
               remedy={"kind": "human_step", "autorun": False, "owner": "user",
                       "need": "adapters.ticket.direct_api — the tracker's base url and the API "
                               "token onboarding already asks for",
                       "steps": ["/qa-factory:qa-onboarding — topic 7: how the tracker is READ",
                                 "references/jira-direct-access.md carries the shape it records",
                                 "or say the word instead and the story runs on what this route "
                                 "does reach: `waiver.py --stage S1 --block \"tracker route\" "
                                 "--decision \"<your words>\"`"],
                       "blocks": "S1 source collection by qa-scout",
                       "verify": "readiness.py --require ticket_adapter"})


def _role_route(cfg: dict) -> bool:
    """Is there a recorded route the role reads the tracker by (SS1-15)? `ticket_adapter.reads_by_role` AND a recorded
    `tracker_route`: a tracker with no route recorded keeps the earlier verdicts (a project with a `command` is rated by it)."""
    import ticket_adapter
    from source_inventory import tracker_route
    return bool(ticket_adapter.reads_by_role(cfg) and tracker_route(cfg))


def check_ticket_adapter(cfg: dict, root: Path) -> dict:
    """`ok` means "this session can reach it", and the only thing that proves it is a probe.

    The pilot bug this rule exists for: onboarding wrote `command: dmtools jira get {key}`
    with `status: configured` for a `dmtools` that was never installed, readiness reported
    `ok / adapter jira reachable per config` — repeating the config's own claim back as a
    finding — and the first story died in S0 on a missing executable. A capability that
    cannot be verified is `unknown`, never `ok`: unknown is checked again by the orchestrator
    in-session, `ok` is not checked by anyone."""
    entry = ((cfg.get("adapters") or {}).get("ticket") or {})
    name = str(entry.get("name") or entry.get("kind") or "").strip()  # adapters-read.md: `name` and `kind` are both accepted
    if name.lower() == "jira" and entry.get("direct_api"):
        return check_jira_direct(cfg, root)
    status_field = str(entry.get("status") or "").strip()
    if not name:
        return cap(NOT_CONFIGURED, "user",
                   "adapters.ticket.name is empty — onboarding names the tracker, or `file` for a "
                   "local ticket file (--ticket-file)")
    if name in BUILTIN_TICKET_ADAPTERS:
        raw_path = str(entry.get("path") or "").strip()
        if raw_path and not _resolve(root, raw_path).exists():
            return cap(MISSING, "user",
                       f"adapter `{name}` reads ticket files from `{raw_path}`, which does not "
                       "exist — create the directory or fix adapters.ticket.path")
        return cap(OK, "factory", f"adapter `{name}` — a local ticket file, nothing external to reach")

    method = str(entry.get("method") or "").strip().lower()
    command = str(entry.get("command") or "").strip()
    if not method:  # back-compat inference, mirroring ticket_adapter.resolve_method
        method = ("command" if command else
                  "mcp_tool" if str(entry.get("mcp_tool") or "").strip() else "")

    if _role_route(cfg):
        # SS1-15: the factory holds no client for this tracker; the ROLE reads it by the route onboarding recorded. Never `ok`
        # (only a probe proves a route): `unknown`, proved by use, and `route: role` tells the dispatch guard it is a route
        # the scout can follow (an orchestrator-only route carries no such field).
        return cap(UNKNOWN, "role", f"adapter `{name}`: the role reads it by the route onboarding recorded; proved by use",
                   route="role")
    if method in ("agent", "skill") and not str(entry.get("invoke") or "").strip():
        return cap(NOT_CONFIGURED, "user",
                   f"adapter `{name}` is reached through a session {method} but "
                   "adapters.ticket.invoke is empty — onboarding records the name to dispatch")
    if status_field != "configured":
        return cap(NOT_CONFIGURED, "user",
                   f"adapter `{name}` is declared but status is '{status_field or 'unset'}' — the "
                   "connector or CLI was not detected in this session (adapters-read.md)")

    if method == "command":
        if not command:
            return cap(NOT_CONFIGURED, "user",
                       f"adapter `{name}` is reached by command but adapters.ticket.command is "
                       "empty — onboarding records the command template")
        found = probe_executable(command, root)
        if not found:
            return cap(MISSING, "user",
                       f"adapter `{name}` runs `{command}`, but `{executable_of(command)}` is not "
                       "on PATH in this session — the adapter was DECLARED configured, never "
                       "detected. Install it and re-check, or re-run qa-onboarding and pick a "
                       "connector this session can actually reach (references/adapters-read.md)")
        return cap(OK, "factory", f"adapter `{name}` — `{executable_of(command)}` found at {found}")

    if method in ("agent", "skill"):
        return session_route(name, method, str(entry.get("invoke") or "").strip())
    if method == "mcp_tool":
        return session_route(name, method, str(entry.get("mcp_tool") or "").strip())

    if method == "api":
        # `method: "api"` (written by `ticket_adapter.py --migrate-method`) IS the read
        # route — reached here only for a non-jira adapter, or a jira one whose direct_api the
        # shortcut above already found unusable; jira with a usable direct_api never falls
        # through to this branch at all.
        return cap(NOT_CONFIGURED, "user",
                   f"adapter `{name}` declares method 'api' but adapters.ticket.direct_api is "
                   "missing or incomplete — set base_url, auth_type and secret_ref (and "
                   "username_ref for basic_token), or run /qa-factory:qa-onboarding "
                   "(references/adapters-read.md)")

    return cap(NOT_CONFIGURED, "user",
               f"adapter `{name}` declares no access method — set adapters.ticket.method to one of "
               "command · mcp_tool · agent · skill · api (references/adapters-read.md)")


def check_test_repo(cfg: dict, root: Path) -> dict:
    raw = str(cfg.get("tests_root") or "").strip()
    if not raw:
        return cap(NOT_CONFIGURED, "user", "tests_root is empty — onboarding records where the tests live")
    path = _resolve(root, raw)
    if not path.exists():
        return cap(MISSING, "user", f"tests_root `{raw}` does not exist ({path})")
    return cap(OK, "factory", f"tests_root `{raw}`")


def check_case_store(cfg: dict, root: Path) -> dict:
    """Where the project keeps its case documents — a fact about the project, recorded once.

    An empty key is a legitimate answer ("we keep none"), and the factory then keeps cases
    per story. What is not legitimate is a store that does not exist, or one pointing into
    application code: the factory never writes there, and a config key cannot grant it."""
    raw = str(cfg.get("cases_root") or "").strip()
    if not raw:
        return cap(NOT_CONFIGURED, "user",
                   "cases_root is empty — cases stay per story under "
                   "qa-factory/artifacts/<TICKET>/work/test-cases/. Onboarding records the "
                   "project's own case store here when it has one",
                   remedy={"kind": "not_a_defect", "autorun": False, "owner": "user",
                           "need": "nothing — a project with no case library is a normal project",
                           "steps": [], "blocks": "nothing",
                           "verify": "no verification needed; this is a recorded answer, not a gap"})
    path = _resolve(root, raw)
    app_root = _resolve(root, str(cfg.get("app_root") or ".").strip() or ".")
    for protected in [str(p).strip() for p in (cfg.get("protected_app_paths") or []) if str(p).strip()]:
        guarded = (app_root / protected).resolve()
        try:
            path.resolve().relative_to(guarded)
        except Exception:
            continue
        return cap(MISSING, "user",
                   f"cases_root `{raw}` is inside protected_app_path `{protected}` — the "
                   "factory does not write into application code, so no case could ever be "
                   "written there. Point it at the test repository or at documentation")
    if not path.exists():
        return cap(MISSING, "user", f"cases_root `{raw}` does not exist ({path})")
    return cap(OK, "factory", f"cases_root `{raw}`")


def check_case_id_form(cfg: dict) -> dict:
    """Can the factory read the project's case id form? (B-013)

    Absent or empty is a complete answer: the default `TC-{nnn}`. A form it cannot compile is
    ignored by every reader — only the default (and whichever entries were valid) is recognised —
    so this says what is wrong and who fixes it instead of letting a project find out when its
    cases stop being read. Never a blocker: no story needs this capability to start."""
    bad = case_forms.problems(cfg)
    in_force = case_forms.forms(cfg)
    if bad:
        return cap(MISSING, "user",
                   "config.case_id_form cannot be read: " + "; ".join(bad) + ". Fix or clear "
                   "config.case_id_form; until then the factory uses " + ", ".join(in_force),
                   remedy={"kind": "human_step", "autorun": False, "owner": "user",
                           "need": "the project's case id form written as a template such as "
                                   f"{case_forms.EXAMPLE_TEMPLATE}, or the key emptied",
                           "steps": ["edit config.case_id_form in qa-factory/config.json to a valid "
                                     "template, or set it to an empty string"],
                           "blocks": "nothing stops: cases written in the default form TC-NNN keep "
                                     "working; ids in the project's own form are not recognised "
                                     "until the form is readable",
                           "verify": "re-run readiness.py"})
    configured = [f for f in in_force if f != case_forms.DEFAULT_FORM]
    if not configured:
        return cap(OK, "factory", f"default {case_forms.DEFAULT_FORM}")
    return cap(OK, "factory", "case_id_form " + ", ".join(configured) + f" (and {case_forms.DEFAULT_FORM})")


def _adapter_forms_note(cfg: dict, table) -> str:
    """The `ok` note of adapter_forms: the key form and the delivery commands in force, each with where it
    comes from, and - in words - what is only a default or a guess, with the config key that changes it."""
    form = adapter_forms.key_form(cfg)
    forms = adapter_forms.delivery_forms(cfg)
    own = [name for name, source in forms if source == "adapters.vcs.delivery_commands"]
    notes = [f"{adapter_forms.describe_key_form(cfg)}. The delivery gate knows {len(forms) - len(own)} command(s) from "
             f"references/{adapter_forms.TABLE_NAME} ({', '.join(name for name, source in forms if name not in own)})"
             + (f" and {len(own)} from adapters.vcs.delivery_commands ({', '.join(own)})" if own else "") + "."]
    notes += [p.text + "." for p in form.problems if p.code in (adapter_forms.TRACKER_KIND_GUESSED,
                                                               adapter_forms.KEY_PATTERN_IGNORED)]
    if adapter_forms.vcs_kind(cfg) not in table.vcs:
        notes.append("The version-control host is not one the table holds (adapters.vcs.name is "
                     f"{adapter_forms.vcs_kind(cfg) or 'empty'}), so the delivery gate knows only the data defaults: "
                     "name your own command in adapters.vcs.delivery_commands, for example `bb pr create`")
    return " ".join(notes)


def check_adapter_forms(cfg: dict) -> dict:
    """Can the factory read the ticket-key form and the delivery commands its gates use? (B-405, B-406)

    The data answers for every project that names nothing, so an empty `adapters.vcs.name`, a host the table
    does not hold and a tracker it does not know are all `ok` with a note that says what is a default or a
    guess. `missing` is for a value nobody can read: an unreadable `adapters.ticket.key_pattern`, an invalid
    `adapters.vcs.delivery_commands` entry (the user's), or the table itself (the factory's). `unknown`: a
    merge request opened through the session's own tool (mcp_tool, agent, skill) never passes through the
    shell the delivery gate watches. Never a blocker: no story needs this capability to start."""
    try:
        table = adapter_forms.load_table()
    except adapter_forms.FormsTableError as exc:
        return cap(MISSING, "factory", str(exc),
                   remedy={"kind": "human_step", "autorun": False, "owner": "factory",
                           "need": f"references/{adapter_forms.TABLE_NAME} back from the plugin package",
                           "steps": ["update or reinstall the qa-factory plugin: the file ships in it"],
                           "blocks": f"nothing stops: the gates use {adapter_forms.FLOOR_SAYS}; another tracker's "
                                     "keys and another host's delivery commands are not recognised until it is restored",
                           "verify": "re-run readiness.py"})
    unreadable = [p.text for p in adapter_forms.key_form(cfg).problems if p.code == adapter_forms.KEY_PATTERN_UNREADABLE]
    unreadable += [p.text for p in adapter_forms.delivery_problems(cfg)]
    if unreadable:
        return cap(MISSING, "user", "; ".join(unreadable),
                   remedy={"kind": "human_step", "autorun": False, "owner": "user",
                           "need": "adapters.ticket.key_pattern written as a bare regex for one ticket key (for example "
                                   f"{adapter_forms.KEY_PATTERN_EXAMPLE}), and each adapters.vcs.delivery_commands entry "
                                   "as the program and its subcommand (for example bb pr create)",
                           "steps": ["edit those keys in qa-factory/config.json, or empty them"],
                           "blocks": "nothing stops: the value is ignored and the table's own forms apply; what the "
                                     "project's value would have added is not recognised until it is readable",
                           "verify": "re-run readiness.py"})
    vcs = (cfg.get("adapters") or {}).get("vcs")
    method = str((vcs.get("method") if isinstance(vcs, dict) else "") or "").strip().lower()
    if method in ("mcp_tool", "agent", "skill"):
        return cap(UNKNOWN, "factory",
                   f"adapters.vcs.method is {method}: a merge request opened through the session's own tool does "
                   "not pass through the shell the delivery gate watches, so the gate cannot be shown to stop it "
                   "before the verdict is read")
    return cap(OK, "factory", _adapter_forms_note(cfg, table))


def check_app_repo(cfg: dict, root: Path) -> dict:
    """Evidence that application code is PRESENT, not that some path resolves. `app_root: "."`
    is the template's default and always exists, so on its own it proves nothing — in a
    dedicated test repository it is exactly the value onboarding leaves behind when it never
    asked where the application lives. It counts only when something marks code under it."""
    for entry in cfg.get("code_repos") or []:
        raw = str((entry.get("path") if isinstance(entry, dict) else entry) or "").strip()
        if raw and _resolve(root, raw).exists():
            name = entry.get("name") if isinstance(entry, dict) else ""
            return cap(OK, "factory", f"application code at `{raw}`" + (f" ({name})" if name else ""))

    app_raw = str(cfg.get("app_root") or "").strip()
    protected = [str(p).strip() for p in (cfg.get("protected_app_paths") or []) if str(p).strip()]
    if app_raw and _resolve(root, app_raw).exists():
        app_path = _resolve(root, app_raw)
        if any((app_path / p).exists() for p in protected):
            return cap(OK, "factory", f"application code at `{app_raw}`")
        if protected:
            return cap(MISSING, "user",
                       f"app_root `{app_raw}` exists but none of protected_app_paths "
                       f"({', '.join(protected)}) is on disk under it — the application repository "
                       "is not where config.json says it is")
        return cap(NOT_CONFIGURED, "user",
                   f"app_root `{app_raw}` exists but nothing marks application code in it "
                   "(protected_app_paths and code_repos are both empty) — if the application lives "
                   "in another checkout, re-run qa-onboarding and give its path, or add it to "
                   "code_repos[] as {name, path, default_branch}")
    return cap(MISSING, "user",
               "neither app_root nor any code_repos[] path exists on disk — grounding by diff "
               "needs the application repository present locally")


def check_vcs(root: Path, probe_remote: bool = False) -> dict:
    if not shutil.which("git"):
        return cap(MISSING, "user", "git is not on PATH")
    try:
        out = subprocess.run(["git", "remote"], cwd=str(root), capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=10)
    except Exception as e:
        return cap(UNKNOWN, "factory", f"git remote could not be read ({type(e).__name__})")
    if out.returncode != 0:
        return cap(MISSING, "user", f"{root} is not a git working tree — no branch, no MR")
    if not out.stdout.strip():
        return cap(NOT_CONFIGURED, "user", "git works but the project has no remote — an MR has nowhere to go")
    remotes = out.stdout.split()
    remote = 'origin' if 'origin' in remotes else remotes[0]
    from vcs_evidence import git_readiness
    access = git_readiness(root, remote) if probe_remote else cap(
        UNKNOWN, 'factory', 'Remote read access not probed; run readiness.py --probe-vcs.')
    return cap(OK, "factory", f"Local Git available; remote: {remote}. {access['note']}",
               remote_read=access)


def config_fails_own_probe(env: dict, root: Path) -> dict | None:
    """The acceptance check of onboarding's own output: every key the config declares as the
    stand's own must be there NOW, and must be a credential of the stand at all.

    23.09.2026, a second checkout of the same harness: onboarding inventoried the key names
    it found in the harness's code — `AUTH_CLIENT_SECRET`, `AWS_SESSION_TOKEN`, `AWS_PROFILE`,
    `HEADLESS` — into `secret_keys`, none of them in that project's env file and none of them
    read by any test of the story. The first story halted, and the person was asked to "add
    four keys" that nobody needed. A config that cannot pass its own probe is a defect of the
    onboarding that wrote it; it is never the person's errand, and it is never a key value
    that fixes it."""
    import env_probe
    keys = [str(k).strip() for k in [env.get("user_key")] + list(env.get("secret_keys") or [])
            if str(k or "").strip()]
    misplaced = env_probe.misplaced_keys(env)
    if misplaced:
        return cap(MISSING, "factory",
                   "onboarding wrote a config that lists keys which are not credentials of this "
                   "stand: " + "; ".join(f"{k} — {why}" for k, why in misplaced),
                   remedy={"kind": "human_step", "autorun": False, "owner": "factory",
                           "need": "these names out of environment.secret_keys/extra_keys",
                           "steps": [f"remove {', '.join(k for k, _ in misplaced)} from "
                                     "environment.secret_keys / environment.extra_keys",
                                     "re-run /qa-factory:qa-onboarding (environment batch) to "
                                     "record only the keys the login actually used"],
                           "blocks": "nothing of the stand — the probe no longer stops a story "
                                     "over them, and this line exists so the config gets fixed",
                           "verify": "readiness.py — the environment capability"})
    values, source, fatal = env_probe.load_env(env, root)
    if fatal:
        return None  # the probe below reports it, with the address and the code
    absent = [k for k in keys if not str(values.get(k, "") or "").strip()]
    if not absent:
        return None
    where = (env.get("env_file") or "").strip() or "the process environment"
    return cap(MISSING, "factory",
               f"onboarding wrote a config that fails its own probe: {', '.join(absent)} "
               f"{'are' if len(absent) > 1 else 'is'} in secret_keys/user_key but not in {where}",
               remedy={"kind": "human_step", "autorun": False, "owner": "factory",
                       "need": "the config to name only the keys this project really holds",
                       "steps": [f"remove {', '.join(absent)} from environment.secret_keys / "
                                 "environment.user_key, or",
                                 f"move {', '.join(absent)} to environment.integrations[] with "
                                 "`required_by` naming the area or profile that needs them — a "
                                 "key found in code but absent from the file belongs there, "
                                 "never in secret_keys",
                                 "re-run /qa-factory:qa-onboarding (environment batch) to write "
                                 "the keys its own login proof used"],
                       "blocks": "the environment capability, and with it the stand-dependent "
                                 "stages; nothing about the stand itself is known to be wrong",
                       "verify": f"readiness.py — every listed key resolves in {where}"})


def login_field_unknown(result: dict) -> dict | None:
    """The login endpoint refused every body the factory knows and asked for fields it was not sent (FB-3, FB-5): a
    config fact, not a missing stand. The one-line fix is the note's first characters and is never cut; the login item
    of `layer1` is the one that starts with it (env_probe puts it first), so the other items are kept apart from it.
    None for any other result - the caller's old branch then runs byte-unchanged."""
    login = (result.get("login") or {}) if isinstance(result, dict) else {}
    fix = login.get("fix")
    if login.get("refusal") != "body_shape" or not isinstance(fix, str) or not fix:
        return None
    others = [item for item in result.get("layer1") or [] if not str(item).startswith(fix)]
    note = fix + " (env_probe: " + DV.joined([str(i)[:200] for i in others] + [str(login.get("why") or "")[:200]],
                                              noun="stand problem", max_chars=None) + ")"
    return cap(MISSING, "factory", note, gap_id="login-field-unknown",
               remedy={"kind": "human_step", "autorun": False, "owner": "factory",
                       "need": "the names of the login body fields this stand expects",
                       "steps": [fix, "run env_probe.py --json again: the `login` line reads `ok`",
                                 "re-run /qa-factory:qa-onboarding (environment batch) so the accepted names and "
                                 "the proof are recorded"],
                       "blocks": "the stand-dependent stages: the factory cannot log in; nothing about the stand "
                                 "itself is known to be wrong",
                       "verify": "env_probe.py - the `login` line reads `ok as <key>`"})


def check_environment(cfg: dict, root: Path | None = None) -> dict:
    """Delegated to env_probe.py — one probe, one source of truth. Nothing configured is
    `unknown`, not `missing`: a story may legitimately need no stand at all.

    Three facts, three verdicts (`liveness`, `login`, `keys`), and the capability answers for
    the first one that is wrong. The factory's own defects come first: a config that fails its
    own probe is reported before the stand is blamed for what onboarding wrote."""
    env = cfg.get("environment") or {}
    root = Path(root) if root else project_root()
    stands = [e for e in (cfg.get("environments") or []) if isinstance(e, dict)]
    if any("surface" in e for e in stands):
        # EP1-41c: a row that names a `surface` is told by the table (surfaces.py, the one reader); a config with no such row
        # never gets here, and its answers below do not change by a byte (the web pin)
        return _check_surface_environment(cfg, root, env, stands)
    return _check_plain_environment(cfg, root, env, stands)


def _device_check(cfg: dict, stand: dict) -> dict:
    """The capability for ONE device stand: `device_stand.probe` (read-only, `deep=False`: the session is never created here).
    INVARIANT (AR-28): a stand of a device is never `ok` because nothing was asked - an empty `app.id`, a probe that cannot run
    and a probe that answers anything but `ok` are each named; `unreadable`/`foreign` (the block's owner is the factory) is
    `unknown`, every other refusal is `missing` and the person's."""
    name = str(stand.get("name") or "?")
    app = stand.get("app") if isinstance(stand.get("app"), dict) else {}
    if not str(app.get("id") or "").strip():
        return cap(NOT_CONFIGURED, "user", f"device stand {name}: environments[].app.id is empty, so no application can be told "
                   "from another and none is guessed",
                   remedy={"kind": "human_step", "autorun": False, "owner": "user",
                           "need": "the application id of the app under test on this stand",
                           "steps": ["record it as environments[].app.id of this stand, or run /qa-factory:qa-onboarding again"],
                           "blocks": "every check that drives the application on this stand",
                           "verify": "readiness.py - the environment capability"})
    try:
        import device_stand
        result = device_stand.probe(cfg, name, deep=False)
    except Exception as exc:
        return cap(UNKNOWN, "factory", f"device stand {name}: the check could not run ({type(exc).__name__})")
    if not isinstance(result, dict) or not isinstance(result.get("verdict"), str):
        return cap(UNKNOWN, "factory", f"device stand {name}: the check gave no verdict")
    block = result.get("block") if isinstance(result.get("block"), dict) else {}
    if result["verdict"] == "ok":
        shown = "; ".join(str(c.get("line"))[:200] for c in result.get("checks") or [] if isinstance(c, dict) and c.get("line"))
        return cap(OK, "factory", f"device stand {name}: " + (shown or "the device stand answers"))
    said = str(block.get("probe_line") or f"the check says {result['verdict']}")[:300]
    how = str(block.get("remedy") or "")[:300]
    if str(block.get("owner") or "") == "factory" or not block:
        return cap(UNKNOWN, "factory", f"device stand {name}: {said}")
    return cap(MISSING, "user", f"device stand {name}: {said}",
               remedy={"kind": "human_step", "autorun": False, "owner": "user",
                       "need": "the device stand to answer", "steps": [how] if how else [],
                       "blocks": "every check that drives the application on this stand; nothing else",
                       "verify": "device_stand.py --json"})


def _check_surface_environment(cfg: dict, root: Path, env: dict, stands: list) -> dict:
    """`check_environment` for a config with a row that names a `surface`. A device stand (a `hands: driver` row) is asked on its
    own and NEVER answers `ok` "in-process"; the other rows are checked as ever, by the plain road, over the rest. Several stands
    of different kinds each answer; the capability takes the first wrong one (devices first) and the note names the rest.
    An unreadable table or an unknown `surface` is `unknown`, never `ok`."""
    import surfaces
    try:
        device = [(s, r) for s, r in surfaces.stand_rows(cfg) if surfaces.is_device_row(r)]
    except ValueError as exc:
        return cap(UNKNOWN, "factory", "the surface of an environments[] row could not be read: " + " ".join(str(exc).split())[:300])
    if not device:
        return _check_plain_environment(cfg, root, env, stands)
    taken = {id(s) for s, _ in device}
    rest = [e for e in stands if id(e) not in taken]
    answers = [_device_check(cfg, s) for s, _ in device]
    declared = any(str(env.get(k) or "") for k in ("env_file", "base_url_key", "user_key", "health_url", "health_path")) \
        or bool(env.get("secret_keys") or env.get("extra_keys"))
    others = _check_plain_environment(cfg, root, env, rest) if (rest or declared) else None
    wrong = [a for a in answers if a["status"] != OK]
    if not wrong and (others is None or others["status"] == OK):
        notes = [a["note"] for a in answers] + ([others["note"]] if others else [])
        return cap(OK, "factory", " | ".join(notes))
    first = wrong[0] if wrong else others
    tail = [a["note"] for a in answers if a is not first] + ([others["note"]] if others and others is not first else [])
    return dict(first, note=first["note"] + ("" if not tail else " | also: " + " | ".join(tail)))


def _check_plain_environment(cfg: dict, root: Path, env: dict, stands: list) -> dict:
    """The environment check of the rows that are not a device stand (all of them for a project with none): the body
    `check_environment` always had."""
    declared = [env.get(k) for k in ("env_file", "base_url_key", "user_key", "health_url", "health_path")]
    in_process = [e.get("name") or "?" for e in stands
                  if not any(str(e.get(k) or "") for k in ("base_url", "url", "health_url"))
                  or str(e.get("kind") or "").lower() in ("in-process", "in_process", "local-module")
                  or str(e.get("probe") or "").lower() == "none"]
    if stands and len(in_process) == len(stands) and not any(str(x or "") for x in declared):
        return cap(OK, "factory", "in-process environment(s), nothing to probe: " + ", ".join(in_process))
    if not any(str(x or "") for x in declared) and not (env.get("secret_keys") or env.get("extra_keys")):
        return cap(UNKNOWN, "user",
                   "no environment configured — env_probe has nothing to check; a story that needs a "
                   "stand halts at S0 until onboarding fills the environment block")
    try:
        own = config_fails_own_probe(env, root)
    except Exception as exc:
        own = cap(UNKNOWN, "factory", f"the config's own keys could not be checked ({type(exc).__name__})")
    if own is not None:
        return own
    probe = PLUGIN_ROOT / "scripts" / "env_probe.py"
    try:
        out = subprocess.run([sys.executable, "-B", str(probe), "--json", "--project-root", str(root)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=120)
        result = json.loads(out.stdout)
    except Exception as e:
        return cap(UNKNOWN, "factory", f"env_probe.py could not be run ({type(e).__name__})")
    live, login, keys = result.get("liveness") or {}, result.get("login") or {}, result.get("keys") or {}
    if result.get("layer1"):
        unknown_field = login_field_unknown(result)
        if unknown_field is not None:
            return unknown_field
        owner = "factory" if str(login.get("status")) == "not_recorded" else "user"
        # EVERY stand problem, each cut to 200 characters as before (the length of one problem, not a slice of the
        # list). `layer1` is bounded by construction (env_probe: the stand, the login, one per missing key), so no
        # ceiling and no pointer are needed here.
        return cap(MISSING, owner, "env_probe: " + DV.joined([str(item)[:200] for item in result["layer1"]],
                                                              noun="stand problem", max_chars=None))
    if live.get("verdict") == "wants_login" and not (env.get("access") or {}).get("kind"):
        # The stand is alive and asking for a login, and this project never recorded how it
        # logs in. Unknown, not missing: nothing is broken, the factory simply cannot prove
        # the account works, and a story is warned rather than stopped over a gap of its own.
        return cap(UNKNOWN, "factory",
                   f"access scheme not recorded — {live.get('note', 'the stand wants a login')}, "
                   "and environment.access says nothing about how this project logs in",
                   remedy={"kind": "human_step", "autorun": False, "owner": "factory",
                           "need": "environment.access: the kind of login, the key NAMES it uses, "
                                   "and the codes an unauthenticated request answers",
                           "steps": ["re-run /qa-factory:qa-onboarding and answer the environment "
                                     "batch (p2) — it asks by name, never for a value"],
                           "blocks": "nothing today: liveness and the keys still answer. What is "
                                     "missing is the proof that the account can get in",
                           "verify": "env_probe.py — the `login` line reads `ok as <key>`"})
    note = f"env_probe: {live.get('verdict', '?')}; login {login.get('status', '?')}; keys {keys.get('verdict', '?')}"
    if keys.get("missing"):
        # Named, not blocking: a key nothing in this story reads never halted anyone honestly.
        note += " (" + "; ".join(f"{m['key']} needed by {m['needed_by']}" for m in keys["missing"]) + ")"
    return cap(OK, "factory", note)


def closed_for_run() -> dict:
    """The verdict of an outward capability in an experiment run (`--no-trace`, t-017 D3): not
    applicable, and never probed. The same word `tracker_write` answers a project with no bugs
    channel, so every reader of readiness.json that already understands `applicable: false`
    reads this too."""
    return cap(NOT_CONFIGURED, "factory",
               "closed for this run: an experiment writes nothing outside the project",
               applicable=False,
               remedy={"kind": "not_a_defect", "autorun": False, "owner": "factory",
                       "need": "nothing", "steps": [], "blocks": "nothing",
                       "verify": "the bug files in this repository are the record"})


def check_tracker_write(cfg: dict, root: Path, no_trace: bool = False) -> dict:
    """Not "is a bugs channel configured" but "may it CREATE an issue". TP2-2534: a good
    run whose findings never reached Jira, because the channel was read-only and nobody asked.

    `no_trace`: an experiment asks nothing of the tracker - the probe is not called at all
    (a probe of a tracker is itself a call to it, and FR-36 forbids probing what the run's
    standing decision forbids)."""
    if no_trace:
        return closed_for_run()
    try:
        import tracker_write
        r = tracker_write.probe(cfg, root, where="doctor")
    except Exception as exc:
        return cap(UNKNOWN, "factory", f"the tracker-write probe did not run ({exc})")
    if r.get("applicable") is False:
        return cap(NOT_CONFIGURED, "factory", r["reason"], applicable=False,
                   remedy={"kind": "not_a_defect", "autorun": False, "owner": "factory",
                           "need": "nothing", "steps": [], "blocks": "nothing",
                           "verify": "the bug files in this repository are the record"})
    if r["status"] == tracker_write.CONFIRMED:
        return cap(OK, "factory", r["reason"], checked_at=r.get("checked_at"),
                   evidence_ref="state/integrations/tracker-write.json")
    if r["status"] == tracker_write.NO:
        return cap(MISSING, "user", r["reason"], gap_id="tracker-write",
                   remedy={"kind": "human_step", "autorun": False, "owner": "user",
                           "need": "a way to file the bugs this factory finds",
                           "steps": r.get("alternatives") or [],
                           "blocks": "filing bugs in the tracker; every bug still gets its own "
                                     "file in this repository",
                           "verify": "`tracker_write.py --force` asks again"})
    return cap(UNKNOWN, "orchestrator", r["reason"], gap_id="tracker-write",
               remedy={"kind": "human_step", "autorun": False, "owner": "orchestrator",
                       "need": "one question to the tracker agent, which no script can ask",
                       "steps": [r.get("ask") or "ask whether the channel may create issues",
                                 'tracker_write.py --record confirmed|no --words "<its answer>"'],
                       "blocks": "nothing yet — bugs are filed locally either way",
                       "verify": "readiness.py re-reads state/integrations/tracker-write.json and the answer "
                                 f"recorded in {RP.rel_text('onboarding-approvals.jsonl', root)}"})


def check_external_writes(cfg: dict, root: Path) -> dict:
    channels = cfg.get("external_writes") or {}
    if not channels:
        return cap(NOT_CONFIGURED, "user",
                   "external_writes is empty — onboarding sets the bugs and cases channels "
                   "(markdown is the default and a first-class choice)")
    adapters = cfg.get("adapters") or {}
    unconfigured = []
    for kind, channel in channels.items():
        # `channels` is the per-channel delivery map, probed below; `probe`, `bugs_project`,
        # `commands` and `write_scopes` are settings of the writes, not channels of their own.
        if kind in ("channels", "commands", "write_scopes", "probe", "bugs_project") or not isinstance(channel, str):
            continue
        value = str(channel or "").strip()
        if not value or value in MARKDOWN_CHANNELS:
            continue
        key = "ticket" if kind == "bugs" else "test_management"
        entry = adapters.get(key) or {}
        if str(entry.get("name") or entry.get("kind") or "") != value or str(entry.get("status") or "") != "configured":
            unconfigured.append(f"{kind}={value}")
    if unconfigured:
        return cap(NOT_CONFIGURED, "user",
                   "channels without a configured adapter: " + ", ".join(unconfigured) +
                   " — either configure the adapter or set the channel to markdown")
    # A delivery command is the same claim as the ticket adapter's, and deserves the same proof.
    for channel, delivery in (channels.get("channels") or {}).items():
        if not isinstance(delivery, dict):
            continue
        command = str(delivery.get("command") or "").strip()
        if command and not probe_executable(command, root):
            return cap(MISSING, "user",
                       f"external_writes.channels.{channel} delivers with `{command}`, but "
                       f"`{executable_of(command)}` is not on PATH in this session — install it, "
                       "or set the channel to markdown so bugs stay in the repository")
    return cap(OK, "factory", "channels: " + ", ".join(
        f"{k}={v}" for k, v in channels.items() if k != "channels"))


# Top-level keys the template carries but a config written under the CURRENT
# schema_version may legitimately lack: they were added to the template after that version
# and their absence has a documented default. Without this list, shipping one new key makes
# every existing install report `config_schema: not_configured` and S0 refuses to start —
# so the choice would be "never add a key" or "re-onboard everyone". A key moves out of
# here when schema_version is bumped, and then its absence is a real gap.
#
# The list is DATA (FR-13): `references/config-keys.json`, `keys.<key>.absent_means: default`,
# one entry per top-level template key with the release that added it. It was a tuple here, and
# `handoffs`, `prompts` and `retro` were never added to it, so the live config of a 0.7.x project
# read `not_configured` over three keys with working defaults (t-232 C8). A test now fails when
# the template carries a key the table does not name.
def _optional_top_keys() -> tuple:
    try:
        keys = config_keys()["keys"]
    except ValueError:
        return ()
    return tuple(k for k, meta in keys.items()
                 if "." not in k and isinstance(meta, dict) and meta.get("absent_means") == "default")


OPTIONAL_TOP_KEYS = _optional_top_keys()


def template_top_keys() -> list:
    """The template's top-level keys a config MUST carry: those config-keys.json does not call
    `default`. A template key the table does not name counts as required - the error direction
    that fails loudly in the test suite instead of silently in a project."""
    try:
        data = json.loads((ref("templates") / "config.json").read_text(encoding="utf-8"))
        optional = _optional_top_keys()
        return [k for k in data.keys()
                if not k.endswith("_note") and k not in optional]
    except Exception:
        return []


def check_execution_profile(cfg: dict) -> dict:
    """Can anything in this configuration RUN one test? (TP2-2553)

    `run_suite.py --mine` builds its command from `profiles[].commands.one_test.argv` and from
    nothing else — the top-level `test_command_templates` are read by the gate rehearsal's
    collect and by no runner, so they are not a second shape that answers this. A project
    without such a profile therefore passed S0 green, passed gate A in silence, and then
    refused every run inside S5; the whole story's requests were typed by hand.

    It is the onboarding's gap, not the person's homework, so the note names the onboarding
    command and the status is `not_configured` — a warning `--require` prints and exits 0 on,
    never a halt: cases can still be written, reviewed and handed to a person to run."""
    profiles = cfg.get("profiles")
    named, runnable, broken = [], [], []
    for profile in profiles if isinstance(profiles, list) else []:
        if not isinstance(profile, dict) or not str(profile.get("profile_id") or "").strip():
            continue
        pid = str(profile["profile_id"]).strip()
        named.append(pid)
        # The same reading `execution_request._command_from_profile` does, through the ONE reader (AR-13): an argv that is
        # nothing but placeholders is not a command, and a shape the reader cannot read is no command either - and is named.
        words, problem = one_test_argv(profile, drop_placeholders=True)
        if problem:
            broken.append(f"profile {pid}: {problem}")
        elif words:
            runnable.append(pid)
    # a healthy profile never hides a broken one, and a broken one never takes the healthy one's place
    if runnable:
        return cap(OK, "user", "execution profile(s) with a one-test command: " + ", ".join(runnable)
                   + ("; not readable: " + "; ".join(broken) if broken else ""))
    note = ("no execution profile in qa-factory/config.json — nothing configured here can run a "
            "test, and S5 would refuse every run (mine_refused)") if not named else (
        "no execution profile has commands.one_test.argv (" + ", ".join(named) + ") — S5 would "
        "refuse every run (mine_refused)" + (": " + "; ".join(broken) if broken else ""))
    return cap(NOT_CONFIGURED, "user", note,
               remedy={"kind": "human_step", "autorun": False, "owner": "user",
                       "need": "the command that runs ONE test of this project: its argv, the "
                               "directory it runs in, and the report it writes",
                       "steps": ["/qa-factory:qa-onboarding — its execution batch asks for that "
                                 "command and writes the profile into qa-factory/config.json",
                                 "or add profiles[] with commands.one_test {argv, cwd, reporter} "
                                 "to qa-factory/config.json by hand"],
                       "blocks": "every automated run of S5 (run_suite.py --mine refuses); the "
                                 "cases are still written and reviewed, and gate A asks you "
                                 "whether to onboard now, name the command, or run them yourself",
                       "verify": "run_suite.py --mine <a case of the story> launches instead of "
                                 "printing mine_refused"})


def check_project_dependencies(cfg: dict, root: Path) -> dict:
    """Does what is installed in the PROJECT's environment match the project's own lock? (RH1-4)

    `dependency_drift.check_profiles` reads the lock and the installed set of the project's environment (never the
    factory's), once per distinct environment of the SELECTED profiles (a profile with no `selected` key is selected), and
    answers; this only turns the worst answer into a capability. A difference or a missing package is `missing`, owner
    `user`, and the remedy is the project's install command AS RECORDED (the profile's `commands.install`, else the package
    manager's table row), or the sentence to record one at onboarding when there is none. The doctor PRINTS the command and
    never runs it (FR-48; installing is the conductor's, C3-18 part 2). `unknown` (no lock, a lock format not read yet, an
    environment the factory cannot read) is the factory's question, not the person's next step."""
    try:
        import dependency_drift
        import profile_contract
        entries = dependency_drift.check_profiles(root, profile_contract.selected_profiles(cfg))
    except Exception as exc:  # a reader that cannot run is an unknown, never a pass
        return cap(UNKNOWN, "factory", f"the dependency check did not run ({type(exc).__name__})")
    head = entries[0]["result"]
    state = head["state"]
    if state == "in_sync":
        return cap(OK, "factory", head["why"], checked=head["checked"], lock=head["lock"])
    if state == "unknown":
        return cap(UNKNOWN, "factory", head["why"] or "the installed libraries could not be compared with the lock",
                   remedy={"kind": "probe", "autorun": False, "owner": "factory",
                           "need": "the project's environment and a lock the factory reads, to compare them",
                           "steps": ["dependency_drift.py <project root> --json names what could not be read"],
                           "blocks": "nothing on its own: tests still run; a failed import on a stale library is "
                                     "then reported as the project's environment",
                           "verify": "dependency_drift.py <project root> prints in_sync"})
    steps = []
    for entry in entries:
        command = entry["result"]["command"]
        text = dependency_drift.command_text(command)
        where = command.get("cwd") or "."
        step = (text if where in ("", ".") else f"in {where}: {text}") if text else "record the project's install command at onboarding"
        if entry["result"]["state"] in ("differs", "missing_only") and step not in steps:
            steps.append(step)
    return cap(MISSING, "user", dependency_drift.drift_text(entries), checked=head["checked"], lock=head["lock"],
               remedy={"kind": "human_step", "autorun": False, "owner": "user",
                       "need": "the libraries the project's tests import, installed at the versions its lock pins",
                       "steps": steps,
                       "blocks": "tests that import a library at the wrong version fail or run old code; gate A and S5 report "
                                 "the pair of versions. Cases can still be written and reviewed",
                       "verify": "dependency_drift.py <project root> prints in_sync"})


def check_config_schema(cfg: dict) -> dict:
    """The schema verdict as `_config_schema_status` decides it, plus - on ANY outcome that has a `note` - the line that
    names an unknown `pipeline.stop_after` (GW1-19). Status and owner never change: the value stops nothing, so it is a
    note, not a refusal (P1, I-6)."""
    result = _config_schema_status(cfg)
    problem = stop_after_problem(cfg)
    if problem and result.get("note"):
        result["note"] = f"{result['note']} {problem}"
    return result


def _config_schema_status(cfg: dict) -> dict:
    version = cfg.get("schema_version")
    try:
        config_keys()
    except ValueError as exc:
        # An unreadable key table is the plugin's damage, not a verdict on the project's
        # config: `unknown` (FR-41), never an empty list of required keys that passes everything.
        return cap(UNKNOWN, "factory", f"cannot tell which keys the configuration needs: {exc}")
    missing_keys = [k for k in template_top_keys() if k not in cfg]
    contract_errors = validate_config_contract(cfg)
    if version == REQUIRED_SCHEMA_VERSION and not missing_keys and not contract_errors:
        return cap(OK, "factory", f"schema_version {version}")
    hint = missing_keys
    if version != REQUIRED_SCHEMA_VERSION:
        return cap(MISSING, "user",
                   f"schema_version is {version!r}, this plugin requires {REQUIRED_SCHEMA_VERSION} — "
                   "re-run qa-onboarding or add the missing keys by hand",
                   migration_hint=hint)
    return cap(NOT_CONFIGURED, "user",
               "schema_version matches but configuration needs a migration decision: " +
               "; ".join(contract_errors or ["top-level keys are missing compared with the template: "
                                             + ", ".join(missing_keys)]),
               migration_hint=hint, validation_errors=contract_errors)


def compute(cfg: dict, root: Path, selected_profiles: list[str] | None = None,
            selected_repos: set[str] | None = None, probe_vcs: bool = False,
            no_trace: bool = False) -> dict:
    original_cfg = cfg
    cfg = effective_config(cfg)
    data = {
        "schema_version": REQUIRED_SCHEMA_VERSION,
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "capabilities": {
            "ticket_adapter": check_ticket_adapter(cfg, root),
            "jira_direct_api": check_jira_direct(cfg, root),
            "test_repo": check_test_repo(cfg, root),
            "case_store": check_case_store(cfg, root),
            "case_id_form": check_case_id_form(cfg),
            "adapter_forms": check_adapter_forms(cfg),
            "app_repo": check_app_repo(cfg, root),
            "vcs": check_vcs(root, probe_vcs),
            "environment": check_environment(cfg, root),
            "external_writes": closed_for_run() if no_trace else check_external_writes(cfg, root),
            "tracker_write": check_tracker_write(cfg, root, no_trace),
            "project_dependencies": check_project_dependencies(cfg, root),
            "config_schema": check_config_schema(cfg),
        },
        "repository_inventory": build_inventory(original_cfg, root, selected_repos),
        "telemetry": {"status":"unverified", "owner":"factory",
                      "note":"Claude and response-scoped Codex usage adapters are shipped; this project has no verified usage receipt yet. Host activation and pricing are separate checks."},
    }
    from host_capabilities import inspect as inspect_host
    data['host_integration'] = inspect_host(root)
    from vcs_evidence import readiness as api_readiness, read_api_receipts, api_capability
    # A merge request read through the API (a receipt of `vcs_evidence.py`) is proof the API works, so this regenerated
    # file no longer says "not verified" about what the story already proved; the live probe, when it ran, and a fresh
    # refusal still come first (HF8-12, W-4; the table is in `vcs_evidence.api_capability`).
    data['capabilities']['vcs_api'] = api_capability(api_readiness(cfg, root) if probe_vcs else None,
                                                     read_api_receipts(root)) or {
        'status': 'unknown', 'owner': 'orchestrator',
        'note': 'Run readiness.py --probe-vcs or probe the exact required MR through its configured route; local Git does not verify API access.'}
    data['capabilities']['vcs_api']['required_for'] = ['provider_api_operations', 'required_mr_metadata_and_discussions']
    # Built through cap() like every other capability, so it cannot be the one row that
    # reaches a person with no remedy attached — which is exactly what it was.
    # `ok` also when a real role dispatch of this project was handed its packet and the live guard is verified, on a host
    # where `story_ready` is not a gate (HF8-12, W-5): `hooks_proved` is the one statement of that condition.
    from host_capabilities import hooks_proved
    hooks_ok = hooks_proved(data['host_integration'])
    data['capabilities']['host_hooks'] = cap(
        OK if hooks_ok else UNKNOWN,
        'factory', data['host_integration']['note'],
        **({'proved_by': 'role_context'} if hooks_ok and not data['host_integration'].get('story_ready') else {}),
        remedy={'kind': 'probe', 'autorun': False, 'owner': 'factory',
                'need': 'the live allow/deny hook probe, which needs native shell calls and so '
                        'cannot be run by a script on its own',
                'steps': ['qa-doctor step 1b runs it: host_probe.py --prepare, the two echo '
                          'commands as separate native calls, then --check'],
                'blocks': 'nothing on its own — it is evidence about the host, not a missing '
                          'capability, and a story is not held up by an unrun probe',
                'verify': 'host_probe.py --check after the pair'})
    from runtime_paths import resolve_runtime
    try:
        data['runtime_paths'] = {'status': 'ok', **resolve_runtime(root, root)}
    except (OSError, ValueError) as exc:
        data['runtime_paths'] = {'status': 'missing', 'owner': 'factory', 'reason': str(exc)}
    data['orchestrator_context'] = {
        'status': 'manual_continuation', 'owner': 'host',
        'fresh_orchestrator_context': False,
        'note': 'No bundled host adapter has verified automatic fresh-session creation. '
                'Save the durable checkpoint and resume qa-story in a new session; approvals are retained.'}
    for path in sorted_paths((root / 'qa-factory/state/cost').glob('*.json')):
        try:
            receipt=json.loads(path.read_text(encoding='utf-8'))
            if receipt.get('requests'):
                data['telemetry']={"status":"recorded", "owner":"factory",
                    "note":"Usage receipts are present; completeness: "+str(receipt.get("usage_completeness"))+". Pricing is reported separately on the dashboard.",
                    "evidence":str(path.relative_to(root))}
                break
        except (ValueError,OSError):
            continue
    # Published beside `profiles`/`profile_contract` rather than inside `capabilities`: the
    # capability block is pinned key-for-key to references/templates/readiness.json, and a
    # project must not have to re-onboard to be told its execution is unconfigured.
    data["execution_profile"] = check_execution_profile(cfg)
    # What the project tests on that an agent's hands cannot reach, or has no stand for (EP1-41a): the key exists only when
    # there is something to say, so a web or API project's document is unchanged. A broken table is `unknown`, never a crash
    # and never silence (AR-28).
    import surfaces
    try:
        declared = surfaces.declared_surfaces(cfg)
    except ValueError as exc:
        declared = {surfaces.UNKNOWN: str(exc)}
    if declared:
        data["surfaces"] = declared
    # Profiles are additive. Configs written before this contract retain the exact legacy
    # readiness shape; once profiles are present, their scoped result is published alongside it.
    if "profiles" in cfg:
        errors = validate_profile_config(cfg)
        data["profiles"] = profile_readiness(cfg, selected_profiles, root)
        data["implementation_repos"] = implementation_repo_readiness(cfg, data["profiles"], root)
        data["profile_contract"] = {"status": "ok" if not errors else "missing",
                                    "owner": "user", "errors": errors}
    return data


def print_summary(data: dict) -> None:
    caps = data.get("capabilities") or {}
    width = max(len(k) for k in caps) if caps else 0
    for name in CAPABILITIES:
        entry = caps.get(name) or {}
        status = entry.get("status", UNKNOWN)
        owner = entry.get("owner", "")
        print(f"  {name.ljust(width)}  {status:<15} owner: {owner:<8} {entry.get('note', '')}")
        for key in entry.get("migration_hint") or []:
            print(f"  {' ' * width}    add config key: {key}")
    profile = data.get('execution_profile')
    if profile:
        print(f"  execution_profile  {profile['status']:<15} owner: {profile['owner']:<8} {profile['note']}")
    host=data.get('host_integration')
    if host:print(f"  host_integration  {host['status']}  missing: {', '.join(host['missing'])}; live parity: {host['live_parity']}")
    telemetry=data.get('telemetry')
    if telemetry:print(f"  telemetry  {telemetry['status']}  {telemetry['note']}")
    runtime = data.get('runtime_paths', {})
    if runtime: print(f"  runtime_paths  {runtime['status']}  {runtime.get('plugin_root') or runtime.get('reason')}")
    context = data.get('orchestrator_context', {})
    if context: print(f"  orchestrator_context  {context['status']}  {context['note']}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Project readiness by capability")
    ap.add_argument("--write", action="store_true", help="write <project>/qa-factory/state/readiness.json")
    ap.add_argument("--json", action="store_true", help="print the document to stdout")
    ap.add_argument("--probe-vcs", action="store_true", help="probe Git remote read access and provider API identity independently")
    ap.add_argument("--require", default="", help="comma-separated capability names; exit 1 if any is not ok")
    ap.add_argument("--profiles", default="",
                    help="comma-separated execution profiles to evaluate (others cannot block them)")
    ap.add_argument("--repos", default="",
                    help="comma-separated repository ids/names in selected scope")
    ap.add_argument("--no-trace", action="store_true", dest="no_trace",
                    help="experiment run: the tracker-write and external-writes checks are closed "
                         "for this run and nothing is probed (P8)")
    args = ap.parse_args()

    if not config_path().exists():
        sys.exit(0)  # not an onboarded project — say nothing

    root = project_root()
    selected_profiles = [p.strip() for p in args.profiles.split(",") if p.strip()] or None
    selected_repos = set(filter(None, (part.strip() for part in args.repos.split(","))))
    data = compute(load_config(), root, selected_profiles, selected_repos, args.probe_vcs,
                   args.no_trace)

    if args.write:
        target = RP.readiness_write(root)       # qa-factory/state/readiness.json: regenerated, machine-local
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"readiness.json written: {target}")

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif not args.write:
        print(f"READINESS ({root})")
        print_summary(data)

    if args.require:
        wanted = [c.strip() for c in args.require.split(",") if c.strip()]
        unknown = [c for c in wanted if c not in CAPABILITIES]
        if unknown:
            print(f"unknown capability name(s): {unknown} — known: {CAPABILITIES}", file=sys.stderr)
            sys.exit(1)
        blockers, warnings = [], []
        for name in wanted:
            entry = (data.get("capabilities") or {}).get(name) or {}
            line = f"{name}: {entry.get('status')} — {entry.get('note')} (owner: {entry.get('owner')})"
            # A blocker is a capability the story asked for that this machine ANSWERED with a
            # refusal. `unknown` is an unfinished question — an unreachable host, a probe
            # nobody ran — and an unfinished question stops nothing; it is named at gate A.
            # host_hooks and vcs_api used to block on anything but `ok`, which meant a
            # hardcoded host label and a dropped VPN could each, alone, refuse to start a
            # story that needed neither the provider API nor a live hook probe.
            if entry.get("status") == MISSING:
                blockers.append(line)
            elif entry.get("status") != OK:
                warnings.append(line)  # not_configured / unknown: the story can run, the gap is named at gate A
        # The short stop_after line is printed at EVERY status: S0 folds every `WARN` line into `pipeline.warnings` and gate A
        # cuts each one to 180 characters (`gate_brief.py`), and a not-ok config_schema note is longer than that, so the long
        # form inside it would be cut before it names the stop (GW1-19, F-1). It goes right after the capability lines, short.
        stop_line = stop_after_problem(load_config(), short=True) if "config_schema" in wanted else ""
        for w in warnings:
            print(f"WARN {w}")
        if stop_line:
            print(f"WARN {stop_line}")
        if blockers:
            print("THIS STORY CANNOT START — capabilities it needs are not available:\n- "
                  + "\n- ".join(blockers), file=sys.stderr)
            sys.exit(1)
        print(f"required capabilities available: {', '.join(wanted)}")
    sys.exit(0)


if __name__ == "__main__":
    main()
