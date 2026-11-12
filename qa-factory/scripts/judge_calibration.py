"""What every judged question actually did: asked, decided, and what it cost.

A judgment that never decides is not free. It is a question the factory asks a thousand times
and then answers itself with a model turn - `code_smell_justified` was asked forty times on
TP1-13797 and decided zero. A judgment that always decides is the opposite finding: the
role that still re-derives it is spending turns on something settled.

So the registry is not written once. This reads the journal of one project (or several) and
prints the table that says which question to keep, which to re-threshold and which to retire.

  judge_calibration.py [--project-root P] [--journal F ...] [--min-asks 10] [--json]

It sends nothing anywhere and changes nothing: it is a reader.
"""
import argparse
import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import judge  # noqa: E402

try:
    import hooklib  # noqa: E402
except Exception:                                    # pragma: no cover - outside a project
    hooklib = None


def journals(args) -> list:
    if args.journal:
        return [Path(j) for j in args.journal]
    root = args.project_root
    if not root and hooklib:
        try:
            root = str(hooklib.project_root())
        except Exception:
            root = ""
    path = judge.journal_path(root) if root else None
    return [path] if path and path.is_file() else []


def rows(paths) -> list:
    out = []
    for path in paths:
        try:
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            continue
    return out


def summarise(records: list) -> dict:
    asked = collections.Counter()
    decided = collections.Counter()
    values = collections.defaultdict(collections.Counter)
    for row in records:
        if row.get("kind") != "answer":
            continue
        name = row.get("judgment")
        asked[name] += 1
        if row.get("decided"):
            decided[name] += 1
            values[name][str(row.get("value"))] += 1
    requests = [r for r in records if r.get("kind") == "request"]
    return {
        "asked": asked, "decided": decided, "values": values,
        "requests": len(requests),
        "tokens": sum(int(r.get("input_tokens") or 0) for r in requests),
        "usd": round(sum(float(r.get("cost_usd") or 0) for r in requests), 4),
        "passes": sum(1 for r in records if r.get("kind") == "pass"),
        "held": sum(1 for r in records if r.get("kind") == "held"),
        "errors": sum(1 for r in records if r.get("kind") == "error"),
    }


def verdicts(stats: dict, registry: dict, min_asks: int) -> dict:
    out = {}
    for name in sorted(set(registry) | set(stats["asked"])):
        asked, decided = stats["asked"].get(name, 0), stats["decided"].get(name, 0)
        share = decided / asked if asked else 0.0
        if not asked:
            verdict = "never asked - either the call site does not exist or the stage never ran"
        elif asked >= min_asks and decided == 0:
            verdict = "retire or re-threshold: asked and never once decided"
        elif asked >= min_asks and share < 0.25:
            verdict = "re-threshold: it decides too rarely to pay for the question"
        elif share >= 0.95 and asked >= min_asks:
            verdict = "settled: the role that still re-derives this is spending turns"
        else:
            verdict = "working"
        out[name] = {"asked": asked, "decided": decided, "share": round(share, 3),
                     "verdict": verdict,
                     "in_registry": name in registry,
                     "top_values": dict(stats["values"][name].most_common(3)) if name in stats["values"] else {}}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", default="")
    ap.add_argument("--journal", action="append", default=[])
    ap.add_argument("--min-asks", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    paths = journals(args)
    if not paths:
        print("judge_calibration: no judgments journal found. It is written at "
              "qa-factory/state/judgments.jsonl once a judge is configured "
              "(judge.provider in config.json); pass --journal <file> to read one directly.")
        return 2
    records = rows(paths)
    stats = summarise(records)
    try:
        registry = judge.load_registry()
    except Exception:
        registry = {}
    table = verdicts(stats, registry, args.min_asks)

    if args.json:
        print(json.dumps({"files": [str(p) for p in paths], "totals": {
            "answers": sum(stats["asked"].values()), "decided": sum(stats["decided"].values()),
            "requests": stats["requests"], "tokens": stats["tokens"], "usd": stats["usd"],
            "passes": stats["passes"], "held": stats["held"], "errors": stats["errors"]},
            "judgments": table}, ensure_ascii=False, indent=1))
        return 0
    total_asked = sum(stats["asked"].values())
    total_decided = sum(stats["decided"].values())
    print(f"judge calibration over {len(paths)} journal(s): {total_asked} answers, "
          f"{total_decided} decided ({(total_decided / total_asked * 100) if total_asked else 0:.0f}%), "
          f"{stats['requests']} requests, {stats['tokens']} input tokens, ${stats['usd']}")
    print(f"{'judgment':34}{'asked':>7}{'decided':>9}{'share':>7}  verdict")
    for name, row in sorted(table.items(), key=lambda kv: (-kv[1]["asked"], kv[0])):
        if not row["asked"] and not row["in_registry"]:
            continue
        print(f"{name:34}{row['asked']:7}{row['decided']:9}{row['share'] * 100:6.0f}%  {row['verdict']}")
    never = [n for n, r in table.items() if not r["asked"] and r["in_registry"]]
    if never:
        print(f"\nnever asked ({len(never)}): " + ", ".join(sorted(never)))
        print("A question nobody asks is not calibration - it is a call site that does not exist.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
