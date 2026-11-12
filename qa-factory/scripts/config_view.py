"""One key of the project's config, not the whole file (speed-cost SC1-8, release 0.10.3).

TP1-12586: the conductor and the tester each read `qa-factory/config.json` whole - 52 187 characters, about three million
token-reads over the run - because nothing offered a smaller door and the big-read guard exempts the file by name. This is that door.

  config_view.py --keys [PREFIX]       the children of PREFIX (default: the root) as `<key>  <type> <size>`; ` [note]` marks a key that
                                       has a `<key>_note` beside it (the notes themselves are not listed)
  config_view.py --get PATH [PATH ...] the value of each PATH as JSON, whole; a container over 6000 bytes is answered with its keys and
                                       the narrower path to ask for; a scalar is always whole

A PATH is dotted (`adapters.ticket.name`; a number is an array index: `code_repos.0`) or, when it starts with `/`, a JSON pointer
(`/environments/a.b`, for a key that holds a dot). Git Bash on Windows rewrites an argument that starts with `/` into a Windows
path before this script sees it (measured: `/adapters/ticket` arrives as `C:/Program Files/Git/adapters/ticket`, `/a/b` as `A:/b`;
`#/a/b` is rewritten too): there run the command with `MSYS_NO_PATHCONV=1`. A path that arrives already rewritten is refused
(exit 2) with that door, never answered as an absent key. A key that is not there is an ANSWER, not an
error: `PATH: absent`, what the table `references/config-keys.json` says an absent key means, and the nearest prefix that exists
with its keys - the nearest key is never substituted for the asked one (FR-41). A list over 6000 bytes shows what fits, then a
pointer line (`detector_verdict._pointer`, the one wording); the whole list is in `qa-factory/state/output/config-keys.txt`
(written by this script only, through `event_store.atomic_text`; when it cannot be written the whole list is printed).

Exit codes: 0 an answer (absent included); 2 a call or a path that cannot be read (stderr, with an example); 3 the project has no
`qa-factory/config.json` (stderr: the onboarding door); 4 the file is there and is empty, not JSON or not an object (stderr: the reader's
own sentence and its door - an unreadable config is never read as an empty one, AR-28).

The ONE reader of the file is `config_contract.read_config_file` (AR-13); the stage cards of `story_step.py card` call `card_values`.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config_contract  # noqa: E402
import detector_verdict  # noqa: E402  (`fit`: the one cutter of a list into whole lines, AR-15)
import event_store  # noqa: E402  (`atomic_text`: the one atomic writer, beside `atomic_json` which `controller.py --brief` uses)
import hooklib  # noqa: E402

VIEW_MAX_BYTES = 6000        # a listing or a value this long is whole; one byte more is cut to a pointer / a narrower path
CARD_VALUE_MAX_BYTES = 600   # a value on a stage card: whole up to here, else its shape and the door
SCALAR_SHOWN_MAX = 60        # a scalar of a listing is shown by value up to this many characters
EXIT_USAGE = 2
EXIT_NO_CONFIG = hooklib.EXIT_NO_PROJECT
EXIT_UNREADABLE = 4
OUTPUT_PARTS = ("state", "output", "config-keys.txt")
NO_CONFIG_LINE = "no qa-factory/config.json - run /qa-factory:qa-onboarding"
EXAMPLE = ("config_view.py --keys adapters   |   config_view.py --get adapters.ticket.name code_repos.0   |   "
           "config_view.py --get /environments/a.b (Git Bash on Windows: MSYS_NO_PATHCONV=1 config_view.py --get /environments/a.b)")


class PathSyntax(ValueError):
    """A path that names nothing readable (empty, an empty segment, a bad pointer escape)."""


class NoConfig(Exception):
    """The project has no qa-factory/config.json (not an unreadable one: that is `ConfigUnreadable`)."""


MANGLED = re.compile(r"^#?[A-Za-z]:/")   # what Git Bash on Windows makes of `/a/b`: `A:/b` (it reads `/a` as a drive)


def parse_path(text: str) -> tuple:
    """`(segments, pointer)` of a dotted path or a JSON pointer. Nothing is guessed: an empty text or an empty segment is a syntax
    error, and so is a text Git Bash has already rewritten from `/a/b` into a drive path (no config key looks like `C:/...`)."""
    text = str(text)
    if MANGLED.match(text):
        raise PathSyntax(f"{text!r}: this is not a config path - Git Bash on Windows rewrites an argument that starts with `/` into a "
                         "Windows path before this script sees it. Set MSYS_NO_PATHCONV=1 for the command (then `/a/b` arrives as "
                         "typed), or write the dotted path")
    if text.startswith("/"):
        segments = []
        for raw in text[1:].split("/"):
            if "~" in raw.replace("~0", "").replace("~1", ""):
                raise PathSyntax(f"{text!r}: a JSON pointer escapes only `~0` (~) and `~1` (/)")
            segments.append(raw.replace("~1", "/").replace("~0", "~"))
        pointer = True
    else:
        segments, pointer = text.split("."), False
    if not text or any(not segment for segment in segments):
        raise PathSyntax(f"{text!r}: a path is `a.b.c` or `/a/b`, with no empty part")
    return segments, pointer


def join_path(segments: list, pointer: bool) -> str:
    if pointer:
        return "".join("/" + s.replace("~", "~0").replace("/", "~1") for s in segments)
    return ".".join(segments)


def resolve(root, segments: list) -> tuple:
    """`(found, node, depth)`: how far the path goes. A number indexes an array (canonical form only: `1`, not `01`); a key that
    is a number is still a key of an object. A step that leads nowhere stops, and `node` is the last thing that exists."""
    node, depth = root, 0
    for segment in segments:
        if isinstance(node, dict) and segment in node:
            node = node[segment]
        elif (isinstance(node, list) and segment.isascii() and segment.isdigit()
              and str(int(segment)) == segment and int(segment) < len(node)):
            node = node[int(segment)]
        else:
            return False, node, depth
        depth += 1
    return True, node, depth


def describe(value) -> str:
    """The type and the size of a value; a scalar by value when that is short."""
    if isinstance(value, dict):
        return f"object {len(value)} keys"
    if isinstance(value, list):
        return f"array {len(value)} items"
    shown = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        return f"string {len(value)} chars" + (f" = {shown}" if len(shown) <= SCALAR_SHOWN_MAX else "")
    return shown if len(shown) <= SCALAR_SHOWN_MAX else f"number {len(shown)} chars"


def listing(node) -> list:
    """The children of a container, one line each. A `<key>_note` is not a child; its key carries ` [note]`."""
    if isinstance(node, dict):
        return [f"{key}  {describe(value)}" + (" [note]" if f"{key}_note" in node else "")
                for key, value in node.items() if not str(key).endswith("_note")]
    if isinstance(node, list):
        return [f"{index}  {describe(value)}" for index, value in enumerate(node)]
    return []


def _output_file() -> Path:
    return hooklib.state_dir().joinpath(*OUTPUT_PARTS)


def _save_text(path: Path, text: str) -> str:
    """Write `text` through the package's one atomic text writer; `""` on success, else the reason in words (never raised: the
    caller prints the whole text instead, a hidden part with no place to find it is a loss)."""
    try:
        event_store.atomic_text(path, text)
        return ""
    except (OSError, ValueError) as exc:
        return f"{type(exc).__name__}: {exc}"


def show_lines(lines: list) -> None:
    """Print a listing: whole up to VIEW_MAX_BYTES (as `detector_verdict.fit` counts), else what fits and the pointer line
    (`detector_verdict._pointer`, the one wording; `fit` marks a cut line with its own `…`) - the whole list is in the output file.
    A file that cannot be written leaves nothing hidden: the whole list is printed (AR-21)."""
    if not lines:
        return
    shown, cut = detector_verdict.fit(lines, VIEW_MAX_BYTES)
    left = len(lines) - len(shown) if not cut else len(lines) - 1
    if not left and not cut:
        print("\n".join(lines))
        return
    reason = _save_text(_output_file(), "\n".join(lines) + "\n")
    if reason:
        print("\n".join(lines))
        print(f"(the list is over {VIEW_MAX_BYTES} bytes and could not be saved: {reason}; it is printed whole)")
        return
    print("\n".join(shown))
    print(detector_verdict._pointer(left, cut, lines, "key", "config_view", None, where="/".join(("qa-factory",) + OUTPUT_PARTS)))


def absent_means(segments: list) -> str:
    """What the table says an absent key means (`default` / `required`), for a path it lists; `""` for a path it does not list."""
    if any("." in s for s in segments):
        return ""
    try:
        entry = config_contract.config_keys()["keys"].get(".".join(segments))
    except ValueError as exc:
        return f"unknown - {exc}"
    return str(entry.get("absent_means") or "") if isinstance(entry, dict) else ""


def print_absent(config: dict, text: str, segments: list, pointer: bool) -> None:
    """`PATH: absent`, what an absent key means, and the nearest prefix that exists with its keys - never a substituted value."""
    means = absent_means(segments)
    print(f"{text}: absent" + (f" (absent_means: {means})" if means else ""))
    _, node, depth = resolve(config, segments)
    prefix = join_path(segments[:depth], pointer)
    print(f"nearest existing prefix: {prefix or '(root)'} - {describe(node)}")
    show_lines(listing(node))


def _load() -> dict:
    config = config_contract.read_config_file(hooklib.project_root())
    if config is None:
        raise NoConfig()
    return config


def card_values(keys: list, max_bytes: int = CARD_VALUE_MAX_BYTES) -> list:
    """One line per key for a stage card: the value whole when it is at most `max_bytes` bytes of JSON, else its shape and the
    door; an absent key says so (with what the table says that means); no config and an unreadable config are ONE line each."""
    try:
        config = _load()
    except NoConfig:
        return [NO_CONFIG_LINE]
    except config_contract.ConfigUnreadable:
        return ["qa-factory/config.json is unreadable - `config_view.py --keys` prints why and what to do"]
    lines = []
    for key in keys:
        try:
            segments, pointer = parse_path(key)
        except PathSyntax as exc:
            lines.append(f"{key}: not a readable config path ({exc})")
            continue
        found, value, _ = resolve(config, segments)
        if not found:
            means = absent_means(segments)
            lines.append(f"{key}: absent" + (f" (absent_means: {means})" if means else ""))
            continue
        text = json.dumps(value, ensure_ascii=False)
        size = len(text.encode("utf-8", "replace"))
        if size <= max_bytes:
            lines.append(f"{key}: {text}")
            continue
        shape = {dict: f"object of {len(value)} keys", list: f"array of {len(value)} items"}.get(type(value), f"string of {size} bytes")
        lines.append(f"{key}: {shape} - config_view.py --get {key}")
    return lines


def cmd_keys(config: dict, prefix: str) -> int:
    if not prefix:
        node, text, segments, pointer = config, "", [], False
    else:
        segments, pointer = parse_path(prefix)
        text = prefix
        found, node, _ = resolve(config, segments)
        if not found:
            print_absent(config, text, segments, pointer)
            return 0
    if not isinstance(node, (dict, list)):
        print(f"{text}: {describe(node)}")
        print(f"(a value, not a container: config_view.py --get {text})")
        return 0
    if text:
        print(f"{text}: {describe(node)}")
    show_lines(listing(node) or ["(empty)"])
    return 0


def cmd_get(config: dict, paths: list) -> int:
    for text in paths:
        segments, pointer = parse_path(text)
        found, node, _ = resolve(config, segments)
        if len(paths) > 1:
            print(f"== {text}")
        if not found:
            print_absent(config, text, segments, pointer)
            continue
        shown = json.dumps(node, ensure_ascii=False, indent=1)
        size = len(shown.encode("utf-8", "replace"))
        if not isinstance(node, (dict, list)) or size <= VIEW_MAX_BYTES:
            print(shown)
            continue
        print(f"{text}: {describe(node)}")
        show_lines(listing(node))
        child = "<key>" if isinstance(node, dict) else "<index>"
        print(f"value is {size} bytes; ask a narrower path: config_view.py --get "
              f"{join_path(segments + [child], pointer)}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="One key of the project's qa-factory/config.json, not the whole file.",
                                     epilog="examples: " + EXAMPLE)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--keys", nargs="?", const="", default=None, metavar="PREFIX",
                       help="list the children of PREFIX (default: the root) with type and size")
    group.add_argument("--get", nargs="+", default=None, metavar="PATH",
                       help="print the value at each PATH (dotted, or a JSON pointer starting with /; Git Bash on Windows rewrites "
                            "a leading / into a Windows path: run the command with MSYS_NO_PATHCONV=1 there)")
    return parser


def main(argv=None) -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    args = _parser().parse_args(argv)
    try:
        for text in ([args.keys] if args.keys else []) + (args.get or []):
            parse_path(text)
    except PathSyntax as exc:
        print(f"config_view: {exc}. Examples: {EXAMPLE}", file=sys.stderr)
        return EXIT_USAGE
    try:
        config = _load()
    except NoConfig:
        print(f"config_view: no qa-factory/config.json under {hooklib.project_root()} - this project was never onboarded: run "
              "/qa-factory:qa-onboarding; or this is the wrong project root: run the command from inside the project, or set "
              "CLAUDE_PROJECT_DIR to it.", file=sys.stderr)
        return EXIT_NO_CONFIG
    except config_contract.ConfigUnreadable as exc:
        print(f"config_view: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE
    return cmd_keys(config, args.keys) if args.keys is not None else cmd_get(config, args.get)


if __name__ == "__main__":
    sys.exit(main())
