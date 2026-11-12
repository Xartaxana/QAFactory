#!/usr/bin/env python3
"""A person's words reach the record whole: `--words-file` (legacy-2406 wave 3, node W3-W1, M30).

TP2-2406, gate B: the person's answer was three paragraphs and ended "local only, do not
publish". Every command that records a person's words took them only as a command-line argument,
cmd.exe stops reading a command line at the first line break (before the launcher runs), and the
receipt kept the first paragraph. The restriction was lost silently.

The fix is one reader, `person_words.read(inline, path, flag)`, and one option name,
`--words-file <path>`, on every CLI that records a person's words in this node: controller
`gate-decision` and `release`, waiver (every form), archive_task, project_decisions `resolve`.
Inline words that arrive through the cmd launcher are refused (a cut text must never be recorded);
inline words by plain python keep working.

This file walks the reader (magnitude, nesting, encoding, empty and broken input), each CLI end to
end through plain python, the controller through the REAL launcher (hooks/run-py.cmd, Windows
only), the pre-tool guard (FR-39: the orchestrator may Write `state/words/<name>.txt`), `--help`
naming the option, and the texts the orchestrator reads.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import (PLUGIN_ROOT, SCRIPTS, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, run_script, temp_dir, temp_project)

sys.path.insert(0, str(SCRIPTS))
import person_words  # noqa: E402
import run_py_entry  # noqa: E402
from content_size import content_bytes  # noqa: E402

import test_controller_rework_scope as SCOPED  # noqa: E402
import test_controller_release as REL  # noqa: E402
import test_controller_state as BASE  # noqa: E402
from controller import Controller  # noqa: E402

WIN = os.name == "nt"
LAUNCHER = PLUGIN_ROOT / "hooks" / "run-py.cmd"
FLAG = "--words-file"

# The words of the incident, shape and all: paragraphs, a quoted NEGATIVE instruction, a last line.
WORDS = 'Approve.\n\nScope: local only - "do not publish" to Jira.\nKeep the MR closed.\n'
NEGATIVE = '"do not publish" to Jira'
# Built from code points: this file is part of the package, and the package carries no Cyrillic.
CYRILLIC = "".join(chr(c) for c in (0x414, 0x430, 0x2c, 0x20, 0x43e, 0x434, 0x43e, 0x431, 0x440, 0x44f,
                                    0x44e, 0x2e, 0x20, 0x41d, 0x435, 0x20, 0x43f, 0x443, 0x431, 0x43b,
                                    0x438, 0x43a, 0x43e, 0x432, 0x430, 0x442, 0x44c, 0x2e))
EMOJI = "ok \U0001F600 \U0001F44D"
NESTING = ['"', "'", "C:" + chr(92) + "d" + chr(92), '{"a":1}', "%PATH%", "^&|<>"]


def jload(text: str) -> dict:
    """A CLI's stdout as an object; a red run reports the missing field, not a traceback."""
    try:
        return json.loads(text)
    except ValueError:
        return {}


# A file that was named and holds no words: zero bytes, a BOM only, spaces, CRLF and tabs.
EMPTY_FILES = (("a zero-byte file", b""), ("a file with only a BOM", b"\xef\xbb\xbf"),
               ("a file with only spaces", b"   "), ("a file with only CRLF and blanks", b" \r\n\t \r\n\r\n"),
               ("a BOM and whitespace", b"\xef\xbb\xbf \r\n"))


def err_of(stderr: str) -> str:
    """The controller prints its refusal as {"error": "..."}: JSON-escaped, so decode it."""
    return jload(stderr).get("error", stderr)


def empty_text(path) -> str:
    return (f"--words-file {path} is empty. Write the person's words to it exactly as they were "
            "given and pass it again; nothing was recorded.")


def put(directory: Path, name: str, data: bytes) -> Path:
    path = directory / name
    path.write_bytes(data)
    return path


def refusal_of(inline, path, flag="--words"):
    try:
        return "READ:" + str(person_words.read(inline, str(path) if path is not None else None, flag))
    except person_words.WordsRefused as exc:
        return str(exc)


def via_cmd(value: bool):
    """Pretend (or not) that the launcher's cmd half started this process; returns the restorer."""
    saved = run_py_entry.VIA_CMD
    run_py_entry.VIA_CMD = value

    def restore():
        run_py_entry.VIA_CMD = saved
    return restore


# --- the reader --------------------------------------------------------------------------------

def the_reader_returns_the_file_as_written():
    work = temp_dir("qa-words-reader-")
    try:
        check_eq("the incident's words come back byte for byte",
                 person_words.read(None, str(put(work, "w.txt", WORDS.encode("utf-8"))), "--words"),
                 WORDS)
        check_in("the negative instruction is in what was read", NEGATIVE,
                 person_words.read(None, str(work / "w.txt"), "--words"))
        check_eq("a BOM is removed and nothing else",
                 person_words.read(None, str(put(work, "bom.txt", b"\xef\xbb\xbf" + WORDS.encode("utf-8"))),
                                   "--words"), WORDS)
        crlf = "line one\r\nline two\r\n"
        check_eq("CRLF stays CRLF",
                 person_words.read(None, str(put(work, "crlf.txt", crlf.encode("utf-8"))), "--words"), crlf)
        check_eq("a last line with no newline is recorded as it is",
                 person_words.read(None, str(put(work, "nonl.txt", b"no newline at the end")), "--words"),
                 "no newline at the end")
        padded = "  \n  keep my margins  \n\n"
        check_eq("nothing is stripped by the reader",
                 person_words.read(None, str(put(work, "pad.txt", padded.encode("utf-8"))), "--words"), padded)
        spaced = work / "a folder with spaces"
        spaced.mkdir()
        check_eq("a path with spaces",
                 person_words.read(None, str(put(spaced, "my words.txt", b"spaced")), "--words"), "spaced")
        # a relative path resolves against the current directory, like any CLI path
        here = os.getcwd()
        os.chdir(work)
        try:
            check_eq("a relative path resolves against the current directory",
                     person_words.read(None, "w.txt", "--words"), WORDS)
        finally:
            os.chdir(here)
        # magnitude: no limit is introduced
        big = ("0123456789abcdef" * 64 + "\n") * 100          # about 100 KB
        check("the magnitude case really is 100 KB", len(big) >= 100 * 1024, str(len(big)))
        check_eq("100 KB comes back whole",
                 person_words.read(None, str(put(work, "big.txt", big.encode("utf-8"))), "--words"), big)
        # nesting: quotes, a trailing backslash, braces, a percent name, shell syntax
        for sample in NESTING + ["\n".join(NESTING)]:
            got = person_words.read(None, str(put(work, "nest.txt", sample.encode("utf-8"))), "--words")
            check_eq(f"nesting {sample[:24]!r}", got, sample)
        # encoding
        for label, sample in (("Cyrillic", CYRILLIC), ("an emoji", EMOJI), ("both", CYRILLIC + "\n" + EMOJI)):
            check_eq(f"encoding: {label}",
                     person_words.read(None, str(put(work, "enc.txt", sample.encode("utf-8"))), "--words"),
                     sample)
        # inline: unchanged, and a missing option is None (each CLI keeps its own treatment)
        check_eq("inline words by plain python come back as they are",
                 person_words.read("one line", None, "--words"), "one line")
        check_eq("no inline and no file is None", person_words.read(None, None, "--words"), None)
        check_eq("an empty inline value is returned for the CLI's own refusal",
                 person_words.read("", None, "--words"), "")
        # a named file with no words is refused by the reader (see the refusals below); a text with
        # blank lines around its words is not "empty" and comes back untouched
        framed = "\n\r\n  Keep it local.  \r\n\n\n"
        check_eq("leading and trailing blank lines around words are returned as they are",
                 person_words.read(None, str(put(work, "framed.txt", framed.encode("utf-8"))), "--words"),
                 framed)
    finally:
        cleanup(work)


def the_reader_refuses_with_a_door():
    work = temp_dir("qa-words-refusals-")
    try:
        file = put(work, "w.txt", WORDS.encode("utf-8"))
        both = refusal_of("typed words", file, "--decision")
        check_in("both options: names the inline option", "--decision", both)
        check_in("both options: names the file option", FLAG, both)
        check_in("both options: says exactly one", "one", both)
        missing = refusal_of(None, work / "nope.txt")
        check_in("a missing path: names the option", FLAG, missing)
        check_in("a missing path: names the path", "nope.txt", missing)
        check_in("a missing path: says what to do", "write", missing.lower())
        folder = refusal_of(None, work)
        check_in("a directory: names the option", FLAG, folder)
        check_in("a directory: says it is a directory", "directory", folder)
        for label, data in EMPTY_FILES:
            path = put(work, "empty.txt", data)
            text = refusal_of(None, path)
            check_eq(f"{label}: the reader's own refusal, as written", text, empty_text(path))
        utf16 = put(work, "ps5.txt", WORDS.encode("utf-16"))               # what PowerShell 5.1 `>` writes
        text = refusal_of(None, utf16)
        check_in("UTF-16: says to save the file as UTF-8", "UTF-8", text)
        check_in("UTF-16: names the option", FLAG, text)
        check_not_in("UTF-16: nothing was decoded with replacement", "READ:", text)
        nobom = put(work, "u16le.txt", WORDS.encode("utf-16-le"))           # no BOM: NUL after each letter
        check_in("UTF-16 without a BOM is refused too", "UTF-8", refusal_of(None, nobom))
        broken = put(work, "bad.txt", b"fine so far \xff\xfe\xfa and then not")
        text = refusal_of(None, broken)
        check_in("invalid UTF-8: says to save the file as UTF-8", "UTF-8", text)
        check_not_in("invalid UTF-8: not decoded with replacement", "READ:", text)
        restore = via_cmd(True)
        try:
            text = refusal_of("Approve. Keep it local.", None, "--words")
            check_in("inline words through the cmd launcher: names the file option", FLAG, text)
            check_in("inline words through the cmd launcher: says nothing is recorded", "recorded", text)
            check_in("inline words through the cmd launcher: says why (the line break)", "line break", text)
            check_eq("through the cmd launcher the file form still works",
                     person_words.read(None, str(file), "--words"), WORDS)
            check_eq("through the cmd launcher no words at all is None",
                     person_words.read(None, None, "--words"), None)
        finally:
            restore()
        check_eq("by plain python the same inline words are accepted",
                 person_words.read("Approve. Keep it local.", None, "--words"), "Approve. Keep it local.")
    finally:
        cleanup(work)


# --- the controller ----------------------------------------------------------------------------

def gate_a_root():
    root = temp_dir("qa-words-gate-")
    (root / "qa-factory").mkdir(parents=True, exist_ok=True)
    (root / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
    controller = Controller(root)
    controller.apply("initialize", {"scope": ["TC-1"], "source_revision": "src-1",
                                    "known_paths": {"root": str(root)}, "idempotency_key": "init"})
    BASE.seed_plan(root, [SCOPED.plan_row(1, "automate")])
    for number in range(5):
        BASE.accept_stage(controller, root, f"S{number}")
    return root


def decision_of(root):
    return Controller(root).state()["decisions"].get("gateA-" + root.name)


def revision_of(root):
    return Controller(root).state().get("revision")


def gate(root, *words_args, cwd=None):
    return run_script("controller.py", "--task-root", root, "--operation", "gate-decision",
                      "--gate", "A", *words_args, cwd=cwd)


def the_controller_records_gate_words_from_a_file():
    root = gate_a_root()
    work = temp_dir("qa-words-files-")
    try:
        before = revision_of(root)
        for label, args in (("both options", ("--words", "typed", FLAG, str(put(work, "w.txt", WORDS.encode())))),
                            *[(label, (FLAG, str(put(work, f"e{i}.txt", data))))
                              for i, (label, data) in enumerate(EMPTY_FILES)],
                            ("a missing file", (FLAG, str(work / "nope.txt"))),
                            ("a directory", (FLAG, str(work))),
                            ("UTF-16", (FLAG, str(put(work, "u16.txt", WORDS.encode("utf-16"))))),
                            ("inline words, empty", ("--words", ""))):
            result = gate(root, *args)
            check(f"gate-decision refuses {label}: exit 2", result.returncode == 2,
                  f"{result.returncode} {result.stderr[-300:]}")
            check_eq(f"gate-decision refuses {label}: nothing recorded", decision_of(root), None)
            check_eq(f"gate-decision refuses {label}: the revision did not move", revision_of(root), before)
        for i, (label, _data) in enumerate(EMPTY_FILES):
            path = work / f"e{i}.txt"
            check_in(f"gate-decision, {label}: the reader's refusal text", empty_text(path),
                     err_of(gate(root, FLAG, str(path)).stderr))
        empty_inline = gate(root, "--words", "").stderr
        check_in("empty inline words: the controller's own refusal names what is wanted",
                 "person's own words", empty_inline)
        check_in("and names the file door", "Pass --words-file <path to their words, as they were given>",
                 empty_inline)
        check_in("`--help` names the file form", FLAG, run_script("controller.py", "--help").stdout)

        result = gate(root, FLAG, str(put(work, "w.txt", WORDS.encode("utf-8"))))
        check("gate-decision records from a file", result.returncode == 0, result.stderr)
        recorded = decision_of(root)
        check_eq("authorization_source is byte-equal to the file",
                 (recorded or {}).get("authorization_source"), WORDS)
        check_in("and the negative instruction is in it", NEGATIVE, (recorded or {}).get("authorization_source", ""))
        check_eq("the file is left where it was, untouched", (work / "w.txt").read_bytes(), WORDS.encode("utf-8"))
    finally:
        cleanup(work)
        cleanup(root)


def the_controller_keeps_inline_words_by_plain_python():
    root = gate_a_root()
    try:
        result = gate(root, "--words", "approve, keep all automate")
        check("inline words by plain python still record", result.returncode == 0, result.stderr)
        check_eq("exactly as typed", (decision_of(root) or {}).get("authorization_source"),
                 "approve, keep all automate")
        check("stdout is still one JSON object", jload(result.stdout).get("recorded") is True, result.stdout)
    finally:
        cleanup(root)


def the_controller_releases_from_a_file():
    root = temp_dir("qa-words-release-")
    work = temp_dir("qa-words-release-files-")
    try:
        controller = REL.at_s3_rework(root)
        request = controller.build_rework_request("S3", "qa-test-strategist", [], "redo the plan")
        controller.apply("dispatch", dict(request))
        before = revision_of(root)
        for label, data in EMPTY_FILES:
            path = put(work, "e.txt", data)
            result = run_script("controller.py", "--task-root", root, "--operation", "release",
                                "--dispatch", request["id"], FLAG, str(path))
            check(f"release refuses {label}: exit 2", result.returncode == 2, result.stderr)
            check_in(f"release, {label}: the reader's refusal text", empty_text(path), err_of(result.stderr))
            check_eq(f"release, {label}: records nothing", revision_of(root), before)
        inline = run_script("controller.py", "--task-root", root, "--operation", "release",
                            "--dispatch", request["id"], "--words", "").stderr
        check_in("empty inline words: the controller's own refusal names the file door",
                 "Pass --words-file <path to their words, as they were given>", inline)
        check_eq("and records nothing", revision_of(root), before)
        result = run_script("controller.py", "--task-root", root, "--operation", "release",
                            "--dispatch", request["id"], FLAG, str(put(work, "w.txt", WORDS.encode("utf-8"))))
        check("release records from a file", result.returncode == 0, result.stderr)
        answer = jload(result.stdout)
        check_eq("the words in the answer are byte-equal to the file", answer.get("words"), WORDS)
        check_in("and the negative instruction is there", NEGATIVE, answer.get("words") or "")
    finally:
        cleanup(work)
        cleanup(root)


def the_real_launcher_carries_the_file_and_refuses_inline_words():
    if not WIN:
        print("SKIPPED: not Windows (the cmd route was not run)")
        return
    root = gate_a_root()
    work = temp_dir("qa words with spaces ")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", QA_FACTORY_PYTHON=sys.executable)
    env.pop("QA_FACTORY_LAUNCHER", None)
    try:
        def launch(tail):
            proc = subprocess.run(f'"{LAUNCHER}" controller.py --task-root "{root}" --operation '
                                  f"gate-decision --gate A {tail}", shell=True, capture_output=True,
                                  cwd=str(work), env=env, timeout=300)
            return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")

        before = revision_of(root)
        words = put(work, "the words.txt", WORDS.encode("utf-8"))
        # the same words as the incident, inline, with the real line breaks: cmd.exe cuts the line
        code, out, err = launch('--words "' + WORDS + '"')
        check("inline words with line breaks through the cmd launcher are refused", code != 0, f"{code} {out} {err}")
        check_in("the refusal names --words-file", FLAG, err)
        check_eq("nothing was recorded, the journal did not move", revision_of(root), before)
        check_eq("no decision exists", decision_of(root), None)
        code, out, err = launch('--words "Approve. Keep it local."')
        check("a ONE-line inline through the cmd launcher is refused too", code != 0, f"{code} {out} {err}")
        check_in("and names --words-file", FLAG, err)
        check_eq("nothing was recorded either", revision_of(root), before)
        code, out, err = launch(f'{FLAG} "{words}"')
        check("the file form through the cmd launcher records (path with spaces)", code == 0, f"{code} {out} {err}")
        check_eq("byte-equal to the file", (decision_of(root) or {}).get("authorization_source"), WORDS)
        check_in("with the negative instruction", NEGATIVE, (decision_of(root) or {}).get("authorization_source", ""))
    finally:
        cleanup(work)
        cleanup(root)


# --- waiver, archive_task, project_decisions ---------------------------------------------------

def project_env(root):
    return dict(os.environ, CLAUDE_PROJECT_DIR=str(root), PYTHONDONTWRITEBYTECODE="1")


def pipeline_of(root, ticket="QA-1"):
    return json.loads((root / "qa-factory" / "artifacts" / ticket / "pipeline.json").read_text(encoding="utf-8"))


def story(root, pipeline, ticket="QA-1"):
    task = root / "qa-factory" / "artifacts" / ticket
    task.mkdir(parents=True, exist_ok=True)
    (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
    return task


def waiver_records_from_a_file_in_every_form():
    root = temp_project("qa-words-waiver-")
    work = temp_dir("qa-words-waiver-files-")
    try:
        env = project_env(root)
        story(root, {"task": "QA-1", "gates": {"A": {"decision": "approved"}}, "stages": {}})
        words = put(work, "w.txt", WORDS.encode("utf-8"))

        def waiver(*args):
            return run_script("waiver.py", *args, cwd=root, env=env)

        # every form refuses the same broken input and records nothing
        forms = {"gate": ["--task", "QA-1", "--gate", "A", "--requirement", "R-9"],
                 "stage": ["--task", "QA-1", "--stage", "S1", "--block", "source material unavailable"],
                 "revoke": ["--task", "QA-1", "--revoke", "--stage", "S1", "--block", "x"],
                 "remark": ["--task", "QA-1", "--remark", "--stage", "S5"]}
        inline_flag = {"gate": "--decision", "stage": "--decision", "revoke": "--decision", "remark": "--text"}
        before = (root / "qa-factory" / "artifacts" / "QA-1" / "pipeline.json").read_bytes()
        for name, base in forms.items():
            pipeline_file = root / "qa-factory" / "artifacts" / "QA-1" / "pipeline.json"
            for label, data in EMPTY_FILES:
                path = put(work, "e.txt", data)
                empty = waiver(*base, FLAG, str(path))
                check(f"waiver {name}: {label} is refused, exit 2", empty.returncode == 2,
                      f"{empty.returncode} {empty.stderr}")
                check_in(f"waiver {name}: {label}: the reader's refusal text", empty_text(path),
                         " ".join(empty.stderr.split()))
                check_eq(f"waiver {name}: {label}: nothing recorded", pipeline_file.read_bytes(), before)
            inline_empty = waiver(*base, inline_flag[name], "")
            check_eq(f"waiver {name}: empty inline words keep their own refusal, exit 2",
                     inline_empty.returncode, 2)
            both = waiver(*base, FLAG, str(words), inline_flag[name], "typed")
            check(f"waiver {name}: both options are refused", both.returncode == 2, f"{both.returncode} {both.stderr}")
            check_in(f"waiver {name}: the refusal names both options", FLAG, both.stderr)
            check_in(f"waiver {name}: and the inline one", inline_flag[name], both.stderr)
            missing = waiver(*base, FLAG, str(work / "nope.txt"))
            check(f"waiver {name}: a missing file is refused", missing.returncode == 2, missing.stderr)
        check_eq("a refused call leaves pipeline.json untouched",
                 (root / "qa-factory" / "artifacts" / "QA-1" / "pipeline.json").read_bytes(), before)

        mapping = {}
        done = waiver(*forms["gate"], FLAG, str(words))
        check("waiver: the gate-requirement form records from a file", done.returncode == 0, done.stderr)
        mapping["gate"] = pipeline_of(root).get("gate_waivers", [{}])[0].get("decision")
        check_eq("--words-file stands for --decision: the gate waiver is the file, stripped",
                 mapping["gate"], WORDS.strip())
        check_in("and carries the negative instruction", NEGATIVE, mapping["gate"] or "")

        done = waiver(*forms["stage"], FLAG, str(words))
        check("waiver: the stage form records from a file", done.returncode == 0, done.stderr)
        check_eq("--words-file stands for --decision: the stage override is the file, stripped",
                 pipeline_of(root).get("stage_overrides", [{}])[0].get("decision"), WORDS.strip())

        revoke_words = put(work, "r.txt", b"The video is attached now.\r\n\r\nRead it.\r\n")
        done = waiver("--task", "QA-1", "--revoke", "--stage", "S1", "--block", "source material unavailable",
                      FLAG, str(revoke_words))
        check("waiver: the revoke form records from a file", done.returncode == 0, done.stderr)
        check_eq("--words-file stands for --decision: the revoking words are the file, stripped",
                 pipeline_of(root).get("stage_overrides", [{}])[0].get("revoked_decision"),
                 "The video is attached now.\r\n\r\nRead it.")

        done = waiver(*forms["remark"], FLAG, str(words))
        check("waiver: the remark form records from a file", done.returncode == 0, done.stderr)
        check_eq("--words-file stands for --text: the remark is the file, stripped",
                 pipeline_of(root).get("remarks", [{}])[0].get("text"), WORDS.strip())

        inline = waiver("--task", "QA-1", "--remark", "--stage", "S6", "--text", "one typed line")
        check("inline words by plain python still record", inline.returncode == 0, inline.stderr)
        check_eq("exactly as typed", [r["text"] for r in pipeline_of(root).get("remarks", [])][-1:],
                 ["one typed line"])
        check_in("`--help` names the file form", FLAG, waiver("--help").stdout)
        check_in("and the inline refusal of the empty form still says what it needs", "--text",
                 waiver(*forms["remark"], "--text", "").stderr)
    finally:
        cleanup(work)
        cleanup(root)


def archive_task_records_the_note_from_a_file():
    root = temp_project("qa-words-archive-")
    work = temp_dir("qa-words-archive-files-")
    try:
        env = project_env(root)
        story(root, {"ticket": "QA-9", "stages": {}, "halts": []}, "QA-9")

        def archive(*args):
            return run_script("archive_task.py", "--task", "QA-9", *args, cwd=root, env=env)

        both = archive("--note", "typed", FLAG, str(put(work, "w.txt", WORDS.encode("utf-8"))))
        check("archive_task: both options are refused", both.returncode == 2, f"{both.returncode} {both.stderr}")
        check_in("and the refusal names both", "--note", both.stderr)
        check_in("and the file option", FLAG, both.stderr)
        for label, target in (("a missing file", work / "nope.txt"), ("a directory", work)):
            result = archive(FLAG, str(target))
            check(f"archive_task: {label} is refused", result.returncode == 2, f"{result.returncode} {result.stderr}")
        result = archive(FLAG, str(put(work, "u16.txt", WORDS.encode("utf-16"))))
        check("archive_task: UTF-16 is refused", result.returncode == 2, f"{result.returncode} {result.stderr}")
        check_in("and says to save the file as UTF-8", "UTF-8", result.stderr)
        check_eq("a refused call archives nothing", pipeline_of(root, "QA-9").get("archived"), None)
        pipeline_file = root / "qa-factory" / "artifacts" / "QA-9" / "pipeline.json"
        before = pipeline_file.read_bytes()
        for label, data in EMPTY_FILES:
            path = put(work, "e.txt", data)
            result = archive(FLAG, str(path))
            check(f"archive_task: {label} is refused, exit 2", result.returncode == 2,
                  f"{result.returncode} {result.stderr}")
            check_in(f"archive_task: {label}: the reader's refusal text", empty_text(path),
                     " ".join(result.stderr.split()))
            check_eq(f"archive_task: {label}: nothing recorded", pipeline_file.read_bytes(), before)

        result = archive(FLAG, str(put(work, "w.txt", WORDS.encode("utf-8"))))
        check("archive_task records the note from a file", result.returncode == 0, result.stderr)
        check_eq("archived_note is byte-equal to the file", pipeline_of(root, "QA-9").get("archived_note"), WORDS)
        check_in("and carries the negative instruction", NEGATIVE, pipeline_of(root, "QA-9").get("archived_note", ""))
        check_in("stdout keeps its shape", "QA-9: archived at", result.stdout)

        # a second story: CRLF, Cyrillic and an emoji survive the file -> text -> JSON road
        story(root, {"ticket": "QA-8", "stages": {}, "halts": []}, "QA-8")
        wide = chr(0xFEFF) + "line one\r\n" + CYRILLIC + "\r\n" + EMOJI + "\r\n"
        put(work, "wide.txt", wide.encode("utf-8"))
        result = run_script("archive_task.py", "--task", "QA-8", FLAG, str(work / "wide.txt"), cwd=root, env=env)
        check("archive_task: a BOM, CRLF, Cyrillic and an emoji are recorded", result.returncode == 0, result.stderr)
        check_eq("the BOM is gone, the rest is byte-equal", pipeline_of(root, "QA-8").get("archived_note"),
                 wide[1:])
        # blank lines around words are not "empty": recorded byte-equal (archive_task strips nothing)
        story(root, {"ticket": "QA-5", "stages": {}, "halts": []}, "QA-5")
        framed = "\n\r\n  Keep it local.  \r\n\n\n"
        put(work, "framed.txt", framed.encode("utf-8"))
        result = run_script("archive_task.py", "--task", "QA-5", FLAG, str(work / "framed.txt"), cwd=root, env=env)
        check("archive_task: a text with blank lines around its words is recorded", result.returncode == 0,
              result.stderr)
        check_eq("byte-equal, blank lines and all", pipeline_of(root, "QA-5").get("archived_note"), framed)
        # inline behaviour is untouched: no --note and no --words-file still means "no note"
        story(root, {"ticket": "QA-6", "stages": {}, "halts": []}, "QA-6")
        result = run_script("archive_task.py", "--task", "QA-6", cwd=root, env=env)
        check("archive_task with neither option still archives", result.returncode == 0, result.stderr)
        check_eq("with no note", pipeline_of(root, "QA-6").get("archived_note"), None)
        inline = run_script("archive_task.py", "--task", "QA-7", "--note", "typed", cwd=root, env=env)
        check("inline `--note` keeps its behaviour (a story that is not there is still exit 1)",
              inline.returncode == 1, f"{inline.returncode} {inline.stderr}")
        check_in("`--help` names the file form", FLAG, run_script("archive_task.py", "--help").stdout)
    finally:
        cleanup(work)
        cleanup(root)


def project_decisions_resolves_from_a_file():
    root = temp_project("qa-words-decisions-")
    work = temp_dir("qa-words-decisions-files-")
    try:
        env = project_env(root)

        def tool(*args):
            return run_script("project_decisions.py", "--root", root, *args, cwd=root, env=env)

        added = tool("add", "--field-ref", "/x", "--essence", "the x", "--asked", "asked at gate A")
        check("a deferred decision to resolve", added.returncode == 0, added.stderr)
        row_id = jload(added.stdout).get("id", "DD-1")
        resolve = ["resolve", "--id", row_id, "--resolution-ref", "r-1", "--field-values", '{"/x": "v"}']
        both = tool(*resolve, "--decision", "typed", FLAG, str(put(work, "w.txt", WORDS.encode("utf-8"))))
        check("project_decisions: both options are refused", both.returncode == 2, f"{both.returncode} {both.stderr}")
        check_in("and the refusal names both", FLAG, both.stderr)
        missing = tool(*resolve, FLAG, str(work / "nope.txt"))
        check("project_decisions: a missing file is refused", missing.returncode == 2, missing.stderr)
        check_in("a refused call closed nothing", "open",
                 (root / "qa-factory" / "factory-backlog.md").read_text(encoding="utf-8"))
        backlog_file = root / "qa-factory" / "factory-backlog.md"
        receipts = root / "qa-factory" / "state" / "decision-transactions"
        before = backlog_file.read_bytes()
        for label, data in EMPTY_FILES:
            path = put(work, "e.txt", data)
            empty = tool(*resolve, FLAG, str(path))
            check(f"project_decisions: {label} is refused, exit 2", empty.returncode == 2,
                  f"{empty.returncode} {empty.stderr}")
            check_in(f"project_decisions: {label}: the reader's refusal text", empty_text(path),
                     " ".join(empty.stderr.split()))
            check_eq(f"project_decisions: {label}: the registry is untouched", backlog_file.read_bytes(), before)
            check_eq(f"project_decisions: {label}: no receipt was written", receipts.exists(), False)
        result = tool(*resolve, FLAG, str(put(work, "w.txt", WORDS.encode("utf-8"))))
        check("project_decisions resolve records from a file", result.returncode == 0, result.stderr)
        closed = jload(result.stdout)
        check_eq("the decision in the answer is byte-equal to the file", closed.get("decision with witness"), WORDS)
        receipt_path = root / "qa-factory" / "state" / "decision-transactions" / f"{row_id}.json"
        receipt = jload(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else {}
        check_eq("and so is the one in the transaction receipt", receipt.get("decision"), WORDS)
        check_in("with the negative instruction", NEGATIVE, receipt.get("decision") or "")
        neither = tool(*resolve)
        check("without either option resolve is still refused", neither.returncode != 0, neither.stdout)
        check_in("`resolve --help` names the file form", FLAG, tool("resolve", "--help").stdout)
    finally:
        cleanup(work)
        cleanup(root)


# --- FR-39: the orchestrator may write where the words go --------------------------------------

def the_guard_lets_the_orchestrator_write_the_words_file():
    root = temp_project("qa-words-guard-")
    try:
        task = story(root, {"ticket": "QA-1", "stages": {"S8": {"status": "done"}}})
        (task / "state").mkdir(exist_ok=True)

        def write_as_orchestrator(label, name="gateB.txt", expect=0):
            target = task / "state" / "words" / name
            event = {"hook_event_name": "PreToolUse", "session_id": "words-guard", "cwd": str(root),
                     "tool_name": "Write", "tool_input": {"file_path": str(target), "content": WORDS}}
            env = project_env(root)
            proc = subprocess.run([sys.executable, "-B", str(SCRIPTS / "guard_pre_tool.py")],
                                  input=json.dumps(event), capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", cwd=str(root), env=env, timeout=120)
            check_eq(f"the guard {'permits' if expect == 0 else 'refuses'} the orchestrator's Write of "
                     f"state/words/{name} ({label})", proc.returncode, expect)
            if proc.returncode != expect:
                print(proc.stderr[:400])

        write_as_orchestrator("no dispatch open, S8 done")
        (task / "state" / "controller.json").write_text(json.dumps(
            {"dispatches": {"D-1": {"role": "qa-bug-reporter", "status": "running", "stage": "S8"}}, "stages": {}}),
            encoding="utf-8")
        write_as_orchestrator("a role's dispatch is running")
        (task / "pipeline.json").write_text(json.dumps({"ticket": "QA-1", "stages": {"S1": {"status": "running"}}}),
                                            encoding="utf-8")
        write_as_orchestrator("a stage is running")
        # The texts tell the orchestrator to name the file by gate or stage: a secret-file name
        # (`credentials.txt`) is the one thing under state/words/ the guard refuses.
        write_as_orchestrator("a secret-file name", name="credentials.txt", expect=2)
    finally:
        cleanup(root)


# --- the key-presence checks -------------------------------------------------------------------

def help_names(text: str) -> bool:
    return FLAG in text


def every_help_names_the_option():
    for script, args in (("controller.py", ["--help"]), ("waiver.py", ["--help"]),
                         ("archive_task.py", ["--help"]), ("project_decisions.py", ["resolve", "--help"])):
        proc = run_script(script, *args)
        check(f"{script} {' '.join(args)} exits 0 and names {FLAG}", proc.returncode == 0 and help_names(proc.stdout),
              proc.stdout[:200] + proc.stderr[:200])
    check("negative control: a help text without the option fails the key check",
          not help_names("usage: waiver.py [--decision DECISION] [--text TEXT]"))


# The keys are quoted from the node's definition of done, fixed before the run: the conductor
# carries the one rule, and no owned file passes a person's words to these commands inline.
DOCS = {
    # `ticket_adapter.py review --record --words`, `judge_reply.py --reply` and `log_append.py
    # --reason` pass words too, but they are not this node's commands (W3-W2): not checked here.
    # `except_on`: a LINE that names one of these is left out of the `not` check (the `has` check reads
    # the whole text). `source_exclusions.py --revoke --words "<...>"` is an upstream 0.8.1 carrier with
    # no file route, queued B-365; any other inline `--words "<` in the file still fails.
    "references/conductor.md": {"has": [FLAG, "state/words/"], "not": [
        '--words "<', '--decision "<', '--text "<'], "except_on": ["source_exclusions.py"]},
    "references/controller-api.md": {"has": [FLAG], "not": ['--words "<', '--decision "<']},
    "references/artifact-contract-json.md": {"has": [FLAG], "not": ['--decision "<']},
    "skills/qa-story/phases/s4.md": {"has": [FLAG, "state/words/"], "not": [
        '--text "<', '--decision "<', 'gate-decision --gate A --words "']},
    "skills/qa-story/phases/s8.md": {"has": [FLAG, "state/words/"], "not": [
        '--decision "<', '--words "<', '--text "<']},
    "skills/qa-doctor/phases/repair.md": {"has": [FLAG, "state/words/"], "not": ['--words "<']},
    "skills/qa-doctor/phases/archive.md": {"has": [FLAG, "state/words/"], "not": ['--note "<']},
}


def problems_of(text: str, keys: dict) -> list:
    flat = " ".join(text.split())
    out = [f"missing {k!r}" for k in keys["has"] if k not in flat]
    kept = [line for line in text.splitlines() if not any(mark in line for mark in keys.get("except_on", ()))]
    flat_kept = " ".join(" ".join(kept).split())
    out += [f"still has {k!r}" for k in keys["not"] if " ".join(k.split()) in flat_kept]
    return out


def the_texts_the_orchestrator_reads_use_the_file_form():
    for name, keys in DOCS.items():
        text = (PLUGIN_ROOT / name).read_text(encoding="utf-8")
        found = problems_of(text, keys)
        check(f"{name}: the file form, no inline words on these commands", not found, "; ".join(found))
    check("negative control: the key check fails on a text with the inline form",
          bool(problems_of('run controller.py gate-decision --gate A|B --words "<their words, verbatim>"',
                           DOCS["references/conductor.md"])))
    conductor_keys = dict(DOCS["references/conductor.md"], has=[])
    inline = '`{} --task <T> --revoke <X-id> --words "<their words, verbatim>"`'
    check("control: an inline `--words \"<` on a waiver.py line fails the conductor key",
          bool(problems_of(inline.format("waiver.py"), conductor_keys)))
    check_eq("control: the same text on a source_exclusions.py line passes it (B-365)",
             problems_of(inline.format("python <plugin>/scripts/source_exclusions.py"), conductor_keys), [])
    check("control: a waiver.py line right after a source_exclusions.py line still fails",
          bool(problems_of(inline.format("source_exclusions.py") + "\n" + inline.format("waiver.py"), conductor_keys)))
    for name in ("references/controller-api.md", "references/conductor.md"):
        size = content_bytes(harness.PLUGIN_ROOT.joinpath(name))        # the ONE prompt-limit measure (CRLF counted as LF), B-409
        check(f"{name} stays within its 12000-byte cap", size <= 12000, str(size))


def t4c_the_one_writer_of_state_words():
    """T4c (t-721 section L-4 F-23, F-26): `words_file_path` is pure and names the base under
    `<task root>/state/words/`; `write_words` writes the words as given, never over a taken name, and a
    failed write leaves no half file and raises OSError. Mutation (12): the write loses its "x"."""
    import tempfile
    from unittest import mock
    root = Path(tempfile.mkdtemp(prefix="qa-words-writer-"))
    try:
        base = person_words.words_file_path(root, "S5-qa-code-critic-1", "decide hand")
        check_eq("T4c: the base sits under state/words and carries the kind and the dispatch",
                 base, root / "state" / "words" / "driver-decidehand-S5-qa-code-critic-1")
        check_eq("T4c: no dispatch - the base is driver-<kind>",
                 person_words.words_file_path(root, "", "gateA").name, "driver-gateA")
        check_eq("T4c: pure - the same call gives the same path", person_words.words_file_path(
            root, "S5-qa-code-critic-1", "decide hand"), base)
        check("T4c: and creates nothing", not (root / "state").exists())
        for empty in ("", "  \r\n\t ", None):
            check_eq(f"T4c: words {empty!r} write nothing and return None",
                     person_words.write_words(root, "D", "decidehand", empty), None)
        check("T4c: and no folder", not (root / "state").exists())
        text = "first line\r\nsecond " + chr(233) + " line\r\n"
        first = person_words.write_words(root, "D-1", "decidehand", text)
        check("T4c: the file is under the base's folder and named from the base",
              first.parent == base.parent and first.name.startswith("driver-decidehand-D-1-")
              and first.suffix == ".txt", str(first))
        check_eq("T4c: bytes as given - CRLF kept, UTF-8, no BOM", first.read_bytes(), text.encode("utf-8"))
        second = person_words.write_words(root, "D-1", "decidehand", text)
        check("T4c: the same words again are a second, different file (the stamp or -<n>)",
              second != first and second.read_bytes() == first.read_bytes(), f"{first.name} {second.name}")
        # a taken name is never overwritten: freeze the stamp so both calls want the same name
        with mock.patch.object(person_words.time, "time", return_value=1700000000.0):
            one = person_words.write_words(root, "D-2", "decidehand", "one")
            two = person_words.write_words(root, "D-2", "decidehand", "two")
        check("T4c: a taken name is not overwritten - the second words get -<n>",
              one.read_text(encoding="utf-8") == "one" and two.read_text(encoding="utf-8") == "two"
              and one != two, f"{one.name} {two.name}")
        # a failed write: nothing half-written stays, and the error is OSError
        class Broken:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_a):
                return False

            def write(self_inner, _text):
                raise OSError("disk full")
        before = sorted(p.name for p in base.parent.iterdir())
        real_open = open

        def failing_open(path, mode="r", *a, **kw):
            if mode == "x":
                real_open(path, "x").close()          # the name is made, then the write fails
                return Broken()
            return real_open(path, mode, *a, **kw)
        raised = ""
        with mock.patch("builtins.open", failing_open):
            try:
                person_words.write_words(root, "D-3", "decidehand", "words")
            except OSError as exc:
                raised = type(exc).__name__
        check_eq("T4c: a failed write raises OSError", raised, "OSError")
        check_eq("T4c: and leaves no half file", sorted(p.name for p in base.parent.iterdir()), before)
    finally:
        cleanup(root)


def c26_go_on_with_a_block_passes_the_original_words() -> None:
    """t-722 C2-6 §4.5 / §6 p.12: `go on` with `asked.block` hands `waiver.py` the ORIGINAL answer's file (byte for byte); with no original
    file named, the file of the token (the token was all that was said); a file named but gone -> the question is held and `waiver.py`
    is not called (FR-8: the token's file never stands in for words that are lost)."""
    from story_run_common import driver_for, seed
    import story_run
    cwd0 = os.getcwd()          # the Driver chdirs into the temp project; this test puts the process back
    root, task_root, env = seed("QA-9")
    try:
        driver = driver_for(root, env, "QA-9")
        waiver_calls = []
        driver.py = lambda script, *a, **k: (waiver_calls.append(a) if script == "waiver.py" else None, (0, ""))[1]
        original = "the dirty tree is fine,\r\nplease go on with it\r\n"
        rel = driver.words_file(original, "answer").relative_to(driver.task_root).as_posix()
        options = [{"token": "go on", "move": "go_on_as_is"}, {"token": "stop", "move": "stop_here"}]

        def asked(words_file):
            return {"kind": "conductor", "stage": "S5", "dispatch": "", "offered": ["go on", "stop"], "options": options,
                    "words_file": words_file, "why": "unread_answer", "block": "dirty tree"}

        def take(words_file):
            driver._answer = {"text": "go on", "rel": None}
            waiver_calls.clear()
            try:
                driver.take_seam_answer("go on", asked(words_file), "", "S5", "")
                return None
            except story_run.Person as person:
                return person
        check_eq("C26: with the original file the pass is its file, byte for byte", (take(rel), (task_root / waiver_calls[0][waiver_calls[0].index("--words-file") + 1]).read_bytes()),
                 (None, original.encode("utf-8")))
        check_eq("C26: with no original file named the token's own file is the words (the token was all that was said)",
                 (take(""), (Path(waiver_calls[0][waiver_calls[0].index("--words-file") + 1])).read_bytes()), (None, b"go on"))
        held = take("state/words/gone.txt")
        check("C26: a file named but gone -> held, waiver.py not called", held is not None and waiver_calls == [] and "not on file" in held.text, str(held))
    finally:
        os.chdir(cwd0)          # off the temp project BEFORE it is deleted: Linux keeps a process in a deleted dir
        cleanup(root)
    check("C26: the working directory still exists after the project is deleted", Path(os.getcwd()).is_dir())


def main() -> None:
    c26_go_on_with_a_block_passes_the_original_words()
    t4c_the_one_writer_of_state_words()
    the_reader_returns_the_file_as_written()
    the_reader_refuses_with_a_door()
    the_controller_records_gate_words_from_a_file()
    the_controller_keeps_inline_words_by_plain_python()
    the_controller_releases_from_a_file()
    the_real_launcher_carries_the_file_and_refuses_inline_words()
    waiver_records_from_a_file_in_every_form()
    archive_task_records_the_note_from_a_file()
    project_decisions_resolves_from_a_file()
    the_guard_lets_the_orchestrator_write_the_words_file()
    every_help_names_the_option()
    the_texts_the_orchestrator_reads_use_the_file_form()
    finish("test_person_words")


if __name__ == "__main__":
    main()
