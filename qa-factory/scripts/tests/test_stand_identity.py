"""stand_identity.py (t-300 N1a): the registry of ways to read a stand's build, and the person's word for one story.

Keys: K1 validate, K2 load, K3 `record` (and its refusals), K4 the writer lock (a DETERMINISTIC test: the test holds the
lock, the writer waits - plus two real writers at once), K5 `confirm`, K6 `forget`, K7 `show`, K8 `unconfirm`,
K9 `definition_sha`. The probe's reading of these stores is test_runtime_probe_onboarding.py.

Mutations this file kills (each by this file alone, run on a scratch copy of the package):
  the writer takes no lock | the writer does not wait for a held lock (K4) | the writer overwrites a corrupt file (K3)
  the `--command` split keeps the posix escape on Windows (N1b: `C:\\x\\y.exe` loses its backslashes) | the Windows split
  keeps the quotes round a part of a word (t-366 F1)

Run: python -B scripts/tests/test_stand_identity.py
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     temp_project)

import runtime_paths as RP  # noqa: E402
import stand_identity as SI  # noqa: E402
from event_store import EventStore  # noqa: E402

HEAD = "0cc6c4f1" + "a" * 32
OTHER = "d" * 40
DIGEST = "image:sha256:" + "b" * 64
STAMP = "2026-10-02T11:40:00+00:00"
SHA64 = "c" * 64


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project() -> Path:
    """A throwaway project whose config names two stands and two test profiles (the CLI refuses what it does not name)."""
    root = temp_project()
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["environments"] = [{"name": "localhost", "base_url": "http://localhost:8080", "frontend_url": "http://localhost:5173",
                            "credentials_by_role": {"default_user": "x"}},
                           {"name": "preview", "base_url": "https://preview.example/api"}]
    cfg["profiles"] = [{"profile_id": "api"}, {"profile_id": "e2e-ui"}]
    cfg["implementation_repos"] = [{"repo_id": "testproject1-ui", "local_path": "../ui", "execution_profile_id": "e2e-ui"}]
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return root


def cli(root: Path, *args):
    return run_script("stand_identity.py", *args, cwd=root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)))


def good(method: str, **extra) -> dict:
    row = {"environment_id": "localhost", "profile_id": "e2e-ui", "repo_id": "testproject1-ui", "method": method,
           "source": "person", "recorded_by": "person", "recorded_at": STAMP, "words": "the way I read it"}
    row.update({"oci_label": {"label": "org.opencontainers.image.revision"},
                "build_sha_file": {"path": "/usr/share/nginx/html/build-sha.txt"},
                "command": {"argv": ["python", "build.py", "--print"]}, "sources": {},
                "person_confirms": {"stand_definition_sha": SHA64}, "withdrawn": {}}[method])
    row.update(extra)
    return row


def k1_validate() -> None:
    methods = ["oci_label", "build_sha_file", "command", "sources", "person_confirms", "withdrawn"]
    ok = {"schema_version": 1, "rows": [good(m) for m in methods]}
    check_eq("K1 control: one valid row per method (and an app_root on sources) validates clean",
             (SI.validate(ok), SI.validate({"rows": [good("sources", app_root="/srv/app")]})), ([], []))
    check_eq("K1: a file with no rows, and an empty object, validate clean (absence is never an error)",
             (SI.validate({"rows": []}), SI.validate({}), SI.check_text(""), SI.check_text("{}")), ([], [], [], []))

    def refused(label, field, row=None, **swap):
        base = dict(row if row is not None else good("oci_label"), **swap)
        errors = SI.validate({"rows": [base]})
        check_eq(f"K1: {label}: exactly one error", len(errors), 1)
        text = errors[0] if errors else ""
        for needle in ("row 0", "localhost", "e2e-ui", field):
            check_in(f"K1: {label}: the error names `{needle}`", needle, text)

    refused("an unknown method", "method", row=dict(good("sources"), method="teleport"))
    refused("build_sha_file without a path", "path", row={k: v for k, v in good("build_sha_file").items() if k != "path"})
    refused("a command with an empty argv", "argv", row=good("command", argv=[]))
    refused("a command whose argv holds a non-string", "argv", row=good("command", argv=["ok", 5]))
    refused("a command whose argv holds an empty word", "argv", row=good("command", argv=["ok", " "]))
    refused("recorded_at that is not ISO-8601", "recorded_at", recorded_at="yesterday")
    refused("a source outside the set", "source", source="somebody")
    refused("empty words with source person", "words", words="  ")
    refused("a probe-discovered person_confirms", "person_confirms", row=good("person_confirms", source="probe discovered", words=""))
    refused("a probe-discovered command", "command", row=good("command", source="probe discovered", words=""))
    refused("a probe-discovered withdrawn", "withdrawn", row=good("withdrawn", source="probe discovered", words=""))
    refused("a factory-default command", "command", row=good("command", source="factory default", words=""))
    refused("a stand_definition_sha that is not 64 hex", "stand_definition_sha", row=good("person_confirms", stand_definition_sha="abc"))
    refused("an oci_label with a blank label", "label", row=good("oci_label", label=" "))
    check_eq("K1 control: a probe-discovered oci_label with NO words is valid (the probe is not a person)",
             SI.validate({"rows": [good("oci_label", source="probe discovered", recorded_by="runtime_probe.py", words="")]}), [])
    errors = SI.check_text('{"rows": [], "rows": []}')
    check_eq("K1: duplicate JSON keys are refused, once", len(errors), 1)
    check_in("K1: and the error says what is wrong", "appears twice", errors[0] if errors else "")
    check_eq("K1: a file that is not an object is refused", len(SI.validate([1])), 1)
    check_eq("K1: `rows` that is not a list is refused", len(SI.validate({"rows": {}})), 1)
    check_eq("K1: a schema_version this factory does not read is refused", len(SI.validate({"schema_version": 2, "rows": []})), 1)
    check_eq("K1: a row that is not an object is refused, naming its index",
             "row 1" in "".join(SI.validate({"rows": [good("sources"), "x"]})), True)


def k2_load() -> None:
    root = project()
    try:
        path = SI.registry_path(root)
        check_eq("K2: the registry's path is the layout's own (records/, FR-37)", path, root / "qa-factory" / "records" / "stand-identity.json")
        check_eq("K2: absent -> nothing in force, no error", SI.load(root), ({}, []))
        path.parent.mkdir(parents=True)
        for label, text in (("0 bytes", ""), ("{}", "{}"), ('{"rows":[]}', '{"rows":[]}')):
            path.write_text(text, encoding="utf-8")
            check_eq(f"K2: {label} -> nothing in force, no error", SI.load(root), ({}, []))
        rows = [good("oci_label", label="a.b/first", recorded_at="2026-10-01T10:00:00+00:00"),
                good("build_sha_file", recorded_at="2026-10-02T10:00:00+00:00"),
                good("oci_label", environment_id="preview", profile_id="api"),
                good("sources", words="sources, please")]
        path.write_text(json.dumps({"schema_version": 1, "rows": rows}), encoding="utf-8")
        in_force, errors = SI.load(root)
        check_eq("K2: the last row of a stand+profile wins (file order)",
                 (in_force[("localhost", "e2e-ui")]["method"], len(in_force), errors), ("sources", 2, []))
        check_eq("K2: the state counts the history (every valid row)", SI.state(root)["history"], 4)
        check_eq("K2: keys are exact: `Localhost` is another stand", ("Localhost", "e2e-ui") in in_force, False)
        withdrawn = good("withdrawn", environment_id="preview", profile_id="api")
        path.write_text(json.dumps({"rows": rows + [withdrawn]}), encoding="utf-8")
        found = SI.state(root)
        check_eq("K2: a `withdrawn` row leaves nothing in force for its key, and is remembered (a probe never writes over it)",
                 (("preview", "api") in found["in_force"], ("preview", "api") in found["withdrawn"], len(found["in_force"])),
                 (False, True, 1))
        bad = dict(good("build_sha_file"))
        bad.pop("path")
        path.write_text(json.dumps({"rows": [good("oci_label"), bad]}), encoding="utf-8")
        in_force, errors = SI.load(root)
        check_eq("K2: one invalid row is ignored and named; its valid neighbour still answers (AE5)",
                 (list(in_force), len(errors), "row 1" in errors[0]), ([("localhost", "e2e-ui")], 1, True))
        path.write_text("{ not json", encoding="utf-8")
        in_force, errors = SI.load(root)
        check_eq("K2: a corrupt file -> nothing in force and ONE error", (in_force, len(errors)), ({}, 1))
        check_in("K2: the error names the file", "qa-factory/records/stand-identity.json", errors[0])
        check_in("K2: and the door (fix the row or delete the file)", "delete the file", errors[0])
        path.write_text('{"rows": [], "rows": []}', encoding="utf-8")
        check_eq("K2: duplicate keys make the file unreadable (the same error)", len(SI.load(root)[1]), 1)
        path.write_text("[1, 2]", encoding="utf-8")
        check_eq("K2: a file that is not an object is an error too", len(SI.load(root)[1]), 1)
    finally:
        cleanup(root)


def k3_cli_record() -> None:
    root = project()
    try:
        path = SI.registry_path(root)
        done = cli(root, "record", "--environment", "localhost", "--profile", "e2e-ui", "--method", "oci_label",
                   "--words", "label it: org.opencontainers.image.revision")
        check_eq("K3: record exits 0", done.returncode, 0)
        check_in("K3: it acknowledges the stand", "Recorded the decision for stand `localhost`", done.stdout)
        check_in("K3: it names the file the team commits", "qa-factory/records/stand-identity.json", done.stdout)
        check_eq("K3: one row appended, with the person's words whole and the repository of the profile",
                 [(r["method"], r["source"], r["words"], r["repo_id"], r["label"])
                  for r in json.loads(path.read_text(encoding="utf-8"))["rows"]],
                 [("oci_label", "person", "label it: org.opencontainers.image.revision", "testproject1-ui",
                   "org.opencontainers.image.revision")])
        for method, args, field in (("build_sha_file", ["--path", "/srv/build.txt"], "path"),
                                    ("command", ["--command", "python3 print_build.py --short"], "argv"),
                                    ("sources", ["--app-root", "/srv/app"], "app_root"),
                                    ("person_confirms", [], "stand_definition_sha")):
            done = cli(root, "record", "--environment", "localhost", "--profile", "api", "--method", method, *args,
                       "--words", f"my words for {method}")
            check_eq(f"K3: record --method {method} exits 0", done.returncode, 0)
            row = json.loads(path.read_text(encoding="utf-8"))["rows"][-1]
            check(f"K3: and the row carries `{field}`", field in row or method == "person_confirms" and bool(row.get(field)), str(row))
        row = json.loads(path.read_text(encoding="utf-8"))["rows"]
        check_eq("K3: a --command is split like a shell does (posix), into an argv list",
                 [r["argv"] for r in row if r["method"] == "command"], [["python3", "print_build.py", "--short"]])
        check_eq("K3: a person_confirms row carries the stand definition it was given for (Q10, base_url + frontend_url)",
                 [r["stand_definition_sha"] for r in row if r["method"] == "person_confirms"],
                 [SI.definition_sha({"base_url": "http://localhost:8080", "frontend_url": "http://localhost:5173"})])
        check_eq("K3: the registry validates clean after all that", cli(root, "validate").returncode, 0)
        before = sha(path)
        for label, args, needles in (
                ("a stand that is not in the config", ["record", "--environment", "staging", "--profile", "api", "--method", "oci_label",
                                                       "--words", "w"], ("staging", "/qa-factory:qa-onboarding")),
                ("a profile that is not in the config", ["record", "--environment", "localhost", "--profile", "perf", "--method", "oci_label",
                                                         "--words", "w"], ("perf", "/qa-factory:qa-onboarding")),
                ("a profile written as the template placeholder `{profile}` (the executor writes the concrete key, never this)",
                 ["record", "--environment", "localhost", "--profile", "{profile}", "--method", "oci_label", "--words", "w"],
                 ("{profile}", "/qa-factory:qa-onboarding")),
                ("the `*` entry's wildcard as a profile (a registry key is a concrete profile of the config)",
                 ["record", "--environment", "localhost", "--profile", "*", "--method", "oci_label", "--words", "w"],
                 ("`*`", "/qa-factory:qa-onboarding")),
                ("empty words", ["record", "--environment", "localhost", "--profile", "api", "--method", "oci_label", "--words", " "],
                 ("--words", "own words")),
                ("an unknown method", ["record", "--environment", "localhost", "--profile", "api", "--method", "teleport",
                                       "--words", "w"], ("teleport", "oci_label")),
                ("a build_sha_file with no path", ["record", "--environment", "localhost", "--profile", "api", "--method",
                                                   "build_sha_file", "--words", "w"], ("--path",)),
                ("a command with nothing to run", ["record", "--environment", "localhost", "--profile", "api", "--method", "command",
                                                   "--words", "w"], ("--command",)),
                ("a source that is not a person's for a command", ["record", "--environment", "localhost", "--profile", "api",
                                                                   "--method", "command", "--command", "x y", "--words", "w",
                                                                   "--source", "probe discovered"], ("only a person",)),
                ("withdrawn through record (forget is the door)", ["record", "--environment", "localhost", "--profile", "api",
                                                                   "--method", "withdrawn", "--words", "w"], ("forget",))):
            done = cli(root, *args)
            check_eq(f"K3: {label}: exit 2", done.returncode, 2)
            for needle in needles:
                check_in(f"K3: {label}: the refusal says `{needle}`", needle, done.stderr)
            check_eq(f"K3: {label}: nothing written, the file is byte for byte what it was", sha(path), before)
        fresh = project()
        try:
            refused = cli(fresh, "record", "--environment", "nowhere", "--profile", "api", "--method", "oci_label", "--words", "w")
            check_eq("K3: a refusal with no registry creates no file at all", (refused.returncode, SI.registry_path(fresh).exists()), (2, False))
            # t-373 (class completeness of t-363 B3): the onboarding command stands in the how-to-answer block, not above it
            import human_text
            body, block = human_text.split(refused.stderr)
            check_eq("K3: a stand that is not in the config: the sentence carries no plugin command, the how-to-answer block names it",
                     ("/qa-factory:" in body, "`/qa-factory:qa-onboarding`" in block, "onboarding step named below" in body), (False, True, True))
        finally:
            cleanup(fresh)
        # a corrupt file: exit 2, bytes unchanged (M: the writer overwrites a corrupt file)
        path.write_text('{"schema_version": 1, "rows": [ {"half": ', encoding="utf-8")
        before = sha(path)
        done = cli(root, "record", "--environment", "localhost", "--profile", "api", "--method", "oci_label", "--words", "w")
        check_eq("K3: a corrupt registry is refused with exit 2", done.returncode, 2)
        check_in("K3: the refusal names the file", "qa-factory/records/stand-identity.json", done.stderr)
        check_in("K3: and the door", "delete the file", done.stderr)
        check_eq("K3: sha256 equal before and after (a corrupt file is never overwritten, AE4)", sha(path), before)
        done = cli(root, "forget", "--environment", "localhost", "--profile", "api", "--words", "w")
        check_eq("K3: `forget` refuses a corrupt file too, bytes unchanged", (done.returncode, sha(path)), (2, before))
        # stand_identity.py with no subcommand and with a missing --environment
        check_eq("K3: `record` without --environment: exit 2 and the flag is named",
                 (cli(root, "record", "--profile", "api", "--method", "oci_label", "--words", "w").returncode), 2)
    finally:
        cleanup(root)


def k3_f3_a_registry_of_another_version_is_never_rewritten() -> None:
    """t-345 F3 (AE4): the reader (`state()`) refuses a registry whose schema_version is not 1; the WRITER used to rewrite such a
    file as version 1 holding the other version's rows. Reader and writer share ONE predicate now, so they cannot disagree."""
    root = project()
    try:
        path = SI.registry_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        row = good("oci_label")
        for label, version in (("2", 2), ("0", 0), ("a string '1'", "1"), ("null", None)):
            path.write_text(json.dumps({"schema_version": version, "note": "n", "rows": [row]}), encoding="utf-8")
            before = sha(path)
            for words in (["record", "--environment", "localhost", "--profile", "api", "--method", "oci_label", "--words", "w"],
                          ["forget", "--environment", "localhost", "--profile", "api", "--words", "w"]):
                done = cli(root, *words)
                check_eq(f"F3 (schema_version {label}): `{words[0]}` is refused with exit 2", done.returncode, 2)
                check_in(f"F3 (schema_version {label}): the refusal names the file and what the factory reads", "is not one this factory reads (it reads 1)", done.stderr)
                check_in(f"F3 (schema_version {label}): and the door, the same as a corrupt file's", "delete the file", done.stderr)
                check_in(f"F3 (schema_version {label}): and says nothing was written", "Nothing was written", done.stderr)
                check_eq(f"F3 (schema_version {label}): sha256 equal before and after", sha(path), before)
            try:
                SI.append_row(root, SI.make_row({}, "localhost", "api", "oci_label", words="w"))
                raised = False
            except SI.RegistryError as exc:
                raised = "is not one this factory reads" in str(exc)
            check_eq(f"F3 (schema_version {label}): the library writer refuses too, bytes unchanged", (raised, sha(path)), (True, before))
            check_eq(f"F3 (schema_version {label}): and the READER agrees: file_error set, nothing in force",
                     (bool(SI.state(root)["file_error"]), SI.state(root)["in_force"]), (True, {}))
        # CONTROL: version 1 is written, and so is a file with NO schema_version (what state() already reads as 1)
        for label, body in (("1", {"schema_version": 1, "rows": []}), ("absent", {"rows": []})):
            path.write_text(json.dumps(body), encoding="utf-8")
            done = cli(root, "record", "--environment", "localhost", "--profile", "api", "--method", "oci_label", "--words", "w")
            check_eq(f"F3 CONTROL (schema_version {label}): the writer writes, exit 0, and the file says version 1",
                     (done.returncode, json.loads(path.read_text(encoding="utf-8"))["schema_version"], len(json.loads(path.read_text(encoding="utf-8"))["rows"])),
                     (0, 1, 1))
    finally:
        cleanup(root)


def k4_the_writer_waits_for_the_lock() -> None:
    """DETERMINISTIC (t-300 §0b K4): the test HOLDS the writer lock, and the writer waits - the test releases it from
    inside the writer's own wait (`sleep` is injectable), so nothing depends on how fast a process starts."""
    import contextlib
    root = project()
    try:
        path = SI.registry_path(root)
        row = good("oci_label")
        held = contextlib.ExitStack()
        held.enter_context(EventStore(RP.state_file(root, SI.WRITER_LOCK)).lock())
        seen = {"sleeps": 0, "file_while_held": None}

        def sleeper(step):
            seen["sleeps"] += 1
            if seen["sleeps"] == 1:
                seen["file_while_held"] = path.exists()      # the writer has NOT written while the lock was held
                held.close()                                  # ...and the holder lets go
        try:
            written = SI.append_row(root, row, sleep=sleeper)
        except SI.RegistryError as exc:
            written = f"refused instead of waiting: {exc}"
        finally:
            held.close()
        check_eq("K4: the writer found the lock held and waited (it slept at least once)", seen["sleeps"] >= 1, True)
        check_eq("K4: it wrote NOTHING while the lock was held", seen["file_while_held"], False)
        check_eq("K4: and it wrote once the lock was free (the row is there, the file is valid JSON)",
                 (written, [r["method"] for r in json.loads(path.read_text(encoding="utf-8"))["rows"]]), (path, ["oci_label"]))
        check_eq("K4 control: with the lock free the writer does not wait at all",
                 (SI.append_row(root, good("sources", profile_id="api"), sleep=lambda _s: seen.__setitem__("sleeps", 99)), seen["sleeps"]),
                 (path, 1))
        # a lock that is never released: a bounded wait, counted not timed (FR-31), then a refusal with the door
        stuck = contextlib.ExitStack()
        stuck.enter_context(EventStore(RP.state_file(root, SI.WRITER_LOCK)).lock())
        before, naps = sha(path), []
        try:
            SI.append_row(root, good("sources", profile_id="perf"), sleep=naps.append)
            refused = ""
        except SI.RegistryError as exc:
            refused = str(exc)
        finally:
            stuck.close()
        check_eq("K4: a lock nobody releases: exactly `lock_wait_attempts` waits, then a refusal",
                 (len(naps), bool(refused)), (SI.data()["limits"]["lock_wait_attempts"], True))
        check_in("K4: the refusal says what happened and what to do", "Run the command again", refused)
        check_eq("K4: and nothing was written", sha(path), before)
    finally:
        cleanup(root)
    # two real writers at once, ten rows each, different keys: all twenty land (the spec's own K4)
    root = project()
    try:
        procs = [subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(root), tag],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for tag in ("w1", "w2")]
        [p.communicate(timeout=240) for p in procs]
        check_eq("K4: both writers exit 0", [p.returncode for p in procs], [0, 0])
        rows = json.loads(SI.registry_path(root).read_text(encoding="utf-8"))["rows"]
        check_eq("K4: twenty rows, valid JSON, none lost", len(rows), 20)
        check_eq("K4: every key of both writers is there", sorted(r["profile_id"] for r in rows),
                 sorted(f"{tag}-{i}" for tag in ("w1", "w2") for i in range(10)))
        check_eq("K4: the file validates clean", SI.validate(json.loads(SI.registry_path(root).read_text(encoding="utf-8"))), [])
    finally:
        cleanup(root)


def worker(root: str, tag: str) -> int:
    """One of the two concurrent writers of K4: ten rows, ten different keys, through the real writer."""
    for i in range(10):
        SI.append_row(Path(root), good("oci_label", profile_id=f"{tag}-{i}"))
    return 0


def story(root: Path, task: str = "QA-1") -> Path:
    folder = root / "qa-factory" / "artifacts" / task
    (folder / "state").mkdir(parents=True)
    return folder


def k5_confirm() -> None:
    root = project()
    try:
        story(root)
        registry = SI.registry_path(root)
        done = cli(root, "confirm", "--task", "QA-1", "--environment", "localhost", "--profile", "e2e-ui", "--revision", HEAD,
                   "--image", DIGEST, "--words", "yes, it is deployed - I checked the page footer")
        check_eq("K5: confirm exits 0", done.returncode, 0)
        check_in("K5: it says the word is for this story only and where it is", "qa-factory/artifacts/QA-1/state/stand-confirmations.jsonl",
                 done.stdout)
        check_in("K5: and that the registry is unchanged", "stand-identity.json is unchanged", done.stdout)
        lines = (root / "qa-factory" / "artifacts" / "QA-1" / "state" / "stand-confirmations.jsonl").read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[0])
        check_eq("K5: one line, kind deployed, the revision, the image, the words whole",
                 (len(lines), row["kind"], row["revision"], row["image"], row["words"], row["task"], row["recorded_by"]),
                 (1, "deployed", HEAD, DIGEST, "yes, it is deployed - I checked the page footer", "QA-1", "stand_identity.py"))
        check_eq("K5: and the stand definition it was given for", row["stand_definition_sha"],
                 SI.definition_sha({"base_url": "http://localhost:8080", "frontend_url": "http://localhost:5173"}))
        check_eq("K5: the registry is still ABSENT (a confirmation never touches it)", registry.exists(), False)
        done = cli(root, "confirm", "--task", "QA-1", "--environment", "localhost", "--profile", "api", "--revision", HEAD,
                   "--story-revision", OTHER, "--words", "test what is deployed")
        row = json.loads((root / "qa-factory" / "artifacts" / "QA-1" / "state" / "stand-confirmations.jsonl")
                         .read_text(encoding="utf-8").splitlines()[1])
        check_eq("K5: a --story-revision that differs makes it a `test_deployed` word naming both commits, image absent",
                 (done.returncode, row["kind"], row["revision"], row["story_revision"], row["image"]),
                 (0, "test_deployed", HEAD, OTHER, "absent"))
        for label, change, needle in (
                ("a revision that is not 40 hex", {"--revision": HEAD[:12]}, "--revision"),
                ("an image that is not a digest", {"--image": "sha256:abc"}, "--image"),
                ("empty words", {"--words": " "}, "--words"),
                ("a story that has no folder", {"--task": "NOPE-9"}, "NOPE-9"),
                ("a stand that is not in the config", {"--environment": "staging"}, "/qa-factory:qa-onboarding")):
            flags = {"--task": "QA-1", "--environment": "localhost", "--profile": "api", "--words": "w", "--revision": HEAD}
            flags.update(change)
            done = cli(root, "confirm", *[token for pair in flags.items() for token in pair])
            check_eq(f"K5: {label}: exit 2", done.returncode, 2)
            check_in(f"K5: {label}: the refusal names `{needle}`", needle, done.stderr)
        check_eq("K5: no refusal wrote a line (still two lines) and the registry is still absent",
                 (len((root / "qa-factory" / "artifacts" / "QA-1" / "state" / "stand-confirmations.jsonl")
                      .read_text(encoding="utf-8").splitlines()), registry.exists()), (2, False))
        check_eq("K5: no story folder was created by the refusal", (root / "qa-factory" / "artifacts" / "NOPE-9").exists(), False)
        task_root = root / "qa-factory" / "artifacts" / "QA-1"
        errors = []
        word = SI.task_confirmation(task_root, "localhost", "e2e-ui", errors)
        check_eq("K5: task_confirmation reads the word back (the last valid line of the key)", (word["revision"], errors), (HEAD, []))
        check_eq("K5: and another key has none", SI.task_confirmation(task_root, "preview", "e2e-ui"), None)
        # a line nobody can read is skipped and NAMED; its neighbours stay readable (AE11)
        file = task_root / "state" / "stand-confirmations.jsonl"
        file.write_text(file.read_text(encoding="utf-8") + "this is not json\n"
                        + json.dumps({"schema_version": 1, "at": STAMP, "task": "QA-1", "environment_id": "localhost",
                                      "profile_id": "e2e-ui", "kind": "deployed", "revision": "short", "image": "absent",
                                      "stand_definition_sha": SHA64, "words": "w"}) + "\n", encoding="utf-8")
        errors = []
        word = SI.task_confirmation(task_root, "localhost", "e2e-ui", errors)
        check_eq("K5: two bad lines are skipped, named (with their line numbers), and the last VALID word still answers",
                 (word["revision"], len(errors), "line 3" in errors[0], "line 4" in errors[1]), (HEAD, 2, True, True))
        check_in("K5: a skipped line says it is skipped", "skipped", errors[0])
        other = story(root, "QA-2")
        (other / "state" / "stand-confirmations.jsonl").write_text(file.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
        errors = []
        check_eq("K5: a line written for ANOTHER story is not this story's word (named, skipped)",
                 (SI.task_confirmation(other, "localhost", "e2e-ui", errors), len(errors)), (None, 1))
        file.write_bytes(b"\xff\xfe\x00 not utf-8")
        errors = []
        check_eq("K5: a confirmation file that cannot be read at all is NO word (asked again), with one error line",
                 (SI.task_confirmation(task_root, "localhost", "e2e-ui", errors), len(errors)), (None, 1))
    finally:
        cleanup(root)


def k6_forget() -> None:
    root = project()
    try:
        path = SI.registry_path(root)
        cli(root, "record", "--environment", "localhost", "--profile", "e2e-ui", "--method", "oci_label", "--words", "label")
        check_eq("K6: before forget a way is in force", list(SI.load(root)[0]), [("localhost", "e2e-ui")])
        done = cli(root, "forget", "--environment", "localhost", "--profile", "e2e-ui", "--words", "no, I do not want that any more")
        check_eq("K6: forget exits 0", done.returncode, 0)
        rows = json.loads(path.read_text(encoding="utf-8"))["rows"]
        check_eq("K6: nothing is in force, the history grew by one `withdrawn` row with the words",
                 (SI.load(root)[0], len(rows), rows[-1]["method"], rows[-1]["words"], SI.state(root)["history"]),
                 ({}, 2, "withdrawn", "no, I do not want that any more", 2))
        check_in("K6: it says the factory reads the stand by its defaults again", "by its defaults", done.stdout)
        done = cli(root, "forget", "--environment", "localhost", "--profile", "e2e-ui", "--words", " ")
        check_eq("K6: forget with empty words is refused, nothing written", (done.returncode, len(json.loads(path.read_text(encoding="utf-8"))["rows"])), (2, 2))
        done = cli(root, "forget", "--environment", "nowhere", "--profile", "e2e-ui", "--words", "w")
        check_eq("K6: forget for a stand that is not in the config is refused", done.returncode, 2)
        cli(root, "record", "--environment", "localhost", "--profile", "e2e-ui", "--method", "build_sha_file", "--path", "/x", "--words", "again")
        check_eq("K6 control: a later row after a withdrawal is in force again", SI.load(root)[0][("localhost", "e2e-ui")]["method"], "build_sha_file")
    finally:
        cleanup(root)


def k7_show() -> None:
    root = project()
    try:
        shown = cli(root, "show")
        check_eq("K7: show on a project with no registry exits 0", shown.returncode, 0)
        check_in("K7: and says there is nothing", "0 row(s)", shown.stdout)
        cli(root, "record", "--environment", "localhost", "--profile", "e2e-ui", "--method", "command", "--command",
            "C:/tools/build.exe --print", "--words", "my machine's tool")
        cli(root, "record", "--environment", "preview", "--profile", "api", "--method", "person_confirms", "--words", "I check it")
        path = SI.registry_path(root)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["rows"].append(good("oci_label", environment_id="gone-stand", profile_id="api"))
        data["rows"].append({"method": "teleport"})
        path.write_text(json.dumps(data), encoding="utf-8")
        shown = cli(root, "show")
        check_eq("K7: show exits 0", shown.returncode, 0)
        for needle in ("stand `localhost`", "the command", "stand `preview`", "you check the build yourself",
                       "3 row(s) in all", "not in this project's config: kept, never used",
                       "a place on this machine; a teammate who shares this file needs the same path", "ignored:"):
            check_in(f"K7: show says `{needle}`", needle, shown.stdout)
        only = cli(root, "show", "--environment", "preview")
        check_in("K7: --environment narrows it", "stand `preview`", only.stdout)
        check_not_in("K7: and drops the other stand", "stand `localhost`", only.stdout)
        as_json = json.loads(cli(root, "show", "--json").stdout)
        check_eq("K7: --json carries the rows in force, the history and the problems (the bad row's faults, all named)",
                 (len(as_json["in_force"]), as_json["history"], len(as_json["errors"]) >= 1,
                  all(e.startswith("row 3") for e in as_json["errors"])), (3, 3, True, True))
        check_eq("K7: the absolute path in a `command` row was WARNED about and never refused (it is in force)",
                 ("localhost", "e2e-ui") in SI.load(root)[0], True)
        path.write_text("{ broken", encoding="utf-8")
        shown = cli(root, "show")
        check_eq("K7: a corrupt registry: exit 2", shown.returncode, 2)
        check_in("K7: with the file and the door", "delete the file", shown.stderr)
        check_eq("K7: `validate` of a corrupt file exits 1", cli(root, "validate").returncode, 1)
        path.write_text(json.dumps({"rows": [good("oci_label", source="probe discovered", words=""),
                                             good("person_confirms", source="probe discovered", words="")]}), encoding="utf-8")
        done = cli(root, "validate")
        check_eq("K7: a hand-edited `probe discovered` + person_confirms row: validate exits 1 and names it",
                 (done.returncode, "person_confirms" in done.stdout), (1, True))
        path.write_text(json.dumps({"rows": [good("oci_label")]}), encoding="utf-8")
        check_eq("K7 control: a clean file validates, exit 0", cli(root, "validate").returncode, 0)
        elsewhere = root / "other.json"
        elsewhere.write_text(json.dumps({"rows": [{"method": "x"}]}), encoding="utf-8")
        check_eq("K7: validate --file reads another file", cli(root, "validate", "--file", str(elsewhere)).returncode, 1)
    finally:
        cleanup(root)


def k8_unconfirm() -> None:
    root = project()
    try:
        task_root = story(root)
        registry = SI.registry_path(root)
        args = ("--task", "QA-1", "--environment", "localhost", "--profile", "e2e-ui")
        cli(root, "confirm", *args, "--revision", HEAD, "--words", "deployed, I checked")
        check_eq("K8: a word is there", SI.task_confirmation(task_root, "localhost", "e2e-ui") is not None, True)
        done = cli(root, "unconfirm", *args, "--words", "I was wrong, it is not deployed")
        check_eq("K8: unconfirm exits 0", done.returncode, 0)
        check_eq("K8: task_confirmation returns None (the last line is a withdrawal)",
                 SI.task_confirmation(task_root, "localhost", "e2e-ui"), None)
        check_eq("K8: the registry is untouched (still absent)", registry.exists(), False)
        lines = (task_root / "state" / "stand-confirmations.jsonl").read_text(encoding="utf-8").splitlines()
        check_eq("K8: the withdrawal is one more LINE (history stays), with the person's words",
                 (len(lines), json.loads(lines[1])["kind"], json.loads(lines[1])["words"]), (2, "withdrawn", "I was wrong, it is not deployed"))
        cli(root, "confirm", *args, "--revision", OTHER, "--words", "deployed after all")
        check_eq("K8 control: a later confirm counts again", SI.task_confirmation(task_root, "localhost", "e2e-ui")["revision"], OTHER)
        done = cli(root, "unconfirm", *args, "--words", "")
        check_eq("K8: unconfirm with empty words is refused", done.returncode, 2)
    finally:
        cleanup(root)


def k9_definition_sha() -> None:
    base = {"name": "localhost", "base_url": "http://localhost:8080", "frontend_url": "http://localhost:5173",
            "credentials_by_role": {"default_user": "a"}}
    sha_of = SI.definition_sha
    check_eq("K9: 64 hex characters", len(sha_of(base)), 64)
    check_eq("K9: stable under key order", sha_of(base), sha_of(dict(reversed(list(base.items())))))
    check_eq("K9: stable under the whitespace around a value", sha_of(base), sha_of(dict(base, base_url="  http://localhost:8080 ")))
    check("K9: changes when base_url changes", sha_of(base) != sha_of(dict(base, base_url="http://localhost:9090")))
    check("K9: changes when frontend_url changes (an e2e-ui test targets it)", sha_of(base) != sha_of(dict(base, frontend_url="http://localhost:1")))
    check_eq("K9: UNCHANGED when credentials_by_role changes (a password edit never voids a build decision)",
             sha_of(base), sha_of(dict(base, credentials_by_role={"default_user": "b", "auditor": "c"})))
    check_eq("K9: unchanged by any other field of the stand (bring_up, verified, limits)", sha_of(base), sha_of(dict(base, verified="2026-10-02", bring_up="x")))
    check_eq("K9: a stand with neither URL has a sha too (the empty definition)", len(sha_of({"name": "x"})), 64)
    cfg = {"environments": [base, {"name": "preview", "base_url": "https://p"}]}
    check_eq("K9: definition_sha_for finds the stand by name; an unknown stand is ''",
             (SI.definition_sha_for(cfg, "localhost"), SI.definition_sha_for(cfg, "nowhere")), (sha_of(base), ""))
    check_eq("K9: in_config says what is missing", (SI.in_config({**cfg, "profiles": [{"profile_id": "api"}]}, "localhost", "api"),
                                                    "stand `x`" in SI.in_config(cfg, "x", "api"),
                                                    "profile `p`" in SI.in_config({**cfg, "profiles": []}, "localhost", "p")),
             ("", True, True))


def extras() -> None:
    root = project()
    try:
        cfg = json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8"))
        row = SI.make_row(cfg, "localhost", "e2e-ui", "oci_label", words="line one\r\nline two")
        check_eq("make_row: a row is valid, carries the repo of the profile, the default label, the words whole (CRLF folded)",
                 (SI.row_errors(row, 0), row["repo_id"], row["label"], row["words"]),
                 ([], "testproject1-ui", "org.opencontainers.image.revision", "line one\nline two"))
        try:
            SI.append_row(root, dict(row, method="teleport"))
            raised = False
        except SI.RegistryError:
            raised = True
        check_eq("append_row refuses an invalid row and writes nothing", (raised, SI.registry_path(root).exists()), (True, False))
        check_eq("append_row only_if=False after the re-read writes nothing and says so (the probe's discovered row)",
                 (SI.append_row(root, row, only_if=lambda found: False), SI.registry_path(root).exists()), (None, False))
        check_eq("append_row only_if=True writes", SI.append_row(root, row, only_if=lambda found: ("localhost", "e2e-ui") not in found["in_force"])
                 is not None, True)
        check_eq("and the same only_if now says no: a row is in force", SI.append_row(
            root, row, only_if=lambda found: ("localhost", "e2e-ui") not in found["in_force"]), None)
        check_eq("the file keeps its schema_version and its note", [k for k in json.loads(SI.registry_path(root).read_text(encoding="utf-8"))][:3],
                 ["schema_version", "note", "rows"])
        helped = " ".join(cli(root, "record", "--help").stdout.split())
        check_in("t-345 F4: `record --help` says to write Windows paths of --command with forward slashes", "write paths with forward slashes (C:/x)", helped)
        check_in("t-345 F4: ...and why", "backslashes are consumed by the shell-style split", helped)
        check_in("t-345 F4: the module docstring says it too", "forward slashes (C:/x)", " ".join((SI.__doc__ or "").split()))
        check_eq("registry_rel is the spelling a person reads (FR-37)", SI.registry_rel(), "qa-factory/records/stand-identity.json")
        check_in("method_words speaks in words, from data (FR-13)", "the label org.opencontainers.image.revision of the image", SI.method_words(row))
        check_in("method_words for a command quotes the line", "the command `python3 x.py`", SI.method_words({"method": "command", "argv": ["python3", "x.py"]}))
        check("the vocabulary has the five things the ladder needs, in data", all(k in SI.data() for k in ("methods", "ladder", "limits", "outcomes", "remedy")))
        check_eq("and the default label and path are the ones the compose file and the nginx image use",
                 (SI.default_of("oci_label"), SI.default_of("build_sha_file")),
                 ("org.opencontainers.image.revision", "/usr/share/nginx/html/build-sha.txt"))
    finally:
        cleanup(root)


def n1b_command_line_keeps_a_windows_path() -> None:
    """t-300 N1b (t-336 deviation 8, B-276 a): `--command` is parsed the way the PERSON'S platform spells a command.
    On Windows (`os.name == "nt"`) the split is `posix=False`: `C:\\x\\y.exe --flag` keeps its backslashes; on POSIX it
    is unchanged (a backslash escapes). One key per platform through a shim of `os.name` in the module alone (patching
    the real `os.name` would break pathlib); a third key runs the real CLI on THIS platform."""
    class Os:
        def __init__(self, name):
            self.name = name

        def __getattr__(self, attr):
            return getattr(os, attr)
    real = SI.os
    path_line = r"C:\x\y.exe --flag"
    try:
        SI.os = Os("nt")
        check_eq("N1b nt: `C:\\x\\y.exe --flag` keeps its backslashes", SI.command_argv(path_line), [r"C:\x\y.exe", "--flag"])
        check_eq("N1b nt: forward slashes mean the same thing", SI.command_argv("C:/x/y.exe --flag"), ["C:/x/y.exe", "--flag"])
        check_eq("N1b nt: a quoted path with a space loses its quotes (the split keeps them, a path needs them off)",
                 SI.command_argv('"C:\\Program Files\\t.exe" --a'), [r"C:\Program Files\t.exe", "--a"])
        check_eq("N1b nt: single quotes round a whole word too", SI.command_argv("python 'a b.py'"), ["python", "a b.py"])
        check_eq("N1b nt (t-366 F1): a quoted PART inside a word stays one word, the quotes removed as a shell would",
                 SI.command_argv('tool --name="a b" x'), ["tool", "--name=a b", "x"])
        check_eq("N1b nt (t-366 F1): `--format=\"{{.Id}}\"` (docker's own spelling) is one word",
                 SI.command_argv('docker inspect --format="{{.Id}}" c1'), ["docker", "inspect", "--format={{.Id}}", "c1"])
        check_eq("N1b nt (t-366 F1): a quoted part after a backslash path still keeps the path",
                 SI.command_argv(r'C:\tools\sha.exe --label="x y"'), [r"C:\tools\sha.exe", "--label=x y"])
        check_eq("N1b nt (t-366 F1): a quote inside a word is removed, as on POSIX", SI.command_argv("python -c print('x')"), ["python", "-c", "print(x)"])
        check_eq("N1b nt (t-366 F1): a `#` is no comment", SI.command_argv("tool #1 x"), ["tool", "#1", "x"])
        check_eq("N1b nt (t-366 F1): `\"\"` is one EMPTY word (the row validator refuses it, below)", SI.command_argv('""'), [""])
        try:
            SI.command_argv('python "unclosed')
            refused = False
        except ValueError:
            refused = True
        check_eq("N1b nt: an unbalanced quote is refused (ValueError), as on POSIX", refused, True)
        check_eq("N1b nt: empty line, no words", SI.command_argv(""), [])
        SI.os = Os("posix")
        check_eq("N1b posix: UNCHANGED - a backslash escapes, so the Windows spelling loses it (why Windows is different)",
                 SI.command_argv(path_line), ["C:xy.exe", "--flag"])
        check_eq("N1b posix: quotes group and are removed", SI.command_argv('"a b" c'), ["a b", "c"])
        check_eq("N1b posix: forward slashes mean the same thing", SI.command_argv("C:/x/y.exe --flag"), ["C:/x/y.exe", "--flag"])
        check_eq("N1b posix: a quoted part inside a word (the same as nt)", SI.command_argv('tool --name="a b" x'), ["tool", "--name=a b", "x"])
        check_eq("N1b posix: a `#` is no comment (the same as nt)", SI.command_argv("tool #1 x"), ["tool", "#1", "x"])
    finally:
        SI.os = real
    root = project()
    try:
        done = cli(root, "record", "--environment", "localhost", "--profile", "api", "--method", "command",
                   "--command", path_line, "--words", "run it like this")
        rows = json.loads(SI.registry_path(root).read_text(encoding="utf-8"))["rows"] if SI.registry_path(root).exists() else []
        expected = [r"C:\x\y.exe", "--flag"] if os.name == "nt" else ["C:xy.exe", "--flag"]
        check_eq("N1b: the real CLI on this platform records the command the way this platform spells it",
                 (done.returncode, [r["argv"] for r in rows]), (0, [expected]))
        before = sha(SI.registry_path(root))
        quoted = cli(root, "record", "--environment", "localhost", "--profile", "api", "--method", "command",
                     "--command", 'tool --name="a b" x', "--words", "w")
        check_eq("N1b (t-366 F1): the real CLI keeps a quoted part inside a word as ONE word on every platform",
                 (quoted.returncode, json.loads(SI.registry_path(root).read_text(encoding="utf-8"))["rows"][-1]["argv"]),
                 (0, ["tool", "--name=a b", "x"]))
        after_good = sha(SI.registry_path(root))
        for label, line, needle in (("an unbalanced quote", 'tool "unclosed', "could not be read as a command line"),
                                    ("an empty quoted word", '""', "argv must be a non-empty list of non-empty strings")):
            refused = cli(root, "record", "--environment", "localhost", "--profile", "api", "--method", "command", "--command", line, "--words", "w")
            check_eq(f"N1b (t-366 F1): {label}: a refusal with exit 2, nothing written", (refused.returncode, sha(SI.registry_path(root))), (2, after_good))
            check_in(f"N1b (t-366 F1): {label}: the refusal says what is wrong", needle, refused.stderr)
        check("N1b (t-366 F1): the earlier good row is still there (the refusals wrote nothing)", before != after_good)
    finally:
        cleanup(root)


def fb8_confirm_content_records_kind() -> None:
    root = project()
    try:
        task_root = story(root)
        args = ("--task", "QA-1", "--environment", "localhost", "--profile", "e2e-ui", "--revision", HEAD)
        done = cli(root, "confirm", *args, "--content", SHA64, "--image", DIGEST, "--words", "test as is, it is a build file")
        row = json.loads((task_root / "state" / "stand-confirmations.jsonl").read_text(encoding="utf-8").splitlines()[0])
        check_eq("FB8 (R10): --content records kind content_accepted with the revision, the content, the image and the words whole",
                 (done.returncode, row["kind"], row["revision"], row["content"], row["image"], row["words"], "story_revision" in row),
                 (0, "content_accepted", HEAD, SHA64, DIGEST, "test as is, it is a build file", False))
        check_eq("FB8 (R10): task_confirmation reads it back as the word in force",
                 (SI.task_confirmation(task_root, "localhost", "e2e-ui") or {}).get("kind"), "content_accepted")
        done = cli(root, "confirm", *args, "--content", SHA64, "--words", "again, no image")
        row = json.loads((task_root / "state" / "stand-confirmations.jsonl").read_text(encoding="utf-8").splitlines()[1])
        check_eq("FB8 (R10): without --image the row says `absent`; a plain confirm has no content",
                 (done.returncode, row["image"]), (0, "absent"))
        cli(root, "confirm", *args, "--words", "deployed")
        check_eq("FB8: a plain confirm after it is a `deployed` word with no content key",
                 (lambda r: (r["kind"], "content" in r))(SI.task_confirmation(task_root, "localhost", "e2e-ui")), ("deployed", False))
    finally:
        cleanup(root)


def fb8_confirm_content_refusals() -> None:
    root = project()
    try:
        task_root = story(root)
        base = ("--task", "QA-1", "--environment", "localhost", "--profile", "e2e-ui", "--revision", HEAD)
        for label, extra, needle in (
                ("an empty value", ("--content", "", "--words", "w"), "--content"),
                ("63 hex", ("--content", SHA64[:63], "--words", "w"), "--content"),
                ("65 hex", ("--content", SHA64 + "c", "--words", "w"), "--content"),
                ("upper case", ("--content", SHA64.upper().replace("C", "A"), "--words", "w"), "--content"),
                ("with --story-revision", ("--content", SHA64, "--story-revision", OTHER, "--words", "w"), "--story-revision"),
                ("no words", ("--content", SHA64), "--words")):
            done = cli(root, "confirm", *base, *extra)
            check_eq(f"FB8 (R10): {label}: exit 2", done.returncode, 2)
            check_in(f"FB8 (R10): {label}: the refusal names `{needle}`", needle, done.stderr)
        check_eq("FB8 (R10): no refusal recorded anything",
                 (task_root / "state" / "stand-confirmations.jsonl").exists(), False)
    finally:
        cleanup(root)


def fb8_unconfirm_withdraws_content_word() -> None:
    root = project()
    try:
        task_root = story(root)
        args = ("--task", "QA-1", "--environment", "localhost", "--profile", "e2e-ui")
        cli(root, "confirm", *args, "--revision", HEAD, "--content", SHA64, "--words", "test as is")
        check_eq("FB8 (AR-25): the content word is in force", SI.task_confirmation(task_root, "localhost", "e2e-ui") is not None, True)
        done = cli(root, "unconfirm", *args, "--words", "no, stop")
        check_eq("FB8 (AR-25): unconfirm withdraws it", (done.returncode, SI.task_confirmation(task_root, "localhost", "e2e-ui")), (0, None))
        check_eq("FB8: a row of this kind with no content is not a word at all (a reader never honours it)",
                 SI.confirmation_errors({"schema_version": 1, "at": STAMP, "task": "QA-1", "environment_id": "localhost",
                                         "profile_id": "e2e-ui", "kind": "content_accepted", "revision": HEAD, "image": "absent",
                                         "stand_definition_sha": SHA64, "words": "w"}, "QA-1") != [], True)
    finally:
        cleanup(root)


# --- EP1-41e: the build a device holds, read by the probe, and the word of a person bound to it ---------------------------------
# GENERAL KNOWLEDGE, NOT READ FROM A REAL TOOL: every adb and simctl output here (the forms are those of test_device_stand.py); the
# test proves the READING and the BINDING (the real `Reading.binding`), never a real device (FR-33 stays open).

P1 = "/data/app/~~Zx9==/com.example.app-Q1==/base.apk"
P2 = "/data/app/~~Zx9==/com.example.app-Q1==/split_config.en.apk"
ONE_DEVICE = "List of devices attached\nemulator-5554\tdevice\n\n"
TWO_DEVICES = "List of devices attached\nemulator-5554\tdevice\nR58M12345\tdevice\n\n"
NO_DEVICE = "List of devices attached\n\n"


def dump(version="1.2.3", code="42") -> str:
    return ("Packages:\n  Package [com.example.app] (1a2b3c):\n    userId=10123\n"
            + (f"    versionCode={code} minSdk=24 targetSdk=34\n" if code else "") + (f"    versionName={version}\n" if version else ""))


class Phone:
    """A fake `adb`/`xcrun`: `RUN_TOOL` of device_stand. Each field is what that command prints; a `*_code` is its exit code."""

    def __init__(self, devices=ONE_DEVICE, text=None, pm=f"package:{P1}\n", sha="a" * 64, sha_code=0, dump_code=0):
        self.devices, self.text, self.pm, self.sha, self.sha_code, self.dump_code = devices, dump() if text is None else text, pm, sha, sha_code, dump_code
        self.calls = []

    def __call__(self, argv, timeout):
        said = [str(a) for a in argv]
        self.calls.append(said)
        if "devices" in said or "simctl" in said:
            return 0, self.devices.encode()
        if "pm" in said:
            return 0, self.pm.encode()
        if "sha256sum" in said:
            return self.sha_code, (f"{self.sha}  {said[-1]}\n" if self.sha_code == 0 else "denied").encode()
        if "dumpsys" in said:
            return self.dump_code, self.text.encode()
        raise AssertionError(f"41e: the fake device was asked something it does not know: {said}")


def device_config(surface="android", app_id="com.example.app", url="http://127.0.0.1:4723") -> dict:
    return {"environments": [{"name": "localhost", "base_url": "http://localhost:8080"},
                             {"name": "emulator", "surface": surface, "driver": {"url": url},
                              "device": {"serial_key": "QAF_41E_TEST_SERIAL_NOT_SET"}, "app": {"id": app_id}}],
            "profiles": [{"profile_id": "api"}, {"profile_id": "android"}],
            "implementation_repos": [{"repo_id": "app", "local_path": ".", "execution_profile_id": "android"}]}


def probe(root, cfg, phone, *, environment="emulator", story_stand="emulator", profile="android", platform="linux", task="QA-1") -> dict:
    """One probe run through `runtime_probe.build_identity` (the REAL ladder, the REAL `binding`): the record it prints."""
    import contextlib
    import io
    import types
    import device_stand as DS
    import runtime_probe as R
    task_root = root / "qa-factory" / "artifacts" / task
    task_root.mkdir(parents=True, exist_ok=True)
    ns = types.SimpleNamespace(container="", environment=environment, profile=profile, app_root="/app", timeout=5, no_evidence=True)
    record = {"profile_id": profile, "timestamp": STAMP, "environment_id": environment, "expected_source_revision": HEAD,
              "observed_runtime_identity": "", "evidence_refs": [], "provenance": {"technical_verification": False}, "result": "unknown"}
    DS.RUN_TOOL, DS.WHICH, DS.PLATFORM = phone, (lambda name: "/fake/" + name), platform
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            return R.build_identity(ns, record, root=root, task_root=task_root, checkout=root, expected=HEAD, files=[], has_diff=False,
                                    now=STAMP, cfg=cfg, story_stand=story_stand)
    finally:
        DS.RUN_TOOL = DS.WHICH = DS.PLATFORM = None


def word(root, cfg, record, *, kind="deployed", task="QA-1", environment="emulator", image=True) -> None:
    """The word `deployed` as the driver records it after the question: bound to the image identity of the record asked about."""
    ident = record.get("observed_runtime_identity") or ""
    SI.add_confirmation(root, root / "qa-factory" / "artifacts" / task, task=task, environment_id=environment, profile_id="android",
                        kind=kind, words="yes, it is deployed", revision=HEAD, image=ident if image and ident.startswith("image:") else "",
                        stand_definition_sha=SI.definition_sha_for(cfg, environment))


def full_digest(version="1.2.3", code="42", sha="a" * 64) -> str:
    return "sha256:" + hashlib.sha256(f"com.example.app {version} ({code}) sha256:{sha}".encode("utf-8")).hexdigest()


def ep1_41e_definition_of_a_device_stand() -> None:
    web = {"name": "localhost", "base_url": "http://localhost:8080", "frontend_url": "http://localhost:5173"}
    check_eq("41e: a stand with no `surface` hashes as it did before this node (a literal, so no stored word of a web stand is voided)",
             SI.definition_sha(web), "5439c904c7d16dee1ff5e74cb70d17b08a0b128f3dd93936991d6a19acb03ffa")
    check_eq("41e: ...and so does a stand with neither URL", SI.definition_sha({"name": "x"}),
             "2a545b798dbbe60eea941e2f1165e3ae32c4e9558ad54e8053ca82bc720041fd")
    device = device_config()["environments"][1]
    base = SI.definition_sha(device)
    check_eq("41e: a device stand has a sha, stable under key order and the blanks round a value", (len(base), base),
             (64, SI.definition_sha(dict(reversed(list(dict(device, app={"id": " com.example.app "}).items()))))))
    check("41e: another app id is another definition (a word does not follow the stand to another app)",
          SI.definition_sha(dict(device, app={"id": "com.example.other"})) != base)
    check("41e: another driver server is another definition", SI.definition_sha(dict(device, driver={"url": "http://127.0.0.1:4724"})) != base)
    check("41e: another surface is another definition", SI.definition_sha(dict(device, surface="ios")) != base)
    check_eq("41e: the serial key and the app's other keys are not in it (a device swap is the build's to see, not the definition's)",
             SI.definition_sha(dict(device, device={"serial_key": "OTHER"}, app={"id": "com.example.app", "activity": ".Main"})), base)
    check_eq("41e: a `surface` whose `app` or `driver` is not a block still hashes (the empty value), never raises",
             len(SI.definition_sha(dict(device, app="x", driver=None))), 64)


def ep1_41e_the_device_build_and_the_word() -> None:
    root = project()
    cfg = device_config()
    saved = os.environ.pop("QAF_41E_TEST_SERIAL_NOT_SET", None)
    try:
        first = probe(root, cfg, Phone())
        check_eq("41e: a read build is `unknown` that asks how, and the record says it is a device stand",
                 (first["result"], first.get("asks_person"), first.get("device_stand")), ("unknown", "how", True))
        check_eq("41e: the line a person reads carries the app id, version, code and 12 hex of the file",
                 first.get("observed_device_build"), "com.example.app 1.2.3 (42) sha256:" + "a" * 12)
        # t-599 F-8 (FR-10): the packet of a device question does not contradict itself - no image-label remedy, and an error that
        # says the build WAS read (mutation: drop the `not self.device` of the remedy line in `runtime_probe.finish_unknown`)
        check_eq("t-599 F-8: a device question carries no docker/OCI-label remedy and its error says the build was read",
                 ("remedy" in first, "was read" in first.get("error", ""), "could not be read:" in first.get("error", "")), (False, True, False))
        check_eq("41e: the identity is the digest of the WHOLE value (the hash included)",
                 first["observed_runtime_identity"], "image:" + full_digest())
        check("41e: no limitation when the file was hashed, and no `matched`, no revision from a version",
              "limitation" not in first and "build_sha" not in first and first["result"] != "matched")
        check_eq("41e: the container is empty and no docker rung noted it", (first["container"], first.get("tried", [])), ("", []))
        # the word binds: the SAME build keeps it
        word(root, cfg, first)
        again = probe(root, cfg, Phone())
        check_eq("41e: the same build, the person's word: person_confirmed through the real `binding`, bound to the image",
                 (again["result"], again["observed_runtime_identity"], again["person_confirmation"]["image"]),
                 ("person_confirmed", "image:" + full_digest(), "image:" + full_digest()))
        check("41e: ...and nothing is voided", "voided" not in again)
        # REINSTALL with the SAME version and code, another file: the word is voided (the promise of the question)
        rebuilt = probe(root, cfg, Phone(sha="b" * 64))
        check_eq("41e: a reinstall with an UNCHANGED version and another file voids the word (voided.image) and asks again",
                 (rebuilt["result"], rebuilt.get("asks_person"), rebuilt["voided"]["what"], "person_confirmation" in rebuilt),
                 ("unknown", "how", SI.data()["voided"]["image"], False))
        check_eq("41e: ...the new build has another identity", rebuilt["observed_runtime_identity"], "image:" + full_digest(sha="b" * 64))
        # a new version and a new code void it too
        for label, phone in (("a new version", Phone(text=dump(version="1.2.4"))), ("a new code", Phone(text=dump(code="43")))):
            check_eq(f"41e: {label} voids the word", probe(root, cfg, phone)["voided"]["what"], SI.data()["voided"]["image"])
        # two files: ONE of them rebuilt voids it; both hashed in the identity
        two = f"package:{P1}\npackage:{P2}\n"
        both = probe(root, cfg, Phone(pm=two))
        check_eq("41e: two `package:` lines are two hashes in the line", both["observed_device_build"],
                 "com.example.app 1.2.3 (42) sha256:" + "a" * 12 + "," + "a" * 12)
        # the hash cannot be read: the version line stays, the limitation says what is not seen, the word of a HASHED build is voided
        blind = probe(root, cfg, Phone(sha_code=1))
        check_eq("41e: hash unreadable: the version line is kept, the limitation is the record's, the question is asked",
                 (blind["result"], blind.get("asks_person"), blind["observed_device_build"], blind["limitation"]),
                 ("unknown", "how", "com.example.app 1.2.3 (42)", "the installed file was not hashed, so a rebuild with the same version is not seen"))
        check_eq("41e: hash readable then unreadable voids the word (the safe side)", blind["voided"]["what"], SI.data()["voided"]["image"])
        check_eq("41e: ...the identity is the digest of the version line alone", blind["observed_runtime_identity"],
                 "image:sha256:" + hashlib.sha256(b"com.example.app 1.2.3 (42)").hexdigest())
        word(root, cfg, blind)
        check_eq("41e: a word given on the unhashed build holds while it is unhashed",
                 probe(root, cfg, Phone(sha_code=1))["result"], "person_confirmed")
        check_eq("41e: ...and unhashed then hashed voids it", probe(root, cfg, Phone())["voided"]["what"], SI.data()["voided"]["image"])
        # a `matched` is out of reach of a version, even one that LOOKS like a commit
        looks = probe(root, cfg, Phone(text=dump(version=HEAD)))
        check_eq("41e: a version of 40 hex is not a revision: unknown, no build_sha, asks how",
                 (looks["result"], looks.get("asks_person"), "build_sha" in looks), ("unknown", "how", False))
        # multi-line output: the first match
        multi = probe(root, cfg, Phone(text=dump() + "  Package [other]:\n    versionCode=7\n    versionName=9.9\n"))
        check_eq("41e: several blocks: the first match", multi["observed_device_build"], "com.example.app 1.2.3 (42) sha256:" + "a" * 12)
    finally:
        if saved is not None:
            os.environ["QAF_41E_TEST_SERIAL_NOT_SET"] = saved
        cleanup(root)


def ep1_41e_an_unreadable_build_never_takes_a_word() -> None:
    root = project()
    cfg = device_config()
    try:
        asked = probe(root, cfg, Phone())
        word(root, cfg, asked)                                      # a word with the image
        word(root, cfg, dict(asked, observed_runtime_identity=""))  # the LAST word names no image (`absent`): it would pass `binding`
        check_eq("41e control: the last word, on a build that is read, holds",
                 probe(root, cfg, Phone())["result"], "person_confirmed")
        for label, phone in (("the package tool fails", Phone(dump_code=1)),
                             ("the app is not installed", Phone(text="Unable to find package: com.example.app\n")),
                             ("the tool prints nothing", Phone(text="")),
                             ("no version in the output (a code only)", Phone(text=dump(version=""))),
                             ("no device", Phone(devices=NO_DEVICE)),
                             ("two devices and none named", Phone(devices=TWO_DEVICES))):
            got = probe(root, cfg, phone)
            check_eq(f"41e: {label}: unknown, no question, no word taken (not even one that names no image), an error that says why",
                     (got["result"], "asks_person" in got, "person_confirmation" in got, bool(got.get("error"))),
                     ("unknown", False, False, True))
        check_in("41e: ...the error is the line of the reading (the app, not a guess)", "com.example.app is not installed",
                 probe(root, cfg, Phone(text="Unable to find package: com.example.app\n"))["error"])
        check_eq("41e: no_device is told as such", "no device is connected" in probe(root, cfg, Phone(devices=NO_DEVICE))["error"], True)
        # a broken table is an error, not a crash and not a question
        import device_stand
        real = device_stand.installed_build
        device_stand.installed_build = lambda *a, **k: (_ for _ in ()).throw(ValueError("surfaces.json cannot be read"))
        try:
            broken = probe(root, cfg, Phone())
        finally:
            device_stand.installed_build = real
        check_eq("41e: a table that cannot be read stops the probe with its line (no raise, no question)",
                 (broken["result"], "asks_person" in broken, "cannot be read" in broken["error"]), ("unknown", False, True))
        # no_method: iOS reads no build, the question is asked as before, a word binds to no image
        ios = device_config(surface="ios")
        booted = "== Devices ==\n-- iOS 17.0 --\n    iPhone 15 (" + "A" * 8 + "-" + "B" * 4 + "-" + "C" * 4 + "-" + "D" * 4 + "-" + "E" * 12 + ") (Booted)\n"
        sim = probe(root, ios, Phone(devices=booted), platform="darwin")
        check_eq("41e: no_method (iOS): unknown that asks how, no build line, no identity", (sim["result"], sim.get("asks_person"), sim.get("device_stand"),
                 "observed_device_build" in sim, sim["observed_runtime_identity"]), ("unknown", "how", True, False, ""))
        word(root, ios, sim)
        held = probe(root, ios, Phone(devices=booted), platform="darwin")
        check_eq("41e: ...the word then holds with no image (`person-confirmed:`), as the line `person_confirmed_no_image` says",
                 (held["result"], held["observed_runtime_identity"].startswith("person-confirmed:")), ("person_confirmed", True))
        check_eq("41e: iOS on a host that is not darwin is a stop with the reason, not a question",
                 "asks_person" in probe(root, ios, Phone(devices=booted), platform="linux"), False)
    finally:
        cleanup(root)


def ep1_41e_stands_words_and_doors() -> None:
    root = project()
    cfg = device_config()
    try:
        first = probe(root, cfg, Phone())
        word(root, cfg, first)
        check_eq("41e: a word of ANOTHER story is not taken (asked again)",
                 probe(root, cfg, Phone(), task="QA-2")["result"], "unknown")
        other = root / "qa-factory" / "artifacts" / "QA-2" / "state"
        other.mkdir(parents=True, exist_ok=True)
        (other / "stand-confirmations.jsonl").write_text(
            (root / "qa-factory" / "artifacts" / "QA-1" / "state" / "stand-confirmations.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        check_eq("41e: ...even a copy of it in the other story's file (the line names the story that gave it)",
                 probe(root, cfg, Phone(), task="QA-2")["result"], "unknown")
        # the stand's definition moved: the word is voided for that reason first
        moved = probe(root, device_config(app_id="com.example.other"), Phone())
        check_eq("41e: another app id on the stand voids the word (voided.definition)", moved["voided"]["what"], SI.data()["voided"]["definition"])
        moved = probe(root, device_config(url="http://127.0.0.1:4724"), Phone())
        check_eq("41e: another driver server voids it too", moved["voided"]["what"], SI.data()["voided"]["definition"])
        # a mixed project: the story stands on the API stand, this probe reads the device
        mixed = probe(root, cfg, Phone(), environment="emulator", story_stand="localhost")
        check_eq("41e: mixed: `--environment` names the device, the story's stand is the API one: the device is read, under the device's name, "
                 "and the word given for the device stand holds there",
                 (mixed.get("device_stand"), mixed["environment_id"], mixed["result"], mixed.get("voided")),
                 (True, "emulator", "person_confirmed", None))
        web = probe(root, cfg, Phone(), environment="localhost", story_stand="localhost", profile="api")
        check_eq("41e: control: an API stand is read the old way (no device read, the no-container note stays)",
                 ("device_stand" in web, [t["method"] for t in web.get("tried", [])]), (False, ["docker"]))
        # `command` stays the door of a project whose build knows its commit: the row reads it, a version never does
        script = root / "sha.py"
        script.write_text(f"print('{HEAD}')\n", encoding="utf-8")
        SI.append_row(root, SI.make_row(cfg, "emulator", "android", "command", words="the build prints it", argv=[sys.executable, str(script)]))
        door = probe(root, cfg, Phone())
        check_eq("41e: a `command` row of the stand reads the commit: matched, the identity is the device's digest",
                 (door["result"], door["observed_runtime_identity"]), ("matched", "image:" + full_digest()))
        # AT the 12-hex of the line: the whole hash is what is compared
        check("41e: the 12 hex of the line are not what the digest is taken of (two hashes sharing 12 hex are two builds)",
              probe(root, cfg, Phone(sha="a" * 12 + "0" * 52), ).get("observed_runtime_identity") != "image:" + full_digest())
    finally:
        cleanup(root)


def pc9b_a_reference_stand_is_not_asked() -> None:
    """t-2181 PC-9b (AR-4, AR-11): a stand that runs the OLD version of a side of the story is never asked for its build identity - the
    implicit stand pick skips it, the probe of a named reference stand compares nothing (`not_applicable`, `no_changed_file`) - while
    the story's own stand is still asked, and a story with no reference reads exactly as before."""
    import argparse
    import runtime_probe as rp
    from harness import use_project
    root = temp_project("qa-pc9b-")
    try:
        use_project(root)
        task = root / "qa-factory" / "artifacts" / "PC-1"
        task.mkdir(parents=True)

        def story(pipeline):
            (task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        cfg = {"environments": [{"name": "dev"}, {"name": "old"}], "profiles": []}
        story({"ticket": "PC-1", "environment": "dev",
               "sides": {"ui": {"reality": "real", "deliverable": True, "reference": "old", "source": "person"}}})
        check_eq("the story's record names the reference stand and its side", SI.reference_stands(root, "PC-1"), {"old": "ui"})
        check_eq("no story named: the registry alone, which holds no row here", SI.reference_stands(root, ""), {})
        check("without the skip two stands cannot be told apart (the refusal as it was)", rp.pick_environment(cfg, "")[1] != "")
        check_eq("the implicit pick skips the reference stand and returns the story's own", rp.pick_environment(cfg, "", "", {"old": "ui"}), ("dev", ""))
        check_eq("a stand the caller NAMES is returned as named, reference or not", (rp.pick_environment(cfg, "old", "", {"old": "ui"}),
                 rp.pick_environment(cfg, "dev", "", {"old": "ui"})), (("old", ""), ("dev", "")))

        def ns(env):
            return argparse.Namespace(environment=env, profile="api", container="", checkout="")
        got = rp.reference_skip(ns("old"), task)
        check("the probe of the reference stand compares nothing: not_applicable with the code every gate already passes",
              got.get("result") == "not_applicable" and got.get("reason_code") == rp.NO_CHANGED_FILE and got.get("environment_id") == "old", str(got))
        check_eq("the story's OWN stand is still asked (no skip record)", rp.reference_skip(ns("dev"), task), {})
        check_eq("no stand named: nothing to skip", rp.reference_skip(ns(""), task), {})
        story({"ticket": "PC-1", "environment": "old",
               "sides": {"ui": {"reality": "real", "deliverable": True, "reference": "old", "source": "person"}}})
        check_eq("a stand that is both the story's own and a reference is asked (the safe direction)", rp.reference_skip(ns("old"), task), {})
        story({"ticket": "PC-1", "environment": "dev"})
        check_eq("a story with no reference: nothing is skipped, the pick is as before",
                 (rp.reference_skip(ns("old"), task), rp.pick_environment(cfg, "", "", SI.reference_stands(root, "PC-1"))[0]), ({}, ""))
        (task / "pipeline.json").write_text("{not json", encoding="utf-8")
        check_eq("an unreadable record reads no reference (ask more, never refuse on it)", SI.reference_stands(root, "PC-1"), {})
    finally:
        cleanup(root)


def main() -> None:
    if len(sys.argv) >= 4 and sys.argv[1] == "--worker":
        sys.exit(worker(sys.argv[2], sys.argv[3]))
    pc9b_a_reference_stand_is_not_asked()
    fb8_confirm_content_records_kind()
    fb8_confirm_content_refusals()
    fb8_unconfirm_withdraws_content_word()
    k1_validate()
    k2_load()
    k3_cli_record()
    k3_f3_a_registry_of_another_version_is_never_rewritten()
    k4_the_writer_waits_for_the_lock()
    k5_confirm()
    k6_forget()
    k7_show()
    k8_unconfirm()
    k9_definition_sha()
    ep1_41e_definition_of_a_device_stand()
    ep1_41e_the_device_build_and_the_word()
    ep1_41e_an_unreadable_build_never_takes_a_word()
    ep1_41e_stands_words_and_doors()
    extras()
    n1b_command_line_keeps_a_windows_path()
    finish("test_stand_identity")


if __name__ == "__main__":
    main()
