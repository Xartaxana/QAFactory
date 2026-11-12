"""RH2-9: the automator's brief carries the project's per-test timeout (K-B keys).

`brief_pack.test_timeout_line` reads the limit through `execution_request.pytest_timeout_setting` (the one reader) for every selected
profile's `one_test` command. A number is never printed that the project did not set: no timeout is `none configured`, an unreadable one
says why, a runner this code does not read says so.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, check_not_in, cleanup, finish, temp_dir  # noqa: E402

import brief_pack as BP  # noqa: E402

ROOT = None


def project(files: dict) -> Path:
    base = Path(ROOT) / f"p{len(list(Path(ROOT).glob('p*')))}"
    base.mkdir(parents=True)
    for name, text in files.items():
        (base / name).parent.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(text, encoding="utf-8")
    return base


def profile(name="api", argv=("pytest", "<f>"), cwd=".") -> dict:
    return {"profile_id": name, "commands": {"one_test": {"argv": list(argv), "cwd": cwd}}}


def line(base: Path, *profiles, role="qa-automator") -> str:
    return BP.test_timeout_line(base, role, {"profiles": list(profiles)})


def main() -> None:
    global ROOT
    ROOT = temp_dir("qa-brief-timeout-")
    try:
        base = project({"pyproject.toml": "[tool.pytest.ini_options]\ntimeout = 300\n"})
        got = line(base, profile())
        check_in("K-B1 a configured limit is printed with its source", "api: 300 s set in pyproject.toml [tool.pytest.ini_options] timeout", got)
        check_in("K-B1 ... said as the project's setting, not as an applied fact", "applies when pytest-timeout is installed", got)
        check_in("K-B1 the line says what a kill is called and whose it is", "reported as `timeout`: it is your test's to fit or mark, never the stand's", got)
        check("K-B1 one line only, from `Per-test timeout:`", got.startswith("Per-test timeout: ") and "\n" not in got, got)

        none = project({"pytest.ini": "[pytest]\naddopts = -q\n"})
        got = line(none, profile())
        check_in("K-B2 / M9 no timeout set: `none configured`", "api: none configured", got)
        check_not_in("K-B2 ... and never a number", " s set in", got)
        check_not_in("K-B2 ... nor `0 s`", "0 s", got)
        off = project({"pytest.ini": "[pytest]\ntimeout = 0\n"})
        check_in("K-B3 timeout = 0 switches it off, said so", "api: none configured (timeout = 0 switches it off)", line(off, profile()))
        bad = project({"pytest.ini": "[pytest]\ntimeout = abc\n"})
        got = line(bad, profile())
        check_in("K-B4 an unreadable value says so", "api: could not be read (", got)
        check_not_in("K-B4 ... and is not shown as none", "none configured", got)
        argv900 = line(base, profile(argv=("pytest", "--timeout=900", "<f>")))
        check_in("K-B1 the profile's own --timeout wins and names its source", "api: 900 s set in the profile's command", argv900)
        sub = project({"svc/pytest.ini": "[pytest]\ntimeout = 45\n"})
        check_in("K-B1 the command's cwd is where the ini is looked for", "api: 45 s set in svc/pytest.ini timeout", line(sub, profile(cwd="svc")))

        many = [profile(f"p{i}") for i in range(3)]
        got = line(base, *many)
        check_eq("K-B5 three profiles: three entries, no `more`", (got.count(" s set in"), "more profiles" in got), (3, False))
        got = line(base, *many, profile("p3"))
        check_eq("K-B5 four profiles: three entries and `(+1 more profiles)`", (got.count(" s set in"), "(+1 more profiles)" in got), (3, True))

        import execution_request as ER
        real = ER.pytest_timeout_setting
        try:
            for length in (120, 121):
                ER.pytest_timeout_setting = lambda *a, _n=length: {"state": "unreadable", "limit_s": None, "source": "", "why": "y" * _n}
                got = line(base, profile())
                check_eq(f"K-B6 {length}-character why at the boundary", ("y" * 120 in got, "y" * 120 + "..." in got), (True, length == 121))
        finally:
            ER.pytest_timeout_setting = real

        check_in("K-B7 a runner this code does not read is said, not guessed", "ui: not read for this runner",
                 line(base, profile(), profile("ui", argv=("npx", "playwright", "test"))))
        check_eq("K-B7 a non-automator role gets no line", line(base, profile(), role="qa-code-critic"), "")
        check_eq("K-B7 no profile with a command: no line", line(base, {"profile_id": "x", "commands": {}}), "")
        check_in("K-B8 a defect of the reader is one line saying so, not a crash", "Per-test timeout: not measured",
                 BP.test_timeout_line(base, "qa-automator", object()))
    finally:
        cleanup(ROOT)
    finish("brief timeout")


if __name__ == "__main__":
    main()
