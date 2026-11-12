"""hooklib.sorted_paths - the one order of a Path walk (t-892 / C4-7, after t-887).

`sorted(<Path>)` compares the path PARTS with the platform's flavour (case-folded on Windows, case-sensitive
on Linux), so the lines of a refusal or a report built from a walk came out in a different order on a
developer's machine and in CI. `sorted_paths` orders by `as_posix()`: the code point of the whole string.

The order pins use PureWindowsPath / PurePosixPath, whose comparison rules are those of their flavour on EVERY
platform, so the Windows half of the old defect is pinned on Linux and the Linux half on Windows. One pin walks a
real directory too. Run it in docker (python:3.12) as well as on Windows: each platform's own `Path` is only
exercised there.
"""
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooklib as H
from harness import temp_dir, cleanup, check, check_eq, finish


def _names(paths):
    return [p.as_posix() for p in paths]


def main() -> None:
    # --- the flavour split, pinned on any platform ---
    win = [PureWindowsPath(x) for x in ("a/x.md", "B/x.md", "TC-001.md")]
    check_eq("the premise: sorted(PureWindowsPath) case-folds - a/, B/, TC-001 (the old Windows order)",
             _names(sorted(win)), ["a/x.md", "B/x.md", "TC-001.md"])
    check_eq("sorted_paths on Windows-flavour Paths is by code point - B/, TC-001, a/ (uppercase first)",
             _names(H.sorted_paths(win)), ["B/x.md", "TC-001.md", "a/x.md"])

    posix = [PurePosixPath(x) for x in ("a/x.md", "a.md", "a-b/x.md")]
    check_eq("the premise: sorted(PurePosixPath) compares parts - a/x.md before a-b/ and a.md",
             _names(sorted(posix)), ["a/x.md", "a-b/x.md", "a.md"])
    check_eq("sorted_paths on POSIX-flavour Paths is by the whole string - a-b/ ('-'), a.md ('.'), a/x.md ('/')",
             _names(H.sorted_paths(posix)), ["a-b/x.md", "a.md", "a/x.md"])

    # --- the edges named in the helper's docstring ---
    for flavour in (PurePosixPath, PureWindowsPath):
        tag = flavour.__name__
        check_eq(f"{tag}: B/ before a/ and TC-001 after TC-0001 and before tc-001",
                 _names(H.sorted_paths(flavour(x) for x in ("tc-001.md", "a/x.md", "TC-001.md", "B/x.md", "TC-0001.md"))),
                 ["B/x.md", "TC-0001.md", "TC-001.md", "a/x.md", "tc-001.md"])
    check_eq("an empty walk is []", H.sorted_paths([]), [])
    check_eq("a generator is accepted and its items are sorted", H.sorted_paths(iter([Path("b"), Path("a")])),
             [Path("a"), Path("b")])
    first, second = PurePosixPath("same"), PurePosixPath("same")
    out = H.sorted_paths([first, PurePosixPath("a"), second])
    check("equal keys keep their input order (stable)", out[1] is first and out[2] is second)

    # --- a str among Paths is refused loudly, never ordered by another rule ---
    try:
        H.sorted_paths([Path("a"), "b"])
        refused = ""
    except TypeError as exc:
        refused = str(exc)
    check("a str among the Paths -> TypeError naming the type and the item", "str" in refused and "'b'" in refused,
          refused or "no exception")
    try:
        H.sorted_paths(["a", "b"])
        refused_all = False
    except TypeError:
        refused_all = True
    check("a list of only str is refused too (names are sorted with plain sorted)", refused_all)

    # --- a real walk of this platform's own Path ---
    root = temp_dir()
    try:
        for rel in ("TC-0002.md", "TC-001.md", "a.md", "a/x.md", "a-b/x.md", "B/y.md", "tc-9.md"):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        walked = [p.relative_to(root) for p in root.rglob("*.md")]
        check_eq("rglob of a mixed-case tree: the same order on every platform",
                 _names(H.sorted_paths(walked)),
                 ["B/y.md", "TC-0002.md", "TC-001.md", "a-b/x.md", "a.md", "a/x.md", "tc-9.md"])
        check_eq("the walk is sorted by posix string whatever order the filesystem listed it in",
                 _names(H.sorted_paths(reversed(walked))), _names(H.sorted_paths(walked)))
    finally:
        cleanup(root)
    finish("test_hooklib_sorted_paths")


if __name__ == "__main__":
    main()
