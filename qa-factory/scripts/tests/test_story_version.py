"""CL3-5 (t-640): `story_version.plugin_version_of` - the one reader of the plugin version a story's pipeline.json carries.
Expected values come from the node spec (run_mode first, top-level fallback, "" for none; FR-41), not from running the code (FR-58).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import SCRIPTS, check_eq, finish  # noqa: E402

sys.path.insert(0, str(SCRIPTS))
import story_version as V  # noqa: E402

# K1: the real shape (story_step.stamp_run_mode writes run_mode.plugin_version)
check_eq("K1 run_mode.plugin_version only -> read", V.plugin_version_of({"run_mode": {"mode": "plugin", "plugin_version": "0.10.0"}}), "0.10.0")
# K2: an older story has only the top-level key
check_eq("K2 top-level plugin_version only -> still read", V.plugin_version_of({"plugin_version": "0.8.0"}), "0.8.0")
# K3: neither -> "" and no crash, on every odd input
for name, pipe in (("empty dict", {}), ("None", None), ("a list", []), ("run_mode without the key", {"run_mode": {"mode": "plugin"}}),
                   ("empty strings", {"run_mode": {"plugin_version": ""}, "plugin_version": "  "}), ("non-string", {"plugin_version": 9})):
    check_eq(f"K3 neither ({name}) -> empty, no crash", V.plugin_version_of(pipe), "")
# K4: both, different -> run_mode wins
check_eq("K4 both differ -> run_mode's value", V.plugin_version_of({"run_mode": {"plugin_version": "0.10.0"}, "plugin_version": "0.9.0"}), "0.10.0")
# edges: run_mode not a dict is absent; run_mode with an empty version falls back to the top-level key
check_eq("run_mode not a dict -> top-level read", V.plugin_version_of({"run_mode": "plugin", "plugin_version": "0.9.0"}), "0.9.0")
check_eq("run_mode with an empty version -> top-level read", V.plugin_version_of({"run_mode": {"plugin_version": ""}, "plugin_version": "0.9.0"}), "0.9.0")
finish("test_story_version")
