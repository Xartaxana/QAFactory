"""stand_lease `walk` mode (t-1957 N1b): manual walkers share a serial stand with each other, never with a suite.

The lease record holds `holders: [{job, pid, started, mode, acquired_at}]`. Holders here are distinct JOBS of one
process (the lease identity is job + pid + birth), so no child process is needed; the clock is injected, nothing sleeps.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stand_lease as SL  # noqa: E402


class FakeClock:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(SL, "_sleep", fake.sleep)
    monkeypatch.setattr(SL, "_monotonic", fake.monotonic)
    return fake


@pytest.fixture
def root(tmp_path, clock):
    (tmp_path / "qa-factory" / "state").mkdir(parents=True)
    return tmp_path


def lease_file(root) -> dict:
    return json.loads((root / "qa-factory" / "state" / "stand-lease.json").read_text(encoding="utf-8"))


def holders(root, env="default") -> list:
    return lease_file(root)["leases"].get(env, {}).get("holders", [])


def walk(root, job, max_shared=2, wait_s=0):
    return SL.hold(root, job, "", wait_s=wait_s, poll_s=5, mode="walk", max_shared=max_shared)


def test_two_walk_holders_admitted(root):
    with walk(root, "walk:a") as first:
        with walk(root, "walk:b") as second:
            assert (first["waited_s"], second["waited_s"]) == (0, 0)
            assert [(h["job"], h["mode"], h["pid"]) for h in holders(root)] == [
                ("walk:a", "walk", os.getpid()), ("walk:b", "walk", os.getpid())]
            assert all(h["started"] for h in holders(root))
        assert [h["job"] for h in holders(root)] == ["walk:a"]
    assert lease_file(root)["leases"] == {}


def test_walk_over_max_waits(root, clock):
    with walk(root, "walk:a", max_shared=1):
        with pytest.raises(SL.StandBusy) as busy:
            with walk(root, "walk:b", max_shared=1, wait_s=7):
                pytest.fail("a second walker entered a stand that takes one")
        assert clock.sleeps == [5, 2]
        assert (busy.value.holder["job_id"], busy.value.holder["mode"]) == ("walk:a", "walk")
        assert [h["job"] for h in holders(root)] == ["walk:a"]
    with walk(root, "walk:a", max_shared=2), walk(root, "walk:b", max_shared=2):
        with pytest.raises(SL.StandBusy):
            with walk(root, "walk:c", max_shared=2):
                pytest.fail("a third walker entered a stand that takes two")


def test_same_job_is_not_a_second_walker(root):
    """Distinct jobs: the same job and process re-enters its own row and never takes a second slot."""
    with walk(root, "walk:a", max_shared=3):
        with walk(root, "walk:a", max_shared=3):
            assert len(holders(root)) == 1
        assert len(holders(root)) == 1          # the inner exit did not release the outer row


def test_exclusive_waits_for_walk(root, clock):
    with walk(root, "walk:a"):
        with pytest.raises(SL.StandBusy) as busy:
            with SL.hold(root, "suite-1", "", wait_s=5, poll_s=5):
                pytest.fail("a suite ran beside a walk")
        assert busy.value.holder["job_id"] == "walk:a"
        assert clock.sleeps == [5]
    with SL.hold(root, "suite-1", "", wait_s=0) as lease:
        assert lease["waited_s"] == 0
        assert [h["mode"] for h in holders(root)] == ["exclusive"]


def test_walk_waits_for_exclusive(root):
    with SL.hold(root, "suite-1", "", wait_s=0):
        with pytest.raises(SL.StandBusy) as busy:
            with walk(root, "walk:a", max_shared=5, wait_s=5):
                pytest.fail("a walk ran beside a suite")
        assert (busy.value.holder["job_id"], busy.value.holder["mode"]) == ("suite-1", "exclusive")
    with walk(root, "walk:a"):
        assert [h["mode"] for h in holders(root)] == ["walk"]


def test_each_holder_releases_itself(root):
    path, _ = SL._paths(root)
    with walk(root, "walk:a"):
        state = lease_file(root)
        state["leases"]["default"]["holders"].append({**state["leases"]["default"]["holders"][0], "job": "walk:z"})   # a live foreign row
        path.write_text(json.dumps(state), encoding="utf-8")
        with walk(root, "walk:b", max_shared=3):
            pass                                        # walk:b leaves; walk:a and the foreign row stay
        assert [h["job"] for h in holders(root)] == ["walk:a", "walk:z"]
    assert [h["job"] for h in holders(root)] == ["walk:z"]      # walk:a left; only its own row went


def test_dead_holder_dropped(root):
    path, _ = SL._paths(root)
    dead = [{"job": "walk:dead1", "pid": 0, "started": "", "mode": "walk", "acquired_at": "2026-11-01T00:00:00+00:00"},
            {"job": "walk:dead2", "pid": os.getpid(), "started": "winfiletime:1", "mode": "walk",
             "acquired_at": "2026-11-01T00:00:00+00:00"}]          # a recycled pid: the birth differs
    path.write_text(json.dumps({"schema_version": 1, "notes": [], "leases": {"default": {"holders": dead}}}), encoding="utf-8")
    with walk(root, "walk:a", max_shared=1) as lease:           # the dead hold nothing: a stand of one walker is free
        assert lease["waited_s"] == 0
        assert lease["took_over"]["job_id"] == "walk:dead1"
        assert [h["job"] for h in holders(root)] == ["walk:a"]
    named = [n["from"] for n in lease_file(root)["notes"] if n["event"] == "takeover"]
    assert named == ["walk:dead1", "walk:dead2"]
    path.write_text(json.dumps({"schema_version": 1, "notes": [], "leases": {"default": {"holders": dead}}}), encoding="utf-8")
    with SL.hold(root, "suite-1", "", wait_s=0):                 # and a suite is not kept out by a dead walker either
        assert [h["job"] for h in holders(root)] == ["suite-1"]


def test_status_lists_all_holders(root):
    with walk(root, "walk:a"), walk(root, "walk:b"):
        rows = SL.status(root)["leases"]
        assert [r["environment"] for r in rows] == ["default"]
        assert [(h["job"], h["mode"], h["state"]) for h in rows[0]["holders"]] == [
            ("walk:a", "walk", "alive"), ("walk:b", "walk", "alive")]


def test_person_release_releases_every_holder(root):
    with walk(root, "walk:a"), walk(root, "walk:b"):
        answer = SL.release_by_person(root, "", "walkers were killed by hand")
        assert answer["status"] == "released" and [h["job"] for h in answer["released"]] == ["walk:a", "walk:b"]
        notes = [n for n in lease_file(root)["notes"] if n["event"] == "released_by_person"]
        assert [(n["from"], n["reason"]) for n in notes] == [("walk:a", "walkers were killed by hand"),
                                                             ("walk:b", "walkers were killed by hand")]
        assert lease_file(root)["leases"] == {}
    assert SL.release_by_person(root, "", "again")["status"] == "not_held"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
