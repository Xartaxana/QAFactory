"""Role slices of the references: one source of truth, one injected file per reader.

A reference stays ONE file per subject — the truth about that subject is in one place and is
edited in one place. What a role is injected is a SLICE of it: the file's lead plus only the
sections marked for that role.

Markup (its own line directly above a `##`/`###` heading of `references/*.md`):

    <!-- roles: qa-automator, qa-code-critic -->
    ## `automation-manifest.json`

    <!-- roles: all -->
    ## Design review

The marker sits ABOVE the heading and never inside it, so that the heading line stays byte
for byte what it was: several checks match section headings exactly (`test_stages.py` reads
the artifact tree out of "## Where artifacts live", `critic_rollcall.py` reads
"## Gate A debts"), and marking a section must never be able to break one of them.

`all` means every role that has a slice of this file. A `###` heading with no marker of its
own belongs to its `##` parent; a marked `###` is its own section and is not repeated under
the parent. Text before the first heading is the lead and is in every slice: it says what the
subject is, and a slice that opens mid-rule reads as a different document.

Generation is a build step, not runtime: `--write` renders `references/slices/<role>/<subject>.md`
and the files are COMMITTED. The injection hook has no time to render anything (TP1-15045:
a dispatch pays for every byte on every turn and the hook must fail open in milliseconds), so
`--check` is what keeps a slice honest — selftest and audit A9 run it, and a stale slice is a
red build, never a silent half-truth delivered to a role.

Why slices at all (owner's decision of 21.09): the audit capped what one role is
injected at 42,000 bytes (since RC1-14 audit A22 judges the role's whole start load in tokens,
`role_load.py`), and five roles sat within a thousand bytes of the cap while four of
them were writing fields out of documents nobody delivered to them. Splitting a subject into
one file per reader would have given the same fact two owners (audit A21); splitting by
section keeps one owner and pays only for what the reader acts on.

CLI:
  --write     render every slice named in references/inject-map.json, and the one generated
              line of every charter (the digest form is `common-rules.md`'s fact, not theirs)
  --check     exit 2 with the reason when any slice or generated charter line is missing,
              stale, empty or orphaned
  --report    per-role injected bytes, whole sources vs slices, and the common layer (`common_layer`)
  --selftest  unit checks of the parser and the freshness rules on synthetic text
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from content_size import content_bytes  # noqa: E402
from hooklib import read_json, sorted_paths  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SLICES_REL = "references/slices"
PLUGIN_PREFIX = "plugin:"
SLICE_PREFIX = PLUGIN_PREFIX + SLICES_REL + "/"
ROLE_MARKER = re.compile(r"<!--\s*roles:\s*([^>]*?)\s*-->")
KIND_LINE = re.compile(r"<!--\s*kind:\s*[A-Za-z0-9_-]+\s*-->")      # role_load.KIND_MARKER: craft/process, no meaning to a slice
HEADING = re.compile(r"^(#{2,3})\s+(.*)$")
WRITER = re.compile(r"\*\*Writer\*\*\s+`(qa-[a-z-]+)`")
# The subjects of the COMMON layer: each role's slice of them is delivered in every mode, so the
# per-role catalogue never names them (inject_context.collect_blocks keeps them out of `on_demand`
# by the same list) and `common_layer` weighs them. The one owner of the list (AR-13).
COMMON_LAYER_SUBJECTS = ("common-rules.md",)
# The generated page of the keys a role hands over (spec t-1765 X1-7): it has no source file to cut from, so
# `targets` skips it and `keys_targets` / `keys_findings` / `keys_write` own it.
KEYS_NAME = "handoff-keys.md"


def _provenance(subject: str, role: str) -> str:
    """The first line of every slice. It names the source in the same `plugin:` spelling the
    map uses, so a role that needs the whole subject knows the one file to open and an
    operator reading a dispatch prompt can tell a slice from a source at a glance."""
    return (f"<!-- generated from {PLUGIN_PREFIX}references/{subject} for {role} by "
            "scripts/contract_slices.py; edit the source, never this file -->")


class Section:
    __slots__ = ("heading", "roles", "lines")

    def __init__(self, heading: str, roles: list, lines: list) -> None:
        self.heading, self.roles, self.lines = heading, roles, lines

    @property
    def title(self) -> str:
        return HEADING.match(self.heading).group(2).strip() if HEADING.match(self.heading) else self.heading

    def text(self) -> str:
        return "\n".join([self.heading] + self.lines).rstrip() + "\n"

    def bytes(self) -> int:
        return len(self.text().encode("utf-8"))

    def wants(self, role: str) -> bool:
        return "all" in self.roles or role in self.roles


def parse(text: str) -> tuple:
    """(lead, sections). A heading without a marker keeps the roles of the `##` it sits under,
    which is how a long `##` can be split into `###` parts for the readers that differ without
    re-marking the parts that do not."""
    lead: list = []
    sections: list = []
    current: Section | None = None
    inherited: list = []
    pending: list | None = None
    fence = False
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            fence = not fence
        if not fence and stripped.startswith("<!--") and ROLE_MARKER.fullmatch(stripped):
            # Held for the next heading, and never written into a slice: the marker is
            # bookkeeping for the generator, not a rule the role has to read.
            pending = [r.strip() for r in ROLE_MARKER.fullmatch(stripped).group(1).split(",") if r.strip()]
            continue
        m = None if fence else HEADING.match(line)
        if m:
            inline = ROLE_MARKER.search(line)
            if inline:  # accepted, but the markup writes the marker above the heading
                roles = [r.strip() for r in inline.group(1).split(",") if r.strip()]
            elif pending is not None:
                roles = list(pending)
            else:
                roles = list(inherited)
            pending = None
            if m.group(1) == "##":
                inherited = list(roles)
            heading = ROLE_MARKER.sub("", line).rstrip()
            current = Section(heading, roles, [])
            sections.append(current)
            continue
        if pending is not None and stripped and not KIND_LINE.fullmatch(stripped):
            # A marker that turned out to head nothing: keep the text, drop the claim. A `<!-- kind: ... -->` line
            # (role_load's craft marker) is not text: the roles marker above it still heads the heading below (t-1793 F6).
            pending = None
        (current.lines if current is not None else lead).append(line)
    return "\n".join(lead).rstrip() + "\n", sections


def marked(text: str) -> bool:
    """A file carrying at least one role marker is a sliced subject: it is injected through
    slices only, so that adding a section for one reader cannot quietly grow every reader."""
    return bool(ROLE_MARKER.search(text))


# A reference may name the closed words of the vocabulary with this token. The role it is injected to
# cannot open `handoffs/vocabulary.yaml` (the pre-tool guard lets a role read only `references/`), so
# "see `vocabulary.<list>`" hands it a name and no word (OH3-14). The slice carries the words
# themselves, written in by the ONE line builder `handoff.grounding_vocabulary_line` (AR-13) - never
# a list typed into the reference. `--check` compares the slice with the CURRENT vocabulary, so a
# vocabulary change makes the slice stale until `--write`: that is the ratchet, the same one the
# charters' digest line has.
GROUNDING_WORDS_TOKEN = "<!-- gen:grounding-words -->"


def grounding_words() -> str:
    """The closed words of `work/grounding.yaml` as one line, from `handoff.grounding_vocabulary_line`. An unreadable
    vocabulary or an empty list is declared inside that line ("NONE READABLE"); a reader that cannot even be imported is
    declared the same way here. Never blank, never raises."""
    try:
        import handoff
        return handoff.grounding_vocabulary_line()
    except Exception as exc:
        return f"NONE READABLE (the vocabulary reader failed: {type(exc).__name__})."


def render(subject: str, role: str, text: str) -> str:
    lead, sections = parse(text)
    chosen = [s for s in sections if s.wants(role)]
    body = "".join("\n" + s.text() for s in chosen)
    out = _provenance(subject, role) + "\n" + lead + body
    return out.replace(GROUNDING_WORDS_TOKEN, grounding_words()) if GROUNDING_WORDS_TOKEN in out else out


def targets(plugin_root: Path) -> list:
    """Every (role, subject) pair inject-map.json asks for, as
    {role, subject, source, slice, entry}. The map is the declaration: a slice exists because
    a role is injected it, never because a marker mentions a role."""
    try:
        imap = json.loads((plugin_root / "references" / "inject-map.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for role, entries in (imap.get("roles") or {}).items():
        for entry in entries or []:
            if not str(entry).startswith(SLICE_PREFIX):
                continue
            rel = str(entry)[len(PLUGIN_PREFIX):]
            parts = Path(rel).parts
            subject = parts[-1]
            if subject == KEYS_NAME:        # generated from the contracts, not cut from a source: `keys_targets`
                continue
            out.append({"role": role, "subject": subject, "entry": str(entry),
                        "slice_role": parts[-2],
                        "source": plugin_root / "references" / subject,
                        "slice": plugin_root / rel})
    return sorted(out, key=lambda t: (t["role"], t["subject"]))


def direct_entries(plugin_root: Path) -> list:
    """(role, entry, path) for plugin references injected whole."""
    try:
        imap = json.loads((plugin_root / "references" / "inject-map.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for role, entries in list((imap.get("roles") or {}).items()) + [("common", imap.get("common") or [])]:
        for entry in entries or []:
            e = str(entry)
            if e.startswith(PLUGIN_PREFIX) and not e.startswith(SLICE_PREFIX) and e.endswith(".md"):
                out.append((role, e, plugin_root / e[len(PLUGIN_PREFIX):]))
    return out


def findings(plugin_root: Path) -> list:
    """Everything that makes a slice untrustworthy, in the words the fixer needs."""
    errors: list = []
    wanted = targets(plugin_root)
    for t in wanted:
        if t["slice_role"] != t["role"]:
            errors.append(f"{t['entry']}: injected to {t['role']} but lives in the {t['slice_role']} folder")
        if not t["source"].exists():
            errors.append(f"{t['entry']}: no source references/{t['subject']} to render it from")
            continue
        text = t["source"].read_text(encoding="utf-8")
        if not marked(text):
            errors.append(f"references/{t['subject']}: no `<!-- roles: ... -->` marker anywhere, "
                          f"so the slice for {t['role']} would be the lead alone — mark the sections")
            continue
        fresh = render(t["subject"], t["role"], text)
        if not t["slice"].exists():
            errors.append(f"{t['entry']}: missing — run `python -B scripts/contract_slices.py --write`")
            continue
        if t["slice"].read_text(encoding="utf-8").replace("\r\n", "\n") != fresh:
            errors.append(f"{t['entry']}: stale — the source changed; run "
                          "`python -B scripts/contract_slices.py --write`")
        _, sections = parse(text)
        if not [s for s in sections if s.wants(t["role"])]:
            errors.append(f"{t['entry']}: {t['role']} is marked on no section of references/"
                          f"{t['subject']} — it would be injected a title and nothing else")
        # A role that WRITES an artifact must be injected the section that defines it: the
        # deferred findings of 0.7.7 were four roles writing fields out of contracts nobody
        # delivered (code critic and failure analyst on the automation manifest, case critic
        # on the findings file, doc scribe on coverage links).
        for s in sections:
            writers = set(WRITER.findall(s.text()))
            if t["role"] in writers and not s.wants(t["role"]):
                errors.append(f"references/{t['subject']} `{s.title}` names {t['role']} as its "
                              "**Writer** but the marker leaves it out of that role's slice")
    declared = {t["slice"].resolve() for t in wanted}
    slices_dir = plugin_root / SLICES_REL
    for path in sorted_paths(slices_dir.rglob("*.md")) if slices_dir.exists() else []:
        # The per-role catalogue is this generator's own file, not a slice: it is injected only
        # when `config.prompts.slices` is `on_demand`, so the map never names it.
        if path.name in (CATALOGUE_NAME, KEYS_NAME):        # the key page: `keys_findings` judges it
            continue
        if path.resolve() not in declared:
            errors.append(f"{SLICES_REL}/{path.relative_to(slices_dir).as_posix()}: a slice no "
                          "role is injected — delete it or point inject-map.json at it")
    for role, entry, path in direct_entries(plugin_root):
        if path.exists() and marked(path.read_text(encoding="utf-8")):
            errors.append(f"{entry}: {role} is injected the whole marked subject — point the map "
                          f"at {SLICE_PREFIX}{role}/{path.name}")
    return errors + keys_findings(plugin_root)


def write(plugin_root: Path) -> list:
    """Render every declared slice. Returns the paths that changed."""
    changed = []
    for t in targets(plugin_root):
        if not t["source"].exists():
            continue
        fresh = render(t["subject"], t["role"], t["source"].read_text(encoding="utf-8"))
        old = t["slice"].read_text(encoding="utf-8").replace("\r\n", "\n") if t["slice"].exists() else None
        if old != fresh:
            t["slice"].parent.mkdir(parents=True, exist_ok=True)
            t["slice"].write_text(fresh, encoding="utf-8", newline="\n")
            changed.append(t["slice"])
    return changed


# --- the charters' mechanical line (P7.2/P7.3) ---------------------------------------------------
# The digest FORM belongs to one layer - `references/common-rules.md`, which the injection hook
# delivers to every dispatch. Eleven of the twelve charters restated it anyway, and five of those
# restated a shape the common layer had already replaced: `<role> S8 done|halt · <path> · <one
# fact>`, two parts where the form has three. `role_digest.py` tolerates the old spelling on
# purpose, so nothing was ever red - a story in flight must not be refused over a role file nobody
# updated - and the drift simply stood, in the layer the audit puts its tightest cap on.
#
# So the line is generated from the owners it was copied out of: `role_digest.ROLE_ITEM` for what
# one row is about, `handoffs/vocabulary.yaml` (through `handoff.options_for_role`) for the words
# this role may write in that row, and `references/stages.json` for the artifact path. The charter
# keeps the part that is genuinely its own - everything outside the markers.
CHARTER_OPEN = "<!-- gen:digest contract_slices.py -->"
CHARTER_CLOSE = "<!-- /gen -->"


def _role_states(role: str) -> list:
    """The row states this role may write, from the vocabulary that owns them."""
    try:
        import handoff
        vocab = handoff.vocabulary()
        states = vocab.get("row_states")
        if not isinstance(states, dict):
            return []
        out = []
        for word, spec in states.items():
            spec = spec if isinstance(spec, dict) else {}
            used_by = spec.get("used_by") or ""
            restricted = spec.get("restricted_to") or ""
            if restricted and role not in str(restricted):
                continue
            if used_by and role not in str(used_by) and "all" not in str(used_by):
                continue
            out.append(str(word))
        return out
    except Exception:
        return []


def charter_line(plugin_root: Path, role: str) -> str:
    """The one bullet the generator owns, or "" when this role is not one of the twelve."""
    try:
        sys.path.insert(0, str(plugin_root / "scripts"))
        from role_digest import ROLE_ITEM
    except Exception:
        return ""
    item = ROLE_ITEM.get(role)
    if not item:
        return ""
    # The WORDS are not listed here either, and that is the same rule one layer down: which row
    # states this role may write is `handoffs/vocabulary.yaml`'s fact, narrowed per role by
    # `handoff.options_for_role`, and printed by the check itself the moment a value is wrong. A
    # copy in the charter is a second answer as soon as a word is added - and it cost more bytes
    # than the whole rule it was copied from.
    states = _role_states(role)
    # Whose artifact the path is: `artifact-writers.json` is where that is decided ("one
    # artifact, one writer"), so the charter quotes the owner rather than a guess from the stage
    # table - which gave the bug reporter `work/ledger.json`, a file it does not own.
    artifact = ""
    try:
        writers = json.loads((plugin_root / "references" / "artifact-writers.json")
                             .read_text(encoding="utf-8")).get("artifacts") or {}
        mine = [name for name, spec in writers.items()
                if str((spec or {}).get("writer") or "").split()[0:1] == [role]]
        artifact = mine[0] if mine else ""
    except Exception:
        artifact = ""
    # A role that owns no artifact of its own - the two critics write a findings file, the
    # automator and the runner write into files code owns - is not given a path GUESSED from its
    # stage: the stage table hands both S4 roles `work/test-cases/`, which is the designer's. What
    # it writes is its own Outputs block, one section above, and that is where the charter points.
    # A role that may be dispatched for the S5 PLAN as well as for a window ends its digest on a
    # different file by purpose (the plan, or the window's own artifact) and counts a different
    # unit (a case, or a test instance): one generated line cannot name either truthfully, so it
    # names no path and its item word covers both. The fact is `controller.S5_PLAN_ROLES`, the
    # survivor that already gates `--purpose s5_plan` (AR-13); no second list here.
    try:
        from controller import S5_PLAN_ROLES
    except Exception:
        S5_PLAN_ROLES = ()
    if role in S5_PLAN_ROLES:
        artifact = ""
        item = f"{item} (a plan dispatch: per case)"
    where = (f"`{artifact}`" if artifact else "what you wrote (your `Outputs` above)")
    parts = [f"- Digest: the common form (`common-rules.md`), one line per {item}, then {where}."]
    if not states:                                    # a role the vocabulary gives no word to
        parts.append("  Your states are the ones your artifact's contract names.")
    return "\n".join(parts)


def charter_targets(plugin_root: Path) -> list:
    """[(role, path)] of the charters the generator owns a block in."""
    out = []
    for path in sorted_paths((plugin_root / "agents").glob("qa-*.md")):
        if charter_line(plugin_root, path.stem):
            out.append((path.stem, path))
    return out


def charter_block(plugin_root: Path, role: str) -> str:
    return "\n".join([CHARTER_OPEN, charter_line(plugin_root, role), CHARTER_CLOSE])


def charter_rendered(plugin_root: Path, role: str, text: str) -> str:
    """`text` with the generated block put where it belongs: replacing the block that is there,
    or replacing the hand-written `- Digest:` bullet the first time."""
    block = charter_block(plugin_root, role)
    if CHARTER_OPEN in text:
        head, _, rest = text.partition(CHARTER_OPEN)
        _, _, tail = rest.partition(CHARTER_CLOSE)
        return head + block + tail
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if not line.startswith("- Digest:"):
            continue
        end = i + 1
        while end < len(lines) and lines[end].startswith("  ") and lines[end].strip():
            end += 1
        return "\n".join(lines[:i] + block.split("\n") + lines[end:])
    return text


def charter_findings(plugin_root: Path) -> list:
    out = []
    for role, path in charter_targets(plugin_root):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if CHARTER_OPEN not in text:
            out.append(f"agents/{path.name}: restates the digest form by hand — the form belongs "
                       "to references/common-rules.md; run "
                       "`python -B scripts/contract_slices.py --write`")
            continue
        if charter_rendered(plugin_root, role, text) != text:
            out.append(f"agents/{path.name}: the generated digest line is stale (the vocabulary or "
                       "the stage table moved) — run "
                       "`python -B scripts/contract_slices.py --write`")
    return out


def charter_write(plugin_root: Path) -> list:
    changed = []
    for role, path in charter_targets(plugin_root):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        fresh = charter_rendered(plugin_root, role, text)
        if fresh != text:
            path.write_text(fresh, encoding="utf-8")
            changed.append(f"agents/{path.name}: digest line generated")
    return changed


# --- the key page: what a role hands over, generated from the carriers (spec t-1765 X1-7) --------
# A role's file used to say which artifacts it writes, which witness it leaves and which fields its handoff form has - a
# copy of tables other files own. The page is those tables read for ONE role and printed: `artifact-writers.json` (who
# writes what, and why), `validate_artifacts.PHASE_JSON_KEYS` (the keys the validator requires), `stages.json` (the stage's
# required outputs, the gate's detectors, the witness), `stage-joints.json` (what else a gate reads of the role) and the
# handoff form of the role's stage (`handoff.spec_of`, so a field added to the form is on the page by itself). The role
# gets it as one slice in `inject-map.json`; `--check` refuses a page that is missing or stale, so it is never edited by hand.
def _json_of(path: Path):
    # THE reader (AR-13); errors=Exception keeps this caller's outcome (anything unreadable is "nothing there", a
    # nesting too deep for the parser included), kind=dict because every caller below goes on with `.get`.
    return read_json(path, kind=dict, errors=Exception)


def keys_targets(plugin_root: Path) -> list:
    """[(role, entry, path)] of the key pages inject-map.json names: the map is the declaration, as for slices."""
    imap = _json_of(plugin_root / "references" / "inject-map.json") or {}
    out = []
    for role, entries in (imap.get("roles") or {}).items():
        for entry in entries or []:
            e = str(entry)
            if e.startswith(SLICE_PREFIX) and Path(e).name == KEYS_NAME:
                out.append((role, e, plugin_root / e[len(PLUGIN_PREFIX):]))
    return sorted(out)


def _keys_outputs(plugin_root: Path, role: str, stage, writers: dict) -> list:
    """The `## Outputs` lines: the artifacts the role writes, the stage's required outputs, the gate's re-runs and the extra
    demands the joints registry makes of this very page. An unknown is declared, never left out (AR-28)."""
    lines = ["## Outputs", ""]
    mine = [(name, spec) for name, spec in writers.items()
            if str((spec or {}).get("writer") or "").split()[0:1] == [role]]
    keys = {}
    try:
        import validate_artifacts
        keys = validate_artifacts.PHASE_JSON_KEYS
    except Exception as exc:
        lines += [f"- NOT KNOWN: the validator's key table could not be read ({type(exc).__name__})."]
    for name, spec in mine:
        lines.append(f"- `{name}` - {' '.join(str(spec.get('why') or '').split())}")
        required = keys.get(Path(name).name)
        if required:
            lines.append("  Keys the validator requires: " + ", ".join(f"`{k}`" for k in required) + ".")
    if not mine:
        lines.append("- You write no artifact of your own: what you hand over is your handoff form and what your brief names.")
    if stage is None:
        lines += ["", f"NOT KNOWN: {role} is in no stage of stages.json, so its required outputs are not listed."]
        return lines
    lines += ["", f"Required at your stop (stage {stage.get('id')}): "
              + (", ".join(f"`{o}`" for o in stage.get("required_outputs") or []) or "nothing") + "."]
    ran = (stage.get("detectors") or {}).get(role) or []
    advice = {str(s) for s in stage.get("advice") or []}
    if ran:
        lines.append("Re-run by the gate at your stop: "
                     + ", ".join(f"`{s}`" + (" (advice only)" if s in advice else "") for s in ran) + ".")
    joints = _json_of(plugin_root / "references" / "stage-joints.json") or {}
    page = f"references/slices/{role}/{KEYS_NAME}"
    extra = []
    for joint in joints.get("joints") or []:
        for producer in joint.get("producers") or []:
            if role not in (producer.get("roles") or []):
                continue
            if not any(str(t.get("path") or "").replace("<role>", role) == page for t in producer.get("told") or []):
                continue
            extra += [f"- {producer.get('field')}: `{token}`" for token in producer.get("demands") or []]
    if extra:
        lines += ["The gate also reads:"] + list(dict.fromkeys(extra))
    return lines


def _keys_form(role: str, stage) -> list:
    """The `## Handoff form` lines: every field of the role's handoff form that it fills, with the word `required` or
    `optional` and the form's own hint (and a trailing `# Fill:` comment of the form, when it has one)."""
    lines = ["## Handoff form", ""]
    try:
        import handoff
        contract = handoff.contract_of(str(stage.get("id")), role) if stage else ""
        if not contract:
            return lines + [f"NOT KNOWN: no handoff contract is registered for {role} in handoffs/index.yaml."]
        doc = handoff.template(contract)
        spec = handoff.spec_of(doc)
        first = {}
        for path, node in doc.nodes.items():
            first.setdefault(re.sub(r"\[\d+\]", "[]", path), node)
        lines += [f"Contract `{contract}` (fill `work/handoffs/<dispatch>.yaml`; `handoff_check.py` reads it):", ""]
        for generic, field in spec.items():
            node = first.get(generic)
            if handoff.owned_by_contract(generic) or node is None or not handoff.is_placeholder(node.value):
                continue
            fill = (node.comment or "").lstrip("#").strip()
            fill = f" {fill}" if fill.startswith("Fill:") else ""
            # `handoff_check.check` never refuses an unfilled `blocked.*` field: it is filled only when the role is blocked
            word = "only when blocked" if generic.startswith("blocked.") else ("optional" if field.optional else "required")
            lines.append(f"- `{generic}` ({word}) - "
                         f"{' '.join(str(field.hint).split())}{fill}")
        shape = handoff.index().get("common_shape")
        if isinstance(shape, dict):
            lines += ["", "Every handoff form shares one skeleton (`common_shape` of handoffs/index.yaml): "
                      + ", ".join(f"`{k}`" for k in shape) + "."]
    except Exception as exc:
        lines.append(f"NOT KNOWN: the handoff form could not be read ({type(exc).__name__}).")
    return lines


def handoff_keys_page(plugin_root: Path, role: str) -> str:
    """The generated `references/slices/<role>/handoff-keys.md`: Outputs, Witness and the handoff form of ONE role. Pure and
    deterministic; a carrier it cannot read is named on the page, never dropped."""
    model = _json_of(plugin_root / "references" / "stages.json") or {}
    writers = (_json_of(plugin_root / "references" / "artifact-writers.json") or {}).get("artifacts") or {}
    try:
        from stage_guard import stage_of_role
        stage = stage_of_role(model, role)
    except Exception:
        stage = None
    lines = [f"<!-- generated by scripts/contract_slices.py (handoff_keys_page) from artifact-writers.json, stages.json, "
             f"stage-joints.json and handoffs/*.yaml for {role}; edit those, never this file -->",
             "", f"# Keys you hand over - {role}", ""]
    lines += _keys_outputs(plugin_root, role, stage, writers)
    witness = (model.get("witness") or {}).get(role)
    lines += ["", "## Witness", "",
              (f"Your witness artifact (stages.json `witness`): `{witness}`." if witness
               else f"NOT KNOWN: stages.json declares no witness for {role}.")]
    lines += [""] + _keys_form(role, stage)
    return "\n".join(lines).rstrip() + "\n"


def keys_findings(plugin_root: Path) -> list:
    out = []
    declared = set()
    for role, entry, path in keys_targets(plugin_root):
        declared.add(path.resolve())
        if path.parent.name != role:
            out.append(f"{entry}: injected to {role} but lives in the {path.parent.name} folder")
        elif not path.exists():
            out.append(f"{entry}: missing - run `python -B scripts/contract_slices.py --write`")
        elif path.read_text(encoding="utf-8").replace("\r\n", "\n") != handoff_keys_page(plugin_root, role):
            out.append(f"{entry}: stale - a carrier changed; run `python -B scripts/contract_slices.py --write`")
    slices_dir = plugin_root / SLICES_REL
    for path in sorted_paths(slices_dir.rglob(KEYS_NAME)) if slices_dir.exists() else []:
        if path.resolve() not in declared:
            out.append(f"{SLICES_REL}/{path.relative_to(slices_dir).as_posix()}: a key page no role is injected - "
                       "delete it or point inject-map.json at it")
    return out


def keys_write(plugin_root: Path) -> list:
    changed = []
    for role, _entry, path in keys_targets(plugin_root):
        if path.parent.name != role:
            continue
        fresh = handoff_keys_page(plugin_root, role)
        old = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
        if old != fresh:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(fresh, encoding="utf-8", newline="\n")
            changed.append(path.relative_to(plugin_root).as_posix())
    return changed


# --- the catalogue: slices named instead of delivered (P7.4) -------------------------------------
# The heaviest layer of a dispatch is the slices: 23,626 bytes for the code critic against 8,881 of
# charter. The plan's proposal is to hand a role their PATHS and one line of what is in each, the
# way the brief already hands it files and commands, and let it read what it needs - 15-20 KB off
# every dispatch, more than the whole charter budget.
#
# It is generated here and it is OFF by default, and the reason is a measurement this factory was
# built on: `inject_context.py`'s own note records that 0 of 290 dispatched subagents opened a file
# they were told to read. The brief is not a counter-example - it names files the role needs FOR
# its work (the diff, the plan), not rules it must obey. So the saving is real and the risk is
# real, and which one wins is not a thing to assume: `config.prompts.slices: on_demand` turns it
# on, `stage_compare` on a real story says whether the artifacts got worse, and until that number
# exists the default stays `inline`.
CATALOGUE_NAME = "index.md"
CATALOGUE_HEAD = """# Your rule files — paths, not copies

Each line is a file of YOUR rules and the sections it carries. They are not in this prompt: read
the ones your work touches BEFORE you write your artifact, the way you read the files the brief
names. A rule you did not read is still a rule the exit gate checks.
"""


def catalogue(plugin_root: Path, role: str) -> str:
    """The role's slices as paths plus what each carries."""
    lines = [CATALOGUE_HEAD]
    for t in targets(plugin_root):
        if t["role"] != role or not t["slice"].exists():
            continue
        if t["subject"] in COMMON_LAYER_SUBJECTS:      # always delivered, so never "named instead"
            continue
        text = t["slice"].read_text(encoding="utf-8")
        heads = [HEADING.match(ln).group(2).strip()
                 for ln in text.split("\n") if HEADING.match(ln)]
        rel = t["slice"].relative_to(plugin_root).as_posix()
        lines.append(f"- `{rel}` ({content_bytes(t['slice']):,} B) — "
                     + (", ".join(heads[:6]) + ("…" if len(heads) > 6 else "")
                        if heads else "one subject, no sections"))
    for _role, _entry, page in keys_targets(plugin_root):
        if _role == role and page.exists():
            heads = [HEADING.match(ln).group(2).strip() for ln in page.read_text(encoding="utf-8").split("\n")
                     if HEADING.match(ln)]
            lines.append(f"- `{page.relative_to(plugin_root).as_posix()}` ({content_bytes(page):,} B) — "
                         + ", ".join(heads))
    return "\n".join(lines) + "\n"


def catalogue_path(plugin_root: Path, role: str) -> Path:
    return plugin_root / SLICES_REL / role / CATALOGUE_NAME


def catalogue_roles(plugin_root: Path) -> list:
    return sorted({t["role"] for t in targets(plugin_root)})


def catalogue_write(plugin_root: Path) -> list:
    changed = []
    for role in catalogue_roles(plugin_root):
        path = catalogue_path(plugin_root, role)
        fresh = catalogue(plugin_root, role)
        old = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
        if old != fresh:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(fresh, encoding="utf-8", newline="\n")
            changed.append(path.relative_to(plugin_root).as_posix())
    return changed


def catalogue_findings(plugin_root: Path) -> list:
    out = []
    for role in catalogue_roles(plugin_root):
        path = catalogue_path(plugin_root, role)
        if not path.exists():
            out.append(f"{SLICES_REL}/{role}/{CATALOGUE_NAME}: missing — run "
                       "`python -B scripts/contract_slices.py --write`")
        elif path.read_text(encoding="utf-8").replace("\r\n", "\n") != catalogue(plugin_root, role):
            out.append(f"{SLICES_REL}/{role}/{CATALOGUE_NAME}: stale — run "
                       "`python -B scripts/contract_slices.py --write`")
    return out


def common_layer(plugin_root: Path) -> dict:
    """What every role is handed ALIKE, in bytes - the one measurer (AR-13) A22 and `--report` both call.

    {"list": the bytes of the `common` entries of the map,
     "shared": list + the bytes every role's slice of a common-layer subject has in common: the lead and
               the `all` sections, WITHOUT the provenance line (it names the role, so it is never alike),
     "per_role": {role: list + the bytes of that role's own slice of the common-layer subjects},
     "errors": [why a number could not be measured]}.

    The map unreadable -> {}. A common-layer source or slice that is missing while the map names a slice of it
    is an ERROR, never a zero: an unmeasured layer must not read as an empty one (AR-28)."""
    try:
        imap = json.loads((plugin_root / "references" / "inject-map.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    listed = sum(content_bytes(plugin_root / e[len(PLUGIN_PREFIX):])
                 for e in (imap.get("common") or [])
                 if str(e).startswith(PLUGIN_PREFIX) and (plugin_root / str(e)[len(PLUGIN_PREFIX):]).exists())
    errors: list = []
    per_role: dict = {}
    shared_rules = 0
    wanted = [t for t in targets(plugin_root) if t["subject"] in COMMON_LAYER_SUBJECTS]
    for subject in COMMON_LAYER_SUBJECTS:
        if not any(t["subject"] == subject for t in wanted):
            continue
        source = plugin_root / "references" / subject
        try:
            text = source.read_text(encoding="utf-8")
        except Exception as exc:
            errors.append(f"references/{subject}: cannot be read ({type(exc).__name__}) - the common layer is not measured")
            continue
        shared_rules += len(render(subject, "", text).split("\n", 1)[1].encode("utf-8"))
    for t in wanted:
        if not t["slice"].exists():
            errors.append(f"{t['entry']}: missing - the weight of {t['role']}'s common layer is not measured "
                          "(run `python -B scripts/contract_slices.py --write`)")
            continue
        per_role[t["role"]] = per_role.get(t["role"], listed) + content_bytes(t["slice"])
    return {"list": listed, "shared": listed + shared_rules, "per_role": per_role, "errors": errors}


def report(plugin_root: Path) -> str:
    """Per role: what the map delivers now, and what the same entries would weigh unsliced."""
    try:
        imap = json.loads((plugin_root / "references" / "inject-map.json").read_text(encoding="utf-8"))
    except Exception:
        return "inject-map.json is unreadable"
    layer = common_layer(plugin_root)
    common = layer["list"]
    lines = [f"common layer: list {common:,} bytes, shared with every role {layer['shared']:,} bytes"]
    lines += [f"common layer NOT MEASURED: {why}" for why in layer["errors"]]
    lines += [f"common list (every role): {common:,} bytes",
              f"{'role':24} {'now':>8} {'unsliced':>9} {'saved':>8} {'on_demand':>10} {'would save':>11}"]
    for role, entries in sorted((imap.get("roles") or {}).items()):
        now = common
        before = common
        for entry in entries or []:
            e = str(entry)
            if not e.startswith(PLUGIN_PREFIX):
                continue
            path = plugin_root / e[len(PLUGIN_PREFIX):]
            source = (plugin_root / "references" / Path(e).name) if (e.startswith(SLICE_PREFIX)
                                                                      and Path(e).name != KEYS_NAME) else path
            now += content_bytes(path) if path.exists() else 0
            before += content_bytes(source) if source.exists() else 0
        # What `config.prompts.slices: on_demand` would deliver instead: everything that is not a
        # slice, plus the catalogue. The saving is the largest one available in a dispatch prompt,
        # and it is printed here so it is a number rather than an argument (P7.4).
        named = common
        for entry in entries or []:
            e = str(entry)
            # a common-layer slice is delivered in every mode: it stays in the `on_demand` weight
            if not e.startswith(PLUGIN_PREFIX) or (e.startswith(SLICE_PREFIX)
                                                   and Path(e).name not in COMMON_LAYER_SUBJECTS):
                continue
            path = plugin_root / e[len(PLUGIN_PREFIX):]
            named += content_bytes(path) if path.exists() else 0
        index = catalogue_path(plugin_root, role)
        if any(str(e).startswith(SLICE_PREFIX) and Path(str(e)).name not in COMMON_LAYER_SUBJECTS
               for e in entries or []) and index.exists():
            named += content_bytes(index)
        lines.append(f"{role:24} {now:8,} {before:9,} {before - now:8,} {named:10,} "
                     f"{now - named:11,}")
    return "\n".join(lines)


def dropped(plugin_root: Path, role: str, count: int = 3) -> list:
    """The largest sections this role's slices leave behind — the report of what the saving
    actually was, section by section, not as a lump of bytes."""
    out = []
    for t in targets(plugin_root):
        if t["role"] != role or not t["source"].exists():
            continue
        _, sections = parse(t["source"].read_text(encoding="utf-8"))
        for s in sections:
            if not s.wants(role):
                out.append((s.bytes(), f"{t['subject']} `{s.title}`"))
    return [f"{name} ({size:,} B)" for size, name in sorted(out, reverse=True)[:count]]


def _selftest() -> int:
    doc = ("# Subject\n\nThe lead.\n\n"
           "<!-- roles: qa-automator -->\n## Kept\n\nkept body\n\n"
           "<!-- roles: all -->\n## Shared\n\nshared body\n\n"
           "### Inherited\n\ninherited body\n\n"
           "<!-- roles: qa-runner -->\n### Split\n\nsplit body\n\n"
           "## Gone <!-- roles: qa-runner -->\n\n```\n## not a heading <!-- roles: all -->\n```\n")
    bad = 0

    def check(name: str, ok: bool, detail: str = "") -> None:
        nonlocal bad
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else " | " + detail))
        bad += 0 if ok else 1

    lead, sections = parse(doc)
    check("lead is everything before the first heading", lead.strip().endswith("The lead."), lead)
    check("a fenced line is not a heading", [s.title for s in sections].count("not a heading") == 0,
          str([s.title for s in sections]))
    automator = render("subject.md", "qa-automator", doc)
    check("the marked section is in the slice", "kept body" in automator)
    check("an `all` section is in every slice", "shared body" in automator)
    check("an unmarked `###` inherits its `##`", "inherited body" in automator)
    check("a marked `###` leaves the parent's readers", "split body" not in automator)
    check("another role's section is dropped", "Gone" not in automator)
    check("the marker itself never reaches the role", "roles:" not in automator.split("\n", 1)[1])
    check("the slice names its source", "plugin:references/subject.md" in automator.split("\n")[0])
    runner = render("subject.md", "qa-runner", doc)
    check("the split `###` goes to its own role", "split body" in runner and "kept body" not in runner)
    unnamed = render("subject.md", "qa-scout", doc)
    check("a role named on no marker still gets the `all` sections and nothing else",
          "shared body" in unnamed and "kept body" not in unnamed and "split body" not in unnamed)
    print(f"contract_slices selftest: {'ok' if not bad else str(bad) + ' failed'}")
    return 1 if bad else 0


def main() -> int:
    try:
        import console_io
        console_io.utf8_stdio()
    except ImportError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--plugin-root", default=str(PLUGIN_ROOT))
    args = ap.parse_args()
    root = Path(args.plugin_root).resolve()
    if args.selftest:
        return _selftest()
    if args.write:
        changed = write(root)
        for path in changed:
            print("wrote " + path.relative_to(root).as_posix())
        print(f"slices: {len(targets(root))} declared, {len(changed)} rewritten")
        for line in keys_write(root):
            print("wrote " + line)
        for line in charter_write(root):
            print("wrote " + line)
        for line in catalogue_write(root):
            print("wrote " + line)
        problems = findings(root) + charter_findings(root) + catalogue_findings(root)
        for line in problems:
            print("STILL WRONG: " + line)
        return 2 if problems else 0
    if args.report:
        print(report(root))
        return 0
    problems = findings(root) + charter_findings(root) + catalogue_findings(root)
    for line in problems:
        print("SLICE: " + line)
    if not problems:
        print(f"slices: {len(targets(root))} declared, all present and fresh; "
              f"{len(keys_targets(root))} key pages; "
              f"{len(charter_targets(root))} charters carry a generated digest line")
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
