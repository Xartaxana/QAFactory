"""Resolve a stand from explicit decisions, never configuration list order."""
def select_environment(config, requested=None, saved=None, user_decision=None):
    choices = [item for item in config.get("environments", []) if isinstance(item, dict)]
    names = {item.get("name") for item in choices if item.get("name")}
    for source, value in (("launch", requested), ("story", saved), ("user_decision", user_decision)):
        if value:
            if value not in names:
                return {"status": "unknown", "reason": "selected environment not configured", "environment_id": value}
            return {"status": "selected", "environment_id": value, "selected_by": source}
    defaults = [item["name"] for item in choices if item.get("default") is True]
    if len(defaults) == 1:
        return {"status": "selected", "environment_id": defaults[0], "selected_by": "confirmed_default"}
    if len(names) == 1:
        return {"status": "selected", "environment_id": next(iter(names)), "selected_by": "only_environment"}
    # An empty `environments[]` is NOT the same question. s1.md printed "Which stand do I test
    # on: <names>?" with nothing after the colon — a question with no answers in it, asked of a
    # person whose project simply has no stand recorded (0.7.7 review, finding A-F10). The
    # caller branches on this flag instead: say that onboarding records a stand, and go on with
    # everything that does not need one.
    return {"status": "question_required", "choices": sorted(names),
            "no_environments_configured": not names,
            "independent_discovery_allowed": True, "execution_allowed": False}


if __name__ == "__main__":
    import argparse, json
    from pathlib import Path
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--requested")
    parser.add_argument("--saved")
    parser.add_argument("--decision")
    args = parser.parse_args()
    print(json.dumps(select_environment(json.loads(Path(args.config).read_text(encoding="utf-8-sig")),
                                        args.requested, args.saved, args.decision)))
