"""B-416 (D-0031): the factory's helper for a test report the code could not read - `report_adapt.py`.

The keys of the dispatch: `kind` writes ONLY after it re-read the kept bytes (G7: a receipt measured on other bytes never counts) and only
for an EMPTY recorded kind with the command unchanged (G8: the factory never overwrites a person's recorded kind); `understood` reads
the words strictly (UTF-8) and stores at most 2000 characters; `forget` never touches the configuration; a row counts toward the one
conductor turn per command only while it is NEWER than the latest proof of that command, an equal moment is not newer, and a record or a
proof file that cannot be read reads as "a row exists" (M5, FR-59); N8 lists a `reporter_kind` row only when a later proof confirms it.
"""
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script,  # noqa: E402
                     temp_project, use_project)

sys.path.insert(0, str(SCRIPTS))

import onboarding_probe  # noqa: E402
import report_adapt as RA  # noqa: E402
import reporters  # noqa: E402

ARGV = ["dotnet", "test", "--logger", "trx;LogFileName={report_path}", "<test-id>"]
TRX_NS = "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"
TRX = (f'<?xml version="1.0"?><TestRun xmlns="{TRX_NS}"><Results><UnitTestResult testId="1" testName="A.B" outcome="Passed" duration="00:00:01"/>'
       '</Results><TestDefinitions><UnitTest id="1" name="A.B"><TestMethod className="A" name="B"/></UnitTest></TestDefinitions></TestRun>')
DIGEST = onboarding_probe.argv_digest(ARGV)


def project(kind: str = "") -> Path:
    root = temp_project("qa-report-adapt-")
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    profile = {"profile_id": "web", "commands": {"one_test": {"argv": ARGV, "cwd": "."}}}
    if kind:
        profile["reporter"] = {"kind": kind}
    cfg["profiles"] = [profile, {"profile_id": "api", "commands": {"one_test": {"argv": ["pytest"], "cwd": "."}}}]
    cfg["test_command_templates"] = {"one_test": "dotnet test <test-file>", "suite": "dotnet test", "quiet": ""}
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    use_project(root)
    return root


def keep(root: Path, files: dict, profile: str = "web", argv=None, keep_files: int = 5, keep_limit: int = 5242880):
    slot = root / "slot"
    if slot.exists():
        shutil.rmtree(slot)         # one probe run's slot: each keep is of ONE run's files
    slot.mkdir()
    for name, data in files.items():
        (slot / name).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    meta = {"argv": list(argv or ARGV), "argv_digest": onboarding_probe.argv_digest(argv or ARGV), "fmt": "none", "declared_kind": "",
            "reason_class": "unparsable", "stdout_tail": "", "stderr_tail": "", "tried": [], "fit": ""}
    return RA.keep_unread(root, profile, slot, meta, keep_files, keep_limit)


def cli(root: Path, *args):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    return run_script("report_adapt.py", *args, cwd=root, env=env)


def config_bytes(root: Path) -> bytes:
    return (root / "qa-factory" / "config.json").read_bytes()


def record_rows(root: Path) -> list:
    return RA.load(root)[0]


def write_proof(root: Path, at: str, digest: str = DIGEST, profile: str = "web") -> None:
    path = root / "qa-factory" / "state" / "reporter-rehearsals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "rehearsals": {"k": {"at": at, "profile_id": profile, "argv_digest": digest}}}), encoding="utf-8")


def part_keep() -> None:
    root = project()
    try:
        manifest, problem = keep(root, {"a.trx": TRX, "b.xml": "<x/>"})
        check_eq("keep: a manifest and no problem", (bool(manifest), problem), (True, ""))
        check_eq("keep: every file named with its size and a sha256, kept", [(f["name"], f["bytes"], len(f["sha256"]), f["kept"]) for f in manifest["files"]],
                 [("a.trx", len(TRX.encode()), 64, True), ("b.xml", 4, 64, True)])
        folder = RA.kept_dir(root, "web")
        check_eq("keep: the copies and the manifest are under reporter-unread/<profile>/",
                 (folder.relative_to(root).as_posix(), (folder / "files" / "a.trx").read_text(encoding="utf-8") == TRX, (folder / "manifest.json").is_file()),
                 ("qa-factory/state/reporter-unread/web", True, True))
        check_eq("keep: the manifest carries the command and its digest", (manifest["argv"], manifest["argv_digest"]), (ARGV, DIGEST))
        # the folder is REPLACED each time
        manifest, _ = keep(root, {"c.xml": "<y/>"})
        check_eq("keep: a second keep replaces the folder (the old files are gone)", sorted(p.name for p in (folder / "files").iterdir()), ["c.xml"])
    finally:
        cleanup(root)
    # G3: KEEP_FILES at and beyond; KEEP_LIMIT at and beyond (small limits - the rule is the comparison)
    root = project()
    try:
        manifest, _ = keep(root, {f"f{i}.xml": "<x/>" for i in range(5)})
        check_eq("G3: AT KEEP_FILES (5): all five are kept", [f["kept"] for f in manifest["files"]], [True] * 5)
        manifest, _ = keep(root, {f"f{i}.xml": "<x/>" for i in range(6)})
        check_eq("G3: BEYOND (6): the sixth is listed, not kept",
                 ([f["name"] for f in manifest["files"]], [f["kept"] for f in manifest["files"]]),
                 ([f"f{i}.xml" for i in range(6)], [True] * 5 + [False]))
        check_eq("G3: and the sixth is not on disk", sorted(p.name for p in (RA.kept_dir(root, "web") / "files").iterdir()), [f"f{i}.xml" for i in range(5)])
    finally:
        cleanup(root)
    root = project()
    try:
        manifest, _ = keep(root, {"at.xml": b"x" * 10, "over.xml": b"x" * 11}, keep_limit=10)
        check_eq("G3: AT KEEP_LIMIT the file is kept; ONE BYTE beyond it is listed with its size, `kept: false`, no sha",
                 [(f["name"], f["bytes"], f["kept"], bool(f["sha256"])) for f in manifest["files"]], [("at.xml", 10, True, True), ("over.xml", 11, False, False)])
        check("G3: the file beyond the limit is not copied", not (RA.kept_dir(root, "web") / "files" / "over.xml").exists())
    finally:
        cleanup(root)
    # a copy that fails is a problem, never a raise
    root = project()
    try:
        blocker = RA.kept_dir(root, "web").parent
        blocker.parent.mkdir(parents=True, exist_ok=True)
        blocker.write_text("not a folder", encoding="utf-8")
        manifest, problem = keep(root, {"a.xml": "<x/>"})
        check_eq("a keep that cannot copy is `(None, why)` and never raises", (manifest, "could not be kept" in problem), (None, True))
    finally:
        cleanup(root)


def part_countable() -> None:
    root = project()
    try:
        check_eq("G1: before the first unread report: no record, no proof - `none`, the conductor is called", RA.countable(root, "web", DIGEST)["state"], "none")
        row, problem = RA.append(root, {"kind": "not_adapted", "by": "conductor", "profile_id": "web", "argv_digest": DIGEST, "story": "T-1", "understood": "x"})
        check_eq("append: RA-1, with a moment", (row["id"], bool(row["at"]), problem), ("RA-1", True, ""))
        check_eq("a row of this command and no proof: it counts (`rows`: the card)", RA.countable(root, "web", DIGEST)["state"], "rows")
        check_eq("G6: another command (another digest) has no row: `none`", RA.countable(root, "web", "other")["state"], "none")
        check_eq("another profile with the same digest has no row: `none`", RA.countable(root, "api", DIGEST)["state"], "none")
        at = row["at"]
        write_proof(root, at)
        check_eq("an EQUAL moment is not newer: the proof and the row at one second - the row no longer counts (`none`)", RA.countable(root, "web", DIGEST)["state"], "none")
        write_proof(root, "2000-01-01T00:00:00+00:00")
        check_eq("a proof OLDER than the row: the row counts", RA.countable(root, "web", DIGEST)["state"], "rows")
        write_proof(root, "2999-01-01T00:00:00+00:00")
        check_eq("G5: a proof NEWER than the row (the command read since, and now fails again): the conductor once more", RA.countable(root, "web", DIGEST)["state"], "none")
        write_proof(root, "2999-01-01T00:00:00+00:00", digest="other")
        check_eq("a newer proof of ANOTHER command does not retire this row", RA.countable(root, "web", DIGEST)["state"], "rows")
        # M5: unreadable files read as `unknown`, with the file named
        state = root / "qa-factory" / "state" / "reporter-rehearsals.json"
        state.write_text("{not json", encoding="utf-8")
        got = RA.countable(root, "web", DIGEST)
        check_eq("M5: an unreadable proof file is `unknown` and names the file", (got["state"], "reporter-rehearsals.json" in got["note"]), ("unknown", True))
        state.write_text(json.dumps({"rehearsals": []}), encoding="utf-8")
        check_eq("M5: a proof file with no `rehearsals` map is `unknown` too", RA.countable(root, "web", DIGEST)["state"], "unknown")
        RA.record_path(root).write_text("{not json", encoding="utf-8")
        got = RA.countable(root, "web", DIGEST)
        check_eq("M5: an unreadable record is `unknown` and names the file", (got["state"], "report-adaptations.json" in got["note"]), ("unknown", True))
        row, problem = RA.append(root, {"kind": "not_adapted", "by": "driver", "profile_id": "web", "argv_digest": DIGEST})
        check_eq("M5: and nothing is written over it", (row, "report-adaptations.json" in problem, RA.record_path(root).read_text(encoding="utf-8")), (None, True, "{not json"))
        RA.record_path(root).write_text(json.dumps({"schema_version": 9, "rows": []}), encoding="utf-8")
        check_eq("a record of another schema is `unknown` as well", RA.countable(root, "web", DIGEST)["state"], "unknown")
    finally:
        cleanup(root)
    root = project()
    try:
        for bad in ({"kind": "cure", "by": "driver", "profile_id": "web", "argv_digest": DIGEST},
                    {"kind": "not_adapted", "by": "person", "profile_id": "web", "argv_digest": DIGEST},
                    {"kind": "not_adapted", "by": "driver", "profile_id": "", "argv_digest": DIGEST},
                    {"kind": "not_adapted", "by": "driver", "profile_id": "web", "argv_digest": ""}):
            row, problem = RA.append(root, bad)
            check_eq(f"append refuses a row of another shape ({bad['kind']}/{bad['by']}/{bad['profile_id']!r}/{bad['argv_digest']!r}) and writes nothing",
                     (row, bool(problem), RA.record_path(root).exists()), (None, True, False))
        row, _ = RA.append(root, {"kind": "not_adapted", "by": "driver", "profile_id": "web", "argv_digest": DIGEST, "understood": "w " * 2000})
        check_eq("the stored words are at most UNDERSTOOD_LIMIT characters", len(row["understood"]) <= RA.UNDERSTOOD_LIMIT, True)
    finally:
        cleanup(root)


def part_kind() -> None:
    root = project()
    try:
        keep(root, {"report.trx": TRX})
        before = config_bytes(root)
        out = cli(root, "kind", "--profile", "web", "--reader", "trx", "--by", "conductor", "--task", "T-1")
        check_eq("kind: success exits 0 and names RA-1", (out.returncode, out.stdout.startswith("RA-1:")), (0, True))
        config = json.loads(config_bytes(root))
        check_eq("kind: the profile's report kind is trx, the command is unchanged, the other profile untouched",
                 (config["profiles"][0]["reporter"]["kind"], config["profiles"][0]["commands"]["one_test"]["argv"], "reporter" in config["profiles"][1]),
                 ("trx", ARGV, False))
        rows = record_rows(root)
        check_eq("kind: one row, `reporter_kind`, by the conductor, for this command and story",
                 [(r["id"], r["kind"], r["by"], r["reader"], r["profile_id"], r["argv_digest"], r["story"]) for r in rows],
                 [("RA-1", "reporter_kind", "conductor", "trx", "web", DIGEST, "T-1")])
        backups = sorted((root / "qa-factory" / "records" / "config-migrations").glob("*.json"))
        check_eq("kind: ONE backup of the old config, whose approval_ref is the RA row (M7 v)",
                 (len(backups), json.loads(backups[0].read_text(encoding="utf-8")).get("approval_ref") if backups else None), (1, "RA-1"))
        check_eq("kind: no approval line was written (a log of people's words)", (root / "qa-factory" / "records" / "config-approvals.jsonl").exists()
                 or any("approval" in p.name for p in (root / "qa-factory" / "records").glob("*.jsonl")), False)
        check("kind: the config did change (control)", config_bytes(root) != before)
        out = cli(root, "kind", "--profile", "web", "--reader", "trx", "--by", "conductor")
        check_eq("G8: a second `kind` over the recorded kind is refused, with the door", (out.returncode, "already records its report kind" in out.stderr,
                 "report_adapt.py understood" in out.stderr), (2, True, True))
        check_eq("G8: and wrote nothing (one row still)", len(record_rows(root)), 1)
    finally:
        cleanup(root)
    # G8: a person's recorded kind (every real config: M3) is never overwritten
    root = project(kind="junit-xml")
    try:
        keep(root, {"report.trx": TRX})
        before = config_bytes(root)
        out = cli(root, "kind", "--profile", "web", "--reader", "trx", "--by", "conductor")
        check_eq("G8: a recorded `junit-xml` is refused (P13), the config byte-identical, no row",
                 (out.returncode, "already records its report kind (`junit-xml`)" in out.stderr, config_bytes(root) == before, RA.record_path(root).exists()),
                 (2, True, True, False))
        check_in("G8: the door is the `understood` words, with the profile and the speaker", "report_adapt.py understood --profile web --text-file <file> --by conductor", out.stderr)
    finally:
        cleanup(root)
    # G7: kept bytes against the current state
    root = project()
    try:
        keep(root, {"report.trx": TRX})
        (RA.kept_dir(root, "web") / "files" / "report.trx").write_text(TRX.replace("A.B", "A.C"), encoding="utf-8")
        before = config_bytes(root)
        out = cli(root, "kind", "--profile", "web", "--reader", "trx", "--by", "conductor")
        check_eq("G7: kept bytes that changed since the manifest: refused, nothing written",
                 (out.returncode, "sha256 differs" in out.stderr, config_bytes(root) == before, RA.record_path(root).exists()), (2, True, True, False))
        keep(root, {"report.trx": TRX})
        config = json.loads(config_bytes(root))
        config["profiles"][0]["commands"]["one_test"]["argv"] = ARGV + ["--other"]
        (root / "qa-factory" / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        before = config_bytes(root)
        out = cli(root, "kind", "--profile", "web", "--reader", "trx", "--by", "conductor")
        check_eq("G7: a report written by ANOTHER command than the profile's now: refused, nothing written",
                 (out.returncode, "another command" in out.stderr, config_bytes(root) == before, RA.record_path(root).exists()), (2, True, True, False))
        (RA.kept_dir(root, "web") / "files" / "report.trx").unlink()
        config["profiles"][0]["commands"]["one_test"]["argv"] = ARGV
        (root / "qa-factory" / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        out = cli(root, "kind", "--profile", "web", "--reader", "trx", "--by", "conductor")
        check_eq("G7: a kept file that is gone: refused, no crash", (out.returncode, "cannot be read any more" in out.stderr or "another command" in out.stderr), (2, True))
    finally:
        cleanup(root)
    # a reader that counts no test, an unknown profile, an unknown reader, no kept report
    root = project()
    try:
        keep(root, {"report.trx": TRX})
        before = config_bytes(root)
        out = cli(root, "kind", "--profile", "web", "--reader", "junit-xml", "--by", "conductor")
        check_eq("a reader that counts no test in the kept report is refused", (out.returncode, "`junit-xml` reads no test" in out.stderr, config_bytes(root) == before), (2, True, True))
        out = cli(root, "kind", "--profile", "nope", "--reader", "trx", "--by", "conductor")
        check_eq("an unknown profile is refused, naming the profiles there are", (out.returncode, "it has: web, api" in out.stderr), (2, True))
        out = cli(root, "kind", "--profile", "web", "--reader", "pytest", "--by", "conductor")
        check_eq("an unknown reader is refused", (out.returncode, "--reader is one of" in out.stderr, config_bytes(root) == before), (2, True, True))
        out = cli(root, "kind", "--profile", "web", "--reader", "trx", "--by", "person")
        check_eq("`--by` is one of driver | conductor | orchestrator (a person is not the helper)", out.returncode != 0, True)
        out = cli(root, "kind", "--profile", "api", "--reader", "trx", "--by", "conductor")
        check_eq("a profile with no kept report: refused, saying the next rehearsal keeps one", (out.returncode, "no kept report of `api`" in out.stderr), (2, True))
        RA.record_path(root).parent.mkdir(parents=True, exist_ok=True)
        RA.record_path(root).write_text("{not json", encoding="utf-8")
        out = cli(root, "kind", "--profile", "web", "--reader", "trx", "--by", "conductor")
        check_eq("M5: over an unreadable record `kind` refuses before it changes the config",
                 (out.returncode, "nothing was written over it" in out.stderr, config_bytes(root) == before), (2, True, True))
    finally:
        cleanup(root)
    # G2: a binary report - no reader fits
    root = project()
    try:
        keep(root, {"report.bin": bytes(range(256)) * 4})
        out = cli(root, "kind", "--profile", "web", "--reader", "trx", "--by", "conductor")
        check_eq("G2: a binary report: no reader fits, `kind` is refused (the conductor writes `understood`)", (out.returncode, "reads no test" in out.stderr), (2, True))
    finally:
        cleanup(root)


def part_understood() -> None:
    root = project()
    try:
        words = root / "words.txt"
        words.write_text("The report is a binary xUnit v3 file.\nCure: the project needs a JUnit logger for that runner.", encoding="utf-8")
        out = cli(root, "understood", "--profile", "web", "--text-file", str(words), "--by", "conductor", "--task", "T-1")
        rows = record_rows(root)
        check_eq("understood: appended as `not_adapted`, by the conductor, for the command of the profile",
                 (out.returncode, [(r["id"], r["kind"], r["by"], r["profile_id"], r["argv_digest"], r["story"]) for r in rows]),
                 (0, [("RA-1", "not_adapted", "conductor", "web", DIGEST, "T-1")]))
        check_in("understood: the words are stored on one line, whole", "The report is a binary xUnit v3 file. Cure: the project needs a JUnit logger for that runner.", rows[0]["understood"])
        check_eq("understood: the configuration is untouched (a cure is words, never a change)", "reporter" in json.loads(config_bytes(root))["profiles"][0], False)
        # the limit: 2000 at and beyond
        for size in (2000, 2001, 5000):
            words.write_text("x" * size, encoding="utf-8")
            cli(root, "understood", "--profile", "web", "--text-file", str(words), "--by", "conductor")
            check_eq(f"limit: {size} characters stored as {min(size, RA.UNDERSTOOD_LIMIT)}", len(record_rows(root)[-1]["understood"]), min(size, RA.UNDERSTOOD_LIMIT))
        count = len(record_rows(root))
        # Fix 3 (b), N7, FR-6: what the person is shown is refused where it is written - a script name, a flag, a path, a NAME=value pair
        for label, text in (("a script name", "it ran run_tests.py and found nothing"), ("a flag", "add --logger junit to the command"),
                            ("a path", "the report is at C:\\proj\\out\\report.bin"), ("a NAME=value pair", "the run set TOKEN=abc123 first"),
                            ("a command line", "I ran report_adapt.py kind --profile web; it said no")):
            words.write_text(text, encoding="utf-8")
            out = cli(root, "understood", "--profile", "web", "--text-file", str(words), "--by", "conductor")
            check_eq(f"Fix 3 (b): {label} is refused with the door, nothing written",
                     (out.returncode, "Say it in words" in out.stderr and "no commands, flags, file names or paths" in out.stderr, len(record_rows(root))),
                     (2, True, count))
            check_not_in(f"Fix 3 (b): {label}: the refusal does not echo a secret value", "abc123", out.stderr)
        words.write_text("the runner wrote a binary report; a JUnit logger for it would fix this", encoding="utf-8")
        check_eq("Fix 3 (b) control: the same sentence in words is stored", cli(root, "understood", "--profile", "web", "--text-file", str(words), "--by", "conductor").returncode, 0)
        count = len(record_rows(root))
        # strict UTF-8, empty, no file, unknown profile
        words.write_bytes(b"\xff\xfe broken")
        out = cli(root, "understood", "--profile", "web", "--text-file", str(words), "--by", "conductor")
        check_eq("strict UTF-8: a file that is not UTF-8 is refused, nothing written", (out.returncode, len(record_rows(root))), (2, count))
        words.write_text("   \n", encoding="utf-8")
        out = cli(root, "understood", "--profile", "web", "--text-file", str(words), "--by", "conductor")
        check_eq("an empty text file is refused by the one words reader, nothing written", (out.returncode, "is empty" in out.stderr, len(record_rows(root))), (2, True, count))
        out = cli(root, "understood", "--profile", "web", "--by", "conductor")
        check_eq("no --text-file: refused saying what is needed, with the door, nothing written",
                 (out.returncode, "what the helper understood, in words" in out.stderr, "--words-file <file>" in out.stderr or "--text-file" in out.stderr,
                  len(record_rows(root))), (2, True, True, count))
        words.write_text("x", encoding="utf-8")
        out = cli(root, "understood", "--profile", "nope", "--text-file", str(words), "--by", "conductor")
        check_eq("an unknown profile is refused", (out.returncode, len(record_rows(root))), (2, count))
        RA.record_path(root).write_text("{not json", encoding="utf-8")
        out = cli(root, "understood", "--profile", "web", "--text-file", str(words), "--by", "conductor")
        check_eq("M5: over an unreadable record: refused, the file untouched", (out.returncode, RA.record_path(root).read_text(encoding="utf-8")), (2, "{not json"))
    finally:
        cleanup(root)


def part_show_forget() -> None:
    root = project()
    try:
        out = cli(root, "show")
        check_eq("show: nothing recorded says so", (out.returncode, out.stdout.strip()), (0, "no report adaptation is recorded."))
        RA.append(root, {"kind": "reporter_kind", "by": "driver", "profile_id": "web", "argv_digest": DIGEST, "reader": "trx", "understood": "read as trx"})
        RA.append(root, {"kind": "not_adapted", "by": "conductor", "profile_id": "web", "argv_digest": DIGEST, "understood": "a binary"})
        out = cli(root, "show")
        check_eq("show: one line per row", (out.returncode, [line.split(" ")[0] for line in out.stdout.strip().splitlines()]), (0, ["RA-1", "RA-2"]))
        data = json.loads(cli(root, "show", "--json").stdout)
        check_eq("show --json: the rows and no problem", ([r["id"] for r in data["rows"]], data["problem"]), (["RA-1", "RA-2"], ""))
        before = config_bytes(root)
        out = cli(root, "forget", "--id", "RA-2")
        check_eq("forget: the row is gone, the other stays, the configuration is byte-identical",
                 (out.returncode, [r["id"] for r in record_rows(root)], config_bytes(root) == before), (0, ["RA-1"], True))
        check_in("forget: says the next unread report goes to the conductor once more", "goes to the conductor once more", out.stdout)
        out = cli(root, "forget", "--id", "RA-9")
        check_eq("forget: an unknown id is refused and names `show`", (out.returncode, "report_adapt.py show" in out.stderr), (2, True))
        RA.record_path(root).write_text("{not json", encoding="utf-8")
        out = cli(root, "forget", "--id", "RA-1")
        check_eq("forget over an unreadable record: refused, the file untouched", (out.returncode, RA.record_path(root).read_text(encoding="utf-8")), (2, "{not json"))
        out = cli(root, "show")
        check_eq("show over an unreadable record says why and exits 1", (out.returncode, "cannot be read" in out.stdout), (1, True))
    finally:
        cleanup(root)


def part_proven() -> None:
    root = project()
    try:
        row, _ = RA.append(root, {"kind": "reporter_kind", "by": "driver", "profile_id": "web", "argv_digest": DIGEST, "story": "T-1", "reader": "trx"})
        RA.append(root, {"kind": "not_adapted", "by": "conductor", "profile_id": "web", "argv_digest": DIGEST, "story": "T-1"})
        RA.append(root, {"kind": "reporter_kind", "by": "driver", "profile_id": "api", "argv_digest": "d2", "story": "T-2", "reader": "junit-xml"})
        check_eq("last_adaptation: the newest `reporter_kind` row of the command (a `not_adapted` row is no adaptation)",
                 (RA.last_adaptation(root, "web", DIGEST) or {}).get("id"), row["id"])
        check_eq("last_adaptation: none for another command", RA.last_adaptation(root, "web", "x"), None)
        check_eq("N8: no proof, nothing is listed (FR-41: not confirmed)", RA.proven_adaptations(root, "T-1"), [])
        write_proof(root, "2999-01-01T00:00:00+00:00")
        check_eq("N8: a proof of the command NEWER than the row lists the row - and only this story's", [r["id"] for r in RA.proven_adaptations(root, "T-1")], ["RA-1"])
        check_eq("N8: another story's row is not listed", RA.proven_adaptations(root, "T-3"), [])
        write_proof(root, row["at"])
        check_eq("N8: an EQUAL moment is not a later proof", RA.proven_adaptations(root, "T-1"), [])
        (root / "qa-factory" / "state" / "reporter-rehearsals.json").write_text("{not json", encoding="utf-8")
        check_eq("N8: an unreadable proof file lists nothing (an unknown is never a fact)", RA.proven_adaptations(root, "T-1"), [])
        check_eq("N8: no story, nothing", RA.proven_adaptations(root, ""), [])
    finally:
        cleanup(root)


def part_guard() -> None:
    """M10 and the R10 sibling: a factory ROLE may not run `report_adapt.py kind` (it changes how a command's report is read in the
    configuration) or `forget` (it resets the one-turn bound) and may not write the helper's record by any road; `understood`, `show` and reading stay open; the main
    session (the driver, the conductor) is never refused."""
    import guard_pre_tool as G
    root = project()
    try:
        role = {"agent_type": "qa-factory:qa-automator", "cwd": str(root)}
        record = (root / "qa-factory" / "records" / "report-adaptations.json").as_posix()

        def word(command, **who):
            return G._blocked(G.human_word_check, dict(who or role, tool_name="Bash", tool_input={"command": command}), {}) is not None

        def writes(tool, path=None, command=None, **who):
            ti = {"file_path": path} if path is not None else {"command": command}
            return G._blocked(G.stand_record_write_check, dict(who or role, tool_name=tool, tool_input=ti), {}) is not None
        for command in ("python report_adapt.py kind --profile web --reader trx --by conductor",
                        "python -B scripts/report_adapt.py kind --profile web --reader trx --by conductor --task T",
                        "python report_adapt.py forget --id RA-1",
                        "python3 'report_adapt.py' 'kind' --profile web"):
            check(f"M10: a role is refused: {command[:48]}", word(command))
        check_in("M10: the refusal names the conductor's door and what stays open",
                 "(`understood` and `show` are open to you)", G._blocked(G.human_word_check, dict(role, tool_name="Bash", tool_input={
                     "command": "python report_adapt.py kind --profile web --reader trx --by conductor"}), {}) or "")
        for command in ("python report_adapt.py understood --profile web --text-file f.txt --by conductor", "python report_adapt.py show",
                        "python report_adapt.py show --json", "python report_adapt.py kindly", "python report_adapt.py forgetful"):
            check(f"M10: open to a role: {command[:48]}", not word(command))
        check("M10: the main session may run `kind`", not word("python report_adapt.py kind --profile web --reader trx --by conductor", cwd=str(root)))
        check("M10: a role quoting the command inside a file it writes is not refused (the executable part only)",
              not word("cat > notes.md <<'EOF'\npython report_adapt.py kind --profile web\nEOF"))
        for tool in ("Write", "Edit", "NotebookEdit"):
            check(f"R10 sibling: a role's {tool} on the helper's record is refused", writes(tool, record))
        for command, why in ((f"echo '{{}}' > {record}", "a redirection"), ("echo x >> qa-factory/records/report-adaptations.json", "an append, relative path"),
                             (f"rm {record}", "an rm (the conductor's words would be gone)")):
            check(f"R10 sibling: a role is refused: {why}", writes("Bash", command=command))
        check("R10 sibling: reading the record is open", not writes("Bash", command=f"cat {record}"))
        check("R10 sibling: another file of the same name elsewhere is not refused", not writes("Bash", command="echo x > /tmp/other/report-adaptations.json"))
        check("R10 sibling: the main session writes it: never refused", G._blocked(G.stand_record_write_check, {"cwd": str(root), "tool_name": "Write",
              "tool_input": {"file_path": record}}, {}) is None)
        check_in("R10 sibling: the refusal names the file", "report-adaptations.json",
                 G._blocked(G.stand_record_write_check, dict(role, tool_name="Write", tool_input={"file_path": record}), {}) or "")
    finally:
        cleanup(root)


def part_reporters_agree() -> None:
    check_eq("the helper and the rehearsal use the same limits (one definition in reporters.py)",
             (RA.UNREAD_REL.endswith("reporter-unread"), reporters.KEEP_FILES, reporters.KEEP_LIMIT), (True, 5, 5242880))
    check_not_in("the helper never names a path of the person's project in its words", "C:\\", RA.NOT_CALLED_TEXT)


def main() -> None:
    part_keep()
    part_countable()
    part_kind()
    part_understood()
    part_show_forget()
    part_proven()
    part_guard()
    part_reporters_agree()
    finish("the factory's helper for an unread report (report_adapt.py)")


if __name__ == "__main__":
    main()
