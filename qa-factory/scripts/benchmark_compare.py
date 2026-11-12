"""Compare measured paired factory runs; never infer savings from fewer tool calls."""
import argparse
import json
from pathlib import Path


def compare(before, after):
    required = ("model_policy", "scope_hash", "environment", "cache_policy", "quality_corpus")
    mismatch = [k for k in required if before.get(k) is None or before.get(k) != after.get(k)]
    if mismatch:
        return {"status": "not_comparable", "mismatches": mismatch}
    for record in (before, after):
        if record.get("usage_status") != "actual" or not isinstance(record.get("cost_usd"), (int, float)):
            return {"status": "not_measured", "reason": "final measured cost required"}
        if record.get("regression_runs", 0) != 0:
            return {"status": "invalid", "reason": "regression must be recommendation-only in both runs"}
        if not record.get("evidence_refs"):
            return {"status": "not_measured", "reason": "usage evidence references required"}
    if before["cost_usd"] <= 0 or after["cost_usd"] < 0:
        raise ValueError("invalid costs")
    if (after.get("missed_seeded_defects", 0) > before.get("missed_seeded_defects", 0) or
            set(before.get("verified_scope", [])) - set(after.get("verified_scope", []))):
        return {"status": "quality_regression"}
    ratio = after["cost_usd"] / before["cost_usd"]
    return {"status": "passed" if ratio <= 0.5 else "target_not_met", "cost_ratio": ratio,
            "savings_percent": 100 * (1 - ratio)}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("before")
    parser.add_argument("after")
    args = parser.parse_args()
    print(json.dumps(compare(json.loads(Path(args.before).read_text(encoding="utf-8")),
                             json.loads(Path(args.after).read_text(encoding="utf-8")))))


if __name__ == "__main__":
    main()
