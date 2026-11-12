"""FB-3 / FB-5 (TP1-14857): the stand login probe learns the body field pair the endpoint accepts.

`POST /v1/local-auth/login` with `username` answered 422 asking for `email`; the factory read it as "environment
missing (HTTP 422)" and a person edited `environment.access.user_field` by hand. These checks drive the real
`stand_access._local_login` (the transport `_open` replaced by a fake that answers BY THE FIELD NAMES of the body
and records every request), the real `manual_capture._http_login` (a fake client), `env_probe.probe` in-process and
the readiness class. One named check per acceptance key of the spec (K-C*, K-L*, K-S*, K-F1, K-E1, K-R*, K-H1, K-M*,
K-D1, K-B*).
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import config_contract as CC  # noqa: E402
import env_probe  # noqa: E402
import manual_capture as MC  # noqa: E402
import readiness  # noqa: E402
import stand_access as SA  # noqa: E402
import stand_health  # noqa: E402

PW = "not-a-real-value"
USER = "admin@example.invalid"
BASE = "http://stand.example:8080"
VALUES = {"AUTH_USERNAME": USER, "AUTH_PASSWORD": PW}
ACCESS = {"kind": "local_login", "url": "/v1/local-auth/login", "user_key": "AUTH_USERNAME", "secret_key": "AUTH_PASSWORD"}
TOKEN_BODY = json.dumps({"access_token": "jwt-value"})
PACKAGE = SCRIPTS.parent
RECEIPTS: list = []   # every receipt a check made: K-S8 reads them all


def complaint(*names, shape="detail") -> str:
    if shape == "detail":
        return json.dumps({"detail": [{"type": "missing", "loc": ["body", n], "msg": "Field required"} for n in names]})
    return json.dumps({"errors": {n: ["x"] for n in names}})


def testproject1(sent: dict) -> tuple:
    """The measured Test Project 1 shape: `email` is required, `username` is not a field."""
    return (200, TOKEN_BODY) if "email" in sent else (422, complaint("email"))


def login(handler, access=None, values=None) -> tuple:
    """(receipt, requests): `_local_login` against a fake stand whose answer is handler(sent body) -> (code, text)."""
    asked: list = []
    real = SA._open

    def fake(url, method, data, headers, timeout):
        sent = json.loads(data.decode("utf-8"))
        asked.append(sent)
        answer = handler(sent)
        if isinstance(answer, Exception):
            raise answer
        return answer

    SA._open = fake
    try:
        receipt = SA.login(dict(ACCESS, **(access or {})), VALUES if values is None else values, BASE)
    finally:
        SA._open = real
    RECEIPTS.append(receipt)
    return receipt, asked


def row_file(payload) -> Path:
    path = Path(tempfile.mkdtemp(prefix="qa-factory-pairs-")) / "pairs.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


def with_row(payload, fn):
    real = CC.LOGIN_BODY_FIELDS_PATH
    CC.LOGIN_BODY_FIELDS_PATH = row_file(payload) if payload is not None else real.with_name("no-such-row.json")
    try:
        return fn()
    finally:
        CC.LOGIN_BODY_FIELDS_PATH = real


def the_data_row() -> None:
    shipped = [("username", "password"), ("email", "password")]
    check_eq("K-C1 candidates_from_the_row", CC.body_field_candidates({}), shipped)
    check_eq("K-C2 recorded: user_field only is one pair", CC.body_field_candidates({"user_field": "email"}),
             [("email", "password")])
    check_eq("K-C2 recorded: secret_field only is one pair", CC.body_field_candidates({"secret_field": "pw"}),
             [("username", "pw")])
    check_eq("K-C2 recorded: both", CC.body_field_candidates({"user_field": "a", "secret_field": "b"}), [("a", "b")])
    check_eq("K-C2 recorded: padded name is stripped (battery)", CC.body_field_candidates({"user_field": "  email  "}),
             [("email", "password")])
    check_eq("K-B config: empty and blank names mean probing", CC.body_field_candidates(
        {"user_field": "", "secret_field": "   "}), shipped)
    fallback = [("username", "password")]
    crooked = {"file absent": None, "not json": "{", "empty object": {}, "pairs empty": {"pairs": []},
               "pairs a string": {"pairs": "x"}, "equal names": {"pairs": [["a", "a"]]},
               "a 3-item pair": {"pairs": [["a", "b", "c"]]}, "a non-string": {"pairs": [[1, "b"]]},
               "a value-shaped name": {"pairs": [["a b", "c"]]}, "not an object": [["a", "b"]]}
    for label, payload in crooked.items():
        check_eq(f"K-C3 crooked_rows_fall_back: {label}", with_row(payload, lambda: CC.body_field_candidates({})), fallback)
    check_eq("K-C3 a duplicate pair is dropped, the valid ones stay in order", with_row(
        {"pairs": [["a", "b"], ["a", "b"], [1, 2], ["c", "d"]]}, lambda: CC.body_field_candidates({})),
        [("a", "b"), ("c", "d")])
    check_eq("K-C3 default_body_fields follows the row's first pair", with_row(
        {"pairs": [["x", "y"]]}, CC.default_body_fields), ("x", "y"))
    for label, junk in (("None", None), ("a string", "x"), ("a list", [])):
        check_eq(f"K-C4 access_not_a_dict: {label} reads the row", CC.body_field_candidates(junk), shipped)
    row = json.loads((PACKAGE / "references" / "login-body-fields.json").read_text(encoding="utf-8"))
    check_eq("K-C5 fallback_equals_first_row_pair: the code constant is the first pair of the shipped row",
             (CC.BODY_FIELD_DEFAULTS["user_field"], CC.BODY_FIELD_DEFAULTS["secret_field"]), tuple(row["pairs"][0]))
    check_eq("K-C5 ... and is what a recorded half-block fills with", CC.default_body_fields(), tuple(row["pairs"][0]))
    # K-C6: one text per constraint
    text = CC._field_name_error("environment.access.login_probe.user_field")
    check_in("K-C6 the text names the constraint", "letters, digits, _ . -; at most 64", text)
    for label, bad in (("a list", ["email"]), ("a spaced name", "a b"), ("a number", 5)):
        errors = CC.access_errors({"kind": "local_login", "url": "/x", "login_probe": {
            "user_key": "AUTH_USERNAME", "status": 200, "checked_at": "2026-10-27", "user_field": bad}})
        check(f"K-C6 login_probe.user_field {label} -> the full _field_name_error text", text in errors, str(errors))
    good = CC.access_errors({"kind": "local_login", "url": "/x", "login_probe": {
        "user_key": "AUTH_USERNAME", "status": 200, "checked_at": "2026-10-27", "user_field": "email",
        "secret_field": ""}})
    check_eq("K-C6 a name or an empty string is legal; absent is legal (E22)", good, [])
    check_eq("K-C6 body_field_errors text is byte-equal to today's",
             CC.body_field_errors({"user_field": ["email"]}),
             ["environment.access.user_field must be a JSON body field NAME (letters, digits, _ . -; at most 64), "
              "not a value or an object"])
    equal = CC.body_field_errors({"user_field": "x", "secret_field": "x"})
    check_in("K-C6 equal names still name the defaults through the row", "an empty one means `username` / `password`",
             equal[0])


def the_loop() -> None:
    def scripted(*answers):
        queue = list(answers)
        calls: list = []

        def send(u, s):
            calls.append((u, s))
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return send, calls

    pairs = [("username", "password"), ("email", "password")]
    send, calls = scripted((422, complaint("email")), (200, TOKEN_BODY))
    got = SA.try_body_pairs(pairs, send, (USER, PW))
    check_eq("K-L1 an unsent name asked for -> the next pair is tried", (len(got), got[-1]["code"]), (2, 200))
    send, calls = scripted((422, complaint("username")), (200, TOKEN_BODY))
    check_eq("K-L1 only a SENT name complained about -> stop", len(SA.try_body_pairs(pairs, send, (USER, PW))), 1)
    send, calls = scripted((422, "{}"), (200, TOKEN_BODY))
    check_eq("K-L1 nothing named -> stop", len(SA.try_body_pairs(pairs, send, (USER, PW))), 1)
    send, calls = scripted(RuntimeError("boom"), (200, TOKEN_BODY))
    got = SA.try_body_pairs(pairs, send, (USER, PW))
    check_eq("K-L1 an exception is no answer: stop, with the error class", (len(got), got[0]["code"], got[0]["error"]),
             (1, None, "RuntimeError"))
    send, calls = scripted((422, complaint("email")), TimeoutError("slow"))
    got = SA.try_body_pairs(pairs, send, (USER, PW))
    check_eq("K-L1 an exception after a shape refusal stops there", (len(got), got[-1]["error"]), (2, "TimeoutError"))
    check_eq("K-L1 shape_refused: case-insensitive sent compare (E27)", SA.shape_refused(
        422, complaint("Email"), (USER, PW), ("email", "password")), False)
    check_eq("K-L1 shape_refused: a 401 naming an unsent field is not a shape refusal", SA.shape_refused(
        401, complaint("email"), (USER, PW), ("username", "password")), False)
    check_eq("K-L1 shape_refused: None code", SA.shape_refused(None, complaint("email"), (), ("username",)), False)

    marker = "MARKER-ctx-7731"
    body = json.dumps({"detail": [{"loc": ["body", "email"], "msg": "Field required", "ctx": marker}]})
    receipt, asked = login(lambda sent: (422, body))
    printed = json.dumps(receipt)
    check_not_in("K-L2 the answer's text never enters the receipt (values)", marker, printed)
    check("K-L2 ... nor a `text` key anywhere in it", "text" not in receipt and all("text" not in t for t in receipt["tried"]),
          printed)

    calls_seen: list = []
    real_loop = SA.try_body_pairs

    def recorder(candidates, send, secrets=()):
        calls_seen.append("loop")
        return real_loop(candidates, send, secrets)

    SA.try_body_pairs = recorder
    try:
        login(testproject1)
        check_eq("K-L3 _local_login goes through stand_access.try_body_pairs", calls_seen, ["loop"])
        manual(testproject1_http)
        check_eq("K-L3 ... and so does manual_capture._http_login", calls_seen, ["loop", "loop"])
    finally:
        SA.try_body_pairs = real_loop


def the_stand_login() -> None:
    receipt, asked = login(testproject1)
    check_eq("K-S1 second pair after a 422 is accepted (Test Project 1): ok, 2 requests",
             (receipt["status"], len(asked)), ("ok", 2))
    check_eq("K-S1 ... accepted_fields", receipt.get("accepted_fields"), {"user_field": "email", "secret_field": "password"})
    check_eq("K-S1 ... fields_recorded is False", receipt["fields_recorded"], False)
    check_in("K-S1 ... the why says they are not recorded", "not recorded in environment.access", receipt["why"])
    check_eq("K-S1 ... tried carries both codes", [(t["user_field"], t["code"]) for t in receipt["tried"]],
             [("username", 422), ("email", 200)])
    check_eq("K-S1 ... the bodies sent", asked, [{"username": USER, "password": PW}, {"email": USER, "password": PW}])
    check("K-S1 ... no refusal on a login that got in", "refusal" not in receipt and "fix" not in receipt)

    receipt, asked = login(testproject1, {"user_field": "email"})
    check_eq("K-S2 recorded_field_sends_one_request", (receipt["status"], len(asked), receipt["fields_recorded"]),
             ("ok", 1, True))
    check_not_in("K-S2 ... and no 'not recorded' sentence", "not recorded", receipt["why"])
    receipt, asked = login(lambda sent: (200, TOKEN_BODY), {"secret_field": "pw"})
    check_eq("K-S2 (E4) a half block is still a record: one request, the empty one from the default", asked,
             [{"username": USER, "pw": PW}])

    receipt, asked = login(lambda sent: (422, complaint("login")))
    check_eq("K-S3 every_pair_refused_is_body_shape", (receipt["status"], receipt["code"], len(asked)), ("failed", 422, 2))
    check_eq("K-S3 ... refusal and fix", (receipt["refusal"], receipt["fix"]), ("body_shape", SA.LOGIN_FIELD_FIX))
    check_eq("K-S3 ... complained", receipt["complained"], ["login"])
    check_eq("K-S3 ... tried with codes", [t["code"] for t in receipt["tried"]], [422, 422])
    check_in("K-S3 ... today's door on the last attempt", "access.user_field", receipt["why"])
    check_in("K-S3 ... prefixed by the first attempt", "tried the body fields `username` / `password` (HTTP 422); then",
             receipt["why"])
    receipt, asked = login(testproject1, {"user_field": "login"})
    check_eq("K-S3 (E5b) a wrong recorded name is a name problem: one request, body_shape",
             (len(asked), receipt.get("refusal")), (1, "body_shape"))

    for code in (401, 403, 429, 500, 503):
        receipt, asked = login(lambda sent, c=code: (c, complaint("email")))
        check_eq(f"K-S4 no_advance after HTTP {code}: one request, no refusal", (len(asked), "refusal" in receipt), (1, False))
    receipt, asked = login(lambda sent: (200, "{}"))
    check_eq("K-S4 (E10) 2xx without a token: stop", (len(asked), receipt["status"]), (1, "failed"))
    receipt, asked = login(lambda sent: TimeoutError("slow"))
    check_eq("K-S4 (E11) no answer: stop, failed NO ANSWER, no refusal", (len(asked), "NO ANSWER" in receipt["why"],
             "refusal" in receipt), (1, True, False))
    state = {"n": 0}

    def silent_second(sent):
        state["n"] += 1
        return (422, complaint("email")) if state["n"] == 1 else TimeoutError("slow")
    receipt, asked = login(silent_second)
    check_eq("K-S4 (E11) no answer on the second pair after a refusal: failed, no refusal",
             (len(asked), receipt["status"], "refusal" in receipt, "NO ANSWER" in receipt["why"]), (2, "failed", False, True))

    state = {"n": 0}

    def then_401(sent):
        state["n"] += 1
        return (422, complaint("email")) if state["n"] == 1 else (401, "")
    receipt, asked = login(then_401)
    check_eq("K-S5 unsent_then_401_records_nothing", (receipt["code"], len(receipt["tried"]), "accepted_fields" in receipt,
             "refusal" in receipt), (401, 2, False, False))

    judged = {
        "Laravel wrong password (E8b)": (lambda sent: (422, complaint("email", shape="errors")), {"user_field": "email"}),
        "Laravel throttle (E8b)": (lambda sent: (422, json.dumps({"errors": {"email": ["Too many login attempts."]}})),
                                   {"user_field": "email"}),
        "400 errors.password (E8b)": (lambda sent: (400, complaint("password", shape="errors")), {"user_field": "email"}),
        "case game Email after email (E27)": (lambda sent: (422, complaint("Email", shape="errors")), {"user_field": "email"}),
    }
    for label, (handler, access) in judged.items():
        receipt, asked = login(handler, access)
        check_eq(f"K-S6 {label}: one request, no refusal, the name is listed", (len(asked), "refusal" in receipt,
                 bool(receipt["complained"])), (1, False, True))
        check_in(f"K-S6 {label}: today's failed HTTP why", "-> HTTP", receipt["why"])
    state = {"n": 0}

    def laravel(sent):
        state["n"] += 1
        return (422, complaint("email", shape="errors"))
    receipt, asked = login(laravel)
    check_eq("K-S6 (E8c) Laravel probing: 2 requests, today's receipt of the second, no refusal",
             (len(asked), receipt["code"], "refusal" in receipt), (2, 422, False))
    receipt, asked = login(lambda sent: (422, json.dumps({"errors": {"email": ["required"]}})) if "username" in sent
                           else (200, TOKEN_BODY))
    check_eq("K-S6 {errors:{email:[required]}} after username advances", (len(asked), receipt["status"]), (2, "ok"))
    unknowns = {"invalid_grant": json.dumps({"error": "invalid_grant", "error_description": "Invalid user credentials"}),
                "detail string": json.dumps({"detail": "Invalid credentials"}),
                "loc body only": json.dumps({"detail": [{"loc": ["body"]}]}),
                "value-shaped key": json.dumps({"errors": {"admin@example.invalid": ["x"]}}),
                "list": "[]", "html": "<html>422</html>", "empty": "", "broken": "{", "null": "null",
                "256 KB junk": "x" * 262144}
    for code in (400, 422):
        quiet = True
        for label, text in unknowns.items():
            receipt, asked = login(lambda sent, t=text, c=code: (c, t))
            if (len(asked), "refusal" in receipt) != (1, False):
                quiet = False
                check(f"K-S6 {label} HTTP {code}: one request, no refusal", False, str((len(asked), receipt.get("refusal"))))
        check(f"K-S6 {len(unknowns)} unknown answers with HTTP {code}: one request each, no refusal", quiet)

    def rows(payload, handler):
        return with_row(payload, lambda: login(handler))
    receipt, asked = rows({"pairs": [["a", "b"]]}, lambda sent: (422, complaint("zzz")))
    check_eq("K-S7 a row of 1 pair -> 1 request (AT)", len(asked), 1)
    receipt, asked = rows({"pairs": [["a", "b"], ["c", "d"], ["e", "f"]]}, lambda sent: (422, complaint("zzz")))
    check_eq("K-S7 a row of 3 pairs -> 3 requests (BEYOND the shipped 2)", len(asked), 3)
    check_eq("K-S7 ... and the refusal stands", receipt.get("refusal"), "body_shape")
    receipt, asked = rows({"pairs": []}, lambda sent: (422, complaint("zzz")))
    check_eq("K-S7 no valid pair -> the fallback pair, never no request", asked, [{"username": USER, "password": PW}])

    for r in RECEIPTS:
        printed = json.dumps(r)
        if PW in printed or USER in printed:
            check("K-S8 no_credential_in_any_key", False, printed[:300])
            break
    else:
        check(f"K-S8 no_credential_in_any_key (over {len(RECEIPTS)} receipts)", True)

    real = SA._open
    SA._open = lambda url, method, data, headers, timeout: (401, "")
    try:
        o = SA.login({"kind": "oidc_password", "url": "https://idp.example.invalid/t", "user_key": "AUTH_USERNAME",
                      "secret_key": "AUTH_PASSWORD"}, VALUES)
        b = SA.login({"kind": "bearer_env", "token_key": "API_TOKEN"}, {"API_TOKEN": "t"}, BASE)
    finally:
        SA._open = real
    check_eq("K-S9 other_kinds_unchanged: oidc and bearer keep the four keys",
             (sorted(o), sorted(b)), (["code", "status", "user_key", "why"],) * 2)
    check_eq("K-S9 ... local_login that sent nothing keeps them too", sorted(SA.login(dict(ACCESS), {}, BASE)),
             ["code", "status", "user_key", "why"])


def the_fix_and_the_probe() -> None:
    fix = SA.LOGIN_FIELD_FIX
    fits = lambda s: len(s) <= 155 and s.isascii() and "\n" not in s  # noqa: E731
    check("K-F1 fix_fits_the_160_cut: <= 155, ASCII, one line", fits(fix), f"{len(fix)} chars")
    check("K-F1 negative control: a 156-character string fails the same predicate", not fits("x" * 156))

    root = temp_project("qa-factory-fb3-")
    real_fetch = env_probe._fetch
    real_open = SA._open
    try:
        (root / "tests" / ".env").write_text("STAND=http://stand.example:8080\nAUTH_USERNAME=" + USER
                                             + f"\nAUTH_PASSWORD={PW}\n", encoding="utf-8")
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["environment"] = {"env_file": "tests/.env", "base_url_key": "STAND", "user_key": "AUTH_USERNAME",
                              "secret_keys": ["AUTH_PASSWORD"], "health_path": "/v1/config",
                              "access": {"kind": "local_login", "url": "/" + "a" * 300, "user_key": "AUTH_USERNAME",
                                         "secret_key": "AUTH_PASSWORD"}}
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        env_probe._fetch = lambda url, timeout: 200
        SA._open = lambda url, method, data, headers, timeout: testproject1(json.loads(data.decode("utf-8")))
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result = env_probe.probe(cfg, root=root)
        check_eq("K-S10 probe_writes_nothing: config.json is byte-identical after the probe",
                 hashlib.sha256(path.read_bytes()).hexdigest(), before)
        check_eq("E1/E26 before onboarding writes the pair the login reads ok", result["login"]["status"], "ok")
        check_eq("... and layer1 is empty", result["layer1"], [])

        SA._open = lambda url, method, data, headers, timeout: (422, complaint(*[f"f{i}" + "n" * 60 for i in range(5)]))
        result = env_probe.probe(cfg, root=root)
        item = result["layer1"][0]
        check("K-E1 layer1_item_leads_with_the_fix (300-char URL, 5 x 64-char names)",
              item.startswith(fix + " - ") and len(fix) <= 155, item[:200])
        check_eq("... the login object passes through whole", result["login"]["refusal"], "body_shape")
        note = readiness.login_field_unknown(result)
        check("K-R1 readiness_class_login_field_unknown: missing, factory, gap_id, no cause",
              note["status"] == "missing" and note["owner"] == "factory" and note["gap_id"] == "login-field-unknown"
              and "cause" not in note, str(note)[:200])
        check("K-R1 ... the note starts with the fix and remedy.steps[0] is the fix",
              note["note"].startswith(fix) and note["remedy"]["steps"][0] == fix)
        check_not_in("K-R1 ... 'environment missing' is absent", "environment missing", note["note"])
        check_in("K-R1 ... the whole fix survives the gate_preflight cut at 160", fix, " ".join(note["note"].split())[:160])

        SA._open = lambda url, method, data, headers, timeout: (401, "")
        result = env_probe.probe(cfg, root=root)
        check_eq("K-R2 a 401 is not the class", readiness.login_field_unknown(result), None)
        check_eq("K-R2 ... and its layer1 item is today's", result["layer1"][0].split(":")[0],
                 "the login this project records was refused")
        SA._open = lambda url, method, data, headers, timeout: (422, complaint("email", shape="errors"))
        cfg["environment"]["access"]["user_field"] = "email"
        result = env_probe.probe(cfg, root=root)
        check_eq("K-R2 a 422 naming a sent field (E8b) is not the class either", readiness.login_field_unknown(result), None)
        check_in("K-R2 ... its layer1 item is today's", "the login this project records was refused", result["layer1"][0])
    finally:
        env_probe._fetch = real_fetch
        SA._open = real_open
        cleanup(root)

    # K-R2 through check_environment: today's cap is byte-equal for a result without the class; the class wins with it
    real_run, real_own = readiness.subprocess.run, readiness.config_fails_own_probe

    class Done:
        def __init__(self, payload):
            self.stdout = json.dumps(payload)

    other = {"liveness": {"verdict": "alive"}, "login": {"status": "failed", "why": "w"}, "keys": {"verdict": "ok"},
             "layer1": ["the login this project records was refused: w"]}
    shaped = {"liveness": {"verdict": "alive"}, "login": {"status": "failed", "why": "w", "refusal": "body_shape",
                                                         "fix": fix}, "keys": {"verdict": "ok"},
              "layer1": [fix + " - w", "AUTH_X is not set, and the login needs it"]}
    try:
        readiness.config_fails_own_probe = lambda env, root: None
        env_cfg = {"environment": {"env_file": "tests/.env", "user_key": "AUTH_USERNAME"}}
        readiness.subprocess.run = lambda *a, **k: Done(other)
        got = readiness.check_environment(env_cfg, Path(tempfile.gettempdir()))
        today = readiness.cap(readiness.MISSING, "user", "env_probe: " + readiness.DV.joined(
            [str(i)[:200] for i in other["layer1"]], noun="stand problem", max_chars=None))
        check_eq("K-R2 readiness_other_failures_unchanged: byte-equal to today's expression", got, today)
        readiness.subprocess.run = lambda *a, **k: Done(shaped)
        got = readiness.check_environment(env_cfg, Path(tempfile.gettempdir()))
        check_eq("K-R1 check_environment returns the class", (got["gap_id"], got["owner"]), ("login-field-unknown", "factory"))
        check_in("K-R3 the other layer1 item is kept after the fix", "AUTH_X is not set", got["note"])
    finally:
        readiness.subprocess.run, readiness.config_fails_own_probe = real_run, real_own

    long_item = "x" * 300
    why = "w" * 300
    res = {"login": {"refusal": "body_shape", "fix": fix, "why": why}, "layer1": [long_item, fix + " - " + why]}
    note = readiness.login_field_unknown(res)["note"]
    check("K-R3 readiness_fix_never_cut: the fix is first and whole (E17)", note.startswith(fix + " (env_probe: "), note[:200])
    check_in("K-R3 ... the other item is kept, cut at 200", "x" * 200, note)
    check_not_in("K-R3 ... and not beyond it", "x" * 201, note)
    check_in("K-R3 ... the login why is cut at 200", "w" * 200, note)
    check_not_in("K-R3 ... and not beyond it", "w" * 201, note)
    check_eq("K-R3 no fix in the login object -> None", readiness.login_field_unknown(
        {"login": {"refusal": "body_shape"}, "layer1": ["x"]}), None)


def the_doctor() -> None:
    """RH1-7 N5 (the owner's word 27.10.2026): only `outcome: ok` is "proved"; every record without it is "not confirmed"."""
    recheck = env_probe.stand_answers()["login_recheck"]
    record = {"user_key": "K", "status": 200, "checked_at": "2026-10-27T10:00:00", "outcome": "ok",
              "user_field": "email", "secret_field": "password"}

    def receipt(**changes):
        probe = {k: v for k, v in {**record, **changes}.items() if v is not DROP}
        return stand_health._login_receipt({"environment": {"access": {"login_probe": probe}}})

    DROP = object()
    got = receipt()
    check_eq("K-H1 doctor_sentence_names_the_field", got["sentence"],
             "Login was last proved as K (HTTP 200, body field `email`) on 2026-10-27.")
    check_eq("K-H1 ... the dict carries the names", (got["user_field"], got["secret_field"], got["outcome"]), ("email", "password", "proved"))
    got = receipt(user_field=DROP)
    check_eq("K-H1 (E22, outcome ok) without user_field the sentence has no field clause", got["sentence"],
             "Login was last proved as K (HTTP 200) on 2026-10-27.")
    check("K-H1 ... and no field keys", "user_field" not in got)

    sentences = {}   # K-H11: every non-ok input, collected below
    got = receipt(outcome=DROP)
    sentences["K-H2"] = got["sentence"]
    check_in("K-H2 E-L1: the same record with no outcome is not confirmed, with the HTTP code it carries", "is not confirmed (recorded HTTP 200", got["sentence"])
    check_in("K-H2 ... and the one re-check literal", recheck, got["sentence"])
    check_eq("K-H2 ... outcome unknown, still a record", (got["outcome"], got["recorded"]), ("unknown", True))
    check_in("K-H2 ... dated", "on 2026-10-27", got["sentence"])
    got = receipt(outcome=DROP, status=DROP)
    sentences["K-H2b"] = got["sentence"]
    check_in("K-H2 E-L1: no code recorded is said so", "no code recorded", got["sentence"])
    got = receipt(outcome=DROP, status=422, user_field=DROP, secret_field=DROP)
    sentences["K-H3"] = got["sentence"]
    check_in("K-H3 E-L2: the finding's record (K, 422, no outcome) carries the same re-check literal", recheck, got["sentence"])
    check_in("K-H3 ... and the hint from the recorded code", "access.user_field", got["sentence"])
    check_not_in("K-H3 ... not 'did not succeed': an old record is not confirmed, never derived failed", "did not succeed", got["sentence"])
    check_eq("K-H3 ... outcome unknown", got["outcome"], "unknown")
    got = receipt(status=None, user_field=DROP, secret_field=DROP)
    sentences["K-H4"] = got["sentence"]
    check_eq("K-H4 E-L4: outcome ok with no code (the project's login command)", got["sentence"],
             "Login was last proved as K (the project's login command) on 2026-10-27.")
    check_not_in("K-H4 ... no literal None reaches a person", "None", got["sentence"])
    got = receipt(outcome="failed", status=200, user_field=DROP, secret_field=DROP)
    sentences["K-H5"] = got["sentence"]
    check_in("K-H5 E-L5: failed with HTTP 200 (oidc without a token): did not succeed, the outcome beats the code", "did not succeed (HTTP 200) on 2026-10-27", got["sentence"])
    check_eq("K-H5 ... outcome failed", got["outcome"], "failed")
    got = receipt(outcome="failed", status=401, user_field=DROP, secret_field=DROP)
    sentences["K-H5b"] = got["sentence"]
    check_in("K-H5 Table L: a 401 names the account or its secret and the re-check", "the account or its secret".lower(), got["sentence"].lower())
    got = receipt(outcome="failed", status=503, user_field=DROP, secret_field=DROP)
    sentences["K-H5c"] = got["sentence"]
    check_in("K-H5 Table L: a 5xx names the stand", "stand_health.py", got["sentence"])
    got = receipt(outcome="ok", status=422, user_field=DROP, secret_field=DROP)
    sentences["K-H6"] = got["sentence"]
    check_in("K-H6 E-L6: outcome ok with a 422 contradicts itself", "contradicts itself (outcome ok, HTTP 422)", got["sentence"])
    check_in("K-H6 ... re-check", recheck, got["sentence"])
    for label, status in (("a string", "422"), ("a bool", True), ("a float", 422.0)):
        got = receipt(outcome=DROP, status=status)
        sentences[f"K-H7 {label}"] = got["sentence"]
        check_in(f"K-H7 E-L7 status {label}: read as no code recorded", "no code recorded", got["sentence"])
    for label, word in (("OK", "OK"), ("empty", ""), ("success", "success"), ("null", None)):
        got = receipt(outcome=word)
        sentences[f"K-H8 {label}"] = got["sentence"]
        check_eq(f"K-H8 E-L8 outcome {label!r}: read as absent (not confirmed)", (got["outcome"], recheck in got["sentence"]), ("unknown", True))
    check_eq("K-H9 E-L9 no login_probe: today's sentence, unchanged",
             stand_health._login_receipt({"environment": {"access": {}}})["sentence"],
             "No login has been proved on this stand (environment.access has no login_probe): liveness is all this check can say.")
    check_eq("K-H9 ... an empty record the same", stand_health._login_receipt({"environment": {"access": {"login_probe": {}}}})["recorded"], False)
    check_eq("K-H9 ... and a record with no user_key", stand_health._login_receipt({"environment": {"access": {"login_probe": {"outcome": "ok", "status": 200}}}})["recorded"], False)
    check_eq("K-H9 E-L10 no date: no ' on <date>'", receipt(checked_at="")["sentence"].count(" on "), 0)
    got = receipt(outcome="skipped", status=None, user_field=DROP, secret_field=DROP)
    sentences["K-H10 skipped"] = got["sentence"]
    check_in("K-H10 E-L11 skipped: not tried, the stand did not answer", "was not tried (the stand did not answer)", got["sentence"])
    check_in("K-H10 ... and the stand, not the login, is the remedy", "stand_health.py", got["sentence"])
    got = receipt(outcome="not_recorded", status=None, user_field=DROP, secret_field=DROP)
    sentences["K-H10 not_recorded"] = got["sentence"]
    check_in("K-H10 E-L11 not_recorded: the access scheme is not recorded", "the access scheme is not recorded", got["sentence"])
    check_eq("K-H10 ... outcome not_tried", got["outcome"], "not_tried")
    for label, sentence in sentences.items():
        if label == "K-H4":
            continue   # the one `ok` input of this list (outcome ok, no code): the project's command is the proof
        check_not_in(f"K-H11 {label}: no non-ok sentence says 'proved'", "proved", sentence.lower())


def the_record() -> None:
    """RH1-7 N4: `env_probe` emits the ready `login_probe` object as `login.record`; the role copies it whole. K-W1 .. K-W8."""
    root = temp_project("qa-factory-rh17-")
    real_fetch, real_open, real_login = env_probe._fetch, SA._open, SA.login
    try:
        (root / "tests" / ".env").write_text("STAND=http://stand.example:8080\nAUTH_USERNAME=" + USER
                                             + f"\nAUTH_PASSWORD={PW}\n", encoding="utf-8")
        path = root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        cfg["environment"] = {"env_file": "tests/.env", "base_url_key": "STAND", "user_key": "AUTH_USERNAME",
                              "secret_keys": ["AUTH_PASSWORD"], "health_path": "/v1/config",
                              "access": {"kind": "local_login", "url": "/v1/local-auth/login", "user_key": "AUTH_USERNAME",
                                         "secret_key": "AUTH_PASSWORD"}}
        env_probe._fetch = lambda url, timeout: 200
        SA._open = lambda url, method, data, headers, timeout: testproject1(json.loads(data.decode("utf-8")))
        result = env_probe.probe(cfg, root=root)
        record = result["login"]["record"]
        check_eq("K-W1 an ok login -> record.outcome ok, status 200, the configured key NAME", (record["outcome"], record["status"], record["user_key"]),
                 ("ok", 200, "AUTH_USERNAME"))
        check_eq("K-W1 ... the accepted body fields travel, and checked_at is an ISO date", (record["user_field"], record["secret_field"],
                                                                                              record["checked_at"][:4].isdigit() and "T" in record["checked_at"]),
                 ("email", "password", True))
        check_eq("K-W1 ... and the record passes the contract", CC.access_errors({"kind": "local_login", "url": "/x", "login_probe": record}), [])
        check("K-W5 the fixture password is nowhere in the whole result", PW not in json.dumps(result))
        SA._open = lambda url, method, data, headers, timeout: (422, complaint("zzz"))
        record = env_probe.probe(cfg, root=root)["login"]["record"]
        check_eq("K-W2 a 422 -> outcome failed, status 422", (record["outcome"], record["status"]), ("failed", 422))
        check_eq("K-W2 ... a failed login accepted no field", "user_field" in record, False)

        def down(url, timeout):
            raise OSError("no route")
        env_probe._fetch = down
        record = env_probe.probe(cfg, root=root)["login"]["record"]
        check_eq("K-W3 the stand dead -> outcome skipped, status None, user_key = the CONFIGURED name (not the receipt's empty one)",
                 (record["outcome"], record["status"], record["user_key"]), ("skipped", None, "AUTH_USERNAME"))
        record = env_probe.probe(cfg, root=root, do_login=False)["login"]["record"]
        check_eq("K-W3 --no-login is a skipped record too", (record["outcome"], record["user_key"]), ("skipped", "AUTH_USERNAME"))
        broken = {**cfg, "environment": {**cfg["environment"], "env_file": "tests/missing.env"}}
        record = env_probe.probe(broken, root=root)["login"]["record"]
        check_eq("K-W3 the early fatal return carries the record as well", (record["outcome"], record["user_key"]), ("skipped", "AUTH_USERNAME"))
        env_probe._fetch = lambda url, timeout: 200
        SA.login = lambda *a, **k: {"status": "ok", "code": None, "user_key": "AUTH_USERNAME", "why": "the project's own login command `x` exited 0"}
        record = env_probe.probe(cfg, root=root)["login"]["record"]
        check_eq("K-W4 a harness_command ok has no code: status None, outcome ok", (record["outcome"], record["status"]), ("ok", None))
        SA.login = real_login
        bare = {**cfg, "environment": {"env_file": "tests/.env", "base_url_key": "STAND", "health_path": "/v1/config"}}
        check_eq("K-W6 no configured login key -> no record", "record" in env_probe.probe(bare, root=root)["login"], False)
        none_kind = {**cfg, "environment": {**cfg["environment"], "access": {"kind": "none"}}}
        check_eq("K-W6 a stand that needs no login -> no record", "record" in env_probe.probe(none_kind, root=root)["login"], False)
    finally:
        env_probe._fetch, SA._open, SA.login = real_fetch, real_open, real_login
        cleanup(root)
    check("K-W8 the stand_access docstring documents the outcome key", '"outcome"' in (SA.__doc__ or ""))


class Client:
    """`request(method, url, headers, body, timeout)` -> HttpResult, or raises. `handler(sent body) -> HttpResult|Exception`."""

    def __init__(self, handler):
        self.handler, self.calls = handler, []

    def request(self, method, url, headers, body, timeout_s):
        sent = json.loads(body.decode("utf-8"))
        self.calls.append(sent)
        answer = self.handler(sent)
        if isinstance(answer, Exception):
            raise answer
        return answer


def http(code, text) -> "MC.HttpResult":
    return MC.HttpResult(code, [("Content-Type", "application/json")], text.encode("utf-8"), 0.01)


def testproject1_http(sent):
    code, text = testproject1(sent)
    return http(code, text)


def manual(handler, cfg=None) -> tuple:
    """(token or the ValueError, client)."""
    client = Client(handler)
    try:
        out = MC._http_login(client, {"base_url": BASE}, MC.Credentials(USER, PW), MC.spec(), cfg or {}, 5.0)
    except ValueError as exc:
        out = exc
    return out, client


def the_manual_capture() -> None:
    out, client = manual(testproject1_http)
    check_eq("K-M1 manual_default_tries_the_row: a token after the second pair", (out, len(client.calls)), ("jwt-value", 2))
    check_eq("K-M1 ... the bodies", client.calls, [{"username": USER, "password": PW}, {"email": USER, "password": PW}])
    out, client = manual(testproject1_http, {"environment": {"access": {"user_field": "email"}}})
    check_eq("K-M2 manual_reads_access_user_field: one request with it", (out, client.calls),
             ("jwt-value", [{"email": USER, "password": PW}]))
    for label, access in (("absent", None), ("not a dict", "x"), ("empty", {})):
        out, client = manual(testproject1_http, {"environment": {"access": access}})
        check_eq(f"K-M1 (E20) access {label}: the row's pairs", (out, len(client.calls)), ("jwt-value", 2))
    own = {"manual_capture": {"login": {"http": {"path": "/x", "body": {"login": "{username}", "pw": "{password}"},
                                                 "token_field": "access_token"}}}}
    out, client = manual(lambda sent: http(422, complaint("email")), own)
    check_eq("K-M3 manual_project_body_is_sent_as_written: once, exactly that body", client.calls,
             [{"login": USER, "pw": PW}])
    check_in("K-M3 ... today's text", "The stand rejected the account", str(out))
    out, client = manual(lambda sent: http(422, complaint("zzz")))
    check("K-M4 manual_shape_refusal_is_not_a_wrong_account", isinstance(out, ValueError)
          and "refused for its body shape" in str(out) and "`zzz`" in str(out) and SA.LOGIN_FIELD_FIX in str(out)
          and "rejected the account" not in str(out), str(out))
    check_in("K-M4 ... names both pairs that were sent", "`username` / `password`, then `email` / `password`", str(out))
    check_not_in("K-M4 ... and no credential", PW, str(out))
    for label, access in (("equal names", {"user_field": "x", "secret_field": "x"}), ("a list", {"user_field": ["email"]})):
        out, client = manual(testproject1_http, {"environment": {"access": access}})
        check("K-M5 manual_refuses_what_the_probe_refuses: " + label, isinstance(out, ValueError) and str(out).startswith(
              CC.body_field_errors(access)[0]) and "nothing was sent" in str(out) and client.calls == [], str(out))
    out, client = manual(lambda sent: MC.StepTimeout("slow"))
    check("K-M6 manual_no_answer_stops: one request, today's text", len(client.calls) == 1 and "no usable answer" in str(out),
          str(out))
    state = {"n": 0}

    def second_silent(sent):
        state["n"] += 1
        return http(422, complaint("email")) if state["n"] == 1 else MC.StepFailed("down")
    out, client = manual(second_silent)
    check("K-M6 ... also after a shape refusal: two requests, no shape sentence", len(client.calls) == 2
          and "refused for its body shape" not in str(out) and "no usable answer" in str(out), str(out))


class UrlClient:
    """Records (url, body) of every request; `answer(url, sent body)` -> HttpResult | Exception."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def request(self, method, url, headers, body, timeout_s):
        self.calls.append((url, json.loads(body.decode("utf-8"))))
        reply = self.answer(url, self.calls[-1][1])
        if isinstance(reply, Exception):
            raise reply
        return reply


def sourced(access, answer, own=None, root=None) -> tuple:
    """(token or the exception, client) of `_http_login` for a config whose environment.access is `access`."""
    cfg = {"environment": {"access": access, "env_file": "stand.env"}}
    if own is not None:
        cfg["manual_capture"] = {"login": own}
    client = UrlClient(answer)
    try:
        out = MC._http_login(client, {"base_url": BASE}, MC.Credentials(USER, PW), MC.spec(), cfg, 5.0, root)
    except (ValueError, MC.EnvBlocked) as exc:
        out = exc
    return out, client


def the_login_source() -> None:
    """EP1-31 (t-524 sec. 7, t-506 5.2): where the HTTP sign-in comes from, and what is never sent."""
    spec = MC.spec()
    ok = lambda url, sent: http(200, TOKEN_BODY)  # noqa: E731
    # the three kinds the factory has no request for, and an unknown one: 0 requests, the key is named, no project name
    for kind in ("harness_command", "bearer_env", "oidc_password", "frobnicate"):
        out, client = sourced({"kind": kind, "url": "/v1/token", "command": "x"}, ok)
        check("S1 %s without a recipe: EnvBlocked, 0 requests" % kind, isinstance(out, MC.EnvBlocked) and client.calls == [], str(out))
        if isinstance(out, MC.EnvBlocked):
            check_in(f"S1 {kind}: the line names the kind", f"environment.access.kind {kind}", out.row["probe_line"])
            check_in(f"S1 {kind}: and that nothing was sent", "nothing was sent", out.row["probe_line"])
            check_in(f"S1 {kind}: the door names the key to record", "manual_capture.login.http", out.row["remedy"])
            check_eq(f"S1 {kind}: factory-owned, no retry, cause login_unknown (t-1955 N2: nothing was sent)",
                     (out.row["owner"], out.row.get("do_not_retry"), out.row.get("cause")),
                     ("factory", True, MC.LOGIN_UNKNOWN_CAUSE))
            check_not_in(f"S1 {kind}: no project name", "Test Project 1", out.row["probe_line"] + out.row["remedy"])
    own = {"http": {"path": "/own/login", "token_field": "access_token"}}
    for kind in ("harness_command", "bearer_env", "oidc_password"):
        out, client = sourced({"kind": kind}, ok, own)
        check_eq(f"S2 {kind} + the project's own recipe: its path, once", (out, [c[0] for c in client.calls]),
                 ("jwt-value", [BASE + "/own/login"]))
    # access local_login: the recorded address, a key name resolved from the env file, the project's recipe still wins
    out, client = sourced({"kind": "local_login", "url": "/v1/other"}, ok)
    check_eq("S3 local_login with a path: glued to base_url, not the default path", (out, [c[0] for c in client.calls][:1]),
             ("jwt-value", [BASE + "/v1/other"]))
    out, client = sourced({"kind": "local_login", "url": "https://idp.example.invalid/tok"}, ok)
    check_eq("S3 ... an address written out is used as written", [c[0] for c in client.calls][:1], ["https://idp.example.invalid/tok"])
    out, client = sourced({"kind": "local_login", "url": "/v1/other"}, ok, own)
    check_eq("S4 the project's own recipe beats environment.access", [c[0] for c in client.calls], [BASE + "/own/login"])
    out, client = sourced({"user_field": "email"}, ok)
    check_eq("S5 an access with no kind keeps the factory's default path", [c[0] for c in client.calls],
             [BASE + spec["login"]["http"]["path"]])
    out, client = sourced(None, ok)
    check_eq("S5 no access at all: the same", [c[0] for c in client.calls], [BASE + spec["login"]["http"]["path"]])
    root = temp_project()
    try:
        (root / "stand.env").write_text("TOKEN_URL=https://idp.example.invalid/from-env\n", encoding="utf-8")
        out, client = sourced({"kind": "local_login", "url": "TOKEN_URL"}, ok, root=root)
        check_eq("S6 a key name in access.url is read from the project's env files", [c[0] for c in client.calls][:1],
                 ["https://idp.example.invalid/from-env"])
        out, client = sourced({"kind": "local_login", "url": "NO_SUCH_KEY"}, ok, root=root)
        check("S6 a key the files do not hold: EnvBlocked, 0 requests", isinstance(out, MC.EnvBlocked) and client.calls == [], str(out))
        out, client = sourced({"kind": "local_login", "url": ""}, ok, root=root)
        check("S6 an empty url: EnvBlocked, 0 requests", isinstance(out, MC.EnvBlocked) and client.calls == [], str(out))
        out, client = sourced({"kind": "local_login"}, ok, root=root)
        check("S6 no url key at all: EnvBlocked, 0 requests", isinstance(out, MC.EnvBlocked) and client.calls == [], str(out))
    finally:
        cleanup(root)
    out, client = sourced({"kind": "local_login", "url": "TOKEN_URL"}, ok, root=None)
    check("S7 root=None resolves no key name: EnvBlocked, 0 requests", isinstance(out, MC.EnvBlocked) and client.calls == [], str(out))
    out, client = sourced({"kind": "oidc_password", "url": "/v1/token"}, ok)
    check("S7 oidc_password with a url is NOT sent as a JSON login (its form is another request)",
          isinstance(out, MC.EnvBlocked) and client.calls == [], str(out))
    # `none` is a record of "no login": the declared-none answer, the source refuses to guess
    cfg_none = {"environment": {"access": {"kind": "none"}}}
    check_eq("S8 login_declared_none: http + access none", MC.login_declared_none(cfg_none, "http"), True)
    check_eq("S8 ... ui is not changed", MC.login_declared_none(cfg_none, "ui"), False)
    check_eq("S8 ... a project's own recipe beats it", MC.login_declared_none(dict(cfg_none, manual_capture={"login": {"http": {}}}), "http"), False)
    check_eq("S8 ... a present null is still none", MC.login_declared_none({"manual_capture": {"login": {"http": None}}}, "http"), True)
    check_eq("S8 ... no access / kind empty / kind local_login are not none",
             [MC.login_declared_none(c, "http") for c in ({}, {"environment": {"access": {"kind": ""}}},
                                                          {"environment": {"access": {"kind": "local_login"}}})], [False] * 3)
    out, client = sourced({"kind": "none"}, ok)
    check("S8 http_login_source itself never turns none into the default: EnvBlocked, 0 requests",
          isinstance(out, MC.EnvBlocked) and client.calls == [], str(out))
    # the token: any wrapper the factory knows when the recipe names no field; the project's token_field wins
    wrapped = lambda url, sent: http(200, json.dumps({"data": {"token": "wrapped-jwt"}}))  # noqa: E731
    out, client = sourced({"kind": "local_login", "url": "/v1/other"}, wrapped)
    check_eq("S9 access recipe: a token under data.token is read", out, "wrapped-jwt")
    out, client = sourced({"kind": "local_login", "url": "/v1/other"}, lambda u, s: http(200, "{}"))
    check_in("S9 no token: the stand's refusal words, with the source", "environment.access", str(out))
    both = lambda url, sent: http(200, json.dumps({"tok": "mine", "access_token": "other"}))  # noqa: E731
    out, client = sourced({"kind": "local_login", "url": "/v1/other"}, both,
                          {"http": {"path": "/own", "token_field": "tok"}})
    check_eq("S9 a project's token_field wins over the walk", out, "mine")
    out, client = sourced({"kind": "local_login", "url": "/v1/other"}, both)
    check_eq("S9 ... without one the factory's order (access_token first)", out, "other")
    # the words after a failed answer: the default address that the stand does not have is not "the account was rejected"
    gone = lambda url, sent: http(404, json.dumps({"detail": "Not Found"}))  # noqa: E731
    out, client = sourced(None, gone)
    check("S10 factory default + 404: the address and the door, not 'rejected the account'",
          isinstance(out, ValueError) and "rejected the account" not in str(out) and BASE + spec["login"]["http"]["path"] in str(out)
          and "never confirmed" in str(out) and "manual_capture.login.http" in str(out), str(out))
    refused401 = lambda url, sent: http(401, json.dumps({"detail": "no"}))  # noqa: E731
    out, client = sourced(None, refused401)
    check("S10 factory default + 401: the stand judged the account (the old sentence), the source named",
          isinstance(out, ValueError) and "The stand rejected the account" in str(out) and "never confirmed" in str(out), str(out))
    out, client = sourced({"kind": "local_login", "url": "/v1/other"}, gone)
    check("S10 access + 404: the old sentence (the project recorded the address), the source named",
          isinstance(out, ValueError) and "The stand rejected the account" in str(out) and "environment.access" in str(out), str(out))
    # a web application answers 404 with an HTML page: on the factory's guess it is still "the address is not there"
    page404 = lambda url, sent: MC.HttpResult(404, [("Content-Type", "text/html")], b"<!DOCTYPE html><html>nope</html>", 0.01)  # noqa: E731
    out, client = sourced(None, page404)
    check("S10 factory default + an HTML 404: the address and the door, not the protection-layer sentence",
          isinstance(out, ValueError) and "protection layer" not in str(out) and "never confirmed" in str(out)
          and BASE + spec["login"]["http"]["path"] in str(out) and "manual_capture.login.http" in str(out), str(out))
    out, client = sourced({"kind": "local_login", "url": "/v1/other"}, page404)
    check("S10 access + an HTML 404: the recorded address, so the protection-layer sentence stays",
          isinstance(out, ValueError) and "protection layer" in str(out), str(out))
    not_allowed = lambda url, sent: MC.HttpResult(405, [("Content-Type", "text/plain")], b"", 0.01)  # noqa: E731
    out, client = sourced(None, not_allowed)
    check("S10 factory default + an empty 405: the address is not confirmed, the account was not judged",
          isinstance(out, ValueError) and "never confirmed" in str(out) and "rejected the account" not in str(out), str(out))
    # a project's own recipe with a `url`: the address of the access record only is ever used
    out, client = sourced(None, ok, {"http": {"path": "/own/login", "url": "https://other.example.invalid/x", "token_field": "access_token"}})
    check_eq("S10 a project recipe's own url is not an address the factory sends the account to", [c[0] for c in client.calls],
             [BASE + "/own/login"])
    # why bearer_env keeps the general door: a header made of a token is refused by the shipped secret patterns
    patterns = json.loads((PACKAGE / "references" / "templates" / "config.json").read_text(encoding="utf-8"))["secret_content_patterns"]
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.c2ln"
    check("S11 --header 'Authorization: Bearer <jwt>' matches secret_content_patterns (run_http would refuse it)",
          MC.secret_pattern_hit(f"Authorization: Bearer {jwt}", {"secret_content_patterns": patterns}) is not None)
    check("S11 control: a header with no token in it matches none", MC.secret_pattern_hit(
        "Accept: application/json", {"secret_content_patterns": patterns}) is None)


def the_docs() -> None:
    steps = json.loads((PACKAGE / "references" / "manual-capture-steps.json").read_text(encoding="utf-8"))
    check("K-D1 the manual-capture default recipe has no body", "body" not in steps["login"]["http"])


def the_battery() -> None:
    sent = ("username", "password")
    big = json.dumps({"detail": [{"loc": ["body", "email"], "msg": "x" * 100} for _ in range(1000)]})
    check("K-B1 magnitude: 256 KB with 1000 detail items is a shape refusal", len(big) > 100000
          and SA.shape_refused(422, big, (USER, PW), sent))
    check("K-B1 ... and complained stays within max_names", len(SA.complained_fields(big)) <= SA._login_error_shapes()["max_names"])
    nested = json.dumps({"detail": [{"loc": [[["body"]], "email"]}]})
    check("K-B2 nesting: a list inside loc is read without an exception", isinstance(SA.shape_refused(422, nested, (), sent), bool))
    deep = "{\"a\":" * 200 + "1" + "}" * 200
    check_eq("K-B2 a 200-deep object names nothing, no exception", SA.shape_refused(422, deep, (), sent), False)
    check_eq("K-B3 encoding: a non-ASCII (escaped in this source) field name is dropped -> no advance",
             SA.shape_refused(422, complaint(chr(0x435) + "mail"), (), sent), False)
    check_eq("K-B3 ... replacement characters in the body do not raise", SA.shape_refused(
        422, '{"detail": "' + chr(0xFFFD) * 2 + '"}', (), sent), False)
    for code in (400, 422):
        for text in ("", "{", "null", "[]"):
            check_eq(f"K-B4 broken body {text!r} with HTTP {code} does not advance", SA.shape_refused(code, text, (), sent), False)
    # the LOGIN_FIELD_FIX length pin is K-F1 (the real constant, with its 156-character negative control)


def the_login_seconds() -> None:
    """RN1-3 K-RN3-W1..W3: `login_probe.seconds` - written by the record, validated by the contract, a timeout told as a timeout."""
    cfg, access = {"user_key": "U"}, {"user_key": "U"}
    for label, receipt, has in (("80.3", {"status": "ok", "code": None, "seconds": 80.3}, True),
                                ("0", {"status": "ok", "code": None, "seconds": 0}, False),
                                ("absent", {"status": "ok", "code": None}, False),
                                ("a string", {"status": "ok", "code": None, "seconds": "80"}, False)):
        record = env_probe.login_record(cfg, access, ["U"], receipt)
        check_eq(f"K-RN3-W1 receipt seconds {label} -> `seconds` {'copied' if has else 'not written'}", "seconds" in record, has)
    check_eq("K-RN3-W1 ... the copied value is the receipt's", env_probe.login_record(cfg, access, ["U"], {"status": "ok", "seconds": 80.3})
             .get("seconds"), 80.3)
    proof = {"user_key": "AUTH_USERNAME", "outcome": "ok", "checked_at": "2026-10-31T10:00:00"}
    for value in ("80", True, 0, -1):
        errors = CC.access_errors({"kind": "none", "login_probe": {**proof, "seconds": value}})
        check_in(f"K-RN3-W2 seconds {value!r} is refused, with the way out", "must be a positive number of seconds", " ".join(errors))
    check_eq("K-RN3-W2 seconds 80 passes", CC.access_errors({"kind": "none", "login_probe": {**proof, "seconds": 80}}), [])
    check_eq("K-RN3-W2 seconds absent passes (a project onboarded before it)", CC.access_errors({"kind": "none", "login_probe": proof}), [])
    root = temp_project("qa-factory-rn13-")
    real_fetch, real_login = env_probe._fetch, SA.login
    try:
        (root / "tests" / ".env").write_text("STAND=http://stand.example:8080\nAUTH_USERNAME=" + USER + "\n", encoding="utf-8")
        full = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        full["environment"] = {"env_file": "tests/.env", "base_url_key": "STAND", "user_key": "AUTH_USERNAME", "health_path": "/v1/config",
                               "access": {"kind": "harness_command", "command": "npx playwright test", "user_key": "AUTH_USERNAME"}}
        env_probe._fetch = lambda url, timeout: 200
        SA.login = lambda *a, **k: {"status": "failed", "code": None, "user_key": "AUTH_USERNAME", "refusal": "timeout",
                                    "why": "`npx` did not finish within 300s (no login duration is recorded)"}
        result = env_probe.probe(full, root=root)
        text = " ".join(result["layer1"])
        check_in("K-RN3-W3 a login that did not finish is told as one", "did not finish in time", text)
        check_not_in("K-RN3-W3 ... and not as a refusal", "was refused", text)
        check_eq("K-RN3-W3 ... the status stays failed (F-5): the exit code and the record's outcome are unchanged",
                 (result["login"]["status"], result["login"]["record"]["outcome"]), ("failed", "failed"))
        SA.login = lambda *a, **k: {"status": "failed", "code": 401, "user_key": "AUTH_USERNAME", "why": "HTTP 401"}
        check_in("K-RN3-W3 control: another failure still says it was refused", "was refused", " ".join(env_probe.probe(full, root=root)["layer1"]))
    finally:
        env_probe._fetch, SA.login = real_fetch, real_login
        cleanup(root)


the_data_row()
the_login_seconds()
the_loop()
the_stand_login()
the_fix_and_the_probe()
the_doctor()
the_record()
the_manual_capture()
the_login_source()
the_docs()
the_battery()
finish("test_login_body_fields")
