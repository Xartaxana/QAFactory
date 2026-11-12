"""reachability: "can this machine REACH the host" — separated from credentials, per the
module's own pilot-bug docstring (a dropped VPN was mis-reported as a credentials
problem). Covers host_of() URL/git-remote/bare-host parsing, the LOCAL host regex,
declared_hosts() config discovery, and probe()'s three outcomes (reachable / unreachable
/ unknown) with socket.getaddrinfo and socket.socket mocked out — no real network calls,
so this stays fast and deterministic on a host with or without connectivity.
"""
import socket
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reachability as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, finish  # noqa: E402

# --- host_of(): URL / git-remote / bare host, with the port that matters ---
check_eq("an http URL keeps its explicit port", R.host_of("http://localhost:8080"), ("localhost", 8080))
check_eq("an https URL defaults to 443", R.host_of("https://gitlab.example.com/group/proj"), ("gitlab.example.com", 443))
check_eq("a plain http URL defaults to 80", R.host_of("http://example.com"), ("example.com", 80))
check_eq("a git@host:group/project.git remote resolves to the SSH host on 443",
         R.host_of("git@git.example:group/project.git"), ("git.example", 443))
check_eq("a bare host:port with no scheme", R.host_of("jira.example.com:443/rest"), ("jira.example.com", 443))
check_eq("empty input yields an empty host", R.host_of(""), ("", 0))
check_eq("a value starting with '-' is not adopted as a host (add() rejects it)",
         R.host_of("-bad")[0], "-bad")  # host_of itself doesn't filter; declared_hosts' add() does

# --- the LOCAL classification: a local stand answers with or without a corporate VPN ---
for local_host in ("localhost", "127.0.0.1", "::1", "myapp.local", "0.0.0.0"):
    check(f"{local_host!r} is classified local", bool(R.LOCAL.match(local_host)))
check("a real external host is not classified local", not R.LOCAL.match("gitlab.example.com"))

# --- declared_hosts(): every host the project's config points at, with its source ---
with mock.patch.object(R, "subprocess") as fake_subprocess:
    fake_subprocess.run.return_value = mock.Mock(stdout="git@git.example:team/app.git\n")
    cfg = {
        "adapters": {"ticket": {"direct_api": {"base_url": "https://jira.example.com/rest"}}},
        "environments": [{"name": "stage", "base_url": "https://stage.example.com"}],
    }
    hosts = R.declared_hosts(cfg, Path("."))
    by_host = {h["host"]: h for h in hosts}
    check("the git remote host is discovered and labeled", "git.example" in by_host and
          by_host["git.example"]["source"] == "git remote origin")
    check("the ticket tracker API host is discovered and labeled",
          by_host.get("jira.example.com", {}).get("source") == "the ticket tracker API")
    check("a declared environment's host is discovered and names the environment",
          by_host.get("stage.example.com", {}).get("source") == "the `stage` environment")
    check_eq("declared_hosts() de-duplicates by (host, port)", len(hosts), len(set((h["host"], h["port"]) for h in hosts)))

with mock.patch.object(R, "subprocess") as fake_subprocess2:
    fake_subprocess2.SubprocessError = Exception
    fake_subprocess2.run.side_effect = OSError("git not found")
    quiet = R.declared_hosts({}, Path("."))
    check_eq("no git remote and no config hosts -> an empty, not a crashing, list", quiet, [])

# --- probe(): DNS failure, TCP refusal, and success — all mocked, no real network I/O ---
with mock.patch.object(socket, "getaddrinfo", side_effect=socket.gaierror("nope")):
    result = R.probe("no-such-host.invalid")
    check_eq("a DNS failure is reported as unreachable at the dns stage", (result["status"], result["stage"]), ("unreachable", "dns"))

fake_addr = (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("203.0.113.1", 443))
with mock.patch.object(socket, "getaddrinfo", return_value=[fake_addr]):
    with mock.patch.object(socket, "socket") as fake_sock_cls:
        fake_sock = mock.MagicMock()
        fake_sock.connect.side_effect = OSError("refused")
        fake_sock_cls.return_value.__enter__.return_value = fake_sock
        result = R.probe("example.com", 443)
        check_eq("a refused TCP connect is unreachable at the tcp stage", (result["status"], result["stage"]), ("unreachable", "tcp"))

    with mock.patch.object(socket, "socket") as fake_sock_cls:
        fake_sock = mock.MagicMock()
        fake_sock_cls.return_value.__enter__.return_value = fake_sock
        result = R.probe("example.com", 443)
        check_eq("a successful connect is reachable, and proves nothing about auth",
                 result["status"], "reachable")
        check("the reachable detail says nothing was authenticated",
              "nothing authenticated" in result["detail"])

# --- collect()/summary()/status_for(): the one line a person reads instead of red rows ---
with mock.patch.object(R, "probe", side_effect=lambda host, port=443: {
        "host": host, "port": port, "local": False, "checked_at": "t", "status": "unreachable",
        "stage": "tcp", "detail": "no answer"}):
    receipt = R.collect({}, Path("."), hosts=["blocked.example.com"])
check_eq("collect() marks the network no_route when every remote host is unreachable",
         receipt["network"], "no_route")
check("summary() names the VPN as the likely cause for a total network drop",
      "VPN" in receipt["summary"])
check_eq("status_for() reports the probed status for a known host",
         R.status_for(receipt, "blocked.example.com"), "unreachable")
check_eq("status_for() is 'unknown' for a host never probed", R.status_for(receipt, "nope"), "unknown")

no_unreachable = {"unreachable": [], "network": "ok"}
check_eq("summary() with nothing unreachable says every host answers",
         R.summary(no_unreachable), "every declared host is reachable")

finish("test_reachability")
