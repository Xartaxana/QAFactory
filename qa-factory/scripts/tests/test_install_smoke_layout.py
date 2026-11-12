"""The smoke survives a plugin root that lies inside an onboarded project (macOS 0.7.11).

Two defects, both invisible from Windows development: the launcher probe passed a LIST with
shell=True (on POSIX that is ["/bin/sh","-c"] + args — the launcher gets zero arguments), and
the isolated self-tests ran with cwd=PLUGIN_ROOT, which on that install lay inside the user's
own project, so they read and wrote against the user's real stories.

Nothing real is spawned here: every subprocess.run is answered by a recorder. The full smoke
takes minutes and is the integrator's run, not a unit test's.
"""
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_smoke


class Recorder:
    """Answers exit 0 to every child and keeps what the smoke asked for."""

    def __init__(self):
        self.calls = []
        self.roots = []  # per call: (cwd, the project that cwd resolves to, or None)

    def __call__(self, cmd, **kwargs):
        cwd = kwargs.get("cwd")
        # Resolved here and not afterwards: the smoke's sandbox is gone by then, and a
        # marker check against a deleted directory answers None whatever the layout was.
        self.calls.append((cmd, kwargs))
        self.roots.append((Path(cwd).resolve(), install_smoke.project_above(cwd)) if cwd else None)
        return subprocess.CompletedProcess(cmd, 0, "", "")


def fake_plugin_root(base: Path, *, inside_project: bool) -> Path:
    """A plugin root with the two files main() reads, optionally nested in a real project."""
    project = base / "deathstroke"
    if inside_project:
        (project / "qa-factory").mkdir(parents=True)
        (project / "qa-factory" / "config.json").write_text("{}", encoding="utf-8")
        root = project / "QAFactory" / "qa-factory"
    else:
        root = base / "qa-factory-plugin"
    (root / "references" / "templates").mkdir(parents=True)
    (root / "references" / "templates" / "config.json").write_text("{}", encoding="utf-8")
    (root / "hooks").mkdir(parents=True)
    (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"PreCompact": [
        {"hooks": [{"command": '"${CLAUDE_PLUGIN_ROOT}/hooks/run-py.cmd" compact_hook.py'}]}
    ]}}), encoding="utf-8")
    return root


def drive(plugin_root: Path):
    """Run main() against a faked child layer; it exits 1 (no cost file was written)."""
    recorder, out = Recorder(), io.StringIO()
    with patch.object(install_smoke, "PLUGIN_ROOT", plugin_root), \
            patch.object(install_smoke, "SCRIPTS", plugin_root / "scripts"), \
            patch("subprocess.run", recorder), contextlib.redirect_stdout(out):
        with contextlib.suppress(SystemExit):
            install_smoke.main()
    return recorder, out.getvalue()


class LauncherProbe(unittest.TestCase):
    def test_probe_is_one_string_like_the_hooks_json_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_plugin_root(Path(tmp), inside_project=False)
            recorder, _ = drive(root)
        probes = [(cmd, kwargs) for cmd, kwargs in recorder.calls
                  if "subagent_journal.py" in (cmd if isinstance(cmd, str)
                                               else " ".join(str(part) for part in cmd))]
        self.assertEqual(len(probes), 1, "the minimal-PATH launcher probe never ran")
        cmd, kwargs = probes[0]
        self.assertIsInstance(cmd, str, "a list with shell=True leaves the launcher "
                                        "argumentless on POSIX")
        self.assertTrue(kwargs.get("shell"), "the .cmd launcher needs a shell on Windows")
        self.assertIn(f'"{root / "hooks" / "run-py.cmd"}"', cmd)
        self.assertTrue(cmd.endswith("subagent_journal.py"))
        for call_cmd, call_kwargs in recorder.calls:
            # On POSIX a list with shell=True hands the child zero arguments.
            self.assertFalse(call_kwargs.get("shell") and isinstance(call_cmd, list),
                             f"list + shell=True: {call_cmd}")


class PluginRootInsideAProject(unittest.TestCase):
    def test_isolated_runs_take_a_neutral_cwd_and_the_layout_is_said_out_loud(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_plugin_root(Path(tmp), inside_project=True)
            user_project = Path(tmp).resolve() / "deathstroke"
            recorder, output = drive(root)

            seen = [entry for entry in recorder.roots if entry]
            self.assertTrue(seen, "the smoke spawned nothing")
            for cwd, root in seen:
                self.assertNotEqual(cwd, user_project)
                self.assertNotIn(user_project, cwd.parents,
                                 f"a child ran inside the user's project: {cwd}")
                self.assertNotEqual(root, user_project,
                                    f"a child would resolve the user's project from {cwd}")
            # The self-tests' cwd carries no marker at all, so each resolves its own temp root.
            self.assertTrue([cwd for cwd, root in seen if root is None],
                            "no child ran from a directory free of a project marker")

            info = [line for line in output.splitlines() if line.startswith("INFO ")
                    and "plugin root sits inside" in line]
            self.assertEqual(len(info), 1, output)
            self.assertIn(str(user_project), info[0])
            self.assertNotIn("FAIL", info[0])


class AgentLaunchPayload(unittest.TestCase):
    """RN1-1 B-2 (FR-33): the smoke DRIVES the Agent path - only the entries whose matcher names `Agent` get the launch of the
    probe child with the host's real answer, over a probe store it prepared; the Read payload goes to the others."""
    def test_agent_matcher_entries_get_the_launch_and_only_they(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fake_plugin_root(Path(tmp), inside_project=False)
            run = '"${CLAUDE_PLUGIN_ROOT}/hooks/run-py.cmd" '
            (root / "hooks" / "hooks.json").write_text(json.dumps({"hooks": {"PostToolUse": [
                {"matcher": "Agent|Task", "hooks": [{"command": run + "agent_autobind.py"}]},
                {"matcher": "Write|Edit", "hooks": [{"command": run + "other_post.py"}]}]}}), encoding="utf-8")
            recorder, _ = drive(root)
        sent = {cmd.split()[-1]: json.loads(kwargs["input"]) for cmd, kwargs in recorder.calls
                if isinstance(cmd, str) and "input" in kwargs and cmd.split()[-1] in ("agent_autobind.py", "other_post.py")}
        agent = sent["agent_autobind.py"]
        self.assertEqual((agent["tool_name"], agent["tool_use_id"], agent["tool_response"].get("agentId")),
                         ("Agent", "smoke-spawn", "smoke-agent"))
        self.assertEqual(sent["other_post.py"]["tool_name"], "Read", "a non-Agent entry keeps the Read payload")
        self.assertNotIn("agentId", sent["other_post.py"].get("tool_response", {}))


if __name__ == "__main__":
    unittest.main()
