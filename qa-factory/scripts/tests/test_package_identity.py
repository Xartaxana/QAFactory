"""Package identity (GM2-1): the licence text, the plugin manifests, the skill authors and the marketplace name.

Four keys, all data checks (AR-29): K1 the LICENSE bytes and the README pointer, K2 the manifest flavours and their
fields, K3 the skill authors, K4 the marketplace name in every install instruction against hooklib.VERSION_MARKETPLACE.
The forbidden words are assembled at run time, so this file gives the scrub scanner no hit of its own.
Run from the repo root: python -B ai-packages/qa-factory/scripts/tests/test_package_identity.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, check_in, finish  # noqa: E402

import hooklib  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
# SHA-256 of https://www.apache.org/licenses/LICENSE-2.0.txt, measured on 05.11.2026 (LF endings).
APACHE_2_0_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"
COMPANY = "EP" + "AM"
PRODUCT = "code" + "mie"
FLAVOURS = {".claude-plugin", ".codex-plugin", ".kimi-plugin", ".plugin"}
AUTHOR = "Xartaxana"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from strings(k)
            yield from strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from strings(v)


def k1_license() -> None:
    text = read(PLUGIN_ROOT / "LICENSE")
    check_eq("K1: LICENSE is the canonical Apache-2.0 text (sha256 after CRLF -> LF)",
             hashlib.sha256(text.encode("utf-8")).hexdigest(), APACHE_2_0_SHA256)
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    check_eq("K1: the first non-empty line is `Apache License`", first, "Apache License")
    check_in("K1: the version line is there", "Version 2.0, January 2004", text)
    check_in("K1: the terms end where the text ends", "END OF TERMS AND CONDITIONS", text)
    check("K1: no company name in LICENSE", COMPANY.lower() not in text.lower())
    check("K1: no `All rights reserved` in LICENSE", "all rights reserved" not in text.lower())
    check_in("K1: README points at LICENSE", "see [LICENSE](LICENSE)", read(PLUGIN_ROOT / "README.md"))


def k2_manifests() -> None:
    found = {p.parent.name for p in PLUGIN_ROOT.glob("*/plugin.json") if p.parent.name.startswith(".")}
    check_eq("K2: the manifest flavours are exactly the four hosts (extra: %s; missing: %s)"
             % (sorted(found - FLAVOURS), sorted(FLAVOURS - found)), found, FLAVOURS)
    for flavour in sorted(found & FLAVOURS):
        data = json.loads(read(PLUGIN_ROOT / flavour / "plugin.json"))
        check_eq(f"K2: {flavour} license", data.get("license"), "Apache-2.0")
        check_eq(f"K2: {flavour} author", data.get("author"), {"name": AUTHOR})
        if "interface" in data:
            check_eq(f"K2: {flavour} interface.developerName", data["interface"].get("developerName"), AUTHOR)
        bad = [s for s in strings(data) if PRODUCT in s.lower() or COMPANY.lower() in s.lower()]
        check(f"K2: {flavour} has no company or product-host word in any value", not bad, repr(bad[:3]))


def k3_skill_authors() -> None:
    skills = sorted((PLUGIN_ROOT / "skills").glob("*/SKILL.md"))
    check("K3: there are skills to check", len(skills) > 0)
    for path in skills:
        lines = [ln for ln in read(path).splitlines() if re.match(r"\s*author:", ln)]
        check(f"K3: {path.parent.name} author line", [ln.strip() for ln in lines] == [f"author: {AUTHOR}"], repr(lines))


def k4_marketplace() -> None:
    check_eq("K4: the fallback marketplace", hooklib.VERSION_MARKETPLACE, "qafactory")
    check_in("K4: INSTALL adds the marketplace from GitHub", "claude plugin marketplace add Xartaxana/QAFactory",
             read(PLUGIN_ROOT / "INSTALL.md"))
    files = [PLUGIN_ROOT / n for n in ("INSTALL.md", "UPGRADE.md", "README.md", "CHANGELOG.md")]
    files += sorted((PLUGIN_ROOT / "skills").glob("*/README.md"))
    counts = {}
    cache_form = re.compile(r"plugins[/\\]+cache[/\\]+([A-Za-z0-9_.-]+)[/\\]+qa-factory")   # the installed-copy path form
    check("K4: the cache-path form names the marketplace it is given (negative control: another name is caught)",
          [m.group(1) for m in cache_form.finditer("~/.claude/plugins/cache/other-market/qa-factory/1.0")] == ["other-market"])
    for path in files:
        for no, line in enumerate(read(path).splitlines(), 1):
            for m in re.finditer(r"qa-factory@([A-Za-z0-9_.-]+)", line):
                counts[path.name] = counts.get(path.name, 0) + 1
                check(f"K4: {path.name}:{no} names the marketplace", m.group(1) == hooklib.VERSION_MARKETPLACE, line.strip())
            for m in cache_form.finditer(line):
                check(f"K4: {path.name}:{no} names the marketplace in its cache path", m.group(1) == hooklib.VERSION_MARKETPLACE, line.strip())
    check("K4: INSTALL.md names the plugin id at least once (not green on an empty set)", counts.get("INSTALL.md", 0) > 0)


def main() -> None:
    k1_license()
    k2_manifests()
    k3_skill_authors()
    k4_marketplace()
    finish("test_package_identity")


if __name__ == "__main__":
    main()
