"""The base slice by code (G1-8): the text of the code a diff changed, as it was, read from git objects of a named base.

Edges (spec t-1016 sections 3-5, L, L-2): the base is the MR receipt's `diff_refs.base_sha` (when its head is the recorded commit) else
`<impl>^1`, and a file is `read` only when that base reproduces its hunks AND (commit present) base + hunks is the implementation's blob;
a new file is `absent`; every doubt is `unknown` with a reason; one canonical path form in the file set and the predicate; the judgement
is recomputed (`collect`), never cached; the chain diff -> repo id -> checkout -> commit is the table's matcher plus the config's.
Mutation killers (each one test file, this one): see the tail of the test names (M1 predicate canonical form, M2 base from <impl>,
M3 impl-blob comparison, M4 cache after refresh, M5 second matcher).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, cleanup, finish, run_script, temp_dir, temp_project  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import base_slice as BS  # noqa: E402
import contract as C  # noqa: E402
import grounding_table as GT  # noqa: E402
import planning_contract as PC  # noqa: E402
import source_exclusions as SE  # noqa: E402
import test_novelty as TN  # noqa: E402
import vcs_evidence as VE  # noqa: E402

REAL = Path(__file__).resolve().parents[4] / "experiments" / "TP1-13877"
SHA0 = "0" * 40
GIT_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="ci", GIT_AUTHOR_EMAIL="ci@x",
               GIT_COMMITTER_NAME="ci", GIT_COMMITTER_EMAIL="ci@x")


def git(cwd, *args, stdin=None) -> bytes:
    env = {k: v for k, v in GIT_ENV.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
    done = subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=str(cwd), env=env, input=stdin, capture_output=True)
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout


class Repo:
    def __init__(self):
        self.dir = temp_dir("qa-bs-repo-")
        git(self.dir, "init", "-q")

    def commit(self, files: dict, message="c") -> str:
        for name, data in files.items():
            target = self.dir / name
            if data is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        git(self.dir, "add", "-A")
        git(self.dir, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.dir, "rev-parse", "HEAD").decode().strip()

    def diff(self, a, b, *opts) -> bytes:
        return git(self.dir, "diff", "-M", *opts, a, b)


def first_text(col) -> str:
    """The first slice file's text of a `collect` result, or '' - a kill of a mutation must show as a FAIL line, never as a crash."""
    return next(iter(col.files.values()), "")


def numbered(n=100, tag="line"):
    return "".join(f"{tag} {i}\n" for i in range(1, n + 1))


def edit(text, **changes):
    lines = text.splitlines(keepends=True)
    for key, value in changes.items():
        lines[int(key[1:]) - 1] = value + "\n"
    return "".join(lines)


REG_HEAD = ("# Register\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact | delta |\n"
            "|---|---|---|---|---|---|---|---|---|\n")


def register(*places):
    return REG_HEAD + "".join(f"| R-{i} | thing {i} | ac | — | yes | AC{i} | {p} | access | unchanged |\n" for i, p in enumerate(places, 1))


class Story:
    def __init__(self, places=()):
        self.root = temp_project("qa-bs-")
        self.task = self.root / "qa-factory" / "artifacts" / "T-1"
        (self.task / "work").mkdir(parents=True)
        (self.task / "pipeline.json").write_bytes(json.dumps({"ticket": "T-1", "stages": {}, "implementation_source": "diff"}).encode())
        self.cfg = {"implementation_repos": []}
        self.entries = {}
        if places:
            (self.task / "work" / "requirements-register.md").write_bytes(register(*places).encode("utf-8"))

    def checkout(self, repo_id, path):
        self.cfg["implementation_repos"] = [r for r in self.cfg["implementation_repos"] if r["repo_id"] != repo_id] + [
            {"repo_id": repo_id, "local_path": str(path)}]

    def set_diff(self, diff, sha, name="impl-diff.txt", repo_id="backend", mr=None):
        (self.task / "work" / name).write_bytes(diff if isinstance(diff, bytes) else diff.encode("utf-8"))
        entry = {"repo_id": repo_id, "source": "diff", "diff_path": f"qa-factory/artifacts/T-1/work/{name}", "source_sha": sha}
        if mr:
            entry["mr"] = f"https://git.example.com/g/p/-/merge_requests/{mr}"
        self.entries[name] = entry
        (self.task / "work" / "context-manifest.json").write_bytes(json.dumps({"implementations": list(self.entries.values())}).encode())

    def receipt(self, iid, head, base, where="sources/SRC-1"):
        """The MR receipt where the driver writes it: `work/sources/<SRC>/mr-<iid>.json` (story_run `close_vcs_gaps`)."""
        target = self.task / "work" / where / f"mr-{iid}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(json.dumps({"metadata": {"diff_refs": {"head_sha": head, "base_sha": base}}}).encode())

    def save_config(self):
        path = self.root / "qa-factory" / "config.json"
        cfg = json.loads(path.read_bytes().decode("utf-8")) if path.is_file() else {}
        path.write_bytes(json.dumps(dict(cfg, **self.cfg)).encode())

    def collect(self):
        return BS.collect(self.task, project=self.root, cfg=self.cfg)

    def by_file(self, col=None):
        return {e["file"]: e for e in (col or self.collect()).entries}

    def done(self):
        cleanup(self.root)


def one(repo, tweak, places=(), opts=(), size=100):
    """A repo of two files, `tweak` (a dict for the second commit) applied: (story, base sha, impl sha)."""
    base = repo.commit({"src/a.py": numbered(size), "src/b.py": numbered(40, "b")})
    impl = repo.commit(tweak)
    story = Story(places)
    story.checkout("backend", repo.dir)
    story.set_diff(repo.diff(base, impl, *opts), impl)
    return story, base, impl


# --- S1 / S16: a one-line edit -> read, windows +-30 (AT 30 / BEYOND 31), the key fields, the header -----------------------------------
repo = Repo()
story, base, impl = one(repo, {"src/a.py": edit(numbered(), L50="changed 50")})
col = story.collect()
rec = story.by_file(col)["src/a.py"]
check_eq("S1: one edit in the middle of a file -> read at the parent, path in work/base-slice", (rec["state"], rec["base_rev"], rec["why"], rec["path"].startswith("work/base-slice/")), ("read", base, "", True))
check_eq("S1: the other file is not in the diff, so it has no record", sorted(story.by_file(col)), ["src/a.py"])
text = first_text(col)
numbers = [int(x.split("|")[0]) for x in text.split("\n")[1:] if "|" in x] or [0]
check_eq("S16: the hunk reads 47..53; the window is +-30 around it (AT: 83 in, BEYOND: 84 out; 17 in, 16 out)", (min(numbers), max(numbers)), (17, 83))
check_in("S1: the header names the base, the origin, the way and what was verified", f"base_rev={base} from={impl} how=parent verified=hunks+implementation", text.split("\n")[0])
check("S1: the slice text is the blob's (line 50 reads as it was)", "50| line 50" in text and "changed 50" not in text)
story.done()

repo = Repo()
story, base, impl = one(repo, {"src/a.py": edit(numbered(), L2="x2", L99="x99")})
text = first_text(story.collect())
numbers = [int(x.split("|")[0]) for x in text.split("\n")[1:] if "|" in x] or [0]
check_eq("S16: a hunk at line 2 and one at the end of the file: windows clipped to 1..100, one break between them, no error", (min(numbers), max(numbers), text.count("\n...\n")), (1, 100, 1))
story.done()

repo = Repo()
story, base, impl = one(repo, {"src/a.py": edit(numbered(300), L10="x10", L140="x140")}, size=300)
text = first_text(story.collect())
check("S16: two far hunks give two windows with a break line `...` (gap over 1 line)", "\n...\n" in text and "80| line 80" not in text)
story.done()

# --- S2 / S3 / S4: new file -> absent; new but present in the base -> unknown; modified but missing in the base -> unknown ----------------
repo = Repo()
story, base, impl = one(repo, {"src/new.py": numbered(5), "src/a.py": edit(numbered(), L5="x5")})
got = story.by_file()
check_eq("S2: a new file is the third word `absent` (never `read` of nothing), no text", (got["src/new.py"]["state"], got["src/new.py"]["path"], got["src/new.py"]["base_rev"] == base), ("absent", "", True))
check_eq("S2: the modified neighbour is read", got["src/a.py"]["state"], "read")
story.done()
repo = Repo()
story, base, impl = one(repo, {"src/new.py": numbered(5), "src/a.py": edit(numbered(), L5="x5")}, places=["current-code:src/new.py:3"])
check_eq("S23: an `unchanged` place in a NEW file (absent at the base) is never evidenced - there is no base line to point at",
         BS.unchanged_evidence({"r": "R-1", "observable": "current-code:src/new.py:3", "delta": "unchanged"}, story.task, project=story.root, cfg=story.cfg),
         ("unevidenced", "", "the base slice of src/new.py is absent"))
story.done()

repo = Repo()
base = repo.commit({"src/a.py": numbered(), "src/new.py": "x\n"})
impl = repo.commit({"src/a.py": edit(numbered(), L5="x5")})
diff = repo.diff(base, impl) + b"diff --git a/src/new.py b/src/new.py\nnew file mode 100644\n--- /dev/null\n+++ b/src/new.py\n@@ -0,0 +1 @@\n+x\n"
story = Story()
story.checkout("backend", repo.dir)
story.set_diff(diff, impl)
got = story.by_file()["src/new.py"]
check_eq("S3: the diff creates a file the base already has -> unknown", (got["state"], got["why"]), ("unknown", f"base {base[:12]} has src/new.py while the diff creates it"))
story.done()
story = Story()
story.checkout("backend", repo.dir)
story.set_diff("diff --git a/src/ghost.py b/src/ghost.py\n--- a/src/ghost.py\n+++ b/src/ghost.py\n@@ -1 +1 @@\n-a\n+b\n", impl)
got = story.by_file()["src/ghost.py"]
check_eq("S4: the diff modifies a file the base lacks -> unknown", (got["state"], got["why"]), ("unknown", f"base {base[:12]} lacks src/ghost.py while the diff modifies it"))
story.done()

# --- S5 / M-6 / M2: the base must reproduce the hunks AND base + hunks must be the implementation's blob ---------------------------
repo = Repo()
c0 = repo.commit({"src/a.py": numbered(), "src/b.py": numbered(40, "b")})
c1 = repo.commit({"src/a.py": edit(numbered(), L10="early 10")})
c2 = repo.commit({"src/a.py": edit(numbered(), L10="early 10", L50="late 50"), "src/b.py": edit(numbered(40, "b"), L5="b5")})
story = Story()
story.checkout("backend", repo.dir)
story.set_diff(repo.diff(c0, c2), c2)
got = story.by_file()
check_eq("S5: a two-commit MR: the file an earlier commit touched is unknown (the parent is not the diff's base), the untouched one is read",
         (got["src/a.py"]["state"], "does not reproduce the hunk" in got["src/a.py"]["why"], got["src/b.py"]["state"]), ("unknown", True, "read"))
story.receipt(7, c2, c0)
story.set_diff(repo.diff(c0, c2), c2, mr=7)
got = story.by_file()
check_eq("S5: with the MR receipt (head == the recorded commit) the base is its base_sha and both files are read",
         (got["src/a.py"]["state"], got["src/a.py"]["base_rev"], got["src/b.py"]["state"]), ("read", c0, "read"))
story.receipt(7, c1, c0)
check_eq("S5: a receipt whose head is another commit is not the base: back to the parent", story.by_file()["src/a.py"]["state"], "unknown")
story.done()

repo = Repo()
c0 = repo.commit({"src/a.py": numbered()})
c1 = repo.commit({"src/a.py": edit(numbered(), L10="X")})
c2 = repo.commit({"src/a.py": edit(numbered(), L50="late 50")})                       # reverts line 10, changes line 50
story = Story()
story.checkout("backend", repo.dir)
story.set_diff(repo.diff(c0, c2), c2)
got = story.by_file()["src/a.py"]
check_eq("M-6 (M3): changed and reverted inside the MR: the parent's old side reproduces the one hunk but its blob is not the base -> unknown",
         (got["state"], "an earlier commit of the MR changed it" in got["why"]), ("unknown", True))
story.done()

# --- the receipt's base without the implementation commit in the checkout (the 13877 case) ------------------------------------------
repo = Repo()
c0 = repo.commit({"src/a.py": numbered(), "src/b.py": numbered(40, "b")})
git(repo.dir, "tag", "base")
c2 = repo.commit({"src/a.py": edit(numbered(), L50="late 50")})
co = temp_dir("qa-bs-co-")
git(co, "init", "-q")
git(co, "fetch", "-q", "--no-tags", str(repo.dir), "refs/tags/base:refs/tags/base")
story = Story(places=["current-code:src/b.py:5"])
story.checkout("backend", co)
story.set_diff(repo.diff(c0, c2), c2, mr=9)
story.receipt(9, c2, c0)
got = story.by_file()
check_eq("receipt: the implementation commit is not in the checkout but the receipt's base is: the hunks are verified alone -> read",
         (got["src/a.py"]["state"], got["src/a.py"]["base_rev"]), ("read", c0))
check_in("receipt: the header says only the hunks were verified", "verified=hunks ", first_text(story.collect()).split("\n")[0])
check_eq("receipt: an untouched file cannot be verified without the implementation commit -> unknown, by name",
         (got["src/b.py"]["state"], "cannot be verified" in got["src/b.py"]["why"]), ("unknown", True))
story.receipt(9, c2, "f" * 40)
check_eq("a base commit absent from the local objects: a refusal naming the route (nothing is fetched)",
         (story.by_file()["src/a.py"]["state"], "nothing is fetched" in story.by_file()["src/a.py"]["why"], story.by_file()["src/a.py"]["base_rev"]), ("unknown", True, ""))
story.done()
shutil.rmtree(co, ignore_errors=True)

# --- F-1: the receipt route looks where the driver writes (work/sources/<SRC>/mr-<iid>.json, any depth) - the ONE locator -------------------
repo = Repo()
c0 = repo.commit({"src/a.py": numbered(), "src/b.py": numbered(40, "b")})
git(repo.dir, "tag", "base")
c2 = repo.commit({"src/a.py": edit(numbered(), L50="late 50")})
co = temp_dir("qa-bs-co-")
git(co, "init", "-q")
git(co, "fetch", "-q", "--no-tags", str(repo.dir), "refs/tags/base:refs/tags/base")
story = Story()
story.checkout("backend", co)
story.set_diff(repo.diff(c0, c2), c2, mr=9)
for where, state, rev in (("sources/SRC-1", "read", c0), ("sources/SRC-1/deep/er", "read", c0), (".", "unknown", ""), ("notes", "unknown", "")):
    shutil.rmtree(story.task / "work" / "sources", ignore_errors=True)
    for stale in (story.task / "work").glob("mr-*.json"):
        stale.unlink()
    shutil.rmtree(story.task / "work" / "notes", ignore_errors=True)
    story.receipt(9, c2, c0, where=where)
    got = story.by_file()["src/a.py"]
    check_eq(f"F-1: a receipt at work/{where}/mr-9.json -> {state} (only work/sources/<SRC>/ at any depth is a route; the old work/mr-9.json is not)",
             (got["state"], got["base_rev"]), (state, rev))
shutil.rmtree(story.task / "work" / "notes", ignore_errors=True)
story.receipt(9, c2, c0, where="sources/SRC-1/deep")
story.receipt(9, c2, c0, where="sources/SRC-2")
(story.task / "work" / "sources" / "SRC-2" / "mr-9.txt").write_bytes(b"x")
(story.task / "work" / "sources" / "SRC-2" / "mr-19.json").write_bytes(b"{}")
check_eq("F-1: the locator is the shared source_exclusions._receipt_files narrowed by name to work/sources/ (never a copy of its walk)",
         BS.receipt_files(story.task, 9), [p for p in SE._receipt_files(story.task / "work") if (story.task / "work" / "sources") in p.parents and p.name == "mr-9.json"])
check_eq("F-1: both receipts of the iid are found (two depths); mr-9.txt and mr-19.json are not receipts of 9",
         [p.relative_to(story.task / "work").as_posix() for p in BS.receipt_files(story.task, 9)], ["sources/SRC-1/deep/mr-9.json", "sources/SRC-2/mr-9.json"])
# t-2277 batch 2b F: the manifest's `mr` is what the story was given - a bare number, `!n` or a URL (the real shapes) - and the
# receipt is found by its number in every form; a value that is no MR number reads as none (the base stays unknown, never guessed).
# t-2548 F3 (AR-13): `vcs_evidence.mr_iid` is the ONE reader (the first look's `Driver._first_look_live_head` calls it too); this table is the
# union of the base slice's shapes and the first look's (`?x=1`, `/diffs`, http, no `-/`), and N4: leading zeros are stripped (`mr-7.json`)
for given, want in (("4214", "4214"), ("!42", "42"), (" 9 ", "9"), (9, "9"), ("https://git.example.com/g/p/-/merge_requests/9", "9"),
                    ("https://git.example.com/g/p/-/merge_requests/9/", "9"), ("", ""), (None, ""), ("!", ""), ("-5", ""), ("4214x", ""), ("!!4", ""),
                    ("http://git.example.com/g/p/-/merge_requests/9", "9"), ("https://git.example.com/g/p/-/issues/9", ""), (True, ""), ([9], ""),
                    ("https://git.example.com/g/p/-/merge_requests/9/diffs", "9"), ("https://git.example.com/g/p/merge_requests/9", "9"),
                    ("https://git.example/g/product/-/merge_requests/7?x=1", "7"), ("https://git.example.com/g/p/-/merge_requests/9#note_1", "9"),
                    ("https://git.example.com/g/p/-/merge_requests/9x", ""), ("https://git.example.com/g/p/-/merge_requests/", ""),
                    ("007", "7"), ("!007", "7"), (7, "7"), ("https://git.example.com/g/p/-/merge_requests/007", "7"), ("0", ""), ("000", ""), ("٣", ""),
                    ("not a number", ""), ("   ", "")):
    check_eq(f"F: mr_iid({given!r}) -> {want!r}", VE.mr_iid(given), want)
check_eq("F: a very long number is read whole, never raises (no int conversion)", VE.mr_iid("9" * 5000), "9" * 5000)
check("F3: base_slice has no reader of its own (one reader of the manifest's mr)", not hasattr(BS, "mr_iid"))
shutil.rmtree(story.task / "work" / "sources", ignore_errors=True)
story.receipt(9, c2, c0)
for given in ("9", "!9", 9, "https://git.example.com/g/p/-/merge_requests/9"):
    story.entries["impl-diff.txt"]["mr"] = given
    (story.task / "work" / "context-manifest.json").write_bytes(json.dumps({"implementations": list(story.entries.values())}).encode())
    got = story.by_file()["src/a.py"]
    check_eq(f"F: the manifest's mr {given!r} finds the receipt of MR 9 -> base read", (got["state"], got["base_rev"]), ("read", c0))
story.entries["impl-diff.txt"]["mr"] = "not a number"
(story.task / "work" / "context-manifest.json").write_bytes(json.dumps({"implementations": list(story.entries.values())}).encode())
got = story.by_file()["src/a.py"]
check_eq("F: an mr that is no number finds no receipt -> unknown, no base", (got["state"], got["base_rev"]), ("unknown", ""))
story.done()
shutil.rmtree(co, ignore_errors=True)

# --- S6 / S7 / S8 / S9 / S10 / S11: the chain's refusals ---------------------------------------------------------------------------------
repo = Repo()
story, base, impl = one(repo, {"src/a.py": edit(numbered(), L5="x")})
diff = story.entries["impl-diff.txt"]
story.set_diff(repo.diff(base, impl), "a" * 40)
check_eq("S6: the commit is not in the checkout -> unknown naming both", story.by_file()["src/a.py"]["why"], f"commit {'a' * 40} is not in {Path(story.cfg['implementation_repos'][0]['local_path']).resolve()}")
for word in ("HEAD", "abc123", "A" * 40, ""):
    calls = []
    real = BS._git
    BS._git = lambda *a, **k: calls.append(a) or (None, b"")
    story.set_diff(repo.diff(base, impl), word)
    got = story.by_file()["src/a.py"]
    BS._git = real
    said = f"source_sha '{word}' is not a commit id" if word else "no source_sha for repo backend"        # the table's reason, WITHOUT its `unmeasured: ` prefix (G1-2, F-6)
    check_eq(f"S9: source_sha {word!r} is no commit id: unknown with the table's reason as is (no wrapper), git never called", (got["state"], got["why"], calls), ("unknown", said, []))
story.set_diff(repo.diff(base, impl), impl)
story.checkout("backend", repo.dir / "nowhere")
check_eq("S10: no checkout on this machine", story.by_file()["src/a.py"]["why"], "no checkout of backend on this machine")
story.checkout("backend", repo.dir / "src" / "a.py")
check_eq("S10: a checkout that is a file", story.by_file()["src/a.py"]["why"], "no checkout of backend on this machine")
story.cfg["implementation_repos"] = []
check_eq("S10: no config entry", story.by_file()["src/a.py"]["why"], "no checkout of backend on this machine")
story.done()

repo = Repo()
root_commit = repo.commit({"src/a.py": numbered()})
story = Story()
story.checkout("backend", repo.dir)
story.set_diff(git(repo.dir, "show", "--format=", "-M", root_commit), root_commit)
check_eq("S7: the root commit has no parent", story.by_file()["src/a.py"]["why"], f"{root_commit} has no parent")
story.done()

repo = Repo()
story, base, impl = one(repo, {"src/a.py": edit(numbered(), L5="x")})
shallow = temp_dir("qa-bs-shallow-")
shutil.rmtree(shallow)
git(repo.dir.parent, "clone", "-q", "--depth", "1", repo.dir.as_uri(), str(shallow))
story.checkout("backend", shallow)
check_eq("S8: a shallow clone: the parent is missing and the reason says why", story.by_file()["src/a.py"]["why"], f"parent of {impl} is not in {shallow.resolve()} (shallow clone)")
story.done()
shutil.rmtree(shallow, ignore_errors=True)

repo_a, repo_b = Repo(), Repo()
base_a = repo_a.commit({"src/a.py": numbered()})
impl_a = repo_a.commit({"src/a.py": edit(numbered(), L5="x")})
base_b = repo_b.commit({"src/b.py": numbered()})
impl_b = repo_b.commit({"src/b.py": edit(numbered(), L5="x")})
story = Story()
story.checkout("backend", repo_a.dir)
story.checkout("ui", temp_dir("qa-bs-gone-") / "missing")
story.set_diff(repo_a.diff(base_a, impl_a), impl_a, name="impl-diff-backend.txt", repo_id="backend")
story.set_diff(repo_b.diff(base_b, impl_b), impl_b, name="impl-diff-ui.txt", repo_id="ui")
got = story.by_file()
check_eq("S11: two repositories: the one without a checkout is unknown, the other is read (each by its own config entry)",
         (got["src/a.py"]["state"], got["src/b.py"]["state"], got["src/b.py"]["why"], got["src/a.py"]["repo"], got["src/b.py"]["repo"]),
         ("read", "unknown", "no checkout of ui on this machine", "backend", "ui"))
story.done()

# F-2: a repository's failure marks ONLY the places in that repository's files; `_one` never sees two records for one place.
def two_repos(ui_checkout, places):
    story = Story(places)
    story.checkout("backend", repo_a.dir)
    if ui_checkout:
        story.checkout("ui", repo_b.dir)
    else:
        story.checkout("ui", temp_dir("qa-bs-gone-") / "missing")
    story.set_diff(repo_a.diff(base_a, impl_a), impl_a, name="impl-diff-backend.txt", repo_id="backend")
    story.set_diff(repo_b.diff(base_b, impl_b), impl_b, name="impl-diff-ui.txt", repo_id="ui")
    return story
unchanged_row = {"r": "R-1", "observable": "current-code:src/a.py:90", "delta": "unchanged"}
for ui_checkout in (True, False):
    story = two_repos(ui_checkout, ["current-code:src/a.py:90"])
    col = story.collect()
    check_eq(f"F-2: two repositories, ui checkout {'present' if ui_checkout else 'MISSING'}: the place in backend's file is evidenced at the base line",
             BS.unchanged_evidence(unchanged_row, story.task, collected=col), ("evidenced", f"base:{base_a}:src/a.py:90", ""))
    check_eq(f"F-2: ui checkout {'present' if ui_checkout else 'MISSING'}: the records (repo, file, state) - ui never gets a record for backend's src/a.py",
             [(e["repo"], e["file"], e["state"]) for e in col.entries], [("backend", "src/a.py", "read"), ("ui", "src/b.py", "read" if ui_checkout else "unknown")])
    story.done()
# m-9: a place no repository base holds is pinned to NO repository; the reason says which repositories could not be checked
for ui_checkout in (True, False):
    story = two_repos(ui_checkout, ["current-code:src/nowhere.py:3"])
    col = story.collect()
    ghost = [e for e in col.entries if e["file"] == "src/nowhere.py"]
    check_eq(f"m-9: a place in no repository's base (ui checkout {'present' if ui_checkout else 'MISSING'}) -> one record, repo '' (never the first diff's), unknown, `repo unresolved`",
             (len(ghost), ghost[0]["repo"], ghost[0]["state"], ghost[0]["why"].startswith("repo unresolved")), (1, "", "unknown", True))
    check_eq("m-9: the unchecked repository is named in the reason only when one failed",
             "not checked: ui: no checkout of ui on this machine" in ghost[0]["why"], not ui_checkout)
    check_eq("m-9: the predicate reports the unknown record, not evidence",
             BS.unchanged_evidence({"r": "R-1", "observable": "current-code:src/nowhere.py:3", "delta": "unchanged"}, story.task, collected=col)[0], "unevidenced")
    story.done()
# F-2 at the batch step: git answers for the checkout of one repo with an error -> that repo's files only
story = two_repos(True, ["current-code:src/a.py:90"])
real = BS._blobs
BS._blobs = lambda checkout, specs: ({}, "git cat-file exited 128 in broken") if Path(checkout) == repo_b.dir.resolve() else real(checkout, specs)
col = story.collect()
BS._blobs = real
check_eq("F-2: a failed batch read in ui marks ui's own file; the place of backend's file is still evidenced",
         ([(e["repo"], e["file"], e["state"]) for e in col.entries], BS.unchanged_evidence(unchanged_row, story.task, collected=col)[0]),
         ([("backend", "src/a.py", "read"), ("ui", "src/b.py", "unknown")], "evidenced"))
story.done()

# --- S12 / S13 / S14 / S15: binary, rename, delete, a path outside the repository ---------------------------------------------------------
repo = Repo()
story, base, impl = one(repo, {"src/bin.py": b"\x00\x01\x02 binary\n", "src/old.py": numbered(60, "o")})
base2 = impl
impl2 = repo.commit({"src/bin.py": b"\x00\x01\x03 binary2\n", "src/old.py": None, "src/renamed.py": edit(numbered(60, "o"), L30="renamed 30"), "src/a.py": None})
story.set_diff(repo.diff(base2, impl2), impl2)
got = story.by_file()
check_eq("S12: a binary file (NUL) is unknown, named", (got["src/bin.py"]["state"], got["src/bin.py"]["why"]), ("unknown", BS.NOT_UTF8))
check_eq("S13: a rename with a change: read at the new path, `renamed from` the old one, the old side from the old path",
         (got["src/renamed.py"]["state"], got["src/renamed.py"]["why"], "src/old.py" in got), ("read", "renamed from src/old.py", False))
check_eq("S14: a deleted file is read (the whole 'before' is in the slice)", got["src/a.py"]["state"], "read")
story.done()

repo = Repo()
base = repo.commit({"src/latin.py": b"caf\xe9 = 1\n" * 3})
impl = repo.commit({"src/latin.py": b"caf\xe9 = 2\n" * 3})
story = Story()
story.checkout("backend", repo.dir)
story.set_diff(repo.diff(base, impl), impl)
check_eq("S12: bytes that are not UTF-8 are unknown (no text is invented)", story.by_file()["src/latin.py"]["why"], BS.NOT_UTF8)
story.done()

repo = Repo()
story, base, impl = one(repo, {"src/a.py": edit(numbered(), L5="x")})
for bad in ("../x.py", "src/../x.py", "/etc/x.py", "./src/z.py", "src\\z.py"):
    story.set_diff(f"diff --git a/{bad} b/{bad}\n--- a/{bad}\n+++ b/{bad}\n@@ -1 +1 @@\n-a\n+b\n", impl)
    got = story.by_file().get(bad)
    check_eq(f"S15: the path {bad!r} is outside / not canonical -> unknown, no git object asked", (got or {}).get("state"), "unknown")
story.done()

# --- S17 / S18: the size cap AT and BEYOND; a git that does not answer -> the whole repo unknown, nothing partial ---------------------------
repo = Repo()
story, base, impl = one(repo, {"src/a.py": edit(numbered(), L50="changed 50")})
size = len(first_text(story.collect()).split("\n", 1)[-1].encode("utf-8"))
cap = BS.MAX_SLICE_BYTES
BS.MAX_SLICE_BYTES = size
at = story.by_file()["src/a.py"]
BS.MAX_SLICE_BYTES = size - 1
beyond = story.by_file()["src/a.py"]
BS.MAX_SLICE_BYTES = cap
check_eq("S17: a body of exactly the cap is read; one byte over is unknown (never cut)", (at["state"], beyond["state"], beyond["why"]),
         ("read", "unknown", f"base slice is {size} bytes, over {size - 1}"))
timeout = TN.GIT_TIMEOUT
TN.GIT_TIMEOUT = 0
got = story.by_file()
TN.GIT_TIMEOUT = timeout
check_eq("S18: git that does not finish in time: every file of the repo is unknown, no partial output", [(e["state"], e["why"].startswith("git did not run or did not finish")) for e in got.values()], [("unknown", True)])
story.done()

# --- S19 / S20: the working tree is never read; GIT_DIR is not trusted -----------------------------------------------------------------------
repo = Repo()
story, base, impl = one(repo, {"src/a.py": edit(numbered(), L50="changed 50")})
(repo.dir / "src" / "a.py").write_bytes(b"DIRTY\r\n" * 100)
git(repo.dir, "config", "core.autocrlf", "true")
col = story.collect()
text = first_text(col)
check_eq("S19: a dirty working tree and autocrlf do not change the slice (the blob is read)", ("DIRTY" in text, "50| line 50" in text, story.by_file(col)["src/a.py"]["state"]), (False, True, "read"))
story.done()

repo = Repo()
other = Repo()
other.commit({"x.txt": "x\n"})
story, base, impl = one(repo, {"src/a.py": edit(numbered(), L50="changed 50")})
os.environ["GIT_DIR"] = str(other.dir / ".git")
try:
    got = story.by_file()["src/a.py"]
finally:
    del os.environ["GIT_DIR"]
check_eq("S20: GIT_DIR on a foreign repository: unknown, never the foreign bytes", (got["state"], got["why"].startswith("commit ")), ("unknown", True))
crlf = Repo()
base = crlf.commit({"src/a.py": numbered().replace("\n", "\r\n")})
impl = crlf.commit({"src/a.py": edit(numbered(), L50="changed 50").replace("\n", "\r\n")})
story = Story()
story.checkout("backend", crlf.dir)
story.set_diff(crlf.diff(base, impl), impl)
check_eq("S19: a CRLF base is still the base (one trailing CR dropped on both sides)", story.by_file()["src/a.py"]["state"], "read")
story.done()

# --- S21 / S22: prepare writes the files and the key once; the other keys are byte for byte; no diff -> []; the key's refusals -----------
repo = Repo()
story, base, impl = one(repo, {"src/a.py": edit(numbered(), L50="changed 50")}, places=["current-code:src/a.py:5"])
(story.task / "work" / "requirements-register.md").write_bytes(b"# Register\n\n## Register\n\n| R | Requirement | source | derived_from | verifiable | ac_ref | observable | impact | delta |\n|---|---|---|---|---|---|---|---|---|\n| R-1 | thing | ac | - | yes | AC1 | diff:src/a.py:5 | access | new |\n")
try:
    BS.prepare(story.task, project=story.root, cfg=story.cfg)
    refused = ""
except GT.Refusal as exc:
    refused = exc.text
check_in("a missing table is a refusal that names the fix and writes nothing", "grounding_table.py --refresh", refused)
check("S21: nothing was written by the refused call", not (story.task / "work" / "base-slice").exists())
GT._cmd_skeleton_or_refresh(story.task, False, False)
before = GT.table_path(story.task).read_bytes()
BS.prepare(story.task, project=story.root, cfg=story.cfg)
first = GT.table_path(story.task).read_bytes()
files1 = {p.name: p.read_bytes() for p in (story.task / "work" / "base-slice").glob("*.txt")}
BS.prepare(story.task, project=story.root, cfg=story.cfg)
check_eq("S21: the second run gives the same bytes, key and files", (GT.table_path(story.task).read_bytes() == first, {p.name: p.read_bytes() for p in (story.task / "work" / "base-slice").glob("*.txt")} == files1), (True, True))
check("S21: every other key of the table is byte for byte (the key is appended)", first.startswith(before) and first[len(before):].startswith(b"base_slice:"))
doc, problem = PC.read_grounding(story.task)
check_eq("S21: the key is read back by the one reader, in the form of the schema", (problem, sorted(doc.data["base_slice"][0])), ("", ["base_rev", "file", "path", "repo", "state", "why"]))
(story.task / "work" / "base-slice" / "stale.txt").write_bytes(b"old\n")
BS.prepare(story.task, project=story.root, cfg=story.cfg)
check("a slice file that no record names is removed at the next run (the slice does not outlive its diff)", not (story.task / "work" / "base-slice" / "stale.txt").exists())
story.save_config()
done = run_script("base_slice.py", "--task", "T-1", "--json", cwd=story.root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(story.root), PYTHONDONTWRITEBYTECODE="1"))
check_eq("CLI: --json prints the records, exit 0, and writes nothing", (done.returncode, json.loads(done.stdout)["base_slice"][0]["state"], GT.table_path(story.task).read_bytes() == first), (0, "read", True))
done = run_script("base_slice.py", "--task", "NOPE-1", cwd=story.root, env=dict(os.environ, CLAUDE_PROJECT_DIR=str(story.root)))
check_eq("CLI: a ticket key that names no story is a refusal, exit 2", done.returncode, 2)
rel = C.artifact_write_path(story.task, "base-slice").relative_to(story.task).as_posix()
check("m-1: the key `path` is the resolver's folder relative to the task (axis 8), and the files are written there",
      all(e["path"].startswith(rel + "/") for e in doc.data["base_slice"] if e["state"] == "read") and (story.task / rel).is_dir())
shutil.rmtree(story.task / "work" / "base-slice")
real = C.artifact_write_path
C.artifact_write_path = lambda root, name: Path(root) / "work" / "moved" / name if name == "base-slice" else real(root, name)   # noqa: E501
try:
    BS.prepare(story.task, project=story.root, cfg=story.cfg)
finally:
    C.artifact_write_path = real
doc, problem = PC.read_grounding(story.task)
check_eq("m-1: a resolver that moves the folder moves the files AND the key path (nothing hard-coded in base_slice)",
         ([e["path"].startswith("work/moved/base-slice/") for e in doc.data["base_slice"]], (story.task / "work" / "moved" / "base-slice").is_dir(),
          (story.task / "work" / "base-slice").exists()), ([True], True, False))
# (the resolver moved only the slice folder; the table stays where it is - the patch above names "base-slice" alone)
check_eq("m-2: _span is (start, count): a range, or the two lines around an empty side", (BS._span(10, 3), BS._span(10, 0)), ((10, 12), (10, 11)))
source = Path(BS.__file__).read_text(encoding="utf-8")
check("m-4 (FR-29): base_slice.py is plain ASCII - no literal BOM or control byte (the BOM is chr(0xFEFF))", all(ch == "\n" or 32 <= ord(ch) < 127 for ch in source))
story.done()

repo = Repo()
story, base, impl = one(repo, {"src/a.py": edit(numbered(), L50="changed 50"), "tests/test_a.py": "x\n", "README.md": "doc\n"})
check_eq("F-1 (c): only changed files of kind production/config get a record (tests and docs do not)", sorted(story.by_file()), ["src/a.py"])
story.done()
story = Story()
(story.task / "pipeline.json").write_bytes(json.dumps({"ticket": "T-1", "stages": {}}).encode())
col = story.collect()
check_eq("S22: no implementation source and no diff -> the list is empty and the source is named `absent`", (col.source, col.entries), ("absent", []))
GT._cmd_skeleton_or_refresh(story.task, False, False)
BS.prepare(story.task, project=story.root, cfg=story.cfg)
check_eq("S22: the null outcome's table gets `base_slice: []` (exit 0 road)", PC.read_grounding(story.task)[0].data["base_slice"], [])
story.done()

# --- S23: the predicate: evidenced on an untouched line; every inconvenient input stays unevidenced --------------------------------------------
repo = Repo()
c0 = repo.commit({"src/a.py": numbered(), "src/other.py": numbered(10, "o")})
c1 = repo.commit({"src/a.py": edit(numbered(), L10="ten\ninserted 1\ninserted 2", L80="eighty")})
story = Story()
story.checkout("backend", repo.dir)
story.set_diff(repo.diff(c0, c1), c1)
col = story.collect()
row = lambda obs, delta="unchanged": {"r": "R-1", "observable": obs, "delta": delta}                     # noqa: E731
ev = lambda obs, **k: BS.unchanged_evidence(row(obs), story.task, collected=col, **k)                    # noqa: E731
got = ev("current-code:src/a.py:70")
check_eq("S23: a new-side line below the inserted lines is evidenced at the base line (shifted by 2)", got, ("evidenced", f"base:{c0}:src/a.py:68", ""))
check_eq("S23: a base: place on an untouched line is evidenced", ev(f"base:{c0}:src/a.py:30")[0], "evidenced")
check_eq("S23: backticks around the cell are stripped", ev(f"`base:{c0}:src/a.py:30`")[0], "evidenced")
bad = {"inside a hunk (new side)": "current-code:src/a.py:82", "inside a hunk (old side)": f"base:{c0}:src/a.py:80",
       "a context line of a hunk counts as touched": "current-code:src/a.py:79", "a short revision": f"base:{c0[:12]}:src/a.py:30",
       "another revision": f"base:{'1' * 40}:src/a.py:30", "line 0": "current-code:src/a.py:0", "line -1": "current-code:src/a.py:-1",
       "line 12a": "current-code:src/a.py:12a", "line 12.0": "current-code:src/a.py:12.0", "a ./ path (B-1)": "current-code:./src/a.py:42",
       "a backslash path": "current-code:src\\a.py:42", "a diff: place": "diff:src/a.py:3", "an empty cell": "", "past the end": "current-code:src/a.py:5000",
       "a file with no record": "current-code:src/nowhere.py:1", "a file the diff does not touch but the register does not name": f"base:{c0}:src/other.py:3",
       "an upper-case path": "current-code:SRC/a.py:42"}
for name, obs in bad.items():
    check_eq(f"S23: {name} -> unevidenced with a reason", (ev(obs)[0], bool(ev(obs)[2])), ("unevidenced", True))
check_eq("S23: a row that is not `unchanged` is not for this function", BS.unchanged_evidence(row("current-code:src/a.py:70", "changed"), story.task, collected=col), ("unevidenced", "", "not unchanged"))
check_eq("S23: a ./ path makes no record in the file set (M1b: the set takes the canonical form)", [e["file"] for e in BS.collect(story.task, project=story.root, cfg=story.cfg).entries if e["file"].startswith(".")], [])
story.done()

# --- B-1 / M1: the predicate ALONE refuses a non-canonical place even if a record for it existed ------------------------------------------
story = Story(places=["current-code:./src/a.py:42"])
story.checkout("backend", repo.dir)
story.set_diff(repo.diff(c0, c1), c1)
col = story.collect()
check_eq("B-1: a `./src/a.py` place of an unchanged row makes no record (the file set is canonical)", sorted(e["file"] for e in col.entries), ["src/a.py"])
fed = BS.collect(story.task, project=story.root, cfg=story.cfg)
fake = type(fed.infos[0])(base_path="./src/a.py", lines=100, windows=[(1, 100)], deleted=False, hunks=[], entry={
    "repo": "", "file": "./src/a.py", "base_rev": c0, "path": "work/base-slice/x.txt", "state": "read", "why": ""})
fed.infos, fed.entries = [fake], [fake.entry]
check_eq("B-1 (M1): with such a record fed in by hand, the predicate still says unevidenced - inside the hunk of `src/a.py` or not",
         [BS.unchanged_evidence(row(obs), story.task, collected=fed)[0] for obs in ("current-code:./src/a.py:42", "current-code:./src/a.py:5", f"base:{c0}:./src/a.py:5")],
         ["unevidenced"] * 3)
story.done()

# --- -U0 neighbours of a cut ---------------------------------------------------------------------------------------------------------------
repo = Repo()
c0 = repo.commit({"src/a.py": numbered()})
c1 = repo.commit({"src/a.py": "".join(l for i, l in enumerate(numbered().splitlines(True), 1) if i != 30)})
story = Story()
story.checkout("backend", repo.dir)
story.set_diff(repo.diff(c0, c1, "-U0"), c1)
col = story.collect()
ev = lambda obs: BS.unchanged_evidence(row(obs), story.task, collected=col)[0]                          # noqa: E731
check_eq("S23: a deletion with no context: the line before and the line after the cut are touched, the next one is not (shift -1 -> base 32)",
         (ev("current-code:src/a.py:29"), ev("current-code:src/a.py:30"), BS.unchanged_evidence(row("current-code:src/a.py:31"), story.task, collected=col)), ("unevidenced", "unevidenced", ("evidenced", f"base:{c0}:src/a.py:32", "")))
story.done()
repo = Repo()
c0 = repo.commit({"src/a.py": numbered()})
c1 = repo.commit({"src/a.py": edit(numbered(), L50="line 50\nfifty-one")})
story = Story()
story.checkout("backend", repo.dir)
story.set_diff(repo.diff(c0, c1, "-U0"), c1)
col = story.collect()
check_eq("S23: an insertion with no context: base lines old_start and old_start+1 are touched, the lines beyond are not",
         [BS.unchanged_evidence(row(f"base:{c0}:src/a.py:{n}"), story.task, collected=col)[0] for n in (49, 50, 51, 52)], ["evidenced", "unevidenced", "unevidenced", "evidenced"])
story.done()

# --- M4: the judgement is recomputed after the diff moved (--refresh), never cached ------------------------------------------------------------
repo = Repo()
c0 = repo.commit({"src/a.py": numbered()})
c1 = repo.commit({"src/a.py": edit(numbered(), L50="changed 50")})
git(repo.dir, "checkout", "-q", "-b", "alt", c0)
c3 = repo.commit({"src/a.py": edit(numbered(), L20="changed 20")})
story = Story(places=["current-code:src/a.py:20"])
story.checkout("backend", repo.dir)
story.set_diff(repo.diff(c0, c1), c1)
first = BS.unchanged_evidence(row("current-code:src/a.py:20"), story.task, project=story.root, cfg=story.cfg)
story.set_diff(repo.diff(c0, c3), c3)
second = BS.unchanged_evidence(row("current-code:src/a.py:20"), story.task, project=story.root, cfg=story.cfg)
check_eq("M4: the same place is evidenced before the diff moved and unevidenced after (nothing is cached across --refresh)", (first[0], second[0]), ("evidenced", "unevidenced"))
problem = lambda ref: BS.base_place_problem(ref, story.task, project=story.root, cfg=story.cfg)                # noqa: E731
check_eq("F-6C: base_place_problem: a line inside a window of the read base is fine; another revision / a path / a line past the end is a reason",
         [bool(problem(f"base:{c0}:src/a.py:{n}")) for n in (1, 20, 53)] +
         [bool(problem(f"base:{'2' * 40}:src/a.py:20")), bool(problem("diff:src/a.py:5")), bool(problem(f"base:{c0}:src/a.py:101"))],
         [False, False, False, True, True, True])
# the diff of this fixture is c0..c3: one hunk at base lines 17..23, so the window is 1..53 (the hunk +-30 clipped at 1)
check_eq("m-3: a line of the file's base the role never got (outside the windows: AT the edge 53 is in, 54 and 100 are out) is a reason naming the windows",
         [bool(problem(f"base:{c0}:src/a.py:{n}")) for n in (53, 54, 100)] + ["outside the slice windows" in problem(f"base:{c0}:src/a.py:54")], [False, True, True, True])
story.done()

# --- M5 / S24: the chain goes through the table's matcher: the 13877 copy (3 manifest entries, key `repo`, one with a diff) ---------------------
if REAL.is_dir():
    story = Story()
    shutil.rmtree(story.task)
    shutil.copytree(REAL, story.task, ignore=shutil.ignore_patterns("state"))
    (story.task / "pipeline.json").write_bytes(json.dumps({"ticket": "T-1", "stages": {}, "implementation_source": "diff"}).encode())
    col = BS.collect(story.task, project=story.root, cfg={})
    check_eq("S24 (M5): the real 13877 copy with no checkout configured: every record is unknown `no checkout of testproject1-backend` (the other two repos have no diff and no record)",
             (len(col.entries), {e["state"] for e in col.entries}, {e["why"] for e in col.entries}, {e["repo"] for e in col.entries}),
             (11, {"unknown"}, {"no checkout of testproject1-backend on this machine"}, {""}))
    story.done()
    # F-1 on the real data: the receipt of the copy lies at the OLD place (work/mr-4340.json) - not a route; at the driver's place
    # (work/sources/<SRC>/mr-4340.json) it names the base (4 read, 7 absent). Needs the stand's clone; without it a named SKIP.
    stand = REAL.parents[2] / "testproject1-dev-fresh" / "testproject1"
    if (stand / ".git").exists() and (REAL / "work" / "mr-4340.json").is_file():
        def real_states(receipt_at):
            story = Story()
            shutil.rmtree(story.task)
            shutil.copytree(REAL, story.task, ignore=shutil.ignore_patterns("state"))
            (story.task / "pipeline.json").write_bytes(json.dumps({"ticket": "T-1", "stages": {}, "implementation_source": "diff"}).encode())
            old = story.task / "work" / "mr-4340.json"
            if receipt_at:
                (story.task / "work" / receipt_at).mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(story.task / "work" / receipt_at / "mr-4340.json"))
            cfg = {"implementation_repos": [{"repo_id": "testproject1-backend", "local_path": str(stand)}]}
            got = BS.collect(story.task, project=story.root, cfg=cfg).entries
            story.done()
            return {s: sum(1 for e in got if e["state"] == s) for s in sorted({e["state"] for e in got})}, {e["why"][:12] for e in got if e["state"] == "unknown"}                                    # "commit 66014"
        check_eq("F-1 (S24b): the real 13877 copy, receipt at the driver's path work/sources/<SRC>/ -> 4 read / 7 absent, no unknown",
                 real_states("sources/SRC-1")[0], {"absent": 7, "read": 4})
        check_eq("F-1 (S24b): the same copy with the receipt at the old place work/mr-4340.json only -> not a route: 11 unknown, the commit is not in the clone",
                 real_states(None), ({"unknown": 11}, {"commit 66014"}))
    else:
        print("SKIP S24b (F-1 on the real receipt): the stand clone testproject1-dev-fresh/testproject1 or work/mr-4340.json is not on this machine (the synthetic F-1 pins above still run)")
else:
    print("SKIP S24 / S24b: experiments/TP1-13877 is not in this tree (released package or docker copy); the synthetic pins above still run")

finish("test_base_slice")
