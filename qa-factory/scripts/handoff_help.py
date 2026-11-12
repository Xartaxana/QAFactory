"""A role cannot fill a field: the question goes to the conductor, never to the person.

This builds the request from the form's own `blocked` section (contract, field, what was
tried, the refusal verbatim, the word the role WOULD have written), writes it beside the form
as `<dispatch>.help.yaml`, and - when a judge is configured - asks the one question that
decides what happens next:

    fill | correct_the_work | ask_the_person | change_the_contract

A conductor session on TP1-13797 cost about $0.45 and there were fifty-four of them; this
question costs about $0.00002. What the judge cannot decide still goes to the conductor, with
the same file, so nothing is lost - only the routine is taken off the expensive path.

  handoff_help.py --file work/handoffs/<dispatch>.yaml [--field F] [--problem "..."]
                  [--tried "..."] [--candidate WORD] [--json]

The judge never answers for the person here: `ask_the_person` is an outcome, not a shortcut,
and the question it produces is the one the conductor puts, in the factory's own form.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import handoff  # noqa: E402

try:
    import judge  # noqa: E402
except Exception:                                    # pragma: no cover - judge is optional
    judge = None

RESOLUTIONS = ("fill", "correct_the_work", "ask_the_person", "change_the_contract")


def request_of(doc, form_path: Path, args) -> dict:
    blocked = doc.data.get("blocked") if isinstance(doc.data.get("blocked"), dict) else {}
    def pick(key, override):
        value = override or blocked.get(key) or ""
        return "" if handoff.is_placeholder(value) else str(value)
    tried = blocked.get("tried") if isinstance(blocked.get("tried"), list) else []
    tried = [str(t) for t in tried if not handoff.is_placeholder(t)]
    if args.tried:
        tried.append(args.tried)
    data = blocked.get("data") if isinstance(blocked.get("data"), list) else []
    return {
        "contract": str(doc.get("contract") or ""),
        "file": str(form_path),
        "dispatch": form_path.stem,
        "role": str(doc.get("header.role") or doc.get("from_role") or ""),
        "stage": str(doc.get("header.stage") or doc.get("stage") or ""),
        "field": pick("field", args.field),
        "problem": pick("problem", args.problem),
        "refusal": pick("problem", args.refusal or ""),
        "tried": tried,
        "candidate": args.candidate or "",
        "data": [str(d) for d in data if not handoff.is_placeholder(d)],
    }


def options_for(request: dict) -> dict:
    """The four outcomes, described for the question rather than for a reader of this file."""
    return {
        "fill": "The answer is already in the contract, the vocabulary or the artifacts on "
                "disk, and the role simply did not find it. The conductor writes the value.",
        "correct_the_work": "The form is right and the WORK is not: the role must change "
                            "something it did or produce a missing artifact before it can fill this.",
        "ask_the_person": "Only a person can settle it: it is a decision about scope, risk, "
                          "money, their stand or their data.",
        "change_the_contract": "The role is right and the FORM is wrong: the value it needs "
                               "does not exist in the contract or the vocabulary.",
    }


def ask(request: dict, ticket: str):
    if not judge or not judge.active():
        return None
    state = {k: v for k, v in request.items() if v}
    try:
        reply = judge.ask(state, {"q": {"judgment": "conductor_resolution",
                                        "criteria": options_for(request)}},
                          ticket=ticket, stage=request.get("stage") or None)
    except Exception:
        return None
    if reply.get("status") != "ok":
        return None
    answer = (reply.get("answers") or {}).get("q") or {}
    answer["advisory"] = reply.get("advisory")
    return answer


def render(request: dict, answer) -> list:
    lines = ["# The request a role makes when it cannot fill its handoff. The conductor answers",
             "# in `answer:`; the role never takes a filling problem to the person.",
             "schema_version: 1", "contract: role-to-conductor", "request:"]
    for key in ("contract", "file", "dispatch", "role", "stage", "field", "problem", "candidate"):
        if request.get(key):
            lines.append(f"  {key}: {json.dumps(request[key], ensure_ascii=False)}")
    if request.get("refusal"):
        lines.append(f"  refusal: {json.dumps(request['refusal'], ensure_ascii=False)}")
    for key in ("tried", "data"):
        if request.get(key):
            lines.append(f"  {key}:")
            lines += [f"    - {json.dumps(str(v), ensure_ascii=False)}" for v in request[key]]
    lines.append("answer:")
    if answer and answer.get("decided") and not answer.get("advisory"):
        lines += [f"  resolution: {answer.get('value')}",
                  "  authority: vocabulary",
                  "  source: judge conductor_resolution",
                  f"  confidence: {answer.get('confidence')}",
                  "  by: judge"]
    else:
        lines += ["  resolution: <one of vocabulary.conductor_resolutions>",
                  "  authority: <one of vocabulary.conductor_authorities>",
                  "  source: <the file and section the answer comes from>",
                  "  write: <exactly what the role puts in the field>",
                  "  why: <one sentence, in the role's own terms>"]
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--task", default="")
    ap.add_argument("--field", default="")
    ap.add_argument("--problem", default="")
    ap.add_argument("--refusal", default="")
    ap.add_argument("--tried", default="")
    ap.add_argument("--candidate", default="", help="the word the role WOULD write - the most "
                                                    "useful line in the form: it finds the holes")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    form = Path(args.file)
    if not form.is_file():
        print(f"handoff_help: no such file: {form}")
        return 2
    from handoff_check import form_view      # the form plus its waiting values file: a `blocked` written there is seen (SC1-2, B-1)
    doc = form_view(form)
    request = request_of(doc, form, args)
    if not request["field"] and not request["problem"]:
        print("handoff_help: the form's `blocked` section is empty and no --field/--problem was "
              "given. Fill `blocked` (the field, what you tried, what refused you, the paths to "
              "the data) - that IS the question, and a conductor cannot answer without it.")
        return 2
    answer = ask(request, args.task)
    out = form.with_suffix(".help.yaml")
    out.write_text("\n".join(render(request, answer)) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps({"request": request, "answer": answer, "file": str(out)},
                         ensure_ascii=False, indent=1))
        return 0
    print(f"conductor request: {out}")
    if answer and answer.get("decided") and not answer.get("advisory"):
        print(f"judge: {answer.get('value')} (confidence {answer.get('confidence')})")
        print({"fill": "the answer is in the contract or the artifacts - the conductor writes it",
               "correct_the_work": "the form is right and the work is not: repair the work first",
               "ask_the_person": "this is a person's decision; the conductor asks it, not you",
               "change_the_contract": "you are right and the form is wrong: this goes to the "
                                      "factory backlog, with an interim value for today",
               }.get(str(answer.get("value")), ""))
        return 0
    if answer:
        print(f"judge: undecided ({answer.get('value')} at {answer.get('confidence')}) - the "
              f"conductor answers")
    print("hand this file to the conductor, with the contract and the vocabulary:")
    print(f"  contract: {handoff.CONTRACTS / (request['contract'] + '.yaml')}")
    print(f"  vocabulary: {handoff.CONTRACTS / 'vocabulary.yaml'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
