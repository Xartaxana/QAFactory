"""What a person's own words mean - as a pre-filled option the orchestrator reads back, never a record.

Three turns of the live run went to the same shape: the person answered a gate or a stand-gap
card in their own words, and the orchestrator spent a model turn deciding which registered
option that was before it could build the request. The judge answers that in 100 ms. What it
never does is record it: `gate-decision` and `waiver.py` still take the person's verbatim
words, and the orchestrator confirms the option with them first. A gate is a safety refusal,
so `judged_refusal` is not used here and no answer of this script lifts anything.

  judge_reply.py --asked-file <f> --reply "<their words>" [--gate A|B]
  judge_reply.py --stand-gap --reply "<their words>"
  judge_reply.py --same-cause --a "<refusal>" --b "<refusal>"

One line on stdout, the decision JSON with `--json`. Exit 0 on `ok` and `off`, 3 when the
judge was wanted and could not answer - then the orchestrator asks the person, as before.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge  # noqa: E402

# The words the orchestrator may act on, per form. `other` is in every list on purpose: a
# reply that is none of the options must be able to say so instead of being rounded to one.
INTENTS = ("approve", "approve_with_edits", "reject", "question", "waiver", "other")


def _decision(state: dict, judgment_id: str, *, ticket=None, stage=None, project_root=None) -> dict:
    cfg = judge.settings(project_root)
    out = {"judgment": judgment_id, "provider": cfg["provider"], "mode": cfg["mode"],
           "status": "off", "value": None, "leaning": None, "confidence": None,
           "advisory": cfg["mode"] != "on"}
    if not judge.active(cfg, judgment_id):
        return out
    answer = judge.ask_one(state, judgment_id, ticket=ticket, stage=stage,
                           project_root=project_root, cfg=cfg)
    if not answer:
        return dict(out, status="unavailable")
    return dict(out, status="ok", value=answer.get("value"), leaning=answer.get("leaning"),
                confidence=answer.get("confidence"), probability=answer.get("probability"),
                decided=answer.get("decided"), advisory=answer.get("advisory", True))


def intent(question: str, reply: str, **common) -> dict:
    """Which registered option a gate answer is. The orchestrator confirms it before recording."""
    return _decision({"question": question[:6000], "reply": reply[:4000]},
                     "gate_reply_intent", **common)


def stand_gap_option(reply: str, **common) -> dict:
    return _decision({"reply": reply[:4000]}, "gate_stand_gap_option", **common)


def same_cause(message_a: str, message_b: str, **common) -> dict:
    return _decision({"message_a": message_a[:4000], "message_b": message_b[:4000]},
                     "gate_same_cause", **common)


def render(result: dict, form: str) -> str:
    if result["status"] == "off":
        return f"judge_reply: off ({form}) - read the answer yourself, as without a judge"
    if result["status"] == "unavailable":
        return f"judge_reply: unavailable ({form}) - ask the person which option they meant"
    if result.get("value") is None:
        return (f"judge_reply: {form} undecided (leaning {result.get('leaning')}, "
                f"confidence {result.get('confidence')}) - ask the person")
    strength = result.get("probability")
    strength = result.get("confidence") if strength is None else strength
    mode = "pre-filled" if result["mode"] == "on" else "shadow, act on nothing"
    return (f"judge_reply: {form}={result['value']} ({strength}) - {mode}; "
            "confirm it with the person before you record anything")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--asked-file", help="the file holding the exact message the person answered")
    parser.add_argument("--asked", help="the message the person answered, inline")
    parser.add_argument("--reply", help="their answer, verbatim")
    parser.add_argument("--gate", choices=["A", "B"])
    parser.add_argument("--stand-gap", action="store_true", help="the reply answers a stand-gap card")
    parser.add_argument("--same-cause", action="store_true")
    parser.add_argument("--a", help="the first refusal message")
    parser.add_argument("--b", help="the second refusal message")
    parser.add_argument("--ticket")
    parser.add_argument("--project-root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    common = {"ticket": args.ticket, "stage": f"gate {args.gate}" if args.gate else "gate",
              "project_root": args.project_root}
    if args.same_cause:
        if not args.a or not args.b:
            parser.error("--same-cause needs --a and --b")
        result, form = same_cause(args.a, args.b, **common), "same_cause"
    elif args.stand_gap:
        if not args.reply:
            parser.error("--stand-gap needs --reply")
        result, form = stand_gap_option(args.reply, **common), "stand_gap_option"
    else:
        if not args.reply or not (args.asked_file or args.asked):
            parser.error("the gate form needs --reply and --asked-file or --asked")
        question = args.asked or ""
        if args.asked_file:
            try:
                question = Path(args.asked_file).read_text(encoding="utf-8")
            except OSError as exc:
                print(f"judge_reply: cannot read {args.asked_file}: {exc}")
                return 2
        result, form = intent(question, args.reply, **common), "intent"
    result["form"] = form
    if form == "intent":
        result["options"] = list(INTENTS)
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result, form))
    return 0 if result["status"] in ("ok", "off") else 3


if __name__ == "__main__":
    sys.exit(main())
