#!/usr/bin/env python3
"""The orchestrator's share is bounded, and the bound says whose finding it is.

TP2-2553: $47.86 of $100.37 (47.7 %) and 123.8M tokens went to dispatching,
hand-assembling requests, repeated acceptances and holding context across S1-S8.
`retro_numbers.orchestrator_totals` measured it and bounded nothing, and the retro's only
line about it fired at a hard-coded 50 % — so the story that earned the rule stayed silent.
This file holds the configured threshold, the per-stage split taken from the same receipts,
the one sentence the retro and the Factory tab banner share, and the rule that a story with
no orchestrator receipts reads as missing rather than as a zero share.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import (SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish,  # noqa: E402
                     temp_dir)

sys.path.insert(0, str(SCRIPTS))
import retro_numbers as RN  # noqa: E402
import factory_dashboard as D  # noqa: E402

TASK = "TP2-2553"
# One stage window per stamp, and orchestrator requests inside each of them.
PIPELINE = {"stages": {
    "S1": {"status": "done", "started": "2026-09-23T10:00:00Z", "finished": "2026-09-23T11:00:00Z"},
    "S5": {"status": "done", "started": "2026-09-23T11:00:00Z", "finished": "2026-09-23T12:00:00Z"},
    # The stage of the same story whose clock ran backwards: it can place nothing.
    "S0": {"status": "done", "started": "2026-09-23T13:20:00Z", "finished": "2026-09-23T11:42:43Z"}}}


def request(when, usd, stream="orchestrator", task=TASK):
    """One request of the story's own activity, priced at `usd` by the catalogue's output rate (a story the
    retro can price by evidence: the price function re-prices every request from its stored usage)."""
    usage = {"input": 0, "output": int(round(usd / 0.00001)), "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
    return {"task": task, "stream": stream, "timestamp": when, "activity_id": "a", "model_id": "claude-sonnet-5-5",
            "usage": usage, "valuation": {"pricing_coverage": "complete", "subtotal_usd": str(usd)}}


def cost_file(sid, usd, task=TASK):
    """A cost file of one request priced at `usd` by a table that is NOT the driver's (the catalogue's output rate)."""
    usage = {"input": 0, "output": int(round(usd / 0.00001)), "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
    row = {"request_key": sid + ":r", "task": task, "stream": "orchestrator", "timestamp": "2026-09-30T05:00:00Z",
           "model_id": "claude-sonnet-5-5", "usage": usage,
           "valuation": {"pricing_coverage": "complete", "subtotal_usd": str(usd)}}
    return {"session_id": sid, "usage_completeness": "complete", "requests": [row]}


def session(share_usd):
    """A cost file whose orchestrator spent `share_usd` of a $100 story."""
    return {"session_id": "s1", "usage_completeness": "complete",
            "by_activity": {"a": {"type": "story", "task": TASK}},
            "by_task": {TASK: {"active_s": 10, "machine_s": 10, "cost": 100.0, "tokens": 1000}},
            "agents": [{"agent": "qa-automator", "task": TASK, "tokens": 900, "cost": 52.0}],
            "requests": [request("2026-09-23T10:30:00Z", share_usd * 0.25),
                         request("2026-09-23T11:30:00Z", share_usd * 0.7),
                         request("2026-09-23T20:00:00Z", share_usd * 0.05),
                         request("2026-09-23T11:30:00Z", 100.0 - share_usd, stream="agent-1")]}


def the_limit_comes_from_the_config_with_a_default():
    check_eq("a project that never heard of the key keeps the default",
             RN.share_limit_from_cfg({}), 35.0)
    check_eq("and so does one onboarded on 0.7.x with no retro block",
             RN.share_limit_from_cfg({"schema_version": 1}), 35.0)
    check_eq("a project that set it gets what it set",
             RN.share_limit_from_cfg({"retro": {"orchestrator_share_max": 0.2}}), 20.0)
    check_eq("a percentage written where a fraction belongs cannot switch the limit off",
             RN.share_limit_from_cfg({"retro": {"orchestrator_share_max": 35}}), 35.0)
    check_eq("nor can a zero, a negative or a word",
             [RN.share_limit_from_cfg({"retro": {"orchestrator_share_max": v}})
              for v in (0, -1, "half", None)], [35.0] * 4)
    root = temp_dir("qa-orch-share-cfg-")
    try:
        (root / "config.json").write_text(json.dumps({"retro": {"orchestrator_share_max": 0.5}}),
                                          encoding="utf-8")
        check_eq("read off disk it is the same number",
                 RN.share_limit_percent(root), 50.0)
        check_eq("and a project with no config.json at all still has a limit",
                 RN.share_limit_percent(root / "nowhere"), 35.0)
    finally:
        cleanup(root)


def the_split_is_placed_by_the_story_s_own_stage_clock():
    files = [(None, session(48.0))]
    split = RN.orchestrator_by_stage(TASK, files, PIPELINE)
    check_eq("each request lands in the stage whose window holds it",
             (round(split["S1"], 2), round(split["S5"], 2)), (12.0, 33.6))
    check_eq("a request no sound window holds is unattributed, not folded into a neighbour",
             round(split["unattributed"], 2), 2.4)
    check_not_in("and the stage whose clock runs backwards places nothing",
                 "S0", json.dumps(split))
    check_eq("another story's requests are not this story's",
             RN.orchestrator_by_stage("OTHER-1", files, PIPELINE), {})


def a_share_over_the_limit_is_a_finding_with_its_stages():
    data = {"story": {"usd": 100.37}, "orchestrator_share_percent": 47.7,
            "orchestrator_share_limit_percent": 35.0,
            "orchestrator_by_stage": {"S5": 21.0, "S1": 12.0}}
    line = RN.orchestrator_finding(data)
    check_in("the share and the limit stand together",
             "the orchestrator spent 48 % of the story (limit 35 %)", line)
    check_in("with the largest stage first", "- S5 21 %, S1 12 %", line)
    check_in("and the work it names", "holding context across the stages", line)
    check_in("the finding is the factory's", "finding about the factory (FB)", line)
    check_in("never the person's", "never a cost line the person is asked to repair", line)

    check_eq("a share under the limit says nothing at all",
             RN.orchestrator_finding(dict(data, orchestrator_share_percent=20.0)), "")
    check_eq("a story whose share could not be computed is missing, not zero",
             RN.orchestrator_finding(dict(data, orchestrator_share_percent=None)), "")
    check_in("a share over the limit with no stage receipts is still the finding",
             "(limit 35 %). Dispatching",
             RN.orchestrator_finding(dict(data, orchestrator_by_stage={})))


def the_retro_and_the_banner_say_the_same_sentence():
    root = temp_dir("qa-orch-share-")
    try:
        state = root / "qa-factory"
        (state / "state" / "cost").mkdir(parents=True)
        (state / "artifacts" / TASK).mkdir(parents=True)
        (state / "state" / "cost" / "s1.json").write_text(json.dumps(session(48.0)), encoding="utf-8")
        (state / "artifacts" / TASK / "pipeline.json").write_text(json.dumps(PIPELINE), encoding="utf-8")

        data = RN.numbers(TASK, root=state, task_root=state / "artifacts" / TASK)
        check_eq("the limit travels with the numbers",
                 data["orchestrator_share_limit_percent"], 35.0)
        check_eq("the share is the orchestrator's own cost over the story's",
                 data["orchestrator_share_percent"], 48.0)
        text = RN.render(data)
        check_in("the retro prints it as a finding about the factory",
                 "**Finding about the factory:** the orchestrator spent 48 % of the story "
                 "(limit 35 %)", text)
        check_in("with the per-stage breakdown", "S5 34 %, S1 12 %", text)

        rows = D.orchestrator_shares([session(48.0)], [{"task": TASK, "pipeline": PIPELINE}], 35.0)
        check_eq("the banner carries one row for the one story", len(rows), 1)
        check_in("naming the story", TASK + ":", rows[0])
        check_in("and wording the threshold exactly as the retro does",
                 "the orchestrator spent 48 % of the story (limit 35 %)", rows[0])
        card = D.factory_health([session(48.0)], [], [], [], None, 35.0)
        check_in("the Factory health card gives the same 48 % from the same records",
                 "48%</div><div class='lbl'>orchestrator share of the cost", card)
        check_eq("a 20 % share yields no banner row at all",
                 D.orchestrator_shares([session(20.0)], [{"task": TASK, "pipeline": PIPELINE}], 35.0), [])
        check_eq("and an older story with no orchestrator receipts yields none either",
                 D.orchestrator_shares([{"requests": [request("2026-09-23T10:30:00Z", 9.0,
                                                              stream="agent-1")]}],
                                       [{"task": TASK, "pipeline": PIPELINE}], 35.0), [])
    finally:
        cleanup(root)


def the_card_names_the_limit_it_is_measured_against():
    sessions = [session(48.0)]
    html = D.factory_health(sessions, [], [], [], None, 35.0)
    check_in("the card states the limit beside the share", "limit 35 %", html)
    check_in("and is coloured as a finding when it is over it", "#F9303C", html)
    check_in("its tooltip says whose work the share is",
             "never a cost line the person is asked to repair", html)
    quiet = D.factory_health([session(20.0)], [], [], [], None, 35.0)
    check_not_in("a share under the limit is not coloured as one", "#F9303C", quiet)
    check_not_in("a render with no limit says nothing about one",
                 "limit", D.factory_health(sessions, [], [], []).split("repair rounds")[0]
                 .split("orchestrator share")[1])


def driver_project(root, task, rows):
    """A project under `root` whose story `task` ran on the driver: its journal holds `rows`. Returns
    (state folder, task folder), the two paths `retro_numbers.numbers` reads."""
    state = root / "qa-factory"
    troot = state / "artifacts" / task
    (troot / "state").mkdir(parents=True)
    (state / "state" / "cost").mkdir(parents=True)
    (state / "config.json").write_text("{}", encoding="utf-8")
    (troot / "state" / "driver-runs.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return state, troot


def a_driver_run_publishes_the_share_the_orchestrator_stream_cannot():
    """TP1-13797 ran on the driver: no request carries `stream: orchestrator`, so the share
    was `not computable` while the conductor's sessions held part of the story's money. The driver's
    own journal is the same split under another name: the conductor's record over every session's.
    The money of a role resumed after a question is the ROLE's spend, on its own line (owner, 30.09): the
    old "control layer" that added resumed roles to the conductor is gone."""
    root = temp_dir()
    try:
        rows = [{"kind": "conductor", "resumed": False, "total_cost_usd": 24.27, "stage": "S5", "session_id": "c1"},
                {"kind": "role", "role": "qa-automator", "dispatch": "D1", "resumed": False,
                 "total_cost_usd": 42.06, "stage": "S5", "session_id": "r1"},
                {"kind": "role", "role": "qa-automator", "dispatch": "D1", "resumed": True,
                 "total_cost_usd": 76.51, "stage": "S5", "session_id": "r1"}]
        state, troot = driver_project(root, "QA-DRIVER", rows)
        data = RN.numbers("QA-DRIVER", root=state, task_root=troot)
        check("the retro has no control-layer total any more", not hasattr(RN, "control_layer"))
        check_eq("the share is the conductor's record over every session's", data["orchestrator_share_percent"], 24.1)
        check_eq("a resumed role's extra work is the role's own spend", data["handed_back_to_roles"]["usd"], 34.45)
        text = RN.render(data)
        check_in("the retro prints it as the role spend line", "handed back to roles: $34.45", text)
        check_not_in("and never says the factory agreed with itself", "agreeing with itself", text)
    finally:
        cleanup(root)


def one_share_on_a_driver_run_the_banner_the_card_and_the_retro_agree():
    """R12: on a driver fixture the banner line, the Factory health card and the retro's finding give the SAME
    share, because they read the same records: the journal's, one per (session, dispatch), priced by the driver's
    own charge. The cost files of the fixture are priced by another table on purpose (the conductor's files
    at $30 each, the roles' at $10): a banner that read them would say 75 %, not 48 %."""
    root = temp_dir()
    task = "QA-DRIVER2"
    try:
        stamp = "2026-09-30T05:00:00+00:00"
        rows = [{"kind": "conductor", "total_cost_usd": 12.0, "stage": "S1", "session_id": "c1", "num_turns": 4, "ts": stamp},
                {"kind": "conductor", "total_cost_usd": 12.0, "stage": "S5", "session_id": "c2", "num_turns": 6, "ts": stamp},
                {"kind": "role", "role": "qa-scout", "dispatch": "S1-qa-scout-1", "total_cost_usd": 13.0, "stage": "S1",
                 "session_id": "r1", "num_turns": 30, "ts": stamp},
                {"kind": "role", "role": "qa-automator", "dispatch": "S5-qa-automator-1", "total_cost_usd": 13.0,
                 "stage": "S5", "session_id": "r2", "num_turns": 40, "ts": stamp}]
        state, troot = driver_project(root, task, rows)
        files = [cost_file(sid, usd, task) for sid, usd in (("c1", 30.0), ("c2", 30.0), ("r1", 10.0), ("r2", 10.0))]
        driver, _spread = D.parse_driver_runs(root)
        charged = D.root_charged(driver)[0]
        data = RN.numbers(task, root=state, task_root=troot)
        check_eq("the retro's share is the conductor's record over every session's", data["orchestrator_share_percent"], 48.0)
        finding = RN.orchestrator_finding(dict(data, orchestrator_share_limit_percent=35.0))
        check_in("the retro's finding says the share and the limit",
                 "the orchestrator spent 48 % of the story (limit 35 %)", finding)
        line = D.orchestrator_shares(files, [{"task": task, "pipeline": {}}], 35.0, driver, D.task_binding(driver), charged)
        check_eq("the banner carries one row for the one story", len(line), 1)
        check_eq("and it is the retro's own sentence, word for word", line[0] if line else None, task + ": " + finding)
        card = D.factory_health(files, [], [], [], None, 35.0, driver, charged)
        shown = re.search(r"<div class='val'>([^<]*)</div><div class='lbl'>orchestrator share of the cost", card)
        check_eq("the health card gives the same share", shown.group(1) if shown else None, "48%")
        check_in("and says it is $24.00 of the $50.00 the driver's record priced", "$24.00 of $50.00 priced", card)
        check_in("and that in a driver run the orchestrator is the conductor plus the driver's code",
                 "the orchestrator is the conductor plus the driver's code, and that code spends no model money", card)
        check_in("and how many sessions each record priced", "priced by the driver's record: 4 session(s), by the cost files: 0 session(s)", card)
    finally:
        cleanup(root)


def the_health_card_leaves_a_dispatch_of_unknown_cost_out_of_both_sums_and_counts_it():
    """C9: a pair the journal cannot price is in neither sum and is counted in the sub-text; with every session
    bound and no conductor record the share is 0 % and the card says so; with nothing priced it is a dash, not a
    division."""
    driver = {"c1": {"task": "T", "rows": [{"kind": "conductor", "total_cost_usd": 6.0, "num_turns": 3}]},
              "r1": {"task": "T", "rows": [{"kind": "role", "role": "qa-runner", "dispatch": "D", "total_cost_usd": 14.0,
                                            "num_turns": 9}]},
              "u1": {"task": "T", "rows": [{"kind": "role", "role": "qa-scout", "dispatch": "D", "total_cost_usd": None,
                                            "num_turns": 7}]}}
    charged = D.root_charged(driver)[0]
    card = D.factory_health([], [], [], [], None, None, driver, charged)
    check_in("the share is of the priced records only: $6 of $20", "$6.00 of $20.00 priced", card)
    check_in("and one dispatch of unknown cost is counted, not summed", "1 dispatch(es) of unknown cost left out of both sums", card)
    roles_only = {k: v for k, v in driver.items() if k != "c1"}
    card = D.factory_health([], [], [], [], None, None, roles_only, D.root_charged(roles_only)[0])
    check_in("every session bound and no conductor record: 0 %", "0%</div><div class='lbl'>orchestrator share", card)
    check_in("and the sub-text says there is no conductor record", "no conductor record: the share is 0%", card)
    nothing = {"u1": roles_only["u1"]}
    card = D.factory_health([], [], [], [], None, None, nothing, D.root_charged(nothing)[0])
    check_in("with nothing priced the share is a dash, never a division",
             chr(0x2014) + "</div><div class='lbl'>orchestrator share", card)


def the_rules_are_priced_in_the_same_currency_as_everything_else():
    """P7.5: a byte cap is a proxy, and two proxies cannot be compared.

    "The charter grew 300 bytes" and "the slice grew 3 KB" are the same sentence until both are
    dollars. A dispatch prompt is read on the first turn and re-read from cache on every turn
    after it, so what a layer costs is its bytes times the requests the role made, at the model's
    cache-read rate - and then the heaviest layer is a fact, not an impression.
    """
    rows = [{"role": "qa-code-critic", "requests": 40},
            {"role": "qa-automator", "requests": 60},
            {"role": "not-a-role-of-this-factory", "requests": 500}]
    weight = RN.rules_weight(rows, "claude-sonnet-4-5")
    check_eq("only the factory's own roles are priced", sorted(weight["by_role"]),
             ["qa-automator", "qa-code-critic"])
    check_eq("every request of every dispatch re-reads the prompt", weight["requests"], 100)
    check("the rate comes from the shipped catalogue, not from a constant",
          weight["rate_per_mtok"] == RN.cache_read_rate("claude-sonnet-4-5") > 0)
    layers = weight["by_layer"]
    check_eq("the four layers are priced separately", sorted(layers),
             ["brief", "charter", "common", "slices"])
    check("the slices are the most expensive layer, which is the whole point",
          layers["slices"] == max(layers.values()), str(layers))
    check("the charter is not", layers["charter"] < layers["slices"], str(layers))
    check("and the total is their sum",
          abs(weight["usd"] - sum(layers.values())) < 0.01, f"{weight['usd']} vs {layers}")
    text = RN.render({"task": "T", "story": {"usd": 100.78, "tokens": 1},
                      "orchestrator_share_percent": None, "rules_weight": weight})
    check_in("the retro prints it beside the price", "The rules cost", text)
    check_in("names the heaviest layer", "The heaviest is `slices`", text)
    check_in("and states the one approximation it makes", "4 bytes per token", text)
    check_eq("a story with no priced dispatch prints nothing at all", RN.rules_weight([]), {})


def main():
    the_limit_comes_from_the_config_with_a_default()
    a_driver_run_publishes_the_share_the_orchestrator_stream_cannot()
    one_share_on_a_driver_run_the_banner_the_card_and_the_retro_agree()
    the_health_card_leaves_a_dispatch_of_unknown_cost_out_of_both_sums_and_counts_it()
    the_rules_are_priced_in_the_same_currency_as_everything_else()
    the_split_is_placed_by_the_story_s_own_stage_clock()
    a_share_over_the_limit_is_a_finding_with_its_stages()
    the_retro_and_the_banner_say_the_same_sentence()
    the_card_names_the_limit_it_is_measured_against()
    finish("test_orchestrator_share")


if __name__ == "__main__":
    main()
