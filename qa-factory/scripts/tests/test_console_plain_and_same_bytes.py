"""PC1-2 remainder (t-1724, spec t-1701 D5-D): the typed JSON comparison of `onboard_apply._same_bytes` and the one
ASCII fallback of `console_io`.

Keys: K1 typed comparison (`true`/`1`/`1.0` are three values) | K2 `compare_trees` names the path |
K3 an empty ignore keeps the raw-bytes rule | K4 `plain` / `ascii_only` | K5 the helpers of
`judge_run`, `stand_health` use the one fallback; E-D1 not JSON, E-D2 RecursionError -> differing.

Mutation this file kills: K1 <- Python `==` back in `_same_bytes` (K1 and K2 go red).

Run: python -B scripts/tests/test_console_plain_and_same_bytes.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, cleanup, finish, temp_dir, temp_project, use_project  # noqa: E402

use_project(temp_project("qa-console-plain-audit-"))

import console_io  # noqa: E402
import onboard_apply as OA  # noqa: E402

root = temp_dir("qa-console-plain-")


def same(a: bytes, b: bytes, ignore=frozenset({"ts"}), name="f.json") -> bool:
    pa, pb = root / ("a_" + name), root / ("b_" + name)
    pa.write_bytes(a)
    pb.write_bytes(b)
    return OA._same_bytes(pa, pb, frozenset(ignore))


# K1 - typed comparison, with a non-empty ignore
check("K1 true vs 1 is not same", not same(b'{"a":true}', b'{"a":1}'))
check("K1 1 vs 1.0 is not same", not same(b'{"a":1}', b'{"a":1.0}'))
check("K1 '1' vs 1 is not same", not same(b'{"a":"1"}', b'{"a":1}'))
check("K1 key order is same", same(b'{"a":1,"b":2}', b'{"b":2,"a":1}'))
check("K1 a difference only in an ignored field is same", same(b'{"a":1,"ts":"x"}', b'{"a":1,"ts":"y"}'))
check("K1 a difference in a kept field beside an ignored one is not same", not same(b'{"a":1,"ts":"x"}', b'{"a":2,"ts":"x"}'))

# E-D1 / E-D2 - the error direction is "differing"
check("E-D1 one side not JSON is not same", not same(b'{"a":1}', b"not json"))
check("E-D1 both sides not JSON and different is not same", not same(b"xx", b"yy"))
check("E-D1 a side that is not UTF-8 is not same", not same(b'{"a":1}', b'\xff\xfe{"a":1}'))
deep = b"[" * 5000 + b"]" * 5000
check("E-D2 a RecursionError is differing, not an exception", not same(deep, deep.replace(b"[]", b"[1]", 1)))

# K2 - compare_trees names the path in `differing`
ta, tb = root / "ta", root / "tb"
for t, body in ((ta, b'{"a":true}'), (tb, b'{"a":1}')):
    (t / "cfg").mkdir(parents=True)
    (t / "cfg" / "x.json").write_bytes(body)
try:
    found = OA.compare_trees(ta, tb, ignore_json_fields={"cfg/x.json": ["ts"]})
except Exception as exc:  # the real table is loaded by default; report any trouble as a red line
    found = {"differing": [f"EXC {type(exc).__name__}: {exc}"]}
check("K2 compare_trees names cfg/x.json in differing", "cfg/x.json" in found["differing"], str(found))

# K3 - an empty ignore: raw bytes only (unchanged)
check("K3 empty ignore, identical bytes: same", same(b'{"a":1}', b'{"a":1}', ignore=()))
check("K3 empty ignore, key order differs: not same", not same(b'{"a":1,"b":2}', b'{"b":2,"a":1}', ignore=()))

# K4 - the helper
check_eq("K4 plain one_line", console_io.plain('a "b" `c`\n d', one_line=True), "a 'b' 'c' d")
check_eq("K4 plain keeps whitespace without one_line", console_io.plain('a  "b"\nc'), "a  'b'\nc")
check_eq("K4 plain non-ascii", console_io.plain("é"), "?")
check_eq("K4 ascii_only None", console_io.ascii_only(None), "")
check_eq("K4 ascii_only keeps quotes", console_io.ascii_only('a"b`'), 'a"b`')
check_eq("K4 plain None", console_io.plain(None), "")

# K5 - the helpers of `judge_run` and `stand_health` go through the one ASCII fallback
import judge_run  # noqa: E402
import stand_health  # noqa: E402
check_eq("K5 behaviour: judge_run._plain goes through the helper", judge_run._plain('a "b"\nc é'), "a 'b' c ?")
check_eq("K5 behaviour: stand_health._plain goes through the helper", stand_health._plain('a "b" é'), "a 'b' ?")

cleanup(root)
finish("console_plain_and_same_bytes")
