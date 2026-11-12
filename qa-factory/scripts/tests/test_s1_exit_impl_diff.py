"""TR2-7 (B-8): the S1 exit refuses `--set implementation_source=current-code` while `work/impl-diff*.txt` holds a line.

The scout writes that file (`references/artifact-writers.json`); the S3 entry (`grounding_table.source_state`) refused it later, to the
conductor. Now the scout hears it on its own exit, with two doors, and the requirement is stated in its charter and the S1 phase.
Run: `python -B -m pytest <this file> -q`. Fast: a temp story, no subprocess.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_controller_stage_acceptance as T  # noqa: E402  (story, quiet)
from harness import SCRIPTS, cleanup  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import hooklib  # noqa: E402
import stage_done  # noqa: E402

REAL = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
CC = {"implementation_source": "current-code"}


@pytest.fixture()
def task():
    old = hooklib._PROJECT_ROOT_CACHE
    root, task, _ = T.story()
    hooklib._PROJECT_ROOT_CACHE = root
    (task / "work").mkdir(parents=True, exist_ok=True)
    try:
        yield task
    finally:
        hooklib._PROJECT_ROOT_CACHE = old
        cleanup(root)


def pipeline(task):
    return (task / "pipeline.json").read_bytes()


def put(task, text, name="impl-diff.txt"):
    (task / "work" / name).write_bytes(text.encode("utf-8"))


def test_a_stub_diff_with_current_code_is_refused_with_both_doors(task):
    put(task, "# stub: the diff goes here\n")
    before = pipeline(task)
    code, said = T.quiet(stage_done.set_facts, "QA-1", dict(CC), [])
    assert code == stage_done.EXIT_BAD_ARGS
    assert "work/impl-diff*.txt holds content" in said                                    # what is wrong
    assert "Expected: no diff file with `current-code`" in said                            # what is expected
    assert "rm work/impl-diff.txt" in said                                                 # door 1: the scout can delete its own file
    assert "stage_done.py\" --task QA-1 --set implementation_source=diff" in said          # door 2: the real command
    assert pipeline(task) == before                                                        # nothing written


def test_the_same_refusal_comes_with_the_stage_close(task):
    put(task, REAL)
    before = pipeline(task)
    code, said = T.quiet(stage_done.run, "QA-1", "S1", "done", "qa-scout", "d", True, sets=dict(CC), warns=[])
    assert code == stage_done.EXIT_BAD_ARGS and "holds content" in said
    assert pipeline(task) == before


def test_no_file_passes(task):
    code, said = T.quiet(stage_done.set_facts, "QA-1", dict(CC), [])
    assert code == 0, said
    assert json.loads(pipeline(task))["implementation_source"] == "current-code"


@pytest.mark.parametrize("text", ["", "\n", "  \r\n\t \n"])
def test_empty_or_blank_file_passes(task, text):
    put(task, text)                                                                        # same fact as no file: nothing recorded
    code, said = T.quiet(stage_done.set_facts, "QA-1", dict(CC), [])
    assert code == 0, said


def test_a_one_line_real_diff_is_refused(task):
    put(task, "+y")
    code, _ = T.quiet(stage_done.set_facts, "QA-1", dict(CC), [])
    assert code == stage_done.EXIT_BAD_ARGS


def test_a_file_over_the_usual_size_is_refused_and_a_large_blank_one_passes(task):
    put(task, REAL * 20000)                                                                # a few MB: read whole, no limit to slip under
    assert T.quiet(stage_done.set_facts, "QA-1", dict(CC), [])[0] == stage_done.EXIT_BAD_ARGS
    put(task, " \n" * 2_000_000)
    assert T.quiet(stage_done.set_facts, "QA-1", dict(CC), [])[0] == 0


def test_a_named_second_diff_counts(task):
    put(task, REAL, "impl-diff-backend.txt")                                               # the reader is the one `diff_recorded` globs
    assert T.quiet(stage_done.set_facts, "QA-1", dict(CC), [])[0] == stage_done.EXIT_BAD_ARGS


@pytest.mark.parametrize("word", ["diff", "ungrounded"])
def test_other_sources_do_not_run_the_check(task, word):
    put(task, REAL)
    code, said = T.quiet(stage_done.set_facts, "QA-1", {"implementation_source": word}, [])
    assert code == 0, said
    assert json.loads(pipeline(task))["implementation_source"] == word


def test_a_call_without_the_source_does_not_run_the_check(task):
    put(task, REAL)
    code, said = T.quiet(stage_done.set_facts, "QA-1", {"size": "S"}, ["S0 note: x"])
    assert code == 0, said


def test_one_reader_of_a_recorded_diff():
    src = (SCRIPTS / "stage_done.py").read_text(encoding="utf-8")
    body = src.split("def current_code_diff_refusal", 1)[1].split("def parse_sets", 1)[0]
    assert "from runtime_probe import diff_recorded" in body and ".read_text" not in body and "glob(" not in body


def test_the_requirement_reaches_the_scout_before_the_work():
    root = SCRIPTS.parent
    charter = (root / "agents" / "qa-scout.md").read_text(encoding="utf-8")
    phase = (root / "skills" / "qa-story" / "phases" / "s1.md").read_text(encoding="utf-8")
    assert "write no `work/impl-diff.txt`, no stub there" in charter
    assert "with `current-code` no diff file is written" in phase


def diff_file_lines(text):
    return [line for line in text.splitlines() if "impl-diff.txt" in line and ("absent" in line)]


def says_current_code(text):
    lines = diff_file_lines(text)
    return bool(lines) and all("current-code" in line for line in lines)


def test_the_four_role_facing_texts_say_current_code_at_the_diff_files_line():
    root = SCRIPTS.parent
    s1 = (root / "handoffs" / "s1-scout-to-tester.yaml").read_text(encoding="utf-8")
    s2 = (root / "handoffs" / "s2-tester-to-strategist.yaml").read_text(encoding="utf-8")
    phase = (root / "skills" / "qa-story" / "phases" / "s2.md").read_text(encoding="utf-8")
    brief = (SCRIPTS / "story_run.py").read_text(encoding="utf-8")
    assert "absent when implementation_source is `ungrounded` or `current-code`" in s1
    assert "absent when the source is `ungrounded` or `current-code`" in s2
    assert "(absent when ungrounded or current-code)" in phase
    assert brief.count("(absent when ungrounded or current-code)") == 1 and "(absent when ungrounded)" not in brief
    for text in (s2, phase, brief):
        assert says_current_code(text), "the diff file's line must name current-code"
    assert "current-code" in s1.split("work/impl-diff.txt", 2)[1]


def test_negative_control_a_line_without_the_word_fails_the_check():
    assert not says_current_code("impl-diff.txt: work/impl-diff.txt (absent when ungrounded)")
    assert says_current_code("impl-diff.txt: work/impl-diff.txt (absent when ungrounded or current-code)")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
