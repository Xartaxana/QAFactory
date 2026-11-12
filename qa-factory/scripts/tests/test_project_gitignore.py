"""project_gitignore.py: the block is written once, whole and contiguous, untouched otherwise.

t-232 C11 / K4: a reinstall ends with the file a fresh install writes, so the stray first-generation
line is taken out and the block is put back as ONE piece; the project's own lines keep their
places and their order.

Run: python -B scripts/tests/test_project_gitignore.py
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import project_gitignore as G  # noqa: E402
import install_paths  # noqa: E402

GEN1 = "qa-factory/artifacts/*/work/evidence/"
SCRIPT = Path(__file__).resolve().parents[1] / "project_gitignore.py"


def read(root: Path) -> str:
    return (root / ".gitignore").read_bytes().decode("utf-8")


def block_at(lines: list, start: int) -> bool:
    return lines[start:start + len(G.GITIGNORE_BLOCK)] == G.GITIGNORE_BLOCK


def main() -> None:
    root = temp_dir("qa-gitignore-")
    try:
        # No .gitignore at all -> the whole block is what a write has to put in.
        check_eq("fresh project: every block line is to be written", G.missing_lines(root), G.GITIGNORE_BLOCK)
        added = G.write_block(root)
        check_eq("write_block reports every line written", added, G.GITIGNORE_BLOCK)
        text = read(root)
        check_eq("fresh project: exactly the header and the block, one newline at the end",
                 text, "\n".join([G.HEADER, *G.GITIGNORE_BLOCK]) + "\n")
        check("factory-dashboard.html is NOT separately excepted (owner's call, 22.09)", "factory-dashboard.html" not in text)

        # Idempotent: a second write on an up-to-date file changes nothing, not even the bytes' mtime.
        before = (root / ".gitignore").stat().st_mtime_ns
        check_eq("second write reports nothing", G.write_block(root), [])
        check_eq("second write does not touch the file", ((root / ".gitignore").stat().st_mtime_ns, read(root)), (before, text))
        check_eq("an up-to-date file has nothing missing", G.missing_lines(root), [])

        # K4: the project's own two lines + the stray first-generation line (what a gen-1 install left).
        old = temp_dir("qa-gitignore-gen1-")
        try:
            (old / ".gitignore").write_bytes(f"node_modules/\n.env\n{GEN1}\n".encode("utf-8"))
            check_eq("the table's gitignore_lines names the first generation's line, and it is the block's first line",
                     ([r["line"] for r in install_paths.gitignore_lines() if r["generation"] == 1], G.GITIGNORE_BLOCK[0]),
                     ([GEN1], GEN1))
            check_eq("gen-1 project: the block is not in place", G.missing_lines(old), G.GITIGNORE_BLOCK)
            G.write_block(old)
            lines = read(old).splitlines()
            check_eq("K4: the project's own two lines are unchanged and in place", lines[:2], ["node_modules/", ".env"])
            start = lines.index(G.GITIGNORE_BLOCK[0])
            check("K4: the block lines are contiguous", block_at(lines, start), "\n".join(lines))
            check_eq("K4: the first-generation line stands exactly once", lines.count(GEN1), 1)
            check_eq("K4: our header stands once, directly above the block", (lines.count(G.HEADER), lines[start - 1]), (1, G.HEADER))
            check_eq("K4: one blank line between the project's lines and ours", lines[2], "")
            check_eq("K4: nothing else was added", len(lines), 2 + 1 + 1 + len(G.GITIGNORE_BLOCK))
            # And a reinstall of a reinstall is a no-op.
            check_eq("K4: a second write is a no-op", G.write_block(old), [])
        finally:
            cleanup(old)

        # The stray line stands among the project's own lines: they keep their order, the stray goes.
        mid = temp_dir("qa-gitignore-mid-")
        try:
            (mid / ".gitignore").write_bytes(f"a/\n{GEN1}\nb/\n".encode("utf-8"))
            G.write_block(mid)
            lines = read(mid).splitlines()
            check_eq("a stray line between two project lines: they stay in order, nothing between them but the removal",
                     lines[:2], ["a/", "b/"])
            check_eq("...and the stray line is back once, inside the block", lines.count(GEN1), 1)
            check("...and the block is contiguous", block_at(lines, lines.index(G.GITIGNORE_BLOCK[0])))
        finally:
            cleanup(mid)

        # A partial block of an earlier generation (some lines, any order): taken out, put back whole.
        partial = temp_dir("qa-gitignore-partial-")
        try:
            (partial / ".gitignore").write_text(
                "node_modules/\n!qa-factory/state/journal.jsonl\nqa-factory/state/*\nbuild/\n", encoding="utf-8")
            check_eq("partial block: the whole block is to be put back (not 'the remaining five')",
                     G.missing_lines(partial), G.GITIGNORE_BLOCK)
            G.write_block(partial)
            lines = read(partial).splitlines()
            check_eq("partial block: the project's own lines keep their order", [l for l in lines if l in ("node_modules/", "build/")],
                     ["node_modules/", "build/"])
            check_eq("partial block: each line of the block stands exactly once", [lines.count(l) for l in G.GITIGNORE_BLOCK],
                     [1] * len(G.GITIGNORE_BLOCK))
            check("partial block: and they are contiguous, in the order the negations need",
                  block_at(lines, lines.index(G.GITIGNORE_BLOCK[0])))
            check_eq("partial block: fully up to date after the write", G.missing_lines(partial), [])
        finally:
            cleanup(partial)

        # The block is complete but the header of the first versions stands above it: one header after.
        legacy = temp_dir("qa-gitignore-header-")
        try:
            old_header = G.OLD_HEADERS[0]
            (legacy / ".gitignore").write_text("x/\n\n" + old_header + "\n" + "\n".join(G.GITIGNORE_BLOCK) + "\n", encoding="utf-8")
            G.write_block(legacy)
            text = read(legacy)
            check_eq("an old header is replaced, not duplicated", (text.count(old_header), text.count(G.HEADER)), (0, 1))
            check_eq("...and the project's line stays", text.splitlines()[0], "x/")
        finally:
            cleanup(legacy)

        # The project's line endings stay theirs.
        crlf = temp_dir("qa-gitignore-crlf-")
        try:
            (crlf / ".gitignore").write_bytes(b"node_modules/\r\n.env\r\n")
            G.write_block(crlf)
            raw = (crlf / ".gitignore").read_bytes()
            check("a CRLF file stays CRLF: no bare LF anywhere", b"\n" not in raw.replace(b"\r\n", b""), repr(raw[:60]))
            check_eq("...and the project's lines are byte-identical", raw.split(b"\r\n")[:2], [b"node_modules/", b".env"])
        finally:
            cleanup(crlf)

        # --check CLI contract: exit 1 with the block while it is not in place, exit 0 once written.
        fresh = temp_dir("qa-gitignore-check-")
        try:
            def cli(*args):
                return subprocess.run([sys.executable, "-B", str(SCRIPT), "--root", str(fresh), *args],
                                      capture_output=True, text=True, encoding="utf-8")
            r1 = cli("--check")
            check_eq("--check exits 1 on a project missing the block", r1.returncode, 1)
            check("--check lists a block line", "qa-factory/state/" in r1.stdout)
            check_eq("--write exits 0", cli("--write").returncode, 0)
            r3 = cli("--check")
            check_eq("--check exits 0 once the block is written", r3.returncode, 0)
            check_eq("--check prints nothing once up to date", r3.stdout.strip(), "")
            (fresh / ".gitignore").write_bytes(f"{GEN1}\n".encode("utf-8"))
            check_eq("--check exits 1 for a file that only holds the stray first-generation line", cli("--check").returncode, 1)
        finally:
            cleanup(fresh)

        # t-232 F7+F8: the block is DERIVED from the table - one line per untracked class folder, none
        # for the tracked one, no per-file exceptions.
        table = install_paths.load_table()
        untracked = [f["path"] for f in install_paths.folders(table) if not f["tracked"]]
        tracked = [f["path"] for f in install_paths.folders(table) if f["tracked"]]
        check_eq("F7: the block is the generated files inside the artifacts, then ONE line for the ignored folder",
                 G.GITIGNORE_BLOCK, [*table["gitignore_block"]["inside_tracked"], "qa-factory/state/"])
        check_eq("F7: the ignored folder is exactly qa-factory/state, the tracked one qa-factory/records", (untracked, tracked),
                 (["qa-factory/state"], ["qa-factory/records"]))
        check("OH3-33: the block names the exported evidence folder of a story and keeps the first generation's line first",
              "qa-factory/artifacts/*/evidence/" in G.GITIGNORE_BLOCK and G.GITIGNORE_BLOCK[0] == GEN1, str(G.GITIGNORE_BLOCK))
        check("OH3-33: every block line is relative (AR-4: no machine path, no drive, no backslash)",
              not any(line.startswith("/") or ":" in line or "\\" in line for line in G.GITIGNORE_BLOCK), str(G.GITIGNORE_BLOCK))
        check("F7: no line names the tracked folder records/ - it must stay visible to git",
              not any("records" in line for line in G.GITIGNORE_BLOCK), str(G.GITIGNORE_BLOCK))
        check("F7: no per-file exception survives (no `!` line, no `state/*`)",
              not any(line.startswith("!") or line.endswith("/*") for line in G.GITIGNORE_BLOCK), str(G.GITIGNORE_BLOCK))
        check_eq("F7: one line per untracked folder, however many files it holds",
                 [sum(1 for line in G.GITIGNORE_BLOCK if line == f + "/") for f in untracked], [1])
        spare = {"folders": [{"path": "qa-factory/records", "tracked": True}, {"path": "qa-factory/state", "tracked": False},
                             {"path": "qa-factory/scratch", "tracked": False}], "gitignore_block": {"inside_tracked": ["a/b/"]}}
        check_eq("F7: the derivation follows the table: a new untracked folder is a new line, a tracked one never is",
                 install_paths.gitignore_block(spare), ["a/b/", "qa-factory/state/", "qa-factory/scratch/"])

        # A project with the 22.09 block (per-file exceptions) gets the block as one piece, nothing of it left.
        old_block = temp_dir("qa-gitignore-0922-")
        try:
            lines_0922 = ["qa-factory/artifacts/*/work/evidence/", "qa-factory/artifacts/*/work/*fragment*.json",
                          "qa-factory/artifacts/*/work/impl-diff*.txt", "qa-factory/state/*", "!qa-factory/state/journal.jsonl",
                          "!qa-factory/state/coverage-map.md", "!qa-factory/state/estimation-ledger.jsonl"]
            (old_block / ".gitignore").write_text("node_modules/\n\n" + G.OLD_HEADERS[0] + "\n" + "\n".join(lines_0922) + "\nbuild/\n",
                                                  encoding="utf-8")
            check_eq("the 22.09 block is not the block of this version", G.missing_lines(old_block), G.GITIGNORE_BLOCK)
            G.write_block(old_block)
            got = read(old_block).splitlines()
            check_eq("the 22.09 block: none of its per-file lines is left", [l for l in got if l.startswith("!") or l == "qa-factory/state/*"], [])
            check_eq("the 22.09 block: the project's own lines keep their order, the block is one piece at the end",
                     (got[:2], got[-len(G.GITIGNORE_BLOCK):], "build/" in got), (["node_modules/", ""], G.GITIGNORE_BLOCK, True))
            check_eq("the 22.09 block: our header stands once", got.count(G.HEADER), 1)
            check_eq("the 22.09 block: a second write is a no-op", G.write_block(old_block), [])
        finally:
            cleanup(old_block)
    finally:
        cleanup(root)
    finish("test_project_gitignore")


if __name__ == "__main__":
    main()
