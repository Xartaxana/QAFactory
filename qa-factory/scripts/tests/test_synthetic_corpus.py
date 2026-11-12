"""test_synthetic_corpus.py - the synthetic tracker corpus is a fixed point (node GM2-7 of the move; spec t-1855-gm2-7).

Run from the package root: python -B scripts/tests/test_synthetic_corpus.py

`fixtures/investigation-14857/` (a story folder of a real run) and `fixtures/sizing-14857/` are SYNTHETIC data of the same shape: same
files, JSON keys, list lengths, counts. This test judges DATA only (hashes, keys, counts, forms), never a role's judgment:
  K1  every `fresh` record of `synthetic-derivations.json` is recomputed by the package's own function and EQUALS the recorded value;
      every `stale` record does NOT equal it; the event chain is read by `EventStore.read` without a refusal
  K2  the four screenshots are rebuilt by `materialize_blobs`: name == sha256 of the bytes, size == the inventory's `size`, a PNG signature
  K3  ASCII only, in every file and every path (a `\\uXXXX` escape of a Cyrillic letter included)
  K4  the counts of the real run, as literals
  K5  no forbidden form (a tracker key other than the synthetic ones, the product, the company, a foreign mail or host, a display name that is
      not `User N`, a user-home path) in a path or in the content - forms copied here, not imported from the scanner (docs/migration/ does not
      travel with the package)
  K6  negative control of K5: a forbidden form planted in a copy is found
  K7  the anchors the reader tests edit still occur as many times as before
  K8  empty stays empty
Mutations (named, not run; the batch canon decides): a stale hash recomputed as fresh -> K1; `User N` replaced by `devN` in a display name -> K5;
a blob one byte shorter -> K2; a protected word replaced -> K7.
"""
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
import harness  # noqa: E402
from harness import check, check_eq, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import event_store  # noqa: E402
import source_inventory  # noqa: E402
import synthetic_corpus as SYN  # noqa: E402

FIX = harness.FIXTURES
INV = FIX / "investigation-14857"
SIZ = FIX / "sizing-14857"
TASK = INV / "TP1-14857"
ROOTS = (INV, SIZ)
DERIV = SYN.derivations()

# the anchors the reader tests edit (test_investigation.py): (file, literal, how many times it occurs over the files matched)
ANCHORS = (
    ("work/handoffs/S6-qa-runner-1.yaml", "\n# Rows blocked by the stand", 1),
    ("work/handoffs/S6-qa-runner-1.yaml", "not observed: same stand setting as TC-007", 1),
    ("work/handoffs/S6-qa-runner-1.yaml", "    evidence: work/evidence/manual/TC-009/a1/001-request-response.json\n", 2),
    ("work/handoffs/S6-qa-runner-1.yaml", "    evidence: work/evidence/manual/TC-006/a1/005-request-response.json\n", 1),
    ("work/handoffs/S6-qa-runner-3.yaml", "evidence: work/evidence/manual/TC-010/a1/017-request-response.json", 2),
    ("state/case-versions/TC-007/*.md", "R-15", 6),
    ("state/case-versions/TC-007/*.md", '"source": "unknown", "ref": "Q2"', 1),
    ("state/case-versions/TC-008/*.md", "R-13", 6),
    ("state/case-versions/TC-008/*.md", '"source": "unknown", "ref": "Q3"', 1),
)
KEYS_OK = ("TP1", "TP2", "TP3", "TC", "DEMO", "OB", "TS", "CR", "SC", "FR")    # the synthetic tracker prefixes and the factory's own ids
HOSTS_OK = {"localhost", "127.0.0.1", "example.invalid", "example.org", "invalid.example", "git.example", "github.com", "www.apache.org"}
FORBIDDEN = {                                                          # composed, so this file is no hit of its own
    "company": re.compile("(?i)" + "ep" + "am"),
    "product": re.compile("(?i)" + "code-?" + "mie"),
    "client": re.compile("(?i)" + "ema" + "kina"),
    "tracker key": re.compile(r"\b(?!(?:%s)-)[A-Z][A-Z0-9]{1,9}-[0-9]{2,6}\b" % "|".join(KEYS_OK)),
    "key shape": re.compile("(?i)" + "ep" + "m[a-z]*[-_][0-9a-z]+"),
    "user path": re.compile(r"[A-Za-z]:[\\/]{1,4}(?:Users|AI)[\\/]"),
}
MAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
HOST = re.compile(r"(?i)(?:https?|wss?|ftps?)://([a-z0-9][a-z0-9.-]*)")
NAME = re.compile(r'"displayName"\s*:\s*"([^"]*)"')


def files(roots=ROOTS):
    return [(r, p) for r in roots for p in sorted(r.rglob("*")) if p.is_file()]


def locate(rel):
    for root in ROOTS:
        if (root / rel).is_file():
            return root / rel
    raise FileNotFoundError(rel)


def node(doc, pointer):
    for key in pointer:
        doc = doc[key]
    return doc


def forbidden(items):
    """[(what, where)] over (relative path, text) pairs."""
    out = []
    for rel, text in items:
        for label, rx in FORBIDDEN.items():
            for target, name in ((rel, "path"), (text, "content")):
                if rx.search(target):
                    out.append((label, f"{name} of {rel}"))
        for m in MAIL.finditer(text):
            if m.group(1).lower() != "example.invalid" and not text[m.start() - 1:m.start()] == "@":
                out.append(("mail", rel))
        for m in HOST.finditer(text):
            if m.group(1).lower() not in HOSTS_OK:
                out.append(("host", rel))
        for m in NAME.finditer(text):
            if not re.fullmatch(r"User [0-9]+|QA Factory", m.group(1)):
                out.append(("display name", rel))
    return out


def k1_derivations_are_a_fixed_point() -> None:
    bad, n = [], 0
    for rec in DERIV["fresh"]:
        n += 1
        kind, value = rec["kind"], rec["value"]
        if kind == "file_sha256":
            ok = hashlib.sha256(locate(rec["path"]).read_bytes()).hexdigest().startswith(value)
        elif kind == "json_canonical":
            text = locate(rec["path"]).read_text(encoding="utf-8")
            doc = json.loads(text.split("\n")[rec["line"]]) if rec["line"] is not None else json.loads(text)
            ok = event_store.content_hash(node(doc, rec["pointer"])).startswith(value)
        elif kind == "source_id":
            ok = source_inventory.stable_source_id(rec["instance"], rec["canonical_ref"])[4:] == value
        else:
            ok = False
        if not ok:
            bad.append(rec)
    check(f"K1 every one of the {n} fresh records equals the package function's output", n > 100 and not bad, str(bad[:2]))
    stale_bad = [r for r in DERIV["stale"] if hashlib.sha256(locate(r["path"]).read_bytes()).hexdigest() == r["value"]]
    check(f"K1 every one of the {len(DERIV['stale'])} stale records is NOT the sha256 of the file it names", DERIV["stale"] and not stale_bad,
          str(stale_bad[:2]))
    tmp = temp_dir("qa-synth-chain-")
    try:
        task = tmp / "TP1-14857"
        shutil.copytree(TASK, task)
        events = event_store.EventStore(task).read()
        check_eq("K1 EventStore.read accepts the chain of 103 events", len(events), 103)
        check_eq("K1 the recorded tail is the chain's tail", events[-1]["event_hash"], DERIV["event_chains"][0]["tail"])
    finally:
        cleanup(tmp)


def k2_blobs() -> None:
    tmp = temp_dir("qa-synth-blobs-")
    try:
        written = SYN.materialize_blobs(tmp)
        inventory = json.loads((TASK / "work" / "source-inventory.json").read_text(encoding="utf-8"))
        sizes = {}

        def walk(value):
            if isinstance(value, dict):
                if str(value.get("local_ref") or "").startswith("blobs/"):
                    sizes[value["local_ref"][6:]] = (value.get("content_hash"), value.get("size"))
                for v in value.values():
                    walk(v)
            elif isinstance(value, list):
                for v in value:
                    walk(v)
        walk(inventory)
        check_eq("K2 four blobs are rebuilt", len(written), 4)
        check_eq("K2 the inventory names exactly those four, by name == content_hash", sorted(sizes), written)
        for name in written:
            data = (tmp / "work" / "blobs" / (name + ".png")).read_bytes()
            check(f"K2 {name[:10]}: name == sha256 of the bytes", hashlib.sha256(data).hexdigest() == name)
            check(f"K2 {name[:10]}: size == the inventory's size ({len(data)})", sizes[name][0] == name and sizes[name][1] == len(data))
            check(f"K2 {name[:10]}: a PNG signature", data[:8] == SYN.SIGNATURE)
        check("K2 no blob is committed under the corpus", not list(INV.rglob("*.png")))
        check("K2 a size too small for the frame is refused", _raises(lambda: SYN.synthetic_png(SYN.MIN_SIZE - 1, 1)))
        check("K2 two seeds give two files of one size", SYN.synthetic_png(2000, 1) != SYN.synthetic_png(2000, 2))
        check_eq("K2 the four sizes are the sizes of the real screenshots", sorted(b["size"] for b in DERIV["blobs"]), [8533, 10330, 83997, 93414])
        check_eq("K2 the bytes come from SHA-256 blocks and a fixed IDAT, not from a library generator: a pinned digest",
                 hashlib.sha256(SYN.synthetic_png(2000, 1)).hexdigest(), "fbba1e44fd117bb5c86164e9118de76fdf9eeaa8d39ac55bb137b65ea8656d78")
    finally:
        cleanup(tmp)


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def k3_ascii() -> None:
    bad = []
    for root, path in files():
        data = path.read_bytes()
        rel = path.relative_to(root).as_posix()
        if any(b > 0x7F for b in data) or not rel.isascii() or re.search(rb"\\u04[0-9a-fA-F]{2}", data):
            bad.append(rel)
    check(f"K3 {len(files())} files: ASCII only, no Cyrillic escape", not bad, str(bad[:3]))


def k4_counts() -> None:
    inv = [p for p in TASK.rglob("*") if p.is_file()]
    check_eq("K4 142 text files in the story folder", len(inv), 142)
    check_eq("K4 4 blob records", len(DERIV["blobs"]), 4)
    events = (TASK / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
    check_eq("K4 103 events", len(events), 103)
    check_eq("K4 19 case versions", len(list((TASK / "state" / "case-versions").rglob("*.md"))), 19)
    check_eq("K4 12 cases", len(list((TASK / "state" / "case-versions").iterdir())), 12)
    check_eq("K4 9 run blocks", len(list((TASK / "work" / "run-blocks").glob("*.json"))), 9)
    check_eq("K4 7 manual request.json", len(list((TASK / "work" / "evidence" / "manual").rglob("request.json"))), 7)
    pairs = sorted(p.parent for p in (TASK / "work" / "sources").rglob("raw.json") if (p.parent / "ticket.json").is_file())
    check_eq("K4 10 pairs raw.json + ticket.json", len(pairs), 10)
    names = {m.group(1) for _r, p in files((INV,)) if p.suffix in (".json", ".jsonl") for m in NAME.finditer(p.read_text(encoding="utf-8"))}
    check_eq("K4 14 distinct display names", len(names), 14)
    check_eq("K4 3 files of the sizing story", len([p for p in SIZ.rglob("*") if p.is_file()]), 3)


def k5_no_forbidden_form() -> None:
    items = [(p.relative_to(r).as_posix(), p.read_text(encoding="utf-8")) for r, p in files()]
    hits = forbidden(items)
    check(f"K5 {len(items)} files: no forbidden form in a path or in the content", not hits, str(sorted(set(hits))[:4]))


def k6_negative_control() -> None:
    plant = "ep" + "am"
    clean = [("work/a.md", "a plain sentence\n")]
    check("K6 the clean sample has no hit", not forbidden(clean))
    for text in (f"see {plant}.com", "key " + "EP" + "MCD" + "ME-1", '"displayName": "dev1"', "to a@corp.test", "http://corp.test/x",
                 "C:\\Users\\dev3\\y"):
        check(f"K6 a planted form is found: {text[:12]}", bool(forbidden([("work/a.md", text)])), text)
    check("K6 a planted form in a path is found", bool(forbidden([(f"work/{plant}/a.md", "x")])))


def k7_anchors() -> None:
    for rel, literal, expected in ANCHORS:
        matched = sorted(TASK.glob(rel)) if "*" in rel else [TASK / rel]
        got = sum(p.read_text(encoding="utf-8").count(literal) for p in matched)
        check_eq(f"K7 {rel}: {literal.strip()[:36]!r} occurs {expected} times", got, expected)


def k8_empty_stays_empty() -> None:
    inventory = json.loads((TASK / "work" / "source-inventory.json").read_text(encoding="utf-8"))
    check("K8 an empty list is still an empty list (reads_skipped)", inventory["reads_skipped"] == [])
    check("K8 a null is still null (exclusion_or_error of a read source)",
          any(s["exclusion_or_error"] is None for s in inventory["sources"]))
    attachments = [json.loads(p.read_text(encoding="utf-8")) for p in (TASK / "work" / "sources").rglob("ticket.json")]
    check("K8 empty attachment lists stay empty", any(t["attachments"] == [] for t in attachments))
    check("K8 no zero-byte file was filled", all(p.stat().st_size > 0 for _r, p in files() if p.name != "__init__.py"))


def main() -> None:
    for fn in (k1_derivations_are_a_fixed_point, k2_blobs, k3_ascii, k4_counts, k5_no_forbidden_form, k6_negative_control, k7_anchors,
               k8_empty_stays_empty):
        fn()
    finish("test_synthetic_corpus")


if __name__ == "__main__":
    main()
