"""A person's permission for the automator to write TEST files inside the application tree, for ONE story
(the wave 4 spec, the branch author's word - D-0025; the name rule is D-0030, 06.10.2026).

P-00 (the factory never modifies application code) is absolute. Two things open test files inside the
application tree besides an `apply` decision for one named file. The permanent one is the project's own
word: `test_locations` in the config (`test_locations.py`, D-0030). The per-story one is this module:
`waiver.py --task <T> --stage S5 --block "protected test path: <folder/ or pattern>" --words-file <file>`
lets the automator of that story write test files that match the pattern. This module is the whole of that
rule and nothing else (it is built to be removed cleanly: the guard pass and the waiver record call it,
nothing more reads it):

  pattern_errors(p, cfg, app_root)       the refusal texts for a pattern, [] when it is admitted
  pattern_notes(p, cfg, app_root)        advisory lines for an admitted pattern (never a refusal)
  active_grants(pipeline, cfg, app_root) the recorded permissions of one story that STILL pass
  grant_for(pipeline, target, cfg, root) the active permission that covers one resolved target

The same function runs at record time and at read time: a permission recorded before this rule
existed, or one the config has since turned into a protected root, no longer passes and is ignored
(fail closed, never raised: the guard calls this on a blocking path).

Pattern language, relative to app_root (it lives in `test_locations.py`, the one reader, and is imported
here): `\\` is `/`; `*` inside a segment, `**` as a whole segment (zero or more folders), `?`; a trailing `/`
means `dir/**`; lower-cased like `hooklib.norm`, which is how a target is compared (RESOLVED, so a symlink
inside a test folder cannot lead into application code). Refused: empty; absolute; a `..` segment; `[ ] { }
!`; a pattern that matches a protected root or any ancestor of one, or that ends in a wildcard-only segment
(empty after removing every `*`, `?` and `.`) below a root or its parent; one inside no protected root; one
of several segments whose first folder holds a wildcard (it reaches into the root without naming it), and
a single-segment one (it names files directly in app_root) - each its own refusal, unless app_root itself
is a protected root. What is NOT refused any more: a pattern that does not say by its own name that it holds
tests. The list of usual test names (`references/test-path-markers.json`, FR-13) is a suggestion, not a gate
(D-0030): the person's recorded word is the project's word, and an unusual name gets an advisory note.
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hooklib  # noqa: E402
from test_locations import (MARKERS_FILE, _grammar_problem, _match,  # noqa: E402,F401
                            _opens_boundary, _roots, _segments, _text, markers)

# `--block "protected test path: <p>"`: the key of a permission in `stage_overrides[]`.
GRANT_BLOCK = re.compile(r"^\s*protected\s+test\s+path\s*:\s*(.*)$", re.IGNORECASE | re.DOTALL)
UNRECORDED_DATE = "an unrecorded date"

# The refusals of the wave 4 spec (section 5, the branch author's word - D-0025), verbatim.
OPENS_BOUNDARY = ('waiver: "protected test path: {p}" would open {what} - that is the boundary itself, not a '
                  'place for tests. Name the folder or file pattern the tests live in, inside it (for example '
                  '"src/tests/" or "src/**/*.spec.ts"), and record again with the person\'s words.')
BAD_PATTERN = ("waiver: a protected test path is a folder or pattern relative to app_root ({app_root}); "
               "'{p}' is {why}. Write it the way protected_app_paths are written, for example "
               '"src/tests/", and record again.')
OUTSIDE_ROOTS = ("waiver: '{p}' lies inside no protected_app_paths entry ({listed}), so writing there needs "
                 "no permission. Nothing was recorded.")
# D-0030: these two are advice, not refusals. The person's recorded word is the project's word; the markers
# are a suggestion. They are printed after the record, so the person is told and nothing is blocked (FR-4).
NOT_TEST_SPECIFIC = ('waiver: note - "protected test path: {p}" does not carry a usual test name '
                     "(references/" + MARKERS_FILE + " is a suggestion, not a rule); it was recorded as the "
                     "person said it. Application code outside the pattern stays closed.")
MARKERS_BROKEN = ("waiver: note - the list of usual test names (references/" + MARKERS_FILE + ") is {why}, so "
                  'the name of "protected test path: {p}" was not checked; it was recorded as the person '
                  "said it.")
# A pattern is read from app_root, so one whose FIRST FOLDER holds a wildcard reaches into the protected
# root without naming it. It is neither "inside no protected root" (that sentence said such a write needs
# no permission, which is false) nor admitted: it is turned away with the way to write it.
FIRST_FOLDER_WILDCARD = ("waiver: a protected test path is read from app_root ({app_root}), so it has to start "
                         "with the protected folder it opens; the first folder of '{p}' is a wildcard. Write it "
                         'as, for example, "{root}/**/*.spec.ts" or "{root}/tests/", and record again with the '
                         "person's words.")
# A SINGLE segment (`test_*.py`, `foo_test.py`) has no first folder: it names files directly in app_root,
# which is not protected here, so it opens nothing - saying "starts with a wildcard" of it was untrue
# (`test_*.py` starts with a literal) and gave the person nothing to change.
FILES_IN_APP_ROOT = ("waiver: '{p}' names files directly in app_root ({app_root}), outside the protected folder "
                     "'{root}', so it opens nothing there. Write it with the folder, for example "
                     '"{root}/**/{p}", and record again with the person\'s words.')


# --- the protected roots -------------------------------------------------------------------------

def _listed(cfg) -> str:
    entries = [str(e).strip().replace("\\", "/") for e in ((cfg or {}).get("protected_app_paths") or [])
               if isinstance(e, str) and e.strip()]
    return ", ".join(entries) or "none"


def _innermost_root(segs: list, roots: list):
    """The deepest protected root the pattern literally lies inside, as segments, or None."""
    best = None
    for _, root in roots:
        if len(segs) > len(root) and tuple(segs[:len(root)]) == root:
            if best is None or len(root) > len(best):
                best = root
    return best


def _is_test_specific(segs: list, root: tuple, table: dict) -> bool:
    """Does the pattern say by its own path or name that it holds tests: a wildcard-free FOLDER below the
    root named like a test folder, or a last segment whose stem carries a test marker, the marker's
    characters literal? Advice only since D-0030 (`pattern_notes`). The last segment is never read as a
    folder (`src/tests` without a slash is a file named `tests`); a trailing `/` is already a `**`
    segment, so the folder it names counts as a folder."""
    for part in segs[len(root):-1]:
        if "*" in part or "?" in part:
            continue
        if part in table["dir_names"] or any(part.endswith(s) and len(part) > len(s) for s in table["dir_suffixes"]):
            return True
    last = segs[-1]
    stem = last.rpartition(".")[0] if "." in last else last
    return (any(stem.startswith(m) for m in table["stem_prefixes"])
            or any(stem.endswith(m) for m in table["stem_suffixes"]))


def _judge(p, cfg, app_root, loaded: tuple) -> tuple:
    """(refusals, notes) for a pattern: the refusals stop a record, the notes only tell."""
    text = _text(p)
    shown = str(p if p is not None else "").strip()  # as the person's words named it, not normalised
    problem = _grammar_problem(text)
    table, why = loaded
    errors: list = []
    notes: list = []
    if problem:
        errors.append(BAD_PATTERN.format(app_root=app_root, p=shown, why=problem))
    else:
        segs = _segments(text)
        roots = _roots(cfg, app_root)
        opened = _opens_boundary(segs, roots)
        inner = _innermost_root(segs, roots)
        if opened:
            what = (f"the whole of '{opened[0]}'" if opened[1] == "root"
                    else f"the folder that holds '{opened[0]}'")
            errors.append(OPENS_BOUNDARY.format(p=shown, what=what))
        elif inner is None and roots and len(segs) > 1 and ("*" in segs[0] or "?" in segs[0]):
            # (when app_root itself is a protected root `inner` is never None - every pattern lies
            # inside it - so those patterns are judged as before)
            errors.append(FIRST_FOLDER_WILDCARD.format(app_root=app_root, p=shown, root=roots[0][0]))
        elif inner is None and roots and len(segs) == 1:
            errors.append(FILES_IN_APP_ROOT.format(app_root=app_root, p=shown, root=roots[0][0]))
        elif inner is None:
            errors.append(OUTSIDE_ROOTS.format(p=shown, listed=_listed(cfg)))
        elif why:
            notes.append(MARKERS_BROKEN.format(p=shown, why=why))
        elif not _is_test_specific(segs, inner, table):
            notes.append(NOT_TEST_SPECIFIC.format(p=shown))
    return errors, notes


def pattern_errors(p, cfg, app_root) -> list:
    """The refusal texts for a pattern (verbatim, ready to print), or [] when it is admitted. A name that
    is not a usual test name, and a markers file that cannot be read, are not refusals (D-0030)."""
    return _judge(p, cfg, app_root, markers())[0]


def pattern_notes(p, cfg, app_root) -> list:
    """The advisory lines for a pattern that is admitted (verbatim, ready to print), [] when there is
    nothing to say or when the pattern is refused: an unusual name, or a markers file that cannot be read."""
    errors, notes = _judge(p, cfg, app_root, markers())
    return [] if errors else notes


# --- the permission of one story -----------------------------------------------------------------

def is_grant_block(block) -> bool:
    """Is this `--block` / `match` a test-path permission (`protected test path: ...`)?"""
    return bool(GRANT_BLOCK.match(str(block or "")))


def pattern_of(block) -> str:
    """The pattern a `protected test path: <p>` block names; "" for any other block."""
    found = GRANT_BLOCK.match(str(block or ""))
    return found.group(1).strip().strip("`\"'").strip() if found else ""


def date_of(at) -> str:
    """`YYYY-MM-DD` of a stamp, else the unrecorded-date phrase."""
    try:
        moment = datetime.fromisoformat(str(at or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return UNRECORDED_DATE
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).date().isoformat()


def active_grants(pipeline, cfg, app_root) -> list:
    """[{pattern, words, at, stage}] of the permissions in `stage_overrides[]` that are live: not
    revoked, with the person's words, and passing `pattern_errors` NOW (read time, same function)."""
    loaded = markers()
    out = []
    for entry in (pipeline or {}).get("stage_overrides") or []:
        if not isinstance(entry, dict) or entry.get("revoked_at"):
            continue
        pattern = pattern_of(entry.get("match"))
        words = str(entry.get("decision") or "").strip()
        if not pattern or not words or _judge(pattern, cfg, app_root, loaded)[0]:
            continue
        out.append({"pattern": pattern, "words": words, "at": str(entry.get("at") or ""),
                    "stage": str(entry.get("stage") or "")})
    return out


def grant_for(pipeline, target, cfg, app_root) -> dict:
    """The live permission that covers this target (compared RESOLVED: `hooklib.norm`), or {}.

    The latest recorded one when several cover it. A target outside app_root is covered by none."""
    base = hooklib.norm(str(app_root)).rstrip("/")
    full = hooklib.norm(str(target))
    if not full.startswith(base + "/"):
        return {}
    path = tuple(s for s in full[len(base) + 1:].split("/") if s)
    found: dict = {}
    for grant in active_grants(pipeline, cfg, app_root):
        if path and _match(tuple(_segments(_text(grant["pattern"]))), path):
            found = grant
    return found
