#!/usr/bin/env python3
"""The stand's BUILD question (t-300 N1b): `Driver.build_check`, the variants of its text, the closed answers and the
`take_answer` branch, by the driver in this process with `claude` replaced by the stub.

Two rigs. The FAKE one registers a probe script named `runtime_probe.py` that prints the record a test put in
`records.json` (so every shape of record the real ladder can print is reachable without docker) and logs the argv it was
run with. The REAL one registers the package's own `runtime_probe.py` over a git checkout with two commits and NO
container, so the ladder runs for real (the registry, a person's word, a `command` row) and a person's answer changes
what the next probe reads - the pair driver <-> probe is exercised end to end.

Keys: K35 the question and its texts (every variant obeys references/human-questions.md), K36 the answers, K37 the
positions and the flag, K38 the `confirm` variant, K39 what is a line and not a question, K40 one question per profile,
K44 a labelled stand asks nothing; plus the edges of the node spec (per window, per dispatch scope, `--task-root`, the
closed forms at and beyond their limits, a commit that is not the story's, a stand the config no longer has).

Mutations this file kills (each by this file alone, run on a scratch copy of the package):
  the question is asked although the record is `matched` (M8) | a free-text answer is read by code as a form (M9) |
  the driver shows the script line to the person (M10)

Run: python -B scripts/tests/test_story_run_stand_identity.py
"""
import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_in, check_not_in  # noqa: E402
from story_run_common import (  # noqa: E402
    OTHER_SCRIPT, run_scenarios,
    d2_answer, d2_conductor_calls, d2_driver, d2_enter, d2_pipeline, d2_seed, eq, human_broken, s0_journal, s0_question,
    s0_state, set_control,
)

HEAD = "e" * 6 + "0" * 34
OLD = "a1b2c3" + "0" * 34
NOWHERE = "9" * 40
TS = "2026-10-03T09:00:00+00:00"
LABEL = "org.opencontainers.image.revision"
DIGEST = "image:sha256:" + "b" * 64
PY = Path(sys.executable).as_posix()

FAKE_PROBE = r'''
import json, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
args = sys.argv[1:]
profile = args[args.index("--profile") + 1]
with (here / "calls.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({"profile": profile, "argv": args}) + "\n")
mode = json.loads((here / "records.json").read_text(encoding="utf-8")).get(profile)
if mode == "__fail__":
    sys.exit(3)
if mode == "__nojson__":
    print("this is not json")
    sys.exit(0)
if mode == "__hang__":
    time.sleep(60)
print(json.dumps(mode))
'''

WRAPPED_PROBE = r'''
import contextlib, io, json, sys
sys.path.insert(0, r"@SCRIPTS@")
import runtime_probe as R
out = io.StringIO()
with contextlib.redirect_stdout(out):
    code = R.main()
record = json.loads(out.getvalue())
record["container"] = record.get("container") or "ui-c"
print(json.dumps(record))
sys.exit(code)
'''

_PLAN: dict = {}


def use_plan(rows: dict) -> None:
    """The plan's rows as `gate_preflight.plan_rows_of` reads them: {case: (profile, disposition)}. The real keying of a row to
    a profile (`s5_profiles`, N1a's K32) runs; only the reading of work/test-plan.json is replaced."""
    import gate_preflight
    _PLAN.clear()
    _PLAN.update(rows)

    def rows_of(task_root, dispositions):
        return [(case, {"execution_profile_id": profile, "disposition": disposition})
                for case, (profile, disposition) in _PLAN.items() if disposition in dispositions]
    gate_preflight.plan_rows_of = rows_of


class Rig:
    """A seeded project (S0 done, controller initialised, stand `localhost` CONFIRMED) with profiles, a registered probe per
    profile and a checkout; the driver is built after the config is final (a Driver reads it once)."""

    def __init__(self, profiles=("api", "e2e-ui"), real=False, foreign=False, timeout=30, task="QA-9", host=False):
        """`real`: the package's own probe. Since EP1-28 a probe that names no container asks the `no_container` question, so
        the REAL rig runs the probe through a thin wrapper that only puts a container NAME in the record (the ladder is the real
        one, docker is not asked): the `how` question and its label / file / command answers stay what these tests are about.
        `host=True`: no wrapper, the plain probe with no container (the application runs on the host)."""
        self.task, self.real, self.profiles = task, real, profiles
        self.root, self.task_root, self.env = d2_seed(task, environment="localhost", pending=False, stands=("localhost",))
        self.config_path = self.root / "qa-factory" / "config.json"
        cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "localhost", "base_url": "http://localhost:8080", "frontend_url": "http://localhost:5173"}]
        cfg["profiles"] = [{"profile_id": p, "capabilities": [p]} for p in profiles]
        cfg["implementation_repos"] = [{"repo_id": f"repo-{p}", "local_path": "ui", "execution_profile_id": p} for p in profiles]
        self.fake = self.root / "fake-probe"
        probes = {}
        if real:
            self.git_checkout()
            head = ["{python}", "{plugin_root}/scripts/runtime_probe.py"]
            if not host:
                wrapper = self.root / "wrapped-probe"
                wrapper.mkdir()
                (wrapper / "runtime_probe.py").write_text(WRAPPED_PROBE.replace("@SCRIPTS@", str(harness.SCRIPTS)), encoding="utf-8")
                head = [sys.executable, str(wrapper / "runtime_probe.py")]
            for p in profiles:
                probes[p] = {"argv": [*head, "--profile", p, "--environment", "localhost",
                                      "--checkout", "ui", "--app-root", "/app"], "cwd": ".", "timeout_s": 60}
        else:
            self.fake.mkdir()
            self.script = self.fake / ("probe_check.py" if foreign else "runtime_probe.py")
            self.script.write_text(FAKE_PROBE, encoding="utf-8")
            self.records()
            for p in profiles:
                probes[p] = {"argv": [sys.executable, str(self.script), "--profile", p, "--environment", "localhost"], "cwd": ".",
                             "timeout_s": timeout}
        cfg.setdefault("execution", {})["runtime_probes"] = probes
        self.config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        self.cfg = cfg

    def git_checkout(self) -> None:
        ui = self.root / "ui"
        ui.mkdir()

        def git(*args):
            return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args], cwd=str(ui),
                                  capture_output=True, text=True, check=True).stdout.strip()
        git("init", "-q")
        git("commit", "--allow-empty", "-q", "-m", "one")
        self.old = git("rev-parse", "HEAD")
        git("commit", "--allow-empty", "-q", "-m", "two")
        self.head = git("rev-parse", "HEAD")
        self.git = git

    def records(self, **by_profile) -> None:
        (self.fake / "records.json").write_text(json.dumps(by_profile), encoding="utf-8")

    def calls(self) -> list:
        path = self.fake / "calls.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.is_file() else []

    def driver(self, **kw):
        return d2_driver(self.root, self.env, self.task, **kw)

    def command_script(self, sha: str) -> list:
        """A registry `command` that prints `sha` - a way a person would give; python itself reads nothing from docker."""
        path = self.root / f"sha-{sha[:6]}.py"
        path.write_text(f"print('{sha}')\n", encoding="utf-8")
        return [sys.executable, str(path)]

    def registry(self) -> Path:
        return self.root / "qa-factory" / "records" / "stand-identity.json"

    def rows(self) -> list:
        return json.loads(self.registry().read_text(encoding="utf-8"))["rows"] if self.registry().is_file() else []

    def confirmations(self) -> list:
        path = self.task_root / "state" / "stand-confirmations.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.is_file() else []

    def put_row(self, method: str, profile: str = None, **extra) -> None:
        import stand_identity as SI
        SI.append_row(self.root, SI.make_row(self.cfg, "localhost", profile or self.profiles[0], method, words="my own words", **extra))

    def sha(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "absent"

    def done(self) -> None:
        harness.cleanup(self.root)


def record(profile, result, **extra) -> dict:
    out = {"profile_id": profile, "timestamp": TS, "environment_id": "localhost", "expected_source_revision": HEAD,
           "observed_runtime_identity": "", "evidence_refs": [], "provenance": {"technical_verification": False},
           "result": result, "comparisons": [], "container": "ui-c", "checkout": "ui"}
    out.update(extra)
    return out


def matched(profile, kind="oci_label", linkage="exact") -> dict:
    return record(profile, "matched", observed_runtime_identity=DIGEST, observed_without_evidence=True,
                  provenance={"technical_verification": True, "source_linkage": linkage, "identity_kind": kind,
                              "deployed_source_revision": HEAD, "verified_source_revisions": [HEAD]})


def unknown(profile, asks="how", **extra) -> dict:
    base = dict(error="which build the stand runs could not be read: no container is named for this profile",
                tried=[{"method": "docker", "outcome": "no container is named for this profile"}], remedy="label the image")
    if asks:
        base["asks_person"] = asks
    base.update(extra)
    return record(profile, "unknown", **base)


def mismatched(profile, **extra) -> dict:
    base = dict(build_sha=OLD, observed_runtime_identity=DIGEST, observed_without_evidence=True,
                provenance={"technical_verification": True, "source_linkage": "exact", "identity_kind": "oci_label",
                            "deployed_source_revision": OLD, "verified_source_revisions": [HEAD]})
    base.update(extra)
    return record(profile, "mismatched", **base)


def sources_mismatched(profile, files) -> dict:
    return record(profile, "mismatched", differing_files=files, observed_runtime_identity="verified_content:abc",
                  provenance={"technical_verification": True, "source_linkage": "verified_content",
                              "deployed_source_revision": "content_mismatch", "verified_source_revisions": [HEAD]})


def run_entry(rig, words=None, stage="S5", built=None, **kw):
    """One driver process: an answer taken first when `words` is given, then one entry into the stage. `built` is a driver
    already made (the 4-tuple of `d2_driver`). (exit code, stdout, roles started, the driver)."""
    if words is None:
        reset_question(rig)         # an entry with no answer is a NEW process with no question the person has not answered
    if built is None:
        extra = dict(kw)
        if words is not None:
            extra["answer"] = d2_answer(rig.root, words)
        built = rig.driver(**extra)
    driver, started = built[0], built[1]
    if stage == "S6":
        driver_stub(driver)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = d2_enter(driver, stage)
    return code, out.getvalue(), started, driver


def reset_question(rig) -> None:
    """The state of a driver process that starts with no question open: the open question, its file and its flag are gone
    (the person answered it, or this is the first run). Everything else of the story is as it was."""
    path = rig.task_root / "state" / "driver-state.json"
    if path.is_file():
        state = json.loads(path.read_text(encoding="utf-8"))
        state["asked"] = {}
        state.pop("build_question", None)
        state.pop("stand_question", None)
        path.write_text(json.dumps(state), encoding="utf-8")
    question = rig.task_root / "state" / "driver-question.md"
    if question.is_file():
        question.unlink()


def asked(rig) -> dict:
    return s0_state(rig.task_root).get("asked") or {}


def flag(rig) -> dict:
    return s0_state(rig.task_root).get("build_question") or {}


def journal_answers(rig) -> list:
    return [str(e.get("notes")) for e in s0_journal(rig.root) if e.get("event") == "human_answer"]


def line_broken(text: str) -> list:
    """The shape rules of references/human-questions.md for one printed line (a status is not a whole question)."""
    import human_text
    return [p["rule"] for p in human_text.problems(text) if p["rule"] not in ("filler", "too_short", "no_how_to_answer")]


# --- K35: the question and its texts ----------------------------------------------------------------------------

def realistic_persons(driver) -> dict:
    """Every variant, and the prefixes stacked on them, with the slots a real stand gives: a label name, a container path, a
    command with a flag and a script name in it (which the text must not carry), a docker message with a flag in it."""
    import stand_identity as SI
    out = SI.data()["outcomes"]
    tried = [{"method": "oci_label", "outcome": out["oci_label.no_label"].format(container="testproject1-ui-static", label=LABEL)},
             {"method": "build_sha_file", "outcome": out["build_sha_file.missing"].format(
                 path="/usr/share/nginx/html/build-sha.txt", container="testproject1-ui-static", why="cat: can't open the file")}]
    row = {"environment_id": "localhost", "profile_id": "e2e-ui", "method": "oci_label", "label": LABEL, "source": "person",
           "recorded_at": "2026-10-01T10:00:00+00:00", "words": "x"}
    command_row = dict(row, method="command", argv=["python3", "print_build.py", "--short"])
    confirms_row = dict(row, method="person_confirms")

    def make(variant, rec, with_row=None, stage="S6", kind="both"):
        return driver.build_person(stage, kind, "localhost", "e2e-ui", rec, with_row, variant)
    voided = {"what": "the checkout moved to commit eeeeee000000", "earlier_at": "2026-10-02T08:00:00+00:00"}
    return {
        "how": make("how", unknown("e2e-ui", tried=tried, container="testproject1-ui-static")),
        "how, more tried": make("how", unknown("e2e-ui", tried=[{"method": "docker", "outcome": "no container is named for this profile"}], tried_more=2)),
        "how, a docker message with a flag": make("how", unknown("e2e-ui", tried=[
            {"method": "docker", "outcome": "docker did not answer (unknown flag: --format; see 'docker inspect --help')"}])),
        "how, registry unreadable": make("how", unknown("e2e-ui", tried=tried, registry_error="qa-factory/records/stand-identity.json: bad")),
        "mismatched": make("mismatched", mismatched("e2e-ui"), row),
        "mismatched by a command": make("mismatched", mismatched("e2e-ui", provenance={
            "technical_verification": True, "source_linkage": "exact", "identity_kind": "command", "deployed_source_revision": OLD,
            "verified_source_revisions": [HEAD]}), command_row),
        "mismatched_sources": make("mismatched_sources", sources_mismatched("e2e-ui", ["src/app/page.ts", "src/app/main.ts"])),
        "mismatched_sources, a script among them": make("mismatched_sources", sources_mismatched("e2e-ui", ["src/app/page.ts", "build.py"])),
        "confirm": make("confirm", unknown("e2e-ui", asks="confirm"), confirms_row),
        "method_failed": make("how", unknown("e2e-ui", tried=tried, registry_method_failed=out["command.failed"].format(
            why="python3: can't open file 'print_build.py'")), command_row),
        "method_failed, a plain label": make("how", unknown("e2e-ui", tried=tried, registry_method_failed=out["oci_label.no_label"].format(
            container="testproject1-ui-static", label=LABEL)), row),
        "voided": make("how", unknown("e2e-ui", tried=tried, voided=voided)),
        "voided confirm": make("confirm", unknown("e2e-ui", asks="confirm", voided=voided), confirms_row),
        "voided mismatched": make("mismatched", mismatched("e2e-ui", voided=voided), row),
    }


def k35_the_question_and_its_texts() -> None:
    rig = Rig(profiles=("e2e-ui",))
    try:
        use_plan({"TC-1": ("e2e-ui", "automate")})
        rig.records(**{"e2e-ui": unknown("e2e-ui", container="ui-c")})
        code, out, started, driver = run_entry(rig, s5=("TC-1",))
        eq("K35: `unknown` + asks_person how at the S5 entry: exit 3", code, 3)
        eq("K35: the question is kind stand_identity at S5", (asked(rig).get("kind"), asked(rig).get("stage")), ("stand_identity", "S5"))
        eq("K35: no role was started", started, [])
        shown = s0_question(rig.task_root)
        eq("K35: the question text obeys human-questions.md, answer block included", human_broken(shown.split("\n", 6)[-1].split("\n---\nAnswer:")[0]), [])
        for needle in ("localhost", "qa-factory/records/stand-identity.json", "`deployed`", "`always confirm`", "`retry`", "`label <name>`",
                       "no container is named for this profile", "e2e-ui tests", "repo-e2e-ui", HEAD[:12]):
            check_in(f"K35: the how text names {needle}", needle, shown)
        packet = flag(rig)
        eq("K35: the flag carries the packet, set by ask() alone (stand, profile, variant, commits, what was offered)",
           (packet.get("environment"), packet.get("profile"), packet.get("variant"), packet.get("revision"), packet.get("answers")),
           ("localhost", "e2e-ui", "how", HEAD, ["label", "file", "command", "deployed", "always confirm", "retry"]))
        check("K35: the factory's own words went to the details file, and the body names no script or flag",
              "tried - docker: no container" in (rig.task_root / "state" / "driver-question-details.md").read_text(encoding="utf-8")
              and ".py" not in shown.split("---\nAnswer:")[0] and "--" not in shown.split("---\nAnswer:")[0])
        argv = rig.calls()[0]["argv"]
        eq("K35 (R5/R1/R4 rule): the rehearsal run carries --no-evidence and the story's own --task-root",
           ("--no-evidence" in argv, Path(argv[argv.index("--task-root") + 1]).resolve() if "--task-root" in argv else None),
           (True, rig.task_root.resolve()))
        # every variant, with the prefixes stacked on it
        persons = realistic_persons(driver)
        for label, person in persons.items():
            eq(f"K35: the `{label}` text obeys human-questions.md", human_broken(person.text), [])
            eq(f"K35: `{label}` is a Person of kind stand_identity with its packet", (person.kind, bool(person.build_question["answers"])),
               ("stand_identity", True))
        for label in ("how", "how, registry unreadable", "method_failed", "voided"):
            for needle in ("`deployed`", "`always confirm`", "`retry`", "qa-factory/records/stand-identity.json", "`localhost`"):
                check_in(f"K35: the `{label}` text names {needle}", needle, persons[label].text)
        for needle in (OLD[:12], HEAD[:12], "`test deployed`", "`stop`", "`retry`"):
            check_in(f"K35: `mismatched` names {needle}", needle, persons["mismatched"].text)
        for needle in ("`src/app/page.ts`", HEAD[:12], "`stop`", "`retry`"):
            check_in(f"K35: `mismatched_sources` names {needle}", needle, persons["mismatched_sources"].text)
        check_not_in("K35: `mismatched_sources` offers no `test deployed` (the build there has no commit to name)", "test deployed",
                     persons["mismatched_sources"].text)
        check_in("K35: a path with a folder in it (`src/app/main.ts`) breaks no rule and is named", "`src/app/main.ts`", persons["mismatched_sources"].text)
        scripted = persons["mismatched_sources, a script among them"]
        check_not_in("K35: a bare file name that is a script name breaks the rules - it is not named in the body (FR-6)", "build.py", scripted.text)
        check_in("K35: ... the count is said instead", "2 of the files this story changes", scripted.text)
        check_in("K35: ... and the details file keeps the names", "build.py", scripted.details)
        check_not_in("K35: a command with a flag and a script name is not quoted in the body (FR-6)", "print_build.py", persons["mismatched by a command"].text)
        check_not_in("K35: ... nor in a failed way's sentence", "print_build.py", persons["method_failed"].text)
        check_not_in("K35: a docker message with a flag in it is not quoted in the body (FR-6)", "--format", persons["how, a docker message with a flag"].text)
        check_in("K35: ... its details are in the file", "--format", persons["how, a docker message with a flag"].details)
        check_in("K35: the failed way's text says what it was and when", "The way you gave on 2026-10-01", persons["method_failed, a plain label"].text)
        check_in("K35: the voided text says when and what moved", "You confirmed it on 2026-10-02; since then the checkout moved", persons["voided"].text)
        check_in("K35: a registry that cannot be read says so and that `deployed` and `retry` still work", "while `deployed` and `retry` still work",
                 persons["how, registry unreadable"].text)
        check("K35: the five variants are different texts (FR-7: the text moves when the situation moved)",
              len({persons[k].text for k in ("how", "mismatched", "mismatched_sources", "confirm", "method_failed", "voided")}) == 6)
        check_in("K35: more tried than shown says how many more", "and 2 more", persons["how, more tried"].text)
        check("K35: tried outcomes that name the image label are in the body whole when the rules of human-text.json allow it, in plain words when "
              "they do not (the rules move: t-363's `config_key`) - and either way the text obeys them",
              ("the details of what I tried are in the file named at the end" in persons["how"].text or LABEL in persons["how"].text)
              and human_broken(persons["how"].text) == [])
        check_in("K35: ... and the details file keeps them whole", LABEL, persons["how"].details)
        # the limit on the files named: AT 5 all named, BEYOND 6 one more is counted
        at = driver.build_person("S6", "both", "localhost", "e2e-ui", sources_mismatched("e2e-ui", [f"f{i}.ts" for i in range(5)]), None, "mismatched_sources")
        beyond = driver.build_person("S6", "both", "localhost", "e2e-ui", sources_mismatched("e2e-ui", [f"f{i}.ts" for i in range(6)]), None, "mismatched_sources")
        check("K35: AT 5 differing files all five are named, none counted more", all(f"`f{i}.ts`" in at.text for i in range(5)) and "more" not in at.text.split("differ")[0])
        check("K35: BEYOND (6) the sixth is not named and `and 1 more` is said", "`f5.ts`" not in beyond.text and "and 1 more" in beyond.text)
        # NEGATIVE CONTROL: the checker is not asleep
        check("K35 NEGATIVE CONTROL: a text with a script name, a flag and an exit code IS caught by the same checker",
              set(human_broken("I ran stand_identity.py confirm --task X and it said exit 2.")) >= {"script_name", "flag", "exit_code"})
        # the data: every answer a variant offers is in its text and has a form; every executor slot is one the driver fills
        import stand_identity as SI
        data = SI.data()
        forms = data["answers"]["forms"]
        for name, variant in data["question"]["variants"].items():
            body = "\n".join(variant["text"])
            check(f"K35 data: every answer of `{name}` is a form and is named in its text (`word` or `word <value>`)",
                  all(a in forms and (f"`{forms[a]['word']}`" in body or f"`{forms[a]['word']} <" in body) for a in variant["answers"]),
                  str(variant["answers"]))
        slots = driver.build_answer_slots({"environment": "localhost", "profile": "api", "revision": HEAD, "deployed": OLD, "image": DIGEST}, "w", "a")
        for name, spec in forms.items():
            for argv in spec.get("runs") or []:
                try:
                    driver.build_expand(argv, slots)
                    filled = True
                except KeyError:
                    filled = False
                check(f"K35 data: the executor of `{name}` uses only slots the driver fills", filled)
    finally:
        rig.done()


# --- the closed forms: the reader, at and beyond its limits -------------------------------------------------------

def forms_reader() -> None:
    import stand_identity as SI
    import story_run
    forms = SI.data()["answers"]["forms"]
    everything = list(forms)
    read = lambda words, offered=everything: story_run.Driver.build_read_answer(words, offered, forms)  # noqa: E731
    for words, form, arg in (("deployed", "deployed", ""), ("Deployed.", "deployed", ""), ("`deployed`", "deployed", ""), ("  DEPLOYED!  ", "deployed", ""),
                             ("test deployed", "test deployed", ""), ("Test   Deployed", "test deployed", ""), ("always confirm", "always confirm", ""),
                             ("retry", "retry", ""), ("stop", "stop", ""), ("\ufeffretry", "retry", ""),
                             ("label", "label", ""), ("label org.example.rev", "label", "org.example.rev"), ("label `org.example.rev`", "label", "org.example.rev"),
                             ("file /usr/share/x.txt", "file", "/usr/share/x.txt"), ("file", "file", ""), ("command", "command", ""),
                             ("command python3 sha.py --short", "command", "python3 sha.py --short"),
                             ('command "C:/Program Files/p.exe" -c "print(1)"', "command", '"C:/Program Files/p.exe" -c "print(1)"'),
                             ("deployed 0123456", "deployed", "0123456"), ("deployed " + "AB" * 20, "deployed", "ab" * 20)):
        got = read(words)
        eq(f"forms: `{words}` reads as {form} {arg!r}", (got.get("form"), got.get("arg", "")), (form, arg))
    for label, words in (("a form with prose after it", "deployed, I checked it yesterday"), ("`retry` with a word after it", "retry please"),
                         ("a commit one character short (6)", "deployed 012345"), ("a commit one character long (41)", "deployed " + "a" * 41),
                         ("a non-hex word where a commit would go", "deployed ghijklm"), ("prose", "the stand is fine, I looked at it"),
                         ("another script", OTHER_SCRIPT), ("two lines", "deployed\nretry"), ("a form hidden in a sentence", "yes, deployed"),
                         ("prose after `label` (t-366 F3, the critic's D4)", "label i do not know which one, use the default"),
                         ("a label of two words", "label org.example rev"), ("a `file` value that is no path", "file my notes"),
                         ("a `file` value that is a relative path", "file build-sha.txt"), ("a path with a space in it", "file /srv/my file.txt"),
                         ("empty", ""), ("only a BOM", "\ufeff"), ("only quotes", "``")):
        got = read(words)
        eq(f"forms: {label} is NOT read (it goes to the conductor)", (got.get("form"), bool(got.get("why"))), ("", True))
    named = read("test deployed", ["deployed", "retry"])
    eq("forms: a form this question did not offer is not read, and is named", (named["form"], named.get("named")), ("", "test deployed"))
    eq("forms: `test deployed` is never read as `deployed` plus words", read("test deployed")["form"], "test deployed")


# --- K36: the answers (the real ladder) -----------------------------------------------------------------------------

def k36_deployed_always_confirm_retry() -> None:
    # deployed: the confirm executor ran, the registry is untouched, the words are whole in the journal, the next entry starts the role
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        eq("K36 setup: the stand is asked about (exit 3)", (code, asked(rig).get("kind"), flag(rig).get("variant")), (3, "stand_identity", "how"))
        question_text = s0_question(rig.task_root).split("\n---\nAnswer:")[0]       # the answer block is where a command may stand (rule 5)
        check_in("K36 setup: the real ladder said why", "no container is named for this profile", question_text)
        words = "Deployed."        # the form, as a person types it: case and the closing full stop do not matter, the words are kept whole
        code, out, started, _ = run_entry(rig, words, s5=("TC-1",))
        eq("K36 deployed: the answer is taken and the next entry starts the role (exit 0)", (code, ("S5", "qa-automator") in started), (0, True))
        rows = rig.confirmations()
        eq("K36 deployed: ONE confirmation line, for this story, with this story's commit and the words whole",
           [(r["kind"], r["revision"], r["task"], r["words"], r["image"]) for r in rows], [("deployed", rig.head, rig.task, words, "absent")])
        eq("K36 deployed: the registry is untouched (still absent)", rig.registry().exists(), False)
        check("K36 deployed: the journal's human_answer holds the words WHOLE", any(words in n and "stand build at S5 (localhost, api tests)" in n for n in journal_answers(rig)),
              str(journal_answers(rig)))
        check_in("K36 deployed: the next entry says the build is the person's word, in a line", "confirmed by your word of", out)
        check("K36 (M10, FR-6): the person is shown no script name, flag or exit code - not in the question, not in what the driver printed",
              all(bad not in out and bad not in question_text for bad in ("stand_identity.py", "--revision", "--words", "--task", "exit ")), out[:400])
        eq("K36 deployed: the next entry asked nothing", (asked(rig), flag(rig)), ({}, {}))
    finally:
        rig.done()
    # a story started BEFORE N1b has no confirmations file: the registry alone answers (TE6, edge ix); the word is read first afterwards
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.put_row("person_confirms")
        check("K36 temporal: a story with no confirmations file yet", not (rig.task_root / "state" / "stand-confirmations.jsonl").exists())
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        eq("K36 temporal: the question works from the registry alone (the `confirm` variant)", (code, flag(rig).get("variant")), (3, "confirm"))
        code, out, started, _ = run_entry(rig, "deployed", s5=("TC-1",))
        eq("K36 temporal: after the file exists the word is read first: the next entry goes on (exit 0)", (code, len(rig.confirmations())), (0, 1))
    finally:
        rig.done()

    # always confirm: a person_confirms row, THEN a confirmation; with the record failing no confirmation, and the question returns
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        run_entry(rig, s5=("TC-1",))
        driver, started, steps, probes = rig.driver(s5=("TC-1",), answer=d2_answer(rig.root, "always confirm"))
        seq, real_py = [], driver.py

        def spy(script, *args, **kw):
            if script == "stand_identity.py":
                seq.append(args[0])
            return real_py(script, *args, **kw)
        driver.py = spy
        code = d2_enter(driver, "S5")
        eq("K36 always confirm: a person_confirms row, then the confirmation, in that order", seq, ["record", "confirm"])
        eq("K36 always confirm: the row is the person's, method person_confirms; the story is confirmed too",
           ([(r["method"], r["source"]) for r in rig.rows()], [r["kind"] for r in rig.confirmations()]), ([("person_confirms", "person")], ["deployed"]))
        eq("K36 always confirm: the stage goes on (exit 0)", code, 0)
    finally:
        rig.done()
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.registry().parent.mkdir(parents=True, exist_ok=True)
        rig.registry().write_text("{ this is not json", encoding="utf-8")
        before = rig.sha(rig.registry())
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        eq("K36 AE4: a registry nobody can read still asks (the defaults ran)", (code, flag(rig).get("variant")), (3, "how"))
        check_in("K36 AE4: the question says the file cannot be read and `deployed` and `retry` still work", "while `deployed` and `retry` still work", s0_question(rig.task_root))
        seq = []
        driver, started, steps, probes = rig.driver(s5=("TC-1",), answer=d2_answer(rig.root, "always confirm"))
        real_py = driver.py

        def spy2(script, *args, **kw):
            if script == "stand_identity.py":
                seq.append(args[0])
            return real_py(script, *args, **kw)
        driver.py = spy2
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = d2_enter(driver, "S5")
        eq("K36 always confirm, the record step FAILS: the confirmation never ran", seq, ["record"])
        eq("K36 ... no confirmation was written and the corrupt file was not touched", (rig.confirmations(), rig.sha(rig.registry())), ([], before))
        eq("K36 ... the question comes back (exit 3) saying nothing was recorded", (code, flag(rig).get("variant")), (3, "how"))
        check_in("K36 ... changed, and it names the failure", "I could not write down your last answer", s0_question(rig.task_root))
        check_in("K36 ... the factory's own words are in the details file", "stand-identity.json", (rig.task_root / "state" / "driver-question-details.md").read_text(encoding="utf-8"))
        check("K36 ... and the journal has the words, said as not recorded", any("not recorded" in n and "always confirm" in n for n in journal_answers(rig)))
        # `deployed` still works with that file (AE4: the confirmation never touches the registry)
        code, out, started, _ = run_entry(rig, "deployed", s5=("TC-1",))
        eq("K36 AE4: `deployed` goes through while the registry is unreadable", (code, [r["kind"] for r in rig.confirmations()], rig.sha(rig.registry())),
           (0, ["deployed"], before))
    finally:
        rig.done()

    # retry: nothing is written; the question comes back with the FR-7 notice
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        run_entry(rig, s5=("TC-1",))
        first = s0_question(rig.task_root)
        code, out, started, _ = run_entry(rig, "retry", s5=("TC-1",))
        eq("K36 retry: nothing is written (no registry, no confirmation)", (rig.registry().exists(), rig.confirmations()), (False, []))
        eq("K36 retry: the stand is checked at once and is still unknown: asked again (exit 3)", (code, flag(rig).get("variant")), (3, "how"))
        check_in("K36 retry: FR-7 - the same question comes back with the notice that it was answered before", "You have answered this exact question before", s0_question(rig.task_root))
        check_not_in("K36 retry CONTROL: the FIRST ask carried no such notice", "You have answered this exact question before", first)
    finally:
        rig.done()


def k36_method_answers() -> None:
    # label: a `record` row and an immediate re-probe; the way fails (no container) so the next text differs and names it (FR-7)
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        run_entry(rig, s5=("TC-1",))
        first = s0_question(rig.task_root)
        words = f"label {LABEL}"
        code, out, started, _ = run_entry(rig, words, s5=("TC-1",))
        rows = rig.rows()
        eq("K36 label: a registry row, the person's, with the label and the words whole",
           [(r["method"], r["source"], r["label"], r["words"]) for r in rows], [("oci_label", "person", LABEL, words)])
        eq("K36 label: the re-probe ran in the same move: the way failed, so the question comes back (exit 3), in the failed-way text", (code, flag(rig).get("variant")), (3, "how"))
        second = s0_question(rig.task_root)
        check_in("K36 label: the second text names the failed way and when (FR-7)", "The way you gave on", second)
        check_in("K36 label: ... and why, in the details file (the label name in the body would break the `config_key` rule)", "no container is named for this profile",
                 (rig.task_root / "state" / "driver-question-details.md").read_text(encoding="utf-8"))
        check("K36 label: the second text is NOT the first", second != first and "did not answer" in second and "did not answer" not in first)
        check_in("K36 label: ONE outcome line says it is recorded (data, t-366 F5)", "S5: the person's answer for stand `localhost` (api tests) is recorded; the build is checked again", out)
        check("K36 label: the script's own acknowledgement is NOT echoed (it names a state path) - one line, not two (t-366 F5)",
              "Recorded the decision" not in out and "stand-identity.json" not in out.split("# Driver question")[0]
              and out.count("is recorded") == 1, out[:600])
        # a second recording answer for the same stand and profile: the last one counts, the log says so, the record quotes the earlier line
        code, out, started, _ = run_entry(rig, "label example.org/revision", s5=("TC-1",))
        check_in("K36 last wins: the log says the stand was answered more than once and the last line counts", "answered more than once in this story; the last line counts", out)
        last = rig.rows()[-1]
        eq("K36 last wins: two rows, the last in force, with the label", (len(rig.rows()), last["label"]), (2, "example.org/revision"))
        check_in("K36 last wins: the record quotes the earlier line", "(replaces their earlier line: label org.opencontainers.image.revision)", last["words"])
        check_in("K36 last wins CONTROL: the FIRST recording answer carried no such note", "label org.opencontainers.image.revision", rig.rows()[0]["words"])
        check_not_in("K36 last wins CONTROL: ... and was not marked as replacing anything", "replaces", rig.rows()[0]["words"])
    finally:
        rig.done()

    # command (the Windows spelling of a path, quotes round a word) and file: recorded, the ladder reads them at once
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        run_entry(rig, s5=("TC-1",))
        argv = rig.command_script(rig.head)
        words = f'command "{Path(argv[0]).as_posix()}" "{Path(argv[1]).as_posix()}"'
        code, out, started, _ = run_entry(rig, words, s5=("TC-1",))
        eq("K36 command: a registry `command` row with the argv split the platform's way", [r.get("argv") for r in rig.rows()],
           [[Path(argv[0]).as_posix(), Path(argv[1]).as_posix()]])
        eq("K36 command: the next probe runs it, reads this story's commit, and the stage goes on (exit 0)", (code, ("S5", "qa-automator") in started), (0, True))
        check_in("K36 command: the entry says the build is this story's, in a line", "the stand runs this story's build", out)
        eq("K36 FR-45: the entry check is a rehearsal - it wrote no evidence file and no `probe discovered` row (only the person's row is there)",
           (sorted((rig.task_root / "evidence").glob("runtime-provenance-*")) if (rig.task_root / "evidence").is_dir() else [],
            [r["source"] for r in rig.rows()]), ([], ["person"]))
    finally:
        rig.done()
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        run_entry(rig, s5=("TC-1",))
        code, out, started, _ = run_entry(rig, "file /usr/share/nginx/html/build-sha.txt", s5=("TC-1",))
        eq("K36 file: a registry row with the path", [(r["method"], r["path"]) for r in rig.rows()], [("build_sha_file", "/usr/share/nginx/html/build-sha.txt")])
        # `file` with nothing after it: asked again, naming the form; no conductor
        rig2 = Rig(profiles=("api",), real=True)
        try:
            set_control(rig2.root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
            run_entry(rig2, s5=("TC-1",))
            code, out, started, _ = run_entry(rig2, "file", s5=("TC-1",))
            eq("K36 `file` with nothing after it: asked again (exit 3), no conductor, nothing written",
               (code, len(d2_conductor_calls(rig2.root)), rig2.rows(), rig2.confirmations()), (3, 0, [], []))
            check_in("K36 ... naming the form and what is needed", "You answered `file` with nothing after it. I need the path of the file inside the container", s0_question(rig2.task_root))
            check_in("K36 ... and how to write it", "file /path/inside/the/container", s0_question(rig2.task_root))
            eq("K36 ... the question is still the same one (the packet is kept)", flag(rig2).get("variant"), "how")
            run_entry(rig2, "command", s5=("TC-1",))
            check_in("K36 `command` with nothing after it: the same, naming the command form", "You answered `command` with nothing after it", s0_question(rig2.task_root))
        finally:
            rig2.done()
    finally:
        rig.done()


def k36_mismatched_answers() -> None:
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.put_row("command", argv=rig.command_script(rig.old))
        registry_before = rig.sha(rig.registry())
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        eq("K36 mismatched setup: the stand reads another commit of the checkout: a question, no role", (code, flag(rig).get("variant"), started), (3, "mismatched", []))
        text = s0_question(rig.task_root)
        check("K36 mismatched setup: the question names both commits", rig.old[:12] in text and rig.head[:12] in text)
        eq("K36 mismatched setup: the packet carries the commit the stand runs", (flag(rig)["deployed"], flag(rig)["revision"]), (rig.old, rig.head))
        # a plain `deployed` is no answer here (it never lifts a proven mismatch): the conductor reads it, nothing is recorded
        set_control(rig.root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        code, out, started, _ = run_entry(rig, "deployed", s5=("TC-1",))
        eq("K36 NEGATIVE CONTROL: `deployed` at the mismatched question is not read as a form: one conductor call, no confirmation", (len(d2_conductor_calls(rig.root)), rig.confirmations()), (1, []))
        # test deployed -> confirm --revision D --story-revision HEAD; the probe then says person_confirmed, the role starts
        code, out, started, _ = run_entry(rig, "test deployed", s5=("TC-1",))
        rows = rig.confirmations()
        eq("K36 test deployed: ONE line, kind test_deployed, revision = the deployed commit, story_revision = this story's",
           [(r["kind"], r["revision"], r["story_revision"]) for r in rows], [("test_deployed", rig.old, rig.head)])
        eq("K36 test deployed: the registry is unchanged by a mismatch answer, and the stage goes on (exit 0)", (rig.sha(rig.registry()), code), (registry_before, 0))
        check_in("K36 test deployed: the next entry says it is the person's word", "confirmed by your word of", out)
    finally:
        rig.done()
    # stop: the words are journaled, the question stays open with the held text, exit 3, nothing passed
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.put_row("command", argv=rig.command_script(rig.old))
        run_entry(rig, s5=("TC-1",))
        code, out, started, _ = run_entry(rig, "stop", s5=("TC-1",))
        eq("K36 stop: exit 3, no role, nothing recorded for the stand", (code, started, rig.confirmations()), (3, [], []))
        held = s0_question(rig.task_root)
        check_in("K36 stop: the held text says it stopped and nothing was passed", "You said to stop the story here. Nothing runs on `localhost` and nothing is passed", held)
        check_in("K36 stop: the question is still there with its answers", "`test deployed`", held)
        eq("K36 stop: the question stays open (kind stand_identity, flag set)", (asked(rig).get("kind"), bool(flag(rig))), ("stand_identity", True))
        check("K36 stop: the words are in the journal, with the owner", any("stop; owner: environment" in n and n.endswith(": stop") for n in journal_answers(rig)), str(journal_answers(rig)))
        eq("K36 stop: the held text is not an echo of the first ask (it moved)", "You said to stop" in held, True)
        code, out, started, _ = run_entry(rig, "retry", s5=("TC-1",))
        eq("K36 stop, then `retry`: the held question is answered like any other (the stand is read again: mismatched, asked again)", (code, flag(rig).get("variant")), (3, "mismatched"))
    finally:
        rig.done()


def k36_other_words_and_edges() -> None:
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        set_control(rig.root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        run_entry(rig, s5=("TC-1",))
        before = rig.sha(rig.registry())
        # M9: other words, in any language, are NOT read as a form - exactly one conductor call carrying the exact command lines
        for said in ("the stand is fine, I looked at it yesterday", OTHER_SCRIPT, "deployed, I checked"):
            calls_before = len(d2_conductor_calls(rig.root))
            code, out, started, _ = run_entry(rig, said, s5=("TC-1",))
            eq(f"K36 other words `{said[:30]}`: exactly one conductor call, nothing recorded", (len(d2_conductor_calls(rig.root)) - calls_before, rig.confirmations(), rig.rows()), (1, [], []))
        prompt = d2_conductor_calls(rig.root)[0]["prompt"]
        for needle in ("`localhost`", "`api`", rig.task, "qa-factory/records/stand-identity.json", "stand_identity.py", " confirm ", "--revision " + rig.head,
                       " record ", "--method person_confirms", "--method oci_label", "--method build_sha_file", "--method command", "<their words, verbatim>", "## The question"):
            check_in(f"K36 conductor: the note carries {needle}", needle, prompt)
        check_not_in("K36 conductor: ... and offers no form the question did not (`test deployed` is for a mismatch)", "--story-revision",
                     prompt.split("## Files the refusal names")[0])
        eq("K36 other words: the question is not changed by it: still asked (the loop re-entered the stage)", (asked(rig).get("kind"), flag(rig).get("variant")), ("stand_identity", "how"))
        # an answer for a stand the config no longer has: the conductor, never a crash, no executor ran
        cfg = json.loads(rig.config_path.read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "elsewhere", "base_url": "http://elsewhere"}]
        rig.config_path.write_text(json.dumps(cfg), encoding="utf-8")
        calls_before = len(d2_conductor_calls(rig.root))
        code, out, started, _ = run_entry(rig, "deployed", s5=("TC-1",))
        eq("K36 a stand the config no longer has: the conductor reads the answer, nothing was recorded", (len(d2_conductor_calls(rig.root)) - calls_before, rig.confirmations(), rig.sha(rig.registry())), (1, [], before))
        check_in("K36 ... and the note says what is missing", "is not in this project's config", d2_conductor_calls(rig.root)[-1]["prompt"])
        # an empty answer file and a BOM-only one: never a crash
        empty = rig.root / "answer.md"
        empty.write_bytes(b"")
        driver, started, steps, probes = rig.driver(s5=("TC-1",), answer=str(empty))
        eq("K36 an empty answer file: a stop with a message (exit 1), the question stays open", (driver.run(), bool(asked(rig))), (1, True))
        calls_before = len(d2_conductor_calls(rig.root))
        code, out, started, _ = run_entry(rig, "\ufeff", s5=("TC-1",))
        eq("K36 a BOM-only answer: the conductor, no crash, nothing recorded", (len(d2_conductor_calls(rig.root)) - calls_before, rig.confirmations()), (1, []))
    finally:
        rig.done()

    # (vi) a commit the answer names that is not the story's: asked again ONCE with the reason, then the conductor
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        set_control(rig.root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        run_entry(rig, s5=("TC-1",))
        code, out, started, _ = run_entry(rig, f"deployed {NOWHERE}", s5=("TC-1",))
        eq("K36 a commit that is no commit of the checkout: asked again once (exit 3), nothing recorded, no conductor", (code, rig.confirmations(), len(d2_conductor_calls(rig.root))), (3, [], 0))
        check_in("K36 ... with the reason", "is not a commit of this story's checkout, so I recorded nothing", s0_question(rig.task_root))
        eq("K36 ... the packet remembers it was asked once", flag(rig).get("reasked"), True)
        code, out, started, _ = run_entry(rig, f"deployed {NOWHERE}", s5=("TC-1",))
        eq("K36 ... the SECOND bad commit goes to the conductor", (len(d2_conductor_calls(rig.root)), rig.confirmations()), (1, []))
        # a commit of the checkout that is not THIS story's: the same re-ask, with its own reason
        run_entry(rig, s5=("TC-1",))
        code, out, started, _ = run_entry(rig, f"deployed {rig.old[:10]}", s5=("TC-1",))
        check_in("K36 a commit of the checkout but not this story's: the reason names this story's commit", f"but this story is commit {rig.head[:12]}", s0_question(rig.task_root))
        eq("K36 ... nothing recorded", rig.confirmations(), [])
        # CONTROLS: this story's own commit, abbreviated or whole, IS `deployed`
        for how in ("abbreviated", "whole", "upper case"):
            rig3 = Rig(profiles=("api",), real=True)
            try:
                spelling = {"abbreviated": rig3.head[:10], "whole": rig3.head, "upper case": rig3.head.upper()[:12]}[how]
                use_plan({"TC-1": ("api", "automate")})
                run_entry(rig3, s5=("TC-1",))
                code, out, started, _ = run_entry(rig3, f"deployed {spelling}", s5=("TC-1",))
                eq(f"K36 CONTROL: `deployed {spelling[:12]}` (this story's commit) is recorded and the stage goes on", (code, [r["kind"] for r in rig3.confirmations()]), (0, ["deployed"]))
            finally:
                rig3.done()
    finally:
        rig.done()


# --- t-366: the fix pass after critic t-361 ----------------------------------------------------------------------------

def t366_f2_f3_f5_partly_recorded_prose_label_and_console() -> None:
    # F2 (the critic's D3): `always confirm` where `record` is written and `confirm` fails
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        run_entry(rig, s5=("TC-1",))
        blocker = rig.task_root / "state" / "stand-confirmations.jsonl"
        blocker.mkdir(parents=True)               # the confirmation cannot be appended to a folder: the second step fails
        code, out, started, _ = run_entry(rig, "always confirm", s5=("TC-1",))
        eq("F2: the decision IS written (a person_confirms row) and the word for this story is not", (code, [(r["method"], r["source"]) for r in rig.rows()], rig.confirmations()),
           (3, [("person_confirms", "person")], []))
        eq("F2: the question is the partly-recorded one, offering deployed / retry / stop", (flag(rig).get("variant"), flag(rig).get("answers")),
           ("partly_recorded", ["deployed", "retry", "stop"]))
        text = s0_question(rig.task_root).split("\n---\nAnswer:")[0]
        check_in("F2: it says what is written", "is written: you check the build on that stand yourself", text)
        check_in("F2: ... and what is not", "What is not written is your word that this story's build is there now", text)
        check_not_in("F2 (FR-10): it does NOT say nothing was recorded", "nothing was recorded", text)
        check("F2: no state path, no exception name in it", not any(bad in text for bad in (".jsonl", "Error", "Traceback", "stand_identity.py")), text)
        eq("F2: the text obeys human-questions.md", human_broken(text.split("\n", 6)[-1]), [])
        check_in("F2: the factory's own words are in the details file", "stand-confirmations.jsonl", (rig.task_root / "state" / "driver-question-details.md").read_text(encoding="utf-8"))
        check("F2 (FR-10): the console prints ONE outcome line - not `recorded` and then `not recorded`",
              "your decision for stand `localhost` (api tests) is written but your word for this story is not" in out
              and "is recorded" not in out and "was not recorded" not in out and "Recorded the decision" not in out, out[:700])
        check("F2: the journal says it was partly recorded, with the words", any("partly recorded" in n and n.endswith(": always confirm") for n in journal_answers(rig)))
        blocker.rmdir()
        code, out, started, _ = run_entry(rig, "deployed", s5=("TC-1",))
        eq("F2: `deployed` then completes it: the word is written and the stage goes on (exit 0)", (code, [r["kind"] for r in rig.confirmations()], len(rig.rows())), (0, ["deployed"], 1))
    finally:
        rig.done()
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        run_entry(rig, s5=("TC-1",))
        (rig.task_root / "state" / "stand-confirmations.jsonl").mkdir(parents=True)
        run_entry(rig, "always confirm", s5=("TC-1",))
        code, out, started, _ = run_entry(rig, "stop", s5=("TC-1",))
        eq("F2: `stop` after a partly-recorded answer is held like any stop (exit 3, nothing passed)", (code, started, rig.confirmations()), (3, [], []))
        check_in("F2: ... with the held text", "You said to stop the story here", s0_question(rig.task_root))
    finally:
        rig.done()
    # F2 CONTROL: `record` itself failing is still the plain not-recorded question (nothing IS written)
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        run_entry(rig, s5=("TC-1",))
        rig.registry().parent.mkdir(parents=True, exist_ok=True)
        rig.registry().write_text("{ not json", encoding="utf-8")
        run_entry(rig, "always confirm", s5=("TC-1",))
        check_in("F2 CONTROL: when the FIRST step fails, nothing is written and the text says so", "so nothing was recorded for this stand", s0_question(rig.task_root))
        eq("F2 CONTROL: ... and it is the how question, not the partly one", flag(rig).get("variant"), "how")
    finally:
        rig.done()
    # F3 (the critic's D4): prose after `label` or `file` is NOT a value - the conductor reads it, no registry row
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        set_control(rig.root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        run_entry(rig, s5=("TC-1",))
        for said in ("label i do not know which one, use the default", "file my notes about the build", "label a b"):
            before = len(d2_conductor_calls(rig.root))
            run_entry(rig, said, s5=("TC-1",))
            eq(f"F3: `{said[:30]}...` goes whole to the conductor, and no registry row was written", (len(d2_conductor_calls(rig.root)) - before, rig.rows()), (1, []))
        check_in("F3: the conductor was given the person's words", "use the default", d2_conductor_calls(rig.root)[0]["prompt"])
        # CONTROL: the same forms with a value of the right shape ARE recorded
        run_entry(rig, "label example.org/revision", s5=("TC-1",))
        eq("F3 CONTROL: a one-word label is recorded as a row", [(r["method"], r["label"]) for r in rig.rows()], [("oci_label", "example.org/revision")])
    finally:
        rig.done()


def t366_o1_a_person_label_does_not_outrank_the_sources() -> None:
    """The critic's P3: a stale label a person recorded, equal to HEAD, on a container whose files differ. AE2 holds for every
    row: the label row joins the ladder AT the label rung, AFTER the sources. The ladder is `runtime_probe.main` driven the way
    test_runtime_probe_onboarding does (its fake docker): the container is the one thing a real run cannot be given here."""
    import test_runtime_probe_onboarding as ONB
    w = ONB.World(git=True)
    try:
        c1, c2 = w.commits
        w.row("oci_label", label=ONB.LABEL)
        stand = ONB.Stand(app=True, labels={ONB.LABEL: c2}, sha=lambda container, path: "f" * 64)
        code, rec, _said = w.probe(stand, "--no-evidence", expected=c2)
        eq("O1/P3: a stale person label == HEAD, the container's content differs: MISMATCHED by content, never matched",
           (rec["result"], rec.get("provenance", {}).get("deployed_source_revision"), rec.get("differing_files")),
           ("mismatched", "content_mismatch", ["src/Page.vue"]))
        # FB-8 N2 (68539227): a content mismatch reads the container's image digest once (`docker inspect`, `observed_image`: what a
        # `test as is` word binds to), so `inspect` is expected; the label rung is `image inspect` and it must still not run
        eq("O1/P3: the label was never consulted (the `/app` check, the compare and the one digest read ran; no `image inspect`)",
           ONB.calls_of(stand), ["test -d", "inspect"])
        eq("O1/P3: the person's row was not rewritten or replaced", [(r["method"], r["source"]) for r in w.rows()], [("oci_label", "person")])
        # CONTROL: the sources cannot be compared (no /app in the container): the person's label decides, as before
        stand = ONB.Stand(app=False, labels={ONB.LABEL: c2})
        code, rec, _said = w.probe(stand, "--no-evidence", expected=c2)
        eq("O1 CONTROL: no /app in the container: the person's label answers - matched by the label",
           (rec["result"], rec["provenance"].get("identity_kind"), ONB.calls_of(stand)), ("matched", "oci_label", ["test -d", "inspect", "image inspect"]))
        # CONTROL: the sources match: matched by content, the label is still not needed
        same = ONB.R.sha_local(w.ui / "src" / "Page.vue")
        stand = ONB.Stand(app=True, labels={ONB.LABEL: c1}, sha=lambda container, path: same)
        code, rec, _said = w.probe(stand, "--no-evidence", expected=c2)
        eq("O1 CONTROL: the files match: matched by content even though the person's label says another commit", (rec["result"], ONB.calls_of(stand)), ("matched", ["test -d"]))
    finally:
        w.close()
    # the texts say it (the decided sentence)
    import stand_identity as SI
    for variant in ("how", "confirm"):
        body = " ".join("\n".join(SI.data()["question"]["variants"][variant]["text"]).split())
        check_in(f"O1: the `{variant}` text says a label tells which image the stand runs and the files are compared whatever it says",
                 "a label tells which image the stand runs, and when the files of this story can be compared with the files inside the container they are, whatever the label says", body)


# --- K37: positions, and the flag ----------------------------------------------------------------------------------

def k37_positions_and_the_flag() -> None:
    import story_run
    rig = Rig(profiles=("api",))
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.records(api=unknown("api"))
        # a stage with nothing to run never asks: S5 with no window refuses first, S6 with nothing to run closes
        driver, started, steps, probes = rig.driver(s5=())
        try:
            driver.stage_S5()
            check("K37 S5 with nothing to run refuses before any probe", False)
        except story_run.Refusal:
            check("K37 S5 with nothing to run refuses before any probe", True)
        except story_run.Person:
            check("K37 S5 with nothing to run refuses before any probe", False)
        driver, started, steps, probes = rig.driver(auto=(), manual=())
        driver.code_only = lambda stage, reason, evidence: None
        real_py = driver.py
        driver.py = lambda script, *a, **k: (0, "") if script in ("stage_done.py", "finalize_task.py") else real_py(script, *a, **k)
        try:
            driver.stage_S6()
            check("K37 S6 with nothing to execute closes without a question", True)
        except story_run.Person:
            check("K37 S6 with nothing to execute closes without a question", False)
        eq("K37 ... and no probe was run for either", rig.calls(), [])
        # a dispatch already begun and resumed with the person's words is not gated
        driver, started, steps, probes = rig.driver()
        driver.controller_state = lambda: {"dispatches": {"S5-qa-automator-1": {"stage": "S5", "role": "qa-automator", "scope": ["TC-1"]}}}
        resumed = []
        driver.resume_role = lambda stage, role, dispatch, words, **kw: resumed.append(dispatch)
        driver.state["pending_words"]["S5-qa-automator-1"] = "the person's words"
        driver.dispatch_action({"action": "resume_checkpoint", "dispatch_id": "S5-qa-automator-1"})
        driver.dispatch_action({"action": "wait_existing_job", "dispatch_id": "S5-qa-automator-1"})
        eq("K37 resume_checkpoint and wait_existing_job (begun) resume the role: no build check, no probe", (len(resumed), rig.calls()), (2, []))
        # the flag is not taken by another question's answer (mirror of D2 R1), and ask() clears it for every other Person
        set_control(rig.root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        for label, kind, packet in (("kind conductor with a stale flag", "conductor", {"environment": "localhost", "profile": "api", "answers": ["deployed"], "revision": HEAD}),
                                    ("kind stand_identity with NO flag", "stand_identity", None)):
            before = len(d2_conductor_calls(rig.root))
            driver = rig.driver()[0]
            driver.state["asked"] = {"kind": kind, "stage": "S5", "dispatch": ""}
            driver.state.pop("build_question", None)
            if packet:
                driver.state["build_question"] = packet
            driver.save_state()
            (rig.task_root / "state" / "driver-question.md").write_text(f"# q\nkind: {kind}\n", encoding="utf-8")
            driver.take_answer(Path(d2_answer(rig.root, "deployed")))
            eq(f"K37 answer: {label} keeps its own branch - the conductor is called once, as before", len(d2_conductor_calls(rig.root)) - before, 1)
            eq(f"K37 answer: {label} - no confirmation was recorded", rig.confirmations(), [])
        driver = rig.driver()[0]
        driver.state["build_question"] = {"environment": "localhost"}
        driver.ask(story_run.Person("conductor", "A question that is not the build's, with enough words in it to be a question for the person."))
        check("K37 ask(): a Person that carries no packet clears the flag (it never outlives its question)", "build_question" not in driver.state)
    finally:
        rig.done()
    # an unconfirmed stand asks the STAND question first, never the build question; a stand passed by word returns at once
    rig = Rig(profiles=("api",))
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.records(api=unknown("api"))
        d2_pipeline(rig.task_root, environment="localhost", environment_pending=True)
        code, out, started, driver = run_entry(rig, s5=("TC-1",))
        eq("K37 an unconfirmed stand asks the stand question first (kind environment); no build probe ran", (code, asked(rig).get("kind"), rig.calls()), (3, "environment", []))
        d2_pipeline(rig.task_root, environment=None, environment_pending=True,
                    stage_overrides=[{"stage": "S5", "match": "stand not confirmed", "decision": "go on", "at": "2026-10-03T10:00:00+00:00", "by": "human"}])
        code, out, started, driver = run_entry(rig, s5=("TC-1",))
        eq("K37 a stand passed by the person's word: build_check returns at once (no probe, no question), the role starts", (code, rig.calls(), ("S5", "qa-automator") in started), (0, [], True))
        # M8's neighbour: the same unconfirmed pair but matched, with the stand confirmed: no question either
        d2_pipeline(rig.task_root, environment="localhost", environment_pending=False, stage_overrides=[])
        rig.records(api=matched("api"))
        code, out, started, driver = run_entry(rig, s5=("TC-1",))
        eq("K37 (M8) a MATCHED record asks nothing (exit 0, no question open)", (code, asked(rig)), (0, {}))
        rig.records(api=unknown("api"))
        code, out, started, driver = run_entry(rig, s5=("TC-1",))
        eq("K37 (M8 CONTROL) the same stand with an `unknown` record DOES ask", (code, asked(rig).get("kind")), (3, "stand_identity"))
    finally:
        rig.done()
    # the dispatch sites: a relaunch and a never-launched dispatch ask before the role starts
    rig = Rig(profiles=("api", "e2e-ui"))
    try:
        use_plan({"TC-1": ("api", "automate"), "TC-2": ("e2e-ui", "manual-agent")})
        rig.records(api=unknown("api"), **{"e2e-ui": unknown("e2e-ui")})
        for stage, role, kind, scope, profile in (("S5", "qa-automator", "", ["TC-1"], "api"), ("S6", "qa-runner", "automation", ["TC-1"], "api"),
                                                  ("S6", "qa-runner", "manual", ["TC-2"], "e2e-ui")):
            driver, started, steps, probes = rig.driver()
            relaunch = {"action": "relaunch", "stage": stage, "role": role, "dispatch_request": {"scope": scope, "execution_kind": kind}}
            try:
                driver.dispatch_action(relaunch)
                check(f"K37 a relaunch on {stage} ({kind or 'no kind'}) asks first", False)
            except story_run.Person as person:
                eq(f"K37 a relaunch on {stage} ({kind or 'no kind'}) asks about the build of {profile} (kind stand_identity)", (person.kind, person.build_question["profile"]), ("stand_identity", profile))
            eq("K37 ... and no role started", started, [])
            driver, started, steps, probes = rig.driver()
            driver.controller_state = lambda stage=stage, role=role, scope=scope, kind=kind: {
                "dispatches": {f"{stage}-{role}-3": {"stage": stage, "role": role, "scope": scope, "execution_kind": kind}}}
            try:
                driver.dispatch_action({"action": "wait_existing_job", "dispatch_id": f"{stage}-{role}-3"})
                check(f"K37 a never-launched {stage} dispatch asks first", False)
            except story_run.Person as person:
                eq(f"K37 a never-launched {stage} dispatch asks about {profile}", (person.kind, person.build_question["profile"]), ("stand_identity", profile))
            eq("K37 ... and no role started", started, [])
        # a dispatch with no scope names no profile: nothing is probed, nothing is asked ("never all")
        before = len(rig.calls())
        driver, started, steps, probes = rig.driver()
        driver.dispatch_action({"action": "relaunch", "stage": "S6", "role": "qa-runner", "dispatch_request": {"scope": [], "execution_kind": ""}})
        eq("K37 a dispatch with an EMPTY scope probes nothing and asks nothing: the role starts", (len(rig.calls()) - before, started), (0, [("S6", "qa-runner")]))
    finally:
        rig.done()
    # the source-order check (build_check follows stand_check at every site) and the F5 console-line check over the region of
    # `build_check` were source pins of named members: deleted by TD-11 phase 0 (F3)


# --- K38 / K39 / K40 / K44 -------------------------------------------------------------------------------------------

def k38_the_confirm_variant() -> None:
    rig = Rig(profiles=("api",), real=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.put_row("person_confirms")
        date = rig.rows()[0]["recorded_at"][:10]
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        eq("K38 a person_confirms stand with no word for this story: the `confirm` question (exit 3)", (code, flag(rig).get("variant")), (3, "confirm"))
        text = s0_question(rig.task_root)
        check_in("K38 it names the decision date", f"your decision of {date}", text)
        check_in("K38 it names the registry file", "qa-factory/records/stand-identity.json", text)
        check_in("K38 it says nothing was read (the person checks it)", "you check the build yourself", text)
        check_not_in("K38 CONTROL: the `how` question does not say it", "you check the build yourself", persons_how(rig))
        code, out, started, _ = run_entry(rig, "deployed", s5=("TC-1",))
        eq("K38 `deployed` takes the word for this story and the stage goes on", (code, [r["kind"] for r in rig.confirmations()]), (0, ["deployed"]))
        # the stand's definition moved since the decision: the decision no longer counts - `voided`, asked as a how-question
        cfg = json.loads(rig.config_path.read_text(encoding="utf-8"))
        cfg["environments"][0]["base_url"] = "http://localhost:9999"
        rig.config_path.write_text(json.dumps(cfg), encoding="utf-8")
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        eq("K38 a stand whose address changed since the decision: asked again (exit 3)", code, 3)
        check_in("K38 ... with the voided text", f"You confirmed it on {date}; since then the stand's settings changed", s0_question(rig.task_root))
    finally:
        rig.done()


def persons_how(rig) -> str:
    driver = rig.driver()[0]
    return driver.build_person("S5", "", "localhost", "api", unknown("api"), None, "how").text


def k39_what_is_a_line_and_not_a_question() -> None:
    rig = Rig(profiles=("api",), timeout=2)
    try:
        use_plan({"TC-1": ("api", "automate")})
        # mismatched IS a question (the amendment); the others are one printed line each and the role starts
        rig.records(api=mismatched("api"))
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        eq("K39 `mismatched` at entry is a question (variant mismatched), no role", (code, flag(rig).get("variant"), started), (3, "mismatched", []))
        rig.records(api=sources_mismatched("api", ["a.ts"]))
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        eq("K39 a sources mismatch is a question too (variant mismatched_sources)", (code, flag(rig).get("variant")), (3, "mismatched_sources"))
        for label, record_, needle in (
                ("docker down (unknown, nobody to ask)", unknown("api", asks=None, error="which build the stand runs could not be read: docker did not answer (Cannot connect)"), "I could not read which build stand `localhost` runs"),
                ("the probe exits with an error", "__fail__", "the check stopped with an error"),
                ("the probe prints no JSON", "__nojson__", "the check printed no readable answer"),
                ("the probe does not finish in time", "__hang__", "the check did not finish in time"),
                ("a result word the factory does not know", dict(matched("api"), result="MATCHED"), "was not one I know"),
                ("a matched record that proves nothing (no technical verification)", dict(matched("api"), provenance={"technical_verification": False}), "was not one I know")):
            rig.records(api=record_)
            asked(rig)
            code, out, started, _ = run_entry(rig, s5=("TC-1",))
            lines = [ln for ln in out.splitlines() if "stand `localhost`" in ln and ln.startswith("S5:")]
            eq(f"K39 {label}: no question (exit 0), the role starts", (code, ("S5", "qa-automator") in started), (0, True))
            check_in(f"K39 {label}: ONE printed line says so", needle, "\n".join(lines))
            eq(f"K39 {label}: exactly one such line", len(lines), 1)
            eq(f"K39 {label}: the line obeys human-questions.md", line_broken(lines[0]) if lines else ["no line"], [])
            check(f"K39 {label}: and it is not a question (nothing open, no packet)", not asked(rig) and not flag(rig), str(asked(rig)))
        # a check that breaks inside the driver is a line and the run goes on (P1: code informs, it does not stop the factory)
        rig.records(api=matched("api"))
        built = rig.driver(s5=("TC-1",))

        def broken(*_args, **_kw):
            raise KeyError("slot")
        built[0].build_outcome = broken
        code, out, started, _ = run_entry(rig, built=built)
        eq("K39 a check that BREAKS is a line, not a crash: the role starts (exit 0)", (code, ("S5", "qa-automator") in started), (0, True))
        check_in("K39 ... and the line (data) says it could not be checked and that nothing is asked, with no exception name in it",
                 "the build of stand `localhost` for the api tests could not be checked; nothing is asked of you", out)
        check_not_in("K39 (t-366 F5) ... the exception's name is not on the console", "KeyError", out)
        errors = io.StringIO()
        built = rig.driver(s5=("TC-1",))
        built[0].build_outcome = broken
        with contextlib.redirect_stderr(errors):
            run_entry(rig, built=built)
        check_in("K39 (t-366 F5) ... the raw error text goes to stderr", "KeyError", errors.getvalue())
        # no registered probe (E21): a line, no question
        cfg = json.loads(rig.config_path.read_text(encoding="utf-8"))
        cfg["execution"]["runtime_probes"] = {}
        rig.config_path.write_text(json.dumps(cfg), encoding="utf-8")
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        check_in("K39 no probe registered: one line, no question, the role starts", "no way to read the build of stand `localhost` is registered for the api tests", out)
        eq("K39 ... exit 0", (code, ("S5", "qa-automator") in started), (0, True))
    finally:
        rig.done()
    # docker down on a stand the person checks themselves: a STATUS line naming the word, never a question (FR-7)
    rig = Rig(profiles=("api",))
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.put_row("person_confirms")
        date = rig.rows()[0]["recorded_at"][:10]
        rig.records(api=unknown("api", asks=None, error="which build the stand runs could not be read: docker did not answer"))
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        eq("K39 docker down on a person_confirms stand: no question, the role starts", (code, ("S5", "qa-automator") in started, asked(rig)), (0, True, {}))
        check_in("K39 ... the status line says docker is down and whose word cannot be checked", f"docker is down on `localhost`; your word of {date} (you check the build yourself on this stand) cannot be checked now", out)
        eq("K39 ... and the line obeys the rules", line_broken([ln for ln in out.splitlines() if "docker is down" in ln][0]), [])
        # CONTROL: the same record on a stand with no such row is the plain unread line
        rig2 = Rig(profiles=("api",))
        try:
            use_plan({"TC-1": ("api", "automate")})
            rig2.records(api=unknown("api", asks=None, error="which build the stand runs could not be read: docker did not answer"))
            code, out2, started2, _ = run_entry(rig2, s5=("TC-1",))
            check_not_in("K39 CONTROL: with no person_confirms row the line does not speak of a word", "your word of", out2)
        finally:
            rig2.done()
    finally:
        rig.done()


def k40_one_question_per_profile() -> None:
    rig = Rig(profiles=("api", "e2e-ui"))
    try:
        use_plan({"TC-1": ("api", "automate"), "TC-2": ("e2e-ui", "manual-agent")})
        rig.records(api=unknown("api"), **{"e2e-ui": unknown("e2e-ui")})
        code, out, started, driver = run_entry(rig, stage="S6", auto=("TC-1",), manual=("TC-2",))
        eq("K40 S6 `both` with api and e2e-ui both unknown: ONE question (exit 3), no role", (code, started), (3, []))
        first = s0_question(rig.task_root)
        eq("K40 the first question names api only", (flag(rig).get("profile"), "api tests" in first, "e2e-ui" in first), ("api", True, False))
        check_in("K40 ... and says S6 will run both halves", "running the automated tests and carrying out the manual checks", first)
        eq("K40 ... only api was probed so far", sorted({c["profile"] for c in rig.calls()}), ["api"])
        # after its answer (api is read now), the next entry asks e2e-ui
        rig.records(api=matched("api"), **{"e2e-ui": unknown("e2e-ui")})
        code, out, started, driver = run_entry(rig, "retry", stage="S6", auto=("TC-1",), manual=("TC-2",))
        eq("K40 after the answer the next entry asks e2e-ui (exit 3)", (code, flag(rig).get("profile")), (3, "e2e-ui"))
        check_in("K40 ... the api line was printed first", "the api tests on stand `localhost`: the stand runs this story's build", out)
        check_not_in("K40 ... and the second question is not about api", "api tests", s0_question(rig.task_root).split("What I need")[0])
        # CONTROL: one unknown among matched asks exactly one question, and a matched pair asks none (K44)
        rig.records(api=matched("api"), **{"e2e-ui": matched("e2e-ui")})
        code, out, started, driver = run_entry(rig, stage="S6", auto=("TC-1",), manual=("TC-2",))
        eq("K40 CONTROL: both matched - no question", (code, asked(rig)), (0, {}))
    finally:
        rig.done()


def driver_stub(driver) -> None:
    """S6 reads the stand's freshness through the registered probe too (R4); this file is about the build question, so the
    freshness read is replaced for the entry that follows."""
    driver.s6_freshness = lambda cases: {"decided": False, "why": "stub", "stand": [], "run": {}, "passed": 0, "failed": 0}


def k44_a_labelled_stand_asks_nothing() -> None:
    rig = Rig(profiles=("api", "e2e-ui"))
    try:
        use_plan({"TC-1": ("api", "automate"), "TC-2": ("e2e-ui", "manual-agent")})
        rig.records(api=matched("api", kind="", linkage="verified_content"), **{"e2e-ui": matched("e2e-ui", kind="oci_label")})
        driver, started, steps, probes = rig.driver(auto=("TC-1",), manual=("TC-2",))
        driver_stub(driver)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = d2_enter(driver, "S6")
        lines = [ln for ln in out.getvalue().splitlines() if "stand `localhost`" in ln and ln.startswith("S6:")]
        eq("K44 e2e-ui labelled == HEAD, api matched by content: S6 entry asks nothing (exit 0)", (code, asked(rig), flag(rig)), (0, {}, {}))
        eq("K44 ... and prints exactly two lines, api then e2e-ui", len(lines), 2)
        check("K44 ... the api line says it was matched by the files; the e2e-ui line names the label, or says `the way it was read` when the rules of "
              "human-text.json (they move: t-363's `config_key`) would break on the label's dotted name",
              "the files inside the container" in lines[0] and ("(read by the label org.opencontainers.image.revision of the image)" in lines[1]
                                                                   or "(read by the way it was read)" in lines[1]), "\n".join(lines))
        check("K44 ... both obey the rules", all(line_broken(ln) == [] for ln in lines))
        eq("K44 ... the roles started (the run goes on)", ("S6", "manual") in started or ("S6", "qa-runner") in started, True)
        eq("K44 ... one probe per profile, no more", sorted(c["profile"] for c in rig.calls()), ["api", "e2e-ui"])
    finally:
        rig.done()


# --- the edges of the node spec -----------------------------------------------------------------------------------------

def edges_per_window_and_per_kind() -> None:
    import story_run
    rig = Rig(profiles=("api", "e2e-ui"))
    try:
        use_plan({"TC-1": ("api", "automate"), "TC-2": ("e2e-ui", "automate")})
        rig.records(api=matched("api"), **{"e2e-ui": unknown("e2e-ui")})
        windows = [{"scope": ["TC-1"], "accepted_by": {}}, {"scope": ["TC-2"], "accepted_by": {}}]
        built = rig.driver()
        built[0].stage_scope = lambda stage, kind="": {"scope": ["TC-1", "TC-2"], "windows": windows}
        code, out, started, _ = run_entry(rig, built=built)
        eq("EDGE per window: an api window is entered while e2e-ui is unknown: no question (an e2e-ui question never blocks an api-only window)", (code, asked(rig)), (0, {}))
        eq("EDGE per window: ... and only the window's own profile was probed", sorted({c["profile"] for c in rig.calls()}), ["api"])
        windows[0]["accepted_by"] = {"qa-code-critic": 1}       # the first window is accepted: the next one is entered
        built = rig.driver()
        built[0].stage_scope = lambda stage, kind="": {"scope": ["TC-1", "TC-2"], "windows": windows}
        code, out, started, _ = run_entry(rig, built=built)
        eq("EDGE per window: the next window (e2e-ui) asks about e2e-ui", (code, flag(rig).get("profile")), (3, "e2e-ui"))
    finally:
        rig.done()
    # S6 by kind: a manual-only S6 never asks about an automate-only profile
    rig = Rig(profiles=("api", "e2e-ui"))
    try:
        use_plan({"TC-1": ("api", "automate"), "TC-2": ("e2e-ui", "manual-agent")})
        rig.records(api=unknown("api"), **{"e2e-ui": matched("e2e-ui")})
        driver, started, steps, probes = rig.driver()
        driver.build_check("S6", "manual", cases=["TC-2"])
        eq("EDGE S6 manual: only the manual-agent profile is probed; the unknown api is not asked about", [c["profile"] for c in rig.calls()], ["e2e-ui"])
        try:
            driver.build_check("S6", "automation", cases=["TC-1"])
            check("EDGE S6 automation: the automate profile is asked about", False)
        except story_run.Person as person:
            eq("EDGE S6 automation: the automate profile is asked about", person.build_question["profile"], "api")
        # a profile the dispatch's scope does not hold is not asked about, whatever the kind says
        before = len(rig.calls())
        driver.build_check("S6", "", cases=["TC-2"])
        eq("EDGE S6 no kind (a dispatch of an older story): the DISPATCH's scope decides, never all", [c["profile"] for c in rig.calls()[before:]], ["e2e-ui"])
    finally:
        rig.done()


def edges_foreign_probe_and_data() -> None:
    # AE16: a project's own probe script is never handed a flag it does not know
    rig = Rig(profiles=("api",), foreign=True)
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.records(api=matched("api"))
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        argv = rig.calls()[0]["argv"]
        eq("EDGE AE16: a foreign probe script gets neither --no-evidence nor --task-root", ("--no-evidence" in argv, "--task-root" in argv), (False, False))
        eq("EDGE AE16: and what it printed is read by its fields all the same (a matched record that validates: a line, exit 0)", code, 0)
        check_in("EDGE AE16: ... the line", "the stand runs this story's build", out)
    finally:
        rig.done()
    import stand_identity as SI
    q = SI.data()["question"]
    for key, line in q["lines"].items():
        if key.startswith("why_"):
            continue
        text = line.format(stage="S5", stand="localhost", profile="api", method="the label x of the image", date="2026-10-03", error="the build could not be read",
                           why="the check did not finish in time", said="deployed",
                           files="`src/Page.vue`, `src/Other.vue` (and 2 more)")     # FB-8 N2 (68539227): `{files}` of two lines
        eq(f"EDGE data: the status line `{key}` obeys the rules", line_broken(text), [])
    partly = "\n".join(q["partly_recorded"]["text"]).format(stand="localhost", profile="api")
    eq("EDGE data (t-366 F2): the partly-recorded text obeys the rules", human_broken(partly), [])
    check("EDGE data (t-366 F2): it names what is written and what is not, and offers deployed / retry / stop, without a path or an exception",
          all(n in partly for n in ("is written", "is not written", "`deployed`", "`retry`", "`stop`"))
          and not any(bad in partly for bad in (".jsonl", ".json", "Error", "Traceback", "exit ")), partly)
    forms = SI.data()["answers"]["forms"]
    check("EDGE data (t-366 F3): every form that takes a value has its shape in the data, and it compiles",
          all(re.compile(str(spec["value"])) for spec in forms.values() if spec.get("arg") != "none") and
          all("value" in spec for spec in forms.values() if spec.get("arg") != "none"))
    for key, text in q["reasks"].items():
        sentence = text.format(form="file", needs="the path", example="file /x", sha="a" * 7, short=HEAD[:12], stand="localhost", deployed_short=OLD[:12])
        eq(f"EDGE data: the re-ask `{key}` obeys the rules", human_broken(sentence + "\n\nWhat I need from you is one of these:\n(a) answer `retry` once you have changed the stand, and I check again."), [])
    check("EDGE data: the held text obeys the rules too", human_broken(q["held"]["stop"].format(stand="localhost") + "\n\nWhat I need from you is one of these:\n(a) `retry`.") == [])


def fb8_matched_line_names_not_shipped() -> None:
    """FB-8 (R10N1, E13): a `matched` record that did not compare a build input the container does not ship SAYS so; the cap
    is 5 names (AT 5: all named, BEYOND at 6: five and "and 1 more"); an empty or absent list is the old `matched` line."""
    rig = Rig(profiles=("api",))
    try:
        driver = rig.driver()[0]
        names = [f"build/Makefile{n}" for n in range(1, 7)]

        def line_of(shipped):
            extra = {} if shipped is None else {"not_shipped_files": shipped}
            rec = dict(matched("api", kind="sources", linkage="verified_content"), **extra)
            text, person = driver.build_outcome("S5", "", "localhost", "api", rec, "")
            return text, person
        old, person = line_of(None)
        check_in("FB8 no list: the old matched line", "the stand runs this story's build (read by", old)
        check_not_in("FB8 no list: no not-compared words", "not compared", old)
        eq("FB8 empty list: the very same old line", line_of([])[0], old)
        five, person = line_of(names[:5])
        check_in("FB8 five files: the line says they were not compared, because they are not in the container",
                 "not compared, because they are not in the container: ", five)
        check("FB8 five files: all five named, no 'more'", all(f"`{n}`" in five for n in names[:5]) and "more" not in five, five)
        six, person = line_of(names)
        check("FB8 six files: five named and 'and 1 more'", f"`{names[4]}`" in six and f"`{names[5]}`" not in six
              and "and 1 more" in six, six)
        eq("FB8 it is a line, never a question", person, None)
        for text in (five, six):
            eq("FB8 the line obeys human-questions.md", line_broken(text), [])
        odd, person = line_of(["run_suite.py"])
        eq("FB8 a file name the question rules refuse (a script name) is said in the plain words, and the line still obeys the rules",
           (line_broken(odd), "run_suite.py" in odd, "some files of this story" in odd), ([], False, True))
    finally:
        rig.done()


CONTENT = "c" * 64


def fb8_with_identity(files, content=CONTENT, image=DIGEST) -> dict:
    rec = dict(sources_mismatched("api", files))
    if content:
        rec["content_identity"] = content
    if image:
        rec["observed_image"] = image
    return rec


def fb8_mismatched_sources_offers_test_as_is() -> None:
    """FB-8 (R13): the content-mismatch question offers `test as is` beside `retry` and `stop`, its text obeys the question rules and
    names the third door, and the packet carries the content the word will bind to and the image the probe read."""
    rig = Rig(profiles=("api",))
    try:
        driver = rig.driver()[0]
        person = driver.build_person("S5", "", "localhost", "api", fb8_with_identity(["Makefile"]), None, "mismatched_sources")
        packet = person.build_question
        eq("FB8 the answers", packet["answers"], ["retry", "test as is", "stop"])
        eq("FB8 the packet: the content fingerprint and the image the probe read", (packet["content"], packet["image"]), (CONTENT, DIGEST))
        check_in("FB8 the text names the third door", "`test as is`", person.text)
        check_in("FB8 ... and says the report will say it was the person's decision", "the report says the tests ran by your decision", person.text)
        check_not_in("FB8 ... and no longer says no door exists", "no way to test it as it is", person.text)
        eq("FB8 the text obeys human-questions.md", human_broken(person.text), [])
        bare = driver.build_person("S5", "", "localhost", "api", fb8_with_identity(["Makefile"], content="", image=""), None, "mismatched_sources")
        eq("FB8 a record with no identity: the packet says so (empty content, no image)", (bare.build_question["content"], bare.build_question["image"]), ("", ""))
        slots = driver.build_answer_slots(packet, "w", "")
        eq("FB8 the answer slots carry the content", slots["content"], CONTENT)
    finally:
        rig.done()


def fb8_test_as_is_runs_confirm_with_content() -> None:
    """FB-8 (K-door, R13, E20): `test as is` runs `confirm ... --content <identity> --image <image>` with the words whole; a packet
    without it among its answers (a question asked before this change) sends the words to the conductor and records nothing."""
    rig = Rig(profiles=("api",))
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.records(api=fb8_with_identity(["Makefile"]))
        code, out, started, _ = run_entry(rig, s5=("TC-1",))
        eq("FB8 the entry asks the content question, no role", (code, flag(rig).get("variant"), started), (3, "mismatched_sources", []))
        eq("FB8 the open packet offers `test as is`", "test as is" in flag(rig)["answers"], True)
        run_entry(rig, "test as is", s5=("TC-1",))
        eq("FB8 ONE line: kind content_accepted, this story's commit, the content, the image and the words whole",
           [(r["kind"], r["revision"], r["content"], r["image"], r["words"]) for r in rig.confirmations()],
           [("content_accepted", HEAD, CONTENT, DIGEST, "test as is")])
    finally:
        rig.done()
    rig = Rig(profiles=("api",))
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.records(api=fb8_with_identity(["Makefile"], content=""))
        run_entry(rig, s5=("TC-1",))
        eq("FB8 (E20) the packet offers `test as is` although it carries no content",
           ("test as is" in flag(rig)["answers"], flag(rig).get("content")), (True, ""))
        run_entry(rig, "test as is", s5=("TC-1",))
        eq("FB8 (E20) an empty content never records a word nobody gave (`--content ''` reaches the CLI, which refuses): "
           "nothing recorded", rig.confirmations(), [])
    finally:
        rig.done()
    rig = Rig(profiles=("api",))
    try:
        use_plan({"TC-1": ("api", "automate")})
        rig.records(api=fb8_with_identity(["Makefile"]))
        run_entry(rig, s5=("TC-1",))
        path = rig.task_root / "state" / "driver-state.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["build_question"]["answers"] = ["retry", "stop"]          # a question asked before this change
        path.write_text(json.dumps(state), encoding="utf-8")
        set_control(rig.root, {"conductor": {"action": "continue", "did": "read it", "text": "Read."}})
        run_entry(rig, "test as is", s5=("TC-1",))
        eq("FB8 (E20) a packet that did not offer it: one conductor call, nothing recorded",
           (len(d2_conductor_calls(rig.root)), rig.confirmations()), (1, []))
    finally:
        rig.done()


def fb8_person_content_line_replaces_confirmed() -> None:
    """FB-8 (R16): the build-check line of a person-confirmed record of kind content_accepted is `person_content`, never the base
    `person_confirmed` / `person_confirmed_no_image` pair; the files are capped at the question's limit (5 at, 6 beyond)."""
    rig = Rig(profiles=("api",))
    try:
        driver = rig.driver()[0]

        def line_of(files, identity="person-confirmed:2026-10-03T09:30:00+00:00"):
            rec = record("api", "person_confirmed", observed_runtime_identity=identity, evidence_refs=[],
                         content_identity=CONTENT, accepted_files=files,
                         provenance={"technical_verification": False, "identity_kind": "person_confirmed"},
                         person_confirmation={"words": "test as is", "at": "2026-10-03T09:30:00+00:00", "task": rig.task,
                                              "kind": "content_accepted", "revision": HEAD, "content": CONTENT})
            return driver.build_outcome("S5", "", "localhost", "api", rec, "")
        names = [f"build/Makefile{n}" for n in range(1, 7)]
        text, person = line_of(names[:5])
        check_in("FB8 the line says it was tested as it is, by the person's word, with the date", "tested as it is by your word of 2026-10-03", text)
        check("FB8 five files: all named, none counted", all(f"`{n}`" in text for n in names[:5]) and "more" not in text, text)
        check_not_in("FB8 no base sentence (the build is not 'confirmed')", "the build is confirmed", text)
        six, _ = line_of(names, identity="image:sha256:" + "b" * 64)
        check("FB8 six files (and an image identity): five named and 'and 1 more'; the no-image sentence is still not used",
              f"`{names[5]}`" not in six and "and 1 more" in six and "no image was read" not in six, six)
        eq("FB8 it is a line, never a question; it obeys the rules", (person, line_broken(text)), (None, []))
    finally:
        rig.done()


def ep1_28_host_run_stand_asks_the_version() -> None:
    """EP1-28 (H-1, H-2, H-7): a stand whose application runs on the host (no container) reaches the build question on the
    manual half of S6, with no probe registered; a role-less repository pair says why in ONE line and asks nothing."""
    import runtime_probe
    import story_run
    app = {"repo_id": "app", "local_path": "ui", "role": "application", "execution_profile_id": "web"}
    tests = {"repo_id": "tests", "local_path": "ui-tests", "role": "tests", "execution_profile_id": "web"}

    def host_rig(*repos):
        rig = Rig(profiles=("web",), real=True, host=True)
        cfg = json.loads(rig.config_path.read_text(encoding="utf-8"))
        cfg["implementation_repos"] = [dict(r) for r in repos]
        cfg["execution"]["runtime_probes"] = {}
        rig.config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        use_plan({"TC-1": ("web", "manual-agent")})
        return rig
    saved = runtime_probe.containers
    runtime_probe.containers = lambda *a, **k: []
    rig = host_rig(app, tests)
    try:
        driver = rig.driver()[0]
        try:
            driver.build_check("S6", "manual", cases=["TC-1"])
            check("EP1-28 the MyBooks-shape fixture (web profile, application + tests repositories, no entry) asks", False)
        except story_run.Person as person:
            bq = person.build_question
            eq("EP1-28 the MyBooks-shape fixture reaches the `no_container` question, for the application's checkout",
               (bq["variant"], bq["profile"], bq["answers"]), ("no_container", "web", ["deployed", "retry", "command", "stop"]))
            check_in("EP1-28 the question says the application is not run by a container", "not run by a container I can read", person.text)
            check_not_in("EP1-28 docker names nothing: no docker line", "Docker runs", person.text)
            eq("EP1-28 the question obeys human-questions.md", human_broken(person.text), [])
    finally:
        rig.done()
    # same role twice: ONE line with the reason, no question, no probe
    rig = host_rig(dict(app, role="tests"), tests)
    try:
        driver = rig.driver()[0]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            driver.build_check("S6", "manual", cases=["TC-1"])
        text = out.getvalue()
        check_in("EP1-28 two repositories of one role: the line says why no probe could be worked out", "2 implementation repositories for profile web", text)
        check_in("EP1-28 ... and that nothing is asked", "nothing is asked of you", text)
        eq("EP1-28 ... it is a line and obeys the rules", line_broken(text.strip()), [])
        eq("EP1-28 ... no probe ran", rig.calls(), [])
        # F-1: S5 and the automation half keep the old line (no derived probe there)
        for stage, kind in (("S5", ""), ("S6", "automation")):
            use_plan({"TC-1": ("web", "automate")})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                driver.build_check(stage, kind, cases=["TC-1"])
            check_in(f"EP1-28 F-1 {stage} {kind or 'window'}: the plain no-probe line", "is registered for the web tests, so it is not checked here", out.getvalue())
    finally:
        rig.done()
        runtime_probe.containers = saved
    # H-7: the docker line of the question
    rig = Rig(profiles=("web",))
    try:
        driver = rig.driver()[0]

        def text_with(containers):
            runtime_probe.containers = containers if callable(containers) else (lambda *a, **k: containers)
            try:
                return driver.build_person("S6", "manual", "localhost", "web", unknown("web", container=""), None, "no_container").text
            finally:
                runtime_probe.containers = saved
        check_not_in("EP1-28 H-7 no docker (OSError): no docker line, no error", "Docker runs", text_with(lambda *a, **k: (_ for _ in ()).throw(OSError("x"))))
        quiet = text_with([])
        check_not_in("EP1-28 H-7 docker runs nothing: no docker line", "Docker runs", quiet)
        check_in("EP1-28 H-7 ... and the paragraphs keep their one blank line", "is your call.\n\nWhat I need from you is one of these:", quiet)
        foreign = text_with([("proj-db-1", "postgres"), ("proj-mail-1", "mailpit")])
        check_in("EP1-28 H-7 foreign containers: named, with the invitation to say which", "Docker runs `proj-db-1`, `proj-mail-1` on this machine", foreign)
        check_in("EP1-28 H-7 ... `deployed` is still the person's word, offered as before", "(a) answer `deployed`", foreign)
        six = text_with([(f"c{n}", "img") for n in range(1, 7)])
        check("EP1-28 H-7 six containers: five named and a count", all(f"`c{n}`" in six for n in range(1, 6)) and "`c6`" not in six and "and 1 more" in six, six)
        five = text_with([(f"c{n}", "img") for n in range(1, 6)])
        check("EP1-28 H-7 five containers: all named, none counted", "`c5`" in five and "more on this machine" not in five, five)
        for label, text in (("foreign", foreign), ("six", six)):
            eq(f"EP1-28 H-7 {label}: the question obeys human-questions.md", human_broken(text), [])
    finally:
        rig.done()


def ep1_41c_the_stand_of_the_profile() -> None:
    """EP1-41c: `build_check` asks about the stand of the PROFILE (surfaces.stand_of_profile), not the story's `pipeline.environment`:
    on a mixed project the native profile's question names the device stand and the web profile's the API stand; a profile with no
    stand of its own is a line and no question; a project that names no `surface` reads the table 0 times and is asked as before."""
    import runtime_probe
    import story_run
    import surfaces
    device = {"name": "emulator", "surface": "android", "driver": {"url": "http://127.0.0.1:4723"}, "app": {"id": "com.example.app"}}
    api = {"name": "localhost", "base_url": "http://localhost:8080"}
    web_p, native_p = {"profile_id": "web", "capabilities": ["web"]}, {"profile_id": "android", "capabilities": ["native"]}
    saved = runtime_probe.containers
    runtime_probe.containers = lambda *a, **k: []

    def rig_of(environments, profiles, plan, selected="localhost", **records):
        rig = Rig(profiles=tuple(p["profile_id"] for p in profiles))
        cfg = json.loads(rig.config_path.read_text(encoding="utf-8"))
        cfg["environments"], cfg["profiles"] = [dict(e) for e in environments], [dict(p) for p in profiles]
        rig.config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        d2_pipeline(rig.task_root, environment=selected, environment_pending=False)       # the stand the story confirmed
        use_plan(plan)
        rig.records(**records)
        return rig

    def ask(driver, stage="S6", kind="manual", cases=("TC-1", "TC-2")):
        """(None, printed text) or (the Person's build_question, text)."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                driver.build_check(stage, kind, cases=list(cases))
            except story_run.Person as person:
                return person.build_question, out.getvalue()
        return None, out.getvalue()
    plan = {"TC-1": ("web", "manual-agent"), "TC-2": ("android", "manual-agent")}
    rig = None
    try:
        # a mixed project, two stands: the native profile asks about the device stand, the web profile about the API stand
        rig = rig_of([api, device], [web_p, native_p], plan, web=unknown("web", container=""), android=unknown("android", container=""))
        driver = rig.driver()[0]
        eq("41c mixed: the story's stand is the API stand (confirmed)", driver.pipeline().get("environment"), "localhost")
        bq, text = ask(driver, cases=("TC-2",))
        eq("41c mixed: the native profile's question is about the DEVICE stand, not `pipeline.environment`",
           (bq or {}).get("environment"), "emulator")
        eq("41c mixed: ...for the native profile, a question that obeys the rules", (bq["profile"], human_broken(bq["text"])), ("android", []))
        check_in("41c mixed: ...and the text names the device stand", "`emulator`", bq["text"])
        bq, text = ask(driver, cases=("TC-1",))
        eq("41c mixed: the web profile's question stays on the API stand", (bq or {}).get("environment"), "localhost")
        eq("41c mixed: the probe was told the profile's own stand", sorted(c["profile"] for c in rig.calls()), ["android", "web"])
        rig.done()
        # one stand only, and it is the device: the native profile asks about it; the web profile has no stand of its own
        rig = rig_of([device], [web_p, native_p], plan, selected="emulator", web=unknown("web", container=""),
                     android=unknown("android", container=""))
        driver = rig.driver()[0]
        bq, text = ask(driver, cases=("TC-2",))
        eq("41c one stand: the native profile asks about the only (device) stand", (bq or {}).get("environment"), "emulator")
        before = len(rig.calls())
        bq, text = ask(driver, cases=("TC-1",))
        check("41c one stand: the web profile has no stand of its own - a line, NO question, no probe run",
              bq is None and "web tests have no stand of their own" in text and len(rig.calls()) == before, text)
        eq("41c ... the line is a line and obeys the rules", line_broken(text.strip().splitlines()[-1]), [])
        check_not_in("41c ... and it names no flag or script", "story_run", text)
        rig.done()
        # two device stands: the one whose `surface` is the profile id
        tablet = dict(device, name="tablet", surface="ios")
        ios_p = {"profile_id": "ios", "capabilities": ["native"]}
        rig = rig_of([device, tablet], [native_p, ios_p], {"TC-1": ("android", "manual-agent"), "TC-2": ("ios", "manual-agent")},
                     selected="emulator", android=unknown("android", container=""), ios=unknown("ios", container=""))
        driver = rig.driver()[0]
        eq("41c two device stands: profile `android` -> the stand with surface android", (ask(driver, cases=("TC-1",))[0] or {}).get("environment"), "emulator")
        eq("41c two device stands: profile `ios` -> the stand with surface ios", (ask(driver, cases=("TC-2",))[0] or {}).get("environment"), "tablet")
        rig.done()
        other = {"profile_id": "mobile", "capabilities": ["native"]}
        rig = rig_of([device, tablet], [other], {"TC-1": ("mobile", "manual-agent")}, selected="emulator", mobile=unknown("mobile", container=""))
        driver = rig.driver()[0]
        bq, text = ask(driver, cases=("TC-1",))
        check("41c two device stands and no surface equal to the profile id: a line, no question (the stand is never guessed)",
              bq is None and "no stand of their own" in text and rig.calls() == [], text)
        rig.done()
        # the API stand is still pending: build_check returns at once - native is not asked either (the safe side)
        rig = rig_of([api, device], [web_p, native_p], plan, android=unknown("android", container=""))
        d2_pipeline(rig.task_root, environment="localhost", environment_pending=True)
        driver = rig.driver()[0]
        bq, text = ask(driver, cases=("TC-2",))
        eq("41c a pending story stand: no probe, no question, no line", (bq, text, rig.calls()), (None, "", []))
        rig.done()
        # a broken table is a line (the check broke), never a question and never a pass
        rig = rig_of([api, dict(device, surface="andriod")], [web_p, native_p], plan, android=unknown("android", container=""))
        driver = rig.driver()[0]
        bq, text = ask(driver, cases=("TC-2",))
        check("41c a `surface` the table lacks: one line says the check broke, no question", bq is None and "could not be checked" in text, text)
        rig.done()
        # a project that names no `surface`: the table is read 0 times and the question is about the story's stand as before
        reads = {"n": 0}
        real_rows = surfaces.rows
        surfaces.rows = lambda: (reads.__setitem__("n", reads["n"] + 1), real_rows())[1]
        try:
            rig = rig_of([api], [web_p], {"TC-1": ("web", "manual-agent")}, web=unknown("web", container=""))
            driver = rig.driver()[0]
            bq, text = ask(driver, cases=("TC-1",))
        finally:
            surfaces.rows = real_rows
        eq("41c a web config: the question is about the story's stand, the table was read 0 times",
           ((bq or {}).get("environment"), reads["n"]), ("localhost", 0))
    finally:
        runtime_probe.containers = saved
        if rig is not None:
            rig.done()


def ep1_41e_the_device_build_question() -> None:
    """EP1-41e: `how` on a record that says `device_stand` is the `device_build` question (chosen by the FIELD, before the container
    test); what it says the device holds and what voids the word follow what the probe could see (hash read / not read / no build
    read), so the promise of the question is always one the code can keep. The binding itself is proved in test_stand_identity.py."""
    import story_run
    rig = Rig(profiles=("android",))
    seen = "com.example.app 1.2.3 (42) sha256:" + "a" * 12
    ident = "image:sha256:" + "b" * 64
    try:
        driver = rig.driver()[0]

        def ask(**extra):
            rec = unknown("android", container="", device_stand=True, observed_runtime_identity=ident, **extra)
            line, person = driver.build_outcome("S6", "manual", "emulator", "android", rec, "")
            return line, person

        line, person = ask(observed_device_build=seen)
        bq = person.build_question
        eq("41e: a device record's `how` is the device_build question, with the four answers the no-container question has",
           (line, bq["variant"], bq["answers"]), ("", "device_build", ["deployed", "retry", "command", "stop"]))
        check_in("41e: it names the device stand", "on the device stand `emulator`", person.text)
        check_in("41e: it says what the device holds", f"The device has {seen}.", person.text)
        check_in("41e: with the file hashed, the promise is about the BUILD", "a different build on the device voids it;", person.text)
        check_not_in("41e: ...and says nothing of the container the no-container question speaks of", "container", person.text)
        eq("41e: ...it obeys human-questions.md", human_broken(person.text), [])
        eq("41e: ...and the word binds to the identity the probe read (the `{image}` of the executor)", bq["image"], ident)
        check_in("41e: the details file keeps what the check said", "stand `emulator`", person.details)
        # the hash could not be read: the promise narrows to the version
        _line, narrow = ask(observed_device_build="com.example.app 1.2.3 (42)",
                            limitation="the installed file was not hashed, so a rebuild with the same version is not seen")
        check_in("41e: hash unread: the promise is about the VERSION", "a different version on the device voids it;", narrow.text)
        check_not_in("41e: ...and no promise about a build is left in the text", "a different build", narrow.text)
        eq("41e: ...it obeys the rules", human_broken(narrow.text), [])
        # no build read at all (a platform with no way to read it): no promise that nothing can keep
        _line, blind = ask()
        check_in("41e: no build read: it says so", "I could not read which build is installed.", blind.text)
        check_not_in("41e: ...and promises nothing about a different build or version", "voids", blind.text)
        check_in("41e: ...the answers are still there", "(a) answer `deployed` if this build holds that commit; I take your word for this story only;", blind.text)
        # chosen by the field, before the container test; the other variants are unchanged
        rec = unknown("android", container="ui-c", device_stand=True, observed_device_build=seen)
        eq("41e: a device record with a container named is still the device question",
           driver.build_outcome("S6", "manual", "emulator", "android", rec, "")[1].build_question["variant"], "device_build")
        rec = unknown("android", container="", observed_device_build=seen)
        eq("41e: control: the same record without the field is the no-container question (the old road)",
           driver.build_outcome("S6", "manual", "emulator", "android", rec, "")[1].build_question["variant"], "no_container")
        rec = unknown("android", asks="confirm", device_stand=True, observed_device_build=seen)
        eq("41e: `confirm` on a device stand stays `confirm`",
           driver.build_outcome("S6", "manual", "emulator", "android", rec, "")[1].build_question["variant"], "confirm")
        rec = unknown("android", asks=None, device_stand=True, error="com.example.app is not installed on the device")
        line, person = driver.build_outcome("S6", "manual", "emulator", "android", rec, "")
        check("41e: an unreadable device build (no `asks_person`) is a line and no question", person is None and "com.example.app is not installed" in line, line)
        eq("41e: ...the line obeys the rules", line_broken(line), [])
        # a build line that breaks a rule of the questions falls back to plain words, never to the broken text
        _line, odd = ask(observed_device_build="com.example.app 1.2.3 (42) --flag build.py")
        eq("41e: a build line the rules do not allow in a question is said in plain words", (human_broken(odd.text), "build.py" in odd.text), ([], False))
        check_in("41e: ...and the details are not lost", "stand `emulator`", odd.details)
        data = SI_data()["question"]["variants"]["device_build"]
        check_eq_keys = {"device_has", "device_unread", "voids_build", "voids_version", "voids_unseen"} <= set(data)
        check("41e data: the variant carries the sentences it fills (FR-13: words are data)", check_eq_keys and story_run is not None)
    finally:
        rig.done()


def SI_data() -> dict:
    import stand_identity
    return stand_identity.data()


def main() -> None:
    run_scenarios([], [
        ep1_41e_the_device_build_question,
        ep1_41c_the_stand_of_the_profile,
        ep1_28_host_run_stand_asks_the_version,
        fb8_mismatched_sources_offers_test_as_is,
        fb8_test_as_is_runs_confirm_with_content,
        fb8_person_content_line_replaces_confirmed,
        forms_reader,
        k35_the_question_and_its_texts,
        k36_deployed_always_confirm_retry,
        k36_method_answers,
        k36_mismatched_answers,
        k36_other_words_and_edges,
        t366_f2_f3_f5_partly_recorded_prose_label_and_console,
        t366_o1_a_person_label_does_not_outrank_the_sources,
        k37_positions_and_the_flag,
        k38_the_confirm_variant,
        k39_what_is_a_line_and_not_a_question,
        k40_one_question_per_profile,
        k44_a_labelled_stand_asks_nothing,
        edges_per_window_and_per_kind,
        edges_foreign_probe_and_data,
        fb8_matched_line_names_not_shipped,
    ])
    harness.finish("test_story_run_stand_identity")


if __name__ == "__main__":
    main()
