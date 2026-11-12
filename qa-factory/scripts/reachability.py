#!/usr/bin/env python3
"""Can this machine REACH the hosts the project names, before anything about credentials.

The pilot bug this exists for. A doctor run on 2026-09-20 reported
`vcs_api: missing / owner: user` with the note "check existing glab host credentials ...
SSH credentials do not authenticate the API" and made it the project's single next action.
Nothing was wrong with the credentials: the corporate VPN had dropped. The probe failed in
under a second, `glab` returned its catch-all error, and the factory translated "I could not
reach the host" into "your access is wrong" — sending a person to look at keys and SSH that
the problem never touched. The same drop would have failed the Jira probe in exactly the same
way, so ONE cause was about to be reported as several unrelated red lines with the wrong
owner on each.

So: this EXPLAINS a failure, it does not pre-empt the attempt. Callers ask the real question
first — the receipt on disk, the API call — and consult this only when the answer was not a
clear refusal. Asking the socket first would cost every healthy run a probe it does not need
and would let a network hiccup overrule a server that answered perfectly clearly. Once
consulted, its answer outranks everything else: an unreachable host yields `unknown` with "no
network route to <host>", never `missing`, and never a sentence about credentials.

What is proven here is deliberately small: the name resolves and a TCP connection opens.
That is enough to separate "the network is not there" from "the network is there and the
server said no", which is the only distinction the callers need. It proves nothing about
authentication, and it says so.

CLI:
  reachability.py --json                  probe every host the config names, print the receipt
  reachability.py --host HOST [--host H2] probe exactly these
  reachability.py --write                 also write state/integrations/reachability.json
"""
import argparse
import json
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hooklib import load_config, project_root, state_dir  # noqa: E402

RECEIPT = "state/integrations/reachability.json"
TIMEOUT = 4.0
# Reachable with or without a corporate network, so an unreachable one says nothing about a
# VPN. Kept separate rather than skipped: a local stand that does not answer is a real fact.
LOCAL = re.compile(r"^(localhost|127\.|0\.0\.0\.0$|\[?::1\]?$|.*\.local$|.*\.localhost$)", re.I)


def host_of(value: str) -> tuple[str, int]:
    """The hostname and port inside a URL or a git remote, SSH forms included.

    The port matters: a stand declared as `http://localhost:8080` is not answering on 443,
    and probing the wrong port would report a healthy stand as unreachable."""
    raw = str(value or "").strip()
    if not raw:
        return "", 0
    if "://" in raw:
        parsed = urlparse(raw)
        port = parsed.port or (80 if parsed.scheme == "http" else 443)
        return (parsed.hostname or "").strip(), port
    if "@" in raw and ":" in raw.split("@", 1)[1]:  # git@host:group/project.git
        return raw.split("@", 1)[1].split(":", 1)[0].strip(), 443
    return raw.split("/", 1)[0].split(":", 1)[0].strip(), 443


def declared_hosts(cfg: dict, root: Path) -> list[dict]:
    """Every host this project's configuration points at, with where it was declared.

    The `source` is carried through to the report so a person reads "git.example (the
    test repository's remote)" instead of a bare name they then have to place themselves."""
    found: dict[tuple[str, int], str] = {}

    def add(value: str, source: str) -> None:
        host, port = host_of(value)
        if host and not host.startswith("-") and (host, port) not in found:
            found[(host, port)] = source

    try:
        remote = subprocess.run(["git", "remote", "get-url", "origin"], cwd=root,
                                capture_output=True, text=True, timeout=10).stdout.strip()
        add(remote, "git remote origin")
    except (OSError, subprocess.SubprocessError):
        pass
    ticket = ((cfg.get("adapters") or {}).get("ticket") or {})
    add(((ticket.get("direct_api") or {}).get("base_url") or ""), "the ticket tracker API")
    for entry in cfg.get("environments") or []:
        if isinstance(entry, dict):
            add(entry.get("base_url") or "", f"the `{entry.get('name') or 'unnamed'}` environment")
    return [{"host": host, "port": port, "source": source}
            for (host, port), source in found.items()]


def probe(host: str, port: int = 443) -> dict:
    """Name resolution, then one TCP connection. No request is sent, nothing is authenticated."""
    result = {"host": host, "port": port, "local": bool(LOCAL.match(host)), "checked_at": _now()}
    try:
        addresses = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        return dict(result, status="unreachable", stage="dns", detail=exc.strerror or "name not resolved")
    except OSError as exc:
        return dict(result, status="unknown", stage="dns", detail=str(exc))
    family, socktype, proto, _, address = addresses[0]
    try:
        with socket.socket(family, socktype, proto) as sock:
            sock.settimeout(TIMEOUT)
            sock.connect(address)
    except (socket.timeout, TimeoutError):
        return dict(result, status="unreachable", stage="tcp", detail=f"no answer within {TIMEOUT:g}s")
    except OSError as exc:
        return dict(result, status="unreachable", stage="tcp", detail=exc.strerror or str(exc))
    return dict(result, status="reachable", stage="tcp",
                detail=f"name resolves and port {port} accepts a connection (nothing authenticated)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def collect(cfg: dict, root: Path, hosts: list[str] | None = None) -> dict:
    targets = ([{"host": host_of(h)[0] or h, "port": host_of(h)[1] or 443, "source": "requested"}
                for h in hosts] if hosts else declared_hosts(cfg, root))
    rows = [dict(probe(entry["host"], entry["port"]), source=entry["source"]) for entry in targets]
    remote = [row for row in rows if not row["local"]]
    unreachable = [row for row in remote if row["status"] == "unreachable"]
    receipt = {"schema_version": 1, "checked_at": _now(), "hosts": rows,
               "unreachable": [row["host"] for row in unreachable],
               "network": ("unknown" if not remote else
                           "no_route" if len(unreachable) == len(remote) else
                           "partial" if unreachable else "ok")}
    receipt["summary"] = summary(receipt)
    return receipt


def summary(receipt: dict) -> str:
    """The one line a person reads instead of several red capability rows.

    It stops at what was observed. "The VPN is off" is a guess — a very likely one, and it
    belongs in the remedy as the first thing to try, not in the finding as a fact."""
    names = receipt.get("unreachable") or []
    if not names:
        return "every declared host is reachable"
    listed = " and ".join("`" + n + "`" for n in names)
    if receipt.get("network") == "no_route":
        return (f"no network route to {listed} — a corporate VPN that is off is the usual cause. "
                "Access to these hosts is NOT verified and NOT denied: nothing was asked of them.")
    return (f"no network route to {listed}; other declared hosts answer. "
            "Access to these hosts is not verified and not denied.")


def status_for(receipt: dict, host: str) -> str:
    """`reachable` / `unreachable` / `unknown` for one host, for a caller that must decide
    whether it is even allowed to talk about credentials."""
    for row in receipt.get("hosts") or []:
        if row.get("host") == host:
            return str(row.get("status") or "unknown")
    return "unknown"


def load_receipt(root: Path) -> dict:
    path = root / "qa-factory" / RECEIPT
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", action="append", default=[])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    root = project_root()
    receipt = collect(load_config(), root, args.host or None)
    if args.write:
        target = state_dir() / RECEIPT
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    else:
        print("REACHABILITY: " + receipt["summary"])
        for row in receipt["hosts"]:
            local = " (local)" if row["local"] else ""
            print(f"  {row['host']}{local}  {row['status']}  {row['source']} — {row['detail']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
