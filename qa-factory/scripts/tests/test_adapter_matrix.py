"""OH3-30: the adapter capability matrix and `supported_capabilities` - a profile is not read `unsupported` because the matrix
was never filled, and a configuration of a foreign shape never raises in the readiness reader.

Keys of the battery: A-sample A-empty A-unknown-word A-hostile A-wiring A-human, through `profile_contract.profile_readiness` /
`capability_gaps` and the onboarding listing (`onboard_apply.py --listing`).
"""
import copy
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check, check_eq, check_in, check_not_in, cleanup, finish, run_script, temp_dir  # noqa: E402

sys.path.insert(0, str(SCRIPTS))

import config_contract as C  # noqa: E402
import human_text  # noqa: E402
import onboard_apply as OA  # noqa: E402
import profile_contract as PC  # noqa: E402

REFERENCES = SCRIPTS.parent / "references"
SAMPLE = json.loads((REFERENCES / "profile-shape.json").read_text(encoding="utf-8"))
TEMPLATE = C.canonical_template()
P4 = SCRIPTS.parent / "skills" / "qa-onboarding" / "phases" / "p4-generate.md"
NOT_READY = "will read as not ready"


def cap_gaps(result: dict) -> list:
    return [g for g in result.get("gaps", []) if "capability" in g]


def runnable(profile_id: str = "api", **fields) -> dict:
    """A profile whose command exists on any machine (this interpreter): only the capability can make it not ready."""
    return {"profile_id": profile_id, "adapter_id": "native", "capabilities": ["web"], "roots": {"test": "tests"},
            "commands": {"one_test": {"kind": "test", "scope": "selected", "argv": [sys.executable, "{selector}"], "cwd": "."}},
            **fields}


def config(**fields) -> dict:
    return {"supported_capabilities": ["web", "api"], "adapter_capabilities": {"native": ["web", "api"]},
            "profiles": [runnable()], **fields}


def sample_and_empty_and_word(root: Path) -> None:
    sample_cfg = {"supported_capabilities": TEMPLATE["supported_capabilities"],
                  "adapter_capabilities": SAMPLE["adapter_capabilities"], "profiles": [SAMPLE["profile"]]}
    got = PC.profile_readiness(sample_cfg, root=root)["web-tests"]
    check_eq("A-sample: the sample, its matrix and the template's supported words leave no capability gap", cap_gaps(got), [])
    check_eq("A-sample: the sample's dependency names the same word the profile does",
             SAMPLE["managed_dependency"]["capability"], SAMPLE["profile"]["capabilities"][0])
    check_in("A-sample: the word is one the template knows", SAMPLE["profile"]["capabilities"][0],
             TEMPLATE["supported_capabilities"])
    check_eq("A-sample: the sample's own project config is accepted by the profile gate",
             PC.validate_config({"profiles": [SAMPLE["profile"]], "implementation_repos": [SAMPLE["implementation_repo"]],
                                 "managed_dependencies": [SAMPLE["managed_dependency"]]}), [])
    check_eq("A-sample: control - the matrix is what makes it so (an empty one leaves the gap)",
             [g["status"] for g in cap_gaps(PC.profile_readiness(dict(sample_cfg, adapter_capabilities={}), root=root)["web-tests"])],
             ["unknown"])

    ready = PC.profile_readiness(config(), root=root)["api"]
    check_eq("A-sample: control - a complete configuration is ready", ready["status"], "ready")
    empty = PC.profile_readiness(config(adapter_capabilities={}), root=root)["api"]
    check_eq("A-empty: `adapter_capabilities: {}` reads the profile unknown", empty["status"], "unknown")
    absent = {k: v for k, v in config().items() if k != "adapter_capabilities"}
    check_eq("A-empty: ... and so does a configuration with no such key", PC.profile_readiness(absent, root=root)["api"]["status"],
             "unknown")
    word = PC.profile_readiness(config(profiles=[runnable(capabilities=["e2e-ui"])]), root=root)["api"]
    check_eq("A-unknown-word: `e2e-ui` (a level, not a capability) reads unsupported", word["status"], "unsupported")
    check_eq("A-unknown-word: the gap names the word", [g["capability"] for g in cap_gaps(word)], ["e2e-ui"])
    check_in("A-unknown-word: its note says why", "supported catalogue", cap_gaps(word)[0]["note"])
    lines = OA._capability_lines(config(profiles=[runnable("web-tests", capabilities=["e2e-ui"])]))
    check_in("A-unknown-word: the listing line names the word", "`e2e-ui`", "\n".join(lines))
    check_in("A-empty: the listing line says the profile reads not ready", NOT_READY,
             "\n".join(OA._capability_lines(config(adapter_capabilities={}))))
    check_eq("A-empty: no profiles, no line", OA._capability_lines(config(profiles=[])), [])
    check_eq("A-empty: a complete matrix, no line", OA._capability_lines(config()), [])
    check_eq("A-empty: nothing to read, no line (not a config / profiles not a list)",
             (OA._capability_lines(None), OA._capability_lines({"profiles": 5})), ([], []))


HOSTILE = [
    ("capabilities-has-list", {"capabilities": [[]]}, {}),
    ("capabilities-has-dict", {"capabilities": [{}]}, {}),
    ("capabilities-has-number", {"capabilities": [5]}, {}),
    ("capabilities-is-number", {"capabilities": 5}, {}),
    ("capabilities-is-object", {"capabilities": {"web": 1}}, {}),
    ("supported-is-number", {}, {"supported_capabilities": 5}),
    ("supported-is-string", {}, {"supported_capabilities": "web"}),
    ("supported-has-list", {}, {"supported_capabilities": ["web", []]}),
    ("matrix-is-list", {}, {"adapter_capabilities": ["web"]}),
    ("matrix-is-number", {}, {"adapter_capabilities": 5}),
    ("adapter-id-is-list", {"adapter_id": ["native"]}, {}),
    ("adapter-id-is-object", {"adapter_id": {"a": 1}}, {}),
]


def hostile(root: Path) -> None:
    for name, profile_fields, cfg_fields in HOSTILE:
        cfg = config(**cfg_fields)
        cfg["profiles"] = [runnable(**profile_fields)]
        try:
            got = PC.profile_readiness(cfg, root=root)["api"]
        except Exception as exc:        # noqa: BLE001 - the key is exactly that nothing is raised
            check(f"A-hostile[{name}]: does not raise", False, repr(exc))
            continue
        check(f"A-hostile[{name}]: the status is not ready", got["status"] != "ready", str(got))
        check(f"A-hostile[{name}]: a capability gap says why", bool(cap_gaps(got)) and all(
            isinstance(g["capability"], str) and g["note"] for g in cap_gaps(got)), str(got))
        try:
            OA._capability_lines(cfg)
        except Exception as exc:        # noqa: BLE001
            check(f"A-hostile[{name}]: the listing line does not raise", False, repr(exc))
    huge = [[[[]]]]
    for _ in range(50):
        huge = [huge]
    deep = PC.profile_readiness(config(profiles=[runnable(capabilities=huge)]), root=root)["api"]
    check("A-hostile[deep-nesting]: depth 50 is a gap, not a raise", deep["status"] != "ready" and len(cap_gaps(deep)[0]["capability"]) <= 80)

    repos = [{"repo_id": "r", "role": "tests", "local_path": ".", "remote_identity": "o", "source_ref": "refs/heads/main",
              "source_sha": "a" * 40, "write_target": False, "readiness_evidence": [], "execution_profile_id": "api"}]
    base = config()
    ok = PC.implementation_repo_readiness(base, PC.profile_readiness(base, root=root), root)
    check_eq("A-hostile[execution_profile_id]: control - a str id on a ready profile is ready",
             [r["status"] for r in PC.implementation_repo_readiness(dict(base, implementation_repos=repos),
                                                                    PC.profile_readiness(base, root=root), root)], ["ready"])
    check_eq("A-hostile[execution_profile_id]: no repos, no records", ok, [])
    for label, bad in (("list", ["api"]), ("object", {"a": 1}), ("number", 5)):
        cfg = dict(base, implementation_repos=[dict(repos[0], execution_profile_id=bad)])
        try:
            records = PC.implementation_repo_readiness(cfg, PC.profile_readiness(cfg, root=root), root)
        except Exception as exc:        # noqa: BLE001
            check(f"A-hostile[execution_profile_id={label}]: does not raise", False, repr(exc))
            continue
        check(f"A-hostile[execution_profile_id={label}]: the status is not ready", records[0]["status"] != "ready", str(records))


def wiring() -> None:
    text = P4.read_text(encoding="utf-8")
    check_in("A-wiring: p4 tells the role to write `adapter_capabilities`", "adapter_capabilities", text)
    check_in("A-wiring: ... and never to infer from the framework's name", "Never infer", text)
    check_not_in("A-wiring: the old one-clause 'adapter capability matrix, ' is gone", "adapter capability matrix, ", text)
    check_in("A-wiring: the shape's note names the key", "adapter_capabilities", SAMPLE["note"])
    check_eq("A-wiring: the sample's key is the top-level one", SAMPLE["adapter_capabilities"],
             {SAMPLE["profile"]["adapter_id"]: SAMPLE["profile"]["capabilities"]})


def cli(root: Path, config_in: dict, *args, env=None):
    proposal = root.parent / f"{root.name}-proposal.json"
    proposal.write_text(json.dumps({"proposed_config": config_in}), encoding="utf-8")
    return run_script("onboard_apply.py", "--root", root, "--proposal", proposal, *args, env=env)


def proposed(profile_id: str = "web-tests", matrix=None) -> dict:
    profile = dict(copy.deepcopy(SAMPLE["profile"]), profile_id=profile_id)
    repo = dict(copy.deepcopy(SAMPLE["implementation_repo"]), execution_profile_id=profile_id)
    out = {"schema_version": 1, "app_root": "src", "tests_root": "tests", "profiles": [profile],
           "implementation_repos": [repo], "managed_dependencies": [copy.deepcopy(SAMPLE["managed_dependency"])]}
    if matrix is not None:
        out["adapter_capabilities"] = matrix
    return out


def human_and_listing() -> None:
    line = OA._capability_lines(config(profiles=[runnable("web-tests", capabilities=["web"])], adapter_capabilities={}))[0]
    check_eq("A-human: the line is the sentence the spec names",
             line, "The test profile `web-tests` will read as not ready: nothing in the configuration says its tool can do `web`.")
    check_eq("A-human: it breaks no rule of the report form", human_text.problems(line, kind="report"), [])

    root = temp_dir("qa-matrix-")
    (root / ".git").mkdir()
    try:
        empty = cli(root, proposed(), "--listing")
        check("A-empty: the listing runs (exit 0)", empty.returncode == 0, empty.stderr[-400:])
        check_in("A-empty: with the template's empty matrix the listing names the profile", "`web-tests`", empty.stdout)
        check_in("A-empty: ... and says it reads not ready", NOT_READY, empty.stdout)
        full = cli(root, proposed(matrix=SAMPLE["adapter_capabilities"]), "--listing")
        check("A-sample: the sample's own matrix: the listing runs (exit 0)", full.returncode == 0, full.stderr[-400:])
        check_not_in("A-sample: ... and has no not-ready line", NOT_READY, full.stdout)
        none = cli(root, dict(proposed(), profiles=[], implementation_repos=[], managed_dependencies=[]), "--listing")
        check("A-empty: `profiles: []` lists (exit 0)", none.returncode == 0, none.stderr[-400:])
        check_not_in("A-empty: ... with no not-ready line", NOT_READY, none.stdout)
        ascii_env = dict(os.environ, PYTHONIOENCODING="ascii")
        cyr = cli(root, proposed("".join(chr(c) for c in (0x442, 0x435, 0x441, 0x442))), "--listing", env=ascii_env)
        check("A-human: a Cyrillic profile id under PYTHONIOENCODING=ascii has no traceback",
              "Traceback" not in cyr.stderr, cyr.stderr[-400:])
    finally:
        cleanup(root)


def main() -> None:
    root = temp_dir("qa-matrix-root-")
    try:
        sample_and_empty_and_word(root)
        hostile(root)
        wiring()
        human_and_listing()
    finally:
        cleanup(root)
    finish("test_adapter_matrix")


if __name__ == "__main__":
    main()
