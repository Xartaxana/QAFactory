"""explore_step.py - the ONE command line of an exploration (qa-explore).

    explore_step.py frame "<the feature, in the person's words>" [--story KEY]... [--repo NAME]... [--jql TEXT] [--session ID] [--json]
    explore_step.py answer --slug S (--words-file F [--token yes|stop] | --not-asked) [--session ID]
    explore_step.py narrow --slug S --words-file F [--story KEY]... [--repo NAME]... [--jql TEXT] [--clear stories|repos|jql]... [--session ID]
    explore_step.py next --slug S [--json]
    explore_step.py brief --slug S --step E1|E2|E3 [--repo ID]
    explore_step.py release --slug S [--words-file F] [--session ID]

Exit codes: 0 done; 2 a refusal (it says what is wrong, what was expected and the command that opens the door); 3 the project is not
onboarded. The library is exploration.py; this file only reads the arguments, resolves the session, calls it and prints. Every
writing command takes the lock of the exploration first (one session at a time); `next` and `brief` read only. `--session` takes
only an id the host gave: without it the id comes from the session's own hook receipt or environment.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import console_io
    console_io.utf8_stdio()
except ImportError:
    pass
import exploration
import hooklib
import session_identity
from role_cli import RefusingParser, run_guarded

SCRIPT = exploration.SCRIPT
SUBCOMMANDS = ("frame", "answer", "narrow", "next", "brief", "release")


def _command(argv) -> str:
    for token in argv:
        if token in SUBCOMMANDS:
            return f"{SCRIPT} {token}"
    return SCRIPT


def _parser(command: str) -> RefusingParser:
    parser = RefusingParser(command=command, prog=SCRIPT, description=__doc__.split("\n\n")[0])
    subs = parser.add_subparsers(dest="sub", required=True, parser_class=RefusingParser)

    def add(name: str, **more):
        sub = subs.add_parser(name, command=f"{SCRIPT} {name}", help=name, **more)
        return sub

    def session(sub):
        sub.add_argument("--session", default="", help="a session id the host gave; leave it out and the command finds its own")

    frame = add("frame")
    frame.add_argument("phrase", help="the feature, in the person's words")
    frame.add_argument("--story", action="append", default=[], help="an issue key to read (repeatable)")
    frame.add_argument("--repo", action="append", default=[], help="a repository name to read (repeatable)")
    frame.add_argument("--jql", default=None, help="a tracker query to search with")
    frame.add_argument("--json", action="store_true", help="print one JSON object")
    session(frame)
    answer = add("answer")
    answer.add_argument("--slug", required=True)
    answer.add_argument("--words-file", default=None, help="the person's words, whole, in a file")
    answer.add_argument("--token", default=None, help="the word they chose (yes or stop), when you read it from their words")
    answer.add_argument("--not-asked", action="store_true", help="nobody was asked: take the recommended answer")
    session(answer)
    narrow = add("narrow")
    narrow.add_argument("--slug", required=True)
    narrow.add_argument("--words-file", default=None)
    narrow.add_argument("--story", action="append", default=[])
    narrow.add_argument("--repo", action="append", default=[])
    narrow.add_argument("--jql", default=None)
    narrow.add_argument("--clear", action="append", default=[], choices=("stories", "repos", "jql"))
    session(narrow)
    nxt = add("next")
    nxt.add_argument("--slug", required=True)
    nxt.add_argument("--json", action="store_true")
    brief = add("brief")
    brief.add_argument("--slug", required=True)
    brief.add_argument("--step", required=True, help="E1, E2 or E3")
    brief.add_argument("--repo", default=None, help="the repository (E2 only)")
    release = add("release")
    release.add_argument("--slug", required=True)
    release.add_argument("--words-file", default=None, help="the person's words, when the lock is another session's")
    session(release)
    return parser


def _session(args, optional: bool = False) -> str:
    """The id of this session, or a refusal with the receipt's own text; `optional`: a call that a person's words can carry alone."""
    found = session_identity.resolve(explicit=getattr(args, "session", "") or "", script=SCRIPT)
    if found["problem"] != "none":
        if optional:
            return ""
        raise exploration.ExplorationRefused(session_identity.refusal(found, SCRIPT))
    return found["session_id"]


def _print_next(nxt: dict) -> None:
    for line in exploration.next_lines(nxt):
        print(line)


def _run(argv) -> int:
    args = hooklib.exact_options(_parser(_command(argv))).parse_args(argv)
    state_dir = hooklib.require_project(SCRIPT)
    project = state_dir.parent
    if args.sub == "frame":
        found = exploration.frame(project, args.phrase, args.story, args.repo, args.jql, _session(args))
        if found["price_defect"]:
            print(found["price_defect"], file=sys.stderr)
        if args.json:
            print(json.dumps(found, ensure_ascii=False))
            return 0
        print(f"slug: {found['slug']}\nroot: {found['root']}\nstate: {found['state']}")
        _print_next(found["next"])
        if found["next"]["kind"] == "ask" and found["packet_text"]:
            print("---\n" + found["packet_text"], end="")
    elif args.sub == "answer":
        _print_next(exploration.record_answer(project, args.slug, _session(args), words_path=args.words_file, token=args.token,
                                              not_asked=args.not_asked))
    elif args.sub == "narrow":
        found = exploration.narrow(project, args.slug, _session(args), args.words_file, stories=args.story, repos=args.repo,
                                   jql=args.jql, clear=args.clear)
        print("\n".join(exploration.probe_lines(found["probes"])))
        _print_next(found["next"])
    elif args.sub == "next":
        nxt = exploration.next_step(project, args.slug)
        print(json.dumps(nxt, ensure_ascii=False)) if args.json else _print_next(nxt)
    elif args.sub == "brief":
        print(exploration.brief(project, args.slug, args.step, args.repo), end="")
    else:
        print(exploration.release_lock(project, args.slug, _session(args, optional=bool(args.words_file)), args.words_file))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    return run_guarded(_command(argv), lambda: _run(argv))


if __name__ == "__main__":
    sys.exit(main())
