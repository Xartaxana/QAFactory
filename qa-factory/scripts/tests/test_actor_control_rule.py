"""TQ1-2 (K3): the actor-control rule. Part T is TC-014 (TP1 MR !719): the mutation "the token is invalid" leaves a test
written by the old rule green and turns a test written by the new rule red. (The role-text keys of part D moved to
design/role-rules.json.)

No pytest, no network, no stand: a temporary git repository, `red_sandbox.prepare`, and a tiny runner.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

ROOT = temp_project("qa-factory-actor-control-")
use_project(ROOT)

import red_sandbox as RS  # noqa: E402

# --- part T: TC-014 ----------------------------------------------------------------------------------------------------------------
PRODUCT = '''\
VALID = {"tok-readonly", "tok-admin"}


def call(token, method, path):
    if token not in VALID:
        return 401
    if method == "GET":
        return 200
    if method == "POST" and path.endswith("/validate"):
        return 403
    return 404
'''
ACCOUNTS = 'READONLY_TOKEN = "tok-readonly"\nADMIN_TOKEN = "tok-admin"\n'
MUTATED_ACCOUNTS = 'READONLY_TOKEN = "tok-expired"\nADMIN_TOKEN = "tok-admin"\n'
HEAD = "from accounts import ADMIN_TOKEN, READONLY_TOKEN\nfrom product import call\n\n\n"
REFUSAL = 'status = call(READONLY_TOKEN, "POST", "/v1/workflows/w1/validate")\n    assert 400 <= status < 500  # oracle_unknown: Q4\n'
CONTROL = 'assert call({token}, "GET", "/v1/workflows/w1") == 200\n    '
TESTS = {
    "test_old_rule.py": HEAD + "def test_refused_TC_014():\n    " + REFUSAL,
    "test_new_rule.py": HEAD + "def test_refused_TC_014():\n    " + CONTROL.format(token="READONLY_TOKEN") + REFUSAL,
    "test_new_rule_fixture.py": HEAD + 'def readonly_session():\n    assert call(READONLY_TOKEN, "GET", "/v1/workflows/w1") == 200\n'
                                      "    return READONLY_TOKEN\n\n\ndef test_refused_TC_014():\n    readonly_session()\n    " + REFUSAL,
    "test_other_account.py": HEAD + "def test_refused_TC_014():\n    " + CONTROL.format(token="ADMIN_TOKEN") + REFUSAL,
}
RUNNER = '''\
import importlib
import sys

module = importlib.import_module(sys.argv[1])
failed = 0
for name in sorted(vars(module)):
    if name.startswith("test_") and callable(getattr(module, name)):
        try:
            getattr(module, name)()
            print("PASS", name)
        except AssertionError:
            failed += 1
            print("FAIL", name)
sys.exit(1 if failed else 0)
'''


def run(cwd: Path, module: str) -> int:
    done = subprocess.run([sys.executable, "-B", "run.py", module], cwd=str(cwd), capture_output=True, text=True, timeout=60,
                          env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    return done.returncode


repo = temp_dir("qa-actor-control-repo-")
sandbox_root = temp_dir("qa-actor-control-sbx-")
try:
    subprocess.run(["git", "init", "-q"], cwd=str(repo), capture_output=True, timeout=60)
    (repo / "product.py").write_text(PRODUCT, encoding="utf-8")
    (repo / "accounts.py").write_text(ACCOUNTS, encoding="utf-8")
    (repo / "run.py").write_text(RUNNER, encoding="utf-8")
    for name, body in TESTS.items():
        (repo / name).write_text(body, encoding="utf-8")
    check_eq("T0: on the unmutated repository all four modules pass",
             [run(repo, name[:-3]) for name in TESTS], [0, 0, 0, 0])

    control_line = next(i for i, line in enumerate(TESTS["test_new_rule.py"].splitlines(), start=1) if "== 200" in line)
    request = {"mutations": [{
        "path": "accounts.py", "before_sha256": RS.digest(repo / "accounts.py"), "replacement_utf8": MUTATED_ACCOUNTS,
        "instance_id": "TC-014", "expected_location": f"test_new_rule.py:{control_line}", "expected_reason": "assert 401 == 200"}]}
    receipt = RS.prepare(repo, sandbox_root / "sbx", request)
    sandbox = Path(receipt["sandbox"])
    check_eq("T-prepare: the sandbox is prepared with the token mutated", receipt["status"], "prepared")
    check("T-prepare: the sandbox holds the mutated bytes", "tok-expired" in (sandbox / "accounts.py").read_text(encoding="utf-8"))
    check_eq("T1: the test written by the old rule SURVIVES the dead token (4xx is 4xx)", run(sandbox, "test_old_rule"), 0)
    check_eq("T2: the test with the allowed call by the same credentials FAILS", run(sandbox, "test_new_rule"), 1)
    check_eq("T3: ... and so does the one whose control lives in a fixture function", run(sandbox, "test_new_rule_fixture"), 1)
    check_eq("T4: a control by ANOTHER account does not catch the mutation (hence the SAME)", run(sandbox, "test_other_account"), 0)
finally:
    cleanup(repo)
    cleanup(sandbox_root)
    cleanup(ROOT)

finish("test_actor_control_rule")
