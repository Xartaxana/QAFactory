"""product_gaps.py - the ONE writer of the product-gaps carrier (`check_delivery.PRODUCT_GAPS_FILE`), the requirements a person said the product does not implement.

D1-C2 (RN1-15, t-1697 / t-1727 Q1; AR-14 one writer). The carrier's shape and its one reader are `check_delivery` (`PRODUCT_GAPS_FILE`,
`_read_product_gaps`): `{"gaps": [{"requirement", "words", "words_ref", "gate"}], "revoked": [...]}`. The reader reads only `gaps`.

    product_gaps.py record --task-root <r> --row <TS-n> --gate A|B --words-file <f>
    product_gaps.py revoke --task-root <r> --requirement <R-n> --words-file <f>

A product gap is a record of the person's word about a requirement, never a waiver (it passes no block). Both commands print one line;
exit 0 on success, 2 with the problem otherwise. A carrier that cannot be read is never written over (FR-45 in spirit, E-C11).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_delivery  # noqa: E402  (PRODUCT_GAPS_FILE: the reader's own name for the carrier)
import contract as C  # noqa: E402
import hooklib  # noqa: E402  (exact_options, story_cli: CX1-18)
import event_store  # noqa: E402  (atomic_json: the one publisher)
import gate_brief  # noqa: E402  (plan_rows: the one reader of the plan)
import planning_contract  # noqa: E402  (row_requirements)


def row_ids(row) -> list:
    """The requirement ids a plan row names, sorted and unique: `planning_contract.row_requirements` searched with `REQ_ID_RE`.

    Error direction: that reader errs toward FINDING a requirement, which here means MORE requirements under a product gap, so the
    delivery stays `no` - the safe side. A non-dict row, a row with no refs, and an id named only in prose give []."""
    found = set()
    for text in planning_contract.row_requirements(row):
        found.update(C.REQ_ID_RE.findall(str(text)))
    return sorted(found)


def plan_row(task_root, row_id) -> dict | None:
    """The plan row `row_id` of `work/test-plan.json` (a list of rows, or `{"rows": [...]}`), or None."""
    rows = gate_brief.plan_rows(Path(task_root))[0]      # the ONE reader of the plan, whichever shape it has (AR-13)
    for row in rows:
        if isinstance(row, dict) and str(row.get("id") or "").strip() == str(row_id or "").strip() and str(row_id or "").strip():
            return row
    return None


def _carrier(task_root) -> Path:
    """The carrier where the reader finds it (`contract.artifact`); a new one is born at its canonical place under `work/` (the reader's
    lookup answers the LEGACY flat path for a file that does not exist yet)."""
    found = C.artifact(Path(task_root), check_delivery.PRODUCT_GAPS_FILE)
    if found.exists():
        return found
    import artifact_registry
    return artifact_registry.canonical(task_root, check_delivery.PRODUCT_GAPS_FILE)


def _load(path: Path) -> tuple:
    """`(data, problem)`: an absent carrier is `({"gaps": []}, "")`; one that is not `{"gaps": [...]}` is `(None, why)`.

    A raw JSON read on purpose (axis 16, the KEPT row): this writer must tell an ABSENT carrier (start one) from a MALFORMED one (never
    write over it), which `hooklib.read_json`'s one `default` cannot say."""
    if not path.is_file():
        return {"gaps": []}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("gaps"), list):
            raise ValueError("it is not `{\"gaps\": [...]}`")
        return data, ""
    except (OSError, ValueError) as exc:
        return None, f"{path.name} cannot be read: {type(exc).__name__}: {str(exc)[:100]}; nothing is written over it"


def _write(path: Path, data: dict) -> str:
    """Atomic, through the package's one publisher (`event_store.atomic_json`: unique temp, fsync, the Windows retry). '' on success, else the reason."""
    try:
        event_store.atomic_json(path, data)
        return ""
    except OSError as exc:
        return f"{path.name} could not be written ({type(exc).__name__}: {str(exc)[:100]})"


def record(task_root, row_id, words, words_ref, gate) -> tuple:
    """`(requirements, problem)`: one row per requirement of plan row `row_id`, the LAST words winning (E-C12). A row naming R-23 and
    R-24 records both (E-C13: the person spoke about the row; the error goes toward `no`)."""
    row = plan_row(task_root, row_id)
    if row is None:
        return [], f"no plan row {row_id}"
    reqs = row_ids(row)
    if not reqs:
        return [], f"the row {row_id} names no requirement, so no product gap can be recorded"
    path = _carrier(task_root)
    data, problem = _load(path)
    if data is None:
        return [], problem
    kept = [g for g in data["gaps"] if not (isinstance(g, dict) and str(g.get("requirement") or "").strip() in reqs)]
    said = " ".join(str(words or "").split())
    for req in reqs:
        kept.append({"requirement": req, "words": said, "words_ref": str(words_ref or ""), "gate": str(gate or "")})
    data["gaps"] = kept
    problem = _write(path, data)
    return ([], problem) if problem else (reqs, "")


def revoke(task_root, requirement, words, words_ref) -> str:
    """Take a recorded product gap back: its rows leave `gaps` and one line of `{requirement, words, words_ref}` joins the top-level
    `revoked` list. '' on success, else the problem; an unknown requirement writes nothing."""
    path = _carrier(task_root)
    data, problem = _load(path)
    if data is None:
        return problem
    req = str(requirement or "").strip()
    if not any(isinstance(g, dict) and str(g.get("requirement") or "").strip() == req for g in data["gaps"]):
        return f"no product gap is recorded for {req}"
    data["gaps"] = [g for g in data["gaps"] if not (isinstance(g, dict) and str(g.get("requirement") or "").strip() == req)]
    revoked = data.get("revoked") if isinstance(data.get("revoked"), list) else []
    revoked.append({"requirement": req, "words": " ".join(str(words or "").split()), "words_ref": str(words_ref or "")})
    data["revoked"] = revoked
    return _write(path, data)


def _words_of(path: str, root: Path) -> tuple:
    """`(words, ref)`: the file's text and its path relative to the task root when it lies inside it."""
    target = Path(path)
    words = target.read_text(encoding="utf-8-sig")
    try:
        return words, target.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return words, str(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="product_gaps.py")
    sub = ap.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--task-root", required=True)
    rec.add_argument("--row", required=True)
    rec.add_argument("--gate", required=True, choices=["A", "B"])
    rec.add_argument("--words-file", required=True)
    rev = sub.add_parser("revoke")
    rev.add_argument("--task-root", required=True)
    rev.add_argument("--requirement", required=True)
    rev.add_argument("--words-file", required=True)
    try:
        ns = hooklib.exact_options(ap).parse_args(argv)
    except SystemExit:
        return 2
    root = hooklib.story_cli("product_gaps.py", root=ns.task_root, key_flag=None)      # CX1-18: a phantom root is refused, exit 2
    try:
        words, ref = _words_of(ns.words_file, root)
    except OSError as exc:
        print(f"the words file {ns.words_file} could not be read ({type(exc).__name__})")
        return 2
    if ns.command == "record":
        reqs, problem = record(root, ns.row, words, ref, ns.gate)
        print(problem or f"recorded as a product gap of {', '.join(reqs)}")
    else:
        problem = revoke(root, ns.requirement, words, ref)
        print(problem or f"the product gap of {ns.requirement} is taken back")
    return 2 if problem else 0


if __name__ == "__main__":
    sys.exit(main())
