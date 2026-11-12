"""CL1-4 (t-1062; t-962 section 6, L-2 F-5 / m5 / m15 / m18): the qa-collect skill, its activity type and the way it calls the packer.

Expectations come from the spec text, not from the code's output (FR-58): the two questions are quoted below from t-962 section 6 (the
one change: the "How to answer" line is a `## How to answer` block, because the form `human_text` recognises as the answer block is a
heading or `---` + `Answer:`; the words are the spec's). Keys:

  S1  the file: bytes (target 4 KB, hard cap 19000 B), frontmatter (name, allowed-tools exactly Bash + Write), three Bash lines
  S2  the questions: the spec text, word for word; one message, two questions, the cost line once; `human_text` finds nothing wrong
  S3  the options the skill names are the options the command has; the steps the skill writes work on a project (blank / answered /
      not_asked; the archive is written in every case; a second run reads only the newer, timestamped words files - F4)
  S4  FACTORY_TYPES is ONE set (TYPES is the same object), it holds the old types and `collect`, the activity recorder accepts it, the
      dashboard group is labelled by it, and the dashboard's own label set (FIXED_LABELS) knows the label (F2)
"""
import contextlib
import io
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import PLUGIN_ROOT, SCRIPTS, check, check_eq, cleanup, finish, mark_project, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import activity_capture as AC  # noqa: E402
import collect_pack as C  # noqa: E402
import dashboard_cost_groups as DCG  # noqa: E402
import factory_dashboard as FD  # noqa: E402
import human_text  # noqa: E402
import machine_facts as M  # noqa: E402

SKILL = PLUGIN_ROOT / "skills" / "qa-collect" / "SKILL.md"
BASE = temp_dir("collect-skill-")
NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)

# t-962 section 6, verbatim (the em dash included); the last line is the answer block in the form human_text recognises.
QUESTIONS = (
    "Before I pack the factory's records for its developers, two questions \u2014 answer either, both or neither, in your own words:\n"
    "1. What problems did you have with the QA factory since it was installed (or since the factory last packed them)?\n"
    "2. What would you like the factory to do differently or better?\n"
    "Answering costs you only this message; the factory then runs one packing command, no agent works; your stories are unchanged.\n"
    "## How to answer\n"
    'reply with your two answers, or "nothing to add".\n')


def skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


def asked(text: str) -> str:
    """The message the skill tells the agent to send: its blockquote, markers removed."""
    return "".join((line[2:] if line.startswith("> ") else line[1:]) + "\n" for line in text.split("\n") if line.startswith(">"))


def s1_the_file():
    raw = SKILL.read_bytes()
    text = raw.decode("utf-8")
    check("S1 FR-51 / m15: the skill is small - target 4 KB (it is a prompt read on every run), and far under the 19000 B cap", len(raw) <= 4096 and len(raw) < 19000, f"{len(raw)} bytes")
    front = text.split("---")[1]
    check_eq("S1 FR-56: name qa-collect, allowed-tools exactly Bash and Write (no Read, no Agent: no role, no LLM work)",
             (re.search(r"^name:\s*(\S+)", front, re.M).group(1), re.findall(r"^\s+- (\w+)\s*$", front.split("allowed-tools:")[1], re.M)), ("qa-collect", ["Bash", "Write"]))
    lines = [ln.strip() for ln in text.split("\n") if "run-py.cmd" in ln]
    cmds = [re.search(r"run-py\.cmd\"\s+([^`]+)`", ln).group(1).split() for ln in lines]
    check_eq("S1 m15: three Bash lines in this order - start the activity, ONE packing command (from the project root), end the activity after the response",
             [(c[0], c[1:3]) for c in cmds] + [cmds[0][1:], cmds[2][1:]],
             [("activity_capture.py", ["--action", "start"]), ("collect_pack.py", ["--root", "."]), ("activity_capture.py", ["--action", "end"]),
              ["--action", "start", "--type", "collect"], ["--action", "end", "--type", "collect", "--after-response"]])
    # F4 (t-1067, the Lead's word): the words files are named by time like the sibling skills' (never overwritten, never deleted)
    check("S1 F4: the words go to qa-factory/state/words/collect-problems-<stamp>.txt and collect-suggestions-<stamp>.txt, <stamp> is yyyymmddThhmmss, a clash gets -2",
          all(p in text for p in ("qa-factory/state/words/collect-problems-<stamp>.txt", "qa-factory/state/words/collect-suggestions-<stamp>.txt", "yyyymmddThhmmss", "add `-2`")))
    check("S1 F4: no fixed words-file name is left (a second collect would overwrite it), and the packing line names the files by placeholder",
          not re.search(r"collect-(problems|suggestions)\.txt", text) and "--problems-file <problems file> --suggestions-file <suggestions file>" in text)
    check("S1 F6 / FR-15: the plugin root is stated in the skill itself (CLAUDE_PLUGIN_ROOT holding scripts/hooklib.py, else two levels up) - no pointer to a file the skill cannot read",
          "scripts/hooklib.py" in text and "two levels up" in text and "common-rules" not in text)
    check("S1 F1 section 6: --extra when the output (or a refusal) names `--extra <SET>=`, which is what 'not found at the standard place' prints",
          "not found at the standard place" in text and "names `--extra <SET>=`" in text)
    check("S1 F9 / F10: the two things only the agent sees are carried by an option each, named at the step where they happen",
          text.count("--activity-not-recorded") == 1 and text.count("--answers-not-split") == 1 and "ACTIVITY NOT RECORDED" in text and "is a finding" not in text)
    check("S1: no other command than the three", text.count("run-py.cmd") == 3)


def s2_the_questions():
    got = asked(skill_text())
    check_eq("S2 section 6: the message is the spec's text word for word (a changed word fails here)", got, QUESTIONS)
    check_eq("S2: one message, two questions: exactly two numbered questions, and the cost line stated once",
             (len(re.findall(r"^\d\. ", got, re.M)), got.count("Answering costs you only this message")), (2, 1))
    check_eq("S2 FR-6: human_text.problems finds nothing wrong with the message (no path, script or flag in the body; the answer block at the bottom)", human_text.problems(got), [])
    body, how = human_text.split(got)
    check("S2 FR-6: the body has no path, script or flag (the answer block holds only the instruction to reply)",
          not re.search(r"\.py|--[a-z]|[/\\]", body) and how.strip().startswith("## How to answer") and how.strip().endswith('"nothing to add".'))
    control = got.replace("one packing command", "one packing command (collect_pack.py --root .)")
    check("S2 negative control: a script name put into the body IS found by the same check", any(p["rule"] == "script_name" for p in human_text.problems(control)), str(human_text.problems(control)))
    check("S2 negative control: the answer block missing IS found", any(p["rule"] == "no_how_to_answer" for p in human_text.problems(got.replace("## How to answer", ""))))


def run_main(argv, **extra):
    out, err = io.StringIO(), io.StringIO()
    seams = dict(redactor=RED, git=lambda p, *a: (124, ""), temp_root=BASE / "out", rules_sha=M.rules_sha256(), now=NOW)
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = C.main(argv, **{**seams, **extra})
    return code, out.getvalue(), err.getvalue()


def answers_of(out):
    doc = json.loads(out)
    import zipfile
    with zipfile.ZipFile(doc["archive"]) as zf:
        return json.loads(zf.read("manifest.json").decode("utf-8"))["answers"], doc


def s3_the_command():
    text = skill_text()
    helped = subprocess.run([sys.executable, "-B", str(SCRIPTS / "collect_pack.py"), "--help"], capture_output=True, text=True, encoding="utf-8").stdout
    named = {o for o in re.findall(r"`[^`\n]*(--[a-z][a-z-]+)", text) + re.findall(r"(--[a-z][a-z-]+)", text.split("4. ONE Bash")[1].split("5. Show")[0])}
    own = {"--action", "--type", "--after-response"}
    check_eq("S3: every option the skill gives the packing command is an option the command has", sorted(o for o in named - own if o not in helped), [])
    check("S3: ... and the skill gives the command its answers files, the door --extra, --since install, --not-asked for a run with no person, and the two things only the agent sees",
          {"--root", "--problems-file", "--suggestions-file", "--extra", "--since", "--not-asked", "--activity-not-recorded", "--answers-not-split"} <= named, str(sorted(named)))
    root = mark_project(BASE / "p-blank")
    code, out, err = run_main(["--root", str(root), "--json"])
    ans, _d = answers_of(out)
    check_eq("S3 m5: 'nothing to add' / an answer left out = no file, no option -> BLANK for both; the archive is written", (code, ans), (0, {"problems": {"state": "blank", "arc": None}, "suggestions": {"state": "blank", "arc": None}}))
    code, out, err = run_main(["--root", str(root), "--not-asked", "--json"])
    ans, _d = answers_of(out)
    check_eq("S3 m5: nobody to ask (--not-asked) = NOT_ASKED for both, and the archive is written in this case too", (code, ans["problems"]["state"], ans["suggestions"]["state"]), (0, "not_asked", "not_asked"))
    words = BASE / "collect-problems-20261019T120000.txt"           # F4: named by time, as the skill tells the agent
    words.write_bytes("It stopped twice.\r\nSecond paragraph.\n".encode("utf-8"))
    code, out, err = run_main(["--root", str(root), "--problems-file", str(words), "--json"])
    ans, doc = answers_of(out)
    import zipfile
    with zipfile.ZipFile(doc["archive"]) as zf:
        kept = zf.read(ans["problems"]["arc"])
    check_eq("S3 FR-8 / I7: the words are kept as the person gave them (CRLF and paragraphs intact), only the answered option is answered",
             (ans["problems"]["state"], ans["suggestions"]["state"], kept), ("answered", "blank", b"It stopped twice.\r\nSecond paragraph.\n"))
    # F4: a second collect writes a NEW pair; the earlier pair stays on disk (never overwritten, never deleted) and only the files NAMED are read
    old_s = BASE / "collect-suggestions-20261019T120000.txt"
    old_s.write_bytes(b"OLD suggestion of the first run\n")
    new_p = BASE / "collect-problems-20261019T130000.txt"
    new_p.write_bytes(b"It stopped again.\n")
    code, out, err = run_main(["--root", str(root), "--problems-file", str(new_p), "--since", "install", "--json"], now=NOW.replace(hour=13))
    ans2, doc2 = answers_of(out)
    with zipfile.ZipFile(doc2["archive"]) as zf:
        kept2 = zf.read(ans2["problems"]["arc"])
        blob = b"".join(zf.read(n) for n in zf.namelist())
    check_eq("S3 F4: the second run's answer is the NEWER file's words, the earlier pair is still on disk, and an old suggestions file that is not named is not read (blank)",
             (ans2["problems"]["state"], kept2, ans2["suggestions"]["state"], b"OLD suggestion" in blob, words.read_bytes().startswith(b"It stopped twice."), old_s.is_file()),
             ("answered", b"It stopped again.\n", "blank", False, True, True))


def s4_activity_type():
    old = {"onboarding", "doctor", "story", "environment-maintenance", "unclassified"}
    check("S4 F-5: FACTORY_TYPES holds the old five and `collect`", old | {"collect"} <= AC.FACTORY_TYPES and AC.FACTORY_TYPES == old | {"collect"}, str(AC.FACTORY_TYPES))
    check("S4 F-5: TYPES is the SAME object (an alias, not a copy that can drift)", AC.TYPES is AC.FACTORY_TYPES)
    path = BASE / "activity.json"
    AC.update(path, "s-collect", "start", "collect", "", "evt-1")
    doc = json.loads(path.read_text(encoding="utf-8"))
    check_eq("S4: the recorder takes the type, with no fall back to unclassified (P18: the skill's spend is classified)", [a["type"] for a in doc["activities"]], ["collect"])
    refused = None
    try:
        AC.update(BASE / "x.json", "s", "start", "not-a-type", "", "e")
    except ValueError as exc:
        refused = str(exc)
    check("S4 control: a type that is not in the set is still refused", refused == "invalid activity type", str(refused))
    check("S4 F-5: the dashboard group reads FACTORY_TYPES (its named labels are the set less story and unclassified)", DCG.NAMED_TYPES == AC.FACTORY_TYPES - {"story", "unclassified"} and "collect" in DCG.NAMED_TYPES)
    request = {"request_key": "k1", "activity_id": "a1", "task": None, "timestamp": "2026-10-19T10:00:00Z", "usage": {"input": 5}, "valuation": {}}
    got = DCG.group([{"session_id": "s1", "by_activity": {"a1": {"type": "collect"}}, "requests": [request]}])
    labels = set(got[0]) if isinstance(got, tuple) else set(got.get("tasks", got))
    check("S4 F-5: a request made under a `collect` activity is labelled Collect on the dashboard, not Unclassified", "Collect" in labels and "Unclassified" not in labels, str(labels))
    doctor = DCG.group([{"session_id": "s2", "by_activity": {"a1": {"type": "doctor"}}, "requests": [request]}])
    check("S4 control: the old types keep their labels (doctor -> Doctor)", "Doctor" in (set(doctor[0]) if isinstance(doctor, tuple) else set(doctor.get("tasks", doctor))))
    # F2 (t-1067): the dashboard keeps a SECOND label set, FIXED_LABELS; a label outside it is read as 'a task name a tag carries' and captioned 'tagged only'
    check("S4 F2: every named type's label is in the dashboard's FIXED_LABELS (a type added to FACTORY_TYPES without its label fails here)",
          {t.title() for t in DCG.NAMED_TYPES} <= FD.FIXED_LABELS and "Collect" in FD.FIXED_LABELS and "Unclassified" in FD.FIXED_LABELS, str(sorted(FD.FIXED_LABELS)))
    rows = FD.task_groups([{"session_id": "s1", "by_activity": {"a1": {"type": "collect"}}, "requests": [request]}], [],
                          {"T-1": {"price_low_usd": None, "sessions": [{"session_id": "zz"}]}}, {}, None)["by_task"]
    check("S4 F2: with a price answer on the money page the skill's spend is the row 'Collect', not 'Collect - tagged only, not counted in its price'",
          "Collect" in rows and not any(k.startswith("Collect -") for k in rows), str(list(rows)))


RED = M.compile_redactor(M.load_rules(), project_root=str(BASE), plugin_root=str(PLUGIN_ROOT), pythons=(sys.executable,), home="C:\\Users\\Alexandra_Testova",
                         tmp=str(BASE), identities={"users": ["Alexandra_Testova"], "display_names": [], "emails": [], "machine": [], "domain": []}, hosts=(), secret_values={}, short=lambda p: None)

try:
    s1_the_file()
    s2_the_questions()
    s3_the_command()
    s4_activity_type()
finally:
    cleanup(BASE)
finish("test_collect_skill")
