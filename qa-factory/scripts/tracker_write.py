"""Can this factory actually CREATE an issue in the tracker it is told to file bugs into?

The owner's decision of 21.09.2026: the factory shows the bugs as a list in the chat and
files the ones the person approved. A tracker that can only be read is not a property of the
project to be lived with — it is an unfinished setup of the factory in that project, and it
belongs at onboarding, at the doctor and at S0, never after gate B.

TP2-2534 is the story that earned it. The run was good (169/169, three real product
problems found) and not one finding reached Jira: the project's channel was an assistant with
read-only rights, and the factory learned that AFTER the person had chosen which bugs to file.

What this proves is deliberately small — the RIGHT to create, not the success of one issue:

  direct API   `mypermissions` says CREATE_ISSUES in the bug project, and `createmeta` names
               the fields that project will demand, so a required field nobody filled is
               named in advance instead of rejecting the write.
  an assistant no script can call one, so the evidence is the project's own declaration
               (`external_writes.channels.<c>.writes`) plus ONE question to the assistant,
               which only the orchestrator can ask. This module hands over the exact prompt
               and takes the answer back through `--record`.

Nothing here writes to the tracker, and nothing here can: every request is a GET through
`source_inventory.JiraClient`, which sends no body and knows no other verb.

Credentials are env var NAMES in the config and stay names here: the receipt, the findings and
every printed line carry `QA_JIRA_API_TOKEN`, never what it holds.

  tracker_write.py                  the cached answer, re-probed when it is stale
  tracker_write.py --force --json   probe again whatever the cache says
  tracker_write.py --record confirmed --words "the assistant answered: it can create issues"

The receipt lives at `qa-factory/state/integrations/tracker-write.json` with the date and a
fingerprint of the channel's settings, so a probe does not run on every story: onboarding and
the doctor always probe, S0 re-probes after a day or a changed channel, and the gate B
rehearsal after a few hours (a token can expire inside one story).

The receipt is a probe cache: every onboarding and every doctor run rewrites it, so it is
machine-local (ignored by git, never moved by a reinstall). What a person said is not a cache:
`--record` also appends the answer as one `tracker_write_answer` line to the carried approvals
log (`qa-factory/records/onboarding-approvals.jsonl`), and a probe finding no `answered` in the
receipt (a fresh clone, a new machine) reads the latest such line instead.
"""
import argparse
import functools
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402  (`read_json`, the one JSON reader)
import runtime_paths as RP  # noqa: E402 - the receipt is machine-local (state/), the person's answer is carried (records/)

# The receipt is a probe cache that readiness rewrites on every run: machine-local, in `state/`, one
# place in every layout and never moved (t-232 F1 as decided by Lead after t-260). Its parts under
# `qa-factory/state/`, resolved through `runtime_paths.state_file`, never joined by hand.
RECEIPT = ("integrations", "tracker-write.json")
# The person's answer outlives the cache: a line of this kind in the carried approvals log (a
# record: `qa-factory/records/`, same name as config_contract.APPROVALS_NAME).
APPROVALS = "onboarding-approvals.jsonl"
ANSWER_KIND = "tracker_write_answer"
CONFIRMED = "confirmed"
NO = "no"
UNVERIFIED = "unverified"
STATUSES = (CONFIRMED, NO, UNVERIFIED)
# Factory defaults; `external_writes.probe.max_age_h` / `.gate_b_max_age_h` override them.
DEFAULT_MAX_AGE_H = 24
DEFAULT_GATE_B_MAX_AGE_H = 4
LOCAL_CHANNELS = ("", "markdown", "none", "file")
AGENT_METHODS = ("agent", "skill")
DIRECT_METHODS = ("api", "direct", "direct_api")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# The package's one JSON reader. This module's direction: whatever goes wrong while reading is `default`, None unless passed.
_read_json = functools.partial(hooklib.read_json, errors=Exception)


def _age_hours(checked_at: str):
    try:
        stamp = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
    except Exception:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0


def _writes(config) -> dict:
    """The config's `external_writes` as an object: an absent, empty or non-object value (a string a hand-edit left) is `{}`, so
    every reader below treats it as "nothing recorded" instead of failing with AttributeError (`validate` does not refuse it)."""
    ew = config.get("external_writes") if isinstance(config, dict) else None
    return ew if isinstance(ew, dict) else {}


def max_age_h(config: dict, where: str = "story") -> float:
    probe_cfg = (_writes(config).get("probe") or {})
    key = "gate_b_max_age_h" if where == "gate_b" else "max_age_h"
    default = DEFAULT_GATE_B_MAX_AGE_H if where == "gate_b" else DEFAULT_MAX_AGE_H
    try:
        return float(probe_cfg.get(key, default))
    except Exception:
        return float(default)


def channel_of(config: dict) -> str:
    return str(_writes(config).get("bugs") or "markdown").strip()


def bug_project(config: dict) -> str:
    """The tracker project bugs are filed into: `external_writes.bugs_project`, else the first
    project key onboarding already recorded for the tracker adapter."""
    explicit = str(_writes(config).get("bugs_project") or "").strip()
    if explicit:
        return explicit.upper()
    keys = ((config.get("adapters") or {}).get("ticket") or {}).get("project_keys") or []
    for key in keys if isinstance(keys, list) else []:
        if str(key).strip():
            return str(key).strip().upper()
    return ""


def fingerprint(config: dict) -> str:
    """Everything about the channel that could change the answer — names only, never values.

    A receipt whose fingerprint no longer matches is not evidence about the current setup, so
    a project that swapped a read-only assistant for a token is re-probed on the next run
    rather than believed for another day."""
    ew = _writes(config)
    channel = channel_of(config)
    entry = (ew.get("channels") or {}).get(channel)
    entry = entry if isinstance(entry, dict) else {}
    direct = ((config.get("adapters") or {}).get("ticket") or {}).get("direct_api") or {}
    payload = {
        "channel": channel,
        "method": str(entry.get("method") or ""),
        "invoke": str(entry.get("invoke") or ""),
        "command": json.dumps(entry.get("command") or (ew.get("commands") or {}).get(channel) or ""),
        "writes": entry.get("writes"),
        "project": bug_project(config),
        "base_url": str(direct.get("base_url") or ""),
        "auth_type": str(direct.get("auth_type") or ""),
        "username_ref": str(direct.get("username_ref") or ""),   # the NAME of the variable
        "secret_ref": str(direct.get("secret_ref") or ""),       # likewise: never its content
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def receipt_path(project_root) -> Path:
    return RP.state_file(project_root, *RECEIPT)


def recorded_answers(project_root) -> list:
    """Every `tracker_write_answer` line of the carried approvals log -> its `answered` dict, in file
    order ([] when there is no log or no such line). A line that cannot be read is skipped: an
    answer not found is asked once more, the safe direction (FR-41)."""
    try:
        lines = RP.record(Path(project_root), APPROVALS).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        try:
            item = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(item, dict) and item.get("kind") == ANSWER_KIND and isinstance(item.get("answered"), dict):
            found.append(item["answered"])
    return found


def recorded_answer(project_root):
    """The latest line of `recorded_answers` (by position in the log), or None."""
    found = recorded_answers(project_root)
    return found[-1] if found else None


def _stamp(answered: dict):
    """The `at` of an answer as an aware datetime, or None when it is missing or unreadable."""
    try:
        stamp = datetime.fromisoformat(str(answered.get("at")).replace("Z", "+00:00"))
    except Exception:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def newest_answer(fingerprint_now: str, receipt_answered, logged: list):
    """The answer a probe goes by: among those that are about THIS channel setup (same fingerprint,
    a status of `confirmed` or `no`) the one with the NEWER `at` wins - the receipt's own and the
    person's lines of the approvals log are one pool (t-272 item 4: a receipt that kept a 09-23
    `confirmed` used to hide a 10-01 `no` written by a clone or another machine). Equal `at` goes
    to the receipt; among log lines of equal `at` the later line. An answer with no readable `at`
    is the oldest there is. One of another fingerprint never counts: it is not evidence about this
    setup. None when nothing fits."""
    def fits(answer) -> bool:
        return (isinstance(answer, dict) and answer.get("fingerprint") == fingerprint_now
                and answer.get("status") in (CONFIRMED, NO))
    floor = datetime.min.replace(tzinfo=timezone.utc)

    def when(answer):
        return _stamp(answer) or floor
    best = None
    for answer in logged:
        if fits(answer) and (best is None or when(answer) >= when(best)):
            best = answer
    if fits(receipt_answered) and (best is None or when(receipt_answered) >= when(best)):
        best = receipt_answered
    return best


def _remember_answer(project_root, channel: str, answered: dict) -> None:
    """Append the person's answer to the carried approvals log (one line, never a rewrite)."""
    path = RP.record(Path(project_root), APPROVALS)
    line = json.dumps({"kind": ANSWER_KIND, "channel": channel, "answered": answered,
                       "at": answered.get("at")}, ensure_ascii=False)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        glue = "\n" if path.is_file() and path.stat().st_size and not path.read_bytes().endswith(b"\n") else ""
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(glue + line + "\n")
    except OSError:
        pass  # a probe never fails over its own bookkeeping


def load_receipt(project_root) -> dict:
    data = _read_json(receipt_path(project_root))
    return data if isinstance(data, dict) else {}


def save_receipt(project_root, receipt: dict) -> None:
    path = receipt_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    except OSError:
        pass  # a probe never fails over its own bookkeeping


def agent_prompt(invoke: str, project: str) -> str:
    """The one question the orchestrator asks the assistant. It asks about a RIGHT and never
    asks for an issue: a probe that creates a ticket to prove it can create tickets leaves
    litter in a real project every time a doctor runs."""
    where = f"the `{project}` project" if project else "the project this factory files bugs into"
    return (f"Answer in one line, create nothing: do you have permission to CREATE issues in "
            f"{where}? Reply exactly `writes: yes` or `writes: no`, and if no, say which "
            f"permission or integration is missing. Do not create, update or comment on any "
            f"issue while answering.")


def _client(config: dict):
    """The read-only Jira client. A separate function so a test can substitute a fake opener:
    the probe must never reach a real tracker from a test run."""
    from source_inventory import client_from_config
    return client_from_config(((config.get("adapters") or {}).get("ticket") or {}))


def _required_fields(meta: dict, project: str) -> list:
    """Fields the project will demand of a created issue, from `createmeta`.

    The limit of the probe, named in the plan: a permission proves the right, not the success
    of one issue — a mandatory project field can still reject the request. For the direct API
    that hole is closed here, ahead of the write, by naming the fields nobody has filled."""
    out = []
    for proj in (meta or {}).get("projects") or []:
        if project and str(proj.get("key") or "").upper() != project.upper():
            continue
        for issue_type in proj.get("issuetypes") or []:
            if str(issue_type.get("name") or "").lower() not in ("bug", "defect"):
                continue
            for name, field in (issue_type.get("fields") or {}).items():
                if not isinstance(field, dict) or not field.get("required"):
                    continue
                if field.get("hasDefaultValue") or name in ("project", "issuetype", "summary"):
                    continue
                out.append(str(field.get("name") or name))
    return sorted(set(out))


def _probe_direct(config: dict, channel: str) -> dict:
    """GET `mypermissions`, then GET `createmeta`, then GET `myself`. Three reads; nothing is
    created. `myself` names the token's OWNER: `gate_brief.py`'s filing line and
    `external_writes.py`'s own "writing as" line are both read-only / one-shot by contract, so
    the display name they need travels in THIS cached receipt rather than a live call of
    their own."""
    project = bug_project(config)
    base = {"channel": channel, "checked_at": _now(), "method": "direct_api", "project": project}
    if not project:
        return dict(base, status=UNVERIFIED,
                    reason="no bug project is named — set `external_writes.bugs_project` (or "
                           "`adapters.ticket.project_keys`) so the right to create can be asked "
                           "about a project")
    try:
        client = _client(config)
    except Exception as exc:
        return dict(base, status=UNVERIFIED,
                    reason=f"the direct tracker API is not usable from this session "
                           f"({type(exc).__name__}: {exc})")
    version = getattr(client, "api_version", "2")
    try:
        answer = client.get_json(
            f"/rest/api/{version}/mypermissions?projectKey={project}&permissions=CREATE_ISSUES")
    except Exception as exc:
        return dict(base, status=UNVERIFIED,
                    reason=f"the permission question could not be asked: "
                           f"{getattr(exc, 'reason', None) or f'{type(exc).__name__}: {exc}'}")
    entry = ((answer or {}).get("permissions") or {}).get("CREATE_ISSUES") or {}
    if entry.get("havePermission") is not True:
        return dict(base, status=NO,
                    reason=f"the account behind the configured token may not create issues in "
                           f"`{project}` (Jira answers CREATE_ISSUES: no)")
    required = []
    try:
        meta = client.get_json(f"/rest/api/{version}/issue/createmeta?projectKeys={project}"
                               "&expand=projects.issuetypes.fields")
        required = _required_fields(meta, project)
    except Exception:
        required = []  # the right is proven either way; the field list is the extra half
    author = {"username_ref": getattr(client, "username_ref", "") or "", "display_name": ""}
    try:
        identity = client.get_json(f"/rest/api/{version}/myself")
        author["display_name"] = str(identity.get("displayName") or identity.get("name")
                                     or identity.get("accountId") or "")
    except Exception:
        pass  # the right to create is proven either way; the author's name is the extra half
    return dict(base, status=CONFIRMED, required_fields=required, author=author,
                reason=f"the configured token may create issues in `{project}`"
                       + (f"; that project requires: {', '.join(required)}" if required else ""))


def probe(config: dict, project_root, force: bool = False, where: str = "story",
          save: bool = True) -> dict:
    """`{"status", "reason", "checked_at", "channel"}` — plus `ask`, `required_fields` and
    `alternatives` when there are any. Cached; `force` ignores the cache.

    `where` picks the freshness rule only: `onboarding` / `doctor` always probe, `gate_b`
    re-probes after a few hours, everything else after a day.

    `save=False` is for the gate rehearsal, which is read-only by contract: a rehearsal that
    wrote a receipt would be a second way to change the project's state."""
    config = config or {}
    channel = channel_of(config)
    cached = load_receipt(project_root)
    if not force and where not in ("onboarding", "doctor"):
        age = _age_hours(cached.get("checked_at"))
        if (cached.get("status") in STATUSES and cached.get("fingerprint") == fingerprint(config)
                and age is not None and 0 <= age <= max_age_h(config, where)):
            # A fresh receipt is not believed over a NEWER answer of the approvals log (item 4): that
            # one falls through to the probe below, which folds it in.
            newest = newest_answer(cached["fingerprint"], cached.get("answered"), recorded_answers(project_root))
            if newest is None or newest is cached.get("answered"):
                return dict(cached, cached=True)

    result = _answer(config, channel)
    result["fingerprint"] = fingerprint(config)
    # An answer a person already carried back from the assistant is evidence, and it is not
    # thrown away by a re-probe that only re-read the same config. Precedence (t-272 item 4): of the
    # receipt's own `answered` (a cache a clone or a new machine does not have) and the person's lines
    # in the carried approvals log, the NEWER `at` among those about this setup wins - the receipt
    # does not hide a newer line of the log; none fits: unanswered.
    answered = newest_answer(result["fingerprint"], cached.get("answered"), recorded_answers(project_root))
    if answered is not None and result["status"] == UNVERIFIED:
        result["status"] = answered["status"]
        result["reason"] = str(answered.get("reason") or result["reason"])
        result["answered"] = answered
    elif answered is not None:
        result["answered"] = answered
    if save:
        save_receipt(project_root, result)
    return result


def _answer(config: dict, channel: str) -> dict:
    """The probe proper, cache aside."""
    base = {"channel": channel, "checked_at": _now()}
    if channel.lower() in LOCAL_CHANNELS:
        # Not a gap: bugs kept in the repository need no tracker, and the S0 warning must not
        # nag about a tracker that was never asked for. The code cannot tell a recorded
        # choice from a template default (channel_of fills a missing key), so the text states
        # the value, not whose choice it is (FR-41).
        raw = _writes(config).get("bugs")
        shown = "not set" if raw in (None, "") else str(raw)
        return dict(base, status=NO, applicable=False, method="markdown",
                    reason=f"bugs stay in the repository (external_writes.bugs = {shown}) "
                           "— nothing is written to a tracker")
    ew = _writes(config)
    try:
        from external_writes import channel_delivery
        delivery = channel_delivery(ew, channel)
    except Exception:
        entry = (ew.get("channels") or {}).get(channel)
        entry = entry if isinstance(entry, dict) else {}
        delivery = {"method": str(entry.get("method") or "none"),
                    "command": entry.get("command"), "invoke": str(entry.get("invoke") or "")}
    method = str(delivery.get("method") or "none").lower()
    entry = (ew.get("channels") or {}).get(channel)
    entry = entry if isinstance(entry, dict) else {}
    declared = entry.get("writes")
    base["method"] = method

    if method == "none":
        return dict(base, status=NO,
                    reason=f"external_writes.bugs goes to `{channel}` and nothing is configured "
                           "to perform that write — no command, no agent",
                    alternatives=_alternatives(config))
    if method in DIRECT_METHODS:
        return dict(_probe_direct(config, channel), alternatives=_alternatives(config))
    if method in AGENT_METHODS:
        invoke = str(delivery.get("invoke") or "")
        if not invoke:
            return dict(base, status=NO,
                        reason=f"`{channel}` is delivered by a session {method} and "
                               f"external_writes.channels.{channel}.invoke is empty",
                        alternatives=_alternatives(config))
        if declared is False:
            return dict(base, status=NO, invoke=invoke,
                        reason=f"the project declares `{invoke}` as read-only "
                               f"(external_writes.channels.{channel}.writes: false)",
                        alternatives=_alternatives(config))
        return dict(base, status=UNVERIFIED, invoke=invoke, declared_writes=bool(declared),
                    ask=agent_prompt(invoke, bug_project(config)),
                    reason=(f"`{invoke}` is declared able to write, and no script can call an "
                            "assistant: ask it once and record the answer"
                            if declared else
                            f"nothing says whether `{invoke}` may create issues — the config "
                            f"does not declare external_writes.channels.{channel}.writes and "
                            "nobody has asked it"),
                    alternatives=_alternatives(config))
    # A command channel: the executable exists or it does not, and its rights are the
    # tracker's business. Proving them would mean writing, which this module never does.
    return dict(base, status=UNVERIFIED,
                reason=f"`{channel}` is delivered by a command; whether the account behind it "
                       "may create issues is only proven by the first real write, which is "
                       "read back and reported either way",
                alternatives=_alternatives(config))


def _alternatives(config: dict) -> list:
    """Routes this project already has, for the person choosing how to close the gap. Named,
    never used: switching a channel is onboarding's decision, not a probe's."""
    out = []
    direct = ((config.get("adapters") or {}).get("ticket") or {}).get("direct_api") or {}
    if direct.get("base_url") and direct.get("secret_ref"):
        out.append(f"a direct API token is already configured for `{direct['base_url']}` "
                   f"(`{direct.get('secret_ref')}`) — onboarding can make it the bugs channel")
    out.append("keep bugs local: `external_writes.bugs: markdown` files every bug into the "
               "repository and records the unsent write as an obligation")
    return out


def record(config: dict, project_root, status: str, words: str = "") -> dict:
    """The assistant's own answer, carried back by the orchestrator.

    It is a FACT about a right, not a decision, and it is stored beside the probe rather than
    on top of it: a channel that changes invalidates the answer with the fingerprint."""
    status = str(status or "").strip().lower()
    if status not in (CONFIRMED, NO):
        raise ValueError("record: status must be `confirmed` or `no`")
    result = probe(config, project_root, force=True)
    answered = {"status": status, "at": _now(), "fingerprint": fingerprint(config),
                "reason": " ".join(str(words or "").split())[:300]
                          or ("the assistant answered that it may create issues" if status == CONFIRMED
                              else "the assistant answered that it may not create issues")}
    result["answered"] = answered
    result["status"] = status
    result["reason"] = answered["reason"]
    result["checked_at"] = answered["at"]
    save_receipt(project_root, result)
    _remember_answer(project_root, result.get("channel") or channel_of(config), answered)
    return result


def readiness_line(result: dict) -> str:
    """The doctor's one row: confirmed (with the date) · no (with the reason) · not checked."""
    status = str(result.get("status") or UNVERIFIED)
    channel = result.get("channel") or "?"
    if result.get("applicable") is False:
        return f"tracker write: not applicable — bugs stay in the repository (`{channel}`)"
    if status == CONFIRMED:
        return f"tracker write: confirmed {result.get('checked_at', '')} — `{channel}`"
    if status == NO:
        return f"tracker write: no — {result.get('reason') or 'no reason recorded'}"
    return f"tracker write: not checked — {result.get('reason') or 'nobody has looked'}"


def selftest() -> int:
    import tempfile
    failures = []

    def case(name, got, expected):
        if got != expected:
            failures.append(f"{name}: expected {expected!r}, got {got!r}")

    agent_cfg = {"external_writes": {"bugs": "jira", "channels": {
        "jira": {"method": "agent", "invoke": "jira-rw-assistant-cli"}}},
        "adapters": {"ticket": {"project_keys": ["TP2"]}}}
    with tempfile.TemporaryDirectory(prefix="qa-tracker-write-") as td:
        root = Path(td)
        (root / "qa-factory").mkdir(parents=True)
        result = probe(agent_cfg, root)
        case("an assistant nobody asked about is `unverified`, not a failure",
             result["status"], UNVERIFIED)
        case("and the exact question is handed over",
             "writes: yes" in (result.get("ask") or ""), True)
        case("the question creates nothing",
             "Do not create" in (result.get("ask") or ""), True)
        case("the receipt is on disk", receipt_path(root).is_file(), True)
        recorded = record(agent_cfg, root, NO, "the assistant has no create permission")
        case("the assistant's own answer is recorded", recorded["status"], NO)
        case("and it survives the next probe", probe(agent_cfg, root)["status"], NO)
        agent_cfg["external_writes"]["channels"]["jira"]["invoke"] = "another-assistant"
        case("a changed channel invalidates the old answer",
             probe(agent_cfg, root, force=True)["status"], UNVERIFIED)
        local = probe({"external_writes": {"bugs": "markdown"}}, root, force=True)
        case("a markdown project is not nagged about a tracker", local.get("applicable"), False)
        none_cfg = {"external_writes": {"bugs": "jira"}}
        case("a channel with no delivery at all is a plain `no`",
             probe(none_cfg, root, force=True)["status"], NO)
        case("and the person is told what routes exist",
             any("markdown" in a for a in probe(none_cfg, root, force=True)["alternatives"]), True)
    case("the fingerprint never carries a secret's value",
         "QA_JIRA_API_TOKEN" in json.dumps(agent_cfg), False)
    if failures:
        print("TRACKER_WRITE SELFTEST: VIOLATIONS")
        for f in failures:
            print("  - " + f)
        return 1
    print("TRACKER_WRITE SELFTEST: no violations (unverified/no/confirmed, prompt, cache, names)")
    return 0


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--project-root", dest="project_root", default="")
    ap.add_argument("--force", action="store_true", help="probe again, whatever the cache says")
    ap.add_argument("--where", default="story",
                    choices=("story", "gate_b", "doctor", "onboarding"),
                    help="which freshness rule applies to the cached answer")
    ap.add_argument("--record", default="", choices=("", CONFIRMED, NO),
                    help="the assistant's answer, carried back by the orchestrator")
    ap.add_argument("--words", default="", help="--record: what the assistant actually said")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.project_root:
        root = Path(args.project_root)
        config = _read_json(root / "qa-factory" / "config.json", {}) or {}
    else:
        from hooklib import load_config, project_root, require_project
        require_project("tracker_write")
        root, config = project_root(), load_config()
    result = (record(config, root, args.record, args.words) if args.record
              else probe(config, root, force=args.force, where=args.where))
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(readiness_line(result))
        for item in result.get("alternatives") or []:
            print("  - " + item)
        if result.get("ask"):
            print("  ask the assistant, exactly once:\n    " + result["ask"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
