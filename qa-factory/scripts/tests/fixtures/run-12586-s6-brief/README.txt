Source: the 12586 run (TP1-12586, testproject1-dev-010 test-harness), taken 28.10.2026.
- dispatch.json: the record of dispatch S6-qa-runner-2 in state/controller.json, reduced to id, stage, role, scope,
  execution_kind, manual_case_ids, purpose, status and request_binding (the long known_paths, evidence_refs and agent
  fields are dropped; status is set to running, the run had it accepted).
- utils-paths.txt: the first ten paths of the section "Utils, page objects and test data, ranked" of
  work/briefs/repo-map-4852b66ca7.md, in the map's order.
The stand config and the env file come from ../run-12586-stand-config/ (HF5-2). The three request.json of the cases are NOT
kept here: the test makes them with the real producer (manual_evidence.prepare_to_file on the manual-evidence scaffold, with
the TC-014 and TC-012 preconditions of ../run-12586-actors/) and files them under the names TC-010 / TC-012 / TC-014.
Replacements: none (no Cyrillic, no value of the real env file).
