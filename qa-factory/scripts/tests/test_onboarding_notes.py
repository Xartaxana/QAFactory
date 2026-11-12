"""B-411: the onboarding run's own notes (scripts/onboarding_notes.py), as the spec's acceptance keys name them.

K1-K13 (the CLI), the text keys T1a-T9 and P1 with their negative pins (the doc-witness run: keys quoted
verbatim from the DoD, the script is this file, and one deliberately absent sentence must be reported absent),
and the data file. The hooks are in test_onboarding_compaction.py, the install table in test_install_retire.py /
test_install_paths.py, the guard in test_guard_write_owners.py.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import onboarding_notes as N  # noqa: E402

DATA = N.load_data()
STATUS_KEYS = ["exists", "path", "readable", "problem", "schema_version", "phase", "started_at", "updated_at",
               "approval_ref", "frozen", "head_then", "head_now", "config_sha_then", "config_sha_now",
               "changed_since", "stale_sections", "discovery_sections", "extra_sections", "batches",
               "answered", "not_answered", "awaiting_reply", "awaiting_topics", "unrecorded_words"]


def call(root, *args):
    """The command line, in process: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = N.main(["--root", str(root), *map(str, args)])
        except SystemExit as exc:           # argparse
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def status(root) -> dict:
    code, out, err = call(root, "status")
    assert code == 0, (code, err)
    return json.loads(out)


def notes(root) -> Path:
    return N.notes_dir(root, DATA)


def tree(root: Path) -> list:
    return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob("*"))


def git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.autocrlf=false", *args],
                          cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace")


def repo(prefix="qa-onb-repo-") -> Path:
    root = temp_dir(prefix)
    git(root, "init", "-q")
    (root / "a.py").write_text("print(1)\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "init")
    return root


def questions(tmp: Path, items, name="q.json") -> Path:
    path = tmp / name
    path.write_text(json.dumps(items), encoding="utf-8")
    return path


def words(root, name, text="their words\n") -> Path:
    folder = notes(root) / "words"
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
    return path


def started(prefix="qa-onb-") -> Path:
    root = temp_dir(prefix)
    code, out, err = call(root, "start", "--tree", "clean")
    assert code == 0, err
    return root


# --------------------------------------------------------------------------------------- K3, K5, edges of absence

def absent_and_shape() -> None:
    root = temp_dir("qa-onb-absent-")
    try:
        before = tree(root)
        doc = status(root)
        check_eq("K3: status on a project with no qa-factory/ reports exists false", (doc["exists"], doc["readable"]), (False, True))
        check_eq("K3: ...and creates nothing (reading never creates)", tree(root), before)
        check_eq("K3: the status keys are the fixed FR-14 list", list(doc), STATUS_KEYS)
        check("K3: closed and package_version are not keys", "closed" not in doc and "package_version" not in doc)
        code, out, err = call(root, "start", "--tree", "dirty")
        doc = status(root)
        check_eq("start opens a run at p1", (code, doc["exists"], doc["phase"], doc["readable"]), (0, True, "p1", True))
        check_eq("K3: with a run the key list is the same", list(doc), STATUS_KEYS)
        check_eq("start printed {path} and the folder is the data file's", json.loads(out), {"path": str(notes(root))})
        check_eq("the folder is qa-factory/state/onboarding", notes(root), root.resolve() / "qa-factory" / "state" / "onboarding")
        check_eq(".gitignore holds the single line *", (notes(root) / ".gitignore").read_text(encoding="utf-8"), "*\n")
        check_eq("the skeleton: every section is pending", set(doc["discovery_sections"].values()), {"pending"})
        check_eq("...and the ids are the data file's", list(doc["discovery_sections"]), DATA["discovery_sections"])
        check("start leaves no temp file behind", not [p for p in notes(root).iterdir() if p.name.endswith(".tmp")])
        progress = (notes(root) / "progress.yaml").read_text(encoding="utf-8")
        check("progress.yaml carries no package_version and no closed", "package_version" not in progress and "closed" not in progress)
        check_eq("tree is recorded", N.handoff.parse(progress).data["tree"], "dirty")
    finally:
        cleanup(root)

    # K5: the schema gate
    root = started("qa-onb-schema-")
    try:
        path = notes(root) / "progress.yaml"
        good = path.read_text(encoding="utf-8")
        doc = status(root)
        check_eq("K5: schema 1 is readable", (doc["readable"], doc["schema_version"]), (True, 1))
        path.write_text(good.replace("schema_version: 1", "schema_version: 2"), encoding="utf-8")
        doc = status(root)
        check("K5: schema 2 is readable false and says newer", not doc["readable"] and any("newer" in p for p in doc["problem"]), str(doc["problem"]))
        path.write_text(good.replace("schema_version: 1\n", ""), encoding="utf-8")
        doc = status(root)
        check("K5: a missing schema is readable false", not doc["readable"] and any("schema_version" in p for p in doc["problem"]), str(doc["problem"]))
        for label, content in (("empty", ""), ("garbage", "}{ not yaml at all \x00"), ("a phase that is not a phase", good.replace('phase: "p1"', 'phase: "p9"'))):
            path.write_text(content, encoding="utf-8")
            doc = status(root)
            check(f"edge: a {label} progress.yaml is readable false (never partly reused), exit 0", not doc["readable"] and doc["exists"], str(doc["problem"]))
        path.unlink()
        path.mkdir()
        doc = status(root)
        check("edge: a progress.yaml that is a directory is readable false", not doc["readable"] and any("folder" in p for p in doc["problem"]), str(doc["problem"]))
        code, out, err = call(root, "ask", "--batch", "b1", "--questions-file", questions(root.parent, [{"topic": "t", "text": "q"}]))
        check("an unreadable run refuses every write, with the doors", code == 2 and "set-aside" in err and "status" in err, err)
        code, out, err = call(root, "set-aside")
        check_eq("...and set-aside is the way out of it", (code, status(root)["exists"]), (0, False))
    finally:
        cleanup(root)

    # only archives and the ignore file: no open run
    root = started("qa-onb-archive-")
    try:
        call(root, "set-aside")
        check_eq("edge: only retired/ and .gitignore present: no open run", status(root)["exists"], False)
        check_eq("edge: ...and open_onboarding says so", N.open_onboarding(root)["open"], False)
        (notes(root) / "done" / "x").mkdir(parents=True)
        check_eq("edge: done/ too", N.open_onboarding(root)["open"], False)
    finally:
        cleanup(root)

    # the data file cannot be read
    root = temp_dir("qa-onb-nodata-")
    saved = N.DATA_REL
    try:
        N.DATA_REL = "references/no-such-onboarding-notes.json"
        code, out, err = call(root, "start", "--tree", "clean")
        check("edge: an unreadable data file refuses, naming the file", code == 2 and "no-such-onboarding-notes.json" in err, err)
        check_eq("...and creates nothing", tree(root), [])
        code, out, err = call(root, "status")
        doc = json.loads(out)
        check("edge: status still exits 0 and reports it", code == 0 and not doc["readable"] and "no-such-onboarding-notes.json" in doc["problem"][0], out)
    finally:
        N.DATA_REL = saved
        cleanup(root)


# --------------------------------------------------------------------------------------- K1, K2, K6, K12, K13

ADVERSARIAL = ["x: y", " # x", "- a", "[", "{", '"', "\\", "line1\nline2", "a\r\nb", "tab\t", "null", "~", "true", "123",
               "# a comment-looking line", "'", "it's", "C:\\Users\\dev6\\x", "\U0001F600 non-BMP", "a\u2028b", "a\x85b", "a\x0bb",
               "a]b[c}{", "key: [1, 2", "x" * 10000, "- topic: injected\n  text: injected", "end: |", "---", "a #b"]


def round_trips_and_batches() -> None:
    root = started("qa-onb-rt-")
    try:
        items = [{"topic": f"t{i}", "text": t} for i, t in enumerate(ADVERSARIAL)]
        code, out, err = call(root, "ask", "--batch", "rt-1", "--questions-file", questions(root.parent, items))
        check_eq("ask records the batch", (code, json.loads(out)["times_asked"]), (0, 1))
        data = N.read_run(notes(root), DATA)
        got = [(q["topic"], q["text"]) for q in data["batch_data"][0]["questions"]]
        bad = [(a["topic"], a["text"][:20]) for a, (_t, b) in zip(items, got) if a["text"] != b]
        check_eq("K1: every adversarial question text round-trips byte-exact through ask -> status' reader", bad, [])
        check_eq("K1: ...no row lost or invented", len(got), len(items))
        check("K1: the file is json-quoted: no bare scalar of the text is left in it",
              "injected" in (notes(root) / "interview.yaml").read_text(encoding="utf-8")
              and "\n  text: injected" not in (notes(root) / "interview.yaml").read_text(encoding="utf-8"))
    finally:
        cleanup(root)


def replies_and_batches() -> None:
    root = started("qa-onb-batches-")
    try:
        three = [{"topic": "t0", "text": "zero?"}, {"topic": "t1", "text": "one?"}, {"topic": "t2", "text": "two?"}]
        code, out, err = call(root, "ask", "--batch", "p2-1", "--questions-file", questions(root.parent, three, "q1.json"))
        check_eq("ask records the first batch", (code, json.loads(out)["times_asked"]), (0, 1))

        # a reply, then a second batch: batch 1 stays byte-identical (K2)
        w1 = words(root, "batch-p2-1-20261006-100000.txt", 'Go on.\n\nKeep it local - "do not publish".\n')
        code, out, err = call(root, "answer", "--batch", "p2-1", "--words-file", w1, "--answered", "t0,t1", "--not-answered", "t2")
        check("answer records the reply", code == 0, err)
        text1 = (notes(root) / "interview.yaml").read_text(encoding="utf-8")
        block1 = text1[text1.index("  - batch: \"p2-1\""):]
        doc = status(root)
        check_eq("answered and not_answered come from the reply", (doc["answered"], doc["not_answered"]), (["t0", "t1"], ["t2"]))
        check_eq("a batch with a valid reply is not awaiting", doc["awaiting_reply"], [])
        reply = doc["batches"][0]["replies"][0]
        check_eq("the reply carries the words file's sha256 over its bytes", reply["sha256"], hashlib.sha256(w1.read_bytes()).hexdigest())
        check_eq("...and the words file is untouched, byte for byte", w1.read_bytes(), 'Go on.\n\nKeep it local - "do not publish".\n'.encode("utf-8"))
        code, out, err = call(root, "ask", "--batch", "p2-2", "--questions-file", questions(root.parent, [{"topic": "u1", "text": "second?"}], "q2.json"))
        doc = status(root)
        check_eq("K2: a second batch is awaiting, the first is not", doc["awaiting_reply"], ["p2-2"])
        text2 = (notes(root) / "interview.yaml").read_text(encoding="utf-8")
        check("K2: batch 1's block is byte-identical after batch 2 was asked", block1.rstrip() in text2 and text2.count("- batch:") == 2)
        w2 = words(root, "batch-p2-2-20261006-100100.txt", "u1 answer")
        code, out, err = call(root, "answer", "--batch", "p2-2", "--words-file", w2, "--answered", "u1")
        text3 = (notes(root) / "interview.yaml").read_text(encoding="utf-8")
        check("K2: answer on batch 2 leaves batch 1's block byte-identical", block1.rstrip() in text3)
        w1b = words(root, "batch-p2-1-20261006-100200.txt", "a later reply")
        code, out, err = call(root, "answer", "--batch", "p2-1", "--words-file", w1b, "--answered", "t2")
        doc = status(root)
        check_eq("K2: a second reply is appended, never overwritten", [r["words_file"] for r in doc["batches"][0]["replies"]],
                 ["words/batch-p2-1-20261006-100000.txt", "words/batch-p2-1-20261006-100200.txt"])
        check_eq("...and the later reply wins for the topic it names", (doc["answered"], doc["not_answered"]), (["t0", "t1", "t2", "u1"], []))

        # a reply measured on other bytes never counts
        w2.write_text("u1 answer, edited after it was recorded", encoding="utf-8")
        doc = status(root)
        check_eq("K1: a reply whose sha256 changed counts as absent: the batch is awaiting again", doc["awaiting_reply"], ["p2-2"])
        check("...and it is named in problem", any("p2-2" in p and "changed" in p for p in doc["problem"]), str(doc["problem"]))
        check("...u1 is no longer answered", "u1" not in doc["answered"])
        w2.unlink()
        doc = status(root)
        check("a words file that is gone: the reply is absent too", doc["awaiting_reply"] == ["p2-2"] and any("missing" in p for p in doc["problem"]), str(doc["problem"]))

        # a re-ask of an awaiting batch: times_asked + 1, earlier text kept, new text appended
        code, out, err = call(root, "ask", "--batch", "p2-2", "--questions-file", questions(root.parent, [{"topic": "u1", "text": "second, once more, because the context was compacted"}], "q3.json"))
        doc = status(root)
        data = N.read_run(notes(root), DATA)
        b2 = [b for b in data["batch_data"] if b["batch"] == "p2-2"][0]
        check_eq("a re-ask: times_asked + 1, both texts kept", (code, b2["times_asked"], [q["text"] for q in b2["questions"]],
                                                                [q["ask"] for q in b2["questions"]]),
                 (0, 2, ["second?", "second, once more, because the context was compacted"], [1, 2]))
        code, out, err = call(root, "ask", "--batch", "p2-1", "--questions-file", questions(root.parent, [{"topic": "t0", "text": "again"}], "q4.json"))
        check("a topic a reply of its batch already settled is not asked again, and the refusal names it",
              code == 2 and "'t0'" in err and "already settled" in err, err)
    finally:
        cleanup(root)


def partial_replies_and_reask_rules() -> None:
    """Critic t-530 F1 (a batch stays awaiting until every topic is covered), F2 (words on disk no reply refers to),
    F6 (an answered topic is not asked again under a new batch id, but for the listed prefixes)."""
    root = started("qa-onb-partial-")
    try:
        two = [{"topic": "ci", "text": "ci?"}, {"topic": "env", "text": "env?"}]
        call(root, "ask", "--batch", "p2-1", "--questions-file", questions(root.parent, two, "qp.json"))
        w = words(root, "batch-p2-1-20261007-100000.txt", "ci is gitlab")
        code, out, err = call(root, "answer", "--batch", "p2-1", "--words-file", w, "--answered", "ci")
        check_eq("F1: answer prints what is still open", (code, json.loads(out)["still_open"]), (0, ["env"]))
        doc = status(root)
        check_eq("F1 (a): after a partial reply the batch is still awaiting", doc["awaiting_reply"], ["p2-1"])
        check_eq("F1 (a): awaiting_topics names the topic left out", doc["awaiting_topics"], {"p2-1": ["env"]})
        check_eq("F1 (a): answered is just the topic named", (doc["answered"], doc["not_answered"]), (["ci"], []))
        found = N.open_onboarding(root)
        check_eq("F1: open_onboarding carries awaiting_topics too (the hooks' predicate)", (found["awaiting_reply"], found["awaiting_topics"]),
                 (["p2-1"], {"p2-1": ["env"]}))
        code, out, err = call(root, "ask", "--batch", "p2-1", "--questions-file", questions(root.parent, [{"topic": "env", "text": "env, once more?"}], "qe.json"))
        check_eq("F1 (b): asking the open topic of the batch again is accepted, times_asked 2", (code, json.loads(out)["times_asked"]), (0, 2))
        code, out, err = call(root, "ask", "--batch", "p2-1", "--questions-file", questions(root.parent, [{"topic": "ci", "text": "ci again?"}], "qc.json"))
        check("F1 (b): asking the covered topic again is refused, naming it", code == 2 and "'ci'" in err, err)
        w2 = words(root, "batch-p2-1-20261007-100100.txt", "env is docker")
        code, out, err = call(root, "answer", "--batch", "p2-1", "--words-file", w2, "--answered", "env")
        doc = status(root)
        check_eq("F1 (c): naming the last topic clears the batch", (code, json.loads(out)["still_open"], doc["awaiting_reply"], doc["awaiting_topics"]), (0, [], [], {}))
        check_eq("...and both topics are answered", sorted(doc["answered"]), ["ci", "env"])
        # a topic named not-answered covers it too
        call(root, "ask", "--batch", "p2-2", "--questions-file", questions(root.parent, [{"topic": "a", "text": "a?"}, {"topic": "b", "text": "b?"}], "qa.json"))
        w3 = words(root, "batch-p2-2-20261007-100200.txt", "a: yes, b: no idea")
        call(root, "answer", "--batch", "p2-2", "--words-file", w3, "--answered", "a", "--not-answered", "b")
        check_eq("F1: a topic named in --not-answered is covered", status(root)["awaiting_reply"], [])
        # a reply measured on other bytes uncovers its topics again
        w3.write_text("changed", encoding="utf-8")
        doc = status(root)
        check_eq("F1: a reply whose words changed no longer covers: the whole batch is open again", (doc["awaiting_reply"], doc["awaiting_topics"]),
                 (["p2-2"], {"p2-2": ["a", "b"]}))
        w3.write_text("a: yes, b: no idea", encoding="utf-8")

        # F6: an answered topic under a NEW batch id
        code, out, err = call(root, "ask", "--batch", "p2-3", "--questions-file", questions(root.parent, [{"topic": "ci", "text": "ci, again?"}], "q6.json"))
        check("F6: ask p2-3 {ci} is refused: ci is answered, the refusal names the batch that holds it", code == 2 and "'p2-1'" in err and "'ci'" in err, err)
        code, out, err = call(root, "ask", "--batch", "p4-x", "--questions-file", questions(root.parent, [{"topic": "ci", "text": "ci, changed?"}], "q7.json"))
        check_eq("F6: ask p4-x {ci} is accepted (the prefix is listed in the data file)", code, 0)
        code, out, err = call(root, "ask", "--batch", "p3-edit-1", "--questions-file", questions(root.parent, [{"topic": "env", "text": "env, changed?"}], "q8.json"))
        check_eq("F6: ask p3-edit-1 {env} is accepted too", code, 0)
        code, out, err = call(root, "ask", "--batch", "p2-4", "--questions-file", questions(root.parent, [{"topic": "b", "text": "b, once more?"}], "q9.json"))
        check_eq("F6: a topic that was NOT answered (b: not answered) may be asked under a new batch", code, 0)
        check_eq("F6: the exemptions are data (FR-13)", DATA["reask_batch_prefixes"], ["p3-edit-", "p4-"])

        # F2: words on disk that no reply refers to
        words(root, "batch-p2-4-20261007-100300.txt", "b: staging")
        doc = status(root)
        check_eq("F2: a words file no reply refers to is reported", doc["unrecorded_words"], ["words/batch-p2-4-20261007-100300.txt"])
        check("F2: ...and the recorded ones are not", "words/batch-p2-1-20261007-100000.txt" not in doc["unrecorded_words"])
        call(root, "answer", "--batch", "p2-4", "--words-file", notes(root) / "words" / "batch-p2-4-20261007-100300.txt", "--answered", "b")
        check_eq("F2: once answer records it the list is empty", status(root)["unrecorded_words"], [])
    finally:
        cleanup(root)


def refusals_and_ids() -> None:
    root = started("qa-onb-refuse-")
    try:
        base = questions(root.parent, [{"topic": "t1", "text": "one?"}, {"topic": "t2", "text": "two?"}], "qr.json")
        call(root, "ask", "--batch", "b1", "--questions-file", base)
        before = (notes(root) / "interview.yaml").read_bytes()
        door = "onboarding_notes.py --root . answer --batch b1 --answered <topics> --words-file <file>"
        w = words(root, "batch-b1-1.txt", "fine")
        cases = {
            "an empty words file": (words(root, "batch-b1-2.txt", ""), "t1"),
            "a whitespace-only words file": (words(root, "batch-b1-3.txt", "  \n \n"), "t1"),
            "a UTF-16 words file": (words(root, "batch-b1-4.txt", "hello".encode("utf-16")), "t1"),
            "invalid UTF-8": (words(root, "batch-b1-5.txt", b"\xff\xfe\xfa bad"), "t1"),
            "a words file outside words/": (root / "elsewhere.txt", "t1"),
            "a topic outside the batch": (w, "t9"),
            "a topic id with a colon": (w, "t1:x"),
        }
        (root / "elsewhere.txt").write_text("their words", encoding="utf-8")
        for label, (path, topics) in cases.items():
            code, out, err = call(root, "answer", "--batch", "b1", "--words-file", path, "--answered", topics)
            check(f"K6: {label} is refused, exit 2, nothing recorded", code == 2 and out == "" and (notes(root) / "interview.yaml").read_bytes() == before, err)
            check(f"K13: ...the refusal ends with the person_words door ({label})", err.strip().endswith(door), err[-160:])
        code, out, err = call(root, "answer", "--batch", "nope", "--words-file", w, "--answered", "t1")
        check("K13: an unknown batch is refused with the door too", code == 2 and "not on record" in err and err.strip().endswith(door.replace("b1", "nope")), err)
        code, out, err = call(root, "answer", "--batch", "b1", "--words-file", w, "--answered", "t1", "--not-answered", "t1")
        check("a topic both answered and not answered is refused", code == 2 and (notes(root) / "interview.yaml").read_bytes() == before, err)
        code, out, err = call(root, "answer", "--batch", "b1", "--words-file", notes(root) / "words", "--answered", "t1")
        check("a words path that is a directory is refused", code == 2 and (notes(root) / "interview.yaml").read_bytes() == before, err)

        # K12: ids
        for bad in ("a:b", "p2:x", "-lead", ".dot", "has space", "", "a/b", "..", "a\\b"):
            code, out, err = call(root, "ask", "--batch", bad, "--questions-file", base)
            check(f"K12: batch id {bad!r} is refused", code == 2 and (notes(root) / "interview.yaml").read_bytes() == before, err)
        for bad in ("t:1", "-x", "a b"):
            code, out, err = call(root, "ask", "--batch", "ok", "--questions-file", questions(root.parent, [{"topic": bad, "text": "q"}], "qb.json"))
            check(f"K12: topic id {bad!r} is refused", code == 2 and (notes(root) / "interview.yaml").read_bytes() == before, err)
        for good in ("p2-1", "A1", "p4-api_x.1-2", "9"):
            code, out, err = call(root, "ask", "--batch", good, "--questions-file", base)
            check(f"K12 control: batch id {good!r} is accepted", code == 0, err)
        # the questions file
        for label, content in (("not JSON", b"nope"), ("UTF-16", "[]".encode("utf-16")), ("an empty list", b"[]"),
                               ("an item with no text", b'[{"topic": "t"}]'), ("an item with empty text", b'[{"topic": "t", "text": " "}]')):
            path = root.parent / "bad-q.json"
            path.write_bytes(content)
            snap = (notes(root) / "interview.yaml").read_bytes()
            code, out, err = call(root, "ask", "--batch", "zz", "--questions-file", path)
            check(f"a questions file that is {label} is refused, nothing recorded", code == 2 and (notes(root) / "interview.yaml").read_bytes() == snap, err)
        code, out, err = call(root, "ask", "--batch", "zz", "--questions-file", root.parent / "no-such.json")
        check("a questions file that does not exist is refused", code == 2 and "no-such.json" in err, err)
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- K4, K7, K9

def approve(root: Path, ref: str) -> None:
    import config_contract
    path = config_contract.approvals_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"schema_version": 1, "approval_ref": ref, "status": "approved"}) + "\n")


def frozen_and_phases() -> None:
    root = started("qa-onb-frozen-")
    try:
        code, out, err = call(root, "phase", "--set", "p2")
        check_eq("phase --set p2 moves the phase", (code, status(root)["phase"]), (0, "p2"))
        for p in ("p2b", "p3"):
            call(root, "phase", "--set", p)
        check_eq("p2b and p3 are phases", status(root)["phase"], "p3")
        code, out, err = call(root, "phase", "--set", "p7")
        check("an unknown phase is refused, naming the list", code == 2 and "p2b" in err, err)
        code, out, err = call(root, "phase", "--set", "p4")
        check("F3: --set p4 with no approval and no frozen run is refused, with the recording command as the door",
              code == 2 and "--record-approval" in err and status(root)["phase"] == "p3", err)
        code, out, err = call(root, "phase", "--set", "done")
        check("F3: --set done is refused always, with `close` as the door", code == 2 and "close --approval-ref" in err and status(root)["phase"] == "p3", err)
        code, out, err = call(root, "phase", "--set", "p4", "--approval-ref", "onboarding:t1")
        check("K4: an approval ref not on record is refused, with the recording command as the door",
              code == 2 and "--record-approval" in err and status(root)["phase"] == "p3", err)
        approve(root, "onboarding:t1")
        code, out, err = call(root, "phase", "--set", "p4", "--approval-ref", "onboarding:t1", "--sealed", "notes/sealed.json")
        doc = status(root)
        check_eq("K4: with the approval on record the run is frozen at p4", (code, doc["phase"], doc["frozen"], doc["approval_ref"]),
                 (0, "p4", True, "onboarding:t1"))
        items = [{"topic": "t1", "text": "q"}]
        code, out, err = call(root, "ask", "--batch", "3", "--questions-file", questions(root.parent, items))
        check("K4: frozen: a batch without the p4- prefix is refused", code == 2 and "frozen" in err, err)
        code, out, err = call(root, "ask", "--batch", "p4-api-1", "--questions-file", questions(root.parent, items))
        check("K4: frozen: ask --batch p4-api-1 is accepted", code == 0, err)
        code, out, err = call(root, "phase", "--set", "p2")
        check("K4: frozen: phase --set p2 is refused", code == 2 and status(root)["phase"] == "p4", err)
        code, out, err = call(root, "phase", "--set", "p4", "--approval-ref", "other")
        check("a frozen run is not moved to another approval", code == 2 and status(root)["approval_ref"] == "onboarding:t1", err)
        code, out, err = call(root, "phase", "--set", "p4")
        check("p4 again is accepted once the run is frozen", code == 0, err)
        code, out, err = call(root, "phase", "--set", "done")
        check("F3: --set done is refused on a frozen run too", code == 2 and status(root)["phase"] == "p4", err)
        check_eq("the sealed path is kept as given", N.read_run(notes(root), DATA)["progress"]["sealed"], "notes/sealed.json")
        # updated_at moves on every write
        a = status(root)["updated_at"]
        check("every CLI write sets updated_at", a is not None and a >= status(root)["started_at"])
    finally:
        cleanup(root)


def set_aside_close_and_start() -> None:
    root = started("qa-onb-move-")
    try:
        call(root, "ask", "--batch", "b1", "--questions-file", questions(root.parent, [{"topic": "t1", "text": "q"}]))
        w = words(root, "batch-b1-1.txt", "answer")
        call(root, "answer", "--batch", "b1", "--words-file", w, "--answered", "t1")
        code, out, err = call(root, "start", "--tree", "clean")
        check("K9: start over an open run is refused", code == 2, err)
        check("K9: ...naming the path, the phase, the dates and the doors status and set-aside",
              str(notes(root)) in err and "phase p1" in err and "started" in err and "status" in err and "set-aside" in err, err)
        code, out, err = call(root, "set-aside")
        moved = json.loads(out)
        target = Path(moved["to"])
        check_eq("K7: set-aside moves the run to retired/<date>/", (code, target.parent.name, target.parent.parent.name), (0, "retired", "onboarding"))
        check("K7: ...never deleting: progress, interview, discovery and the words file are all there",
              all((target / n).exists() for n in ("progress.yaml", "interview.yaml", "discovery.yaml", "words/batch-b1-1.txt")), str(os.listdir(target)))
        check_eq("K7: ...the words are byte-identical", (target / "words" / "batch-b1-1.txt").read_bytes(), b"answer")
        check("K7: .gitignore stays, the top level holds only it and retired/", set(os.listdir(notes(root))) == {".gitignore", "retired"}, str(os.listdir(notes(root))))
        check_eq("...and no run is open", status(root)["exists"], False)
        code, out, err = call(root, "set-aside")
        check_eq("set-aside with no run is a no-op, exit 0", (code, json.loads(out)["set_aside"]), (0, []))
        code, out, err = call(root, "close", "--approval-ref", "ref:1")
        check("K7: close with no run and no done/ folder is refused (nothing is answered 'already closed')",
              not (notes(root) / "done").exists() and code == 2 and "nothing to close" in err and "already" not in out, out + err)
        call(root, "start", "--tree", "clean")
        call(root, "set-aside")
        check("a second set-aside the same day lands in a -2 folder (nothing is overwritten)", len(os.listdir(notes(root) / "retired")) == 2
              and any(n.endswith("-2") for n in os.listdir(notes(root) / "retired")), str(os.listdir(notes(root) / "retired")))

        # start again, freeze, close
        call(root, "start", "--tree", "clean")
        # OH3-29: `close` reads the live config (its first reader); a project that closes has one profile with a one-test command
        (root / "qa-factory" / "config.json").write_text(json.dumps(
            {"schema_version": 1, "profiles": [{"profile_id": "api", "commands": {"one_test": {"argv": ["pytest", "<test-file>"]}}}]}), encoding="utf-8")
        code, out, err = call(root, "close", "--approval-ref", "ref:1")
        check("close of an unfrozen run is refused", code == 2 and "not the approval" in err, err)
        approve(root, "ref:1")
        call(root, "phase", "--set", "p4", "--approval-ref", "ref:1")
        code, out, err = call(root, "close", "--approval-ref", "wrong")
        check("close with another ref is refused", code == 2, err)
        code, out, err = call(root, "close", "--approval-ref", "ref:1")
        done = Path(json.loads(out)["path"])
        check_eq("K7: close moves the run to done/<sanitised ref>/", (code, done.parent.name, done.name), (0, "done", "ref_1"))
        check_eq("K7: ...phase done in what was moved", N.handoff.parse((done / "progress.yaml").read_text(encoding="utf-8")).data["phase"], "done")
        check("K7: ...the top level holds only .gitignore, retired/ and done/", set(os.listdir(notes(root))) == {".gitignore", "retired", "done"}, str(os.listdir(notes(root))))
        code, out, err = call(root, "close", "--approval-ref", "ref:1")
        check_eq("K7: close is idempotent: already closed, exit 0", (code, json.loads(out).get("already"), json.loads(out).get("note")), (0, True, "already closed"))
        check_eq("...and moved nothing", sorted(os.listdir(notes(root) / "done")), ["ref_1"])
        check_eq("a closed run is not offered as unfinished", status(root)["exists"], False)
        code, out, err = call(root, "close", "--approval-ref", "never-existed")
        check("close of a ref nothing was closed under is refused", code == 2, err)
        # a second run closed under a ref that sanitises to the same folder
        call(root, "start", "--tree", "clean")
        approve(root, "ref/1")
        call(root, "phase", "--set", "p4", "--approval-ref", "ref/1")
        code, out, err = call(root, "close", "--approval-ref", "ref/1")
        check_eq("two refs that sanitise alike: the second goes to -2, the first is not overwritten", sorted(os.listdir(notes(root) / "done")), ["ref_1", "ref_1-2"])
        # A9: only a run closed under the SAME approval answers "already closed"
        code, out, err = call(root, "close", "--approval-ref", "ref/1")
        again = json.loads(out) if code == 0 else {}
        check_eq("K7: closing again under 'ref/1' (same done/ folder family) answers already closed, at the run closed under it",
                 (code, again.get("already"), again.get("note"), Path(again.get("path", "")).name), (0, True, "already closed", "ref_1-2"))
        code, out, err = call(root, "close", "--approval-ref", "ref:1")
        check_eq("K7: ...and 'ref:1' still answers at ref_1, not at the later folder", (code, Path(json.loads(out)["path"]).name), (0, "ref_1"))
        code, out, err = call(root, "close", "--approval-ref", "ref*1")
        check("K7: a different approval that sanitises to the same folder is not 'already closed': refused, nothing moved",
              code == 2 and "nothing to close" in err and "already" not in out and sorted(os.listdir(notes(root) / "done")) == ["ref_1", "ref_1-2"], out + err)
        # a path-looking ref cannot leave done/
        call(root, "start", "--tree", "clean")
        approve(root, "../../escape")
        call(root, "phase", "--set", "p4", "--approval-ref", "../../escape")
        code, out, err = call(root, "close", "--approval-ref", "../../escape")
        check("a ref made of dots and slashes stays inside done/", code == 0 and Path(json.loads(out)["path"]).parent == notes(root) / "done", out + err)
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- K8

def git_clean() -> None:
    root = repo("qa-onb-git-")
    try:
        before = git(root, "status", "--porcelain").stdout
        call(root, "start", "--tree", "clean")
        call(root, "ask", "--batch", "b1", "--questions-file", questions(root.parent, [{"topic": "t1", "text": "q?"}]))
        w = words(root, "batch-b1-1.txt", "an answer")
        call(root, "answer", "--batch", "b1", "--words-file", w, "--answered", "t1")
        (notes(root) / "proposal.json").write_text("{}", encoding="utf-8")
        check_eq("K8: git status --porcelain is empty after start, ask and answer (and a proposal)", git(root, "status", "--porcelain").stdout, before)
        check_eq("K8: ...and it was empty to begin with", before, "")
        # the ignore file is written FIRST: a folder with a run file and no .gitignore would show up
        check("the notes are there, ignored", (notes(root) / "interview.yaml").exists() and git(root, "check-ignore", "-q", str(notes(root) / "interview.yaml")).returncode == 0)
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- K10, K11

SECTION = "{id}:\n  state: {state}\n  evidence: {evidence}\n  notes: {notes}\n"


def discovery_states() -> None:
    root = started("qa-onb-disc-")
    try:
        text = ""
        text += SECTION.format(id="execution_profiles", state='"found"', evidence='["src/a.py:1"]', notes='"ok"')     # control
        text += SECTION.format(id="run_commands", state="Found", evidence="[]", notes='""')
        text += SECTION.format(id="ci_gates", state="found#x", evidence="[]", notes='""')
        text += SECTION.format(id="declared_conventions", state="null", evidence="[]", notes='""')
        text += SECTION.format(id="cases_tms", state='"found"', evidence="src/a.py:1", notes='""')               # a string, not a list
        text += SECTION.format(id="tracker_reach", state='"gap"', evidence="[]", notes='""')
        text += "tracker_reach2:\n  evidence: []\n"                                                                # an extra section with no state
        text += SECTION.format(id="my_own_section", state='"inferred"', evidence="[]", notes='""')                 # an extra one, fine
        text += "stray_scalar: 5\n"
        (notes(root) / "discovery.yaml").write_text(text, encoding="utf-8")
        doc = status(root)
        states = doc["discovery_sections"]
        check_eq("K10 control: state \"found\" is reported found", states["execution_profiles"], "found")
        for key, why in (("run_commands", "Found"), ("ci_gates", "found#x"), ("declared_conventions", "null"), ("cases_tms", "a string evidence"),
                         ("tracker_reach2", "a section with no state")):
            check_eq(f"K10: {why} is reported pending", states[key], "pending")
            check(f"K10: ...and named in problem ({why})", any(f"section {key}" in p for p in doc["problem"]), str(doc["problem"]))
        check_eq("a valid gap stays gap", states["tracker_reach"], "gap")
        check_eq("an extra section of the role's own is kept, and listed", (states["my_own_section"], "my_own_section" in doc["extra_sections"]), ("inferred", True))
        check("a top-level scalar is not a section: ignored and named", "stray_scalar" not in states and any("stray_scalar" in p for p in doc["problem"]), str(doc["problem"]))
        check("a skeleton id the role never wrote is pending", states["application_stack"] == "pending")
        check_eq("the file's states never count a malformed section as found", [k for k, v in states.items() if v == "found"], ["execution_profiles"])
        check("problems about a section do not make the run unreadable", doc["readable"])
        # a notes: line indented at the key's own level is lost to status only (the role reads the file raw)
        (notes(root) / "discovery.yaml").write_text('execution_profiles:\n  state: "found"\n  evidence: []\n  notes: |\n    kept\n  dropped: no\n', encoding="utf-8")
        check_eq("an Edit leaves other sections as they were: the others are still pending", status(root)["discovery_sections"]["run_commands"], "pending")
        (notes(root) / "discovery.yaml").write_bytes(b"\xff\xfe\x00 not utf8")
        doc = status(root)
        check("an unreadable discovery.yaml: every section pending, named", set(doc["discovery_sections"].values()) == {"pending"} and any("discovery.yaml" in p for p in doc["problem"]), str(doc["problem"]))
    finally:
        cleanup(root)


def risk_ranking_row() -> None:
    """OH2-3 (t-1193): `risk_ranking` is a data row of the skeleton (AR-1), held pending until discovery resolves it
    (AR-28: never skipped silently), and phase 2 names only section ids the data file holds (AR-22)."""
    ids = DATA["discovery_sections"]
    check_eq("OH2-3: risk_ranking is a data row, right after declared_conventions",
             ids[ids.index("declared_conventions") + 1] if "declared_conventions" in ids else None, "risk_ranking")
    skeleton = N.emit_discovery_skeleton(ids)
    check("OH2-3: the skeleton holds the row pending (never skipped silently)",
          'risk_ranking:\n  state: "pending"\n  evidence: []\n' in skeleton)
    root = started("qa-onb-rank-")
    try:
        check_eq("OH2-3: a fresh run shows the row pending", status(root)["discovery_sections"].get("risk_ranking"), "pending")
        # a notes file from before this row: no such section in discovery.yaml. It shows the row pending, named by no problem
        old = "".join(SECTION.format(id=s, state='"found"', evidence="[]", notes='""') for s in ids if s != "risk_ranking")
        (notes(root) / "discovery.yaml").write_text(old, encoding="utf-8")
        doc = status(root)
        check_eq("OH2-3: an older notes file (no risk_ranking section) shows the row pending, the file still readable",
                 (doc["discovery_sections"].get("risk_ranking"), doc["readable"]), ("pending", True))
        check("OH2-3: ...and the missing row is not a problem the status names", not any("risk_ranking" in p for p in doc["problem"]), str(doc["problem"]))
        # the resolved forms: nothing found (the paths looked at are in notes), a document found
        resolved = old + SECTION.format(id="risk_ranking", state='"not_read_nothing_found"', evidence="[]", notes='"looked at: docs/, README.md"')
        (notes(root) / "discovery.yaml").write_text(resolved, encoding="utf-8")
        doc = status(root)
        check_eq("OH2-3: a resolved row reads back as written", doc["discovery_sections"].get("risk_ranking"), "not_read_nothing_found")
        check("OH2-3: ...and no problem names the row", not any("risk_ranking" in p for p in doc["problem"]), str(doc["problem"]))
    finally:
        cleanup(root)
    p2 = (PH / "p2-interview.md").read_text(encoding="utf-8")
    check("OH2-3: phase 2 names section `risk_ranking` (the checker finds it: positive control)", "risk_ranking" in section_ids_named(p2), str(section_ids_named(p2)))
    check_eq("OH2-3: every section id phase 2 names is a row of the data file", unknown_section_ids(p2, ids), [])
    check_eq("OH2-3 NEGATIVE CONTROL: a section id that is no data row is reported by the same checker",
             unknown_section_ids("read the section `no_such_row` first", ids), ["no_such_row"])
    check_eq("OH2-3: ...and with the row dropped from the data, phase 2's name is reported",
             unknown_section_ids(p2, [s for s in ids if s != "risk_ranking"]), ["risk_ranking"])
    evals = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
    eval13 = [e for e in evals if e["id"] == 13][0]
    check("OH2-3: eval 13 carries the one assertion about the resolved row (no new eval)",
          [a["name"] for a in eval13["assertions"]].count("discovery-risk-ranking-resolved") == 1,
          str([a["name"] for a in eval13["assertions"]]))


def section_ids_named(text: str) -> list:
    """The ids a phase text names as `section `<id>``: the reader of the data file's rows (AR-22)."""
    return re.findall(r"section `([A-Za-z0-9_.-]+)`", normalised(text))


def unknown_section_ids(text: str, ids) -> list:
    return [s for s in section_ids_named(text) if s not in ids]


def staleness() -> None:
    # a project in a git SUBFOLDER: the diff must be relative to the project root
    top = repo("qa-onb-stale-")
    try:
        proj = top / "sub" / "proj"
        proj.mkdir(parents=True)
        (proj / "pom.xml").write_text("<a/>\n", encoding="utf-8")
        (proj / "other.py").write_text("x = 1\n", encoding="utf-8")
        git(top, "add", ".")
        git(top, "commit", "-qm", "proj")
        call(proj, "start", "--tree", "clean")
        text = SECTION.format(id="ci_gates", state='"found"', evidence='["pom.xml:3"]', notes='""')
        text += SECTION.format(id="run_commands", state='"found"', evidence='["other.py:1"]', notes='""')
        text += SECTION.format(id="declared_conventions", state='"found"', evidence="[]", notes='""')
        (notes(proj) / "discovery.yaml").write_text(text, encoding="utf-8")
        doc = status(proj)
        check_eq("K11: nothing changed: nothing is stale", (doc["changed_since"], doc["stale_sections"]), ([], []))
        (proj / "pom.xml").write_text("<a><b/></a>\n", encoding="utf-8")
        doc = status(proj)
        check_eq("K11: editing an evidence file in a git subfolder marks its section stale", (doc["changed_since"], doc["stale_sections"]), (["pom.xml"], ["ci_gates"]))
        head = doc["head_then"]
        without = subprocess.run(["git", "diff", "--name-only", head], cwd=str(proj), capture_output=True, text=True).stdout.split()
        check_eq("K11 control: the same diff WITHOUT --relative names sub/proj/pom.xml (would match no evidence)", without, ["sub/proj/pom.xml"])
        check("an untouched section stays fresh, and the section with no evidence is never stale", "run_commands" not in doc["stale_sections"] and "declared_conventions" not in doc["stale_sections"])

        # an unknown head: every section with evidence is stale, the problem is named
        path = notes(proj) / "progress.yaml"
        good = path.read_text(encoding="utf-8")
        path.write_text(good.replace(head, "d" * 40), encoding="utf-8")
        doc = status(proj)
        check_eq("K11: an unknown head marks every section with evidence stale", (doc["changed_since"], doc["stale_sections"]), ([], ["ci_gates", "run_commands"]))
        check("K11: ...and names the cause (git exit 128)", any("not known" in p and "128" in p for p in doc["problem"]), str(doc["problem"]))
        path.write_text(good.replace(head, ""), encoding="utf-8")
        doc = status(proj)
        check("an empty head is the same: stale, named", doc["stale_sections"] == ["ci_gates", "run_commands"] and any("no usable head" in p for p in doc["problem"]), str(doc["problem"]))
        path.write_text(good.replace(head, "--output=/x"), encoding="utf-8")
        doc = status(proj)
        check("a head that looks like a git option is never passed to git: stale, named", doc["stale_sections"] == ["ci_gates", "run_commands"], str(doc))
    finally:
        cleanup(top)

    # the path forms
    changed = {"a.py"}
    for label, entry in (("a.py:3", "a.py:3"), ("./a.py:3", "./a.py:3"), (".\\a.py:3", ".\\a.py:3"), ("a.py", "a.py"), ("A.PY:3 (case)", "A.PY:3")):
        check(f"K11: {label} matches a.py", N.evidence_is_stale(entry, {N._norm_path(c) for c in changed}))
    cn = {N._norm_path("a.py")}
    check("K11: C:/abs/a.py:1 counts as stale (cannot be compared)", N.evidence_is_stale("C:/abs/a.py:1", cn))
    check("K11: ../x counts as stale", N.evidence_is_stale("../x", cn))
    check("K11: /abs/x counts as stale", N.evidence_is_stale("/abs/x", cn))
    check("K11: a non-string entry counts as stale", N.evidence_is_stale({"a": 1}, cn))
    check("K11 control: b.py:3 is not stale when only a.py changed", not N.evidence_is_stale("b.py:3", cn))
    check("a directory entry is stale when a file below it changed", N.evidence_is_stale("src/", {N._norm_path("src/x/y.py")}))
    check("a path with a colon and no line is still compared whole", N.evidence_is_stale("dir/a:b.py", {N._norm_path("dir/a:b.py")}))

    # no git at all
    root = temp_dir("qa-onb-nogit-")
    try:
        call(root, "start", "--tree", "clean")
        (notes(root) / "discovery.yaml").write_text(SECTION.format(id="ci_gates", state='"found"', evidence='["x.py:1"]', notes='""'), encoding="utf-8")
        doc = status(root)
        check("no git, no head: stale and named, status still exits 0", doc["stale_sections"] == ["ci_gates"] and doc["head_then"] is None and doc["problem"], str(doc["problem"]))
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- the locator

def locator_and_two_sessions() -> None:
    root = started("qa-onb-loc-")
    try:
        found = N.open_onboarding(root)
        check_eq("open_onboarding finds the run at the root", (found["open"], found["phase"], found["root"], found["path"]),
                 (True, "p1", root.resolve(), notes(root)))
        below = root / "src" / "deep"
        below.mkdir(parents=True)
        found = N.open_onboarding(below, {"cwd": str(below)})
        check_eq("C8 (library): a cwd below the root still finds the run", (found["open"], found["root"]), (True, root.resolve()))
        check_eq("...and without an event only the given root is looked at", N.open_onboarding(below)["open"], False)
        # a partial folder with no progress file is still reported, unreadable
        call(root, "set-aside")
        (notes(root) / "words").mkdir()
        found = N.open_onboarding(root)
        check("a partial folder (words/ only) is reported, unreadable", found["open"] and not found["readable"], str(found))
        (notes(root) / "words").rmdir()
        check_eq("an empty folder with only its ignore file is not a run", N.open_onboarding(root)["open"], False)
        check_eq("reading created nothing: the folder holds its ignore file and retired/", sorted(os.listdir(notes(root))), [".gitignore", "retired"])
    finally:
        cleanup(root)
    fresh = temp_dir("qa-onb-loc2-")
    try:
        before = tree(fresh)
        N.open_onboarding(fresh, {"cwd": str(fresh)})
        check_eq("open_onboarding on a project with no qa-factory/ creates nothing", tree(fresh), before)
    finally:
        cleanup(fresh)


def atomic_and_data() -> None:
    root = temp_dir("qa-onb-atomic-")
    try:
        target = root / "f.yaml"
        N.write_atomic(target, "a: 1\n")
        N.write_atomic(target, "a: 2\n")
        check_eq("write_atomic replaces and leaves no temp file", (target.read_text(encoding="utf-8"), os.listdir(root)), ("a: 2\n", ["f.yaml"]))
    finally:
        cleanup(root)
    source = (SCRIPTS / "onboarding_notes.py").read_text(encoding="utf-8")
    check("F4: the line separators are written as escapes in the source, not as the characters (an editor or a splitlines would eat them)",
          " " not in source and " " not in source and "\\u2028" in source and "\\u2029" in source)
    check_eq("F4: and the escape still does its work: U+2028 and U+2029 are written as \\uXXXX", (N.q("a b c"),), ('"a\\u2028b\\u2029c"',))
    check_eq("the data file's phases are the spec's", DATA["phases"], ["p1", "p2", "p2b", "p3", "p4", "done"])
    check_eq("the data file's states are the spec's", DATA["section_states"],
             ["pending", "found", "gap", "inferred", "read", "not_read_no_checkout", "not_read_nothing_found"])
    check_eq("topic states and the p4 prefix", (DATA["topic_states"], DATA["after_approval_batch_prefix"]), (["answered", "not_answered"], "p4-"))
    check_eq("the folder is a value of the data file", DATA["folder"], "qa-factory/state/onboarding")
    phases_dir = PLUGIN_ROOT / Path(*DATA["phases_dir"].split("/"))
    check("every phase file the data file names exists", all((phases_dir / n).is_file() for n in DATA["phase_files"].values() if n),
          str([n for n in DATA["phase_files"].values() if n and not (phases_dir / n).is_file()]))
    check_eq("phase_files names every phase", sorted(DATA["phase_files"]), sorted(DATA["phases"]))
    check("the sections are unique ids", len(set(DATA["discovery_sections"])) == len(DATA["discovery_sections"])
          and all(N.ID_RE.match(s) for s in DATA["discovery_sections"]))
    # the CLI as a process: stdout is one JSON document, a refusal goes to stderr (FR-14)
    root = temp_dir("qa-onb-proc-")
    try:
        p = subprocess.run([sys.executable, "-B", str(SCRIPTS / "onboarding_notes.py"), "--root", str(root), "status"],
                           capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        check("FR-14: status as a process prints one JSON document and exits 0", p.returncode == 0 and list(json.loads(p.stdout)) == STATUS_KEYS, p.stderr[-200:])
        p = subprocess.run([sys.executable, "-B", str(SCRIPTS / "onboarding_notes.py"), "--root", str(root), "phase", "--set", "p2"],
                           capture_output=True, text=True, encoding="utf-8", env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        check("a refusal as a process: stdout empty, stderr names the door, exit 2", p.returncode == 2 and p.stdout == "" and "start --tree" in p.stderr, p.stderr[-200:])
        check_eq("...and it created nothing", tree(root), [])
    finally:
        cleanup(root)


# --------------------------------------------------------------------------------------- the texts (doc witness)

SKILL = PLUGIN_ROOT / "skills" / "qa-onboarding"
SKILL_MD = SKILL / "SKILL.md"
PH = SKILL / "phases"


def normalised(text: str) -> str:
    return " ".join(text.split())


def present(path: Path, sentence: str) -> bool:
    """The key, whitespace-normalised, as a substring of the file, whitespace-normalised (A8)."""
    return normalised(sentence) in normalised(path.read_text(encoding="utf-8"))


# The keys, quoted VERBATIM from the DoD of t-472 (variant (a)) before this run was written.
KEYS = [
    ("T1a", SKILL_MD, "The one exception is the run's own notes in `qa-factory/state/onboarding/`: git ignores that folder from its first file, and every phase writes what it found and what the person answered there as it goes."),
    ("T2", SKILL_MD, "After a compaction or in a new session, run `onboarding_notes.py --root . status` and continue from what it reports: a topic it lists as answered is never asked again, and the notes win over memory."),
    ("T3", PH / "p0-preflight.md", "When `onboarding_notes.py --root . status` reports an unfinished onboarding, show its date, its phase and the topics already answered, and ask one question: resume it, start over (its notes are set aside, never deleted), or stop."),
    ("T4", PH / "p1-discovery.md", "Write each row's finding into its section of `discovery.yaml` in the notes folder as soon as the row is resolved, before reading the next row's sources; write `notes:` lines indented deeper than the `notes:` key."),
    ("T5", PH / "p2-interview.md", "Record a batch before sending it (`onboarding_notes.py --root . ask`), and record the reply, as given, before doing anything else (`onboarding_notes.py --root . answer --words-file <file>`)."),
    ("T6", PH / "p2-interview.md", "A batch the notes show as asked with no reply recorded is asked once more, saying why: the context was compacted before the reply was written down."),
    ("T7", PH / "p3-summary-gate.md", "Build the summary from the notes (`onboarding_notes.py --root . status` names their folder), not from memory."),
    ("P1 p2", PH / "p2-interview.md", "`onboarding_notes.py --root . phase --set p2`"),
    ("P1 p2b", PH / "p2b-rediscovery.md", "`onboarding_notes.py --root . phase --set p2b`"),
    ("P1 p3", PH / "p3-summary-gate.md", "`onboarding_notes.py --root . phase --set p3`"),
    ("R6 start", PH / "p1-discovery.md", "onboarding_notes.py\" --root . start --tree <clean|dirty>"),
    ("R9 proposal", PH / "p3-summary-gate.md", "it is written to `<notes>/proposal.json`, the run's own notes, and nothing else under `qa-factory/`"),
    ("R9 freeze", PH / "p3-summary-gate.md", "phase --set p4 --approval-ref <ref> --sealed"),
    ("R9 forget", PH / "p3-summary-gate.md", "onboarding_notes.py --root . set-aside"),
    ("A7 p3 gate", PH / "p3-summary-gate.md", "the only gate before anything is written in the project"),
    ("A7 p3 gate (a)", PH / "p3-summary-gate.md", "other than the run's own notes"),
    ("A7 SKILL row", SKILL_MD, "no project file is written until \"yes\""),
    ("R1 rows", SKILL_MD, "Read-only in the project, notes in `qa-factory/state/onboarding/`"),
    ("R10 times_asked", PH / "p4-generate.md", "counted with the `times_asked` of that profile's batch in the notes"),
    ("R10 batch names", PH / "p4-generate.md", "named `p4-<profile>-<n>`"),
    ("R7 pending gap", PH / "p2-interview.md", "A section it reports `pending` because of a `problem` is an open gap, never treated as found."),
    ("F1 p2", PH / "p2-interview.md", "Name every topic of the batch in `--answered` or `--not-answered`; one left out stays awaiting and is asked again"),
    ("F2 p2", PH / "p2-interview.md", "record such a file with `answer` instead of asking again"),
    ("R8 batch", PH / "p2b-rediscovery.md", "the batch is `p2b-access`"),
    ("README (a)", SKILL / "README.md", "No project file is written until you say `yes`"),
    # OH1-10 (t-1161): the risk-areas question and the form sizing.py reads. Keys chosen BEFORE the first run of this file.
    ("OH1-10 p2 question", PH / "p2-interview.md", "Which parts of the product - features, screens, services - would hurt most if they broke?"),
    ("OH1-10 p2 three answers", PH / "p2-interview.md", "(a) Name the areas, most important first."),
    ("OH1-10 p2 how to answer", PH / "p2-interview.md", "How to answer: write the areas in your own words, most important first"),
    ("OH1-10 p2 two topic ids", PH / "p2-interview.md", "`4` (the risk areas) and `4-map` (the impact-class map)"),
    ("OH1-10 p2 E16 kept on a later", PH / "p2-interview.md", "a person's earlier answer is never erased by a later deferral"),
    # t-1172 fix round (critic t-1166 B-1, F-1, F-3, F-5): the E16 carriers, interview and generator halves. Keys chosen BEFORE the run.
    ("OH1-10 B-1 p2 E16 option (c) label", PH / "p2-interview.md", "(c) reads \"Keep what is on record.\" and ALL THREE of its lines change to"),
    ("OH1-10 B-1 p2 E16 option (c) price lines",PH / "p2-interview.md", "the factory: nothing runs. you: nothing more. the story: sized by the areas on record; delivery unchanged."),
    ("OH1-10 F-1 p2 E16 recorded as answered", PH / "p2-interview.md", "the topic goes in `--answered`, never `--not-answered`: the record stands as the default"),
    ("OH1-10 F-1 p3 part 4 kept topic 4 is not deferred", PH / "p3-summary-gate.md", "Topic 4 kept as on record is not a deferred item (it has no marker and no row): it is shown in part 2."),
    ("OH1-10 F-3 p4 E16 keep clause covers (c) and silence", PH / "p4-generate.md", "asked again, or answered (c) or silence: the paragraph"),
    ("OH1-10 F-3 p4 step 2 deferred needs no paragraph", PH / "p4-generate.md", "Deferred (answer (c) or silence, with no paragraph on record): no labels"),
    ("OH1-10 F-3 p4 step 5 marker needs no paragraph", PH / "p4-generate.md", "not answered (answer (c) or silence, with no paragraph on record): the same marker text"),
    ("OH1-10 F-5 p4 the resolve removes the marker", PH / "p4-generate.md", "with the marker line left where it stands; the resolve (`project_decisions.py resolve`) removes it, and the generator never removes the marker"),
    ("OH1-10 p3 summary shows the areas", PH / "p3-summary-gate.md", "the risk areas as they will be written"),
    ("OH1-10 p4 P2 label follows P1", PH / "p4-generate.md", "So `**P2 areas.**` always follows `**P1 areas.**`"),
    ("OH1-10 p4 the none sentence", PH / "p4-generate.md", "No area stands out: the team named no part of the product as riskier than the rest"),
    ("OH1-10 p4 B-1 marker in every lens branch", PH / "p4-generate.md", "Whichever lenses are written (those discovery found, those the team's areas added, or the three inferred ones), put the marker `[DEFERRED: risk areas not named]` on its own line under the intro line"),
    ("OH1-10 p4 E16 paragraph kept", PH / "p4-generate.md", "the paragraph, from that label to the next `## ` heading, is kept byte for byte"),
    ("OH1-10 p4 one row for both files", PH / "p4-generate.md", "A deferred risk-areas answer is ONE row for both files"),
    ("OH1-10 p4 B-2 resolve names both files, gives no value (OH2-6: a document ref)", PH / "p4-generate.md", "--resolution-ref <evidence> --marker-file qa-factory/strategy/test-strategy.md --marker-file qa-factory/strategy/aspect-profile.md --marker-text \"[DEFERRED: risk areas not named]\""),
    ("OH1-10 strategist input table", PLUGIN_ROOT / "agents" / "qa-test-strategist.md", "the P1/P2/P3 risk areas"),
    ("OH1-10 F-2 automation input 3", PLUGIN_ROOT / "references" / "automation-candidacy.md", "A critical flow, a fragile area, a P1 area, a history of bugs, a shared component, or a migration in the blast radius — named in `test-strategy.md`"),
    ("OH1-10 backlog template example", PLUGIN_ROOT / "references" / "templates" / "factory-backlog.md", "(the main risk areas left open, a tracker integration postponed"),
    ("OH1-10 SKILL phase row", SKILL_MD, "risk areas and the impact-class map"),
    ("OH1-10 eval 13 assertion", SKILL / "evals" / "evals.json", "\"name\": \"p1-areas-paragraph-parses\""),
    ("OH1-10 eval 14 assertion", SKILL / "evals" / "evals.json", "\"name\": \"later-is-a-deferral-with-a-row\""),
    # OH2-3 (t-1193): discovery looks for a document that ranks areas; P2's offer rests on it. Keys chosen BEFORE the first run.
    ("OH2-3 p1 row", PH / "p1-discovery.md", "A project document that ranks areas or names fragile places — a risk register, SLO/SLA documents, incident post-mortems, an ownership map that marks critical services — read, and recorded in section `risk_ranking` with its path:line."),
    ("OH2-3 p1 link is a gap", PH / "p1-discovery.md", "A link to a document outside the repository is recorded as a gap with the link, not opened."),
    ("OH2-3 p1 never a ranking", PH / "p1-discovery.md", "Folder size, churn or test counts are never a ranking"),
    ("OH2-3 p1 none found is a state", PH / "p1-discovery.md", "it is `not_read_nothing_found`, and its `notes:` name the paths and patterns searched"),
    ("OH2-3 p2 offer rests on the section", PH / "p2-interview.md", "a project document that ranks areas (`discovery.yaml` section `risk_ranking`, named by its path; a linked one is named as a link the factory did not open)"),
    ("OH2-3 p2 nothing-found alternative", PH / "p2-interview.md", "is said only when that section is `not_read_nothing_found`"),
    ("OH2-3 p2 pending says nothing", PH / "p2-interview.md", "while the section is still `pending`, the question is put with no found-sentence at all"),
    ("OH2-3 p2 no checkout or inferred say nothing found either", PH / "p2-interview.md", "The same holds when the section is `not_read_no_checkout` or `inferred`: nothing was read that ranks areas, so the question is put with no found-sentence and without the alternative above, which claims a search that found nothing."),
    # t-1204 (the critic's C-c2): the P1 duty that makes P2's `pending` clause a corner case, not the normal path
    ("OH2-3 p1 the section is never left pending", PH / "p1-discovery.md", "Section `risk_ranking` is never left `pending` when this phase ends: phase 2 reads it before topic 4 asks."),
    ("OH2-3 p1 several documents", PH / "p1-discovery.md", "With several documents, each gets its own `evidence:` line, the one that ranks areas first."),
    ("OH2-3 eval 13 assertion", SKILL / "evals" / "evals.json", "\"name\": \"discovery-risk-ranking-resolved\""),
    # OH2-6 (b) (t-1217): the impact-scale marker's meaning (P2, P3, P4) and the DD row that names a document. Keys chosen BEFORE the run.
    ("OH2-6 p4 doc-ref add", PH / "p4-generate.md", "`project_decisions.py --root . add --field-ref doc:strategy/test-strategy.md#risk-and-impact-scale"),
    ("OH2-6 p4 a document ref writes nothing into config", PH / "p4-generate.md", "A document ref writes nothing into `config.json`"),
    ("OH2-6 p4 narrowed marker sentence", PH / "p4-generate.md", "`[DEFERRED: impact scale not set]` stands in its place only when the targeted question about a preserved legacy numeric value was asked and not answered, with its DD (step 8)"),
    ("OH2-6 p4 impact-scale add", PH / "p4-generate.md", "`project_decisions.py --root . add --field-ref /impact_scale/<class> --essence \"impact scale not set: strategy/test-strategy.md (Risk and impact scale)\" --asked \"batch <id>: <the question as it was put>\" --trigger-type manual`"),
    ("OH2-6 p4 integrations add has its essence (Q1)", PH / "p4-generate.md", "`project_decisions.py --root . add --field-ref /environment/integrations --essence \"environment integrations kept by the person's word: config.json\" --asked"),
    ("OH2-6 p2 4-map unanswered, no legacy value", PH / "p2-interview.md", "Unanswered with no legacy value: the canonical map stands; record `4-map` in `--not-answered`; no marker and no backlog row (the canonical map is a complete answer, not a hole)."),
    ("OH2-6 p2 recording exception by reference", PH / "p2-interview.md", "The one exception is topic `4-map` with no legacy numeric value: the canonical map stands as a complete answer (topic 4, question 2), so it is recorded in `--not-answered` with no marker and no row."),
    ("OH2-6 p3 part 2 says kept the canonical map", PH / "p3-summary-gate.md", "an impact-class map left unanswered with no legacy value is shown here as \"kept the canonical map\" (it is not a deferred item)"),
    # OH2-6 (b) fix round (t-1222): the template names the F-4 exception; the generic DD recipe names both ref forms. Keys chosen BEFORE the run.
    ("OH2-6 fix F1 template names the F-4 exception", PLUGIN_ROOT / "references" / "templates" / "factory-backlog.md", "except an impact-class map left unanswered with no legacy value: the canonical map stands, no row"),
    ("OH2-6 fix F2 p2 recipe names both ref forms", PH / "p2-interview.md", "by `field_refs`: a JSON pointer, or a document ref `doc:<path>[#<anchor>]` (`--field-values` is omitted when every ref is a document ref)"),
    ("OH2-6 fix F2 p4 add names both ref forms", PH / "p4-generate.md", "add --field-ref <json-pointer-or-doc:path[#anchor]>"),
    ("OH2-6 fix F2 p4 resolve omits --field-values for doc refs", PH / "p4-generate.md", "(`--field-values` is omitted when every ref is a document ref; their exact answer"),
]
# Negative pins: the old texts that must be GONE (FR-10: the texts no longer contradict each other).
PINS = [
    ("p2 'nothing is written to disk yet'", PH / "p2-interview.md", "nothing is written to disk yet"),
    ("p1 'Working notes only (no file)'", PH / "p1-discovery.md", "Working notes only (no file)"),
    ("p3 'This is the only gate before anything is written in `qa-onboarding`'", PH / "p3-summary-gate.md", "This is the only gate before anything is written in `qa-onboarding`"),
    ("SKILL 'the only point at which any file under `qa-factory/` is created'", SKILL_MD, "the only point at which any file under `qa-factory/` is created"),
    ("SKILL 'nothing is written until \"yes\"'", SKILL_MD, "nothing is written until \"yes\""),
    ("p3 'nothing is written to `qa-factory/` for it'", PH / "p3-summary-gate.md", "nothing is written to `qa-factory/` for it"),
    ("eval 3 'No file exists anywhere under qa-factory/'", SKILL / "evals" / "evals.json", "No file exists anywhere under qa-factory/"),
    ("SKILL 'no writes anywhere in the project'", SKILL_MD, "no writes anywhere in the project"),
    ("p0 'in-memory copy'", PH / "p0-preflight.md", "retain an in-memory copy"),
    # OH1-10 (t-1161): the dropped wording must be gone (FR-10: the texts no longer contradict each other).
    ("OH1-10 strategist 'risk multipliers'", PLUGIN_ROOT / "agents" / "qa-test-strategist.md", "risk multipliers"),
    ("OH1-10 p4 'project aspects not named'", PH / "p4-generate.md", "project aspects not named"),
    ("OH1-10 p2 'weighed as high priority' (the effect is size, not priority)", PH / "p2-interview.md", "weighed as high priority"),
    ("OH1-10 p2 old topic 4 heading", PH / "p2-interview.md", "4. **Risk and impact scale.**"),
    ("OH1-10 F-4 p2 damage-class examples ('costs money, loses data')", PH / "p2-interview.md", "costs money, loses data"),
    ("OH1-10 backlog template 'a default risk multiplier'", PLUGIN_ROOT / "references" / "templates" / "factory-backlog.md", "a default risk multiplier"),
    ("OH1-10 SKILL row 'risk and impact scale'", SKILL_MD, "risk and impact scale,"),
    # OH2-3 (t-1193): the offer that named a document discovery never looked for must be gone
    ("OH2-3 p2 offer 'ranks areas (named by its path)'", PH / "p2-interview.md", "a project document that ranks areas (named by its path)"),
    # OH2-6 (b) (t-1217): the risk-areas row names a document now; the config pointer and its "known gap" sentence are gone
    ("OH2-6 p4 the /risk_areas config pointer", PH / "p4-generate.md", "--field-ref /risk_areas"),
    ("OH2-6 p4 'known gap' of /risk_areas", PH / "p4-generate.md", "nothing reads it (a known gap, queued as its own node)"),
    ("OH2-6 p4 the marker 'if empty'", PH / "p4-generate.md", "`[DEFERRED: impact scale not set]` if empty"),
    ("OH2-6 fix F2 p2 'matched by JSON-pointer `field_refs`'", PH / "p2-interview.md", "matched by JSON-pointer `field_refs`"),
    ("OH2-6 fix F2 p4 'add --field-ref <json-pointer>'", PH / "p4-generate.md", "add --field-ref <json-pointer>"),
]


def texts() -> None:
    for name, path, sentence in KEYS:
        check(f"K-TEXT {name}: present in {path.name}", present(path, sentence), sentence[:90])
    for name, path, sentence in PINS:
        check(f"K-TEXT negative pin: {name} is gone from {path.name}", not present(path, sentence))
    evals = json.loads((SKILL / "evals" / "evals.json").read_text(encoding="utf-8"))
    eval3 = [e for e in evals["evals"] if e["id"] == 3][0]
    check("T9: eval 3 says 'except the run's own notes in qa-factory/state/onboarding/'",
          "except the run's own notes in qa-factory/state/onboarding/" in eval3["expected_output"], eval3["expected_output"][:120])
    check("T9: ...and its assertion says it too", "except the run's own notes in qa-factory/state/onboarding/" in json.dumps(eval3["assertions"]))
    # F5: the package benchmark is a reader of the same promise (FR-10): the entry says the notes may exist before the yes
    bench_path = PLUGIN_ROOT / "evals" / "plugin-eval-benchmark.json"
    bench = json.loads(bench_path.read_text(encoding="utf-8"))
    first = [b for b in bench["benchmarks"] if b["id"] == "onboarding-happy-path-writes-scoped"][0]["success_criteria"][0]
    check("F5: the benchmark file parses and its onboarding criterion allows the run's own notes before the yes",
          "qa-factory/state/onboarding/" in first and "no project file exists under qa-factory/" in first, first[:160])
    check("F5: ...and no longer quotes the removed SKILL.md phrase 'nothing is written before yes'",
          "'nothing is written before yes'" not in bench_path.read_text(encoding="utf-8"))
    # the doc-witness NEGATIVE CONTROL: a sentence that is in no file must be reported absent
    check("NEGATIVE CONTROL: a deliberately absent sentence is reported absent by the same matcher",
          not present(SKILL_MD, "Nothing here is written before the moon is full, and every phase reads it twice."))
    check("NEGATIVE CONTROL: ...and a key whose whitespace differs but words do not still matches (A8)",
          present(PH / "p0-preflight.md", "When  `onboarding_notes.py --root . status`\nreports an unfinished onboarding"))
    # builder-rules 5: SKILL.md budget (11111 bytes before this node) and the physical lines of the wrapped keys
    size = SKILL_MD.stat().st_size
    lines = SKILL_MD.read_text(encoding="utf-8").count("\n")
    check("SKILL.md: net growth at most 700 bytes (11111 before) and under the 19000 byte / 500 line caps",
          size <= 11111 + 700 and size <= 19000 and lines <= 500, f"{size} bytes, {lines} lines")
    text = SKILL_MD.read_text(encoding="utf-8")
    for name, fragments in (("T1a", ("The one exception is the run's own notes", "that folder from its first file", "answered there as it goes.")),
                            ("T2", ("After a compaction or in a new session", "from what it reports"))):
        first = [ln for ln in text.splitlines() if any(f in ln for f in fragments)]
        check(f"{name} is wrapped: no physical line of it reaches 200 bytes", len(first) >= 2 and all(len(ln.encode("utf-8")) < 200 for ln in first),
              str([len(ln) for ln in first]))
    p0 = (PH / "p0-preflight.md").read_text(encoding="utf-8").splitlines()
    check("T3 is wrapped: its lines are under 200 bytes", all(len(ln.encode("utf-8")) < 200 for ln in p0 if "unfinished onboarding" in ln or "start over" in ln), "")


def main() -> None:
    absent_and_shape()
    round_trips_and_batches()
    replies_and_batches()
    partial_replies_and_reask_rules()
    refusals_and_ids()
    frozen_and_phases()
    set_aside_close_and_start()
    git_clean()
    discovery_states()
    risk_ranking_row()
    staleness()
    locator_and_two_sessions()
    atomic_and_data()
    texts()
    finish("onboarding notes")


if __name__ == "__main__":
    main()
