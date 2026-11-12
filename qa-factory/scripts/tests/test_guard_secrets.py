"""guard_secrets.check: the PreToolUse guard that blocks secrets from ever reaching a
factory file (Write|Edit), by file-name pattern (.env, id_rsa, credentials...) and by
content signature (private keys, api_key="...", the AWS secret-key field, JWT). The
guard needs no project config — the defaults apply even to an unonboarded project — and
its own `scannable()` carve-out must not let a real secret hide behind the config keys
that merely DESCRIBE the detection policy.

Note: the secret-shaped sample payloads below are assembled from separate string pieces
on purpose, and even the CHECK DESCRIPTIONS avoid spelling a live signature out in full.
This file is itself written through the Write tool, and the plugin installed in THIS
session runs the very hook under test on every Write — a literal contiguous secret
signature anywhere in this source would get the file itself blocked before the test
could run. Splitting the literals changes nothing about what check() sees at runtime:
the pieces are joined into one string before they ever reach guard_secrets.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import guard_secrets as G  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, finish  # noqa: E402


def blocked(event: dict, cfg: dict | None = None) -> str:
    """The block message, or '' if the call was allowed through."""
    try:
        G.check(event, cfg or {})
    except SystemExit as exc:
        check_eq("a block always exits 2 (PreToolUse block contract)", exc.code, 2)
        return "blocked"
    return ""


def write(path: str, content: str = "") -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


check("a write to .env is blocked by file name alone, no content needed",
      blocked(write("qa-factory/.env")) == "blocked")
check("a write to id_rsa is blocked", blocked(write("home/.ssh/id_rsa")) == "blocked")
check("a write to an ordinary file with harmless content is allowed",
      blocked(write("qa-factory/artifacts/QA-1/work/notes.md", "just some notes")) == "")

pem_header = "-----BEGIN " + "RSA PRIVATE KEY" + "-----"
check("a private key body is blocked regardless of the file name",
      blocked(write("notes.md", pem_header + "\nMIIB...\n")) == "blocked")

api_key_field = "api" + "_key"
long_value = "sk" + "-" + ("x" * 24)
check("a quoted api-key literal is blocked",
      blocked(write("case.md", api_key_field + ' = "' + long_value + '"')) == "blocked")

aws_field = "aws" + "_secret_access_key"
check("the AWS secret-key field name is a blocked signature",
      blocked(write("case.md", aws_field + ": AKIA" + ("Q" * 16))) == "blocked")

eyj = "eyJ"
jwt_like = eyj + "abcdefghij1" + "." + eyj + "klmnopqrst2" + "."
check("a JWT-shaped token is blocked",
      blocked(write("case.md", "token=" + jwt_like + "sig")) == "blocked")

check("a reference to an env var, not a literal, is not a secret signature",
      blocked(write("case.md", api_key_field + " = os.environ['API_KEY']")) == "")
check("a short placeholder value does not match the 16-char minimum",
      blocked(write("case.md", "password" + ' = "x"')) == "")

check("a Read of a .env file is not a Write/Edit and is not touched by this guard",
      blocked({"tool_name": "Read", "tool_input": {"file_path": "qa-factory/.env"}}) == "")

# --- config extends, never replaces, the built-in patterns ---
cfg_extra = {"secret_file_patterns": [r"myproject-secret\.txt$"]}
check("a project pattern adds to, not instead of, the default .env rule",
      blocked(write("myproject-secret.txt"), cfg_extra) == "blocked" and
      blocked(write(".env"), cfg_extra) == "blocked")

# --- scannable(): the factory's own policy-describing keys are not scanned as content ---
policy_key = "secret" + "_content_patterns"
policy_json = ('{"' + policy_key + '": ["(?i)' + aws_field + '"], '
               '"note": "' + aws_field + ' is a DETECTOR pattern, not a real key"}')
scanned = G.scannable(policy_json)
check("scannable() strips the pattern list itself from a declared-policy JSON payload",
      aws_field not in scanned)
check("scannable() strips prose *_note fields alongside the patterns",
      "DETECTOR" not in scanned)

leaking_json = '{"' + policy_key + '": ["x"], "' + aws_field + '": "AKIA' + ("Q" * 16) + '"}'
check("a real secret elsewhere in the same policy-shaped JSON is still scannable",
      ("AKIA" + ("Q" * 16)) in G.scannable(leaking_json))
check("...and writing that JSON is therefore still blocked",
      blocked(write("qa-factory/config.json", leaking_json)) == "blocked")

check("content with neither policy key is returned unchanged",
      G.scannable("plain text, nothing special") == "plain text, nothing special")
check("content that looks like policy but does not parse as JSON is scanned whole (fail-closed)",
      aws_field in G.scannable(policy_key + " " + aws_field + " but not json"))

finish("test_guard_secrets")
