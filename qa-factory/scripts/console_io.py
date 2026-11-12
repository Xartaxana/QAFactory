"""One place that puts the standard streams on UTF-8 (B-413).

A Windows console or pipe is cp1251, cp866 or ascii, and the scripts print non-ASCII text (an
em dash in `install_smoke`'s first line, in every `--help`). Under such a stream the same script
either dies with UnicodeEncodeError or prints the wrong bytes (U+2014 is byte 0x97 in cp1251),
so a person reads `?` where the text was. Before this module twelve scripts carried their own
copy of the reconfigure loop and a dozen entry scripts carried none.

    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass

The guard is a missing file's door (nothing crashes, a hook never fails open); the import stands
on its own line because audit A1 reads `import X` at the start of a line.

Precedence, measured (B-413 R0): `reconfigure()` in the process beats a caller's
`PYTHONIOENCODING`, which beats UTF-8 mode (`PYTHONUTF8=1`); only the in-process call is
certain to win, so this module never relies on the environment.

Error direction: the function may leave a stream exactly as it was (a StringIO, a capture, a
closed stream, `None` under pythonw, a stream without `reconfigure`) and it NEVER raises. It
runs at the top of every hook and launcher, so the only failure it may cause is no change.
Streams are looked up at CALL time, so a stream swapped in before the call is the one handled.
Importing the module has no side effect.
"""
from __future__ import annotations

import sys


def utf8_stdio(*, stdin: bool = False, errors: str = "replace",
               line_buffering: bool | None = None) -> None:
    """Reconfigure stdout and stderr (and stdin when `stdin` is True) to UTF-8 with `errors`.

    `line_buffering` is passed only when it is not None, and never to stdin. An exception on
    one stream is swallowed and the next stream is still tried."""
    names = ["stdout", "stderr"] + (["stdin"] if stdin else [])
    for name in names:
        stream = getattr(sys, name, None)
        try:
            if name == "stdin" or line_buffering is None:
                stream.reconfigure(encoding="utf-8", errors=errors)
            else:
                stream.reconfigure(encoding="utf-8", errors=errors,
                                   line_buffering=line_buffering)
        except Exception:
            pass


def ascii_only(text) -> str:
    """`text` as ASCII: every character outside it becomes `?`. The one copy of the console
    fallback (PC1-2): a line printed on a console that cannot spell a word must not raise.
    Never raises; `None` and empty give an empty string."""
    return str(text or "").encode("ascii", "replace").decode("ascii")


def plain(text, *, one_line: bool = False) -> str:
    """ASCII text with no quotes of its own: `"` and a backtick become `'`; with `one_line`
    every run of whitespace is folded to one space first. Then `ascii_only`."""
    flat = str(text or "")
    if one_line:
        flat = " ".join(flat.split())
    return ascii_only(flat.replace('"', "'").replace("`", "'"))
