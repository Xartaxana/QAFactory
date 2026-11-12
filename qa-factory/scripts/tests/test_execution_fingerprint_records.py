"""execution_fingerprint reads a `{path, sha256}` record where a path is expected (EP1-8, hotfix port HF1-2).

`fingerprint_files` is a list of records `{path, sha256, kind}`; the role card says a spec's file lists hold paths or
such records. A record in `test_files` met `Path(record)` and a bare TypeError that named nothing. Now:

* B1 - ONE reader (`_input_record`) and ONE claim check (`_check_claim`) serve `build` and `verify_files`: the same
  record gets the same verdict from both (invariant: one record form has one reader, AR-13);
* B2 - a present `sha256` that is not a 64-hex string is refused by name, never skipped and never "bytes changed"
  (invariant: a claim is checked or refused, never silently ignored);
* B3 - a value that is neither a path nor a record is refused naming the group, the index and an example record (FR-1);
* B4 - the role card, `--help` and the parser describe one spec form, and a spec written as the card says is fingerprinted.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir  # noqa: E402

import execution_fingerprint as F  # noqa: E402
from role_cli import epilog, registry  # noqa: E402

PROVENANCE = {"result": "not_applicable", "profile_id": "unit", "environment_id": "local",
              "expected_source_revision": "abc", "timestamp": "2026-10-23T00:00:00Z", "evidence_refs": []}
CARD_FORM = "each a list of paths or {path, sha256} records (helper_files optional)"


def outcome(fn):
    """('ok', None) or ('refused', message); a bare TypeError/KeyError would escape and fail the test loudly."""
    try:
        fn()
        return "ok", ""
    except ValueError as exc:
        return "refused", str(exc)


def main() -> None:
    root = temp_dir("qa-fingerprint-records-")
    try:
        test = root / "test_one.py"
        test.write_text("def test_one():\n    assert True\n", encoding="utf-8")
        cfg = root / "config.json"
        cfg.write_text("{}", encoding="utf-8")
        sha = F.file_hash(test)
        cfg_sha = F.file_hash(cfg)
        record = {"path": str(test), "sha256": sha, "kind": "test_files"}
        spec = {"source_revision": "abc", "test_files": [str(test)], "config_files": [str(cfg)],
                "dependency_files": [], "runtime_provenance": dict(PROVENANCE), "profile_id": "unit"}

        def build_with(item, key="test_files"):
            return lambda: F.build(dict(spec, **{key: [item]}))

        # --- the shapes that work -------------------------------------------------------------------
        check_eq("file_hash reads a Path", F.file_hash(Path(str(test))), sha)
        by_path = F.build(spec)
        by_record = F.build(dict(spec, test_files=[record], config_files=[{"path": str(cfg), "sha256": cfg_sha}]))
        check_eq("a spec built from records fingerprints the same as one built from paths",
                 by_record["input_fingerprint"], by_path["input_fingerprint"])
        check_eq("and its records carry the resolved path string",
                 by_record["fingerprint_files"][0]["path"], str(Path(test).resolve()))
        check("verify_files accepts the records build wrote", F.verify_files(by_record["fingerprint_files"]))
        check_eq("a record without a claim is a plain path in build (no claim to check)",
                 outcome(build_with({"path": str(test)}))[0], "ok")
        check_eq("a Path in a spec list is still a path", outcome(build_with(Path(str(test))))[0], "ok")

        # --- B1: the same record, the same verdict from build and verify_files ------------------------
        cases = [
            ("a good record", dict(record), None),
            ("an uppercase-hex claim of the right digest", dict(record, sha256=sha.upper()), None),
            ("a claim that disagrees with the bytes", dict(record, sha256="0" * 64), "input bytes changed"),
            ("an empty sha256", dict(record, sha256=""), "must be its 64-hex digest"),
            ("a numeric sha256", dict(record, sha256=123), "must be its 64-hex digest"),
            ("a null sha256", dict(record, sha256=None), "must be its 64-hex digest"),
            ("a short sha256", dict(record, sha256=sha[:63]), "must be its 64-hex digest"),
            ("a non-hex sha256", dict(record, sha256="z" * 64), "must be its 64-hex digest"),
            ("a path that is not a string", dict(record, path={"path": str(test)}), "requires a `path` string"),
            ("an empty path", dict(record, path=""), "requires a `path` string"),
            ("a record with no path", {"sha256": sha}, "requires a `path` string"),
            ("a file that is not there", dict(record, path=str(root / "gone.py")), "fingerprint input is unavailable"),
        ]
        for label, rec, needle in cases:
            got_build = outcome(build_with(rec))
            got_verify = outcome(lambda rec=rec: F.verify_files([rec]))
            if needle is None:
                check_eq("B1 " + label + ": build and verify_files both accept", (got_build[0], got_verify[0]), ("ok", "ok"))
                continue
            check_eq("B1 " + label + ": build and verify_files both refuse", (got_build[0], got_verify[0]),
                     ("refused", "refused"))
            check_in("B1 " + label + ": build says so", needle, got_build[1])
            check_in("B1 " + label + ": verify_files says so", needle, got_verify[1])
        # the one place the two readers differ on purpose: a request's recorded input MUST carry its claim
        check_eq("B1 verify_files requires the claim a spec may omit",
                 (outcome(lambda: F.verify_files([{"path": str(test)}]))[0], outcome(build_with({"path": str(test)}))[0]),
                 ("refused", "ok"))
        check_eq("B1 a bare path string is no recorded input for verify_files",
                 outcome(lambda: F.verify_files([str(test)]))[0], "refused")
        check_eq("B1 a file that is not there: today's refusal, unchanged",
                 outcome(build_with(str(root / "gone.py")))[1].startswith("fingerprint input is unavailable: "), True)
        check_eq("B1 verify_files still refuses an empty list", outcome(lambda: F.verify_files([]))[0], "refused")
        check_eq("B1 file_hash takes no claim: a record is refused, not read half",
                 outcome(lambda: F.file_hash(record))[0], "refused")

        # --- B2: a present claim is checked or refused, never skipped, never "bytes changed" ---------
        for label, bad in (("empty", ""), ("numeric", 123), ("null", None), ("list", [sha])):
            kind, message = outcome(build_with(dict(record, sha256=bad)))
            check_in("B2 a " + label + " sha256 is refused by name", "sha256 of " + str(test) + " must be its 64-hex digest",
                     message)
            check_not_in("B2 a " + label + " sha256 is not reported as changed bytes", "bytes changed", message)

        # --- B3: a value that is neither is refused naming group, index and an example ---------------
        kind, message = outcome(lambda: F.build(dict(spec, test_files=[str(test), record, 42])))
        check_eq("B3 a number among the paths is a refusal, not a TypeError", kind, "refused")
        check_in("B3 the refusal names the group and the index", "test_files[2]", message)
        check_in("B3 the refusal names the type", "got int", message)
        check_in("B3 the refusal gives an example record", '{"path": "tests/test_x.py", "sha256": "<64 hex>"}', message)
        kind, message = outcome(build_with(["nested"], key="config_files"))
        check_in("B3 another group is named by its own key", "config_files[0]", message)
        kind, message = outcome(build_with(dict(record, path=None), key="helper_files"))
        check_in("B3 a record without a path string names group and index", "helper_files[0]", message)
        kind, message = outcome(lambda: F.build(dict(spec, test_files=[""])))
        check_in("B3 an empty path string is refused by position", "test_files[0]", message)
        kind, message = outcome(lambda: F.verify_files([record, {"path": {"path": str(test)}, "sha256": sha}]))
        check_in("verify_files names the position of the bad record", "fingerprint_files[1]", message)
        check_eq("verify_files refuses a nested record instead of raising", kind, "refused")

        # --- B4: the card, --help and the parser describe ONE spec form -------------------------------
        rows = registry()        # the one reader of role-commands.json (AR-13)
        card = next(str(rows[n].get("input") or "") for n in sorted(rows) if n.split()[0] == "execution_fingerprint.py")
        check_in("B4 the role card says paths or {path, sha256} records, helper_files optional", CARD_FORM, card)
        check_in("B4 the epilog repeats the card word for word", card, epilog("execution_fingerprint.py"))
        helped = run_script("execution_fingerprint.py", "--help")
        check_eq("B4 --help runs", helped.returncode, 0)
        check_in("B4 the real --help output repeats the card word for word", card, helped.stdout)
        test_two = root / "test_two.py"
        test_two.write_text("def test_two():\n    assert True\n", encoding="utf-8")
        from_card = F.build(dict(spec, test_files=[{"path": str(test), "sha256": sha}, str(test_two)],
                                 config_files=[{"path": str(cfg), "sha256": cfg_sha}], dependency_files=[]))
        check_eq("B4 a spec written as the card says (a record and a path, no helper_files) is fingerprinted",
                 from_card["input_fingerprint"],
                 F.build(dict(spec, test_files=[str(test), str(test_two)]))["input_fingerprint"])
        with_helper = F.build(dict(spec, helper_files=[{"path": str(cfg), "sha256": cfg_sha}]))
        check_eq("B4 helper_files takes the same form", len(with_helper["fingerprint_files"]), 3)
        spec_file = root / "spec.json"
        spec_file.write_text(json.dumps(dict(spec, test_files=[{"path": str(test), "sha256": sha}],
                                             config_files=[{"path": str(cfg), "sha256": cfg_sha}])), encoding="utf-8")
        ran = run_script("execution_fingerprint.py", spec_file)
        check_eq("B4 the command fingerprints a spec written as the card says", ran.returncode, 0)
        check_eq("B4 and prints the same fingerprint as the paths form",
                 json.loads(ran.stdout)["input_fingerprint"], by_path["input_fingerprint"])
        spec_file.write_text(json.dumps(dict(spec, test_files=[{"path": str(test), "sha256": ""}])), encoding="utf-8")
        ran = run_script("execution_fingerprint.py", spec_file)
        check_eq("an empty sha256 through the command is a refusal (exit 2), not a traceback", ran.returncode, 2)
        check_in("and the refusal names the position", "test_files[0]", ran.stderr)
        check_not_in("and no traceback reaches the role", "Traceback", ran.stderr)

        # --- t-1355 N2: one refusal lists every problem of a specification ---------------------------
        import friction
        from detector_verdict import split_items
        missing = {k: v for k, v in spec.items() if k not in ("source_revision", "dependency_files")}
        _, text = outcome(lambda: F.build(missing))
        items = split_items(text)
        check("N2-F: a spec missing two keys names both",
              len(items) == 2 and "missing source_revision" in items[0] and "missing dependency_files" in items[1], text)
        check_eq("N2-F: SPEC_REQUIRED is the carrier of the six keys (EP2-1 added profile_id, last)", F.SPEC_REQUIRED,
                 ("source_revision", "test_files", "config_files", "dependency_files", "runtime_provenance", "profile_id"))
        _, text = outcome(lambda: F.build({}))
        check_eq("E-N2-1 an empty spec names the six keys and nothing else", len(split_items(text)), 6)
        for bad in ([], "x", None, 3):
            _, text = outcome(lambda: F.build(bad))
            check_eq("E-N2-2 a spec that is not an object is one problem (%r)" % (bad,), text,
                     "fingerprint specification must be a JSON object")
        absent = root / "no_such_config.json"
        bad_sha = dict(spec, test_files=[{"path": str(test), "sha256": "xyz"}], config_files=[str(absent)])
        _, text = outcome(lambda: F.build(bad_sha))
        items = split_items(text)
        check("N2-F: two bad file records in two lists are both named with their position",
              len(items) == 2 and "test_files[0]: sha256 of" in text and "(config_files[0])" in text
              and items[1].startswith("fingerprint input is unavailable: "), text)
        check("E-N2-5 an empty config list is not told twice when its items were refused",
              "must be explicit" not in text, text)
        _, text = outcome(lambda: F.build(dict(spec, test_files="a.py")))
        check_in("N2-F: a string where a list belongs is refused, not iterated",
                 "test_files must be a list of paths or {path, sha256} records", text)
        check_not_in("E-N2-3 and no one-letter path is read", "unavailable", text)
        _, text = outcome(lambda: F.build(dict(spec, test_files=[])))
        check_eq("N2-F: an empty test_files list is refused as before", text, "test and configuration inputs must be explicit")
        _, text = outcome(lambda: F.build(dict(spec, test_files=[], config_files=[], runtime_provenance={})))
        check("a provenance refusal and the empty lists are listed together, in order",
              len(split_items(text)) >= 2 and text.rstrip().endswith("test and configuration inputs must be explicit"), text)
        _, text = outcome(lambda: F.build(dict(spec, helper_files=7)))
        check_in("helper_files (optional, present) is judged like the others", "helper_files must be a list", text)
        for odd in ({"path": str(test)}, 7):      # Q6 (t-1398): a dict or a number for a file list is refused like a string
            _, text = outcome(lambda: F.build(dict(spec, config_files=odd)))
            check_in("Q6: %r where a file list belongs is refused, not read" % (odd,),
                     "config_files must be a list of paths or {path, sha256} records", text)
        for odd in ("zz", 7, None, []):           # fix 3: a non-object provenance is ONE problem and the others are still listed
            _, text = outcome(lambda: F.build(dict(spec, runtime_provenance=odd, test_files=[], config_files=[])))
            items = split_items(text)
            check("fix 3: runtime_provenance %r is one problem, listed with the others, no crash" % (odd,),
                  items == ["runtime_provenance must be an object", "test and configuration inputs must be explicit"], text)
        no_prov = {k: v for k, v in spec.items() if k != "runtime_provenance"}
        _, text = outcome(lambda: F.build(no_prov))
        check_eq("fix 3: an absent runtime_provenance keeps today's single line", text,
                 "fingerprint specification missing runtime_provenance")
        problems, groups, records = F.spec_problems(spec)
        check("fix 4: the collector returns no problems for a valid spec and the records the build uses",
              problems == [] and len(records) == 2
              and set(groups) == set(F.SPEC_FILE_LISTS) | {"config_sha", "policy_revision"})
        check("N2: every multi-problem refusal is validator friction",
              friction.classify("execution_fingerprint.py: " + outcome(lambda: F.build({}))[1]) == "validator")
        # the success output is byte-identical: runtime_sha / dependency_sha captured from the PILE code (c675c508) for
        # this provenance and an empty dependency list (path independent); the file-dependent parts are recomputed by the
        # pile formula from the records the build itself returns
        built = F.build(spec)
        comp = built["fingerprint_components"]
        check_eq("N2-F: runtime_sha is the pile's", comp["runtime_sha"],
                 "3eec869ac6803592fa0e740a1a0a969918f1a63db9ff33414416feff40ee4ec9")
        check_eq("N2-F: dependency_sha of an empty list is the pile's", comp["dependency_sha"],
                 "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945")
        by_kind = {k: sorted([r for r in built["fingerprint_files"] if r["kind"] == k], key=lambda r: r["path"])
                   for k in F.SPEC_FILE_LISTS}
        legacy = {"source_sha": "abc",
                  "test_content_sha": F.content_hash(by_kind["test_files"] + by_kind["helper_files"]),
                  "config_sha": F.content_hash(by_kind["config_files"]),
                  "dependency_sha": F.content_hash(by_kind["dependency_files"]),
                  "runtime_sha": comp["runtime_sha"], "policy_revision": F.projection_rules()["policy_revision"]}
        check_eq("N2-F: a valid spec fingerprints exactly as before (the pile formula over the same records)",
                 built["input_fingerprint"], F.content_hash(legacy))
        check_eq("and its files are in spec order of lists, as before", [r["kind"] for r in built["fingerprint_files"]],
                 ["test_files", "config_files"])
    finally:
        cleanup(root)
    finish("test_execution_fingerprint_records")


if __name__ == "__main__":
    main()
