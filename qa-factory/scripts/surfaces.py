#!/usr/bin/env python3
"""The one reader of references/surfaces.json: what the factory can test on, who holds the hands, how a stand is told (EP1-41a).

The table is closed variety (FR-13, AR-1); this file carries no platform name, no language and no test runner: a row is data,
and a value the table lacks is a hint to a role, never a refusal (AR-2). A project that has a web or API surface never reads
the table in `declared_surfaces` / `row_for_profile` (`profiles_driven_by` reads it, RN1-3) (`table_free` rows of manual-capture-steps.json `capture_surfaces`, the same words the capture reads): the web
road does not change by a byte. A project with a `native`, `desktop` or `cli` surface, or a word the table does not know,
reads it, and silence is unreachable for it (P22): `declared_surfaces` says what goes to a person.

Error direction (D-0021): `unsupported` errs toward saying too much, never toward "supported"; an unreadable table is a
`ValueError` (factory-owned, AR-28), never an empty answer; `row_of` refuses a surface name the table lacks, so a typo
never becomes the web.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

TABLE_PATH = Path(__file__).resolve().parents[1] / "references" / "surfaces.json"
AGENT_HANDS = ("browser", "http", "driver")     # the hands of an agent; any other row's cases go to a person
UNKNOWN = "unknown"


def rows() -> dict:
    """The whole table. Raises ValueError (owner: factory) when the file cannot be read or is not shaped as the reader needs."""
    try:
        data = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{TABLE_PATH.name} cannot be read ({exc.__class__.__name__}): the factory's table of test surfaces is "
                         "missing or broken in this install. This is a factory defect: record it as a finding and go on "
                         "with what does work") from exc
    table = data.get("surfaces") if isinstance(data, dict) else None
    if not isinstance(table, dict) or not table or not all(
            isinstance(row, dict) and isinstance(row.get("capability"), str) and isinstance(row.get("hands"), str)
            for row in table.values()):
        raise ValueError(f"{TABLE_PATH.name} has no `surfaces` object of rows that name a `capability` and `hands`: the "
                         "factory's table of test surfaces is broken in this install. This is a factory defect: record it as "
                         "a finding and go on with what does work")
    return data


def _not_surfaces(data: dict) -> list:
    """The capability words of the catalogue that are not a place to test on (`not_surfaces` of the table): they never speak."""
    listed = data.get("not_surfaces")
    return [w for w in listed if isinstance(w, str)] if isinstance(listed, list) else []


def _table_free_words() -> set:
    """The capability words whose capture needs no table: `capture_surfaces` rows marked `table_free` in
    manual-capture-steps.json, read through its one reader (manual_capture.spec, AR-13)."""
    import manual_capture
    block = manual_capture.spec().get("capture_surfaces")
    words: set = set()
    for row in (block.values() if isinstance(block, dict) else ()):
        if isinstance(row, dict) and row.get("table_free") is True:
            words.update(w for w in (row.get("capabilities") or []) if isinstance(w, str))
    return words


def _environments(cfg) -> list:
    envs = cfg.get("environments") if isinstance(cfg, dict) else None
    return [e for e in envs if isinstance(e, dict)] if isinstance(envs, list) else []


def row_of(stand):
    """The table row of one environment row. None when the row names no `surface` (the table is not read: the web road).
    A `surface` the table lacks is a ValueError naming it and the list (FR-1)."""
    if not isinstance(stand, dict) or "surface" not in stand:
        return None
    table = rows()["surfaces"]
    name = stand["surface"]
    if not isinstance(name, str) or name not in table:
        raise ValueError(f"environments[].surface {name!r} is not a row of references/surfaces.json. Expected one of: "
                         f"{', '.join(sorted(table))}")
    return table[name]


def stand_rows(cfg) -> list:
    """[(environment row, table row)] of the rows that name a `surface`; [] without reading the table when none does."""
    return [(stand, row_of(stand)) for stand in _environments(cfg) if "surface" in stand]


def _who(row: dict) -> str:
    return "agent" if row.get("hands") in AGENT_HANDS else "person"


def declared_surfaces(cfg) -> dict:
    """{surface: {"hands": "agent"|"person", "stand": <name or None>, "words": str}} for what the project declares; {} when
    there is nothing to say (a web or API project, read without the table). `{"unknown": <text>}` when the profiles cannot
    be read. Raises ValueError when the table is needed and broken (readiness publishes it as `unknown`)."""
    profiles = cfg.get("profiles") if isinstance(cfg, dict) else None
    if profiles is None:
        profiles = []
    capabilities: set = set()
    if not isinstance(profiles, list):
        return {UNKNOWN: "profiles[] of qa-factory/config.json is not a list, so the test surfaces the project declares "
                         "could not be read. Expected a list of profiles; fix the key and run the check again"}
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        listed = profile.get("capabilities")
        if listed is None:
            continue
        if not isinstance(listed, list):
            return {UNKNOWN: f"profiles[{profile.get('profile_id', '?')}].capabilities is not a list, so the test surfaces "
                             "it declares could not be read. Expected a list of words; fix the key and run the check again"}
        capabilities.update(w for w in listed if isinstance(w, str))
    named = [e for e in _environments(cfg) if "surface" in e]
    if not named and capabilities <= _table_free_words():
        return {}
    data = rows()
    table = data["surfaces"]
    found = {}
    arms = set()
    for stand in named:
        row = row_of(stand)
        found[stand["surface"]] = {"hands": _who(row), "stand": stand.get("name") or None, "words": str(row.get("words") or "")}
        arms.add(row["hands"])
    for word in sorted(capabilities):
        arms.update(row["hands"] for row in table.values() if row["capability"] == word)
    other_arm = bool(arms & set(AGENT_HANDS))
    known = {row["capability"] for row in table.values()} | _table_free_words() | set(_not_surfaces(data))
    for word in sorted(capabilities - known):       # a word nothing describes: silence is unreachable (t-524 9.2, F-4); no word of any language is named
        found.setdefault(word, {"hands": "person", "stand": None, "words": str((data.get("words") or {}).get("unknown_word") or "")
                                .replace("{word}", " ".join(word.split())[:40])})
    for word in sorted(capabilities):
        for name, row in table.items():
            if row["capability"] != word or name in found:
                continue
            if row["hands"] == "none":
                if row.get("words_only_alone") and other_arm:
                    continue
                found[name] = {"hands": "person", "stand": None, "words": str(row.get("words") or "")}
            elif row["hands"] == "driver" and not any(
                    table[s]["capability"] == word for s in found if s in table):
                found.setdefault(word, {"hands": "person", "stand": None,
                                        "words": str((data.get("words") or {}).get("no_stand") or "")})
    return found


def unsupported(cfg) -> dict:
    """{surface: words} of the declared surfaces whose cases go to a person. Errs toward saying too much."""
    return {name: entry["words"] for name, entry in declared_surfaces(cfg).items()
            if isinstance(entry, dict) and entry.get("hands") == "person"}


def stand_for(cfg, asked: str = ""):
    """The device stand a capture is about: the environment row named by `asked` (a surface id), else the only row whose hands
    are a driver. ValueError (exit 2 of the caller) when none, or several and none asked: a surface is never guessed."""
    device = [(s, r) for s, r in stand_rows(cfg) if is_device_row(r)]
    if asked:
        device = [(s, r) for s, r in device if s["surface"] == asked]
    names = ", ".join(str(s.get("name")) for s, _ in device)
    if not device:
        raise ValueError((f"no device stand has surface {asked!r}" if asked else "no device stand is described in config.json")
                         + ". Expected an environments[] row with `surface` of a driver row of references/surfaces.json; "
                         "run the onboarding again to describe it")
    if len(device) > 1:
        raise ValueError(f"several device stands fit ({names}): name one with --surface <id>")
    return device[0][0]


def profile_words(cfg, profile: str):
    """The capability words of the profile `profile` in `cfg["profiles"]`; None when no such profile is declared (an unknown
    profile). A declared profile with no usable `capabilities` list answers an empty set. The one reader of the field (AR-13)."""
    found, words = False, set()
    for item in (cfg.get("profiles") if isinstance(cfg, dict) and isinstance(cfg.get("profiles"), list) else []):
        if isinstance(item, dict) and item.get("profile_id") == profile:
            found = True
            if isinstance(item.get("capabilities"), list):
                words.update(w for w in item["capabilities"] if isinstance(w, str))
    return words if found else None


def profiles_driven_by(cfg, hands: str) -> list:
    """The `profile_id`s of `cfg["profiles"]` that hold a capability word of a table row whose `hands` is `hands` (RN1-3: the
    profiles driven by a `browser` are the UI profiles). Capabilities are read through `profile_words` (the one reader, AR-13), the
    table through `rows()`. `profiles` absent or not a list -> []; a profile whose `capabilities` is not a list holds no word, so it
    is skipped; a broken table is the module's ValueError (the caller turns it into a note). Config order, each id once."""
    ids: list = []
    for item in (cfg.get("profiles") if isinstance(cfg, dict) and isinstance(cfg.get("profiles"), list) else []):
        if isinstance(item, dict) and isinstance(item.get("profile_id"), str) and item["profile_id"] not in ids:
            ids.append(item["profile_id"])
    if not ids:
        return []
    words = {row["capability"] for row in rows()["surfaces"].values() if row["hands"] == hands}
    return [pid for pid in ids if (profile_words(cfg, pid) or set()) & words]


def drives_device(table: dict, words) -> bool:
    """True when some row of `table` (surfaces.json `surfaces`) is driven by a device driver and holds one of `words`: the
    profile of those words is a device profile. The one expression behind `stand_of_profile` and runtime_probe (AR-13)."""
    return any(is_device_row(row) and row["capability"] in words for row in table.values())


def row_for_profile(cfg, profile: str):
    """The table row a test profile is about, or None. None for a profile `cfg` does not declare, and - WITHOUT reading the
    table - for a profile whose capabilities are all `table_free` words (the web road) when no environment names a `surface`.
    Otherwise the first row, in table order, whose `capability` the profile holds (android before ios: callers read `hands`) - when
    the rows of its words all have the SAME `hands`. Words whose rows differ in `hands` (a profile that is native and desktop at
    once) are not answered: None, the old road, so table order never decides who holds a case (F-12). A profile whose words fit no
    row: None. A broken table is the module's ValueError (the caller turns it into a line)."""
    words = profile_words(cfg, profile)
    if not words:
        return None
    if not any("surface" in e for e in _environments(cfg)) and words <= _table_free_words():
        return None
    fits = [row for row in rows()["surfaces"].values() if row["capability"] in words]
    return fits[0] if fits and len({row["hands"] for row in fits}) == 1 else None


def is_device_row(row) -> bool:
    """True when a table row is driven through a device driver (`hands: driver`). The one expression of "a device stand" (AR-13)."""
    return isinstance(row, dict) and row.get("hands") == "driver"


def driver_url_problem(url) -> str:
    """The one reading of an environment row's `driver.url`: "" when it is a plain http(s) address (host, optional port and path);
    "absent" when none is given (a person's "I do not know": the doctor reads it as `down`, it is no contract error); "secret" when it
    holds a user, a password, a query or a fragment (a token travels there; the file is committed); "unusable" for anything else (not
    text, another scheme, no host, a port that is no number). Used by `device_stand.base_url` and `config_contract` alike (AR-13)."""
    if url is None or (isinstance(url, str) and not url.strip()):
        return "absent"
    if not isinstance(url, str):
        return "unusable"
    try:
        parts = urlsplit(url.strip())
        parts.port  # noqa: B018 - reading it raises ValueError for a port that is not a number
    except ValueError:
        return "unusable"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "unusable"
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        return "secret"
    return ""


def device_stands(cfg) -> list:
    """[environment row] of the stands that name a `surface` driven through a device driver, in config order. ValueError when the
    table is broken or a `surface` is not its row; [] without reading the table when no row names a `surface`."""
    return [stand for stand, row in stand_rows(cfg) if is_device_row(row)]


def stand_of_profile(cfg, profile: str, selected: str) -> str:
    """The stand name a test profile is about. A project with no `surface` anywhere answers `selected` (the web road, no table
    read). A profile whose capabilities fit a driver row: the device stands of that capability, one -> it, several -> the one
    whose `surface` equals the profile id, else "". Any other profile: `selected` unless it names a device stand, else the only
    stand that is not a device stand, else ""."""
    pairs = stand_rows(cfg)
    if not pairs:
        return selected
    wanted = profile_words(cfg, profile) or set()
    table = rows()["surfaces"]
    if drives_device(table, wanted):
        fits = [s for s, r in pairs if is_device_row(r) and r["capability"] in wanted]
        if len(fits) > 1:
            fits = [s for s in fits if s.get("surface") == profile]
        return str(fits[0].get("name") or "") if len(fits) == 1 else ""
    device_names = {str(s.get("name")) for s, r in pairs if is_device_row(r)}
    if selected and selected not in device_names:
        return selected
    others = [str(s.get("name") or "") for s in _environments(cfg) if str(s.get("name")) not in device_names]
    return others[0] if len(others) == 1 else ""
