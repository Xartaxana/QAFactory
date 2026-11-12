#!/usr/bin/env python3
"""The stand of a device surface, told by code (EP1-41b): is a device connected, does the driver server answer, does a session open.

The table is `references/surfaces.json`, read through its one reader `surfaces.py` (AR-1, AR-13): the tool a row runs, the
patterns that read its output, the driver's paths and limits are DATA; no platform, tool or driver name is in this file. A project's
own facts (the driver's address, the app id, the NAME of the key that holds a serial) come from its `config.json` environment row.

Three outcomes, and the reason on every branch (FR-41, FR-59): a tool that is missing, a tool that failed and a tool that printed
nothing it should have printed are each told apart from "no device". The error direction (D-0021): every doubtful input reads as
"not ready" and never as "ready"; empty or unrecognised output is `unreadable` (the factory's to say), never "no device"; a device
is never chosen "first in the list". Nothing here asks a person (P5, D-0043): what the probe found out is a gap with a line and a door.

`probe` reads only (a device list, the server's `/status`). `deep=True` also creates and deletes one minimal session, which
occupies the device for a moment: it is for the onboarding and a capture, never for a doctor (read-only).

Fakes (tests): `RUN_TOOL(argv, timeout) -> (exit_code, bytes)` may raise `subprocess.TimeoutExpired` or `OSError`; `WHICH(name)`;
`HTTP` takes the place of `http_client.fetch`; `NOW()`; `PLATFORM` takes the place of `sys.platform`.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import hooklib  # noqa: E402
import http_client as HC  # noqa: E402
import stand_identity as SI  # noqa: E402
import surfaces  # noqa: E402

RUN_TOOL = None
WHICH = None
HTTP = None
NOW = None
PLATFORM = None

FACTORY_STATES = ("unreadable", "foreign")       # the factory's to say; every other problem is the user's to fix
NOT_PROBLEMS = ("ok", "skipped")
MESSAGE_CHARS = 200                              # a server's first line, as far as it is shown (t-511 41b)
LIST_SHOWN = 5                                   # serials named in one sentence
_URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>]+")
_APP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


# ---- small helpers ------------------------------------------------------------------------------------------------

def _clip(text, limit: int) -> str:
    """One line, control characters and runs of blanks collapsed, at most `limit` characters."""
    flat = " ".join(re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(text or "")).split())
    return flat if len(flat) <= limit else flat[:max(limit - 3, 0)].rstrip() + "..."


def _safe_text(text, limit: int) -> str:
    """A server's words for a person: any address in them loses its credential and query (a secret travels there)."""
    return _clip(_URL_IN_TEXT.sub(lambda m: HC.safe_url(m.group(0)), str(text or "")), limit)


def _names(items, limit: int = LIST_SHOWN) -> str:
    items = [str(i) for i in items]
    return ", ".join(items[:limit]) + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _table() -> dict:
    return surfaces.rows()


def driver_data(row: dict) -> dict:
    """The driver block a row names. ValueError (the factory's table is broken) when the row names none or the block is not usable."""
    name = row.get("driver")
    block = (_table().get("drivers") or {}).get(name) if isinstance(name, str) else None
    if not isinstance(block, dict):
        raise ValueError(f"references/surfaces.json: the row names driver {name!r} that the table does not describe. Expected a "
                         "`drivers` block of that name; this is a factory defect: record it as a finding")
    return block


def _positive(value, what: str):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"references/surfaces.json: {what} must be a positive number; got {value!r}. This is a factory defect: "
                         "record it as a finding")
    return value


def tool_timeout() -> float:
    return _positive(_table().get("tool_timeout_s"), "tool_timeout_s")


def _platform() -> str:
    return PLATFORM or sys.platform


# ---- the process --------------------------------------------------------------------------------------------------

def _run_process(argv, timeout):
    done = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=timeout,
                          shell=False, check=False)
    return done.returncode, done.stdout


def run_tool(argv, timeout, limit=None) -> dict:
    """{state: ok|tool_missing|tool_error|timeout, out, cut, line}. The tool is looked up first (`shutil.which`): a tool that is not on the
    PATH is `tool_missing`, which says nothing about a device. Standard error is read together with standard output (a daemon's start
    line comes with the list). `out` is decoded with `errors="replace"` and CRLF is left to the reader; it is at most `limit` bytes
    (default: build-identity-methods.json limits.output_bytes) and `cut` says it was longer. ValueError when that limit cannot be read."""
    cap = int(limit) if limit else int(_output_cap())
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        return {"state": "tool_error", "out": "", "cut": False, "line": "the command to run is not a list of words"}
    found = (WHICH or shutil.which)(argv[0])
    if not found:
        return {"state": "tool_missing", "out": "", "cut": False, "line": f"`{argv[0]}` is not on the PATH of this machine"}
    try:
        code, raw = (RUN_TOOL or _run_process)([found, *argv[1:]], timeout)
    except subprocess.TimeoutExpired:
        return {"state": "timeout", "out": "", "cut": False, "line": f"`{argv[0]}` did not finish in {timeout:g} seconds"}
    except OSError as exc:
        return {"state": "tool_error", "out": "", "cut": False, "line": f"`{argv[0]}` could not be run ({exc.__class__.__name__})"}
    raw = bytes(raw or b"")
    cut = len(raw) > cap
    out = raw[:cap].decode("utf-8", errors="replace")
    if code != 0:
        return {"state": "tool_error", "out": out, "cut": cut,
                "line": f"`{argv[0]}` exited with code {code}: {_safe_text(out, 120) or 'it printed nothing'}"}
    return {"state": "ok", "out": out, "cut": cut, "line": ""}


def _output_cap() -> int:
    try:
        return int(SI.limit("output_bytes"))
    except (SI.RegistryError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"the factory's output limit cannot be read ({exc.__class__.__name__}). This is a factory defect: record it "
                         "as a finding") from exc


# ---- the device list ----------------------------------------------------------------------------------------------

def _pattern(spec: dict, key: str, required: bool = True):
    text = spec.get(key)
    if text is None and not required:
        return None
    try:
        return re.compile(text)
    except (re.error, TypeError) as exc:
        raise ValueError(f"references/surfaces.json: devices.{key} of the row is not a pattern ({exc.__class__.__name__}). This is "
                         "a factory defect: record it as a finding") from exc


def _read_rows(out: str, spec: dict):
    """(serials, others, unknown) of a device list, or (None, why) when the text is not a list at all. A line before the header
    (a daemon's start line) is noise; a header must be found; a row of a form the table does not know is kept, never dropped."""
    header, row, other = _pattern(spec, "header_re"), _pattern(spec, "row_re"), _pattern(spec, "other_row_re", required=False)
    lines = out.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((i for i, line in enumerate(lines) if header.search(line.rstrip())), None)
    if start is None:
        return None, "none of its lines is the header the table expects"
    serials, others, unknown = [], [], []
    for line in (raw.rstrip() for raw in lines[start + 1:]):
        if not line.strip():
            continue
        found = row.search(line)
        if found:
            if found.group(1) not in serials:
                serials.append(found.group(1))
            continue
        state = other.search(line) if other else None
        if state:
            others.append({"serial": state.group(1), "state": state.group(2)})
        else:
            unknown.append(_clip(line, 60))
    return (serials, others, unknown), ""


def list_devices(row: dict) -> dict:
    """{state: devices|no_device|tool_missing|tool_error|host_os|unreadable, serials, others, unknown, line}.
    `host_os` empty means any host; otherwise the host must be listed, and the tool is not run on another (no_device is never
    said about a host that cannot ask). Only a header followed by no row is `no_device`; an empty output, an output without the header,
    an output cut at the limit and an output with only rows of an unknown form are `unreadable` (the factory's). ValueError when the
    table's own patterns are broken."""
    spec = row.get("devices") if isinstance(row.get("devices"), dict) else None
    argv = spec.get("argv") if spec else None
    tool = str(row.get("tool") or (argv[0] if isinstance(argv, list) and argv else "the device tool"))
    base = {"serials": [], "others": [], "unknown": []}
    host_os = row.get("host_os", [])
    if not isinstance(host_os, list):
        return {**base, "state": "unreadable", "line": "the table's `host_os` of this row is not a list, so it is not known where the "
                                                       "device tool can run"}
    if host_os and _platform() not in host_os:
        return {**base, "state": "host_os", "line": f"this device surface can be read only on a host of kind {_names(host_os)}; this "
                                                    f"machine reports {_platform()}"}
    if spec is None or not isinstance(argv, list):
        return {**base, "state": "unreadable", "line": "the table row has no way to list devices"}
    ran = run_tool(argv, tool_timeout())
    if ran["state"] == "tool_missing":
        return {**base, "state": "tool_missing", "line": f"{tool}: {ran['line']}"}
    if ran["state"] in ("tool_error", "timeout"):
        return {**base, "state": "tool_error", "line": ran["line"]}
    if ran["cut"]:
        return {**base, "state": "unreadable", "line": f"the answer of `{tool}` is longer than {len(ran['out'].encode('utf-8'))} bytes "
                                                       "and was cut, so the devices in it cannot be counted"}
    if not ran["out"].strip():
        return {**base, "state": "unreadable", "line": f"`{tool}` printed nothing, which is not an answer about devices"}
    parsed, why = _read_rows(ran["out"], spec)
    if parsed is None:
        return {**base, "state": "unreadable", "line": f"the answer of `{tool}` is not a device list: {why}"}
    serials, others, unknown = parsed
    shown = {"serials": serials, "others": others, "unknown": unknown[:3]}
    if serials:
        return {**shown, "state": "devices", "line": f"{len(serials)} device(s) ready: {_names(serials)}"}
    if unknown:
        return {**shown, "state": "unreadable",
                "line": f"the device list has rows of a form the table does not know, e.g. `{unknown[0]}`"}
    if others:
        named = _names(f"{o['serial']} is {o['state']}" for o in others)
        return {**shown, "state": "no_device", "line": f"no device is ready ({named})"}
    return {**shown, "state": "no_device", "line": "no device is connected"}


def pick_device(row: dict, stand: dict, values, listing=None) -> dict:
    """{state: picked|ambiguous|not_connected|<a state of list_devices>, serial, line, listing}. The serial is never in the config: the
    config holds the NAME of the key (`device.serial_key`) and `values` (the environment) holds the serial. A serial that is named
    must be among the ready devices (a device that is not, or is offline, is `not_connected`: another device is never used instead);
    no serial named and one ready device -> it; no serial and several -> `ambiguous`, never the first in the list."""
    listing = listing if listing is not None else list_devices(row)
    if listing["state"] != "devices":
        return {"state": listing["state"], "serial": "", "line": listing["line"], "listing": listing}
    device = stand.get("device") if isinstance(stand, dict) and isinstance(stand.get("device"), dict) else {}
    key = device.get("serial_key") if isinstance(device.get("serial_key"), str) else ""
    wanted = str(values.get(key) or "").strip() if key and hasattr(values, "get") else ""
    serials = listing["serials"]
    if wanted:
        if wanted in serials:
            return {"state": "picked", "serial": wanted, "line": f"the device named by {key}: {wanted}", "listing": listing}
        state = next((o["state"] for o in listing["others"] if o["serial"] == wanted), "")
        return {"state": "not_connected", "serial": wanted, "listing": listing,
                "line": f"the device {wanted} named by {key} is " + (f"{state}" if state else "not connected")
                        + f" (ready: {_names(serials)})"}
    if len(serials) == 1:
        return {"state": "picked", "serial": serials[0], "line": f"the only ready device: {serials[0]}", "listing": listing}
    named = f"the key {key}" if key else "a key (`device.serial_key` of the environment row)"
    return {"state": "ambiguous", "serial": "", "listing": listing,
            "line": f"{len(serials)} devices are ready ({_names(serials)}) and none is named by {named}"}


# ---- the driver server --------------------------------------------------------------------------------------------

def base_url(stand: dict, data: dict):
    """The server's address up to its base path, or None when the row's `driver.url` is not a plain http(s) address with no
    credential, query or fragment in it (a secret must not be in a file that is committed)."""
    driver = stand.get("driver") if isinstance(stand.get("driver"), dict) else {}
    url = driver.get("url")
    if surfaces.driver_url_problem(url):        # the one reading, shared with the contract (F-7)
        return None
    parts = urllib.parse.urlsplit(url.strip())
    path = driver.get("base_path")
    path = path if isinstance(path, str) else str(data.get("default_base_path") or "/")
    segments = [s for s in (parts.path + "/" + path).split("/") if s]
    return f"{parts.scheme}://{parts.netloc}" + ("/" + "/".join(segments) if segments else "")


def fetch(url, **kwargs):
    return (HTTP or HC.fetch)(url, **kwargs)


def _body_json(answer):
    """(parsed, ok): the answer's body as JSON. Anything that is not JSON is (None, False)."""
    try:
        return json.loads(bytes(answer.body or b"").decode("utf-8", errors="replace")), True
    except ValueError:
        return None, False


def _foreign_line(answer) -> str:
    verdict = answer.verdict or {}
    if 200 <= int(answer.status or 0) < 300 and verdict.get("kind") == "ok":
        return f"HTTP {answer.status}, a body that is not what the server's status looks like"
    return (HC.unattributed(answer.status, answer.body, answer.headers) or HC.describe(answer.status, verdict))


def driver_status(stand: dict, row: dict) -> dict:
    """{state: ready|not_ready|down|foreign, line}. `ready` only when the table's ready field is exactly `true`: a string, a number, a
    missing value is not ready (`not_ready`) or not the server's shape (`foreign`). A cut or unreadable body, a page, a redirect and any
    status other than 2xx is `foreign` (the factory cannot tell whose answer it is); no answer at all is `down`."""
    data = driver_data(row)
    name = str(row.get("driver")).capitalize()
    base = base_url(stand, data)
    if base is None:
        return {"state": "down", "line": f"{name} server: the environment row has no usable `driver.url` (expected a plain http or "
                                         "https address with no user, password or query, e.g. http://127.0.0.1:4723)"}
    try:
        answer = fetch(base + str(data["status_path"]), timeout=tool_timeout(), max_body=int(data["max_body"]), expect="json")
    except (OSError, http.client.HTTPException) as exc:
        return {"state": "down", "line": f"{name} server is not answering at {HC.safe_url(base)} ({exc.__class__.__name__})"}
    if answer.truncated or answer.unreadable:
        return {"state": "foreign", "line": f"the answer at {HC.safe_url(base)} was cut or could not be read, so it cannot be "
                                            f"taken for {name}'s"}
    if not 200 <= int(answer.status or 0) < 300:
        return {"state": "foreign", "line": f"at {HC.safe_url(base)}: {_foreign_line(answer)} (expected {name}'s status)"}
    parsed, readable = _body_json(answer)
    if not readable:
        return {"state": "foreign", "line": f"at {HC.safe_url(base)}: {_foreign_line(answer)} (expected {name}'s status as JSON)"}
    cursor = parsed
    for step in str(data["ready_field"]).split("."):
        if not isinstance(cursor, dict) or step not in cursor:
            return {"state": "foreign", "line": f"the JSON at {HC.safe_url(base)} has no `{data['ready_field']}`, so it is not "
                                                f"{name}'s status"}
        cursor = cursor[step]
    if cursor is True:
        return {"state": "ready", "line": f"{name} server is ready at {HC.safe_url(base)}"}
    return {"state": "not_ready", "line": f"{name} server at {HC.safe_url(base)} answers but is not ready "
                                          f"(`{data['ready_field']}` is {_clip(json.dumps(cursor, ensure_ascii=False), 40)})"}


def _first_message(answer) -> str:
    """The first line of what the server said about a failure, hidden from secrets and short."""
    parsed, readable = _body_json(answer)
    text = ""
    value = parsed.get("value") if readable and isinstance(parsed, dict) else None
    if isinstance(value, dict):
        text = next((str(value[k]) for k in ("message", "error") if isinstance(value.get(k), str) and value[k].strip()), "")
    if not text:
        text = bytes(answer.body or b"").decode("utf-8", errors="replace")
    first = next((line for line in text.splitlines() if line.strip()), "")
    return _safe_text(first, MESSAGE_CHARS)


SESSION_NAMES = ("app_id_capability", "device_capability", "app_id_param", "activity_capability")     # a row's keys that name a capability or a request key, not a capability


def create_session(stand: dict, row: dict, device: str, deep: bool = False) -> dict:
    """{state: ok|session_failed, session_id, line}: the smallest session the row describes (the platform, the automation name, the
    device; the table's session defaults, or with `deep` the shorter-lived `deep_session_defaults`: a probe keeps the device only as
    long as it must). No app is named, so none is started. A reply without a session id is a failure."""
    data = driver_data(row)
    session = row.get("session") if isinstance(row.get("session"), dict) else {}
    base = base_url(stand, data)
    failed = {"state": "session_failed", "session_id": ""}
    if base is None or not session.get("device_capability"):
        return {**failed, "line": "a session cannot be asked for: the driver address or the row's session description is unusable"}
    caps = dict(data.get("deep_session_defaults" if deep else "session_defaults") or {})
    caps.update({k: v for k, v in session.items() if k not in SESSION_NAMES})
    caps[str(session["device_capability"])] = device
    body = json.dumps({"capabilities": {"alwaysMatch": caps}}).encode("utf-8")
    try:
        answer = fetch(base + str(data["session_path"]), method="POST", data=body, timeout=_positive(data.get("session_timeout_s"),
                        "drivers.*.session_timeout_s"), max_body=int(data["max_body"]), expect="json",
                        headers={"Content-Type": "application/json; charset=utf-8"})
    except (OSError, http.client.HTTPException) as exc:
        return {**failed, "line": f"no answer to the session request at {HC.safe_url(base)} ({exc.__class__.__name__})"}
    parsed, readable = _body_json(answer)
    value = parsed.get("value") if readable and isinstance(parsed, dict) else None
    sid = value.get("sessionId") if isinstance(value, dict) else None
    if 200 <= int(answer.status or 0) < 300 and not answer.truncated and isinstance(sid, str) and sid.strip():
        return {"state": "ok", "session_id": sid, "line": "a session was created"}
    said = _first_message(answer) or _foreign_line(answer)
    return {**failed, "line": f"the server is up but the session did not start (HTTP {answer.status}): {said}"}


def delete_session(stand: dict, row: dict, session_id: str) -> dict:
    """{state: deleted|failed, line}. The id goes into the address as one path segment (quoted)."""
    data = driver_data(row)
    base = base_url(stand, data)
    if base is None:
        return {"state": "failed", "line": "the driver address is unusable"}
    url = base + str(data["session_path"]) + "/" + urllib.parse.quote(str(session_id), safe="")
    try:
        answer = fetch(url, method="DELETE", timeout=_positive(data.get("session_timeout_s"), "drivers.*.session_timeout_s"),
                        max_body=int(data["max_body"]), expect="json")
    except (OSError, http.client.HTTPException) as exc:
        return {"state": "failed", "line": f"no answer to the session delete ({exc.__class__.__name__})"}
    if 200 <= int(answer.status or 0) < 300:
        return {"state": "deleted", "line": "the session was deleted"}
    return {"state": "failed", "line": f"the session delete was answered with HTTP {answer.status}"}


def deep_session(stand: dict, row: dict, device: str) -> dict:
    """{state: ok|session_failed, line, session_id}: create a minimal session and delete it again. The delete runs in `finally` and
    only after a session exists (nothing is deleted when the creation failed). A delete that fails leaves the session confirmed (`ok`)
    and the line names the one left behind and when the server ends it by itself."""
    made = create_session(stand, row, device, deep=True)
    if made["state"] != "ok":
        return {"state": "session_failed", "line": made["line"], "session_id": ""}
    sid = made["session_id"]
    result = {"state": "ok", "session_id": sid, "line": "a session was created and deleted"}
    idle = None
    try:
        idle = next((v for k, v in (driver_data(row).get("deep_session_defaults") or {}).items() if "timeout" in k.lower()), None)
    finally:
        gone = delete_session(stand, row, sid)
    if gone["state"] != "deleted":
        result["line"] = (f"a session was created; it could not be deleted ({gone['line']}), so session {_clip(sid, 60)} is left on "
                          "the device" + (f" and ends by itself after {idle} seconds without a command" if idle else ""))
    return result


# ---- the installed build ------------------------------------------------------------------------------------------

HASH_LIMITATION = "the installed file was not hashed, so a rebuild with the same version is not seen"
_PATH_ON_DEVICE = re.compile(r"/[A-Za-z0-9/._~=+@-]*")     # a path that is safe to hand to a shell on the device
_SHA_SHOWN = 12                                             # hex characters of each file's hash in the line a person reads


def _file_hashes(spec: dict, device: str, app_id: str) -> list:
    """The sha256 (64 hex, lower case) of each file the device holds for the app, in the order the device printed them, or [] when
    any of them cannot be read (the row has no `artifact`, a tool fails or times out, an answer is not the form the row names, a path
    is not a plain path): all or none, so a hash that stands for only part of an install is never reported. ValueError when the row's
    patterns are broken. ERROR DIRECTION (D-0021): a doubtful read is "not hashed", never a hash."""
    art = spec.get("artifact") if isinstance(spec.get("artifact"), dict) else None
    if art is None:
        return []
    try:
        path_re, sha_re = re.compile(art["path_re"], re.M), re.compile(art["sha_re"], re.M)
        path_argv, sha_argv = art["path_argv"], art["sha_argv"]
        if not isinstance(path_argv, list) or not isinstance(sha_argv, list):
            raise TypeError("an argv is not a list")
    except (KeyError, re.error, TypeError) as exc:
        raise ValueError(f"references/surfaces.json: installed_build.artifact of the row is broken ({exc.__class__.__name__}). "
                         "This is a factory defect: record it as a finding") from exc
    timeout = tool_timeout()
    listed = run_tool([p.replace("{device}", device).replace("{app_id}", app_id) for p in path_argv], timeout)
    if listed["state"] != "ok" or listed["cut"]:
        return []
    paths = [m.group(1) for m in path_re.finditer(listed["out"].replace("\r\n", "\n").replace("\r", "\n")) if m.groups()]
    if not paths or not all(_PATH_ON_DEVICE.fullmatch(p) for p in paths):
        return []
    shas = []
    for path in paths:
        ran = run_tool([p.replace("{device}", device).replace("{path}", path) for p in sha_argv], timeout)
        found = sha_re.search(ran["out"].replace("\r\n", "\n").replace("\r", "\n").strip()) if ran["state"] == "ok" else None
        if not found or not found.groups():
            return []
        shas.append(found.group(1))
    return shas


def installed_build(row: dict, device: str, app_id: str) -> dict:
    """{state: read|not_installed|no_method|tool_error, version, code, line, value, hashed, limitation}. `no_method`: the row has no way
    to read it, or the app id is not a plain identifier (it reaches a shell on the device). `not_installed` only when the tool
    answered and its output names neither pattern; an empty output, a failure and a cut output with no match are `tool_error`, never
    "not installed".
    EP1-41e: a build that is `read` also carries the hash of the file(s) the device holds (`_file_hashes`), so a rebuild with the
    SAME version is seen. `line` is what a person reads (`<app id> <version> (<code>) sha256:<12 hex>`, one 12-hex group per file,
    comma between); `value` is the same with the whole hashes, what a digest is taken of. When the hash cannot be read, `hashed` is
    false, `line` and `value` are the version line alone and `limitation` says what is not seen: the version was read, so this is
    not an error."""
    spec = row.get("installed_build") if isinstance(row.get("installed_build"), dict) else None
    out = {"state": "no_method", "version": "", "code": "", "value": "", "hashed": False, "limitation": ""}
    if spec is None:
        return {**out, "line": "this surface has no way to read the installed build"}
    if not isinstance(app_id, str) or not _APP_ID.fullmatch(app_id) or not isinstance(device, str) or not device.strip():
        return {**out, "line": "the app id is empty or is not a plain identifier, or no device is named, so the build was not asked for"}
    argv = [part.replace("{device}", device).replace("{app_id}", app_id) for part in spec.get("argv") or []]
    data = driver_data(row)
    ran = run_tool(argv, tool_timeout(), limit=int(data["max_body"]))
    fail = {**out, "state": "tool_error"}
    if ran["state"] != "ok":
        return {**fail, "line": ran["line"]}
    if not ran["out"].strip():
        return {**fail, "line": f"`{argv[0]}` printed nothing, so the installed build is not known"}
    try:
        found_v = re.compile(spec["version_re"]).search(ran["out"])
        found_c = re.compile(spec["code_re"]).search(ran["out"])
    except (KeyError, re.error, TypeError) as exc:
        raise ValueError(f"references/surfaces.json: installed_build patterns of the row are broken ({exc.__class__.__name__}). "
                         "This is a factory defect: record it as a finding") from exc
    version, code = (found_v.group(1) if found_v else ""), (found_c.group(1) if found_c else "")
    if version or code:
        base = f"{app_id} {_clip(version, 120) or 'unknown version'}" + (f" ({_clip(code, 60)})" if code else "")
        shas = _file_hashes(spec, device, app_id)
        if not shas:
            return {**out, "state": "read", "version": _clip(version, 120), "code": _clip(code, 60), "line": base, "value": base,
                    "limitation": HASH_LIMITATION}
        return {**out, "state": "read", "version": _clip(version, 120), "code": _clip(code, 60), "hashed": True,
                "line": f"{base} sha256:" + ",".join(s[:_SHA_SHOWN] for s in shas), "value": f"{base} sha256:" + ",".join(shas)}
    if ran["cut"]:
        return {**fail, "line": f"the output for {app_id} was cut before it named a version"}
    return {**out, "state": "not_installed", "line": f"{app_id} is not installed on the device (its output names no version)"}


# ---- the probe ----------------------------------------------------------------------------------------------------

def _check(name: str, state: str, line: str, remedy: str = "") -> dict:
    owner = "" if state in NOT_PROBLEMS else ("factory" if state in FACTORY_STATES else "user")
    return {"name": name, "state": state, "line": line, "owner": owner, "remedy": remedy}


def remedy(state: str, row: dict, stand: dict) -> str:
    tool = str(row.get("tool") or "the device tool")
    key = ((stand.get("device") or {}).get("serial_key") if isinstance(stand.get("device"), dict) else "") or ""
    driver = str(row.get("driver") or "the driver")
    return {
        "tool_missing": f"Install {tool} and make it runnable from the command line of this machine, then check again.",
        "tool_error": f"Run the {tool} command by hand, fix what it reports, then check again.",
        "host_os": "Run the check on a host of the kind the line names, or hand these cases to a person.",
        "no_device": "Start an emulator or connect a device and allow it, then check again.",
        "ambiguous": (f"Set the environment variable {key} to the serial of the device to use, or leave one device connected."
                      if key else "Name the environment variable that holds the serial in `device.serial_key` of the environment "
                                  "row, set it to the device to use, or leave one device connected."),
        "not_connected": "Connect that device and allow it, or set the key to a device that is ready, then check again.",
        "down": f"Start the {driver} server at the address in the environment row (`driver.url`), then check again.",
        "not_ready": f"Wait until the {driver} server reports it is ready, or restart it, then check again.",
        "session_failed": "Read the server's line above: the usual cause is a device or driver that is not set up for the app; fix "
                          "it, then check again.",
        "not_configured": "Fix the environment row in qa-factory/config.json, or run the onboarding again.",
        "unreadable": "This is a factory defect: record it as a finding and go on with what does work.",
        "foreign": "This is a factory defect if the address is right: record it as a finding. If another program is on that "
                   "address, point `driver.url` at the right server.",
    }.get(state, "")


def _guarded(name: str, make):
    """Run one check; a ValueError (the factory's table or limit is unusable) is that check's `unreadable`, never a crash."""
    try:
        return make()
    except ValueError as exc:
        return _check(name, "unreadable", _clip(exc, 300), remedy("unreadable", {}, {}))


def _stand_of(cfg, env_name: str) -> dict:
    envs = cfg.get("environments") if isinstance(cfg, dict) else None
    envs = [e for e in envs if isinstance(e, dict)] if isinstance(envs, list) else []
    if not env_name:
        return surfaces.stand_for(cfg)
    for env in envs:
        if env.get("name") == env_name:
            return env
    raise ValueError(f"no environment is named {env_name!r} in config.json. Expected one of: "
                     f"{', '.join(str(e.get('name')) for e in envs) or '(none is described)'}")


def _result(checks: list, deep: bool, env_name: str) -> dict:
    problems = [c for c in checks if c["state"] not in NOT_PROBLEMS]
    first = problems[0] if problems else None
    verdict = "ok" if first is None else ("blocked" if first["owner"] == "user" else "unknown")
    block = None if first is None else {"probe_line": first["line"], "remedy": first["remedy"], "owner": first["owner"],
                                        "do_not_retry": True, "cause": "device"}
    stamp = NOW() if NOW else datetime.now().replace(microsecond=0).isoformat()
    return {"verdict": verdict, "environment": env_name, "deep": deep, "checked_at": stamp, "checks": checks, "block": block}


def probe(cfg: dict, env_name: str = "", deep: bool = False, values=None) -> dict:
    """{verdict: ok|blocked|unknown, environment, deep, checked_at, checks:[{name, state, line, owner, remedy}], block}. Every check runs
    (the person sees every problem at once); `block` is the first problem in the form `EnvBlocked.row` has, `owner` user or factory,
    `do_not_retry` true, `cause` "device". `ok` means every check ran and held; without `deep` no session was tried, and it
    says so (`deep` false). No question to a person is ever built here."""
    values = os.environ if values is None else values
    try:
        _table()
    except ValueError as exc:       # the factory's own table: its fault, said as such (FR-12: by the call, not by the words)
        return _result([_check("stand", "unreadable", _clip(exc, 300), remedy("unreadable", {}, {}))], deep, env_name)
    try:
        stand = _stand_of(cfg, env_name)
        row = surfaces.row_of(stand)
        if not surfaces.is_device_row(row):
            raise ValueError(f"the environment {stand.get('name')!r} is not a device stand. Expected an environment row whose "
                             "`surface` is a row of references/surfaces.json that is driven through a driver")
    except ValueError as exc:       # the project's config: its owner fixes it
        return _result([_check("stand", "not_configured", _clip(exc, 300), remedy("not_configured", {}, {}))], deep, env_name)
    name = str(stand.get("name") or env_name)

    def device_check():
        picked = pick_device(row, stand, values)
        state = "ok" if picked["state"] == "picked" else picked["state"]
        return _check("device", state, picked["line"], "" if state == "ok" else remedy(state, row, stand)), picked["serial"]

    try:
        device, serial = device_check()
    except ValueError as exc:
        device, serial = _check("device", "unreadable", _clip(exc, 300), remedy("unreadable", {}, {})), ""

    def driver_check():
        said = driver_status(stand, row)
        state = "ok" if said["state"] == "ready" else said["state"]
        return _check("driver", state, said["line"], "" if state == "ok" else remedy(state, row, stand))

    server = _guarded("driver", driver_check)
    checks = [device, server]
    if deep:
        if device["state"] == "ok" and server["state"] == "ok":
            def session_check():
                made = deep_session(stand, row, serial)
                state = "ok" if made["state"] == "ok" else made["state"]
                return _check("session", state, made["line"], "" if state == "ok" else remedy(state, row, stand))
            checks.append(_guarded("session", session_check))
        else:
            checks.append(_check("session", "skipped", "not tried: it needs a ready device and a ready server first"))
    return _result(checks, deep, name)


# ---- the command line ---------------------------------------------------------------------------------------------

def _print_human(result: dict) -> None:
    print(f"device stand {result['environment'] or '(unnamed)'}: {result['verdict']}" + (" (session tried)" if result["deep"] else
                                                                                         " (no session tried)"))
    for check in result["checks"]:
        print(f"  {check['name']}: {check['state']} - {check['line']}")
        if check["remedy"]:
            print(f"    what to do: {check['remedy']}")


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description="Check the stand of a device surface: a ready device, an answering driver server, "
                                             "and with --deep one real session. Exit 0 when every check holds, 1 when one does not, "
                                             "2 when the project's config cannot be read.")
    ap.add_argument("--project-root", default="", help="the project that holds qa-factory/config.json (default: the current project)")
    ap.add_argument("--environment", default="", help="the environment row to check (default: the only device stand)")
    ap.add_argument("--json", action="store_true", help="print the result as one JSON document")
    ap.add_argument("--deep", action="store_true", help="also create and delete one minimal session (occupies the device a moment)")
    args = ap.parse_args(argv)
    root = Path(args.project_root) if args.project_root else hooklib.project_root()
    cfg = hooklib.read_json(root / "qa-factory" / hooklib.CONFIG_PATH_NAME, None, kind=dict)
    if cfg is None:
        print(f"device_stand: no readable qa-factory/config.json under {root}. Expected a project the factory onboarded; pass "
              "--project-root <that project> or run the onboarding.", file=sys.stderr)
        return 2
    result = probe(cfg, args.environment, deep=args.deep)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result)
    return 0 if result["verdict"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
