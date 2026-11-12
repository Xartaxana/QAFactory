"""Check a filled handoff form, and repair by code everything code can already answer.

The contract is the schema (`handoff.spec`), so this refuses with the field, the problem and
**the allowed values for that field** - never with a traceback and never with "invalid".

Three things happen here, in this order:

  --fix      values DERIVED from the artifacts on disk are written in. `run_witness` sits in
             `runs[]` of the manifest being refused; the findings file is on disk; the pinned
             case version is in `story-case-links.json`. On TP1-13797 those three refusals
             alone woke a 218k-token role again and again: twenty-three resumed sessions at S5
             ($14.15) and nineteen conductor sessions ($5.97). Code knew every answer.
  the judge  ADVISES, never writes the role's word. A stage S1-S4 list is a PROPOSED one: a word of
             it passes, `new: <word> -- <why>` passes the form and is kept in `proposed[]` for the
             stage critic to judge, anything else is refused with that door. With a judge on, the
             word of the list nearest to what the role wrote (a System One question) is printed
             under the refusal and kept in `suggested[]`; the field is never changed. Only a blank
             field of the S6 row (`_ask_judge_row`) is still filled by a judge, in `judged[]`.
  the claims a claim the form asserts is verified against the artifacts when `CLAIMS` holds a
             verifier for its key. A false claim is caught here, before the receiving role
             spends a turn believing it. A key with no verifier is the role's own statement, and
             a verifier that could not measure gives NO verdict (it returns `(None, reason)`):
             the claim is neither accepted nor refused, and the reason is printed.

One contract may name an empty item list as its own legitimate answer (`null_outcome` in the contract, FR-23):
S7's `scope` is empty when nothing is to be repaired, and the check accepts that ONLY while `work/triage.json`
agrees (see `_null_outcome_view`); every other contract still refuses an empty `scope`.

The role's own words reach the form in ONE place (SC1-2): `apply_values`. Three sources pass it, in this order,
before anything is measured or derived - the waiting file beside the form (`<dispatch>.values.yaml`), `--values`,
then `--set` (the most explicit and the latest word wins). A values file is `path: value` lines (or one flat JSON
object), the paths the refusal prints, with the row index: `scope[1].id`. The index equal to the number of rows
opens the next row from the CONTRACT's own row; a path with a hole before it is a problem and opens nothing; an
unknown path is a problem beside the values that were applied, never a stop. A waiting file is applied by the next
WRITING run (`--fix`, `--values`, `--set`) and renamed `<dispatch>.values.applied.yaml`; a read-only run only
reports the merged form and writes nothing (FR-45).

A form that is not ready is refused in ONE block (SC1-2 part A2): a line per problem, then ONE command - the `path: value`
skeleton with the allowed values inline and a line for every path to fill - for a role with Bash, and beside it always
the door of the values file (a role without a shell writes that file with one Write). `values_report` is the same
check for a values text not yet written; it never writes and never asks the judge, and leaves out a blank field that
`--fix` fills (`_code_fills`).

  handoff_check.py --file F [--task T] [--fix] [--set path=value] [--values FILE|-] [--json]

Exit 0 green, 1 problems remain, 2 the file or the contract cannot be read (or a named --values file is absent).
"""
import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract as C  # noqa: E402
import handoff  # noqa: E402
import host_adapter  # noqa: E402
import null_outcomes as NO  # noqa: E402
from role_cli import REPAIR_MARKER  # noqa: E402
import hooklib  # noqa: E402
from hooklib import sorted_paths  # noqa: E402

try:
    import judge  # noqa: E402
except Exception:                                    # pragma: no cover - judge is optional
    judge = None


class Artifacts:
    """Everything a deriver may read, loaded once and only when asked for."""

    def __init__(self, root: Path, dispatch: str = ""):
        self.root = root
        self._cache = {}
        # The dispatch the form belongs to (its file name), for the claims that are scoped to it.
        # Not `dispatch`: `_review_receipt` reads that name and nothing has ever set it.
        self.form_dispatch = dispatch
        # Claims a verifier could not judge: `{"claim": name, "reason": text}`. Filled by
        # `_check_claims`, printed by `main`.
        self.no_verdict = []

    def json(self, rel: str):
        if rel not in self._cache:
            self._cache[rel] = handoff.load_json(self.root / rel)
        return self._cache[rel]

    def text(self, rel: str) -> str:
        try:
            return (self.root / rel).read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return ""

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists()

    @property
    def manifest(self):
        return self.json("work/automation-manifest.json") or {}

    @property
    def run(self):
        return self.json("work/run-report.json") or {}

    @property
    def links(self):
        return self.json("state/story-case-links.json") or {}

    @property
    def pipeline(self):
        return self.json("pipeline.json") or {}

    @property
    def ledger(self):
        return self.json("work/ledger.json") or {}

    @property
    def project(self) -> Path:
        """The project root of this story (the marker walk from the task root, `hooklib.project_root`)."""
        if "<project>" not in self._cache:
            import hooklib
            self._cache["<project>"] = hooklib.project_root({"cwd": str(self.root)})
        return self._cache["<project>"]

    @property
    def config(self) -> dict:
        """The project's `qa-factory/config.json`, {} when there is none."""
        if "<config>" not in self._cache:
            import hooklib
            loaded = hooklib.load_config({"cwd": str(self.root)})
            self._cache["<config>"] = loaded if isinstance(loaded, dict) else {}
        return self._cache["<config>"]


# ------------------------------------------------------------------ what code can derive
def _run_witness(art, doc, row=None):
    runs = art.manifest.get("runs") or []
    for entry in reversed(runs):
        path = entry.get("summary_path") or entry.get("witness")
        if path:
            return path, "automation-manifest.runs[]"
    witness = art.manifest.get("run_witness") or art.run.get("witness")
    if witness:
        return witness, "automation-manifest.run_witness"
    # every test pending its absent side: no run exists, the collect row is the evidence the manifest carries (t-2181 PC-4, B3)
    import acceptance
    if acceptance.run_witness_excused(art.manifest) == "pending":
        collect = next((e for e in reversed(runs) if isinstance(e, dict) and e.get("kind") == "collect" and e.get("label")), None)
        if collect:
            return collect["label"], "automation-manifest.runs[] collect"
    return None


def _review_receipt(art, doc, row=None):
    """`work/windows/<dispatch>.json` — the window `window_record.py` wrote for THIS dispatch.

    TP1-13797, 26.09: the file existed, the field carried its own placeholder, `--fix` did not
    look, and the refusal went to the conductor and then to the person — who can produce a review
    receipt even less than the role can. The dispatch id is in the form's own name."""
    dispatch = str(doc.get("header.dispatch") or doc.get("dispatch") or "").strip()
    if not dispatch:
        dispatch = getattr(art, "dispatch", "") or ""
    if not dispatch:
        return None
    rel = f"work/windows/{dispatch}.json"
    return (rel, "window_record.py wrote it for this dispatch") if (art.root / rel).is_file() else None


def _findings_file(art, doc, row=None):
    """The findings file of THIS form's dispatch: `work/test-code/critic-findings-<dispatch>.md` (the registry row
    `critic-findings-*.md`, one file per critic dispatch, so a window's handoff never points at another window's findings).
    Absent: `work/test-code/critic-findings.md`, the one file of a story started before (an old story; the new world never
    writes it). Never "the newest on disk": that was another window's file when two ran. The S4 case critic's file
    (`work/test-cases/`) answers an S4 form ONLY; an S5 form whose own file is missing gets None (t-2098 F2, AR-19)."""
    import findings_path
    dispatch = str(getattr(art, "form_dispatch", "") or doc.get("header.dispatch") or doc.get("dispatch") or "").strip()
    stage = _form_stage(art, dispatch)
    if stage == "S4":
        for rel in findings_path.s4_files(art.root, nested=False):
            return f"work/test-cases/{rel.name}", "the findings file on disk"
        return None
    # an unknown stage takes only the file named after the form itself, never the old single file (a guess; t-2106 X4b)
    found = findings_path.resolve(art.root, dispatch, allow_old=bool(stage))
    if found:
        return found, ("the findings file of this dispatch" if found == findings_path.per_dispatch(dispatch)
                       else "the findings file of a story from before one file per dispatch")
    return None


def _form_stage(art, dispatch: str) -> str:
    """The stage a form's dispatch belongs to: its record's `stage`, else the `S<n>` its id starts with, else "". Never raises."""
    try:
        from s5_precheck import dispatch_record
        stage = str((dispatch_record(art.root, dispatch) or {}).get("stage") or "")
    except Exception:  # noqa: BLE001 - an unreadable record is "unknown", and unknown is not S4
        stage = ""
    if not stage:
        head = dispatch.split("-", 1)[0]
        stage = head if len(head) > 1 and head[0] == "S" and head[1:].isdigit() else ""
    return stage


def implementation_entries(manifest) -> list:
    """The implementation entries of a context manifest: `implementations[]` when it is a non-empty list, else
    `[implementation]` when that is an object, else []. The one reader of this shape the handoff uses (queued:
    `context_bundle.build` and `judge_diff._diff_files` still carry their own two-line copy)."""
    manifest = manifest if isinstance(manifest, dict) else {}
    listed = manifest.get("implementations")
    if isinstance(listed, list) and listed:
        return listed
    single = manifest.get("implementation")
    return [single] if isinstance(single, dict) else []


def _checkout_path(repo_id: str, cfg: dict, project: Path):
    """The configured checkout of a repository id: `implementation_repos[].repo_id` -> `local_path`, else
    `code_repos[].name` -> `path`, relative to the project root. None when the config names no such checkout."""
    for key, id_field, path_field in (("implementation_repos", "repo_id", "local_path"), ("code_repos", "name", "path")):
        for repo in cfg.get(key) or []:
            if isinstance(repo, dict) and str(repo.get(id_field) or "").strip() == repo_id:
                where = str(repo.get(path_field) or "").strip()
                if where:
                    return (Path(where) if Path(where).is_absolute() else project / where).resolve()
    return None


def implementation_checkout(entry, cfg: dict, project: Path, diff_name: str) -> tuple:
    """`(checkout folder, "")` or `(None, reason)`: the checkout on THIS machine of the repository the manifest `entry` names, for
    the diff `diff_name` (G1-2, axis 10: the one «entry -> checkout» survivor, called by `blast_radius` and `base_slice`). The id is
    `repo_id or repo`, stripped; an EMPTY id never reaches `_checkout_path` (it would match a config entry that has no id). The
    reason is the text both callers show: `no manifest entry for <diff>` / `no repository id for <diff>` / `no checkout of <id> on
    this machine` (config names no such folder, or it is not a folder here)."""
    if not isinstance(entry, dict):
        return None, f"no manifest entry for {diff_name}"
    repo_id = str(entry.get("repo_id") or entry.get("repo") or "").strip()
    if not repo_id:
        return None, f"no repository id for {diff_name}"
    found = _checkout_path(repo_id, cfg, project)
    if found is None or not found.is_dir():
        return None, f"no checkout of {repo_id} on this machine"
    return found, ""


def _impl_checkout(art):
    """The folder the diff's paths are relative to: the checkout of the one implementation repository the manifest
    names, through the PROJECT's config (the manifest's own `local_path` is a hint from some machine and is never
    the base). None when no entry, more than one entry (ambiguous), no `repo_id` / `repo`, no configured checkout, or a
    checkout that is not a folder on this machine: then no config word can be matched to the diff's paths."""
    entries = implementation_entries(art.json("work/context-manifest.json"))
    if len(entries) != 1 or not isinstance(entries[0], dict):
        return None
    repo_id = str(entries[0].get("repo_id") or entries[0].get("repo") or "").strip()   # `repo` as source_exclusions reads it
    found = _checkout_path(repo_id, art.config, art.project) if repo_id else None
    return found if found is not None and found.is_dir() else None


# The production rule behind the S1 count `implementation.diff.production_files` and its edges (B-407 A, G1-1; the question is
# `test_files.file_kind`'s, the one rule). The count is terminal: no field downstream is measured against it, so a false "test" /
# "docs" here only miscounts a size figure. The unsafe error of the same rule lives in `exit_gate.new_production_files`, which
# feeds `exit_gate.grounding_errors` (the S2 gate): a new production file taken for a test escapes it (a test-looking NAME
# alone, or code under `docs/`, is not one).
# - a counted file is of kind `production` or `config`; `test`, `docs` (`.md`, a non-code file under `docs/`) and `generated`
#   (`.lock`) are not counted.
# - the project's word is matched against the diff's paths only with the checkout they are relative to
#   (`_impl_checkout`); with none, the config is not consulted at all and the usual names decide (an extra
#   file counted, never a lost one).
# - only a `test_locations` entry (the person's word) excludes a file alone. A carrier that names a folder
#   (`run.levels`, `profiles[].roots.test`, `tests_root`) hides the usual names in the verdict and may name a folder
#   that is not wholly tests: a file under it leaves the count only with a usual name of its own; a classic folder or an
#   agreeing name-and-folder pair (`test_files._production_names`) is what excludes without the config.
def _production_files(files: list, cfg: dict, art) -> list:
    import test_files
    base = _impl_checkout(art)
    return test_files.production_files(files, {"production", "config"}, cfg if base is not None else {},
                                       base=base, root=art.project)


def _diff_counts(kind):
    def derive(art, doc, row=None):
        import diff_pass
        found = diff_pass.index(art.root / "work")
        records = found["files"]
        if not records:
            return None                       # no diff, or only empty ones: the field stays the role's
        source = ", ".join(dict.fromkeys(record["diff"] for record in records))
        unread = any(item["kind"] == "unreadable" for item in found["refusals"])
        if kind == "hunks":
            # A diff refused (combined, path unknown) or unread has hunks nobody counted: None, never a smaller number.
            return (None if found["refusals"] else sum(1 for r in records for h in r["hunks"] if not h.get("pseudo"))), source
        if unread:
            return None, source               # a diff nobody could read has files nobody counted
        if kind == "files":
            return len(records), source
        return len(_production_files([record["path"] for record in records], art.config, art)), source
    return derive


def _totals(art, doc, row=None):
    totals = art.run.get("totals")
    return (json.dumps(totals, sort_keys=True), "run-report.totals") if totals else None


def _window_totals(art, doc, row=None):
    totals = art.run.get("current_totals")
    return (json.dumps(totals, sort_keys=True), "run-report.current_totals") if totals else None


def _execution_status(art, doc, row=None):
    value = art.run.get("execution_status")
    return (value, "run-report.execution_status") if value else None


def _case_version(art, doc, row=None):
    """The pinned version of the case this row answers - from the orchestrator's own links."""
    case = (row or {}).get("case") or (row or {}).get("id")
    if not case:
        return None
    for link in art.links.get("links") or []:
        if link.get("case_id") == case:
            return link.get("version"), "story-case-links.links[]"
    return None


def _material_collected(art, doc, row=None):
    """What S1 actually collected FOR THIS SOURCE, as paths, so the next role can read it.

    TP1-13797, 26.09: the factory collected four merge requests of the precedent ticket
    through its own authenticated route and the handover said nothing about them — the contract
    had a place for the source's decision and none for the source's material. Collected and not
    handed over is the same as not collected, only paid for."""
    wanted = str((row or {}).get("id") or "").strip()
    if not wanted:
        return None
    inventory = art.json("work/source-inventory.json") if hasattr(art, "json") else {}
    if not inventory:
        try:
            inventory = json.loads((art.root / "work" / "source-inventory.json")
                                   .read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
    for source in inventory.get("sources") or []:
        ref = str(source.get("canonical_ref") or "")
        if wanted not in (str(source.get("source_id") or ""), ref.rsplit("/", 1)[-1]):
            continue
        paths = []
        for kind in ("external_media", "attachments"):
            for item in ((source.get("materials") or {}).get(kind) or {}).get("items") or []:
                local = str(item.get("local_ref") or item.get("analysis_evidence_ref") or "").strip()
                if local and item.get("status") in ("read", "partial"):
                    digest = local.replace(".json", ".md")
                    paths.append(digest if (art.root / "work" / digest).is_file() else local)
        return (", ".join(dict.fromkeys(paths)) if paths else "-", "source-inventory materials")
    return None


def _case_front_matter(art, case: str) -> dict:
    """The case file's own front matter: what the designer wrote there, not a second copy."""
    from s5_precheck import case_files_named  # the one strict-by-name lookup (t-911): lazy, as at the other S5 import
    for path in case_files_named(art.root / "work" / "test-cases", case):
        head = path.read_text(encoding="utf-8", errors="replace").split("---")
        block = head[1] if len(head) > 2 else ""
        out = {}
        for line in block.splitlines():
            key, _, value = line.partition(":")
            if value.strip():
                out[key.strip()] = value.strip()
        return out
    return {}


def _requirements_of(art, doc, row=None):
    """The requirement ids the case itself says it covers (`covers:` in its front matter)."""
    case = (row or {}).get("case") or (row or {}).get("id") or ""
    # A case id in the project's own form (`config.case_id_form`), with or without its area: the
    # check used to be a prefix test on the default form, so a project-form case never reached its
    # own front matter and the handover field stayed empty (B-013, FR-17).
    bare = C.split_case_key(str(case), art.root)[1]
    front = _case_front_matter(art, bare) if C.is_case_id(bare, art.root) else {}
    covers = front.get("covers") or ""
    # Requirement ids (`R-12`), read by their one reader (`contract.REQ_ID_RE`): `covers:` never held ticket keys, and
    # the old `[A-Z]+-\d+` also read an `AC-1` that is no requirement (B-405: a third key variant, not a key at all).
    ids = ", ".join(C.REQ_ID_RE.findall(covers))
    return (ids, f"{case}.md front matter `covers`") if ids else None


def _plan_row_of(art, doc, row=None):
    """The plan row this case answers — the case file's own front matter says it (`plan_row:`).

    Not from the plan: the plan is written before the cases exist and names none of them, so the
    only place this fact lives is the case the designer wrote."""
    case = str((row or {}).get("case") or (row or {}).get("id") or "")
    bare = C.split_case_key(case, art.root)[1]
    if not C.is_case_id(bare, art.root):
        return None
    value = _case_front_matter(art, bare).get("plan_row") or ""
    found = re.search(r"TS-\d+", value)
    return (found.group(0), f"{case}.md front matter `plan_row`") if found else None


def _delivery_ready(art, doc, row=None):
    """The ledger's verdict WORD (`yes`, `after_checks`, `no`; `unknown` when the ledger disagrees with itself), through the
    one reader (t-305 N8) - never the truthiness of a field, so the string "no" is not read as ready. None when the ledger
    holds neither the word nor the bool: nothing was computed."""
    if art.ledger.get("delivery_ready") is None and art.ledger.get("delivery_verdict") is None:
        return None
    import delivery_verdict as DV
    return DV.word_of(art.ledger), "ledger.delivery_verdict"


def _blocked_by(art, doc, row=None):
    value = art.ledger.get("blocked_by")
    return (json.dumps(value), "ledger.blocked_by") if value else None


def _size(art, doc, row=None):
    sizing = art.json("work/sizing.json") or {}
    return (sizing.get("size"), "sizing.json") if sizing.get("size") else None


def manifest_impl_source(manifest) -> str:
    """The implementation source a context manifest names, from the shapes the scout writes (validate_artifacts: the summary
    `implementation.source`, the list `implementations[].source` whose first entry IS the primary one, and the top-level
    `implementation_source` of the older shape) - ONE reader of all three, so `none` (no diff found) is visible to every caller
    (the handover form, the driver's no-diff question). '' when the manifest is not a dict or names none."""
    if not isinstance(manifest, dict):
        return ""
    summary = manifest.get("implementation") if isinstance(manifest.get("implementation"), dict) else {}
    rows = manifest.get("implementations") if isinstance(manifest.get("implementations"), list) else []
    first = rows[0] if rows and isinstance(rows[0], dict) else {}
    return str(summary.get("source") or first.get("source") or manifest.get("implementation_source") or "")


def _impl_source(art, doc, row=None):
    manifest = art.json("work/context-manifest.json") or {}
    value = art.pipeline.get("implementation_source") or manifest_impl_source(manifest)
    return (value, "pipeline.json / context-manifest.json") if value else None


def _version_of(art, doc, row=None):
    path = (row or {}).get("path")
    if not path or "<" in str(path):
        return None
    digest = handoff.sha(art.root / str(path))
    return (digest, f"sha256 of {path}") if digest else None


def _probe_list(art, doc, row=None):
    # the live probes' records, and the product probes' (`work/probes/product/`, written by red_sandbox.py)
    probes = sorted_paths((art.root / "work" / "probes").glob("*.json"))
    product = sorted_paths((art.root / "work" / "probes" / "product").glob("*.json"))
    found = [f"work/probes/{p.name}" for p in probes] + [f"work/probes/product/{p.name}" for p in product]
    return (found, "work/probes/") if found else None


def _tests_list(art, doc, row=None):
    files = []
    for test in art.manifest.get("tests") or []:
        path = test.get("file") or test.get("path")
        if path and path not in files:
            files.append(path)
    return (files, "automation-manifest.tests[].file") if files else None


def _runtime_provenance(art, doc, row=None):
    records = sorted_paths((art.root / "evidence").glob("runtime-provenance-*.json"))
    if not records:
        return None
    return f"evidence/{records[-1].name}", f"the newest of {len(records)} provenance records"


def _story_relative(value) -> str:
    """The path `value` names when it is a relative path that stays inside the story, else "".

    A placeholder, a dash, a path in either dialect's absolute form (a drive, a leading slash) and any `..` all give "":
    a verifier that reads a file a role named must never be led out of the story by the role's own word (SC1-2 part C)."""
    from pathlib import PurePosixPath, PureWindowsPath
    text = str(value if value is not None else "").strip()
    if not text or text == "-" or handoff.is_placeholder(text):
        return ""
    for flavour in (PurePosixPath, PureWindowsPath):
        pure = flavour(text)
        if pure.is_absolute() or pure.drive or pure.root or ".." in pure.parts:
            return ""
    return text


ROLLCALL_DEFAULT_FILE = "work/test-cases/critic-findings.md"


def _rollcall_file(doc) -> str:
    """The findings file the case critic's roll-call lives in: the form's own `review.findings_file` unless that is
    still a placeholder, then the contract's default."""
    named = doc.get("review.findings_file") if doc is not None else None
    return ROLLCALL_DEFAULT_FILE if handoff.is_placeholder(named) else str(named).strip()


def _rollcall(art, doc) -> dict | None:
    """`critic_rollcall.derive` over the roll-call rows of this form's findings file, or None.

    None is the answer to everything that is not a roll-call: no file named inside the story, no file on disk, a file with
    no `## Roll-call` rows. `derive([])` would say `0 of 0 reviewed` and the digest would then read as a measurement of
    nothing (FR-59, FR-41): an empty roll-call writes no digest and proves no claim."""
    import critic_rollcall
    rel = _story_relative(_rollcall_file(doc))
    if not rel or not (art.root / rel).is_file():
        return None
    rows = critic_rollcall.parse_rollcall(art.text(rel), art.root)
    return critic_rollcall.derive(rows) if rows else None


def _rollcall_digest(art, doc, row=None):
    """`review.rollcall`: the `n of m reviewed` that `critic_rollcall.derive` computes - never typed by the role."""
    try:
        found = _rollcall(art, doc)
    except Exception:
        return None
    return (found["digest"], "critic_rollcall.derive") if found else None


# Sections code fills whole, not field by field.
LIST_DERIVERS = {
    "artifacts.tests": _tests_list,
    "artifacts.probes": _probe_list,
}

DERIVERS = {
    "artifacts.runtime_provenance": _runtime_provenance,
    "probes.runtime_provenance": _runtime_provenance,
    # The same value under the name a third contract gives it. A deriver wired into two of the
    # three paths that ask for it is not adopted (FR-17): the automator's handover to the runner
    # asked for `runtime.provenance` and got nothing, and the role typed it by hand or left it.
    # Found by the FR-11 walk of every required field, 28.09.
    "runtime.provenance": _runtime_provenance,
    "artifacts.run_witness": _run_witness,
    "run.witness": _run_witness,
    # The repair round's own verification summary: the same witness, per round.
    "rounds[].verify.witness": _run_witness,
    "review.findings_file": _findings_file,
    "review.receipt_ref": _review_receipt,
    "review.rollcall": _rollcall_digest,
    "artifacts.probes": _probe_list,
    "artifacts.tests": _tests_list,
    "implementation.diff.files": _diff_counts("files"),
    "implementation.diff.hunks": _diff_counts("hunks"),
    "implementation.diff.production_files": _diff_counts("production"),
    "implementation.source": _impl_source,
    "run.totals": _totals,
    "run.window_totals": _window_totals,
    "run.execution_status": _execution_status,
    "delivery.ready": _delivery_ready,
    "delivery.blocked_by": _blocked_by,
    "size.computed": _size,
    "scope[].case_version": _case_version,
    "scope[].material_collected": _material_collected,
    "inputs_read[].version": _version_of,
}


# The same fact under the same name, in whatever section a contract puts it. Judgement fields
# (`reason`, `state`, `what`, `origin`) are deliberately absent: those are the role's to write,
# and a deriver there would be code answering a question that was asked of a person's stand-in.
BY_LEAF = {
    "case_version": _case_version,
    "requirements": _requirements_of,
    "plan_row": _plan_row_of,
}


# ------------------------------------------------------------------- what code can verify
def _claim_instance_versions(art):
    stale, total = [], 0
    current = {l.get("case_id"): l.get("version") for l in (art.links.get("links") or [])}
    for test in art.manifest.get("tests") or []:
        links = test.get("case_version_links") or []
        if not links:
            continue
        total += 1
        for link in links:
            if current.get(link.get("case_id")) and link.get("version") != current[link.get("case_id")]:
                stale.append(test.get("instance_id") or test.get("test"))
                break
    if not total:
        return None
    return (not stale, f"{len(stale)} of {total} instances carry a version other than the pin"
                       + (f" ({', '.join(str(s) for s in stale[:3])}...)" if stale else ""))


def _claim_traceability(art):
    return (art.exists("work/traceability.json"),
            "work/traceability.json is on disk" if art.exists("work/traceability.json")
            else "work/traceability.json does not exist - traceability.py --write never ran")


def _claim_impl_recorded(art):
    value = art.pipeline.get("implementation_source")
    return (bool(value), f"pipeline.implementation_source is {value!r}")


def _claim_size_recorded(art):
    value = art.pipeline.get("size")
    return (bool(value), f"pipeline.size is {value!r}")


def _claim_bug_has_a_draft(art):
    """`no_bug_reaches_the_gate_without_a_draft_and_a_triage_row` (G1-9): every draft the writer left
    (`bug_records.draft_paths`: `work/bug-drafts/*.json`, then the old `bug-drafts/*.json`) rests on a triage row
    whose verdict is APP_BUG, and every APP_BUG row of `work/triage.json` has a draft - the pairing gate B
    rehearses, ONE helper (`bug_records.pair_drafts`). Nothing on either side holds (I3). The error goes one
    way: a refusal costs the role a round, a pass over an unpaired bug would not. A `work/triage.json` that
    exists and cannot be read as a triage is no verdict (`_triage_view`'s own reason), never 'zero rows'. The same
    for a draft folder that exists and cannot be listed (`bug_records.draft_listing`): 'drafts unreadable: <reason>',
    never 'no drafts' - a pass over a folder nobody could read would be a pass on an unknown (FR-59, FR-41).

    One bug, many manifestations (t-2187 N2, 5.2): an APP_BUG row a draft's `manifestations[].triage_row` names is covered by that draft
    (`pair_drafts`); a manifestation naming no row or a non-APP_BUG row, and a draft with 2+ manifestations whose `mechanism` is not
    confirmed by a basis that re-reads (`bug_records.merged_unconfirmed`, F-2 (a)) are each one problem with its door. The error goes
    one way: toward the analyst splitting the draft."""
    import bug_records as BR
    paths, unreadable = BR.draft_listing(art.root)
    if unreadable:
        return (None, "drafts unreadable: " + "; ".join(unreadable) + " - the claim cannot tell which bug drafts "
                "exist; say so under `blocked` in the form, so the conductor can make the folder listable")
    drafts = [(path.name, C.load_json(path)) for path in paths]
    rows = []
    if art.exists("work/triage.json"):
        rows, why = _triage_view(art)
        if rows is None:
            return (None, why)
    paired = BR.pair_drafts(drafts, rows, filed=BR.filed_draft_names(art.root))
    seen = (f"{len(drafts)} draft(s) in work/bug-drafts/*.json (or the old bug-drafts/*.json) and "
            f"{paired['app_bug_rows']} APP_BUG triage row(s) in work/triage.json")
    problems = []
    if paired["no_row"]:
        problems.append(f"no triage row for {_shown(paired['no_row'])} - the draft goes back to triage, "
                        "where the analyst adds the row its triage_ref names")
    if paired["not_app_bug"]:
        problems.append("the row is not APP_BUG for "
                        + _shown([f"{name} ({', '.join(found) or 'empty'})" for name, found in paired["not_app_bug"]])
                        + " - the verdict is corrected or the draft is withdrawn")
    if paired["app_bug_without_draft"]:
        problems.append(f"no draft for the APP_BUG row {_shown(paired['app_bug_without_draft'])} - the draft is "
                        "written, or the verdict is corrected")
    for name in paired["duplicate_draft"]:
        problems.append(f"the row of the draft {name} says its red is another case's defect (`blocking_check`); its draft "
                        "duplicates the blocker's - withdraw it or drop `blocking_check`")
    for case, blocker in paired["blocker_draft_misses_case"]:
        problems.append(f"the draft of {blocker} does not list {case} in `cases`; add it (row {case} says its red is "
                        f"{blocker}'s defect)")
    problems += BR.same_location_problems(paired)
    # One bug, many manifestations (t-2187 N2): a manifestation that names no row, or a row that is not APP_BUG, and a merge whose
    # cause the factory cannot re-read (`BR.merged_unconfirmed`, the only reader here that opens files). Every refusal has its door.
    for name, label in paired["manifestation_no_row"]:
        problems.append(f"a manifestation of the draft {name} names the row {label}, which is no row of work/triage.json - add the row "
                        "the manifestation names, or remove the manifestation")
    for name, label, found in paired["manifestation_not_app_bug"]:
        problems.append(f"a manifestation of the draft {name} names the row {label}, whose verdict is {', '.join(found) or 'empty'}, not "
                        "APP_BUG - the verdict is corrected, or the manifestation is removed")
    for name, why in BR.merged_unconfirmed(art.root, drafts):
        problems.append(f"the draft {name} puts several manifestations under one cause the factory cannot confirm: {why} - fix the basis "
                        "(a shared `defect_location` line can be cited as a `code_line`), or split the draft and link the parts with "
                        "`possibly_same_cause`")
    # A code-reading draft (t-1676, RN1-12) has no triage row: its one checker is `bug_records.code_reading_problems` (oracle, S1 fact,
    # check state, one draft per requirement). The same reader as the gate B rehearsal, so the claim and the gate cannot disagree.
    code_reading = set(paired["code_reading"])
    for name, draft in drafts:
        if name in code_reading:
            problems += [f"the code-reading draft {name}: {detail} - fix it or withdraw it"
                         for _code, detail in BR.code_reading_problems(art.root, draft, drafts)]
    if problems:
        legacy = BR.legacy_md_drafts(art.root)
        note = (f"; {len(legacy)} *.md file(s) in the draft folder were not counted, a draft is a *.json file "
                f"({_shown([p.name for p in legacy])})" if legacy else "")
        return (False, f"{seen} - a bug at the gate needs both, paired one to one: " + "; ".join(problems) + note)
    if not drafts and not paired["app_bug_rows"]:
        return (True, "no draft and no APP_BUG triage row: nothing claims a bug")
    return (True, seen + " - every draft rests on an APP_BUG row and every APP_BUG row has its draft"
            + (f" ({len(code_reading)} code-reading draft(s) stand on their oracle and S1 fact instead)" if code_reading else ""))


def _measure_expectation_changes(art):
    """What the S5 exit check itself says about tests that went red and later passed on changed
    code: `(standing, unmeasured)`. `standing` is `[(finding, fix)]`, one per owed pair that has no
    record and no person's word; `unmeasured` is the reasons the detector could not measure, or a
    one-element list when this measurement itself failed.

    The words are `s5_precheck`'s own: it is asked for its finding (message and fix) and the
    person's word is applied by its own `passed_by_word`, so the claim, the S5 finding and the
    person's waiver can never disagree. Read-only (FR-45), and a failure here is "not measured",
    never a pass (FR-41)."""
    try:
        import s5_precheck as S5
        root = Path(art.root)
        manifest = C.load_json(C.artifact(root, "automation-manifest.json"))
        cases = S5.scope_cases(root, manifest, getattr(art, "form_dispatch", "") or None)
        changes = S5.expectation_changes(root, cases, manifest)
        findings, notes = [], []
        S5.check_expectation_changes(root, changes, cases, findings, notes)
        standing_ids = {f["id"] for f in S5.passed_by_word(root, findings, notes)}
        by_id = {f["id"]: f for f in findings}
        standing = [(by_id[p["finding_id"]], by_id[p["finding_id"]]["fix"])
                    for p in changes.get("pairs") or []
                    if p.get("finding_id") in standing_ids and p["finding_id"] in by_id]
        return standing, list(changes.get("unmeasured") or [])
    except Exception as exc:
        return [], [f"the expectation-change measurement could not run ({type(exc).__name__}: {exc})"]


def _claim_expectation_changes(art):
    """`every_expectation_change_after_red_is_recorded`: no OWED pair lacks a record.

    Three answers: `(True, ...)` when every owed pair has a record or a person's word (and when
    there is no pair at all - no run block, an empty manifest, a manifest with no
    `expectation_changes` key); `(False, ...)` naming each pair and the two doors; `(None, why)`
    - no verdict - when the detector could not measure. The detector runs ONCE per check run: the
    answer is kept on `art`.

    The two meet in one place: a pair the detector DID find, owed and with no record, makes the
    claim false whatever else it could not measure - an unmeasured corner takes no pair away - and
    the unmeasured reasons are added to the answer. `None` is for the case where nothing is owed
    and something is unmeasured, because only then does the missing measurement decide."""
    view = getattr(art, "_expectation_view", None)
    if view is None:
        view = _measure_expectation_changes(art)
        try:
            art._expectation_view = view
        except AttributeError:
            pass
    standing, unmeasured = view
    if standing:
        fixes = list(dict.fromkeys(fix for _finding, fix in standing))
        return (False, f"{len(standing)} test(s) went red and later passed on changed code, or "
                       "disappeared, and nothing records why: "
                       + "; ".join(finding["message"] for finding, _fix in standing)
                       + ". The way on, per pair of runs: " + " | ".join(fixes)
                       + ("; and the detector could not measure everything either: "
                          + "; ".join(unmeasured) if unmeasured else ""))
    if unmeasured:
        return (None, "the detector could not measure everything, so it gives no verdict: "
                + "; ".join(unmeasured))
    return (True, "no test went red and later passed on changed code without a record "
                  "or a person's word")


# The three verifiers of SC1-2 part C read the FORM being checked (`art.form_doc`, set by `_check_claims` and `_fill_claims`
# right before each call) as well as the story's files, and keep one error direction: what they cannot measure is `None`
# (a reason, never a `true`), and what the form says against what they measure is `False`.
def _claim_rollcall(art):
    """`the_verdict_was_computed_by_rollcall_not_typed`: the form's verdict and digest against the roll-call table.

    An approving `review.outcome` over a roll-call that leaves a case without a review (a `no` or a table with no
    `reviewed` column) is false whatever digest the form carries: `critic_rollcall.derive` puts the ceiling at `partial`
    for exactly that shape (TP1-15045: `approve_with_concerns` next to seven unreviewed rows of fifteen)."""
    import report_facts
    doc = getattr(art, "form_doc", None)
    if doc is None:
        return (None, "no form is being checked")
    found = _rollcall(art, doc)
    if found is None:
        return (None, f"no roll-call rows in {_rollcall_file(doc)}")
    outcome = str(doc.get("review.outcome") or "").strip()
    if outcome in report_facts.APPROVING and found["verdict_ceiling"] == "partial":
        left = found["unreviewed"] + found["unstated"]
        return (False, f"the form says {outcome}, and the roll-call leaves {_shown(left)} without a review: "
                       "the ceiling is partial")
    said = doc.get("review.rollcall")
    if handoff.is_placeholder(said):
        return (None, "review.rollcall is not filled")
    if str(said).strip() != found["digest"]:
        return (False, f"the form says {str(said).strip()}, critic_rollcall computes {found['digest']}")
    return (True, f"review.rollcall is {found['digest']}, as critic_rollcall computes it")


def _claim_sizing(art):
    """`size_computed_by_sizing_py_not_quoted`: the form's `size.computed` is what `work/sizing.json` holds (AR-13: the size
    is read through `_size`, the one reader `--fix` fills the field with)."""
    doc = getattr(art, "form_doc", None)
    if doc is None:
        return (None, "no form is being checked")
    got = _size(art, doc)
    if not got:
        return (None, "work/sizing.json holds no size")
    said = doc.get("size.computed")
    if handoff.is_placeholder(said):
        return (None, "size.computed is not filled")
    if str(said).strip() != str(got[0]).strip():
        return (False, f"the form says {str(said).strip()}, work/sizing.json says {str(got[0]).strip()}")
    return (True, f"size.computed is {str(said).strip()}, as work/sizing.json says")


def _claim_fingerprints(art):
    """`every_instance_carries_a_fingerprint_or_says_never_run`: a row that says it ran has its receipt on disk.

    Only a row that STATES its freshness is judged (a template row, `freshness` still a placeholder, says nothing - F10 (a)).
    `never_run` passes. Any other word (`fresh`, `stale`, a word outside the list) means the instance ran, and needs a
    `last_receipt` that is no placeholder, no dash, a relative path inside the story, and a file on disk."""
    doc = getattr(art, "form_doc", None)
    if doc is None:
        return (None, "no form is being checked")
    rows = doc.data.get("scope")
    rows = rows if isinstance(rows, list) else []
    stated = [(index, row) for index, row in enumerate(rows)
              if isinstance(row, dict) and not handoff.is_placeholder(row.get("freshness"))]
    if not stated:
        return (None, "no instance row states its freshness")
    bare = []
    for index, row in stated:
        if str(row.get("freshness")).strip() == "never_run":
            continue
        receipt = _story_relative(row.get("last_receipt"))
        if not receipt or not (art.root / receipt).is_file():
            ident = row.get("id")
            bare.append(f"scope[{index}]" if handoff.is_placeholder(ident) else ident)
    if bare:
        return (False, f"{len(bare)} instance(s) say they ran and carry no receipt on disk: " + _shown(bare))
    return (True, f"{len(stated)} instance row(s) state their freshness; each one that ran has its receipt on disk")


# The S3 form's grounding claims (G1-5) and fields. NO logic of their own (FR-10): each reads the function of `grounding_table` the S3 gate
# calls, so a claim and the gate cannot disagree. `grounding_table` is imported LAZILY: it imports this module at its top (AR-13).
def _grounding_plan(art):
    """`(plan_rows | None, not_planned)` for the claims that need the plan: `work/test-plan.json` (rows, or the list itself) and the
    `not_planned` entries of the form being checked beside the plan document's and the saved form's own."""
    import grounding_table as GT
    plan = art.json("work/test-plan.json")
    rows = plan.get("rows") if isinstance(plan, dict) else plan
    if not isinstance(rows, list):
        return None, []
    doc = getattr(art, "form_doc", None)
    listed = doc.data.get("not_planned") if doc is not None else None
    own = [e for e in (listed if isinstance(listed, list) else []) if isinstance(e, dict)]
    return rows, own + GT.not_planned_of(art.root, art.form_dispatch, plan if isinstance(plan, dict) else None)


def _claim_grounding_hunks(art):
    """`every_hunk_of_the_diff_has_a_grounding_row`: rule R1 of the table's check. `None` off a diff or when the table cannot be judged."""
    import grounding_table as GT
    return GT.claim_view(art.root, ("R1",))


def _claim_grounding_requirements(art):
    """`every_register_requirement_has_a_grounding_line`: rule R2 of the table's check."""
    import grounding_table as GT
    return GT.claim_view(art.root, ("R2",))


def _claim_grounding_reach(art):
    """`every_risk_and_uncovered_area_reaches_a_row_or_not_planned`: rule R7 of the S3 exit. `None` when there is no plan."""
    import grounding_table as GT
    rows, not_planned = _grounding_plan(art)
    if rows is None:
        return (None, "work/test-plan.json holds no plan rows yet")
    return GT.claim_view(art.root, ("R7",), plan_rows=rows, not_planned=not_planned)


def _claim_grounding_regression(art):
    """`every_area_that_matters_has_regression_or_a_gap`: the R8 findings about the regression command."""
    import grounding_table as GT
    return GT.claim_view(art.root, regression=True)


def _claim_grounding_share(art):
    """`refactoring_share_computed_by_code`: the table's `refactoring_share` equals, whole, what `GT.share` computes over the bytes now on
    disk. `None` when the key is absent, or the policy or the table cannot be read."""
    import grounding_table as GT
    import planning_contract as PC
    doc, problem = PC.read_grounding(art.root)
    if doc is None:
        return (None, f"the table cannot be read: {problem}")
    stored = doc.data.get("refactoring_share")
    if not isinstance(stored, dict):
        return (None, "work/grounding.yaml holds no `refactoring_share` yet")
    policy, why = PC.grounding_policy()
    if policy is None:
        return (None, f"the policy cannot be read: {why}")
    computed = GT.share(doc.data, policy, GT.check(art.root))
    if computed != stored:
        off = sorted(str(k) for k in set(computed) | set(stored) if computed.get(k) != stored.get(k))
        return (False, f"`refactoring_share` differs from grounding_table.share in {', '.join(off[:4])}: "
                       "the table's number is the code's, never typed")
    return (True, "`refactoring_share` is what grounding_table.share computes")


def _grounding_counts(field):
    """A deriver of `grounding.<field>` out of `GT.grounding_counts` - the counts are code's, the role never writes them."""
    def derive(art, doc, row=None):
        import grounding_table as GT
        found = GT.grounding_counts(art.root)
        value = (found or {}).get(field)
        return (value, "grounding_table.grounding_counts") if value not in (None, "") else None
    return derive


def _blast_lines(art, doc, row=None):
    """`blast_radius`: one line per area of the table (id, path kind, matters, regression, add_tests) - filled whole by code."""
    import grounding_table as GT
    lines = GT.blast_lines(art.root)
    return (lines, "work/grounding.yaml blast_radius") if lines else None


# The S3 form's `grounding` section and `blast_radius` list are CODE's: the role writes neither (they join the dicts above here, after the
# functions they name).
LIST_DERIVERS["blast_radius"] = _blast_lines
DERIVERS.update({f"grounding.{name}": _grounding_counts(name)
                 for name in ("hunks", "rows_cover", "requirements_cover", "refactoring_percent", "road")})


CLAIMS = {
    "every_hunk_of_the_diff_has_a_grounding_row": _claim_grounding_hunks,
    "every_register_requirement_has_a_grounding_line": _claim_grounding_requirements,
    "every_risk_and_uncovered_area_reaches_a_row_or_not_planned": _claim_grounding_reach,
    "every_area_that_matters_has_regression_or_a_gap": _claim_grounding_regression,
    "refactoring_share_computed_by_code": _claim_grounding_share,
    "every_instance_names_its_current_case_version": _claim_instance_versions,
    "traceability_table_exists_on_disk": _claim_traceability,
    "implementation_source_recorded_in_pipeline": _claim_impl_recorded,
    "size_recorded_in_pipeline": _claim_size_recorded,
    "no_bug_reaches_the_gate_without_a_draft_and_a_triage_row": _claim_bug_has_a_draft,
    "every_expectation_change_after_red_is_recorded": _claim_expectation_changes,
    "size_computed_by_sizing_py_not_quoted": _claim_sizing,
    "the_verdict_was_computed_by_rollcall_not_typed": _claim_rollcall,
    "every_instance_carries_a_fingerprint_or_says_never_run": _claim_fingerprints,
}


# ------------------------------------------------------------------------------ the check
class Problem:
    __slots__ = ("path", "text", "fix", "limit", "kind", "also")

    def __init__(self, path, text, fix="", limit=None, kind="", also=()):
        # `limit` is set ONLY on a length problem: the structured fact the driver (and `--shorten`)
        # read instead of the phrase (FR-12).
        # `kind` is `"blank"` ONLY on the problem "not filled": the structural fact `values_report` reads to tell a
        # field the role must supply from one `--fix` fills (SC1-2, FR-12 - never the phrase). `also` holds the paths of
        # the OTHER door of this problem (`blocked.problem` for a blocked row): the refusal's skeleton writes a line for
        # each, so a problem whose door is another path still shows the role where to write.
        self.path, self.text, self.fix, self.limit = path, text, fix, limit
        self.kind, self.also = kind, tuple(also)

    def line(self) -> str:
        # One refusal block carries ONE command (`refusal_text`); a command per field was the 89-process failure
        # (RC1-11). `fix` stays on the object for `--json`.
        return f"{self.path}: {self.text}"


def _row_of(doc, path):
    """The filled row a `section[3].field` path belongs to, as a plain dict."""
    section, _, rest = path.partition("[")
    index = rest.split("]")[0]
    rows = doc.data.get(section)
    if isinstance(rows, list) and index.isdigit() and int(index) < len(rows):
        row = rows[int(index)]
        return row if isinstance(row, dict) else {}
    return {}


def _row_template(doc, section: str) -> tuple:
    """`(start, end, lines)` of the first row of a list section, as the document holds it; None when it has
    no first row (the section is absent, or written `[]`)."""
    rows = [p for p in doc.nodes if p.startswith(f"{section}[0]")]
    if not rows:
        return None
    start = min(doc.nodes[p].line for p in rows)
    end = max(doc.nodes[p].end_line for p in rows)
    return start, end, doc.lines[start:end + 1]


def _rows_block(template: list, key: str, values: list, also=None) -> list:
    """The lines of one row per value, from the lines of the template's first row.

    `also`, when given, is `{value: {field: word}}`: fields code ALSO knows for that row (S7's
    `not_for_repair` rows carry the triage verdict). The value is written in the file's own spelling
    (`handoff._render`) then; without `also` it is written as it always was."""
    head = template[0]
    indent = head[:len(head) - len(head.lstrip())]
    block = []
    for value in values:
        block.append(f"{indent}- {key}: {handoff._render(value) if also is not None else value}")
        known = (also or {}).get(value) or {}
        for line in template[1:]:
            if not line.strip():
                continue
            field = handoff.KEY_LINE.match(line)
            name = handoff._unquote(field.group(3)) if field else ""
            if name in known:
                line = line[:len(line) - len(line.lstrip())] + f"{name}: {handoff._render(known[name])}"
            block.append(line)
    return block


def _open_rows(doc, section: str, key: str, values: list, also=None) -> bool:
    """One row per value, with the template's other fields left for the role to fill."""
    found = _row_template(doc, section)
    if not found or f"{section}[0].{key}" not in doc.nodes:
        return False
    start, end, template = found
    doc.lines = doc.lines[:start] + _rows_block(template, key, values, also) + doc.lines[end + 1:]
    return True


def _open_rows_from_contract(doc, contract: str, section: str, key: str, values: list, also=None) -> bool:
    """The same rows when the form holds no first row to copy - the role wrote the section `[]`, or left it
    out: the template row comes from the CONTRACT, and the section's own line is replaced (or appended)."""
    found = _row_template(handoff.template(contract), section)
    if not found:
        return False
    block = _rows_block(found[2], key, values, also)
    at = next((i for i, line in enumerate(doc.lines)
               if re.match(r"^" + re.escape(section) + r":\s*(\[\s*\])?\s*(#.*)?$", line)), None)
    if at is None:
        doc.lines = doc.lines + ["", f"{section}:"] + block
    else:
        doc.lines = doc.lines[:at] + [f"{section}:"] + block + doc.lines[at + 1:]
    return True


def _is_empty_section(doc, spec, section: str) -> bool:
    """A list whose every row is still the contract's example: the role filled nothing."""
    rows = doc.data.get(section)
    if not isinstance(rows, list) or not rows:
        return True
    for row in rows:
        values = row.values() if isinstance(row, dict) else [row]
        if any(not handoff.is_placeholder(v) for v in values):
            return False
    return True


# ----------------------------------------------------------------- the null outcome (FR-23)
# How many ids one refusal line names before it says "and N more": a triage of two hundred rows must not
# become a refusal of two hundred ids (the whole list is `work/triage.json` itself).
NULL_IDS_SHOWN = 6

def _shown(ids: list) -> str:
    ids = [str(i) for i in ids]
    more = len(ids) - NULL_IDS_SHOWN
    return ", ".join(ids[:NULL_IDS_SHOWN]) + (f" and {more} more" if more > 0 else "")


def _triage_view(art) -> tuple:
    """`(rows, "")` when `work/triage.json` reads as a triage, else `(None, why)`.

    Every shape that is not a triage is a reason, never a guess: a missing file, bytes that are not JSON,
    a document that is not an object, a `triage` that is not a list, an entry that is not a row. The
    caller turns each into a refusal that names it - an empty scope is never accepted over a triage nobody
    could read."""
    path = art.root / "work" / "triage.json"
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None, "work/triage.json is missing or cannot be read"
    try:
        data = json.loads(raw)
    except ValueError:
        return None, "work/triage.json is not valid JSON"
    if not isinstance(data, dict):
        return None, "work/triage.json is not an object with a `triage` list"
    rows = data.get("triage")
    if not isinstance(rows, list):
        return None, "work/triage.json has no `triage` list"
    if any(not isinstance(row, dict) for row in rows):
        return None, "the `triage` list of work/triage.json holds an entry that is not a row"
    return rows, ""


REPORT_UNREADABLE = "the run report work/run-report.json cannot be read"
REPORT_NO_LIST = "the run report work/run-report.json shows no results list"
# The refusal says what it cannot tell; the door (`fix`) alone says what to do - t-323 F2-cosmetic: the `blocked`
# sentence used to stand in both, so the role read it twice
REPORT_TELL = "this check cannot tell which failures exist"
REPORT_DOOR = ("say so under `blocked` in the form, so the conductor can restore work/run-report.json (the S6 reduce "
               "rebuilds it), then run this check again")


def _report_unreadable(art) -> str:
    """"" when `work/run-report.json` reads as a run report with a results list, else why it does not (t-323 B4/F2).
    ONE reading and ONE text for both branches of the null outcome, zero rows or rows present: neither can tell which
    failures exist from a report it cannot read (FR-41: never "so a failure has no verdict"), and "every branch that
    cannot tell ends in a refusal". The door is `REPORT_DOOR` - the zero-row door "triage every failure" is unusable
    for a report that cannot be read (FR-2)."""
    report = art.json("work/run-report.json")
    if not isinstance(report, dict):
        return REPORT_UNREADABLE
    if not isinstance(report.get("current_results"), list) and not isinstance(report.get("results"), list):
        return REPORT_NO_LIST
    return ""


def _binding_texts(ambiguous: list, multiple: list) -> list:
    """The sentences for the rows that cannot be a verdict: ambiguous (a row names several failures) and multiple
    (several rows for one failure) - ONE wording for both S7 paths (t-323 F1)."""
    said = []
    if ambiguous:
        said.append("; ".join(f"the row {' / '.join(row_names)} names {len(failure_names)} failures "
                              f"({_shown(failure_names)}) and is a verdict for none of them"
                              for row_names, failure_names in ambiguous[:NULL_IDS_SHOWN])
                    + (f"; and {len(ambiguous) - NULL_IDS_SHOWN} more such row(s)" if len(ambiguous) > NULL_IDS_SHOWN else ""))
    if multiple:
        said.append("; ".join(f"{count} rows answer the failure {name}; keep one" for name, count in multiple[:NULL_IDS_SHOWN])
                    + (f"; and {len(multiple) - NULL_IDS_SHOWN} more such failure(s)" if len(multiple) > NULL_IDS_SHOWN else ""))
    return said


def _binding_problems(art, rows, section: str) -> list:
    """The ambiguity / multiple refusal alone, for a form whose `section` is NOT empty (t-323 F1: it runs on both S7
    paths; a kept ambiguous TEST_BUG row with a non-empty repair list used to reach `s7_repairs`). Nothing is said
    when the triage or the report cannot be read: the other checks name that."""
    if not rows or _report_unreadable(art):
        return []
    _names, _unnamed, ambiguous, multiple = _untriaged_failures(art, rows)
    said = _binding_texts(ambiguous, multiple)
    if not said:
        return []
    return [Problem(section, f"work/triage.json holds rows that cannot be a verdict: {'; '.join(said)}.",
                    "triage every failure in work/triage.json with ONE row under that failure's own instance_id, then "
                    "run this check again")]


def _untriaged_failures(art, rows: list) -> tuple:
    """`(names, unnamed, ambiguous, multiple)` - the failures of `work/run-report.json` that no row of `rows` answers,
    the failures that carry no name at all, the rows that answer several failures and so none of them
    (`[(row names, [failure names])]`), and the failures that SEVERAL rows answer (`[(failure name, n rows)]`, t-323 F1:
    a failure with two rows is refused, never accepted as answered). The WITH-ROWS half of S1 (t-319, critic t-312 F2): "an empty scope is never
    accepted while a failure has no verdict" is checked on the zero-row branch by `_no_failure_shown`; with one row
    or more it was not checked, so a triage of the ENV rows alone passed while an APP_BUG failure had no row at all.
    Failures and rows meet through `contract.bind_triage` (t-323 A1) - the binding gate B, the reducer, the ledger,
    the traceability table and the dashboard read too: `x[json]` is no verdict of `x[multi]`, a row `x` over both is
    ambiguous (it answers neither, and is named), and a `case` row answers a manual check only. An observation of a manual
    check (`<case>#obs<n>`, P26) is a failure of the kind `observation` here as well - an unanswered one is named in `names`
    in this branch, as the zero-row branch names it through `_no_failure_shown`. A report that cannot
    be read answers ([], [], [], []): the caller refuses it first (`_report_unreadable`)."""
    report = art.json("work/run-report.json")
    if not isinstance(report, dict):
        return [], [], [], []
    failures, unnamed = C.triage_failures(report)
    bound = C.bind_triage(failures, rows)
    competing = {key for _names, keys in bound["ambiguous"] for key in keys}
    names = [key[1] for key, answers in bound["matched"].items() if not answers and key not in competing]
    ambiguous = [(row_names, sorted(key[1] for key in keys)) for row_names, keys in bound["ambiguous"]]
    multiple = [(key[1], len(found)) for key, found in bound["multiple"].items()]
    return sorted(dict.fromkeys(names)), unnamed, ambiguous, multiple


def _no_failure_shown(art) -> str:
    """"" when `work/run-report.json` SHOWS no failure, else why it does not.

    The zero-row branch: a triage with no row is "nothing failed" only if the run says so. Read the way
    `story_run.failures_to_triage` reads it (`current_totals`, else `totals`), plus the `error` total, and the
    failing rows through `contract.triage_targets` - the one definition the driver and the reducer use (t-309) -
    so this check never calls a failure the driver would triage a non-failure. Unreadable, or a shape that
    shows nothing, is a reason."""
    report = art.json("work/run-report.json")
    if not isinstance(report, dict):
        return REPORT_UNREADABLE
    totals = report.get("current_totals") or report.get("totals")
    if not isinstance(totals, dict):
        return "work/run-report.json shows no totals"
    for word in ("failed", "error"):
        try:
            count = int(totals.get(word) or 0)
        except (TypeError, ValueError):
            return f"work/run-report.json totals carry `{word}` = {totals.get(word)!r}, which is not a count"
        if count:
            return f"work/run-report.json shows {count} result(s) `{word}`"
    checks = report.get("current_manual_checks") or report.get("manual_checks") or []
    if not isinstance(checks, list):
        return "work/run-report.json `manual_checks` is not a list"
    targets = C.triage_targets(report)
    bad = sorted(targets["manual"]) + sorted(targets["unnamed_manual"])
    if bad:
        return "work/run-report.json shows manual check(s) that failed or were inconclusive: " + _shown(bad)
    nameless = sorted(targets["unnamed"] - targets["unnamed_manual"])     # t-319 F4: a failed row with no name is a failure
    if targets["results"] or nameless:
        return ("work/run-report.json shows failed result row(s): " + _shown(sorted(targets["results"]) + nameless))
    if targets["observations"]:       # P26: a runner's doubt, whatever its check's result, is a target that wants a row
        return ("work/run-report.json shows observation(s) of a manual check that want a verdict: "
                + _shown(sorted(targets["observations"])))
    return ""


def _listed_ids(doc, section: str) -> list:
    """The ids the role wrote under `section` (a placeholder is not an id)."""
    rows = doc.data.get(section)
    out = []
    for row in rows if isinstance(rows, list) else []:
        value = row.get("id") if isinstance(row, dict) else row
        text = str(value if value is not None else "").strip()
        if text and not handoff.is_placeholder(text):
            out.append(text)
    return out


def _or_list(words: list) -> str:
    """"A", "A or B", "A, B or C" - the verdict list of a refusal, read out of the declaration's own params."""
    words = [str(w) for w in words]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + f" or {words[-1]}"


def _null_outcome_view(doc, section: str, entry: dict, contract: str, art) -> tuple:
    """`(problems, openable)` for the condition `triage_has_no_repair` (t-305 N0: the registry's `impl`).

    `entry` is the contract's own declaration for `section` (`handoff.null_outcomes`): its `params` carry the
    verdicts that make the section non-empty (`repair_verdicts`) and the list that must then hold the triage
    (`listed_in`); both are data (FR-13), and a param that is missing is not defaulted here - `check` applies
    only a declaration that `null_outcomes.entry_problems` finds well formed.

    Called for a form whose `section` is empty (the null outcome itself) and for one whose `section` is not (then
    only the binding of triage rows to failures, t-323 F1, is said).

    `problems` is [] exactly when the empty list is accepted. INVARIANT (S1): an empty list is never accepted
    while a repair verdict exists, nor while a failure has no verdict. Every branch below that cannot tell
    ends in a refusal: the allowed error is refusing a legitimate empty case, which costs the role one row or
    the person one word (`finish --ignore-handoff`); the forbidden one is accepting a repair left undone.
    `openable` is `[(id, verdict)]` for the rows `--fix` may open under `listed_in` (all of them, and only
    when the triage itself is clean), else []."""
    if not _is_empty_section(doc, None, section):
        return _binding_problems(art, _triage_view(art)[0], section), []
    params = entry["params"]
    verdicts = [str(v) for v in params["repair_verdicts"]]
    listed_in = str(params["listed_in"])
    repair = {v.split(":")[0].strip().upper() for v in verdicts}
    rows, why = _triage_view(art)
    got = _listed_ids(doc, listed_in)
    header = (f"`{section}` is empty, and an empty `{section}` is accepted only when work/triage.json shows nothing "
              "to repair")
    if rows is None:
        return [Problem(section, f"{header} - and {why}. The triage is written before this form: the failure "
                                 f"analyst writes work/triage.json (one row per failure, with its verdict).",
                        "write work/triage.json, then run: handoff_check.py --file <form> --fix")], []
    problems, known = [], []
    field = handoff.spec(contract).get(f"{listed_in}[].verdict")
    allowed = list(field.options) if field else []
    repairs, unknown, nameless, covered, reordered = [], [], [], set(), False
    for row in rows:
        ids = C.row_names(row)
        verdict = str(row.get("verdict") or "").strip()
        label = ids[0] if ids else "a row with no instance"
        if not ids:
            nameless.append(verdict or "no verdict")
        if verdict.split(":")[0].strip().upper() in repair:
            repairs.append(f"{label} ({verdict})")
        elif row.get("reorder") not in (None, False):
            # a row that asks for the `reorder` round IS a repair whatever its verdict (AR-23, t-1508 R7): the empty scope is
            # never accepted over it; any value but absent/false counts, so a malformed request is refused, not skipped
            repairs.append(f"{label} ({verdict or 'no verdict'}, reorder)")
            reordered = True
        elif verdict not in allowed:
            unknown.append(f"{label} ({verdict or 'no verdict'})")
        elif ids:
            known.append((ids[0], verdict))
        covered.update(ids)
    if repairs:
        problems.append(Problem(
            section, f"{header} - and it holds {len(repairs)} repair verdict(s): {_shown(repairs)}. A repair "
                     f"belongs in `{section}`, one row per instance (id, state, reason, case, round); \"nothing "
                     f"to repair\" means no {_or_list(verdicts)} row at all"
                     # the clause is about a FLAKY row, so it is said only while FLAKY is a repair verdict here
                     + (", a FLAKY row already fixed included" if "FLAKY" in verdicts else "")
                     # a row that asks for the `reorder` round is a repair too (FR-1: the refusal must not say otherwise)
                     + (", and no row that asks for a `reorder`." if reordered else "."),
            f"fill the `{section}` rows in the form, then run this check again"))
    if unknown:
        problems.append(Problem(
            section, f"{header} - and a triage row has no verdict this check knows: {_shown(unknown)}. Every "
                     f"failure carries one of {', '.join(verdicts + allowed)}.",
            "correct the verdict in work/triage.json, then run this check again"))
    if nameless:
        problems.append(Problem(
            section, f"{header} - and {len(nameless)} triage row(s) name no instance (`instance_id`, `test` or, "
                     "for a manual check, `case`), so nobody can tell which failure they answer.",
            "give each triage row its instance_id (or case), then run this check again"))
    # t-323 B4/F2: a run report that cannot be read, or shows no results list, is ONE refusal with ONE text and ONE
    # door - zero rows or rows present alike. This check cannot tell which failures exist, so it never says "a failure
    # has no verdict", and the zero-row door "triage every failure" (unusable for such a report) is not offered.
    cannot_tell = _report_unreadable(art)
    if cannot_tell:
        problems.append(Problem(section, f"{header} - {cannot_tell} - {REPORT_TELL}.", REPORT_DOOR))
    unshown = "" if (rows or cannot_tell) else _no_failure_shown(art)
    if unshown:
        problems.append(Problem(
            section, f"{header} - work/triage.json holds no row, and {unshown}, so a failure has no verdict.",
            "triage every failure in work/triage.json, then run this check again"))
    untriaged, unnamed, ambiguous, multiple = (_untriaged_failures(art, rows) if rows and not cannot_tell
                                               else ([], [], [], []))
    if untriaged or unnamed or ambiguous or multiple:
        said = []
        if untriaged:
            said.append(f"{len(untriaged)} failure(s) of work/run-report.json have no row in it: {_shown(untriaged)}")
        if unnamed:
            said.append(f"{len(unnamed)} failure(s) carry no name a row could answer to: {_shown(unnamed)}")
        said += _binding_texts(ambiguous, multiple)
        problems.append(Problem(
            section, f"{header} - and {'; '.join(said)}, so a failure has no verdict.",
            "triage every failure in work/triage.json, one row per failure under that failure's own instance_id "
            "(the analyst writes that file; a failure answers to the instance_id or test the run report names it by, "
            "a manual check to its case), then run this check again"))
    clean = not (repairs or unknown or nameless or unshown or cannot_tell or untriaged or unnamed or ambiguous
                 or multiple)
    missing = [ids for ids in ([C.row_names(row) for row in rows])
               if ids and not any(C.same_id(i, g) for i in ids for g in got)]
    if missing and clean:
        door = ("handoff_check.py --file <form> --fix opens a row for each (id, verdict); you write "
                "`where_it_went`") if not got else (f"add a row to `{listed_in}` for each: id, verdict, "
                                                    "where_it_went")
        problems.append(Problem(
            listed_in, f"{len(missing)} triage row(s) are not listed here: {_shown([ids[0] for ids in missing])}. "
                       f"With an empty `{section}` this list is the whole triage, so the automator can see its "
                       "window is complete.", door))
    extra = [i for i in got if not any(C.same_id(i, c) for c in covered)]
    if extra:
        problems.append(Problem(
            listed_in, f"{_shown(extra)} {'is' if len(extra) == 1 else 'are'} listed here, and no row of "
                       "work/triage.json is named so (a row is named by its instance_id, its test or, for a manual "
                       "check, its case): that names a failure nobody triaged, and a failure with no triage row "
                       "has no verdict.",
            "triage it in work/triage.json (the analyst writes that file), or write the id the triage row "
            "carries"))
    openable = []
    if clean and rows and not got:
        seen = set()
        for ident, verdict in known:
            if ident not in seen:
                seen.add(ident)
                openable.append((ident, verdict))
    return problems, openable


def _null_outcome_impl(entry: dict):
    """The function the REGISTRY names for this declaration's condition (`null_outcomes.CONDITIONS[..].impl`),
    resolved in this module: one source for "what implements the condition". The registry is code, and the detector
    (`null_outcomes.audit`) is red on an impl that does not resolve, so this raises on one rather than guess."""
    impl = NO.CONDITIONS[entry["condition"]].impl or ""
    name = impl.partition("::")[2] if impl.startswith("handoff_check.py::") else ""
    return globals()[name]


def _declared_null_outcomes(contract: str, spec: dict) -> dict:
    """`{section: entry}` the check APPLIES: the contract's declarations (`handoff.null_outcomes`) whose condition
    is live and which `null_outcomes.entry_problems` finds well formed. Anything else is not applied and the
    contract behaves as if it declared nothing - the old refusal stands (fail closed: a typo in a param, a
    reserved condition, a missing `listed_in` never accepts an empty list; the detector says what is wrong)."""
    declared = handoff.null_outcomes(contract)
    if not declared:
        return {}
    sections, stages = handoff.sections(contract), NO.stage_ids()
    return {section: entry for section, entry in declared.items()
            if not NO.entry_problems(section, entry, spec=spec, sections=sections, stage_ids=stages)}


def filled_share(doc, contract: str) -> tuple:
    """(filled, total) over the fields the ROLE owns and the template left blank.

    A value the contract itself writes (`artifacts.manifest: work/automation-manifest.json`)
    is not the role's answer, so it is not counted: an untouched form must read as untouched,
    or `story_step finish` would refuse a stage for a form nobody was asked to use yet.
    """
    tmpl = handoff.template(contract)
    blanks = {re.sub(r"\[\d+\]", "[]", path) for path, node in tmpl.nodes.items()
              if handoff.is_placeholder(node.value)}
    by_code = {str(row.get("field")) for row in (doc.data.get("derived") or [])
               if isinstance(row, dict)}
    filled = total = 0
    for path, node in doc.nodes.items():
        generic = re.sub(r"\[\d+\]", "[]", path)
        if generic not in blanks or handoff.owned_by_contract(path) or path.startswith("header."):
            continue
        if path in by_code:
            continue
        total += 1
        if not handoff.is_placeholder(node.value):
            filled += 1
    return filled, total


def _investigation_dispatch(art) -> bool:
    """Is the form's dispatch an S7 INVESTIGATION dispatch (`controller.s7_part_of`, the one reader of the kind)? The id is the
    form's file stem (`art.form_dispatch`: the S7 header carries no dispatch field); the record is read through
    `s5_precheck.dispatch_record`. A record that cannot be read answers False: the FULL check runs (refuse-prone, AR-28)."""
    try:
        import controller as CT
        from s5_precheck import dispatch_record
        return CT.s7_part_of(dispatch_record(art.root, art.form_dispatch) or {}) == "investigation"
    except Exception:
        return False


def _investigation_view(doc, section: str, entry: dict, contract: str, art) -> tuple:
    """`(problems, [])` for an investigation hand-back: it hands nothing for repair and relists no triage row, so BOTH `scope`
    and `not_for_repair` must be empty (`_is_empty_section`: an empty list or the template's placeholder row) and each a list or
    absent. Nothing is ever openable: `--fix` opens no row. Whatever `work/triage.json` holds is not judged here."""
    problems = []
    for name in ("scope", "not_for_repair"):
        value = doc.data.get(name)
        if value is not None and not isinstance(value, list):
            problems.append(Problem(name, f"`{name}` must be a list; an investigation hands back `scope: []`",
                                    f"write `{name}: []`"))
        elif not _is_empty_section(doc, None, name):
            problems.append(Problem(name, "an investigation hands nothing for repair and relists no triage row: "
                                          f"`{name}` is not empty; the triage is not yours to change",
                                    f"empty `{name}` (write `{name}: []`)"))
    return problems, []


def check(doc, contract: str, art: Artifacts, *, fix=False, task="", use_judge=True) -> tuple:
    spec = handoff.spec(contract)
    nulled = _declared_null_outcomes(contract, spec)    # {} for every contract that names no null outcome (S3)
    investigating = _investigation_dispatch(art) if nulled else False
    role = str(doc.get("header.role") or doc.get("from_role") or "")
    vocab = handoff.vocabulary()
    # sections the form owes only under a header value (`required_when:`), not owed under the value this form holds
    relaxed = handoff.relaxed_sections(contract, doc.get("header.verdict"))
    fixed, problems, judged, derived = [], [], [], []
    if fix:
        for section, deriver in LIST_DERIVERS.items():
            if _is_empty_section(doc, spec, section.split(".")[0]) or True:
                got = deriver(art, doc)
                if got and got[0] and handoff.is_placeholder(doc.get(f"{section}[0]")):
                    if handoff.set_list(doc, section, got[0]):
                        fixed.append(f"{section} = {len(got[0])} path(s) (from {got[1]})")
                        derived.append({"field": f"{section}[]", "source": got[1]})
                        doc = handoff.parse(doc.text())
        for section, entry in nulled.items():
            if not (NO.CONDITIONS[entry["condition"]].opens_rows and _is_empty_section(doc, spec, section)):
                continue
            # The null outcome (FR-23): code opens what the triage already says - one `not_for_repair` row per
            # triage row, with its verdict - and only when the triage is clean, so a repair the role forgot is
            # never papered over by rows that look like a finished handover.
            listed = str(entry["params"]["listed_in"])
            _problems, openable = (_investigation_view if investigating else _null_outcome_impl(entry))(doc, section, entry, contract, art)
            if openable and _is_empty_section(doc, spec, listed):
                ids = [ident for ident, _verdict in openable]
                also = {ident: {"verdict": verdict} for ident, verdict in openable}
                if (_open_rows(doc, listed, "id", ids, also)
                        or _open_rows_from_contract(doc, contract, listed, "id", ids, also)):
                    fixed.append(f"{listed} = {len(ids)} row(s) opened (from {NO.CONDITIONS[entry['condition']].source})")
                    for index in range(len(ids)):
                        for name in ("id", "verdict"):
                            derived.append({"field": f"{listed}[{index}].{name}",
                                            "source": NO.CONDITIONS[entry["condition"]].source})
                    doc = handoff.parse(doc.text())
    empty_sections = set()
    for section, kind in handoff.sections(contract).items():
        if kind != "list" or handoff.owned_by_contract(section):
            continue
        if _is_empty_section(doc, spec, section):
            empty_sections.add(section)
            if section in handoff.REQUIRED_LISTS:
                if section in nulled:
                    # an empty list is this contract's own legitimate answer, on the conditions the block names
                    problems += (_investigation_view if investigating else _null_outcome_impl(nulled[section]))(doc, section, nulled[section], contract, art)[0]
                    continue
                problems.append(Problem(
                    section, "no rows. One row per item in scope: the id, a state and a reason "
                             f"of at most 80 characters. {_row_sentence(row_form(spec, section)[1])}",
                    "write the rows as index lines in the values file, then run this check again"))
    # F4 (AR-10, AR-28, AR-29): a verdict that sends the window back owes the sections the contract's `rows_owed_when`
    # lists; an empty one (nothing, or only the template row) is a presence gap returned to the role. Only the
    # presence of a row is read, never what it says; `tooling_findings` rows are another list and do not satisfy it.
    verdict_word = str(doc.get("header.verdict") or "").strip()
    for section in sorted(handoff.rows_owed(contract, verdict_word)):
        rows = doc.data.get(section)
        if not (_is_empty_section(doc, spec, section) or (isinstance(rows, list) and all(handoff.only_template(r) for r in rows))):
            continue
        keys = row_form(spec, section)[1]               # this contract's own row paths: S2-S4 rows are not S5 rows
        cause = f"; cause is one of {', '.join(handoff.allowed('repair_causes'))}" if any(k.endswith(".cause") for k in keys) else ""
        problems.append(Problem(
            section, f"no rows. The verdict {verdict_word} sends the window back, so each thing the author must change "
                     f"is a row: {_row_sentence(keys)}{cause}",
            f"write the rows as index lines in the values file ({', '.join(keys)}), then run this check again"))
    for section, entry in nulled.items():
        if _is_empty_section(doc, spec, section):
            continue
        # t-323 F1: a row that names several failures, or several rows for one failure, is refused on THIS path too -
        # the empty-section path says it in the condition's view; here a kept ambiguous TEST_BUG row beside a
        # non-empty repair list used to reach `s7_repairs` (the view says only that, for a non-empty section)
        problems += (_investigation_view if investigating else _null_outcome_impl(entry))(doc, section, entry, contract, art)[0]
    for section, entry in nulled.items():
        if _is_empty_section(doc, spec, section):
            continue
        # A word that SAYS the null (`none` in `header.window`) beside a section that lists rows says the opposite:
        # the automator would read the header and skip its window. The words, and what each one means, are the
        # declaration's own data (Q-N0-2); no S7 prose lives here.
        for path, said in entry.get("words", {}).items():
            if str(doc.get(path) or "").strip().lower() != said["word"].lower():
                continue
            rows_in_scope = len(doc.data.get(section) or [])
            problems.append(Problem(
                path, f"`{said['word']}` says {said['means']}, and `{section}` lists {rows_in_scope} row(s). "
                      f"`{said['word']}` belongs only to the empty `{section}` of the null outcome.",
                f'--set {path}="{handoff.template(contract).get(path) or "<the value of the field>"}"'))
    for path, node in list(doc.nodes.items()):
        if handoff.owned_by_contract(path) or path.split("[")[0].split(".")[0] in empty_sections:
            continue
        generic = re.sub(r"\[\d+\]", "[]", path)
        field = spec.get(generic)
        if not field:
            continue                                  # a value the role added: never refused
        value = doc.get(path)
        blank = handoff.is_placeholder(value)
        if blank and fix and path.startswith("claims.") and path[len("claims."):] in CLAIMS:
            continue            # a claim with a verifier is filled (or left open with a reason) by `_fill_claims`, after this loop
        if blank and fix:
            # A fact keeps its name wherever it sits: `case_version` in `scope[]` and in
            # `cases[]` is the same pin, read from the same links file. Registering it per full
            # path meant the designer typed "pending case_versions.py --all (no Bash available to
            # this role)" into a field code could fill from `story-case-links.json` — the role
            # could not even run the script its own field names (TP1-13797, 26.09).
            deriver = DERIVERS.get(generic) or BY_LEAF.get(generic.rsplit(".", 1)[-1])
            got = deriver(art, doc, _row_of(doc, path)) if deriver else None
            if got and got[0] not in (None, "", []):
                handoff.set_value(doc, path, got[0])
                fixed.append(f"{path} = {got[0]} (from {got[1]})")
                derived.append({"field": path, "source": got[1]})
                doc = handoff.parse(doc.text())
                value, blank = doc.get(path), False
        if blank and fix and use_judge:
            asked = _ask_judge_row(generic, path, doc, task)
            if asked:
                handoff.set_value(doc, path, asked["value"])
                judged.append({"field": path, "value": asked["value"],
                               "as_written": asked["as_written"],
                               "confidence": asked.get("confidence"),
                               "judgment": asked["judgment"]})
                fixed.append(f"{path} = {asked['value']} (judge read the row)")
                doc = handoff.parse(doc.text())
                value, blank = doc.get(path), False
        if blank:
            if field.optional or path.startswith("blocked.") or path.split("[")[0].split(".")[0] in relaxed:
                continue
            options = handoff.options_for_role(field, role, vocab) if path.endswith(".state") else field.options
            problems.append(Problem(path, f"not filled. {field.hint}"
                                    + (f" One of: {', '.join(options)}" if options else ""), kind="blank"))
            continue
        # `true` read back from the file is a Python bool: compare in the form's own spelling
        text = "true" if value is True else "false" if value is False else str(value)
        options = handoff.options_for_role(field, role, vocab) if path.endswith(".state") else field.options
        if options and text not in options and text not in field.options:
            # The list of a stage S1-S4 handoff is a PROPOSED one (F-3 (b)): `new: <word> -- <why>` passes the form and is
            # kept in `proposed[]` for the stage critic to judge. The judge only ADVISES: the field keeps the role's word.
            opened = _list_is_open(contract, generic)
            door = C.open_word_errors(text, options, "handoff_field") if opened and text.startswith("new:") else None
            if door == []:
                if fix:
                    word, _sep, why = text[len("new:"):].partition(" -- ")
                    judged.append({"kind": "proposed", "field": path, "word": word.strip(), "why": why.strip()})
                continue
            nearest = (_ask_judge(field, path, text, contract, doc, task, options)
                       if (fix and use_judge and door is None) else None)
            advice = ""
            if nearest:
                judged.append({"kind": "suggested", "field": path, "as_written": text, "nearest": nearest["value"],
                               "confidence": nearest.get("confidence"),
                               "judgment": nearest.get("judgment", "form_row_state")})
                advice = (f" The judge reads it nearest to `{nearest['value']}` (advice: the word you wrote stays yours, "
                          "and is not changed).")
            # A word outside the list is the role's own repair, and the refusal says so in
            # the one sentence the driver routes on (P6). TP1-13797, 26.09: `unresolved[0]
            # .reason: contradiction` — one word away from `contradicts_requirement` — reached the
            # conductor and then the person, because the known-refusal table was written from the
            # wordings it had already met and this was not one of them.
            if door:
                problems.append(Problem(path, "; ".join(door) + f".{advice} {REPAIR_MARKER}."))
                continue
            problems.append(Problem(
                path, f"`{text[:60]}` is not a value of this field. Write one of: "
                      + ", ".join(options)
                      + (", or a word the list lacks as `new: <word> -- <why>` (the stage critic judges it)" if opened else "")
                      + f".{advice} {REPAIR_MARKER}."))
            continue
        if field.max_len and len(text) > field.max_len:
            # Counting characters is nobody's judgement: the same marker as the closed list, so a
            # driver routes it to the role instead of spending a conductor session on it.
            problems.append(Problem(path, f"{len(text)} characters, at most {field.max_len}. "
                                          "The explanation belongs in the artifact, not in the "
                                          f"form. {REPAIR_MARKER}.", limit=field.max_len))
    if fix:
        # P3: every deriver of the loop has written by now, so a verifier sees the form as `--fix` leaves it, whatever
        # order the sections are in.
        doc, claim_fixed, claim_derived, claim_problems = _fill_claims(doc, art, spec)
        fixed += claim_fixed
        derived += claim_derived
        problems += claim_problems
    problems += _blocked_row_problems(doc, spec, role, vocab)
    problems += tried_errors(doc, contract)
    problems += _check_claims(doc, art)
    finding_problems, finding_judged = check_findings(doc, contract, task, fix and use_judge)
    problems += finding_problems
    judged += finding_judged
    return doc, fixed, problems, judged, derived


ROW_STATE_PATH = re.compile(r"\w+\[\d+\]\.state")

# The handoffs of the stages whose roles keep a `tried` table (spec t-1765 B3, X7-7): what the role tried and saw, one row per
# attempt. S1-S4 and six S5-S9 forms; not `s5-automator-plan-to-critic`, `s5-automator-to-runner`, `s7-analyst-to-automator`,
# `s7-automator-to-analyst`. No `required_when` or verdict relaxes it. Their stage critic reads the table against the role's Good outcome; this module only sees that a table is there.
TRIED_CONTRACTS = ("s1-scout-to-tester", "s2-tester-to-strategist", "s3-strategist-to-designer",
                   "s4-designer-to-case-critic", "s5-automator-to-critic", "s6-runner-to-analyst",
                   "s7-analyst-to-scribe", "s8-scribe-to-gate-b", "s8-bug-reporter-to-scribe", "s9-retro-to-project")
# The stage contracts whose closed lists are PROPOSED ones (spec t-1765 X2-3 / F-3 (b), X7-5): a word the list lacks goes in
# as `new: <word> -- <why>`. An EXPLICIT tuple, not an alias of TRIED_CONTRACTS: the two answer different questions (where a
# `tried` table is owed / where a list may be extended) and a change to one must not move the other (AR-20). The first four
# are open on every list field; the last three (S5, S8, S9) are open ONLY on the fields of OPEN_LIST_FIELDS - every other
# list field of an S5-S9 form is a ROUTE (code branches on its word, E-16) and stays closed, `new:` refused (FR-19).
OPEN_LIST_CONTRACTS = ("s1-scout-to-tester", "s2-tester-to-strategist", "s3-strategist-to-designer",
                       "s4-designer-to-case-critic", "s5-automator-to-runner", "s8-bug-reporter-to-scribe",
                       "s9-retro-to-project")
# The open fields of the S5-S9 contracts above, by generic path (spec t-1765 X7-P §3: the five whose word no code reads).
# A contract of OPEN_LIST_CONTRACTS that is absent here is open on every field.
OPEN_LIST_FIELDS = {
    "s5-automator-to-runner": ("scope[].stale_because",),
    "s8-bug-reporter-to-scribe": ("filed[].action",),
    "s9-retro-to-project": ("knowledge_fold[].kind", "numbers.estimation_ledger_line",
                            "delivery_bookkeeping.post_s9_update"),
}


def _list_is_open(contract: str, generic: str) -> bool:
    """May the list of the field at generic path `generic` of `contract` be extended with `new: <word> -- <why>`?"""
    if contract not in OPEN_LIST_CONTRACTS:
        return False
    return generic in OPEN_LIST_FIELDS.get(contract, (generic,))


TRIED_NO_NOTE = ("", "-")
# What a `tried` row means in an S5-S9 form (spec t-1765 X7-7), named in the refusal so the role knows what to write. Text for the
# role only: nothing reads whether the rows say it.
TRIED_MEANING = {
    "s5-automator-to-critic": "what you did to make the test fall",
    "s6-runner-to-analyst": "one line per window, and the path of your tried.md",
    "s7-analyst-to-scribe": "per red test: the experiment you ran and its outcome",
    "s8-scribe-to-gate-b": "per claim of the report: the code block it rests on",
    "s8-bug-reporter-to-scribe": "your duplicate searches and your reproduction attempts",
    "s9-retro-to-project": "where you looked for the cause",
}


def tried_errors(doc, contract: str) -> list:
    """The presence and shape of the top-level `tried` table of a handoff in TRIED_CONTRACTS: no row with a filled field
    AND no `tried_note` that says why is one problem. Whether a technique fits, or an observation convinces, is the stage
    critic's judgment and is never read here; `blocked.tried` (what failed while filling the form) is another field and
    is not read. A contract outside TRIED_CONTRACTS is not refused: []. Inside it, the direction of error is toward asking:
    a placeholder row, an absent table and a dash are no rows and no reason."""
    if contract not in TRIED_CONTRACTS:
        return []
    if not _is_empty_section(doc, None, "tried"):
        return []
    note = doc.get("tried_note")
    if not handoff.is_placeholder(note) and str(note).strip() not in TRIED_NO_NOTE:
        return []
    meaning = TRIED_MEANING.get(contract)
    what = f" ({meaning})" if meaning else ""
    return [Problem("tried", f"no rows and no tried_note. One row per attempt{what}: requirement, technique, observation, "
                             "evidence - or tried_note with why nothing was tried",
                    "write the rows (or tried_note) in the values file, then run this check again")]


def _blocked_row_problems(doc, spec, role: str = "", vocab: dict | None = None) -> list:
    """GW1-8 (N4, F-10 b): a row in state `blocked` of a form whose `blocked.problem` is empty or a placeholder says
    nothing about what stops it. The trigger is the VALUE `blocked` of a row's `state` field and the PRESENCE of the
    contract's `blocked` section (FR-12, FR-38): a contract with no such section offered the role nothing to fill and is
    never refused for it. A row beside a filled `blocked.problem` passes - that is the vocabulary's own meaning of the
    word. The refusal names, FIRST, the shape that keeps the row as it is (fill `blocked.problem`), then the stand's
    word `blocked_by_env` ONLY when `handoff.options_for_role` gives it to this `role` (FR-1, FR-2: a word the role
    may not write is no door), then the halt road. `blocked_by_env` keeps its own `remedy` check in `s5_precheck`, so
    the form's `remedy` stays optional (one reader of that rule)."""
    if "blocked.problem" not in spec or not handoff.is_placeholder(doc.get("blocked.problem")):
        return []
    out = []
    for path in doc.nodes:
        generic = re.sub(r"\[\d+\]", "[]", path)
        if not ROW_STATE_PATH.fullmatch(path) or generic not in spec:
            continue
        if str(doc.get(path) or "").strip() != "blocked":
            continue
        stand = "blocked_by_env" in handoff.options_for_role(spec[generic], role, vocab)
        shapes = ["keep `blocked` and say what stops the row - fill `blocked.problem` (and `blocked.field`, "
                  "`blocked.tried`); nothing else changes"]
        if stand:
            shapes.append("the stand blocks it - `state: blocked_by_env` and an `unresolved[]` row with "
                          "`reason: blocked_by_env` and a `remedy` (kind, where, change, restart - names only)")
        shapes.append("a factory command refused your run, or anything else outside you stops it - "
                      "`header.verdict: halt` with `blocked.field`, `blocked.problem` (the refusal quoted) and "
                      "`blocked.tried` filled")
        numbered = "; ".join(f"({n}) {text}" for n, text in enumerate(shapes, 1))
        out.append(Problem(
            path, "`blocked` says something outside you stops this row, and `blocked.problem` does not say what. "
                  f"Write it as one of {'three' if stand else 'two'} things: {numbered}. {REPAIR_MARKER}.",
            '--set blocked.problem="<what stops the row>"  ('
            + (f'or for the stand: --set {path}="blocked_by_env"; or ' if stand else "or ")
            + "set header.verdict=halt)",
            also=("blocked.problem",)))
    return out


def check_findings(doc, contract: str, task: str, use_judge: bool) -> tuple:
    """A review's findings, against the rule that cost four windows.

    `cause: tooling` means the author cannot remove the finding by changing the work: nine of
    the twelve findings the code critic wrote on TP1-13797 said exactly that, and every one
    of them went back to the author anyway, four windows running. So a tooling finding must be
    repeated under `tooling_findings` with the tool and a backlog row - the author's window then
    carries `unverified`, which is the honest record, instead of another repair round.

    Where a finding names no cause and a judge is configured, `finding_is_factory_tool` is asked
    once. It is advice recorded beside the finding, never a verdict written into it.
    """
    findings = doc.data.get("findings")
    if not isinstance(findings, list):
        return [], []
    listed = {str(row.get("id")) for row in (doc.data.get("tooling_findings") or [])
              if isinstance(row, dict) and not handoff.is_placeholder(row.get("id"))}
    problems, judged = [], []
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            continue
        fid = str(finding.get("id") or "")
        if handoff.is_placeholder(fid):
            continue
        cause = str(finding.get("cause") or "")
        if cause == "tooling" and fid not in listed:
            problems.append(Problem(
                f"findings[{index}].cause",
                f"{fid} names the factory's own tool, so it is not a repair round for the author: "
                f"repeat it under `tooling_findings` with the tool and a backlog row, and leave "
                f"the instances it blocks in `unverified` with `would_settle_it`",
                "add the tooling_findings row, or name a cause the author can act on"))
            continue
        if cause and not handoff.is_placeholder(cause):
            continue
        answer = _ask_tooling(finding, task, use_judge)
        if answer:
            judged.append({"field": f"findings[{index}].cause", "value": "tooling",
                           "as_written": "", "confidence": answer.get("confidence"),
                           "judgment": "finding_is_factory_tool"})
    return problems, judged


def _ask_tooling(finding, task, use_judge):
    if not use_judge or not judge or not judge.active():
        return None
    try:
        reply = judge.ask({"finding": finding, "subject": finding.get("file") or finding.get("case")},
                          {"q": {"judgment": "finding_is_factory_tool"}}, ticket=task)
    except Exception:
        return None
    answer = (reply.get("answers") or {}).get("q") or {}
    if reply.get("status") != "ok" or reply.get("advisory") or answer.get("value") is not True:
        return None
    return answer


def _fill_claims(doc, art, spec=None) -> tuple:
    """`(doc, fixed, derived, problems)`: the empty claims that have a verifier, filled where code PROVES them.

    Only the claim's own verifier writes a claim, and only `true` (the judge is never asked, the role's word is never
    overwritten: a claim that is not a placeholder is not touched - a role's `false` stays). `False` and `None` write
    nothing: the first is a problem that says what code measured, the second a problem that says what code could not
    measure and leaves the word to the role (an exception inside a verifier is the same `None`, named by its class).
    `spec`, when given, keeps a claim line the contract no longer holds (a form in flight) out of this pass, as the field
    loop keeps it out."""
    fixed, derived, problems = [], [], []
    for path in [p for p in doc.nodes if p.startswith("claims.")]:
        verifier = CLAIMS.get(path[len("claims."):])
        if verifier is None or (spec is not None and path not in spec) or not handoff.is_placeholder(doc.get(path)):
            continue
        art.form_doc = doc
        try:
            got = verifier(art)
        except Exception as exc:
            got = (None, type(exc).__name__)
        if not got:
            got = (None, "the verifier gave no answer")
        verdict, reason = got[0], got[1]
        if verdict is True:
            handoff.set_value(doc, path, True)
            fixed.append(f"{path} = true (verified by handoff_check.CLAIMS: {reason})")
            derived.append({"field": path, "source": "verified by handoff_check.CLAIMS"})
            doc = handoff.parse(doc.text())
        elif spec is not None and spec[path].optional:
            continue
        elif verdict is None:
            problems.append(Problem(path, f"not filled. code could not measure it: {reason}; write your own word",
                                    kind="blank"))
        else:
            problems.append(Problem(path, f"code measured this as false: {reason}; write false and name it in "
                                          "`unresolved`, or repair the work",
                                    "repair the work, or write false and name it in `unresolved`"))
    return doc, fixed, derived, problems


def _check_claims(doc, art) -> list:
    out = []
    art.no_verdict = []
    claims = doc.data.get("claims")
    if not isinstance(claims, dict):
        return out
    for name, value in claims.items():
        verifier = CLAIMS.get(name)
        if not verifier or value is not True:
            continue
        art.form_doc = doc
        got = verifier(art)
        if got and got[0] is None:
            # No verdict: the verifier could not measure. The claim is neither accepted as true
            # nor refused as false; the reason is printed so nobody reads silence as a pass.
            art.no_verdict.append({"claim": f"claims.{name}", "reason": got[1]})
            continue
        if got and not got[0]:
            out.append(Problem(f"claims.{name}",
                               f"the form claims this is true, and it is not: {got[1]}",
                               "repair the work, or write false and name it in `unresolved`"))
    return out


# Which registered question maps this field. They are `judge_form.py`'s own, already calibrated;
# what they never had is a call site on the handover form (all four were asked ZERO times in the
# judged run of TP1-13797, while the form cost twenty-three role resumptions at S5 alone).
JUDGMENT_FOR_FIELD = {
    "state": "form_row_state",
    "verdict": "form_digest_verdict",
    "reason": "form_unresolved_reason",
    "outcome": "form_digest_verdict",
}


# J5: fields a judge answers from the ROW's own contents rather than from a word the role wrote.
# `form_*` above maps a spelling onto a closed list; these answer a question about the work. The
# runner's manual observation against the Then the case quoted is the one that cost a word: with
# nothing able to say whether an observation settled its Then, `inconclusive` was invented in the
# middle of TP1-13797. The question existed, calibrated, with no call site at all - thirty-one
# of the registry's fifty-three were never asked once (plan section 10.2). A judge answering `true`
# or `false` cannot produce `inconclusive`, and does not try: an undecided answer leaves the field
# to the role, exactly as if no judge were configured.
ROW_JUDGMENTS = {
    "manual_observations[].result": {
        "judgment": "result_observation_matches_then",
        "from": ("then", "observed"),
        "values": {True: "passed", False: "failed"},
    },
}


def _ask_judge_row(generic: str, path: str, doc, task: str):
    spec = ROW_JUDGMENTS.get(generic)
    if not spec or not judge or not judge.active():
        return None
    row = _row_of(doc, path) or {}
    state = {}
    for key in spec["from"]:
        value = row.get(key)
        if value in (None, "") or handoff.is_placeholder(value):
            return None                       # the role has not written the question's own input
        state[key] = str(value)
    try:
        reply = judge.ask(state, {"q": {"judgment": spec["judgment"]}},
                          ticket=task, stage=str(doc.get("stage") or ""))
    except Exception:
        return None
    if reply.get("status") != "ok" or reply.get("advisory"):
        return None
    answer = (reply.get("answers") or {}).get("q") or {}
    value = spec["values"].get(answer.get("value")) if answer.get("decided") else None
    if not value:
        return None
    return {"value": value, "confidence": answer.get("confidence"), "judgment": spec["judgment"],
            "as_written": "<unfilled: " + ", ".join(f"{k}={v[:40]}" for k, v in state.items()) + ">"}


def _ask_judge(field, path, written, contract, doc, task, options=None):
    """One question for ADVICE: which value of THIS proposed list is nearest to the word the role wrote?

    The judge is called by the code at the boundary, never by a model inside a dispatch. Its answer is
    printed beside the refusal and recorded in `suggested[]`; it never replaces the role's word, lifts a
    block, passes a gate or decides anything that belongs to a person (AR-29: the word is the role's).
    """
    judgment = JUDGMENT_FOR_FIELD.get(path.rsplit(".", 1)[-1])
    if not judgment:
        return None
    if not judge or not judge.active():
        return None
    vocab = handoff.vocabulary()
    meanings = {}
    for name in ("row_states", "unresolved_reasons", "header_verdicts", "probe_verdicts"):
        block = vocab.get(name)
        if isinstance(block, dict):
            for word, spec in block.items():
                if isinstance(spec, dict):
                    meanings[str(word)] = str(spec.get("meaning") or word)
                else:
                    meanings[str(word)] = str(spec)
    criteria = {opt: meanings.get(opt, opt) for opt in (options or field.options)}
    criteria["other"] = "The word means none of these."
    state = {"contract": contract, "field": path, "written": written,
             "field_means": field.hint, "row": _row_of(doc, path)}
    try:
        reply = judge.ask(state, {"q": {"judgment": judgment, "criteria": criteria}},
                          ticket=task, stage=str(doc.get("stage") or ""))
    except Exception:
        return None
    if reply.get("status") != "ok" or reply.get("advisory"):
        return None
    answer = (reply.get("answers") or {}).get("q") or {}
    value = answer.get("value")
    if not answer.get("decided") or value in (None, "other") or value not in (options or field.options):
        return None
    return {"value": value, "confidence": answer.get("confidence"), "judgment": judgment}


def record_derived(doc, derived: list):
    """What CODE filled, in the form itself.

    Two reasons, and both are about honesty: the receiving role sees which values are the
    artifacts' rather than the author's, and the check can still tell a form the ROLE never
    touched from one `--fix` has written into - without this, one derivable field made an
    ignored form look filled.
    """
    if not derived:
        return doc
    lines = list(doc.lines)
    known = {str(row.get("field")) for row in (doc.data.get("derived") or []) if isinstance(row, dict)}
    new_rows = [row for row in derived if row["field"] not in known]
    if not new_rows:
        return doc
    if "derived" not in doc.data:
        lines += ["",
                  "# Values code filled from the artifacts on disk when the check ran. They are the",
                  "# artifacts' word, not the author's; the receiving role may refuse any of them.",
                  "derived:"]
    for row in new_rows:
        lines += [f"  - field: {row['field']}",
                  f"    source: {json.dumps(str(row['source']), ensure_ascii=False)}"]
    return handoff.parse("\n".join(lines) + "\n")


def record_judged(doc, judged: list):
    """What a judge did and what a role proposed, in the form itself, in three sections by the row's `kind`.

    `judged[]` (no kind): a value a judge WROTE into a blank field - the field carries it, `as_written` keeps what
    the role wrote. `suggested[]` (kind `suggested`): the judge's ADVICE for a word outside a proposed list - the field
    is untouched. `proposed[]` (kind `proposed`): a word the role added with `new: <word> -- <why>`, for the stage
    critic to judge. A row already recorded (same field and word) is not written twice."""
    if not judged:
        return doc
    lines = list(doc.lines)
    seen = {name: {(str(r.get("field")), str(r.get(key))) for r in (doc.data.get(name) or []) if isinstance(r, dict)}
            for name, key in (("suggested", "as_written"), ("proposed", "word"))}
    out = {"judged": [], "suggested": [], "proposed": []}
    for row in judged:
        kind = row.get("kind") or "judged"
        if kind == "suggested":
            if (str(row["field"]), str(row["as_written"])) in seen["suggested"]:
                continue
            out["suggested"] += [f"  - field: {row['field']}",
                                 f"    as_written: {json.dumps(str(row['as_written']), ensure_ascii=False)}",
                                 f"    nearest: {row['nearest']}",
                                 f"    confidence: {row.get('confidence')}",
                                 f"    judgment: {row.get('judgment')}"]
        elif kind == "proposed":
            if (str(row["field"]), str(row["word"])) in seen["proposed"]:
                continue
            out["proposed"] += [f"  - field: {row['field']}",
                                f"    word: {json.dumps(str(row['word']), ensure_ascii=False)}",
                                f"    why: {json.dumps(str(row['why']), ensure_ascii=False)}"]
        else:
            out["judged"] += [f"  - field: {row['field']}",
                              f"    value: {row['value']}",
                              f"    as_written: {json.dumps(str(row['as_written']), ensure_ascii=False)}",
                              f"    confidence: {row.get('confidence')}",
                              f"    judgment: {row.get('judgment')}"]
    heads = {"judged": ["# Values a judge wrote into a blank field when the check ran. The field carries the",
                        "# vocabulary's spelling; `as_written` keeps what the role actually wrote. The receiving",
                        "# role may refuse any of these like any other claim."],
             "suggested": ["# Advice only: the word of the list a judge reads nearest to a word the role wrote. The field",
                           "# keeps the role's word; nothing was changed."],
             "proposed": ["# Words the role added to a proposed list with `new: <word> -- <why>`. The field keeps the",
                          "# word as written; the stage critic judges whether the list needs it."]}
    changed = False
    for name in ("judged", "suggested", "proposed"):
        if not out[name]:
            continue
        changed = True
        start = next((i for i, line in enumerate(lines) if line.rstrip() == f"{name}:"), None)
        if start is None:
            lines += ["", *heads[name], f"{name}:"] + out[name]
            continue
        # the section is already there, and another may follow it: the new rows go at the END OF ITS OWN block
        end = start + 1
        while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
            end += 1
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        lines[end:end] = out[name]
    return handoff.parse("\n".join(lines) + "\n") if changed else doc


# Characters of the role's OWN words that must survive a cut beside the mark: a value made of the mark alone
# would be code's word in the role's field (C2-4 edge 2). At the 80-character limit this is `len(stem) <= 45`.
SHORTEN_ROOM = 8


def shorten_mark(stem: str) -> str:
    return f" [cut: work/handoffs/{stem}.yaml]"


def shorten(doc, problems: list, stem: str) -> tuple:
    """C2-4: cut the TAIL of a field over its limit, only when nothing but length is wrong.

    Returns (doc, rows, problems left). The guard lives HERE because only this check knows all of its
    own problems: a form that also has a judgement problem is not cut - the role is woken for that one
    anyway and can say it shorter itself (P1, FR-47). A field whose limit leaves less than SHORTEN_ROOM
    characters beside the mark is not cut either, and then nothing is. The cut field passes the very
    length check that raised the problem (`kept` is at most the limit), so the cut never loops.
    """
    length = [p for p in problems if p.limit]
    mark = shorten_mark(stem)
    if not length or len(length) != len(problems) or any(p.limit < len(mark) + SHORTEN_ROOM for p in length):
        return doc, [], problems
    rows = []
    for problem in length:
        text = str(doc.get(problem.path))
        kept = text[: problem.limit - len(mark)].rstrip() + mark
        if not handoff.set_value(doc, problem.path, kept):
            continue
        rows.append({"field": problem.path, "as_written": text, "kept": kept})
        doc = handoff.parse(doc.text())            # set_value moves the lines below it
    cut = {row["field"] for row in rows}
    return doc, rows, [p for p in problems if p.path not in cut]


def record_shortened(doc, rows: list):
    """The role's whole text, in the form itself, beside the cut value (FR-37: the mark names this file).

    One row per field: a later cut of the same field replaces the row, so `as_written` is always the
    role's LAST word (C2-4 edge 3).
    """
    if not rows:
        return doc
    old = [r.get("field") if isinstance(r, dict) else None for r in (doc.data.get("shortened") or [])]
    fresh = []
    for row in rows:
        if row["field"] in old:
            index = old.index(row["field"])
            # the one scalar writer (t-919 F-4): it drops a wrapped value's continuation lines and quotes what needs quoting
            for key in ("as_written", "kept"):
                handoff.set_value(doc, f"shortened[{index}].{key}", row[key])
                doc = handoff.parse(doc.text())            # set_value moves the lines below it
        else:
            fresh.append(row)
    lines = list(doc.lines)
    added = [line for row in fresh
             for line in (f"  - field: {row['field']}",
                          f"    as_written: {json.dumps(row['as_written'], ensure_ascii=False)}",
                          f"    kept: {json.dumps(row['kept'], ensure_ascii=False)}")]
    rows_at = [n.end_line for p, n in doc.nodes.items() if p.startswith("shortened[")]
    if fresh and rows_at:
        lines[max(rows_at) + 1:max(rows_at) + 1] = added      # inside the section, whatever follows it
    elif fresh:
        lines += ["",
                  "# Fields code cut to their limit when the check ran (--shorten). The field carries the",
                  "# start of what the role wrote and the mark; `as_written` keeps the whole text.",
                  "shortened:"] + added
    return handoff.parse("\n".join(lines) + "\n")


# ------------------------------------------------------------ the role's values (SC1-2, RC1-11)
# A field was filled by one `--set` process each (89 of them in one scout's S1, 35-50 s apiece), and a new row of a
# list could not be created at all. The role now says every field it owns in one file or one call, and ONE function
# writes them - `--set`, `--values` and the waiting file differ only in where the pairs come from.
INDEXED = re.compile(r"\[(\d+)\]")
VALUE_PATH = re.compile(r"^[A-Za-z_][\w\-]*(?:\[\d+\])?(?:\.[A-Za-z_][\w\-]*(?:\[\d+\])?)*$")
FILE_FIX = ("write the line as `path: value`, one field per line; a row of a list by its index, "
            "`\"<list>[0].<field>\": value`, the next row `[1]` (a JSON object of paths is also read)")


def sibling_values(form_path) -> Path:
    """The file the role writes its fields to, beside its form: `<dispatch>.values.yaml`. Only this exact name -
    `.values.applied.yaml` (the trace code leaves) and `.values.stale.yaml` are never read as words to apply."""
    form = Path(form_path)
    return form.with_name(f"{form.stem}.values.yaml")


def sibling_help(form_path) -> Path:
    """The conductor's help beside a form, `<dispatch>.help.yaml` (written by `handoff_help.py` as `form.with_suffix(".help.yaml")`)."""
    return Path(form_path).with_suffix(".help.yaml")


def _flat(value) -> bool:
    """A word, a number, or a list of those. A map is never a value of a form field."""
    if isinstance(value, dict):
        return False
    return not isinstance(value, list) or all(not isinstance(v, (dict, list)) for v in value)


def _row_lists(spec: dict) -> dict:
    """`{list name: [paths of its row 0]}` of the lists of ROWS in a contract's spec, in the spec's order (HF8-7).

    A list of rows is the prefix before the first `[].` of a path (`scope[].id` -> `scope`; a nested prefix such as
    `environment.preconditions_accepted_as_blocked[].case` is kept whole); `blocked.tried[]` is a list of values, not
    of rows. Every `[]` of a path reads `[0]`; a leaf list of values keeps its index (`execution[0].preconditions[0]`).
    A path the contract writes itself (`owned_by_contract`) or code fills (`_code_fills`) is not the role's: it is left
    out, and a list with nothing left is not a list of rows (the role is never shown a path it cannot write)."""
    out = {}
    for generic in spec:
        head, sep, _rest = generic.partition("[].")
        if not sep or handoff.owned_by_contract(generic) or _code_fills(generic):
            continue
        out.setdefault(head, []).append(generic.replace("[]", "[0]"))
    return out


def _list_key(name: str) -> str:
    """`name` with its trailing row indexes taken off (`scope[0]` -> `scope`)."""
    return re.sub(r"(?:\[\d+\])+$", "", name or "")


def row_form(spec: dict, name: str = "") -> tuple:
    """`(list name, paths of its row 0)`: the ONE hint of how a row of a list is written (HF8-7, AR-13/AR-15).

    The list is `name` (indexes taken off) when it is a list of rows; else the first of `handoff.REQUIRED_LISTS` the
    contract has; else the first by the spec's order. No list of rows -> `("", [])`. The contract decides which list
    and which fields (AR-1); code only shows the form of the line."""
    lists = _row_lists(spec)
    key = _list_key(name)
    if key not in lists:
        key = next((n for n in handoff.REQUIRED_LISTS if n in lists), next(iter(lists), ""))
    return (key, lists[key]) if key else ("", [])


def row_pair(paths: list) -> tuple:
    """`(first, next)`: the first path of a row that is not a list of values, and the same path in the next row (the
    first index plus one); `("", "")` when there is none. The one place the two samples are made."""
    first = next((p for p in paths if not p.endswith("]")), "")
    if not first:
        return "", ""
    return first, INDEXED.sub(lambda m: "[" + str(int(m.group(1)) + 1) + "]", first, count=1)


def _row_sentence(paths: list) -> str:
    """The sentence that names the indexed form of a row; the general form when the contract names no row."""
    first, later = row_pair(paths)
    if not first:
        return 'a row of a list is written by its index: `"<list>[0].<field>": <value>`'
    return f'a row of a list is written one line per key: `"{first}": <value>`, the next row `"{later}"`'


class _ValuesHints:
    """The row-form hints of one `parse_values` call (HF8-7, SC2-14): the contract is read lazily, at the first problem
    of a row's form, once per parse; an unreadable one gives the general text (AR-28: a hint cannot pass a form, the
    caller's `problems` is already set). A hint only changes the TEXT of a problem, never whether a line is a pair."""

    def __init__(self, contract: str):
        self.contract = contract
        self._memo = {}

    def spec_once(self) -> dict:
        if "spec" not in self._memo:
            try:
                self._memo["spec"] = handoff.spec(self.contract) if self.contract else {}
            except Exception:
                self._memo["spec"] = {}
        return self._memo["spec"]

    def hint(self, name: str = "", strict: bool = False) -> tuple:
        """`(sentence, also)` of the row form for `name`; `strict`: nothing when a readable contract says `name` is not
        a list of rows."""
        key = ("hint", name, strict)
        if key not in self._memo:
            spec = self.spec_once()
            if strict and spec and _list_key(name) not in _row_lists(spec):
                self._memo[key] = ("", ())
            else:
                _list, paths = row_form(spec, name)
                self._memo[key] = (_row_sentence(paths), tuple(paths))
        return self._memo[key]

    def aim(self, name: str, header: str = "") -> tuple:
        """`(sentence, also)` for a line that did not become a pair, by the shape of its path alone (FR-12): a dotted
        index is read as an index (`scope.0.id` -> `scope[0].id`) when the contract has that field; else the list of
        the block header above; else the first word of the line when it is a list of rows; else the first list."""
        spec = self.spec_once()
        dotted = re.sub(r"\.([0-9]+)(?=\.|$)", lambda m: f"[{int(m.group(1))}]", name)
        if dotted != name and VALUE_PATH.match(dotted) and spec:
            if (INDEXED.sub("[]", dotted) in spec and not handoff.owned_by_contract(dotted)
                    and not _code_fills(dotted)):
                return ("" if dotted.endswith("]") else _row_sentence([dotted])), (dotted,)
        if header:
            return self.hint(header)
        word = re.match(r"[A-Za-z_][\w\-]*", name)
        return self.hint(word.group(0) if word else "")


def parse_values(text: str, label: str = "values", *, contract: str = "") -> tuple:
    """`(pairs, problems)` of a values text. A pair is `(path, value, line_no, raw_line)`.

    Two shapes, nothing in between: `path: value` lines (the path with or without quotes, the value read by the
    form's own scalar reader), or ONE flat JSON object `{path: word | [words]}` when the text starts with `{`.
    Comments, blank lines, a BOM and CRLF are accepted. Every line that does not parse is a problem WITH ITS NUMBER;
    the pairs that did parse are returned anyway (the guard keeps them for the role) but the CALLER applies
    nothing while `problems` is not empty - a line is never lost silently and never applied by halves.

    `contract` (HF8-7) only makes the TEXT of a problem exact: it names the indexed form of a row on the contract's own
    list, and `Problem.also` carries the paths of that row for the refusal's skeleton. It never changes which lines are
    pairs and which are problems. The contract is read lazily - at the first problem of a row's form, once per parse -
    and an unreadable one gives the general text (AR-28: the hint cannot pass a form, `problems` is already set)."""
    pairs, problems = [], []
    text = text.lstrip("﻿")
    hints = _ValuesHints(contract)
    hint, aim = hints.hint, hints.aim

    def bad(number, what, also=()):
        problems.append(Problem(f"{label} line {number}", what, FILE_FIX, also=also))

    def said(base: str, sentence: str) -> str:
        return f"{base}; {sentence}" if sentence else base

    if text.lstrip().startswith(("{", "[")):
        repeated = []

        def keep_all(items):
            names = [name for name, _ in items]
            repeated.extend(sorted({name for name in names if names.count(name) > 1}))
            return dict(items)

        try:
            data = json.loads(text, object_pairs_hook=keep_all)
        except (ValueError, RecursionError) as exc:
            sentence, also = hint()
            bad(1, said(f"not valid JSON ({exc}); the file is `path: value` lines or one flat JSON object",
                        sentence), also)
            return pairs, problems
        if not isinstance(data, dict):
            sentence, also = hint()
            bad(1, said("a JSON values file is one object {\"path\": value}, not a list", sentence), also)
            return pairs, problems
        for name in repeated:
            bad(1, f"`{name}` is given twice")
        for name, value in data.items():
            if not VALUE_PATH.match(name):
                sentence, also = aim(name)
                bad(1, said(f"`{name[:60]}` is not a field path such as `header.verdict`", sentence), also)
            elif not _flat(value):
                sentence, also = hint(name, strict=True)
                bad(1, said(f"`{name}`: a value is a word or a flat list of words, not a nested object", sentence), also)
            elif name not in repeated:
                pairs.append((name, value, 1, f"{name}: {handoff._render(value)}"))
        return pairs, problems

    seen = {}
    header = ""                      # the list a bare `name:` line above opened (block YAML), until another line
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head, sep, rest = line.partition(":")
        name = handoff._unquote(head.strip())
        if not sep or (rest and not rest[0].isspace()) or not VALUE_PATH.match(name):
            sentence, also = aim(name, header if line.startswith("- ") else "")
            if not line.startswith("- "):
                header = ""
            bad(number, said(f"`{line[:60]}` is not a `path: value` line", sentence), also)
            continue
        body, _comment = handoff._strip_comment(rest)
        header = name if not body.strip() else (header if raw[:1].isspace() else "")
        try:
            value = handoff._scalar(body)
        except RecursionError:
            bad(number, f"`{line[:60]}` is not a `path: value` line")
            continue
        if not _flat(value):
            sentence, also = hint(name, strict=True)
            bad(number, said(f"`{name}`: a value is a word or a flat list of words, not a nested object", sentence), also)
        elif name in seen:
            bad(number, f"`{name}` is given twice (lines {seen[name]} and {number})")
        else:
            seen[name] = number
            pairs.append((name, value, number, line))
    return pairs, problems


def _row_count(doc, list_path: str) -> int:
    """How many rows the list at `list_path` holds in this document: the highest row index of any node under it, plus one."""
    pattern = re.compile(re.escape(list_path) + r"\[(\d+)\]")
    last = -1
    for path in doc.nodes:
        found = pattern.match(path)
        if found:
            last = max(last, int(found.group(1)))
    return last + 1


def open_row(doc, contract: str, list_path: str, index: int) -> bool:
    """Open the row `list_path[index]` when `index` is exactly the number of rows the form holds; True when it did.

    The new row's lines are the CONTRACT's own first row (`_row_template` of the contract, parents read as row 0): its
    placeholders, never the values of another row of the form. There is no second row builder here. It goes after the
    last line of the list, so a nested row (`open_questions[0].readings[1]`) lands inside its parent. A list the form
    holds with no row at all (`scope: []`, or the section left out) is opened the way `_open_rows_from_contract`
    does it; a nested list with no row is not (False: the caller reports it). Any other index is not an opening: an
    index past the next one would leave a hole, an index of an existing row opens nothing."""
    count = _row_count(doc, list_path)
    if index != count:
        return False
    in_contract = INDEXED.sub("[0]", list_path)
    contract_doc = handoff.template(contract)
    found = _row_template(contract_doc, in_contract)
    if not found or not any(p.startswith(in_contract + "[0].") for p in contract_doc.nodes):
        return False                                  # a list of plain values has no row to open
    lines = list(found[2])

    def lead(text):
        return len(text) - len(text.lstrip())

    if count:
        first = min(node.line for path, node in doc.nodes.items() if path.startswith(f"{list_path}[0]"))
        shift = lead(doc.lines[first]) - lead(lines[0])      # the form's rows keep the form's own indent
        if shift:
            lines = [(" " * shift + line if shift > 0 else line[min(-shift, lead(line)):]) if line.strip() else line
                     for line in lines]
        last = max(node.end_line for path, node in doc.nodes.items() if path.startswith(f"{list_path}[{count - 1}]"))
        doc.lines[last + 1:last + 1] = lines
        return True
    name = list_path.rsplit(".", 1)[-1]
    if "." in list_path:
        return False
    header = re.compile(r"^" + re.escape(name) + r":\s*(\[\s*\])?\s*(#.*)?$")
    at = next((i for i, line in enumerate(doc.lines) if header.match(line)), None)
    if at is None:
        doc.lines = doc.lines + ["", f"{name}:"] + lines
    else:
        doc.lines = doc.lines[:at] + [f"{name}:"] + lines + doc.lines[at + 1:]
    return True


def _open_rows_for(doc, contract: str, path: str) -> tuple:
    """`(document, "")` with every row `path` names opened in order, or `(document unchanged, why not)`.

    Left to right, so a parent row opens before the child that sits in it. The work is done on a copy: a path that
    fails half way opens nothing (the hole is the role's mistake, not a row to leave behind)."""
    trial = handoff.parse(doc.text())
    for found in INDEXED.finditer(path):
        list_path, index = path[:found.start()], int(found.group(1))
        count = _row_count(trial, list_path)
        if index < count:
            continue
        if index > count:
            return doc, f"the next row is `{list_path}[{count}]` - rows are opened in order and none is skipped"
        if not open_row(trial, contract, list_path, index):
            return doc, f"no row of `{list_path}` can be opened from `{contract}`"
        trial = handoff.parse(trial.text())
    return trial, ""


def _set_whole_list(doc, path: str, values: list) -> tuple:
    """Replace the list of values at `path` by `values`, whatever number of items it held; `(document, written)`.
    `handoff.set_list` replaces only the first item, so the others go first."""
    items = [node for item, node in doc.nodes.items() if re.fullmatch(re.escape(path) + r"\[\d+\]", item)]
    if not items:
        return doc, False
    dead = {number for node in items[1:] for number in range(node.line, node.end_line + 1)}
    doc.lines = [line for number, line in enumerate(doc.lines) if number not in dead]
    doc = handoff.parse(doc.text())
    return doc, handoff.set_list(doc, path, values)


def _blank_value(value) -> bool:
    """A placeholder (or nothing, or a list of nothing): not a word of the role."""
    if isinstance(value, list):
        return all(handoff.is_placeholder(v) for v in value)
    return handoff.is_placeholder(value)


def _path_order(path: str) -> list:
    """Sort key: names alphabetically, row indexes by number - `scope[2]` is applied before `scope[10]`."""
    return [(1, int(token)) if token.isdigit() else (0, token)
            for token in re.findall(r"[A-Za-z_][\w\-]*|\d+", path)]


def _near(path: str, spec: dict, doc) -> str:
    """The closest path the contract or the form knows, for an unknown one; "" when nothing is close."""
    generic = INDEXED.sub("[]", path)
    near = difflib.get_close_matches(generic, [p for p in spec if not handoff.owned_by_contract(p)], n=1, cutoff=0.6)
    if near:
        guess = near[0]
        for index in INDEXED.findall(path):
            guess = guess.replace("[]", f"[{index}]", 1)
        guess = guess.replace("[]", "[0]")
        return guess[:guess.rindex("[")] if guess.endswith("]") else guess   # a list of values is written whole
    near = difflib.get_close_matches(path, [p for p in doc.nodes if not handoff.owned_by_contract(p)], n=1, cutoff=0.6)
    return near[0] if near else ""


def _apply_one(doc, contract: str, spec: dict, path: str, value, raw: bool) -> tuple:
    """`(document, written, problem | None, note)` for one pair; see `apply_values`."""
    generic = INDEXED.sub("[]", path)

    def refuse(text, fix=""):
        return doc, False, Problem(path, text, fix), ""

    if raw and path in doc.nodes:              # `--set` of a line the form holds: as it always was, the typed text
        # a write that changes nothing says so (FR-41) - only for a word the field can hold: a placeholder typed with
        # `--set` stays what it always was, a write (the form would refuse it from a values file)
        if not _blank_value(value) and handoff._render(doc.get(path)) == handoff._render(value):
            return doc, False, None, f"nothing changed: `{path}` already reads {handoff._render(value)}"
        handoff.set_value(doc, path, value)
        return handoff.parse(doc.text()), True, None, ""
    if not raw and _blank_value(value):
        return doc, False, None, f"`{path}`: a placeholder or an empty value is not a word - nothing written"
    if path.endswith("]"):
        head = path[:path.rindex("[")]
        if INDEXED.sub("[]", head) + "[]" in spec:
            return refuse(f"`{head}` is a list of values: write it whole on one line, `{head}: [a, b]`",
                          f"{head}: [a, b]")
        return refuse(f"name the field of the row: `{path}.<field>`", f"{path}.<field>: <value>")
    if handoff.owned_by_contract(path):
        return refuse(f"`{path}` is written by the contract itself, not by the role",
                      "leave it out of the values")
    as_list = generic + "[]" in spec and generic not in spec
    if generic in spec or as_list:
        if as_list and not isinstance(value, list):
            return refuse(f"`{path}` is a list of values: write it whole on one line, `{path}: [a, b]`",
                          f"{path}: [a, b]")
        if not as_list and isinstance(value, list):
            return refuse(f"`{path}` is one value, not a list", f"{path}: <value>")
        opened, why = _open_rows_for(doc, contract, path)
        if why:
            return refuse(why)
        if as_list:
            opened, wrote = _set_whole_list(opened, path, value)
        else:
            wrote = handoff.set_value(opened, path, value)
        if not wrote:                                 # M-7: a form begun on an older package has no line for it
            return doc, False, None, (f"`{path}`: this form has no line for it and its check does not ask for it - "
                                      "not written")
        return handoff.parse(opened.text()), True, None, ""
    if path in doc.nodes:                             # M-7: a line the form still holds, the contract no longer does
        handoff.set_value(doc, path, value)
        return (handoff.parse(doc.text()), True, None,
                f"`{path}` is not in `{contract}` any more; written as the form holds it")
    guess = _near(path, spec, doc)
    return refuse(f"`{path}` is not a field of `{contract}`" + (f" - did you mean `{guess}`?" if guess else ""),
                  f"{guess}: <value>" if guess else FILE_FIX)


def apply_values(doc, contract: str, pairs: list, *, raw: bool = False) -> tuple:
    """`(document, applied, problems, notes)`: write the pairs `(path, value, line_no, raw_line)` into the form.

    The ONE writer of a role's words. Pairs go in path order (row indexes ascending), so `scope[2]` and `scope[3]` in
    one file open two rows one after the other. For each pair, in this order:
    a placeholder or an empty value is not written (a note), except for `raw` (`--set`: the text as typed, a
    placeholder included, as it always was);
    a path that ends in an index has no field: a problem naming the whole-list line or the row's field;
    a path the contract writes itself is a problem;
    a path of the contract's spec (row indexes generalised) is written; an index equal to the number of rows opens
    that row first (`open_row`), a larger one is a problem and opens nothing; a path of the spec the form has no line
    for is not written, with a note;
    a path only the form still holds (an older contract) is written, with a note;
    any other path is a problem naming the closest known one. Every other pair is applied: one unknown path never
    stops the rest. `applied` counts the values written. The caller applies nothing from a text that did not parse."""
    spec = handoff.spec(contract)
    applied, problems, notes = 0, [], []
    for path, value, _line, _text in sorted(pairs, key=lambda pair: _path_order(pair[0])):
        doc, wrote, problem, note = _apply_one(doc, contract, spec, path, value, raw)
        applied += wrote
        if problem:
            problems.append(problem)
        if note:
            notes.append(note)
    return doc, applied, problems, notes


def _text_of(label: str, read) -> tuple:
    """`(text, problem | None)`: the bytes of a values source as UTF-8 (BOM allowed), or why they cannot be read."""
    try:
        return read().decode("utf-8-sig"), None
    except (OSError, UnicodeDecodeError) as exc:
        return "", Problem(label, f"cannot be read as UTF-8 text ({exc})", "write it again as plain UTF-8 text")


def _apply_text(doc, contract: str, label: str, read) -> tuple:
    """`(document, applied, problems, notes, parsed, kept)` for one values source. A text with a line that does not parse
    applies NOTHING (its problems come back with their line numbers); `parsed` is False then, and `kept` holds the
    lines that DID parse, verbatim - the refusal's skeleton gives them back, so the role rewrites its file whole and
    loses no good line (SC1-2 A2, M-4)."""
    text, unread = _text_of(label, read)
    if unread:
        return doc, 0, [unread], [], False, []
    pairs, problems = parse_values(text, label, contract=contract)
    if problems:
        return doc, 0, problems, [], False, [raw for _p, _v, _n, raw in pairs]
    doc, applied, problems, notes = apply_values(doc, contract, pairs)
    return doc, applied, problems, notes, True, []


def _apply_sources(path: Path, doc, contract: str, args) -> tuple:
    """Every source of a role's words, in the order sibling file -> `--values` -> `--set`; the later word wins.

    Returns `(document, applied, problems, notes, consumed, pending, from_sibling, kept)`:
    `consumed` is the waiting file to rename `.values.applied.yaml` once the form is written (set only on a WRITING
    run - `--fix`, `--values`, `--set` - and only for a file that parsed); `pending` is the waiting file's name when it
    is still there after this run; `from_sibling` counts what the waiting file put in (the line main prints); `kept`
    is the good lines of every source that did NOT parse (the refusal gives them back, M-4).
    A source that does not parse is not applied by a single line and not renamed; an explicit `--values` file other
    than the sibling is never renamed."""
    writing = bool(args.fix or args.set or args.values)
    sibling = sibling_values(path)
    problems, notes, applied, from_sibling, consumed, kept = [], [], 0, 0, None, []
    if sibling.is_file():
        doc, from_sibling, found, more, parsed, good = _apply_text(doc, contract, sibling.name, sibling.read_bytes)
        applied += from_sibling
        problems += found
        notes += more
        kept += good
        if parsed and writing:
            consumed = sibling
    if args.values:
        named = None if args.values == "-" else Path(args.values)
        if named is None or not (sibling.is_file() and named.resolve() == sibling.resolve()):
            label = "stdin" if named is None else named.name
            read = sys.stdin.buffer.read if named is None else named.read_bytes
            doc, count, found, more, _parsed, good = _apply_text(doc, contract, label, read)
            applied += count
            problems += found
            notes += more
            kept += [line for line in good if line not in kept]
    if args.set:
        pairs = [(key.strip(), value, 0, assignment)
                 for assignment in args.set for key, _, value in [assignment.partition("=")]]
        doc, count, found, more = apply_values(doc, contract, pairs, raw=True)
        applied += count
        problems += found
        notes += more
    pending = sibling.name if sibling.is_file() and consumed is None else ""
    return doc, applied, problems, notes, consumed, pending, from_sibling, kept


def form_view(form_path):
    """The form as the NEXT writing `handoff_check` will see it: the form plus its waiting values file merged IN MEMORY
    (SC1-2 part D, B-1). The ONE reader for everything that looks at a form before `--fix` has applied the file - the
    halt reader of `finish` and of the driver, the digest assembler, the conductor's help, the repair route - so a
    `header.verdict: halt`, a `blocked` or a critic's `findings` the role wrote only in `<dispatch>.values.yaml` are
    heard, not missed because the form on disk still shows the placeholders.

    PURE and read-only: nothing is written, the file is not renamed, no `check`, no deriver, no judge. The error
    direction is the RAW form (what every reader saw before this function): a missing, empty or unparseable waiting
    file, a file that is not UTF-8 text, a form that names no readable contract, or any exception on the values side
    gives the form as it lies on disk - never a view with LESS than the raw form. The form's own read errors are the
    caller's (each reader has its `except`). An unparseable waiting file is refused by `--fix` (a problem with its
    line number), so the form does not pass `finish` over it."""
    text = Path(form_path).read_text(encoding="utf-8-sig", errors="replace")
    doc = handoff.parse(text)
    try:
        sibling = sibling_values(form_path)
        if not sibling.is_file():
            return doc
        values_text, unread = _text_of(sibling.name, sibling.read_bytes)
        if unread:
            return doc
        pairs, problems = parse_values(values_text, sibling.name)
        contract = str(doc.get("contract") or "")
        if problems or not pairs or not contract:
            return doc
        return apply_values(handoff.parse(text), contract, pairs, raw=False)[0]      # an unreadable contract raises: raw
    except Exception:
        return doc


# ------------------------------------------------------- one refusal, one command (SC1-2 part A2, RC1-11)
# A refusal used to print `fix: --set path="<value>"` under every problem, and the role ran them one by one (89
# processes in one scout's S1). Now a form that is not ready is refused in ONE block with ONE ready command: a skeleton
# of `path: value` lines - the allowed values inline, a line for every path to fill, the door of a problem that lives on
# another path - and the same lines can be written to the values file by a role that has no shell.
def _code_fills(path: str) -> bool:
    """Whether `--fix` fills this field itself: the ONE answer. A path (row indexes generalised) is code-filled when it
    has a deriver (`DERIVERS`), is a list a deriver fills whole (`LIST_DERIVERS`), its leaf is a fact code reads under one
    name everywhere (`BY_LEAF`), or it is a claim a verifier covers (`CLAIMS`). A role that cannot produce such a field
    must not be refused for leaving it blank (FR-11) - the writing check at `finish` fills it, or refuses it with its own
    reason; `test_field_producers.derived_paths` reads the same dictionaries."""
    generic = INDEXED.sub("[]", path)
    if generic in DERIVERS or generic.removesuffix("[]") in LIST_DERIVERS:
        return True
    if generic.rsplit(".", 1)[-1] in BY_LEAF:
        return True
    return generic.startswith("claims.") and generic[len("claims."):] in CLAIMS


def _placeholder(generic: str, spec: dict, role: str, vocab: dict, whole_list: bool = False) -> str:
    """`<a|b|c>` for a field with a closed list (the role's own `state` words, FR-13: the list is the vocabulary's),
    `<hint>` for any other; `[<...>]` for a list of values written whole on one line (`whole_list`). Never a value the
    form cannot take (FR-59): the role reads what it must supply. The text is proved to read back as BLANK through the
    values parser itself, so a skeleton left unfilled writes nothing; a hint that would not (a `#`, a quote, or a comma
    inside a one-line list) is replaced by a plain sentence."""
    field = spec[generic]
    options = handoff.options_for_role(field, role, vocab) if generic.endswith(".state") else field.options
    shown = "|".join(options) if options else " ".join(str(field.hint).split())
    for words in (shown, "the value of this field"):
        text = f"<{words}>"
        if whole_list:
            text = "[" + text.replace(",", ";") + "]"
        pairs, bad = parse_values(f"x: {text}")
        if not bad and pairs and _blank_value(pairs[0][1]):
            break
    return text                                           # the plain sentence, the last candidate, always reads blank


def values_skeleton(problems: list, contract: str, role: str, *, kept=()) -> str:
    """The values lines a role writes to fix `problems`: first `kept` (the role's own good lines, verbatim, M-4), then
    one line for every unique path of a problem and of its `also`, `<path>: <placeholder>`. A path with `[` or `]` is
    quoted. Nothing is cut: a long list of allowed words and a long list of paths are printed whole (an incomplete list
    is a value the role would learn only from the next refusal). A path of `kept` is not repeated. A problem on a LIST
    SECTION (no rows) gets the line of every field of its first row from the contract; a path ending in an index is a
    list of values and is written whole on one line, `path: [<hint>]`; a problem on no field of the contract gets a
    comment line `# <path>: <fix>`. Every fact here is the contract's."""
    spec = handoff.spec(contract)
    vocab = handoff.vocabulary()
    sections = handoff.sections(contract)
    lines = {}

    def quoted(path):
        return f'"{path}"' if "[" in path or "]" in path else path

    def add(path, generic):
        value = _placeholder(generic, spec, role, vocab)
        lines.setdefault(path, f"{quoted(path)}: {value}")

    def whole(head, generic):
        lines.setdefault(head, f"{quoted(head)}: " + _placeholder(generic, spec, role, vocab, whole_list=True))

    for raw in kept:
        name = handoff._unquote(raw.partition(":")[0].strip())
        lines.pop(name, None)                 # the same path twice: the later word, in the later place
        lines[name] = raw
    for problem in problems:
        for path in dict.fromkeys((problem.path, *problem.also)):
            generic = INDEXED.sub("[]", path)
            if path.endswith("]") and generic in spec:           # a list of values: one line for the whole list
                whole(path[:path.rindex("[")], generic)
            elif generic in spec and not handoff.owned_by_contract(path):
                add(path, generic)
            elif sections.get(path) == "list" and any(g.startswith(path + "[].") for g in spec):
                for g in spec:
                    if not g.startswith(path + "[].") or handoff.owned_by_contract(g) or _code_fills(g):
                        continue                         # the role cannot write it (M-9): code fills it
                    if g.endswith("[]"):                 # a list of values in a row: one line, written whole (FR-2)
                        whole(g.replace("[]", "[0]")[:-3], g)
                    else:
                        add(g.replace("[]", "[0]"), g)
            elif path == problem.path:
                lines.setdefault("# " + path, f"# {path}: {problem.fix or problem.text}")
    return "\n".join(lines.values())


def _doors(role: str) -> tuple:
    """`(shell, no_shell)` - which doors this role is shown. A role whose file lists Bash gets the command; a role that
    does not gets the file only; no role named, or a role with no readable file (`role_tools` is None), both."""
    tools = host_adapter.role_tools(role) if role else None
    return tools is None or "Bash" in tools, tools is None or "Bash" not in tools


def _arg(text: str) -> str:
    """A path as one shell word in bash and PowerShell alike: forward slashes, quoted only when it has to be."""
    text = str(text).replace("\\", "/")
    return f'"{text}"' if re.search(r"[\s'\"$`&;()<>|]", text) else text


def refusal_text(form_path, contract: str, problems: list, role: str, *, kept=()) -> str:
    """The ONE refusal of a form that is not ready; the pre-tool guard builds its refusal with this same function.

    The header and a line per problem, then ONE command: for a role with Bash the `--values -` heredoc carrying the
    skeleton, and ALWAYS the file door beside it (it works in any shell and in none - a heredoc is bash only); for a
    role without Bash the file door alone, because it has no command to run. A role not named gets both. With `kept`
    the door says to rewrite the file WHOLE: yours that passed first, then the lines to fix (M-4)."""
    form = Path(form_path)
    sibling = sibling_values(form).as_posix()          # the whole path: a role is given it, not left to search (FR-15)
    skeleton = values_skeleton(problems, contract, role, kept=kept)
    shell, no_shell = _doors(role)
    out = [f"handoff_check: {contract} is not ready - {len(problems)} field(s) below.", f"  form: {form_path}"]
    out += ["  " + problem.line() for problem in problems]
    if shell:
        out += ["  Fill every field with this one command (replace each <...>; a line left as <...> writes nothing):",
                f'python "{HERE.as_posix()}/handoff_check.py" --file {_arg(form_path)} --fix --values - <<\'EOF\'',
                skeleton, "EOF"]
        if kept:
            out.append(f"or, in any shell or none: Rewrite {sibling} WHOLE with the same lines - yours that passed "
                       "first, then the ones to fix; the next check applies them")
        else:
            out.append(f"or, in any shell or none: Write the same lines to {sibling} in one Write; the next check "
                       "applies them")
    else:
        if kept:
            out.append(f"  Rewrite {sibling} WHOLE with the lines below: yours that passed first, then the ones to fix")
        else:
            out.append(f"  Write these lines to {sibling} in one Write; story_step finish applies them")
        out.append(skeleton)
    tail = "  Nothing here is about your work: it is the form."
    if shell:
        tail += f" What you cannot fill, fill under `blocked` and run: handoff_help.py --file {form_path}"
    if no_shell:
        tail += " What you cannot fill: fill blocked.field and blocked.problem in the same values file."
    out.append(tail)
    return "\n".join(out)


class ValuesReport(NamedTuple):
    """What `values_report` says about a form with a values text merged in memory (SC2-13, AR-13).

    `problems`, `role`, `kept` as before; `contract` is the form's own `contract:` line (`""` when it has none);
    `blocked_said` is the one fact the guard's door reads: the merged form, BEFORE `check(fix=True)` derives anything,
    holds a filled `blocked.problem`. It is False for a text that did not parse: a file that will not apply opens no door."""
    problems: list
    role: str
    kept: list
    contract: str
    blocked_said: bool


def values_report(form_path, values_text: str, *, artifacts_root=None) -> ValuesReport:
    """`ValuesReport(problems, role, kept, contract, blocked_said)` of a form with a values text merged IN MEMORY - the
    pre-tool guard's question before a role's values file is written. PURE: nothing is written, the judge is never
    asked (`use_judge=False`), and the form on disk is read once. The exceptions are the caller's (the guard lets the
    write through on one: `finish` checks it again).

    A text that does not parse applies nothing: its problems come back with the parsed lines as `kept`. Otherwise each
    pair goes through `apply_values` (in the order it uses itself) and the merged form meets `check(fix=True)`.
    The error direction is SOFTER than `--fix` in one place only: a blank field `kind == "blank"` that `_code_fills`
    names is not a problem here - the role cannot produce it, and the writing check at `finish` fills it or refuses
    it. `kept` is each line that was written and whose path no problem names, verbatim.
    `blocked_said` is read after the pairs went in and before `check(fix=True)`: a derivation of `--fix` opens no door."""
    form = Path(form_path)
    doc = handoff.parse(form.read_text(encoding="utf-8-sig", errors="replace"))
    contract = str(doc.get("contract") or "")
    role = str(doc.get("header.role") or doc.get("from_role") or "")
    pairs, problems = parse_values(values_text, contract=contract)
    if problems:
        return ValuesReport(problems, role, [raw for _path, _value, _line, raw in pairs], contract, False)
    written = []
    for pair in sorted(pairs, key=lambda pair: _path_order(pair[0])):
        doc, count, found, _notes = apply_values(doc, contract, [pair])
        problems += found
        if count:
            written.append(pair)
    blocked_said = not handoff.is_placeholder(doc.get("blocked.problem"))
    root = Path(artifacts_root) if artifacts_root else form.parent.parent.parent
    doc, _fixed, found, _judged, _derived = check(doc, contract, Artifacts(root, dispatch=form.stem),
                                                  fix=True, use_judge=False)
    problems += [p for p in found if not (p.kind == "blank" and _code_fills(p.path))]
    named = {p.path for p in problems}
    return ValuesReport(problems, role, [raw for path, _value, _line, raw in written if path not in named],
                        contract, blocked_said)


class _Outcome(NamedTuple):
    """What `main` knows once the form is written and the values file renamed: everything the answer prints (SC2-14).
    `consumed` is None when nothing was consumed or the rename failed; `writes` is True when the run asked to write."""
    contract: str
    doc: object
    role: str
    kept: list
    problems: list
    source_problems: list
    fixed: list
    shortened: list
    judged: list
    untouched: bool
    no_verdict: list
    values_applied: int
    values_notes: list
    consumed: object
    pending: str
    from_sibling: int
    applied_name: str
    writes: bool


def _answer_json(out: _Outcome) -> int:
    """The `--json` answer: the keys and their ORDER are a contract (FR-14: story_run.py and story_step.py parse it)."""
    filled, total = filled_share(out.doc, out.contract)
    print(json.dumps({"contract": out.contract, "fixed": out.fixed,
                      "shortened": [{"field": r["field"], "kept_len": len(r["kept"]),
                                     "written_len": len(r["as_written"])} for r in out.shortened],
                      "judged": out.judged, "filled": filled, "fields": total,
                      "untouched": out.untouched,
                      "no_verdict": out.no_verdict,
                      "values_applied": out.values_applied,
                      "values_pending": out.pending if out.consumed is None else "",
                      "values_notes": out.values_notes,
                      "values_skeleton": (values_skeleton(out.problems, out.contract, out.role, kept=out.kept)
                                          if out.problems else ""),
                      "problems": [{"path": p.path, "problem": p.text, "fix": p.fix,
                                    "kind": p.kind, "also": list(p.also),
                                    # a blank `--fix` fills itself (the `values_report` rule): the stop-time reader skips it (SC2-38, F-2)
                                    "code_fills": bool(p.kind == "blank" and _code_fills(p.path)),
                                    **({"limit": p.limit} if p.limit else {})}
                                   for p in out.problems]}, ensure_ascii=False, indent=1))
    return 1 if out.problems else 0


def _answer_text(path: Path, out: _Outcome) -> int:
    """The text answer: its lines come in this order (a reader takes the last one as the reason)."""
    for note in out.values_notes:
        print("note: " + note)
    if out.consumed is not None:
        print(f"applied {out.from_sibling} value(s) from {out.consumed.name}; it is now {out.applied_name}")
    elif out.pending and not out.writes and not any(p.path.startswith(out.pending) for p in out.source_problems):
        print(f"pending values from {out.pending} - applied by --fix")
    for line in out.fixed:
        print("filled by code: " + line)
    for row in out.shortened:
        print(f"cut by code: {row['field']} ({len(row['as_written'])} -> {len(row['kept'])} characters); "
              f"the whole text is in `shortened:` of {path.name}")
    for row in out.no_verdict:
        print(f"no verdict on {row['claim']}: {row['reason']}")
    if not out.problems:
        print(f"handoff_check: {out.contract} is complete ({len(out.doc.nodes)} fields checked)")
        return 0
    print(refusal_text(path, out.contract, out.problems, out.role, kept=out.kept))
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--task", default="")
    ap.add_argument("--task-root", default=None)
    ap.add_argument("--fix", action="store_true", help="write in what code can derive")
    ap.add_argument("--shorten", action="store_true",
                    help="with --fix: cut a field over its limit, only when length is the form's sole problem")
    ap.add_argument("--set", action="append", default=[], metavar="PATH=VALUE")
    ap.add_argument("--values", default=None, metavar="FILE|-",
                    help="every field of the role at once: `path: value` lines from a file, or `-` for stdin")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = hooklib.exact_options(ap).parse_args()
    if args.task_root is not None:      # a GIVEN root names an existing story before the form is read or written
        hooklib.story_cli("handoff_check.py", root=args.task_root, key_flag=None)

    path = Path(args.file)
    if args.shorten and not args.fix:
        print("handoff_check: --shorten needs --fix (the driver passes both; a role's own --fix never cuts)")
        return 2
    if not path.is_file():
        print(f"handoff_check: no such file: {path}")
        return 2
    try:
        form_text = path.read_text(encoding="utf-8-sig")      # a BOM is no part of the form (as `form_view` reads it)
    except UnicodeDecodeError:
        # Never `errors="replace"` here: `--fix` would write the replaced text over the role's own file. One plain line
        # for both output modes (as `no such file` above): the callers read the LAST line of stdout as the reason.
        # The form is named by its file name, not its path: the driver keeps the first 200 characters of this line
        # (story_run.py), and the door is its tail. `--dispatch` is part of the door: without it `handoff_init.py` writes
        # the default `-1` form and leaves this one broken.
        print(f"handoff_check: {path.name} is not UTF-8, left untouched. Start it again: "
              f"handoff_init.py --task <T> --stage <S> --role <role> --dispatch {path.stem} --force")
        return 2
    doc = handoff.parse(form_text)
    contract = str(doc.get("contract") or "")
    if not contract:
        print("handoff_check: the form does not name its `contract:` - it was not written by "
              "handoff_init.py. Start it with: handoff_init.py --task <T> --stage <S> --role <role>")
        return 2
    try:
        handoff.spec(contract)
    except FileNotFoundError as exc:
        print(f"handoff_check: {exc}")
        return 2

    if args.values not in (None, "-") and not Path(args.values).is_file():
        print(f"handoff_check: no such values file: {args.values}")      # a NAMED file is never read as an empty one
        return 2

    # The role's words go in first (P1): before `untouched` is measured and before `--fix` derives anything.
    doc, values_applied, source_problems, values_notes, consumed, pending, from_sibling, kept = \
        _apply_sources(path, doc, contract, args)
    role = str(doc.get("header.role") or doc.get("from_role") or "")
    root = Path(args.task_root) if args.task_root is not None else path.parent.parent.parent
    art = Artifacts(root, dispatch=path.stem)
    # Untouched means the ROLE wrote nothing - measured BEFORE `--fix`, or a form the role
    # ignored would read as touched the moment code filled one derivable field for it.
    untouched = filled_share(doc, contract)[0] == 0
    doc, fixed, problems, judged, derived = check(doc, contract, art, fix=args.fix,
                                                  task=args.task, use_judge=not args.no_judge)
    problems = source_problems + problems
    if derived:
        doc = record_derived(doc, derived)
    if judged:
        doc = record_judged(doc, judged)
    shortened = []
    if args.shorten:
        doc, shortened, problems = shorten(doc, problems, path.stem)
        doc = record_shortened(doc, shortened)
    if args.fix or args.set or args.values or judged or derived:
        path.write_text(doc.text(), encoding="utf-8")
    applied_name = f"{path.stem}.values.applied.yaml"
    if consumed is not None:                 # the form holds the words now: the file must never be applied again (P2)
        try:
            os.replace(consumed, path.with_name(applied_name))
        except OSError as exc:
            consumed, pending = None, sibling_values(path).name
            problems.append(Problem(sibling_values(path).name,
                                    f"was applied to the form but could not be renamed to {applied_name} ({exc}); "
                                    "it would be applied again over the form",
                                    f"delete {sibling_values(path).name}"))

    out = _Outcome(contract=contract, doc=doc, role=role, kept=kept, problems=problems, source_problems=source_problems,
                   fixed=fixed, shortened=shortened, judged=judged, untouched=untouched, no_verdict=art.no_verdict,
                   values_applied=values_applied, values_notes=values_notes, consumed=consumed, pending=pending,
                   from_sibling=from_sibling, applied_name=applied_name, writes=bool(args.fix or args.set or args.values))
    return _answer_json(out) if args.json else _answer_text(path, out)


if __name__ == "__main__":
    raise SystemExit(main())
