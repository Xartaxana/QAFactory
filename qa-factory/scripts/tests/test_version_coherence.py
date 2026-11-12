"""hooklib.version_line - the four version carriers read by code (t-232 F-VERSION, section 7).

The plugin that runs (the cache copy), the marketplace it came from, the project's install manifest
and its readiness report drift apart silently: on one machine 0.7.9 ran while the marketplace had
0.7.19 and the project's readiness said 0.7.4, and nobody was told. One function reads them and
prints ONE line when the readable ones disagree; the SessionStart hook and onboarding's preflight
print the same line (FR-17). An unreadable carrier is `unknown` in the line, never a crash (FR-41).

Run: python -B scripts/tests/test_version_coherence.py
"""
import contextlib
import hashlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import check, check_eq, check_in, cleanup, finish, run_script, temp_dir  # noqa: E402

import config_contract  # noqa: E402
import hooklib  # noqa: E402
import install_paths as I  # noqa: E402
import onboard_apply as OA  # noqa: E402

UPDATE = ("`claude plugin uninstall qa-factory@qafactory`, `claude plugin marketplace update qafactory`, "
          "`claude plugin install qa-factory@qafactory`")


CURRENT = json.dumps(config_contract.canonical_template())   # the config as onboarding ships it: config_schema `ok`


def put(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def package(directory: Path, version) -> Path:
    body = {"name": "qa-factory", "version": version} if version is not None else {"name": "qa-factory"}
    put(directory / ".claude-plugin" / "plugin.json", json.dumps(body))
    return directory


class Machine:
    """A throwaway user: <home>/.claude with the cache, settings and marketplace, plus a project."""

    def __init__(self, cache="0.7.9", source="0.7.19", manifest=None, readiness=None, config="{}", market_name="qafactory"):
        self.market_name = market_name
        self.top = temp_dir("qa-versions-")
        self.home = self.top / "claude"
        self.market = self.top / "market"
        self.project = self.top / "project"
        self.plugin = package(self.home / "plugins" / "cache" / market_name / "qa-factory" / (cache or "0.0.0"), cache)
        put(self.home / "settings.json", json.dumps({"extraKnownMarketplaces": {market_name: {"source": {"source": "directory", "path": str(self.market)}}}}))
        put(self.market / ".claude-plugin" / "marketplace.json", json.dumps({"name": market_name, "plugins": [
            {"name": "other", "source": "./ai-packages/other"}, {"name": "qa-factory", "source": "./ai-packages/qa-factory"}]}))
        if source is not None:
            package(self.market / "ai-packages" / "qa-factory", source)
        (self.project / "qa-factory").mkdir(parents=True)
        if manifest is not None:
            put(self.project / "qa-factory" / "config.json", config)
            I.write_manifest(self.project, ["qa-factory/config.json"], plugin_root=package(self.top / "writer", manifest), table=I.load_table())
        if readiness is not None:
            put(self.project / "qa-factory" / "readiness.json", json.dumps({"runtime_paths": {"package_version": readiness}}))

    def line(self, **kw) -> str:
        return hooklib.version_line(self.project, plugin_root=kw.pop("plugin_root", self.plugin), claude_home=kw.pop("claude_home", self.home))

    def close(self) -> None:
        cleanup(self.top)


def this_machine() -> None:
    m = Machine(cache="0.7.9", source="0.7.19", manifest=None, readiness="0.7.4")
    try:
        got = m.line()
        check_eq("this machine's shape: cache 0.7.9, marketplace 0.7.19, no manifest, readiness 0.7.4: one line, the words of the spec",
                 got, "QA Factory versions differ: the factory running here is 0.7.9; the marketplace has 0.7.19; "
                      "this project has no record of an installation; its readiness report was written by 0.7.4 - "
                      f"update the plugin ({UPDATE}), restart, and run the onboarding again")
        check_eq("it is ONE line", "\n" in got, False)
        carriers = hooklib.version_carriers(m.project, plugin_root=m.plugin, claude_home=m.home)
        check_eq("FR-14: the four carriers, always the same keys", sorted(carriers), ["manifest", "readiness", "running", "source"])
        check_eq("...with their versions as read", {k: v["version"] for k, v in carriers.items()},
                 {"running": "0.7.9", "source": "0.7.19", "manifest": None, "readiness": "0.7.4"})
        check_eq("the running copy under the cache is not frozen", carriers["running"]["frozen"], False)
        check_eq("an absent manifest is `absent` (nothing to read), not `unreadable`", carriers["manifest"]["state"], "absent")
    finally:
        m.close()


def agreement_and_direction() -> None:
    m = Machine(cache="0.7.19", source="0.7.19", manifest="0.7.19", readiness="0.7.19")
    try:
        check_eq("all four equal: no line", m.line(), "")
    finally:
        m.close()
    only_one = Machine(cache="0.7.19", source=None)
    try:
        check_eq("one readable carrier only (no marketplace, no manifest, no readiness): nothing to compare, no line", only_one.line(), "")
    finally:
        only_one.close()
    stale_project = Machine(cache="0.7.19", source="0.7.19", manifest="0.7.19", readiness="0.7.4")   # config "{}": needs a migration
    try:
        got = stale_project.line()
        check_in("only the readiness report is stale and the config needs a migration: the line says so", "its readiness report was written by 0.7.4", got)
        check("...and the one move is the onboarding, not a plugin update", got.endswith(" - run the onboarding again") and "claude plugin" not in got, got)
    finally:
        stale_project.close()
    stale_current = Machine(cache="0.7.19", source="0.7.19", manifest="0.7.19", readiness="0.7.4", config=CURRENT)
    try:
        check_eq("only the readiness report is stale but the config is current (AR-3): no line", stale_current.line(), "")
    finally:
        stale_current.close()
    older_project = Machine(cache="0.7.19", source="0.7.19", manifest="0.7.4", readiness=None)   # config "{}": needs a migration
    try:
        got = older_project.line()
        check_in("the project was installed by an older factory and its config needs a migration: named", "this project was installed by 0.7.4", got)
        check("...and the move is the onboarding", got.endswith("run the onboarding again") and "claude plugin" not in got, got)
    finally:
        older_project.close()
    release_bump = Machine(cache="0.10.5", source="0.10.5", manifest="0.10.3", readiness="0.10.3", config=CURRENT)
    try:
        check_eq("K1/E1: installed by 0.10.3, plugin and marketplace 0.10.5, the config is current: NO line (AR-3)", release_bump.line(), "")
    finally:
        release_bump.close()
    newer_project = Machine(cache="0.7.9", source="0.7.9", manifest="0.7.19", readiness=None)
    try:
        got = newer_project.line()
        check("a newer factory wrote the project: the plugin is the one behind, the update words follow", UPDATE in got, got)
    finally:
        newer_project.close()
    market_behind = Machine(cache="0.7.19", source="0.7.9", manifest="0.7.19", readiness="0.7.19")
    try:
        got = market_behind.line()
        check("a marketplace behind the running copy is stated and asks for nothing (nothing to update here)",
              "the marketplace has 0.7.9" in got and "claude plugin" not in got and "onboarding" not in got, got)
    finally:
        market_behind.close()


def migration_gates_the_project_side() -> None:
    """OH1-11: an older project is told to re-onboard only when its configuration needs a migration (AR-3);
    silence only on a positive `ok` read from a config that was read, every doubt prints (FR-59)."""
    def older(config, **kw):
        return Machine(cache="0.10.5", source="0.10.5", manifest="0.10.3", readiness="0.10.3", config=config, **kw)

    def prints(label, m, mutate=None):
        try:
            if mutate:
                mutate(m)
            got = m.line()
            check(label, got.endswith(" - run the onboarding again") and "this project was installed by 0.10.3" in got, got)
        finally:
            m.close()

    prints("E2: the config needs a migration ({}): the line, with the onboarding advice", older("{}"))
    template = json.loads(CURRENT)
    stale_version = dict(template, schema_version=template["schema_version"] + 7)
    import readiness as R
    dropped = [k for k in R.template_top_keys() if k not in ("schema_version", "cost", "impact_scale")][-1]   # required, and not filled by readiness's runtime defaults (m-1)
    lacking = {k: v for k, v in template.items() if k != dropped}
    prints("E3: no config.json at all: not established, the line prints", older(CURRENT), lambda m: os.unlink(m.project / "qa-factory" / "config.json"))
    prints("E3: config.json is not JSON: the line prints", older("{ not json"))
    prints("E3: config.json is a JSON list: the line prints", older("[1, 2]"))
    prints("E3: config.json is empty: the line prints", older(""))
    prints("E2: schema_version other than the required one: the line prints", older(json.dumps(stale_version)))
    prints("E2: a template top key missing: the line prints", older(json.dumps(lacking)))

    # m-1: readiness reports the EFFECTIVE config; a config lacking keys it fills (cost, impact_scale) is `ok`
    for optional in ("cost", "impact_scale"):
        if optional in template:
            trimmed = {k: v for k, v in template.items() if k != optional}
            quiet = older(json.dumps(trimmed))
            try:
                check_eq(f"m-1: a current config lacking `{optional}` (readiness fills it): no line", quiet.line(), "")
            finally:
                quiet.close()
    # B-3 (FR-59): an unreadable install record is an unknown; a current config never silences it
    ok_manifest = older(CURRENT)
    try:
        check_eq("B-3 AT: valid manifest, readiness older, current config: silent", ok_manifest.line(), "")
    finally:
        ok_manifest.close()
    broken = older(CURRENT)
    try:
        put(broken.project / "qa-factory" / "install-manifest.json", "{ broken")
        got = broken.line()
        check("B-3 BEYOND: manifest unreadable + readiness older + current config: the line prints, naming `unknown`",
              "installed by unknown" in got and got.endswith(" - run the onboarding again"), got)
    finally:
        broken.close()
    prints("B-3: readiness unreadable (no version) + manifest older + current config: the line prints", older(CURRENT),
           lambda m: put(m.project / "qa-factory" / "readiness.json", "{ broken"))

    real = R.check_config_schema

    def boom(cfg):
        raise RuntimeError("schema check broke")
    R.check_config_schema = boom
    try:
        prints("E3: check_config_schema raising: the line prints", older(CURRENT))
    finally:
        R.check_config_schema = real

    behind = Machine(cache="0.10.5", source="0.10.9", manifest="0.10.3", readiness=None, config=CURRENT)
    try:
        got = behind.line()
        check("K3/E4: the plugin is behind and the config is current: the line still prints, with the update advice",
              UPDATE in got and got.startswith("QA Factory versions differ: "), got)
    finally:
        behind.close()
    newer = Machine(cache="0.10.5", source="0.10.5", manifest="0.10.9", readiness=None, config=CURRENT)
    try:
        check_in("E4: the project was written by a newer factory (current config): the update advice stays", UPDATE, newer.line())
    finally:
        newer.close()
    market = Machine(cache="0.10.5", source="0.10.3", manifest="0.10.3", readiness="0.10.3", config=CURRENT)
    try:
        check_in("F-4: a marketplace older than the running copy is not explained by the project side: the line prints",
                 "the marketplace has 0.10.3", market.line())
    finally:
        market.close()
    frozen = older(CURRENT)
    try:
        old_frozen = package(frozen.top / "Temp" / "qa-factory-frozen", "0.10.5")
        check_in("E5: a frozen package that differs from the project's carriers still names itself",
                 "a frozen package", frozen.line(plugin_root=old_frozen))
    finally:
        frozen.close()

    # E7 / position invariant: the config is read only when the project side alone disagrees
    real_helper = hooklib._project_needs_migration

    def never(project):
        raise AssertionError("the config must not be read here")
    hooklib._project_needs_migration = never
    agree = Machine(cache="0.10.5", source="0.10.5", manifest="0.10.5", readiness="0.10.5", config=CURRENT)
    behind = Machine(cache="0.10.5", source="0.10.9", manifest="0.10.3", readiness=None, config=CURRENT)
    try:
        check_eq("E7: all carriers agree: no line, and the config is never read", agree.line(), "")
        check("E7/E4: the plugin is behind: the line prints without reading the config", UPDATE in behind.line())
    finally:
        hooklib._project_needs_migration = real_helper
        agree.close()
        behind.close()


def conductor_twin_of_the_driver_line() -> None:
    """K4 (B-2, SIBLING_MAP row 127): s3.md tells the conductor to write the SAME prefixed base_slice line as `s3_prepare`."""
    here = Path(__file__).resolve().parent.parent
    phase = (here.parent / "skills" / "qa-story" / "phases" / "s3.md").read_text(encoding="utf-8")
    driver = (here / "story_run.py").read_text(encoding="utf-8")
    words = "base_slice: unknown - S3 preparation: base_slice.py exited"
    check_in("K4: s3.md dictates the prefixed `base_slice: unknown - ...` line", '--warn "' + words, phase)
    check_in("K4: the driver writes the same words", words, driver)


def frozen_package() -> None:
    m = Machine(cache="0.7.9", source="0.7.19", manifest="0.7.19", readiness="0.7.19")
    try:
        frozen = package(m.top / "Temp" / "qa-factory-frozen", "0.7.19")
        got = m.line(plugin_root=frozen)
        carriers = hooklib.version_carriers(m.project, plugin_root=frozen, claude_home=m.home)
        check_eq("a package outside the cache is frozen", carriers["running"]["frozen"], True)
        check_eq("frozen and every carrier agrees: no line (an experiment's copy is a declared exception)", got, "")
        old = package(m.top / "Temp" / "qa-factory-old", "0.7.4")
        got = m.line(plugin_root=old)
        check_in("a frozen package that differs names itself as one, with its path", "the factory running here is a frozen package: ", got)
        check_in("...the path is the frozen package's", str(old).replace("\\", "/"), got)
        check_in("...and its own version", "(0.7.4)", got)
    finally:
        m.close()


def unreadable_is_unknown_never_a_crash() -> None:
    # each carrier broken on its own, while another readable one keeps disagreeing with the running copy
    m = Machine(cache="0.7.9", source="0.7.19", manifest="0.7.4", readiness=None)
    try:
        put(m.market / "ai-packages" / "qa-factory" / ".claude-plugin" / "plugin.json", "{ not json")
        check_in("an unreadable marketplace package is `unknown` in the line", "the marketplace has unknown", m.line())
        (m.home / "settings.json").write_text("[ not a settings object ]", encoding="utf-8")
        got = m.line()
        check("garbage settings.json: no crash, still one line, the marketplace unknown", "\n" not in got and "the marketplace has unknown" in got, got)
        os.unlink(m.home / "settings.json")
        check("no settings.json and no known_marketplaces: the marketplace is unknown, no crash", "the marketplace has unknown" in m.line())
        check_eq("no project at all: the project's clauses are left out, no crash",
                 "project" in hooklib.version_line(None, plugin_root=m.plugin, claude_home=m.home), False)
        check_eq("a home that does not exist: no crash", isinstance(hooklib.version_line(m.project, plugin_root=m.plugin, claude_home=m.top / "nowhere"), str), True)
    finally:
        m.close()
    m = Machine(cache="0.7.9", source="0.7.19", manifest="0.7.4", readiness=None)
    try:
        os.unlink(m.plugin / ".claude-plugin" / "plugin.json")
        check_in("the running copy unreadable: `unknown`, not a crash", "the factory running here is unknown", m.line())
        check_eq("...and with the running version unknown there is no basis to say which side is behind: no update words",
                 "claude plugin" in m.line(), False)
    finally:
        m.close()
    m = Machine(cache="0.7.9", source="0.7.19", manifest=None, readiness=None)
    try:
        put(m.project / "qa-factory" / "install-manifest.json", "{ not json")
        check_in("an unreadable manifest is `unknown` in the line", "this project was installed by unknown", m.line())
        put(m.project / "qa-factory" / "readiness.json", "[1, 2]")
        check_in("an unreadable readiness report is `unknown` in the line", "its readiness report was written by unknown", m.line())
    finally:
        m.close()
    m = Machine(cache="0.7.19", source="0.7.19", manifest="0.7.19", readiness="0.7.19")
    try:
        put(m.market / "ai-packages" / "qa-factory" / ".claude-plugin" / "plugin.json", "{ not json")
        check_eq("one unreadable carrier and the readable ones agree: no line (unknown is not a disagreement)", m.line(), "")
    finally:
        m.close()


def marketplace_by_known_marketplaces() -> None:
    m = Machine(cache="0.7.9", source="0.7.19", manifest=None, readiness=None)
    try:
        os.unlink(m.home / "settings.json")
        put(m.home / "plugins" / "known_marketplaces.json", json.dumps({m.market_name: {"installLocation": str(m.market)}}))
        check_in("without settings.json the marketplace is found by known_marketplaces.json", "the marketplace has 0.7.19", m.line())
    finally:
        m.close()


def two_callers_one_implementation() -> None:
    m = Machine(cache="0.7.9", source="0.7.19", manifest=None, readiness="0.7.4")
    try:
        want = m.line()
        pre = OA.preflight(m.project, plugin_root=m.plugin, claude_home=m.home)
        check_eq("FR-17: onboarding's preflight prints the very line the hook function makes", pre["version_line"], want)
        sid = uuid.uuid4().hex      # a fresh id every run: the once-per-session marker lives in the OS temp directory
        event = {"session_id": f"versions-test-{sid}-1"}
        with hooklib.selftest_root_restored():
            hooklib.pin_project_root(m.project)
            put(m.project / "qa-factory" / "config.json", "{}")
            first = hooklib.session_start_version_line(event, plugin_root=m.plugin, claude_home=m.home)
            second = hooklib.session_start_version_line(event, plugin_root=m.plugin, claude_home=m.home)
            other = hooklib.session_start_version_line({"session_id": f"versions-test-{sid}-2"}, plugin_root=m.plugin, claude_home=m.home)
            anon_a = hooklib.session_start_version_line({}, plugin_root=m.plugin, claude_home=m.home)
            anon_b = hooklib.session_start_version_line(None, plugin_root=m.plugin, claude_home=m.home)
        check_eq("the SessionStart line is printed once per session: the first call has it, the second is empty", (bool(first), second), (True, ""))
        check_eq("...another session gets it again", bool(other), True)
        check_eq("...a call with no session id cannot be deduplicated, so it prints (noise beats silence)", (bool(anon_a), bool(anon_b)), (True, True))
        check_in("the session line is the same words", "the factory running here is 0.7.9", first)
        agree = Machine(cache="0.7.19", source="0.7.19", manifest="0.7.19", readiness="0.7.19")
        try:
            with hooklib.selftest_root_restored():
                hooklib.pin_project_root(agree.project)
                check_eq("agreeing versions: the hook function says nothing",
                         hooklib.session_start_version_line({"session_id": f"versions-test-{sid}-3"}, plugin_root=agree.plugin, claude_home=agree.home), "")
        finally:
            agree.close()
        broken = hooklib.session_start_version_line({"session_id": f"versions-test-{sid}-4"}, plugin_root=m.top / "no-such-plugin", claude_home=m.top / "no-such-home")
        check_eq("a version note never stops a session: nothing readable is a string, not a crash", isinstance(broken, str), True)
        out = run_script("onboard_apply.py", "--root", m.project, "--preflight")
        check("the command line preflight carries the key (the real machine's value is its own)", "version_line" in json.loads(out.stdout), out.stderr[-300:])
    finally:
        m.close()
        for n in (1, 2, 3, 4):      # the markers the calls above left in the OS temp directory
            digest = hashlib.sha1(f"versions-test-{sid}-{n}".encode("utf-8")).hexdigest()[:16]
            with contextlib.suppress(OSError):
                os.unlink(Path(tempfile.gettempdir()) / f"qa-factory-version-{digest}")


def marketplace_name_comes_from_the_install_path() -> None:
    check_eq("O5: the fallback marketplace is qafactory", hooklib.VERSION_MARKETPLACE, "qafactory")
    m = Machine(cache="0.7.9", source="0.7.19", market_name="old-market")
    try:
        got = m.line()
        check_in("a cached copy reports the marketplace of its own install path", "qa-factory@old-market", got)
        check("...and not the fallback constant", "qafactory" not in got, got)
        frozen = package(m.top / "Temp" / "qa-factory-frozen", "0.7.4")
        carriers = hooklib.version_carriers(m.project, plugin_root=frozen, claude_home=m.home)
        check_eq("a copy outside the cache looks for the fallback marketplace, which this machine lacks: absent", carriers["source"]["state"], "absent")
        line = m.line(plugin_root=frozen)
        check("...and the line never advises a marketplace this machine does not have", "claude plugin" not in line, line)
    finally:
        m.close()


def main() -> None:
    this_machine()
    agreement_and_direction()
    migration_gates_the_project_side()
    conductor_twin_of_the_driver_line()
    frozen_package()
    unreadable_is_unknown_never_a_crash()
    marketplace_by_known_marketplaces()
    marketplace_name_comes_from_the_install_path()
    two_callers_one_implementation()
    finish("test_version_coherence")


if __name__ == "__main__":
    main()
