"""The reference snapshot (S-c, t-2181 PC-9a): `work/reference-snapshot.yaml` is the OLD version's behaviour as the S1 reference walk saw it.

  reference_snapshot.py put  --task-root DIR --reference ENV --items-file F [--replace]   write the snapshot (runner, after the reference walk)
  reference_snapshot.py show --task-root DIR                                                print it

`F` is JSON or the YAML subset of the factory: `{"items": [{id, area, user_path, observed, evidence: [{path, quote}], old_test, locators_portable}],
"gaps": [lines]}`. The snapshot keeps the evidence as capture PATHS; the quote is the proof offered once, at `put` (code checks the words are in
the capture, never that they show what `observed` says - that is the S2 tester's and the case critic's judgment, AR-29).

Every item cites evidence or an old test (AR-6: an LLM agent is never a read route). A cited capture goes through `walk_session.capture_cited`
with the walk the CODE takes - the newest S1 dispatch of `state/controller.json` whose purpose is `reference_walk` - and the reference stand: a
capture of a first-look walk (another walk, another stand) is refused. `items: []` needs a gap line (the empty outcome, AR-23).
Exit codes: 0 done, 2 a refused call (stderr names what is wrong, what is expected and the door; nothing is written).
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract as C  # noqa: E402
import dispatch_identity  # noqa: E402
import grounding_table as GT  # noqa: E402
import handoff  # noqa: E402
import hooklib  # noqa: E402
import walk_session  # noqa: E402

SNAPSHOT = "reference-snapshot.yaml"
PURPOSE = "reference_walk"
STAGE = "S1"
TEXT_KEYS = ("area", "user_path", "observed")
PORTABLE = ("yes", "no", "unknown")
OLD_TEST_RE = re.compile(r"^\S+:\d+$")
DOOR_FORM = ("Door: item = {id, area, user_path, observed, evidence: [{path, quote}] and/or old_test: <file>:<line>, "
             "locators_portable: yes|no|unknown}")


def snapshot_path(root) -> Path:
    return C.artifact_write_path(Path(root), SNAPSHOT)


def read(root):
    """The snapshot as a dict, or None when there is none or it cannot be read (the reader of every consumer; AR-13)."""
    try:
        text = snapshot_path(root).read_text(encoding="utf-8-sig")
    except OSError:
        return None
    data = handoff.parse(text).data
    return data if isinstance(data, dict) and isinstance(data.get("items"), list) else None


def item_ids(root):
    """The ids of the snapshot's items for `contract.then_oracle_errors(snapshot_items=...)`; None when the story has no snapshot."""
    data = read(root)
    return None if data is None else {str(i.get("id")) for i in data["items"] if isinstance(i, dict) and i.get("id")}


def reference_walk(root) -> str:
    """The id of the NEWEST S1 dispatch whose `request_binding.purpose` is `reference_walk` ('' when none): the walk the reference was
    walked in. Taken by code from the controller's state, never named by the role (J-C2: the evidence of one walk is not another's)."""
    try:
        state = json.loads((Path(root) / "state" / "controller.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    rows = dispatch_identity.records(state.get("dispatches") if isinstance(state, dict) else None)
    mine = [r["id"] for r in rows if r.get("stage") == STAGE and isinstance(r.get("request_binding"), dict)
            and r["request_binding"].get("purpose") == PURPOSE]
    return mine[-1] if mine else ""


def _load_items_file(path) -> dict:
    text = Path(path).read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except ValueError:
        data = handoff.parse(text).data
    if not isinstance(data, dict):
        raise GT.Refusal(f"{path} holds no mapping with `items` and `gaps`. {DOOR_FORM}")
    return data


def _evidence_problems(root, walk, reference, item_id, evidence) -> tuple:
    """(cited capture paths, [problem]) of one item's `evidence` list: every entry is {path, quote} and passes `capture_cited`."""
    paths, out = [], []
    for n, entry in enumerate(evidence):
        if not isinstance(entry, dict) or not entry.get("path"):
            out.append(f"item {item_id}: evidence[{n}] is not {{path, quote}} (a capture is cited with words of it, never by name alone)")
        elif not walk:
            out.append(f"item {item_id}: evidence[{n}] cites a capture, but no S1 dispatch with purpose `{PURPOSE}` exists to take it from. "
                       "Door: the reference window walks the reference first; or cite an `old_test`")
        else:
            why = walk_session.capture_cited(root, walk, item_id, str(entry["path"]), str(entry.get("quote") or ""), stand=reference)
            if why:
                out.append(f"item {item_id}: evidence[{n}]: {why}")
            else:
                paths.append(Path(str(entry["path"])).as_posix())
    return paths, out


def build(root, reference, items, gaps) -> dict:
    """The snapshot dict, or a `Refusal` naming every problem at once (what is wrong, what is expected, the door)."""
    if not str(reference or "").strip():
        raise GT.Refusal("put needs `--reference <stand name>`: the stand the old version was walked on. Door: the S1 reference window names it")
    if not isinstance(items, list) or not isinstance(gaps, list) or not all(isinstance(g, str) and g.strip() for g in gaps):
        raise GT.Refusal("`items` must be a list and `gaps` a list of non-empty lines. " + DOOR_FORM)
    if not items and not gaps:
        raise GT.Refusal("`items: []` needs a gap line saying why nothing was seen (for example the old version could not be reached). "
                         "Door: add it to `gaps`")
    walk, problems, seen, kept = reference_walk(root), [], set(), []
    for n, raw in enumerate(items):
        item = raw if isinstance(raw, dict) else {}
        ident = str(item.get("id") or "")
        label = ident or f"#{n + 1}"
        if not re.fullmatch(C.REFERENCE_ITEM, ident) or ident in seen:
            problems.append(f"item {label}: `id` must be a unique plain id (letters, digits, . _ -; `reference:<id>` cites it)")
        seen.add(ident)
        problems.extend(f"item {label}: `{k}` is empty" for k in TEXT_KEYS if not str(item.get(k) or "").strip())
        if item.get("locators_portable") not in PORTABLE:
            problems.append(f"item {label}: `locators_portable` is one of {', '.join(PORTABLE)} (say `unknown` when not checked)")
        old = item.get("old_test")
        if old not in (None, "") and not (isinstance(old, str) and OLD_TEST_RE.match(old)):
            problems.append(f"item {label}: `old_test` is `<file>:<line>`, not {str(old)[:60]!r}")
        evidence = item.get("evidence") or []
        paths, bad = _evidence_problems(root, walk, reference, ident, evidence if isinstance(evidence, list) else [None])
        problems.extend(bad)
        if not paths and not old:
            problems.append(f"item {label}: cites no capture of the reference walk and no old test, so it is no observation. {DOOR_FORM}")
        kept.append({"id": ident, **{k: str(item.get(k) or "") for k in TEXT_KEYS}, "evidence": paths,
                     **({"old_test": old} if old else {}), "locators_portable": item.get("locators_portable")})
    if problems:
        raise GT.Refusal("the snapshot was not written, " + str(len(problems)) + " problem(s):\n- " + "\n- ".join(problems))
    return {"reference_env": str(reference), "walked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "items": kept, "gaps": [g.strip() for g in gaps]}


def put(root, reference, items_file, replace=False) -> str:
    """Write `work/reference-snapshot.yaml` and return the line to print. An existing snapshot is replaced only with `replace`."""
    target = snapshot_path(root)
    if target.exists() and not replace:
        raise GT.Refusal(f"{target.name} already exists: the reference was walked before. Door: `--replace` after a new walk, or `rework S1`")
    data = _load_items_file(items_file)
    snapshot = build(root, reference, data.get("items", []), data.get("gaps", []))
    GT.write_yaml(target, snapshot)
    return f"reference snapshot written: {len(snapshot['items'])} item(s), {len(snapshot['gaps'])} gap line(s) in {target.name}"


def put_gap(root, reference, gaps, replace=False) -> str:
    """Write a snapshot with NO items and these gap lines - the empty outcome the code itself knows (the old version could not be reached),
    written by the driver, never by a role session (critic t-2513 F5; P6, FR-51). The same `build` and writer as `put`; an existing
    snapshot is replaced only with `replace`. Returns the line to print; raises `GT.Refusal` as `put` does."""
    target = snapshot_path(root)
    if target.exists() and not replace:
        raise GT.Refusal(f"{target.name} already exists: the reference was walked before. Door: `--replace` after a new walk, or `rework S1`")
    snapshot = build(root, reference, [], [str(g) for g in gaps])
    GT.write_yaml(target, snapshot)
    return f"reference snapshot written: 0 item(s), {len(snapshot['gaps'])} gap line(s) in {target.name}"


def show(root) -> str:
    try:
        return snapshot_path(root).read_text(encoding="utf-8-sig").rstrip("\n")
    except OSError:
        return "no reference snapshot: no side of this story has a reference, or the reference walk has not written one"


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    from role_cli import RefusingParser, epilog   # PC-9b: `put` is the runner's command (role-commands.json): a usage error carries its card
    ap = RefusingParser(command="reference_snapshot.py", prog="reference_snapshot.py", epilog=epilog("reference_snapshot.py"),
                        description="The reference snapshot of a story (put, show).", formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True, parser_class=RefusingParser)
    p_put = sub.add_parser("put", command="reference_snapshot.py put")
    p_show = sub.add_parser("show", command="reference_snapshot.py show")
    for p in (p_put, p_show):
        p.add_argument("--task-root", required=True, help="the story's folder")
    p_put.add_argument("--reference", required=True, help="the stand the old version was walked on")
    p_put.add_argument("--items-file", required=True, help="JSON or YAML with `items` and `gaps`")
    p_put.add_argument("--replace", action="store_true", help="replace an existing snapshot (a new walk)")
    args = ap.parse_args(argv)
    try:
        root = hooklib.story_root_at(args.task_root, "reference_snapshot")
        print(put(root, args.reference, args.items_file, args.replace) if args.command == "put" else show(root))
        return 0
    except GT.Refusal as refusal:
        print(refusal.text, file=sys.stderr)
    except (ValueError, OSError, TypeError) as exc:
        print(f"reference_snapshot: {str(exc).rstrip('.')}. Nothing was written (an existing snapshot is as it was).", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
