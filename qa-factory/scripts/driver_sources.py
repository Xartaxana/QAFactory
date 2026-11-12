"""driver_sources.py - Driver members and names homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import re
import subprocess
from pathlib import Path
from source_inventory import normalize_url
import adapter_forms as AF
import ticket_light as TL
from driver_core import Refusal, _now, _read_json
from driver_dispatch import S1_GAP_RE, S1_REVIEW_RE


S1_DISPATCH_RE = r"exit gate for (S1-qa-scout-\d+)"

# Who wrote a review comment is a fact in the payload; what it is worth is not. GitLab marks a
# service account `bot`, and this instance's CI posts as `auto_*_vcs` — on !1522 those accounts
# wrote most of the 101 comments, each a pipeline log, and inlining them made a 1.7 MB "digest".
# Code never decides what matters; it decides only what fits in one file. A comment over this
# size moves to a file of its own with its address left behind — a pasted build log and a
# decisive review argument look identical by size, and telling them apart is the reader's work.
BIG_COMMENT_BYTES = 8000


def _is_bot(author: dict) -> bool:
    """Only what the server itself declares. Guessing a service account from its name (`auto_`,
    `_vcs`, `ci`) works on one instance and misnames a person on the next, and the factory runs on
    projects nobody here has seen. Where the server says nothing, size decides instead - and a
    byte is the same fact on every instance."""
    return (author or {}).get("bot") is True


def _note_lines(notes: list) -> list:
    out = []
    for note in notes:
        who = ((note.get("author") or {}).get("name") or "?")
        when = str(note.get("created_at") or "")[:10]
        out += [f"**{who}**" + (f", {when}" if when else "") + ":", "",
                str(note.get("body") or "").strip(), ""]
    return out


class DriverSources:
    def report_gap_class_problem(self) -> None:
        """C2-9 (L-2 V-5 b): after S1 is closed, a record of the person's answers about KINDS of gap that cannot be read does not
        stop the story (G3: what was closed stays closed), and it is not silent either (FR-41): ONE finding of the factory
        (`defect_found`), once per problem text (`state.gap_class_defect`). Read from the controller's own projection, the place
        that first holds it; before S1 is closed the question itself carries the line and no finding is owed."""
        state = self.controller_state()
        closed = ((state.get("stages") or {}).get("S1") or {}).get("status") == "completed"
        problem = str((state.get("source_completeness") or {}).get("gap_class_problem") or "")
        if not closed or not problem or self.state.get("gap_class_defect") == problem:
            return
        self.state["gap_class_defect"] = problem
        self.save_state()
        self.file_defect(self.boundary, f"owner: factory — {problem}. S1 is closed, so every gap point a kind of gap closed stays "
                                        "closed (nothing is asked again), but the record is damaged: restore "
                                        "work/gap-classes.json (or references/source-causes.json) and say so in the report")

    @staticmethod
    def s1_exit_gate(text: str) -> str:
        """The scout dispatch an S1 exit-gate refusal names, or '' when the text is not one."""
        m = re.search(S1_DISPATCH_RE, text or "")
        return m.group(1) if m else ""

    def _answer_s1_gap(self, words: str, asked: dict, qtext: str, stage: str, dispatch: str) -> bool:
        """The executor of an answer to the `s1_gap` question (C2-9). Code reads TOKENS and a structural sign (a fence), never a
        phrase (FR-12). True when the answer was taken; False sends it down the road it had (free words, the conductor).
        POSITION INVARIANT: called only for kind `s1_gap`, before the `offered` branch - the question carries no `offered`, and an
        answer to a question of another kind never reaches here. The sources and kinds are the ones the QUESTION named
        (`asked.sources` / `asked.classes`), not whatever the inventory holds now (I4: a kind is written only for what was shown)."""
        inventory = self.task_root / "work" / "source-inventory.json"
        sources, classes = list(asked.get("sources") or []), list(asked.get("classes") or [])
        token = self.s0_normalize(words)
        inv_rel = f"qa-factory/artifacts/{self.task}/work/source-inventory.json"
        if not inventory.is_file():
            return False
        if token in ("skip all like these", "not needed") and not sources:
            print("s1_gap: the question named no source the factory can record the word for; the conductor reads it")
            return False
        if token == "skip all like these" and classes:
            return self._accept_gap_kinds(words, sources, classes, qtext, inv_rel)
        if token == "not needed":
            return self.record_gaps(qtext, words, ids=sources)
        if "```" in (words or ""):
            pasted = self.record_pasted(set(sources), words)
            if pasted:
                self.answer_row("S1 material supplied by the person: " + "; ".join(pasted)[:1500], "", what="the note of the material you supplied")
                return True
        return False

    def _accept_gap_kinds(self, words: str, sources: list, classes: list, qtext: str, inv_rel: str) -> bool:
        """`skip all like these`: the person's word for the KINDS the question offered (one `accept-gap --cause` call), then for the
        points of the named sources that have no cause at all (one `--point` call per source). The first call writes the kinds; a
        refusal of it leaves nothing recorded. A refusal of a later call leaves the kinds ON DISK, and the text says so."""
        import source_inventory as SI
        shown = " ".join(line.strip() for line in qtext.splitlines() if line.startswith("- "))[:1500]
        code, recorded = self.py("ticket_adapter.py", "accept-gap", "--output", inv_rel, "--cause", ",".join(classes),
                                 "--shown-text", shown, *self.words_args(words, "s1gap"))
        if code:
            # remains: the person's own question comes back with the refusal's words, nothing was accepted (FR-59)
            raise self.held_question("Your word could not be recorded as the acceptance, so nothing was accepted.", recorded)
        inv = SI.load_inventory(self.task_root / "work" / "source-inventory.json")
        summary = SI.completeness(inv, **SI.class_kwargs(self.task_root))
        for item in inv.get("sources") or []:
            sid = item.get("source_id")
            open_ids = (summary.get("open_points") or {}).get(sid) or []
            bare = [p["id"] for p in SI.gap_points(item)
                    if p["class"] == SI.POINT_GAP and not SI.point_cause(item, p) and p["id"] in open_ids]
            if sid not in sources or not bare:
                continue
            code, out = self.py("ticket_adapter.py", "accept-gap", "--output", inv_rel, "--source-id", sid,
                                "--point", ",".join(bare), *self.words_args(words, "s1gap"))
            if code:
                # remains: the person's own question comes back with the refusal's words; the kinds are on disk and say so (FR-59)
                raise self.held_question(
                    f"Your word was recorded for the kinds of gap ({', '.join(classes)}) and covers every later one of them, "
                    "but not for the other points of this question.", recorded.strip() + "\n" + out)
        self.answer_row(f"S1 gaps accepted by kind ({', '.join(classes)}): ", words.strip(), what="your word accepting the gaps by kind")
        return True

    def record_gaps(self, text: str, words: str, ids: list | None = None) -> bool:
        """Every source named gets the person's words as its acceptance, by code. The names are `ids` (the sources a question
        `asked`) or, for the exit-gate refusal text of `record_s1`, the ids the gate printed in `text`. False when nothing is named or
        the inventory is missing.

        Content the person pasted is material, not an acceptance: it is recorded first, and only
        what is still missing afterwards becomes an accepted gap. The order matters — a run that
        accepted the gap first would file a source as unreachable in the same breath as receiving
        its content. A fenced answer is content (a structural sign): it is never ALSO an acceptance, and no phrase of the
        person's makes it one (FR-12)."""
        inventory = self.task_root / "work" / "source-inventory.json"
        ids = sorted(set(ids if ids is not None else re.findall(S1_GAP_RE, text or "", re.IGNORECASE)))
        if not ids or not inventory.is_file():
            return False
        pasted = self.record_pasted(set(ids), words)
        if "```" in (words or ""):
            # POSITION INVARIANT (C1-7a, F-1): on the FENCE, not on `pasted`. They answered with the content, not with a decision: a
            # fenced answer is never ALSO an acceptance, whatever `record_pasted` managed to record (no block read, none recorded:
            # the conductor reads the words, `False`).
            if not pasted:
                return False
            self.answer_row("S1 material supplied by the person: " + "; ".join(pasted)[:1500], "", what="the note of the material you supplied")
            return True
        code, out = self.py("ticket_adapter.py", "accept-gap", "--output",
                            f"qa-factory/artifacts/{self.task}/work/source-inventory.json",
                            "--source-id", ",".join(ids), *self.words_args(words, "s1gap"))
        if code:
            print(f"accept-gap failed (exit {code}): {out[-300:]}")
            return False
        self.answer_row(f"S1 gap accepted for {', '.join(ids)}: ", words.strip(), what="your word accepting the gap")
        return True

    def record_s1(self, text: str, words: str) -> bool:
        """An S1 exit-gate refusal answered by the person: the review and the gaps it names
        are recorded by code; the scout resumes on the words. False when the text names
        nothing code can record (the conductor takes over)."""
        did = False
        if re.search(S1_REVIEW_RE, text or "", re.IGNORECASE):
            did = self.record_review(words) or did
        if re.search(S1_GAP_RE, text or "", re.IGNORECASE):
            did = self.record_gaps(text, words) or did
        if not did and self.s1_exit_gate(text) and (self.task_root / "work" / "source-inventory.json").is_file():
            # Nothing left for the person to record: the refusal is the scout's own work
            # (receipts, the form). The words go to the scout as they are.
            self.answer_row("S1: ", words.strip(), what="your answer at the source review")
            did = True
        return did

    def excluded_heads(self) -> list:
        """The head commits of what the person left out before the run (B-231, C2): the full ids
        `source_exclusions.py` holds for a merge request (`target.head_sha`) or a commit word
        (`target.sha`). [] with no list or none resolved: then `git_route` skips nothing.

        A record that exists and cannot be read raises a refusal that names the file: the git door
        must never run past the person's word because the word could not be read."""
        import source_exclusions as SE
        try:
            live = SE.live(self.task_root)
        except SE.ExclusionRecordError as exc:
            raise Refusal(str(exc))
        heads = []
        for exclusion in live:
            target = exclusion.get("target") or {}
            # A null head (the lookup failed) is no head: `str(None)` here once gave the word 'None', and
            # `git_route` then ran a pointless rev-parse of it for every commit it listed.
            value = target.get("head_sha") if target.get("kind") == "mr" else target.get("sha")
            sha = value.strip() if isinstance(value, str) else ""
            if sha and sha not in heads:
                heads.append(sha)
        return heads

    @staticmethod
    def only_from_excluded_head(checkout: Path, commit: str, heads: list) -> bool:
        """Is `commit` reachable from an excluded head and from nothing else (two `git` calls per head).

        INVARIANT: in doubt it is NOT skipped. A head this checkout does not hold, a commit it does not
        hold, an abbreviated id that resolves to nothing, a timeout: all answer False, so the route reads
        what it read before. A commit that a branch such as `main` also carries is not the excluded
        request's own change (an older commit of the same ticket prefix is an ancestor of every branch
        cut after it), so a ref whose tip is not an excluded head makes the answer False."""
        def git(*args):
            return subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=30)
        try:
            full = []
            for head in heads:
                done = git("rev-parse", "--verify", "--quiet", f"{head}^{{commit}}")
                if done.returncode == 0 and done.stdout.strip():
                    full.append(done.stdout.strip())
            if not full or not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit or ""):
                return False
            for head in full:
                if git("merge-base", "--is-ancestor", commit, head).returncode != 0:
                    continue
                tips = git("for-each-ref", "--contains", commit, "--format=%(objectname)")
                found = [line.strip() for line in tips.stdout.splitlines() if line.strip()]
                if tips.returncode == 0 and found and all(tip in full for tip in found):
                    return True
        except (OSError, subprocess.TimeoutExpired):
            return False
        return False

    def git_route(self, url: str, rel: str) -> str:
        """Route 2 for a merge request: the local checkout of the same project. `refs/merge-requests`
        exist only while an MR is open (githost prunes them on merge — 3758 and 3890 are gone while
        the listing runs to 4346), but a merged MR's own commits are in the history, so the CHANGE is
        readable offline. What this route cannot give is the description and the discussions, which
        is why what it produces is recorded `partial` and never `read`. Returns a note naming the
        commits, or "" when this route has nothing either."""
        project = str(url).split("/-/merge_requests/")[0].rsplit("/", 1)[-1]
        # The ticket's PREFIX is the project's own key form (`adapter_forms`, B-405): `MY_PROJ-12` is `MY_PROJ`,
        # and a prefix-less form (a numeric story on GitHub issues) has none. With none, the commits are not searched
        # by `--grep=<prefix>-` (an empty prefix would read `--grep=-`, every commit with a hyphen); the merge-request
        # ref is still asked, and the line says what was skipped.
        form = AF.key_form(self.config, floor=True)
        prefix = (AF.prefix_of(self.task, form)
                  if AF.is_key(self.task, self.config) and not self.s0_is_local() else None)    # `LOCAL-` is no commit prefix (SS1-14 m5)
        if prefix is None:
            print(f"local git route: task {self.task!r} has no project prefix in its key form ({form.source}), "
                  "so the commits are not searched by prefix; only the merge-request ref is asked")
        heads = self.excluded_heads()
        wanted = self.list_tail(project)
        for repo in self.config.get("implementation_repos") or []:
            identity = str(repo.get("remote_identity") or "")
            local = str(repo.get("local_path") or "")
            # The entry is selected by WHOLE tail, as `repo_of_project` does (B-412, critic t-554 F2): by substring
            # `testproject1` was "in" `.../testproject1-ui`, and the first such entry answered for the wrong project.
            if not local or not wanted or wanted != self.list_tail(identity):
                continue
            # B-412: the checkout may be a folder inside a repository (a monorepo); `want` keeps an enclosing
            # repository of ANOTHER project from being asked.
            checkout, _top, why = self.checkout_for(repo, want=wanted)
            if not checkout:
                if why:
                    print(f"local git route: {why}")
                continue
            # The number comes from the regex's own digits: the URL may still carry a trailing `.` or `**`.
            found = re.search(r"/merge_requests/(\d+)", str(url))
            iid = found.group(1) if found else str(url).rstrip("/").rsplit("/", 1)[-1]
            for query in (["ls-remote", "origin", f"refs/merge-requests/{iid}/head"],
                          *([["log", "--all", "--format=%H%x09%s", f"--grep={prefix}-", "--max-count=20"]]
                            if prefix else [])):
                done = subprocess.run(["git", "-C", str(checkout), *query], capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=120)
                if done.returncode or not done.stdout.strip():
                    continue
                # A commit that only an excluded head carries is the excluded merge request's own change,
                # reached by the git door instead of the API one (t-172 C2: live testproject1-ui keeps MR 1924
                # under a branch name with no "1924" in it, and `--grep=TP1-` lists its commit).
                lines, skipped = [], []
                for line in done.stdout.strip().splitlines():
                    sha = line.split("\t")[0].strip()
                    if heads and self.only_from_excluded_head(checkout, sha, heads):
                        skipped.append(sha)
                    else:
                        lines.append(line)
                for sha in skipped:
                    print(f"local git route: {sha[:12]} is left out: only a merge request you asked me not to "
                          "read carries it")
                if not lines:
                    continue
                done.stdout = "\n".join(lines)
                target = self.task_root / "work" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                body = [f"# Local git route for {url}", f"checkout: {local}", f"query: git {' '.join(query)}",
                        "", done.stdout.strip(), ""]
                shas = [line.split("\t")[0] for line in done.stdout.strip().splitlines()][:4]
                for sha in shas:
                    show = subprocess.run(["git", "-C", str(checkout), "show", "--stat", "--patch", sha],
                                          capture_output=True, text=True, encoding="utf-8",
                                          errors="replace", timeout=180)
                    body += [f"## git show {sha}", show.stdout[:200000], ""]
                target.write_text("\n".join(body), encoding="utf-8")
                return (f"the local checkout {local} carries the change as "
                        + ", ".join(sha[:9] for sha in shas))
        return ""

    def close_vcs_gaps(self, errors: list) -> bool:
        """A merge-request URL that arrived as ticket material is not a web page for a role to
        open: the factory has an authenticated read-only collector for it (`vcs_evidence.py`), and
        code runs it, not the role.

        TP1-13797, 26.09: four MR pages of the precedent ticket were filed `unavailable` with
        the reason "superseded closed precedent MR; content already captured from ticket text" and
        offered to the person as a gap to accept — while every one of them collects clean through
        the API (16 notes, 16 discussions, 9 diffs, revision pinned). The collector was named only
        for the implementation MR in the S0 phase file; a URL that arrives in a comment goes to
        `external_media`, where a role has two verbs (`read --local-ref`, `unavailable --reason`)
        and no web tool. Nothing between the URL and the script that reads it was code. This is it.
        True when something was collected, so the caller re-reads the gate instead of asking."""
        inventory_rel = f"qa-factory/artifacts/{self.task}/work/source-inventory.json"
        inventory = _read_json(self.task_root / "work" / "source-inventory.json")
        ids = {found for error in errors for found in re.findall(S1_GAP_RE, error or "", re.IGNORECASE)}
        if not ids:
            # The gate complains about material in more than one wording, and only the "unaccepted
            # gap" one carries a source id: "materials not inspected" names none. Material that is
            # merely `pending` is the normal case — four merge requests of the precedent ticket sat
            # `pending` while the ladder waited for a gap to be declared first. With no id to go on,
            # every source is fair game: collecting is idempotent and skips what is already read.
            ids = {str(source.get("source_id")) for source in inventory.get("sources") or []}
        collected = False
        for source in inventory.get("sources") or []:
            if source.get("source_id") not in ids:
                continue
            block = (source.get("materials") or {}).get("external_media") or {}
            for entry in block.get("items") or []:
                url = str(entry.get("url") or "")
                # The inventory keeps the URL as the comment wrote it (markdown escaping and all);
                # the collector needs the real one, and the record is updated by the stored one.
                target = normalize_url(url)
                # `excluded`: the person said before the run not to read it (B-231). This skip sits before
                # `vcs_evidence`, and it holds in the "every source is fair game" branch too.
                if entry.get("status") in ("read", "excluded"):
                    continue
                # B-405: what the link IS comes from `ticket_light.classify_url` (reference-kinds.json), against its PATH
                # only: a merge-request path inside a query string is no request. The number is group 2 of the kind's own
                # rule and must END the path or be followed by `/` (`/-/merge_requests/5/diffs` is request 5, `.../5a` is
                # none). A pull request is not sent to `vcs_evidence`, a GitLab collector: one line says why and the item
                # stays pending. Every error direction is toward "not a request" - never a link collected without a receipt.
                try:
                    kind, _host, found = TL.classify_url(target)
                except TL.TableError as exc:
                    print(f"merge requests are not collected: {exc}")
                    return collected
                if kind not in TL.MR_KINDS or not found or (found.end(2) < len(found.string)
                                                            and found.string[found.end(2)] != "/"):
                    continue
                if kind == "pull_request":
                    print(f"{target} is a pull request: vcs_evidence reads GitLab merge requests only, so it is left "
                          "pending for the person (a GitHub collector is not part of the factory yet)")
                    continue
                iid = found.group(2)
                rel = f"sources/{source['source_id']}/mr-{iid}.json"
                (self.task_root / "work" / rel).parent.mkdir(parents=True, exist_ok=True)
                code, out = self.py("vcs_evidence.py", "--url", target, "--output",
                                    f"qa-factory/artifacts/{self.task}/work/{rel}")
                receipt = _read_json(self.task_root / "work" / rel)
                status, reason = "read", ""
                if code or receipt.get("status") != "read":
                    # Route 1 (the authenticated API) did not answer. Route 2 is the local checkout:
                    # it carries the change, never the discussion, so what it gives is `partial`.
                    cause = str(receipt.get("error") or "")
                    print(f"vcs_evidence could not collect {url}: {cause or out[-200:]}")
                    note = self.git_route(target, f"sources/{source['source_id']}/mr-{iid}-git.md")
                    if not note:
                        # C2-9 (N9): the API did not answer and no local route has the change. When the collector's receipt
                        # carries a code the factory's table knows, the CODE records the verdict, with the receipt as its
                        # carrier (`--probe-ref`) - a role's copy of it is no carrier. A code the table does not know, or no
                        # receipt at all, writes nothing: the item stays pending, the road it had (the unknown is asked).
                        if self.record_unreachable(source, entry, url, rel, cause, inventory_rel):
                            collected = collected or entry.get("probe_code") != cause or entry.get("status") != "unavailable"
                        continue
                    rel = f"sources/{source['source_id']}/mr-{iid}-git.md"
                    status = "partial"
                    reason = (f"partial_route: the API route answered `{cause}`; {note}, which is the "
                              "change only — the MR description and its discussions are not in it")
                    print(f"local git route: {url} -> work/{rel} ({note})")
                elif not receipt.get("complete", True):
                    status = "partial"
                    reason = (f"partial_route: vcs_evidence collected the MR but marked it incomplete "
                              f"({receipt.get('error') or 'complete: false'})")
                code, out = self.py("ticket_adapter.py", "inspect", "--output", inventory_rel,
                                    "--source-id", source["source_id"], "--media-url", url,
                                    "--inspection-status", status, "--local-ref", rel,
                                    *(("--reason", reason) if reason else ()))
                if code:
                    print(f"collected {url} but recording it failed: {out[-200:]}")
                    continue
                digest = self.material_digest(rel, receipt) if status == "read" else ""
                self.state.setdefault("collected", {}).setdefault(str(source["source_id"]), []).append(
                    f"{url} -> work/{rel}" + (f" (+ {digest})" if digest else ""))
                print(f"collected by code ({status}): {url} -> work/{rel}"
                      + (f" (revision {str(receipt.get('revision'))[:12]}, "
                         f"{len(receipt.get('discussions') or [])} discussions"
                         + (f"; digest {digest}" if digest else "") + ")" if status == "read" else ""))
                collected = True
        return collected

    def record_unreachable(self, source: dict, entry: dict, url: str, rel: str, code: str, inventory_rel: str) -> bool:
        """The code writes `unavailable` for a merge request the collector could not reach, with the cause the table of
        references/source-causes.json gives the collector's code and the receipt as `--probe-ref`. False (nothing written) for a
        code the table does not know or none: the item stays pending and is asked - the unknown is never a default."""
        import source_inventory as SI
        try:
            cause = SI.cause_table()["vcs_codes"].get(code) if code else None
        except ValueError:
            cause = None
        if not cause:
            print(f"vcs_evidence answered {code or 'nothing'}, which the factory's table does not know: the item stays pending")
            return False
        done, out = self.py("ticket_adapter.py", "inspect", "--output", inventory_rel, "--source-id", source["source_id"],
                            "--media-url", url, "--inspection-status", "unavailable",
                            "--reason", f"{cause}: vcs_evidence answered {code}", "--probe-ref", rel)
        if done:
            print(f"vcs_evidence answered {code} for {url} but recording it failed: {out[-200:]}")
            return False
        return True

    def record_pasted(self, ids: set, words: str) -> list:
        """The person's own last route: they read the material themselves and paste what matters.
        Text inside a fenced block of their answer becomes material of the source, recorded with
        `provenance: person_pasted` — the record says where it came from instead of implying the
        factory fetched it. Returns one line per file recorded."""
        blocks = [b.strip() for b in re.findall(r"```[a-zA-Z0-9_-]*\n(.*?)```", words or "", re.S) if b.strip()]
        if not blocks:
            return []
        inventory_rel = f"qa-factory/artifacts/{self.task}/work/source-inventory.json"
        inventory = _read_json(self.task_root / "work" / "source-inventory.json")
        done, failed, taken = [], [], set()
        for source in inventory.get("sources") or []:
            if source.get("source_id") not in ids:
                continue
            open_items = [i for i in ((source.get("materials") or {}).get("external_media") or {}).get("items") or []
                          if i.get("status") in {"pending", "unavailable", "partial", None}]
            for index, block in enumerate(blocks, start=1):
                named = [i for i in open_items if str(i.get("url") or "") and str(i["url"]) in (words or "")]
                target_item = named[0] if len(named) == 1 else (open_items[0] if len(open_items) == 1 else None)
                if not target_item:
                    continue
                rel = f"sources/{source['source_id']}/pasted-{index}.md"
                path = self.task_root / "work" / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"<!-- pasted by the person on {_now()} for {target_item['url']} -->\n\n"
                                + block + "\n", encoding="utf-8")
                code, out = self.py("ticket_adapter.py", "inspect", "--output", inventory_rel,
                                    "--source-id", source["source_id"], "--media-url", target_item["url"],
                                    "--inspection-status", "read", "--local-ref", rel,
                                    "--provenance", "person_pasted")
                if code:
                    print(f"recording pasted material failed: {out[-200:]}")
                    failed.append((index, f"{target_item['url']} ({out.strip()[-200:] or 'the tool said nothing'})"))
                    continue
                done.append(f"{target_item['url']} <- work/{rel} (pasted by the person)")
                taken.add(index)
                open_items = [i for i in open_items if i is not target_item]
        for line in done:
            print(f"material from the person: {line}")
        # Q1 (C1-7a, F-1): a block that was not recorded - its `inspect` failed, or no open item could be named for it - is the person's own
        # question back, with what IS recorded and what is not. POSITION INVARIANT: inside this function, before it returns to
        # `record_gaps` / `_answer_s1_gap`, so a block that was not recorded never reaches `accept-gap` as if it were a decision.
        lost = [index for index in range(1, len(blocks) + 1) if index not in taken]
        if lost:
            # remains: the person's own question comes back with what is written and what is not (FR-10, the t-366 F2 pattern)
            raise self.held_question(
                f"{len(lost)} of the {len(blocks)} text(s) you pasted could not be recorded, so nothing was recorded for "
                f"{'it' if len(lost) == 1 else 'them'}; your answer was not taken as accepting the gap. "
                + (f"Recorded: {'; '.join(done)}. " if done else "Nothing of what you pasted was recorded. ")
                + "Say which source each text is for (name its link), or answer in your own words.",
                "\n".join(tool for _index, tool in failed) or "no open item of the named sources could be matched to the text")
        return done

    def material_digest(self, rel: str, receipt: dict) -> str:
        """A merge request's own words, unpacked from its receipt — not summarised.

        The API receipt is evidence and it is huge: the precedent's four came back at 79 KB, 183 KB,
        965 KB and **3.8 MB**, nearly all of it diff hunks. A brief that names a 3.8 MB JSON has
        delivered nothing — the guard refuses a whole read at 30 KB and the role would slice blind.

        What code does here is EXTRACTION, never judgement: the title, the state, the branches, the
        revision, the description exactly as its author wrote it, every human review comment in
        full, and the list of files the change touched. Nothing is shortened and nothing is chosen
        as important — choosing is the reading role's work, and the hunks stay one line away in the
        evidence file this names. (The first version of this method capped comments at 25 and cut
        each at 400 characters; on a merge request with 101 discussions that cap is code deciding
        which review thread matters, which is exactly what it must not do.)"""
        meta = receipt.get("metadata") or {}
        if not meta:
            return ""
        target = self.task_root / "work" / rel.replace(".json", ".md")
        lines = [f"# {meta.get('title') or 'merge request'}", "",
                 f"- url: {receipt.get('url')}",
                 f"- state: {meta.get('state')}, merged_at: {meta.get('merged_at')}",
                 f"- branches: {meta.get('source_branch')} -> {meta.get('target_branch')}",
                 f"- revision: {receipt.get('revision')}",
                 f"- evidence (full, machine-readable): work/{rel}", "",
                 "## What its author wrote", "", str(meta.get("description") or "(no description)").strip(), ""]
        notes = [n for n in (receipt.get("notes") or []) if isinstance(n, dict) and not n.get("system")]
        people = [n for n in notes if not _is_bot(n.get("author") or {})]
        machines = [n for n in notes if _is_bot(n.get("author") or {})]
        if people:
            lines += [f"## Review, {len(people)} comment(s) by people, each in full", ""]
            kept, moved = [], []
            for index, note in enumerate(people, start=1):
                body = str(note.get("body") or "")
                if len(body) <= BIG_COMMENT_BYTES:
                    kept.append(note)
                    continue
                # Too big to inline is not the same as unimportant, and code cannot tell the
                # difference: a pasted build log and a decisive design argument look alike by
                # size. So the rule is size alone, and what moves leaves its address behind.
                side = self.task_root / "work" / rel.replace(".json", f"-comment-{index}.md")
                side.write_text("\n".join(_note_lines([note])) + "\n", encoding="utf-8")
                who = ((note.get("author") or {}).get("name") or "?")
                moved.append(f"- **{who}**, {len(body) // 1024} KB — in full: "
                             f"work/{side.relative_to(self.task_root / 'work').as_posix()} "
                             f"(first line: {body.strip().splitlines()[0][:120] if body.strip() else ''})")
            lines += _note_lines(kept)
            if moved:
                lines += [f"### {len(moved)} comment(s) too large to inline — moved whole, "
                          "not shortened and not judged", ""] + moved + [""]
        if machines:
            # Not judged as unimportant — moved, and said so. On !1522 the 101 "comments" were
            # mostly a CI bot pasting pipeline logs: keeping them inline made the digest 1.7 MB,
            # which is the 3.8 MB problem again. The split is by WHO wrote it, which is a fact in
            # the payload, not an opinion about what matters.
            side = self.task_root / "work" / rel.replace(".json", "-machine.md")
            side.write_text(f"# Machine comments on {receipt.get('url')}\n\n"
                            + "\n".join(_note_lines(machines)) + "\n", encoding="utf-8")
            lines += [f"## {len(machines)} comment(s) by machine accounts (CI, bots)", "",
                      f"Moved, not dropped — all of them, in full: work/{side.relative_to(self.task_root / 'work').as_posix()}", ""]
        diffs = [d for d in (receipt.get("diffs") or []) if isinstance(d, dict)]
        if diffs:
            lines += [f"## Files it touched ({len(diffs)})", ""]
            lines += [f"- {d.get('new_path') or d.get('old_path')}" for d in diffs]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return f"work/{rel.replace('.json', '.md')} ({target.stat().st_size // 1024} KB)"

    GAP_TEXT_MAX = 6000     # bytes of the body of the `s1_gap` question; the rest of the list is in the details file (t-720 F-2)

    def s1_gap_lines(self, ids: list, inventory: dict, summary: dict) -> tuple:
        """`(source_lines, access, sources, causes)` of the points the person is ASKED about: the gap points of the named sources
        that the summary still holds open (a point closed by a word, a kind, or by the factory's own verdict is not one of them).
        `sources` / `causes` are ALL the asked ones, shown or not - the tokens close exactly what was named (C2-9)."""
        import source_inventory as SI
        out, access, sources, causes = [], [], [], set()
        for item in inventory.get("sources") or []:
            sid = item.get("source_id")
            if sid not in ids:
                continue
            key = str(item.get("canonical_ref") or "").rsplit("/", 1)[-1]
            open_ids = set((summary.get("open_points") or {}).get(sid) or [])
            gone = []
            for point in SI.gap_points(item):
                if point["id"] not in open_ids or point["class"] != SI.POINT_GAP:
                    continue
                cause = SI.point_cause(item, point)
                if cause:
                    causes.add(cause)
                if point["id"] == "source:unavailable":
                    gone.append(f"the ticket itself ({item.get('exclusion_or_error') or 'unavailable'})")
                    continue
                if point["kind"] == "block":
                    gone.append(point["id"].split(":")[0])
                    continue
                entry = SI._point_row(item, point) or {}
                # An attachment keeps its name in `filename` and its cause in `analysis_*`; media keep theirs in `url`/`error`.
                # Reading only the media spelling is how the person got "attachment: ? - no cause recorded" about a file whose
                # receipt named both the size and the missing tool.
                name = entry.get("filename") or entry.get("name") or entry.get("url") or "?"
                why = str(entry.get("analysis_reason") or entry.get("error") or entry.get("analysis_cause")
                          or entry.get("cause") or "no cause recorded")
                gone.append(f"{point['kind']}: {name} — {why}")
                if cause in SI.ACCESS_CAUSES:
                    access.append(f"{key}: {name}")
            if gone:
                sources.append(sid)
                out.append(f"- {key} ({sid}): " + "; ".join(gone))
        return out, access, sources, sorted(causes)

    GAP_NAME_MAX = 100      # bytes of one name in the lists of the tail (the access list, the recorded-by-default list)

    GAP_LINE_MAX = 400      # bytes of one source line; the whole line is in the details file

    GAP_NAMES_SHOWN = 5     # names shown in each list of the tail, then `(+K more)`

    GAP_BODY_JOIN = 2       # the blank line between the body and the options: the body of the question is everything before them

    @staticmethod
    def clip_bytes(text: str, limit: int) -> str:
        """`text` cut to at most `limit` bytes of UTF-8 (on a character edge), with `...` when something was cut."""
        raw = str(text).encode("utf-8")
        return str(text) if len(raw) <= limit else raw[:max(limit - 3, 0)].decode("utf-8", "ignore") + "..."

    def name_list(self, names: list) -> str:
        """The first GAP_NAMES_SHOWN names (each clipped to GAP_NAME_MAX bytes), then `(+K more)`: a list of any length is bounded."""
        shown = [self.clip_bytes(name, self.GAP_NAME_MAX) for name in names[:self.GAP_NAMES_SHOWN]]
        return "; ".join(shown) + (f"; (+{len(names) - self.GAP_NAMES_SHOWN} more)" if len(names) > self.GAP_NAMES_SHOWN else "")

    def s1_gap_tail(self, summary: dict, access: list, options: list) -> list:
        """The lines after the source lines of the `s1_gap` question: what the factory recorded by itself, a damaged record of
        kinds, the lost-access paragraph (only when an access cause is ASKED), the routes already spent. Every part is bounded
        (the lists by `name_list`, the record's problem by `clip_bytes`), so the tail never eats the body's limit. The answers it
        refers to are read from `options`, the list the question is built from - by their words and their count, never by a
        position (a position moves when an answer is added in front of it)."""
        tail = []
        defaulted = [str(point["name"]) for points in (summary.get("defaulted_points") or {}).values() for point in points]
        if defaulted:
            tail.append(f"Already recorded as gaps, without a question: the factory established by itself that it cannot reach "
                        f"them - {len(defaulted)}: " + self.name_list(defaulted) + ". The report names each.")
        if summary.get("gap_class_problem"):
            tail.append(f"The record of your earlier answers about kinds of gaps could not be read "
                        f"({self.clip_bytes(summary['gap_class_problem'], 300)}), so every gap is asked again.")
        route = next((str(o["says"]).partition(":")[0] for o in options if o.get("answer") == "route"), "")
        if access:
            tail += ["", "**This reads as lost access, not as a missing source**: " + self.name_list(access)
                     + ". A dropped VPN or an expired login answers exactly this way. Check the access, "
                     f"then give the answer \"{route}\" and the collection runs again. "
                     "Accepting a gap here would put a reachable source on the record as unreachable."]
        count = {2: "Two", 3: "Three", 4: "Four"}.get(len(options), str(len(options)))
        tail += ["", "The factory's own routes are already spent on this: the authenticated API "
                 "(`vcs_evidence.py`) and the local checkouts. It has no browser — a headless role "
                 "cannot hold your session, and the factory does not carry credentials — so the "
                 "browser route belongs to whoever has the session. "
                 f"{count} answers work; anything else you say goes to the scout as it is."]
        return tail

    def s1_gap_more(self, left: int) -> str:
        return f"(+{left} more sources - the whole list is in the file named below)"

    def s1_gap_cap(self, head: list, tail: list, source_lines: list) -> tuple:
        """`(shown, cut)`: the source lines that fit the BODY of the `s1_gap` question - everything before the options, the blank
        line included - at most GAP_TEXT_MAX bytes; a body of exactly GAP_TEXT_MAX is printed whole, one byte more is cut. When
        cut, the printed lines are followed by ONE line `(+K more sources ...)`, whose bytes are reserved exactly; the whole list
        goes to the details file. Each printed line is clipped to GAP_LINE_MAX bytes, so a body with a source at all holds a line."""
        clipped = [self.clip_bytes(line, self.GAP_LINE_MAX) for line in source_lines]
        used = len("\n".join(head + tail).encode("utf-8")) + self.GAP_BODY_JOIN + (1 if clipped else 0)   # + the blank line
        sizes = [len(line.encode("utf-8")) + 1 for line in clipped]
        if used + sum(sizes) <= self.GAP_TEXT_MAX:
            return clipped, clipped != list(source_lines)       # a clipped line is the other reason for the details file
        fit = 0
        for count, size in enumerate(sizes, 1):
            used += size
            if used + len(self.s1_gap_more(len(clipped) - count).encode("utf-8")) + 1 <= self.GAP_TEXT_MAX:
                fit = count
            if used > self.GAP_TEXT_MAX:
                break
        return clipped[:fit] + [self.s1_gap_more(len(clipped) - fit)], True

    def s1_gap_options(self, causes: list) -> list:
        """The answers of the `s1_gap` question, in the order they are offered."""
        role = {"role": f"the {self.role_words('qa-scout')}"}
        kind_words = ", ".join(c.replace("_", " ") for c in causes)
        options = [
            {"answer": "not_needed", "token": "not needed",
             "says": "not needed: it is recorded as an accepted gap in your words"}]
        if causes:
            options.append({"answer": "not_needed_kind", "token": "skip all like these",
                            "says": "not needed, and the same for every later one that fails for the same reason in this story: "
                                    + kind_words})
        options += [
            {"answer": "route", "says": "here is how to reach it: name the route (a token, a CLI, a VPN to reconnect, a "
                                         "connector) and the collection runs again",
             "slots": {**role, "what": "give the route, or restore the access"}},
            {"answer": "content", "says": "here is the content: read it yourself (or have an agent with a browser read it) and "
                                           "paste what matters inside a ``` fence; it is saved as material of that source "
                                           "with `provenance: person_pasted`, so the record says where it came from",
             "slots": {"what": "read the source and paste what matters"}}]
        return options

    def s1_gap_text(self, refusal: str) -> str:
        """What is unavailable and STILL ASKED, per source the exit gate names, read from the inventory's own summary (the points,
        not the raw item statuses). A point the factory itself established as out of reach, or a kind of gap the person
        already answered, is not here: one line says how many are recorded without a question (D-0043)."""
        import source_inventory as SI
        ids = sorted(set(re.findall(S1_GAP_RE, refusal or "", re.IGNORECASE)))
        inventory = _read_json(self.task_root / "work" / "source-inventory.json")
        kinds = SI.class_kwargs(self.task_root)
        summary = SI.completeness(inventory, **kinds) if inventory.get("sources") else {}
        # The sources the gate NAMED are required by definition; the points asked are read for exactly those.
        named = {"sources": [dict(item, required=True) for item in inventory.get("sources") or [] if item.get("source_id") in ids]}
        source_lines, access, sources, causes = self.s1_gap_lines(ids, inventory, SI.completeness(named, **kinds))
        head = [f"Some source material of `{self.task}` cannot be reached:"]
        options = self.s1_gap_options(causes)
        tail = self.s1_gap_tail(summary, access, options)
        shown, cut = self.s1_gap_cap(head, tail, source_lines)
        lines = head + shown + ([""] if shown else []) + tail
        text = self.closed_question("s1.gap", "\n".join(lines), options)
        # What this question named, for its answer (the tokens close exactly this - never what the inventory holds later):
        # `ask()` writes them into `asked` for kind `s1_gap` only. The full list rides in `details` when the body was cut.
        text.sources, text.classes = tuple(sources), tuple(causes)
        text.details = ("The sources this question is about, whole:\n" + "\n".join(source_lines)) if cut else ""
        return text

    def record_review(self, words: str) -> bool:
        """The person's source-review words, recorded by code with the factory's own command.
        False when the inventory is not there to record into (the conductor takes over)."""
        inventory = self.task_root / "work" / "source-inventory.json"
        if not inventory.is_file():
            return False
        code, out = self.py("ticket_adapter.py", "review", "--record", "--output",
                            f"qa-factory/artifacts/{self.task}/work/source-inventory.json",
                            *self.words_args(words, "s1review"))
        if code:
            print(f"review --record failed (exit {code}): {out[-300:]}")
            return False
        self.answer_row("S1 source review: ", words.strip(), what="your source review")
        return True

    def has_left_out_list(self) -> bool:
        """Does this story carry the person's list of sources not to read (a live exclusion)? An unreadable
        record is reported by the writers that refuse over it; the review question is not one of them."""
        import source_exclusions as SE
        try:
            return bool(SE.live(self.task_root))
        except SE.ExclusionRecordError:
            return False

    def s1_review_text(self, digest: str) -> str:
        inventory = self.task_root / "work" / "source-inventory.json"
        code, table = self.py("ticket_adapter.py", "review", "--output",
                              f"qa-factory/artifacts/{self.task}/work/source-inventory.json")
        pipeline = self.pipeline()
        lines = [f"These are the sources I found for `{self.task}` and what I decided about each.", "",
                 table if code == 0 else digest, "",
                 "Kept sources will be read in full — comments, attachments, linked material. Left-out "
                 "ones are not downloaded."]
        if self.has_left_out_list():
            lines.append("The ones marked 'left out by you (before the run)' are not read; to read one after "
                         "all, name it in your answer.")
        # Four cases, exclusive (t-017 D2): a stand that is named and unconfirmed; no name with stands
        # to choose from; no name and none recorded; a stand that is named and confirmed. A story
        # written by the old S0 (`environment: null`, `environment_pending: false`) is the no-name
        # case, the same reading `stand_check` gives it.
        environment = pipeline.get("environment")
        if environment and pipeline.get("environment_pending"):
            lines.append(f"The stand `{environment}` did not answer when I checked it; planning goes "
                         "on, I check it again before the tests run; name another stand here if you "
                         "want one.")
        elif not environment and self.config.get("environments"):
            names = ", ".join(e.get("name", "") for e in self.config["environments"])
            lines.append(f"Which stand do I test on: {names}?")
        elif not environment:
            # t-363 B3, third site of the class: the plugin's command is something to TYPE, so it stands in the answer
            # block (human-questions.md rule 5) - ONE shape for the three sites (`Person.answer_note`, t-373 F7, see
            # `s1_review_note`) - and the body says "the onboarding step named below".
            lines.append("This project records no stand, so nothing is run on one yet; before the "
                         "tests run I will ask again (the onboarding step named below adds one).")
        else:
            lines.append(f"The stand is `{environment}`.")
        if not inventory.is_file():
            lines.append("(work/source-inventory.json is not on disk yet; the digest above is the table)")
        # C2-9: the `unavailable` answer is offered only while something is still ASKED; what the factory itself established as out of
        # reach (or a kind the person answered) is not a question, and one line says so.
        asked_open, defaulted = True, 0
        if inventory.is_file():
            try:
                import source_inventory as SI
                summary = SI.completeness(SI.load_inventory(inventory), **SI.class_kwargs(self.task_root))
                asked_open = bool(summary.get("unavailable") or summary.get("unavailable_materials"))
                defaulted = sum(len(points) for points in (summary.get("defaulted_points") or {}).values())
            except Exception:
                asked_open, defaulted = True, 0         # an inventory that cannot be read: the answer stays offered (the unknown is asked)
        if defaulted and not asked_open:
            lines.append(f"{defaulted} materials the factory cannot reach by itself are recorded as gaps; the report names them.")
        role = {"role": f"the {self.role_words('qa-scout')}"}
        options = [
            {"answer": "agree", "says": "agree with the table: the kept sources are read in full", "slots": role},
            {"answer": "flip", "says": "name a ticket to flip, or to ask about", "slots": role}]
        if asked_open:
            options.append({"answer": "unavailable", "says": "for anything unavailable: get me access, or tell me to go on without it",
                            "slots": {**role, "what": "restore the access, or say to go on without it"}})
        return self.closed_question("s1.review", "\n".join(lines), options)

    # --- stages ----------------------------------------------------------------------------

    def left_out_lines(self) -> list:
        """The scout's line about the person's list of sources not to read (B-231, FR-38: the requirement
        a check will judge - the manifest detector, the library fetch doors - is stated BEFORE the work).
        [] with no list. A list that exists and cannot be read is a refusal naming the file."""
        import source_exclusions as SE
        try:
            live = SE.live(self.task_root)
        except SE.ExclusionRecordError as exc:
            raise Refusal(str(exc))
        if not live:
            return []
        parts = []
        for exclusion in live:
            target = exclusion.get("target") or {}
            head = target.get("head_sha") if target.get("kind") == "mr" else target.get("sha")
            parts.append(f"{exclusion.get('as_written')} (\"{SE.clip(exclusion.get('reason') or '')}\""
                         + (f"; head commit {str(head)[:12]}" if head else "") + ")")
        return ["Left out by the person's word before the run - do not read, collect, cite as a source, "
                "precedent or existing coverage: " + "; ".join(parts) + ". A citation of one of them by its "
                "merge request number, link, branch or head commit is the same source; the exit gate checks "
                "your manifest and your receipts for it. If you think one is needed, say so in your handoff: "
                "the person decides at the source review."]
