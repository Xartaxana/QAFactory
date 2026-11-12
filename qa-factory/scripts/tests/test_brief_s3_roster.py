#!/usr/bin/env python3
"""t-2142 PK0-2: the S3 brief hands the strategist the product's roles (AR-10, AR-11, AR-13, AR-29; FR-38, FR-56, FR-41).

`brief_pack.s3_roster_lines` reads `project_knowledge.roster` (the one reader) and prints data and provenance, never a judgment: the roles,
which have an account on the chosen stand, who said so, what the person removed. S3 only. Every role line carries the data token
`[knowledge:product.roles]` (a count for later); the empty, no-stand and unreadable forms say so; a failure is no lines.

Run: python -B -m pytest scripts/tests/test_brief_s3_roster.py -q
"""
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import harness  # noqa: E402

sys.path.insert(0, str(harness.SCRIPTS))
import brief_pack  # noqa: E402
import project_knowledge as PK  # noqa: E402

TASK = "QA-9"
MARK = "[knowledge:product.roles]"
FILE = "qa-factory/records/project-knowledge.json"


def set_stands(root: Path, stands: list) -> dict:
    path = root / "qa-factory" / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg["environments"] = stands
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return cfg


def stand(name="dev", roles=None) -> dict:
    return {"name": name, "base_url": "http://localhost:8080", "credentials_by_role": roles or {}}


def accounts(*names) -> dict:
    return {n: f"{n.upper()}_USER / {n.upper()}_PASS" for n in names}


def facts(root: Path, rows: list) -> None:
    PK.record_path(root).parent.mkdir(parents=True, exist_ok=True)
    PK.record_path(root).write_text(json.dumps({"schema_version": 1, "facts": rows}), encoding="utf-8")


def role_row(n, element, state, story="LOCAL-7", sign_in="account") -> dict:
    return {"id": f"PK-{n}", "key": PK.ROLES_KEY, "environment": "", "element": element, "state": state, "scope": "project",
            "value": {"sign_in": sign_in}, "provenance": {"source": "person" if state != "noticed_unconfirmed" else "role",
                                                          "words": "w", "story": story, "by": "conductor", "where": ""},
            "at": f"2026-11-0{n}T10:00:00"}


@pytest.fixture
def world():
    root = harness.temp_project("s3-roster-")
    harness.use_project(root)
    task = root / "qa-factory" / "artifacts" / TASK
    (task / "work").mkdir(parents=True)
    (task / "pipeline.json").write_text(json.dumps(
        {"ticket": TASK, "size": "S", "environment": "dev", "implementation_source": "diff",
         "stages": {"S0": {"status": "pending"}}, "gates": {}, "halts": []}), encoding="utf-8")
    try:
        yield root, task
    finally:
        harness.cleanup(root)


def lines(world, env="dev") -> list:
    root, task = world
    return brief_pack.s3_roster_lines(task, json.loads((root / "qa-factory" / "config.json").read_text(encoding="utf-8")), env)


def role_lines(got) -> list:
    return [ln for ln in got if ln.startswith("- ")]


def test_roster_lines_s3_only(world):
    root, _ = world
    set_stands(root, [stand("dev", accounts("admin"))])
    brief = {(stage, role): brief_pack.build(TASK, stage, role, f"{stage}-{role}-1", write=False)["markdown"]
             for stage, role in (("S3", "qa-test-strategist"), ("S3", "qa-case-critic"))}      # S3 has two roles; other stages are not S3
    assert "- admin: an account on dev (the project's settings) " + MARK in brief[("S3", "qa-test-strategist")]
    assert [k for k, text in brief.items() if "Product roles" in text or MARK in text or "product_roles" in text] == [("S3", "qa-test-strategist")]


def test_cap_15_then_more(world):
    root, _ = world
    names = [f"role{i:02d}" for i in range(17)]
    set_stands(root, [stand("dev", accounts(*names[:15]))])
    at_cap = lines(world)
    assert len(role_lines(at_cap)) == 15 and not any("more:" in ln for ln in at_cap)
    set_stands(root, [stand("dev", accounts(*names))])
    beyond = lines(world)
    assert len(role_lines(beyond)) == 15
    assert f"+2 more: {FILE}" in beyond


def test_removed_line_capped(world):
    root, _ = world
    set_stands(root, [stand("dev")])
    facts(root, [role_row(1 + i % 9, f"gone{i:02d}", "not_needed", story="") | {"id": f"PK-{i}"} for i in range(17)])
    line = next(ln for ln in lines(world) if ln.startswith("Removed by the person: "))
    assert line.count("gone") == 15 and line.endswith(f"; +2 more: {FILE}")


def test_empty_roster_line(world):
    root, _ = world
    set_stands(root, [stand("dev")])
    got = lines(world)
    assert got[0].startswith("Product roles: none recorded yet (a project learns them story by story).")
    assert "product_roles" in got[0] and not role_lines(got) and MARK not in "\n".join(got)


def test_no_stand_line(world):
    root, _ = world
    set_stands(root, [stand("dev", accounts("admin")), stand("stage")])        # two stands, none named: not guessed
    got = lines(world, env="")
    assert "Stand: not chosen yet - which roles have an account is not shown." in got
    assert role_lines(got) == ["- admin: (the project's settings) " + MARK]       # no account part, nothing said about accounts


def test_unreadable_registry_line(world):
    root, _ = world
    set_stands(root, [stand("dev", accounts("admin"))])
    PK.record_path(root).parent.mkdir(parents=True, exist_ok=True)
    PK.record_path(root).write_text("{not json", encoding="utf-8")
    got = lines(world)
    assert got[0].startswith("Product roles: the record of earlier answers cannot be read (")
    assert got[0].endswith("); listed from the stand's accounts only.") and len(got[0]) < 400
    assert role_lines(got) == ["- admin: an account on dev (the project's settings) " + MARK]


def test_noticed_marked_not_confirmed(world):
    root, _ = world
    set_stands(root, [stand("dev")])
    facts(root, [role_row(1, "guest", "noticed_unconfirmed", sign_in="none")])
    assert role_lines(lines(world)) == ["- guest: no sign-in; noticed in LOCAL-7, not confirmed by the person " + MARK]


def test_removed_line(world):
    root, _ = world
    set_stands(root, [stand("dev", accounts("superuser", "admin"))])
    facts(root, [role_row(1, "superuser", "not_needed", story="LOCAL-8")])
    got = lines(world)
    assert "Removed by the person: superuser (LOCAL-8)." in got
    assert [ln.split(":")[0] for ln in role_lines(got)] == ["- admin"]           # out of the roster though a config account exists


def test_provenance_shown(world):
    root, _ = world
    set_stands(root, [stand("dev", accounts("admin", "auditor"))])
    facts(root, [role_row(1, "auditor", "known", story="LOCAL-7")])
    got = {ln.split(":")[0]: ln for ln in role_lines(lines(world))}
    assert got["- auditor"] == "- auditor: an account on dev (the person, LOCAL-7) " + MARK
    assert got["- admin"] == "- admin: an account on dev (the project's settings) " + MARK


def test_optional_section_named(world):
    root, _ = world
    set_stands(root, [stand("dev", accounts("admin"))])
    full = "\n".join(lines(world))
    set_stands(root, [stand("dev")])
    empty = "\n".join(lines(world))
    for text in (full, empty):
        assert "optional handoff section product_roles" in text and "[]" in text


def test_exception_gives_no_lines(world, monkeypatch):
    root, _ = world
    set_stands(root, [stand("dev", accounts("admin"))])

    def boom(*args, **kwargs):
        raise RuntimeError("registry exploded")
    monkeypatch.setattr(PK, "roster", boom)
    assert lines(world) == []        # the try/except lives inside s3_roster_lines, so the empty list proves the brief is not blocked


def test_roster_lines_carry_knowledge_marker(world):
    root, _ = world
    set_stands(root, [stand("dev", accounts("admin", "auditor"))])
    facts(root, [role_row(1, "guest", "noticed_unconfirmed"), role_row(2, "gone", "not_needed")])
    got = lines(world)
    assert len(role_lines(got)) == 3 and all(ln.endswith(" " + MARK) for ln in role_lines(got))
    assert not [ln for ln in got if not ln.startswith("- ") and MARK in ln]       # the header, removed and closing lines carry none


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
