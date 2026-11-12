"""test_conductor_investigates_first.py - RN1-9 Part C: the conductor settles a problem itself before it asks a person (P22, FR-48, AR-17).

A lint over our OWN text, not a detector of a role's or a person's wording (FR-12 n/a). The keys, anchors and classes below are fixed
before the run and read the text VERBATIM:

  K1  FR-48 (design/factory-rules.md) and AR-17 (design/architecture.md) carry `what the code left`, `person-owned.json` and
      `never the text of the question`, each inside its own paragraph.
  K2  SKILL.md's Invariants bullet `- **Settle it yourself first` and conductor.md's lead line of "How you decide" carry
      `what the code left` and `person-owned.json`.
  K3  every row of SITES (a phase paragraph that tells the orchestrator to ask a person about a recorded state): exactly one paragraph
      of the file holds the anchor, and that paragraph holds `person-owned: <class>`. K3b: the markers per phase file equal its rows.
  K4  every `person-owned: <id>` marker in phases/*.md, SKILL.md and references/halts.md names a class of person-owned.json;
      halts.md has 18 rows, each with a marker or `factory: a finding, not a question`.

Negative controls run the same helpers over damaged copies and require them red. In a tree where SKILL.md has not been edited yet
(Part C hands its lines to the integrator), the SKILL.md key of K2 and the SKILL.md markers of K4 are red: expected, not a defect.

Runnable on its own: `python -B scripts/tests/test_conductor_investigates_first.py`.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import PLUGIN_ROOT, check, finish  # noqa: E402

sys.path.insert(0, str(PLUGIN_ROOT / "scripts"))
import person_owned  # noqa: E402

PHASES = "skills/qa-story/phases"
SKILL = "skills/qa-story/SKILL.md"
HALTS = "references/halts.md"
MARKER = re.compile(r"person-owned: ([a-z_]+)")
FACTORY_ROW = "factory: a finding, not a question"

# (file, anchor kept verbatim by the rewrite, class). C.4 of the spec t-722; the anchors are single-spaced after the join.
SITES = (
    ("s0.md", "and the person is asked ONCE (`ticket_title`", "access"),
    ("s0.md", "and you ask once, in the same message as the S1 source", "access"),
    ("s0.md", "so put it to them **here**", "access"),
    ("s2.md", "such a row waits for one question", "requirement_intent"),
    ("s2.md", "A second `blocked` verdict is the halt question again", "requirement_intent"),
    ("s4.md", "If `gate_a_stale` is true", "gate_word"),
    ("s4.md", "**A runner I cannot start at all.**", "access"),
    ("s5.md", "`go on` to go without a stand", "access"),
    ("s5.md", "Blocked again: no window starts.", "risk"),
    ("s5.md", "**A probe that cannot run here.**", "gate_word"),
    ("s5.md", "**A stand block carries its fix.**", "access"),
    ("s5.md", "A test file that has to live inside the application tree", "team_agreement"),
    ("s5.md", "**The stand.** On `stand_signal`", "access"),
    ("s6.md", "no name or no answer -> ask once", "access"),
    ("s6.md", "no name or no answer → ask", "access"),
    ("s7.md", "a round past the cap is the `s7.repair_limit` question", "gate_word"),
    ("s7.md", "Before it runs, tell the person its price", "money"),
    ("s8.md", "ask the one question the rehearsal already worded", "outbound"),
    ("s8.md", "`stage_done` prints a `STORY BUDGET:` line and exits non-zero", "money"),
    ("s8.md", "For the incomplete before/after comparisons", "access"),
    ("s9.md", "the question is `run again` / `leave` / `stop`", "risk"),
    ("s9.md", "The ceiling the project set was reached.", "money"),
)
ROW_8 = "`go on` to go without a stand"


def read(rel: str) -> str:
    return (PLUGIN_ROOT / rel).read_text(encoding="utf-8")


def paragraphs(text: str) -> list:
    """Blank-line separated blocks; a table row is its own block; the lines of a block are stripped and joined by ONE space."""
    blocks, current = [], []
    for line in text.splitlines():
        if not line.strip():
            if current:
                blocks.append(" ".join(current))
            current = []
        elif line.lstrip().startswith("|"):
            if current:
                blocks.append(" ".join(current))
            blocks.append(line.strip())
            current = []
        else:
            current.append(line.strip())
    if current:
        blocks.append(" ".join(current))
    return blocks


def block_from(text: str, head: str) -> str:
    """The text from the line starting with `head` up to the next blank line (design entries)."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(head)), None)
    if start is None:
        return ""
    out = []
    for line in lines[start:]:
        if not line.strip():
            break
        out.append(line)
    return "\n".join(out)


def bullet_from(text: str, head: str) -> str:
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(head)), None)
    if start is None:
        return ""
    out = [lines[start]]
    for line in lines[start + 1:]:
        if line.startswith("- **") or line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out)


def lead_line(text: str) -> str:
    """The paragraph right under `## How you decide` of conductor.md."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "## How you decide"), None)
    if start is None:
        return ""
    for line in lines[start + 1:]:
        if line.strip():
            return line
    return ""


def absent(keys: tuple, text: str) -> list:
    return [k for k in keys if k not in text]


K1_KEYS = ("what the code left", "person-owned.json", "never the text of the question")
K2_KEYS = ("what the code left", "person-owned.json")


def k1_problems(fr: str, ar: str) -> list:
    """`fr`: the FR-48 paragraph (to its blank line); `ar`: AR-17's heading plus bullet lines (to its blank line)."""
    return [f"FR-48 lacks {k!r}" for k in absent(K1_KEYS, fr)] + [f"AR-17 lacks {k!r}" for k in absent(K1_KEYS, ar)]


def k2_skill_problems(skill: str) -> list:
    return [f"SKILL.md bullet lacks {k!r}" for k in absent(K2_KEYS, bullet_from(skill, "- **Settle it yourself first"))]


def k2_conductor_problems(conductor: str) -> list:
    return [f"conductor.md lead line lacks {k!r}" for k in absent(K2_KEYS, lead_line(conductor))]


def k3_problems(texts: dict) -> list:
    """`texts`: file name -> text. One finding per defective row, plus K3b per file."""
    found = []
    for name, anchor, klass in SITES:
        holders = [p for p in paragraphs(texts[name]) if anchor in p]
        if len(holders) != 1:
            found.append(f"{name}: anchor not found exactly once ({len(holders)}): {anchor!r}")
        elif f"person-owned: {klass}" not in holders[0]:
            found.append(f"{name}: paragraph of {anchor!r} lacks `person-owned: {klass}`")
    for name, text in texts.items():
        rows = sum(1 for site in SITES if site[0] == name)
        marks = len(MARKER.findall(text))
        if marks != rows:
            found.append(f"{name}: {marks} markers for {rows} site rows")
    return found


def k4_problems(texts: dict) -> list:
    ids = person_owned.class_ids()
    return [f"{name}: marker names {m!r}, not a class" for name, text in texts.items() for m in MARKER.findall(text) if m not in ids]


def halts_problems(text: str) -> list:
    rows = [line for line in text.splitlines() if line.startswith("| ") and not line.startswith("| Digest or condition")]
    found = [] if len(rows) == 18 else [f"halts.md has {len(rows)} rows, not 18"]
    return found + [f"halts row without a marker: {r[:60]}" for r in rows if not MARKER.search(r) and FACTORY_ROW not in r]


rules_text = (PLUGIN_ROOT / "design" / "factory-rules.md").read_text(encoding="utf-8")
arch_text = (PLUGIN_ROOT / "design" / "architecture.md").read_text(encoding="utf-8")
conductor_text, skill_text, halts_text = read("references/conductor.md"), read(SKILL), read(HALTS)
phase_texts = {p.name: p.read_text(encoding="utf-8") for p in sorted((PLUGIN_ROOT / PHASES).glob("*.md"))}

# K1
fr48, ar17 = block_from(rules_text, "**FR-48"), block_from(arch_text, "**AR-17")
check("K1: FR-48 and AR-17 carry the three keys", not k1_problems(fr48, ar17), str(k1_problems(fr48, ar17)))
for key in K1_KEYS:
    check(f"K1 negative control: FR-48 without {key!r} is red", bool(k1_problems(fr48.replace(key, ""), ar17)))
    check(f"K1 negative control: AR-17 without {key!r} is red", bool(k1_problems(fr48, ar17.replace(key, ""))))

# K2
check("K2: conductor.md's lead line of `How you decide` carries both keys", not k2_conductor_problems(conductor_text), str(k2_conductor_problems(conductor_text)))
check("K2 (SKILL.md key; red until the integrator applies C.6): the Invariants bullet carries both keys", not k2_skill_problems(skill_text), str(k2_skill_problems(skill_text)))
for key in K2_KEYS:
    check(f"K2 negative control: conductor.md lead line without {key!r} is red",
          bool(k2_conductor_problems("## How you decide\n\n" + lead_line(conductor_text).replace(key, "") + "\n")))
fake_skill = "- **Settle it yourself first; x.** what the code left, references/person-owned.json\n- **Next.** y\n"
check("K2 control: a well-formed bullet is green", not k2_skill_problems(fake_skill))
for key in K2_KEYS:
    check(f"K2 negative control: a bullet without {key!r} is red", bool(k2_skill_problems(fake_skill.replace(key, ""))))

# K3
problems = k3_problems(phase_texts)
check("K3: all 22 site rows hold their anchor once, with their marker, and the marker counts match", not problems, "; ".join(problems))
check("K3: the list has 22 rows", len(SITES) == 22, str(len(SITES)))
row8 = next(p for p in paragraphs(phase_texts["s5.md"]) if ROW_8 in p)
broken = dict(phase_texts, **{"s5.md": phase_texts["s5.md"].replace("(person-owned: access).", "(x).", 1)})
check("K3 negative control: the marker removed from row 8's paragraph is red", bool(k3_problems(broken)))
check("K3 control: row 8's paragraph carries its marker now", "person-owned: access" in row8)
reworded = dict(phase_texts, **{"s5.md": phase_texts["s5.md"].replace(ROW_8, "`go on` to proceed without a stand", 1)})
check("K3 negative control: a reworded anchor is red (`anchor not found`)", any("anchor not found" in p for p in k3_problems(reworded)))
extra = dict(phase_texts, **{"s1.md": phase_texts["s1.md"] + "\nperson-owned: access\n"})
check("K3b negative control: a marker added with no row is red", any("s1.md" in p for p in k3_problems(extra)))

# K4
scanned = dict(phase_texts, **{"SKILL.md": skill_text, "halts.md": halts_text})
check("K4: every marker names a class of person-owned.json (phases and halts.md)", not k4_problems(dict(phase_texts, **{"halts.md": halts_text})),
      str(k4_problems(dict(phase_texts, **{"halts.md": halts_text}))))
check("K4 (SKILL.md markers; vacuous until the integrator applies C.6): SKILL.md markers name a class", not k4_problems({"SKILL.md": skill_text}))
check("K4: halts.md has 18 rows, each with a marker or the factory words", not halts_problems(halts_text), str(halts_problems(halts_text)))
bad = dict(phase_texts, **{"s7.md": phase_texts["s7.md"].replace("person-owned: money", "person-owned: nope", 1)})
check("K4 negative control: `person-owned: nope` is red", bool(k4_problems(bad)))
check("K4 negative control: a halts row without a marker is red", bool(halts_problems(halts_text.replace("person-owned: risk", "x", 1))))
dropped = "\n".join(line for line in halts_text.splitlines() if not line.startswith("| Dirty working tree at S5"))
check("K4 negative control: a dropped halts row is red (17 rows)", bool(halts_problems(dropped)))
check("K4: the scan reaches SKILL.md, the phases and halts.md", bool(scanned) and len(phase_texts) >= 10, str(sorted(scanned)))

# K5 (verdict t-764 B-1 / m-3 / m-8): the door text is `<id>` everywhere; conductor.md names the flag and keeps its cap; SKILL.md keeps its
# cap and no longer says the two gate briefs are the only documents (halts.md and person-owned.json are opened too).
conductor_bytes = (PLUGIN_ROOT / "references" / "conductor.md").read_bytes()
skill_bytes = (PLUGIN_ROOT / SKILL).read_bytes()
conductor_text, skill_all = conductor_bytes.decode("utf-8"), skill_bytes.decode("utf-8")
check("K5: conductor.md names `--why-person <id>` for a word it records", "--why-person <id>" in conductor_text)
check("K5: conductor.md stays within 12 000 bytes", len(conductor_bytes) <= 12000, str(len(conductor_bytes)))
check("K5: SKILL.md stays within 19 000 bytes", len(skill_bytes) <= 19000, str(len(skill_bytes)))
check("K5 (m-8): SKILL.md says `--why-person <id>`, never `<class>`", "--why-person <id>" in skill_all and "--why-person <class>" not in skill_all)
check("K5 (m-3): SKILL.md no longer says the two gate briefs are the only documents you open", "are the only documents you open" not in skill_all)
check("K5 negative control: the old sentence would be caught", "are the only documents you open" in skill_all.replace(
    "besides the two gate briefs you open only the references this file names.", "the two gate briefs are the only documents you open."))

finish("test_conductor_investigates_first")
