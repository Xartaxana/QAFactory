"""P4: the stand's probe is the project's, so onboarding writes it — not a dispatch.

`execution.runtime_probes.<profile>` is what `run_suite.py --mine` needs on a story's first
typed run. On TP1-13797 nothing wrote it: the automator of run 1 wrote a probe by hand
inside its dispatch, the automator of run 3 could not, and the first typed run was refused three
times. This holds the derivation instead: everything from the project's own config, one question
for the person (which container), and the entry verified once at onboarding time.

t-300 N1a: and THE LADDER (K10-K26): the probe reads the build a stand runs by sources, the OCI label of the image, a
file, a command a person recorded, or the person's word for the story - and says `unknown` rather than guess. Docker is a
fake command runner in every in-process case (S9: this module replaces `run_command` and `sha_container` at import with
functions that RAISE, so a test that forgets its stand fails loudly instead of asking a real docker).

Mutations this file kills (each by this file alone, on a scratch copy of the package):
  the membership check removed (K11) | the discovered write ignores --no-evidence (K10) | the person_confirms
  short-circuit removed (K13) | a plain `deployed` lifts `mismatched` (K14) | rehearsal_argv appends to a foreign argv (K25)
  (t-345) 126/127 sent to `down()` (F2) | rehearsal_argv reads argv[1] only (F7) | a non-sha value at a default rung ends the ladder (F8)
"""
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_dir, temp_project, use_project)

import runtime_probe as R  # noqa: E402
import stand_identity as SI  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1]


def _no_docker(*_args, **_kwargs):
    raise AssertionError("S9: this test reached the real run_command / sha_container - install a Stand")


REAL_SHA_CONTAINER = R.sha_container      # kept for the one test that drives the real function over a fake subprocess.run
R.run_command, R.sha_container = _no_docker, _no_docker

HEAD = "0cc6c4f1" + "a" * 32          # a full 40-hex sha, the shape of a real checkout HEAD
OTHER = "d" * 40                      # another 40-hex sha, the shape of a build that is not HEAD
DIGEST = "sha256:" + "b" * 64          # the shape `docker inspect --format '{{.Image}}'` prints
IDENT = "image:" + DIGEST              # what the record carries as the identity
DIGEST2 = "sha256:" + "e" * 64
LABEL = "org.opencontainers.image.revision"
BUILD_FILE = "/usr/share/nginx/html/build-sha.txt"
# The remedy this module printed before t-300: the Dockerfile lines. Kept here ONLY as the negative control of K17.
OLD_REMEDY = ("to let the probe read the git sha of this build, add to the image's Dockerfile `ARG GIT_SHA=unknown`, and after "
              "the build step `RUN printf '%s\\n' \"$GIT_SHA\" > dist/build-sha.txt`, and to its compose service `build: args: "
              "GIT_SHA: ${UI_GIT_SHA:-unknown}`; then build with UI_GIT_SHA=$(git -C <the checkout> rev-parse HEAD)")


class Stand:
    """A fake docker (and git passthrough) for ONE probe run: it replaces `run_command` and `sha_container` and records
    every call. An answer is `(code, stdout, stderr)`, or an exception to raise (a docker that is not there, a timeout)."""

    def __init__(self, *, app=False, digest=DIGEST, labels=None, files=None, commands=None, sha=None):
        self.app, self.digest, self.labels = app, digest, labels
        self.files, self.commands, self.sha = dict(files or {}), dict(commands or {}), sha
        self.calls, self.sha_calls, self._held = [], [], None

    @staticmethod
    def _answer(value):
        if isinstance(value, BaseException):
            raise value
        return value

    def run(self, argv, timeout):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        if argv[0] == "git":
            done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
            return done.returncode, done.stdout, done.stderr
        if argv[:2] == ["docker", "inspect"]:
            value = self.digest
            return self._answer(value if not isinstance(value, str) else (0, value + "\n", ""))
        if argv[:3] == ["docker", "image", "inspect"]:
            value = self.labels
            if isinstance(value, dict):
                return 0, json.dumps(value) + "\n", ""
            return self._answer((0, "null\n", "") if value is None else value)
        if argv[:2] == ["docker", "exec"] and argv[3:5] == ["test", "-d"]:
            value = self.app
            return self._answer((0, "", "") if value is True else (1, "", "") if value is False else value)
        if argv[:2] == ["docker", "exec"] and argv[3] == "cat":
            return self._answer(self.files.get(argv[4], (1, "", f"cat: {argv[4]}: No such file or directory")))
        if tuple(argv) in self.commands:
            return self._answer(self.commands[tuple(argv)])
        raise AssertionError(f"S9: the fake stand was asked something it does not know: {argv}")

    def sha_container(self, container, path, timeout):
        self.sha_calls.append((container, path))
        if self.sha is None:
            raise RuntimeError(f"docker exec {container} sha256sum {path}: No such file or directory")
        return self.sha(container, path)

    def docker(self) -> list:
        """The docker calls only, as short words: ['test -d', 'inspect', 'image inspect', 'cat <path>']."""
        short = []
        for argv in self.calls:
            if argv[0] != "docker":
                continue
            short.append("image inspect" if argv[1] == "image" else "inspect" if argv[1] == "inspect"
                         else "test -d" if argv[3] == "test" else f"cat {argv[4]}" if argv[3] == "cat" else " ".join(argv[1:4]))
        return short

    def __enter__(self):
        self._held = (R.run_command, R.sha_container)
        R.run_command, R.sha_container = self.run, self.sha_container
        return self

    def __exit__(self, *_exc):
        R.run_command, R.sha_container = self._held


def make_repo(path: Path) -> tuple:
    """A git checkout with two commits of src/Page.vue: (the first sha, the second sha = HEAD)."""
    (path / "src").mkdir(parents=True, exist_ok=True)

    def git(*args):
        done = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                               "-C", str(path), *args], capture_output=True, text=True, encoding="utf-8")
        return done.stdout.strip()
    git("init", "-q")
    shas = []
    for body in ("one\n", "two\n"):
        (path / "src" / "Page.vue").write_text(body, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", f"commit {body.strip()}")
        shas.append(git("rev-parse", "HEAD"))
    return shas[0], shas[1]


class World:
    """A throwaway project (two stands, two test profiles), a story QA-1 with an implementation diff, and a checkout."""

    def __init__(self, diff="+++ b/src/Page.vue\n", pipeline=None, config=None, git=False):
        self.root = temp_project().resolve()
        self.cfg_path = self.root / "qa-factory" / "config.json"
        self.cfg = json.loads(self.cfg_path.read_text(encoding="utf-8"))
        self.cfg["environments"] = [{"name": "localhost", "base_url": "http://localhost:8080", "frontend_url": "http://localhost:5173"},
                                    {"name": "preview", "base_url": "https://preview.example.invalid/api"}]
        self.cfg["profiles"] = [{"profile_id": "api"}, {"profile_id": "e2e-ui"}]
        self.cfg["implementation_repos"] = [{"repo_id": "testproject1-ui", "local_path": "ui", "execution_profile_id": "e2e-ui"}]
        if config:
            config(self.cfg)
        self.save_config()
        self.task = self.root / "qa-factory" / "artifacts" / "QA-1"
        (self.task / "work").mkdir(parents=True)
        if diff is not None:
            (self.task / "work" / "impl-diff.txt").write_text(diff, encoding="utf-8")
        if pipeline is not None:
            (self.task / "pipeline.json").write_text(json.dumps(pipeline), encoding="utf-8")
        self.ui = self.root / "ui"
        (self.ui / "src").mkdir(parents=True)
        (self.ui / "src" / "Page.vue").write_text("one\n", encoding="utf-8")
        self.commits = make_repo(self.ui) if git else (None, None)
        use_project(self.root)
        self.registry = SI.registry_path(self.root)

    def save_config(self) -> None:
        self.cfg_path.write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")

    def probe(self, stand, *extra, profile="e2e-ui", environment="localhost", container="ui-c", expected=HEAD) -> tuple:
        """`runtime_probe.main()` as every caller reaches it: (exit code, the record, stderr). The record's evidence and the
        registry are read from the folder by the caller."""
        argv = ["runtime_probe.py", "--profile", profile, "--environment", environment, "--checkout", str(self.ui),
                "--task-root", str(self.task), *extra]
        if container:
            argv += ["--container", container]
        if expected:
            argv += ["--expected", expected]
        out, err, old = io.StringIO(), io.StringIO(), sys.argv
        sys.argv = argv
        try:
            with stand, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = R.main()
        finally:
            sys.argv = old
        return code, json.loads(out.getvalue()), err.getvalue()

    def rows(self) -> list:
        return json.loads(self.registry.read_text(encoding="utf-8"))["rows"] if self.registry.is_file() else []

    def row(self, method, *, environment="localhost", profile="e2e-ui", words="my way", **kw):
        return SI.append_row(self.root, SI.make_row(self.cfg, environment, profile, method, words=words, **kw))

    def confirm(self, kind="deployed", revision=HEAD, story_revision="", image="", words="yes, it is deployed",
                environment="localhost", profile="e2e-ui", definition=None, content=""):
        return SI.add_confirmation(self.root, self.task, task="QA-1", environment_id=environment, profile_id=profile, kind=kind,
                                   words=words, revision=revision, story_revision=story_revision, image=image, content=content,
                                   stand_definition_sha=definition if definition is not None else SI.definition_sha_for(self.cfg, environment))

    def evidence(self) -> list:
        return sorted((self.task / "evidence").glob("runtime-provenance-*.json")) if (self.task / "evidence").exists() else []

    def close(self) -> None:
        cleanup(self.root)


def main() -> int:
    root = temp_project()
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "localhost", "base_url": "http://localhost:8080"}]
        cfg["implementation_repos"] = [{"repo_id": "app", "local_path": "../app"}]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        # --- the derivation, without touching docker -------------------------------------
        spec, refusal = R.suggest(cfg, root, "api", "", "app-1", "", "/app", SCRIPTS)
        check_eq("with the container named there is nothing left to ask", refusal, "")
        check_in("the stand comes from environments[]", "localhost", spec["argv"])
        check_in("the checkout comes from implementation_repos[]", "../app", spec["argv"])
        check("the probe it names is this script", any(
            str(a).endswith("runtime_probe.py") for a in spec["argv"]))
        check("and the spec carries what run_suite reads",
              set(spec) == {"argv", "cwd", "timeout_s"})

        two = dict(cfg, environments=[{"name": "localhost"}, {"name": "qa"}])
        spec_two, refusal_two = R.suggest(two, root, "api", "", "app-1", "", "/app", SCRIPTS)
        check("two stands and no --environment is a question, not a guess", spec_two is None)
        check_in("and it names them", "localhost, qa", refusal_two)

        many = dict(cfg, implementation_repos=[{"repo_id": "app", "local_path": "../app"},
                                               {"repo_id": "sdk", "local_path": "../sdk"}])
        spec_many, refusal_many = R.suggest(many, root, "api", "localhost", "app-1", "", "/app",
                                            SCRIPTS)
        check("two repositories and no --checkout is a question too", spec_many is None)
        check_in("and it names them", "app, sdk", refusal_many)

        # --- the CLI: print, then write, then refuse to overwrite -------------------------
        shown = run_script("runtime_probe.py", "--suggest", "--profile", "api",
                           "--container", "app-1", cwd=root)
        check_eq("--suggest alone prints and exits 0", shown.returncode, 0)
        check_in("it prints the entry under its own key", '"runtime_probes"', shown.stdout)
        check_in("and says where to put it", "--write", shown.stderr)
        check("printing changes nothing",
              not (json.loads(cfg_path.read_text(encoding="utf-8")).get("execution")
                   or {}).get("runtime_probes"))

        written = run_script("runtime_probe.py", "--suggest", "--profile", "api",
                            "--container", "app-1", "--write", cwd=root)
        check_eq("--write stores it", written.returncode, 0)
        stored = ((json.loads(cfg_path.read_text(encoding="utf-8")).get("execution")
                   or {}).get("runtime_probes") or {}).get("api") or {}
        check("the entry is in the project's config", bool(stored.get("argv")))
        check_in("and it is verified once, at onboarding time", "probe check", written.stderr)
        check_in("the note says the tokens are resolved where the probe runs", "{plugin_root}",
                 stored.get("note", ""))
        check_eq("W5: the stored argv opens with the PORTABLE head, never this machine's python or plugin path",
                 stored["argv"][:2], ["{python}", "{plugin_root}/scripts/runtime_probe.py"])
        check_not_in("W5: nothing of this machine is in the stored entry", sys.executable, json.dumps(stored))
        check_not_in("W5: nor the plugin location", str(SCRIPTS), json.dumps(stored))

        again = run_script("runtime_probe.py", "--suggest", "--profile", "api",
                          "--container", "other-1", "--write", cwd=root)
        check_eq("an entry that exists is the project's own, not discovery's", again.returncode, 2)
        check_in("and the refusal names the way through", "--force", again.stderr)
        forced = run_script("runtime_probe.py", "--suggest", "--profile", "api",
                           "--container", "other-1", "--write", "--force", cwd=root)
        check_eq("--force replaces it", forced.returncode, 0)
        check_in("with the container the person named", "other-1", json.dumps(
            ((json.loads(cfg_path.read_text(encoding="utf-8")).get("execution")
              or {}).get("runtime_probes") or {}).get("api")))

        # --- the probe itself refuses as an instruction ----------------------------------
        bare = run_script("runtime_probe.py", "--profile", "api", cwd=root)
        check_eq("a probe with no story and no task refuses", bare.returncode, 2)
        check_in("and names what to pass", "--task", bare.stderr)
        check("it does not raise", "Traceback" not in (bare.stdout + bare.stderr))
    finally:
        cleanup(root)
    keyed_by_the_profile()
    the_probe_writes_no_evidence_when_told_not_to()
    the_container_is_a_candidate_only_when_it_holds_every_file()
    the_write_check_compares_against_the_story_it_is_given()
    refusals_keep_their_two_halves_and_the_checkout_questions_are_pure()
    t238_w1_w4_the_probe_says_what_it_can_say_about_a_story_that_does_not_touch_its_checkout()
    t238_w5_the_config_stores_the_portable_argv_and_the_reader_fills_in_the_machine()
    t279_k_na_the_probe_that_does_not_apply_says_why_in_a_field()
    # t-300 N1a: the ladder (it replaces the K-IMG case of t-279: a container with no sources is read by its label or a file)
    k10_a_label_equal_to_head_is_matched_and_remembered()
    k11_a_commit_of_the_checkout_is_mismatched_and_a_sha_of_nowhere_is_not()
    k12_a_value_that_is_no_commit_is_unknown()
    k13_a_person_confirms_stand_reads_nothing_and_binds_the_word()
    k14_step_5b_the_word_lifts_only_what_it_names()
    k15_a_content_mismatch_is_never_lifted()
    k16_a_command_the_person_gave()
    k17_nothing_answered_is_unknown_and_a_question()
    k18_sources_outrank_a_stale_label()
    k19_no_diff_and_a_diff_that_touches_nothing()
    k20_docker_that_does_not_answer_is_not_a_question()
    k21_the_story_stand_decides_which_stand_is_read()
    k22_a_corrupt_registry_is_named_and_never_overwritten()
    k23_a_stand_the_config_does_not_name_is_never_written_for()
    k24_no_container_named()
    k25_rehearsal_argv()
    f7_rehearsal_argv_recognises_our_script_in_the_python_dash_b_form()
    f2_the_docker_outcomes_are_classified_by_exit_and_stderr()
    f8_a_value_that_is_no_commit_at_a_default_rung_does_not_end_the_ladder()
    k26_the_onboarding_verification_is_always_a_rehearsal()
    ep1_24_b2_the_check_after_the_write_is_bounded_and_never_a_trace()
    the_registry_rows_the_probe_tries_first()
    the_discovered_row_is_written_only_where_nobody_said_anything()
    t298_k_c1_portable_checkout_table()
    t319_k6_portable_checkout_folds_two_spellings_of_one_place()
    t298_k_c2_the_cli_stores_what_it_prints_portable()
    t298_k_c3_a_portable_probe_survives_the_migration()
    fb8_makefile_absent_others_equal_is_matched()
    fb8_makefile_present_different_is_content_mismatch()
    fb8_makefile_present_equal_counts()
    fb8_only_non_runtime_absent_goes_next()
    fb8_non_runtime_present_proves_folder()
    fb8_added_non_runtime_absent_is_no_difference()
    fb8_unknown_name_stays_runtime()
    fb8_config_also_except_and_malformed()
    fb8_data_block_absent_is_today()
    fb8_candidates_runtime_only_and_cfg()
    fb8_candidates_say_the_readers_problems()
    fb8_mismatched_record_carries_identity_and_image()
    fb8_content_word_lifts_only_its_bytes()
    fb8_content_word_never_lifts_unknown_or_sha_mismatch()
    return finish("test_runtime_probe_onboarding")


# --- t-218: the gate rehearsal derives a probe in memory and must not write anything -------------------

# --- FB-8 N1: files that are not part of the running application ---------------------------------------------

def fb8_world(diff: str, local=(), config=None) -> World:
    w = World(diff=diff, config=config)
    for name in local:
        (w.ui / name).parent.mkdir(parents=True, exist_ok=True)
        (w.ui / name).write_text(f"local {name}\n", encoding="utf-8")
    return w


def fb8_stand(w: World, absent=(), differ=(), labels=None) -> Stand:
    """A container whose files equal the checkout's, except those named: `absent` ones are not there, `differ` ones hold other bytes."""
    def sha(container, path):
        rel = path.split("/app/", 1)[1]
        if rel in absent:
            raise RuntimeError(f"docker exec {container} sha256sum {path}: No such file or directory")
        return "f" * 64 if rel in differ else R.sha_local(w.ui / rel)
    return Stand(app=True, labels=labels, sha=sha)


def fb8_makefile_absent_others_equal_is_matched() -> None:
    w = fb8_world("+++ b/src/Page.vue\n+++ b/src/Other.vue\n+++ b/src/Third.vue\n+++ b/Makefile\n",
                  local=("src/Other.vue", "src/Third.vue", "Makefile"))
    try:
        code, rec, _said = w.probe(fb8_stand(w, absent=("Makefile",)), "--no-evidence")
        check_eq("FB8: three runtime files equal and the Makefile absent from the container: matched, the Makefile recorded",
                 (rec["result"], rec.get("not_shipped_files"), "differing_files" in rec), ("matched", ["Makefile"], False))
        row = [c for c in rec["comparisons"] if c["file"] == "Makefile"][0]
        check_eq("FB8: its comparison row carries the NOT_SHIPPED note and no container sha",
                 (row["note"], row["container_sha256"], bool(row["local_sha256"])), (R.NOT_SHIPPED, None, True))
        check_eq("FB8: the identity names the three compared files only", rec["observed_runtime_identity"].count("|"), 2)
    finally:
        w.close()


def fb8_makefile_present_different_is_content_mismatch() -> None:
    w = fb8_world("+++ b/src/Page.vue\n+++ b/Makefile\n", local=("Makefile",))
    try:
        code, rec, _said = w.probe(fb8_stand(w, differ=("Makefile",)), "--no-evidence")
        check_eq("FB8 (E7): a Makefile the image DOES carry and that differs is compared: content_mismatch naming it",
                 (rec["result"], rec["provenance"]["deployed_source_revision"], rec["differing_files"], "not_shipped_files" in rec),
                 ("mismatched", "content_mismatch", ["Makefile"], False))
    finally:
        w.close()


def fb8_makefile_present_equal_counts() -> None:
    w = fb8_world("+++ b/src/Page.vue\n+++ b/Makefile\n", local=("Makefile",))
    try:
        code, rec, _said = w.probe(fb8_stand(w), "--no-evidence")
        check_eq("FB8 (R6): a present equal Makefile is compared and counted (two compared files, no not-shipped record)",
                 (rec["result"], rec["observed_runtime_identity"].count("|"), "not_shipped_files" in rec), ("matched", 1, False))
    finally:
        w.close()


def fb8_only_non_runtime_absent_goes_next() -> None:
    w = fb8_world("+++ b/Makefile\n", local=("Makefile",))
    try:
        stand = fb8_stand(w, absent=("Makefile",), labels={LABEL: HEAD})
        code, rec, _said = w.probe(stand, "--no-evidence")
        check_eq("FB8 (E8): the story's only compared file is a Makefile the image lacks: the sources could not tell, the label answers "
                 "(not mismatched, not matched by the files)",
                 (rec["result"], rec["provenance"].get("identity_kind"), "differing_files" in rec), ("matched", "oci_label", False))
        check_eq("FB8 (E8): the Makefile is still recorded as not shipped", rec.get("not_shipped_files"), ["Makefile"])
        code, rec, _said = w.probe(fb8_stand(w, absent=("Makefile",)), "--no-evidence")
        tried = " | ".join(t["outcome"] for t in rec.get("tried") or [])
        check_eq("FB8 (E8): with no label either it is `unknown` (never a content_mismatch) and the rung says why, in the data sentence",
                 (rec["result"], R.say("sources.only_non_runtime") in tried), ("unknown", True))
    finally:
        w.close()


def fb8_non_runtime_present_proves_folder() -> None:
    w = fb8_world("+++ b/src/Page.vue\n+++ b/Makefile\n", local=("Makefile",))
    try:
        code, rec, _said = w.probe(fb8_stand(w, absent=("src/Page.vue",)), "--no-evidence")
        check_eq("FB8 (E9): the runtime file is absent but a Makefile is PRESENT: the folder is the app's, the absence is a difference",
                 (rec["result"], rec["differing_files"]), ("mismatched", ["src/Page.vue"]))
    finally:
        w.close()


def fb8_added_non_runtime_absent_is_no_difference() -> None:
    w = fb8_world("--- /dev/null\n+++ b/Makefile\n+++ b/src/Page.vue\n", local=("Makefile",))
    try:
        code, rec, _said = w.probe(fb8_stand(w, absent=("Makefile",)), "--no-evidence")
        check_eq("FB8 (E11): the story ADDS a Makefile the image does not ship: not a difference", (rec["result"], rec.get("not_shipped_files")),
                 ("matched", ["Makefile"]))
        # F2a unchanged for runtime files: every runtime file absent, none added; the added NON-runtime one proves nothing (E10)
        code, rec, _said = w.probe(fb8_stand(w, absent=("Makefile", "src/Page.vue"), labels={LABEL: HEAD}), "--no-evidence")
        check_eq("FB8 (E10/E11): the changed runtime file is absent too and only a Makefile is added: the files could not tell, the label answers",
                 (rec["result"], "differing_files" in rec), ("matched", False))
    finally:
        w.close()


def fb8_unknown_name_stays_runtime() -> None:
    paths = ["Makefile", "src/Makefile.py", "app/Dockerfile.ts", "MAKEFILE", "deploy/Makefile", "Makefile/", "..\\Makefile",
             "src/Ünïcode.vue", "src/Page.vue", "docs/Dockerfile.dev", "LICENSE"]
    found, problems = R.non_runtime_files(paths, {})
    check_eq("FB8 (E24): defaults only; a code file never; the case matters; a folder is not the file; a backslash path is read by its basename",
             sorted(found), sorted(["Makefile", "deploy/Makefile", "..\\Makefile", "docs/Dockerfile.dev", "LICENSE"]))
    check_eq("FB8 (E24): no problem for a plain config", problems, [])
    also, _problems = R.non_runtime_files(["scripts/build.py", "scripts/build.sh", "Taskfile.yml"],
                                          {"execution": {"non_runtime_files": {"also": ["scripts/*", "*.py", "Taskfile.yml"], "except": []}}})
    check_eq("FB8 (F6): `also` never makes a CODE file non-runtime; a path with a slash matches the whole path", sorted(also),
             ["Taskfile.yml", "scripts/build.sh"])


def fb8_config_also_except_and_malformed() -> None:
    def cfg(**word):
        return {"execution": {"non_runtime_files": word}}
    both = ["Makefile", "Taskfile", "deploy/Makefile", "Dockerfile"]
    for label, config, want, bad in (
            ("E1 absent key", {}, ["Dockerfile", "Makefile", "deploy/Makefile"], False),
            ("E1 execution not an object", {"execution": []}, ["Dockerfile", "Makefile", "deploy/Makefile"], False),
            ("E1 null key", {"execution": {"non_runtime_files": None}}, ["Dockerfile", "Makefile", "deploy/Makefile"], False),
            ("E1 empty object", cfg(), ["Dockerfile", "Makefile", "deploy/Makefile"], False),
            ("E1 null lists", cfg(also=None, **{"except": None}), ["Dockerfile", "Makefile", "deploy/Makefile"], False),
            ("also adds", cfg(also=["Taskfile"]), ["Dockerfile", "Makefile", "Taskfile", "deploy/Makefile"], False),
            ("except wins over a default (E5)", cfg(**{"except": ["Dockerfile"]}), ["Makefile", "deploy/Makefile"], False),
            ("except a path spares only that path", cfg(**{"except": ["deploy/Makefile"]}), ["Dockerfile", "Makefile"], False),
            ("same name in also and except is runtime (E6)", cfg(also=["Taskfile"], **{"except": ["Taskfile", "Makefile"]}),
             ["Dockerfile"], False),     # `Makefile` has no slash: it spares every Makefile, deploy/Makefile too
            ("E2 except a string", cfg(**{"except": "Makefile"}), [], True),
            ("E2 except with an empty name", cfg(**{"except": ["Makefile", ""]}), [], True),
            ("E2 except with a number", cfg(**{"except": [1]}), [], True),
            ("E2 the key is a list", {"execution": {"non_runtime_files": ["Makefile"]}}, [], True),
            ("E2 the key is a string", {"execution": {"non_runtime_files": "Makefile"}}, [], True),
            ("E3 also malformed is ignored, defaults stay", cfg(also="Taskfile"), ["Dockerfile", "Makefile", "deploy/Makefile"], True),
            ("E3 also with a blank name is ignored", cfg(also=["  "], **{"except": ["Dockerfile"]}), ["Makefile", "deploy/Makefile"], True)):
        found, problems = R.non_runtime_files(both, config)
        check_eq(f"FB8 {label}: the set", sorted(found), want)
        check_eq(f"FB8 {label}: a problem line {'is' if bad else 'is not'} said", bool(problems), bad)
    # the same word through the probe: a malformed `except` sets nothing aside, says so on stderr and in the record
    w = fb8_world("+++ b/src/Page.vue\n+++ b/Makefile\n", local=("Makefile",),
                  config=lambda c: c.setdefault("execution", {}).__setitem__("non_runtime_files", {"except": "Makefile"}))
    try:
        code, rec, said = w.probe(fb8_stand(w, absent=("Makefile",)), "--no-evidence")
        check_eq("FB8 (E2): a broken `except` is today's behavior (the absent Makefile is a content mismatch) and the record names the problem",
                 (rec["result"], rec["differing_files"], "non_runtime_problem" in rec, "non_runtime_files" in said),
                 ("mismatched", ["Makefile"], True, True))
    finally:
        w.close()
    w = fb8_world("+++ b/src/Page.vue\n+++ b/Dockerfile\n", local=("Dockerfile",),
                  config=lambda c: c.setdefault("execution", {}).__setitem__("non_runtime_files", {"except": ["Dockerfile"]}))
    try:
        code, rec, _said = w.probe(fb8_stand(w, absent=("Dockerfile",)), "--no-evidence")
        check_eq("FB8 (E5): the project says its Dockerfile IS app: absent, it is a difference again",
                 (rec["result"], rec["differing_files"]), ("mismatched", ["Dockerfile"]))
    finally:
        w.close()


def fb8_data_block_absent_is_today() -> None:
    import shutil
    data = json.loads(SI.DATA_PATH.read_text(encoding="utf-8-sig"))
    held_path, held_data = SI.DATA_PATH, dict(SI._DATA)
    scratch = temp_dir()
    w = None
    try:
        for label, mutate in (("absent", lambda d: d.pop("non_runtime_files")),
                              ("malformed", lambda d: d.__setitem__("non_runtime_files", {"patterns": "Makefile"}))):
            copy = dict(data)
            mutate(copy)
            path = Path(scratch) / f"methods-{label}.json"
            path.write_text(json.dumps(copy), encoding="utf-8")
            SI.DATA_PATH = path
            SI._DATA.clear()
            found, problems = R.non_runtime_files(["Makefile"], {})
            check_eq(f"FB8 (E4): the block is {label}: nothing is non-runtime and the problem is said", (found, bool(problems)), (set(), True))
        SI.DATA_PATH = held_path
        SI._DATA.clear()
        w = fb8_world("+++ b/src/Page.vue\n+++ b/Makefile\n", local=("Makefile",))
        path = Path(scratch) / "methods-absent.json"
        SI.DATA_PATH = path
        SI._DATA.clear()
        code, rec, _said = w.probe(fb8_stand(w, absent=("Makefile",)), "--no-evidence")
        check_eq("FB8 (E4): with no block the probe behaves as before the change (absent Makefile = content mismatch)",
                 (rec["result"], rec["differing_files"]), ("mismatched", ["Makefile"]))
    finally:
        SI.DATA_PATH = held_path
        SI._DATA.clear()
        SI._DATA.update(held_data)
        if w:
            w.close()
        shutil.rmtree(scratch, ignore_errors=True)


def fb8_candidates_runtime_only_and_cfg() -> None:
    import types
    root = temp_project()
    try:
        checkout = root / "app"
        (checkout / "src").mkdir(parents=True)
        for name in ("src/a.py", "Makefile", "Dockerfile"):
            (checkout / name).write_text(name, encoding="utf-8")

        def fake_run(argv, **kwargs):
            have = {"app-only": ["src/a.py"], "all": ["src/a.py", "Makefile", "Dockerfile"], "make-only": ["Makefile"],
                    "none": []}[argv[2]]
            shown = [p for p in argv[4:] if p[len("/app/"):] in have]
            return types.SimpleNamespace(returncode=0 if len(shown) == len(argv[4:]) else 1, stderr="",
                                         stdout="".join(f"abc  {p}\n" for p in shown))
        held = R.subprocess
        R.subprocess = types.SimpleNamespace(run=fake_run, TimeoutExpired=held.TimeoutExpired)
        try:
            running = [(n, "img") for n in ("app-only", "all", "make-only", "none")]
            check_eq("FB8 (R8): the Makefile and the Dockerfile are not asked for: a container holding only the app file is a candidate",
                     R.content_candidates(["src/a.py", "Makefile", "Dockerfile"], checkout, "/app", running, cfg={}), ["app-only", "all"])
            check_eq("FB8 (R8/B2): the config's `except` brings the Dockerfile back: a container without it is NOT a candidate",
                     R.content_candidates(["src/a.py", "Makefile", "Dockerfile"], checkout, "/app", running,
                                          cfg={"execution": {"non_runtime_files": {"except": ["Dockerfile"]}}}), ["all"])
            check_eq("FB8 (R8): cfg None reads the project's config, which has no word: the defaults",
                     R.content_candidates(["src/a.py", "Makefile"], checkout, "/app", running), ["app-only", "all"])
            only = ["Makefile", "Dockerfile"]
            check_eq("FB8 (E12): every compared file non-runtime: a container holding ANY of them is a candidate (0 holders: [])",
                     (R.content_candidates(only, checkout, "/app", [running[3]], cfg={}),
                      R.content_candidates(only, checkout, "/app", [running[0], running[2]], cfg={}),
                      R.content_candidates(only, checkout, "/app", [running[1], running[2]], cfg={})),
                     ([], ["make-only"], ["all", "make-only"]))
            check_eq("FB8 (E12): the app-only container holds none of them: no candidate, so no which-container question",
                     R.content_candidates(only, checkout, "/app", [running[0]], cfg={}), [])
        finally:
            R.subprocess = held
    finally:
        cleanup(root)


def fb8_candidates_say_the_readers_problems() -> None:
    """N1 fix after t-1390 (4): `content_candidates` prints the reader's problems to stderr, as `rung_sources` does."""
    root = temp_project()
    try:
        checkout = root / "co"
        (checkout / "src").mkdir(parents=True)
        (checkout / "src" / "a.py").write_text("x\n", encoding="utf-8")
        held = R.subprocess
        R.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="x  /app/src/a.py\n"),
                                             TimeoutExpired=held.TimeoutExpired)
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                R.content_candidates(["src/a.py"], checkout, "/app", [("c1", "i")], cfg={"execution": {"non_runtime_files": 5}})
        finally:
            R.subprocess = held
        check_in("FB8 (t-1390 fix 4): a malformed config word is said on stderr by the gate A pick too", "not an object", err.getvalue())
    finally:
        cleanup(root)


def fb8_identity_of(w: World, container_sha: str = "f" * 64) -> str:
    """The content identity worked out here, independently of the code under test (R9)."""
    rows = [["src/Page.vue", container_sha, R.sha_local(w.ui / "src" / "Page.vue")]]
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def fb8_content_stand(digest=DIGEST, container_sha="f" * 64) -> Stand:
    return Stand(app=True, digest=digest, sha=lambda c, p: container_sha)


NO_IMAGE = (0, "not an image\n", "")       # docker answers, and names no image


def fb8_mismatched_record_carries_identity_and_image() -> None:
    w = World(git=True)
    try:
        c1, c2 = w.commits
        code, rec, _said = w.probe(fb8_content_stand(), "--no-evidence", expected=c2)
        check_eq("FB8 (R9): a content mismatch carries the fingerprint of exactly the bytes compared (worked out apart from the code) "
                 "and the image that held them",
                 (rec["result"], rec.get("content_identity"), rec.get("observed_image")), ("mismatched", fb8_identity_of(w), IDENT))
        code, rec, _said = w.probe(fb8_content_stand(digest=NO_IMAGE), "--no-evidence", expected=c2)
        check_eq("FB8 (E19): docker names no image: the identity is there, `observed_image` is not",
                 (rec["result"], rec.get("content_identity"), "observed_image" in rec), ("mismatched", fb8_identity_of(w), False))
        code, rec, _said = w.probe(fb8_content_stand(container_sha=R.sha_local(w.ui / "src" / "Page.vue")), "--no-evidence", expected=c2)
        check_eq("FB8 (R9): a matched record carries neither", (rec["result"], "content_identity" in rec, "observed_image" in rec),
                 ("matched", False, False))
    finally:
        w.close()


def fb8_content_word_lifts_only_its_bytes() -> None:
    import profile_contract as PC
    w = World(git=True)
    try:
        c1, c2 = w.commits
        ident = fb8_identity_of(w)
        voided = SI.data()["voided"]

        def run(stand=None, expected=c2):
            code, rec, _said = w.probe(stand or fb8_content_stand(), "--no-evidence", expected=expected)
            return rec

        def why(rec):
            return (rec["result"], rec["voided"]["what"]) if "voided" in rec else (rec["result"], None)

        def word(**kw):
            args = dict(kind="content_accepted", revision=c2, content=ident, image=IDENT, words="test as is, it is a build file")
            args.update(kw)
            return w.confirm(**args)
        word()
        rec = run()
        said = rec.get("person_confirmation") or {}
        check_eq("FB8 (R11): the word binds: person_confirmed, the files accepted, the identity is the image, no differing_files",
                 (rec["result"], rec.get("accepted_files"), rec["observed_runtime_identity"], "differing_files" in rec,
                  rec["provenance"]["technical_verification"], rec["provenance"]["identity_kind"]),
                 ("person_confirmed", ["src/Page.vue"], IDENT, False, False, "person_confirmed"))
        check_eq("FB8 (R11): the confirmation says kind, revision, content and image, and the words whole",
                 (said.get("kind"), said.get("revision"), said.get("content"), said.get("image"), said.get("words")),
                 ("content_accepted", c2, ident, IDENT, "test as is, it is a build file"))
        check_eq("FB8 (R12): the lifted record passes the contract (person_confirmed_problems empty, no tested_build)",
                 (PC.person_confirmed_problems(rec), "tested_build" in rec, rec["content_identity"]), ([], False, ident))
        check_eq("FB8 (R12): the same record with another content in the word is refused by the contract",
                 bool(PC.person_confirmed_problems(dict(rec, person_confirmation=dict(said, content="a" * 64)))), True)
        check_eq("FB8 (E17): the stand later `matched`: a reading beats a word, the word is unused",
                 run(fb8_content_stand(container_sha=R.sha_local(w.ui / "src" / "Page.vue")))["result"], "matched")
        check_eq("FB8 (E18, order R11): HEAD moved (the probe expects another commit): voided by the checkout, not by the content",
                 why(run(expected=c1)), ("mismatched", voided["checkout"].format(short=c1[:12])))
        check_eq("FB8 (E18): a container byte moved: voided by the content",
                 why(run(fb8_content_stand(container_sha="c" * 64))), ("mismatched", voided["content"]))
        (w.ui / "src" / "Page.vue").write_text("three\n", encoding="utf-8")
        check_eq("FB8 (E18): a local file moved: voided by the content", why(run()), ("mismatched", voided["content"]))
        (w.ui / "src" / "Page.vue").write_text("two\n", encoding="utf-8")
        check_eq("FB8 (E18): another image: voided by the image",
                 why(run(fb8_content_stand(digest=DIGEST2))), ("mismatched", voided["image"]))
        word(content="a" * 64)
        check_eq("FB8 (E14): a made-up content never binds: voided by the content", why(run()), ("mismatched", voided["content"]))
        word(definition="0" * 64)
        check_eq("FB8 (R11): another stand definition is the first check: voided by the definition",
                 why(run()), ("mismatched", voided["definition"]))
        word(image="")
        rec = run(fb8_content_stand(digest=NO_IMAGE))
        check_eq("FB8 (E19): no image named by docker and none in the word: it binds on definition, commit and content; the identity "
                 "is the person-confirmed one", (rec["result"], rec["observed_runtime_identity"].startswith("person-confirmed:")),
                 ("person_confirmed", True))
        word()
        check_eq("FB8 (R11): the word names an image and docker names none: not lifted (voided, unreadable)",
                 why(run(fb8_content_stand(digest=NO_IMAGE))), ("mismatched", voided["image_unreadable"]))
        w.confirm(revision=c2, image="", words="deployed")
        check_eq("FB8 (K15 extended): a `deployed` word given after the content word is the word in force, and it lifts nothing",
                 why(run()), ("mismatched", None))
        w.confirm(kind="test_deployed", revision=c1, story_revision=c2, image="", words="test what is deployed")
        check_eq("FB8 (K15 extended): neither does a `test_deployed` word", why(run()), ("mismatched", None))
    finally:
        w.close()


def fb8_content_word_never_lifts_unknown_or_sha_mismatch() -> None:
    w = World(git=True)
    try:
        c1, c2 = w.commits
        w.confirm(kind="content_accepted", revision=c2, content="a" * 64, image="", words="test as is")
        code, rec, _said = w.probe(Stand(app=False), "--no-evidence", expected=c2)
        check_eq("FB8 (E16): the reading is `unknown`: the content word is not lifted and NO `voided` is written",
                 (rec["result"], "voided" in rec, rec.get("asks_person")), ("unknown", False, "how"))
        code, rec, _said = w.probe(Stand(app=False, labels={LABEL: c1}), "--no-evidence", expected=c2)
        check_eq("FB8 (E16): the label reads another commit (a sha mismatch): not lifted, no `voided`, no tested_build",
                 (rec["result"], "voided" in rec, "tested_build" in rec), ("mismatched", False, False))
        w.row("person_confirms", words="I check this stand myself")
        code, rec, _said = w.probe(Stand(app=False), "--no-evidence", expected=c2)
        check_eq("FB8 (E16): a `person_confirms` stand with only a content word on record: asks `confirm` plainly, no false `voided`",
                 (rec["result"], rec.get("asks_person"), "voided" in rec), ("unknown", "confirm", False))
    finally:
        w.close()


def keyed_by_the_profile() -> None:
    """cmp2 has two repositories, one per profile (`execution_profile_id`). Counting repositories
    refused both profiles; the repository the profile names is the one its stand runs."""
    cfg = {"environments": [{"name": "localhost"}],
           "implementation_repos": [
               {"repo_id": "backend", "local_path": "../../testproject1", "execution_profile_id": "api"},
               {"repo_id": "ui", "local_path": "../../testproject1-ui", "execution_profile_id": "e2e-ui"}]}
    for profile, path in (("api", "../../testproject1"), ("e2e-ui", "../../testproject1-ui")):
        spec, refusal = R.suggest(cfg, Path("."), profile, "", "c-1", "", "/app", SCRIPTS)
        check_eq(f"{profile}: nothing is asked, the repository naming it is the checkout", refusal, "")
        check_in(f"{profile}: its own checkout is in the probe", path, spec["argv"])
    other = R.pick_checkout(cfg, "unit", "")
    check_eq("a profile no repository names, with two repositories: still the question",
             (other[0], "2 implementation repositories" in other[1]), ("", True))
    check_in("and it names them", "backend, ui", other[1])
    twice = dict(cfg, implementation_repos=[
        {"repo_id": "a", "local_path": "../a", "execution_profile_id": "api"},
        {"repo_id": "b", "local_path": "../b", "execution_profile_id": "api"}])
    refused = R.pick_checkout(twice, "api", "")
    check_eq("two repositories naming one profile are a question too", refused[0], "")
    check_in("which says it is about that profile", "for profile api", refused[1])
    one = dict(cfg, implementation_repos=[{"repo_id": "solo", "local_path": "../solo"}])
    check_eq("one repository that names nothing is still the only one", R.pick_checkout(one, "api", ""),
             ("../solo", ""))
    check_eq("none at all: the app root, as before",
             R.pick_checkout({"app_root": "../x"}, "api", ""), ("../x", ""))
    check_eq("a checkout the caller passes is never second-guessed",
             R.pick_checkout(cfg, "api", "/given"), ("/given", ""))
    check_eq("two stands and no name: the question; a name wins",
             (R.pick_environment({"environments": [{"name": "a"}, {"name": "b"}]}, "")[0],
              R.pick_environment({"environments": [{"name": "a"}, {"name": "b"}]}, "b")),
             ("", ("b", "")))


def the_probe_writes_no_evidence_when_told_not_to() -> None:
    """The rehearsal runs the probe once at gate A and a rehearsal writes nothing (FR-45)."""
    root = temp_project()
    try:
        use_project(root)
        checkout = root / "app"
        (checkout / "src").mkdir(parents=True)
        (checkout / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
        task = root / "story"
        (task / "work").mkdir(parents=True)
        (task / "work" / "impl-diff.txt").write_text("+++ b/src/a.py\n", encoding="utf-8")
        stand = Stand(app=True, sha=lambda container, path: R.sha_local(checkout / "src" / "a.py"))
        argv = ["runtime_probe.py", "--profile", "api", "--environment", "localhost", "--container",
                "c-1", "--checkout", str(checkout), "--expected", "rev-1", "--task-root", str(task)]
        old = sys.argv
        records = {}
        try:
            for label, extra in (("quiet", ["--no-evidence"]), ("loud", [])):
                out = io.StringIO()
                sys.argv = argv + extra
                with stand, contextlib.redirect_stdout(out):
                    code = R.main()
                records[label] = (code, json.loads(out.getvalue()))
                if label == "quiet":   # looked at BEFORE the loud run makes the folder
                    records["quiet_wrote"] = (task / "evidence").exists()
        finally:
            sys.argv = old
        code, quiet = records["quiet"]
        check_eq("--no-evidence: the probe still compares and says matched", (code, quiet["result"]), (0, "matched"))
        check_eq("it names no evidence file", quiet["evidence_refs"], [])
        check_eq("t-300: and SAYS it was observed without one (the marker only a rehearsal reader excuses)",
                 (quiet.get("observed_without_evidence"), "observed_without_evidence" in records["loud"][1]), (True, False))
        check("and none exists: the story's folder has no `evidence/` at all", not records["quiet_wrote"])
        code, loud = records["loud"]
        check_eq("without the flag the probe is what it always was", loud["result"], "matched")
        check_eq("it writes its evidence file", len(list((task / "evidence").glob("runtime-provenance-*.json"))), 1)
        check_eq("and names it", len(loud["evidence_refs"]), 1)
        check_eq("the comparisons are the same either way", quiet["comparisons"], loud["comparisons"])
    finally:
        cleanup(root)


def the_container_is_a_candidate_only_when_it_holds_every_file() -> None:
    """C3: a candidate holds EVERY compared file; none is a fact about the stand, not a question."""
    import types
    root = temp_project()
    try:
        checkout = root / "app"
        (checkout / "src").mkdir(parents=True)
        for name in ("a.py", "b.py"):
            (checkout / "src" / name).write_text(name, encoding="utf-8")
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(list(argv))
            name, paths = argv[2], argv[4:]
            if name == "slow":
                raise R.subprocess.TimeoutExpired(argv, 1)
            if name == "gone":
                raise OSError("no docker")
            have = {"holds-all": paths, "holds-one": paths[:1], "holds-none": [], "extra": paths}[name]
            return types.SimpleNamespace(returncode=0 if len(have) == len(paths) else 1, stderr="",
                                         stdout="".join(f"abc  {p}\n" for p in have))
        held = R.subprocess
        R.subprocess = types.SimpleNamespace(run=fake_run, TimeoutExpired=held.TimeoutExpired)
        try:
            running = [(name, "img") for name in ("holds-all", "holds-one", "holds-none", "slow", "gone", "extra")]
            files = ["src/a.py", "src/b.py", "README.md", "src/not-in-the-checkout.py"]
            found = R.content_candidates(files, checkout, "/app", running)
            check_eq("only a container holding every compared file is a candidate",
                     found, ["holds-all", "extra"])
            check_eq("a document and a file the checkout does not have are never compared",
                     calls[0][4:], ["/app/src/a.py", "/app/src/b.py"])
            check_eq("one `docker exec` per container", len(calls), 6)
            check_eq("AT one candidate, BEYOND at two",
                     (len(R.content_candidates(files, checkout, "/app", running[:2])),
                      len(R.content_candidates(files, checkout, "/app", [running[0], running[5]]))), (1, 2))
            check_eq("a stand serving a built bundle holds no source under the app root: zero",
                     R.content_candidates(files, checkout, "/app", [running[2]]), [])
            calls.clear()
            check_eq("with nothing to compare every container is one, and nothing is asked of docker",
                     (R.content_candidates(["README.md"], checkout, "/app", running[:2]), calls),
                     (["holds-all", "holds-one"], []))
        finally:
            R.subprocess = held
    finally:
        cleanup(root)


def the_write_check_compares_against_the_story_it_is_given() -> None:
    """`--suggest --write --task-root <story>`: the one verification compares against THAT story's
    diff and writes nothing into it, and the stored spec carries no story (a project's cannot).
    A story that changes nothing inside the profile's checkout is another matter (t-224, C4): there
    is nothing to compare, the entry is not written on that evidence, and the sentence the gate
    rehearsal says is printed."""
    root = temp_project()
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "localhost"}]
        cfg["implementation_repos"] = [{"repo_id": "app", "local_path": "app", "execution_profile_id": "api"},
                                       {"repo_id": "ui", "local_path": "ui", "execution_profile_id": "e2e-ui"}]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (root / "app" / "src").mkdir(parents=True)
        (root / "app" / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
        story = root / "story"
        (story / "work").mkdir(parents=True)
        (story / "work" / "impl-diff.txt").write_text("+++ b/src/a.py\n", encoding="utf-8")
        wrote = run_script("runtime_probe.py", "--suggest", "--write", "--profile", "api",
                           "--container", "app-1", "--task-root", str(story), cwd=root)
        check_eq("the write succeeds when the story changes a file of the checkout", wrote.returncode, 0)
        stored = json.loads(cfg_path.read_text(encoding="utf-8"))["execution"]["runtime_probes"]["api"]
        check_in("the profile's own repository is the checkout, with two repositories", "app", stored["argv"])
        check_not_in("the stored spec names no story", "--task-root", json.dumps(stored))
        check_not_in("nor the flag of the rehearsal", "--no-evidence", json.dumps(stored))
        check_in("the verification ran against the story it was given (its diff has a file to compare)",
                 "probe check: result=unknown", wrote.stderr)
        check_not_in("and did not say the diff was empty", "no implementation diff files", wrote.stderr)
        check("and wrote nothing into it", not (story / "evidence").exists())

        # C4: nothing to compare. Every file lies outside the checkout, only documents, no diff at all.
        # W1: a diff that is absent or EMPTY is "nothing is recorded", never "the story changes nothing".
        for label, diff in (("every changed file lies outside the checkout", "+++ b/src/elsewhere.py\n"),
                            ("only documents", "+++ b/README.md\n"),
                            ("an empty diff file", ""),
                            ("a diff file of blank lines", "\n  \n"),
                            ("no diff at all", None)):
            sentence = R.NO_DIFF_RECORDED if diff in (None, "", "\n  \n") else R.nothing_to_compare("app")
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            data["execution"]["runtime_probes"].pop("api", None)
            cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            diff_file = story / "work" / "impl-diff.txt"
            if diff is None:
                diff_file.unlink()
            else:
                diff_file.write_text(diff, encoding="utf-8")
            before = cfg_path.read_bytes()
            quiet = run_script("runtime_probe.py", "--suggest", "--write", "--profile", "api",
                               "--container", "app-1", "--task-root", str(story), cwd=root)
            check_eq(f"{label}: exit 0, it is a fact about the story and not a failure", quiet.returncode, 0)
            check_in(f"{label}: it says what the gate rehearsal says", sentence, quiet.stderr)
            check_eq(f"{label}: and never the other fact's words",
                     (R.nothing_to_compare("app") in quiet.stderr, R.NO_DIFF_RECORDED in quiet.stderr),
                     (sentence == R.nothing_to_compare("app"), sentence == R.NO_DIFF_RECORDED))
            check_in(f"{label}: and that nothing was written", "nothing was written", quiet.stderr)
            check_eq(f"{label}: config.json is byte for byte what it was", cfg_path.read_bytes(), before)
            check_eq(f"{label}: nothing is printed as an entry to store", quiet.stdout, "")
            check_not_in(f"{label}: no probe was run", "probe check", quiet.stderr)
        # and with no story given it is the onboarding write, which never had a story to ask
        again = run_script("runtime_probe.py", "--suggest", "--write", "--profile", "api",
                           "--container", "app-1", cwd=root)
        check_eq("without --task-root the entry is written as always", again.returncode, 0)
        check("and it is in the config", bool(json.loads(cfg_path.read_text(encoding="utf-8"))["execution"]["runtime_probes"].get("api")))
    finally:
        cleanup(root)


def refusals_keep_their_two_halves_and_the_checkout_questions_are_pure() -> None:
    """t-224, C3/Q1/C4. A refusal is written for a command line; the gate rehearsal quotes only its
    plain half to a person, and the whole of it still prints as it always did."""
    import types
    two = R.pick_environment({"environments": [{"name": "a"}, {"name": "b"}]}, "")[1]
    check_eq("the stand refusal: its plain half has no flag", two.plain, "this project names 2 stands (a, b)")
    check_eq("its instruction is the other half", two.how, "pass --environment <name>")
    check_eq("and the whole is the text `--suggest` has always printed",
             str(two), "this project names 2 stands (a, b): pass --environment <name>")
    check("a refusal is still a string", isinstance(two, str) and two.startswith("this project names"))
    cfg = {"implementation_repos": [{"repo_id": "a", "local_path": "../a"}, {"repo_id": "b", "local_path": "../b"}]}
    ambiguous = R.pick_checkout(cfg, "api", "")[1]
    check_eq("the checkout refusal: no flag in its plain half",
             (ambiguous.plain, ambiguous.how.startswith("pass --checkout")),
             ("this project names 2 implementation repositories (a, b)", True))
    check_eq("none of the refusals of an answered question carries a half", R.pick_checkout(cfg, "api", "x"), ("x", ""))
    held = R.containers
    try:
        R.containers = lambda timeout=20: []
        none = R.suggest({"environments": [{"name": "s"}]}, Path("."), "api", "s", "", "c", "/app", SCRIPTS)[1]
        R.containers = lambda timeout=20: [("a", "i"), ("b", "j")]
        several = R.suggest({"environments": [{"name": "s"}]}, Path("."), "api", "s", "", "c", "/app", SCRIPTS)[1]
    finally:
        R.containers = held
    check_eq("docker names no container: plain, then the way out",
             (none.plain, "--" in none.plain, "pass --container <name>" in none.how),
             ("docker names no running container, so the stand cannot be identified by content", False, True))
    check_in("and the text is the one it always was", "by content. Bring the stand up", str(none))
    check_eq("several containers: the names are plain, the flag is not",
             (several.plain, "--" in several.plain, several.how),
             ("more than one container is running: a (i), b (j)", False,
              "Which one runs the application under test? Pass --container <name>, or --no-container if the application "
              "does not run in one"))
    # t-323 C3 (t-319 Q1): a blank checkout is a question naming the flag, never a value stored as `--checkout "  "`;
    # `portable_checkout` itself is unchanged (a blank input comes back as it is)
    env = {"environments": [{"name": "s"}]}
    for label, flag, cfg_blank in (("blank flag", "   ", env), ("tab flag", "\t", env),
                                   ("a repository whose local_path is blank", "",
                                    dict(env, implementation_repos=[{"repo_id": "a", "local_path": "  "}]))):
        spec_blank, refused_blank = R.suggest(cfg_blank, Path("."), "api", "s", "c-1", flag, "/app", SCRIPTS)
        check_eq(f"C3 {label}: no spec, a refusal that names the flag",
                 (spec_blank, getattr(refused_blank, "plain", "<no refusal>"), "--checkout" in getattr(refused_blank, "how", "")),
                 (None, "--checkout is empty", True))
    for label, flag, cfg_ok in (("a checkout given", "../app", env),
                                ("none given, derived from the config", "",
                                 dict(env, implementation_repos=[{"repo_id": "a", "local_path": "../a"}])),
                                ("none given, none in the config: the app root", "", env)):
        spec_ok, refused_ok = R.suggest(cfg_ok, Path("."), "api", "s", "c-1", flag, "/app", SCRIPTS)
        check_eq(f"C3 control, {label}: a spec and no refusal", (bool(spec_ok), refused_ok), (True, ""))
    check_eq("C3: portable_checkout keeps returning a blank input as it is", (R.portable_checkout("  ", Path(".")), R.portable_checkout("", Path("."))),
             (("  ", ""), ("", "")))
    # has_checkout: the profile's OWN repository decides; the other one's checkout is no stand-in
    both = {"implementation_repos": [{"repo_id": "a", "local_path": "../a", "execution_profile_id": "api"},
                                     {"repo_id": "u", "execution_profile_id": "e2e-ui"}]}
    check_eq("a repository that names the profile and has a path", R.has_checkout(both, "api"), True)
    check_eq("one that names it and has none: not a stand-in from the other repository", R.has_checkout(both, "e2e-ui"), False)
    check_eq("a profile no repository names: any repository with a path will do",
             R.has_checkout(both, "unit"), True)
    check_eq("no path anywhere", R.has_checkout({"implementation_repos": [{"repo_id": "u"}, "x", None]}, "api"), False)
    check_eq("no repository at all", R.has_checkout({}, "api"), False)
    check_eq("a path that is blank or not text is none",
             (R.has_checkout({"implementation_repos": [{"local_path": "  "}]}, "api"),
              R.has_checkout({"implementation_repos": [{"local_path": 7}]}, "api")), (False, False))
    # compared_files asks the filesystem only
    root = temp_project()
    try:
        (root / "src").mkdir()
        (root / "src" / "a.py").write_text("a", encoding="utf-8")
        calls = []
        held_run = R.subprocess
        R.subprocess = types.SimpleNamespace(run=lambda *a, **k: calls.append(a), TimeoutExpired=held_run.TimeoutExpired)
        try:
            check_eq("only the files the checkout holds", R.compared_files(["src/a.py", "src/b.py", "README.md"], root),
                     ["src/a.py"])
            check_eq("nothing in it: nothing", R.compared_files(["src/b.py"], root), [])
            check_eq("and docker was not asked", calls, [])
        finally:
            R.subprocess = held_run
    finally:
        cleanup(root)
    check_eq("the sentence for nothing to compare", R.nothing_to_compare("../testproject1"),
             "the story changes nothing in `../testproject1` (no changed file in this checkout), so the probe "
             "does not apply here and there is nothing to compare what the stand runs with")
    check_eq("the sentence for no diff on record",
             R.NO_DIFF_RECORDED,
             "no implementation diff is recorded for this story, so there is nothing to compare what the "
             "stand runs with")


def run_the_probe(profile: str, checkout, task, extra=(), stand=None) -> tuple:
    """`runtime_probe.main()` as the S5 run path and the rehearsal call it: (exit code, record). `stand` is the fake docker
    (S9); the default one answers NOTHING, so a probe that asks docker where it must not fails the test loudly."""
    out, old = io.StringIO(), sys.argv
    sys.argv = ["runtime_probe.py", "--profile", profile, "--environment", "localhost", "--container",
                f"{profile}-c", "--checkout", str(checkout), "--expected", "rev-1", "--task-root",
                str(task), *extra]
    try:
        with (stand or Stand()), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = R.main()
    finally:
        sys.argv = old
    return code, json.loads(out.getvalue())


def t238_w1_w4_the_probe_says_what_it_can_say_about_a_story_that_does_not_touch_its_checkout() -> None:
    """W1: no diff on record is `unknown`, and an EMPTY diff file is the same fact. W4: a diff none of
    whose files is in this checkout makes the probe NOT APPLICABLE to the profile (never `mismatched`
    on 0 of 0 files, which refused the other profile's automator on a false fact). cmp2 has two
    checkouts, one per profile; a UI-only story touches one of them."""
    import profile_contract as P
    root = temp_project()
    try:
        use_project(root)
        backend, ui = root / "backend", root / "ui"
        (backend / "src" / "testproject1").mkdir(parents=True)
        (backend / "src" / "testproject1" / "a.py").write_text("a", encoding="utf-8")
        page = ui / "src" / "components" / "Page.vue"
        page.parent.mkdir(parents=True)
        page.write_text("v", encoding="utf-8")
        task = root / "story"
        (task / "work").mkdir(parents=True)
        diff = task / "work" / "impl-diff.txt"
        fake = Stand(app=True, sha=lambda container, path: R.sha_local(page) if path.endswith("Page.vue") else "0" * 64)
        asked = fake.sha_calls
        try:
            for label, text in (("no diff file at all", None), ("an empty diff file", ""),
                                ("a diff file of blank lines", "\n \n\t\n")):
                if text is None:
                    diff.unlink(missing_ok=True)
                else:
                    diff.write_text(text, encoding="utf-8")
                down = Stand(digest=(1, "", "Cannot connect to the Docker daemon"))
                code, record = run_the_probe("api", backend, task, stand=down)
                # t-300 E15: nothing recorded is still not "nothing changed" (FR-41) - but it is no longer an early
                # `unknown` that never looks at the stand: the sha rungs read it against HEAD, the sources rung is skipped
                check_eq(f"W1 {label}: unknown, never not_applicable (nothing on record is not 'nothing changed')",
                         (code, record["result"], "reason_code" in record), (0, "unknown", False))
                check_eq(f"W1 {label}: the files are never compared (no diff to compare); only the digest was asked of docker",
                         (down.sha_calls, down.docker()), ([], ["inspect"]))
            diff.write_text("+++ b/src/components/Page.vue\n", encoding="utf-8")
            code, api = run_the_probe("api", backend, task, stand=fake)
            check_eq("W4 (cmp2-shaped, a UI-only diff): the api profile's probe is not applicable",
                     (code, api["result"], api["reason"], api["comparisons"]),
                     (0, "not_applicable", "no changed file in this checkout", []))
            check_eq("W4: docker was not asked about it", (asked, fake.calls), ([], []))
            checked = P.validate_runtime_provenance(api)
            check_eq("W4: the record is a VALID provenance record, kept as not_applicable by profile_contract",
                     (checked["valid"], checked["result"]), (True, "not_applicable"))
            check_eq("W4: nothing observed, so no evidence file even without --no-evidence",
                     (api["evidence_refs"], (task / "evidence").exists()), ([], False))
            code, ui_record = run_the_probe("e2e-ui", ui, task, stand=fake)
            check_eq("W4: the e2e-ui profile is probed, today's way",
                     (code, ui_record["result"], len(ui_record["comparisons"])), (0, "matched", 1))
            check_eq("W4: and docker was asked about the one file of its checkout", asked,
                     [("e2e-ui-c", "/app/src/components/Page.vue")])
            check_eq("W4: its record is valid and matched",
                     (P.validate_runtime_provenance(ui_record)["valid"],
                      P.validate_runtime_provenance(ui_record)["result"]), (True, "matched"))
            # a diff of documents and tests only: it IS recorded, and no production file of it is here
            diff.write_text("+++ b/README.md\n+++ b/tests/test_x.py\n", encoding="utf-8")
            code, only_docs = run_the_probe("api", backend, task, stand=Stand())
            check_eq("W4: a diff of documents and tests is recorded and touches nothing: not applicable",
                     only_docs["result"], "not_applicable")
            # control: SOME files compared keeps today's matched / mismatched
            diff.write_text("+++ b/src/testproject1/a.py\n+++ b/src/components/Page.vue\n", encoding="utf-8")
            code, both = run_the_probe("api", backend, task, ["--no-evidence"], stand=fake)
            check_eq("control: one file in the checkout, its content differs in the container: mismatched",
                     (both["result"], len(both["comparisons"])), ("mismatched", 2))
            check_in("control: and it is the file of this checkout that differs", "src/testproject1/a.py",
                     json.dumps([c for c in both["comparisons"] if c.get("container_sha256")]))
            check_eq("t-300: the sources mismatch names the differing files (a field the question reads)",
                     both.get("differing_files"), ["src/testproject1/a.py"])
        finally:
            pass
        # profile_contract: a record that does not apply is never downgraded, bound by content or not
        base = dict(api, mr_source_revision="rev-1")
        for label, provenance, refs in (
                ("a deployed revision that differs, not content-bound", {"deployed_source_revision": "other"}, []),
                ("a deployed revision that differs, bound by content",
                 {"deployed_source_revision": "content_mismatch", "technical_verification": True,
                  "source_linkage": "verified_content", "verified_source_revisions": ["rev-1"]}, ["x"])):
            got = P.validate_runtime_provenance(dict(base, provenance=provenance, evidence_refs=refs))
            check_eq(f"W4 profile_contract: {label}: still not_applicable", got["result"], "not_applicable")
        control = P.validate_runtime_provenance(dict(
            base, result="matched", observed_runtime_identity="x", evidence_refs=["x"],
            provenance={"deployed_source_revision": "other", "technical_verification": True,
                        "source_linkage": "exact"}))
        check_eq("control: the same disagreement on a MATCHED record is still mismatched", control["result"], "mismatched")
    finally:
        cleanup(root)


def t279_k_na_the_probe_that_does_not_apply_says_why_in_a_field() -> None:
    """K-NA (writer half): the `not_applicable` answer carries `reason_code: no_changed_file` - the field the
    gates read (FR-12) - next to its sentence; the other answers carry none."""
    import profile_contract as P
    root = temp_project()
    try:
        backend = root / "backend"
        (backend / "src").mkdir(parents=True)
        (backend / "src" / "a.py").write_text("a", encoding="utf-8")
        task = root / "story"
        (task / "work").mkdir(parents=True)
        (task / "work" / "impl-diff.txt").write_text("+++ b/src/elsewhere.py\n", encoding="utf-8")
        code, record = run_the_probe("api", backend, task)
        check_eq("K-NA: a diff with no file of this checkout: not_applicable, with the reason as a FIELD",
                 (code, record["result"], record["reason_code"]), (0, "not_applicable", "no_changed_file"))
        check_eq("K-NA: and the field is the one profile_contract names", P.NO_CHANGED_FILE, "no_changed_file")
        check("K-NA: the record is a valid provenance and `no_changed_file` reads it", P.validate_runtime_provenance(
            record)["valid"] and P.no_changed_file(record))
        check_eq("K-NA control: the same record with another reason code is not `no_changed_file`",
                 P.no_changed_file(dict(record, reason_code="because")), False)
        check_eq("K-NA control: nor one with the sentence only (FR-12: the sentence is not read)",
                 P.no_changed_file({k: v for k, v in record.items() if k != "reason_code"}), False)
        check_eq("K-NA control: nor a `matched` record that carries the code",
                 P.no_changed_file(dict(record, result="matched")), False)
        (task / "work" / "impl-diff.txt").write_text("", encoding="utf-8")
        _code, unknown = run_the_probe("api", backend, task, stand=Stand(digest=(1, "", "Cannot connect to the Docker daemon")))
        check_eq("K-NA control: no diff on record is `unknown` and carries no reason code",
                 (unknown["result"], "reason_code" in unknown), ("unknown", False))
    finally:
        cleanup(root)


def subprocess_timeout():
    return subprocess.TimeoutExpired("docker", 1)


def calls_of(stand) -> list:
    """The docker calls a Stand saw, as short words."""
    return stand.docker()


def field_of(rec,*path):
    """rec[path[0]][path[1]]... or None when a key is missing: a mutant that breaks the record fails the CHECK that reads it
    instead of crashing the whole run before it reaches the next one."""
    for key in path:
        rec = rec.get(key) if isinstance(rec, dict) else None
    return rec


def k10_a_label_equal_to_head_is_matched_and_remembered() -> None:
    """K10 (t-300): the label of the IMAGE of a container with no sources (the uitest nginx) names the commit it was built
    from. Equal to HEAD it is `matched`; the probe REMEMBERS how it read it (a `probe discovered` row) - but only a run that
    writes evidence does, and a rehearsal writes nothing and says so."""
    import profile_contract as P
    w = World()
    try:
        stand = Stand(app=False, labels={LABEL: HEAD})
        code, rec, said = w.probe(stand)
        check_eq("K10: label == HEAD: matched, exit 0", (code, rec["result"]), (0, "matched"))
        check_eq("K10: identity_kind oci_label, deployed_source_revision == HEAD, the exact linkage",
                 (rec["provenance"]["identity_kind"], rec["provenance"]["deployed_source_revision"], rec["provenance"]["source_linkage"],
                  rec["provenance"]["technical_verification"]), ("oci_label", HEAD, "exact", True))
        check_eq("K10: the identity is the image digest (the weaker identity the old K-IMG said, now with a proof)", rec["observed_runtime_identity"], IDENT)
        checked = P.validate_runtime_provenance(rec)
        check_eq("K10: a valid MATCHED record (the automated path may take it)", (checked["valid"], checked["result"]), (True, "matched"))
        check_eq("K10: the evidence file is written and named", (len(w.evidence()), len(rec["evidence_refs"])), (1, 1))
        check_eq("K10: and no marker (a real run is not a rehearsal)", "observed_without_evidence" in rec, False)
        check_eq("K10: ONE `probe discovered` row appeared: the label, for this stand and profile, written by the probe",
                 [(r["environment_id"], r["profile_id"], r["method"], r["label"], r["source"], r["recorded_by"], r["words"]) for r in w.rows()],
                 [("localhost", "e2e-ui", "oci_label", LABEL, "probe discovered", "runtime_probe.py", "")])
        check_in("K10: stderr names the registry and says the probe wrote it, not a person", "qa-factory/records/stand-identity.json", said)
        check_in("K10: ...", "written by the probe, not by a person", said)
        check_eq("K10: the docker calls were exactly the `test -d` discriminator, `inspect` and `image inspect`",
                 calls_of(stand), ["test -d", "inspect", "image inspect"])
        check_eq("K10: and the compare by content never ran", stand.sha_calls, [])
        check_eq("K10: the registry the probe wrote validates clean", SI.check_text(w.registry.read_text(encoding="utf-8")), [])
        # the same run as a REHEARSAL, on a fresh project: the verdict is the same, nothing is written, and it says so
        r = World()
        try:
            code, quiet, said = r.probe(Stand(app=False, labels={LABEL: HEAD}), "--no-evidence")
            check_eq("K10 rehearsal: the same verdict", (code, quiet["result"], quiet["provenance"]["identity_kind"]), (0, "matched", "oci_label"))
            check_eq("K10 rehearsal: `observed_without_evidence: true`, evidence_refs []", (quiet["observed_without_evidence"], quiet["evidence_refs"]), (True, []))
            check_eq("K10 rehearsal: the registry is still ABSENT and no evidence file exists", (r.registry.exists(), r.evidence()), (False, []))
            check_eq("K10 rehearsal: and stderr names no registry write", "recorded it in" in said, False)
            strict = P.validate_runtime_provenance(quiet)
            check_eq("K10 rehearsal: the STRICT validator refuses that record (no evidence file): only the rehearsal reader takes it",
                     (strict["valid"], P.acceptable_provenance(quiet, ("matched",)), P.acceptable_provenance(quiet, ("matched",), rehearsal=True)),
                     (False, False, True))
        finally:
            r.close()
    finally:
        w.close()


def k11_a_commit_of_the_checkout_is_mismatched_and_a_sha_of_nowhere_is_not() -> None:
    """K11 (t-300 Q5): `mismatched` needs PROOF that the value is another commit of THIS repository
    (`git cat-file -e <sha>^{commit}`); a 40-hex value of nowhere is `unknown`."""
    w = World(git=True)
    try:
        c1, c2 = w.commits
        code, rec, _said = w.probe(Stand(labels={LABEL: c1}), "--no-evidence", expected=c2)
        check_eq("K11: label = C1 (a commit of the checkout, HEAD is C2): mismatched, exit 0", (code, rec["result"]), (0, "mismatched"))
        check_eq("K11: with deployed_source_revision = C1 and the validator agreeing",
                 (rec["provenance"]["deployed_source_revision"], __import__("profile_contract").validate_runtime_provenance(rec)["result"]),
                 (c1, "mismatched"))
        stand = Stand(labels={LABEL: c1})
        w.probe(stand, "--no-evidence", expected=c2)
        check_in("K11: the proof was asked of git, through run_command: `cat-file -e <sha>^{commit}`", "cat-file",
                 " ".join(" ".join(a) for a in stand.calls if a[0] == "git"))
        # a sha that is not in the repository at all
        nowhere = "9" * 40
        code, rec, _said = w.probe(Stand(labels={LABEL: nowhere}), "--no-evidence", expected=c2)
        check_eq("K11: a 40-hex value that is not a commit of the checkout: UNKNOWN", (code, rec["result"]), (0, "unknown"))
        check_in("K11: and the outcome says so", "is not a commit of the checkout", rec["error"])
        check_eq("K11: it asks the person how to read the build, and carries no deployed revision (never `mismatched` by name)",
                 (rec.get("asks_person"), "deployed_source_revision" in rec["provenance"]), ("how", False))
        # CONTROL: the very same sha, once the checkout HAS the commit, is a mismatch. C3 is made, HEAD put back to C2:
        # the object stays in the repository, so the same 40-hex that was "nowhere" in a clone is a commit here.
        clone = w.root / "clone"
        subprocess.run(["git", "clone", "-q", str(w.ui), str(clone)], capture_output=True)

        def git(repo, *args):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                                   "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8").stdout.strip()
        (w.ui / "src" / "Page.vue").write_text("three\n", encoding="utf-8")
        git(w.ui, "commit", "-q", "-am", "three")
        c3 = git(w.ui, "rev-parse", "HEAD")
        git(w.ui, "reset", "-q", "--hard", c2)
        code, rec, _said = w.probe(Stand(labels={LABEL: c3}), "--no-evidence", expected=c2)
        check_eq("K11 CONTROL: the same sha after the checkout has the commit: mismatched", (rec["result"], rec["provenance"]["deployed_source_revision"]),
                 ("mismatched", c3))
        out, old = io.StringIO(), sys.argv
        sys.argv = ["runtime_probe.py", "--profile", "e2e-ui", "--environment", "localhost", "--checkout", str(clone), "--container", "ui-c",
                    "--task-root", str(w.task), "--expected", c2, "--no-evidence"]
        try:
            with Stand(labels={LABEL: c3}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                R.main()
        finally:
            sys.argv = old
        check_eq("K11 CONTROL: ...and in a checkout that never had it (a clone made before) it is unknown",
                 json.loads(out.getvalue())["result"], "unknown")
        # git that cannot answer at all errs toward unknown, never mismatched
        code, rec, _said = w.probe(Stand(labels={LABEL: c1}, commands={}), "--no-evidence", expected=c2, container="ui-c")
        check_eq("K11: (control of the control) C1 is still a mismatch with the checkout intact", rec["result"], "mismatched")
    finally:
        w.close()


def k12_a_value_that_is_no_commit_is_unknown() -> None:
    w = World()
    try:
        for label, value in (("the build arg's default `unknown`", "unknown"), ("empty", ""), ("an abbreviated sha", HEAD[:12]),
                             ("upper case", HEAD.upper()), ("41 characters", HEAD + "a"), ("39 characters", HEAD[:39])):
            code, rec, _said = w.probe(Stand(labels={LABEL: value}), "--no-evidence")
            check_eq(f"K12 ({label}): unknown - never matched, never mismatched", (code, rec["result"]), (0, "unknown"))
            check_eq(f"K12 ({label}): no deployed revision is claimed, the person is asked how", (
                "deployed_source_revision" in rec["provenance"], rec.get("asks_person")), (False, "how"))
            check_in(f"K12 ({label}): and the outcome says it is not the commit of a build", "is not the 40-character commit of a build",
                     " ".join(t["outcome"] for t in rec["tried"]))
        code, rec, _said = w.probe(Stand(labels={LABEL: HEAD}), "--no-evidence")
        check_eq("K12 CONTROL: AT 40 lower-case hex == HEAD it is matched", rec["result"], "matched")
        code, rec, _said = w.probe(Stand(labels={LABEL: "  " + HEAD + "\n"}), "--no-evidence")
        check_eq("K12: whitespace around a full sha is stripped (a file ends with a newline)", rec["result"], "matched")
        code, rec, _said = w.probe(Stand(labels={LABEL: HEAD}), "--no-evidence", expected="rev-1")
        check_eq("K12: an expected revision that is not a full commit cannot be compared with: unknown, no question",
                 (rec["result"], rec.get("asks_person")), ("unknown", None))
        check_in("K12: and it says so", "is not a full 40-character commit", rec["error"])
    finally:
        w.close()


def k13_a_person_confirms_stand_reads_nothing_and_binds_the_word() -> None:
    """K13 (t-300 Q6, C5): `person_confirms` is the person's decision "I check this stand myself": no label, no file, no
    sources, no command - only the image digest is read, to BIND the word to the bytes it was given for."""
    import profile_contract as P
    w = World()
    try:
        w.row("person_confirms", words="I check this stand myself")
        stand = Stand(app=True, labels={LABEL: HEAD}, files={BUILD_FILE: (0, HEAD + "\n", "")})
        code, rec, _said = w.probe(stand, "--no-evidence")
        check_eq("K13: no confirmation for this story: unknown + asks_person confirm", (code, rec["result"], rec.get("asks_person")),
                 (0, "unknown", "confirm"))
        check_eq("K13: NOTHING was read but the digest: no `cat`, no label, no `test -d`, no sha256sum", (calls_of(stand), stand.sha_calls),
                 (["inspect"], []))
        check_eq("K13: the record still names the image (the weaker identity), and carries no remedy (nothing to teach)",
                 (rec["observed_runtime_identity"], "remedy" in rec), (IDENT, False))
        w.confirm(image=IDENT)
        stand = Stand(labels={LABEL: OTHER})
        code, rec, _said = w.probe(stand, "--no-evidence")
        checked = P.validate_runtime_provenance(rec)
        check_eq("K13: a valid word for this story: person_confirmed (not matched), the validator says it is valid",
                 (rec["result"], checked["valid"], checked["result"], P.person_confirmed(rec)), ("person_confirmed", True, "person_confirmed", True))
        check_eq("K13: the identity is the image digest, the provenance says it was the person's word, the words travel whole",
                 (rec["observed_runtime_identity"], rec["provenance"]["technical_verification"], rec["provenance"]["identity_kind"],
                  rec["person_confirmation"]["words"], rec["person_confirmation"]["revision"], "tested_build" in rec),
                 (IDENT, False, "person_confirmed", "yes, it is deployed", HEAD, False))
        check_eq("K13: still only the digest was read (the label that would say OTHER was never looked at)", calls_of(stand), ["inspect"])
        check_eq("K13: and it is NEVER taken for matched by a caller that wants a verified build",
                 (P.acceptable_provenance(rec, ("matched",)), P.acceptable_provenance(rec, ("matched", "person_confirmed"))), (False, True))
        # the binding moves
        code, rec, _said = w.probe(Stand(), "--no-evidence", expected=OTHER)
        check_eq("K13: HEAD moved: unknown, asks again, `voided` names the checkout and when the word was given",
                 (rec["result"], rec.get("asks_person"), "the checkout moved to commit " + OTHER[:12] in rec["voided"]["what"],
                  bool(rec["voided"]["earlier_at"])), ("unknown", "confirm", True, True))
        code, rec, _said = w.probe(Stand(digest=DIGEST2), "--no-evidence")
        check_eq("K13: the stand runs another image: voided, names the image", (rec["result"], rec["voided"]["what"]),
                 ("unknown", "the stand runs another image"))
        code, rec, _said = w.probe(Stand(digest=(0, "not a digest\n", "")), "--no-evidence")
        check_eq("K13: docker answers but names no image (F5b): voided - the word cannot be bound", (rec["result"], rec["voided"]["what"]),
                 ("unknown", "I could not read which image the stand runs"))
        # E17 wins over this question
        code, rec, _said = w.probe(Stand(digest=(1, "", "Cannot connect to the Docker daemon")), "--no-evidence")
        check_eq("K13 (E17): docker does not answer on a stand whose word names an image: no question, the report can say why",
                 (rec["result"], rec.get("asks_person"), "docker did not answer" in rec["error"]), ("unknown", None, True))
        w.confirm(image="", words="yes, deployed (no image was readable then)")
        code, rec, _said = w.probe(Stand(digest=(1, "", "Cannot connect to the Docker daemon")), "--no-evidence")
        check_eq("K13 (E17): a word recorded with NO image binds on the revision alone: person_confirmed, identity `person-confirmed:<at>`",
                 (rec["result"], rec["observed_runtime_identity"].startswith("person-confirmed:")), ("person_confirmed", True))
        # a withdrawn word
        SI.add_confirmation(w.root, w.task, task="QA-1", environment_id="localhost", profile_id="e2e-ui", kind="withdrawn",
                            words="I was wrong")
        code, rec, _said = w.probe(Stand(), "--no-evidence")
        check_eq("K13 (FR-40): a withdrawn word is no word: unknown + the confirm question again",
                 (rec["result"], rec.get("asks_person")), ("unknown", "confirm"))
        # the stand's definition moved: the row itself is not in force, the defaults run, the record says what moved
        w.cfg["environments"][0]["base_url"] = "http://localhost:9999"
        w.save_config()
        code, rec, _said = w.probe(Stand(app=False, labels={LABEL: HEAD}), "--no-evidence")
        check_eq("K13 (AE7): the stand's settings changed since the decision: the row is NOT in force - the label answers - and `voided` says why",
                 (rec["result"], rec["voided"]["what"]), ("matched", "the stand's settings changed"))
        w.cfg["environments"][0]["base_url"] = "http://localhost:8080"
        w.cfg["environments"][0]["credentials_by_role"] = {"default_user": "changed"}
        w.save_config()
        code, rec, _said = w.probe(Stand(), "--no-evidence")
        check_eq("K13 (Q10): editing the CREDENTIALS of the stand voids nothing: the row is still in force",
                 (rec["result"], "voided" in rec), ("unknown", False))
    finally:
        w.close()


def k14_step_5b_the_word_lifts_only_what_it_names() -> None:
    """K14 (t-300 §0b F1): a `deployed` word lifts `unknown`; a `test_deployed` word that names BOTH commits lifts `mismatched`;
    a plain `deployed` NEVER lifts a proven `mismatched`."""
    import profile_contract as P
    w = World(git=True)
    try:
        c1, c2 = w.commits
        w.confirm(revision=c2, image=IDENT)
        code, rec, _said = w.probe(Stand(labels={}), "--no-evidence", expected=c2)
        check_eq("K14: no label + a `deployed` word for HEAD and this digest: person_confirmed",
                 (rec["result"], rec["observed_runtime_identity"], "tested_build" in rec), ("person_confirmed", IDENT, False))
        code, rec, _said = w.probe(Stand(labels={LABEL: "unknown"}), "--no-evidence", expected=c2)
        check_eq("K14: a label that holds no commit (`unknown`, the compose default) + the same word: person_confirmed too",
                 rec["result"], "person_confirmed")
        # NEGATIVE CONTROL: label D (a commit of the checkout) + a PLAIN deployed word: stays mismatched
        code, rec, _said = w.probe(Stand(labels={LABEL: c1}), "--no-evidence", expected=c2)
        check_eq("K14 NEGATIVE CONTROL: label C1 (mismatched) + a plain `deployed` word: STAYS mismatched (a word never overrules a proof)",
                 (rec["result"], rec["provenance"].get("deployed_source_revision")), ("mismatched", c1))
        check_in("K14: and the record says the stand shows another build than the word named", "the stand now shows the build " + c1[:12],
                 rec["voided"]["what"])
        # a test_deployed word naming both
        w.confirm(kind="test_deployed", revision=c1, story_revision=c2, image=IDENT, words="test what is deployed")
        code, rec, _said = w.probe(Stand(labels={LABEL: c1}), "--no-evidence", expected=c2)
        checked = P.validate_runtime_provenance(rec)
        check_eq("K14: label D + a `test_deployed` word (revision D, story HEAD, this digest): person_confirmed, tested_build D",
                 (rec["result"], rec["tested_build"], rec["person_confirmation"]["revision"], rec["person_confirmation"]["story_revision"],
                  rec["provenance"]["deployed_source_revision"], checked["valid"], checked["result"]),
                 ("person_confirmed", c1, c1, c2, c1, True, "person_confirmed"))
        check_eq("K14: the kind says which word it was", rec["person_confirmation"]["kind"], "test_deployed")
        for label, edit, expect_what in (
                ("a revision that is NOT D", dict(revision="7" * 40), "the stand now shows the build " + c1[:12]),
                ("a story revision that is NOT HEAD", dict(story_revision="8" * 40), "the checkout moved to commit " + c2[:12]),
                ("another image", dict(image="image:" + DIGEST2), "the stand runs another image")):
            w.confirm(**dict(dict(kind="test_deployed", revision=c1, story_revision=c2, image=IDENT, words="again"), **edit))
            code, rec, _said = w.probe(Stand(labels={LABEL: c1}), "--no-evidence", expected=c2)
            check_eq(f"K14 NEGATIVE CONTROL: a test_deployed word with {label}: STAYS mismatched, voided says why",
                     (rec["result"], rec["voided"]["what"]), ("mismatched", expect_what))
        w.confirm(kind="test_deployed", revision=c1, story_revision=c2, image=IDENT, words="back")
        code, rec, _said = w.probe(Stand(labels={LABEL: c2}), "--no-evidence", expected=c2)
        check_eq("K14: and when the stand now runs this story's own commit the word is moot: matched (the reading wins)", rec["result"], "matched")
        # a test_deployed word does not lift `unknown`
        code, rec, _said = w.probe(Stand(labels={}), "--no-evidence", expected=c2)
        check_eq("K14: a `test_deployed` word cannot lift `unknown` (there is no build D to name)", rec["result"], "unknown")
        code, rec, _said = w.probe(Stand(labels={LABEL: "9" * 40}), "--no-evidence", expected=c2)
        check_eq("K14: a sha that is no commit of the checkout + a deployed word: stays unknown (the stand shows another build)", rec["result"], "unknown")
    finally:
        w.close()


def k15_a_content_mismatch_is_never_lifted() -> None:
    w = World(git=True)
    try:
        c1, c2 = w.commits
        other = "f" * 64
        stand = Stand(app=True, sha=lambda container, path: other)
        code, rec, _said = w.probe(stand, "--no-evidence", expected=c2)
        check_eq("K15: the story's file differs inside the container: mismatched by CONTENT, no commit to name",
                 (rec["result"], rec["provenance"]["deployed_source_revision"], rec["differing_files"]), ("mismatched", "content_mismatch", ["src/Page.vue"]))
        check_eq("K15: the label was never read (sources outrank it); only the container's image digest was (FB-8: what a `test as is` word binds to)", calls_of(stand), ["test -d", "inspect"])
        w.confirm(kind="test_deployed", revision=c1, story_revision=c2, image="", words="test what is deployed")
        w.confirm(revision=c2, image="", words="deployed")
        code, rec, _said = w.probe(Stand(app=True, sha=lambda c, p: other), "--no-evidence", expected=c2)
        check_eq("K15: neither a `deployed` nor a `test_deployed` word lifts a content mismatch (the deployed build has no sha to bind)",
                 (rec["result"], "tested_build" in rec), ("mismatched", False))
        same = R.sha_local(w.ui / "src" / "Page.vue")
        code, rec, _said = w.probe(Stand(app=True, sha=lambda c, p: same), "--no-evidence", expected=c2)
        check_eq("K15 CONTROL: content equal: matched", (rec["result"], rec["observed_runtime_identity"].startswith("verified_content:")),
                 ("matched", True))
        # the container HAS sources and a file the story adds was never deployed (t-345 F2: this was `unknown`, no question).
        # t-357 F2a: "adds" is now the diff's own word (`--- /dev/null`) - the default diff of this World only changes the file
        (w.task / "work" / "impl-diff.txt").write_text("--- /dev/null\n+++ b/src/Page.vue\n", encoding="utf-8")
        stand = Stand(app=True, labels={LABEL: c2})
        code, rec, _said = w.probe(stand, "--no-evidence", expected=c2)
        check_eq("K15 (t-345 F2): /app present but a file the story adds is not in the container: MISMATCHED by content naming the file "
                 "(a person redeploys), the label is NOT consulted",
                 (rec["result"], rec["provenance"]["deployed_source_revision"], rec["differing_files"], calls_of(stand)),
                 ("mismatched", "content_mismatch", ["src/Page.vue"], ["test -d", "inspect"]))
        (w.task / "work" / "impl-diff.txt").write_text("+++ b/src/Page.vue\n", encoding="utf-8")
        stand = Stand(app=True, labels={LABEL: c2})
        code, rec, _said = w.probe(stand, "--no-evidence", expected=c2)
        check_eq("K15 (t-357 F2a): the same stand, the file only CHANGED by the story and absent from the container: not a mismatch - "
                 "the sources could not tell and the label (the commit it names) answers",
                 (rec["result"], "differing_files" in rec, calls_of(stand)[:2]), ("matched", False, ["test -d", "inspect"]))
    finally:
        w.close()


def k16_a_command_the_person_gave() -> None:
    """K16 (t-300 Q10): a `command` row is an argv the person recorded; the probe runs it FIRST; a way that fails is named and
    the defaults follow; the row is never rewritten."""
    cmd = ["python", "print_build.py", "--short"]
    key = tuple(cmd)
    w = World()
    try:
        w.row("command", argv=cmd, words="our script prints the commit")
        before = w.registry.read_bytes()
        code, rec, _said = w.probe(Stand(commands={key: (0, HEAD + "\n", "")}), "--no-evidence", container="")
        check_eq("K16: the command prints HEAD, no container: matched, identity_kind command, the identity is `revision:<HEAD>`",
                 (code, rec["result"], rec["provenance"]["identity_kind"], rec["observed_runtime_identity"]),
                 (0, "matched", "command", "revision:" + HEAD))
        stand = Stand(commands={key: (0, HEAD + "\n", "")})
        code, rec, _said = w.probe(stand, "--no-evidence")
        check_eq("K16: with a container the identity is the image digest (read after the command answered)",
                 (rec["result"], rec["observed_runtime_identity"], calls_of(stand)), ("matched", IDENT, ["inspect"]))
        for label, answer in (("exit 1", (1, "", "boom: no such tag")), ("a non-sha", (0, "v1.2.3\n", "")),
                              ("a timeout", subprocess_timeout()), ("a command that cannot start", FileNotFoundError("python"))):
            stand = Stand(app=False, labels={LABEL: HEAD}, commands={key: answer})
            code, rec, _said = w.probe(stand, "--no-evidence")
            check_eq(f"K16 ({label}): the way failed -> `registry_method_failed` is set, then the label rung answers: matched",
                     (code, rec["result"], bool(rec.get("registry_method_failed")), rec["provenance"]["identity_kind"]),
                     (0, "matched", True, "oci_label"))
            check_eq(f"K16 ({label}): the registry's bytes are unchanged (a person's way is never rewritten)", w.registry.read_bytes(), before)
        # limits, AT and BEYOND
        sha_padded = " " * (4096 - 40 - 1) + HEAD + "\n"
        check_eq("K16 setup: the padded output is exactly 4096 bytes", len(sha_padded.encode()), 4096)
        code, rec, _said = w.probe(Stand(commands={key: (0, sha_padded, "")}), "--no-evidence", container="")
        check_eq("K16 limit: output AT 4096 bytes (whitespace + the sha) is read as a sha", rec["result"], "matched")
        code, rec, _said = w.probe(Stand(commands={key: (0, " " + sha_padded, "")}), "--no-evidence", container="")
        check_eq("K16 limit: BEYOND, 4097 bytes, is not a commit: the way failed (no defaults without a container: unknown, asks how)",
                 (rec["result"], rec.get("asks_person"), "4096" in rec["registry_method_failed"]), ("unknown", "how", True))
        for chars, label in ((120, "AT 120"), (121, "BEYOND 121")):
            code, rec, _said = w.probe(Stand(commands={key: (1, "", "e" * chars)}), "--no-evidence", container="")
            said_back = rec["registry_method_failed"]
            check_eq(f"K16 limit: the stderr quote {label}: the quote is cut at 120 characters",
                     ("e" * 120 in said_back, "e" * 121 in said_back), (True, False))
        for chars, label in ((60, "AT 60"), (61, "BEYOND 61")):
            code, rec, _said = w.probe(Stand(commands={key: (0, "x" * chars + "\n", "")}), "--no-evidence", container="")
            said_back = rec["registry_method_failed"]
            check_eq(f"K16 limit: the value quote {label}: the quote is cut at 60 characters",
                     ("x" * 60 in said_back, "x" * 61 in said_back), (True, False))
        stand = Stand(commands={key: (0, HEAD + "\n", "")})
        w.probe(stand, "--no-evidence", container="")
        check_eq("K16: the command ran with the row's argv, through run_command, and nothing else was asked of anything", stand.calls, [cmd])
    finally:
        w.close()


def k17_nothing_answered_is_unknown_and_a_question() -> None:
    w = World()
    try:
        stand = Stand(app=False, labels={})
        code, rec, said = w.probe(stand, "--no-evidence")
        check_eq("K17: no label and no file: unknown, `asks_person: how`, exit 0", (code, rec["result"], rec.get("asks_person")), (0, "unknown", "how"))
        outcomes = [(t["method"], t["outcome"]) for t in rec["tried"]]
        check_eq("K17: `tried` lists the rungs it tried (the sources rung, the label, the file), each with its outcome",
                 [m for m, _o in outcomes], ["sources", "oci_label", "build_sha_file"])
        check_in("K17: the label's outcome names the label", LABEL, outcomes[1][1])
        check_in("K17: the file's outcome names the file", BUILD_FILE, outcomes[2][1])
        remedy = rec["remedy"]

        def remedy_ok(text) -> bool:
            return LABEL in text and "qa-factory/records/stand-identity.json" in text and "Dockerfile" not in text
        check_eq("K17: the remedy names the label and the registry, and never the Dockerfile", remedy_ok(remedy), True)
        check_eq("K17 NEGATIVE CONTROL: the old BUILD_SHA_REMEDY string FAILS the same check", remedy_ok(OLD_REMEDY), False)
        check_in("K17: the same remedy is on stderr", "qa-factory/records/stand-identity.json", said)
        check_eq("K17: no `build_sha`, no evidence, the image identity is the digest", (rec["observed_runtime_identity"], w.evidence()), (IDENT, []))
        check_eq("K17: and the registry was not written (an unknown writes nothing, E10)", w.registry.exists(), False)
    finally:
        w.close()
    keep, more = R.cap_tried([{"method": "m", "outcome": str(i)} for i in range(6)])
    check_eq("K17 LE1: `tried` AT 6 keeps all six, no `more`", (len(keep), more), (6, 0))
    keep, more = R.cap_tried([{"method": "m", "outcome": str(i)} for i in range(7)])
    check_eq("K17 LE1: BEYOND, 7 -> six kept and `tried_more` = 1, the first six in order", (len(keep), more, keep[-1]["outcome"]), (6, 1, "5"))
    check_eq("K17: fewer than six is untouched", R.cap_tried([]), ([], 0))


def k18_sources_outrank_a_stale_label() -> None:
    """K18 (t-300 Q4-B): a hot-reloaded dev container carries a STALE label; when it holds the sources, the content decides."""
    w = World()
    try:
        content = R.sha_local(w.ui / "src" / "Page.vue")      # the bytes on THIS machine (a text file gets CRLF on Windows)
        stand = Stand(app=True, labels={LABEL: OTHER}, sha=lambda container, path: content)
        code, rec, _said = w.probe(stand, "--no-evidence")
        check_eq("K18: `/app` present + a stale label: the CONTENT decides (matched) and the label was not read",
                 (rec["result"], rec["provenance"]["source_linkage"], calls_of(stand)), ("matched", "verified_content", ["test -d"]))
        code, rec, _said = w.probe(Stand(app=True, sha=lambda c, p: "f" * 64), "--no-evidence")
        check_eq("K18: the same container with different content: mismatched by content", rec["result"], "mismatched")
        stand = Stand(app=False, labels={LABEL: HEAD}, sha=lambda container, path: content)
        code, rec, _said = w.probe(stand, "--no-evidence")
        check_eq("K18 CONTROL: no `/app` -> the label is read", (rec["result"], calls_of(stand)), ("matched", ["test -d", "inspect", "image inspect"]))
        # AE2: no discovered row when the container HAS sources, even in a run that writes evidence
        code, rec, _said = w.probe(Stand(app=True, sha=lambda c, p: content))
        check_eq("K18: a run that writes evidence over a container WITH sources writes no registry row (a label must not outrank content)",
                 (rec["result"], w.registry.exists(), len(w.evidence())), ("matched", False, 1))
    finally:
        w.close()


def k19_no_diff_and_a_diff_that_touches_nothing() -> None:
    w = World(diff=None)
    try:
        stand = Stand(labels={LABEL: HEAD})
        code, rec, _said = w.probe(stand, "--no-evidence")
        check_eq("K19 (E15): NO diff recorded + label == HEAD: matched (the sha rungs answer about HEAD; `not_applicable` is never said)",
                 (rec["result"], "reason_code" in rec), ("matched", False))
        check_eq("K19: the sources rung was skipped: no `test -d`, only the digest and the label", calls_of(stand), ["inspect", "image inspect"])
        code, rec, _said = w.probe(Stand(labels={}), "--no-evidence")
        check_eq("K19: no diff + nothing readable: unknown, asks how (no early `no implementation diff` stop)", (rec["result"], rec.get("asks_person")),
                 ("unknown", "how"))
    finally:
        w.close()
    w = World(diff="+++ b/src/elsewhere.py\n")
    try:
        stand = Stand()
        code, rec, _said = w.probe(stand, "--no-evidence")
        check_eq("K19 (E14): a diff that touches no file of the checkout: not_applicable with its reason code, ZERO docker calls, nothing written",
                 (rec["result"], rec["reason_code"], stand.calls, w.registry.exists(), w.evidence()),
                 ("not_applicable", "no_changed_file", [], False, []))
    finally:
        w.close()


def k20_docker_that_does_not_answer_is_not_a_question() -> None:
    """K20 (t-300 E17, FR-3): a docker that does not answer is the factory's problem to say, not a question to a person."""
    for diff, first in (("+++ b/src/Page.vue\n", "test -d"), (None, "inspect")):
        w = World(diff=diff)
        try:
            down = {"exit 1 with the daemon's complaint": (1, "", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"),
                    "a docker that is not installed": FileNotFoundError("docker"),
                    "a timeout": subprocess_timeout()}
            for label, failure in down.items():
                stand = Stand(app=failure, digest=failure)
                code, rec, said = w.probe(stand, "--no-evidence")
                check_eq(f"K20 ({'with' if diff else 'without'} a diff, {label}): unknown, exit 0, NO asks_person, no remedy for a person",
                         (code, rec["result"], rec.get("asks_person"), "remedy" in rec), (0, "unknown", None, False))
                check_in(f"K20 ({'with' if diff else 'without'} a diff, {label}): the record says docker did not answer", "docker did not answer", rec["error"])
                check_eq(f"K20 ({'with' if diff else 'without'} a diff, {label}): ONE docker call, then every docker rung is skipped",
                         calls_of(stand), [first])
        finally:
            w.close()


def k21_the_story_stand_decides_which_stand_is_read() -> None:
    """K21 (t-300 Q12-A, E16): the story's stand (`pipeline.json` `environment`) wins over the argv's `--environment`; docker rungs
    only when they agree - a container observed for stand A never answers for stand B."""
    cmd = ["python", "print_preview_build.py"]
    w = World(pipeline={"environment": "preview"})
    try:
        w.row("command", environment="preview", argv=cmd, words="preview's script")
        stand = Stand(commands={tuple(cmd): (0, HEAD + "\n", "")})
        code, rec, _said = w.probe(stand, "--no-evidence", environment="localhost")
        check_eq("K21: pipeline.json says `preview`, the argv says `localhost`: ZERO docker calls and the PREVIEW command row is used",
                 (rec["result"], rec["observed_runtime_identity"], calls_of(stand)), ("matched", "revision:" + HEAD, []))
        w.row("oci_label", label="com.example.localhost-only", environment="localhost", words="localhost's label")
        stand = Stand(labels={"com.example.localhost-only": OTHER}, commands={tuple(cmd): (0, HEAD + "\n", "")})
        code, rec, _said = w.probe(stand, "--no-evidence", environment="localhost")
        check_eq("K21: the LOCALHOST row is not the story's stand, so it is never used: the PREVIEW command answers (and still no docker)",
                 (rec["result"], rec["provenance"]["identity_kind"], calls_of(stand)), ("matched", "command", []))
        w2 = World(pipeline={"environment": "preview"})
        try:
            stand = Stand(labels={LABEL: HEAD})
            code, rec, _said = w2.probe(stand, "--no-evidence", environment="localhost")
            check_eq("K21: with NO row for the story's stand: unknown, asks how, zero docker calls, and the outcome says why",
                     (rec["result"], rec.get("asks_person"), calls_of(stand), "the container named is on another stand" in
                      " ".join(t["outcome"] for t in rec["tried"])), ("unknown", "how", [], True))
        finally:
            w2.close()
        w3 = World(pipeline={"environment": "localhost"})
        try:
            stand = Stand(labels={LABEL: HEAD})
            code, rec, _said = w3.probe(stand, "--no-evidence", environment="localhost")
            check_eq("K21 CONTROL: the two agree: docker is read", (rec["result"], calls_of(stand)), ("matched", ["test -d", "inspect", "image inspect"]))
            code, rec, _said = w3.probe(Stand(labels={LABEL: HEAD}), "--no-evidence", environment="")
            check_eq("K21: an argv with no --environment takes the story's stand (nothing contradicts it)", (rec["result"], rec["environment_id"]),
                     ("matched", "localhost"))
        finally:
            w3.close()
    finally:
        w.close()


def k22_a_corrupt_registry_is_named_and_never_overwritten() -> None:
    w = World()
    try:
        w.registry.parent.mkdir(parents=True)
        w.registry.write_text('{"schema_version": 1, "rows": [ {"half": ', encoding="utf-8")
        before = w.registry.read_bytes()
        code, rec, said = w.probe(Stand(app=False, labels={LABEL: HEAD}))
        check_eq("K22 (E2): a corrupt registry: the default rungs still answer (matched by the label), `registry_error` is set",
                 (code, rec["result"], bool(rec.get("registry_error"))), (0, "matched", True))
        check_in("K22: the record names the file and the door", "qa-factory/records/stand-identity.json", rec["registry_error"])
        check_in("K22: ...", "delete the file", rec["registry_error"])
        check_in("K22: stderr names them too", "qa-factory/records/stand-identity.json", said)
        check_eq("K22: and the registry's bytes are unchanged even by a run that WRITES evidence (a writer never reads a corrupt file as `nothing known`)",
                 (w.registry.read_bytes() == before, len(w.evidence())), (True, 1))
        check_in("K22: the refusal to write is said, not hidden", "was not recorded", said)
    finally:
        w.close()


def k23_a_stand_the_config_does_not_name_is_never_written_for() -> None:
    w = World(config=lambda cfg: cfg.update(environments=[{"name": "preview", "base_url": "https://p"}]))
    try:
        code, rec, said = w.probe(Stand(app=False, labels={LABEL: HEAD}))
        check_eq("K23 (E5): the config does not name the stand: the run still matches and writes its evidence, but NO registry file exists",
                 (rec["result"], len(w.evidence()), w.registry.exists()), ("matched", 1, False))
    finally:
        w.close()
    w = World(config=lambda cfg: cfg.update(profiles=[{"profile_id": "api"}]))
    try:
        code, rec, said = w.probe(Stand(app=False, labels={LABEL: HEAD}))
        check_eq("K23 (E5): nor for a PROFILE the config does not name", (rec["result"], w.registry.exists()), ("matched", False))
        SI.append_row(w.root, SI.make_row(w.cfg, "localhost", "e2e-ui", "command", words="mine", argv=["x", "y"]))
        code, rec, said = w.probe(Stand(app=False, labels={LABEL: HEAD}), "--no-evidence")
        check_eq("K23 (AE8): a row for a profile the config no longer has is kept and NEVER used (the label answers, the command is not run)",
                 (rec["result"], rec["provenance"]["identity_kind"], "registry_method_failed" in rec), ("matched", "oci_label", False))
    finally:
        w.close()


def k24_no_container_named() -> None:
    w = World()
    try:
        stand = Stand()
        code, rec, _said = w.probe(stand, "--no-evidence", container="")
        check_eq("K24 (S13): no --container and no row: unknown, asks how, exit 0 (it was exit 2), zero docker calls",
                 (code, rec["result"], rec.get("asks_person"), stand.calls), (0, "unknown", "how", []))
        check_in("K24: `tried` says no container is named for this profile", "no container is named for this profile",
                 " ".join(t["outcome"] for t in rec["tried"]))
        out = subprocess.run([sys.executable, "-B", str(SCRIPTS / "runtime_probe.py"), "--profile", "api", "--task-root", str(w.task)],
                             capture_output=True, text=True, cwd=str(w.root), env=dict(os.environ, CLAUDE_PROJECT_DIR=str(w.root)))
        check_eq("K24: without --checkout it still refuses, naming the flag", (out.returncode, "--checkout" in out.stderr), (2, True))
    finally:
        w.close()


def k25_rehearsal_argv() -> None:
    ours = [sys.executable, "/plugin/scripts/runtime_probe.py", "--profile", "api"]
    got = R.rehearsal_argv(ours)
    check_eq("K25: our probe's argv gets --no-evidence appended, nothing else changes", (got, got is ours), (ours + ["--no-evidence"], False))
    check_eq("K25: it is idempotent", R.rehearsal_argv(got), got)
    portable = ["{python}", "{plugin_root}/scripts/runtime_probe.py", "--profile", "api"]
    check_eq("K25: the PORTABLE spelling (the config's own) is recognised by the basename of argv[1]", R.rehearsal_argv(portable)[-1], "--no-evidence")
    check_eq("K25: a Windows path spelling is recognised too", R.rehearsal_argv(["py", "C:\\p\\scripts\\runtime_probe.py"])[-1], "--no-evidence")
    for label, foreign in (("a project's own script", ["python", "/opt/project/probe.py", "--profile", "api"]),
                           ("a script whose name only ENDS like ours (NEGATIVE CONTROL)", ["python", "/opt/p/my_runtime_probe.py", "--profile", "api"]),
                           ("a script whose name only starts like ours", ["python", "/opt/p/runtime_probe.py.bak"]),
                           ("our script in argv[2] (not where the factory writes it)", ["python", "-u", "runtime_probe.py"]),
                           ("a one-word argv", ["probe"]), ("an empty argv", []), ("an argv whose argv[1] is not text", ["python", 7])):
        check_eq(f"K25: {label}: returned UNCHANGED (a project's script is never handed a flag it does not know, AE16)",
                 R.rehearsal_argv(foreign), foreign)
    check_eq("K25: a non-list is returned as it came", R.rehearsal_argv(None), None)
    check_eq("K25: with the story named, `--task-root` goes in BEFORE the flag, once",
             R.rehearsal_argv(ours, "/p/artifacts/T-1"), ours + ["--task-root", "/p/artifacts/T-1", "--no-evidence"])
    check_eq("K25: an argv that already names a task root keeps it", R.rehearsal_argv(ours + ["--task-root", "x"], "/p/a")[-1], "--no-evidence")
    check_eq("K25: ...and does not get a second one", R.rehearsal_argv(ours + ["--task-root", "x"], "/p/a").count("--task-root"), 1)
    check_eq("K25: a foreign argv is not handed the task root either", R.rehearsal_argv(["python", "p.py"], "/p/a"), ["python", "p.py"])


OCI_MISSING = ('OCI runtime exec failed: exec failed: unable to start container process: exec: "test": '
               'executable file not found in $PATH: unknown')
NOT_RUNNING = "Error response from daemon: Container 0a1b2c is not running"


def f2_the_docker_outcomes_are_classified_by_exit_and_stderr() -> None:
    """t-345 F2: E17 (docker did not answer, no question) is for a daemon that is unreachable or a container that is not running.
    A container whose shell or `sha256sum` is missing (a distroless image: exit 126/127) is `sources could not tell` - the LABEL rung
    still runs and a person can still be asked how - and a file the story adds that is not in a sources container is a content
    mismatch with the file named. Every class is tried AT and BEYOND its edge, one fake docker per class."""
    w = World()
    try:
        content = R.sha_local(w.ui / "src" / "Page.vue")
        said = lambda rec: " ".join(t["outcome"] for t in rec.get("tried", []))  # noqa: E731
        # --- `test -d`: answered ---------------------------------------------------------------------------------
        stand = Stand(app=(0, "", ""), sha=lambda c, p: content)
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F2 exit 0: answered (the directory is there): the content decides", (rec["result"], calls_of(stand)), ("matched", ["test -d"]))
        stand = Stand(app=(1, "", ""), labels={})
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F2 exit 1 with EMPTY stderr: answered (the directory is absent): the label rung ran, and nobody is told docker was silent",
                 (rec["result"], rec.get("asks_person"), calls_of(stand), "docker did not answer" in rec.get("error", "")),
                 ("unknown", "how", ["test -d", "inspect", "image inspect", f"cat {BUILD_FILE}"], False))
        check_in("F2 exit 1 empty stderr: `tried` says there are no files to compare", "is not a directory in the container", said(rec))
        # --- `test -d`: the binary is missing (a distroless image) -> `sources could not tell`, the label rung STILL runs --------
        for label, answer in (("exit 126, empty stderr", (126, "", "")), ("exit 127, empty stderr", (127, "", "")),
                              ("exit 126 + the OCI message", (126, "", OCI_MISSING)), ("exit 127 + the OCI message", (127, "", OCI_MISSING)),
                              ("exit 1 + `executable file not found` (AT: the words alone, any exit)", (1, "", OCI_MISSING)),
                              ("exit 2 + `OCI runtime exec failed`", (2, "", "OCI runtime exec failed: exec failed"))):
            stand = Stand(app=answer, labels={LABEL: HEAD})
            code, rec, _s = w.probe(stand, "--no-evidence")
            check_eq(f"F2 {label}: the label rung runs and answers (matched by the label), docker is NOT `down`",
                     (rec["result"], field_of(rec,"provenance", "identity_kind"), calls_of(stand)),
                     ("matched", "oci_label", ["test -d", "inspect", "image inspect"]))
            stand = Stand(app=answer, labels={})
            code, rec, _s = w.probe(stand, "--no-evidence")
            check_eq(f"F2 {label}: nothing else answers: unknown, `asks_person: how`, a remedy, and the record does NOT say docker was silent",
                     (rec["result"], rec.get("asks_person"), "remedy" in rec, "docker did not answer" in json.dumps(rec)), ("unknown", "how", True, False))
            first = (rec.get("tried") or [{}])[0]
            check_eq(f"F2 {label}: `tried` names the sources rung and says the files could not be compared",
                     (first.get("method"), "could not be compared" in first.get("outcome", "")), ("sources", True))
        # --- `test -d`: docker or the container did not answer -> E17 -----------------------------------------------------
        for label, answer in (("the daemon is unreachable", (1, "", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock")),
                              ("a Windows named pipe error", (1, "", "error during connect: this error may indicate that the docker daemon is not running")),
                              ("the container is not running", (1, "", NOT_RUNNING)),
                              ("no such container", (1, "", "Error response from daemon: No such container: ui-c")),
                              ("exit 126 + `is not running` (the container wins over the exit code)", (126, "", NOT_RUNNING)),
                              ("BEYOND: an exit nobody classified (2, `boom`)", (2, "", "boom")),
                              ("BEYOND: exit 125 (docker's own failure) with no words", (125, "", "")),
                              ("BEYOND: exit 128", (128, "", "")),
                              ("BEYOND: exit 1 with an unclassified complaint", (1, "", "permission denied"))):
            stand = Stand(app=answer, labels={LABEL: HEAD})
            code, rec, _s = w.probe(stand, "--no-evidence")
            check_eq(f"F2 {label}: E17 - unknown, NO question, no remedy, ONE docker call, the record says docker did not answer",
                     (code, rec["result"], rec.get("asks_person"), "remedy" in rec, calls_of(stand), "docker did not answer" in rec.get("error", "")),
                     (0, "unknown", None, False, ["test -d"], True))
        # --- the compare: a file the story adds is not in the container -----------------------------------------------------
        # t-357 F2a: the absence is a CONTENT difference only for a file the diff ADDS (`--- /dev/null`), or when another compared
        # file IS in the container; the default diff of this World changes an existing file, so it is written as an added one here
        ADDED = "--- /dev/null\n+++ b/src/Page.vue\n"
        CHANGED = "+++ b/src/Page.vue\n"
        (w.task / "work" / "impl-diff.txt").write_text(ADDED, encoding="utf-8")
        stand = Stand(app=True, labels={LABEL: HEAD})              # sha=None: the fake raises `... No such file or directory`
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F2 compare, the file is missing: mismatched by CONTENT, the file named, no label read, nobody asked",
                 (rec["result"], field_of(rec,"provenance", "deployed_source_revision"), rec.get("differing_files"), rec.get("asks_person"), calls_of(stand)),
                 ("mismatched", "content_mismatch", ["src/Page.vue"], None, ["test -d", "inspect"]))
        check_eq("F2 compare, the file is missing: the comparison says so, and the identity is not empty",
                 ([(c["file"], c["container_sha256"], c.get("note")) for c in rec.get("comparisons", [])], rec.get("observed_runtime_identity")),
                 ([("src/Page.vue", None, "not in the container")], "verified_content:absent"))
        import profile_contract as P
        check_eq("F2 compare, the file is missing: profile_contract reads the record as `mismatched`", P.validate_runtime_provenance(rec)["result"], "mismatched")
        # --- F2a (t-357): ALL compared files missing and none of them added by the story: the folder is the wrong one -----------
        (w.task / "work" / "impl-diff.txt").write_text(CHANGED, encoding="utf-8")
        stand = Stand(app=True, labels={LABEL: HEAD})
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F2a: one file the story only CHANGES is missing everywhere: not a mismatch - could not tell, the label rung RUNS and answers",
                 (rec["result"], field_of(rec, "provenance", "identity_kind"), "differing_files" in rec, calls_of(stand)),
                 ("matched", "oci_label", False, ["test -d", "inspect", "image inspect"]))
        stand = Stand(app=True, labels={})
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F2a: ...and nothing else answers: unknown, `asks_person: how`, a remedy, no differing file named",
                 (rec["result"], rec.get("asks_person"), "remedy" in rec, "differing_files" in rec,
                  "docker did not answer" in json.dumps(rec)), ("unknown", "how", True, False, False))
        first = (rec.get("tried") or [{}])[0]
        check_eq("F2a: `tried` names the sources rung and says the files could not be compared",
                 (first.get("method"), "could not be compared" in first.get("outcome", "")), ("sources", True))
        check_in("F2a: and names the folder searched - a wrong `--app-root`, not a stale build", "`/app` may not be the folder the application runs from",
                 first.get("outcome", ""))
        check_in("F2a: ...in the number of files it looked for", "none of its 1 file(s)", first.get("outcome", ""))
        check_not_in("F2a: and the sentence is words - no exit code", "exit ", first.get("outcome", ""))
        import human_text
        check_eq("F2a (t-357 vi): the sentence breaks no rule of human-questions.md (human_text.problems == [])",
                 human_text.problems(first.get("outcome", ""), kind="report"), [])
        check_in("F2a control: the same checker catches the exit code a sentence like it used to carry", "exit_code",
                 [p["rule"] for p in human_text.problems(first.get("outcome", "") + " (exit 1)", kind="report")])
        check_eq("F2a: a rung that could not tell leaves no comparison and no content identity (the image digest, if read, is all it has)",
                 (rec.get("comparisons"), str(rec.get("observed_runtime_identity")).startswith("verified_content:")), ([], False))
        # two files, both missing, neither added
        (w.ui / "src" / "Other.vue").write_text("other\n", encoding="utf-8")
        (w.task / "work" / "impl-diff.txt").write_text("+++ b/src/Page.vue\n+++ b/src/Other.vue\n", encoding="utf-8")
        stand = Stand(app=True, labels={})
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F2a AT the edge: two compared files, both missing, neither added: could not tell (not `mismatched`)",
                 (rec["result"], rec.get("asks_person"), "differing_files" in rec), ("unknown", "how", False))
        check_in("F2a: and counts both", "none of its 2 file(s)", (rec.get("tried") or [{}])[0].get("outcome", ""))
        # BEYOND: one of the two is added by the story: its absence IS a difference (never deployed)
        (w.task / "work" / "impl-diff.txt").write_text("+++ b/src/Page.vue\n--- /dev/null\n+++ b/src/Other.vue\n", encoding="utf-8")
        code, rec, _s = w.probe(Stand(app=True, labels={}), "--no-evidence")
        check_eq("F2a BEYOND the edge: both missing, ONE of them added: mismatched, both named (the container is not the story's)",
                 (rec["result"], sorted(rec.get("differing_files", []))), ("mismatched", ["src/Other.vue", "src/Page.vue"]))
        # a `--- /dev/null` over a file the compare never looks at (a test, a document) adds nothing to the question
        (w.task / "work" / "impl-diff.txt").write_text("+++ b/src/Page.vue\n--- /dev/null\n+++ b/tests/test_page.py\n--- /dev/null\n"
                                                       "+++ b/docs/page.md\n", encoding="utf-8")
        code, rec, _s = w.probe(Stand(app=True, labels={}), "--no-evidence")
        check_eq("F2a: an added TEST or DOCUMENT is not a file of the compare: the changed file's absence still could not tell",
                 (rec["result"], rec.get("asks_person")), ("unknown", "how"))
        # a line that is not followed by its `+++` is no added file
        (w.task / "work" / "impl-diff.txt").write_text("--- /dev/null\n\n+++ b/src/Page.vue\n", encoding="utf-8")
        code, rec, _s = w.probe(Stand(app=True, labels={}), "--no-evidence")
        check_eq("F2a: `--- /dev/null` NOT directly above the `+++` line adds nothing", (rec["result"], rec.get("asks_person")), ("unknown", "how"))
        check_eq("F2a: the new-file reader is exact: only the added production file", R.diff_new_files(w.task), [])
        (w.task / "work" / "impl-diff.txt").write_bytes(b"--- /dev/null\r\n+++ b/src/Page.vue\r\n--- a/src/Other.vue\n+++ b/src/Other.vue\n")
        check_eq("F2a: a CRLF diff reads too, and a CHANGED file (`--- a/...`) is not an added one", R.diff_new_files(w.task), ["src/Page.vue"])
        # G1-1: the exclusion is the one rule (`test_files.file_kind`), not a private copy of the extension list
        names = ["src/a.test.ts", "tests/a.test.ts", "src/__tests__/b.ts", "src/app/test_mode.py", "config/settings.yaml",
                 "docs/x.md", "docs/conf.py", "docs/x.png", "pyproject.toml", "Cargo.lock", "src/ok.py"]
        (w.task / "work" / "impl-diff.txt").write_text("".join(f"+++ b/{n}\n" for n in names), encoding="utf-8")
        check_eq("G1-1: `diff_files` takes only production files: a test NAME outside a test folder (src/a.test.ts, test_mode.py) "
                 "and code under docs/ are IN; tests/, __tests__/, config, documents and generated files are OUT",
                 R.diff_files(w.task), ["src/a.test.ts", "src/app/test_mode.py", "docs/conf.py", "src/ok.py"])
        (w.task / "work" / "impl-diff.txt").write_text("".join(f"--- /dev/null\n+++ b/{n}\n" for n in names), encoding="utf-8")
        check_eq("G1-1: `diff_new_files` applies the same rule to the files the story adds",
                 R.diff_new_files(w.task), ["src/a.test.ts", "src/app/test_mode.py", "docs/conf.py", "src/ok.py"])
        # control: with the added file back in the diff the old behaviour holds on the very same stand
        (w.task / "work" / "impl-diff.txt").write_text(ADDED, encoding="utf-8")
        code, rec, _s = w.probe(Stand(app=True, labels={LABEL: HEAD}), "--no-evidence")
        check_eq("F2a CONTROL: the same stand, the file ADDED: mismatched by content (t-345 F2 holds)",
                 (rec["result"], rec.get("differing_files")), ("mismatched", ["src/Page.vue"]))
        # --- the compare: some files there, one missing, one differing -------------------------------------------------------
        (w.ui / "src" / "Other.vue").write_text("other\n", encoding="utf-8")
        (w.task / "work" / "impl-diff.txt").write_text("+++ b/src/Page.vue\n+++ b/src/Other.vue\n", encoding="utf-8")

        def partial(container, path):
            if path.endswith("Page.vue"):
                return content
            raise RuntimeError(f"docker exec {container} sha256sum {path}: sha256sum: {path}: No such file or directory")
        code, rec, _s = w.probe(Stand(app=True, sha=partial), "--no-evidence")
        check_eq("F2 compare: one file equal, ONE MISSING: mismatched (a missing file is never `matched` on the others), the missing one named",
                 (rec["result"], rec.get("differing_files"), [c["container_sha256"] is None for c in rec.get("comparisons", [])]),
                 ("mismatched", ["src/Other.vue"], [False, True]))
        code, rec, _s = w.probe(Stand(app=True, sha=lambda c, p: content if p.endswith("Page.vue") else "f" * 64), "--no-evidence")
        check_eq("F2 compare CONTROL: one equal, one differing (no file missing): mismatched, the differing one named (unchanged)",
                 (rec["result"], rec.get("differing_files")), ("mismatched", ["src/Other.vue"]))
        (w.task / "work" / "impl-diff.txt").write_text("+++ b/src/Page.vue\n", encoding="utf-8")
        # --- the compare: the container or the tool ------------------------------------------------------------------------
        for label, failure in (("the container stopped mid-compare", RuntimeError(f"docker exec ui-c sha256sum /app/src/Page.vue: {NOT_RUNNING}")),
                               ("the daemon went away", RuntimeError("docker exec ui-c sha256sum /app/src/Page.vue: Cannot connect to the Docker daemon")),
                               ("the same, coded", R.ContainerCommandError("x", code=1, stderr=NOT_RUNNING))):
            stand = Stand(app=True, labels={LABEL: HEAD}, sha=lambda c, p, failure=failure: (_ for _ in ()).throw(failure))
            code, rec, _s = w.probe(stand, "--no-evidence")
            check_eq(f"F2 compare, {label}: E17 - unknown, no question, the label is not consulted",
                     (rec["result"], rec.get("asks_person"), calls_of(stand), "docker did not answer" in rec.get("error", "")),
                     ("unknown", None, ["test -d"], True))
        for label, failure in (("no sha256sum in the image (the OCI message)", RuntimeError(f"docker exec ui-c sha256sum /app/src/Page.vue: {OCI_MISSING}")),
                               ("no sha256sum, by the exit code alone (127, no words)", R.ContainerCommandError("sha256sum failed", code=127, stderr="")),
                               ("no sha256sum, by the exit code alone (126)", R.ContainerCommandError("sha256sum failed", code=126, stderr=""))):
            for labels, want in (({LABEL: HEAD}, ("matched", None)), ({}, ("unknown", "how"))):
                stand = Stand(app=True, labels=labels, sha=lambda c, p, failure=failure: (_ for _ in ()).throw(failure))
                code, rec, _s = w.probe(stand, "--no-evidence")
                check_eq(f"F2 compare, {label}, labels {'read' if labels else 'absent'}: the label rung runs after `could not tell`",
                         (rec["result"], rec.get("asks_person")), want)
            check_in(f"F2 compare, {label}: `tried` names the sources rung and what happened", "could not be compared", said(rec))
            check_eq(f"F2 compare, {label}: and the record does not say docker was silent", "docker did not answer" in json.dumps(rec), False)
        stand = Stand(app=True, labels={LABEL: HEAD}, sha=lambda c, p: (_ for _ in ()).throw(subprocess_timeout()))
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F2 compare BEYOND: a timeout is no class: it keeps its old road (unknown, no question, the label is not consulted)",
                 (rec["result"], rec.get("asks_person"), calls_of(stand)), ("unknown", None, ["test -d"]))
        # --- the file rung: a container that is not running -----------------------------------------------------------
        for label, answer, want in (("not running", (1, "", NOT_RUNNING), (None, True)),
                                    ("no `cat` in the image (127)", (127, "", OCI_MISSING), ("how", False)),
                                    ("the file is simply not there (1)", (1, "", "cat: /x: No such file or directory"), ("how", False))):
            stand = Stand(app=False, labels={}, files={BUILD_FILE: answer})
            code, rec, _s = w.probe(stand, "--no-evidence")
            check_eq(f"F2 file rung, {label}: asks_person / E17",
                     (rec.get("asks_person"), "docker did not answer" in json.dumps(rec)), want)
        # --- the temporal edge: a row that was answering by label keeps answering when the container turns distroless --------
        w.row("oci_label", source="probe discovered", recorded_by="runtime_probe.py", words="")
        stand = Stand(app=(126, "", OCI_MISSING), labels={LABEL: HEAD})
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("O1: a label row asks the sources first (`test -d`); AE2's record stands only where the sources cannot answer - here the container "
                 "has become one with no `test`, so the label row still answers",
                 (rec["result"], calls_of(stand)), ("matched", ["test -d", "inspect", "image inspect"]))
    finally:
        w.close()
    # --- the real `sha256sum` call over a fake subprocess: what it raises carries the exit code and the stderr ------------------
    import types
    real_run = R.subprocess.run

    def fake_run(code, out="", err=""):
        return lambda argv, **kw: types.SimpleNamespace(returncode=code, stdout=out, stderr=err)
    try:
        R.subprocess.run = fake_run(0, "ab" * 32 + "  /app/x\n")
        check_eq("F2 sha_container: exit 0 returns the digest", REAL_SHA_CONTAINER("c", "/app/x", 5), "ab" * 32)
        for code, err in ((127, OCI_MISSING), (1, "sha256sum: /app/x: No such file or directory"), (126, "")):
            R.subprocess.run = fake_run(code, "", err)
            try:
                REAL_SHA_CONTAINER("c", "/app/x", 5)
                got = None
            except R.ContainerCommandError as exc:
                got = (exc.code, exc.stderr == err, "sha256sum" in str(exc))
            check_eq(f"F2 sha_container: exit {code} raises ContainerCommandError carrying the exit code and the stderr", got, (code, True, True))
    finally:
        R.subprocess.run = real_run
    check_eq("F2 classifier: the four classes from (exit, stderr)",
             [R.docker_failure(c, t) for c, t in ((1, NOT_RUNNING), (127, ""), (1, "x: No such file or directory"), (2, "boom"))],
             ["down", "tool", "file", "other"])
    check_eq("F2 classifier: the markers are read case-insensitively and whitespace-folded",
             R.docker_failure(1, "CANNOT   connect\nto the DOCKER daemon"), "down")


def f7_rehearsal_argv_recognises_our_script_in_the_python_dash_b_form() -> None:
    """t-345 F7: `rehearsal_argv` found our own script only at argv[1]; `python -B <path>` (how the factory's own callers and a
    committed probe spell it) was not recognised, so our probe ran WITHOUT the flag and wrote evidence under a rehearsal."""
    path = "/plugin/scripts/runtime_probe.py"
    for label, argv in (("python -B <path>", ["python", "-B", path, "--profile", "api"]),
                        ("the portable spelling with -B", ["{python}", "-B", "{plugin_root}/scripts/runtime_probe.py", "--profile", "api"]),
                        ("a Windows path after -B", ["py", "-B", "C:\\p\\scripts\\runtime_probe.py", "--profile", "api"]),
                        ("a bare <path> (the script run directly)", [path, "--profile", "api"]),
                        ("a bare <path> alone", [path]),
                        ("python <path> (unchanged)", ["python", path, "--profile", "api"])):
        got = R.rehearsal_argv(argv)
        check_eq(f"F7 {label}: recognised - `--no-evidence` appended once, the rest unchanged", (got[:len(argv)], got[len(argv):]), (argv, ["--no-evidence"]))
        check_eq(f"F7 {label}: idempotent", R.rehearsal_argv(got), got)
        check_eq(f"F7 {label}: with the story named `--task-root` goes in before the flag",
                 R.rehearsal_argv(argv, "/p/a")[len(argv):], ["--task-root", "/p/a", "--no-evidence"])
    for label, foreign in (("a foreign script after -B", ["python", "-B", "/opt/project/probe.py", "--profile", "api"]),
                           ("-B and a script that only ENDS like ours (NEGATIVE CONTROL)", ["python", "-B", "/opt/p/my_runtime_probe.py"]),
                           ("-B and a name that only starts like ours", ["python", "-B", "/opt/p/runtime_probe.py.bak"]),
                           ("a bare foreign script", ["/opt/project/probe.py", "--profile", "api"]),
                           ("a bare script that only ENDS like ours", ["/opt/p/my_runtime_probe.py"]),
                           ("our script mentioned as an ARGUMENT of a foreign one", ["python", "/opt/project/probe.py", "runtime_probe.py"]),
                           ("-B alone", ["python", "-B"]), ("-B then a non-text item", ["python", "-B", 7])):
        check_eq(f"F7 {label}: returned UNCHANGED (a project's own script is never handed a flag it does not know, AE16)",
                 R.rehearsal_argv(foreign), foreign)


def f8_a_value_that_is_no_commit_at_a_default_rung_does_not_end_the_ladder() -> None:
    """t-345 F8 (FR-50: every route before a question): a project that labels its image `${UI_GIT_SHA:-unknown}` (the retired
    Dockerfile remedy) carries the literal `unknown` in the label. That label COULD NOT TELL; the next rung (the file) must run,
    and only when nothing answers is the person asked, with what each rung read in `tried`."""
    w = World()
    try:
        stand = Stand(app=False, labels={LABEL: "unknown"}, files={BUILD_FILE: (0, HEAD + "\n", "")})
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F8: label literally `unknown` + a readable file: MATCHED by the file (it was `unknown` + a question)",
                 (rec["result"], field_of(rec,"provenance", "identity_kind"), calls_of(stand)),
                 ("matched", "build_sha_file", ["test -d", "inspect", "image inspect", f"cat {BUILD_FILE}"]))
        for label, value in (("an abbreviated sha", HEAD[:12]), ("a tag", "v1.2.3"), ("empty", ""), ("41 characters", HEAD + "a")):
            stand = Stand(app=False, labels={LABEL: value}, files={BUILD_FILE: (0, HEAD + "\n", "")})
            code, rec, _s = w.probe(stand, "--no-evidence")
            check_eq(f"F8 ({label}): the label could not tell, the file answers", (rec["result"], field_of(rec,"provenance", "identity_kind")), ("matched", "build_sha_file"))
        stand = Stand(app=False, labels={LABEL: HEAD}, files={BUILD_FILE: (0, "unknown\n", "")})
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F8: the label answers first: a file that holds a non-sha later is never read (the first rung decides)",
                 (rec["result"], field_of(rec,"provenance", "identity_kind"), calls_of(stand)), ("matched", "oci_label", ["test -d", "inspect", "image inspect"]))
        # NEGATIVE CONTROL: a non-sha label and NO readable file: unknown, with the question (unchanged)
        stand = Stand(app=False, labels={LABEL: "unknown"})
        code, rec, _s = w.probe(stand, "--no-evidence")
        outcomes = [(t["method"], t["outcome"]) for t in rec["tried"]]
        check_eq("F8 NEGATIVE CONTROL: a non-sha label and no readable file: unknown, `asks_person: how`, the remedy",
                 (rec["result"], rec.get("asks_person"), "remedy" in rec), ("unknown", "how", True))
        check_eq("F8: `tried` names the label rung with the LITERAL value it held, then the file rung",
                 ([m for m, _o in outcomes], "holds 'unknown'" in outcomes[1][1], "is not the 40-character commit of a build" in outcomes[1][1]),
                 (["sources", "oci_label", "build_sha_file"], True, True))
        value = "x" * 70
        stand = Stand(app=False, labels={LABEL: value})
        code, rec, _s = w.probe(stand, "--no-evidence")
        said_label = [t["outcome"] for t in rec["tried"] if t["method"] == "oci_label"][0]
        check_eq("F8 limit: the value in `tried` is cut at the data limit `value_chars` (60): AT kept, BEYOND not",
                 ("x" * 60 in said_label, "x" * 61 in said_label), (True, False))
        # the file rung's own non-sha ends the ladder at the end anyway (no rung is left), and says what it read
        stand = Stand(app=False, labels={}, files={BUILD_FILE: (0, "not-a-sha\n", "")})
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F8: the LAST rung's non-sha: unknown, asks how, and `tried` has what the file held",
                 (rec["result"], rec.get("asks_person"), "holds 'not-a-sha'" in " ".join(t["outcome"] for t in rec["tried"])), ("unknown", "how", True))
    finally:
        w.close()
    w = World()
    try:
        w.confirm(image=IDENT)
        stand = Stand(app=False, labels={LABEL: "unknown"})
        code, rec, _s = w.probe(stand, "--no-evidence")
        check_eq("F8: a non-sha label with the person's `deployed` word for the story and the same image: person_confirmed (rung 7 still runs after the ladder)",
                 (rec["result"], calls_of(stand)), ("person_confirmed", ["test -d", "inspect", "image inspect", f"cat {BUILD_FILE}"]))
        # and a discovered row is written for the rung that ANSWERED, not for the one that could not tell
        code, rec, _s = w.probe(Stand(app=False, labels={LABEL: "unknown"}, files={BUILD_FILE: (0, HEAD + "\n", "")}))
        check_eq("F8: a run that writes evidence remembers the FILE rung (the one that answered), never the label that held `unknown`",
                 ([(r["method"], r["source"]) for r in w.rows()], rec["result"]), ([("build_sha_file", "probe discovered")], "matched"))
    finally:
        w.close()


def k26_the_onboarding_verification_is_always_a_rehearsal() -> None:
    """K26 (t-300 S14, R3): `--suggest --write` verifies the entry it wrote ONCE; that run is a rehearsal whether or not a story
    is named - it used to write evidence (and, with the registry, could write a discovered row) when none was."""
    root = temp_project()
    try:
        use_project(root)
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "localhost", "base_url": "http://localhost:8080"}]
        cfg["profiles"] = [{"profile_id": "api"}]
        cfg["implementation_repos"] = [{"repo_id": "app", "local_path": "app", "execution_profile_id": "api"}]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (root / "app" / "src").mkdir(parents=True)
        (root / "app" / "src" / "a.py").write_text("print(1)\n", encoding="utf-8")
        story = root / "qa-factory" / "artifacts" / "QA-1"
        (story / "work").mkdir(parents=True)
        (story / "work" / "impl-diff.txt").write_text("+++ b/src/a.py\n", encoding="utf-8")
        seen = []
        import node_ids as NI
        held = NI.run_captured       # EP1-35: the verification goes through the one bounded launcher

        def fake(argv, cwd, env, timeout_s):
            seen.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")
        for label, extra in (("no story named", []), ("a story named", ["--task-root", str(story)])):
            seen.clear()
            NI.run_captured = fake
            old, err = sys.argv, io.StringIO()
            sys.argv = ["runtime_probe.py", "--suggest", "--write", "--force", "--profile", "api", "--container", "app-1", *extra]
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    code = R.main()
            finally:
                sys.argv, NI.run_captured = old, held
            verify = [a for a in seen if any(str(x).endswith("runtime_probe.py") for x in a)]
            check_eq(f"K26 ({label}): the verification ran once and carries --no-evidence", (code, len(verify), "--no-evidence" in verify[0]), (0, 1, True))
            check_eq(f"K26 ({label}): and `--task-root` only when a story was named", "--task-root" in verify[0], bool(extra))
            check_eq(f"K26 ({label}): no registry file, no evidence file", (SI.registry_path(root).exists(), (story / "evidence").exists()), (False, False))
    finally:
        cleanup(root)


def ep1_24_b2_the_check_after_the_write_is_bounded_and_never_a_trace() -> None:
    """EP1-24 B2 (AK4, AK5, AK9; B-5, B-6): the entry is written BEFORE the check; a check that hangs, cannot start or prints a
    `{` that is not JSON says so on stderr, exits 0 and leaves the entry in the config; the bound is `VERIFY_TIMEOUT_S`, the
    value handed to `subprocess.run` (the boundary itself - exactly 30 s or 30 s and a bit - is `subprocess`'s, not tested here)."""
    root = temp_project()
    try:
        use_project(root)
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "localhost", "base_url": "http://localhost:8080"}]
        cfg["profiles"] = [{"profile_id": "api"}]
        cfg["implementation_repos"] = [{"repo_id": "app", "local_path": "app", "execution_profile_id": "api"}]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (root / "app" / "src").mkdir(parents=True)
        import node_ids as NI
        held_run = NI.run_captured
        held = R.subprocess
        check_eq("the bound is 30 s and the stored entry keeps its 120 s", R.VERIFY_TIMEOUT_S, 30)
        timeouts = []

        def attempt(behaviour):
            def fake(argv, cwd, env, timeout_s):
                timeouts.append(timeout_s)
                return behaviour(argv)
            cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")   # no entry yet: a fresh write
            NI.run_captured = fake
            old, err = sys.argv, io.StringIO()
            sys.argv = ["runtime_probe.py", "--suggest", "--write", "--profile", "api", "--container", "app-1"]
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                    code = R.main()
            finally:
                sys.argv, NI.run_captured = old, held_run
            stored = json.loads(cfg_path.read_text(encoding="utf-8")).get("execution", {}).get("runtime_probes", {}).get("api")
            return code, err.getvalue(), stored

        def hang(argv):
            raise held.TimeoutExpired(argv, R.VERIFY_TIMEOUT_S)

        def not_started(argv):
            raise OSError("no such file")

        def broken(argv):
            return subprocess.CompletedProcess(argv, 0, stdout='{"result": "matched"', stderr="")

        def good(argv):
            return subprocess.CompletedProcess(argv, 0, stdout='{"result": "matched"}', stderr="")
        code, said, stored = attempt(hang)
        check_eq("AK4: a check that hangs: exit 0 and the entry is written", (code, stored is not None), (0, True))
        check_in("AK4: stderr says it did not finish, in the bound's seconds", "probe check: did not finish in 30 s", said)
        check_in("AK4: and that the entry is written", "the entry is written", said)
        check_eq("B-5: the value handed to subprocess is the bound, not the stored 120", timeouts[-1], R.VERIFY_TIMEOUT_S)
        check_eq("B-6: the stored entry still says 120", (stored or {}).get("timeout_s"), 120)
        import execution_request as ER
        check("B-6: right after the unfinished check the first typed run can read the entry (before any later attempt rewrites it)",
              ER.registered_probe(json.loads(cfg_path.read_text(encoding="utf-8")), "api") is not None)
        code, said, stored = attempt(not_started)
        check_eq("a check that cannot start: exit 0, entry written, said", (code, stored is not None, "could not be started" in said), (0, True, True))
        code, said, stored = attempt(broken)
        check_eq("AK9: output starting with `{` that is not JSON: exit 0, entry written", (code, stored is not None), (0, True))
        check_in("AK9: stderr says the output was not JSON", "output was not JSON", said)
        check_not_in("AK9: and no trace", "Traceback", said)
        code, said, stored = attempt(good)
        check_in("AK5: a check that finishes prints its duration", "probe check took ", said)
        check_in("AK5: and the result line as before", "probe check: result=matched", said)
    finally:
        cleanup(root)


def the_registry_rows_the_probe_tries_first() -> None:
    """Rung 2 (PE3): the person's way is tried BEFORE the defaults, and what it cannot do is named."""
    w = World(git=True)
    try:
        c1, c2 = w.commits
        w.row("oci_label", label="com.example.build", words="our own label")
        stand = Stand(labels={"com.example.build": c2, LABEL: c1})
        code, rec, _said = w.probe(stand, "--no-evidence", expected=c2)
        check_eq("rung 2: an `oci_label` row with ITS label: read first, the default label is never looked at (matched by the row's label)",
                 (rec["result"], rec["provenance"]["identity_kind"], rec["build_sha"]), ("matched", "oci_label", c2))
        w.row("oci_label", label="com.example.build", words="again")
        stand = Stand(labels={LABEL: c1}, files={BUILD_FILE: (0, c2 + "\n", "")})
        code, rec, _said = w.probe(stand, "--no-evidence", expected=c2)
        check_eq("rung 2: the row's label is absent on the image: `registry_method_failed` names it, and the oci_label rung is SKIPPED as a "
                 "whole (`continue without M`): the default label (C1, which would say mismatched) is never read, the file answers",
                 (rec["result"], "com.example.build" in rec["registry_method_failed"], rec["provenance"]["identity_kind"],
                  calls_of(stand).count("image inspect")), ("matched", True, "build_sha_file", 1))
        w.row("build_sha_file", path="/srv/build.txt", words="our file")
        stand = Stand(files={"/srv/build.txt": (0, c2 + "\n", "")}, labels={LABEL: c1})
        code, rec, _said = w.probe(stand, "--no-evidence", expected=c2)
        check_eq("rung 2: a `build_sha_file` row reads ITS path (not the default file, not the label); the digest is read for the identity after",
                 (rec["result"], rec["provenance"]["identity_kind"], calls_of(stand)), ("matched", "build_sha_file", ["cat /srv/build.txt", "inspect"]))
        w.row("sources", app_root="/srv/app", words="the files")
        content = R.sha_local(w.ui / "src" / "Page.vue")
        stand = Stand(app=True, sha=lambda container, path: content if path.startswith("/srv/app/") else "0" * 64)
        code, rec, _said = w.probe(stand, "--no-evidence", expected=c2)
        check_eq("rung 2: a `sources` row compares under ITS app root",
                 (rec["result"], stand.sha_calls, [c for c in stand.calls if c[3:5] == ["test", "-d"]][0][5]),
                 ("matched", [("ui-c", "/srv/app/src/Page.vue")], "/srv/app"))
        w.row("sources", words="sources, no app root")
        w2 = World(diff=None)
        try:
            w2.row("sources", words="the files")
            stand = Stand(labels={LABEL: HEAD})
            code, rec, _said = w2.probe(stand, "--no-evidence")
            check_eq("rung 2: a `sources` row with NO diff recorded cannot compare: the way failed (said), the defaults answer",
                     (rec["result"], "no change of this story is recorded" in rec["registry_method_failed"]), ("matched", True))
        finally:
            w2.close()
    finally:
        w.close()


def the_discovered_row_is_written_only_where_nobody_said_anything() -> None:
    """Rung 9 (S12, E10, C1): ONE `probe discovered` row, from a run that writes evidence, where no row is in force."""
    w = World()
    try:
        w.row("oci_label", words="mine")
        before = w.registry.read_bytes()
        code, rec, _said = w.probe(Stand(app=False, labels={LABEL: HEAD}))
        check_eq("a row is in force for the stand and profile: nothing is written over it", (rec["result"], w.registry.read_bytes() == before), ("matched", True))
        SI.append_row(w.root, SI.make_row(w.cfg, "localhost", "e2e-ui", "withdrawn", words="no more"))
        before = w.registry.read_bytes()
        code, rec, _said = w.probe(Stand(app=False, labels={LABEL: HEAD}))
        check_eq("S12: a `withdrawn` row in force is the person's last word: no discovered row over it", (rec["result"], w.registry.read_bytes() == before), ("matched", True))
        code, rec, _said = w.probe(Stand(app=False, labels={LABEL: HEAD}), profile="api")
        check("another profile of the same stand has no word: it gets its own row (the key is stand + profile)",
              ("api", "probe discovered") in [(r["profile_id"], r["source"]) for r in w.rows()])
        rows_now = len(w.rows())
        code, rec, _said = w.probe(Stand(app=False, labels={LABEL: HEAD}), profile="api")
        check_eq("a second run over the same stand writes no second row (a row is in force now)", len(w.rows()), rows_now)
    finally:
        w.close()
    w = World()
    try:
        code, rec, _said = w.probe(Stand(app=False, labels={LABEL: "unknown"}))
        check_eq("E10: an `unknown` never writes a row", (rec["result"], w.registry.exists()), ("unknown", False))
        code, rec, _said = w.probe(Stand(app=False, labels={LABEL: OTHER}))
        check_eq("E10: a 40-hex that is no commit of the checkout (unknown) writes no row either", (rec["result"], w.registry.exists()), ("unknown", False))
        stand = Stand(app=False, labels={}, files={BUILD_FILE: (0, HEAD + "\n", "")})
        code, rec, said = w.probe(stand)
        check_eq("a default FILE rung that reads a commit is remembered too: a `build_sha_file` row with the default path",
                 (rec["result"], [(r["method"], r["path"], r["source"]) for r in w.rows()]),
                 ("matched", [("build_sha_file", BUILD_FILE, "probe discovered")]))
        check_in("...and says so", BUILD_FILE, said)
    finally:
        w.close()
    w = World()
    try:
        w.row("person_confirms", words="I check it")
        w.confirm(image=IDENT)
        rows_before = len(w.rows())
        code, rec, _said = w.probe(Stand())
        check_eq("a person_confirmed run writes its evidence file and never a registry row",
                 (rec["result"], len(w.evidence()), len(w.rows()) == rows_before), ("person_confirmed", 1, True))
        check_eq("...and the evidence file holds the same record the run printed", json.loads(w.evidence()[0].read_text(encoding="utf-8"))["result"],
                 "person_confirmed")
    finally:
        w.close()
    w = World()
    try:
        # two probes at once, no row yet: the writer re-reads under the lock, so ONE row lands (the second sees the first)
        first = Stand(app=False, labels={LABEL: HEAD})
        original = SI.append_row
        landed = []

        def racing(root, row, **kw):
            if not landed:
                landed.append(original(root, dict(row, words=""), sleep=lambda s: None))
            return original(root, row, **kw)
        SI.append_row = racing
        try:
            w.probe(first)
        finally:
            SI.append_row = original
        check_eq("a row that appeared between the read and the write is NOT written over (re-checked under the lock): still ONE row",
                 len(w.rows()), 1)
    finally:
        w.close()


def t238_w5_the_config_stores_the_portable_argv_and_the_reader_fills_in_the_machine() -> None:
    import hooklib
    plugin = str(hooklib.PLUGIN_ROOT)
    got = R.resolve_argv(["{python}", "{plugin_root}/scripts/runtime_probe.py", "--opt={plugin_root}/x",
                          "/opt/project/probe.py", "C:\\somebody\\python.exe", "plain", 7])
    check_eq("{python} is this machine's interpreter", got[0], sys.executable)
    check_eq("{plugin_root} is hooklib's plugin root", got[1], plugin + "/scripts/runtime_probe.py")
    check("and the script it names is there", Path(got[1]).is_file())
    check_eq("the token inside an option is filled in too", got[2], "--opt=" + plugin + "/x")
    check_eq("an absolute path somebody wrote is left exactly as it was (a project script, an old entry)",
             got[3:5], ["/opt/project/probe.py", "C:\\somebody\\python.exe"])
    check_eq("an element that is no text is not touched", got[5:], ["plain", 7])
    check_eq("an argv with no token comes back equal", R.resolve_argv(["a", "b"]), ["a", "b"])
    check_eq("the portable head is the one the writer stores", R.PORTABLE_HEAD,
             ["{python}", "{plugin_root}/scripts/runtime_probe.py"])
    # the CLI over a config written BEFORE this change (absolute argv): today's refusal, then --force
    root = temp_project()
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "localhost"}]
        cfg["implementation_repos"] = [{"repo_id": "app", "local_path": "../app"}]
        legacy = {"argv": [sys.executable, str(SCRIPTS / "runtime_probe.py"), "--profile", "api"],
                  "cwd": ".", "timeout_s": 120}
        cfg["execution"] = {"runtime_probes": {"api": legacy}}
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        before = cfg_path.read_bytes()
        refused = run_script("runtime_probe.py", "--suggest", "--write", "--profile", "api",
                             "--container", "app-1", cwd=root)
        check_eq("an existing entry without --force: today's refusal, exit 2", refused.returncode, 2)
        check_eq("and the config is byte for byte what it was", cfg_path.read_bytes(), before)
        forced = run_script("runtime_probe.py", "--suggest", "--write", "--force", "--profile", "api",
                            "--container", "app-1", cwd=root)
        check_eq("--force rewrites it", forced.returncode, 0)
        stored = json.loads(cfg_path.read_text(encoding="utf-8"))["execution"]["runtime_probes"]["api"]
        check_eq("to the portable form", stored["argv"][:2], ["{python}", "{plugin_root}/scripts/runtime_probe.py"])
        check_in("and the one verification run resolved the tokens (it ran and answered)", "probe check",
                 forced.stderr)
        check_not_in("it did not name this machine's interpreter anywhere in the config",
                     sys.executable, cfg_path.read_text(encoding="utf-8"))
    finally:
        cleanup(root)


def _other_drive_path(root: Path) -> str:
    """A path on a drive letter other than the root's (Windows only: a letter nobody mounts is enough, relpath is textual)."""
    letter = "Z" if os.path.splitdrive(str(root))[0].upper() != "Z:" else "Y"
    return f"{letter}:/not/here/x"


def t298_k_c1_portable_checkout_table() -> None:
    """K-C1 (t-298, B-253 z): `--suggest --write` stores the checkout RELATIVE to the project root. Every limit is tested AT and
    BEYOND it: the root itself (AT: `.`, never ""), its parent (BEYOND by one: `..`), a sibling that shares the root's name as a
    prefix (`proj-app` is NOT inside `proj`), and a drive with no relative form (F8: stored as given, with a note, never refused)."""
    base = temp_dir("qa-portable-")
    try:
        root = base / "proj"
        absolute = {
            "absolute under the root": (str(root / "app"), "app"),
            "absolute, two levels down": (str(root / "a" / "b"), "a/b"),
            "AT the boundary: the root itself": (str(root), "."),
            "BEYOND by one: the root's parent": (str(base), ".."),
            "a sibling sharing the root's name as a prefix": (str(base / "proj-app"), "../proj-app"),
            "outside the root on the same drive (the live case, two levels up)": (str(base.parent / "testproject1"), "../../testproject1"),
        }
        for label, (given, want) in absolute.items():
            got, note = R.portable_checkout(given, root)
            check_eq(f"K-C1 {label}: {want!r}, no note", (got, note), (want, ""))
            # the invariant: the stored form names the place the caller named, and the next migration keeps it
            check_eq(f"K-C1 {label}: (root / stored) resolves to the place given", (root / got).resolve(), Path(given).resolve())
            check_eq(f"K-C1 {label}: the audit's machine-local gate calls the stored form portable", _machine_local(got), False)
        relative = {"../app": "../app", "./": ".", ".": ".", "./app": "app", "app/": "app", "app": "app", "../../testproject1-ui": "../../testproject1-ui"}
        if os.name == "nt":
            relative.update({".\\app\\": "app", "app\\sub": "app/sub", "..\\app": "../app"})
        for given, want in relative.items():
            got, note = R.portable_checkout(given, root)
            check_eq(f"K-C1 relative {given!r}: normalised to {want!r} (F9: root-relative, never resolved), no note", (got, note), (want, ""))
            check_eq(f"K-C1 relative {given!r}: (root / stored) is (root / given)", (root / got).resolve(), (root / given.replace(chr(92), "/")).resolve())
            check_eq(f"K-C1 relative {given!r}: portable by the audit's gate", _machine_local(got), False)
        check_eq("K-C1 the root is `.` and never an empty string (runtime_paths maps `.` to \"\", which a --checkout must not become)",
                 (R.portable_checkout(".", root)[0], R.portable_checkout(str(root), root)[0]), (".", "."))
        check_eq("K-C1 empty or blank: returned as it is, no note (nothing to normalise; `suggest` never passes one)",
                 (R.portable_checkout("", root), R.portable_checkout("  ", root)), (("", ""), ("  ", "")))
        if os.name == "nt":
            upper = str(root).upper()
            check_eq("K-C1 Windows: a case difference in the root's own spelling still finds the checkout inside it",
                     R.portable_checkout(str(root / "app"), upper)[0].lower(), "app")
            far = _other_drive_path(root)
            got, note = R.portable_checkout(far, root)
        else:
            held = R.os.path.relpath

            def no_relative_form(*_a, **_k):
                raise ValueError("path is on mount 'C:', start on mount 'D:'")
            R.os.path.relpath = no_relative_form
            try:
                far = "/mnt/other/x"
                got, note = R.portable_checkout(far, root)
            finally:
                R.os.path.relpath = held
        check_eq("K-C1 F8: another drive / share has no relative form: stored AS GIVEN", got, far)
        check_in("K-C1 F8: ...with a note saying why, what follows (the next reinstall drops it, audit A20 reports it) and the way out", "audit A20", note)
        check_in("K-C1 F8: ...and the command that derives it again", "--suggest --write", note)
        check_eq("K-C1 F8: a checkout the caller names is never refused (P1): no exception, a value", isinstance(got, str) and bool(got), True)
    finally:
        cleanup(base)


def _alias_of(folder: Path):
    """(alias spelling of `folder`, how) - another name for the SAME existing folder: its Windows 8.3 short name when the
    volume has one, else a junction (Windows) or a symlink (elsewhere). (None, why) when none can be made."""
    import subprocess
    if os.name == "nt":
        import ctypes
        buffer = ctypes.create_unicode_buffer(1024)
        size = ctypes.windll.kernel32.GetShortPathNameW(str(folder), buffer, 1024)
        if size and buffer.value and buffer.value.lower() != str(folder).lower():
            return Path(buffer.value), "8.3 short name"
        link = folder.parent / (folder.name + "-junction")
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(folder)], capture_output=True, text=True)
        return (link, "junction") if done.returncode == 0 and link.exists() else (None, (done.stdout + done.stderr).strip())
    link = folder.parent / (folder.name + "-link")
    try:
        link.symlink_to(folder, target_is_directory=True)
    except OSError as exc:
        return None, str(exc)
    return link, "symlink"


def t319_k6_portable_checkout_folds_two_spellings_of_one_place() -> None:
    """K6 (t-319, B-260): the project root and the checkout are two spellings of places on ONE machine - an 8.3 short name
    (`DEV1~1`) and its long name (a home folder, a temp dir) - and `abspath` kept them apart, so the stored form came out
    `../../../DEV1~1/..`: right here, wrong on every other machine. `realpath` on both sides gives the long-name answer
    whichever side carries the alias."""
    base = temp_dir("qa-portable-alias-")
    try:
        real_base = Path(os.path.realpath(base)) / "a-rather-long-folder-name"
        project = real_base / "the-long-named-project"
        (project / "app").mkdir(parents=True)
        (real_base / "testproject1-sibling").mkdir()
        alias, how = _alias_of(real_base)
        check("K6 precondition: the temp folder has a second spelling (a short name, a junction or a symlink): " + how,
              alias is not None, how)
        if alias is None:
            return
        project_alias = alias / project.name
        long_form = R.portable_checkout(str(project / "app"), project)
        check_eq("K6 long-name baseline: root and checkout in the long spelling -> `app`, no note", long_form, ("app", ""))
        for label, checkout, root in (
                ("the ROOT in its alias, the checkout in the long name", str(project / "app"), project_alias),
                ("the root in the long name, the CHECKOUT in its alias", str(project_alias / "app"), project),
                ("both in the alias", str(project_alias / "app"), project_alias)):
            check_eq(f"K6 ({how}) {label}: the same answer as the long-name one", R.portable_checkout(checkout, root), long_form)
        for label, checkout, root in (
                ("a sibling beside the root, the root in its alias", str(real_base / "testproject1-sibling"), project_alias),
                ("a sibling in its alias, the root in the long name", str(alias / "testproject1-sibling"), project)):
            check_eq(f"K6 ({how}) {label}: `../testproject1-sibling`, no note", R.portable_checkout(checkout, root), ("../testproject1-sibling", ""))
            check_eq(f"K6 ({how}) {label}: the audit's machine-local gate calls it portable",
                     _machine_local(R.portable_checkout(checkout, root)[0]), False)
        check_eq("K6: the root itself, one spelling against the other, is still `.` (AT the boundary)",
                 R.portable_checkout(str(project_alias), project)[0], ".")
        # a checkout that does not exist is still stored (no existence check, as before), and an alias of a MISSING
        # tail keeps the tail as given
        check_eq("K6: a checkout that is not there yet is stored all the same, folded through the existing part of the path",
                 R.portable_checkout(str(project_alias / "not-yet" / "app"), project), ("not-yet/app", ""))
        if os.name == "nt":
            far = _other_drive_path(project)
            got, note = R.portable_checkout(far, project)
            check_eq("K6 control (F8 kept): another drive has no relative form: stored AS GIVEN with a note", (got, bool(note)), (far, True))
    finally:
        cleanup(base)


def t298_k_c2_the_cli_stores_what_it_prints_portable() -> None:
    """K-C2: through the CLI, the absolute checkout a caller passes is stored as `app`, and what `--suggest` prints is what `--write`
    stores (one entry, one form)."""
    # resolve(): the temp dir of this machine may be spelled with a Windows 8.3 short name, while the child process reads
    # its project root in the long form (hooklib); the caller here must name the checkout in the SAME spelling (a finding
    # in the report: portable_checkout uses abspath, as the spec says, so it does not fold the two)
    root = temp_project().resolve()
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "localhost"}]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (root / "app").mkdir()

        def checkout_of(argv) -> str:
            return argv[argv.index("--checkout") + 1]
        shown = run_script("runtime_probe.py", "--suggest", "--profile", "api", "--container", "app-1",
                           "--checkout", str(root / "app"), cwd=root)
        check_eq("K-C2 --suggest with an absolute checkout exits 0", shown.returncode, 0)
        printed = json.loads(shown.stdout)["execution"]["runtime_probes"]["api"]["argv"]
        check_eq("K-C2 the printed entry carries the portable checkout", checkout_of(printed), "app")
        written = run_script("runtime_probe.py", "--suggest", "--write", "--profile", "api", "--container", "app-1",
                             "--checkout", str(root / "app"), cwd=root)
        check_eq("K-C2 --write exits 0", written.returncode, 0)
        stored = json.loads(cfg_path.read_text(encoding="utf-8"))["execution"]["runtime_probes"]["api"]
        check_eq("K-C2 the stored --checkout is `app`", checkout_of(stored["argv"]), "app")
        check_eq("K-C2 the printed argv equals the stored argv (what you see is what is stored)", json.loads(written.stdout)["execution"]["runtime_probes"]["api"]["argv"], stored["argv"])
        check_not_in("K-C2 nothing of this machine's temp location is in the stored entry", str(root), json.dumps(stored))
        check_not_in("K-C2 a checkout inside the root prints no note", "stored as given", written.stderr)
        forced = run_script("runtime_probe.py", "--suggest", "--write", "--force", "--profile", "api", "--container", "app-1",
                            "--checkout", ".\\app\\", cwd=root)
        stored = json.loads(cfg_path.read_text(encoding="utf-8"))["execution"]["runtime_probes"]["api"]
        check_eq("K-C2 F9: a relative `.\\app\\` is root-relative, stored normalised (`app`)", (forced.returncode, checkout_of(stored["argv"])), (0, "app"))
        if os.name == "nt":
            far = _other_drive_path(root)
            odd = run_script("runtime_probe.py", "--suggest", "--write", "--force", "--profile", "api", "--container", "app-1",
                             "--checkout", far, cwd=root)
            stored = json.loads(cfg_path.read_text(encoding="utf-8"))["execution"]["runtime_probes"]["api"]
            check_eq("K-C2 F8: another drive is written as given, exit 0 (never refused)", (odd.returncode, checkout_of(stored["argv"])), (0, far))
            check_in("K-C2 F8: ...and the note is on stderr", "audit A20", odd.stderr)
    finally:
        cleanup(root)


def t298_k_c3_a_portable_probe_survives_the_migration() -> None:
    """K-C3: the entry `--suggest --write` stores is NOT dropped by the next reinstall's migration (the absolute one was: a
    launch command naming a place on this machine is machine-local) - so the person is not asked to derive it again."""
    root = temp_project().resolve()      # the long spelling, as in K-C2
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "localhost"}]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        (root / "app").mkdir()
        run_script("runtime_probe.py", "--suggest", "--write", "--profile", "api", "--container", "app-1",
                   "--checkout", str(root / "app"), cwd=root)
        written = json.loads(cfg_path.read_text(encoding="utf-8"))
        check_eq("K-C3 the probe is in the written config", bool(written["execution"]["runtime_probes"].get("api")), True)
        from harness import use_project
        use_project(root)       # config_contract pulls audit_factory, which reads the hook layer
        import config_contract as C
        stored = written["execution"]["runtime_probes"]["api"]
        check_eq("K-C3 the CHECKOUT element of the stored argv is not machine-local by the migration's own gate (C._machine_local_value)",
                 C._machine_local_value(stored["argv"][stored["argv"].index("--checkout") + 1]), False)
        # t-300 Q5 (B-260, first half): `migration_plan` now judges the entry with the container-aware gate (`--app-root /app` is a
        # place inside the container), so the WHOLE stored entry survives - what the original K-C3 asked for and could not assert
        kept_plan = C.migration_plan(json.loads(json.dumps(written)))
        check_eq("K-C3: the whole entry `--suggest --write` stores, `--app-root /app` and all, SURVIVES the migration (t-300 Q5)",
                 (kept_plan["proposed_config"]["execution"]["runtime_probes"].get("api") == stored,
                  [r["path"] for r in kept_plan["removed"] if "runtime_probes" in r["path"]]), (True, []))
        # control: the SAME element spelled as an absolute path (an older writer) IS machine-local
        check_eq("K-C3 control: the absolute spelling of the checkout is machine-local (the defect this change stands against)",
                 C._machine_local_value(str(root / "app")), True)
        old = json.loads(json.dumps(written))
        argv = old["execution"]["runtime_probes"]["api"]["argv"]
        argv[argv.index("--checkout") + 1] = str(root / "app")
        dropped = C.migration_plan(old)
        check_eq("K-C3 control: an entry with an absolute checkout is dropped by the migration",
                 [r["path"] for r in dropped["removed"] if "runtime_probes" in r["path"]], ["/execution/runtime_probes/api"])
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(root)


_GATE = []


def _machine_local(value) -> bool:
    """audit_factory's own gate (the migration uses it); imported on first use, because it reads the hook layer."""
    if _GATE:
        return _GATE[0](value)
    saved = os.environ.get("CLAUDE_PROJECT_DIR")
    probe_root = temp_project()
    try:
        from harness import use_project
        use_project(probe_root)
        from audit_factory import _machine_local as gate
        _GATE.append(gate)
        return gate(value)
    finally:
        if saved is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = saved
        import hooklib
        hooklib._PROJECT_ROOT_CACHE = None
        cleanup(probe_root)


def ep1_28_application_role_no_container_no_revision() -> None:
    """EP1-28 (H-1, H-4, flag): two repositories on one profile are told apart by a role that is in the data list, and only
    toward a refusal otherwise; `--suggest --no-container` writes an entry with no container; a checkout that names no commit
    says so in a FIELD."""
    app = {"repo_id": "app", "local_path": "app", "role": "application", "execution_profile_id": "web"}
    tests = {"repo_id": "tests", "local_path": "tests", "role": "tests", "execution_profile_id": "web"}

    def pick(*repos, profile="web"):
        return R.pick_checkout({"implementation_repos": [dict(r) for r in repos]}, profile, "")
    check_eq("H-1 the MyBooks shape (application + tests on one profile): the application's path", pick(app, tests), ("app", ""))
    check_eq("H-1 the order of the two does not matter", pick(tests, app), ("app", ""))
    check_eq("H-1 other listed words are the application too (implementation, service)",
             (pick(dict(app, role="implementation"), tests)[0], pick(dict(app, role="service"), tests)[0]), ("app", "app"))
    for label, repos in (("tests + tests", (dict(app, role="tests"), tests)), ("no role at all", (dict(app, role=""), dict(tests, role=""))),
                         ("the role key absent", ({k: v for k, v in app.items() if k != "role"}, {k: v for k, v in tests.items() if k != "role"})),
                         ("both listed", (app, dict(tests, role="service"))), ("case differs: Application", (dict(app, role="Application"), tests)),
                         ("tests + review", (dict(app, role="review"), tests))):
        path, refusal = pick(*repos)
        check_eq(f"H-1 {label}: the refusal as before, no path (never another repository silently)", (path, bool(refusal)), ("", True))
        check_in(f"H-1 {label}: ... naming the door --checkout", "--checkout", str(refusal))
    path, refusal = pick(dict(app, local_path=""), tests)
    check_eq("H-1 the application repository records no path while the tests' does: a refusal, not the tests' checkout", path, "")
    check_in("H-1 ... naming it and the key to record", "the application repository app of profile web records no local_path", str(refusal))
    check_in("H-1 ... and the door", "implementation_repos[].local_path", str(refusal))
    other = [dict(app, execution_profile_id="x"), dict(tests, execution_profile_id="y")]
    path, refusal = pick(*other)
    check_eq("H-1 no repository names the profile and there are several: still the refusal (the branch is not narrowed)", (path, bool(refusal)), ("", True))
    check_eq("H-1 one repository: as ever", pick(app), ("app", ""))
    # the flag
    root = temp_project().resolve()
    try:
        cfg_path = root / "qa-factory" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["environments"] = [{"name": "localhost", "base_url": "http://localhost:8080"}]
        cfg["implementation_repos"] = [app, tests]
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        spec, refusal = R.suggest(cfg, root, "web", "", "", "", "/app", SCRIPTS, no_container=True)
        check_eq("flag: no container, no app root in the entry; the application's checkout", (refusal, "--container" in spec["argv"],
                                                                                          "--app-root" in spec["argv"],
                                                                                          spec["argv"][spec["argv"].index("--checkout") + 1]),
                 ("", False, False, "app"))
        two = dict(cfg, environments=[{"name": "localhost"}, {"name": "qa"}])
        check("flag: after the environment pick: two stands is still the question", R.suggest(two, root, "web", "", "", "", "/app", SCRIPTS,
                                                                                            no_container=True)[0] is None)
        none_repo = dict(cfg, implementation_repos=[], app_root="")
        check("flag: an entry with no checkout is never written", R.suggest(dict(none_repo, app_root=" "), root, "web", "", "", "", "/app",
                                                                           SCRIPTS, no_container=True)[0] is None)
        both = run_script("runtime_probe.py", "--suggest", "--profile", "web", "--no-container", "--container", "c", cwd=root)
        check_eq("flag: with --container is a refusal (exit 2)", both.returncode, 2)
        written = run_script("runtime_probe.py", "--suggest", "--profile", "web", "--no-container", "--write", cwd=root)
        stored = ((json.loads(cfg_path.read_text(encoding="utf-8")).get("execution") or {}).get("runtime_probes") or {}).get("web") or {}
        check_eq("flag: --write stores an entry that names no container", (written.returncode, bool(stored.get("argv")), "--container" in stored.get("argv", [])),
                 (0, True, False))
    finally:
        cleanup(root)
    # H-4: a checkout that is not a git repository says so in a field
    w = World()
    try:
        code, record, _err = w.probe(Stand(), container="", expected="")
        check_eq("H-4 no commit in the checkout: unknown, the reason as a FIELD, the checkout named",
                 (code, record["result"], record.get("reason_code"), record.get("checkout") == str(w.ui)), (0, "unknown", "no_expected_revision", True))
        check_eq("H-4 the constant is the one the capture reads", R.NO_EXPECTED_REVISION, "no_expected_revision")
    finally:
        w.close()


def ep1_41c_the_stand_of_a_profile() -> None:
    """EP1-41c: `pick_environment(cfg, environment, profile)` drops the rows that cannot be the profile's stand when a row names a
    `surface`; `suggest` of a device stand never asks docker. Expectations from the requirement: adding a device row to a web project
    does not make 'two stands' for the web profile; nothing changes without a `surface`; a doubt is a refusal that asks, never a guess."""
    import surfaces
    web_p, native_p = {"profile_id": "web", "capabilities": ["web"]}, {"profile_id": "android", "capabilities": ["native"]}
    api = {"name": "localhost", "base_url": "http://localhost:8080"}
    phone = {"name": "emulator", "surface": "android", "driver": {"url": "http://127.0.0.1:4723"}, "app": {"id": "a.b"}}
    tablet = dict(phone, name="tablet", surface="ios")
    cfg = {"profiles": [web_p, native_p], "environments": [api, phone]}
    pick = R.pick_environment
    check_eq("41c: a device row added to a web project is not a second stand for the web profile", pick(cfg, "", "web"), ("localhost", ""))
    check_eq("41c: ...and the native profile's only stand is the device row", pick(cfg, "", "android"), ("emulator", ""))
    check_eq("41c: a named stand is returned as given, for any profile", (pick(cfg, "emulator", "web"), pick(cfg, "x", "android")), (("emulator", ""), ("x", "")))
    check_eq("41c: with no profile the answer is the old one: two rows ask", pick(cfg, "")[1].startswith("this project names 2 stands"), True)
    check_eq("41c: the old refusal, byte for byte, is still the answer without a profile", str(pick(cfg, "")[1]),
             "this project names 2 stands (localhost, emulator): pass --environment <name>")
    check_eq("41c: two device rows for a native profile: still two stands, it asks", pick({"profiles": [native_p], "environments": [phone, tablet]}, "", "android")[1] != "", True)
    only_api = {"profiles": [native_p], "environments": [api, dict(api, name="b", surface="web")]}
    check_eq("41c: a native profile over web rows only: nothing fits, '' and no refusal (the caller says it has no stand)", pick(only_api, "", "android"), ("", ""))
    for label, config in (("no `surface` anywhere", {"profiles": [web_p], "environments": [api, dict(api, name="b")]}),
                          ("a profile that names no capability", {"profiles": [{"profile_id": "web"}], "environments": [api, phone]}),
                          ("a profile that is not listed", {"profiles": [], "environments": [api, phone]}),
                          ("profiles that are no list", {"profiles": "x", "environments": [api, phone]}),
                          ("a `surface` the table lacks", {"profiles": [web_p], "environments": [api, dict(phone, surface="andriod")]})):
        check_eq(f"41c: {label}: the old answer (two rows ask)", pick(config, "", "web")[1] != "" and pick(config, "", "web")[0] == "", True)
    real_rows = surfaces.rows
    surfaces.rows = lambda: (_ for _ in ()).throw(ValueError("table broken"))
    try:
        check_eq("41c: an unreadable table drops nothing: two rows still ask", pick(cfg, "", "web")[1] != "", True)
    finally:
        surfaces.rows = real_rows
    reads = {"n": 0}
    surfaces.rows = lambda: (reads.__setitem__("n", reads["n"] + 1), real_rows())[1]
    try:
        pick({"profiles": [web_p], "environments": [api]}, "", "web")
        pick({"profiles": [web_p], "environments": [api, dict(api, name="b")]}, "", "web")
    finally:
        surfaces.rows = real_rows
    check_eq("41c: a project with no `surface` reads the table 0 times", reads["n"], 0)
    # suggest: a device stand is never given a container, and docker is not asked
    held = R.containers
    asked = []
    R.containers = lambda timeout=20: asked.append(1) or [("a", "i"), ("b", "j")]
    try:
        spec, refusal = R.suggest(cfg, Path("."), "android", "", "", "app", "/app", SCRIPTS)
        check_eq("41c suggest: a device stand writes the entry with no container and docker was not asked", (refusal, asked, "--container" in spec["argv"]), ("", [], False))
        check_eq("41c suggest: ...for the device stand's name", spec["argv"][spec["argv"].index("--environment") + 1], "emulator")
        spec, refusal = R.suggest(cfg, Path("."), "android", "emulator", "named-container", "app", "/app", SCRIPTS)
        check_eq("41c suggest: a container named for a device stand is not used", ("--container" in spec["argv"], refusal), (False, ""))
        spec, refusal = R.suggest(cfg, Path("."), "web", "", "", "app", "/app", SCRIPTS)
        check_eq("41c suggest: the web profile of the mixed project asks docker as before (two containers ask)", (asked, refusal.startswith("more than one container")), ([1], True))
    finally:
        R.containers = held


if __name__ == "__main__":
    ep1_41c_the_stand_of_a_profile()
    ep1_28_application_role_no_container_no_revision()
    sys.exit(main())
