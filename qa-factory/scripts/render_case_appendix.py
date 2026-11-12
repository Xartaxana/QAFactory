"""Render Gate A's deterministic case appendix from the canonical case snapshot."""
import argparse
import re
from pathlib import Path

import hooklib

FM = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def fields(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = FM.match(text)
    out = {}
    if match:
        for line in match.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "\t")):
                key, value = line.split(":", 1)
                out[key.strip()] = value.strip().strip("'\"")
    return out


START = "<!-- qa-factory:case-appendix:start -->"
END = "<!-- qa-factory:case-appendix:end -->"


def render_files(files, identities=None) -> str:
    rows, details = [], []
    from hooklib import sorted_paths  # THE order of a Path walk: code point, the same as the case_index refusal
    for path in sorted_paths(files):
        data = fields(path)
        identity = (identities or {}).get(str(path), {})
        case_id = identity.get("case_id") or data.get("id") or path.stem
        version = identity.get("version") or "unversioned"
        row = (case_id, data.get("plan_row") or "unlinked", data.get("basis") or "missing",
               data.get("channel") or "missing", data.get("status") or "missing", version)
        rows.append(tuple(str(value).replace("|", "\\|").replace("\n", " ") for value in row))
        body = FM.sub("", path.read_text(encoding="utf-8"), count=1).strip()
        details.extend([f"### {case_id} — {version}", "", body or "Case steps are missing.", ""])
    lines = ["## Case appendix", "", "| Case | Plan row | Oracle/basis | Channel | Review status | Version |",
             "|---|---|---|---|---|---|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    lines.extend(["", f"Cases: {len(rows)}. Generated from pinned case content; do not edit this section by hand.", "", *details])
    return "\n".join(lines)


def render(cases_root: Path) -> str:
    import contract as C  # the id form is the project's (`config.case_id_form`), never a glob here
    return render_files(C.case_glob(cases_root))


def render_task(task_root: Path) -> str:
    import contract as C
    task_root = task_root.resolve()
    if not (task_root / "state/story-case-links.json").is_file():
        raise ValueError("Gate A requires pinned case links before rendering")
    issues = C.case_link_issues(task_root)
    if issues:
        raise ValueError("; ".join(issues))
    links = C.story_case_links(task_root)
    identities = {str((task_root / link["path"]).resolve()): link for link in links}
    return render_files([Path(path) for path in identities], identities)


def embed(plan: Path, appendix: str) -> None:
    text = plan.read_text(encoding="utf-8")
    section = START + "\n" + appendix.rstrip() + "\n" + END
    if START in text or END in text:
        if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
            raise ValueError("case appendix markers are malformed; preserve plan for reconciliation")
        text = text[:text.index(START)] + section + text[text.index(END) + len(END):]
    else:
        text = text.rstrip() + "\n\n" + section + "\n"
    plan.write_text(text, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--cases-root")
    source.add_argument("--task-root")
    ap.add_argument("--plan", help="embed the full appendix into the human test-plan.md")
    ap.add_argument("--output", required=True)
    args = hooklib.exact_options(ap).parse_args()
    task_root = None
    if args.task_root is not None:      # the story BEFORE `--output`'s folder is made: a phantom root makes nothing
        task_root = hooklib.story_cli("render_case_appendix.py", root=args.task_root, key_flag=None)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    appendix = render_task(task_root) if task_root is not None else render(Path(args.cases_root))
    output.write_text(appendix + "\n", encoding="utf-8")
    if args.plan:
        embed(Path(args.plan), appendix)
    print(output)


if __name__ == "__main__":
    main()
