"""install_paths.py, the table half: classification, the table's own validation, and the reader
grep (spec t-232 section 2, keys K1/K2-shaped scans, K11, K14-independent; G4, G5/C6).

t-272: a regenerated file this run does not rebuild is retired (scan_tree retire_unbuilt, the table's
`regenerate_step`), a carried file under a regenerated glob never is (precedence), a smoke with no fingerprint is
foreign, an unrecognised folder is opened file by file, locks carry a kind (os / exclusive_create / folder).

Mutations this file kills (each by this file alone):
  retire_unbuilt does nothing | the smoke with no fingerprint stays unknown | the precedence puts regenerated
  before carried | an unrecognised folder kept as one item | a lock row without its kind

Run: python -B scripts/tests/test_install_paths.py
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import check, check_eq, check_in, cleanup, finish, temp_dir  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_paths as I  # noqa: E402

TABLE = I.load_table()
FOLD = False


def put(root: Path, rel: str, text: str = "x") -> Path:
    path = root.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rule(glob: str, cls: str, reader: str = "reader.py", **extra) -> dict:
    return dict({"glob": glob, "class": cls, "reader": reader}, **extra)


def cls_of(rel: str, **kw) -> dict:
    return I.classify(rel, table=TABLE, casefold=FOLD, **kw)


def section_table_rows() -> None:
    rows = {r["glob"]: r for r in TABLE["rules"]}
    check("every row names its reader (a script, a path, or none)", all(isinstance(r.get("reader"), str) and r["reader"] for r in TABLE["rules"]))
    check_eq("the shipped table passes validate_table", I.validate_table()["ok"], True)
    check("the table has no Cyrillic (FR-30)", all(ord(ch) < 0x400 for ch in json.dumps(TABLE, ensure_ascii=False)))
    price = ["host-receipts", "cost", "turns", "activities", "telemetry", "pre-0.7.0-recovery"]
    for name in price:
        c = cls_of(f"qa-factory/state/{name}/some/file.json")
        check(f"G5/C6: price evidence {name}/ is carried and machine-local", (c["class"], c["machine_local"]) == ("carried", True))
    check_eq("G5/C6: cost/.writers is carried too", cls_of("qa-factory/state/cost/.writers/x")["class"], "carried")
    for rel in ("qa-factory/config.json", "qa-factory/factory-backlog.md", "qa-factory/obligations.md",
                "qa-factory/strategy/test-strategy.md", "qa-factory/strategy/project-profile.md",
                "qa-factory/bugs/BUG-1.md", "qa-factory/artifacts/QA-1/work/test-cases/a/TC-001.md",
                "qa-factory/records/journal.jsonl", "qa-factory/records/estimation-ledger.jsonl",
                "qa-factory/records/coverage-map.md", "qa-factory/records/project-decisions.json",
                "qa-factory/records/onboarding-approvals.jsonl", "qa-factory/records/config-migrations/m1.json",
                # the OLD places of the same records (an older factory kept them in state/): still carried, never retired
                "qa-factory/state/journal.jsonl", "qa-factory/state/estimation-ledger.jsonl",
                "qa-factory/state/coverage-map.md", "qa-factory/state/project-decisions.json",
                "qa-factory/state/onboarding-approvals.jsonl", "qa-factory/state/config-migrations/m1.json"):
        c = cls_of(rel)
        check(f"{rel}: carried, not machine-local (committed data)", (c["class"], c["machine_local"]) == ("carried", False))
    check_eq("F8: the retired folder is carried and machine-local (what a reinstall set aside is never retired again)",
             (cls_of("qa-factory/state/retired/2026-10-01/qa-factory/x.md")["class"], cls_of("qa-factory/state/retired/2026-10-01/x.md")["machine_local"]),
             ("carried", True))
    check_eq("F8: readiness.json lives in state/ now (regenerated, machine-local); the old place beside the config is discarded",
             [(cls_of(p)["class"], cls_of(p)["machine_local"]) for p in ("qa-factory/state/readiness.json", "qa-factory/readiness.json")],
             [("regenerated", True), ("discarded", True)])
    for rel in ("qa-factory/state/readiness.json", "qa-factory/state/factory-dashboard.html", "qa-factory/state/dashboard-dirty.json",
                "qa-factory/state/host-probe.json", "qa-factory/state/metrics.json", "qa-factory/state/stand-lease.json",
                "qa-factory/state/scheduler-requests/r1.json", "qa-factory/state/.exit_gate_blocks.json",
                "qa-factory/state/native-context/state/events.lock", "qa-factory/state/.dashboard-writer/state/events.lock",
                "qa-factory/state/.journal-writer/state/events.lock", "qa-factory/state/coverage-map.receipt.json",
                "qa-factory/state/integrations/jira-direct-probe.json"):
        c = cls_of(rel)
        check(f"{rel}: regenerated and machine-local", (c["class"], c["machine_local"]) == ("regenerated", True))
    # O1-1 (t-239, P18): accumulated history is not rebuildable, whatever the wildcard row beside it says
    for rel in ("qa-factory/state/metrics-history.json", "qa-factory/state/metric-signals.json", "qa-factory/state/stand-health.json"):
        c = cls_of(rel)
        check(f"O1-1: {rel} is history: carried and machine-local, never regenerated", (c["class"], c["machine_local"]) == ("carried", True))
    check_eq("O1-1: metrics-history.json wins over the `metrics*.json` row by precedence, and the loser is named",
             (cls_of("qa-factory/state/metrics-history.json")["rule"], cls_of("qa-factory/state/metrics-history.json")["also_matched"]),
             ("qa-factory/state/metrics-history.json", ["qa-factory/state/metrics*.json"]))
    check_eq("O1-1: stand-health.json wins over the `stand-*.json` row, and the loser is named",
             (cls_of("qa-factory/state/stand-health.json")["rule"], cls_of("qa-factory/state/stand-health.json")["also_matched"]),
             ("qa-factory/state/stand-health.json", ["qa-factory/state/stand-*.json"]))
    check_eq("O1-1: metric-signals.json is in ONE class only (a second row would be a class_overlap)",
             sorted(r["class"] for r in TABLE["rules"] if r["glob"] == "qa-factory/state/metric-signals.json"), ["carried"])
    check_eq("O1-1: a path the wildcard rows own stays regenerated (metrics.json, stand-lease.json)",
             (cls_of("qa-factory/state/metrics.json")["class"], cls_of("qa-factory/state/stand-lease.json")["class"]), ("regenerated", "regenerated"))
    check_eq("the install manifest itself is regenerated and NOT machine-local (it is committed)",
             (cls_of(I.MANIFEST_REL)["class"], cls_of(I.MANIFEST_REL)["machine_local"]), ("regenerated", False))
    for rel in ("qa-factory/state/estimation-ledger.lock", "qa-factory/state/stand-lease.lock",
                "qa-factory/state/execution-leases.lock", "qa-factory/state/native-context/state/events.lock",
                "qa-factory/state/.dashboard-writer/state/events.lock", "qa-factory/state/.exit_gate_blocks.json.lock",
                "qa-factory/state/.project-decisions.lock", "qa-factory/state/project-decisions.lock"):
        c = cls_of(rel)
        check(f"locks: {rel} is regenerated and retire_safe false", (c["class"], c["retire_safe"]) == ("regenerated", False))
    # t-272 item 1: a regenerated file that is NOT a lock is safe to retire when this run does not rebuild it (the lease
    # registry and the writer folders used to carry retire_safe false for the lock files inside them: the lock rows own that now)
    for rel in ("qa-factory/state/execution-leases.json", "qa-factory/state/stand-lease.json", "qa-factory/state/native-context/n.json",
                "qa-factory/state/.dashboard-writer/x.json", "qa-factory/state/.journal-writer/x.json"):
        check_eq(f"t-272: {rel} is regenerated and retire_safe (only its lock files are not)", (cls_of(rel)["class"], cls_of(rel)["retire_safe"]), ("regenerated", True))
    check_eq("carried stays retire_safe true (it is protected by precedence, not by the flag)", cls_of("qa-factory/config.json")["retire_safe"], True)
    c = cls_of("qa-factory/state/jira-probe-01a0.json")
    check_eq("no reader found by grep -> discarded, reader none", (c["class"], c["reader"]), ("discarded", "none"))
    c = cls_of("qa-factory/strategy/product-passport.md")
    check_eq("gen 2: product-passport.md is discarded, generation 2, requires a fold receipt",
             (c["class"], c["generation"], c["requires"]), ("discarded", 2, ["fold_receipt"]))
    c = cls_of("docs/superpowers/qa-tasks/2026-09-04-qa-1")
    check_eq("F5: a superpowers qa-tasks directory is not_ours with NO generation (it is the team's dev factory, not an earlier factory)",
             (c["class"], c["generation"], c["reason"]), ("not_ours", None, "the project's dev factory (superpowers)"))
    check_eq("F5: superpowers/reviews is not_ours too, same reason, no generation",
             (cls_of("docs/superpowers/reviews/r1.md")["class"], cls_of("docs/superpowers/reviews/r1.md")["generation"],
              cls_of("docs/superpowers/reviews/r1.md")["reason"]), ("not_ours", None, "the project's dev factory (superpowers)"))
    check("F5: no row of the table calls superpowers a generation or lets it be retired",
          all(r.get("generation") is None and r["class"] == "not_ours" for r in TABLE["rules"] if "superpowers" in r["glob"]))
    # F2 (owner): retire_mode is per class and lives in the data
    check("F2: every discarded row carries retire_mode delete",
          all(r.get("retire_mode") == "delete" for r in TABLE["rules"] if r["class"] == "discarded"))
    check("F2: so does a regenerated row that can turn stale (discard_when)",
          all(r.get("retire_mode") == "delete" for r in TABLE["rules"] if r.get("discard_when")))
    check("F2: no carried row carries any retire_mode (nothing carried is retired)",
          not any("retire_mode" in r for r in TABLE["rules"] if r["class"] == "carried"))
    check("F2: no not_ours row carries one either (never in a retire listing)",
          not any("retire_mode" in r for r in TABLE["rules"] if r["class"] == "not_ours"))
    check_eq("F2: the per-class rule is read from the table's `retire_modes` block",
             {k: I.retire_modes(TABLE)[k] for k in ("discarded", "regenerated_stale", "undetermined", "carried")},
             {"discarded": "delete", "regenerated_stale": "delete", "undetermined": "move", "carried": "none"})
    check_eq("F2: the undetermined kinds and the move target are data too",
             (I.retire_modes(TABLE)["undetermined_kinds"], I.retire_modes(TABLE)["move_target"]),
             (["unrecognised", "changed_since_install", "unknown"], "qa-factory/state/retired/<date>/"))
    check_eq("F2: classify carries the winning row's retire_mode (delete for the passport, None for carried)",
             (cls_of("qa-factory/strategy/product-passport.md")["retire_mode"], cls_of("qa-factory/config.json")["retire_mode"]), ("delete", None))
    check_eq("F2: a carried `retire_mode` in a table is ignored in code: carried is always 'none'",
             I.retire_modes({"retire_modes": {"carried": "delete"}})["carried"], "none")
    check_eq("gen 1: the stray .gitignore line is a table row", [r["line"] for r in I.gitignore_lines(TABLE) if r["generation"] == 1],
             ["qa-factory/artifacts/*/work/evidence/"])
    check_eq("gen 2: the per-file lines of the 22.09 block are table rows too (a reinstall takes them out)",
             [r["line"] for r in I.gitignore_lines(TABLE) if r["generation"] == 2],
             ["qa-factory/state/*", "!qa-factory/state/journal.jsonl", "!qa-factory/state/coverage-map.md", "!qa-factory/state/estimation-ledger.jsonl"])
    check_eq("C7: no readiness-by-version row (readiness.json is regenerated, never compared by version)",
             [g for g in rows if "readiness" in g], ["qa-factory/state/readiness.json", "qa-factory/readiness.json"])
    check_eq("a file the table does not know under qa-factory/ is unrecognised, retire_safe false",
             (cls_of("qa-factory/my-notes.md")["class"], cls_of("qa-factory/my-notes.md")["retire_safe"]), ("unrecognised", False))
    check_eq("a path outside qa-factory the table does not know is unrecognised (not ours)", cls_of("src/app.py")["class"], "unrecognised")
    keys = set(cls_of("qa-factory/config.json"))
    check("FR-14: every classification result has the same keys",
          all(set(cls_of(p)) == keys for p in ("qa-factory/my-notes.md", "../x", "qa-factory/records/journal.jsonl", "docs/superpowers/reviews")))


def section_precedence() -> None:
    def table(rules):
        return {"home": "qa-factory", "rules": rules}
    both = [rule("a/**", "discarded"), rule("a/keep.txt", "carried")]
    for order, rules in (("discarded row first", both), ("carried row first", both[::-1])):
        c = I.classify("a/keep.txt", table=table(rules), casefold=FOLD)
        check_eq(f"G5/C6: carried beats discarded ({order})", c["class"], "carried")
        check_eq(f"G5/C6: ...and the loser is named ({order})", (c["rule"], c["also_matched"]), ("a/keep.txt", ["a/**"]))
        check_eq(f"G5/C6: the other files under a/ stay discarded ({order})", I.classify("a/other.txt", table=table(rules), casefold=FOLD)["class"], "discarded")
    c = I.classify("a/x", table=table([rule("a/**", "regenerated"), rule("a/x", "carried"), rule("a/*", "discarded")]), casefold=FOLD)
    check_eq("carried > regenerated > discarded in one path", (c["class"], c["also_matched"]), ("carried", ["a/**", "a/*"]))
    c = I.classify("a/x", table=table([rule("a/**", "discarded"), rule("a/x", "regenerated")]), casefold=FOLD)
    check_eq("regenerated beats discarded", c["class"], "regenerated")
    c = I.classify("a/x", table=table([rule("a/**", "not_ours"), rule("a/x", "discarded")]), casefold=FOLD)
    check_eq("discarded beats not_ours", c["class"], "discarded")
    c = I.classify("a/x.lock", table=table([rule("a/*.lock", "regenerated", retire_safe=False), rule("a/**", "regenerated")]), casefold=FOLD)
    check_eq("retire_safe is false when ANY matching rule says so (the safe direction)", c["retire_safe"], False)
    c = I.classify("a/x", table=table([rule("a/**", "discarded", retire_safe=False)]), casefold=FOLD)
    check_eq("a discarded row with retire_safe false is not retire_safe", c["retire_safe"], False)


def section_glob_and_path_rules() -> None:
    t = {"home": "h", "rules": [rule("h/s/*.json", "carried"), rule("h/d/**", "carried"), rule("h/f?.md", "carried"),
                                rule("h/x/**/z.txt", "carried")]}
    for rel, want in (("h/s/a.json", "carried"), ("h/s/a.txt", "unrecognised"), ("h/s/sub/a.json", "unrecognised"),
                      ("h/d", "carried"), ("h/d/a/b/c", "carried"), ("h/f1.md", "carried"), ("h/f12.md", "unrecognised"),
                      ("h/x/z.txt", "carried"), ("h/x/a/b/z.txt", "carried"), ("h/x/a/b/y.txt", "unrecognised")):
        check_eq(f"glob: {rel} -> {want}", I.classify(rel, table=t, casefold=FOLD)["class"], want)
    # the Windows rule: backslashes always; case where the platform folds it
    for given in ("qa-factory\\records\\journal.jsonl", ".\\qa-factory//records/journal.jsonl", "qa-factory/records/journal.jsonl/"):
        check_eq(f"backslash/dot/slash spelling {given!r} classifies as the plain path", cls_of(given)["class"], "carried")
        check_eq(f"...and is reported with forward slashes only ({given!r})", cls_of(given)["rel_path"], "qa-factory/records/journal.jsonl")
    mixed = "QA-Factory\\Records\\JOURNAL.jsonl"
    check_eq("Windows rule (casefold on): a mixed-case spelling matches", I.classify(mixed, table=TABLE, casefold=True)["class"], "carried")
    check_eq("case-sensitive platform (casefold off): the same spelling is another path", I.classify(mixed, table=TABLE, casefold=False)["class"], "unrecognised")
    check_eq("casefold on: price evidence in another case is still carried", I.classify("QA-FACTORY/STATE/COST/x.json", table=TABLE, casefold=True)["class"], "carried")
    check_eq("the platform default is the one sys.platform says",
             I._fold_default(), sys.platform == "win32")
    for bad in ("../x", "qa-factory/../../x", "/etc/x", "C:\\x", "\\\\srv\\s", ""):
        c = cls_of(bad)
        check(f"classify refuses {bad!r} (class refused, a reason, never a retire-safe path)", c["class"] == "refused" and c["refused"] and c["retire_safe"] is False)


def tmp_package(files: dict) -> Path:
    root = temp_dir("qa-pkg-")
    for rel, text in files.items():
        put(root, rel, text)
    return root


def codes(result: dict) -> list:
    return sorted(e["code"] for e in result["errors"])


def section_validate() -> None:
    def table(*rules):
        return {"home": "qa-factory", "rules": list(rules)}
    pkg = tmp_package({"scripts/reader.py": "x = 'alpha.json'\n", "scripts/other.py": "pass\n"})
    try:
        ok = I.validate_table(pkg, table(rule("qa-factory/state/alpha.json", "regenerated"), rule("qa-factory/state/beta.json", "discarded", "none")))
        check_eq("a reader that has the key and a `none` that nothing contradicts -> ok", (ok["ok"], codes(ok)), (True, []))
        check_eq("G4: the positive control ran and found its key", (ok["grep"]["control_key"], ok["grep"]["control_found"]), ("alpha.json", True))

        # K11
        over = I.validate_table(pkg, table(rule("qa-factory/x/**", "carried"), rule("qa-factory/x/**", "discarded", "none"),
                                           rule("qa-factory/state/alpha.json", "regenerated")))
        check_eq("K11: the same glob in carried and discarded -> refused", (over["ok"], "class_overlap" in codes(over)), (False, True))
        msg = next((e["message"] for e in over["errors"] if e["code"] == "class_overlap"), "")
        check("K11: ...naming both classes and the glob", all(w in msg for w in ("carried", "discarded", "qa-factory/x/**")))
        over = I.validate_table(pkg, table(rule("QA-Factory/X/**", "carried"), rule("qa-factory/x/**", "regenerated"), rule("qa-factory/state/alpha.json", "regenerated")))
        check("K11: glob text that differs only by case is the same glob", "class_overlap" in codes(over))
        for a, b in (("carried", "regenerated"), ("regenerated", "discarded"), ("discarded", "not_ours")):
            r = I.validate_table(pkg, table(rule("qa-factory/y", a), rule("qa-factory/y", b), rule("qa-factory/state/alpha.json", "regenerated")))
            check(f"two classes ({a}, {b}) on one glob are refused", "class_overlap" in codes(r))
        dup = I.validate_table(pkg, table(rule("qa-factory/y", "carried"), rule("qa-factory/y", "carried"), rule("qa-factory/state/alpha.json", "regenerated")))
        check_eq("the same glob twice in ONE class is a duplicate, not an overlap", ("duplicate_glob" in codes(dup), "class_overlap" in codes(dup)), (True, False))
        sibling = I.validate_table(pkg, table(rule("qa-factory/x/**", "carried"), rule("qa-factory/x/y.txt", "discarded", "reader.py", key="alpha.json"),
                                              rule("qa-factory/state/alpha.json", "regenerated")))
        check_eq("overlapping but DIFFERENT glob texts are legal (precedence resolves them)", sibling["ok"], True)

        # G4 reader grep
        pkg2 = tmp_package({"scripts/reader.py": "x = 'alpha.json'\n", "skills/s/SKILL.md": "mentions Beta.JSON here\n",
                            "scripts/tests/test_x.py": "gamma.json\n", "references/install-paths.json": "{\"delta.json\": 1}\n",
                            "scripts/install_paths.py": "epsilon.json\n"})
        try:
            alpha = rule("qa-factory/state/alpha.json", "regenerated")
            r = I.validate_table(pkg2, table(alpha, rule("qa-factory/state/beta.json", "discarded", "none")))
            check_eq("G4: a `none` whose key appears in package text (other letter case) is refused", (r["ok"], codes(r)), (False, ["reader_contradicted"]))
            check_in("G4: ...naming the file that contradicts it", "skills/s/SKILL.md", r["errors"][0]["message"])
            r = I.validate_table(pkg2, table(alpha, rule("qa-factory/state/BETA.JSON", "discarded", "none")))
            check("G4: the grep is case-insensitive in both directions", "reader_contradicted" in codes(r))
            for name in ("gamma.json", "delta.json", "epsilon.json"):
                r = I.validate_table(pkg2, table(alpha, rule(f"qa-factory/state/{name}", "discarded", "none")))
                check(f"G4: a mention in tests / this table / this module is not a reader ({name})", r["ok"])
            r = I.validate_table(pkg2, table(alpha, rule("qa-factory/state/nothing-here.json", "discarded", "none")))
            check("G4: a `none` that nothing contradicts passes", r["ok"])
            # O1-2: only a DISCARDED row can be wrongly retired; a carried / not_ours row with reader none is never retired
            for cls in ("carried", "not_ours"):
                r = I.validate_table(pkg2, table(alpha, rule("qa-factory/state/beta.json", cls, "none")))
                check_eq(f"O1-2: a {cls} `none` row whose key appears in package text is accepted without the contradiction grep",
                         (r["ok"], codes(r)), (True, []))
            r = I.validate_table(pkg2, table(alpha, rule("qa-factory/state/beta.json", "carried", "none"), rule("qa-factory/state/other/Beta.json", "discarded", "none")))
            check_eq("O1-2: ...while a discarded `none` row beside it is still refused", codes(r), ["reader_contradicted"])
            r = I.validate_table(pkg2, table(alpha, rule("qa-factory/state/beta.json", "carried", "none")))
            check_eq("O1-2: the positive control still ran for a carried `none` row", (r["grep"]["control_key"], r["grep"]["control_found"]), ("alpha.json", True))
            r = I.validate_table(pkg2, table(rule("qa-factory/state/beta.json", "carried", "none")))
            check("O1-2: ...and a table with no control at all is still refused, carried rows or not", "grep_control_failed" in codes(r))
            r = I.validate_table(pkg2, table(alpha, rule("qa-factory/state/*.zzz", "discarded", "none", key=".json")))
            check("G4: an explicit `key` is what is grepped", "reader_contradicted" in codes(r))
            r = I.validate_table(pkg2, table(rule("qa-factory/state/zeta.json", "regenerated", "reader.py")))
            check_eq("a declared reader that lacks the key is refused", codes(r), ["reader_key_absent"])
            r = I.validate_table(pkg2, table(alpha, rule("qa-factory/state/alpha.json2", "regenerated", "no_such.py")))
            check("a reader script that is not in the package is refused", "reader_missing" in codes(r))
            r = I.validate_table(pkg2, table(rule("qa-factory/state/s.json", "regenerated", "skills/s/SKILL.md", key="beta.json")))
            check_eq("a reader may be a package-relative path (a role's phase text)", r["ok"], True)
            # the control: a grep that cannot see what exists proves nothing about `none`
            r = I.validate_table(pkg2, table(rule("qa-factory/state/epsilon.json", "regenerated", "install_paths.py"),
                                             rule("qa-factory/state/beta.json", "discarded", "none")))
            check("G4 control: the only reader sits where the grep does not look -> control fails, every `none` is unverifiable",
                  "grep_control_failed" in codes(r) and r["ok"] is False and r["grep"]["control_found"] is False)
            r = I.validate_table(pkg2, table(rule("qa-factory/state/beta.json", "discarded", "none")))
            check("G4 control: a table of `none` rows only has no control at all -> refused, not trusted", "grep_control_failed" in codes(r))
        finally:
            cleanup(pkg2)
        empty = temp_dir("qa-pkg-empty-")
        try:
            r = I.validate_table(empty, table(alpha, rule("qa-factory/state/beta.json", "discarded", "none")))
            check("G4 control: a MISCALLED package root (nothing there) cannot pass a `none` row",
                  r["ok"] is False and "grep_control_failed" in codes(r) and "reader_missing" in codes(r))
        finally:
            cleanup(empty)

        # shape
        for what, bad in (("class", rule("qa-factory/a", "keeper")), ("absolute glob", rule("/a", "carried")), ("drive glob", rule("C:/a", "carried")),
                          ("dotdot glob", rule("a/../b", "carried")), ("backslash glob", rule("a\\b", "carried")),
                          ("no reader", {"glob": "a", "class": "carried"}), ("flag type", rule("a", "carried", machine_local="yes")),
                          ("requires type", rule("a", "carried", requires="fold")), ("condition", rule("a", "carried", discard_when={"json_field": 1})),
                          ("retire_mode word", rule("a", "discarded", "none", retire_mode="burn")),
                          ("retire_mode on a carried row", rule("a", "carried", retire_mode="delete")),
                          ("reason type", rule("a", "not_ours", "none", reason=5))):
            check(f"shape: a rule with a bad {what} is refused", "shape" in codes(I.validate_table(pkg, table(bad, alpha))))
        check("shape: no rules list at all is refused", I.validate_table(pkg, {"home": "x"})["ok"] is False)
    finally:
        cleanup(pkg)


def case_b_tree(root: Path) -> dict:
    files = {}
    for rel, text in {
        ".gitignore": "node_modules/\n.env\nqa-factory/artifacts/*/work/evidence/\n",
        "qa-factory/config.json": "{}\n", "qa-factory/obligations.md": "o\n", "qa-factory/factory-backlog.md": "b\n",
        "qa-factory/strategy/test-strategy.md": "t\n", "qa-factory/strategy/project-profile.md": "p\n",
        "qa-factory/strategy/aspect-profile.md": "a\n", "qa-factory/strategy/faq.md": "f\n", "qa-factory/strategy/framework-rules.md": "r\n",
        "qa-factory/strategy/product-passport.md": "passport\n",
        "qa-factory/bugs/BUG-1.md": "bug\n", "qa-factory/artifacts/QA-1/work/test-cases/a/TC-001.md": "tc\n",
        "qa-factory/state/journal.jsonl": "{}\n", "qa-factory/state/estimation-ledger.jsonl": "{}\n", "qa-factory/state/coverage-map.md": "m\n",
        "qa-factory/state/project-decisions.json": "{}\n", "qa-factory/readiness.json": "{\"plugin_root\": \"C:\\\\x\"}\n",
        "qa-factory/state/host-receipts/1.json": "{}\n", "qa-factory/state/host-receipts/2.json": "{}\n", "qa-factory/state/host-receipts/3.json": "{}\n",
        "qa-factory/state/turns/t1.json": "{}\n", "qa-factory/state/doctor-install-smoke-old.json": json.dumps({"package_fingerprint": "OLD"}),
        "qa-factory/state/doctor-install-smoke-new.json": json.dumps({"package_fingerprint": "NEW"}),
        "qa-factory/state/estimation-ledger.lock": "", "qa-factory/state/pre-0.7.0-recovery/metrics.json": "{}\n",
        "qa-factory/my-notes.md": "mine\n", "docs/superpowers/qa-tasks/2026-09-04-qa-1/cases.json": "{}\n",
        "src/app.py": "print()\n",
    }.items():
        files[rel] = put(root, rel, text)
    return files


def tree_state(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): (sha(p) if p.is_file() else None) for p in sorted(root.rglob("*"))}


def section_scan() -> None:
    root = temp_dir("qa-scan-")
    try:
        files = case_b_tree(root)
        ctx = {"package_fingerprint": "NEW"}
        before = tree_state(root)
        scan = I.scan_tree(root, context=ctx, table=TABLE, casefold=FOLD)
        check_eq("FR-45: scan_tree writes nothing (every path and byte unchanged)", tree_state(root), before)
        check_eq("K1 shape: the retire list is the old readiness report, the foreign doctor smoke and the passport; NOT pre-0.7.0-recovery (C6)"
                 " and NOT the records still in state/ (they are moved, never retired)",
                 [i["rel_path"] for i in scan["retire"]],
                 ["qa-factory/readiness.json", "qa-factory/state/doctor-install-smoke-old.json", "qa-factory/strategy/product-passport.md"])
        by = {i["rel_path"]: i for i in scan["retire"]}
        check_eq("the passport item carries its fold-receipt requirement and generation",
                 (by["qa-factory/strategy/product-passport.md"]["requires"], by["qa-factory/strategy/product-passport.md"]["generation"]), (["fold_receipt"], 2))
        check_eq("the smoke item carries generation 3 and the verdict 'foreign'",
                 (by["qa-factory/state/doctor-install-smoke-old.json"]["generation"], by["qa-factory/state/doctor-install-smoke-old.json"]["condition"]), (3, "foreign"))
        check_eq("K2 shape: not_ours_kept is the dev-factory directory (no generation, its own reason) and the unknown file",
                 [(i["rel_path"], i["generation"], i["reason"]) for i in scan["not_ours_kept"]],
                 [("docs/superpowers/qa-tasks/2026-09-04-qa-1", None, "the project's dev factory (superpowers)"),
                  ("qa-factory/my-notes.md", None, "unrecognised")])
        check_eq("F2: every retire item carries its mode: delete for the old readiness report, the passport and the foreign smoke",
                 sorted((i["rel_path"], i["retire_mode"]) for i in scan["retire"]),
                 [("qa-factory/readiness.json", "delete"), ("qa-factory/state/doctor-install-smoke-old.json", "delete"),
                  ("qa-factory/strategy/product-passport.md", "delete")])
        check("K2: the sha of a kept file is unchanged and the gen-1 directory still stands",
              sha(files["qa-factory/my-notes.md"]) == before["qa-factory/my-notes.md"] and
              (root / "docs/superpowers/qa-tasks/2026-09-04-qa-1/cases.json").is_file())
        check_eq("a lock is listed as a lock and never in retire", ("qa-factory/state/estimation-ledger.lock" in scan["locks"],
                 any(i["rel_path"].endswith(".lock") for i in scan["retire"])), (True, False))
        carried = [r for r in files if I.classify(r, table=TABLE, casefold=FOLD)["class"] == "carried"]
        check("invariant: no CARRIED path is in retire", not set(carried) & {i["rel_path"] for i in scan["retire"]})
        check_eq("the current-fingerprint smoke is kept and not even listed", "qa-factory/state/doctor-install-smoke-new.json" in
                 [i["rel_path"] for i in scan["retire"] + scan["unknown"]], False)
        check("nothing under src/ is looked at or listed (outside the factory's home and the table)",
              not any(i["rel_path"].startswith("src/") for i in scan["not_ours_kept"] + scan["retire"]))
        check_eq("no manifest in this tree: status absent, nothing blocked", (scan["manifest"]["status"], scan["retire_blocked"]), ("absent", None))
        scan2 = I.scan_tree(root, ["qa-factory/strategy/product-passport.md"], context=ctx, table=TABLE, casefold=FOLD)
        check("a path this run writes is never retired, whatever the table says",
              "qa-factory/strategy/product-passport.md" not in [i["rel_path"] for i in scan2["retire"]])
        scan3 = I.scan_tree(root, table=TABLE, casefold=FOLD)
        check_eq("FR-41: with no installed fingerprint given the smokes are UNKNOWN and kept, not retired",
                 (sorted(i["rel_path"] for i in scan3["unknown"]), [i["rel_path"] for i in scan3["retire"] if "smoke" in i["rel_path"]]),
                 (["qa-factory/state/doctor-install-smoke-new.json", "qa-factory/state/doctor-install-smoke-old.json"], []))
        (root / "qa-factory/state/doctor-install-smoke-old.json").write_text("{ not json", encoding="utf-8")
        scan4 = I.scan_tree(root, context=ctx, table=TABLE, casefold=FOLD)
        check("FR-41: an unreadable smoke report is unknown, not foreign (kept)",
              "qa-factory/state/doctor-install-smoke-old.json" in [i["rel_path"] for i in scan4["unknown"]]
              and "qa-factory/state/doctor-install-smoke-old.json" not in [i["rel_path"] for i in scan4["retire"]])
        c = I.classify("qa-factory/state/doctor-install-smoke-new.json", table=TABLE, casefold=FOLD, root=root, context=ctx)
        check_eq("classify with root and context: a matching fingerprint stays regenerated", (c["class"], c["condition"]), ("regenerated", "current"))
        c = I.classify("qa-factory/state/doctor-install-smoke-new.json", table=TABLE, casefold=FOLD)
        check_eq("classify without them: regenerated, condition unknown (never discarded blind)", (c["class"], c["condition"]), ("regenerated", "unknown"))
        # a second reinstall-shaped scan with the old things gone (K8 shape: retire is empty)
        (root / "qa-factory/state/doctor-install-smoke-old.json").unlink()
        (root / "qa-factory/strategy/product-passport.md").unlink()
        (root / "qa-factory/readiness.json").unlink()
        scan5 = I.scan_tree(root, context=ctx, table=TABLE, casefold=FOLD)
        check_eq("after the retirements, a second scan offers nothing to retire", scan5["retire"], [])
    finally:
        cleanup(root)


def section_class_mutations_visible() -> None:
    """The shapes the mutations in the DoD change, asserted from the outside."""
    root = temp_dir("qa-scan-prec-")
    try:
        put(root, "qa-factory/keep.md", "k\n")
        put(root, "qa-factory/state/x.json", "{}\n")
        t = {"home": "qa-factory", "rules": [rule("qa-factory/**", "discarded", "none", key="zzz-nothing"),
                                             rule("qa-factory/keep.md", "carried", "reader.py", key="x"),
                                             rule("qa-factory/state/x.json", "regenerated", "reader.py", key="x")]}
        scan = I.scan_tree(root, table=t, casefold=FOLD)
        check_eq("a broad discarded row cannot retire a path a narrower carried row claims",
                 [i["rel_path"] for i in scan["retire"]], [])
    finally:
        cleanup(root)


def section_layout() -> None:
    """t-232 F7+F8: the table says which class lives in which folder, derives the ignore block and the
    moves, and refuses a row that would hide a record from git or commit a machine-local file."""
    import copy
    check_eq("F7: the table names the two class folders: records tracked, state ignored",
             [(f["path"], f["tracked"]) for f in I.folders(TABLE)], [("qa-factory/records", True), ("qa-factory/state", False)])
    check_eq("F7: the block is derived: the generated files inside the artifacts, then one line per untracked folder",
             I.gitignore_block(TABLE), ["qa-factory/artifacts/*/work/evidence/", "qa-factory/artifacts/*/evidence/",
                                        "qa-factory/artifacts/*/work/*fragment*.json",
                                        "qa-factory/artifacts/*/work/impl-diff*.txt", "qa-factory/state/"])
    moves = I.moves(TABLE)
    check_eq("F8: the table carries six old_path -> new_path rows: five files and one folder (the tracker-write receipt is a probe cache and stays in state/)",
             sorted((m["from"], m["to"], m["kind"]) for m in moves),
             sorted([("qa-factory/state/journal.jsonl", "qa-factory/records/journal.jsonl", "file"),
                     ("qa-factory/state/estimation-ledger.jsonl", "qa-factory/records/estimation-ledger.jsonl", "file"),
                     ("qa-factory/state/coverage-map.md", "qa-factory/records/coverage-map.md", "file"),
                     ("qa-factory/state/project-decisions.json", "qa-factory/records/project-decisions.json", "file"),
                     ("qa-factory/state/onboarding-approvals.jsonl", "qa-factory/records/onboarding-approvals.jsonl", "file"),
                     ("qa-factory/state/config-migrations", "qa-factory/records/config-migrations", "dir")]))
    check("F8: every move lands on a carried, non-machine-local row inside records/ and leaves a carried row inside state/",
          all(cls_of(m["to"])["class"] == "carried" and not cls_of(m["to"])["machine_local"] and m["to"].startswith("qa-factory/records/")
              and cls_of(m["from"])["class"] == "carried" and m["from"].startswith("qa-factory/state/") for m in moves))
    check("F7: nothing carried and not machine-local is left in state/ except the old places of the moved records",
          all(r["class"] != "carried" or r.get("machine_local") or "moved_to" in r or not r["glob"].startswith("qa-factory/state/") for r in TABLE["rules"]))

    def mutated(change) -> dict:
        t = copy.deepcopy(TABLE)
        change(t)
        return I.validate_table(table=t)
    r1 = mutated(lambda t: t["rules"].append({"glob": "qa-factory/state/new-record.json", "class": "carried", "reader": "log_append.py", "key": "journal"}))
    check_eq("F7: a carried record in the ignored folder (no moved_to) is refused: git would never see it",
             ("folder_mismatch" in codes(r1), r1["ok"]), (True, False))
    check("F7: ...and the message names the folder and the two ways out",
          any("qa-factory/state" in e["message"] and "machine_local" in e["message"] for e in r1["errors"] if e["code"] == "folder_mismatch"))
    r2 = mutated(lambda t: t["rules"].append({"glob": "qa-factory/records/cache.json", "class": "regenerated", "machine_local": True,
                                              "reader": "log_append.py", "key": "journal"}))
    check_eq("F7: a machine-local row in the tracked folder is refused: it would be committed", ("folder_mismatch" in codes(r2), r2["ok"]), (True, False))
    r3 = mutated(lambda t: [r.update({"moved_to": "qa-factory/records/not-a-row.jsonl"}) for r in t["rules"] if r["glob"] == "qa-factory/state/journal.jsonl"])
    check_eq("F8: a moved_to that is not a row of the table is refused", ("folder_mismatch" in codes(r3), r3["ok"]), (True, False))
    r4 = mutated(lambda t: [r.update({"moved_to": "qa-factory/records/journal.jsonl"}) for r in t["rules"] if r["glob"] == "qa-factory/state/jira-probe-*.json"])
    check_eq("F8: moved_to on a row that is not carried is refused (nothing else is moved by a reinstall)", ("shape" in codes(r4), r4["ok"]), (True, False))
    r5 = mutated(lambda t: [r.update({"moved_to": "qa-factory/records/config-migrations"}) for r in t["rules"]
                            if r["glob"] == "qa-factory/state/config-migrations/**"])
    check_eq("F8: a folder row must move to a folder row (`dir/**` to `dir/**`)", ("shape" in codes(r5), r5["ok"]), (True, False))
    r6 = mutated(lambda t: t.update({"folders": [{"path": "qa-factory/records"}]}))
    check_eq("F7: a folder entry without `tracked` is a shape error", ("shape" in codes(r6), r6["ok"]), (True, False))
    check_eq("F7: a table with no folders block derives no folder line (and refuses nothing about folders)",
             (I.gitignore_block({"rules": []}), I.moves({"rules": []})), ([], []))


REGENERATED_UNBUILT = [
    "qa-factory/state/host-probe.json", "qa-factory/state/integrations/jira-direct-probe.json", "qa-factory/state/stand-lease.json",
    "qa-factory/state/execution-leases.json",
    "qa-factory/state/.exit_gate_blocks.json", "qa-factory/state/coverage-map.receipt.json",
    "qa-factory/state/scheduler-requests/r.json", "qa-factory/state/native-context/n.json",
    "qa-factory/state/bug-snapshot.json", "qa-factory/state/project-decisions-refresh-stale.json",
    "qa-factory/state/reporter-rehearsals.json", "qa-factory/state/benefit-inputs.json", "qa-factory/state/budget/TP3-1.json",
]
REBUILT = ["qa-factory/state/readiness.json", "qa-factory/state/factory-dashboard.html", "qa-factory/state/metrics.json",
           "qa-factory/state/integrations/tracker-write.json"]
CARRIED_UNDER_REGENERATED_GLOBS = ["qa-factory/state/stand-health.json", "qa-factory/state/metrics-history.json", "qa-factory/state/metric-signals.json"]
# t-298 (K-A3): rewritten by a running session's hooks on every call: regenerated and unbuilt, yet never a retire item
HOOK_WRITTEN = ["qa-factory/state/dashboard-dirty.json", "qa-factory/state/dashboard-refresh.json", "qa-factory/state/.dashboard-writer/x.json"]


def section_regenerated_not_rebuilt() -> None:
    """t-272 item 1: a REGENERATED file that this run's regenerate step does not rebuild is retired (listed by name,
    delete), a rebuilt one and a carried one never are, and a smoke with no fingerprint is foreign."""
    root = temp_dir("qa-scan-regen-")
    try:
        for rel in REGENERATED_UNBUILT + REBUILT + CARRIED_UNDER_REGENERATED_GLOBS + HOOK_WRITTEN:
            put(root, rel, f"data of {rel}\n")
        put(root, "qa-factory/state/doctor-install-smoke-nofp.json", json.dumps({"status": "passed"}))
        put(root, "qa-factory/state/doctor-install-smoke-new.json", json.dumps({"package_fingerprint": "NEW"}))
        put(root, "qa-factory/state/doctor-install-smoke-bad.json", "{ not json")
        put(root, "qa-factory/state/.dashboard-writer/state/events.lock", "0")
        put(root, "qa-factory/state/.journal-writer/state/events.lock", "0")
        ctx = {"package_fingerprint": "NEW"}
        outputs = I.regenerate_outputs(TABLE)
        check_eq("the table's regenerate_step names the files the install's scripts rebuild (read from data, not from a list in code)",
                 sorted(set(REBUILT) - set(outputs)), [])
        before = tree_state(root)
        scan = I.scan_tree(root, outputs, context=ctx, table=TABLE, casefold=FOLD, retire_unbuilt=True)
        check_eq("FR-45: the scan writes nothing", tree_state(root), before)
        check_eq("item 1: the retire list is EXACTLY the regenerated files this run does not rebuild + the smoke with no fingerprint (named, mode delete)",
                 sorted((i["rel_path"], i["retire_mode"]) for i in scan["retire"]),
                 sorted([(p, "delete") for p in REGENERATED_UNBUILT] + [("qa-factory/state/doctor-install-smoke-nofp.json", "delete")]))
        check_eq("K-A3 (t-298): the retire list holds NONE of the hook-written files (the two state files and the writer folder's file), "
                 "though each is regenerated and not rebuilt by this run; the writer's lock is still reported in `locks`",
                 ([p for p in HOOK_WRITTEN if p in {i["rel_path"] for i in scan["retire"]}],
                  "qa-factory/state/.dashboard-writer/state/events.lock" in scan["locks"]), ([], True))
        check_eq("item 1: a doctor smoke WITHOUT package_fingerprint is foreign (not unknown), an unreadable one is still unknown (kept), the current one is kept",
                 ([i["condition"] for i in scan["retire"] if "nofp" in i["rel_path"]], [u["rel_path"] for u in scan["unknown"]]),
                 (["foreign"], ["qa-factory/state/doctor-install-smoke-bad.json"]))
        check_eq("item 1: every REBUILT output stays (it is in `written`)", [p for p in REBUILT if p in {i["rel_path"] for i in scan["retire"]}], [])
        check_eq("item 1 INVARIANT (precedence carried > regenerated): a carried file under a regenerated glob (stand-health.json under `stand-*.json`, "
                 "metrics-history.json under `metrics*.json`) is never in retire", [p for p in CARRIED_UNDER_REGENERATED_GLOBS if p in {i["rel_path"] for i in scan["retire"]}], [])
        check_eq("item 6: the lock files inside the writer folders are locks, not retire items (the folders' other files are)",
                 sorted(l for l in scan["locks"] if "writer" in l),
                 ["qa-factory/state/.dashboard-writer/state/events.lock", "qa-factory/state/.journal-writer/state/events.lock"])
        old = I.scan_tree(root, outputs, context=ctx, table=TABLE, casefold=FOLD)
        check_eq("a caller that does not say what it rebuilds (retire_unbuilt off, the default) keeps the older rule: only the foreign smoke",
                 [i["rel_path"] for i in old["retire"]], ["qa-factory/state/doctor-install-smoke-nofp.json"])
        again = I.scan_tree(root, outputs + REGENERATED_UNBUILT, context=ctx, table=TABLE, casefold=FOLD, retire_unbuilt=True)
        check_eq("a path in `written` is never retired, whatever the table says", [i["rel_path"] for i in again["retire"]], ["qa-factory/state/doctor-install-smoke-nofp.json"])
        # a carried file placed under a regenerated GLOB (not a literal row): precedence holds for a table of its own too
        t = {"home": "qa-factory", "rules": [rule("qa-factory/state/x/**", "regenerated", "r.py"), rule("qa-factory/state/x/keep.json", "carried", "r.py")]}
        put(root, "qa-factory/state/x/keep.json", "{}\n")
        put(root, "qa-factory/state/x/gone.json", "{}\n")
        scan = I.scan_tree(root, table=t, casefold=FOLD, retire_unbuilt=True)
        check_eq("precedence on a table of its own: the regenerated folder's other file is retired, the carried one stays",
                 [i["rel_path"] for i in scan["retire"]], ["qa-factory/state/x/gone.json"])
    finally:
        cleanup(root)


def section_undetermined_and_locks() -> None:
    """t-272 items 2 and 6 as scan_tree reports them: an unrecognised FOLDER is opened and each file is its own item; the
    lock kinds come from the table."""
    root = temp_dir("qa-scan-undet-")
    try:
        for rel in ("qa-factory/my-notes.md", "qa-factory/folder/deep/a.txt", "qa-factory/folder/b.txt", "qa-factory/state/mystery.bin",
                    "docs/superpowers/qa-tasks/x/cases.json", "src/app.py", "qa-factory/loose.lock"):
            put(root, rel, "x\n")
        (root / "qa-factory/empty-folder").mkdir()
        (root / "qa-factory/state/.project-decisions.lock").mkdir(parents=True)
        (root / "qa-factory/odd.lock").mkdir()
        put(root, "qa-factory/odd.lock/inner.txt", "must not be opened or listed")
        scan = I.scan_tree(root, I.regenerate_outputs(TABLE), table=TABLE, casefold=FOLD, retire_unbuilt=True)
        check_eq("item 2: the unrecognised items are FILES (a folder is opened, each file below is one item; an empty folder is no item)",
                 [(i["rel_path"], i["reason"]) for i in scan["not_ours_kept"]],
                 [("docs/superpowers/qa-tasks/x", "the project's dev factory (superpowers)"), ("qa-factory/folder/b.txt", "unrecognised"),
                  ("qa-factory/folder/deep/a.txt", "unrecognised"), ("qa-factory/my-notes.md", "unrecognised"),
                  ("qa-factory/state/mystery.bin", "unrecognised")])
        check_eq("item 6: a folder lock (table row) and a lock folder or file nobody named are LOCKS (never opened, never an unrecognised item)",
                 scan["locks"], ["qa-factory/loose.lock", "qa-factory/odd.lock", "qa-factory/state/.project-decisions.lock"])
        check("nothing outside qa-factory/ and the table is looked at (src/)", not any(i["rel_path"].startswith("src/") for i in scan["not_ours_kept"]))
    finally:
        cleanup(root)
    kinds = {"qa-factory/state/.exit_gate_blocks.json.lock": "os", "qa-factory/state/.project-decisions.lock": "folder",
             "qa-factory/state/project-decisions.lock": "os",
             "qa-factory/state/estimation-ledger.lock": "os", "qa-factory/state/stand-lease.lock": "os",
             "qa-factory/state/cost/.writers/s1/state/events.lock": "os", "qa-factory/state/.dashboard-writer/state/events.lock": "os",
             "qa-factory/state/config.json": None, "qa-factory/config.json": None}
    check_eq("item 6: lock_kind comes from the table's rows: the specific rows (exit_gate's and project_decisions' files, the old mkdir folder) before the generic `os` row",
             {rel: cls_of(rel)["lock_kind"] for rel in kinds}, kinds)
    check_eq("item 6: a lock under a CARRIED row stays carried (never removable) and keeps its kind",
             (cls_of("qa-factory/state/cost/.writers/s1/state/events.lock")["class"], cls_of("qa-factory/state/cost/.writers/s1/state/events.lock")["retire_safe"]),
             ("carried", False))
    check_eq("class rows (Q7): regenerated machine-local, retire_safe",
             [(cls_of(f"qa-factory/state/{n}")["class"], cls_of(f"qa-factory/state/{n}")["machine_local"], cls_of(f"qa-factory/state/{n}")["retire_safe"])
              for n in ("bug-snapshot.json", "project-decisions-refresh-stale.json", "reporter-rehearsals.json", "benefit-inputs.json", "budget/TP3-1.json")],
             [("regenerated", True, True)] * 5)
    check_eq("class rows (Q7): carried machine-local evidence (transactions of a decision write, the denied dispatches)",
             [(cls_of(f"qa-factory/state/{n}")["class"], cls_of(f"qa-factory/state/{n}")["machine_local"]) for n in ("decision-transactions/t1.json", "dispatch-denials.jsonl")],
             [("carried", True)] * 2)


def section_new_table_shapes() -> None:
    import copy

    def mutated(change) -> dict:
        t = copy.deepcopy(TABLE)
        change(t)
        return I.validate_table(table=t)
    r = mutated(lambda t: t["rules"].append({"glob": "qa-factory/state/x.lock", "class": "regenerated", "reader": "event_store.py", "key": ".lock", "lock_kind": "os"}))
    check_eq("a lock row that is not retire_safe false is refused: a lock is never in a retire list", ("shape" in codes(r), r["ok"]), (True, False))
    r = mutated(lambda t: t["rules"].append({"glob": "qa-factory/state/y.lock", "class": "regenerated", "reader": "event_store.py", "key": ".lock",
                                             "retire_safe": False, "lock_kind": "advisory"}))
    check_eq("an unknown lock_kind is refused", ("shape" in codes(r), r["ok"]), (True, False))
    r = mutated(lambda t: t["regenerate_step"].append({"script": "readiness.py", "outputs": ["qa-factory/state/never-heard-of.json"]}))
    check_eq("an output the table does not know is refused: a reinstall could not tell what rebuilds it", ("regenerate_output_unrowed" in codes(r), r["ok"]), (True, False))
    r = mutated(lambda t: t["regenerate_step"].append({"script": "readiness.py", "outputs": ["qa-factory/strategy/product-passport.md"]}))
    check("an output that is DISCARDED (the table retires it) is refused", "regenerate_output_unrowed" in codes(r), str(r["errors"]))
    r = mutated(lambda t: t["regenerate_step"].append({"script": "no_such_script.py", "outputs": []}))
    check("a regenerate script that is not in the package is refused", "regenerate_script_missing" in codes(r), str(r["errors"]))
    r = mutated(lambda t: t["regenerate_step"].append({"script": "readiness.py", "outputs": ["qa-factory/state/*.json"]}))
    check("an output must be a literal path, not a glob", "shape" in codes(r), str(r["errors"]))
    r = mutated(lambda t: t.update({"regenerate_step": "readiness.py"}))
    check("regenerate_step that is not a list is a shape error", "shape" in codes(r))
    check_eq("a table with no regenerate_step names no outputs (so a caller keeps nothing by it)", I.regenerate_outputs({"rules": []}), [])
    check_eq("regenerate_outputs narrows to the scripts this run runs", I.regenerate_outputs(TABLE, ["check_coverage.py"]), [])


HOOK_TRUE = ["qa-factory/state/dashboard-dirty.json", "qa-factory/state/dashboard-refresh.json",
             "qa-factory/state/.dashboard-writer/x.json", "qa-factory/state/.dashboard-writer/state/events.lock",
             # t-363 B6: the journal writer's folder and the events lock are hook-written too (hooklib writes both from the hooks)
             "qa-factory/state/.journal-writer/x.json", "qa-factory/state/.journal-writer/state/events.lock",
             "qa-factory/state/events.lock",
             # HF8-15 (1b), F-9: the conductor wake's fuse is rewritten by a running session's Stop hook
             "qa-factory/state/conductor-stop.json"]
# the near misses: each must stay NOT hook_written (a false positive hides a leftover; the allowed error is the other way)
HOOK_FALSE = ["qa-factory/state/dashboard-dirty.json.old", "qa-factory/state/sub/dashboard-dirty.json",
              "qa-factory/state/.dashboard-writer-old/x.json",
              "qa-factory/state/stand-lease.json", "qa-factory/state/host-probe.json", "qa-factory/state/.exit_gate_blocks.json",
              "qa-factory/state/events.lock.old", "qa-factory/state/sub/events.lock", "qa-factory/state/.journal-writer-old/x.json",
              "qa-factory/state/metrics-history.json", "qa-factory/state/stand-health.json", "qa-factory/state/jira-probe-x.json",
              "qa-factory/../qa-factory/state/dashboard-dirty.json", "qa-factory/config.json", "qa-factory/state/cost/.writers/s1/state/events.lock"]


def section_hook_written() -> None:
    """t-298 K-A1/K-A2: `classify` as a GATE (it keeps a file out of the sha recheck): True for exactly the flagged rows and
    the lock below the flagged folder, False for every near miss; the table refuses every shape that could make the flag add."""
    import copy
    check_eq("K-A1: classify says hook_written for the two state files, the dashboard and journal writers' files and locks, and the events lock",
             {rel: cls_of(rel)["hook_written"] for rel in HOOK_TRUE}, {rel: True for rel in HOOK_TRUE})
    check_eq("F-9: the wake's fuse file is a recognised row (regenerated, not `unrecognised`), not a retire candidate",
             (cls_of("qa-factory/state/conductor-stop.json")["class"], cls_of("qa-factory/state/conductor-stop.json")["rule"]),
             ("regenerated", "qa-factory/state/conductor-stop.json"))
    check_eq("K-A1: ...and the lock's WINNING row is the generic lock row (the flag comes from the folder row that also matched)",
             (cls_of(HOOK_TRUE[3])["rule"], cls_of(HOOK_TRUE[3])["also_matched"]),
             ("qa-factory/state/**/*.lock", ["qa-factory/state/.dashboard-writer/**"]))
    check_eq("K-A1 (E(a), adversarial): every near miss - suffix, deeper path, prefix sibling, other state files, the other writer, carried and "
             "discarded rows, a `..` spelling, a carried lock - is NOT hook_written",
             {rel: cls_of(rel)["hook_written"] for rel in HOOK_FALSE}, {rel: False for rel in HOOK_FALSE})
    check_eq("K-A1: a case variant folds like every classify (True with fold, False without: the other path on a case-sensitive disk)",
             (I.classify("QA-Factory/State/Dashboard-Dirty.json", table=TABLE, casefold=True)["hook_written"],
              I.classify("QA-Factory/State/Dashboard-Dirty.json", table=TABLE, casefold=False)["hook_written"]), (True, False))
    check_eq("FR-14: classify's key set gains exactly `hook_written` (and, B-411, `before_install`)",
             sorted(cls_of("qa-factory/config.json")), sorted(["rel_path", "class", "machine_local", "retire_safe", "reader", "generation", "requires",
                                                              "rule", "also_matched", "condition", "refused", "retire_mode", "reason", "lock_kind", "hook_written",
                                                              "before_install"]))
    check_eq("K-A1: hook-written rows (data, FR-13), each regenerated: the dashboard writer, the journal writer, the events lock "
             "- t-298 + t-363 B6 (the dirty and refresh files are the dashboard writer's two state files)",
             sorted((r["glob"], r["class"]) for r in TABLE["rules"] if r.get("hook_written")),
             sorted([("qa-factory/state/dashboard-dirty.json", "regenerated"), ("qa-factory/state/dashboard-refresh.json", "regenerated"),
                     ("qa-factory/state/.dashboard-writer/**", "regenerated"), ("qa-factory/state/.journal-writer/**", "regenerated"),
                     ("qa-factory/state/events.lock", "regenerated"), ("qa-factory/state/.exit_gate_blocks.json.lock", "regenerated"),
                     ("qa-factory/state/conductor-stop.json", "regenerated"),
                     ("qa-factory/state/project-decisions.lock", "regenerated")]))
    t = {"home": "qa-factory", "rules": [rule("a/**", "regenerated", hook_written=True), rule("a/keep.txt", "carried")]}
    check_eq("E(a): a path that is hook-written AND carried is carried: the flag never reaches it (precedence)",
             (I.classify("a/keep.txt", table=t, casefold=FOLD)["class"], I.classify("a/keep.txt", table=t, casefold=FOLD)["hook_written"]), ("carried", False))
    t = {"home": "qa-factory", "rules": [rule("a/**", "regenerated", hook_written="yes")]}
    check_eq("E(a): a flag that is not a real `true` means NO (the safe direction)", I.classify("a/x", table=t, casefold=FOLD)["hook_written"], False)

    def mutated(change) -> dict:
        t2 = copy.deepcopy(TABLE)
        change(t2)
        return I.validate_table(table=t2)

    def flag(glob, **extra):
        return lambda t2: [r.update(dict({"hook_written": True}, **extra)) for r in t2["rules"] if r["glob"] == glob]
    check_eq("K-A2: the shipped table validates", I.validate_table()["ok"], True)
    for what, change in (("a non-bool flag", lambda t2: [r.update({"hook_written": "yes"}) for r in t2["rules"]
                                                         if r["glob"] == "qa-factory/state/dashboard-dirty.json"]),
                         ("the flag on a carried row", flag("qa-factory/config.json")),
                         ("the flag on a discarded row", flag("qa-factory/state/jira-probe-*.json")),
                         ("the flag on a not_ours row", flag("docs/superpowers/reviews/**")),
                         ("the flag together with retire_mode", flag("qa-factory/state/dashboard-dirty.json", retire_mode="delete")),
                         ("the flag together with discard_when", flag("qa-factory/state/dashboard-dirty.json", discard_when={"json_field": "f", "differs_from": "package_fingerprint"})),
                         ("the flag on a regenerate_step output", flag("qa-factory/state/factory-dashboard.html"))):
        r = mutated(change)
        check_eq(f"K-A2: {what} gives exactly one `shape` error", (r["ok"], codes(r)), (False, ["shape"]))
    r = mutated(lambda t2: [s["outputs"].append("qa-factory/state/.dashboard-writer/out.json") for s in t2["regenerate_step"] if s["script"] == "readiness.py"])
    check_eq("K-A2: the flag on a GLOB that covers a regenerate_step output (a broader row than the output itself) is one `shape` error too",
             (r["ok"], codes(r)), (False, ["shape"]))
    check_eq("K-A2: a flag with `false` is harmless and valid on any class (it adds nothing)",
             mutated(lambda t2: [r.update({"hook_written": False}) for r in t2["rules"] if r["glob"] == "qa-factory/config.json"])["ok"], True)


def section_before_install() -> None:
    """B-411 I3: `before_install` marks the onboarding run's own notes, which exist BEFORE any install: `classify` returns the key
    (true only when the WINNING row carries it), and the table refuses every shape that could make the flag hide a real trace of
    an install. The flag only takes away install evidence, so it may err only toward False."""
    import copy
    notes_row = "qa-factory/state/onboarding/**"
    check_eq("I3: the shipped table passes validate_table with the new rows", I.validate_table()["ok"], True)
    rows = {r["glob"]: r for r in TABLE["rules"]}
    check_eq("I3: the notes row is carried, machine-local, read by onboarding_notes.py, and flagged",
             (rows[notes_row]["class"], rows[notes_row]["machine_local"], rows[notes_row]["reader"], rows[notes_row]["before_install"]),
             ("carried", True, "onboarding_notes.py", True))
    check_eq("F7: the words row is carried, machine-local, read by person_words.py, and NOT flagged (a recorded decision is not pre-install)",
             (rows["qa-factory/state/words/**"]["class"], rows["qa-factory/state/words/**"]["machine_local"], rows["qa-factory/state/words/**"]["reader"],
              "before_install" in rows["qa-factory/state/words/**"]), ("carried", True, "person_words.py", False))
    for rel in ("qa-factory/state/onboarding/progress.yaml", "qa-factory/state/onboarding/.gitignore", "qa-factory/state/onboarding/words/batch-b1-1.txt",
                "qa-factory/state/onboarding/retired/2026-10-06/progress.yaml", "qa-factory/state/onboarding/done/ref_1/interview.yaml"):
        c = cls_of(rel)
        check_eq(f"I3: classify returns before_install true for {rel} (carried, never retired)", (c["before_install"], c["class"]), (True, "carried"))
    for rel in ("qa-factory/state/jira-probe-01a0.json", "qa-factory/state/words/x.txt", "qa-factory/state/retired/2026-10-06/x",
                "qa-factory/state/onboarding-approvals.jsonl", "qa-factory/state/readiness.json", "qa-factory/config.json", "docs/superpowers/x.md"):
        check_eq(f"I3: classify returns before_install false for {rel}", cls_of(rel)["before_install"], False)
    # only the WINNING row's flag counts: a carried flagged row loses nothing to a regenerated twin, and a flagged row cannot win by itself
    t = {"home": "qa-factory", "rules": [rule("a/**", "carried", before_install=True), rule("a/x.txt", "regenerated")]}
    check_eq("I3: a flagged carried row that also matches a regenerated one still wins (precedence): flag true", I.classify("a/x.txt", table=t, casefold=FOLD)["before_install"], True)
    t = {"home": "qa-factory", "rules": [rule("a/**", "regenerated", before_install=True)]}
    check_eq("I3: a flag on a regenerated row is never read (the safe direction: False)", I.classify("a/x", table=t, casefold=FOLD)["before_install"], False)
    for bad in ("true", 1, "yes", None):
        t = {"home": "qa-factory", "rules": [rule("a/**", "carried", before_install=bad)]}
        check_eq(f"I3: a value that is not a real bool ({bad!r}) means NO", I.classify("a/x", table=t, casefold=FOLD)["before_install"], False)

    def mutated(change) -> dict:
        t2 = copy.deepcopy(TABLE)
        change(t2)
        return I.validate_table(table=t2)

    def row(glob):
        return lambda t2, **extra: [r.update(extra) for r in t2["rules"] if r["glob"] == glob]
    r = mutated(lambda t2: row(notes_row)(t2, before_install="yes"))
    check_eq("I3: a flag that is not a bool is one `shape` error", (r["ok"], codes(r)), (False, ["shape"]))
    r = mutated(lambda t2: row("qa-factory/state/readiness.json")(t2, before_install=True))
    check_eq("I3: the flag on a regenerated row is one `shape` error", (r["ok"], codes(r)), (False, ["shape"]))
    r = mutated(lambda t2: row("qa-factory/state/jira-probe-*.json")(t2, before_install=True))
    check_eq("I3: the flag on a discarded row is one `shape` error", (r["ok"], codes(r)), (False, ["shape"]))
    r = mutated(lambda t2: row("qa-factory/state/words/**")(t2, before_install=True))
    check_eq("I3 control: the flag on another carried row that overlaps nothing is valid", r["ok"], True)

    def add_row(glob, cls="carried"):
        return lambda t2: t2["rules"].append({"glob": glob, "class": cls, "machine_local": True, "reader": "onboarding_notes.py", "key": "onboarding"})
    for other in ("qa-factory/state/onboarding/**", "qa-factory/state/**", "qa-factory/state/onboarding/progress.yaml", "qa-factory/state/onboarding/*.yaml"):
        r = mutated(add_row(other))
        check("I3: a flagged glob that overlaps another row's glob (%s) is refused" % other, not r["ok"] and "shape" in codes(r), str(r["errors"])[:300])
    check("I3: ...naming the overlap", any("overlap" in e["message"] for e in mutated(add_row("qa-factory/state/**"))["errors"]))
    r = mutated(add_row("qa-factory/state/pre-install-other/**"))
    check_eq("I3 control: a disjoint row is fine next to the flagged one", r["ok"], True)
    # the flag changes nothing in retirement: a scan of a tree holding only the notes retires nothing and lists nothing unknown
    root = temp_dir("qa-ip-notes-")
    try:
        put(root, "qa-factory/state/onboarding/progress.yaml")
        put(root, "qa-factory/state/onboarding/words/batch-b1-1.txt")
        put(root, "qa-factory/state/onboarding/retired/2026-10-06/progress.yaml")
        put(root, "qa-factory/state/words/topic-20261006-100000.txt")
        scan = I.scan_tree(root, [], manifest="auto", table=TABLE)
        check_eq("I3: scan_tree retires and flags nothing for the notes (carried, never retired)",
                 (scan["retire"], scan["unknown"], scan["refused"]), ([], [], []))
    finally:
        cleanup(root)


def section_environment_record() -> None:
    """B-414 R11 (E1): the environment record is a CARRIED record of the project (a person's words are in it), read by
    `environment_record.py`; a reinstall never retires it. The negative control: without the row it is unrecognised."""
    record = "qa-factory/records/environment-properties.json"
    c = cls_of(record)
    check_eq("B-414: the environment record is carried, not machine-local, its reader is environment_record.py",
             (c["class"], c["machine_local"], c["reader"]), ("carried", False, "environment_record.py"))
    root = temp_dir("qa-scan-envrec-")
    try:
        put(root, record, "{}\n")
        scan = I.scan_tree(root, context={"package_fingerprint": "NEW"}, table=TABLE, casefold=FOLD)
        check_eq("B-414 E1: scan_tree with the record in the tree: it is in none of the lists a reinstall sets aside",
                 record in [i["rel_path"] for i in scan["retire"] + scan["unknown"] + scan["not_ours_kept"]], False)
        without = {"home": TABLE["home"], "rules": [r for r in TABLE["rules"] if r["glob"] != record]}
        check_eq("B-414 NEGATIVE CONTROL: without the row the record is unrecognised (a person's words would be moved to retired/)",
                 I.classify(record, table=without, casefold=FOLD)["class"], "unrecognised")
    finally:
        cleanup(root)


def section_report_adaptations() -> None:
    """B-416 N5/N2: the helper's record is CARRIED (a conductor's words about a command are in it; a reinstall never retires it), and the
    kept unread report is REGENERATED machine-local state (the next unread run replaces it). Each has a negative control."""
    record = "qa-factory/records/report-adaptations.json"
    kept = ["qa-factory/state/reporter-unread/web/manifest.json", "qa-factory/state/reporter-unread/web/files/report.trx"]
    c = cls_of(record)
    check_eq("B-416: the helper's record is carried, not machine-local, its reader is report_adapt.py",
             (c["class"], c["machine_local"], c["reader"]), ("carried", False, "report_adapt.py"))
    for rel in kept:
        c = cls_of(rel)
        check_eq(f"B-416: {rel} is regenerated and machine-local, its reader is report_adapt.py", (c["class"], c["machine_local"], c["reader"]),
                 ("regenerated", True, "report_adapt.py"))
    root = temp_dir("qa-scan-adapt-")
    try:
        put(root, record, "{}\n")
        for rel in kept:
            put(root, rel, "x")
        scan = I.scan_tree(root, context={"package_fingerprint": "NEW"}, table=TABLE, casefold=FOLD)
        listed = [i["rel_path"] for i in scan["unknown"] + scan["not_ours_kept"]]
        check_eq("B-416: scan_tree: the record and the kept report are recognised (in neither the unknown nor the kept-unrecognised list)",
                 [p for p in [record, *kept] if p in listed], [])
        check_eq("B-416: the record is never in the retire list", record in [i["rel_path"] for i in scan["retire"]], False)
        for rel, label in ((record, "the record"), (kept[0], "the kept manifest")):
            without = {"home": TABLE["home"], "rules": [r for r in TABLE["rules"] if not (r["glob"] == rel or (r["glob"].endswith("**") and rel.startswith(r["glob"][:-2])))]}
            check_eq(f"B-416 NEGATIVE CONTROL: without its row {label} is unrecognised", I.classify(rel, table=without, casefold=FOLD)["class"], "unrecognised")
    finally:
        cleanup(root)


def section_stand_identity() -> None:
    """K28 (t-300): the stand registry is a CARRIED record of the project (the person's words are in it), and the lock of
    its writer is a regenerated machine-local file the `stand-*.json` row of the stand lease must never claim."""
    registry = "qa-factory/records/stand-identity.json"
    c = cls_of(registry)
    check_eq("K28: the registry is carried, not machine-local, its reader is stand_identity.py",
             (c["class"], c["machine_local"], c["reader"]), ("carried", False, "stand_identity.py"))
    lock = "qa-factory/state/.stand-identity-writer/state/events.lock"
    c = cls_of(lock)
    check_eq("K28: the writer lock is regenerated and machine-local", (c["class"], c["machine_local"]), ("regenerated", True))
    check_eq("K28: and it is a lock: never put in a retire list by classification", c["retire_safe"], False)
    check_eq("K28: the writer folder's other files are regenerated, machine-local and retire_safe (only the lock file is not)",
             (cls_of("qa-factory/state/.stand-identity-writer/x.json")["class"], cls_of("qa-factory/state/.stand-identity-writer/x.json")["retire_safe"]),
             ("regenerated", True))
    check_eq("K28: the table passes validate_table with the two rows", I.validate_table()["ok"], True)
    root = temp_dir("qa-scan-stand-")
    try:
        put(root, registry, "{}\n")
        put(root, lock, "0")
        scan = I.scan_tree(root, context={"package_fingerprint": "NEW"}, table=TABLE, casefold=FOLD)
        listed = [i["rel_path"] for i in scan["retire"] + scan["unknown"] + scan["not_ours_kept"]]
        check_eq("K28: scan_tree with the registry in the tree: it is in neither the retire, the unknown nor the kept-unrecognised list",
                 registry in listed, False)
        check_eq("K28: the writer's lock is in none of the retire, unknown and kept-unrecognised lists either",
                 lock in listed or ".stand-identity-writer" in " ".join(listed), False)
        without = {"home": TABLE["home"], "rules": [r for r in TABLE["rules"] if r["glob"] != registry]}
        c = I.classify(registry, table=without, casefold=FOLD)
        check_eq("K28 NEGATIVE CONTROL: without the row the registry is unrecognised (it would be moved to retired/ on a reinstall)",
                 c["class"], "unrecognised")
        scan = I.scan_tree(root, table=without, casefold=FOLD)
        check_eq("K28 NEGATIVE CONTROL: and the scan then lists it among the files it would set aside",
                 registry in [i["rel_path"] for i in scan["unknown"] + scan["not_ours_kept"] + scan["retire"]], True)
    finally:
        cleanup(root)


def main() -> None:
    section_stand_identity()
    section_environment_record()
    section_report_adaptations()
    section_table_rows()
    section_precedence()
    section_glob_and_path_rules()
    section_validate()
    section_scan()
    section_class_mutations_visible()
    section_layout()
    section_regenerated_not_rebuilt()
    section_undetermined_and_locks()
    section_new_table_shapes()
    section_hook_written()
    section_before_install()
    finish("install paths")


if __name__ == "__main__":
    main()
