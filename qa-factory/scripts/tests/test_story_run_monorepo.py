"""B-412: a project in a subfolder of a git repository (a monorepo). `Driver.checkout_for` decides whether the folder
an `implementation_repos[].local_path` names may be asked: the old test, a `.git` in that very folder, skipped the
application of a monorepo without a word, and `git_route` asked an enclosing repository nobody had named.

What this file proves, each key with its mutation in the hand-back:
  K1  the entry inside the project's own repository is used by the three readers (head, branch, git route);
  K2  an enclosing repository of ANOTHER project is not asked, and the line says which and why (a door);
  K2b the route's selection is by substring (`testproject1` is "in" `.../testproject1-ui`): the URL's project is checked;
  K3-K5 no repository, a broken `.git`, no git: a line, never an exception;
  K6  a worktree; K7 two folders of one repository ask the remote once;
  K8  the project's `.gitignore` block works from a subfolder (and does not at the top: the negative control);
  K9  the texts (p0, common-rules, both SKILL files); K10 identity forms and the secret in an origin (E14).
Run: python -B scripts/tests/test_story_run_monorepo.py
"""
import contextlib
import io
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import harness  # noqa: E402
from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402
import story_run_common as T  # noqa: E402

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_TERMINAL_PROMPT="0")
IDENTITY = "git.example/tp1-group/testproject1"           # a form `split_remote_identity` does not parse: tails compare
UI_IDENTITY = "git.example/tp1-group/testproject1-ui"
TASK = "TP1-15045"
URL = "https://git.example/tp1-group/testproject1/-/merge_requests/1924"
UI_URL = "https://git.example/tp1-group/testproject1-ui/-/merge_requests/1924"
REL = "sources/SRC-1/mr-1924-git.md"


def git(cwd, *args, rc=0):
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=GIT_ENV, timeout=60)
    if rc is not None and done.returncode != rc:
        raise RuntimeError(f"git {' '.join(args)} in {cwd}: {done.stderr.strip()}")
    return done.stdout.strip() if rc == 0 else done.returncode


def commit(repo, name, text, message):
    (Path(repo) / name).parent.mkdir(parents=True, exist_ok=True)
    (Path(repo) / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def build(base: Path) -> dict:
    """mono/ (origin: the bare testproject1.git) with the project mono/harness/, mono-ui/ (origin: testproject1-ui.git), and
    the shas. main: A "TP1-100", B; feat: C "TP1-15045"; MR 1924 of testproject1 = C, of testproject1-ui = D.
    Origins are spelled with forward slashes: a Windows path with backslashes has no last segment (`list_tail`)."""
    out = {}
    for name in ("testproject1", "testproject1-ui"):
        subprocess.run(["git", "init", "-q", "--bare", str(base / f"{name}.git")], check=True, capture_output=True)
    mono = base / "mono"
    subprocess.run(["git", "init", "-q", str(mono)], check=True, capture_output=True)
    git(mono, "checkout", "-q", "-b", "main")
    out["A"] = commit(mono, "services/api/app.py", "a", "TP1-100 an older change of the ticket prefix")
    out["B"] = commit(mono, "b.txt", "b", "an unrelated change")
    git(mono, "branch", "feature/x")
    git(mono, "checkout", "-q", "-b", "feat")
    out["C"] = commit(mono, "c.txt", "c", "TP1-15045 draft evaluation tests")
    git(mono, "checkout", "-q", "main")
    git(mono, "remote", "add", "origin", (base / "testproject1.git").as_posix())
    git(mono, "push", "-q", "origin", "main", "feat", "feature/x", f"{out['C']}:refs/merge-requests/1924/head")
    (mono / "other").mkdir()                                     # a plain folder of the repository, no own .git
    ui = base / "mono-ui"
    subprocess.run(["git", "init", "-q", str(ui)], check=True, capture_output=True)
    git(ui, "checkout", "-q", "-b", "main")
    out["D"] = commit(ui, "web/app.js", "d", "TP1-15045 another repository's change")
    git(ui, "remote", "add", "origin", (base / "testproject1-ui.git").as_posix())
    git(ui, "push", "-q", "origin", "main", f"{out['D']}:refs/merge-requests/1924/head")
    out["mono"], out["ui"], out["project"] = mono, ui, mono / "harness"
    return out


def write_config(project: Path, repos: list) -> None:
    cfg = json.loads((harness.PLUGIN_ROOT / "references" / "templates" / "config.json").read_text(encoding="utf-8"))
    cfg["tests_root"], cfg["app_root"], cfg["implementation_repos"] = "tests", ".", repos
    (project / "qa-factory" / "state").mkdir(parents=True, exist_ok=True)
    (project / "tests").mkdir(parents=True, exist_ok=True)
    (project / "qa-factory" / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def entry(repo_id, local, identity):
    return {"repo_id": repo_id, "local_path": str(local), "remote_identity": identity}


@contextlib.contextmanager
def counting_ls_remote():
    """Every `git ls-remote` the process runs (the wrapper sits on the shared `subprocess.run`)."""
    import story_run
    real, seen = story_run.subprocess.run, []

    def wrapper(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        if isinstance(argv, (list, tuple)) and "ls-remote" in argv:
            seen.append(list(argv))
        return real(*args, **kwargs)

    story_run.subprocess.run = wrapper
    try:
        yield seen
    finally:
        story_run.subprocess.run = real


def say(call, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        result = call(*args)
    return result, out.getvalue()


def head_line(driver, project, iid="1924"):
    entry_ = {"as_written": f"{project.rsplit('/', 1)[-1]}!{iid}",
              "target": {"kind": "mr", "host": None, "project": project, "iid": iid, "head_sha": None, "branch": None}}
    _none, printed = say(driver.s0_resolve_head, entry_)
    return entry_["target"]["head_sha"], printed


def branch_sha(driver, name):
    entry_ = {"as_written": f"branch:{name}", "target": {"kind": "ref", "sha": None, "branch": name}}
    _none, printed = say(driver.s0_resolve_branch, entry_)
    return entry_["target"]["sha"], printed


def route(driver, task_root, url=URL):
    note, printed = say(driver.git_route, url, REL)
    return note, printed, (task_root / "work" / REL)


def has(text: str, key: str) -> bool:
    return key in text


def lacks(text: str, key: str) -> bool:
    return key not in text


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start:] if nxt < 0 else text[start:nxt]


def main() -> None:
    base = temp_dir("qa-monorepo-")
    home = Path.cwd()
    old_path = os.environ.get("PATH", "")
    try:
        shas = build(base)
        mono, project = shas["mono"], shas["project"]
        env = dict(os.environ, STUB_CONTROL=str(base / "control.json"), STUB_LOG=str(base / "log.jsonl"))

        def driver_of(repos):
            write_config(project, repos)
            return T.driver_for(project, env, TASK)

        task_root = project / "qa-factory" / "artifacts" / TASK
        e_api = entry("testproject1", "../services/api", IDENTITY)
        e_dot = entry("testproject1", ".", IDENTITY)

        # --- K1: inside the project's own repository, the entry is used by all three readers -------------------------
        driver = driver_of([e_api])
        found = driver.repo_of_project("tp1-group/testproject1")
        check_eq("K1: repo_of_project finds the folder inside the monorepo", found and found[0], "testproject1")
        check_eq("K1: and returns the configured checkout, not the top", found and found[1], (project / ".." / "services" / "api").resolve())
        value, printed = head_line(driver, "tp1-group/testproject1")
        check_eq("K1: the head of the merge request is looked up through the subfolder", value, shas["C"])
        value, printed = branch_sha(driver, "feature/x")
        check_eq("K1: a branch word resolves through the subfolder", value, shas["B"])
        note, printed, body = route(driver, task_root)
        check("K1: git_route names the commit of the change", shas["C"][:9] in note, note + printed)
        check("K1: and writes the evidence body", body.is_file() and shas["C"] in body.read_text(encoding="utf-8"), note)
        body.unlink(missing_ok=True)                                   # the next keys look for a file this one must not have left
        driver = driver_of([e_dot])
        checkout, top, why = driver.checkout_for(e_dot)
        check("K1: `.` (the project folder itself, inside the repository) is usable", checkout == project.resolve() and why == "", why)
        check_eq("K1: its top is the monorepo", os.path.normcase(os.path.realpath(top)), os.path.normcase(os.path.realpath(mono)))
        # the edge of the other kind: no `local_path` at all is no entry and no line
        check_eq("R1a: an empty local_path is (None, None, '')", driver.checkout_for(entry("testproject1", "", IDENTITY)), (None, None, ""))
        # R1e: the top IS the folder: today's behaviour, no identity check and no `want` check (M5 is killed by test_story_run_s0 C2)
        checkout, top, why = driver.checkout_for(entry("testproject1-ui", str(mono), UI_IDENTITY), want="testproject1-ui")
        check("R1e: the top is the folder: used, whatever its origin and whatever `want` says", checkout == mono.resolve() and why == "", why)
        # R1b: a path that is not there / not a folder
        _c, _t, why = driver.checkout_for(entry("testproject1", "../nope", IDENTITY))
        check("R1b: a missing folder is named with its door", "`../nope` does not exist" in why and "point `local_path` of testproject1" in why, why)
        _c, _t, why = driver.checkout_for(entry("testproject1", "../b.txt", IDENTITY))
        check("R1b: a file is not a folder", "is not a folder" in why, why)

        # --- K2: an enclosing repository of another project is not asked ------------------------------------------
        e_other = entry("testproject1-ui", "../other", UI_IDENTITY)
        driver = driver_of([e_other])
        check_eq("K2: repo_of_project is None for the foreign enclosing repository", driver.repo_of_project("testproject1-ui"), None)
        with counting_ls_remote() as asked:
            value, printed = head_line(driver, "tp1-group/testproject1-ui")
            note, printed_route, body = route(driver, task_root, UI_URL)
        check("K2: the head line names the folder and the origin it found", "`../other`" in printed and "whose origin is `testproject1`" in printed, printed)
        check_not_in("K2: and does not claim that no checkout is configured", "is configured", printed)
        check("K2: it carries its door and its consequence", "right repository" in printed and "the word holds by the number" in printed, printed)
        check("K2: no head", value is None)
        check("K2: git_route returns nothing and writes no file", note == "" and not body.exists(), note)
        check("K2: git_route says why", "local git route:" in printed_route and "`../other`" in printed_route, printed_route)
        check_eq("K2: no remote was asked for either reader", asked, [])
        driver = driver_of([entry("testproject1-ui", "../other", "")])
        value, printed = head_line(driver, "tp1-group/testproject1-ui")
        check("K2: an empty remote_identity: the door says to set it, or to move the local_path",
              "set `remote_identity` of testproject1-ui" in printed and "`local_path`" in printed and value is None, printed)

        # --- K2b: a `testproject1` URL against an entry whose identity only CONTAINS `testproject1`; K2c: the two-entry config ----
        e_ui = entry("testproject1-ui", "../../mono-ui/web", UI_IDENTITY)
        driver = driver_of([e_ui])
        with counting_ls_remote() as asked:
            note, printed, body = route(driver, task_root)
        check("K2b: nothing is returned and no file is written", note == "" and not body.exists(), note)
        check("K2b: the other repository's commit appears nowhere", shas["D"] not in note + printed + (body.read_text(encoding="utf-8") if body.exists() else ""))
        check_eq("K2b: no ls-remote was run", asked, [])
        # the `want` check of `checkout_for` itself (the route's whole-tail selection makes it a second line of defence)
        checkout, _t, why = driver.checkout_for(e_ui, want="testproject1")
        check("K2b: the entry for another project is refused when `want` names the merge request's project",
              checkout is None and "merge request's project `testproject1`" in why, why)
        checkout, _t, why = driver.checkout_for(e_ui, want="testproject1-ui")
        check("K2b: the same entry for its own project is usable", checkout is not None and why == "", why)
        # critic t-554 F2: the live shape: testproject1-ui at its OWN top (top == folder, no origin check) listed before testproject1
        e_ui_top = entry("testproject1-ui", "../../mono-ui", UI_IDENTITY)
        driver = driver_of([e_ui_top, e_api])
        note, printed, body = route(driver, task_root)
        text = body.read_text(encoding="utf-8") if body.exists() else ""
        check("K2c: the testproject1 merge request picks the testproject1 entry, not the first entry that contains the word",
              shas["C"][:9] in note and shas["C"] in text and shas["D"] not in note + text, note)
        body.unlink(missing_ok=True)
        note, printed, body = route(driver, task_root, "https://git.example/tp1-group/unknown-app/-/merge_requests/1924")
        check("K2c: a project with no matching entry has no local git route (nothing, no file)", note == "" and printed == "" and not body.exists(), note + printed)

        # --- K3: no repository; K4: a broken .git; K5: no git -----------------------------------------------------
        plain, broken = temp_dir("qa-plain-"), temp_dir("qa-broken-")
        (broken / ".git").mkdir()
        try:
            driver = driver_of([entry("testproject1", str(plain), IDENTITY)])
            value, printed = head_line(driver, "tp1-group/testproject1")
            check("K3: a folder outside any repository: the line says so, with its door", "is not inside a git repository" in printed and "point `local_path`" in printed and value is None, printed)
            note, printed, body = route(driver, task_root)
            check("K3: git_route returns nothing, no exception", note == "" and not body.exists(), printed)
            driver = driver_of([entry("testproject1", str(broken), IDENTITY)])
            value, printed = head_line(driver, "tp1-group/testproject1")
            check("K4: an empty .git folder: git could not answer (an unknown is not an empty repository)", "git could not answer in" in printed and value is None, printed)
        finally:
            cleanup(plain)
            cleanup(broken)
        driver = driver_of([e_api])
        nogit = temp_dir("qa-nogit-")
        try:
            os.environ["PATH"] = str(nogit)
            value, printed = head_line(driver, "tp1-group/testproject1")
            note, printed_route, body = route(driver, task_root)
            branch, printed_branch = branch_sha(driver, "feature/x")
        finally:
            os.environ["PATH"] = old_path
            cleanup(nogit)
        check("K5: no git on PATH: the head line says so, nothing raised", "git is not on PATH" in printed and value is None, printed)
        check("K5: git_route says so and returns nothing", note == "" and "git is not on PATH" in printed_route, printed_route)
        check("K5: the branch word says so too", "git is not on PATH" in printed_branch and branch is None, printed_branch)

        # --- K6: a worktree ---------------------------------------------------------------------------------------
        wt = base / "wt"
        git(mono, "worktree", "add", "-q", str(wt), "feat")
        for label, local in (("the worktree root (a .git FILE)", wt), ("a folder inside the worktree", wt / "services" / "api")):
            driver = driver_of([entry("testproject1", local, IDENTITY)])
            checkout, _t, why = driver.checkout_for(driver.config["implementation_repos"][0])
            check(f"K6: {label} is usable", checkout is not None and why == "", why)
        driver = driver_of([entry("testproject1", wt / "services" / "api", IDENTITY)])
        check_eq("K6: and it answers the head lookup", head_line(driver, "tp1-group/testproject1")[0], shas["C"])

        # --- K7: two folders of one repository are asked once -----------------------------------------------------
        driver = driver_of([e_api, e_dot])
        with counting_ls_remote() as asked:
            value, printed = branch_sha(driver, "feature/x")
        check_eq("K7: one ls-remote for two folders of one repository", len(asked), 1)
        check_eq("K7: and the branch resolves", value, shas["B"])
        driver = driver_of([e_api, e_ui])
        with counting_ls_remote() as asked:
            value, printed = branch_sha(driver, "feature/x")
        check("K7: two repositories are two asks (the control: the count is not a constant)", len(asked) == 2, str(asked))
        check_eq("K7: only one of them lists the branch, and that one answers", value, shas["B"])
        driver = driver_of([e_other, entry("testproject1-ui", "../other", UI_IDENTITY)])
        value, printed = branch_sha(driver, "feature/x")
        check("K7: only unusable entries: one line each, and not 'no checkout is configured'",
              value is None and printed.count("whose origin is `testproject1`") == 2 and "is configured" not in printed, printed)

        # --- E13: the top on another drive: the line names its last segment and never crashes -------------------
        driver = driver_of([e_other])
        real_relpath = os.path.relpath

        def other_drive(*args, **kwargs):
            raise ValueError("path is on mount 'D:', start on mount 'C:'")

        os.path.relpath = other_drive
        try:
            _c, _t, why = driver.checkout_for(e_other)
        finally:
            os.path.relpath = real_relpath
        check("E13: another drive: the top is named by its last segment", "lies in the repository at `mono`" in why, why)

        # --- K10: identity forms; only `config --get` is read ---------------------------------------------------
        idroot = base / "idrepo"
        subprocess.run(["git", "init", "-q", str(idroot)], check=True, capture_output=True)
        (idroot / "sub").mkdir()
        git(idroot, "remote", "add", "origin", "x")
        driver = driver_of([])

        def verdict(origin, identity):
            git(idroot, "remote", "set-url", "origin", origin)
            return driver.checkout_for(entry("testproject1", idroot / "sub", identity))

        scp = "git@git.example:tp1-group/testproject1.git"
        checkout, _t, why = verdict("git@git.example:other-group/testproject1.git", scp)
        check("K10: same tail, another group: not used", checkout is None, why)
        check("K10: the line shows both as host/path", "git.example/other-group/testproject1" in why and "git.example/tp1-group/testproject1" in why, why)
        checkout, _t, why = verdict(scp, scp)
        check("K10: the same repository: used", checkout is not None and why == "", why)
        checkout, _t, why = verdict("git@Git.EXAMPLE:Tp1-Group/Testproject1.git", scp)
        check("K10: host and path compare in lower case", checkout is not None and why == "", why)
        checkout, _t, why = verdict("https://user:s3cr3t@git.example/other-group/testproject1.git", scp)
        check("K10: a credential in the origin: not used", checkout is None, why)
        check_not_in("K10/E14: and the secret is in no printed line", "s3cr3t", why)
        check_in("K10/E14: the origin is shown as host/path", "git.example/other-group/testproject1", why)
        checkout, _t, why = verdict("user:s3cr3t@git.example/other/testproject1.git", "git@git.example:tp1-group/testproject1-ui.git")
        check("E14: a credential in a form that does not parse: not used, and not printed", checkout is None and "s3cr3t" not in why, why)
        # critic t-554 F1: the credential survives in the tail of an origin that does not parse, and `list_tail`
        # lower-cases it: every secret below is checked CASE-INSENSITIVELY over everything printed
        def clean_of(why_, *secrets):
            return not any(s.lower() in why_.lower() for s in secrets)

        checkout, _t, why = verdict("https://oauth2:TOKEN4@git.example", scp)
        check("E14: a token before a host with no path: not used, and no case of it printed", checkout is None and clean_of(why, "TOKEN4"), why)
        checkout, _t, why = verdict("https://git.example/tp1-group/testproject1.git?private_token=TOKEN5", scp)
        check("E14: a token in the query of the RIGHT repository's origin: it is used, not refused", checkout is not None and why == "", why)
        checkout, _t, why = verdict("https://git.example/tp1-group/testproject1.git?private_token=TOKEN5", IDENTITY)
        check("E14: and with an identity that does not parse (tails)", checkout is not None and why == "", why)
        checkout, _t, why = verdict("https://git.example/other-group/testproject1.git?private_token=TOKEN5#TOKEN6", scp)
        check("E14: a token in the query and the fragment of another group's origin: not used, no case of it printed",
              checkout is None and clean_of(why, "TOKEN5", "TOKEN6") and "git.example/other-group/testproject1" in why, why)
        checkout, _t, why = verdict("user:TOKEN7@git.example/other/testproject1.git?x=TOKEN8", "git@git.example:tp1-group/testproject1-ui.git")
        check("E14: a credential in a form that does not parse, with a query: not used, no case of it printed",
              checkout is None and clean_of(why, "TOKEN7", "TOKEN8"), why)
        git(idroot, "remote", "set-url", "origin", "https://oauth2:TOKEN9@git.example/tp1-group/testproject1.git?private_token=TOKEN9")
        checkout, _t, why = driver.checkout_for(entry("testproject1", idroot / "sub", scp), want="testproject1-ui")
        check("E14: the merge request's project line (R1f3) prints no case of the secret either",
              checkout is None and clean_of(why, "TOKEN9") and "`testproject1`" in why, why)
        checkout, _t, why = driver.checkout_for(entry("testproject1", idroot / "sub", scp), want="testproject1")
        check("R1f3: the origin's parsed path decides, whatever the query says", checkout is not None and why == "", why)
        checkout, _t, why = verdict("https://git.example/other-group/testproject1.git", IDENTITY)
        check("K10: an identity that does not parse compares tails (the queued residual, pinned so a change is seen)", checkout is not None and why == "", why)
        git(idroot, "remote", "remove", "origin")
        checkout, _t, why = driver.checkout_for(entry("testproject1", idroot / "sub", IDENTITY))
        check("K10: no origin at all: not used, shown as not set", checkout is None and "not set" in why, why)

        # --- K8: the project's `.gitignore` block, from a subfolder ----------------------------------------------
        import project_gitignore as G
        import onboard_apply as OA
        G.write_block(project)
        probe = "harness/qa-factory/state/x.json"
        check_eq("K8: the block in the project folder ignores the project's state from the repository top", git(mono, "check-ignore", "-q", probe, rc=None), 0)
        neg = base / "neg"
        subprocess.run(["git", "init", "-q", str(neg)], check=True, capture_output=True)
        (neg / "harness").mkdir()
        G.write_block(neg)
        check_eq("K8 control: the same block at the top does NOT ignore the nested project's state", git(neg, "check-ignore", "-q", probe, rc=None), 1)
        tracked = project / "qa-factory" / "state" / "t.json"
        tracked.write_text("{}", encoding="utf-8")
        git(mono, "add", "-f", "harness/qa-factory/state/t.json")
        git(mono, "commit", "-q", "-m", "a tracked file inside the ignored state folder")
        rm_lines = OA.tracking(project, [])["git_rm"]
        check_in("K8: onboarding's listing finds the tracked file, relative to the project folder", "git rm --cached qa-factory/state/t.json", rm_lines)
        line = [ln for ln in rm_lines if "state/t.json" in ln][0]
        done = subprocess.run(shlex.split(line), cwd=str(project), capture_output=True, text=True, env=GIT_ENV, timeout=60)
        check_eq("K8: and that line, run from the project folder, exits 0", done.returncode, 0)

        # --- K9: the texts -----------------------------------------------------------------------------------------
        pkg = harness.PLUGIN_ROOT
        p0 = (pkg / "skills" / "qa-onboarding" / "phases" / "p0-preflight.md").read_text(encoding="utf-8")
        rules = (pkg / "references" / "common-rules.md").read_text(encoding="utf-8")
        onboarding = (pkg / "skills" / "qa-onboarding" / "SKILL.md").read_text(encoding="utf-8")
        doctor = (pkg / "skills" / "qa-doctor" / "SKILL.md").read_text(encoding="utf-8")
        check("T1: p0 no longer says the project sits at a git root", lacks(p0, "sits at a git root"))
        check("T2: p0 says the project may be a subfolder", has(p0, "may be a subfolder"))
        path_section = section(rules, "## What a path is relative to")
        check("T3: common-rules, `What a path is relative to`, names the .gitignore and the subfolder", has(path_section, ".gitignore") and has(path_section, "subfolder"))
        check("T4: the onboarding SKILL no longer says to run it from the repository root", lacks(onboarding, "Run it from the repository root"))
        check("T5: the doctor SKILL no longer looks for the config at the git top", lacks(doctor, "exists at that"))
        check("T6: the doctor SKILL looks in the current directory", has(doctor, "exists in the current directory, run:"))
        check("T-control: the helper reports failure on the old p0 line",
              not lacks("`qa-story` and every downstream role assume `qa-factory/` sits at a git root; there is", "sits at a git root"))
    finally:
        os.environ["PATH"] = old_path
        os.chdir(home)
        cleanup(base)
    finish("test_story_run_monorepo")


if __name__ == "__main__":
    main()
