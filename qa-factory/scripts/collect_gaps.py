"""The project's test files that could not be collected, kept in the story's own history (RH1-3, B4, AR-14, AR-22).

`qa-factory/artifacts/<task>/state/collect-gaps.json`: one row per (`source`, `profile`) - `gate_a` (the gate A
rehearsal collected the whole profile) or `s5_collect` (S5 collected the files a request names) - holding the files
or folders the runner could not import (`{"path", "head"[, "owner"]}`, as `node_ids.collect_verdict` names them; `owner`
is `project` or `story`, set by the writer that knows: a file the story's own S5 request names is the story's, a
folder or a file it does not name is the project's, and everything gate A finds is the project's - the story's tests
do not exist yet). The collect carries on past such a file and the story goes on, so without a record the report never
says that tests were left out. `report_facts` reads this file (`read`) and prints one line per path, naming the owner.

ONE writer (`record`) and ONE reader (`read`); the gate and the runner both call `record`, nobody writes the file by
hand. The story is the history: a row replaces the earlier row of the same key, an empty `broken` erases the key (the
next collect found nothing broken), and a missing file is "nothing recorded" - never the statement that everything
was collected. A story's other history is never touched, and a request or a projection is never written (FR-45).

Standard library only: the gate imports it lazily next to `node_ids`.
"""
import json
import os
import tempfile
from pathlib import Path

FILE = "collect-gaps.json"
SOURCES = ("gate_a", "s5_collect")
HEAD_MAX = 180
OWNERS = ("project", "story")     # whose file it is: the project's, or one the story itself wrote (F4, AR-27)


def _path(task_root) -> Path:
    return Path(task_root) / "state" / FILE


def _clean(broken) -> list:
    """`[{"path", "head"}]` out of whatever the caller holds: a path once, forward slashes, a head capped."""
    rows, seen = [], set()
    for item in broken or []:
        path = str(item.get("path") if isinstance(item, dict) else item or "").replace("\\", "/").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        head = str(item.get("head") or "") if isinstance(item, dict) else ""
        row = {"path": path, "head": " ".join(head.split())[:HEAD_MAX]}
        owner = item.get("owner") if isinstance(item, dict) else None
        if owner in OWNERS:
            row["owner"] = owner        # only a stated owner is kept; an absent one is "not established", never a default
        rows.append(row)
    return rows


def read(task_root) -> dict:
    """`{"rows": [...], "unreadable": str}` - THE reader. `rows` are `{"source", "profile", "broken", "selected"}`,
    sorted by (source, profile). No file is no rows and no complaint; a file that cannot be read (not JSON, not the
    shape this module writes) is no rows and the reason in `unreadable`: the caller says "unknown", it never
    reports a clean history (AR-28)."""
    path = _path(task_root)
    if not path.is_file():
        return {"rows": [], "unreadable": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        rows = data["rows"] if isinstance(data, dict) else None
        if not isinstance(rows, list) or any(
                not isinstance(r, dict) or r.get("source") not in SOURCES or not isinstance(r.get("profile"), str)
                or not isinstance(r.get("broken"), list) for r in rows):
            raise ValueError("it is not the list of rows this module writes")
    except (OSError, ValueError) as exc:
        return {"rows": [], "unreadable": f"{FILE} cannot be read ({type(exc).__name__}: {exc})"[:300]}
    out = [{"source": r["source"], "profile": r["profile"], "broken": _clean(r["broken"]),
            "selected": r.get("selected") if isinstance(r.get("selected"), int) else None} for r in rows]
    return {"rows": sorted(out, key=lambda r: (r["source"], r["profile"])), "unreadable": ""}


def record(task_root, source: str, profile: str, broken, *, selected=None) -> str:
    """THE writer: set the row of (`source`, `profile`) to `broken` (replacing the earlier one); `broken=[]` erases it.
    Returns "" when done, else the reason nothing was written - it never raises, a record that cannot be kept must
    not stop the stage that found the files (the caller turns the reason into a note). The write is atomic (a
    temporary file in the same folder, then a replace). An unreadable earlier file is replaced: there is nothing in it
    that could be kept."""
    if source not in SOURCES:
        return f"collect_gaps.record: unknown source {source!r} (expected one of {', '.join(SOURCES)})"
    earlier = read(task_root)["rows"]
    rows = [r for r in earlier if (r["source"], r["profile"]) != (source, str(profile))]
    cleaned = _clean(broken)
    had = len(rows) != len(earlier)
    if not cleaned and not had:
        return ""                           # nothing broken, nothing recorded earlier: no file is made for it
    if cleaned:
        rows.append({"source": source, "profile": str(profile), "broken": cleaned,
                     "selected": selected if isinstance(selected, int) and not isinstance(selected, bool) else None})
    rows.sort(key=lambda r: (r["source"], r["profile"]))
    path = _path(task_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=FILE + ".", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"schema_version": 1, "rows": rows}, handle, indent=1, ensure_ascii=False)
                handle.write("\n")
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        return f"{FILE} was not written ({type(exc).__name__}: {exc})"[:300]
    return ""
