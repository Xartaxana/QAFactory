"""Is this a test file? The one leaf that every consumer asks (B-407 A, D-0030).

Nine places used to decide it with nine private rules. The project's own word and the usual test names are
read by `test_locations.is_test_path` (the six-key verdict) and `test_locations.markers()`; this module is
the question the consumers actually ask, answered per consumer, because the unsafe error differs:

  consumer     asked by                                  the unsafe error        the rule (v = the verdict)
  "commit"     stage_guard commit shape                  a test commit unchecked  v.test or markers
  "test_code"  validate_artifacts.is_test_code (C)       detectors skipped        a code file and (markers or
                                                                                  (v.test and v.source not in
                                                                                  {tests_root, roots.test}))
  "production" `file_kind` (handoff_check, exit_gate,    a production file lost   v.test AND the file lies UNDER a test
               runtime_probe)                                                     place: the project's word, a classic
                                                                                  folder, or a usual name beside a usual
                                                                                  folder / a place the config names; a
                                                                                  name ALONE never (G1-1, see below)
  "test_body"  arch_check, repo_map (advice)             noise                    names_a_test or a config file
               guard_pre_tool.window_file_check          a test body unclaimed:   (the same verdict; only a literal True
               (a window claims a test file)             two windows tear it      claims; False or None passes: a fence on a
                                                                                  write, outside FR-59's scope, declared pass)
  "test_place" repo_map helper (advice)                  noise                    v.test
  "name"       judge_run.wanted_names                    noise                    a segment names a test or is a
                                                                                  test folder name

`markers` here means `names_a_test(p) or in_test_folder(p)`, evaluated directly on the path as written, past
step 3 of the verdict (which hides the usual names inside application code when the project has named its
test locations). Every answer is True, False, or None: None is "the usual test names could not be read"
(one stderr note names the file), and the table says what each consumer does with it (a commit is checked, a
production file stays counted, nothing is skipped). Nothing here raises: an exception is None.

The "production" question is asked through `file_kind(path, ...)` (the one rule of "is this a production file", G1-1; the
consumers differ only in the kinds they take and in whether they can bind the project's word to a checkout):

  kind        what it is                                                     taken by
  "test"      under a test place (the consumer table's "production" row)    nobody (a test is outside every count)
  "docs"      `.md`, or a document / image under a `docs` folder (`.txt     nobody
              .rst .adoc .png .jpg .jpeg .gif .svg .pdf`); anything else
              under `docs/` is production: `docs/conf.py`, `docs/db/schema.sql`
  "generated" `.lock`                                                        nobody
  "config"    `.txt .json .jsonl .yaml .yml .toml .cfg .ini`                 handoff_check (counted in the S1 size figure)
  "production" everything else, and every file whose kind cannot be told     handoff_check, exit_gate, runtime_probe

The priority is the order of the table; the error direction is ONE: a file is `test` or `docs` only on positive evidence, and
every doubt (`None` from the markers, an extension no list names, a test-looking name outside a test place:
`scripts/test_files.py`, `src/app/test_mode.py`) is "production", i.e. a file counted too many times over, never one counted too few.

Stdlib only; `test_locations` is imported where it is asked (a hook that never meets a test path never loads
it).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CONSUMERS = ("commit", "test_code", "production", "test_body", "test_place", "name")
# The "production" consumer drops a file from handoff_check's count (a terminal figure) and from exit_gate's list of new modules;
# the unsafe error is the second: a new production file taken for a test escapes the grounding gate.
# A file is a test for it only when it lies UNDER a test place (G1-1, 19.10.2026; before, a test-looking NAME alone was
# enough and dropped `scripts/test_files.py`, `src/app/test_mode.py`, every colocated `a_test.go` / `a.test.ts`): a classic
# folder (`test`, `tests`, `__tests__`, `test-harness`, exactly as written) is a test place by itself; a usual name (any
# kind: `test_` prefix, `_test` / `.test` / `.spec` endings, camel endings) needs a usual folder (`spec/UserSpecs.java`,
# `backend/Tests/XTests.cs`) or a place the config names (`roots.test`, `tests_root`, `run.levels`) beside it, so
# `src/ABTest.java`, `src/SpeedTest.ts`, `api/spec/openapi.py` and `src/app/test_mode.py` stay counted as production.
# The classic FOLDERS are DATA (FR-13): the `classic` sub-table of the markers file. These constants are the FLOOR, used only
# when that sub-table cannot be read (absent, not an object, or a key that is not a list of non-empty strings): then all
# three floors apply together, never a mix of data and floor. `prefixes` / `suffixes` no longer decide anything here
# (a name alone is not a test place); they stay in the data and the floors until G2-1 retires or reuses them.
CLASSIC_PREFIXES = ("test_",)
CLASSIC_SUFFIXES = ("_test", ".test", ".spec")
CLASSIC_FOLDERS = ("test", "tests", "__tests__", "test-harness")
# Carriers of where the project's tests are (`test_locations.is_test_path` source): they never grant anything, but a usual
# name inside one of them is a test (a helper in the same place stays production).
PLACE_SOURCES = ("run.levels", "roots.test", "tests_root")
# The kinds `file_kind` answers, in priority order, and the extension lists of the non-code kinds. ONE copy (they were three:
# handoff_check, exit_gate, runtime_probe); data in `references/` with G2-1 (FR-13 debt, one line).
KINDS = ("test", "docs", "generated", "config", "production")
DOC_EXTENSIONS = (".md",)
DOC_FOLDER = "docs"
# Under a `docs` folder a file is `docs` ONLY on positive evidence: its extension is a document or an asset of one. Everything
# else there is code or data and stays production (`docs/db/schema.sql`, `docs/build.sh`, `docs/site/App.vue`, `docs/native/main.c`,
# `docs/site/index.html`, `docs/site/app.js`, `docs/data.csv`, `docs/conf.py`, `docs/Dockerfile`): the closed list of CODE extensions
# this replaced (`code_extensions`) lost every code file whose extension was not on it. A list of documents can be wrong only
# toward an extra production file. Data later (FR-13 debt, with G2-1), next to CONFIG_EXTENSIONS.
DOC_FOLDER_EXTENSIONS = (".txt", ".rst", ".adoc", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf")
GENERATED_EXTENSIONS = (".lock",)
CONFIG_EXTENSIONS = (".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".cfg", ".ini")
MARKERS_FILE = "test-path-markers.json"
# The FR-59 safe default a consumer applies when `is_code_file` returns None (the code extensions cannot be read): these files count as code.
CODE_EXTENSION_FLOOR = (".py", ".js", ".ts", ".tsx", ".java", ".kt", ".rb", ".go", ".cs")

_NOTED: set = set()


def _tl():
    import test_locations
    return test_locations


def _note(text: str) -> None:
    """One line on stderr per process and text: the file that could not be read, never a refusal."""
    if text not in _NOTED:
        _NOTED.add(text)
        print(f"test_files: {text}", file=sys.stderr)


def markers() -> tuple:
    """`test_locations.markers()`: ({lists}, "") or ({}, why). The one loader."""
    return _tl().markers()


def _table():
    """The loaded lists, or None (one stderr note) when the usual test names cannot be read."""
    table, why = markers()
    if why:
        _note(f"references/{MARKERS_FILE} is {why}, so the usual test names cannot be read and no name is taken for a "
              "test; expected: the package's own file, a JSON object of lists. Restore it from the installed package; until "
              "then each consumer applies its own default (a commit is checked, a production file stays counted, "
              "nothing is skipped)")
        return None
    if table.get("extras_problem"):
        _note(f"references/{MARKERS_FILE}: {table['extras_problem']}; the lists it names are empty "
              "(CamelCase names are not recognised, no extension is a code file)")
    return table


def _raw() -> dict:
    """The markers file as an object ({} when it cannot be read), for the keys `test_locations.markers()` does not carry
    (`classic`, `fence_languages`): the same loader, so a file that cannot be read is read as unreadable by both."""
    import hooklib
    raw = hooklib.load_ref_json(MARKERS_FILE)
    return raw if isinstance(raw, dict) else {}


def _strings(value):
    """A list of non-empty strings, else None."""
    if isinstance(value, list) and all(isinstance(item, str) and item.strip() for item in value):
        return [item.strip() for item in value]
    return None


def _classic() -> dict:
    """{"prefixes", "suffixes", "folders"}: the `classic` sub-table of the markers file, or the three floors together
    when it is absent or any of its keys is malformed. An EMPTY list is readable: it narrows the classic set, and a
    narrower classic set only keeps a production file that was dropped before (the safe direction)."""
    floor = {"prefixes": list(CLASSIC_PREFIXES), "suffixes": list(CLASSIC_SUFFIXES), "folders": list(CLASSIC_FOLDERS)}
    data = _raw().get("classic")
    if not isinstance(data, dict):
        return floor
    got = {key: _strings(data.get(key)) for key in floor}
    return floor if any(value is None for value in got.values()) else got


def fence_language(path) -> str:
    """The word that opens a markdown code fence for this file's extension (`fence_languages` in the markers file), or
    "" for a bare fence: an extension with no entry, a path with no extension, a table that is absent, not an object or
    holds a non-string word. Nothing here raises."""
    try:
        parts, folder = _parts(path)
        table = _raw().get("fence_languages")
        word = table.get(_extension_of(parts, folder)) if isinstance(table, dict) else None
        return word.strip() if isinstance(word, str) else ""
    except Exception:
        return ""


def _parts(path) -> tuple:
    """(segments as written, names a folder): `\\` is `/`, empty and `.` segments are dropped, a trailing `/`
    makes the last segment a folder."""
    text = str(path if path is not None else "").replace("\\", "/")
    return [s for s in text.split("/") if s not in ("", ".")], text.endswith("/")


def _name_hit(parts: list, folder: bool, table: dict) -> bool:
    return bool(parts) and not folder and bool(_tl().name_marker(parts[-1], table))


def _folder_hit(parts: list, folder: bool, table: dict) -> bool:
    return any(_tl().dir_marker(part.lower(), table) for part in (parts if folder else parts[:-1]))


def names_a_test(name_or_path):
    """Does the LAST segment (a file name, original case) carry a usual test name? None when the names cannot be
    read. A path that names a folder (a trailing `/`) has no file name: False."""
    table = _table()
    if table is None:
        return None
    parts, folder = _parts(name_or_path)
    return _name_hit(parts, folder, table)


def in_test_folder(path):
    """Does a folder segment equal a `dir_names` entry or end with a `dir_suffixes` entry (lower-cased)? A
    trailing `/` makes the last segment a folder too. None when the names cannot be read."""
    table = _table()
    if table is None:
        return None
    parts, folder = _parts(path)
    return _folder_hit(parts, folder, table)


def _extension_of(parts: list, folder: bool) -> str:
    if folder or not parts or "." not in parts[-1]:
        return ""
    return "." + parts[-1].rpartition(".")[2].lower()


def is_code_file(path):
    """Is the file's extension one of `code_extensions`? None when that list is unknown (absent or malformed in
    the markers file: an empty list is an unknown, not "no file is code")."""
    table = _table()
    if table is None or not table.get("code_extensions"):
        return None
    parts, folder = _parts(path)
    return _extension_of(parts, folder) in table["code_extensions"]


def verdict(path, cfg, *, base=None, root=None) -> dict:
    """`test_locations.is_test_path`, the six-key verdict, passed through."""
    return _tl().is_test_path(path, cfg, base=base, root=root)


def _by_names(parts: list, folder: bool, table: dict) -> bool:
    return _name_hit(parts, folder, table) or _folder_hit(parts, folder, table)


def _production_names(parts: list, folder: bool, table: dict, source: str = "") -> bool:
    """Does the path lie UNDER a test place, so that it leaves the production files? A classic folder does alone (it is a
    test place); a usual name needs a usual folder beside it, or a place the config names (`source`); a name ALONE never
    does: `src/app/test_mode.py` is application code."""
    folders = parts if folder else parts[:-1]
    if any(part in _classic()["folders"] for part in folders):
        return True
    return _name_hit(parts, folder, table) and (_folder_hit(parts, folder, table) or source in PLACE_SOURCES)


def _decide(consumer: str, path, cfg, base, root):
    table = _table()
    parts, folder = _parts(path)
    if consumer == "name":
        if table is None:
            return None
        return _name_hit(parts, folder, table) or bool(parts and parts[-1].lower() in table["dir_names"])
    v = verdict(str(path if path is not None else "").replace("\\", "/"), cfg if isinstance(cfg, dict) else {},
                base=base, root=root)
    if consumer == "test_place":
        return True if v["test"] else (None if table is None else False)
    if consumer == "test_body":
        if _is_config_file(v):
            return True
        return None if table is None else _name_hit(parts, folder, table)
    if consumer == "commit":
        if v["test"]:
            return True
        return None if table is None else _by_names(parts, folder, table)
    if consumer == "production":
        if not v["test"]:
            return None if table is None else False
        if v["source"] == "test_locations":
            return True     # the person's word names it, alone
        return None if table is None else _production_names(parts, folder, table, v["source"])
    # test_code: a code file, then the usual names, or the project's word unless it names a folder that is not
    # wholly tests (tests_root / roots.test). "Under tests_root" is the caller's: it holds the root.
    if table is None or not table.get("code_extensions"):
        return None
    if _extension_of(parts, folder) not in table["code_extensions"]:
        return False
    return _by_names(parts, folder, table) or (v["test"] and v["source"] not in ("tests_root", "roots.test"))


def _is_config_file(v: dict) -> bool:
    """A file the project's own word names one by one (a `test_locations` entry or a `run.levels` pattern that
    ends in a file shape): it is a test body whatever its name."""
    return v["by"] == "config" and v["kind"] == "file"


def is_test_for(consumer: str, path, cfg=None, *, base=None, root=None):
    """True / False / None for one consumer (see the module's table). `base` is the folder a relative `path` is
    taken from (a commit's cwd, the implementation checkout), `root` the project root. An unknown consumer is a
    programming error (ValueError); any other failure is None."""
    if consumer not in CONSUMERS:
        raise ValueError(f"unknown consumer {consumer!r}: one of {', '.join(CONSUMERS)}")
    try:
        return _decide(consumer, path, cfg, base, root)
    except Exception:
        return None


def file_kind(path, cfg=None, *, base=None, root=None) -> str:
    """One of KINDS for a path as a diff writes it: the one answer to "is this a production file" (G1-1, axis 9).

    `test` first (the "production" consumer: under a test place, `is True`), then `docs` (`.md`; or a file under a `docs`
    folder whose extension is in `DOC_FOLDER_EXTENSIONS`, a document or an image: `docs/schema.sql`, `docs/conf.py` and
    `Docs/guide.py` are production), then `generated`, then `config`, else `production`. Every doubt is `production` (a file
    counted too many times over, never one counted too few): `None` from the markers, an extension nobody listed, a test-looking name outside a test
    place. `cfg` / `base` / `root`
    are `is_test_for`'s: pass `cfg` only with the checkout the path is relative to (`base`); without them the usual names
    decide. Nothing here raises."""
    text = str(path if path is not None else "").replace("\\", "/")
    if is_test_for("production", text, cfg, base=base, root=root) is True:
        return "test"
    parts, _folder = _parts(text)
    name = parts[-1] if parts else ""
    if name.endswith(DOC_EXTENSIONS):
        return "docs"
    if any(part.lower() == DOC_FOLDER for part in parts[:-1]) and _extension_of(parts, False) in DOC_FOLDER_EXTENSIONS:
        return "docs"
    if name.endswith(GENERATED_EXTENSIONS):
        return "generated"
    if name.endswith(CONFIG_EXTENSIONS):
        return "config"
    return "production"


def production_files(paths, kinds, cfg=None, *, base=None, root=None) -> list:
    """The paths of `kinds` (a collection of KINDS), in the order given, each once. The consumers' common filter: handoff_check
    takes {"production", "config"}, exit_gate and runtime_probe {"production"}."""
    wanted = set(kinds)
    out: list = []
    seen: set = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        if file_kind(path, cfg, base=base, root=root) in wanted:
            out.append(path)
    return out
