"""FB-36: `env_probe.py --env NAME` probes THAT stand's address and never qualifies a different
default stack - and a stand without an address of its own is never confirmed by guesswork.

Before the fix `--env` scoped only the integrations and the data cleanup; liveness and login went to the
global `environment` block, whose absolute `health_url` named the default stand, so a dead named stand read
as alive. The expectations below come from the requirement (the FB-36 text, t-958 section 5 and L/L-2), not
from the code's output (FR-58): an address of its own, no request on a disputed selection, the ONLY stand
inherits the block with the fact said on the verdict line, `unchecked` under `--env` is Layer 1, and no
printed line carries a credential. `_fetch` is patched in the direct cases: the checks are about WHICH
address would be asked. The `main` cases run the script in a subprocess against a temp project; the only
socket there is a local counter that stands in for the default stack.
"""
import copy
import http.server
import json
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, check_not_in, finish, run_script  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import env_probe as E  # noqa: E402

STAND = "qa2406-01a1122d"


def config() -> dict:
    return {"environment": {"health_url": "http://localhost:5000/api/conferences",
                            "health_path": "/api/conferences", "access": {"kind": "none"}},
            "environments": [{"name": STAND, "base_url": "http://localhost:15173",
                              "api_base_url": "http://localhost:15000"}]}


def asked(fetch) -> list:
    return [c.args for c in fetch.call_args_list]


def printed(result: dict) -> str:
    """Every line a reader can see: details, the three verdict lines and the JSON form."""
    shown = {k: result[k] for k in ("liveness", "login", "keys", "layer1", "address_source")}
    return "\n".join(result["details"] + E.verdict_lines(result) + [json.dumps(shown)])


def own_address_cases(root: Path) -> None:
    cfg, before = config(), copy.deepcopy(config())
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(cfg, STAND, root=root)
    check_eq("a named stand is probed at ITS api address plus the health path",
             asked(fetch), [("http://localhost:15000/api/conferences", E.HEALTH_TIMEOUT_S)])
    check_eq("a live named stand has no Layer 1 finding", result["layer1"], [])
    check_eq("...and its address is its own", result["address_source"], "own")
    check_eq("access.none keeps the login skipped on a named stand", result["login"]["status"], "skipped")
    check_eq("the probe leaves the config object untouched", cfg, before)
    check("the base_url detail names the stand, not the env-file key",
          any(f"base_url ({STAND}" in line for line in result["details"]), str(result["details"]))
    check_not_in("the stand is not qualified by the default stack's address", "localhost:5000", printed(result))

    cfg = config()
    cfg["environments"][0]["health_url"] = "http://localhost:15000/health"
    with patch.object(E, "_fetch", return_value=200) as fetch:
        E.probe(cfg, STAND, root=root)
    check_eq("the stand's OWN health_url is honoured over base + health_path",
             asked(fetch), [("http://localhost:15000/health", E.HEALTH_TIMEOUT_S)])

    cfg = config()
    cfg["environments"][0]["health_path"] = "/stand/health"
    with patch.object(E, "_fetch", return_value=200) as fetch:
        E.probe(cfg, STAND, root=root)
    check_eq("the stand's OWN health_path replaces the global path and nothing else of the block",
             asked(fetch), [("http://localhost:15000/stand/health", E.HEALTH_TIMEOUT_S)])

    cfg = config()
    cfg["environments"][0] = {"name": STAND, "health_url": "http://localhost:15000/health"}
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(cfg, STAND, root=root)
    check_eq("a stand with only its own health_url is an address of its own",
             (len(asked(fetch)), result["layer1"], result["address_source"]), (1, [], "own"))
    check_in("...and its login is skipped in words (there is no base address to log in at)",
             "no base address", result["login"]["why"])

    cfg = config()
    cfg["environments"][0].update({"health_url": "", "health_path": "", "health_expect": []})
    with patch.object(E, "_fetch", return_value=200) as fetch:
        E.probe(cfg, STAND, root=root)
    check_eq("empty health keys of the entry do not erase the block's path",
             asked(fetch), [("http://localhost:15000/api/conferences", E.HEALTH_TIMEOUT_S)])

    with patch.object(E, "_fetch", return_value=200) as fetch:
        E.probe(config(), root=root)
    check_eq("no --env keeps the legacy global health_url",
             asked(fetch), [("http://localhost:5000/api/conferences", E.HEALTH_TIMEOUT_S)])
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(config(), "", root=root)
    check_eq("...and says it is the block", result["address_source"], "block")


def disputed_selection_cases(root: Path) -> None:
    for label, name, stands in (("missing", STAND, []), ("absent from a longer list", "other", config()["environments"]),
                                ("ambiguous", STAND, [config()["environments"][0]] * 2),
                                ("an option read as a name", "--task", config()["environments"])):
        cfg = dict(config(), environments=stands)
        with patch.object(E, "_fetch", return_value=200) as fetch:
            result = E.probe(cfg, name, root=root)
        check(f"a {label} selection is a Layer 1 finding", bool(result["layer1"]), str(result))
        check_eq(f"a {label} selection contacts nothing (never the global health_url)", len(asked(fetch)), 0)
        check_eq(f"a {label} selection reports liveness dead", result["liveness"]["verdict"], "dead")
        check_in(f"a {label} selection says what is wrong", "missing or ambiguous", result["liveness"]["note"])
        check_in(f"a {label} selection names a door (FR-1)", "Door:", result["liveness"]["note"])
        lines = E.verdict_lines(result)
        check_in(f"a {label} selection: the keys line names the selection, not the env file",
                 "selected environment could not be probed", lines[2])
        check_not_in(f"a {label} selection: ...and never blames the env file", "env file was not found", "\n".join(lines))
        check_in(f"a {label} selection: the login line gives the same reason", "selected environment", lines[1])

    # The disputed selection is judged BEFORE the env file: a stale env_file path must not hide it.
    cfg = config()
    cfg["environment"]["env_file"] = "no/such/file.env"
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(dict(cfg, environments=[]), STAND, root=root)
    check_in("the selection error wins over a stale env_file", "missing or ambiguous", result["layer1"][0])
    check_eq("...with no request", len(asked(fetch)), 0)

    # A stale env file with a stand of its own stays what it was: dead, naming the file (edge 4).
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(cfg, STAND, root=root)
    check_eq("a missing env file under --env: dead, no request, login not tried",
             (result["liveness"]["verdict"], len(asked(fetch)), result["login"]["status"]), ("dead", 0, "skipped"))
    check_in("...the keys line says it was the env file", "env file was not found", E.verdict_lines(result)[2])


def addressless_cases(root: Path) -> None:
    # Two entries, the named one without an address, NO address in the env file either: nothing to ask (FR-59).
    cfg = config()
    cfg["environments"] = [{"name": STAND}, {"name": "second", "base_url": "http://localhost:16000"}]
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(cfg, STAND, root=root)
    check("two entries, the named one without an address, no env file: Layer 1", bool(result["layer1"]), str(result))
    check_eq("...contacts nothing (never the global health_url)", len(asked(fetch)), 0)
    check_in("...and names the missing address", "no address", result["liveness"]["note"])
    check_in("...with the door", "Door:", result["liveness"]["note"])

    cfg["environments"] = [{"name": STAND}, {"name": "second"}]
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(cfg, STAND, root=root)
    check_eq("two entries, both without an address, no env file: stop, no request",
             (bool(result["layer1"]), len(asked(fetch))), (True, 0))

    # The LIVE shape (config-live-shape.json, d2_seed): names only in environments[], the address in the env file.
    (root / "live.env").write_text("LIVE_BASE=http://localhost:17000\n", encoding="utf-8")
    block = {"env_file": "live.env", "base_url_key": "LIVE_BASE", "health_path": "/health", "access": {"kind": "none"}}
    cfg = {"environment": block, "environments": [{"name": STAND}, {"name": "second"}]}
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(cfg, STAND, root=root)
    check_eq("names only + the address in the env file: the env file's address is asked",
             asked(fetch), [("http://localhost:17000/health", E.HEALTH_TIMEOUT_S)])
    check_eq("...no Layer 1, source `env file`", (result["layer1"], result["address_source"]), ([], "env file"))
    check_eq("...liveness.address_source says it", result["liveness"]["address_source"], "env file")
    line = E.verdict_lines(result)[0]
    check_in("...the VERDICT line says `address_source: env file`", E.FROM_ENV_FILE, line)
    check("...at column 0, one of the three lines", line.startswith("liveness: alive"), line)
    check_in("...the detail line names it too", E.FROM_ENV_FILE, "\n".join(result["details"]))

    # FR-4 / adversarial: the block's ABSOLUTE health_url (the default stack) is not borrowed by an address-less entry.
    cfg = {"environment": dict(block, health_url="http://localhost:5000/api/live"),
           "environments": [{"name": STAND}, {"name": "second"}]}
    with patch.object(E, "_fetch", return_value=200) as fetch:
        E.probe(cfg, STAND, root=root)
    check_eq("an address-less entry under 2+ stands never borrows the block's absolute health_url",
             asked(fetch), [("http://localhost:17000/health", E.HEALTH_TIMEOUT_S)])
    cfg = {"environment": {"health_url": "http://localhost:5000/api/live"},
           "environments": [{"name": STAND}, {"name": "second"}]}
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(cfg, STAND, root=root)
    check_eq("...and with no env-file address either it asks nothing and stops",
             (len(asked(fetch)), bool(result["layer1"])), (0, True))
    # F2 (t-1057): the block's ABSOLUTE health_url is kept at the env-file address, dropped elsewhere, and the
    # verdict line says which - truthfully in every case.
    two_stands = [{"name": STAND}, {"name": "second"}]

    def env_file_run(health_url: str, drop_base_key: bool = False):
        blk = dict(block, health_url=health_url)
        if drop_base_key:
            blk.pop("base_url_key")
        with patch.object(E, "_fetch", return_value=200) as fetch:
            res = E.probe({"environment": blk, "environments": two_stands}, STAND, root=root)
        return res, asked(fetch)

    result, hits = env_file_run("http://localhost:17000/api/health")
    check_eq("F2: the block's health_url at the env-file address (scheme, host, port) is KEPT",
             hits, [("http://localhost:17000/api/health", E.HEALTH_TIMEOUT_S)])
    check_in("F2: ...and the verdict line says it is used", "health_url is at that same address and is used",
             result["liveness"]["note"])
    check_not_in("F2: ...and does not claim the block names none", "names no health_url", result["liveness"]["note"])
    result, hits = env_file_run("http://localhost:5000/api/live")
    check_eq("F2: the same host with ANOTHER port is dropped, the env-file address asked",
             hits, [("http://localhost:17000/health", E.HEALTH_TIMEOUT_S)])
    check_in("F2: ...the verdict line says a health_url on another host or port was set aside",
             "names a health_url on another host or port — the env file address is used", result["liveness"]["note"])
    check_not_in("F2: ...and never says the block names none", "names no health_url", result["liveness"]["note"])
    result, hits = env_file_run("https://localhost:17000/api/health")
    check_eq("F2: another scheme on the same host and port is dropped", hits, [("http://localhost:17000/health", E.HEALTH_TIMEOUT_S)])
    result, hits = env_file_run("http://localhost:17000@elsewhere.example/api/health")
    check_eq("F2: userinfo naming the env-file host in front of another host is dropped",
             hits, [("http://localhost:17000/health", E.HEALTH_TIMEOUT_S)])
    result, hits = env_file_run("http://localhost:notaport/api/health")
    check_eq("F2: an unparseable port is dropped, not a crash", hits, [("http://localhost:17000/health", E.HEALTH_TIMEOUT_S)])
    (root / "live-default-port.env").write_text("LIVE_BASE=http://localhost\n", encoding="utf-8")
    default_block = dict(block, env_file="live-default-port.env", health_url="http://localhost:80/api/health")
    with patch.object(E, "_fetch", return_value=200) as fetch:
        E.probe({"environment": default_block, "environments": two_stands}, STAND, root=root)
    check_eq("F2: the scheme's default port equals the explicit one (http 80)", asked(fetch),
             [("http://localhost:80/api/health", E.HEALTH_TIMEOUT_S)])
    result, hits = env_file_run("", False)
    check_in("F2: a block with no health_url says so on the verdict line", "the environment block names no health_url",
             result["liveness"]["note"])
    check_in("F2: ...and the verdict line names where the address was read from", "read from", result["liveness"]["note"])
    result, hits = env_file_run("http://localhost:5000/api/live", drop_base_key=True)
    live_note = result["liveness"]["note"]
    check_eq("F2 (cell C): a block health_url and no base key: nothing asked, Layer 1",
             (len(hits), bool(result["layer1"]), result["liveness"]["verdict"]), (0, True, "unchecked"))
    check_not_in("F2 (cell C): ...and the note does not claim the block names none", "names none", live_note)
    check_in("F2 (cell C): ...it says the block's health_url was not used", "health_url is not used", live_note)
    # the env file exists but holds no such key: dead in words, not a pass
    block_missing = dict(block, base_url_key="NOT_THERE")
    cfg = {"environment": block_missing, "environments": [{"name": STAND}, {"name": "second"}]}
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(cfg, STAND, root=root)
    check_eq("an env file without the address key: stop, no request", (bool(result["layer1"]), len(asked(fetch))), (True, 0))

    # The ONLY entry without an address: the block is that stand (F-1 (b)), said on the verdict line.
    cfg = config()
    cfg["environments"] = [{"name": STAND}]
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(cfg, STAND, root=root)
    check_eq("the only entry without an address is probed at the block's address",
             asked(fetch), [("http://localhost:5000/api/conferences", E.HEALTH_TIMEOUT_S)])
    check_eq("...and passes", result["layer1"], [])
    check_eq("...marked inherited", result["address_source"], "inherited")
    line = E.verdict_lines(result)[0]
    check_in("...the VERDICT line says the address was inherited from the project", E.INHERITED, line)
    check("...at column 0, one of the three lines (not a detail)", line.startswith("liveness: alive"), line)
    check_in("...and so does the JSON form", E.INHERITED, json.dumps(result["liveness"]))
    check_in("...the detail line names it too", E.INHERITED, "\n".join(result["details"]))

    # B-1: that same entry under a block with NO address: nothing was asked, and nothing is confirmed.
    for label, block in (("empty", {}), ("keys but no address", {"user_key": "U", "secret_keys": ["P"]})):
        cfg = {"environment": block, "environments": [{"name": STAND}]}
        with patch.object(E, "_fetch", return_value=200) as fetch:
            result = E.probe(cfg, STAND, root=root)
        check_eq(f"B-1: the only address-less entry under a {label} block asks nothing", len(asked(fetch)), 0)
        check_eq(f"B-1 ({label}): ...liveness stays `unchecked`", result["liveness"]["verdict"], "unchecked")
        check(f"B-1 ({label}): ...and that is Layer 1 under --env, never a pass",
              any("no address" in item for item in result["layer1"]), str(result["layer1"]))
        check_eq(f"B-1 ({label}): ...no login is tried", result["login"]["status"], "skipped")
        check_in(f"B-1 ({label}): ...the verdict line says nobody asked", "nothing was asked",
                 E.verdict_lines(result)[0])


def secrecy_cases(root: Path) -> None:
    secret = "hunter2pw"
    token = "tok3nvalue"
    cfg = config()
    cfg["environments"][0]["api_base_url"] = f"https://svc:{secret}@stand.example:15000/base?token={token}#frag"
    with patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(cfg, STAND, root=root)
    check_in("the request itself goes to the real address (the secret is only hidden from the reader)",
             secret, fetch.call_args.args[0])
    text = printed(result)
    for needle in (secret, token, "svc:", "frag"):
        check_not_in(f"a credential ({needle}) is in no printed line - detail, verdict lines, JSON", needle, text)
    check_in("...the host is still shown", "stand.example:15000", text)

    def fail(url, timeout):
        raise OSError("refused")

    with patch.object(E, "_fetch", side_effect=fail):
        result = E.probe(cfg, STAND, root=root)
    text = printed(result)
    check_eq("the dead path is masked as well", (result["liveness"]["verdict"], secret in text, token in text),
             ("dead", False, False))

    # The block's own address, read from an env file, is printed through the same function.
    (root / "stand.env").write_text(f"BASE=https://svc:{secret}@block.example/x?token={token}\n", encoding="utf-8")
    block = {"env_file": "stand.env", "base_url_key": "BASE", "health_path": "/h", "access": {"kind": "none"}}
    with patch.object(E, "_fetch", return_value=200):
        result = E.probe({"environment": block}, "", root=root)
    text = printed(result)
    check_eq("the block's env-file address is masked in every printed line",
             (secret in text, token in text, "block.example" in text), (False, False, True))


def selected_config_cases() -> None:
    cfg, before = config(), copy.deepcopy(config())
    chosen, base, error, source = E.selected_probe_config(cfg, STAND)
    check_eq("selected_probe_config: the stand's api_base_url wins over base_url", base, "http://localhost:15000")
    check_eq("selected_probe_config: the global health_url is dropped, the health_path kept",
             ("health_url" in chosen, chosen.get("health_path")), (False, "/api/conferences"))
    check_eq("selected_probe_config: no error, own source", (error, source), (None, "own"))
    check_eq("selected_probe_config is pure", cfg, before)
    two = {"environment": {"health_url": "http://h/x", "health_path": "/p"}, "environments": [{"name": STAND}, {"name": "b"}]}
    chosen, base, error, source = E.selected_probe_config(two, STAND)
    check_eq("selected_probe_config: a name-only entry among 2+ is `env file`, no error, the absolute health_url kept as a "
             "CANDIDATE (the caller, which reads the env file, keeps or drops it)",
             (base, error, source, chosen.get("health_url"), chosen.get("health_path")), ("", None, "env file", "http://h/x", "/p"))
    check_eq("_same_origin: scheme, host and port, defaults filled in, case-insensitive",
             [E._same_origin("HTTP://Host:80/a", "http://host"), E._same_origin("http://h:81/a", "http://h"),
              E._same_origin("http://h/a", "h:80"), E._same_origin("", "http://h"), E._same_origin("http://h", "")],
             [True, False, False, False, False])
    chosen, base, error, source = E.selected_probe_config(config(), "")
    check_eq("selected_probe_config: no name returns the environment block as is",
             (chosen, base, error, source), (config()["environment"], "", None, "block"))
    check_eq("selected_probe_config: the name rule is exact, as data_cleanup's",
             E.selected_probe_config(config(), STAND.upper())[2] is not None, True)
    rows = [None, "x", {"name": STAND, "base_url": "http://h"}]
    check_eq("selected_probe_config: a non-dict row is ignored, not a crash",
             E.selected_probe_config({"environments": rows}, STAND)[1], "http://h")
    check_eq("selected_probe_config: environments[] absent or null is `missing`, never a crash",
             [E.selected_probe_config(c, STAND)[3] for c in ({}, {"environments": None}, None)], ["none"] * 3)


def serving(counter: list):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            counter.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run_main(root: Path, cfg: dict, *args):
    (root / "qa-factory").mkdir(exist_ok=True)
    (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return run_script("env_probe.py", "--project-root", str(root), "--no-login", *args)


def main_cases() -> None:
    hits: list = []
    server = serving(hits)
    default_stack = f"http://127.0.0.1:{server.server_address[1]}/health"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # An empty block and a stand that is not in environments[]: not "not configured", not alive.
            done = run_main(root, {"environment": {}, "environments": []}, "--env", "qa", "--json")
            data = json.loads(done.stdout) if done.stdout.strip().startswith("{") else {}
            check_eq("main: an absent stand under an empty block exits 1", done.returncode, 1)
            check("main: ...with the JSON verdict and a Layer 1 finding", bool(data.get("layer1")), done.stdout + done.stderr)
            check_eq("main: ...liveness dead", (data.get("liveness") or {}).get("verdict"), "dead")

            # The default stack is alive and named in the block: a missing stand must not borrow it.
            cfg = {"environment": {"health_url": default_stack}, "environments": [{"name": "other"}]}
            done = run_main(root, cfg, "--env", "qa", "--json")
            check_eq("main: a name that is not in environments[] exits 1 although the default stack answers",
                     done.returncode, 1)
            done = run_main(root, cfg, "--env", "--task", "X")
            check_eq("main: `--env --task X` (an option read as the name) exits 1", done.returncode, 1)
            check_eq("main: ...and no request reached the default stack", hits, [])

            # B-1 through the real exit code.
            done = run_main(root, {"environment": {}, "environments": [{"name": "qa"}]}, "--env", "qa")
            check_eq("B-1 main: the only address-less entry under an empty block exits 1", done.returncode, 1)
            check_in("B-1 main: ...and says why", "no address", done.stdout + done.stderr)

            # The live shape through the real exit code: names only, the address in the env file.
            (root / "live.env").write_text(f"LIVE_BASE={default_stack.rsplit('/', 1)[0]}\n", encoding="utf-8")
            cfg = {"environment": {"env_file": "live.env", "base_url_key": "LIVE_BASE", "health_path": "/health"},
                   "environments": [{"name": "qa"}, {"name": "other"}]}
            done = run_main(root, cfg, "--env", "qa", "--json")
            data = json.loads(done.stdout)
            check_eq("main: names only + the address in the env file exits 0", done.returncode, 0)
            check_eq("main: --json carries liveness.address_source `env file`",
                     (data["liveness"].get("address_source"), sorted(data)), ("env file", ["keys", "layer1", "liveness", "login"]))
            done = run_main(root, cfg, "--env", "qa")
            check_in("main: the text form carries `address_source: env file` on a column-0 line", E.FROM_ENV_FILE,
                     "\n".join(ln for ln in done.stdout.splitlines() if not ln.startswith(" ")))
            check_eq("main: the env file's address was asked, twice", len(hits), 2)
            hits.clear()

            # The only entry inherits the live block: exit 0 and the fact is in the JSON and the text.
            cfg = {"environment": {"health_url": default_stack}, "environments": [{"name": "qa"}]}
            done = run_main(root, cfg, "--env", "qa", "--json")
            data = json.loads(done.stdout)
            check_eq("main: the only entry inherits the live block and exits 0", done.returncode, 0)
            check_eq("main: --json carries address_source (a key of liveness; the four top-level fields stay)",
                     (data["liveness"].get("address_source"), sorted(data)), ("inherited", ["keys", "layer1", "liveness", "login"]))
            check_in("main: --json carries the phrase in liveness.note", E.INHERITED, data["liveness"]["note"])
            done = run_main(root, cfg, "--env", "qa")
            check_in("main: the text form carries the phrase on a column-0 line", E.INHERITED,
                     "\n".join(ln for ln in done.stdout.splitlines() if not ln.startswith(" ")))
            check_eq("main: the block was asked, twice (--json then text)", len(hits), 2)

            # Own dead address with a LIVE default stack: exit 1 (the FB-36 case itself).
            hits.clear()
            cfg = {"environment": {"health_url": default_stack},
                   "environments": [{"name": "qa", "base_url": "http://127.0.0.1:1"}]}
            done = run_main(root, cfg, "--env", "qa", "--json")
            check_eq("main: a dead own address exits 1 although the default stack is alive", done.returncode, 1)
            check_eq("main: ...and the default stack was never asked", hits, [])
    finally:
        server.shutdown()
        server.server_close()


DEVICE_ROW = {"name": "emulator", "surface": "android", "driver": {"url": "http://127.0.0.1:4723"},
              "device": {"serial_key": "ANDROID_SERIAL"}, "app": {"id": "com.example.app"}}
READ_OK = {"verdict": "ok", "checks": [{"name": "devices", "state": "devices", "line": "one device is connected: emulator-5554"},
                                       {"name": "driver", "state": "ready", "line": "the Appium server answers"}], "block": None}


def refused(state: str, owner: str, line: str = "no device is connected") -> dict:
    return {"verdict": state, "checks": [{"name": "devices", "state": state, "line": line}],
            "block": {"probe_line": line, "remedy": "start an emulator, then run this again", "owner": owner,
                      "do_not_retry": owner == "user", "cause": "device"}}


def fake_device(reply=None, raises=None, calls=None):
    """A stand-in for device_stand.py (EP1-41b's script): `probe(cfg, env_name, deep=False)` is all the probe reads of it."""
    import types
    module = types.ModuleType("device_stand")

    def probe(cfg, env_name, deep=False):
        if calls is not None:
            calls.append((env_name, deep))
        if raises is not None:
            raise raises
        return reply
    module.probe = probe
    return module


def device_main(cfg: dict, *args) -> tuple:
    """`env_probe.main` in this process (the fake module must be seen): (exit code, stdout, stderr)."""
    import contextlib
    import io
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "qa-factory").mkdir()
        (root / "qa-factory" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["env_probe.py", "--project-root", str(root), "--no-login", *args]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                E.main()
                code = 0
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()


def device_stand_cases(root: Path) -> None:
    """EP1-41c: a named stand that is a device stand is asked of device_stand.probe (deep=False) BEFORE selected_probe_config;
    nothing but a verdict `ok` is exit 0 (AR-28), a web config keeps its answers."""
    import surfaces
    cfg = {"environment": {}, "environments": [dict(DEVICE_ROW)]}
    for label, reply in (("ok", READ_OK),):
        calls: list = []
        with patch.dict(sys.modules, {"device_stand": fake_device(reply, calls=calls)}), \
                patch.object(E, "_fetch", side_effect=AssertionError("a device stand is never fetched")):
            result = E.probe(cfg, "emulator", root=root)
            code, out, err = device_main(cfg, "--env", "emulator")
        check_eq("device: a live device stand has no Layer 1 finding", result["layer1"], [])
        check_eq("device: ...liveness ok, its note the checks' lines",
                 (result["liveness"]["verdict"], "emulator-5554" in result["liveness"]["note"]), ("ok", True))
        check_eq("device: ...no login by code, no key to miss", (result["login"]["status"], result["keys"]), ("skipped", {"verdict": "ok", "missing": []}))
        check_eq("device: ...address_source own, no env file source", (result["address_source"], result["source"]), ("own", ""))
        check_eq("device: the probe is asked read-only (deep=False) with the row's name", calls[0], ("emulator", False))
        check_eq("device: main exits 0 for a live device stand and never touched the network", code, 0)
        check("device: ...every detail line is indented (only the three verdict lines are at column 0)",
              all(line.startswith("  ") for line in result["details"]) and bool(result["details"]), str(result["details"]))
        check_eq("device: the three verdict lines only at column 0",
                 [ln.split(":")[0] for ln in out.splitlines() if ln and not ln.startswith(" ")], ["liveness", "login", "keys"])

    # no device / a refused check / an unreadable or foreign answer: Layer 1 and exit 1, never ok
    for label, reply, owner_word in (("no device", refused("no_device", "user"), "no device is connected"),
                                      ("tool_error", refused("tool_error", "user", "adb failed"), "adb failed"),
                                      ("unreadable", refused("unreadable", "factory", "adb printed nothing"), "adb printed nothing"),
                                      ("foreign", refused("foreign", "factory", "the address is not an Appium server"), "not an Appium")):
        with patch.dict(sys.modules, {"device_stand": fake_device(reply)}):
            result = E.probe(cfg, "emulator", root=root)
            code, out, err = device_main(cfg, "--env", "emulator", "--json")
        check_eq(f"device {label}: exit 1 and the liveness is dead", (code, result["liveness"]["verdict"]), (1, "dead"))
        check(f"device {label}: Layer 1 names it and the way out", len(result["layer1"]) == 1 and owner_word in result["layer1"][0]
              and "start an emulator" in result["layer1"][0], str(result["layer1"]))
        check_eq(f"device {label}: --json keeps its four fields", sorted(json.loads(out)), ["keys", "layer1", "liveness", "login"])

    # everything unexpected is a line and exit 1 (AR-28)
    for label, module in (("a probe that raises", fake_device(raises=RuntimeError("boom"))),
                          ("a reply that is not a dict", fake_device("fine")),
                          ("a reply with no verdict", fake_device({"checks": []})),
                          ("a verdict that is not `ok` and no block", fake_device({"verdict": "maybe", "checks": []})),
                          ("`ok` written as a truthy non-string", fake_device({"verdict": True, "checks": []})),
                          ("no device_stand module at all", None)):
        with patch.dict(sys.modules, {"device_stand": module}):
            result = E.probe(cfg, "emulator", root=root)
            code, out, err = device_main(cfg, "--env", "emulator")
        check_eq(f"device unknown: {label} -> exit 1, dead", (code, result["liveness"]["verdict"], bool(result["layer1"])), (1, "dead", True))

    # the position invariant: the branch is before selected_probe_config - the row has no address and is still not `unchecked`
    with patch.dict(sys.modules, {"device_stand": fake_device(READ_OK)}):
        check_not_in("device: ...and a live row never says `no address`", "no address", json.dumps(E.probe(cfg, "emulator", root=root)))

    # a surface the table lacks is named, not the web; a surface of another hands goes the old road, table-driven
    calls = []
    typo = {"environment": {}, "environments": [dict(DEVICE_ROW, surface="andriod")]}
    with patch.dict(sys.modules, {"device_stand": fake_device(READ_OK, calls=calls)}):
        result = E.probe(typo, "emulator", root=root)
    check("device: a typo in `surface` is a Layer 1 line that names the list, and the device is not asked",
          "android" in " ".join(result["layer1"]) and calls == [], str(result["layer1"]))
    web_row = {"environment": {}, "environments": [{"name": "w", "surface": "web", "base_url": "http://localhost:1"}]}
    with patch.dict(sys.modules, {"device_stand": fake_device(READ_OK, calls=calls)}), patch.object(E, "_fetch", return_value=200) as fetch:
        result = E.probe(web_row, "w", root=root)
    check_eq("device: a `surface: web` row goes the old road (its own address asked, the device not)",
             (calls, asked(fetch), result["address_source"]), ([], [("http://localhost:1", E.HEALTH_TIMEOUT_S)], "own"))

    # a web config (no `surface` anywhere): the table is never read, the device never asked, the answers are the old ones
    reads = {"n": 0}
    real_rows = surfaces.rows

    def counted():
        reads["n"] += 1
        return real_rows()
    with patch.object(surfaces, "rows", counted), patch.dict(sys.modules, {"device_stand": fake_device(READ_OK, calls=calls)}), \
            patch.object(E, "_fetch", return_value=200):
        old = E.probe(config(), STAND, root=root)
    check_eq("web: a config with no `surface` reads the table 0 times and asks no device",
             (reads["n"], calls, old["layer1"], old["address_source"]), (0, [], [], "own"))
    code, out, err = device_main({"environment": {}, "environments": [{"name": "qa"}]}, "--env", "qa")
    check_eq("web: an address-less named stand is Layer 1 as before", (code, "no address" in out + err), (1, True))

    # the mixed project: one device stand, one API stand - each asked by its own name
    mixed = {"environment": {}, "environments": [dict(DEVICE_ROW), {"name": "qa", "base_url": "http://localhost:9"}]}
    calls = []
    with patch.dict(sys.modules, {"device_stand": fake_device(READ_OK, calls=calls)}), patch.object(E, "_fetch", return_value=200) as fetch:
        api = E.probe(mixed, "qa", root=root)
        phone = E.probe(mixed, "emulator", root=root)
    check_eq("mixed: --env of the API stand asks the API address and not the device", (asked(fetch), calls[:1]),
             ([("http://localhost:9", E.HEALTH_TIMEOUT_S)], [("emulator", False)]))
    check_eq("mixed: both are alive", (api["layer1"], phone["layer1"]), ([], []))
    # two device stands: the name picks the row
    two = {"environment": {}, "environments": [dict(DEVICE_ROW), dict(DEVICE_ROW, name="tablet", surface="ios")]}
    calls = []
    with patch.dict(sys.modules, {"device_stand": fake_device(READ_OK, calls=calls)}):
        E.probe(two, "tablet", root=root)
    check_eq("two device stands: the name picks the row the probe is asked about", calls, [("tablet", False)])
    # two rows of one name stay the selection error, never a device answer
    dup = {"environment": {}, "environments": [dict(DEVICE_ROW), dict(DEVICE_ROW)]}
    calls = []
    with patch.dict(sys.modules, {"device_stand": fake_device(READ_OK, calls=calls)}):
        result = E.probe(dup, "emulator", root=root)
    check("two rows of one name: the old selection error, the device not asked", calls == [] and bool(result["layer1"]), str(result["layer1"]))
    # no name and only a device row: the old road - not configured, exit 1, no pass
    code, out, err = device_main({"environment": {}, "environments": [dict(DEVICE_ROW)]})
    check_eq("device: no --env and an empty block with only a device row is still `not configured`, exit 1", code, 1)
    check_in("device: ...said out loud", "not configured", out + err)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        own_address_cases(root)
        disputed_selection_cases(root)
        addressless_cases(root)
        secrecy_cases(root)
        device_stand_cases(root)
    selected_config_cases()
    main_cases()
    finish("test_env_selected_stand")


if __name__ == "__main__":
    main()
