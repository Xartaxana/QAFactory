"""P7.4: the slices are the heaviest layer of a dispatch, and naming them is opt-in.

23,626 bytes of slices against 8,881 of charter for the code critic, re-billed on every turn. The
plan's proposal is to hand a role the PATHS and one line of what each carries, the way the brief
already hands it files, and let it read what its work touches.

This holds both halves. The catalogue is generated and honest — it names every slice the map gives
that role, with its size and its sections. And the mode is OFF unless the project asks, because the
one measurement we have says the opposite of the proposal: 0 of 290 dispatched subagents opened a
file they were told to read (`inject_context.py`'s own note). What this file proves is that the
saving is real and that nothing changes until a project turns it on.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness import (PLUGIN_ROOT, check, check_eq, check_in, check_not_in, cleanup,  # noqa: E402
                     finish, temp_project, use_project)

import contract_slices as CS  # noqa: E402

ROLE = "qa-code-critic"


def sentinel(slice_path: Path) -> str:
    """One sentence-length body line of a generated slice, read from the slice itself.

    The test used to pin a literal ("An `obligation_id` is the plan's ..."). t-285 re-cut the
    automation contract so that section is marked for the automator alone, the code critic's
    slice lost it, and the checks went red while delivery was fine: a literal about one section
    goes stale every time the markers move, a line read from the slice on disk cannot. Headings,
    markers, tables, list items and code fences are skipped - they can also sit in the catalogue."""
    for line in slice_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if len(s) >= 40 and s[0] not in "#<|-`*>{[" and not s.startswith("```"):
            return s
    raise AssertionError(f"no body line in {slice_path}")


def main() -> int:
    # --- the catalogue itself ---------------------------------------------------------------
    text = CS.catalogue(PLUGIN_ROOT, ROLE)
    all_declared = [t for t in CS.targets(PLUGIN_ROOT) if t["role"] == ROLE]
    # The role's slice of the common rules is delivered in EVERY mode and the catalogue never names it (SC1-9).
    common_slices = [t for t in all_declared if t["subject"] in CS.COMMON_LAYER_SUBJECTS]
    declared = [t for t in all_declared if t["subject"] not in CS.COMMON_LAYER_SUBJECTS]
    check("the role has its own slice of the common rules in the map (the control for the A-K2 checks below)",
          len(common_slices) == 1 and common_slices[0]["slice"].exists(), str(common_slices))
    common_sentinel = sentinel(common_slices[0]["slice"])
    sentinels = [sentinel(t["slice"]) for t in declared]
    check("every slice has a body line to tell it by", len(sentinels) == len(declared) > 0, sentinels)
    check("every slice the map gives this role is named in its catalogue",
          all(t["slice"].name in text for t in declared),
          [t["slice"].name for t in declared if t["slice"].name not in text])
    check_in("with what is inside it, not just a path", "Instance identity", text)
    check_in("and what it costs", " B) — ", text)
    check_in("and the instruction that makes a named file worth naming",
             "BEFORE you write your artifact", text)
    check("the catalogue is a fraction of what it stands for",
          len(text) * 4 < sum(len(t["slice"].read_text(encoding="utf-8")) for t in declared),
          f"catalogue {len(text)}, slices "
          f"{sum(len(t['slice'].read_text(encoding='utf-8')) for t in declared)}")
    check("it is on disk and fresh, like every generated file here",
          CS.catalogue_findings(PLUGIN_ROOT) == [], CS.catalogue_findings(PLUGIN_ROOT))
    check_not_in("A-K2: the catalogue never names the common rules (they are delivered, not named)",
                 "common-rules.md", text)

    # --- the two modes ---------------------------------------------------------------------
    root = temp_project()
    try:
        use_project(root)
        import hooklib
        import inject_context as I

        def blocks_now() -> list:
            for attr in [a for a in dir(hooklib) if "CACHE" in a]:
                setattr(hooklib, attr, None)
            return I.collect_blocks(ROLE, I.load_map())

        check_eq("inline is the default, with no key in the config", I.slices_mode(), "inline")
        inline = blocks_now()
        inline_bytes = sum(len(b) for b in inline)
        inline_text = "\n".join(inline)
        check("inline delivers the slices themselves (a body line of every slice the map gives)",
              all(s in inline_text for s in sentinels), [s for s in sentinels if s not in inline_text])

        cfg = root / "qa-factory" / "config.json"
        data = json.loads(cfg.read_text(encoding="utf-8"))
        data["prompts"] = {"slices": "on_demand"}
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
        for attr in [a for a in dir(hooklib) if "CACHE" in a]:
            setattr(hooklib, attr, None)
        check_eq("a project can ask for the paths instead", I.slices_mode(), "on_demand")
        named = blocks_now()
        named_bytes = sum(len(b) for b in named)
        check("on demand delivers the catalogue", any("index.md" in b for b in named))
        named_text = "\n".join(named)
        check("and not the slice contents", not any(s in named_text for s in sentinels),
              [s for s in sentinels if s in named_text])
        check_in("the block says the files must be read", "before you write your artifact",
                 "\n".join(named))
        # Measured on the wave tree vs 6eee515e (qa-code-critic): saving 17,190 of 41,371 -> 14,060 of 39,063 (inline 39,063,
        # on demand 25,003). The slices the critic is given shrank by 3,444 B - HF2-13 (27a3e697) took the pattern Catalog out of
        # its injection (`test-code-patterns.md` 6,858 -> 3,414) - and the rubric (injected in BOTH modes, so neutral to the
        # saving) grew by 830 B (3d/6a). No duty moved from a slice into the always-injected text; the bound follows the slices left.
        check(f"the saving is the one the plan predicted ({inline_bytes - named_bytes:,} of "
              f"{inline_bytes:,} characters)", inline_bytes - named_bytes > 13000,
              f"inline {inline_bytes:,}, on demand {named_bytes:,}")
        check("the common rules are still delivered in both modes — they are not a slice",
              any("common-rules.md" in b for b in named) and
              any("common-rules.md" in b for b in inline))
        # A-K2: INSIDE the prompt in on_demand, not only a name; the catalogue block does not name them.
        check("A-K2: on demand, a body line of the role's common-rules slice is in the blocks",
              common_sentinel in named_text, common_sentinel)
        check("A-K2: and in inline mode too", common_sentinel in inline_text)
        index_blocks = [b for b in named if "# Your rule files, by path" in b]
        check("A-K2: the on_demand index.md block exists (control) and does not name common-rules.md",
              len(index_blocks) == 1 and "common-rules.md" not in index_blocks[0], str(len(index_blocks)))

        data["prompts"] = {"slices": "nonsense"}
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
        for attr in [a for a in dir(hooklib) if "CACHE" in a]:
            setattr(hooklib, attr, None)
        fallback_text = "\n".join(blocks_now())
        check("a mode nobody implemented delivers the slices, never nothing",
              all(s in fallback_text for s in sentinels), [s for s in sentinels if s not in fallback_text])
    finally:
        cleanup(root)
    return finish("test_slices_on_demand")


if __name__ == "__main__":
    sys.exit(main())
