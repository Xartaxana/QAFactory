"""Detector for the "secrets never reach artifacts" mechanism (PreToolUse: Write|Edit).

Blocks writes into secret files (.env and friends) and writes of content carrying
secret signatures (private keys, api-key=..., JWT) into factory files.

This rule needs NO project config: the plugin is installed user-wide and must guard
secrets even in a project that was never onboarded (no qa-factory/config.json). The
defaults below always apply; a project's config.json can only ADD patterns on top of
them, never replace them.

Invoked through guard_pre_tool.py (one process for all PreToolUse checks); the
standalone entry point is kept for manual runs and backwards compatibility.
"""
import json
import re
import sys

from hooklib import read_event, load_config, block, norm

DEFAULT_SECRET_FILE_PATTERNS = [
    r"\.env$",
    r"\.env\.",
    r"(?:^|/)credentials(?:\.(?:json|ya?ml|txt|ini|conf))?$",
    r"secrets?\.(json|ya?ml|txt)$",
    r"\.pem$",
    "id_rsa",
]

DEFAULT_SECRET_CONTENT_PATTERNS = [
    r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|password)\s*[=:]\s*['\"][A-Za-z0-9+/_\-]{16,}['\"]",
    r"(?i)aws_secret_access_key",
    r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.",
]


POLICY_KEYS = ("secret_content_patterns", "secret_file_patterns")


def _strip_policy(node):
    """Drop the keys that DESCRIBE the policy, at any depth: the pattern lists themselves
    and every `note`/`*_note` prose field."""
    if isinstance(node, dict):
        return {k: _strip_policy(v) for k, v in node.items()
                if k not in POLICY_KEYS and k != "note" and not str(k).endswith("_note")}
    if isinstance(node, list):
        return [_strip_policy(x) for x in node]
    return node


def scannable(content: str) -> str:
    """The factory's own config declares the very signatures this guard hunts for:
    `(?i)aws_secret_access_key` lives in `secret_content_patterns` as a DETECTOR, and the
    `_note` fields explain the policy in prose. Scanning those back blocked the config that
    configures the guard — and the retry that "fixed" it by dropping `secret_content_patterns`
    left the project with no content detectors at all, which is the worse half of the bug.

    A payload that parses as JSON and declares this factory's pattern keys is such a config:
    its pattern lists and its notes are policy and are not scanned. Everything else in it
    still is — a credential pasted into a config is exactly as forbidden as one pasted into a
    test — and anything that does not parse is scanned whole, fail-closed."""
    if not any(key in content for key in POLICY_KEYS):
        return content
    try:
        data = json.loads(content)
    except Exception:
        return content
    if not isinstance(data, dict):
        return content
    return json.dumps(_strip_policy(data), ensure_ascii=False)


def _patterns(cfg: dict, key: str, defaults: list) -> list:
    extra = [p for p in (cfg.get(key) or []) if p]
    seen, merged = set(), []
    for p in defaults + extra:
        if p not in seen:
            seen.add(p)
            merged.append(p)
    return merged


def check(event: dict, cfg: dict) -> None:
    """Blocks the call (exit 2) or returns control."""
    if event.get("tool_name") not in ("Write", "Edit"):
        return
    ti = event.get("tool_input", {}) or {}
    target = norm(ti.get("file_path", ""))
    for pat in _patterns(cfg, "secret_file_patterns", DEFAULT_SECRET_FILE_PATTERNS):
        if re.search(pat, target):
            block(
                f"SECRETS: writing to '{ti.get('file_path')}' is blocked (secret-file pattern '{pat}'). "
                "Credentials travel through environment variables, not through factory files."
            )
    content = scannable((ti.get("content", "") or "") + "\n" + (ti.get("new_string", "") or ""))
    for pat in _patterns(cfg, "secret_content_patterns", DEFAULT_SECRET_CONTENT_PATTERNS):
        m = re.search(pat, content)
        if m:
            block(
                f"SECRETS: the content being written carries a secret signature ({pat}, fragment: '{m.group(0)[:40]}...'). "
                "Secrets in cases/tests/artifacts are forbidden - use env variables and placeholders. "
                "If this IS policy text - a detector pattern or a note in qa-factory/config.json - "
                "write the whole file with Write rather than editing a fragment; never resolve this "
                "block by deleting secret_content_patterns, which would leave the project with no "
                "content detectors at all."
            )


def main() -> None:
    event = read_event()
    if event is None:
        block("SECRETS: hook event could not be parsed (broken stdin) - fail-closed, write blocked.")
    check(event, load_config(event))
    sys.exit(0)


if __name__ == "__main__":
    main()
