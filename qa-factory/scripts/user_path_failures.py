#!/usr/bin/env python3
"""Places of the code that swallow a failure a user would meet, and the requests of the flow - a report for the requirements
tester (G2-14) and the test strategist (RN1-6).

A story's code can hold a `catch` that only logs, a `fetch` whose answer is read without looking at its status, or a request
whose answer is never looked at. No requirement names it, so S2 wrote no row for it and nothing ever tested it (CART-1: the cart
said "added" on a failed call; LOCAL-1: a 500 on a product page took the whole cart down). This finds the places by the shapes in
`references/user-path-failure-patterns.json` and says them in the S2 brief. It decides NOTHING: whether a place lies on a path a
user takes, and whether it becomes a `derived` row of the register, is the tester's judgment (AR-2, AR-7); the script writes no
register and refuses nothing. The error direction is toward a match the role throws away, never toward a miss.

The same files give the REQUESTS of the flow (`flow_requests`): every call site of `references/request-call-patterns.json`, one
entry per request (`method`, `url_template`, `source: code`, `path`, `line`, `also_at`), written to `work/flow-requests.json`
(the ONE writer is `write_requests`, the ONE reader `read_requests`) and said in the S3 brief; the S3 exit owes each one a plan row
that fails it (`planning_contract._request_findings`, kinds and oracle in `references/perturbations.json`). A placeholder is named
after the template variable (`{bookId}`), `{*}` only where the source gives no name; the url glob of a request is derived by code
(`request_identity`). An empty list is "not measured: <reason>", never "no requests" (FR-41).

The set of files is not only what S1 named: `address_neighbours` adds the files of the configured checkouts that call an address the set
already calls (the cart page that shows and edits what the add-to-cart page wrote), at most NEIGHBOURS_MAX; the failures of a story with a
diff are unchanged.

  user_path_failures.py --task <TICKET>                  the brief lines, one per line; the full list goes to work/user-path-failures.json
  user_path_failures.py --task <TICKET> --json           the result as data
  user_path_failures.py --task <TICKET> --requests       the request lines; the list goes to work/flow-requests.json (`--json`: as data)

Scope of the failures: the lines the story's diff ADDED (`diff_pass.index`); outside the diff the places `current-code:<file>:<line>`
of the register (`base_slice.parse_place`, the one parser of a place), read in the project or its configured checkouts; and, when the
story has NO diff, every file the context bundle names (`facts[].path`, and the files its notes name), read whole. Paths resolve through
the project's checkouts (`resolve_code_path`, `_locate`), never by the working directory. Exit 0 always: a failure to measure is a line
saying so, never a stop (P1).
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hooklib  # noqa: E402

PATTERNS_FILE = Path(__file__).resolve().parent.parent / "references" / "user-path-failure-patterns.json"
REQUESTS_FILE = Path(__file__).resolve().parent.parent / "references" / "request-call-patterns.json"
PERTURBATIONS_FILE = Path(__file__).resolve().parent.parent / "references" / "perturbations.json"
LIST_FILE = "work/user-path-failures.json"
REQ_LIST_FILE = "work/flow-requests.json"
MAX_LINES = 20             # match lines of the brief; the rest is counted and the full list named
MINIFIED_CHARS = 1000      # one line this long: the file is minified or generated and is not matched line by line
PREFIX = "User-path failures: "
BUNDLE_FILE = "work/context-bundle.json"   # the text of a line only: the file is found through `contract.artifact`
BUNDLE_NAME = "context-bundle.json"
NAMES_SHOWN = 8            # file names one line prints
NAMED_MAX = NAMES_SHOWN    # places or lines a single reason names; the rest is counted (one number with NAMES_SHOWN)
NAME_MATCH_MAX = 5         # files a file name in a fact note may match in one checkout before none is read
NEIGHBOURS_MAX = 8         # files that call the flow's addresses and join the set; the rest is counted in one reason
NEIGHBOUR_SCAN_MAX = 3000  # files of one checkout read for neighbours; the rest is counted in one reason


def load_patterns(path=None):
    """(patterns, problems): the compiled rows of the table and one sentence per defect of it. An unreadable table gives
    ([], [one sentence]); a row that is no object, lacks a field or does not compile is named and skipped, the others stay.
    Never raises."""
    path = Path(path or PATTERNS_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data["patterns"]
        if not isinstance(rows, list):
            raise ValueError("`patterns` is no list")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [], [f"{path.name} cannot be read ({type(exc).__name__}: {str(exc)[:80]})"]
    out, problems = [], []
    for i, row in enumerate(rows):
        name = row.get("id") if isinstance(row, dict) else None
        try:
            window = int(row["window_lines"])
            if window < 1 or not isinstance(name, str) or not name:
                raise ValueError("no id or a window under 1")
            langs = tuple(str(s).lower() for s in row["languages"])
            out.append({"id": name, "why": str(row.get("why") or ""), "languages": langs, "window": window,
                        "start": re.compile(row["start"]), "quiet": re.compile(row["quiet"]),
                        "loud": re.compile(row["loud"])})
        except (KeyError, TypeError, ValueError, re.error) as exc:
            problems.append(f"{path.name} row {name or i} is unusable ({type(exc).__name__}: {str(exc)[:60]})")
    return out, problems


def load_request_table(path=None):
    """(table | None, problems): the compiled request table (`references/request-call-patterns.json`: the languages, the call rows and
    the spelling of a placeholder) and one sentence per defect. An unreadable table or one with no usable call row is
    (None, [sentence]); a row that lacks `id` / `start` or does not compile is named and skipped, the others stay. Never raises."""
    path = Path(path or REQUESTS_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data["calls"], list):
            raise ValueError("no object with a list `calls`")
        table = {"languages": tuple(str(s).lower() for s in data["languages"]),
                 "comment": re.compile(data["comment"]), "non_literal": re.compile(data["non_literal"]),
                 "interpolation": re.compile(data["interpolation"]), "interpolation_open": str(data["interpolation_open"]),
                 "name_of": re.compile(data["name_of"]), "named_as": str(data["named_as"]), "unnamed_as": str(data["unnamed_as"]),
                 "concat_tail": re.compile(data["concat_tail"]), "query_mark": str(data["query_mark"]),
                 "glob_match": re.compile(data["glob_match"]), "glob_as": str(data["glob_as"]), "calls": []}
        if not table["interpolation_open"]:
            raise ValueError("`interpolation_open` is empty")
    except (OSError, ValueError, KeyError, TypeError, re.error) as exc:
        return None, [f"{path.name} cannot be read ({type(exc).__name__}: {str(exc)[:80]})"]
    problems = []
    for i, row in enumerate(data["calls"]):
        name = row.get("id") if isinstance(row, dict) else None
        try:
            if not isinstance(name, str) or not name:
                raise ValueError("no id")
            call = {"id": name, "start": re.compile(row["start"]), "window": max(1, int(row.get("window_lines") or 1)),
                    "bare_method": str(row.get("bare_method") or "").upper()}
            for key in ("url_accept", "method_in_window", "bare_call"):
                call[key] = re.compile(row[key]) if row.get(key) else None
            table["calls"].append(call)
        except (KeyError, TypeError, ValueError, re.error) as exc:
            problems.append(f"{path.name} row {name or i} is unusable ({type(exc).__name__}: {str(exc)[:60]})")
    if not table["calls"]:
        return None, problems + [f"{path.name} has no usable call row"]
    return table, problems


def perturbation_axis(axis_id, path=None):
    """(kind ids | None, oracle, problem) of one axis of `references/perturbations.json`: the ONE reader of that table (AR-13). `problem`
    says why it cannot be read (then kinds is None). Never raises."""
    path = Path(path or PERTURBATIONS_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        axis = next(a for a in data["axes"] if isinstance(a, dict) and a.get("id") == axis_id)
        kinds = [str(k["id"]) for k in axis["kinds"] if isinstance(k, dict) and k.get("id")]
        oracle = " ".join(str(axis["oracle"]).split())
        if not kinds or not oracle:
            raise ValueError("no kind or no oracle")
        return kinds, oracle, ""
    except Exception as exc:  # noqa: BLE001 - a table that cannot be read is named, never raised
        return None, "", f"{path.name} cannot be read ({type(exc).__name__}: {str(exc)[:80]})"


def failure_axis(path=None):
    """(kind ids | None, oracle, problem) of the `request_failure` axis: the failures every request of the flow is owed and what must
    stay true while one happens (the S3 view of `perturbation_axis`)."""
    return perturbation_axis("request_failure", path)


def perturbation_axes(path=None):
    """(axes, problem): every axis of the table, in file order, for the S6 brief: `[{id, applies_to, subject, kinds: [{id, steps,
    fail_request, why}], oracle}]` (`subject` is the words for what a field or action axis is taken over, "" for none). An axis the table cannot give whole is left out and named in `problem` (one sentence, `; `-joined); an
    unreadable table is `([], "<file> cannot be read (...)")`. Never raises."""
    path = Path(path or PERTURBATIONS_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data["axes"]
        if not isinstance(rows, list):
            raise ValueError("`axes` is no list")
    except Exception as exc:  # noqa: BLE001
        return [], f"{path.name} cannot be read ({type(exc).__name__}: {str(exc)[:80]})"
    axes, bad = [], []
    for i, row in enumerate(rows):
        name = row.get("id") if isinstance(row, dict) else None
        try:
            kinds = [{"id": str(k["id"]), "steps": [str(s) for s in k.get("steps") or []], "fail_request": str(k.get("fail_request") or ""),
                      "why": " ".join(str(k.get("why") or "").split())}
                     for k in row["kinds"] if isinstance(k, dict) and k.get("id")]
            oracle = " ".join(str(row["oracle"]).split())
            if not isinstance(name, str) or not name or not kinds or not oracle:
                raise ValueError("no id, kind or oracle")
            axes.append({"id": name, "applies_to": str(row.get("applies_to") or ""), "kinds": kinds, "oracle": oracle,
                         "subject": " ".join(str(row.get("subject") or "").split())})
        except Exception as exc:  # noqa: BLE001
            bad.append(f"axis {name or i} is unusable ({type(exc).__name__}: {str(exc)[:60]})")
    return axes, "; ".join(bad)


def _scan(patterns, file, lines, found, seen, starts=None):
    """Match `lines` ({number: text}) of one file; `starts` limits the lines a match may START on. A hit is one `start` line with
    `quiet` and no `loud` in its window."""
    suffix = Path(file).suffix.lower()
    for pat in patterns:
        if suffix not in pat["languages"]:
            continue
        for n in sorted(lines if starts is None else starts):
            if not pat["start"].search(lines[n]) or (pat["id"], file, n) in seen:
                continue
            window = [lines[k] for k in range(n, n + pat["window"]) if k in lines]
            if any(pat["quiet"].search(t) for t in window) and not any(pat["loud"].search(t) for t in window):
                seen.add((pat["id"], file, n))
                found.append({"pattern": pat["id"], "file": file, "line": n, "why": pat["why"],
                              "text": lines[n].strip()[:120]})


def _minified(file, lines) -> bool:
    return ".min." in Path(file).name.lower() or any(len(t) > MINIFIED_CHARS for t in lines.values())


def _named(items, shown=NAMED_MAX) -> str:
    """`a, b, c` of at most `shown` items, then ` (and K more)`."""
    items = list(items)
    return ", ".join(str(i) for i in items[:shown]) + (f" (and {len(items) - shown} more)" if len(items) > shown else "")


def _diff_files(task_root):
    """({path: (lines, starts)}, production files only), or None when the task has no diff. `lines` = {number: text} of every line the
    hunks SHOW (added and context: a `loud` word or the `catch` itself may be a line the diff did not touch); `starts` = the numbers of the
    lines of the hunks that hold an added line, the only lines a match may START on (an added log call inside an old `catch`)."""
    import diff_pass as DP
    import test_files as TF
    got = DP.index(task_root / "work")
    files = got.get("files") or []
    if not files and not got.get("refusals"):
        return None
    out: dict = {}
    for rec in files:
        if rec.get("deleted") or rec.get("refused") or rec.get("path_uncertain") or TF.file_kind(rec["path"]) != "production":
            continue
        shown, starts = out.setdefault(rec["path"], ({}, set()))
        for hunk in rec.get("hunks") or []:
            body, here = hunk.get("body"), {}
            if isinstance(body, list) and body:                 # the raw hunk: context lines are in it, numbered from `new_start`
                n = int(hunk.get("new_start") or 0)
                for raw in body:
                    sign = raw[:1]
                    if sign in ("-", "\\"):
                        continue
                    here[n] = (sign, raw[1:])
                    n += 1
            else:
                here = {n: (sign, text) for n, sign, text in hunk.get("lines") or [] if sign == "+"}
            if any(sign == "+" for sign, _ in here.values()):
                starts.update(here)
            shown.update({n: text for n, (_, text) in here.items()})
    return out


def _register_places(task_root):
    """[observable] of the register's rows that start `current-code:`, [] when there is no register (None: no file at all)."""
    import contract
    path = contract.artifact(task_root, "requirements-register.md")
    if not Path(path).is_file():
        return None
    return [r["observable"] for r in contract.register_rows(contract.read_text(path))
            if (r.get("observable") or "").startswith("current-code:")]


def _file_lines(path):
    """{number: text} of a file (a BOM and `\\r` dropped), or None when it cannot be read."""
    try:
        text = Path(path).read_bytes().decode("utf-8-sig", "replace").split("\n")
    except OSError:
        return None
    return {i + 1: t.rstrip("\r") for i, t in enumerate(text)}


def _new_bundle(defect="") -> dict:
    return {"files": [], "unreadable": [], "not_production": 0, "collisions": [], "defect": defect,
            "facts": [], "source_revisions": []}


def _revision_repo_ids(entries) -> list:
    """The repository ids the bundle's `source_revisions` name (`repo_id`, else `repo`), once each."""
    return list(dict.fromkeys(str(r.get("repo_id") or r.get("repo")) for r in entries if isinstance(r, dict) and (r.get("repo_id") or r.get("repo"))))


def _bundle_roots(bundle, project) -> list:
    """Where a path of the bundle is looked for, in order: the project, then the checkout of each `source_revisions` entry
    (`handoff_check.implementation_checkout`, axis 10). A checkout that is not configured here adds no root: the path it would
    have found is named as not readable, so the loss is seen."""
    import handoff_check as HC
    import regression_scope
    roots = [Path(project).resolve()]
    entries = bundle.get("source_revisions")
    cfg = regression_scope.project_config(project) if isinstance(entries, list) and entries else {}
    for entry in entries if isinstance(entries, list) else []:
        found = HC.implementation_checkout(entry, cfg, project, BUNDLE_FILE)[0]
        if found is not None and found.resolve() not in roots:
            roots.append(found.resolve())
    return roots


def _locate(text, roots) -> list:
    """The files `text` names that lie under a root, resolved; nothing outside every root is ever returned (a `..`, a NUL, an
    absolute path elsewhere, a link that leaves)."""
    if not text or "\x00" in text:
        return []
    named = Path(text)
    if named.anchor:
        options = [named]
    elif ".." in named.parts:
        return []
    else:
        options = [root / named for root in roots]
    out = []
    for option in options:
        try:
            option = option.resolve()
            if option.is_file() and any(root in option.parents for root in roots) and option not in out:
                out.append(option)
        except (OSError, ValueError):
            continue
    return out


def _bundle_files(task_root, project):
    """None when the story has no context bundle; else {files: [(label, path)], unreadable: [path text], not_production: n,
    collisions: [label], defect: text, facts: [fact], source_revisions: [entry]}. The bundle is read through `contract.artifact` +
    `hooklib.read_json`; only `facts[].path` (a non-blank string; `file:line` and `\\` forms accepted) and `source_revisions` are read
    (`facts` and `source_revisions` are handed on for the files the notes name, `_note_files`). A label is RELATIVE to the first
    root that holds the file (the project first), never a machine path (AR-4)."""
    import contract
    import test_files
    where = Path(contract.artifact(task_root, BUNDLE_NAME))
    if not where.is_file():
        return None
    out = _new_bundle()
    bundle = hooklib.read_json(where, None, kind=dict)
    if bundle is None:
        out["defect"] = f"{BUNDLE_FILE} cannot be read, a defect of the factory"
        return out
    facts = bundle.get("facts")
    out["facts"] = facts if isinstance(facts, list) else []
    out["source_revisions"] = bundle.get("source_revisions") if isinstance(bundle.get("source_revisions"), list) else []
    roots = _bundle_roots(bundle, project)
    chosen: dict = {}
    for fact in facts if isinstance(facts, list) else []:
        raw = fact.get("path") if isinstance(fact, dict) else None
        text = raw.strip().replace("\\", "/") if isinstance(raw, str) else ""
        if not text:
            continue
        cut = re.match(r"^(.+):(\d+)$", text)
        found = _locate(text, roots) or (_locate(cut.group(1), roots) if cut else [])
        if not found:        # a path that starts with a configured repository id (`App/src/x.ts`): the checkout that id names (RN1-5)
            rel = cut.group(1) if cut else text
            target, _why = resolve_code_path(project, rel, _revision_repo_ids(out["source_revisions"]))
            if target is not None:
                if rel not in chosen:
                    chosen[rel] = target.resolve()
                elif chosen[rel] != target.resolve() and rel not in out["collisions"]:
                    out["collisions"].append(rel)
                continue
        if not found and text not in out["unreadable"]:
            out["unreadable"].append(text)
        for path in found:
            label = next(path.relative_to(root).as_posix() for root in roots if root in path.parents)
            if label not in chosen:
                chosen[label] = path
            elif chosen[label] != path and label not in out["collisions"]:
                out["collisions"].append(label)
    for label, path in sorted(chosen.items()):
        if test_files.file_kind(label) == "production":
            out["files"].append((label, path))
        else:
            out["not_production"] += 1
    return out


def _bundle_reasons(bundle, added, places) -> list:
    """The `unmeasured` lines of the bundle branch. `bundle` is None when it was not read (a diff) or the story has none: the
    absent-bundle line is only for the story with no diff whose register has places (the narrowing is named)."""
    if bundle is None:
        if added is None and places:
            return [f"{BUNDLE_FILE} is absent: only the register's places were read"]
        return []
    out = [bundle["defect"]] if bundle["defect"] else []
    names = bundle["unreadable"]
    if names:
        out.append(f"{len(names)} file(s) the context bundle names are not readable files of the project or its checkouts: "
                   + ", ".join(names[:NAMES_SHOWN]) + (f" and {len(names) - NAMES_SHOWN} more" if len(names) > NAMES_SHOWN else ""))
    if bundle["collisions"]:
        out.append("the same path is in more than one checkout, only the first was read: " + ", ".join(bundle["collisions"][:NAMES_SHOWN]))
    if not bundle["files"] and bundle["not_production"]:
        out.append(f"the context bundle names no production file ({bundle['not_production']} test, docs, config or generated)")
    return out


def _project_of(task_root) -> Path:
    """The project the story belongs to, by the resolver every other reader of the story uses (`runtime_paths.project_for_task`),
    not by the process's working directory; the cwd project when the story's own place proves none."""
    try:
        import runtime_paths
        return Path(runtime_paths.project_for_task(task_root))
    except Exception:  # noqa: BLE001 - a courtesy report: the old resolver is the fallback
        return Path(hooklib.project_root())


# --- paths: through the configured checkouts, never by the working directory -------------------------------------------

def _checkout_of(repo_id, cfg, project):
    """The folder of a configured repository id (`handoff_check.implementation_checkout`, the one survivor), or None."""
    import handoff_check
    folder, _why = handoff_check.implementation_checkout({"repo_id": repo_id}, cfg, project, "")
    return folder


def resolve_code_path(project, rel, repo_ids=()):
    """`(file, "")` or `(None, reason)`: the readable file a repository-relative path names. `rel` must be canonical
    (`base_slice._repo_path`). The first hit of: (1) its first segment is a configured repository id: that checkout / the rest;
    (2) the project / `rel`; (3) each id of `repo_ids` (the repositories the story's own record names): its checkout / `rel`. The
    config is read by `regression_scope.project_config` (AR-13). A candidate must be a file inside its base: nothing outside the
    project or a configured checkout is ever read (AR-4). A missing checkout is named, never guessed."""
    import base_slice
    import regression_scope
    if base_slice._repo_path(rel) is None:
        return None, f"{rel} is not a canonical repository path"
    project = Path(project)
    cfg = regression_scope.project_config(project)
    first, _, rest = rel.partition("/")
    candidates = []
    if rest:
        folder = _checkout_of(first, cfg, project)
        if folder is not None:
            candidates.append((folder, rest))
    candidates.append((project, rel))
    for repo_id in repo_ids:
        folder = _checkout_of(repo_id, cfg, project) if repo_id else None
        if folder is not None:
            candidates.append((folder, rel))
    for base, sub in candidates:
        try:
            target = base / sub
            if target.is_file() and base.resolve() in target.resolve().parents:
                return target, ""
        except OSError:
            continue
    return None, f"{rel} is not a readable file of the project or a configured checkout"


def _production(path) -> bool:
    import test_files as TF
    return TF.file_kind(path) == "production"


def _add(files, path, lines, starts, via):
    """Put one file into the set: the first spelling stays; a second scan of a file the diff already shows (a register place in a changed
    file) rides along as `also`, so no scan the story had before is lost."""
    entry = {"lines": lines, "starts": starts, "via": via}
    if path in files:
        files[path].setdefault("also", []).append(entry)
    else:
        files[path] = entry


def _places(places, project, reach, out):
    """The register's `current-code:` places: each resolved through the checkouts; its file read whole, `starts` = the cited line, `reach`
    lines before and after (the windows read the whole file: the span's edge cuts none)."""
    import base_slice
    spans: dict = {}
    for text in places:
        place = base_slice.parse_place(text)
        if place.problem or place.kind != "current-code":
            out["unmeasured"].append(f"the place `{text[:60]}` cannot be parsed")
            continue
        target, why = resolve_code_path(project, place.path)
        if target is None:
            out["unmeasured"].append(f"the place {place.path}:{place.line} is not a readable file of the checkout ({why})")
            continue
        spans.setdefault(place.path, (target, []))[1].append(place.line)
    for file in sorted(spans):
        target, cited = spans[file]
        lines = _file_lines(target)
        if lines is None:
            out["unmeasured"].append(f"{file} cannot be read")
        elif _production(file):
            wanted = {k for n in cited for k in range(max(1, n - reach), n + reach + 1) if k in lines}
            _add(out["files"], file, lines, wanted, "register")


def _extensions() -> list:
    """The file extensions of BOTH tables (built from the data, no list here), longest first."""
    langs = {s for p in load_patterns()[0] for s in p["languages"]}
    table = load_request_table()[0]
    langs |= set(table["languages"]) if table else set()
    return sorted({s.lstrip(".") for s in langs if s.lstrip(".")}, key=lambda s: (-len(s), s))


def _repo_ids(cfg) -> list:
    """The ids of the configured repositories (`implementation_repos[].repo_id`, `code_repos[].name`), once each, in config order."""
    ids = []
    for key, field in (("implementation_repos", "repo_id"), ("code_repos", "name")):
        ids += [str(r.get(field)).strip() for r in cfg.get(key) or [] if isinstance(r, dict) and str(r.get(field) or "").strip()]
    return list(dict.fromkeys(ids))


def _note_files(facts, project, repo_ids, out):
    """F1: file names the facts' `note` / `value` texts carry (`called from LoginPage.tsx:36`) are files of the flow the scout named only in
    prose. Each name is looked up by `git ls-files` in each configured checkout: 1..NAME_MATCH_MAX matches are all read; more are
    named and none read; none is named. The error direction is an extra file, never a silent miss."""
    import regression_scope
    import test_novelty
    exts = _extensions()
    if not exts:
        return
    token = re.compile(r"(?<![\w./\[\]@-])([\w.\[\]@-]+(?:/[\w.\[\]@-]+)*\.(?:" + "|".join(re.escape(e) for e in exts)
                       + r"))(?::\d+)?(?![\w])")
    names = []
    for fact in facts:
        for field in ("note", "value"):
            text = fact.get(field) if isinstance(fact, dict) else None
            if isinstance(text, str):
                names += token.findall(text)
    names = list(dict.fromkeys(names))
    if not names:
        return
    unmeasured, files = out["unmeasured"], out["files"]
    cfg = regression_scope.project_config(project)
    listing = {}
    ids = _repo_ids(cfg)
    for repo_id in ids:
        folder = _checkout_of(repo_id, cfg, project)
        if folder is None:
            unmeasured.append(f"{repo_id} has no readable checkout: file names in context-bundle.json notes not resolved")
            continue
        code, raw = test_novelty._git(folder, ["ls-files", "-z"])
        if code != 0:
            unmeasured.append(f"{repo_id} is not a git checkout: file names in context-bundle.json notes not resolved")
        else:
            listing[repo_id] = [p for p in raw.decode("utf-8", "replace").split("\0") if p]
    for name in names:
        found, too_many = [], []
        for repo_id, tracked in listing.items():
            hit = [p for p in tracked if p == name or p.endswith("/" + name)]
            if len(hit) > NAME_MATCH_MAX:
                too_many.append((repo_id, len(hit)))
            else:
                found += [f"{repo_id}/{p}" for p in hit]
        unmeasured += [f"{name} named in context-bundle.json matches {k} files of {repo_id}: not read" for repo_id, k in too_many]
        if not found and not too_many and (listing or not ids):
            unmeasured.append(f"{name} named in context-bundle.json is no file of a configured checkout")
        for key in found:
            if key in files or not _production(key):
                continue
            target, _why = resolve_code_path(project, key, repo_ids)
            lines = _file_lines(target) if target is not None else None
            if lines is not None:
                _add(files, key, lines, None, "fact-note")


def _stem(template) -> str:
    """The address prefix of a url template: cut at the first placeholder, a trailing `/` or `?` dropped. A stem of fewer than two
    non-empty `/` segments (`/api`, `{*}`) names everything and is `""` (it adds nothing)."""
    stem = template.split("{", 1)[0].rstrip("/?")
    return stem if len([s for s in stem.split("/") if s]) >= 2 else ""


def address_neighbours(task_root, project, files, table) -> dict:
    """{"files": {path: entry}, "unmeasured": [reason]}: the files that call the addresses the set `files` already calls (the pages that
    READ and CHANGE what the flow writes). The stems are the url templates of the call sites of `files` (`_stem`); a production file
    of a configured git checkout, of the table's languages, not minified and not in `files`, whose call site starts with a stem, is a
    neighbour: at most NEIGHBOURS_MAX (most matching sites first, then path), the rest named in ONE reason; at most NEIGHBOUR_SCAN_MAX
    files of a checkout are read, the rest counted in ONE reason; a checkout that is no git checkout and a file that cannot be read are
    named. No stem: nothing, no reason. Nothing is decided here: the files reach the failure scan and the request list, and the role
    plans them or homes them with a reason. The error direction is an extra file, never a silent miss. No address or name is held in
    code: the stems come from `request-call-patterns.json` matches (AR-1)."""
    import regression_scope
    import test_novelty
    out = {"files": {}, "unmeasured": []}
    stems: list = []
    for file, entry in files.items():
        if Path(file).suffix.lower() not in table["languages"] or _minified(file, entry["lines"]):
            continue
        for scan in [entry["lines"]] + [more["lines"] for more in entry.get("also", [])]:
            for _n, _method_, template in _sites(scan, table)[0]:
                stem = _stem(template)
                if stem and stem not in stems:
                    stems.append(stem)
    if not stems:
        return out
    cfg = regression_scope.project_config(project)
    found, unreadable = [], []
    for repo_id in _repo_ids(cfg):
        folder = _checkout_of(repo_id, cfg, project)
        if folder is None:
            out["unmeasured"].append(f"{repo_id} has no readable checkout: neighbours of the flow not looked for")
            continue
        code, raw = test_novelty._git(folder, ["ls-files", "-z"])
        if code != 0:
            out["unmeasured"].append(f"{repo_id} is not a git checkout: neighbours of the flow not looked for")
            continue
        tracked = sorted(p for p in raw.decode("utf-8", "replace").split("\0")
                         if p and Path(p).suffix.lower() in table["languages"] and _production(f"{repo_id}/{p}"))
        if len(tracked) > NEIGHBOUR_SCAN_MAX:
            out["unmeasured"].append(f"{repo_id}: {len(tracked) - NEIGHBOUR_SCAN_MAX} files not scanned for neighbours of the flow")
        for p in tracked[:NEIGHBOUR_SCAN_MAX]:
            key = f"{repo_id}/{p}"
            if key in files or p in files:
                continue
            target = folder / p
            try:
                inside = folder.resolve() in target.resolve().parents
            except OSError:
                inside = False
            scan = _file_lines(target) if inside else None
            if scan is None:
                unreadable.append(key)
            elif not _minified(key, scan):
                hits = sum(1 for _n, _method_, template in _sites(scan, table)[0] if any(template.startswith(s) for s in stems))
                if hits:
                    found.append((-hits, key, scan))
    if unreadable:
        out["unmeasured"].append(f"{len(unreadable)} file(s) cannot be read, not looked at for neighbours of the flow: {_named(unreadable)}")
    found.sort(key=lambda item: (item[0], item[1]))
    for _neg, key, scan in found[:NEIGHBOURS_MAX]:
        out["files"][key] = {"lines": scan, "starts": None, "via": "neighbour"}
    if len(found) > NEIGHBOURS_MAX:
        out["unmeasured"].append(f"{len(found) - NEIGHBOURS_MAX} more files call the flow's addresses ({_named(stems)}): not read")
    return out


def code_files(task_root, project, with_bundle=None, reach=1, table_file=None) -> dict:
    """The story's code files, the ONE set both consumers read (the failures of `find` and the requests of `flow_requests`, AR-15):
    `{"files": {path: {"lines": {n: text}, "starts": set | None, "via": diff|register|bundle|fact-note|neighbour[, "also": [...]]}},
    "unmeasured": [reason], "had_diff": bool, "had_register": bool, "had_bundle": bool}`. Never raises.

    diff: the lines the hunks show, `starts` the added ones; register: the `current-code:` places, the whole file, `starts` the cited
    line +/- `reach`; bundle: the files S1 recorded (`facts[].path`, read by `_bundle_files`, and the file names of the notes), whole,
    `starts` None; neighbour: the files that call an address the set calls (`address_neighbours`), read with the bundle. `with_bundle`
    True / False / None (the bundle only when the story has NO diff: a story with a diff keeps its S2 as calibrated). Every file is
    production by `test_files.file_kind`; a path key is the spelling of its source, never absolute."""
    out = {"files": {}, "unmeasured": [], "had_diff": False, "had_register": False, "had_bundle": False}
    project = Path(project)
    try:
        added = _diff_files(Path(task_root))
    except Exception as exc:  # noqa: BLE001 - the report is a courtesy
        added = None
        out["unmeasured"].append(f"the diff cannot be read ({type(exc).__name__}: {str(exc)[:80]}), a defect of the factory")
    out["had_diff"] = added is not None
    for file in sorted(added or {}):
        out["files"][file] = {"lines": added[file][0], "starts": added[file][1], "via": "diff"}
    try:
        places = _register_places(Path(task_root))
    except Exception as exc:  # noqa: BLE001
        places = None
        out["unmeasured"].append(f"the register cannot be read ({type(exc).__name__}: {str(exc)[:80]}), a defect of the factory")
    out["had_register"] = places is not None
    if places is not None:
        _places(places, project, reach, out)
    if (not out["had_diff"]) if with_bundle is None else with_bundle:
        try:
            bundle = _bundle_files(Path(task_root), project)
        except Exception as exc:  # noqa: BLE001
            bundle = _new_bundle(f"the context bundle cannot be read ({type(exc).__name__}: {str(exc)[:80]}), a defect of the factory")
        out["had_bundle"] = bundle is not None
        for label, path in (bundle or {"files": []})["files"]:
            body = _file_lines(path)
            if body is None:
                out["unmeasured"].append(f"{label} cannot be read")
            else:
                _add(out["files"], label, body, None, "bundle")
        try:                    # the files the notes name (the facts come from the same bundle read)
            if bundle is not None and not bundle["defect"]:
                _note_files(bundle["facts"], project, _revision_repo_ids(bundle["source_revisions"]), out)
        except Exception as exc:  # noqa: BLE001
            out["unmeasured"].append(f"file names in context-bundle.json notes cannot be looked for ({type(exc).__name__}: {str(exc)[:80]}), a defect of the factory")
        out["unmeasured"] += _bundle_reasons(bundle, added, places)
        try:                    # the pages that read and change what the flow writes join it (a diff story's failures never get here)
            table, _problems = load_request_table(table_file)
            if table is not None and out["files"]:
                got = address_neighbours(Path(task_root), project, out["files"], table)
                for key, entry in got["files"].items():
                    _add(out["files"], key, entry["lines"], entry["starts"], entry["via"])
                out["unmeasured"] += got["unmeasured"]
        except Exception as exc:  # noqa: BLE001
            out["unmeasured"].append(f"neighbours of the flow cannot be looked for ({type(exc).__name__}: {str(exc)[:80]}), a defect of the factory")
    return out


# --- the failures -------------------------------------------------------------------------------------------------------

def find(task_root, project_root=None, patterns_file=None) -> dict:
    """{"matches": [{pattern, file, line, why, text}], "unmeasured": [reason], "checked": [file]}; never raises.

    The files are `code_files` (the diff; the register's places; and, with NO diff, the files of `context-bundle.json`).
    `unmeasured` is what was NOT looked at and why, so "no match" is never read where "not looked" is the fact (FR-41):
    a defect of the table, a language with no pattern, a minified file, a place `current-code:` that cannot be read, the
    places outside the diff on a first S2 (the register does not exist yet), and - without a diff - the context bundle: it
    cannot be read, it names files that are not readable files of the project or its checkouts, it names no production file,
    it is absent while the register has places; `no code` only when there is no diff, no register place and the bundle names
    no file at all. The bundle is read only when the diff is absent (or unreadable): a diff keeps its own scope."""
    task_root = Path(task_root)
    result = {"matches": [], "unmeasured": [], "checked": []}
    patterns, problems = load_patterns(patterns_file)
    for text in problems:
        result["unmeasured"].append(f"{text}, a defect of the factory")
        print(f"user_path_failures: {text}", file=sys.stderr)
    if not patterns:
        return result
    langs = {s for p in patterns for s in p["languages"]}
    seen: set = set()
    no_pattern: set = set()

    def take(file, lines, starts=None, count=True):
        suffix = Path(file).suffix.lower()
        if suffix not in langs:
            no_pattern.add(suffix or "(no extension)")
        elif _minified(file, lines):
            if count:
                result["unmeasured"].append(f"{file} looks minified or generated (a line over {MINIFIED_CHARS} characters)")
        else:
            if count:
                result["checked"].append(file)
            _scan(patterns, file, lines, result["matches"], seen, starts)

    project = Path(project_root) if project_root else _project_of(task_root)
    got = code_files(task_root, project, None, max(p["window"] for p in patterns))
    result["unmeasured"] += got["unmeasured"]
    for file, entry in got["files"].items():
        take(file, entry["lines"], entry["starts"])
        for more in entry.get("also", []):
            take(file, more["lines"], more["starts"], count=False)
    if got["had_diff"] and not got["had_register"]:
        result["unmeasured"].append("the places outside the diff: the register does not exist yet (the first S2)")
    if no_pattern:
        result["unmeasured"].append("no pattern for " + ", ".join(sorted(no_pattern)))
    if not result["checked"] and not result["unmeasured"]:
        result["unmeasured"].append("no code")      # no diff, no register place, no file the bundle names: nothing to look at
    return result


def write_list(task_root, result) -> None:
    """The FULL result to `work/user-path-failures.json`: the one writer of that file. A failed write is stderr, not a stop."""
    path = Path(task_root) / LIST_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"user_path_failures: {LIST_FILE} not written ({exc})", file=sys.stderr)


def lines(result) -> list:
    """The brief lines of a result: one per match up to MAX_LINES, then `N more, the list is in work/user-path-failures.json`
    (the cut is named, the file is whole); a `no match, checked: ...` line only when something was looked at and nothing
    matched; one `not measured: ...` line per thing not looked at."""
    out = [f"{PREFIX}{m['pattern']} {m['file']}:{m['line']} - {m['why']}" for m in result["matches"][:MAX_LINES]]
    rest = len(result["matches"]) - MAX_LINES
    if rest > 0:
        out.append(f"{PREFIX}{rest} more, the list is in {LIST_FILE}")
    if not result["matches"] and result["checked"]:
        out.append(f"{PREFIX}no match, checked: {', '.join(result['checked'][:NAMES_SHOWN])}"
                   + (f" and {len(result['checked']) - NAMES_SHOWN} more"
                   if len(result["checked"]) > NAMES_SHOWN else ""))
    out += [f"{PREFIX}not measured: {reason}" for reason in result["unmeasured"]]
    return out


# --- the requests of the flow -------------------------------------------------------------------------------------------

def _placeholder(expr, table) -> str:
    """The placeholder of one interpolated expression: `{<name>}` when it is a dotted name (the LAST identifier: `item.bookId` ->
    `{bookId}`), else the unnamed form (a call, an operator, a ternary)."""
    named = table["name_of"].match(expr or "")
    return table["named_as"].replace("<name>", named.group("name")) if named else table["unnamed_as"]


def _template(url, rest, table):
    """The url template of one call site, or None when it is no literal address: interpolations become placeholders; an interpolation
    left unclosed (a nested template the line cannot show whole) cuts the template there and becomes the unnamed placeholder; the
    concatenated operand that follows the literal becomes one; the query string is cut; what still holds an interpolation mark is no
    literal address."""
    unnamed, opening = table["unnamed_as"], table["interpolation_open"]
    text = table["interpolation"].sub(lambda m: _placeholder(m.group("expr"), table), url)
    cut = text.find(opening)
    if cut >= 0:
        text = text[:cut] + unnamed
    else:
        tail = table["concat_tail"].match(rest)
        if tail:
            text += _placeholder(tail.group("expr").strip(), table)
    text = text.split(table["query_mark"], 1)[0]
    return None if not text or opening[:1] in text else text


def _method(call, hit, rest, number, lines, table):
    """The verb of one call site: the group `method`; else the row's `method_in_window` in the rest of the call line and the next
    `window - 1` lines, STOPPING before a line that holds the next call (its method is its own); else the row's `bare_method` when the
    call carries no options; else None (an unknown verb is never printed as GET, FR-41)."""
    if "method" in call["start"].groupindex:
        return hit.group("method").upper()
    wanted = call["method_in_window"]
    if wanted:
        found = wanted.search(rest)
        k = number + 1
        while not found and k < number + call["window"]:
            text = lines.get(k)
            if text is None:
                break
            if not table["comment"].match(text):
                if any(c["start"].search(text) for c in table["calls"]):
                    break
                found = wanted.search(text)
            k += 1
        if found:
            return found.group("method").upper()
    if call["bare_call"] and call["bare_method"] and call["bare_call"].match(lines[number], hit.start()):
        return call["bare_method"]
    return None


def _sites(lines, table):
    """([(line, method, template)], [lines whose address is not a literal]) of one file."""
    sites, unseen = [], []
    for n in sorted(lines):
        text = lines[n]
        if table["comment"].match(text):
            continue
        hits = sorted(((m.start(), call, m) for call in table["calls"] for m in call["start"].finditer(text)), key=lambda h: h[0])
        taken = False
        for i, (_, call, hit) in enumerate(hits):
            end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
            template = _template(hit.group("url"), text[hit.end():max(end, hit.end())], table)
            if template is not None and call["url_accept"] and not call["url_accept"].search(template):
                continue                                    # `map.get('key')`: no request
            taken = True
            if template is None:
                unseen.append(n)
            else:
                sites.append((n, _method(call, hit, text[hit.end():max(end, hit.end())], n, lines, table), template))
        if not taken and table["non_literal"].search(text):
            unseen.append(n)
    return sites, sorted(set(unseen))


def request_key(entry) -> str:
    """The ONE spelling of a request in the brief, the plan fields and the closure: `<METHOD|ANY> <url_template>`."""
    return f"{entry.get('method') or 'ANY'} {entry['url_template']}"


def request_identity(key_or_entry, table=None) -> tuple:
    """`(method or ANY, glob)` of a request: the url template with every placeholder replaced by the table's glob mark. Two spellings of one
    endpoint (`{bookId}` and `{id}`) share an identity. The glob is an identity (a PATH glob, compared across stages), NOT what the
    runner's `fail_request` takes: a browser route matches the whole URL, so the route form is `request_route_glob`. Never raises: a
    key the table cannot read is its own identity."""
    key = request_key(key_or_entry) if isinstance(key_or_entry, dict) else str(key_or_entry)
    try:
        table = table or load_request_table()[0]
        method, _, url = key.strip().partition(" ")
        return method.upper(), table["glob_match"].sub(table["glob_as"], url.strip())
    except Exception:  # noqa: BLE001
        return key, key


ROUTE_QUERY_TAIL = "{,\\?*}"      # a browser route matches the whole URL: this tail takes the request with or without a query string


def request_route_glob(key_or_entry, table=None) -> tuple:
    """`(glob, "")` or `(None, why)`: the ONE builder of the pattern the runner's `fail_request` (a browser `page.route`) takes for a
    request of the flow. The route matches the WHOLE URL, so a path glob (`/api/orders`) never fires: the pattern gets a `**` prefix, no
    query string of its own, and a tail that takes the URL with or without one. A variable host prefix (`${API}/x`, `{base}/x`) is
    dropped (any host); a literal host stays as written (the runner then holds it to the stand hosts). An empty path, or a path that is
    only wildcards, has NO pattern (`None` + the reason): a bare `**` would fail every request of the page. Never raises."""
    try:
        table = table or load_request_table()[0]
        if isinstance(key_or_entry, dict):
            url = str(key_or_entry.get("url_template") or "")
        else:
            url = str(key_or_entry).strip().partition(" ")[2]
        url = table["glob_match"].sub(table["glob_as"], url.strip())
        url = url.split("#", 1)[0]
        host = ""
        if "://" in url:
            scheme, _, rest = url.partition("://")
            authority, slash, path = rest.partition("/")
            path = slash + path
            if "*" not in authority and "$" not in authority:
                host = f"{scheme}://{authority}"
        elif not url.startswith("/") and "/" in url.split("?", 1)[0] and any(c in url.split("/", 1)[0] for c in "*$"):
            path = "/" + url.split("/", 1)[1]
        else:
            path = url if url.startswith("/") or not url else "/" + url
        path = path.split("?", 1)[0]
        if not path.strip("*$/ "):
            return None, f"the address `{url or '(empty)'}` has no path to match: a pattern of every request would fail the whole page"
        return (host + path if host else "**" + path) + ROUTE_QUERY_TAIL, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"the address could not be read ({type(exc).__name__})"


def flow_requests(task_root, project_root=None, table_file=None) -> dict:
    """{"requests": [entry], "unmeasured": [reason], "checked": [file]}: every request the code of the flow makes (the files of
    `code_files`, the bundle always read). An entry is `{method, url_template, source: "code", path, line, also_at}`, one per
    `(method, glob)`, at its first site in (path, line) order; the other sites are `also_at`. An empty list always carries a reason (FR-41)."""
    task_root = Path(task_root)
    result = {"requests": [], "unmeasured": [], "checked": []}
    table, problems = load_request_table(table_file)
    for text in problems:
        result["unmeasured"].append(f"{text}, a defect of the factory")
        print(f"user_path_failures: {text}", file=sys.stderr)
    if table is None:
        return result
    project = Path(project_root) if project_root else _project_of(task_root)
    got = code_files(task_root, project, True, table_file=table_file)
    result["unmeasured"] += got["unmeasured"]
    no_pattern: set = set()
    found: dict = {}
    for file, entry in got["files"].items():
        scans = [entry["lines"]] + [more["lines"] for more in entry.get("also", [])]
        suffix = Path(file).suffix.lower()
        if suffix not in table["languages"]:
            no_pattern.add(suffix or "(no extension)")
            continue
        if _minified(file, entry["lines"]):
            result["unmeasured"].append(f"{file} looks minified or generated (a line over {MINIFIED_CHARS} characters)")
            continue
        result["checked"].append(file)
        unseen = set()
        for lines_of in scans:
            sites, no_literal = _sites(lines_of, table)
            unseen.update(no_literal)
            for n, method, template in sites:
                found.setdefault(request_identity(f"{method or 'ANY'} {template}", table), {}).setdefault((file, n), (method, template))
        if unseen:
            result["unmeasured"].append(f"{file}: {len(unseen)} call site(s) whose address is not a literal: {_named(sorted(unseen))}")
    if no_pattern:
        result["unmeasured"].append("no request pattern for " + ", ".join(sorted(no_pattern)))
    for sites in found.values():
        order = sorted(sites)
        (path, line), (method, template) = order[0], sites[order[0]]
        result["requests"].append({"method": method, "url_template": template, "source": "code", "path": path, "line": line,
                                   "also_at": [f"{p}:{n}" for p, n in order[1:]]})
    result["requests"].sort(key=lambda r: (r["path"], r["line"]))
    if not result["requests"]:
        if not result["checked"] and not result["unmeasured"]:
            result["unmeasured"].append("no code")
        elif result["checked"]:
            result["unmeasured"].append(f"no call site of {Path(table_file or REQUESTS_FILE).name} matched in the files read "
                                        f"({len(result['checked'])} checked); requests made another way are not seen")
    return result


def write_requests(task_root, result) -> None:
    """The FULL result to `work/flow-requests.json`: the ONE writer of that file. A failed write is stderr, not a stop."""
    path = Path(task_root) / REQ_LIST_FILE
    body = {"schema_version": 1, "requests": result.get("requests", []), "unmeasured": result.get("unmeasured", []),
            "checked": result.get("checked", [])}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"user_path_failures: {REQ_LIST_FILE} not written ({exc})", file=sys.stderr)


def read_requests(task_root) -> tuple:
    """`(requests, "")`, or `(None, "")` when the file is absent (a story planned before it existed), or `(None, why)` when it cannot be
    read or is no object with a list `requests`: the ONE reader of `work/flow-requests.json`."""
    data, why = _flow_file(task_root)
    return (data["requests"] if data is not None else None), why


def _flow_file(task_root) -> tuple:
    """`(the file's object, "")`, `(None, "")` when the file is absent, `(None, why)` when it is unusable: the ONE open of
    `work/flow-requests.json` (`read_requests` and `exploration_cells` both read through it)."""
    path = Path(task_root) / REQ_LIST_FILE
    if not path.is_file():
        return None, ""
    data = hooklib.read_json(path, None, errors=Exception, kind=dict)
    if not isinstance(data, dict) or not isinstance(data.get("requests"), list):
        return None, f"{REQ_LIST_FILE} is not a JSON object with a list `requests`"
    return data, ""


def exploration_cells(task_root, perturbations=None) -> dict:
    """What the S6 brief prints as `Exploration cells:` (data, no judgment): `{"cells", "unmeasured", "axes", "problem"}`. A cell of a
    request is `{axis, request, glob, kind, at}` for every request of `work/flow-requests.json` (in `(path, line)` order) and every
    kind of every axis that `applies_to` `requests` (in the table's order); the glob is what `fail_request` takes (`request_route_glob`;
    a request with no pattern has no cell and a reason in `unmeasured`).
    The axes of fields and of actions have no cells: the role names them on the page. `unmeasured` is one reason per refusal to
    count, never an empty list that reads as "no requests": no file, an unreadable file, or a list the file leaves empty (with
    the file's own reasons, or a sentence that it gave none). `problem` is `perturbation_axes`' sentence. Never raises."""
    result = {"cells": [], "unmeasured": [], "axes": [], "problem": ""}
    result["axes"], result["problem"] = perturbation_axes(perturbations)
    try:
        data, why = _flow_file(task_root)
        if data is None:
            result["unmeasured"].append(why or f"{REQ_LIST_FILE} does not exist (S3 did not write it)")
            return result
        requests = [r for r in data["requests"] if isinstance(r, dict) and r.get("url_template")]
        requests.sort(key=lambda r: (str(r.get("path") or ""), int(r.get("line") or 0)))
        if not requests:
            reasons = [str(x) for x in data.get("unmeasured") or [] if str(x).strip()]
            result["unmeasured"] += reasons or [f"{REQ_LIST_FILE} lists no request and gives no reason"]
        for axis in result["axes"]:
            if axis["applies_to"] != "requests":
                continue
            for r in requests:
                glob, why = request_route_glob(r)
                if glob is None:
                    gap = f"{request_key(r)} ({r.get('path')}:{r.get('line')}): no cell - {why}"
                    if gap not in result["unmeasured"]:
                        result["unmeasured"].append(gap)
                    continue
                for kind in axis["kinds"]:
                    result["cells"].append({"axis": axis["id"], "request": request_key(r), "glob": glob,
                                            "kind": kind["id"], "at": f"{r.get('path')}:{r.get('line')}"})
    except Exception as exc:  # noqa: BLE001 - a brief line is a courtesy: the defect is named, not raised
        result["cells"] = []
        result["unmeasured"].append(f"{REQ_LIST_FILE} could not be read ({type(exc).__name__}: {str(exc)[:80]})")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--task", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--requests", action="store_true", help="the requests of the flow instead of the failures")
    args = ap.parse_args()
    try:
        task_root = hooklib.story_root(args.task, "user_path_failures")
    except ValueError as exc:
        print(f"user_path_failures: {exc}", file=sys.stderr)
        return 0
    if args.requests:
        import brief_pack
        found = flow_requests(task_root)
        write_requests(task_root, found)
        print(json.dumps(found, indent=2) if args.json else "\n".join(brief_pack.request_lines(found, args.task)))
        return 0
    result = find(task_root)
    write_list(task_root, result)
    print(json.dumps(result, indent=2) if args.json else "\n".join(lines(result)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
