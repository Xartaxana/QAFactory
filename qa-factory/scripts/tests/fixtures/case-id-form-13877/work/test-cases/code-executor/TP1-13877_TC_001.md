---
id: TP1-13877_TC_001
title: README threshold table and models.py docstring reflect corrected LOW=permissive HIGH=strict semantics
area: code-executor
priority: P2
status: Draft
channel: manual-human
reuse_decision: new
updated: 2026-09-28
task: TP1-13877
covers: [R-6, R-7]
defect_class: degraded
basis: "requirement:R-6"
plan_row: TS-6
reuse_reason: "no code-executor cases exist in any prior story; no overlap found"
---
Requirements: R-6, R-7
Plan row: TS-6

## Given

The reviewer has access to the merge request diff for `testproject1-backend`. No stand is required; this is a static diff review.

## When

The reviewer opens the diff and reads the README threshold section, the `SecurityConfig` docstring in `models.py` and the header comment of `default_security_policies.yaml`.

## Then

1. P-readme-table: the README describes `LOW` as the permissive setting that blocks fewer patterns and `HIGH` as the strict one that blocks more; it does NOT describe `HIGH` as permissive or `LOW` as strict.
2. P-models-docstring: the `SecurityConfig` docstring states the corrected semantics (lower threshold = fewer blocks, higher threshold = more blocks) and does NOT repeat the old inverted wording.
3. P-yaml-header: the header comment of `default_security_policies.yaml` states that `LOW` is lenient and `HIGH` is strict.

If a file's diff does not contain the expected content, the reviewer records the actual text found; that is a failed Then for that partition.
