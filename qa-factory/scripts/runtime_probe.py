#!/usr/bin/env python3
"""The runtime probe of a docker stand, by code: which source the stand runs, verified by
content. Prints ONE runtime_provenance record (profile_contract.validate_runtime_provenance)
on stdout, exit 0 - the shape `run_suite.py --mine` reads through
`execution.runtime_probes.<profile>` in qa-factory/config.json.

    python runtime_probe.py --task <TICKET> --profile api --environment localhost \\
        [--container <the container running the app>] --checkout <the app checkout> [--app-root /app]

The files compared are the production files the story's implementation diff touches
(work/impl-diff*.txt, `+++ b/<path>` outside tests and docs): their sha256 inside the container
against the local checkout, which must stand at the MR's head. The expected revision is the
checkout's HEAD (or --expected). A record that could not be verified says so
(`result: unknown`, `technical_verification: false`) - never a plausible invention. A diff none of
whose production files is in this checkout is `not_applicable` (reason: no changed file in this
checkout, and the FIELD `reason_code: no_changed_file`, which is what the gates read) - the probe
does not apply to the profile, which is not a mismatch (t-238 W1, W4; t-279 K-NA).

THE LADDER (t-300, `build_identity`; every caller reaches it through this argv). The build a stand
runs is read in this order, and the first rung that answers decides:

  0. not applicable: a recorded diff that touches no file of the checkout. No rung, no write.
  1. which stand: the story's (`pipeline.json` `environment`) wins over `--environment`; docker rungs
     only when they agree AND `--container` is named.
  2. the registry row of this stand and profile (qa-factory/records/stand-identity.json, written by
     stand_identity.py): the person's way is tried FIRST. `person_confirms` reads nothing: it takes the
     person's word for this story. A way that fails is named (`registry_method_failed`) and never
     rewritten; the defaults follow.
  3. sources: the container holds `--app-root`, so the story's files are compared by content. A
     stale label never outranks content (a hot-reloaded dev container). A file of the story that is not in the
     container is `mismatched` (content_mismatch, the file named), except a file that is not part of the
     running application (`non_runtime_files`, FB-8): that one is recorded in `not_shipped_files` and not compared.
     A container with no `test` or `sha256sum` (a
     distroless image, exit 126/127) could not tell: the next rung runs. Only a daemon that is unreachable or a
     container that is not running is "docker did not answer" (E17: no question).
  4. the OCI label of the IMAGE (`org.opencontainers.image.revision`), 5. a file in the container
     (/usr/share/nginx/html/build-sha.txt) - both from references/build-identity-methods.json.
  6. a value is a 40-hex commit: equal to HEAD is `matched`; a commit of the checkout is
     `mismatched`; a value that is no commit of the checkout is `unknown` - never `mismatched`; a value that is no
     commit at all (the label `unknown` of a `${GIT_SHA:-unknown}` build) is "this rung could not tell": the next
     rung runs, and `tried` keeps what each rung held (t-345 F8).
  7. the person's word for THIS story (qa-factory/artifacts/<T>/state/stand-confirmations.jsonl):
     `unknown` + a `deployed` word that still binds is `person_confirmed`; `mismatched` + a
     `test_deployed` word naming both commits is `person_confirmed` with `tested_build`. A word whose
     binding moved is `voided`. A `content_mismatch` is lifted only by a `content_accepted` word ("test as is",
     FB-8), which binds to the fingerprint of exactly the files compared (`content_identity`), this story's
     commit and the image; a `deployed` or `test_deployed` word never lifts it.
  8. nothing answered: `unknown`, what was tried, `asks_person: how` and the remedy - unless docker
     simply did not answer, which is not a question for a person.
  9. writes, only without `--no-evidence`: the evidence file, and ONE `probe discovered` registry row
     when a default rung read a commit and no row is in force.

`--no-evidence` is the rehearsal's way (gate A, the S6 freshness read, the build check): it compares and
prints, writes nothing, and says so - `observed_without_evidence: true` - so that only a reader that
asked for a rehearsal (profile_contract.acceptable_provenance(rehearsal=True)) takes the `matched` it
prints. `rehearsal_argv` is the one place that adds the flag, and only to this script.

The entry `--suggest --write` stores is PORTABLE: `{python}` and `{plugin_root}` stand for this
machine's interpreter and the plugin's location, and are filled in where the probe is run
(`resolve_argv`; t-238 W5), so a committed config means the same on every machine. So is its
`--checkout`: stored relative to the project root (`portable_checkout`; B-253 z), never as a path of
the writing machine.

TP1-13797: the automator of run 1 wrote this probe by hand inside its dispatch
(work/requests/runtime_probe_s5_2.py); the automator of run 3 could not, and the story's
first typed run was refused three times. A stand's identity is the factory's job.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime_paths  # noqa: E402  (the one path normaliser, used by portable_checkout)
import stand_identity as SI  # noqa: E402  (the registry and the person's word: the ladder's rungs 2 and 7)
from profile_contract import NO_CHANGED_FILE  # noqa: E402  (the one spelling of the reason code, FR-12)
import hooklib  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

# The note `--suggest --write` puts on the entry it writes. The config revert (`config_contract.restore_config`) knows that entry
# by this constant, not by a phrase of its own: this write leaves no approval and no backup, so the note is its only mark.
SUGGEST_NOTE = ("written by `runtime_probe.py --suggest --write`. {python} and {plugin_root} "
                "are resolved on the machine that runs the probe, so this entry is the same "
                "on every machine. Only {argv, cwd, timeout_s} are read.")


def _production(name: str) -> bool:
    """The one rule of "is this a production file" (`test_files.file_kind`), asked without the project's word: this walker
    does not know the checkout the diff's paths are relative to. A test-looking name outside a test place is production."""
    import test_files
    return test_files.file_kind(name) == "production"


def diff_files(task_root: Path) -> list:
    out = []
    for diff in sorted_paths((task_root / "work").glob("impl-diff*.txt")):
        try:
            text = diff.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in re.finditer(r"^\+\+\+ b/(\S+)", text, re.M):
            name = match.group(1)
            if not _production(name):
                continue
            if name not in out:
                out.append(name)
    return out


def diff_new_files(task_root: Path) -> list:
    """The production files the story ADDS: `--- /dev/null` followed by `+++ b/<path>` in a recorded diff.

    The one fact that makes a file's absence from the container a content difference (t-357 F2a): a file the story
    adds was never deployed, whereas a file the story only changes is there on any stand that runs the app, so its
    absence means the folder searched is not the app's. Same exclusions as `diff_files`."""
    out = []
    for diff in sorted_paths((Path(task_root) / "work").glob("impl-diff*.txt")):
        try:
            text = diff.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in re.finditer(r"^--- /dev/null[ \t]*\r?\n\+\+\+ b/(\S+)", text, re.M):
            name = match.group(1)
            if not _production(name):
                continue
            if name not in out:
                out.append(name)
    return out


def diff_recorded(task_root: Path) -> bool:
    """Whether the story HAS an implementation diff: at least one `work/impl-diff*.txt` with a
    line in it. No such file and a file with nothing in it are the same fact - nothing is
    recorded (FR-41): the second must never read as "the story changes nothing", which is a
    claim about the code and not about the record (t-238, W1)."""
    for diff in sorted((Path(task_root) / "work").glob("impl-diff*.txt")):
        try:
            if diff.read_text(encoding="utf-8", errors="replace").strip():
                return True
        except OSError:
            continue
    return False


def content_identity(seen: list) -> str:
    """sha256 hex of the canonical JSON of what a mismatched compare stood on: `[file, container sha | "absent", local sha |
    "absent"]` per compared file, sorted. A person's `test as is` word is bound to it: any byte that moved is another identity."""
    rows = sorted([c["file"], c.get("container_sha256") or "absent", c.get("local_sha256") or "absent"] for c in seen)
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def sha_local(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ContainerCommandError(RuntimeError):
    """A `docker exec` that exited non-zero: the message as it always was, and the exit code and the stderr kept
    whole, so the caller classifies the failure by them (`docker_failure`) and not by a sentence."""

    def __init__(self, message: str, code=None, stderr: str = ""):
        super().__init__(message)
        self.code, self.stderr = code, stderr


def sha_container(container: str, path: str, timeout: int) -> str:
    done = subprocess.run(["docker", "exec", container, "sha256sum", path], capture_output=True,
                          text=True, timeout=timeout)
    if done.returncode != 0:
        raise ContainerCommandError(f"docker exec {container} sha256sum {path}: {done.stderr.strip()[:200]}",
                                    code=done.returncode, stderr=done.stderr)
    return done.stdout.strip().split()[0]


def running_task() -> str:
    """The story this project is running, for a probe spec stored in config.json: that spec is
    the PROJECT's, so it cannot carry a ticket, and requiring one meant the spec could never be
    written down at all - which is why the probe of TP1-13797 was hand-written inside a
    dispatch (P4)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from planning_contract import running_story
        task_root = running_story(None)
    except Exception:                                    # pragma: no cover - no project
        return ""
    return task_root.name if task_root is not None else ""


def containers(timeout: int = 20) -> list:
    """[(name, image)] of what is running, or [] when docker does not answer."""
    try:
        done = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Image}}"],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if done.returncode != 0:
        return []
    rows = []
    for line in done.stdout.splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip():
            rows.append((parts[0].strip(), (parts[1] if len(parts) > 1 else "").strip()))
    return rows


VERIFY_TIMEOUT_S = 30   # `--suggest --write`'s one verification run (EP1-24 B2); the stored entry's `timeout_s` stays 120. An estimate: `probe check took N s` measures it

APP_ROOT = "/app"   # where the checkout lives inside the container, unless --app-root says otherwise

# The probe's own command line as the CONFIG stores it (t-232 G3/C1, t-238 W5). An absolute python
# and an absolute plugin path are a promise only the writing machine can keep, and config.json is
# committed and cloned; the two tokens are resolved where the probe is run, from that machine's
# own interpreter and plugin location. A config written before this change holds absolute paths:
# they are not tokens, `resolve_argv` leaves them as written, and audit A20 reports them.
PY_TOKEN = "{python}"
PLUGIN_TOKEN = "{plugin_root}"
PORTABLE_HEAD = [PY_TOKEN, PLUGIN_TOKEN + "/scripts/runtime_probe.py"]
# A `{word}` left in an argv after `resolve_argv`: a command nobody can run. THE one spelling (the driver's `probe_move`
# and `stage_done`'s command line both refuse to show or run an argv that still holds one; `story_run.py` is queued to read this).
UNKNOWN_TOKEN_RE = re.compile(r"\{[A-Za-z_][\w-]*\}")


def resolve_argv(argv) -> list:
    """The argv as THIS machine runs it: `{python}` becomes `sys.executable`, `{plugin_root}`
    hooklib's plugin root, in every element. Nothing else is touched: an absolute path somebody
    wrote (an older config, a project script) is executed as it stands."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import hooklib
    root = str(hooklib.PLUGIN_ROOT)
    return [a.replace(PY_TOKEN, sys.executable).replace(PLUGIN_TOKEN, root) if isinstance(a, str) else a
            for a in argv]


class Refusal(str):
    """A refusal that keeps its two halves. `str(refusal)` is what `--suggest` has always printed
    for the role at a command line: what is wrong, then the flag that answers it. `.plain` is the
    first half alone, in words with no flag in them, for a text a person reads (the gate rehearsal
    quotes it, FR-6); `.how` is the second, the instruction to type. A refusal with no second half
    has an empty `.how`."""

    def __new__(cls, plain: str, how: str = "", sep: str = ": "):
        obj = super().__new__(cls, plain + (sep + how if how else ""))
        obj.plain, obj.how = plain, how
        return obj


def _stands_of_profile(cfg: dict, profile: str, environments: list) -> list:
    """EP1-41c: the `environments[]` rows that can be THIS profile's stand, when the project describes any stand by a `surface`.
    A row whose `surface` leads (surfaces.json) to a capability the profile does not hold is dropped; a profile that a device
    row drives drops the rows with no `surface` as well. Nothing is dropped when no row names a `surface` (the web road: the
    table is not read), when no profile is asked, when the profile names no capability, or when the table cannot be read -
    the answer is then the one it always was, and ERRS toward asking more (two rows are a refusal, never a guess). A `surface`
    the table lacks is kept for the same reason."""
    if not profile or not any("surface" in e for e in environments):
        return environments
    import surfaces
    wanted = surfaces.profile_words(cfg, profile)
    if not wanted:
        return environments
    try:
        table = surfaces.rows()["surfaces"]
    except ValueError:
        return environments
    device_profile = surfaces.drives_device(table, wanted)
    kept = []
    for e in environments:
        if "surface" not in e:
            if not device_profile:
                kept.append(e)
            continue
        row = table.get(e["surface"]) if isinstance(e["surface"], str) else None
        if row is None or row["capability"] in wanted:
            kept.append(e)
    return kept


def pick_environment(cfg: dict, environment: str, profile: str = "", references=()) -> tuple:
    """(the stand's name, refusal): the one named, else the only one the project has - or, with `profile`, the only one that can
    be that profile's stand (`_stands_of_profile`). `references`: the names of the stands that run an OLD version of a side
    (`stand_identity.reference_stands`; S-c, t-2181 PC-9b): a stand nobody named is never picked among them - a reference stand's
    build is not asked, and its row must not turn "the only stand" into "two stands that cannot be told apart". INVARIANT: only
    the IMPLICIT pick skips them; a stand the caller names is returned as named (the story's own stand is still asked, and a
    walk of the reference names it itself), and with `references` empty the function is as it was."""
    environments = [e for e in (cfg.get("environments") or []) if isinstance(e, dict)]
    if environment:
        return environment, ""
    skipped = {str(r) for r in (references or ())}
    environments = [e for e in environments if str(e.get("name") or "") not in skipped]
    environments = _stands_of_profile(cfg, profile, environments)
    if len(environments) == 1:
        return str(environments[0].get("name") or ""), ""
    if environments:
        return "", Refusal("this project names " + str(len(environments)) + " stands ("
                           + ", ".join(str(e.get("name")) for e in environments) + ")",
                           "pass --environment <name>")
    return "", ""


def application_roles() -> tuple:
    """The `implementation_repos[].role` words that name the repository a profile's stand runs (data, FR-13:
    build-identity-methods.json `application_roles`). Unreadable or absent data is an empty list: no narrowing."""
    try:
        words = SI.data().get("application_roles")
    except Exception:
        return ()
    return tuple(str(w) for w in words if isinstance(w, str)) if isinstance(words, list) else ()


def pick_checkout(cfg: dict, profile: str, checkout: str) -> tuple:
    """(the checkout path, refusal). The repository whose `execution_profile_id` names this
    profile is the one the profile's stand runs (t-218: cmp2 has two repositories, one per
    profile, and the old count of repositories refused both); with none naming it, the only
    repository, and with several the question P4 allows. No repository at all: the app root."""
    if checkout:
        return checkout, ""
    repos = [r for r in (cfg.get("implementation_repos") or []) if isinstance(r, dict)
             and r.get("local_path")]
    named = [r for r in repos if profile and str(r.get("execution_profile_id") or "") == profile]
    if profile:
        # EP1-28 (H-1): the application repository of the profile records no path while another repository of the profile
        # does (the tests): `named` holds that other one alone, and choosing it would compare the stand with the TESTS'
        # commit. Only toward a refusal, never another repository silently (D-0021).
        every = [r for r in (cfg.get("implementation_repos") or []) if isinstance(r, dict)
                 and str(r.get("execution_profile_id") or "") == profile]
        roles = application_roles()
        mine = [r for r in every if str(r.get("role") or "") in roles]
        if named and len(every) > len(named) and len(mine) == 1 and not str(mine[0].get("local_path") or "").strip():
            return "", Refusal(f"the application repository {mine[0].get('repo_id')} of profile {profile} records no local_path",
                               "record implementation_repos[].local_path")
    if len(named) > 1:
        # a role in `application_roles` that is the ONE such role among them is the repository the stand runs; every other
        # input (no role, two such roles, `Application`, a role outside the list at both) keeps the refusal below
        roles = application_roles()
        mine = [r for r in named if str(r.get("role") or "") in roles]
        if len(mine) == 1:
            return str(mine[0]["local_path"]), ""
    if len(named) == 1:
        return str(named[0]["local_path"]), ""
    if len(named) > 1:
        return "", Refusal("this project names " + str(len(named)) + " implementation repositories for "
                           f"profile {profile} (" + ", ".join(str(r.get("repo_id")) for r in named)
                           + ")", "pass --checkout <path to the one the stand runs>")
    if len(repos) == 1:
        return str(repos[0]["local_path"]), ""
    if repos:
        return "", Refusal("this project names " + str(len(repos)) + " implementation repositories ("
                           + ", ".join(str(r.get("repo_id")) for r in repos) + ")",
                           "pass --checkout <path to the one the stand runs>")
    return str(cfg.get("app_root") or "."), ""


def has_checkout(cfg: dict, profile: str) -> bool:
    """Whether the config records a checkout this profile's stand can be compared with (t-224
    fork Q1). A repository that names the profile (`execution_profile_id`) and records no
    `local_path` is the profile's own gap: the OTHER repository's checkout is not a stand-in for
    it. With no repository naming the profile, any repository that records a path will do - the
    fallback `pick_checkout` has always had."""
    repos = [r for r in (cfg.get("implementation_repos") or []) if isinstance(r, dict)]

    def recorded(repo) -> bool:
        return isinstance(repo.get("local_path"), str) and bool(repo["local_path"].strip())
    own = [r for r in repos if profile and str(r.get("execution_profile_id") or "") == profile]
    return any(recorded(r) for r in (own or repos))


def compared_files(files: list, checkout) -> list:
    """The story's production files that exist in the local checkout: the ones the probe can
    compare. Pure filesystem; nothing here asks docker."""
    return [f for f in files if (Path(checkout) / f).is_file()]


NO_EXPECTED_REVISION = "no_expected_revision"   # `reason_code` of a checkout that names no commit (not a git repository, no commit)
DEVICE_UNREADY = "device_unready"               # `reason_code` of a device stand whose build could not be read (no device, tool, table)
NOT_APPLICABLE_REASON = "no changed file in this checkout"   # the probe's own words for `not_applicable`
# ...and the same fact as a FIELD (`reason_code`, profile_contract.NO_CHANGED_FILE): the gates that let a probe
# that does not apply through on any stand kind read the field, never these words (FR-12).
NO_DIFF_RECORDED = ("no implementation diff is recorded for this story, so there is nothing to "
                    "compare what the stand runs with")


def nothing_to_compare(checkout) -> str:
    """The one sentence for a story that changes nothing inside a profile's checkout (t-224, C4):
    the stand cannot be compared with files the story never touched, and saying "0 of the files
    differ" or asking which container serves them would be a question about nothing. The gate
    rehearsal and `--suggest --write --task-root` both say exactly this, and it carries the
    reason the probe itself gives (`not_applicable`, t-238 W4)."""
    return (f"the story changes nothing in `{checkout}` ({NOT_APPLICABLE_REASON}), so the probe "
            "does not apply here and there is nothing to compare what the stand runs with")


def why_nothing_to_compare(task_root, files: list, checkout, shown=None) -> str:
    """'' when the story has files of this checkout to compare; otherwise the ONE sentence that
    says why not. A story with no recorded diff is another fact than a story whose diff does not
    touch this checkout (t-238 W1: the first was reported as the second): `NO_DIFF_RECORDED`
    when no diff is on record, `nothing_to_compare` when one is and none of its files is here.
    `checkout` is where the files are looked for; `shown` is how the sentence writes it (the
    config's own spelling, not the resolved path of this machine)."""
    if compared_files(files, checkout):
        return ""        # a file of the checkout is in the diff, so a diff is on record
    return (nothing_to_compare(checkout if shown is None else shown)
            if diff_recorded(task_root) else NO_DIFF_RECORDED)


NOT_SHIPPED = "not part of the running application, and not in the container"   # the note of a compared file that is skipped (FB-8)


def _names(value) -> bool:
    """A list of non-empty strings: the shape of a pattern list, in the data and in the config."""
    import test_files
    return test_files._strings(value) is not None


def _pattern_hit(path: str, pattern: str) -> bool:
    """`fnmatch.fnmatchcase`; a pattern WITHOUT `/` matches the last segment of the path, one WITH `/` the whole path."""
    return fnmatch.fnmatchcase(path if "/" in pattern else path.rsplit("/", 1)[-1], pattern)


def non_runtime_files(paths, cfg) -> tuple:
    """(the set of `paths` that are not part of the running application, problems): the ONE reader of that fact (FB-8).

    Rows: the data block `non_runtime_files.patterns` of references/build-identity-methods.json, plus the config's
    `execution.non_runtime_files.also`; `execution.non_runtime_files.except` names patterns or paths that ARE part of
    the running application and wins over both. Grammar (case-sensitive, `\\` read as `/`): a pattern without `/`
    matches the last path segment, a pattern with `/` the whole diff path (`fnmatch.fnmatchcase`).

    Error direction: only toward "runtime" (a skipped file is a file not compared). A malformed `except`, a key that
    is not an object, or a data block that is absent or malformed: NO file is non-runtime. A malformed `also` is
    ignored. Each is a line in `problems`. A code file (`test_files.is_code_file`, else the extension floor) is
    never non-runtime, whatever a row says. An absent or null key, or empty lists: the data rows alone."""
    problems = []
    block = SI.data().get("non_runtime_files")
    rows = block.get("patterns") if isinstance(block, dict) else None
    if not _names(rows):
        return set(), ["the list `non_runtime_files.patterns` of build-identity-methods.json is absent or malformed"]
    execution = cfg.get("execution") if isinstance(cfg, dict) else None
    word = execution.get("non_runtime_files") if isinstance(execution, dict) else None
    also, spared = [], []
    if word is not None:
        if not isinstance(word, dict):
            return set(), ["`execution.non_runtime_files` is not an object, so no file was set aside"]
        spared = word.get("except") if word.get("except") is not None else []
        if not _names(spared):
            return set(), ["`execution.non_runtime_files.except` is not a list of names, so no file was set aside"]
        also = word.get("also") if word.get("also") is not None else []
        if not _names(also):
            problems.append("`execution.non_runtime_files.also` is not a list of names, so it was ignored")
            also = []
    import test_files
    found = set()
    for path in paths:
        if not isinstance(path, str) or not path:
            continue
        norm = path.replace("\\", "/")
        code = test_files.is_code_file(norm)
        if code is None:
            code = os.path.splitext(norm.rsplit("/", 1)[-1])[1].lower() in test_files.CODE_EXTENSION_FLOOR
        if code or any(_pattern_hit(norm, p.replace("\\", "/")) for p in spared):
            continue
        if any(_pattern_hit(norm, p.replace("\\", "/")) for p in [*rows, *also]):
            found.add(path)
    return found, problems


def content_candidates(files: list, checkout: Path, app_root: str, running: list,
                       timeout: int = 20, cfg=None) -> list:
    """The running containers that could be the stand, by CONTENT: a container is a candidate
    only when EVERY compared RUNTIME file exists in it, under `app_root` (t-218, C3). A file that is not part of the
    running application (`non_runtime_files`) is not asked for; when EVERY compared file is of that kind a container
    is a candidate when it holds ANY of them, and when none does the result is `[]` (a person is never asked which
    container serves a compare of nothing). `cfg` None reads the project's config as `main` does.

    The compared files are the story's production files that exist in the local checkout (the
    ones the probe compares). One `docker exec ... sha256sum <all files>` per container: a
    missing file fails it, which is the whole test. A container that does not answer is not a
    candidate. With nothing to compare every container is one - the caller cannot tell them
    apart. A CALLER that reaches this with nothing to compare has already lost: it must ask
    `compared_files` first and say `nothing_to_compare` (t-224, C4: the gate rehearsal did not,
    and raised a false ambiguity card). A stand that serves a BUILT bundle (an nginx image with
    no sources under `app_root`) is a candidate of nothing: zero, which is a fact about the
    stand and never a reason to ask anyone (F3d)."""
    compared = compared_files(files, checkout)
    if not compared:
        return [name for name, _image in running]
    skipped, problems = non_runtime_files(compared, hooklib.load_config() or {} if cfg is None else cfg)
    if problems:
        warn("; ".join(problems))      # as rung_sources does: a broken word is said, and no file is set aside
    asked = [f for f in compared if f not in skipped]
    found = []
    for name, _image in running:
        try:
            done = subprocess.run(["docker", "exec", name, "sha256sum",
                                   *[f"{app_root}/{f}" for f in (asked or compared)]],
                                  capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            continue
        held = len([ln for ln in done.stdout.splitlines() if ln.strip()])
        if (done.returncode == 0 and held == len(asked)) if asked else held >= 1:
            found.append(name)
    return found


# What a sentence says when docker said nothing: never an exit code - the gate quotes these sentences to a person, and an
# exit code is the script's answer, not a fact about the story (FR-6, human-text.json `exit_code`; t-345 R8).
NO_MESSAGE = "it gave no message"
NOT_IN_CONTAINER = "not in the container"   # the note of a comparison whose file the container does not hold (t-345 F2)
GIT_SHA_RE = re.compile(r"[0-9a-f]{40}")
IMAGE_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
# The default label, the default build-sha path, the limits and every outcome sentence are DATA
# (references/build-identity-methods.json, FR-13); nothing about a project's way of building lives here.
# The Dockerfile remedy this module used to print is retired: the remedy now names the label and the registry.


def run_command(argv: list, timeout: int) -> tuple:
    """(returncode, stdout, stderr) of one command. THE ONE PLACE the image path asks docker, so a test (or
    any caller without docker) replaces this function and nothing else; a command that cannot start or does
    not finish in time raises OSError / TimeoutExpired, which the callers turn into `unknown`."""
    done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)
    return done.returncode, done.stdout, done.stderr


def rehearsal_argv(argv, task_root=None) -> list:
    """The probe's argv as a REHEARSAL runs it: `--no-evidence` appended, once - and ONLY to this script (S6).

    A rehearsal (gate A's identity read, the S6 freshness read, the build check, the onboarding verification run)
    compares and writes nothing (FR-45). The flag is this script's own: a project's own probe script is never
    handed a flag it does not know (AE16) - it may write its own evidence under a rehearsal, a debt the report
    names and does not hide. The script is recognised by its BASENAME (`runtime_probe.py`, whatever the
    interpreter and the path) in the three places the factory's own spellings put it - argv[0] (run directly), argv[1]
    (`python <path>`), argv[2] after `-B` (`python -B <path>`; t-345 F7) - so `my_runtime_probe.py` is a foreign script.
    ERROR DIRECTION: toward
    not appending. An argv this does not recognise comes back as it came; one that already carries the flag is
    returned as it is (idempotent).

    `task_root`, when the caller knows the story, is added as `--task-root` (before the flag) unless the argv names
    one: without it the probe falls back to the newest pipeline of the project (`planning_contract.running_story`),
    and another story's diff - or another story's confirmation - could be what it reads."""
    if not isinstance(argv, (list, tuple)):
        return argv
    items = list(argv)

    def ours(token) -> bool:
        return isinstance(token, str) and token.replace(chr(92), "/").rsplit("/", 1)[-1] == "runtime_probe.py"
    # Where the factory's own spellings put the script (t-345 F7): argv[0] (the script run directly), argv[1] (`python <path>`),
    # argv[2] after `-B` (`python -B <path>`, the form a committed probe is run with). Invariant: a script that is not ours -
    # whatever else the argv says - never gets the flag, so the positions are listed, not searched.
    here = (items and ours(items[0])) or (len(items) > 1 and ours(items[1])) \
        or (len(items) > 2 and items[1] == "-B" and ours(items[2]))
    if not here or "--no-evidence" in items:
        return items
    if task_root and "--task-root" not in items:
        items += ["--task-root", str(task_root)]
    return items + ["--no-evidence"]


def shown(value) -> str:
    """A value read from a stand, as a person may read it in a sentence: whitespace folded, cut at the limit
    (value_chars, data), quoted. The cut is the whole story: the value itself is in the record's `build_sha`."""
    return repr(" ".join(str(value).split())[:int(SI.limit("value_chars"))])


def quoted_error(text) -> str:
    """The first stderr_chars (data) characters of what a command said, whitespace folded."""
    return " ".join(str(text).split())[:int(SI.limit("stderr_chars"))]


def docker_failure(code, text) -> str:
    """What a failed `docker exec` means, from its exit code and what docker said (t-345 F2; the markers and the exit codes are
    data, references/build-identity-methods.json `docker_failures`, FR-13): 'down' (the daemon is unreachable, or the container
    is not running: nobody can answer it - E17), 'tool' (the image has no shell or no tool in it, a distroless one: it says
    nothing about the build, and the next rung must run), 'file' (the file asked for is not in the container) or 'other' (not
    classified: the caller keeps its old road). ORDER is the invariant: `down` is looked at first, so a container that is not
    running is never read as a missing tool whatever the exit code says; `tool` before `file`, so a missing binary is never
    read as a missing file. Case and whitespace do not matter."""
    spec = SI.data().get("docker_failures") or {}
    low = " ".join(str(text or "").split()).lower()
    if any(marker in low for marker in spec.get("down", [])):
        return "down"
    if code in spec.get("tool_missing_codes", []) or any(marker in low for marker in spec.get("tool_missing", [])):
        return "tool"
    if any(marker in low for marker in spec.get("file_missing", [])):
        return "file"
    return "other"


def say(key: str, **slots) -> str:
    """One outcome sentence of references/build-identity-methods.json (data, FR-13) with its slots filled."""
    return SI.data()["outcomes"][key].format(**slots)


def cap_tried(tried: list) -> tuple:
    """(kept, more): at most `limits.tried` (data) items of what was tried, and how many more there were. No
    truncation hides a rung without saying how many it hid (LE1)."""
    keep = int(SI.limit("tried"))
    return list(tried[:keep]), max(0, len(tried) - keep)


def warn(text: str) -> None:
    print(f"runtime_probe: {text}", file=sys.stderr)


class Reading:
    """One probe run's reading of what a stand runs (t-300): the ladder of the module docstring, with the record
    it fills. Every docker and git call goes through `run_command`; the content compare goes through
    `sha_container`; nothing else here asks the outside world, so a test replaces those two functions and nothing
    more. Never raises for what a stand or a person's way can do: that is an `unknown` with its reason."""

    def __init__(self, ns, record: dict, *, root, task_root, checkout, expected: str, files: list,
                 has_diff: bool, now: str, cfg: dict, story_stand: str = ""):
        self.ns, self.record = ns, record
        self.root, self.task_root, self.checkout = Path(root), Path(task_root), Path(checkout)
        self.expected, self.files, self.has_diff, self.now = expected, files, has_diff, now
        # Rung 1: the stand is the story's own (`pipeline.json` `environment`), else the argv's. Docker rungs are
        # allowed only when the two agree: a container observed for stand A never answers for stand B (E16).
        stand = story_stand or ns.environment
        # EP1-41e: a `--environment` that names a DEVICE stand is the stand this probe reads, whatever the story's own stand is (a
        # mixed project: the story stands on the API stand, this profile's tests run on the device). The device has no container.
        self.device = bool(ns.environment) and is_device_stand(cfg, ns.environment)
        self.device_failed = False
        if self.device:
            stand = ns.environment
        self.cfg, self.stand, self.profile = cfg, stand, ns.profile
        self._kind = ""
        self.tried: list = []
        self.docker_ok = bool(ns.container)
        self.docker_down = False
        self.command_failed = False
        self.stopped = False            # unknown for a reason no person can answer (no question)
        self.digest = None
        self.digest_read = False
        self.app_present: dict = {}
        self.sha_read = ""              # a 40-hex value read from the stand, whether or not it is a commit
        self.discover = None            # (method, parameter) of a DEFAULT rung that read a commit
        self.row = None
        self.registry_state = None
        self._candidate = False
        self.definition = SI.definition_sha_for(cfg, stand)
        self.missing = SI.in_config(cfg, stand, ns.profile)    # '' when the stand and the profile are in config
        self.docker_ok = bool(ns.container) and not self.device
        if self.device:
            self.read_device_build()
        elif ns.container and story_stand and ns.environment and story_stand != ns.environment:
            self.docker_ok = False
            self.note("docker", "docker.other_stand")
        elif not ns.container:
            self.note("docker", "docker.no_container")

    # -- bookkeeping --------------------------------------------------------------------------------

    def note(self, method: str, key: str, **slots) -> str:
        outcome = say(key, **slots)
        self.tried.append({"method": method, "outcome": outcome})
        return outcome

    def down(self, why: str) -> None:
        """Docker did not answer: every docker rung that follows is skipped, and the end is no question (E17)."""
        self.docker_down, self.docker_ok = True, False
        self.note("docker", "docker.unreachable", why=why or "no reason given")

    def candidate(self):
        """The person's word for THIS story and this stand and profile (rung 7), read once."""
        if self._candidate is False:
            self._candidate = None
            if not self.missing:
                problems: list = []
                self._candidate = SI.task_confirmation(self.task_root, self.stand, self.profile, problems)
                for line in problems:
                    warn(line)
        return self._candidate

    # -- the device read (EP1-41e) --------------------------------------------------------------------

    def device_stop(self, line: str) -> None:
        """The build on the device could not be read: `unknown` for a reason no answer of a person can mend, so no question and no
        word is taken (INVARIANT: a word is never bound to a build nobody read - with no digest, an earlier word that names `image:
        absent` would pass `binding` on the next build). `run` ends at once; the line is the record's `error`."""
        self.stopped = self.device_failed = True
        self.record["error"] = line
        self.record["reason_code"] = DEVICE_UNREADY         # a FIELD for the capture's refusal (FR-12): the device halt, never "capture again"

    def read_device_build(self) -> None:
        """Rung 0 for a device stand, before the ladder: the device (`device_stand.pick_device`, never the first of several), then the
        build it holds (`device_stand.installed_build`: app id, version, code and the hash of the installed file). The digest is
        sha256 of the WHOLE value, so a new version, a new code or a new file is another digest, and the word of a person, which
        binds to `image:<digest>` (`binding`), is voided by any of them. A version is never a revision: `sha_read` is not set here,
        so `matched` is out of reach; a `command` row of the registry stays the door of a project whose build knows its commit.
        Never raises: a factory table that cannot be used is the record's `error`, like any state that cannot be read."""
        record = self.record
        record["device_stand"] = True
        try:
            import device_stand as DS
            import surfaces
            stand = next(e for e in self.cfg.get("environments") or [] if isinstance(e, dict) and e.get("name") == self.stand)
            row = surfaces.row_of(stand)
            picked = DS.pick_device(row, stand, os.environ)
            if picked["state"] != "picked":
                return self.device_stop(picked["line"])
            app = stand.get("app") if isinstance(stand.get("app"), dict) else {}
            built = DS.installed_build(row, picked["serial"], app.get("id"))
        except (ValueError, StopIteration) as exc:
            return self.device_stop(" ".join(str(exc).split()) or "the device stand could not be described")
        if built["state"] == "no_method" and isinstance(row.get("installed_build"), dict):
            return self.device_stop(built["line"])          # the row CAN read a build; what is asked of it is wrong (an app id)
        if built["state"] in ("not_installed", "tool_error"):
            return self.device_stop(built["line"])
        if built["state"] == "read" and not built["version"]:
            return self.device_stop(f"the device names no version for {app.get('id')}, so the installed build is not known")
        if built["state"] != "read":
            return None                                      # no_method: nothing to bind a word to; the question is asked as before
        record["observed_device_build"] = built["line"]
        if built["limitation"]:
            record["limitation"] = built["limitation"]
        self.digest = "sha256:" + hashlib.sha256(built["value"].encode("utf-8")).hexdigest()

    # -- the docker reads -----------------------------------------------------------------------------

    def read_digest(self):
        """`sha256:<64 hex>` of the image the container runs, or None (docker is then `down`, or it named no image).
        One call per run, however many rungs ask."""
        if self.digest_read:
            return self.digest
        self.digest_read = True
        if not self.docker_ok:
            return None
        try:
            code, out, err = run_command(["docker", "inspect", "--format", "{{.Image}}", self.ns.container],
                                         self.ns.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.down(exc.__class__.__name__)
            return None
        if code != 0:
            self.down(quoted_error(err or out) or NO_MESSAGE)
            return None
        text = out.strip()
        if not IMAGE_DIGEST_RE.fullmatch(text):
            self.note("docker", "docker.no_digest", container=self.ns.container, why=shown(text))
            return None
        self.digest = text
        return text

    def has_app(self, app_root: str):
        """True / False when docker POSITIVELY says `app_root` is / is not a directory in the container (`test -d`
        exits 0, or exits 1 with nothing on stderr); None when it could not tell, and WHY decides what follows
        (t-345 F2, `docker_failure`): a stopped container, a daemon that does not answer, a timeout or an exit nobody
        classified is `down` (E17: no question, never an identity claim built on a container nobody looked inside);
        a missing `test` (a distroless image: exit 126/127) is only "the sources could not tell" - docker answered, the
        label rung still runs, and the person can still be asked how."""
        if app_root in self.app_present:
            return self.app_present[app_root]
        result = None
        if self.docker_ok:
            try:
                code, _out, err = run_command(["docker", "exec", self.ns.container, "test", "-d", app_root],
                                              self.ns.timeout)
            except (OSError, subprocess.TimeoutExpired) as exc:
                self.down(exc.__class__.__name__)
            else:
                if code == 0:
                    result = True
                elif code == 1 and not err.strip():
                    result = False
                elif docker_failure(code, err) == "tool":
                    self.note("sources", "sources.tool_missing", container=self.ns.container,
                              why=quoted_error(err) or NO_MESSAGE)
                else:
                    self.down(quoted_error(err) or NO_MESSAGE)
        self.app_present[app_root] = result
        return result

    def read_label(self, label: str) -> tuple:
        """(value, kind) of one label of the IMAGE (never the container's: a container's labels merge its image's)."""
        digest = self.read_digest()
        if digest is None:
            return None, "docker"
        try:
            code, out, err = run_command(["docker", "image", "inspect", digest, "--format", "{{json .Config.Labels}}"],
                                         self.ns.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.note("oci_label", "oci_label.unreadable", container=self.ns.container, why=exc.__class__.__name__)
            return None, "failed"
        if code != 0:
            self.note("oci_label", "oci_label.unreadable", container=self.ns.container,
                      why=quoted_error(err or out) or NO_MESSAGE)
            return None, "failed"
        try:
            labels = json.loads(out.strip() or "null")
        except ValueError:
            self.note("oci_label", "oci_label.unreadable", container=self.ns.container, why="not JSON")
            return None, "failed"
        labels = {} if labels is None else labels
        if not isinstance(labels, dict):
            self.note("oci_label", "oci_label.unreadable", container=self.ns.container, why="not a map of labels")
            return None, "failed"
        if labels.get(label) is None:
            self.note("oci_label", "oci_label.no_label", container=self.ns.container, label=label)
            return None, "absent"
        return str(labels[label]), "value"

    def read_file(self, path: str) -> tuple:
        if not self.docker_ok:
            return None, "docker"
        try:
            code, out, err = run_command(["docker", "exec", self.ns.container, "cat", path], self.ns.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.note("build_sha_file", "build_sha_file.missing", path=path, container=self.ns.container,
                      why=exc.__class__.__name__)
            return None, "failed"
        if code != 0:
            if docker_failure(code, err) == "down":
                # a container that is not running is E17 here as it is at `test -d`: not a file that is absent (t-345 F2)
                self.down(quoted_error(err) or NO_MESSAGE)
                return None, "docker"
            self.note("build_sha_file", "build_sha_file.missing", path=path, container=self.ns.container,
                      why=quoted_error(err or out) or "unreadable")
            return None, "absent"
        if len(out.encode("utf-8", "replace")) > int(SI.limit("output_bytes")):
            self.note("build_sha_file", "build_sha_file.too_long", path=path, limit=SI.limit("output_bytes"))
            return None, "garbage"
        return out, "value"

    def read_command(self, argv: list) -> tuple:
        try:
            code, out, err = run_command([str(a) for a in argv], self.ns.timeout)
        except subprocess.TimeoutExpired:
            self.note("command", "command.timeout")
            return None, "failed"
        except OSError as exc:
            self.note("command", "command.not_found", why=quoted_error(exc))
            return None, "failed"
        if code != 0:
            self.note("command", "command.failed", code=code, why=quoted_error(err or out) or "no reason given")
            return None, "failed"
        if len(out.encode("utf-8", "replace")) > int(SI.limit("output_bytes")):
            self.note("command", "command.too_long", limit=SI.limit("output_bytes"))
            return None, "garbage"
        return out, "value"

    # -- rung 6: the verdict of a value -------------------------------------------------------------

    def judge(self, method: str, value: str, **slots) -> str:
        """`matched`, `mismatched`, `unknown` (a 40-hex value that is no commit of the checkout, or an expected
        revision that cannot be compared with it) or `garbage` (not a 40-hex commit at all; the outcome is noted).
        ERROR DIRECTION: toward `unknown`. `mismatched` needs a value that is itself a commit of THIS checkout
        (`git cat-file -e <value>^{commit}`): a sha of nowhere, an abbreviation, an upper-case spelling or a
        41-character value is never proof that the stand runs another commit of this repository (E10, LE5)."""
        text = value.strip()
        if not GIT_SHA_RE.fullmatch(text):
            self.note(method, f"{method}.not_sha", value=shown(value), **slots)
            return "garbage"
        self.record["build_sha"] = text
        if not GIT_SHA_RE.fullmatch(self.expected or ""):
            self.record["error"] = say("expected.not_full_sha", expected=shown(self.expected or "unknown"))
            self.stopped = True
            return "unknown"
        if text == self.expected:
            return "matched"
        try:
            code, _out, _err = run_command(["git", "-C", str(self.checkout), "cat-file", "-e", f"{text}^{{commit}}"],
                                           self.ns.timeout)
        except (OSError, subprocess.TimeoutExpired):
            code = 1
        if code == 0:
            return "mismatched"
        self.sha_read = text
        self.note(method, "value.not_a_commit", value=shown(text))
        return "unknown"

    # -- the identity a sha method records ------------------------------------------------------------

    def identity_of(self, text: str) -> str:
        digest = self.read_digest() if self.docker_ok else self.digest
        return f"image:{digest}" if digest else f"revision:{text}"

    def sha_record(self, result: str, text: str) -> None:
        """matched / mismatched by a value that names a commit: the exact linkage, never `matched` from a digest."""
        self.record.update({
            "observed_runtime_identity": self.identity_of(text), "result": result, "build_sha": text,
            "provenance": {"technical_verification": True, "source_linkage": "exact", "identity_kind": self._kind,
                           "deployed_source_revision": text, "verified_source_revisions": [self.expected]}})

    # -- the rungs -------------------------------------------------------------------------------------

    def rung_sources(self, app_root: str, named: bool) -> str:
        """Rung 3. 'final' (a verdict, or a compare that failed), or 'next'. `named`: a registry row asked for it."""
        if not self.has_diff:
            if named:
                self.note("sources", "sources.no_diff")
            return "next"
        if not self.docker_ok:
            return "next"
        present = self.has_app(app_root)
        if present is None:
            return "next"
        if not present:
            self.note("sources", "sources.no_app_root", app_root=app_root)
            return "next"
        ns, record, checkout = self.ns, self.record, self.checkout
        non_runtime, problems = non_runtime_files(self.files, self.cfg)
        if problems:
            warn("; ".join(problems))
            record["non_runtime_problem"] = "; ".join(problems)
        comparisons = []
        try:
            for name in self.files:
                local = checkout / name
                if not local.is_file():
                    comparisons.append({"file": name, "container_sha256": None, "local_sha256": None,
                                        "note": "no local file"})
                    continue
                try:
                    container_sha = sha_container(ns.container, f"{app_root}/{name}", ns.timeout)
                except RuntimeError as exc:
                    if docker_failure(getattr(exc, "code", None), getattr(exc, "stderr", None) or str(exc)) != "file":
                        raise
                    # A file the story adds that was never deployed: the container's files are NOT the story's, which is
                    # a content mismatch naming the file - a person redeploys (t-345 F2), not a silence.
                    comparisons.append({"file": name, "container_sha256": None, "local_sha256": sha_local(local),
                                        "note": NOT_IN_CONTAINER})
                    continue
                comparisons.append({"file": name, "container_sha256": container_sha, "local_sha256": sha_local(local)})
        except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
            # The compare itself failed, and WHY decides what follows (t-345 F2, `docker_failure`).
            kind = docker_failure(getattr(exc, "code", None), getattr(exc, "stderr", None) or str(exc)) \
                if isinstance(exc, RuntimeError) else "other"
            if kind == "down":      # the daemon went away or the container stopped: E17, nobody can answer it
                self.down(quoted_error(getattr(exc, "stderr", None) or exc))
                return "next"
            if kind == "tool":      # no `sha256sum` in the image: the sources could not tell, the label rung still runs
                self.note("sources", "sources.tool_missing", container=ns.container,
                          why=quoted_error(getattr(exc, "stderr", None) or exc))
                return "next"
            # Anything else: the container HAS sources and the compare failed for a reason nobody classified: its own
            # error, never an image identity and never a label that could be stale (AE2).
            self.note("sources", "sources.compare_failed", container=ns.container, why=quoted_error(exc))
            record["error"] = str(exc)[:300]
            record["comparisons"] = comparisons
            self.stopped = True
            return "final"
        return self._sources_verdict(comparisons, app_root, non_runtime)

    def _sources_verdict(self, comparisons: list, app_root: str, non_runtime: set) -> str:
        """The part of rung 3 after the compare: 'final' (a verdict) or 'next' (the files could not tell)."""
        ns, record = self.ns, self.record
        # FB-8: a file absent from the container that is not part of the running application is RECORDED and not compared.
        for c in comparisons:
            if c.get("note") == NOT_IN_CONTAINER and c["file"] in non_runtime:
                c["note"] = NOT_SHIPPED
        not_shipped = [c["file"] for c in comparisons if c.get("note") == NOT_SHIPPED]
        if not_shipped:
            record["not_shipped_files"] = not_shipped
        absent = [c for c in comparisons if c.get("note") == NOT_IN_CONTAINER]
        present = any(c.get("container_sha256") for c in comparisons)
        if not_shipped and not absent and not present:
            # zero compared runtime bytes is never `matched` and never `content_mismatch`
            self.note("sources", "sources.only_non_runtime")
            return "next"
        # t-357 F2a: a file missing in the container is a difference only when the container proves the folder is the app's
        # (some compared file IS there, a non-runtime one too) or the file is one the story ADDS (`--- /dev/null`). Every
        # compared file missing and none of them new says the folder searched is the wrong one (a wrong `--app-root`), never
        # that the build is stale: the rung could not tell, the label rung still runs and a person can still be asked how.
        if absent and not present:
            added = set(diff_new_files(self.task_root))
            if not any(c["file"] in added for c in absent):
                self.note("sources", "sources.compare_failed", container=ns.container,
                          why=f"none of its {len(absent)} file(s) is under `{app_root}` there, so `{app_root}` may not be "
                              "the folder the application runs from")
                return "next"
        # a file missing in the container is compared too: it is a difference, and the one the story's own diff names
        seen = [c for c in comparisons if c.get("container_sha256") or c.get("note") == NOT_IN_CONTAINER]
        matched = bool(seen) and all(c["container_sha256"] == c["local_sha256"] for c in seen)
        record.update({
            "observed_runtime_identity": "verified_content:" + "|".join((c["container_sha256"] or "absent")[:12] for c in seen),
            "provenance": {"technical_verification": True, "source_linkage": "verified_content",
                           "deployed_source_revision": self.expected if matched else "content_mismatch",
                           "verified_source_revisions": [self.expected]},
            "result": "matched" if matched else "mismatched", "comparisons": comparisons})
        if not matched:
            differing = [c["file"] for c in seen if c["container_sha256"] != c["local_sha256"]]
            record["differing_files"] = differing
            # FB-8: the fingerprint of EXACTLY the bytes this verdict stands on, and the image that held them: what a
            # person's `test as is` word binds to (a `matched` record gets neither)
            identity = content_identity(seen)
            record["content_identity"] = identity
            digest = self.read_digest()
            if digest:
                record["observed_image"] = f"image:{digest}"
            # positional invariant: only AFTER the verdict, only on a mismatch - no word stands in for a compare that did not happen
            self.lift_content(identity, differing)
        return "final"

    def conclude(self, method: str, value, kind: str, named: bool, **slots) -> str:
        """What a rung that READ something decides. 'final': the ladder has its answer. 'next': the rung had none
        (a failure of a way a person gave, or nothing there). A value that is no commit at all - at a default rung as
        at a person's own way - is "this rung could not tell" (t-345 F8, FR-50: every route before a question): the next
        rung runs, `tried` keeps the rung and the value it held (judge notes it), and only when nothing answers is the
        person asked (`nothing_answered`, which still gives a `deployed` word its turn)."""
        if kind in ("docker", "absent", "failed"):
            return "next"
        verdict = "garbage" if kind == "garbage" else self.judge(method, value, **slots)
        if verdict == "garbage":
            return "next"
        self._kind = method
        if verdict == "unknown":
            if not self.stopped:
                self.lift(self.sha_read, mismatched=False)   # voids a word that names another build (rung 7)
            return "final"
        text = value.strip()
        if not named and method in ("oci_label", "build_sha_file"):
            self.discover = (method, slots.get("label") or slots.get("path"))
        if verdict == "matched":
            self.sha_record("matched", text)
            return "final"
        self.sha_record("mismatched", text)
        self.sha_read = text
        self.lift(text, mismatched=True)
        return "final"

    def try_method(self, row: dict) -> str:
        """Rung 2: the person's way for this stand, tried FIRST. 'final' or 'next' (the way failed)."""
        method = row["method"]
        if method == "sources":
            return self.rung_sources(row.get("app_root") or self.ns.app_root, named=True)
        if method == "oci_label":
            label = row.get("label") or SI.default_of("oci_label")
            value, kind = self.read_label(label)
            return self.conclude(method, value, kind, True, label=label)
        if method == "build_sha_file":
            value, kind = self.read_file(row["path"])
            return self.conclude(method, value, kind, True, path=row["path"])
        value, kind = self.read_command(row["argv"])
        if kind != "value" or not GIT_SHA_RE.fullmatch((value or "").strip()):
            self.command_failed = True
        return self.conclude("command", value, kind, True)

    def run(self) -> None:
        """Rungs 1 to 8: fills the record. Rung 9 (the writes) is `finish`."""
        ns = self.ns
        if self.device_failed:
            return          # EP1-41e: the device build was not read - no registry row, no word, no question (`device_stop`)
        state = SI.state(self.root)
        self.registry_state = state
        if state["file_error"]:
            self.record["registry_error"] = state["file_error"]
            warn(state["file_error"])
        for problem in state["errors"]:
            warn(f"ignored registry row: {problem}")
        row = None if self.missing else state["in_force"].get((self.stand, self.profile))
        if row and row["method"] == "person_confirms" and row.get("stand_definition_sha") \
                and row["stand_definition_sha"] != self.definition:
            # A decision given for another stand definition never counts (AE7): the row is not in force, the
            # defaults run, and the record says what moved so the question can say it.
            self.record["voided"] = {"what": SI.data()["voided"]["definition"], "earlier_at": row["recorded_at"]}
            row = None
        self.row = row
        if row and row["method"] == "person_confirms":
            return self.confirmed_by_row()
        failed = ""
        sources_done = False
        if row:
            if row["method"] == "oci_label":
                # t-366 O1 (AE2 holds for a person's label too): their `label` way joins the ladder AT the label rung, AFTER
                # the sources - never before them. A stale label on a hot-reloaded container must not outrank content the
                # sources rung can compare; when it can and the files differ, that verdict stands (`content_mismatch`) and
                # the person's label is not consulted. Their `file` and `command` ways keep their place (PE3: their own
                # reading of the stand); a `sources` row IS the sources rung.
                sources_done = True
                if self.rung_sources(ns.app_root, named=False) == "final":
                    return
            if self.try_method(row) == "final":
                return
            failed = row["method"]
            self.record["registry_method_failed"] = self.tried[-1]["outcome"] if self.tried else ""
        for rung in SI.data()["ladder"]:
            if rung == failed or (rung == "sources" and sources_done):
                continue
            if rung == "sources":
                result = self.rung_sources(ns.app_root, named=False)
            elif rung == "oci_label":
                label = SI.default_of("oci_label")
                value, kind = self.read_label(label)
                result = self.conclude(rung, value, kind, False, label=label)
            else:
                path = SI.default_of("build_sha_file")
                value, kind = self.read_file(path)
                result = self.conclude(rung, value, kind, False, path=path)
            if result == "final":
                return
        self.nothing_answered()

    # -- rung 7: the person's word for this story --------------------------------------------------------

    def binding(self, cand: dict, mismatched: bool) -> tuple:
        """('ok',) | ('void', key, slots) | ('down',): does this word STILL hold for the build on the stand now?
        A word binds to the stand's definition, to the revisions it names and, when it names one, to the image the
        stand runs. ERROR DIRECTION: toward not lifting - anything that moved, or cannot be read, voids it."""
        if cand["stand_definition_sha"] != self.definition:
            return ("void", "definition", {})
        if cand["kind"] == "deployed":
            if cand["revision"] != self.expected:
                return ("void", "checkout", {"short": self.expected[:12]})
            if self.sha_read and self.sha_read != self.expected:
                return ("void", "build_read", {"short": self.sha_read[:12]})
        else:
            if cand.get("story_revision") != self.expected:
                return ("void", "checkout", {"short": self.expected[:12]})
            if not mismatched or not self.sha_read:
                return ("void", "deployed_unreadable", {})
            if cand["revision"] != self.sha_read:
                return ("void", "build_read", {"short": self.sha_read[:12]})
        if cand.get("image") != "absent":
            digest = self.read_digest() if self.docker_ok else self.digest
            if digest is None:
                return ("down",) if self.docker_down else ("void", "image_unreadable", {})
            if f"image:{digest}" != cand["image"]:
                return ("void", "image", {})
        return ("ok",)

    def lift(self, sha_read: str, mismatched: bool) -> bool:
        """Rung 7 (F1): True when the person's word for this story binds and the record is now `person_confirmed`.
        `unknown` + a `deployed` word; `mismatched` (a commit D of the checkout was read) + a `test_deployed` word that
        names D and this story's commit. A plain `deployed` never lifts a proven `mismatched`. A `content_mismatch` never
        reaches here (the sources rung has no sha to name): `lift_content` lifts it, for the `content_accepted` word only."""
        cand = self.candidate()
        if cand is None or cand["kind"] == "content_accepted":      # that word is `lift_content`'s, and it never voids here
            return False
        if not mismatched and cand["kind"] == "test_deployed":
            return False
        # `binding` is the ONE place that decides a plain `deployed` word cannot hold once another build was read (it
        # names the build in `voided`): a sha read that is not HEAD voids a `deployed` word, mismatched or not
        status = self.binding(cand, mismatched)
        if status[0] == "void":
            self.record["voided"] = {"what": SI.data()["voided"][status[1]].format(**status[2]),
                                     "earlier_at": cand["at"]}
            return False
        if status[0] == "down":
            return False
        self.confirm_record(cand)
        return True

    def lift_content(self, identity: str, differing: list) -> bool:
        """Rung 7 for the `content_accepted` word (FB-8): True when the person's `test as is` binds to THESE bytes and the
        record is now `person_confirmed`. Called by `_sources_verdict` after the verdict, on a mismatch only. It lifts that
        word and no other (a `deployed` word never saw the files). The checks run in the order of `binding()`: stand
        definition, this story's commit, the content, the image when the word names one; the first that fails names the
        `voided` reason. ERROR DIRECTION: toward not lifting - anything that moved, or cannot be read, voids it."""
        cand = self.candidate()
        if cand is None or cand["kind"] != "content_accepted":
            return False
        reason = None
        if cand["stand_definition_sha"] != self.definition:
            reason = "definition"
        elif cand["revision"] != self.expected:
            reason = "checkout"
        elif cand.get("content") != identity:
            reason = "content"
        elif cand.get("image") != "absent":
            observed = self.record.get("observed_image")
            if observed is None and self.docker_down:
                return False
            reason = None if observed == cand["image"] else ("image" if observed else "image_unreadable")
        if reason:
            self.record["voided"] = {"what": SI.data()["voided"][reason].format(short=self.expected[:12]),
                                     "earlier_at": cand["at"]}
            return False
        self.read_digest()
        self.confirm_record(cand)
        return True

    def confirm_record(self, cand: dict) -> None:
        digest = self.digest
        record = self.record
        provenance = {"technical_verification": False, "identity_kind": "person_confirmed"}
        confirmation = {"words": cand["words"], "at": cand["at"], "task": cand["task"], "kind": cand["kind"],
                        "revision": cand["revision"]}
        if cand.get("story_revision"):
            confirmation["story_revision"] = cand["story_revision"]
        if cand.get("content"):
            confirmation["content"] = cand["content"]
            record["accepted_files"] = list(record.get("differing_files") or [])
        if cand.get("image") not in (None, "absent"):
            confirmation["image"] = cand["image"]
        record.pop("differing_files", None)
        record.update({"result": "person_confirmed",
                       "observed_runtime_identity": f"image:{digest}" if digest else f"person-confirmed:{cand['at']}",
                       "provenance": provenance, "person_confirmation": confirmation})
        if cand["kind"] == "test_deployed":
            provenance["deployed_source_revision"] = cand["revision"]
            record["tested_build"] = cand["revision"]

    def confirmed_by_row(self) -> None:
        """Rung 2, `person_confirms`: the person said "I check this stand myself", so NOTHING is read - no label, no
        file, no sources, no command. Only the image digest is read, to BIND the word to the bytes it was given for
        (C5): it never detects. A valid word for this story -> `person_confirmed`; none, or one that moved ->
        `unknown` + `asks_person: confirm`. E17 wins over this question: docker that does not answer is not
        something to ask a person (the word cannot be bound, and nobody can fix it by answering)."""
        self.note("registry", "registry.person_confirms")
        if self.docker_ok:
            self.read_digest()
        cand = self.candidate()
        record = self.record
        if cand is None or cand["kind"] == "content_accepted":
            # a `content_accepted` word belongs to a content mismatch; nothing is read here, so it is asked plainly, as for no word
            if self.docker_down:
                self.stopped = True
            else:
                record["asks_person"] = "confirm"
        elif cand["kind"] == "test_deployed":
            # The build the person tested was a read of an earlier moment; nothing is read on this stand any more,
            # so it cannot be re-read now (S11): not lifted, and the word is `voided` with the reason.
            record["voided"] = {"what": SI.data()["voided"]["deployed_unreadable"], "earlier_at": cand["at"]}
            record["asks_person"] = "confirm"
        else:
            status = self.binding(cand, False)
            if status[0] == "ok":
                self.confirm_record(cand)
                return
            if status[0] == "void":
                record["voided"] = {"what": SI.data()["voided"][status[1]].format(**status[2]),
                                    "earlier_at": cand["at"]}
                record["asks_person"] = "confirm"
            else:
                self.stopped = True
        record["result"] = "unknown"

    def nothing_answered(self) -> None:
        """Rung 8, after rung 7 had its turn: no rung answered. `unknown`, what was tried, and the question 'how'."""
        if self.lift(self.sha_read, mismatched=False):
            return
        self.record["result"] = "unknown"

    # -- the end: rung 8's fields and rung 9's writes -------------------------------------------------------

    def finish(self) -> dict:
        record, ns = self.record, self.ns
        record["container"] = ns.container
        record["checkout"] = str(self.checkout)
        record.setdefault("comparisons", [])
        result = record.get("result")
        if result == "unknown":
            self.finish_unknown()
        elif result in ("matched", "mismatched", "person_confirmed"):
            self.write_evidence()
            if self.discover and result in ("matched", "mismatched") and not ns.no_evidence:
                self.write_discovered()
        return record

    def finish_unknown(self) -> None:
        record = self.record
        record["result"] = "unknown"
        digest = self.digest
        if digest:
            record["observed_runtime_identity"] = f"image:{digest}"
        record["provenance"] = {"technical_verification": False, **({"identity_kind": "image_digest"} if digest else {})}
        kept, more = cap_tried(self.tried)
        if kept:
            record["tried"] = kept
        if more:
            record["tried_more"] = more
        asks = record.get("asks_person")
        if not asks and not self.stopped and not (self.docker_down and not self.command_failed):
            asks = record["asks_person"] = "how"
        if asks == "how" and not self.device:       # the label of an image is no way to read a device's build (F-8)
            record["remedy"] = SI.data()["remedy"].format(label=SI.default_of("oci_label"))
        if "error" not in record:
            if self.device and record.get("observed_device_build"):
                record["error"] = (f"the build on the device was read ({record['observed_device_build']}), but nothing ties it to "
                                   "this story's commit: only a person can")
            elif self.device:
                record["error"] = "this surface has no way to read the build the device holds, so only a person can say which it is"
            elif self.docker_down and not self.command_failed:
                said = [t["outcome"] for t in self.tried if t["method"] == "docker"]
                record["error"] = ("which build the stand runs could not be read: "
                                   + ("; ".join(said) if said else "docker did not answer"))
            elif asks == "confirm":
                record["error"] = "you check the build of this stand yourself, and your word for this story is not there yet"
            elif self.stopped:
                record["error"] = "which build the stand runs could not be read"
            else:
                what = "; ".join(t["outcome"] for t in kept)
                record["error"] = ("which build the stand runs could not be read"
                                   + (f": {what}" if what else "")
                                   + (f"; and {more} more" if more else ""))
        if record.get("remedy"):
            warn(f"{record['error']}. {record['remedy']}.")

    def write_evidence(self) -> None:
        record, ns = self.record, self.ns
        if ns.no_evidence:
            record["evidence_refs"] = []
            record["observed_without_evidence"] = True
            return
        stamp = self.now.replace(":", "").replace("-", "").replace("+0000", "Z")
        evidence = self.task_root / "evidence" / f"runtime-provenance-{ns.profile}-{stamp}.json"
        record["evidence_refs"] = [evidence.as_posix()]
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(record, indent=2), encoding="utf-8")

    def write_discovered(self) -> None:
        """Rung 9: ONE `probe discovered` row when a default rung read a commit and the registry has no word for this
        stand and profile - re-checked under the writer lock, so a row that appeared meanwhile (or a `withdrawn` one:
        code never writes over a person's last word, S12) is not overwritten. Never from `unknown` (E10), never a
        `sources` row, never for a stand or profile the config does not name (E5), and never when the container holds
        `app_root`: a label must not outrank content the next time (AE2). A failure to write is one stderr line and
        never changes the verdict."""
        ns = self.ns
        if self.missing:
            return
        if self.registry_state["file_error"]:
            warn(f"the way to read this stand was not recorded: {self.registry_state['file_error']}")
            return
        if self.has_app(ns.app_root) is not False:
            return
        method, parameter = self.discover
        row = SI.make_row(self.cfg, self.stand, self.profile, method, source="probe discovered",
                          recorded_by="runtime_probe.py",
                          **({"label": parameter} if method == "oci_label" else {"path": parameter}))

        def nothing_known(found) -> bool:
            key = (self.stand, self.profile)
            return key not in found["in_force"] and key not in found["withdrawn"]
        try:
            written = SI.append_row(self.root, row, only_if=nothing_known)
        except SI.RegistryError as exc:
            warn(f"the way to read this stand was not recorded: {exc}")
            return
        if written is not None:
            warn(f"found how to read the build of the {self.profile} tests on stand `{self.stand}` "
                 f"({SI.method_words(row)}) and recorded it in {SI.registry_rel()} (written by the probe, not by a person)")


def portable_checkout(checkout, project_root) -> tuple:
    """(value, note): the checkout as `--suggest --write` STORES it, so a committed config means the same
    on every machine (B-253 z, t-298). A checkout is a place on THIS machine; the config is committed and
    cloned, and every reader (execution_request, manual_capture, this probe's own verification run) resolves
    a relative one from the PROJECT ROOT - so the stored form is relative to it.

      relative input    -> normalised, not resolved: backslashes to `/`, no leading `./`, no trailing `/`;
                           the project root itself is `.`, never "" (runtime_paths.normalise_project_path maps
                           `.` to "", which is right for a path compared with the layout and wrong here)
      absolute input    -> `os.path.relpath` to the project root, as POSIX; `..` is allowed (a sibling checkout
                           `../../testproject1` is portable); `.` when it is the root itself
      no relative form  -> (another drive, a network share: ValueError) stored AS GIVEN with a note, never
                           refused (P1): the person's checkout is not the factory's to veto; the note says what
                           follows (the next reinstall drops such an entry, audit A20 reports it) and what to do
      empty or blank    -> returned as it is, no note: there is nothing to normalise (`suggest` never passes one)

    No existence check (as before). realpath on both sides (t-319; before it abspath): a Windows 8.3 short name and
    its long spelling fold into one place, and a symlink or junction is looked through on BOTH sides, so a root and
    a checkout that sit behind the same link keep their real relation. Invariant, for
    every case but "no relative form": (project_root / value).resolve() is the place the caller named, and
    audit_factory._machine_local(value) is False, so the next migration keeps the probe."""
    text = str(checkout or "")
    if not text.strip():
        return text, ""
    drive = os.path.splitdrive(text)[0]
    if not (drive or text.startswith(("/", chr(92))) or os.path.isabs(text)):
        norm = runtime_paths.normalise_project_path(text)
        return norm or ".", ""
    try:
        # realpath on BOTH sides (t-319, B-260): an 8.3 short name (`DEV1~1`, a temp dir, a home folder) and its
        # long spelling are one place, and abspath kept them apart - the stored form came out `../../../DEV1~1/..`,
        # right on this machine and wrong on every other. No existence check: realpath resolves what exists and
        # keeps the rest as given.
        rel = os.path.relpath(os.path.realpath(text), os.path.realpath(str(project_root)))
    except ValueError:
        return text, (f"`{text}` is on another drive (or a network share) than this project, so it has no form relative to the "
                      "project and is stored as given. The next reinstall drops an entry that names a place on this machine "
                      "(audit A20 reports it); run `runtime_probe.py --suggest --write` again on the machine that runs the probe, "
                      "with a checkout beside the project")
    return rel.replace(os.sep, "/").replace(chr(92), "/"), ""


def is_device_stand(cfg: dict, environment: str) -> bool:
    """Does the environments[] row of this name drive a device (`surface` -> a `hands: driver` row)? False for a row with no
    `surface` (the table is not read). A row WITH a `surface` that the table cannot tell is True (F-9): the container road would
    bind a word to no image; the device read stops with the table's line instead."""
    rows = [e for e in (cfg.get("environments") or []) if isinstance(e, dict) and str(e.get("name") or "") == environment]
    if len(rows) != 1 or "surface" not in rows[0]:
        return False
    try:
        import surfaces
        return surfaces.is_device_row(surfaces.row_of(rows[0]))
    except ValueError:
        return True         # a row that names a `surface` with a table nobody can read is never taken for a container's: the device read then stops with the table's line (F-9)


def suggest(cfg: dict, project_root: Path, profile: str, environment: str, container: str,
            checkout: str, app_root: str, plugin_scripts: Path, no_container: bool = False) -> tuple:
    """(spec, refusal). The one thing the factory may not derive is WHICH container - everything
    else is in the project's own config. A refusal here is the single question P4 allows.
    The spec's argv is the PORTABLE form (`PORTABLE_HEAD`), never this machine's python or
    plugin path; `plugin_scripts` stays in the signature for the callers that pass it. The
    checkout in it is the PORTABLE form too (`portable_checkout`): what is printed is what is stored."""
    environment, refusal = pick_environment(cfg, environment, profile, SI.reference_of_running_story())
    if refusal:
        return None, refusal
    checkout, refusal = pick_checkout(cfg, profile, checkout)
    if refusal:
        return None, refusal
    if environment and is_device_stand(cfg, environment):
        # EP1-41c: a device stand runs the application on a device, never in a container: no container is asked of docker
        # (`containers()` is not called), the entry names none - the same entry `--no-container` writes
        no_container = True
    if not str(checkout or "").strip():
        # t-323 C3 (t-319 Q1): a blank checkout (`--checkout "  "`, or a repository whose `local_path` is blank) would
        # be stored as `--checkout "  "` and every reader would resolve it to the project root; it is a question, not a
        # value. (`--checkout ""` is the flag's own default - "not given" - and is derived from the config, as before.)
        return None, Refusal("--checkout is empty", "pass --checkout <path to the application checkout the stand runs>")
    checkout, _note = portable_checkout(checkout, project_root)     # the note is `do_suggest`'s to print
    if no_container:
        # EP1-28: the application does not run in a container (a host process): the entry names none, and no sources
        # root inside one. Placed AFTER the environment and checkout picks: an entry with no checkout is never written.
        # Without a container the probe cannot say `matched`; it asks the person (the build question).
        return {"argv": [*PORTABLE_HEAD, "--profile", profile, "--environment", environment or "local",
                         "--checkout", checkout],
                "cwd": ".", "timeout_s": 120}, ""
    if not container:
        running = containers()
        if not running:
            return None, Refusal("docker names no running container, so the stand cannot be "
                                 "identified by content",
                                 "Bring the stand up and run this again, or pass --container "
                                 "<name>, or --no-container if the application does not run in one", sep=". ")
        if len(running) > 1:
            return None, Refusal("more than one container is running: "
                                 + ", ".join(f"{n} ({i})" for n, i in running),
                                 "Which one runs the application under test? Pass --container "
                                 "<name>, or --no-container if the application does not run in one", sep=". ")
        container = running[0][0]
    spec = {"argv": [*PORTABLE_HEAD,
                     "--profile", profile, "--environment", environment or "local",
                     "--container", container, "--checkout", checkout, "--app-root", app_root],
            "cwd": ".", "timeout_s": 120}
    return spec, ""


def do_suggest(ns) -> int:
    """`--suggest`: the entry a project needs before its first typed run, derived instead of
    hand-written. `--write` stores it; an entry that already exists is left alone unless
    --force, because the person's config wins over discovery (P4)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hooklib
    project_root = Path(hooklib.project_root())
    cfg = hooklib.load_config() or {}
    if ns.write and ns.task_root:
        # The rehearsal's repair passes the story. A story that changes nothing inside this
        # profile's checkout gives the probe nothing to compare: the entry is not written on
        # that evidence, the same sentence the rehearsal says is printed, and the exit is 0 -
        # a fact about the story, not a failure (t-224, C4). Without --task-root this is the
        # onboarding write, which never had a story to ask.
        where, refusal = pick_checkout(cfg, ns.profile, ns.checkout)
        why = "" if (refusal or not str(where or "").strip()) else why_nothing_to_compare(
            ns.task_root, diff_files(Path(ns.task_root)), project_root / where, where)
        if why:
            # A story with no diff on record and a story whose diff lies elsewhere are two
            # facts (t-238 W1); the sentence says which one this is.
            print(f"runtime_probe --suggest --write: {why}; nothing was written.", file=sys.stderr)
            return 0
    if getattr(ns, "no_container", False) and ns.container:
        print("runtime_probe --suggest: --no-container and --container exclude each other: name the container that "
              "runs the application, or say it runs in none", file=sys.stderr)
        return 2
    spec, refusal = suggest(cfg, project_root, ns.profile, ns.environment, ns.container,
                            ns.checkout, ns.app_root, Path(__file__).resolve().parent,
                            no_container=getattr(ns, "no_container", False))
    if refusal:
        print(f"runtime_probe --suggest: {refusal}", file=sys.stderr)
        return 2
    note = portable_checkout(pick_checkout(cfg, ns.profile, ns.checkout)[0], project_root)[1]
    if note:
        print(f"runtime_probe --suggest: {note}", file=sys.stderr)
    print(json.dumps({"execution": {"runtime_probes": {ns.profile: spec}}}, indent=2))
    if not ns.write:
        print(f"to store it: add it under `execution.runtime_probes.{ns.profile}` in "
              f"{(project_root / 'qa-factory' / 'config.json')}, or run the same command with "
              "--write", file=sys.stderr)
        return 0
    path = project_root / "qa-factory" / "config.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    probes = data.setdefault("execution", {}).setdefault("runtime_probes", {})
    if probes.get(ns.profile) and not ns.force:
        print(f"runtime_probe --suggest --write: {path} already carries a probe for profile "
              f"{ns.profile}. It is the project's own; --force replaces it.", file=sys.stderr)
        return 2
    probes[ns.profile] = dict(spec, note=SUGGEST_NOTE)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{path}: execution.runtime_probes.{ns.profile} written", file=sys.stderr)
    # Verified once, here, rather than on the story's first typed run: a spec that does not
    # answer is the onboarding's problem, not the automator's. Before any story exists the probe
    # has no diff to compare, and saying that plainly is the honest half of the check.
    # With --task-root the check compares against THAT story's diff (the gate rehearsal's repair
    # passes it); the stored spec never carries one - it is the project's, and a project's spec
    # cannot name a ticket. Nothing is written into the story by the check.
    # ALWAYS a rehearsal (S14): the verification used to write evidence (and, with the registry, could write a
    # discovered row) whenever no story was named - onboarding writes nothing it did not mean to.
    verify = rehearsal_argv(resolve_argv(spec["argv"])) + (["--task-root", str(Path(ns.task_root).resolve())]
                                                           if ns.task_root else [])
    # EP1-24 B2: the entry is already written, so a check that does not finish (or prints a `{` that is not JSON) is
    # said and the exit stays 0 - a trace back here told the role the WRITE failed. The first typed run is the real check.
    started = time.monotonic()
    try:
        import node_ids
        checked = node_ids.run_captured(verify, str(project_root), None, VERIFY_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError) as exc:
        why = (f"did not finish in {VERIFY_TIMEOUT_S} s" if isinstance(exc, subprocess.TimeoutExpired)
               else f"could not be started ({type(exc).__name__})")
        print(f"probe check: {why}; the entry is written, the story's first run checks the stand", file=sys.stderr)
        return 0
    print(f"probe check took {time.monotonic() - started:.1f} s", file=sys.stderr)
    try:
        verdict = json.loads(checked.stdout) if checked.stdout.strip().startswith("{") else {}
    except ValueError:
        print("probe check: the probe's output was not JSON; the entry is written, the story's first run checks the stand",
              file=sys.stderr)
        return 0
    if verdict:
        print(f"probe check: result={verdict.get('result')}"
              + (f" ({verdict['error']})" if verdict.get("error") else ""), file=sys.stderr)
    else:
        print("probe check: the probe answered no provenance JSON — "
              + ((checked.stderr or checked.stdout).strip().splitlines() or ["nothing"])[0][:200]
              + ". With no story running this is expected: the comparison needs an "
                "implementation diff. Re-run this check on the story's first S5.", file=sys.stderr)
    return 0


REFERENCE_REASON = "a reference stand: the old version runs here by design, its build is not asked"   # the probe's words for a skipped stand


def reference_skip(ns, task_root) -> dict:
    """The record of a probe that compared NOTHING because `--environment` names a stand that runs an OLD version of a side of this story
    (S-c, t-2181 PC-9b; `stand_identity.reference_stands`), else {}. It says what `no_changed_file` says (`not_applicable`, that reason
    code): the story's code does not run on this stand, so there is no build identity to verify - the gates that read the code
    (profile_contract) already pass it on any stand kind and need no new word. POSITION INVARIANT: after the story is resolved (its
    record names the references) and before anything is read or run (git, docker, the checkout): nothing was observed. The story's OWN
    stand is never skipped, even when a record names it twice (`pipeline.environment`): the safe direction is to ask. Never raises."""
    try:
        name = str(getattr(ns, "environment", "") or "")
        if not name or task_root is None:
            return {}
        side, own = SI.reference_side(hooklib.project_root(), Path(task_root).name, name)      # the one reader (F3), the same as C8's
        if not side or name == own:
            return {}
        return {"profile_id": ns.profile, "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"), "environment_id": name,
                "expected_source_revision": "unknown", "observed_runtime_identity": "", "evidence_refs": [],
                "provenance": {"technical_verification": False}, "result": "not_applicable", "reason": REFERENCE_REASON,
                "reason_code": NO_CHANGED_FILE, "comparisons": [], "container": getattr(ns, "container", ""), "checkout": str(ns.checkout or "")}
    except Exception:
        return {}


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(
        epilog="--suggest reads the project's own config (stands, implementation repositories) "
               "and docker, and prints the `execution.runtime_probes.<profile>` entry that "
               "identifies this stand; --write puts it in qa-factory/config.json. The only thing "
               "it asks a person is which container runs the application.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=None, help="default: the story this project is running")
    ap.add_argument("--suggest", action="store_true", help="derive the config entry for this stand")
    ap.add_argument("--write", action="store_true", help="with --suggest: write it into config.json")
    ap.add_argument("--force", action="store_true", help="with --write: replace an existing entry")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--environment", default="")
    ap.add_argument("--container", default="")
    ap.add_argument("--no-container", action="store_true", dest="no_container",
                    help="with --suggest: the application does not run in a container; the entry names none")
    ap.add_argument("--checkout", default="", help="the application checkout at the MR's head")
    ap.add_argument("--app-root", default=APP_ROOT, help="where the checkout lives inside the container")
    ap.add_argument("--expected", default="", help="the expected source revision (default: checkout HEAD)")
    ap.add_argument("--task-root", default=None,
                    help="the story's folder: where the implementation diff is read from (and, "
                         "with --suggest --write, what the one verification run compares)")
    ap.add_argument("--no-evidence", action="store_true",
                    help="compare and print, but write no evidence file into the story: the gate "
                         "rehearsal runs the probe this way, because a rehearsal writes nothing")
    ap.add_argument("--timeout", type=int, default=20)
    ns = hooklib.exact_options(ap).parse_args()
    story = None
    if ns.task is not None or ns.task_root is not None:     # a GIVEN flag names an existing story before anything is read or written
        story = hooklib.story_cli("runtime_probe.py", key=ns.task, root=ns.task_root)
    if ns.suggest:
        return do_suggest(ns)
    if not ns.task and not ns.task_root:
        ns.task = running_task()
        if not ns.task:
            print("runtime_probe: no story is running in this project, so there is no "
                  "implementation diff to compare the stand against. Pass --task <TICKET>.",
                  file=sys.stderr)
            return 2
        story = hooklib.story_cli("runtime_probe.py", key=ns.task)
    skipped = reference_skip(ns, story)
    if skipped:
        print(json.dumps(skipped))
        return 0
    if not ns.checkout:
        print("runtime_probe: --checkout is required: the application checkout the stand should run, which is "
              "where the revision to compare with comes from. `runtime_probe.py --suggest --profile <P>` derives "
              "it from this project's config and prints the entry to store.", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    task_root = story           # the folder the driver resolved (the project's artifact root), never one rebuilt from the cwd
    checkout = Path(ns.checkout)
    expected = ns.expected
    if not expected:
        try:
            code, out, _err = run_command(["git", "-C", str(checkout), "rev-parse", "HEAD"], ns.timeout)
        except (OSError, subprocess.TimeoutExpired):
            code, out = 1, ""
        expected = out.strip() if code == 0 else ""
    record = {"profile_id": ns.profile, "timestamp": now, "environment_id": ns.environment,
              "expected_source_revision": expected or "unknown", "observed_runtime_identity": "",
              "evidence_refs": [], "provenance": {"technical_verification": False}, "result": "unknown"}
    files = diff_files(task_root)
    has_diff = diff_recorded(task_root)
    if has_diff and not compared_files(files, checkout):
        # The story's diff does not touch this checkout, so what this stand runs cannot be
        # compared with it and the probe does not apply to the profile: not `mismatched` (0 of 0
        # files differ is no difference) and not a question (t-238 W4). Nothing was observed, so
        # there is no evidence file either.
        record.update({"result": "not_applicable", "reason": NOT_APPLICABLE_REASON,
                       "reason_code": NO_CHANGED_FILE,
                       "comparisons": [], "container": ns.container, "checkout": str(checkout)})
        print(json.dumps(record))
        return 0
    if not expected:
        record["error"] = "no expected revision"
        record["reason_code"] = NO_EXPECTED_REVISION       # a FIELD for the capture's refusal (FR-12), never the words
        record["checkout"] = str(checkout)
        print(json.dumps(record))
        return 0
    # No diff recorded is NOT "nothing changed" (FR-41), and it is no longer an early `unknown` either (E15): the sha
    # rungs read the stand and judge it against HEAD, the sources rung is skipped, `not_applicable` is never said.
    # A story's pipeline.json is an input here, never a requirement: absent or unreadable reads as {}.
    pipeline = hooklib.read_json(task_root / "pipeline.json", {})
    print(json.dumps(build_identity(
        ns, record, root=hooklib.project_root(), task_root=task_root, checkout=checkout, expected=expected, files=files,
        has_diff=has_diff, now=now, cfg=hooklib.load_config() or {},
        story_stand=str(pipeline.get("environment") or "").strip() if isinstance(pipeline, dict) else "")))
    return 0


def build_identity(ns, record: dict, **context) -> dict:
    """THE ladder (module docstring), as one function every caller reaches through the probe's argv: reads the stand, fills
    `record`, writes what rung 9 allows and returns the record the probe prints. `context` is what `Reading` takes
    (root, task_root, checkout, expected, files, has_diff, now, cfg, story_stand)."""
    reading = Reading(ns, record, **context)
    if not record["environment_id"]:
        record["environment_id"] = reading.stand
    reading.run()
    return reading.finish()


if __name__ == "__main__":
    sys.exit(main())
