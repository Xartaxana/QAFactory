#!/usr/bin/env python3
"""HF5-2 (t-1501 5.2): ONE reader of a stand's frontend address - `env_probe.frontend_of` (axis 29).

Keys: K1 (join) the stand config of run TP1-12586 (fixtures/run-12586-stand-config/) through the real
`manual_capture.environment_of`, no `values`; K2 the block's `url_key` for the one-and-only entry, and not for two;
K3 the probe's hint names the key and never the value; K4 edges (alias against frontend.url, an unreadable env file, the
two worlds of `frontend`, `export`, odd addresses, a steps file with no goto); K5 the hint at 5 and 6 names; K7 (AR-13)
no second reader in `scripts/`; K8 `definition_sha` of a flat-field config is the old hash. (K6 is test_stand_health.py.)

Mutations this file kills (each by this file alone):
  `stand_hosts` reads the entry's flat field itself instead of `frontend_of` (K2) | the block overrides the entry's own
  address (K4) | the hint prints the value (K3) | a copy of `_read_frontend` is left in `stand_health` (K7) |
  `http_address_keys` drops the `SECRET_NAME` test (K-10.2)

Run: python -B scripts/tests/test_frontend_reader.py
"""
import hashlib
import json
import shutil
import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "manual-evidence"))
import scaffold as S  # noqa: E402
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, finish  # noqa: E402

import env_probe  # noqa: E402
import stand_identity as SI  # noqa: E402

MC = S.MC
FIXTURE = harness.FIXTURES / "run-12586-stand-config"
UI = "http://localhost:5173/#/integrations"
ENV_REL = "testproject1_test_harness/env.fixture"


def project():
    """A copy of the fixture project, pointed at by hooklib (the reader's default root)."""
    root = harness.temp_dir("frontend-reader-") / "p"
    shutil.copytree(FIXTURE, root)
    harness.use_project(root)
    return root


def config(root, **edit):
    """The fixture config, `edit` applied to the single entry (None removes a key); `environment` edits via block=."""
    cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
    entry = cfg["environments"][0]
    for key, value in edit.items():
        if key == "block":
            cfg["environment"]["frontend"] = value
        elif value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    return cfg


def refusal(url, cfg, **kw):
    try:
        MC.environment_of(url, cfg, **kw)
    except ValueError as exc:
        return str(exc)
    return ""


def write_env(root, text):
    (root / ENV_REL).write_text(text, encoding="utf-8")


def probe_details(root, cfg, env_name=""):
    real = env_probe._fetch

    def refused(url, timeout):
        raise urllib.error.URLError(ConnectionRefusedError())
    env_probe._fetch = refused
    try:
        return env_probe.probe(cfg, env_name, root=root, do_login=False)["details"]
    finally:
        env_probe._fetch = real


def k1_join(root):
    cfg = config(root)
    check_eq("K1: the run's config (flat frontend_url, no block) - the UI URL is on the stand `local-docker`",
             MC.environment_of(UI, cfg)["name"], "local-docker")
    bare = config(root, frontend_url=None)
    err = refusal(UI, bare)
    check_in("K1 (was): with no flat field and no block the frontend host is refused, naming the API host",
             "Allowed hosts: http://localhost:8080.", err)
    check_in("K1: ... and the refusal says no frontend address is configured, and where it would be set",
             "no frontend address is configured (environment.frontend.url_key or environments[].frontend.url)", err)
    check_eq("K1: stand_hosts of the run's config holds both hosts, one entry",
             sorted(k[2] for k in MC.stand_hosts(cfg)), [5173, 8080])


def k2_block(root):
    cfg = config(root, frontend_url=None, block={"url_key": "FRONTEND_URL"})
    check_eq("K2: no flat field, the block's url_key (FRONTEND_URL in the env file) - the same entry (F-2 a)",
             MC.environment_of(UI, cfg)["name"], "local-docker")
    check_eq("K2: ... `frontend_of` names the source",
             env_probe.frontend_of(cfg, "local-docker")["source"], "environment.frontend.url_key")
    check_eq("K2: ... values given, the env file is not read",
             MC.environment_of(UI, cfg, {"FRONTEND_URL": "http://localhost:5173"})["name"], "local-docker")
    two = dict(cfg, environments=[cfg["environments"][0], {"name": "preview", "base_url": "https://preview.example.test"}])
    check_in("K2: the same block with TWO entries is not applied to any (E-F13): the UI URL is refused",
             "Allowed hosts:", refusal(UI, two))
    check_eq("K2: ... frontend_of of the named entry is ''", env_probe.frontend_of(two, "local-docker")["url"], "")
    check_eq("K2: ... and with no name asked for the block IS the stand",
             env_probe.frontend_of(two, "")["url"], "http://localhost:5173")


def k3_hint(root):
    bare = config(root, frontend_url=None)
    lines = probe_details(root, bare)
    hint = [x for x in lines if x.lstrip().startswith("frontend:")]
    check_eq("K3: one hint line", len(hint), 1)
    check_in("K3: it names FRONTEND_URL and the file", f"FRONTEND_URL in {ENV_REL} holds an http address", hint)
    check_in("K3: ... and the one door (onboarding writes url_key)", "set environment.frontend.url_key to it (onboarding)", hint)
    check_not_in("K3: no value anywhere in the details (the port)", "5173", "\n".join(lines))
    check_not_in("K3: ... nor the key that is declared (JIRA_URL, an integration key) as a candidate", "JIRA_URL", hint)
    check_not_in("K3: the address of the API key is no candidate (it is the base_url)", "TESTPROJECT1_API_DOMAIN", hint)
    wired = probe_details(root, config(root, frontend_url=None, block={"url_key": "FRONTEND_URL"}))
    check("K3 control: with the block wired there is no hint", not [x for x in wired if "frontend:" in x], str(wired))
    named = probe_details(root, config(root), "local-docker")
    check("K3 control: --env on the entry that names its own frontend: no hint", not [x for x in named if "frontend:" in x],
          str(named))
    write_env(root, "TESTPROJECT1_API_DOMAIN=http://localhost:8080\nFRONTEND_TOKEN_URL=http://localhost:5173\n"
                    "FRONTEND_URL=ftp://x\n")
    check("K3: a secret-looking name is never named, a non-http value is no candidate",
          not [x for x in probe_details(root, bare) if "frontend:" in x])


def k4_edges(root):
    write_env(root, "TESTPROJECT1_API_DOMAIN=http://localhost:8080\nFRONTEND_URL=http://localhost:5173\n")
    both = config(root, frontend={"url": "http://localhost:5174"})
    got = env_probe.frontend_of(both, "local-docker")
    check_eq("K4: frontend.url and a DIFFERENT flat field: frontend.url wins", got["url"], "http://localhost:5174")
    check("K4: ... and it says they differ (names, no value)", any("different frontend_url" in n for n in got["notes"]),
          str(got))
    check_in("K4: ... only the used host is on the list: the flat field's host is refused", "Allowed hosts:",
             refusal(UI, both))
    check_eq("K4: ... the used host is allowed", MC.environment_of("http://localhost:5174/x", both)["name"], "local-docker")
    same = config(root, frontend={"url": "http://localhost:5173"})
    check_eq("K4: equal spellings - no note", env_probe.frontend_of(same, "local-docker")["notes"], [])
    alias = env_probe.frontend_of(config(root), "local-docker")
    check_eq("K4: the alias source is named", alias["source"], "environments[0].frontend_url (alias)")
    # the block must not override an entry's own address, whatever it says
    own = config(root, frontend={"url": "http://localhost:5174"}, block={"url_key": "FRONTEND_URL"})
    own["environments"][0].pop("frontend_url")
    check_eq("K4: the block never overrides the entry's own address", env_probe.frontend_of(own, "local-docker")["url"],
             "http://localhost:5174")
    spoke = config(root, frontend="x", block={"url_key": "FRONTEND_URL"})
    spoke["environments"][0].pop("frontend_url")
    got = env_probe.frontend_of(spoke, "local-docker")
    check_eq("K4: an entry that spoke and said nothing readable is not given the block's address", got["url"], "")
    check("K4: ... a note says the frontend block is unreadable (E-F18)", any("unreadable" in n for n in got["notes"]), str(got))
    # the two worlds of `environment.frontend`
    for label, block in (("absent", None), ("empty", {})):
        cfg = config(root, frontend_url=None)
        if block is not None:
            cfg["environment"]["frontend"] = block
        got = env_probe.frontend_of(cfg, "local-docker")
        check_eq(f"K4: {label} environment.frontend: '' and no failure", (got["url"], got["source"]), ("", ""))
    check_eq("K4: environment.frontend as a string is '' with a note (E-F18)",
             env_probe.frontend_of(config(root, frontend_url=None, block="FRONTEND_URL"), "")["url"], "")
    # an env file that cannot be read
    missing = config(root, frontend_url=None, block={"url_key": "FRONTEND_URL"})
    missing["environment"]["env_file"] = "testproject1_test_harness/nope.env"
    got = env_probe.frontend_of(missing, "local-docker")
    check_eq("K4: an env file that is not there: '' (not a pass)", got["url"], "")
    check("K4: ... and a note names the file's role", any("env file" in n for n in got["notes"]), str(got))
    err = refusal(UI, missing)
    check_in("K4 (AR-28): ... the host refusal carries that note", "the env file named in environment.env_file", err)
    folder = config(root, frontend_url=None, block={"url_key": "FRONTEND_URL"})
    folder["environment"]["env_file"] = "testproject1_test_harness"
    check_eq("K4: an env file that is a folder: '' and no exception", env_probe.frontend_of(folder, "")["url"], "")
    # `export KEY=value` is not understood by parse_env_file: the known behaviour, pinned
    write_env(root, "export FRONTEND_URL=http://localhost:5173\n")
    got = env_probe.frontend_of(config(root, frontend_url=None, block={"url_key": "FRONTEND_URL"}), "local-docker")
    check_eq("K4 (known): `export FRONTEND_URL=...` is not read by the block", got["url"], "")
    check("K4: ... the note says the key is not set", any("FRONTEND_URL is not set" in n for n in got["notes"]), str(got))
    write_env(root, "FRONTEND_URL=http://localhost:5173\n")
    # odd addresses: the direction of an error is "the host is not allowed"
    for bad in ("javascript:alert(1)", "http://", "http://user:pw@localhost:5173/", "'http://localhost:5173'",
                "localhost:5173", "ftp://localhost:5173/"):
        cfg = config(root, frontend_url=bad)
        check_in(f"K4: flat {bad!r} allows no host", "Allowed hosts: http://localhost:8080.", refusal(UI, cfg))
    for odd in ({"url": ["http://localhost:5173"]}, ["http://localhost:5173"], 5, None):
        cfg = config(root, frontend_url=None, frontend=odd)
        check_in(f"K4: frontend={odd!r} allows no host", "Allowed hosts:", refusal(UI, cfg))
    named = env_probe.frontend_of(config(root), "no-such-stand")
    check_eq("K4: --env on a name no entry carries: '' (the block is not borrowed)", named["url"], "")
    # a steps file with no goto is refused before any attempt (the refusal is parse_steps')
    task = root / "qa-factory" / "artifacts" / "TP1-1"
    task.mkdir(parents=True)
    steps = task / "steps.txt"
    steps.write_text("capture pre_action initial\n", encoding="utf-8")
    code, _out, err = S.run(["ui", "--task-root", str(task), "--case", "TP1-1_TC_001", "--steps-file", str(steps)])
    check_eq("K4: a steps file with no goto is refused (exit 2)", code, 2)
    check_in("K4: ... and it says the first goto names the stand", "needs a `goto <url>` step", err)


def k5_hint_limit(root):
    bare = config(root, frontend_url=None)
    for count, tail in ((5, False), (6, True)):
        lines = ["TESTPROJECT1_API_DOMAIN=http://localhost:8080"] + [f"UI_{i}_URL=http://h{i}.example.test" for i in range(count)]
        write_env(root, "\n".join(lines) + "\n")
        hint = " ".join(x for x in probe_details(root, bare) if "frontend:" in x)
        names = [f"UI_{i}_URL" for i in range(count)]
        check_eq(f"K5: {count} candidates - the first five are named", all(n in hint for n in names[:5]), True)
        check_eq(f"K5: {count} candidates - the sixth is {'counted, not named' if tail else 'absent'}",
                 ("(+1 more)" in hint, "UI_5_URL" in hint), (tail, False))
        check_not_in(f"K5: {count} candidates - no value", "example.test", hint)
    write_env(root, "FRONTEND_URL=http://localhost:5173\n")


def k9_doors(root):
    """S1: the door names `url_key` only where it can apply (AT one entry, BEYOND two)."""
    write_env(root, "TESTPROJECT1_API_DOMAIN=http://localhost:8080\nFRONTEND_URL=http://localhost:5173\n")
    second = {"name": "preview", "base_url": "https://preview.example.test"}
    wired = config(root, frontend_url=None, block={"url_key": "FRONTEND_URL"})
    two = dict(wired, environments=[wired["environments"][0], second])
    err = refusal(UI, two)
    check_in("K9 BEYOND: two entries and a configured url_key - the refusal says the key serves one entry only",
             "environment.frontend.url_key serves only a single-entry environments[]", err)
    check_in("K9 BEYOND: ... and names the entry's own field", "environments[<name>].frontend.url", err)
    check_not_in("K9 BEYOND: ... and does not say the key is unset", "(environment.frontend.url_key or", err)
    check_in("K9 AT: one entry, no frontend - the refusal names the block's key (unchanged)",
             "(environment.frontend.url_key or environments[].frontend.url)", refusal(UI, config(root, frontend_url=None)))
    check("K9 BEYOND: a key that is already wired is never proposed again (no hint line)",
          not [x for x in probe_details(root, two, "local-docker") if "frontend:" in x])
    unwired = dict(config(root, frontend_url=None), environments=[wired["environments"][0], second])
    line = " ".join(x for x in probe_details(root, unwired, "local-docker") if "frontend:" in x)
    check_in("K9 BEYOND: two entries and no url_key - the hint names the entry's field", "set environments[<name>].frontend.url", line)
    check_not_in("K9 BEYOND: ... never the block's key", "set environment.frontend.url_key", line)
    got = env_probe.frontend_of(dict(wired, environments=[wired["environments"][0]]), "local-docker")
    check_eq("K9: the block's answer carries the key name and the api path", (got["key"], got["api_path"]),
             ("FRONTEND_URL", wired["environment"]["frontend"].get("api_path", "")))


def k10_2_http_address_keys():
    """HF8-10 K-10.2: the enumeration the hint and the onboarding discovery share. The hint itself is K3/K5/K9 above, unchanged."""
    values = {"FRONTEND_URL": "http://localhost:5173", "JIRA_URL": "https://jira.example.test", "API_URL": "http://localhost:8080/",
              "SECRET_URL": "http://x.test", "AUTH_URL": "http://y.test", "OTHER": "ftp://x", "EMPTY": "", "": "http://z.test",
              "UPPER_URL": "HTTPS://w.test"}
    check_eq("K-10.2 the names holding an http(s) address, in file order; a secret-looking name, a non-http value, an empty one and an "
             "empty name are no candidate", env_probe.http_address_keys(values, set(), ""),
             ["FRONTEND_URL", "JIRA_URL", "API_URL", "UPPER_URL"])
    check_eq("K-10.2 `exclude` drops a name", env_probe.http_address_keys(values, {"JIRA_URL", "API_URL"}, ""), ["FRONTEND_URL", "UPPER_URL"])
    check_eq("K-10.2 a value equal to `base` (a trailing slash cut on the value) is the API's own address, no candidate",
             env_probe.http_address_keys(values, set(), "http://localhost:8080"), ["FRONTEND_URL", "JIRA_URL", "UPPER_URL"])
    check_eq("K-10.2 nothing in, nothing out", (env_probe.http_address_keys({}, set()), env_probe.http_address_keys(None, set())), ([], []))
    check_not_in("K-10.2 no value in what it returns", "localhost", json.dumps(env_probe.http_address_keys(values, set(), "")))


def rn3_cfg(root, *, profile=("web",), kind="harness_command", outcome="ok", url_key="", two=False, probe_record=True):
    """RN1-3 fixture (MyBooks shape): UI and API on one address, a passed harness UI login, a browser profile, url_key empty."""
    access = {"kind": kind, "command": "npx playwright test tests/e2e/auth/login.spec.ts", "user_key": "E2E_USER"}
    if probe_record:
        access["login_probe"] = {"user_key": "E2E_USER", "checked_at": "2026-10-31T10:00:00"}
        if outcome is not None:
            access["login_probe"]["outcome"] = outcome
    cfg = {"environments": [{"name": "local", "base_url": "http://localhost:3000"}],
           "environment": {"env_file": "env.local", "base_url_key": "BASE_URL", "user_key": "E2E_USER", "access": access,
                           "frontend": {"url_key": url_key, "api_path": ""}},
           "profiles": [{"profile_id": "e2e", "capabilities": list(profile)}]}
    if two:
        cfg["environments"].append({"name": "preview", "base_url": "https://preview.example.test"})
    return cfg


def rn3_env(root, text="BASE_URL=http://localhost:3000\nAPI_URL=http://localhost:3000/api\nE2E_USER=u\n"):
    (root / "env.local").write_text(text, encoding="utf-8")


def k_rn3_reader():
    """RN1-3 K-RN3-R1..R12: the UI address derived from a passed harness UI login; every guard errs toward ''."""
    import surfaces
    root = harness.temp_dir("rn3-reader-")
    try:
        rn3_env(root)
        got = env_probe.frontend_of(rn3_cfg(root), "local", root=root)
        check_eq("K-RN3-R1: MyBooks shape - the stand's own address is the UI, labelled with its source",
                 (got["url"], got["source"], got["same_origin"], got["api_path"]),
                 ("http://localhost:3000", "base_url (ui login probe)", True, ""))
        blockwise = env_probe.frontend_of(rn3_cfg(root), "", root=root)
        check_eq("K-RN3-R1: ... with no name asked for the address comes from the env file's base key",
                 (blockwise["url"], blockwise["key"], blockwise["same_origin"]), ("http://localhost:3000", "BASE_URL", True))
        check_eq("K-RN3-R1: ... every return has the same shape (`same_origin` False elsewhere)",
                 env_probe.frontend_of({}, "")["same_origin"], False)
        check_eq("K-RN3-R2: no profile driven by a browser (an API-only stand) - nothing derived (E1)",
                 env_probe.frontend_of(rn3_cfg(root, profile=("api",)), "local", root=root)["url"], "")
        for label, outcome in (("failed", "failed"), ("skipped", "skipped"), ("not_recorded", "not_recorded"), ("OK", "OK"),
                               ("absent", None)):
            check_eq(f"K-RN3-R3: login outcome {label} is no proof - nothing derived (E2)",
                     env_probe.frontend_of(rn3_cfg(root, outcome=outcome), "local", root=root)["url"], "")
        string_probe = rn3_cfg(root)
        string_probe["environment"]["access"]["login_probe"] = "ok"
        check_eq("K-RN3-R3: a login_probe that is a string - nothing derived",
                 env_probe.frontend_of(string_probe, "local", root=root)["url"], "")
        check_eq("K-RN3-R3 control: no record at all - nothing derived",
                 env_probe.frontend_of(rn3_cfg(root, probe_record=False), "local", root=root)["url"], "")
        check_eq("K-RN3-R4: an HTTP login that passed proves the API, not a UI (E12)",
                 env_probe.frontend_of(rn3_cfg(root, kind="local_login"), "local", root=root)["url"], "")
        unreadable = env_probe.frontend_of(rn3_cfg(root, url_key="FRONTEND_URL"), "local", root=root)
        check_eq("K-RN3-R5: a url_key that is configured but whose key is not in the env file - nothing derived (E8)",
                 unreadable["url"], "")
        check("K-RN3-R5: ... and the existing note says the key is not set", any("FRONTEND_URL is not set" in n for n in unreadable["notes"]),
              str(unreadable))
        check_eq("K-RN3-R6: a stand among two is never qualified by the block's proof (E7)",
                 env_probe.frontend_of(rn3_cfg(root, two=True), "local", root=root)["url"], "")
        # R7: another origin could be the real UI; a same-origin key does not block
        rn3_env(root, "BASE_URL=http://localhost:3000\nAPI_URL=http://localhost:3000/api\nFRONTEND_URL=http://localhost:5173\nE2E_USER=u\n")
        check_eq("K-RN3-R7: an undeclared http key on ANOTHER origin - nothing derived (E10)",
                 env_probe.frontend_of(rn3_cfg(root), "local", root=root)["url"], "")
        real = env_probe._fetch

        def refused(url, timeout):
            raise urllib.error.URLError(ConnectionRefusedError())
        env_probe._fetch = refused
        try:
            lines = env_probe.probe(rn3_cfg(root), "local", root=root, do_login=False)["details"]
        finally:
            env_probe._fetch = real
        check("K-RN3-R7: ... and the probe's hint still names FRONTEND_URL",
              any(x.lstrip().startswith("frontend:") and "FRONTEND_URL" in x for x in lines), str(lines))
        rn3_env(root, "BASE_URL=http://localhost:3000\nAPI_URL=http://localhost:3000/api\nFRONTEND_URL=http://localhost:3000/app\nE2E_USER=u\n")
        check_eq("K-RN3-R7: a key on the SAME origin does not block", env_probe.frontend_of(rn3_cfg(root), "local", root=root)["url"],
                 "http://localhost:3000")
        rn3_env(root)
        # R8: a broken table of surfaces
        broken = root / "broken-surfaces.json"
        broken.write_text("{}", encoding="utf-8")
        was = surfaces.TABLE_PATH
        surfaces.TABLE_PATH = broken
        try:
            got = env_probe.frontend_of(rn3_cfg(root), "local", root=root)
        finally:
            surfaces.TABLE_PATH = was
        check_eq("K-RN3-R8: the table of test surfaces is broken - nothing derived (AR-28)", got["url"], "")
        check("K-RN3-R8: ... and a note says so", any("table of test surfaces could not be read" in n for n in got["notes"]), str(got))
        # R9: the recorded address wins
        explicit = env_probe.frontend_of(rn3_cfg(root, url_key="BASE_URL"), "local", root=root)
        check_eq("K-RN3-R9: an explicit url_key = base key is the recorded fact, not a derivation (E13)",
                 (explicit["url"], explicit["source"], explicit["same_origin"]),
                 ("http://localhost:3000", "environment.frontend.url_key", False))
        # R10: the stand_identity call shape - an entry and no config
        check_eq("K-RN3-R10: an entry with no config around it - nothing derived",
                 env_probe.frontend_of({}, "", entry={"name": "local", "base_url": "http://localhost:3000"})["url"], "")
        # R11: the env file is named and missing
        (root / "env.local").unlink()
        gone = env_probe.frontend_of(rn3_cfg(root), "local", root=root)
        check_eq("K-RN3-R11: the env file is named but missing - nothing derived, no exception", gone["url"], "")
        cfg11 = rn3_cfg(root)
        gone2 = env_probe.frontend_of(cfg11, "local", {}, entry=cfg11["environments"][0], root=root)
        check_eq("K-RN3-R11: ... also in the brief_pack shape (values={} passed, entry given) - an unread file is no pass (m-1)",
                 gone2["url"], "")
        check("K-RN3-R11: ... and a note says the env file cannot be read, with no value",
              any("cannot be read" in n for n in gone2["notes"]) and not any("localhost" in n for n in gone2["notes"]), str(gone2))
        rn3_env(root)
        # R13: an entry with both addresses derives from base_url, never the API path (m-2)
        both = rn3_cfg(root)
        both["environments"][0] = {"name": "local", "api_url": "http://localhost:3000/api", "base_url": "http://localhost:3000"}
        check_eq("K-RN3-R13: an entry with api_url and base_url - the UI is base_url, not the API path",
                 env_probe.frontend_of(both, "local", root=root)["url"], "http://localhost:3000")
        only_api = rn3_cfg(root)
        only_api["environments"][0] = {"name": "local", "api_url": "http://localhost:3000/api/v1"}
        check_eq("K-RN3-R13: an entry with only api_url - the origin root, never the API path",
                 env_probe.frontend_of(only_api, "local", root=root)["url"], "http://localhost:3000")
        # R14: a block by guard 7 names the KEYS, never a value (m-3)
        rn3_env(root, "BASE_URL=http://localhost:3000\nFRONTEND_URL=http://other.test:5173\nE2E_USER=u\n")
        listed = rn3_cfg(root)
        listed["environment"]["extra_keys"] = ["FRONTEND_URL"]
        blocked = env_probe.frontend_of(listed, "local", root=root)
        check_eq("K-RN3-R14: an other-origin key listed in extra_keys blocks the derivation", blocked["url"], "")
        check("K-RN3-R14: ... and the note names the key, not its value",
              any("FRONTEND_URL" in n for n in blocked["notes"]) and not any("other.test" in n for n in blocked["notes"]), str(blocked))
        noenv = rn3_cfg(root)
        del noenv["environment"]["env_file"]
        blocked2 = env_probe.frontend_of(noenv, "local", {"BASE_URL": "http://localhost:3000", "PROXY_URL": "http://proxy.test:8080"},
                                         entry=noenv["environments"][0], root=root)
        check_eq("K-RN3-R14: no env_file, a process-level other-origin http key blocks", blocked2["url"], "")
        check("K-RN3-R14: ... and the note names the key, not its value",
              any("PROXY_URL" in n for n in blocked2["notes"]) and not any("proxy.test" in n for n in blocked2["notes"]), str(blocked2))
        rn3_env(root)
        # R12: the probe says it, and prints no value
        env_probe._fetch = refused
        try:
            lines = env_probe.probe(rn3_cfg(root), "local", root=root, do_login=False)["details"]
        finally:
            env_probe._fetch = real
        text = "\n".join(lines)
        check_not_in("K-RN3-R12: ... the line does not repeat 'the stand's own address' (m-4)", "address - the stand's own address", text)
        check_in("K-RN3-R12: the probe's details say UI and API are on one address", "UI and API on one address", text)
        check_not_in("K-RN3-R12: ... and print no value of the API key", "localhost:3000/api", text)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def k7_one_reader():
    sources = {p.name: p.read_text(encoding="utf-8") for p in harness.SCRIPTS.glob("*.py")}
    check("K7 control: the same-shape search finds the quoted base_url in manual_capture.py", '"base_url"' in sources["manual_capture.py"])
    for name in ("def _read_frontend", "def _frontend_address"):
        check_eq(f"K7: no `{name}` in scripts/", [n for n, t in sources.items() if name in t], [])
    check_eq('K7: the flat field\'s name, quoted, lives only in env_probe.py and stand_identity.py',
             sorted(n for n, t in sources.items() if '"frontend_url"' in t), ["env_probe.py", "stand_identity.py"])
    check("K7: the survivor is in env_probe and stand_health calls it",
          "def frontend_of" in sources["env_probe.py"] and "env_probe.frontend_of" in sources["stand_health.py"])
    check_eq("K7: manual_capture and stand_identity read the address through frontend_of",
             ["frontend_of" in sources["manual_capture.py"], "frontend_of" in sources["stand_identity.py"]], [True, True])


def k8_definition_sha():
    entry = {"name": "localhost", "base_url": "http://localhost:8080", "frontend_url": " http://localhost:5173 "}
    old = hashlib.sha256(json.dumps({"base_url": "http://localhost:8080", "frontend_url": "http://localhost:5173"},
                                    sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    check_eq("K8: a flat-field entry hashes as before (the old payload, byte for byte)", SI.definition_sha(entry), old)
    blocky = {"name": "localhost", "base_url": "http://localhost:8080"}
    check_eq("K8: a block (the config's) never reaches the hash: no frontend = the empty definition",
             SI.definition_sha(blocky), SI.definition_sha(dict(blocky, frontend_url="")))
    check("K8: frontend.url counts as the entry's own frontend",
          SI.definition_sha(dict(blocky, frontend={"url": "http://localhost:5173"})) == old)


def main():
    root = project()
    try:
        k1_join(root)
        k2_block(root)
        k3_hint(root)
        k4_edges(root)
        k5_hint_limit(root)
        k9_doors(root)
    finally:
        shutil.rmtree(root.parent, ignore_errors=True)
    k10_2_http_address_keys()
    k_rn3_reader()
    k7_one_reader()
    k8_definition_sha()
    finish("test_frontend_reader")


if __name__ == "__main__":
    main()
