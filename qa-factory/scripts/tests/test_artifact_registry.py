"""artifact_registry.canonical: the single logical-path mapping shared by writers,
readers and migration tooling (references/artifact-registry.json). Covers a registered
name resolving to its declared path, an unregistered name falling back to the
`unknown_machine_path` rule (work/{name}), and the path-escape refusal that keeps every
artifact inside the task directory.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import artifact_registry as AR  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, finish  # noqa: E402

TASK = Path("/tasks/QA-1")

check_eq("a delivered top-level artifact resolves to its declared bare path",
         AR.canonical(TASK, "understanding.md"), TASK / "understanding.md")
check_eq("a task-local artifact resolves under work/, per the registry entry",
         AR.canonical(TASK, "automation-manifest.json"), TASK / "work" / "automation-manifest.json")
check_eq("a durable-state artifact resolves under state/",
         AR.canonical(TASK, "events.jsonl"), TASK / "state" / "events.jsonl")

check_eq("a name with no registry entry falls back to work/<name>",
         AR.canonical(TASK, "some-new-thing.json"), TASK / "work" / "some-new-thing.json")

for bad in ("../escape.md", "work/../../etc/passwd"):
    try:
        AR.canonical(TASK, bad)
        check(f"canonical() refuses a name that walks out of the task ({bad!r})", False)
    except ValueError as exc:
        check(f"canonical() refuses a name that walks out of the task ({bad!r})", "inside the task" in str(exc))

# Path.is_absolute() is platform-specific ("/etc/passwd" is NOT absolute to PureWindowsPath,
# lacking a drive letter) — use whichever form this OS actually treats as absolute.
absolute_name = str(Path(__file__).resolve().anchor) + "secrets.txt" if sys.platform == "win32" else "/etc/passwd"
check(f"canonical() treats {absolute_name!r} as absolute on this platform", Path(absolute_name).is_absolute())
try:
    AR.canonical(TASK, absolute_name)
    check("canonical() refuses an absolute name", False)
except ValueError:
    check("canonical() refuses an absolute name", True)

try:
    AR.canonical(TASK, "")
    check("canonical() refuses an empty name", False)
except ValueError:
    check("canonical() refuses an empty name", True)

check("the registered set carries at least the artifacts writers/readers actually use",
      {"understanding.md", "test-plan.md", "test-report.md", "retro.md"} <= set(AR.entries()))

# --- one home per artifact, in the text as well as in the code (FR-37, PLAN P22) -------------
# On TP1-13797 the S8 checks read zero plan rows and called 19 of 19 requirements
# unreachable, because the plan was written under `work/` while every reader looked at the story
# root (FB-10). `contract.artifact` tolerates both spellings so a story in flight survives, and
# the TEXT is what must not offer the choice: a delivered artifact is named by its bare path
# wherever a role is told to write it.
import re  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[2]
delivered = [name for name, entry in AR.entries().items()
             if isinstance(entry, dict) and not str(entry.get("path", "")).startswith("work/")]
check("the registry places the delivered documents at the story root", len(delivered) >= 4, str(delivered))
offenders = []
for folder, pattern in ((PLUGIN / "skills", "*/phases/*.md"), (PLUGIN / "agents", "*.md"),
                        (PLUGIN / "references", "*.md")):
    for path in folder.glob(pattern) if folder.is_dir() else []:
        body = path.read_text(encoding="utf-8", errors="replace")
        for name in delivered:
            if re.search(r"work/" + re.escape(name), body):
                offenders.append(f"{path.relative_to(PLUGIN).as_posix()}: work/{name}")
check("and no phase, charter or reference tells a role to write one under work/",
      not offenders, "; ".join(sorted(set(offenders))[:6]))

finish("test_artifact_registry")
