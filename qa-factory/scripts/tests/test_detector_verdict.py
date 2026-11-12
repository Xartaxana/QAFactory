#!/usr/bin/env python3
"""C2-1: `detector_verdict` - the contract of a detector's output, its one reader, its one renderer.

cmp3 (S5): `exit_gate.detector_errors` took the last three lines of a detector's output, and `s5_precheck` printed two
lines per finding plus a marker line, so a role refused for four findings was shown one and came back four times.
Here: `parse` over every shape an output can take (by the contract, cut off at its end, broken, nothing at all, in
the old form), the tags of the refusal at the source, `Record`, the controller's combined refusal (`split_items`,
`refusal_text`), `render` in BYTES with its pointer to the whole list, and the contract test over the six producers:
statically (the AST of every `print` that starts a REJECT) and by running each on its own refusal.
"""
import ast
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     run_script, temp_project)

sys.path.insert(0, str(SCRIPTS))
import detector_verdict as DV  # noqa: E402
from role_cli import PERSON_MARKER, REPAIR_MARKER  # noqa: E402

HEAD = "REJECT — {n} finding(s):"


def block(n: int, label: str = "") -> str:
    head = HEAD.format(n=n)
    return "\n".join([head[:-1] + (" " + label if label else "") + ":"] + [f"- finding {i}" for i in range(1, n + 1)])


def parse_cases() -> None:
    check_eq("exit 0 is no findings", DV.parse(0, "REJECT — 2 stray\n- a\n- b", "")["findings"], [])
    for n in (1, 4, 1000):
        v = DV.parse(1, block(n) + "\n" + REPAIR_MARKER, "")
        check_eq(f"a block of {n}: n findings, whole, no defect, no unmigrated, the marker of the tail",
                 (len(v["findings"]), v["defects"], v["unmigrated"], v["marker"]), (n, [], "", "repair"))
    check_eq("the findings come without their `- `", DV.parse(1, block(2), "")["findings"], ["finding 1", "finding 2"])
    v = DV.parse(1, block(2) + "\nsome tail\n" + block(3) + "\n" + PERSON_MARKER, "")
    check_eq("two blocks: the sum, the marker of the tail after the LAST block", (len(v["findings"]), v["marker"]),
             (5, "person"))
    check_eq("the marker in the context above the header is not the tail's",
             DV.parse(1, REPAIR_MARKER + "\n" + block(1), "")["marker"], "")
    # cut off at its end: what was printed, and the shortfall said
    v = DV.parse(1, block(5).rsplit("\n", 2)[0], "")
    check_eq("a block cut off at the end of the output: the 3 lines printed and one defect", (len(v["findings"]), v["defects"]),
             (3, ["declared 5 finding(s) and printed 3"]))
    v = DV.parse(1, "REJECT — 4 finding(s):", "")
    check_eq("a header with nothing after it: 0 printed, one defect", (v["findings"], v["defects"]),
             ([], ["declared 4 finding(s) and printed 0"]))
    # broken: one unmigrated text, no finding invented, no defect (no label)
    for name, text in (("a block interrupted by a line that is not `- `", "REJECT — 4 finding(s):\n- a\n- b\nfix: x\n- c"),
                       ("an overrun: one more `- ` line after the n-th", "REJECT — 2 finding(s):\n- a\n- b\n- c"),
                       ("a `- ` line after the tail", "REJECT — 1 finding(s):\n- a\ntail\n- c"),
                       ("a REJECT line with no count", "REJECT — 1 finding(s):\n- a\nREJECT: no count here")):
        v = DV.parse(1, text, "")
        check_eq(f"{name}: one unmigrated text, no finding, no defect",
                 (v["findings"], v["defects"], bool(v["unmigrated"]), "\n" in v["unmigrated"]), ([], [], True, False))
    old = "REJECT — 4 finding(s) for the author:\n" + "".join(f"- [c] message {i}\n  fix: do {i}\n" for i in range(4))
    v = DV.parse(1, old, "")
    check_eq("the old S5 form (a `  fix:` line under each finding), 4 findings: ONE unmigrated text holding all four, "
             "not 'declared 4 printed 1'", (v["findings"], v["defects"], all(f"message {i}" in v["unmigrated"] for i in range(4))),
             ([], [], True))
    v = DV.parse(2, "", "usage: x <file>")
    check_eq("exit 2 (outside the contract) with a free text: unreadable with the stderr tail (RH1-5), no finding",
             (v["findings"], v["unmigrated"], v["unreadable"]),
             ([], "", "exit 2, outside the detector contract: usage: x <file>"))
    v = DV.parse(1, "", "")
    check_eq("refused and printed nothing: unreadable, never a pass", (v["findings"], v["defects"], v["unmigrated"], v["unreadable"]),
             ([], [], "", "exit 1, printed nothing"))
    v = DV.parse(1, "REJECT — 0 finding(s):\ntail", "")
    check_eq("a refusal that declares zero findings is a defect, not a pass", (v["findings"], len(v["defects"])), ([], 1))
    v = DV.parse(1, "", block(2))
    check_eq("the header only in stderr: read by the same rules", len(v["findings"]), 2)
    v = DV.parse(1, block(1), "REJECT — 5 finding(s):\n- x")
    check_eq("headers in stdout: stderr is not read", v["findings"], ["finding 1"])
    v = DV.parse(1, "WARN:\n- w1\n- w2\n" + block(2), "")
    check_eq("`- ` lines of a WARN list above the header are context, not findings", v["findings"],
             ["finding 1", "finding 2"])
    # the label of a producer that judged the words at its source
    v = DV.parse(1, block(2, DV.WORDS_AT_SOURCE), "")
    check_eq("the label in the header: words judged at the source", (v["words"], len(v["findings"])), ("source", 2))
    check_eq("no label: the gate judges the words", DV.parse(1, block(2), "")["words"], "gate")
    for name, text, why in (("interrupted", block(4, DV.WORDS_AT_SOURCE).replace("- finding 3", "tail line").replace("- finding 4", ""),
                             "interrupted after 2"),
                            ("overrun", block(2, DV.WORDS_AT_SOURCE) + "\n- finding 3", "followed by one more '- ' line")):
        v = DV.parse(1, text, "")
        check_eq(f"a labelled header and a block {name}: one unmigrated text and one defect that names the block",
                 (v["findings"], bool(v["unmigrated"]), v["words"], len(v["defects"])), ([], True, "source", 1))
        check("...the defect names the head line, where it stands and why", v["defects"][0].startswith(
            "the block 'REJECT — ") and "at line 1 is malformed: declared " in v["defects"][0]
            and v["defects"][0].endswith(why), v["defects"][0])


def tag_cases() -> None:
    """§L-4/§L-5: `WORDS_REFUSED_AT_SOURCE: <id> <cause>` lines ABOVE the header, tied to the finding by the id in its label."""
    lines = ["- [manifest manifest:TC-1:a] one", "- [smell smell:TC-1:b] two", "- [oracle oracle:TC-1:c] three"]
    tag = lambda fid, cause: f"{DV.WORDS_REFUSED_AT_SOURCE} {fid} {cause}"  # noqa: E731
    head = "REJECT — 3 finding(s) " + DV.WORDS_AT_SOURCE + ":"
    v = DV.parse(1, "\n".join([tag("manifest:TC-1:a", "family"), tag("oracle:TC-1:c", "predating"), head] + lines), "")
    check_eq("a family line and a predating line: the named findings are refused, the other is not",
             v["refused"], ["family", "", "predating"])
    check_eq("...and nothing else is reported", (v["defects"], v["unmigrated"], len(v["findings"])), ([], "", 3))
    for name, line in (("no cause", f"{DV.WORDS_REFUSED_AT_SOURCE} smell:TC-1:b"),
                       ("an unknown cause", tag("smell:TC-1:b", "other"))):
        v = DV.parse(1, "\n".join([line, head] + lines), "")
        check_eq(f"a refusal line with {name}: the finding stays refused and one defect says so",
                 (v["refused"], len(v["defects"])), (["", "unreadable", ""], 1))
        check_in(f"...the defect names the line ({name})", "gives no known cause (family or predating)", v["defects"][0])
    v = DV.parse(1, "\n".join([tag("nothing:here", "family"), head] + lines), "")
    check_eq("a refusal line naming an id that is not printed: a defect, no finding refused",
             (v["refused"], len(v["defects"])), (["", "", ""], 1))
    check_in("...which says so", "which is not among the findings printed", v["defects"][0])
    # a broken block with a refusal line: the line is read all the same
    v = DV.parse(1, "\n".join([tag("manifest:TC-1:a", "family"), head] + lines + ["- one too many"]), "")
    check_eq("a block broken under a refusal line: one unmigrated text that is refused", (v["findings"], v["unmigrated_refused"]),
             ([], "family"))
    v = DV.parse(1, "\n".join([tag("x:y:z", "predating"), "free text, no header"]), "")
    check_eq("no header at all and a refusal line: unmigrated and refused", (bool(v["unmigrated"]), v["unmigrated_refused"]),
             (True, "predating"))
    check_eq("no refusal line: not refused", DV.parse(1, head + "\n" + "\n".join(lines), "")["refused"], ["", "", ""])
    check_eq("`id_token` leaves an id without whitespace or `]` as it is", DV.id_token("oracle:TC-1:f.py:79"),
             "oracle:TC-1:f.py:79")
    check_eq("...and makes one of those a token", DV.id_token("smell:TC-1:env-assert-a b]c"), "smell:TC-1:env-assert-a_b_c")


def record_cases() -> None:
    r = DV.Record("x: y", script="x", words="source", kind="unmigrated", refused="family")
    check_eq("a Record is a str for printing, JSON and substring matching",
             (isinstance(r, str), json.dumps([r]), "y" in r), (True, '["x: y"]', True))
    check_eq("...and carries its attributes", (r.script, r.words, r.kind, r.refused), ("x", "source", "unmigrated", "family"))
    plain = "plain"
    check_eq("a plain str is read as a finding the gate judges", (getattr(plain, "kind", "finding"), getattr(plain, "words", "gate"),
             getattr(plain, "refused", "")), ("finding", "gate", ""))
    check_eq("one_line makes a finding one physical line", DV.one_line("a\n  b\r\nc "), "a b c")
    v = DV.parse(1, block(2), "")
    check_eq("flatten: findings first", DV.flatten(v), ["finding 1", "finding 2"])
    check_in("flatten: the unmigrated text whole", "unmigrated detector output", DV.flatten(DV.parse(1, "free", ""))[0])


COMPOUND = ("3 problems - the request is refused whole, every one is listed:\n"
            "1) decision references stale source revision\n"
            "2) gate before prerequisite completion: already accepted\n   (the second line of item 2)\n"
            "3) author and critic are one identity")


def refusal_cases() -> None:
    items = DV.split_items(COMPOUND)
    check_eq("split_items: the head with 3 items, a continuation line joined to its item", (len(items), "second line" in items[1]),
             (3, True))
    check_eq("split_items: a text with no head is None (a single refusal)", DV.split_items("decision references stale source revision"),
             None)
    check_eq("split_items: a head that declares 3 and 2 items is [] (the head was there: the route is the conductor's)",
             DV.split_items(COMPOUND.rsplit("\n", 1)[0].replace("   (the second line of item 2)\n", "")), [])
    check_eq("refusal_text: the controller's bare text comes back unchanged (the positive control)",
             DV.refusal_text(COMPOUND), COMPOUND)
    check_eq("...and the bare text splits to 3", len(DV.split_items(DV.refusal_text(COMPOUND))), 3)
    wrapped = "story_step finish d1 (exit 2):\nstory_step: refused - " + COMPOUND
    check_eq("refusal_text: the story_step prefix is taken off, the head stands at the start of its line",
             len(DV.split_items(DV.refusal_text(wrapped)) or []), 3)
    check_eq("...and without the normaliser the head is not found at the start of a line, the wrapped text is no compound",
             DV.split_items(wrapped), None)
    cli = "controller decision (exit 2):\n" + json.dumps({"error": COMPOUND})
    check_eq("refusal_text: the JSON `error` of --operation decision gets its real newlines back",
             len(DV.split_items(DV.refusal_text(cli)) or []), 3)
    check_eq("...a line with a `{` that is not JSON stays as it is", DV.refusal_text("a\n{not json\nb"), "a\n{not json\nb")
    check_eq("...and a JSON line without a string `error` stays as it is", DV.refusal_text('{"x": 1}'), '{"x": 1}')


def render_cases() -> None:
    check_eq("render: everything fits - no pointer, no file", DV.render(["a", "b"]), "- a\n- b")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "findings" / "all.txt"
        lines = ["x" * 98] * 10                         # a block of 10 lines is 10 * 100 + 9 = 1009 bytes
        at = DV.render(lines, max_bytes=1009, full_path=path)
        check_eq("render: exactly max_bytes is not a cut (no pointer, no file)", (at.count("\n") + 1, path.exists()), (10, False))
        over = DV.render(lines, max_bytes=1008, full_path=path)
        check_eq("render: max_bytes - 1: a cut - 9 lines and the pointer, the file holds all 10",
                 (len(over.splitlines()), path.exists() and path.read_text(encoding="utf-8").count("\n- ")), (10, 10))
        check_in("render: the pointer counts what is left and names the file", f"- (+1 more finding(s) — the whole list: {path})", over)
        check("render: the file starts with the count of the list", path.read_text(encoding="utf-8").startswith("# 10 finding(s), "))
        # the ceiling is BYTES, not characters: 8 lines of 400 two-byte characters are 3200 characters, 6400 bytes
        two_bytes = chr(0x44F)      # a letter of two UTF-8 bytes, made by code: the package carries no Cyrillic (FR-30)
        wide = [two_bytes * 400] * 8
        shown = DV.render(wide, full_path=path)
        check_eq("render: a ceiling in bytes (the default 6000): 8 lines of 800 bytes do not fit, 7 do, plus the pointer",
                 (len(shown.splitlines()), "(+1 more" in shown), (8, True))
        check("...and the text without the pointer stays within the ceiling",
              len("\n".join(shown.splitlines()[:-1]).encode("utf-8")) <= DV.FINDINGS_MAX_BYTES, shown[-200:])
        # one line longer than the ceiling, a two-byte character at the border
        long_line = DV.render([two_bytes * 100], max_bytes=51, full_path=path)
        body = long_line.splitlines()[0]
        check("render: a first line longer than the ceiling is cut at a character boundary, marked `…`, valid UTF-8",
              body.startswith("- " + two_bytes) and body.endswith("…") and len(body.encode("utf-8")) <= 51 and "�" not in body, body)
        check_in("...and the pointer says a line was cut", "… marks a line cut here", long_line)
    nopath = DV.render(["a"] * 3, max_bytes=5)
    check_in("render: no path (the story is not known): said in words, nothing written", "the whole list could not be saved: "
             "the story is not known", nopath)
    check_not_in("...and no path is invented", "the whole list:", nopath)
    check_eq("render: nothing to show is an empty text", DV.render([]), "")
    check_eq("render: the word of the pointer is a parameter", "(+1 more line(s)" in DV.render(["a", "b"], max_bytes=4, noun="line"), True)


def joined_cases() -> None:
    """C3-8/9: `joined`, the one-line twin of `render`: AT and BEYOND the ceiling, the edges, the adversarial items."""
    five = ["x" * 10] * 5                                    # 5 * 10 + 4 * 2 = 58 characters joined
    check_eq("joined: exactly the ceiling is not a cut (no pointer, no file)", DV.joined(five, noun="item", where="w", max_chars=58),
             "; ".join(five))
    over = DV.joined(five, noun="item", where="the plan file", max_chars=57)
    check_eq("joined: the ceiling - 1 is a cut: 4 items and ONE trailing part that names the place",
             over, "; ".join(five[:4]) + "; (+1 more item(s) — the whole list: the plan file)")
    check_eq("joined: the pointer is its own `; ` part, so a reader that splits at `; ` never glues it to an item",
             over.split("; ")[-1].startswith("(+1 more"), True)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "state" / "findings" / "all.txt"
        fits = DV.joined(five, noun="item", full_path=path, max_chars=58)
        check_eq("joined: at the ceiling with a full_path nothing is written (no pointer without a cut)", (path.exists(), "(+" in fits),
                 (False, False))
        cut = DV.joined(five, noun="item", full_path=path, max_chars=57)
        check_eq("joined: past the ceiling the file written by this call holds all 5 and the pointer names it",
                 (path.read_text(encoding="utf-8").count("\n- "), cut.endswith(f"(+1 more item(s) — the whole list: {path})")), (5, True))
        blocked = Path(tmp) / "plain-file"
        blocked.write_text("x", encoding="utf-8")
        bad = DV.joined(five, noun="item", full_path=blocked / "all.txt", max_chars=57)
        check_in("joined: a path that cannot be written: said in words, the shown items stay (FR-41)",
                 "; (+1 more item(s); the whole list could not be saved: ", bad)
        check_eq("...and the shown items are the same 4", bad.startswith("; ".join(five[:4])), True)
        sur = DV.joined(["a" * 30, "b" + chr(0xD800) + "c"], noun="item", full_path=path, max_chars=31)
        check_in("joined: a lone surrogate in an item does not crash the refusal", "(+1 more item(s)", sur)
    check_eq("joined: no items is `none`, with or without a ceiling", (DV.joined([], noun="x", max_chars=None), DV.joined([], noun="x", where="w")),
             ("none", "none"))
    check_eq("joined: ONE item is the item unchanged (I2)", DV.joined(["only"], noun="x", where="w"), "only")
    check_eq("joined: a line break in an item is folded (precedence: the fold before the cut)", DV.joined(["a\n  b"], noun="x", where="w"), "a b")
    solo = DV.joined(["y" * 100], noun="item", where="w", max_chars=20)
    check_eq("joined: ONE item longer than the ceiling is cut at a character boundary with `…`, and the pointer says so",
             solo, "y" * 19 + "…" + "; (… marks a line cut here — the whole list: w)")
    check_in("joined: first item cut and two more: both counted", "(+2 more item(s) and … marks a line cut here",
             DV.joined(["y" * 100, "b", "c"], noun="item", where="w", max_chars=20))
    try:
        DV.joined(["a"], noun="item")
        refused = False
    except ValueError:
        refused = True
    check_eq("joined: a ceiling with neither `where` nor `full_path` is a ValueError (a site must name the place)", refused, True)
    check_eq("joined: max_chars=None needs no place and shows every item", DV.joined(["a", "b", "c"], noun="x", max_chars=None), "a; b; c")
    check_eq("joined: the separator is a parameter", DV.joined(["a", "b"], noun="x", max_chars=None, sep=", "), "a, b")
    check_eq("joined: the ceiling is a count of CHARACTERS (the parameter is `max_chars`, not `max_bytes`): 5 two-byte letters, 13 characters (18 bytes), fit in 13",
             DV.joined(["é"] * 5, noun="x", where="w", max_chars=13), "; ".join(["é"] * 5))
    try:
        DV.joined(["a"], noun="x", where="w", max_bytes=9)
        old_name = True
    except TypeError:
        old_name = False
    check_eq("joined: the old name `max_bytes` is gone (it counted characters)", old_name, False)
    forged = DV.joined(["ok\n- forged finding\n1) forged item\nREJECT — 9 x\n2 problems - the request is refused whole, every one is listed:"],
                       noun="x", max_chars=None)
    check_eq("joined (adversarial): an item with line breaks never forges a `- `, `N) `, REJECT or head line",
             (len(forged.splitlines()), DV.split_items(forged), DV.parse(1, forged, "")["findings"]), (1, None, []))
    check_eq("joined (adversarial): non-str items are str()-ed, None included", DV.joined([1, None, 2.5], noun="x", max_chars=None), "1; None; 2.5")
    check_eq("joined (documented, not fixed): an item that holds `; ` is joined as it is and splits at `; ` into two parts",
             DV.joined(["a; b", "c"], noun="x", max_chars=None).split("; "), ["a", "b", "c"])


def named_cases() -> None:
    ids = [f"TC_{n:03d}" for n in range(1, 10)]
    check_eq("named: exactly the limit is no tail", DV.named(ids[:6], 6, where="the test plan"), ", ".join(ids[:6]))
    check_eq("named: limit + 1: the tail names the place", DV.named(ids[:7], 6, where="the test plan"),
             ", ".join(ids[:6]) + " and 1 more (the test plan)")
    check_eq("named: empty is the empty text; one id is the id", (DV.named([], 6, where="w"), DV.named(["a"], 6, where="w")), ("", "a"))
    check_eq("named: a repeated id is named once, and the count is of the distinct ones", DV.named(["a", "a", "b"], 1, where="w"), "a and 1 more (w)")
    check_eq("named: the default limit is the twin's (6)", DV.LIST_LIMIT, 6)
    import gate_preflight as GP
    for case in ([], ["a"], ["a", "a", "b"], ids[:6], ids, [3, 1, 3, 2]):
        check_eq(f"named == gate_preflight.named_ids on {len(case)} id(s) (the twin pin, until part B switches the call)",
                 DV.named(case), GP.named_ids(case))
    check_eq("...at another limit too", DV.named(ids, 3), GP.named_ids(ids, 3))
    check_eq("named: `sep` joins the shown ids (the default `, ` is the twin's)", (DV.named(ids[:3], 6, where="w", sep="; "), DV.named(ids[:3])),
             ("TC_001; TC_002; TC_003", "TC_001, TC_002, TC_003"))
    check_eq("named: `sep` with a tail: the tail is not joined, it stays the same sentence",
             DV.named(ids[:7], 6, where="w", sep="; "), "; ".join(ids[:6]) + " and 1 more (w)")


def compound_cases() -> None:
    import controller
    twin = controller.Controller._raise_all

    def raised(messages):
        try:
            twin([(ValueError, m) for m in messages])
        except ValueError as exc:
            return str(exc)
        return ""
    for name, messages in (("none", []), ("one", ["a"]), ("two", ["a", "b"]), ("equal ones folded", ["a", "b", "a", "a"]),
                           ("a multi-line one", ["a\nb\n2) c", "d"]), ("all equal", ["x", "x"])):
        check_eq(f"compound == the controller's _raise_all on {name} (the second builder's detector)", DV.compound(messages), raised(messages))
    check_eq("compound: the head constant is the one COMPOUND_HEAD_RE reads",
             DV.COMPOUND_HEAD_RE.match(DV.COMPOUND_HEAD.format(n=2)) is not None, True)
    text = DV.compound(["first", "second"], prefix="T-1:")
    check_eq("compound: with a prefix the head stands FIRST on a line and split_items reads both items",
             (text.splitlines()[:2], DV.split_items(text)), (["T-1:", DV.COMPOUND_HEAD.format(n=2)], ["first", "second"]))
    check_eq("compound: ONE message with a prefix is `<prefix> <message>`, the sentence as before", DV.compound(["m"], prefix="T-1:"), "T-1: m")


def m2_m4_cases() -> None:
    """m2: a LABELLED producer's stray uncounted REJECT is a defect; m4: one builder of the unmigrated sentence."""
    labelled = "REJECT — 1 finding(s) " + DV.WORDS_AT_SOURCE + ":\n- a\nREJECT: no count here"
    v = DV.parse(1, labelled, "")
    check_eq("m2: a labelled output with a stray REJECT: no finding invented, one defect that names the line",
             (v["findings"], v["defects"], bool(v["unmigrated"])), ([], ["the line 3 'REJECT: no count here' has no count"], True))
    v = DV.parse(1, "REJECT — 1 finding(s):\n- a\nREJECT: no count here", "")
    check_eq("m2 (positive control): the same output UNLABELLED: no defect, unmigrated as before", (v["defects"], bool(v["unmigrated"])), ([], True))
    check_eq("m4: the unmigrated sentence of a reader with no records and of the gate (with its exit) come from one builder",
             (DV.flatten(DV.parse(1, "free", ""))[0], DV.unmigrated_text("free", 1)),
             ("unmigrated detector output (it is not in the one-line-per-finding form, so it is shown whole): free",
              "unmigrated detector output (exit 1; it is not in the one-line-per-finding form, so it is shown whole): free"))
    reason = DV.parse(1, "", "")["unreadable"]
    check_eq("m4: the reason of a refusal that printed nothing ends with the one constant", (reason, reason.endswith(DV.PRINTED_NOTHING)),
             ("exit 1, printed nothing", True))


# --- the contract of the six producers --------------------------------------------------------------------------

PRODUCERS = ("sizing.py", "planning_contract.py", "critic_rollcall.py", "s5_precheck.py", "check_coverage.py", "check_witness.py",
             "grounding_table.py", "claim_projector.py", "branch_accounting.py", "stage_joints.py")


def leading_literal(node):
    """`(the first Constant of the expression, the node right after it)` for a str, an f-string or a `+` chain."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, None
    if isinstance(node, ast.JoinedStr):
        values = node.values
        if values and isinstance(values[0], ast.Constant):
            return values[0].value, (values[1] if len(values) > 1 else None)
        return "", None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return leading_literal(node.left)
    return "", None


def static_findings(source: str) -> list:
    """The contract's violations in the REJECT prints of one source: [(line, what)]."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print" and node.args):
            continue
        text, after = leading_literal(node.args[0])
        if not text.startswith("REJECT"):
            continue
        if any(kw.arg == "file" for kw in node.keywords):
            bad.append((node.lineno, "a REJECT print with file=: the verdict is on stdout"))
        rest = text[len("REJECT — "):] if text.startswith("REJECT — ") else None
        if rest is None:
            bad.append((node.lineno, "a REJECT print that does not start with `REJECT — `"))
        elif not ((rest == "" and isinstance(after, ast.FormattedValue)) or rest[:1].isdigit()):
            bad.append((node.lineno, "a REJECT header with no count"))
    return bad


def contract_static() -> None:
    for name in PRODUCERS:
        found = static_findings((SCRIPTS / name).read_text(encoding="utf-8"))
        check_eq(f"static: {name} has no REJECT print against the contract", found, [])
    check_eq("static: the checker sees a print to stderr", len(static_findings('print("REJECT — 1 x", file=sys.stderr)')), 1)
    check_eq("static: ...a header with a value after the dash passes statically, whatever the value is (the plan name is "
             "told from a count only by the RUN, below)", static_findings('print(f"REJECT — {plan.name} is bad")'), [])
    check_eq("static: ...an old `REJECT: ` header", len(static_findings('print("REJECT: x")')), 1)
    check_eq("static: ...a header joined with `+` that has a count passes, one that has none does not",
             (static_findings('print("REJECT — 2 x" + y)'), len(static_findings('print("REJECT — " + y)'))), ([], 1))
    check_eq("static: ...a counted f-string passes", static_findings('print(f"REJECT — {len(e)} x")'), [])


def run_checks(label: str, script: str, *args, cwd=None, env=None, code: int = 1) -> dict:
    done = run_script(script, *args, cwd=cwd, env=env)
    heads = [line for line in done.stdout.splitlines() if line.startswith("REJECT")]
    check_eq(f"run: {label} exits {code}", done.returncode, code)
    check(f"run: {label}: every REJECT line is `REJECT — <n>`, and there is none on stderr",
          bool(heads) and all(re.match(r"^REJECT — \d+", line) for line in heads) and "REJECT" not in done.stderr,
          done.stdout[:300] + done.stderr[:200])
    verdict = DV.parse(done.returncode, done.stdout, done.stderr)
    declared = sum(int(re.match(r"^REJECT — (\d+)", line).group(1)) for line in heads)
    check_eq(f"run: {label}: parse reads as many findings as the headers declare, none unmigrated, no defect",
             (len(verdict["findings"]), verdict["unmigrated"], verdict["defects"]), (declared, "", []))
    return {"verdict": verdict, "out": done.stdout}


def contract_run() -> None:
    import test_words_doors as WD
    for label, script, make in (("critic_rollcall", "critic_rollcall.py", WD.critic_story),
                                ("planning_contract", "planning_contract.py", WD.plan_story),
                                ("s5_precheck", "s5_precheck.py", WD.s5_story)):
        root = temp_project("qa-verdict-")
        try:
            WD.use_project(root)
            make(root)
            ran = run_checks(label, script, cwd=root, env=WD.project_env(root))
            if script == "s5_precheck.py":
                v = ran["verdict"]
                causes = [line.rsplit(" ", 1)[1] for line in ran["out"].splitlines()
                          if line.startswith(DV.WORDS_REFUSED_AT_SOURCE)]
                check("run: s5_precheck: the header carries the label, every refusal line has family or predating",
                      v["words"] == "source" and all(c in DV.REFUSAL_CAUSES for c in causes), str(causes))
            else:
                check_not_in(f"run: {label}: no refusal line (it judges no words at its source)", DV.WORDS_REFUSED_AT_SOURCE,
                             ran["out"])
                check_eq(f"run: {label}: the gate judges its words", ran["verdict"]["words"], "gate")
        finally:
            cleanup(root)
    root = temp_project("qa-verdict-plan-")
    try:
        WD.use_project(root)
        task = WD.story_with(root, "QA-1", {"S3": {"status": "running"}})
        (task / "work").mkdir()
        (task / "work" / "test-plan.json").write_text("{not json", encoding="utf-8")
        run_checks("planning_contract on a plan that is not JSON", "planning_contract.py", cwd=root, env=WD.project_env(root))
    finally:
        cleanup(root)
    root = temp_project("qa-verdict-cov-")
    try:
        case = root / "qa-factory" / "artifacts" / "T-1" / "test-cases" / "area-a" / "TC-1.md"
        case.parent.mkdir(parents=True)
        case.write_text("---\nid: TC-1\narea: area-a\nstatus: Draft\nupdated: 2026-01-01\n---\nbody\n", encoding="utf-8")
        run_checks("check_coverage with no map", "check_coverage.py", "--root", root, cwd=root)
        run_script("check_coverage.py", "--root", root, "--write", cwd=root)
        for rel in ("records", "state"):
            mp = root / "qa-factory" / rel / "coverage-map.md"
            if mp.exists():
                mp.write_text(mp.read_text(encoding="utf-8").replace("| Cases created | 1 |", "| Cases created | 9 |"),
                              encoding="utf-8")
        run_checks("check_coverage with a diverged map", "check_coverage.py", "--root", root, cwd=root)
    finally:
        cleanup(root)
    with tempfile.TemporaryDirectory() as tmp:
        review = Path(tmp) / "code-review.md"
        review.write_text("nothing here\n", encoding="utf-8")
        two = run_checks("check_witness with 2 errors", "check_witness.py", review)
        check_eq("run: check_witness: the 2 errors are 2 findings", len(two["verdict"]["findings"]), 2)
        run_checks("check_witness on a path that does not exist", "check_witness.py", Path(tmp) / "absent.json")
        broken = Path(tmp) / "automation-manifest.json"
        broken.write_text("{not json", encoding="utf-8")
        run_checks("check_witness on broken JSON", "check_witness.py", broken)
    done = run_script("sizing.py")
    check_eq("run: sizing without arguments never refuses (exit 0): no findings to read", done.returncode, 0)


def one_of_cases() -> None:
    """t-1355 N2 (S-5, AR-15): the ONE closed-list renderer. A set is printed sorted, a tuple in its own order, an empty
    list says it is empty (an empty closed list accepts nothing, and never prints as a bare "one of ")."""
    check_eq("one_of: a set is printed sorted", DV.one_of({"ui", "api", "cli"}), "api, cli, ui")
    check_eq("one_of: a frozenset is printed sorted too", DV.one_of(frozenset({"b", "a"})), "a, b")
    check_eq("one_of: a tuple keeps its own order", DV.one_of(("low", "normal", "critical")), "low, normal, critical")
    check_eq("one_of: a list keeps its own order", DV.one_of(["z", "a"]), "z, a")
    check_eq("one_of: an empty list says the list is empty", DV.one_of([]), "(none: the list is empty)")
    check_eq("one_of: an empty set says so too", DV.one_of(set()), "(none: the list is empty)")
    check_eq("one_of: a non-string item is JSON", DV.one_of([1, None, "a"]), "1, null, a")
    check_eq("one_of: a mixed set sorts by text, never raises", DV.one_of({2, "a", 1}), "1, 2, a")


def unreadable_cases() -> None:
    """RH1-5: the third state of the contract (K4, E4-E8, E22, section 7 of the spec)."""
    check_eq("the line a producer prints", DV.unreadable_line("boom\nsecond"), "UNREADABLE: boom second")
    v = DV.parse(3, DV.unreadable_line("running_story raised OSError"), "")
    check_eq("exit 3 with the marker: the reason, no finding", (v["unreadable"], v["findings"]),
             ("running_story raised OSError", []))
    check_eq("exit 3 with nothing printed", DV.parse(3, "", "")["unreadable"], "exit 3, no reason printed")
    v = DV.parse(3, block(2), "")
    check_eq("exit 3 with a REJECT block: unreadable, the findings are not read", (v["unreadable"], v["findings"]),
             ("exit 3, no reason printed", []))
    for code in (2, 4, 9, 127):
        v = DV.parse(code, "", "Traceback x\nBoom")
        check_eq(f"exit {code}: outside the contract, the stderr tail", (v["unreadable"], v["findings"]),
                 (f"exit {code}, outside the detector contract: Traceback x; Boom", []))
    check_eq("E22: exit 2, empty stdout, a refusal in stderr", DV.parse(2, "", "<refusal>")["unreadable"],
             "exit 2, outside the detector contract: <refusal>")
    check_eq("exit 2 with nothing printed", DV.parse(2, "", "")["unreadable"], "exit 2, outside the detector contract")
    check_eq("E6: exit 1, empty stdout, no head, a stderr (an import crash)", DV.parse(1, "", "ImportError: x")["unreadable"],
             "exit 1, no verdict printed: ImportError: x")
    check_eq("E6: whitespace stdout is empty", DV.parse(1, " \n\r\n", "")["unreadable"], "exit 1, printed nothing")
    v = DV.parse(1, "", "noise\n" + block(2))
    check_eq("E6 control: the head only in stderr: findings, nothing unreadable", (len(v["findings"]), v["unreadable"]), (2, ""))
    check_eq("E4: a block with a wrong count stays unmigrated, not unreadable", (bool(DV.parse(1, "REJECT — 2 f\n- a\n- b\n- c", "")["unmigrated"]),
             DV.parse(1, "REJECT — 2 f\n- a\n- b\n- c", "")["unreadable"]), (True, ""))
    check_eq("E4: free stdout at exit 1 stays unmigrated", (bool(DV.parse(1, "free", "")["unmigrated"]), DV.parse(1, "free", "")["unreadable"]),
             (True, ""))
    check_eq("E8: exit 0 with the marker at the start of a line is unreadable", DV.parse(0, "ok\nUNREADABLE: late", "")["unreadable"], "late")
    check_eq("E8: a BOM before the marker", DV.parse(0, "﻿UNREADABLE: bom", "")["unreadable"], "bom")
    check_eq("E8: the word not at the start of a line is no marker (FR-12)", DV.parse(0, "an UNREADABLE: x\nnote UNREADABLE", "")["unreadable"], "")
    check_eq("E8: CRLF lines", DV.parse(0, "a\r\nUNREADABLE: crlf\r\n", "")["unreadable"], "crlf")
    check_eq("exit 0 clean: nothing unreadable", DV.parse(0, "fine", "")["unreadable"], "")
    check_in("flatten says it, never empty", "unreadable: exit 1, printed nothing", DV.flatten(DV.parse(1, "", ""))[0])
    check_eq("E25: the cause `unreadable` of a refused line is not the new state",
             (DV.parse(1, "WORDS_REFUSED_AT_SOURCE: x\nfree", "")["unreadable"], DV.UNREADABLE, DV.EXIT_UNREADABLE), ("", "unreadable", 3))


def main() -> None:
    unreadable_cases()
    one_of_cases()
    parse_cases()
    tag_cases()
    record_cases()
    refusal_cases()
    render_cases()
    joined_cases()
    named_cases()
    compound_cases()
    m2_m4_cases()
    contract_static()
    contract_run()
    finish("test_detector_verdict")


if __name__ == "__main__":
    main()
