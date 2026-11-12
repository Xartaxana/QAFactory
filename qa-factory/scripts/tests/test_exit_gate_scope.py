#!/usr/bin/env python3
"""exit_gate.scoped_errors: a role is blocked only by broken artifacts its own stage writes.

Second half (t-172 / B-231, P8b): the scout's manifest and receipts are checked against the person's list of
sources not to read (`source_exclusions.manifest_problems`), on the shapes of the real TP1-15045 manifest
that cited the excluded draft merge request as a requirement source and as existing coverage.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import exit_gate  # noqa: E402

ERRS = ["context-manifest.json: required key 'acceptance_criteria' is missing",
        "TC-006.md: required field 'title' is missing",
        "run-report.json: execution_status outside the vocabulary",
        "BUG-1.md: oracle missing"]
real_collect_errors = exit_gate.collect_errors
real_bug_audit_errors = exit_gate.bug_audit_errors
exit_gate.collect_errors = lambda task="", facts_text="": list(ERRS)
exit_gate.bug_audit_errors = lambda task="", facts_text="": [ERRS[3]]
fails = 0
total = 0


def check(name, ok, detail=""):
    global fails, total
    total += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" — {detail}"))
    fails += 0 if ok else 1


scout = exit_gate.scoped_errors("qa-scout")
check("scout sees only its manifest error", scout == [ERRS[0]], str(scout))
designer = exit_gate.scoped_errors("qa-case-designer")
check("designer sees only case errors", designer == [ERRS[1]], str(designer))
runner = exit_gate.scoped_errors("qa-runner")
check("runner sees only run-report errors", runner == [ERRS[2]], str(runner))
reporter = exit_gate.scoped_errors("qa-bug-reporter")
check("bug reporter sees only bug errors", reporter == [ERRS[3]], str(reporter))
foreign = exit_gate.scoped_errors("some-other-agent")
# t-003 (TP2-2406, Codex Desktop): a stop with no stage - a foreign agent, or a factory role the host
# returned as `default` - is judged by the project bug audit alone (scoped to its story), never by the phase
# json, cases or register of a story it may not even belong to: one broken upstream artifact blocked every
# later role's stop. Before t-003 a stage-less stop with a known task saw everything.
check("a stage-less agent sees the bug audit only", foreign == [ERRS[3]], str(foreign))

# t-1020 m-1: the header of an unnamed audit (`bug_audit_errors("unknown-task")`) stays with the bug findings of a
# role WITH a stage, in front of them, and is dropped where those bugs are not the role's (a header alone would block).
HEADER = exit_gate._unnamed_header("\n  ids named by the dispatch text: none")
exit_gate.collect_errors = lambda task="", facts_text="": [HEADER] + list(ERRS)
reporter = exit_gate.scoped_errors("qa-bug-reporter", "unknown-task", "\n  x")
check("m-1: a staged bug reporter keeps the unnamed header, first", reporter == [HEADER, ERRS[3]], str(reporter))
scout = exit_gate.scoped_errors("qa-scout", "unknown-task", "\n  x")
check("m-1: a role that owns no bug finding gets no header", scout == [ERRS[0]], str(scout))
exit_gate.collect_errors = lambda task="", facts_text="": list(ERRS)

# ---- B-231 P8b: the manifest detector on the shapes of the real manifest ---------------------------------
exit_gate.collect_errors = real_collect_errors
exit_gate.bug_audit_errors = real_bug_audit_errors
import harness  # noqa: E402
import hooklib  # noqa: E402
import source_exclusions as SE  # noqa: E402

HEAD = "135699ae2c182eccd49ba6c66f469fc1c55359f1"      # the revision the 15045 manifest gives MR 1924
UI_1881 = "e6532059cc2a965c0a37ba1a40cd481652d40481"
BACKEND = "0cc6c4f1104985cf1fcf338e09172c41cc01c82d"

# The shapes of `work/context-manifest.json` of TP1-15045 (the judge run of 23.09; the cmp1 copy holds the
# same bytes): requirement_sources[] ref "testproject1-ui!1924 (...)", existing_test_candidates[] with `repo` and
# `candidate_requirement_refs`, implementations[] with `repo_id` and `mr` as an iid string, known_paths,
# constraints, evidence_ref. Trimmed to the fields a matcher could read; nothing is invented.
M5 = {
    "implementations": [
        {"repo": "testproject1-backend", "repo_id": "testproject1-backend", "mr": "4214", "branch": "TP1-14482_visual-workflow-diff",
         "commit": BACKEND, "source_sha": BACKEND},
        {"repo": "testproject1-ui", "repo_id": "testproject1-ui", "mr": "1881", "branch": "TP1-14482_visual-workflow-diff",
         "commit": UI_1881, "source_sha": UI_1881}],
    "requirement_sources": [
        {"source_id": "SRC-ca56bd10fb494da41f68", "relation": "task", "ref": "TP1-15045",
         "revision": "2026-09-18T08:23:41.338+0000", "status": "read", "evidence_ref": "work/source-inventory.json"},
        {"source_id": "MR-ui-1881", "relation": "technical", "ref": "testproject1-ui!1881", "revision": UI_1881,
         "status": "read", "evidence_ref": "work/mr-testproject1-ui_-_merge_requests_1881.json"},
        {"source_id": "MR-ui-1924", "relation": "referenced",
         "ref": "testproject1-ui!1924 (draft QA-evaluation test MR, not a product change)", "revision": HEAD,
         "status": "read", "evidence_ref": "work/mr-testproject1-ui_-_merge_requests_1924.json"}],
    "existing_test_candidates": [
        {"candidate_id": "C-UI-restore-validate", "repo": "testproject1-ui", "revision": UI_1881,
         "path": "src/pages/workflows/__tests__/EditWorkflowPage.versionHistory.test.tsx", "selector": "restore validate",
         "candidate_requirement_refs": ["AC-6"], "origin": "existing"},
        {"candidate_id": "C-UI-1924-factory", "repo": "testproject1-ui", "revision": HEAD,
         "path": "src/pages/workflows/**/__tests__/*.test.tsx",
         "selector": "7 test files, +348/-43 vs MR 1881; draft evaluation tests, MR 1924 build failed, not merge-ready",
         "candidate_requirement_refs": ["AC-1", "AC-2", "AC-3", "AC-4", "AC-5", "AC-7"], "origin": "unknown"}],
    "known_paths": ["qa-factory/artifacts/TP1-15045/work/test-mr-1924-diff.txt"],
    "constraints": ["P-00: testproject1 and testproject1-ui are read-only", "MR 1924 is evaluation-only, not product coverage"],
}

TASK = "TP1-15045"


def story(list_text: str, head=HEAD):
    """A temp project with the story's record written by the real module: (root, task root)."""
    root = harness.temp_project("qa-exgate-")
    task_root = root / "qa-factory" / "artifacts" / TASK
    (task_root / "work").mkdir(parents=True)
    entries, problems = SE.parse_bytes(list_text.encode("utf-8"), TASK)
    assert not problems, problems
    for entry in entries:
        if entry["target"]["kind"] == "mr":
            entry["target"]["head_sha"] = head
    SE.write_record(task_root, entries, "list.txt", list_text.encode("utf-8"))
    return root, task_root


def where(errors):
    return sorted(e.split(" cites ")[0].split(": ", 1)[1] for e in errors if " cites " in e)


LIST = "testproject1-ui!1924 - Draft MR of an earlier factory run, not a product change\n"
root, task_root = story(LIST)
try:
    found = SE.manifest_problems(task_root, M5)
    check("manifest_cites_excluded_mr: the requirement source and the existing-coverage candidate are caught",
          where(found) == ["existing_test_candidates[1]", "requirement_sources[2]"], str(found))
    check("manifest_cites_excluded_mr: every error is for the scout's own file and names the word and the door",
          all(e.startswith("context-manifest.json: ") and "testproject1-ui!1924" in e and "X1" in e
              and "say so in your handoff" in e for e in found), str(found))
    check("manifest_free_text_not_matched: constraints and known_paths that say 1924 are not caught",
          not any("constraints" in e or "known_paths" in e for e in found) and len(found) == 2, str(found))

    # implementations[]: repo tail AND the number, whole
    def impl(repo_id, mr, **more):
        manifest = copy.deepcopy(M5)
        manifest["implementations"][1].update(repo_id=repo_id, repo=repo_id, mr=mr, commit="", source_sha="", branch="")
        manifest["implementations"][1].update(more)
        manifest["requirement_sources"] = []
        manifest["existing_test_candidates"] = []
        return where(SE.manifest_problems(task_root, manifest))

    check("implementations: repo_id tail and mr equal the word: caught", impl("testproject1-ui", "1924") == ["implementations[1]"])
    check("implementations: `!1924` as written is the same number", impl("testproject1-ui", "!1924") == ["implementations[1]"])
    check("implementations: the number inside a longer number is not the number", impl("testproject1-ui", "19240") == [])
    check("implementations: the same number in a repo whose tail is shorter (testproject1) is not caught",
          impl("testproject1", "1924") == [])
    check("implementations: a repo path whose tail is the project's is the project", impl("tp1-group/testproject1-ui", "1924") == ["implementations[1]"])
    check("implementations: a commit that is the excluded head is caught with no number at all",
          impl("testproject1-ui", "", commit=HEAD) == ["implementations[1]"])
    check("implementations: an abbreviated head of 11 characters is never a match",
          impl("testproject1-ui", "", commit=HEAD[:11]) == [])
    check("implementations: an abbreviated head of 12 characters is", impl("testproject1-ui", "", source_sha=HEAD[:12]) == ["implementations[1]"])

    # existing_test_candidates[]: the object, not the sentence (C3)
    def candidate(**fields):
        manifest = {"existing_test_candidates": [dict({"candidate_id": "C-X", "repo": "testproject1-ui",
                                                       "selector": "", "revision": UI_1881}, **fields)]}
        return where(SE.manifest_problems(task_root, manifest))

    check("candidate: repo tail equals the project and the number is a whole token: caught",
          candidate(candidate_id="C-UI-1924-factory") == ["existing_test_candidates[0]"])
    check("candidate: the number only inside a longer number: no match", candidate(selector="build 219245 and 19240") == [])
    check("candidate: the number inside a word (test_1924) is no token", candidate(selector="test_1924") == [])
    check("candidate: another repo with the number is no match", candidate(repo="testproject1", candidate_id="C-1924") == [])
    check("candidate: the excluded head alone (a citation with no number in it) is caught", candidate(revision=HEAD) == ["existing_test_candidates[0]"])
    check("candidate: the same head in another repo's object is not this word's candidate", candidate(repo="tests", revision=HEAD) == [])

    # the receipt scan: fetch-leak (C3)
    receipt = task_root / "work" / "mr-testproject1-ui_-_merge_requests_1924.json"
    receipt.write_text(json.dumps({"url": "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924",
                                   "host": "git.example", "project": "tp1-group/testproject1-ui", "iid": "1924",
                                   "status": "read", "revision": HEAD}), encoding="utf-8")
    nested = task_root / "work" / "sources" / "SRC-1" / "mr-1924.json"
    nested.parent.mkdir(parents=True)
    nested.write_text(json.dumps({"host": "git.example", "project": "tp1-group/testproject1-ui", "iid": "1924"}), encoding="utf-8")
    by_revision = task_root / "work" / "git-show.json"
    by_revision.write_text(json.dumps({"revision": HEAD[:12], "files": []}), encoding="utf-8")
    unrelated = task_root / "work" / "mr-testproject1-ui_-_merge_requests_1881.json"
    unrelated.write_text(json.dumps({"url": "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1881",
                                     "host": "git.example", "project": "tp1-group/testproject1-ui", "iid": "1881",
                                     "revision": UI_1881}), encoding="utf-8")
    (task_root / "work" / "source-inventory.json").write_text(json.dumps({"sources": [{"materials": {"external_media": {
        "items": [{"url": "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924", "status": "excluded"}]}}}]}),
        encoding="utf-8")
    leaked = [e for e in SE.manifest_problems(task_root, {}) if e.startswith("source-inventory.json: ")]
    names = sorted(e.split(": ", 2)[1].split(" holds ")[0] for e in leaked)
    check("receipt: url, host+project+iid and revision each name a live exclusion; the 1881 receipt and the inventory do not",
          names == ["work/git-show.json", "work/mr-testproject1-ui_-_merge_requests_1924.json", "work/sources/SRC-1/mr-1924.json"],
          str(leaked))

    # another story's receipt is not read
    other = root / "qa-factory" / "artifacts" / "TP1-14482" / "work"
    other.mkdir(parents=True)
    (other / "mr-1924.json").write_text(json.dumps({"url": "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924"}),
                                        encoding="utf-8")
    again = [e for e in SE.manifest_problems(task_root, {}) if e.startswith("source-inventory.json: ")]
    check("receipt: a receipt of another story under artifacts/* is not read", len(again) == len(leaked) and
          not any("14482" in e for e in again), str(again))

    # the gate itself: the scout sees it, the runner does not (the same scoping as every artifact error)
    saved_root, saved_cache = exit_gate.artifact_root, hooklib._PROJECT_ROOT_CACHE
    hooklib._PROJECT_ROOT_CACHE = root
    exit_gate.artifact_root = lambda: root / "qa-factory" / "artifacts"
    (task_root / "pipeline.json").write_text(json.dumps({"ticket": TASK, "stages": {"S1": {"status": "running"}}}), encoding="utf-8")
    (task_root / "work" / "context-manifest.json").write_text(json.dumps(M5), encoding="utf-8")
    try:
        scout_sees = [e for e in exit_gate.scoped_errors("qa-scout", TASK) if " cites " in e]
        runner_sees = [e for e in exit_gate.scoped_errors("qa-runner", TASK) if " cites " in e]
        check("the S1 exit gate hands the scout the manifest errors and the runner none",
              where(scout_sees) == ["existing_test_candidates[1]", "requirement_sources[2]"] and runner_sees == [],
              f"{scout_sees} / {runner_sees}")
    finally:
        exit_gate.artifact_root, hooklib._PROJECT_ROOT_CACHE = saved_root, saved_cache

    # a record that cannot be read: one error, never a raise, never a silent pass
    SE.record_path(task_root / "work").write_text("{not json", encoding="utf-8")
    broken = SE.manifest_problems(task_root, M5)
    check("an unreadable record is one error that names the file, not a pass and not a crash",
          len(broken) == 1 and "source-exclusions.json" in broken[0], str(broken))
finally:
    harness.cleanup(root)

# no list at all: today's behaviour (temporal, before the list exists)
root2 = harness.temp_project("qa-exgate-none-")
try:
    plain = root2 / "qa-factory" / "artifacts" / TASK
    (plain / "work").mkdir(parents=True)
    (plain / "work" / "mr-1924.json").write_text(json.dumps({"iid": "1924", "host": "git.example",
                                                             "project": "tp1-group/testproject1-ui"}), encoding="utf-8")
    check("no record: no error for a manifest that cites anything, and none for a receipt",
          SE.manifest_problems(plain, M5) == [])
finally:
    harness.cleanup(root2)

# a ref word names a head or a branch, and needs no project
root3, task3 = story("branch:TP1-15045-visual-workflow-diff-validation - the draft branch\n"
                     f"{HEAD[:12]} - its head, by commit\n")
try:
    manifest = {"implementations": [{"repo_id": "x", "branch": "TP1-15045-visual-workflow-diff-validation"}],
                "requirement_sources": [{"ref": "anything", "revision": HEAD}]}
    check("a ref word: the branch and the head commit are caught with no project and no number",
          where(SE.manifest_problems(task3, manifest)) == ["implementations[0]", "requirement_sources[0]"],
          str(SE.manifest_problems(task3, manifest)))
finally:
    harness.cleanup(root3)

# ---- C2-1: the gate reads the WHOLE verdict of a detector and judges each word by the rule of its producer --------------
import contextlib  # noqa: E402
import io  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

import detector_verdict as DV  # noqa: E402
from role_cli import REPAIR_MARKER  # noqa: E402

STAGE = "S5"
NOW = "2026-10-01T10:00:00"


def said(match, decision="the person lets it stand"):
    return {"stage_overrides": [{"stage": STAGE, "match": match, "decision": decision, "at": NOW}]}


def run_fake(script_out: str, code: int = 1, err: str = "", agent: str = "qa-x", script: str = "fake.py"):
    """`detector_errors(agent)` over a detector that printed `script_out` and exited `code`."""
    saved = exit_gate.subprocess.run, exit_gate.detector_gates
    exit_gate.detector_gates = lambda stage="": {agent: [script]}
    exit_gate.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, code, script_out, err)
    try:
        return exit_gate.detector_errors(agent)
    finally:
        exit_gate.subprocess.run, exit_gate.detector_gates = saved


def finding_block(n, label="", tail=""):
    return "\n".join([f"REJECT — {n} finding(s)" + (" " + label if label else "") + ":"]
                     + [f"- finding {i}" for i in range(1, n + 1)]) + ("\n" + tail if tail else "")


recs = run_fake(finding_block(4))
kinds = [r.kind for r in recs]
check("detector_errors: a detector of 4 findings gives 4 finding records and 1 summary",
      kinds == ["finding"] * 4 + ["summary"], str(kinds))
check("...whose texts are `<script>: <finding>` in the order of the output, not a tail of three lines",
      [str(r) for r in recs[:4]] == [f"fake.py: finding {i}" for i in range(1, 5)], str(recs))
check("...and the summary is the record the gate wrote before C2-1, word for word",
      str(recs[4]).startswith("fake.py: REAL exit 1 on the gate re-run (FB-27: quoted detector output is not accepted): "))
marked = run_fake(finding_block(2, tail=REPAIR_MARKER))
check("a marker of the producer is on the FINDING records, verbatim", all(str(r).endswith(f" ({REPAIR_MARKER})")
      for r in marked if r.kind == "finding"), str(marked))
# a defect and the marker in ONE output: a refusal line with no known cause is a defect, the block and its tail are whole
mixed = run_fake(f"{DV.WORDS_REFUSED_AT_SOURCE} a:b:c other\n" + finding_block(3, tail=REPAIR_MARKER))
check("...the findings of that output carry the marker", all(str(r).endswith(f" ({REPAIR_MARKER})")
      for r in mixed if r.kind == "finding") and sum(r.kind == "finding" for r in mixed) == 3, str(mixed))
defect = next(r for r in mixed if r.kind == "defect")
check("...and NOT on a defect of the detector itself (a defect of the factory must not send the role to repair it)",
      REPAIR_MARKER not in defect and "the detector's own defect" in defect and defect.words == "gate", str(defect))
empty = run_fake("", err="")
check("a detector that refused and printed nothing: the third state (RH1-5), never a pass - one `unreadable` record, the conductor's",
      [r.kind for r in empty] == ["unreadable"] and DV.PRINTED_NOTHING in empty[0]
      and str(empty[0]).startswith("fake.py: unreadable - ") and "the conductor takes it" in empty[0],
      str(empty))
old_form = run_fake("REJECT — 2 finding(s):\n- a\n  fix: x\n- b\n  fix: y\n")
check("output not in the contract's form: ONE record, kind unmigrated, shown whole",
      [r.kind for r in old_form] == ["unmigrated", "summary"] and "unmigrated detector output (exit 1" in old_form[0]
      and "- a fix: x - b fix: y" in old_form[0], str(old_form))
labelled = run_fake(finding_block(2, DV.WORDS_AT_SOURCE))
check("a labelled header: the records say the words were judged at the source", {r.words for r in labelled if r.kind == "finding"}
      == {"source"}, str(labelled))
crash = exit_gate.detector_errors("qa-never-heard-of")
check("an agent with no detector: no records", crash == [], str(crash))
# C3-8/9 m4: the unmigrated sentence now has ONE builder (DV.unmigrated_text); the record's BYTES are the ones recorded words
# were matched against, so they are pinned as a literal, not rebuilt from the builder
check("m4: the unmigrated record is byte for byte what the gate wrote before the builder was shared",
      str(old_form[0]) == "fake.py: unmigrated detector output (exit 1; it is not in the one-line-per-finding form, so it is "
                          "shown whole): REJECT — 2 finding(s): - a fix: x - b fix: y", str(old_form[0]))
check("m4: a refusal that printed nothing is told by the constant, and its door is now the conductor (RH1-5: the factory's own defect)",
      str(empty[0]) == f"fake.py: unreadable - exit 1, {DV.PRINTED_NOTHING} - the factory's own defect, not the role's work; "
                       "the conductor takes it", str(empty[0]))

# --- judge_words ---------------------------------------------------------------------------------------------------
R = DV.Record
source = R("s5.py: [oracle oracle:TC-1:changed-after-red-test_five] changed after red: test_five — fix: x", script="s5.py",
           words="source", kind="finding")
summary = R("s5.py: REAL exit 1 on the gate re-run (FB-27: quoted detector output is not accepted): door", script="s5.py",
            kind="summary")
b, p = exit_gate.judge_words([source, summary], said("test_five"), STAGE)
check("(→) a word `test_five` does NOT pass a changed-after-red finding the producer judged (the critic's example): "
      "it stays blocking, nothing is passed", (b, p) == ([source], []), f"{b} {p}")
b, p = exit_gate.judge_words([source, summary], said("REAL exit"), STAGE)
check("...nor through the summary: a source record stays blocking whatever the summary says (rule 2 above rule 4)",
      (b, p) == ([source], []), f"{b} {p}")
check("a summary is never blocking and never shown: with no word, only the real record is left",
      exit_gate.judge_words([source, summary], {}, STAGE) == ([source], []))
gate1, gate2 = R("p.py: finding one", script="p.py", kind="finding"), R("p.py: finding two", script="p.py", kind="finding")
psum = R("p.py: REAL exit 1 on the gate re-run (FB-27: quoted detector output is not accepted): S3 exit: 2 error(s)",
         script="p.py", kind="summary")
b, p = exit_gate.judge_words([gate1, gate2, psum], said("finding two"), STAGE)
check("a detector with no label, 2 findings: a word about one passes that one", (b, [e["error"] for e in p]) == ([gate1], [gate2]),
      f"{b} {p}")
b, p = exit_gate.judge_words([gate1, gate2, psum], said("S3 exit: 2"), STAGE)
check("(←) a word that matched only the old summary passes every plain record of that detector (one release), with the "
      "note in the pass", (b, len(p), {e.get("note") for e in p}) == ([], 2, {exit_gate.SUMMARY_NOTE}), f"{b} {p}")
b, p = exit_gate.judge_words([gate1, gate2, psum], said("REAL exit 1 on the gate"), STAGE)
check("(←) ...also the prefix of the old record", (b, len(p)) == ([], 2), f"{b} {p}")
mixed_rows = [source, gate1, summary, psum]
srcsum = R("s5.py: REAL exit 1 on the gate re-run (S3 exit)", script="s5.py", kind="summary")
b, p = exit_gate.judge_words([source, gate1, srcsum], said("S3 exit"), STAGE)
check("the order of the rules: a word that matched only the summary of the source's script leaves the SOURCE record "
      "blocking, while the plain record of the other script is not touched by it either",
      (b, p) == ([source, gate1], []), f"{b} {p}")
other = R("s5.py: plain", script="s5.py", kind="finding")
b, p = exit_gate.judge_words([source, other, srcsum], said("S3 exit"), STAGE)
check("...but a plain record (`words=gate`) of the SAME script as that summary goes to `passed`, the source record stays",
      (b, [e["error"] for e in p]) == ([source], [other]), f"{b} {p}")
tagged = {c: R(f"s5.py: [x x:{c}] t", script="s5.py", words="source", kind="finding", refused=c)
          for c in ("family", "predating", "unreadable")}
for cause, record in tagged.items():
    b, p = exit_gate.judge_words([record], said("*"), STAGE)
    check(f"`*` does not pass a record the source refused ({cause}): the tag of the source is above `*`", (b, p) == ([record], []),
          f"{b} {p}")
    b, p = exit_gate.judge_words([record], said("x:t"), STAGE)
    check(f"...and a named word does not either ({cause})", (b, p) == ([record], []), f"{b} {p}")
b, p = exit_gate.judge_words([source], said("*"), STAGE)
check("`*` passes a source record that carries no tag (§L-3 id 1 (a))", (b, [e["error"] for e in p]) == ([], [source]), f"{b} {p}")
plain = R("p.py: unmigrated detector output (exit 1; ...): a b c", script="p.py", words="gate", kind="unmigrated")
b, p = exit_gate.judge_words([plain], said("a b c"), STAGE)
check("an unmigrated record: a named word that matches its text does NOT pass it (its items cannot be told apart)",
      (b, p) == ([plain], []), f"{b} {p}")
b, p = exit_gate.judge_words([plain], said("*"), STAGE)
check("...`*` passes it", (b, [e["error"] for e in p]) == ([], [plain]), f"{b} {p}")
refused_un = R(str(plain), script="p.py", words="gate", kind="unmigrated", refused="family")
b, p = exit_gate.judge_words([refused_un], said("*"), STAGE)
check("...but an unmigrated record that carries a source refusal is not passed by `*` (§L-4 above N2)", (b, p) == ([refused_un], []),
      f"{b} {p}")
refused_gate = R("p.py: refused finding", script="p.py", words="gate", kind="finding", refused="family")
b, p = exit_gate.judge_words([refused_gate, psum], said("S3 exit: 2"), STAGE)
check("rule 2 above rule 4: a record that carries a source refusal is not passed through a summary (t-772 m1)",
      (b, p) == ([refused_gate], []), f"{b} {p}")
b, p = exit_gate.judge_words([refused_gate, gate1, psum], said("S3 exit: 2"), STAGE)
check("...while the passable record of the same script rides the summary as before",
      (b, [e["error"] for e in p]) == ([refused_gate], [gate1]), f"{b} {p}")
b, p = exit_gate.judge_words(["a plain str finding"], said("plain str"), STAGE)
check("a plain str (a stub, another check's error) is judged as before: by the word", (b, p[0]["error"]) == ([], "a plain str finding"))
check("no words at all: everything but summaries blocks", exit_gate.judge_words([gate1, psum, "x"], {}, STAGE) == ([gate1, "x"], []))

# --- the whole verdict through witness_errors, and the list through main -------------------------------------------
root = Path(tempfile.mkdtemp(prefix="qa-eg-witness-"))
try:
    (root / "QA-W" / "work").mkdir(parents=True)
    (root / "QA-W" / "work" / "code-review.md").write_text("x", encoding="utf-8")
    saved = exit_gate.witness_gates, exit_gate.artifact_root, exit_gate.subprocess.run, exit_gate.project_root
    exit_gate.witness_gates = lambda: {"qa-w": "work/code-review.md"}
    exit_gate.artifact_root = lambda: root
    exit_gate.project_root = lambda: root
    five = "REJECT — 5 problem(s): acceptance forbidden:\n" + "\n".join(f"- problem {i}" for i in range(1, 6))
    exit_gate.subprocess.run = lambda *a, **k: subprocess.CompletedProcess(a, 1, five, "")
    try:
        got = exit_gate.witness_errors("qa-w", "QA-W")
    finally:
        exit_gate.witness_gates, exit_gate.artifact_root, exit_gate.subprocess.run, exit_gate.project_root = saved
    check("witness_errors: an artifact with 5 errors gives 5 records and the summary", [r.kind for r in got] == ["finding"] * 5
          + ["summary"] and str(got[0]) == "work/code-review.md: problem 1", str(got))
    check("...whose words the gate judges", {r.words for r in got} == {"gate"})
finally:
    shutil.rmtree(root, ignore_errors=True)

import harness  # noqa: E402,F811

EVENT = {"hook_event_name": "SubagentStop", "agent_type": "qa-scout", "session_id": "s", "task_id": "QA-CUT",
         "dispatch_id": "d1", "completion_attempt": "a1", "input_fingerprint": "f1"}


def run_main(event: dict, findings: list) -> tuple:
    """`(exit code, stderr, stdout)` of `exit_gate.main()` for this host event when the detectors give `findings`."""
    names = ("scoped_errors", "detector_errors", "witness_errors", "required_outputs_errors", "next_hint", "read_event")
    saved = [getattr(exit_gate, n) for n in names]
    exit_gate.scoped_errors = lambda _a, _t="", _f="": []
    exit_gate.witness_errors = lambda _a, _t="": []
    exit_gate.required_outputs_errors = lambda _a, _t="": []
    exit_gate.next_hint = lambda _a: ""
    exit_gate.detector_errors = lambda _a, _t="": list(findings)
    exit_gate.read_event = lambda: dict(event)
    err, out, code = io.StringIO(), io.StringIO(), 0
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
            exit_gate.main()
    except SystemExit as exc:
        code = int(exc.code or 0)
    finally:
        for n, f in zip(names, saved):
            setattr(exit_gate, n, f)
    return code, err.getvalue(), out.getvalue()


def receipt_of(proj: Path, dispatch: str) -> dict:
    state = json.loads((proj / "qa-factory" / "state" / ".exit_gate_blocks.json").read_text(encoding="utf-8"))
    return next(r for r in state.values() if r.get("dispatch") == dispatch)


many = [R(f"d.py: finding {i:04d} " + "x" * 40, script="d.py") for i in range(1, 401)]
proj = harness.temp_project("qa-eg-cut-")
try:
    harness.use_project(proj)
    (exit_gate.artifact_root() / "QA-CUT").mkdir(parents=True)     # the story: S0 makes it, the hook never does (CX1-18)
    code, text, _out = run_main(EVENT, many)
    full = exit_gate.artifact_root() / "QA-CUT" / "state" / "findings" / "exit-gate-qa-scout.txt"
    check("main: a list over the byte ceiling blocks (exit 2), says how many, and names the file that holds all of it",
          code == 2 and "400 finding(s)" in text and f"the whole list: {full}" in text, text[-400:])
    check("...the file exists and holds every finding, the first and the last", full.is_file()
          and "finding 0001" in full.read_text(encoding="utf-8") and "finding 0400" in full.read_text(encoding="utf-8")
          and full.read_text(encoding="utf-8").startswith("# 400 finding(s), "))
    check("...the message itself stays within the ceiling (the pointer line apart)",
          len("\n".join(text.split("\n- (+")[0].splitlines()[1:]).encode("utf-8")) < DV.FINDINGS_MAX_BYTES + 400, str(len(text)))
    receipt = receipt_of(proj, "d1")
    check("...and the fuse receipt carries the total, not a count of ten", receipt["errors_total"] == 400
          and 10 < len(receipt["errors"]) < 400, str(receipt)[:200])
    check("...and the file as a path under the task root, not an absolute one (a stored path is a hint, t-772 m7)",
          receipt.get("errors_file") == "state/findings/exit-gate-qa-scout.txt" and "errors_file_note" not in receipt,
          str(receipt)[:300])
    moved = Path(tempfile.mkdtemp(prefix="qa-eg-moved-"))
    try:
        shutil.copytree(exit_gate.artifact_root() / "QA-CUT", moved / "QA-CUT")
        check("...which stays right when the task root moves", (moved / "QA-CUT" / receipt["errors_file"]).is_file())
    finally:
        shutil.rmtree(moved, ignore_errors=True)
    code, _err, out = run_main({**EVENT, "dispatch_id": "d3", "stop_hook_active": True}, many)
    again = receipt_of(proj, "d3")
    check("the re-entry names the same file and stores the same relative path", code == 0 and f"the whole list: {full}" in out
          and again["status"] == "incomplete" and again.get("errors_file") == "state/findings/exit-gate-qa-scout.txt", str(again)[:300])
finally:
    harness.cleanup(proj)

proj = harness.temp_project("qa-eg-nosave-")
try:
    harness.use_project(proj)
    blocker = exit_gate.artifact_root() / "QA-CUT" / "state" / "findings"
    blocker.parent.mkdir(parents=True)
    blocker.write_text("a file where the folder of the list should be", encoding="utf-8")     # the list cannot be saved
    code, text, _out = run_main(EVENT, many)
    receipt = receipt_of(proj, "d1")
    check("main: the list cannot be saved: it still blocks and says so in words", code == 2 and "could not be saved" in text, text[-300:])
    check("...and the receipt stores no path to a file that does not exist, and says so",
          "errors_file" not in receipt and receipt.get("errors_file_note") == "the whole list was not saved", str(receipt)[:300])
finally:
    harness.cleanup(proj)

# --- t-1020 m-2: the unnamed header explains the findings, it is not one -----------------------------------------------
proj = harness.temp_project("qa-eg-header-count-")
try:
    harness.use_project(proj)
    header = exit_gate._unnamed_header("\n  ids named by the dispatch text: none")
    code, text, _out = run_main(EVENT, [header, "BUG-1.md: oracle missing", "BUG-2.md: oracle missing"])
    check("m-2: a header and two findings print '2 finding(s)', not 3, and the header is still shown",
          code == 2 and "by the exit gate - 2 finding(s)" in text and "3 finding(s)" not in text
          and "this stop names no story" in text, text[:300])
    journal_file = next((exit_gate.project_root() / "qa-factory").rglob("journal.jsonl"), None)
    notes = [json.loads(line).get("notes", "") for line in journal_file.read_text(encoding="utf-8").splitlines()] \
        if journal_file else []
    check("m-2: the journal note counts two and quotes the findings, not the header",
          any("broken artifacts: 2; first: BUG-1.md" in n for n in notes), str(notes)[:300])
finally:
    harness.cleanup(proj)

# --- RN1-1: the child of the doctor's context probe is no stage role ------------------------------------------------------
# Mutation killed (this file): the exemption ignores the mark -> K7 (a stage role keeps its block) or K6 (the probe child is
# blocked again), depending on which way it is wrong; a mark compared by prefix only -> the wrong-challenge control.
PROBE_CHALLENGE = "0123456789abcdef0123456789abcdef"
proj = harness.temp_project("qa-eg-probe-child-")
try:
    harness.use_project(proj)
    (exit_gate.artifact_root() / "QA-CUT").mkdir(parents=True)
    (proj / "qa-factory" / "state").mkdir(parents=True, exist_ok=True)
    (proj / "qa-factory" / "state" / "host-probe.json").write_text(json.dumps(
        {"session_id": "s", "injection": {"challenge": PROBE_CHALLENGE, "status": "emitted", "tool_use_id": "spawn"}}), encoding="utf-8")
    probe_stop = {**EVENT, "dispatch_id": "p1", "last_assistant_message": "QA_CONTEXT_RECEIVED_" + PROBE_CHALLENGE + "_END"}

    def journal_events() -> list:
        journal = next((proj / "qa-factory").rglob("journal.jsonl"), None)
        return [json.loads(line).get("event") for line in journal.read_text(encoding="utf-8").splitlines()] if journal else []

    code, text, _out = run_main(EVENT, ["BUG-1.md: oracle missing"])
    check("K7: a stage role's stop with no form and no mark still BLOCKS (the exemption does not widen)",
          code == 2 and "HANDOFF BLOCKED" in text and journal_events().count("gate_block") == 1, f"{code} {text[:200]}")
    code, text, _out = run_main(probe_stop, ["BUG-1.md: oracle missing"])
    check("K6: the probe child's stop (the mark in its last message) is not judged: exit 0, no new `gate_block`",
          code == 0 and "BLOCKED" not in text and journal_events().count("gate_block") == 1, f"{code} {text[:200]}")
    rows = proj / "child.jsonl"
    rows.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "QA_CONTEXT_RECEIVED_" + PROBE_CHALLENGE + "_END"}]}}) + "\n", encoding="utf-8")
    code, text, _out = run_main({**EVENT, "dispatch_id": "p2", "agent_transcript_path": str(rows)}, ["BUG-1.md: oracle missing"])
    check("K6: ...the same when the mark is in the child's transcript, not in the event", code == 0 and journal_events().count("gate_block") == 1,
          f"{code} {text[:200]}")
    wrong = {**EVENT, "dispatch_id": "p3", "last_assistant_message": "QA_CONTEXT_RECEIVED_" + "f" * 32 + "_END"}
    code, text, _out = run_main(wrong, ["BUG-1.md: oracle missing"])
    check("a child that carries a mark of ANOTHER challenge is judged as today (blocked)", code == 2 and "HANDOFF BLOCKED" in text, f"{code}")
    code, text, _out = run_main({**EVENT, "dispatch_id": "p4", "last_assistant_message": "QA_CONTEXT_RECEIVED_"}, ["BUG-1.md: oracle missing"])
    check("a child that carries only the prefix is judged as today (blocked)", code == 2, f"{code}")
    # m-1 / K3: the mark is tied to the SAME launch (the store's session, status `emitted`, the bound agent) - a stage role that
    # carries a mark it could have read from the store is judged. Kills (this file): a predicate that ignores the session.
    import host_probe
    store_path = proj / "qa-factory" / "state" / "host-probe.json"

    def write_store(**proof):
        store_path.write_text(json.dumps({"session_id": "s", "injection": {"challenge": PROBE_CHALLENGE, "status": "emitted",
                                                                          "tool_use_id": "spawn", **proof}}), encoding="utf-8")
    reads = []
    real_texts = host_probe._assistant_texts
    host_probe._assistant_texts = lambda snapshot: (reads.append(1), real_texts(snapshot))[1]
    try:
        other = {**probe_stop, "dispatch_id": "q1", "session_id": "another", "agent_transcript_path": str(rows),
                 "last_assistant_message": "nothing"}
        code, text, _out = run_main(other, ["BUG-1.md: oracle missing"])
        check("K3: the mark under ANOTHER session is judged (blocked), and no transcript was read for it",
              code == 2 and "HANDOFF BLOCKED" in text and not reads, f"{code} reads={reads}")
        write_store(status="delivered")
        code, text, _out = run_main({**probe_stop, "dispatch_id": "q2"}, ["BUG-1.md: oracle missing"])
        check("K3: after the verdict (`delivered`) the mark exempts nothing (blocked)", code == 2, f"{code}")
        write_store(agent_id="bound-1")
        code, text, _out = run_main({**probe_stop, "dispatch_id": "q3", "agent_id": "someone-else"}, ["BUG-1.md: oracle missing"])
        check("K3: a bound probe and a stop of ANOTHER agent: blocked", code == 2, f"{code}")
        code, text, _out = run_main({**probe_stop, "dispatch_id": "q4", "agent_id": "bound-1"}, ["BUG-1.md: oracle missing"])
        check("K3 control: the stop of the bound agent, same session, `emitted`: exempt", code == 0, f"{code} {text[:200]}")
    finally:
        host_probe._assistant_texts = real_texts
        write_store()
    (proj / "qa-factory" / "state" / "host-probe.json").unlink()
    code, text, _out = run_main({**probe_stop, "dispatch_id": "p5"}, ["BUG-1.md: oracle missing"])
    check("with no probe store a message that looks like the mark exempts nothing (blocked)", code == 2, f"{code}")
finally:
    harness.cleanup(proj)

# --- the fuse key: the whole list the gate saves itself is not the role's work (t-772 M1) ------------------------------
proj = harness.temp_project("qa-eg-key-")
try:
    harness.use_project(proj)
    key_event = {k: v for k, v in EVENT.items() if k != "input_fingerprint"}     # the live path: no host supplies one
    task_dir = exit_gate.artifact_root() / "QA-CUT"
    (task_dir / "work").mkdir(parents=True)
    (task_dir / "work" / "a.md").write_text("a", encoding="utf-8")
    key0 = exit_gate._identity(key_event, "qa-scout")[0]
    check("the key of the same event twice is the same (control)", exit_gate._identity(key_event, "qa-scout")[0] == key0)
    (task_dir / "state" / "findings").mkdir(parents=True)
    (task_dir / "state" / "findings" / "exit-gate-qa-scout.txt").write_text("# 3 finding(s)\n", encoding="utf-8")
    check("the gate's own whole-list file appears: the key is unchanged (else the fuse never fires)",
          exit_gate._identity(key_event, "qa-scout")[0] == key0)
    (task_dir / "state" / "other.json").write_text("{}", encoding="utf-8")
    check("another state file appears: the key changes (a repair is a new check)", exit_gate._identity(key_event, "qa-scout")[0] != key0)
finally:
    harness.cleanup(proj)

# --- the order of the error list (t-892 / C4-7): the files are checked in code point order on every platform -----------
# `collect_errors` walked `rglob("*.json")` and `glob("*BUG-*.md")` raw, so the errors a role read came in the
# order of the directory (raw on Linux, case-folded on NTFS). Recorders stand in for the validators, so the
# witness is the ORDER the walks were taken in, and the case files go through `contract.case_glob` (t-887).
proj = harness.temp_project("qa-eg-order-")
real_checks = (exit_gate.va.check_phase_json, exit_gate.va.check_case, exit_gate.va.check_bug)
try:
    harness.use_project(proj)
    task_dir = exit_gate.artifact_root() / "QA-ORD"
    for rel in ("a/x.json", "C.json", "B/x.json"):
        (task_dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (task_dir / rel).write_text("{}", encoding="utf-8")
    bugs = exit_gate.state_dir() / "bugs"
    bugs.mkdir(parents=True)
    for name in ("aBUG-1.md", "ZBUG-2.md"):
        (bugs / name).write_text("x", encoding="utf-8")
    seen = []
    exit_gate.va.check_phase_json = lambda path, errors, notes: seen.append(path.relative_to(task_dir).as_posix())
    exit_gate.va.check_case = lambda path, errors: None
    exit_gate.va.check_bug = lambda path, errors: seen.append("bug:" + path.name)
    exit_gate.collect_errors("QA-ORD")
    check("collect_errors walks the json files and the bugs in code point order (B/ C a/; ZBUG aBUG), not in disk order",
          seen == ["B/x.json", "C.json", "a/x.json", "bug:ZBUG-2.md", "bug:aBUG-1.md"], str(seen))
finally:
    exit_gate.va.check_phase_json, exit_gate.va.check_case, exit_gate.va.check_bug = real_checks
    harness.cleanup(proj)

print(f"=== test_exit_gate_scope: {total - fails}/{total} ok ===")
sys.exit(1 if fails else 0)
