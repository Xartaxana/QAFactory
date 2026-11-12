"""Factory definition manifest — the executable "definition != data" boundary.

The factory definition (roles, skills, hooks, templates, strategy, checklists, maps)
is one per team; data (state/, artifacts/, bugs/, test-cases/) is each instance's own.
Any change to the definition happens only by a calibration decision (or the keeper's
fast-track for local-urgent) with a witness. The manifest is a sha256 snapshot of every
definition file, re-stamped by the latest decision: an instance whose hashes diverge from
the manifest is drifting from the reference. "Every definition file" is the ONE recipe of
`release_fingerprint` (`file_digests`, the same map the release file holds; collect/2 CL2-1,
AR-15): this script keeps no list of its own. A stamp records that recipe's id; a stamp made
by another recipe (or by none: every stamp before CL2-1) is never judged file by file.

Run (from anywhere — the plugin's own definition is what gets stamped, not a project):
  python <plugin>/scripts/factory_manifest.py                     — verify, exit 1 on drift
  python <plugin>/scripts/factory_manifest.py --check             — the same verify, spelled out
  python <plugin>/scripts/factory_manifest.py --stamp "<witness>" — re-stamp by a decision
    (the witness is mandatory: who/when/what was decided — "operator's instruction
    2026-09-02", "team calibration 2026-09-08", "keeper's fast-track, FB-8")

Root split note: in the plugin architecture a project never carries its own copy of
roles/skills/hooks (that used to be the "instance" the donor's manifest protected) — the
definition lives ONLY in the plugin's own git, at PLUGIN_ROOT. This script therefore
snapshots PLUGIN_ROOT, not a project; "drift" now means the plugin's shipped files
diverged from the last stamped decision, which is a plugin-repo concern (CI/release),
not something a project installs or triggers.

A MISSING manifest is reported here (exit 1) because this CLI is the release-side pin: you
asked to verify, there is nothing to verify against. Audit A14 no longer reads this stamp at
all: it reads `release_fingerprint.compare()` (the release file) and writes nothing.

A package file that cannot be read is never a pass and never an accusation: `--check` prints
one UNKNOWN line (exit 1), and `--stamp` refuses (exit 2) and writes nothing.
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hooklib import PLUGIN_ROOT
import release_fingerprint

MANIFEST_PATH = PLUGIN_ROOT / "factory-manifest.json"
_UNREADABLE_PREFIX = "unreadable package files: "   # the text of release_fingerprint.file_digests' OSError (pinned by K20)
_NAMES_SHOWN = 10


class StampRefused(Exception):
    """`--stamp` refuses (FR-1): the message names what is wrong, what was expected and the door."""


def _unreadable_names(exc: OSError) -> str:
    """The files of a failed read, at most _NAMES_SHOWN, then `(+k more)` (a cut list says how much it hid)."""
    text = str(exc)
    names = text[len(_UNREADABLE_PREFIX):].split(", ") if text.startswith(_UNREADABLE_PREFIX) else [text]
    return ", ".join(names[:_NAMES_SHOWN]) + (f" (+{len(names) - _NAMES_SHOWN} more)" if len(names) > _NAMES_SHOWN else "")


def collect_definition() -> dict:
    """Current sha256 of the definition files, POSIX paths relative to the plugin root: the survivor's map
    (`design/` stays outside it - FR-44 - and so does every `tests` part). Raises OSError naming the unreadable files."""
    return release_fingerprint.file_digests(PLUGIN_ROOT)


def verify() -> list:
    """The list of the instance's divergences from the manifest; empty — no drift.
    A missing manifest is a violation too: the reference was never pinned by any decision.
    A stamp made by another recipe, and a tree that cannot be read, each give ONE line and judge no file."""
    if not MANIFEST_PATH.exists():
        return ["factory-manifest.json is missing — the factory definition is not "
                "pinned by a decision; run factory_manifest.py --stamp \"<witness>\""]
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        stamped = manifest["files"]
    except (json.JSONDecodeError, KeyError) as e:
        return [f"factory-manifest.json is unreadable ({e}) — re-stamp by a decision"]
    if manifest.get("recipe") != release_fingerprint.RECIPE_ID:
        return [f"the stamp was made by another recipe ({manifest.get('recipe') or 'none'}) — re-stamp by a decision "
                f"(factory_manifest.py --stamp \"<witness>\"); no file is judged against it"]
    try:
        current = collect_definition()
    except OSError as exc:
        return [f"UNKNOWN — package files could not be read: {_unreadable_names(exc)}; the stamp is not judged"]
    drift = []
    for rel in sorted(set(stamped) | set(current)):
        if rel not in current:
            drift.append(f"{rel}: deleted after the stamp")
        elif rel not in stamped:
            drift.append(f"{rel}: appeared after the stamp")
        elif stamped[rel] != current[rel]:
            drift.append(f"{rel}: content diverged from the stamp")
    return drift


def stamp(witness: str) -> None:
    """Pin the current definition by a decision. The map is read WHOLE before anything is written: a tree that cannot be
    read is refused (StampRefused), because a stamp over a partial map would pin a definition nobody checked."""
    try:
        files = collect_definition()
    except OSError as exc:
        raise StampRefused(f"package files could not be read: {_unreadable_names(exc)}; expected every definition file readable, "
                           "because a stamp over a partial map would pin a definition nobody checked; fix the files "
                           "(permissions, a vanished file), then run --stamp again. Nothing was written.") from exc
    MANIFEST_PATH.write_text(json.dumps({
        "stamped_at": f"{datetime.now():%Y-%m-%d %H:%M}",
        "witness": witness,
        "recipe": release_fingerprint.RECIPE_ID,
        "files": files,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"factory_manifest: {len(files)} definition files, witness: {witness}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Factory definition manifest")
    ap.add_argument("--stamp", metavar="WITNESS",
                    help="re-stamp the manifest by a decision (the witness is mandatory)")
    ap.add_argument("--check", action="store_true",
                    help="verify against the stamped manifest (the default when no flag is given)")
    args = ap.parse_args()
    if args.check and args.stamp is not None:
        print("factory_manifest: --check and --stamp are mutually exclusive")
        sys.exit(2)
    if args.stamp is not None:
        if not args.stamp.strip():
            print("factory_manifest: empty witness — a decision without a witness is not a decision")
            sys.exit(2)
        try:
            stamp(args.stamp.strip())
        except StampRefused as exc:
            print(f"factory_manifest: --stamp refused - {exc}")
            sys.exit(2)
        return
    drift = verify()
    if drift:
        # An unreadable tree and a stamp of another recipe are NOT drift: nothing was compared (FR-41, E3/E7), so the header
        # does not accuse; the exit stays 1, because the caller still cannot proceed as "verified".
        judged = not (len(drift) == 1 and drift[0].startswith(("UNKNOWN", "the stamp was made by another recipe")))
        print(f"factory_manifest: {'DRIFT' if judged else 'NOT JUDGED'} ({len(drift)})")
        for d in drift:
            print(f"  - {d}")
        sys.exit(1)
    print("factory_manifest: no drift")


if __name__ == "__main__":
    main()
