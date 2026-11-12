"""test_hooklib_append_jsonl.py - `hooklib.append_jsonl_line`, the one safe jsonl appender (t-109 m5).

Run from the package root: python -B scripts/tests/test_hooklib_append_jsonl.py

Keys: absent file created (folder too), torn tail gets ONE newline first and no byte is lost, an existing file is never
truncated, the header goes in only when the file is absent or empty and in the SAME write, a line break inside a line is
refused with nothing written, a non-ASCII line is UTF-8, several threads appending at once leave every line whole.
Mutation -> killing key (named, not run): drop the torn-tail newline -> `torn tail`; open without O_APPEND/with truncation ->
`never truncated`; write the header on every call -> `header only once`.
"""
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

import hooklib  # noqa: E402


def main() -> None:
    root = temp_dir("qa-hooklib-append-")
    try:
        path = root / "a" / "b" / "file.jsonl"
        hooklib.append_jsonl_line(path, '{"n": 1}')
        check_eq("absent file and folder: created, one terminated line", path.read_bytes(), b'{"n": 1}\n')
        hooklib.append_jsonl_line(path, '{"n": 2}\n')
        check_eq("an existing file is never truncated: the line is added; a trailing newline of the text is not doubled",
                 path.read_bytes(), b'{"n": 1}\n{"n": 2}\n')
        path.write_bytes(b'{"n": 1}\n{"n": 2}')
        hooklib.append_jsonl_line(path, '{"n": 3}')
        check_eq("torn tail: ONE newline first, every earlier byte kept", path.read_bytes(), b'{"n": 1}\n{"n": 2}\n{"n": 3}\n')
        # header
        fresh = root / "h.jsonl"
        hooklib.append_jsonl_line(fresh, '{"n": 1}', header='{"started_at": "t"}')
        check_eq("header: an absent file gets the header and the line in one write", fresh.read_bytes(),
                 b'{"started_at": "t"}\n{"n": 1}\n')
        hooklib.append_jsonl_line(fresh, '{"n": 2}', header='{"started_at": "t2"}')
        check_eq("header only once: a file with content never gets it again", fresh.read_bytes(),
                 b'{"started_at": "t"}\n{"n": 1}\n{"n": 2}\n')
        empty = root / "e.jsonl"
        empty.write_bytes(b"")
        hooklib.append_jsonl_line(empty, '{"n": 1}', header='{"h": 1}')
        check_eq("header: a 0-byte file counts as empty", empty.read_bytes(), b'{"h": 1}\n{"n": 1}\n')
        # refusals write nothing
        kept = path.read_bytes()
        for label, text, header in (("a line break inside the line", '{"a": 1}\n{"b": 2}', None),
                                    ("a line break inside the header", '{"a": 1}', '{"h": 1}\n{"h": 2}')):
            try:
                hooklib.append_jsonl_line(path, text, header=header)
                refused = False
            except ValueError:
                refused = True
            check(f"{label}: ValueError, nothing written", refused and path.read_bytes() == kept)
        # non-ASCII is UTF-8
        text = json.dumps({"s": "café ✓"}, ensure_ascii=False)
        utf = root / "u.jsonl"
        hooklib.append_jsonl_line(utf, text)
        check_eq("a non-ASCII line is written as UTF-8", utf.read_bytes().decode("utf-8"), text + "\n")
        # several threads at once (one process): every line whole, none lost
        many = root / "t.jsonl"
        threads = [threading.Thread(target=lambda k=k: [hooklib.append_jsonl_line(many, json.dumps({"k": k, "i": i}))
                                                        for i in range(25)]) for k in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        rows = [json.loads(x) for x in many.read_text(encoding="utf-8").split("\n") if x]
        check_eq("8 threads x 25 lines: 200 whole lines, none lost, none torn", (len(rows), len({(r["k"], r["i"]) for r in rows})),
                 (200, 200))
    finally:
        cleanup(root)
    finish("test_hooklib_append_jsonl")


if __name__ == "__main__":
    main()
