#!/usr/bin/env python3
"""config_view.py: one key of the project's config, not the whole file (speed-cost SC1-8 part A1, release 0.10.3).

TP1-12586: the conductor and the tester read the 52 187-character config whole. `config_view.py --keys` / `--get` is the smaller
door; the stage cards print the values their `config:` line names through `card_values`.

Each check names the ONE mutation it kills:
  absent                  a key that is not there is printed as `null` / empty instead of `PATH: absent` (+ absent_means, nearest prefix)
  container over cap      a container over 6000 bytes is printed cut, or the 6000 / 6001 boundary moves
  keys over cap           a listing over 6000 bytes is printed whole / loses its pointer / the file lacks a key; the boundary moves
  save failure            a listing that cannot be saved hides keys instead of printing them whole
  unreadable exit 4       an empty / non-JSON / non-object config exits 0 or reads as `{}`; no config exits other than 3
  syntax exit 2           an empty segment / a bad pointer escape is guessed at instead of refused
  note marks              a `<key>_note` is listed, or the ` [note]` mark is lost
  pointer                 a key holding a dot cannot be asked (the pointer form is read as dotted)
  mangled pointer         a path Git Bash already rewrote (`C:/Program Files/Git/a/b`, `A:/b`, `#A:/b`) is answered as an absent key instead of refused with the door
  cut line                a cut listing line carries two cut marks, or the pointer is not detector_verdict's wording
  atomic_text             the saver writes a shared temp name, translates newlines, raises on a lone surrogate, or loses the WinError retry
  card values             a card value over 600 bytes is printed (cut) instead of its shape and door; an absent key reads as empty
"""
import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import config_view  # noqa: E402
import detector_verdict  # noqa: E402
import event_store  # noqa: E402

DASH = "—"   # the em dash of `detector_verdict._pointer`
EXACT = {"v": "x" * 20}   # a small object whose compact JSON length is the card limit under test
E_ACUTE = "café"   # no Cyrillic in the package (FR-30): a non-ASCII value is an escape


def write_config(project: Path, cfg) -> None:
    (project / "qa-factory" / "config.json").write_text(cfg if isinstance(cfg, str) else json.dumps(cfg), encoding="utf-8")


def run(project: Path, *args):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    return harness.run_script("config_view.py", *args, cwd=project, env=env)


def pad_object(size: int) -> dict:
    """An object whose `json.dumps(indent=1)` is exactly `size` UTF-8 bytes."""
    base = len(json.dumps({"a": ""}, indent=1).encode("utf-8"))
    return {"a": "x" * (size - base)}


project = temp_project("qa-cv-")
use_project(project)
try:
    cfg = {
        "app_root": "services/app",
        "app_root_note": "where the app lives",
        "adapters": {"ticket": {"name": "jira", "direct_api": True}, "vcs": {"name": "git"}},
        "code_repos": ["repo-a", "repo-b"],
        "environments": {"a.b": {"url": "http://stand"}, "plain": 1},
        "accent": E_ACUTE,
        "nothing": None,
    }
    write_config(project, cfg)

    # --- --get -----------------------------------------------------------------------------------------------
    r = run(project, "--get", "adapters.ticket.name")
    check_eq("get scalar: the value as JSON, exit 0", (r.returncode, r.stdout.strip()), (0, '"jira"'))
    r = run(project, "--get", "code_repos.1")
    check_eq("get array index: a numeric segment indexes", r.stdout.strip(), '"repo-b"')
    r = run(project, "--get", "adapters.ticket")
    check_eq("get object: the value whole, indent=1", r.stdout.strip(), json.dumps(cfg["adapters"]["ticket"], indent=1))
    r = run(project, "--get", "accent")
    check_eq("get non-ASCII: UTF-8 on the stream, not an escape", r.stdout.strip(), json.dumps(E_ACUTE, ensure_ascii=False))
    r = run(project, "--get", "nothing")
    check_eq("get null: a present null is `null`, not absent", (r.stdout.strip(), "absent" in r.stdout), ("null", False))
    r = run(project, "--get", "/environments/a.b")
    check_eq("pointer: a key holding a dot is asked by /pointer", r.stdout.strip(), json.dumps(cfg["environments"]["a.b"], indent=1))
    r = run(project, "--get", "environments.a.b")
    check_in("pointer: the dotted form of that key is absent (not guessed)", "environments.a.b: absent", r.stdout)
    r = run(project, "--get", "app_root", "code_repos.0")
    check_eq("get several: a `== PATH` header per value", r.stdout.splitlines()[0::2][:2], ["== app_root", "== code_repos.0"])
    # Git Bash on Windows (MEASURED, t-1331): `/adapters/ticket` arrives as `C:/Program Files/Git/adapters/ticket`, `/a/b` as `A:/b`, and the
    # RFC 6901 fragment `#/a/b` as `#A:/b` - so the fragment form is no door. The door that works is MSYS_NO_PATHCONV=1, and an argument
    # that already arrived rewritten is refused with it instead of answered as an absent key.
    for label, mangled in (("the Program Files form", "C:/Program Files/Git/adapters/ticket"), ("a drive from the first segment", "A:/b"),
                           ("the fragment form", "#A:/b"), ("a lower-case drive", "c:/x/y")):
        r = run(project, "--get", mangled)
        check_eq(f"mangled pointer, exit 2: {label}", (r.returncode, r.stdout), (2, ""))
        check_in(f"mangled pointer: {label} - the door is named", "MSYS_NO_PATHCONV=1", r.stderr)
    r = run(project, "--keys", "C:/Program Files/Git/adapters")
    check_eq("mangled pointer: --keys is refused too", (r.returncode, "MSYS_NO_PATHCONV=1" in r.stderr), (2, True))
    check_in("mangled pointer: the card line says it is not a config path", "not a readable config path",
             config_view.card_values(["C:/Program Files/Git/adapters"])[0])
    r = run(project, "--get", "/environments/a.b")
    check_eq("pointer as typed (MSYS_NO_PATHCONV=1 or any other shell) still works", r.stdout.strip(), json.dumps(cfg["environments"]["a.b"], indent=1))
    check_in("pointer: the example names the Git Bash door", "MSYS_NO_PATHCONV=1", config_view.EXAMPLE)
    check_in("pointer: --help names the Git Bash rewrite and the way round", "MSYS_NO_PATHCONV=1", " ".join(run(project, "--help").stdout.split()))
    check_eq("absent_means takes the path only (no dead parameter)", config_view.absent_means(["no_such_key_at_all"]), "")

    # --- absent: an answer, never null, never a substitute ----------------------------------------------------
    r = run(project, "--get", "protected_app_paths")
    check_eq("absent: exit 0 (an answer, not an error)", r.returncode, 0)
    check_in("absent: `PATH: absent` and what the table says an absent key means", "protected_app_paths: absent (absent_means: ", r.stdout)
    check_in("absent: the nearest existing prefix is named (the root)", "nearest existing prefix: (root)", r.stdout)
    check_in("absent: the root's keys follow", "app_root  string 12 chars", r.stdout)
    r = run(project, "--get", "adapters.ticket.nope")
    check_in("absent nested: the key", "adapters.ticket.nope: absent", r.stdout)
    check_in("absent nested: nearest prefix and its keys", "nearest existing prefix: adapters.ticket - object 2 keys", r.stdout)
    check_in("absent nested: keys of the prefix", "direct_api  true", r.stdout)
    check_not_in("absent nested: no value is substituted", "jira", r.stdout.split("nearest existing", 1)[0])
    r = run(project, "--get", "code_repos.2")
    check_in("absent index past the end: absent, array named", "nearest existing prefix: code_repos - array 2 items", r.stdout)
    r = run(project, "--get", "app_root.deeper")
    check_in("absent inside a scalar: absent, the scalar named", "nearest existing prefix: app_root - string 12 chars", r.stdout)
    r = run(project, "--get", "code_repos.01")
    check_in("index spelling: `01` is not `1`", "code_repos.01: absent", r.stdout)
    r = run(project, "--get", "dispatch.native_completion_grace_s")
    check_in("absent_means by the dotted table key", "(absent_means: ", r.stdout)

    # --- container over the cap: AT 6000 whole, 6001 keys + the narrower path ---------------------------------
    at = dict(cfg, big=pad_object(6000))
    write_config(project, at)
    r = run(project, "--get", "big")
    check_eq("container AT 6000 bytes: whole", r.stdout.strip(), json.dumps(at["big"], indent=1))
    over = dict(cfg, big=pad_object(6001))
    write_config(project, over)
    r = run(project, "--get", "big")
    check_in("container over cap: the narrower-path line", "value is 6001 bytes; ask a narrower path: config_view.py --get big.<key>", r.stdout)
    check_in("container over cap: its keys", "a  string ", r.stdout)
    check_not_in("container over cap: the value is not printed cut", "xxxxxxxxxx", r.stdout)
    big_scalar = dict(cfg, text="y" * 7000)
    write_config(project, big_scalar)
    r = run(project, "--get", "text")
    check_eq("scalar over the cap: whole, whatever its size", r.stdout.strip(), json.dumps("y" * 7000))

    # --- --keys: a listing over 6000 bytes, AT / BEYOND -------------------------------------------------------
    def keys_config(last_key: str) -> dict:
        body = {f"k{i:03d}": "z" * 99 for i in range(249)}   # `k000  string 99 chars`: 21 characters, 23 bytes with `- `
        body[last_key] = "z" * 99
        return dict(cfg, big=body)

    write_config(project, keys_config("k2490"))   # 249 lines of 23 bytes + 1 separator each, then 24: exactly 6000
    r = run(project, "--keys", "big")
    lines = r.stdout.splitlines()
    check_eq("keys AT 6000: heading + 250 whole lines, no pointer", (len(lines), "more" in r.stdout), (251, False))
    out_file = project / "qa-factory" / "state" / "output" / "config-keys.txt"
    check("keys AT 6000: no file written", not out_file.exists())
    write_config(project, keys_config("k24900"))
    r = run(project, "--keys", "big")
    lines = r.stdout.splitlines()
    check_eq("keys BEYOND (6001): 249 lines + the pointer", (len(lines), lines[-1]),
             (251, f"(+1 more key(s) {DASH} the whole list: qa-factory/state/output/config-keys.txt)"))
    check_eq("pointer: the line is detector_verdict's own wording (axis 17), not a copy",
             lines[-1], detector_verdict._pointer(1, False, [], "key", "config_view", None, where="qa-factory/state/output/config-keys.txt"))
    saved = out_file.read_text(encoding="utf-8").splitlines() if out_file.is_file() else []
    check_eq("keys BEYOND: the file holds EVERY key, the hidden one included", (len(saved), saved[-1:]), (250, ["k24900  string 99 chars"]))
    check_eq("keys BEYOND: no temp file left behind", sorted(p.name for p in out_file.parent.iterdir()), ["config-keys.txt"])
    # a save that cannot happen: `state/output` is a file, so the folder cannot be made
    out_file.unlink()
    (project / "qa-factory" / "state" / "output").rmdir()
    (project / "qa-factory" / "state" / "output").write_text("in the way", encoding="utf-8")
    r = run(project, "--keys", "big")
    lines = r.stdout.splitlines()
    check_eq("save failure: the whole list is printed (heading + 250 lines + the reason)", len(lines), 252)
    check_in("save failure: the reason is said", "could not be saved: ", lines[-1])
    check_in("save failure: the last key is on the screen", "k24900  string 99 chars", r.stdout)
    (project / "qa-factory" / "state" / "output").unlink()

    # a first line that alone is over the cap: `fit` cuts it and marks it with its own `…`; the pointer says a line was cut (one mark, not two)
    write_config(project, dict(cfg, wide={"k" * 7000: 1, "z": 2}))
    r = run(project, "--keys", "wide")
    lines = r.stdout.splitlines()
    check_eq("cut line: one `…` at its end, no `...` after it", (lines[1].endswith("…"), "..." in r.stdout), (True, False))
    check_eq("cut line: the pointer is detector_verdict's wording with the cut and the rest",
             lines[-1], detector_verdict._pointer(1, True, [], "key", "config_view", None, where="qa-factory/state/output/config-keys.txt"))
    check_in("cut line: the pointer says what the mark means", "… marks a line cut here", lines[-1])
    check_eq("cut line: the file holds the whole first line", (out_file.read_text(encoding="utf-8").splitlines()[0].startswith("k" * 7000),
                                                               len(out_file.read_text(encoding="utf-8").splitlines())), (True, 2))
    out_file.unlink()

    # --- --keys: the root, notes, scalars ---------------------------------------------------------------------
    write_config(project, cfg)
    r = run(project, "--keys")
    check_in("keys root: an object child by shape", "adapters  object 2 keys", r.stdout)
    check_in("keys root: a note mark on the key that has a `_note`", "app_root  string 12 chars = \"services/app\" [note]", r.stdout)
    check_not_in("keys root: the note itself is not listed", "app_root_note", r.stdout)
    check_in("keys root: an array by shape", "code_repos  array 2 items", r.stdout)
    check_in("keys root: null is the value", "nothing  null", r.stdout)
    r = run(project, "--keys", "code_repos")
    check_in("keys of an array: index lines", "0  string 6 chars = \"repo-a\"", r.stdout)
    r = run(project, "--keys", "app_root")
    check_in("keys of a scalar: not a container, and the door", "config_view.py --get app_root", r.stdout)
    r = run(project, "--keys", "adapters.nope")
    check_in("keys of an absent prefix: absent + nearest", "adapters.nope: absent", r.stdout)

    # --- exits ------------------------------------------------------------------------------------------------
    for label, args in (("an empty segment", ("--get", "a..b")), ("an empty path", ("--get", "")),
                        ("a trailing dot", ("--get", "adapters.")), ("a bad pointer escape", ("--get", "/a~2b")),
                        ("a bare slash", ("--get", "/")), ("neither --get nor --keys", ())):
        r = run(project, *args)
        check_eq(f"syntax exit 2: {label}", r.returncode, 2)
    r = run(project, "--get", "a..b")
    check_in("syntax exit 2: an example is given", "Examples: ", r.stderr)
    check_eq("syntax exit 2: nothing on stdout (FR-14)", r.stdout, "")

    for label, text in (("empty", ""), ("not JSON", "{oops"), ("a list", "[1, 2]"), ("a string", '"x"')):
        write_config(project, text)
        r = run(project, "--get", "app_root")
        check_eq(f"unreadable exit 4: {label}", (r.returncode, r.stdout), (4, ""))
    check_in("unreadable exit 4: the reader's own door, verbatim", "fix the file by hand, or move it aside", r.stderr)
    write_config(project, "")
    r = run(project, "--keys")
    check_eq("unreadable exit 4: --keys too", r.returncode, 4)

    bare = temp_dir("qa-cv-bare-")
    r = run(bare, "--get", "app_root")
    check_eq("no config exit 3", (r.returncode, r.stdout), (3, ""))
    check_in("no config exit 3: the onboarding door", "/qa-factory:qa-onboarding", r.stderr)
    cleanup(bare)

    # --- card_values: the stage card's reader -----------------------------------------------------------------
    big_value = {"rows": ["r" * 50] * 14}   # 14 x 53 bytes + brackets: over 600 bytes of JSON
    write_config(project, dict(cfg, big_value=big_value, exactly=EXACT))
    use_project(project)
    got = config_view.card_values(["adapters.ticket.name", "code_repos", "big_value", "protected_app_paths", "a..b", "accent"])
    check_eq("card values: a short scalar", got[0], 'adapters.ticket.name: "jira"')
    check_eq("card values: a short array whole, on one line", got[1], 'code_repos: ["repo-a", "repo-b"]')
    check_eq("card values: over 600 bytes - the shape and the door, never a cut JSON",
             got[2], "big_value: object of 1 keys - config_view.py --get big_value")
    check("card values: an absent key says absent with its meaning", got[3].startswith("protected_app_paths: absent (absent_means: "), got[3])
    check_in("card values: a bad path is said, not skipped", "a..b: not a readable config path", got[4])
    check_eq("card values: non-ASCII on the line", got[5], "accent: " + json.dumps(E_ACUTE, ensure_ascii=False))
    one = config_view.card_values(["exactly"], max_bytes=len(json.dumps(EXACT).encode()))
    check_eq("card values AT the limit: whole", one[0], "exactly: " + json.dumps(EXACT))
    one = config_view.card_values(["exactly"], max_bytes=len(json.dumps(EXACT).encode()) - 1)
    check_in("card values BEYOND the limit: the shape", "exactly: object of 1 keys - config_view.py --get exactly", one)
    write_config(project, "{broken")
    check_eq("card values, unreadable config: one line, not empty values",
             config_view.card_values(["app_root", "code_repos"]), ["qa-factory/config.json is unreadable - `config_view.py --keys` prints why and what to do"])
    (project / "qa-factory" / "config.json").unlink()
    check_eq("card values, no config: the onboarding door in one line",
             config_view.card_values(["app_root", "code_repos"]), ["no qa-factory/config.json - run /qa-factory:qa-onboarding"])

    # --- one atomic writer: event_store.atomic_text (the text twin of atomic_json), no second saver -------------------------
    check("no second saver: scripts/output_save.py is gone", not (harness.SCRIPTS / "output_save.py").exists())
    atomic_dir = project / "qa-factory" / "state" / "atomic"
    target = atomic_dir / "t.txt"
    event_store.atomic_text(target, "a\nb\n")
    check_eq("atomic_text: the folder is made and the bytes are the text's bytes (no newline translation)", target.read_bytes(), b"a\nb\n")
    event_store.atomic_text(target, "x\ud800y")
    check_eq("atomic_text: a lone surrogate is written as `?`, never raised", target.read_bytes(), b"x?y")
    names, real_replace = [], os.replace

    def spy(src, dst):
        names.append(Path(src).name)
        real_replace(src, dst)

    with mock.patch("event_store.os.replace", spy):
        event_store.atomic_text(target, "1")
        event_store.atomic_text(target, "2")
    check("atomic_text: each write has its own temp name (two writers never share one)",
          len(set(names)) == 2 and all(n.startswith("t.txt.") and n.endswith(".tmp") for n in names), str(names))
    check_eq("atomic_text: no temp file is left", sorted(p.name for p in atomic_dir.iterdir()), ["t.txt"])
    attempts = []

    def flaky(src, dst):
        attempts.append(1)
        if len(attempts) == 1:
            error = PermissionError(5, "Access is denied", str(dst))
            error.winerror = 5
            raise error
        real_replace(src, dst)

    with mock.patch("event_store.os.replace", flaky), mock.patch("event_store._is_windows", lambda: True), \
            mock.patch("event_store.time.sleep", lambda seconds: None):
        event_store.atomic_text(target, "after the retry")
    check_eq("atomic_text: a reader holding the target (WinError 5) is ridden out, as atomic_json rides it",
             (target.read_text(encoding="utf-8"), len(attempts)), ("after the retry", 2))
    blocked = project / "qa-factory" / "state" / "blocked"
    blocked.write_text("in the way", encoding="utf-8")
    try:
        event_store.atomic_text(blocked / "x.txt", "t")
        raised = ""
    except OSError as exc:
        raised = type(exc).__name__
    check("atomic_text: a folder that cannot be made is an OSError for the caller to say in words", bool(raised), raised)
finally:
    cleanup(project)

finish("test_config_view")
