#!/usr/bin/env python3
"""B-407 A-map Q-d: which files the inventory's source sweep reads.

`project_inventory.CODE_SUFFIXES` was a fifth private list of code extensions. The sweep now asks
`test_files.is_code_file` (the markers file's `code_extensions`), falls back to its own floor `_SWEEP_FLOOR` (the old list)
when that is unknown (FR-59), and keeps one residual list of the shell and config files an env-key sweep reads whatever
their language (`ENV_SWEEP_SUFFIXES`). The first pin was taken on the OLD code (the files the sweep returned on this
fixture) and holds byte for byte; the other pins say what the move changes on purpose.
"""
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import project_inventory as PI  # noqa: E402
import test_files as TF  # noqa: E402

# Every name here was in the old CODE_SUFFIXES (or is an env file) and is in the markers' code_extensions or in the
# residual list: the sweep's answer on it is the same before and after the move.
OLD_FIXTURE = ("app.py", "web/app.ts", "web/App.tsx", "web/Old.jsx", "svc/Main.java", "svc/Main.kt", "svc/Main.cs",
               "lib/x.rb", "cmd/main.go", "site/index.php", "ops/run.sh", "ops/run.ps1", "ops/compose.yml",
               "ops/compose.yaml", "ops/pyproject.toml", "ops/tox.cfg", "ops/setup.ini", "harness/.env", ".env.local")
IGNORED = ("README.md", "notes.txt", "data.json", "image.png", "node_modules/dep/index.js", "qa-factory/config.json")
NEW_ON_PURPOSE = ("web/app.mjs", "web/app.cjs", "svc/Main.scala", "native/lib.rs")


def build(root: Path, names) -> None:
    for name in names:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x = 1\n", encoding="utf-8")


def swept(root: Path) -> list:
    return sorted(p.relative_to(root).as_posix() for p in PI._walk(root))


def main() -> None:
    root = temp_dir("qa-inventory-sweep-").resolve()
    try:
        build(root, OLD_FIXTURE + IGNORED)
        check_eq("the sweep reads exactly the old fixture (taken on the code before the move): every old code suffix, "
                 "the shell and config files, the env files; nothing else", swept(root), sorted(OLD_FIXTURE))
        build(root, NEW_ON_PURPOSE)
        got = swept(root)
        check_eq("a code extension the markers know and the old list did not is read now (one list of code, not five)",
                 sorted(n for n in NEW_ON_PURPOSE if n in got), sorted(NEW_ON_PURPOSE))
        real = TF.markers
        TF.markers = lambda: ({}, "missing, unreadable or empty")
        TF._NOTED.clear()
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                floor = swept(root)
        finally:
            TF.markers = real
            TF._NOTED.clear()
        check_eq("markers unreadable: the inventory's own floor decides (F5, the safe direction is to read MORE): every file "
                 "the old sweep read, `.jsx` and `.php` included, and none of the newer extensions", floor, sorted(OLD_FIXTURE))
        check_eq("... and that floor is the old CODE_SUFFIXES, not the leaf's narrower one",
                 sorted(set(PI._SWEEP_FLOOR) - set(TF.CODE_EXTENSION_FLOOR)), [".cfg", ".ini", ".jsx", ".php", ".ps1", ".sh", ".toml", ".yaml", ".yml"])
    finally:
        cleanup(root)
    # F2: the memo is keyed by the extension the leaf reads; a dotfile named `.py` has none, and must not make
    # extension-less files (Makefile, LICENSE) look like code
    dots = temp_dir("qa-inventory-dotfile-").resolve()
    try:
        build(dots, (".py", "Makefile", "LICENSE", "app.py"))
        check_eq("F2: a dotfile named .py has no extension: only app.py is swept", swept(dots), ["app.py"])
    finally:
        cleanup(dots)
    # OH3-10 D4 (AR-22): the producer of the two login-body keys. The proposal carries them (empty: discovery does not
    # read the body form from the call site yet) and the rendering shows them, so the interview confirms what phase 1
    # found instead of asking cold; the keys are the template's own, so the probe's reader has a code producer.
    import json as _json
    template_access = _json.loads((SCRIPTS.parent / "references" / "templates" / "config.json")
                                  .read_text(encoding="utf-8"))["environment"]["access"]
    scan = {"sites": [{"kind": "local_login", "evidence": "/v1/local-auth/login", "where": "sdk/auth.py:12",
                       "keys": ["AUTH_USERNAME", "AUTH_PASSWORD"], "file": "sdk/auth.py"}]}
    proposal = PI.propose_access(scan, ["AUTH_USERNAME", "AUTH_PASSWORD"])
    check_eq("OH3-10 D4: the proposed access carries user_field / secret_field, empty", (
        proposal["access"].get("user_field"), proposal["access"].get("secret_field")), ("", ""))
    check_eq("OH3-10 D4: the proposed keys are the template's access keys (minus the proof)",
             sorted(proposal["access"]), sorted(k for k in template_access if k != "login_probe"))

    def rendered(access: dict) -> str:
        return PI.render_access({"proposed_access": access, "proposal_note": "", "env_file": "harness/.env",
                                 "env_keys": ["AUTH_USERNAME"], "access_evidence": [], "other_login_evidence": [],
                                 "login_keys_absent_from_env_file": [], "absent_key_groups": []})

    shown = rendered(proposal["access"])
    check("OH3-10 D4 / FB-3: render shows the two keys, the pairs the probe tries in order, and that onboarding records "
          "the accepted one, for local_login",
          "user_field / secret_field" in shown and "`username` / `password` then `email` / `password`" in shown
          and "onboarding records it" in shown, shown)
    shown = rendered(dict(proposal["access"], user_field="email", secret_field="password"))
    check("OH3-10 D4: a found name is shown as its own line", "user_field: email" in shown
          and "secret_field: password" in shown and "not found" not in shown, shown)
    shown = rendered(dict(proposal["access"], kind="oidc_password"))
    check("OH3-10 D4: another kind does not talk about the login body", "user_field" not in shown, shown)
    proposals_tests()
    pairs_tests()
    candidates_tests()
    same_origin_tests()
    finish("test_project_inventory")


# --- OH3-8: `integration_proposals`, the places the code reads the keys as facts ---------------------------------------

JIRA = ["JIRA_URL", "JIRA_TOKEN", "JIRA_PROJECT_KEY", "JIRA_CLOUD_URL", "JIRA_CLOUD_TOKEN", "JIRA_CLOUD_EMAIL",
        "JIRA_CLOUD_PROJECT_KEY"]
SENTINEL = "sentinel-value-71ac"


def reads(root: Path, rel: str, keys) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import os\n" + "".join(f'x = os.getenv("{k}")\n' for k in keys), encoding="utf-8")


def discovery(root: Path, env_lines=(), raw: bytes = b"") -> dict:
    (root / ".env").write_bytes(("\n".join(env_lines) + "\n").encode("utf-8") + raw)
    return PI.access_discovery(root)


def proposals_tests() -> None:
    import json as _json
    root = temp_dir("qa-inventory-proposals-").resolve()
    try:
        reads(root, "tests/jira/test_jira.py", JIRA)
        got = discovery(root, [f"{k}={SENTINEL}" for k in JIRA[:3]])["integration_proposals"]
        check_eq("K-B1: the 7 keys of the jira row are one record: ALL of them, and the 3 the file holds named apart",
                 [(p["name"], p["keys"], p["set_in_env_file"]) for p in got],
                 [("jira-integration", sorted(JIRA), sorted(JIRA[:3]))])
        check_eq("K-B1: the same tree, the file holds none: the same 7, nothing set",
                 [(p["keys"], p["set_in_env_file"]) for p in discovery(root, ["OTHER=1"])["integration_proposals"]],
                 [(sorted(JIRA), [])])
        full = discovery(root, [f"{k}=1" for k in JIRA])["integration_proposals"]
        check_eq("K-B1: a prefix whose keys are all set is not proposed", full, [])
        found = discovery(root, [f"{k}={SENTINEL}" for k in JIRA[:3]])
        check_eq("K-B1: and no value leaves discovery, in the JSON or the text",
                 SENTINEL in _json.dumps(found) + PI.render_access(found), False)
        text = PI.render_access(found)
        check("K-B1: the text says how many groups and keys, and that nobody is asked",
              "integration proposals: 1 groups, 7 keys; --json has them" in text
              and "phase 1 records these in integrations[]; nobody is asked about them" in text, text)
    finally:
        cleanup(root)
    root = temp_dir("qa-inventory-areas-").resolve()
    try:
        reads(root, "tests/ado/test_x.py", ["ADO_URL"])
        reads(root, "helpers/config.py", ["HLP_URL"])
        reads(root, "tests/utils/creds.py", ["UTL_URL"])
        reads(root, "test_root.py", ["ROOT_URL"])
        by = {p["name"]: p for p in discovery(root, ["OTHER=1"])["integration_proposals"]}
        check_eq("K-B2: a call in a test file: the folder is the area, the place has its line",
                 (by["ado-integration"]["required_by"], by["ado-integration"]["read_at"]), (["tests/ado"], ["tests/ado/test_x.py:2"]))
        check_eq("K-B2: a helper outside tests/: no area, the place stays", ("required_by" in by["hlp-integration"],
                                                                              by["hlp-integration"]["read_at"]),
                 (False, ["helpers/config.py:2"]))
        check_eq("K-B2: a helper UNDER tests/ is no area either (M3 of the plan critic)", ("required_by" in by["utl-integration"],
                                                                                             by["utl-integration"]["read_at"]),
                 (False, ["tests/utils/creds.py:2"]))
        check_eq("K-B2: a test at the root of the project is its file name", by["root-integration"]["required_by"], ["test_root.py"])
        real = TF.markers
        TF.markers = lambda: ({}, "missing, unreadable or empty")
        TF._NOTED.clear()
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                unknown = {p["name"]: p for p in PI.access_discovery(root)["integration_proposals"]}
        finally:
            TF.markers = real
            TF._NOTED.clear()
        check_eq("K-B2: markers that cannot be read: nothing is a test, so no area (an unknown is never an area)",
                 [n for n, p in unknown.items() if "required_by" in p], [])
    finally:
        cleanup(root)
    for count, more in ((5, False), (6, True)):
        root = temp_dir(f"qa-inventory-limits-{count}-").resolve()
        try:
            for n in range(count):
                reads(root, f"tests/area{n}/test_x.py", [f"SVC_K{n}"])
            one = discovery(root, ["OTHER=1"])["integration_proposals"][0]
            check_eq(f"K-B3: {count} places and {count} areas: {'5 kept, 1 counted' if more else 'all kept, no counter'}",
                     (len(one["read_at"]), one.get("read_at_more"), len(one["required_by"]), one.get("required_by_more")),
                     (5, 1 if more else None, 5, 1 if more else None))
        finally:
            cleanup(root)
    root = temp_dir("qa-inventory-battery-").resolve()
    try:
        prefixes = [f"P{n:02d}" for n in range(12)]
        names = [f"{prefix}_K{m}" for prefix in prefixes for m in range(11)] + [f"P00_A{n}" for n in range(7)]
        reads(root, "tests/all/test_all.py", names + ["HEADLESS", "AWS_PROFILE", "AWS_SESSION_TOKEN"])
        (root / "cli").mkdir()
        (root / "cli" / "commands.py").write_text('import os\n@cli.command("login")\ndef login():\n    os.getenv("LOGINX_KEY")\n',
                                                  encoding="utf-8")
        got = discovery(root, [f"AUTH={SENTINEL}"], raw=b"BAD=\xff\xfe\n")
        proposals = got["integration_proposals"]
        check_eq("K-B4: 139 keys of 12 prefixes and the one key read only in a login file (F-4): none lost",
                 (len(proposals), sum(len(p["keys"]) for p in proposals)), (13, 140))
        every = {k for p in proposals for k in p["keys"]}
        check_eq("K-B4: the factory's switch and a client switch are in no proposal",
                 [k for k in ("HEADLESS", "AWS_PROFILE", "AWS_SESSION_TOKEN") if k in every], [])
        check_eq("F-4: an absent key read only in a login file is still proposed (the role sees it)",
                 [k for k in ("LOGINX_KEY",) if k in every], ["LOGINX_KEY"])
        check_eq("K-B4: the value in the file is in no output", SENTINEL in _json.dumps(got) + PI.render_access(got), False)
        check_eq("K-B4: the same grouping the interview counts (one grouping, two readers; the login-file key is listed apart)",
                 {g["prefix"] for g in got["absent_key_groups"]} - {"HEADLESS", "AWS", "LOGINX"},
                 {p["name"].split("-")[0].upper() for p in proposals} - {"LOGINX"})
    finally:
        cleanup(root)
    root = temp_dir("qa-inventory-login-set-").resolve()
    try:
        # F-4 (P3 of the critic): a shared conftest holds the login call AND reads the Server set of an integration; a test
        # reads the Cloud name. The Server set must stay visible next to it, and a key the proposed login uses must not.
        (root / "tests").mkdir()
        (root / "tests" / "conftest.py").write_text(
            'import os\n@cli.command("login")\ndef login():\n    os.getenv("JIRA_URL")\n    os.getenv("JIRA_TOKEN")\n'
            '    os.getenv("AUTH_USER")\n    os.getenv("AUTH_ZONE")\n', encoding="utf-8")
        reads(root, "tests/test_j.py", ["JIRA_CLOUD_URL"])
        got = discovery(root, ["AUTH_USER=1"])
        by = {p["name"]: p for p in got["integration_proposals"]}
        check_eq("F-4: JIRA_URL and JIRA_TOKEN (read only in the login file) stay in the jira proposal with the Cloud name",
                 by["jira-integration"]["keys"], ["JIRA_CLOUD_URL", "JIRA_TOKEN", "JIRA_URL"])
        check_eq("F-4: the key the proposed login uses (held, chosen) is in no proposal, its absent sibling is",
                 (got["proposed_access"]["user_key"], by["auth-integration"]["keys"]), ("AUTH_USER", ["AUTH_ZONE"]))
    finally:
        cleanup(root)
    empty = temp_dir("qa-inventory-empty-").resolve()
    try:
        check_eq("K-B4: no calls and no env file: nothing is proposed", PI.access_discovery(empty)["integration_proposals"], [])
        reads(empty, "tests/a/test_a.py", ["SVC_URL"])
        check_eq("K-B4: calls but no env file: nothing is proposed (no file, no claim that a key is absent)",
                 PI.access_discovery(empty)["integration_proposals"], [])
    finally:
        cleanup(empty)


# --- HF8-9: `account_pairs`, the accounts the env file's names suggest ---------------------------------------------------------

LOGIN_SITE = 'import os\n@cli.command("login")\ndef login():\n    os.getenv("AUTH_USERNAME")\n    os.getenv("AUTH_PASSWORD")\n'


def pairs_of(root: Path, names, *, example: bool = False) -> dict:
    """`access_discovery` of a project whose env file holds `names` (every value is the sentinel)."""
    target = root / (".env.example" if example else ".env")
    target.write_text("".join(f"{n}={SENTINEL}\n" for n in names), encoding="utf-8")
    return PI.access_discovery(root)


def pair_rows(found: dict) -> list:
    return [(p["user_key"], p["secret_key"], p["is_login"]) for p in found["account_pairs"]]


def pairs_tests() -> None:
    import json as _json
    root = temp_dir("qa-inventory-pairs-").resolve()
    try:
        (root / "sdk").mkdir()
        (root / "sdk" / "auth.py").write_text(LOGIN_SITE, encoding="utf-8")
        found = pairs_of(root, ["AUTH_USERNAME", "AUTH_PASSWORD", "QA_SECOND_USER_EMAIL", "QA_SECOND_USER_PASSWORD"])
        check_eq("K-9.1 the reference: two pairs, the login's first and marked",
                 pair_rows(found), [("AUTH_USERNAME", "AUTH_PASSWORD", True), ("QA_SECOND_USER_EMAIL", "QA_SECOND_USER_PASSWORD", False)])
        check_eq("K-9.1 ... nothing cut, nothing unreadable", ("account_pairs_more" in found, found["account_pairs_unreadable"]), (False, 0))
        text = PI.render_access(found)
        check_in("K-9.1 the text names the pairs, the login's marked", "accounts in the env file: AUTH_USERNAME / AUTH_PASSWORD (the login's); "
                 "QA_SECOND_USER_EMAIL / QA_SECOND_USER_PASSWORD", text)
        check_eq("K-9.1 no value leaves discovery, in the JSON or the text", SENTINEL in _json.dumps(found) + text, False)
        # the awkward inputs of the spec: (the names the file holds, the pairs offered, the pairs the gate cannot read back)
        for label, names, offered, unreadable in (
                ("JIRA_USERNAME / JIRA_PASSWORD is a pair (an integration: the role judges, the code lists)",
                 ["JIRA_USERNAME", "JIRA_PASSWORD"], [("JIRA_USERNAME", "JIRA_PASSWORD")], 0),
                ("JIRA_USER / JIRA_TOKEN is no pair (a token is not a password)", ["JIRA_USER", "JIRA_TOKEN"], [], 0),
                ("a client secret with no user is no pair", ["AUTH_CLIENT_SECRET"], [], 0),
                ("one stem, two user names and one password: a pair for each user name",
                 ["USER_EMAIL", "USER_USERNAME", "USER_PASSWORD"], [("USER_EMAIL", "USER_PASSWORD"), ("USER_USERNAME", "USER_PASSWORD")], 0),
                ("names of different stems are not paired", ["QA_USER", "OTHER_PASSWORD"], [], 0),
                ("EMAIL / PASSWORD: no underscore - counted, not offered", ["EMAIL", "PASSWORD"], [], 1),
                ("USERNAME / PASSWORD: the same", ["USERNAME", "PASSWORD"], [], 1),
                ("lower case: the same", ["qa_user", "qa_password"], [], 1),
                ("the shortest readable names are a pair", ["A_USER", "A_PASSWORD"], [("A_USER", "A_PASSWORD")], 0),
                ("one readable and one unreadable pair", ["P_USER", "P_PASSWORD", "EMAIL", "PASSWORD"], [("P_USER", "P_PASSWORD")], 1)):
            got = pairs_of(root, names)
            check_eq(f"K-9.1 {label}", ([(p["user_key"], p["secret_key"]) for p in got["account_pairs"]], got["account_pairs_unreadable"]),
                     (offered, unreadable))
        check_eq("K-9.1 the readable form is the gate's own: A_B / C_D reads, EMAIL / PASSWORD does not",
                 (PI._pair_readable("A_B", "C_D"), PI._pair_readable("EMAIL", "PASSWORD")), (True, False))
        shown = PI.render_access(pairs_of(root, ["EMAIL", "PASSWORD"]))
        check_in("K-9.1 an unreadable pair is said, with its door", "--as env:USER_KEY/SECRET_KEY", shown)
        check_not_in("K-9.1 ... and is not listed among the accounts", "accounts in the env file", shown)
        # the limit: 8 whole, 9 cut and counted
        for count, more in ((8, None), (9, 1)):
            many = pairs_of(root, [f"P{n}_{kind}" for n in range(count) for kind in ("USER", "PASSWORD")])
            check_eq(f"K-9.1 {count} pairs: 8 are named, {'none left out' if more is None else 'the rest counted'}",
                     (len(many["account_pairs"]), many.get("account_pairs_more")), (8, more))
            shown = PI.render_access(many)
            check_eq(f"K-9.1 {count} pairs: the text says so only when it cut", "and 1 more, they are in the file" in shown, more is not None)
        # nothing to offer
        check_eq("K-9.1 an empty env file: no pairs", (pairs_of(root, [])["account_pairs"], PI.access_discovery(root)["account_pairs_unreadable"]), ([], 0))
        (root / ".env").unlink()
        check_eq("K-9.1 no env file at all: no pairs, no count", (PI.access_discovery(root)["account_pairs"],
                                                              PI.access_discovery(root)["account_pairs_unreadable"]), ([], 0))
        check_eq("K-9.1 ... and a text with no line about accounts", "accounts" in PI.render_access(PI.access_discovery(root)), False)
        only = pairs_of(root, ["AUTH_USERNAME", "AUTH_PASSWORD"], example=True)
        check_eq("K-9.1 a pair held only by .env.example is not offered (nobody set it)", (only["env_file"], only["account_pairs"]), (".env.example", []))
        (root / ".env").write_text("QA_SECOND_USER_EMAIL=x\nQA_SECOND_USER_PASSWORD=y\n", encoding="utf-8")
        both = PI.access_discovery(root)
        check_eq("K-9.1 with a real .env beside it, the real file's pairs are the ones", pair_rows(both),
                 [("QA_SECOND_USER_EMAIL", "QA_SECOND_USER_PASSWORD", False)])
    finally:
        cleanup(root)


# --- HF8-10: `frontend_candidates`, the names that hold an http address -------------------------------------------------------

def candidates_tests() -> None:
    import json as _json
    import env_probe
    root = temp_dir("qa-inventory-frontend-").resolve()
    try:
        def put(lines, name=".env"):
            (root / name).write_text("".join(f"{k}={v}\n" for k, v in lines), encoding="utf-8")
            return PI.access_discovery(root, {"environment": {"base_url_key": "API_BASE"}})
        addr = lambda n: f"http://{SENTINEL}-{n}.example.test"      # noqa: E731
        found = put([("API_BASE", addr("api")), ("FRONTEND_URL", addr(1)), ("JIRA_URL", addr(2)), ("SECRET_URL", addr(3)),
                     ("AUTH_URL", addr(4)), ("NOT_HTTP_URL", "ftp://x"), ("PLAIN", "text")])
        check_eq("K-10.1 the reference: FRONTEND_URL and JIRA_URL (the role judges which is the UI), file order; the API's own address, "
                 "a secret-looking name and a non-http value are not candidates", found["frontend_candidates"], ["FRONTEND_URL", "JIRA_URL"])
        check_eq("K-10.1 ... nothing cut", "frontend_candidates_more" in found, False)
        text = PI.render_access(found)
        check_in("K-10.1 the text names them", "http addresses in the env file: FRONTEND_URL, JIRA_URL", text)
        check_eq("K-10.1 no value leaves discovery, in the JSON or the text", SENTINEL in _json.dumps(found) + text, False)
        # the limit: HINT_MAX_NAMES whole, one more cut and counted
        limit = env_probe.HINT_MAX_NAMES
        for count, more in ((limit, None), (limit + 1, 1)):
            many = put([(f"UI_{n}_URL", addr(n)) for n in range(count)])
            check_eq(f"K-10.1 {count} candidates: {limit} are named, {'none left out' if more is None else 'the rest counted'}",
                     (len(many["frontend_candidates"]), many.get("frontend_candidates_more")), (limit, more))
            check_eq(f"K-10.1 {count} candidates: the text says so only when it cut",
                     "and 1 more, they are in the file" in PI.render_access(many), more is not None)
        # nothing to offer, and no crash
        check_eq("K-10.1 an empty env file", put([])["frontend_candidates"], [])
        (root / ".env").write_bytes(b"A_URL=http://ok.example.test\n\xff\xfe=\x80\nB_URL=\xc3\x28\n")
        check_eq("K-10.1 a file that is not UTF-8 does not crash; the readable name is still found",
                 PI.access_discovery(root)["frontend_candidates"], ["A_URL"])
        (root / ".env").unlink()
        check_eq("K-10.1 no env file: []", (PI.access_discovery(root)["frontend_candidates"], "http addresses" in PI.render_access(PI.access_discovery(root))),
                 ([], False))
        (root / ".env").mkdir()
        check_eq("K-10.1 an env file that is a directory: [] (nothing was read)", PI.frontend_candidates(root, {"path": ".env"}), [])
        check_eq("K-10.1 ... and a path that does not exist: []", PI.frontend_candidates(root, {"path": "gone/.env"}), [])
        (root / ".env").rmdir()
        only = put([("FRONTEND_URL", addr(1))], ".env.example")
        check_eq("K-10.1 an address held only by .env.example is not offered (nobody set it)", (only["env_file"], only["frontend_candidates"]),
                 (".env.example", []))
        check_eq("K-10.1 the enumeration is env_probe's own (one place for the hint and the discovery)",
                 "http_address_keys" in (Path(PI.__file__).read_text(encoding="utf-8")), True)
    finally:
        cleanup(root)


# --- RN1-3: `frontend_same_origin`, the API's own address key and the keys on its origin --------------------------------------

def same_origin_tests() -> None:
    root = temp_dir("qa-inventory-origin-").resolve()
    cfg = {"environment": {"base_url_key": "BASE_URL"}}
    try:
        def put(lines, name=".env", config=cfg):
            (root / name).write_text("".join(f"{k}={v}\n" for k, v in lines), encoding="utf-8")
            return PI.access_discovery(root, config)
        env = [("BASE_URL", "http://localhost:3000"), ("API_URL", "http://localhost:3000/api"), ("JIRA_URL", "https://jira.example")]
        found = put(env)
        check_eq("K-RN3-I1 the base key and the key on its origin", found["frontend_same_origin"],
                 {"base_url_key": "BASE_URL", "keys": ["API_URL"]})
        check_eq("K-RN3-I2 another PORT is another origin: base known, no key on it",
                 put([env[0], ("API_URL", "http://localhost:3001/api"), env[2]])["frontend_same_origin"],
                 {"base_url_key": "BASE_URL", "keys": []})
        check_eq("K-RN3-I2 another SCHEME is another origin", put([env[0], ("API_URL", "https://localhost:3000/api")])["frontend_same_origin"]["keys"], [])
        check_eq("K-RN3-I2 a secret-looking name on the origin is not named",
                 put([env[0], ("AUTH_URL", "http://localhost:3000/a"), ("API_URL", "http://localhost:3000/api")])["frontend_same_origin"]["keys"],
                 ["API_URL"])
        put(env)
        check_eq("K-RN3-I3 no config -> {}", PI.access_discovery(root)["frontend_same_origin"], {})
        check_eq("K-RN3-I3 base_url_key empty -> {}", PI.access_discovery(root, {"environment": {"base_url_key": ""}})["frontend_same_origin"], {})
        check_eq("K-RN3-I3 a base key the file does not hold -> {}",
                 PI.access_discovery(root, {"environment": {"base_url_key": "NOPE"}})["frontend_same_origin"], {})
        (root / ".env").unlink()
        check_eq("K-RN3-I4 only an .env.example -> {}", put(env, ".env.example")["frontend_same_origin"], {})
        check_eq("K-RN3-I5 a base value that is not an address -> {}",
                 put([("BASE_URL", "not-a-url"), ("API_URL", "http://localhost:3000/api")], ".env")["frontend_same_origin"], {})
        (root / ".env").unlink()
        (root / ".env.example").unlink()
        check_eq("K-RN3-I5 no env file at all -> {} and no line", (PI.access_discovery(root, cfg)["frontend_same_origin"],
                                                                  "the API's own address" in PI.render_access(PI.access_discovery(root, cfg))),
                 ({}, False))
        found = put(env)
        text = PI.render_access(found)
        check_in("K-RN3-I6 the text names the base key and the keys on its address", "the API's own address BASE_URL; on the same address: API_URL", text)
        check_in("K-RN3-I6 ... and what to judge", "if the project's UI tests open BASE_URL, the UI is on the API's address", text)
        check_not_in("K-RN3-I6 ... and no value", "localhost:3000", text)
        check_not_in("K-RN3-I6 ... in the JSON either", "localhost", " ".join(str(v) for v in found["frontend_same_origin"].values()))
        check_eq("K-RN3-I7 the W-2 candidates are unchanged (the base key is still left out)", found["frontend_candidates"], ["API_URL", "JIRA_URL"])
    finally:
        cleanup(root)


if __name__ == "__main__":
    main()
