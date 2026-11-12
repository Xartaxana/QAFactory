"""driver_runner.py - Driver members and names homed here by ai-packages/qa-factory/scripts/tests/fixtures/driver-layers.json (TD-11 cut by tools/source_split.py); no behaviour of its own."""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import hooklib
from driver_chains import _CHAIN, once_on
import human_text
import no_move as NM
import person_owned as PO
import waiver
from driver_core import EXIT_ERROR, InfraStop, JOURNAL_ROWS_BLOCK, Person, Priced, Refusal, Stop, _answer_note, _append_jsonl, _now, _read_answer, _read_json, _write_json, gate_refusal, recorded_earlier


# What the person reads beside a Codex call's price (`cost_basis` of the journal row, the cost line, the dashboard card,
# the retro): the number is computed from the factory's default tariffs (references/model-rates.json, or the project's
# `cost.rate_overrides`) - not a charge the CLI reported (P18) - and the long-context tier is chosen by the turn's sum of
# input tokens, as `cost_capture.value_usage` does for a Claude request. The text is the fact (FR-41).
CODEX_COST_LABEL = "estimate: default tariffs (references/model-rates.json); long-context tier by the turn's sum"

ROLE_TOOLS = "Bash,Read,Write,Edit,MultiEdit,Glob,Grep"

HANDOFF_FORM = ("<role> <stage> <window or scope> · ok|concerns|halt|impossible\n"
                "<id> · <state> · <reason ≤ 80 chars>   (one line per item in scope)\n"
                "<task-relative path of the artifact>")

INCOMPLETE_STREAM = ("the Codex event stream ended with no terminal turn event (no turn.completed, no turn.failed), "
                     "so what the call did is not known")

NO_EVENTS_STREAM = ("the Codex CLI printed text but no event under --json, so there is no result to take and what the "
                    "call did is not known")


def parse_codex_jsonl(raw: str, *, resume: str = "") -> dict:
    """The result of a Codex CLI call in the shape `run_claude` reads, from the `--json` event stream of
    `codex exec` (codex-cli 0.158.0: event types `thread.started`, `turn.started`, `turn.completed`,
    `turn.failed`, `error`, `item.started`, `item.updated`, `item.completed`; item type `agent_message`; usage keys
    `input_tokens`, `cached_input_tokens`, `output_tokens` - the names read in the binary, not a live run).

    - `session_id`: the `thread_id` of `thread.started` (any event that carries one), else `resume`.
    - The LAST terminal event (`turn.failed`, `turn.completed`) decides the call (CX1-15 S-7):
      `turn.failed` -> `is_error`, `subtype` `turn_failed`, `result` = ITS message (the failure is what the call says,
      as a failed `claude -p` answers with its error and not with the role's last words; the agent text before it is
      `partial`, and never the result); `turn.completed` -> success, an `error` event before it is a note of the
      stream (`errors`), not a failure (E-5).
    - No terminal event but an `error` event: `is_error`, `subtype` `error_event`, `result` = the messages.
    - No terminal event and no `error`, events read: `is_error`, `subtype` `turn_incomplete`, `result` =
      `INCOMPLETE_STREAM` (E-3, F-10: an unknown outcome is never a success and never a classified failure),
      the agent text `partial`.
    - `resume_mismatch` (E-7): a resumed call whose `thread.started` names ANOTHER thread is `is_error` with the
      session of the request, the new id in `errors`, `num_turns` 0 (the requested thread did no work): a
      continuation never silently becomes a new thread.
    - A success: the text of the LAST `agent_message` item.
    - No event at all: the lines that were not events are `is_error`, `subtype` `no_events`, `result` =
      `NO_EVENTS_STREAM`, the text kept as `partial` (F-4: a stream that ends without a result is never `completed`; a
      `--json` stdout with text and no event is not an answer in another form). An EMPTY stream is "" and not an error
      (E-6: nothing was claimed, as `json.loads("")` is not an error on Claude): the caller names it in a note row.
    - `num_turns`: the count of `item.completed` events (E-21); None when no event was read.
    - `usage`: summed over the `turn.completed` events; `events`: whether any event line was read; `noise`: how many
      non-empty lines were no event (not JSON, or JSON with no `type`/`thread_id`).
    Nothing here raises on a line it cannot read."""
    thread_id, texts, steps, usage, errors, plain, events = "", [], 0, {}, [], [], False
    terminal = ""
    for line in str(raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        event = None
        if line.startswith("{"):
            try:
                event = json.loads(line)
            except ValueError:
                event = None
        if not isinstance(event, dict) or not (event.get("type") or event.get("thread_id")):
            plain.append(line)
            continue
        events = True
        kind = str(event.get("type") or "")
        thread = event.get("thread") if isinstance(event.get("thread"), dict) else {}
        tid = event.get("thread_id") or thread.get("id")
        if tid and not thread_id:
            thread_id = str(tid)
        if kind == "item.completed":
            steps += 1
            item = event.get("item") if isinstance(event.get("item"), dict) else {}
            if item.get("type") == "agent_message":
                text = item.get("text")
                if text is None:
                    text = item.get("content")
                if isinstance(text, list):
                    text = "".join(str(c.get("text") or "") for c in text if isinstance(c, dict))
                if str(text or "").strip():
                    texts.append(str(text))
        elif kind == "turn.completed":
            terminal = "completed"
            used = event.get("usage")
            if isinstance(used, dict):
                for key, value in used.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        usage[key] = usage.get(key, 0) + value
        elif kind in ("turn.failed", "error"):
            detail = event.get("error") if isinstance(event.get("error"), dict) else {}
            message = detail.get("message") or event.get("message") or detail or event.get("error") or json.dumps(event)
            if isinstance(message, (dict, list)):
                message = json.dumps(message, ensure_ascii=False, sort_keys=True)     # an error object with no message: its JSON, not a Python repr
            errors.append(str(message))
            if kind == "turn.failed":
                terminal = "failed"
                failure = str(message)
    partial = texts[-1] if texts else ""
    base = {"num_turns": steps if events else None, "usage": usage, "errors": errors, "events": events,
            "noise": len(plain) if events else 0}
    asked = str(resume or "")
    if asked and thread_id and thread_id != asked:
        return dict(base, session_id=asked, result=("the Codex CLI answered the continuation of thread " + asked
                                                    + " in another thread (" + thread_id + "): the dispatch's own "
                                                    "thread was not continued"),
                    is_error=True, subtype="resume_mismatch", num_turns=0, errors=errors + [thread_id],
                    **({"partial": partial} if partial else {}))
    session = thread_id or asked
    if terminal == "failed":
        return dict(base, session_id=session, result=failure, is_error=True, subtype="turn_failed",
                    **({"partial": partial} if partial else {}))
    if terminal == "completed":
        return dict(base, session_id=session, result=partial, is_error=False, subtype="success")
    if errors:
        return dict(base, session_id=session, result="\n".join(errors), is_error=True, subtype="error_event",
                    **({"partial": partial} if partial else {}))
    if events:
        return dict(base, session_id=session, result=INCOMPLETE_STREAM, is_error=True, subtype="turn_incomplete",
                    **({"partial": partial} if partial else {}))
    if plain:
        # F-4: under `--json` a stdout with text and no event is not an answer in another form, it is a stream that ended
        # with no result: unknown, never `completed`; the text stays as evidence (`partial`, the journal note).
        return dict(base, session_id=session, result=NO_EVENTS_STREAM, is_error=True, subtype="no_events",
                    partial="\n".join(plain), noise=len(plain))
    return dict(base, session_id=session, result="", is_error=False, subtype="", noise=0)


def codex_call_cost(usage: dict, model: str, cost_cfg) -> tuple:
    """(usd or None, text) for one Codex call: its summed `usage` priced by `cost_capture.value_usage`, the ONE pricer.

    The same price list and the same arithmetic the Claude side reads: the project's `cost.rate_overrides`, then the
    bundled `references/model-rates.json` (exact id or alias, OpenAI provider), the long-context tier chosen by the
    sum of the input tokens of the call, as `value_usage` does for one request (a call is read as one request: the
    stream gives a turn's sum, not the size of each request inside it, which `CODEX_COST_LABEL` says). Codex counts
    cached tokens INSIDE `input_tokens` (`codex_usage.scan` splits them the same way): input - cached is billed as
    input, cached as `cache_read`, `output_tokens` includes the reasoning. The text is `CODEX_COST_LABEL` beside a
    number, or `price unknown: <why>` (FR-41: an unknown is never `$0`) with the number None: no tariff for the model,
    a usage that cannot be counted (a bool, a negative, a fractional or unreadable count, a cached count above the
    input, reasoning above the output, any cache write - `codex_usage.scan` refuses the same), or no usage at all."""
    import cost_capture
    from decimal import Decimal
    cfg = cost_cfg if isinstance(cost_cfg, dict) else {}
    usage = usage if isinstance(usage, dict) else {}
    counts = {key: _token_count(usage.get(key, 0)) for key in ("input_tokens", "cached_input_tokens", "output_tokens",
                                                              "reasoning_output_tokens", "cache_write_input_tokens")}
    if (None in counts.values() or counts["cached_input_tokens"] > counts["input_tokens"]
            or counts["reasoning_output_tokens"] > counts["output_tokens"] or counts["cache_write_input_tokens"]):
        return None, f"price unknown: the usage of this call is not countable for {model}"
    if not (counts["input_tokens"] or counts["output_tokens"]):
        return None, f"price unknown: the stream carried no usage for {model}"
    aggregate = {"input": counts["input_tokens"] - counts["cached_input_tokens"],
                 "cache_read": counts["cached_input_tokens"], "output": counts["output_tokens"]}
    valued = cost_capture.value_usage(aggregate, model, cfg, None, "openai", datetime.now(timezone.utc))
    if valued["pricing_coverage"] != "complete":
        if (valued.get("rate_provenance") or {}).get("kind") == "unpriced":
            return None, f"price unknown: no tariff for {model}"
        missing = ", ".join(valued.get("missing_rate_categories") or []) or "a category"
        return None, f"price unknown: no tariff for {model} ({missing})"
    return float(Decimal(valued["subtotal_usd"])), CODEX_COST_LABEL


def codex_running_total(before, call_cost):
    """The thread's running total after a call: `before` (the last usable total of the thread's rows, None when it has none)
    plus the call's price. An unpriced call (`call_cost` None) leaves the total as it was, None when there was none: the
    row's `cost_basis` says the call is not in it. Decimal, so 0.30 + 0.45 is 0.75 and not 0.7500000000000001."""
    from decimal import Decimal
    if call_cost is None:
        return before
    return float(Decimal(repr(before or 0.0)) + Decimal(repr(call_cost)))


def _token_count(value):
    """A token count as an int, or None when it cannot be one: a bool, a negative, a string, an infinity, a fraction. A float
    that is a whole number (`10.0`) is that number; `10.9` is not a count (it was truncated to 10 before)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    return value if isinstance(value, int) and value >= 0 else None


class DriverRunner:
    def waiver_road(self, classed: bool = True) -> tuple:
        """The flags every driver-road `waiver.py` recording call carries (RN1-9 B-1, AR-22): `--by driver` marks the road (so
        `person_owned.share` counts the word on the DRIVER counter, never the interactive one) and `--why-person <id>` carries the
        class of the question the word answers (`asked["why_person"]`, set by `ask()`); no class asked, no flag. `classed=False`:
        the driver's own take-back (a revoke is not an answer to a question) carries the road mark alone."""
        cid = PO.as_class((self.state.get("asked") or {}).get("why_person")) if classed else ""
        return ("--by", "driver") + (("--why-person", cid) if cid else ())

    def py(self, script: str, *args, check: bool = False, expect: str = "") -> tuple:
        """Run one factory script from the project root. (exit code, stdout+stderr).

        `check=True`: a non-zero exit raises `Refusal`, and a TIMEOUT (124, `PY_TIMEOUTS`) is a non-zero exit like any other (C1-7a
        B-4 iii: it was returned before the check and never raised). `expect` (C1-7a, F10): what this step must leave behind, in words
        for the lead. With it the refusal is FR-1 shaped (what failed, what was expected, the door), carries the mark `known = False`
        (see the end of this docstring), and its `retry` carries `expect`
        too (B-4 i: a failing retry is the same kind of refusal, not a plain one). Without `expect` the text is today's, byte for byte.
        `known = False` is the MARK that `route_known` reads (C1-7b) to keep the known-refusals table from routing such a step; the G
        steps of the stage functions (S0, S4, S6, S8, S9) pass `expect`, and a step without one keeps the plain refusal."""
        path = self.scripts / script
        try:
            done = subprocess.run([sys.executable, "-B", str(path), *[str(a) for a in args]],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  cwd=str(self.project), env=self.env, timeout=self.PY_TIMEOUTS.get(script))
            code, out = done.returncode, (done.stdout + ("\n" + done.stderr if done.stderr.strip() else "")).strip()
        except subprocess.TimeoutExpired:
            # F4: a script with a ceiling (`PY_TIMEOUTS`) that does not finish is a script that said nothing: 124, as `timeout(1)`
            code, out = 124, f"{script} did not finish within {self.PY_TIMEOUTS.get(script)} seconds"
        if check and code:
            retry = lambda: self.py(script, *args, check=True, expect=expect)      # noqa: E731
            if not expect:
                raise Refusal(f"{script} {' '.join(str(a) for a in args[:6])} (exit {code}):\n{out}", retry=retry)
            raise gate_refusal(script, code, out, expect, retry)
        return code, out

    # --- rows the journal refused (C1-7a, P22): owed, written again first, then the seam ----------------------------------------

    def owed_list(self) -> list:
        """`state["owed_rows"]` as a list. Absent (a story recorded before C1-7a) reads as no rows owed. A value that is not a list is
        set aside with ONE `trace_failed` line and reads as none: a malformed record never blocks the loop and is never dropped
        unsaid (E12)."""
        rows = self.state.get("owed_rows")
        if rows is None:
            return []
        if not isinstance(rows, list):
            self.journal_run({"kind": "trace_failed", "script": "owed_rows", "exit": 0,
                              "why": f"driver-state owed_rows was a {type(rows).__name__}, not a list; read as no rows"})
            self.state["owed_rows"] = []
            return []
        return rows

    def owed_stage(self) -> str:
        """The stage id an owed row is recorded under (`waiver.py --stage` takes S0..S9 only): the boundary's, else the open question's,
        else the ONE stage running, else S0. Never read from a person's words."""
        for stage in (self.boundary.split(":")[0], str((self.state.get("asked") or {}).get("stage") or "")):
            if re.fullmatch(r"S\d", stage):
                return stage
        running = [s for s, held in (self.pipeline().get("stages") or {}).items()
                   if re.fullmatch(r"S\d", str(s)) and isinstance(held, dict) and held.get("status") == "running"]
        return running[0] if len(running) == 1 else "S0"

    def owe_row(self, script: str, *args, what: str, stage: str = "") -> None:
        """THE write of a journal row the story's later roles read (the person's words, an FR-4 finding, a `--warn` line): the script
        runs once; a non-zero exit makes the row OWED (`state["owed_rows"]`, saved), says so in ONE line, and the flow goes on, because
        the executor at hand already holds the words. `owed_rows_step` writes it again before any brief is built; a second failure is
        the seam's question. ERROR DIRECTION: a duplicate row is allowed (a write that landed and still exited non-zero is run again),
        a lost row is not. `what`: the row in words for the lead, written by the caller (never a person's words). Returns None, so the
        census of the audit reads the exit here and sees the callers' result as handled (A27 py-wrapper rule)."""
        code, out = self.py(script, *args)
        if code and recorded_earlier(script, code):
            print(f"journal: {what} was recorded earlier; nothing more to write")
        elif code:
            rows, at = self.owed_list(), _now()
            ident = "row-" + hashlib.sha256(f"{at}|{script}|{args}|{len(rows)}".encode("utf-8")).hexdigest()[:8]
            rows.append({"id": ident, "script": script, "args": [str(a) for a in args], "what": what, "stage": stage or self.owed_stage(),
                         "at": at, "tries": 1, "exit": code, "tail": out[-300:]})
            self.state["owed_rows"] = rows
            self.save_state()
            print(f"journal: {what} is not in the story's journal yet ({script} exit {code}); it is written again before the next step")

    def answer_row(self, prefix: str, words: str, *, what: str, extra=()) -> None:
        """The `human_answer` row of a person's words, owed when the journal refuses it (FR-8: every later brief reads these rows).
        `extra`: arguments between `--task` and `--notes` (the one caller that names its `--by`)."""
        self.owe_row("log_append.py", "--event", "human_answer", "--task", self.task, *extra, "--notes", _answer_note(prefix, words),
                     what=what)

    def py_trace(self, script: str, *args, why: str) -> None:
        """A script nothing decides on (kind T, a `# remains:` door with its reason in the call): `why` is the invariant that makes its failure safe, and it is MANDATORY (an
        empty one is a programming error). A failure is printed in one line and journalled in driver-runs.jsonl as `trace_failed`;
        it never raises and never stops the story."""
        if not isinstance(why, str) or not why.strip():
            raise ValueError("py_trace needs a non-empty `why`: the invariant that makes this failure safe to leave")
        code, _out = self.py(script, *args)
        if code:
            print(f"note: {script} exit {code}; the story goes on ({why})")
            self.journal_run({"kind": "trace_failed", "script": script, "exit": code, "why": why})

    def mark_rows_word(self, asked: dict, stage: str) -> None:
        """The person's `go on` reached the rows of ITS question (B-1): once `pass_block` recorded the pass (the waiver is the durable
        record), each owed row whose id the question carried (`asked["rows"]`) is marked with the stage the word was recorded under
        (`row["word"]`), and the state is saved. The pairing is by IDENTITY, never by clock: a word recorded in the same second as a
        newer question (or before it) marks nothing of that question's rows, because their ids are not in the answered one."""
        ids = {str(i) for i in asked.get("rows") or []}
        for row in self.owed_list():
            if isinstance(row, dict) and str(row.get("id")) in ids:
                row["word"] = stage
        self.save_state()

    def rows_word(self, row: dict) -> bool:
        """Whether the person's `go on` stands for THIS owed row: the row was marked when its own question was answered
        (`mark_rows_word`) and the override of `JOURNAL_ROWS_BLOCK` recorded for that stage is still unrevoked and has words. The
        override is read through `waiver.split_overridden`, the ONE reader of `stage_overrides[]` (AR-13). THE reader of this block
        name (references/block-names.json). The word is the STORY's, like every waiver, and reaches only the rows it was given for."""
        stage = str(row.get("word") or "")
        if not stage:
            return False
        _blocking, passed = waiver.split_overridden([JOURNAL_ROWS_BLOCK], self.pipeline(), stage)
        return bool(passed)

    def words_file(self, words: str, name: str):
        """Put a person's words in a file, exactly as the driver holds them; the path, or None.

        Every command that records a person's words takes them from a file (`--words-file`, M30):
        on TP2-2406 a three-paragraph answer was recorded as its first paragraph because
        cmd.exe cuts a command line at the first line break. The driver's own argv is not cut (a
        list argv, no cmd), but the Windows command line holds 32767 characters and the conductor,
        a role with only Bash, Read and Grep, cannot make a file of an answer it was handed - so the
        driver makes it, once, here (FR-17: every site that hands words over comes through this).

        `<task root>/state/words/driver-<name>-<millisecond stamp>[-<n>].txt`: UTF-8, no BOM, line
        breaks as given (newline=""), created with "x" so a name that exists is never overwritten.
        `name` is a gate or stage word (`gateA`, `s1review`), never one the secrets guard refuses.
        The file is the audit trail of what was handed over and is never deleted. An empty or
        whitespace-only answer writes nothing and returns None. A write that fails (no folder, a full
        disk) stops the driver with its own error: the words are NOT passed on the command line
        instead - that is the road that cuts them."""
        if not str(words or "").strip():
            return None
        folder = self.state_dir / "words"
        stem = "driver-" + re.sub(r"[^A-Za-z0-9]+", "", str(name or "")) + "-" + str(int(time.time() * 1000))
        path, made = folder / (stem + ".txt"), None
        try:
            folder.mkdir(parents=True, exist_ok=True)
            for number in range(1, 1000):
                try:
                    with open(path, "x", encoding="utf-8", newline="") as stream:
                        made = path
                        stream.write(words)
                except FileExistsError:
                    path = folder / f"{stem}-{number}.txt"
                    continue
                return path
            raise OSError("no unused file name")
        except OSError as exc:
            if made is not None:
                try:
                    made.unlink()                   # half a text must not stand as the person's words
                except OSError:
                    pass
            raise Stop(EXIT_ERROR,
                       f"the driver could not save the person's words to {path} ({exc.strerror or exc}). "
                       "Nothing was recorded: the words are not put on a command line instead, because a "
                       "long or multi-line text would be cut there. Make the folder "
                       f"{folder} writable (or free some disk space), then run the same command again "
                       "with the same --answer file.") from None

    def words_args(self, words: str, name: str) -> list:
        """The arguments that hand a person's words to a command: `--words-file <path>`.

        An empty answer has no file and is passed as it always was, inline and empty, so the
        command gives its own refusal for it and no new stop is invented here."""
        path = self.words_file(words, name)
        return ["--words", words] if path is None else ["--words-file", str(path)]

    def json_file(self, data: dict, name: str):
        """A JSON object in a file under `state/words/` (the driver's one folder for what it hands a command by file), the path."""
        return self.words_file(json.dumps(data, ensure_ascii=False, sort_keys=True), name)

    def step(self, *args) -> str:
        code, out = self.py("story_step.py", *args)
        if code:
            raise Refusal(f"story_step {args[0]} (exit {code}):\n{out}", retry=lambda: self.step(*args))
        return out

    def controller(self, operation: str, *args, input_data=None) -> dict:
        argv = ["--task-root", str(self.task_root), "--operation", operation, *args]
        if input_data is not None:
            path = self.state_dir / "driver-tmp" / f"{operation}-{int(time.time() * 1000)}.json"
            _write_json(path, input_data)
            argv += ["--input", str(path)]
        code, out = self.py("controller.py", *argv)
        if code:
            raise Refusal(f"controller {operation} (exit {code}):\n{out}")
        answer = _read_answer(out)
        if answer is None:
            # t-2020 (AR-28, FR-41): an answer nobody could read is an unknown, never an empty answer a caller would take for "nothing".
            raise Refusal(f"controller {operation}: no line of its output is a JSON object (expected the controller's one-line answer; "
                          f"the text that came back, first 300 characters): {' '.join(str(out).split())[:300] or 'nothing'}")
        return answer

    def journal_run(self, record: dict) -> None:
        row = dict(ts=_now(), **record)
        _append_jsonl(self.state_dir / "driver-runs.jsonl", row)
        # TR4-11: the calls THIS process launched and has seen no end row for - `person_stop_record` names them (`cut`). The ends are
        # matched the way `collect_stall._k3_k4` matches them (an outcome row of the same key); a row that was not written is not kept.
        open_calls = once_on(self, "_open_calls", set)
        if row.get("kind") == "launched":
            started = row.get("started_at") if row.get("started_at") is not None else row["ts"]
            open_calls.add((str(row.get("dispatch_id") or row.get("call") or ""), str(started)))
        elif any(k in row for k in ("is_error", "exit_code", "infra")):
            ended = str(row.get("dispatch") or row.get("kind") or "")
            for entry in [e for e in list(open_calls) if e[0] == ended]:
                open_calls.discard(entry)

    def journal_conductor(self, **record) -> None:
        _append_jsonl(self.state_dir / "conductor.jsonl", dict(ts=_now(), boundary=self.boundary, **record))

    def progress_line(self) -> None:
        """`[progress] <where the story stands>`, once per transition (t-310): at the start, before a role is
        launched, after it returns, when a question is posted (a gate is one), when a stage closes by code,
        and at the end. The line is `story_progress.progress` over the records - never this process's memory -
        and it is a courtesy: whatever goes wrong in it is said in the line and never stops the run (P1).
        Flushed per line (FR-43): the log is read while the story runs."""
        try:
            import story_progress
            line = story_progress.progress(self.task_root, fresh_ok=True)["line"]
        except Exception as exc:
            line = f"not available ({type(exc).__name__}: {' '.join(str(exc).split())[:120]})"
        view = getattr(self, "_s5_view", None)
        if view is not None:      # TR3-6: only while the scheduler runs; no key in the state, nothing on the serial road
            running = sorted(r.n for r in self._chains.values() if not r.done)
            line += (f" · windows running: {','.join(str(n) for n in running) or 'none'} of {view['total']}"
                     + (f" · closed {','.join(str(n) for n in sorted(view['closed']))}" if view["closed"] else ""))
        print(f"[progress] {line}", flush=True)

    # --- one package generation per run (B-014) ----------------------------------------------

    @staticmethod
    def _root_key(path) -> str:
        """A plugin root as it is compared: resolved, and case-folded where the file system is."""
        try:
            return os.path.normcase(str(Path(str(path)).resolve()))
        except (OSError, ValueError):
            return os.path.normcase(str(path))

    @staticmethod
    def _copy_version(root) -> str:
        try:
            import telemetry_hook
            return telemetry_hook._plugin_version(Path(str(root)))
        except Exception:
            return ""

    def package_check(self, session_id: str, *, stage: str = "", dispatch: str = "") -> None:
        """Did the hooks of this session come from the copy of the package this driver runs?

        The driver loads its own copy (`--plugin-dir`), the project may enable another one, and
        nothing recorded which generation's guards ran under a role: a role could be judged by the
        checks of one version and told its rules by another. `telemetry_hook.py` leaves a receipt
        per session with the plugin roots its hooks ran from (SessionStart fires in `claude -p`,
        measured in step 0), so a session's answer is accepted only when that receipt names this
        driver's root and nothing else. A MISSING receipt is a mismatch too: the checks did not
        report, and a session nobody guarded is not one to accept. Until this process has one
        matching session it asks of every session; after that it stops (one generation per run).

        POSITION INVARIANT: called by `run_claude` right after the journal line and BEFORE its
        caller sees the result - a mixed session's result is never bound, handed over or finished.
        The saved result of the dispatch, if one is there, is set aside as `.mixed.json`, so a rerun
        never reuses it. The person's word passes a root pair (FR-4, `take_answer`), and the same
        pair then passes without a question."""
        if self.package_verdict or not session_id:
            return
        ours = self._root_key(self.plugin)
        path = (self.project / "qa-factory" / "state" / "host-receipts"
                / f"package-{hashlib.sha256(session_id.encode('utf-8')).hexdigest()[:16]}.json")
        receipt = _read_json(path)
        seen: dict = {}
        for row in ((receipt.get("roots") if isinstance(receipt, dict) else None) or []):
            if isinstance(row, dict) and row.get("plugin_root"):
                seen.setdefault(self._root_key(row["plugin_root"]),
                                (str(row["plugin_root"]), str(row.get("version") or "")))
        # A copy from before this receipt existed (0.7.9 on) leaves its root in the host-capability
        # receipts, one file per (session, script, hook), each naming `plugin_root`: any root of this
        # session found there counts too. PARTIAL by nature - both copies write the same receipt key,
        # so the last writer wins and a root can be overwritten by the other copy's - but it sees the
        # generations that never wrote a package receipt at all.
        for other in hooklib.sorted_paths(path.parent.glob("*.json")):
            if other == path:
                continue
            row = _read_json(other)
            if isinstance(row, dict) and row.get("session_id") == session_id and row.get("plugin_root"):
                seen.setdefault(self._root_key(row["plugin_root"]),
                                (str(row["plugin_root"]), self._copy_version(row["plugin_root"])))
        hooks = sorted(seen)
        version = self._copy_version(self.plugin)
        if hooks == [ours]:
            self.package_verdict = True
            self.state["package_check"] = {"ok": True, "root": str(self.plugin), "version": version,
                                           "session": session_id}
            self.save_state()
            return
        passed = self.state.get("package_pass")
        if (isinstance(passed, dict) and passed.get("driver_root") == ours
                and sorted(passed.get("hook_roots") or []) == hooks):
            self.package_verdict = True
            self.state["package_check"] = {"ok": True, "root": str(self.plugin), "version": version,
                                           "session": session_id, "passed_by_person": True}
            self.save_state()
            print(f"package: the hooks of this session came from a different copy than the driver's; "
                  f"passed on the person's word of {passed.get('ts') or 'earlier'} (recorded)", flush=True)
            return
        saved = self.state_dir / "driver-runs" / f"{dispatch}.json" if dispatch else None
        if saved is not None and saved.is_file():
            saved.replace(saved.with_name(saved.stem + ".mixed.json"))
        mine =f"version {version} of the factory" if version else "its own copy of the factory"
        versions = sorted({v for _, v in seen.values() if v})
        if not hooks:
            what = (f"The driver runs {mine}, but the checks that guard each step did not report from "
                    "this session at all, so I cannot tell which copy they came from.")
        elif len(hooks) > 1:
            what = (f"The driver runs {mine}, but the checks that guard each step of this session came "
                    "from more than one copy of the factory" + (f" (versions {', '.join(versions)})." if versions else "."))
        elif versions and versions[0] != version:
            what = (f"The driver runs {mine}, but the checks that guard each step of this session came "
                    f"from another copy, version {versions[0]}.")
        elif versions:
            what = (f"The driver runs {mine}, but the checks that guard each step of this session came "
                    "from another copy of the same version.")
        else:
            what = (f"The driver runs {mine}, but the checks that guard each step of this session came "
                    "from another copy.")
        text = self.closed_question(
            "package.copies",
            what + "\n\nWork done under the checks of another copy is not accepted, so nothing of this "
            "session was accepted (what the role wrote stays) and that step runs again.\n\n"
            "What I need is a decision. Answer with exactly one of these words:",
            [{"answer": "retry", "token": "retry", "says": "you first make sure only one copy of the factory is active for this "
                                                          "project, and I look again",
              "slots": {"what": "make sure only one copy of the factory is active for this project"}},
             {"answer": "go on", "token": "go on", "says": "go on as it is; I record your words as the reason the story "
                                                           "carries, and file the mismatch as a defect of ours"},
             self.STOP_OPTION])
        listed = "; ".join(f"{seen[key][0]} (version {seen[key][1] or 'unknown'})" for key in hooks) or "nothing"
        details = (f"driver package: {self.plugin} (version {version or 'unknown'})\n"
                   f"hook roots reported by session {session_id}: {listed}\n"
                   f"receipt: {path}\n"
                   "To make one copy active: disable or uninstall the other one "
                   "(claude plugin disable qa-factory@<marketplace> --scope project), or start the driver "
                   "with --plugin-dir pointing at the copy the project enables.")
        self.state["package_question"] = {"what": "hooks", "driver_root": ours, "hook_roots": hooks,
                                          "session": session_id, "text": text, "details": details}
        raise Person("package", text, stage, dispatch, details=details)

    # --- claude ----------------------------------------------------------------------------

    def claude_cmd(self, prompt: str, *, agent: str = "", resume: str = "", tools: str = ROLE_TOOLS,
                   system_file: Path | None = None, max_turns: int = 0, plugin_agent: bool = True) -> list:
        # The prompt goes through stdin, never argv: a gate packet plus the person's words
        # is longer than a Windows command line (WinError 206 at gate A, driver run 3).
        if self.host == "codex":
            return self.codex_cmd(resume=resume)
        cmd = list(self.claude) + ["-p"]
        if resume:
            cmd += ["--resume", resume]
        cmd += ["--output-format", "json", "--permission-mode", "acceptEdits",
                "--model", self.model, "--allowedTools", tools, "--plugin-dir", str(self.plugin)]
        if agent and not resume:
            cmd += ["--agent", f"qa-factory:{agent}" if plugin_agent else agent]
        if system_file:
            cmd += ["--append-system-prompt-file", str(system_file)]
        if max_turns:
            cmd += ["--max-turns", str(max_turns)]
        return cmd

    # --- codex ------------------------------------------------------------------------------

    def codex_cmd(self, *, resume: str = "") -> list:
        """The Codex CLI call of one role or conductor turn, from `codex exec --help` of codex-cli 0.158.0.

        A fresh session: `codex exec --json -C <project> [-s <sandbox>] --skip-git-repo-check -m <model> [-c key=value
        ...] -` - `--json` is the JSONL event stream `parse_codex_jsonl` reads, `-C` is the project root (the role's
        cwd, as on Claude), `-` reads the prompt from stdin (never argv: the Windows command line is shorter than a
        gate packet). A continuation: `codex exec resume <thread id> --json --skip-git-repo-check -m <model> [-c ...]
        -`: the resume subcommand takes `--json` too, but not `-C` or `-s`: the thread keeps its own cwd and sandbox.
        `-m` is ALWAYS passed: `self.model` is `--model` or the data's `default_model.codex` (refused at start when
        neither exists), never a host default the factory does not name. Codex exec has no `--allowedTools`,
        `--max-turns` or `--agent`: the role's tools are the host's, its turn count is unbounded, and the role's
        instructions travel in the prompt (`host_prompt`). `driver.codex.sandbox` (`read-only`, `workspace-write`,
        `danger-full-access`; any other value is passed as given and Codex refuses it) and `driver.codex.config` (`-c
        key=value` pairs; a value that is not a string is written as JSON, so `true`, `3` and `["a"]` reach Codex as
        TOML reads them; an object or `null` has no such form and is left out at start with a note) are the project's
        say; absent, the project's own `.codex/config.toml` rules (F-6)."""
        cmd = list(self.claude) + ["exec"]
        if resume:
            cmd += ["resume", resume, "--json"]
        else:
            cmd += ["--json", "-C", str(self.project)]
            if self.codex_cfg.get("sandbox"):
                cmd += ["-s", self.codex_cfg["sandbox"]]
        cmd.append("--skip-git-repo-check")
        if self.model:
            cmd += ["-m", str(self.model)]
        overrides = self.codex_cfg.get("config") or {}
        for key in sorted(overrides):
            value = overrides[key]
            cmd += ["-c", f"{key}={value if isinstance(value, str) else json.dumps(value)}"]
        cmd.append("-")
        return cmd

    def host_prompt(self, prompt: str, *, agent: str = "", resume: str = "", system_file: Path | None = None) -> str:
        """What the child reads on stdin. On Claude, the prompt as it is: `--agent` and `--append-system-prompt-file`
        carry the role and the rule layer. On Codex there is no such flag, so a FRESH session gets, in this order, the
        role's own definition (`inject_context.role_block`: the one function of the role's body, which the Codex hook
        also reads, without its Desktop tool block - the child is a CLI), the rule layer the driver built
        (`system_file`: what `--append-system-prompt-file` would append) and the task. A continuation (`resume`) gets
        the prompt alone: the thread already holds its role. A role file that cannot be read adds no block and says so
        in one line (S-8)."""
        if self.host != "codex" or resume:
            return prompt
        parts = []
        if agent:
            import inject_context
            block = inject_context.role_block(agent, self.plugin, desktop_guide=False)
            if block is None:
                print(f"note: no role file for {agent} in {self.plugin}: the Codex prompt carries no role block", flush=True)
            else:
                parts.append(block.strip())
        if system_file is not None:
            try:
                layer = Path(system_file).read_text(encoding="utf-8")
            except OSError as exc:
                layer = ""
                print(f"note: the rule layer {Path(system_file).name} could not be read ({type(exc).__name__}): the Codex prompt "
                      "carries no rule layer", flush=True)
            if layer.strip():
                parts.append("# Rule layer (your system prompt)\n" + layer.strip())
        parts.append("# Task\n" + prompt)
        return "\n\n".join(parts)

    def host_note(self, text: str, *, dispatch: str = "") -> None:
        """A fact about the host's call the person or a later reader should have (a gap, a line that was no event): one
        `note:` line and one `kind: note` row of the driver journal. The row has no `dispatch`, `session_id` or
        `exit_code`, so every reader that binds a session, a price or the end of a dispatch passes it by (the
        `launched` row's shape). A journal that cannot be written is said in the line and never stops the call (P1)."""
        try:
            self.journal_run({"kind": "note", "host": self.host, "dispatch_id": dispatch, "note": text})
            tail = ""
        except OSError as exc:
            tail = f" (and the journal could not be written: {type(exc).__name__})"
        print(f"note: {text}{tail}", flush=True)

    def thread_total(self, session_id: str):
        """The running total of a Codex thread BEFORE the call now ending: the last usable `total_cost_usd` of the rows of
        this task's driver journal that name the thread, read through `driver_journal` (the one reader of that file and of
        what a total means). None when the thread has no row with a usable total (its first call, or only unpriced
        ones) or when the journal cannot be read: the call's price then stands alone, and the row says what it is."""
        import driver_journal
        if not session_id:
            return None
        total = None
        for row in driver_journal.read_rows(self.state_dir / driver_journal.JOURNAL_NAME):
            if row.get("session_id") == session_id:
                usable = driver_journal.usable_total(row.get("total_cost_usd"))
                if usable is not None:
                    total = usable
        return total

    def launch(self, cmd: list, prompt: str, *, dispatch: str = "", resume: str = ""):
        """`_launch` inside the scheduler's launch gate (TR3-6): on a chain thread the session waits for a running session of another
        window that holds a file of its window; off a chain, or with no dispatch (the conductor, the delivery call), nothing changes."""
        with self.session_running(dispatch):
            return self._launch(cmd, prompt, dispatch=dispatch, resume=resume)

    def _launch(self, cmd: list, prompt: str, *, dispatch: str = "", resume: str = ""):
        """Start one `claude -p` process and wait for it: `subprocess.run`'s own steps, taken apart so the process
        id can be written while it runs (B-268: a person, and `dispatch_liveness`, can tell a role at work from a
        record nobody closed). `dispatch` is a ROLE's dispatch id ('' for the conductor and the delivery call:
        liveness is asked per dispatch). The pid exists only once the process has started, so the entry
        `in_flight[<dispatch>] = {dispatch_id, pid, started_at, session_id?}` is written right after the start
        and removed when the call returns by any road (a result, an exception) - an entry still on disk after
        a hard kill is exactly what reads as "the process is gone". The child also gets
        QA_FACTORY_DRIVER_RUN=<dispatch id> in its environment (B-250: the child's own tools can tell they run
        under the driver). A failed state write never stops the run (P1: code informs)."""
        import dispatch_identity
        env = dict(self.claude_env, **{dispatch_identity.DRIVER_RUN_ENV: dispatch}) if dispatch else self.claude_env
        import threading
        import driver_timing
        stop, watcher = threading.Event(), None
        chain = getattr(_CHAIN, "record", None)
        self.stop_if_interrupted()      # B1: the person stopped the run - no new process, whichever road asked (fresh attempt, resume, conductor)
        with subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              encoding="utf-8", errors="replace", cwd=str(self.project), env=env) as proc:
            try:
                # inside the try (t-335 A-n6): a marking that raised outside it left the child waiting for a prompt
                # nobody sends, and `with` then waited for the child forever
                self.mark_in_flight(dispatch, proc.pid, resume)
                if chain is not None:
                    chain.proc = proc      # the interrupt kills it: a chain thread's own `proc.kill()` would never run on Ctrl-C
                # R1: write first, read second (main: flag, then proc; here: proc, then flag) - one of the two sees the other, so a Ctrl-C that
                # landed during Popen / mark_in_flight never leaves a child nobody kills (the `except` below kills it)
                self.stop_if_interrupted()
                if dispatch:
                    # t-1937 P2-4 (F8 (a)): a silent wait is visible - ONE thread asks the transcript's silence every POLL_S and tells
                    # it once per episode. INVARIANT: it only tells; nothing here kills or signals the process (a role that is
                    # working is never stopped by the driver), and the thread ends with this call (`stop` is set in the `finally`).
                    watcher = threading.Thread(target=driver_timing.watch, args=(self.project, dispatch, stop), daemon=True)
                    watcher.start()
                # TR3-6 (M1): `_book` is given up ONLY while the role's process works; the lock is back (exactly once, even on an exception)
                # before `clear_in_flight` below, which runs under it
                with self.unbooked(dispatch):
                    out, err = proc.communicate(input=prompt)
                # B1: a session the interrupt killed returns here as a plain result; it is never classified, booked or retried.
                # What it leaves is the serial road's own record of a Ctrl-C: a `launched` row with no end row.
                self.stop_if_interrupted()
            except BaseException:
                proc.kill()
                raise
            finally:
                stop.set()
                if watcher is not None:
                    watcher.join(timeout=5)
                self.clear_in_flight(dispatch)
                if chain is not None:
                    chain.proc = None
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)

    def timed(self, step: str, dispatch: str = "", stage: str = ""):
        """`with self.timed("bind", dispatch, stage):` - one line in `state/driver-timings.jsonl` when the block ends by any road (t-1937
        P2-1). `time.monotonic` for the seconds, `_now()` for the ts; a block that raises still writes its line, with `error: <type>`; the
        exception passes through. The returned object's `.dispatch` may be set inside the block."""
        import driver_timing
        return driver_timing.Timer(self.timing_write, step, dispatch, stage)

    def timing_write(self, step: str, seconds: float, *, dispatch: str = "", stage: str = "", error: str = "") -> None:
        """The ONE writer of `state/driver-timings.jsonl`: one line, one append (`hooklib.append_jsonl_line`, an O_APPEND write under a
        lock - no read-modify-write, so chains writing at once do not lose a line). The console says `note: <step> took N s` only over 20 s,
        flushed (FR-43). A line that cannot be written is said in one note and never stops the run (P1)."""
        import driver_timing
        try:
            stage = stage or str(self.boundary or "").split(":")[0]
            line = driver_timing.row(_now(), stage, dispatch, step, seconds, error)
            hooklib.append_jsonl_line(self.state_dir / driver_timing.CARRIER, json.dumps(line, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            driver_timing.console(f"note: the timing of {step} could not be written ({type(exc).__name__})")
        if seconds > driver_timing.NOTE_OVER_S:
            driver_timing.console(f"note: {step} took {seconds:.0f} s")      # the original stdout: a redirect_stdout window loses nothing

    def mark_in_flight(self, dispatch: str, pid: int, resume: str = "") -> None:
        if not dispatch:
            return
        entry = {"dispatch_id": dispatch, "pid": pid, "started_at": _now()}
        if resume:
            entry["session_id"] = resume
        try:
            self.state.setdefault("in_flight", {})[dispatch] = entry
            self.save_state()
        except OSError:
            pass

    def clear_in_flight(self, dispatch: str) -> None:
        held = self.state.get("in_flight")
        if not dispatch or not isinstance(held, dict) or dispatch not in held:
            return
        held.pop(dispatch, None)
        if not held:
            self.state.pop("in_flight", None)      # no entry, no key: a state with nobody in flight reads as before
        try:
            self.save_state()
        except OSError:
            pass

    def run_claude(self, kind: str, prompt: str, *, role: str = "", dispatch: str = "", stage: str = "",
                   resume: str = "", tools: str = ROLE_TOOLS, system_file: Path | None = None,
                   max_turns: int = 0, plugin_agent: bool = True, resume_key: str = "",
                   resume_reason: str = "") -> dict:
        """One `claude -p` call, and the ONE place an infrastructure failure of it is recognised.

        POSITION INVARIANT (B-012): the classifier runs right after the process exits, before the
        journal line, before the session is stored and before anything is returned, so that no
        caller - `digest_of`, `exit_errors`, the conductor's `last_json_line`, the S8 delivery -
        ever holds an auth, limit or transient result: TP1-13877 read a login error as a
        handoff that was "not in the form", resumed the role on it, called the conductor with it and
        asked the person about it. What comes back is the role's own answer, or a failure no row of
        `driver-infra.json` knows (`unclassified`, exactly as before); the rest raises `InfraStop`.

        `resume_key` names a call that is not a role's dispatch but must be continued the same way
        (`S8:delivery`); a role's own call is keyed by its dispatch. A key with an `interrupted`
        record means the earlier call of that key was cut off: the caller's own resume wins, else the
        session that did work is resumed with the note alone, else a fresh session gets the note
        after the prompt. A transient failure is retried in here, at most twice, by
        `runtime_policy.retry_decision`: a retry is the same call, not a new attempt, so it is never
        counted by `guarded`, the handoff resumes or the conductor's calls.

        `resume_reason` (t-342, B-273): why the CALLER resumes the role's session, in one short line. Every resume
        of a role prints `resume <dispatch>: <reason>` and writes the same words as `resume_reason` into the
        `driver-runs.jsonl` row (a row of a call that is not a resume carries no such key, and a row from before this
        field reads as it always did). A resume the driver itself chooses in here (the session of a call the service
        cut off; a retry after a broken response) names its own reason. A caller that names none gets
        `unclassified (the call named no reason)` - never a silent resume."""
        if not self.claude:
            raise Stop(EXIT_ERROR, f"no `{self.host}` executable on PATH and STORY_RUN_{self.host.upper()} is not set")
        import infra_failure
        import runtime_policy
        key = resume_key or (dispatch if kind == "role" else "")
        interrupted = self.state.setdefault("interrupted", {})
        prior = interrupted.get(key) if key and isinstance(interrupted.get(key), dict) else None
        original_prompt = prompt
        attempt_resume, attempt_prompt, driver_resumed = resume, prompt, False
        why = (resume_reason.strip() or "unclassified (the call named no reason)") if resume else ""
        if prior:
            if resume:
                note = self.continuation_note(kind, role, stage, dispatch, alone=False, known=True)
                attempt_prompt = prompt + ("\n\n" + note if note else "")
            elif prior.get("worked") and prior.get("session_id"):
                attempt_resume, driver_resumed = str(prior["session_id"]), True
                attempt_prompt = self.continuation_note(kind, role, stage, dispatch, alone=True, known=True)
                why = "an earlier call of this dispatch was cut off by the model service; its own session goes on"
            else:
                note = self.continuation_note(kind, role, stage, dispatch, alone=False, known=True)
                attempt_prompt = prompt + ("\n\n" + note if note else "")
        base_resume, base_prompt, base_driver_resumed, base_why = attempt_resume, attempt_prompt, driver_resumed, why
        retries_used, fresh_after_loss = 0, False
        while True:
            self.stop_if_interrupted()      # B1: before the `launched` row and the process, on every attempt of the loop
            cmd = self.claude_cmd(attempt_prompt, agent=role, resume=attempt_resume, tools=tools,
                                  system_file=system_file, max_turns=max_turns, plugin_agent=plugin_agent)
            if attempt_resume and kind == "role" and dispatch:
                print(f"resume {dispatch}: {why}", flush=True)
            started = time.time()
            # t-363 B2 (B-253 g): the call is journalled BEFORE its process starts, not only after it ends. On
            # 02.10 the driver died silently at 05:38 in the middle of a role and the journal held nothing of that
            # launch, so what was running could not be told. The `launched` row is a new KIND of the same file and
            # the same writer as the end row, never a rewrite of one: it names the call (`call`: role / conductor /
            # ...), `dispatch_id` (not `dispatch`: the readers that key on `dispatch` skip it), the stage and
            # `started_at`. It carries NO pid (there is none before the start - `in_flight` is the pid carrier,
            # written right after) and NO `session_id`, `total_cost_usd` or `exit_code`, so every reader that binds
            # sessions, prices or asks how a dispatch ended passes it by: a `launched` row with no end row after it
            # is a call that was running when the driver died, never a completed one. P1: code informs - a journal
            # that cannot be written is said in one line and never stops the call.
            codex = self.host == "codex"
            try:
                self.journal_run({"kind": "launched", "call": kind, "role": role, "dispatch_id": dispatch,
                                  "stage": stage, "started_at": _now(), "model": self.model, "retry": retries_used,
                                  **({"host": self.host} if codex else {})})
            except OSError as exc:
                print(f"note: the launch of this call could not be journalled ({type(exc).__name__}); it goes on", flush=True)
            if codex and role and not attempt_resume and not self.role_has_bash(role):
                # F-8: `codex exec` takes no tool list, so a role whose file lists no Bash runs with the host's tools,
                # and the text written to it names scripts it may not have. Run as is; the gap is named.
                self.host_note(f"{role} lists no Bash in its agent file and `codex exec` takes no tool list: it runs as is, "
                               "with the tools the Codex host gives it", dispatch=dispatch)
            sent = self.host_prompt(attempt_prompt, agent=role, resume=attempt_resume, system_file=system_file)
            done = self.launch(cmd, sent, dispatch=dispatch if kind == "role" else "", resume=attempt_resume)
            self.stop_if_interrupted()      # B1: a call the interrupt cut off is not parsed, journalled or stored
            wall_ms = int((time.time() - started) * 1000)      # t-1937 P2-4: the driver's own clock, next to the CLI's `duration_ms`
            raw = (done.stdout or "").strip()
            if codex:
                data = parse_codex_jsonl(raw, resume=attempt_resume)
                if data["noise"] or (not data["events"] and not data["result"]):
                    if data["subtype"] == "no_events":
                        # F-4: the text is the evidence of a call whose outcome is unknown; its start goes in the row.
                        said = " ".join(str(data.get("partial") or "").split())[:300]
                        what = f"the Codex stream held no event, only {data['noise']} line(s) of text: {said!r}"
                    else:
                        what = ("the Codex stream was empty" if not data["events"] and not data["result"] else
                                f"{data['noise']} line(s) of the Codex stream were not events")
                    self.host_note(what + f" (exit {done.returncode})", dispatch=dispatch)
                if not data["events"] and not data["result"]:
                    data["result"] = done.stderr or ""
            else:
                try:
                    data = json.loads(raw)
                    if isinstance(data, list):  # stream-json style: the result record is last
                        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), {})
                    if not isinstance(data, dict):
                        raise ValueError("not a result object")
                except ValueError:
                    data = {"result": raw or done.stderr, "is_error": done.returncode != 0}
            cost, cost_basis, call_cost = data.get("total_cost_usd"), "", None
            if codex:
                # `total_cost_usd` has ONE meaning in every row of every host: the running total of the thread
                # (`driver_journal` reads it so). The CLI reports no price, so the call's own price is worked out
                # (`codex_call_cost`) and ADDED to the thread's earlier rows; the call's price alone is `call_cost_usd`.
                call_cost, cost_basis = codex_call_cost(data.get("usage") or {}, self.model, self.config.get("cost")) \
                    if data["events"] else (None, f"price unknown: the Codex stream carried no usage for {self.model}")
                before = self.thread_total(str(data.get("session_id") or ""))
                cost = codex_running_total(before, call_cost)
                if call_cost is None and before is not None:
                    cost_basis += f"; the thread's total of ${before:.4f} does not include this call"
                print(f"cost {dispatch or kind}: " + (f"${call_cost:.4f} ({cost_basis})" if call_cost is not None else cost_basis), flush=True)
            result = {"session_id": str(data.get("session_id") or ""), "result": str(data.get("result") or ""),
                      "num_turns": data.get("num_turns"), "total_cost_usd": cost,
                      "duration_ms": data.get("duration_ms", int((time.time() - started) * 1000)),
                      "is_error": bool(data.get("is_error")) or done.returncode != 0, "exit_code": done.returncode,
                      "stderr": (done.stderr or "")[-1500:], "subtype": str(data.get("subtype") or ""),
                      # Codex only: a Claude result and its journal row are as they were (the `usage` object of a
                      # `claude -p` record is not copied into them). The usage counts are kept whatever the price says.
                      **({"usage": data.get("usage") or {}, "cost_basis": cost_basis, "call_cost_usd": call_cost} if codex else {})}
            infra = infra_failure.classify(result, self.infra_rules, self.host)
            self.journal_run({"kind": kind, "role": role, "dispatch": dispatch, "stage": stage,
                              "session_id": result["session_id"], "num_turns": result["num_turns"],
                              "total_cost_usd": result["total_cost_usd"], "duration_ms": result["duration_ms"], "wall_ms": wall_ms,
                              "resumed": bool(attempt_resume), "exit_code": done.returncode,
                              "is_error": result["is_error"], "model": self.model,
                              "subtype": result["subtype"], "infra": infra["kind"] if infra else None,
                              "infra_rule": infra["rule"] if infra else None, "retry": retries_used,
                              **({"host": self.host, "usage": result["usage"], "cost_basis": cost_basis,
                                  "call_cost_usd": call_cost} if codex else {}),
                              **({"resume_reason": why} if attempt_resume else {})})
            import driver_timing
            wall_said = driver_timing.wall_note(dispatch or kind, wall_ms, result["duration_ms"])
            if wall_said:
                driver_timing.console(wall_said)   # t-1937 P2-4: one line per call whose own count trails the wall clock by > 120 s
            # B-014, right after the journal line and before anything else sees the result. A call the
            # service cut off (`infra` set, classified or not) is not a session whose answer anyone
            # accepts: it is judged by the paths that already handle it, and a session that never got
            # to run has no hooks to report.
            if not infra:
                self.package_check(result["session_id"], stage=stage, dispatch=dispatch)
            turns = result["num_turns"]
            worked = isinstance(turns, int) and turns > 1
            if infra and infra["kind"] == "unclassified" and driver_resumed and not worked and not fresh_after_loss:
                # A resume the driver chose came back failed after one turn or none: the session is
                # gone (or was never there). ONE fresh attempt with the whole prompt; what it says
                # goes back like any failure of a call.
                note = self.continuation_note(kind, role, stage, dispatch, alone=False, known=True)
                attempt_resume, driver_resumed, fresh_after_loss = "", False, True
                attempt_prompt = original_prompt + ("\n\n" + note if note else "")
                why = ""
                continue
            if infra and infra["kind"] == "transient":
                decision = runtime_policy.retry_decision(infra.get("retry_code") or "", retries_used, 1)
                if decision.get("retry"):
                    delay = decision.get("delay_seconds", 0)
                    print(f"note: the model service answered with a broken response; the same call is tried "
                          f"again in {delay} seconds (retry {retries_used + 1} of 2)", flush=True)
                    with self.unbooked(dispatch):       # TR3-6: a backoff is waiting, not bookkeeping: the other chains go on meanwhile
                        self.sleep(delay)
                    retries_used += 1
                    if worked and result["session_id"]:
                        attempt_resume, driver_resumed = result["session_id"], True
                        attempt_prompt = self.continuation_note(kind, role, stage, dispatch, alone=True,
                                                                known=bool(prior))
                        why = (f"the model service broke the response (retry {retries_used} of 2); the session "
                               "that did the work goes on")
                    elif base_driver_resumed:
                        # The retry falls back to what step (a) chose: the recorded session that did work,
                        # with the note alone - not to a fresh session that would lose it.
                        attempt_resume, driver_resumed, attempt_prompt = base_resume, True, base_prompt
                        why = base_why
                    else:
                        note = self.continuation_note(kind, role, stage, dispatch, alone=False, known=bool(prior))
                        attempt_resume, driver_resumed = base_resume, False
                        attempt_prompt = original_prompt + ("\n\n" + note if note else "")
                        why = base_why if base_resume else ""
                    continue
            break
        if not infra or infra["kind"] == "unclassified":
            changed = False
            if dispatch and result["session_id"]:
                self.state["sessions"][dispatch] = result["session_id"]
                changed = True
                self.mark_host()    # F-5: the host the story's sessions belong to (absent = claude)
            if key and key in interrupted:
                interrupted.pop(key)     # the call that was cut off has been answered: its record leaves
                changed = True
            if changed:
                self.save_state()
            return dict(result, infra=infra)
        # auth, limit, or a transient failure that outlived its retries. The dispatch is NOT stored as
        # a session (a session that hit a wall is not the role's answer) and nothing is saved as a
        # reusable result; what is kept is the fact that this call was cut off, and how far it got.
        if key:
            record = self.interruption(infra, result, kind=kind, stage=stage, role=role, dispatch=dispatch)
            if prior and prior.get("worked") and prior.get("session_id") and not record["worked"]:
                # The record already holds a session that did real work and this stop did none (a login
                # that fails at one turn, a broken answer at one turn): that says nothing about the
                # session, and overwriting the record would make the next rerun start fresh and lose it
                # (13877 rows 2-3: the same session id, resumed, one turn). Only what failed and when is
                # refreshed.
                record.update(session_id=prior["session_id"], num_turns=prior.get("num_turns"), worked=True)
            interrupted[key] = record
            if record.get("session_id"):
                self.mark_host()                      # F-5, as above: a cut-off call's session belongs to this host too
            self.save_state()
        raise InfraStop(infra["kind"], self.infra_message(infra, attempts=retries_used + 1))

    @staticmethod
    def interruption(infra: dict, result: dict, *, kind: str, stage: str, role: str, dispatch: str) -> dict:
        """The record of a call an infrastructure failure cut off: what failed, the session it left, and
        whether that session did real work (more than one turn, and an id to resume it by). The same
        shape is written when a result saved by an older driver turns out to be such a failure."""
        turns = result.get("num_turns")
        session = str(result.get("session_id") or "")
        return {"kind": infra["kind"], "rule": infra.get("rule") or "", "session_id": session, "num_turns": turns,
                "worked": isinstance(turns, int) and turns > 1 and bool(session), "call": kind, "stage": stage,
                "role": role, "dispatch": dispatch, "reset": infra.get("reset") or "", "at": _now()}

    def retire_infra_result(self, saved: Path, result: dict, *, role: str, stage: str, dispatch: str) -> bool:
        """A result this driver saved before B-012 may be an infrastructure failure (the 13877 S3 file:
        a Cloudflare page, 29 turns). It is set aside as `<dispatch>.infra.json`, recorded as the
        dispatch's interruption, and treated as absent: the caller runs the role again, and
        `run_claude` continues the session that worked. False when the result is the role's own (or a
        failure no row knows), which is reused exactly as before."""
        import infra_failure
        infra = infra_failure.classify(result, self.infra_rules)
        if not infra or infra["kind"] == "unclassified":
            return False
        saved.replace(saved.with_name(saved.stem + ".infra.json"))
        self.state.setdefault("interrupted", {})[dispatch] = self.interruption(
            infra, result, kind="role", stage=stage, role=role, dispatch=dispatch)
        self.save_state()
        print(f"[{stage}] {dispatch}: the saved result is a {infra['kind']} failure of the service, not the "
              f"role's answer - set aside as {saved.stem}.infra.json; the role continues", flush=True)
        return True

    # --- what an interrupted call is told, and what the person is told ------------------------

    GENERIC_NOTE = ("Your previous attempt was cut by an infrastructure failure, not by anything you did; "
                    "check what you already did before repeating it, then finish and answer in the form asked.")

    def role_has_bash(self, role: str) -> bool:
        """Does the role's own agent file carry Bash? Unknown role, unreadable file or no `tools:` line: no -
        the one default of every text written to a role (`host_adapter.role_tools`, which reads the line): a door
        the role cannot use is a trap (FR-2), the note names scripts only to a role whose line lists Bash, and
        Edit, the door it names otherwise, is in every role's tools."""
        from host_adapter import role_has_bash
        return role_has_bash(role, self.plugin)

    def written_outputs(self, role: str, stage: str, dispatch: str) -> list:
        """What the role of this stage had already written when its call was cut off: the stage's outputs
        (references/stages.json) whose writer in references/artifact-writers.json is this role, that
        exist - path and bytes, a directory as its file count - plus its handover form."""
        import hooklib
        registry = hooklib.load_ref_json("artifact-writers.json").get("artifacts") or {}
        try:
            outputs = (self.stages().get(stage) or {}).get("outputs") or []
        except Exception:
            outputs = []
        found = []
        for name in outputs:
            entry = registry.get(name)
            if not isinstance(entry, dict) or entry.get("writer") != f"{role} (the role)":
                continue
            path = (self.project / name[len("project:"):]) if name.startswith("project:") else (self.task_root / name)
            if path.is_dir():
                count = sum(1 for p in path.rglob("*") if p.is_file())
                if count:
                    found.append(f"{name} ({count} file{'s' if count != 1 else ''})")
            elif path.is_file():
                found.append(f"{name} ({path.stat().st_size} bytes)")
        form = self.task_root / "work" / "handoffs" / f"{dispatch}.yaml"
        if dispatch and form.is_file():
            found.append(f"work/handoffs/{dispatch}.yaml ({form.stat().st_size} bytes)")
        if dispatch:
            import handoff_check                                   # the one rule for the name of the words waiting beside a form
            values = handoff_check.sibling_values(form)            # the role's words waiting to be applied (SC1-2, F9)
            if values.is_file():
                found.append(f"work/handoffs/{values.name} ({values.stat().st_size} bytes)")
        return found

    def continuation_note(self, kind: str, role: str, stage: str, dispatch: str, *, alone: bool, known: bool) -> str:
        """What a cut-off call is told when it goes on. `alone`: the note is the whole prompt of a resumed
        session (so it ends in the handoff form the role owes); otherwise it follows the original
        prompt. `known`: an `interrupted` record exists. Nothing to say - no outputs on disk, no
        record, not alone - is no note at all: a first call that failed after one turn has nothing to
        continue, and the prompt goes again as it was."""
        if kind != "role":
            return self.GENERIC_NOTE if (alone or known) else ""
        lines = self.written_outputs(role, stage, dispatch)
        if not lines and not (alone or known):
            return ""
        text = ("Your previous attempt at this dispatch was cut by an infrastructure failure, not by anything "
                "you did: this is the same dispatch with the same inputs.")
        if lines:
            text += "\nWhat you had already written:\n- " + "\n- ".join(lines) + "\n"
            if self.role_has_bash(role):
                text += (f"Continue them: keep what parses and passes its check (the plan: `python "
                         f"{self.scripts}/planning_contract.py --kind plan`), repair stale rows "
                         f"(`python {self.scripts}/plan_row.py --task {self.task} --row <id> --set <field>=<value>`), "
                         "add the rest (`--add-row`); set a file aside with `python "
                         f"{self.scripts}/artifact_supersede.py --task {self.task} --path <file> --role {role} "
                         "--reason \"<why nothing in it is usable>\"` only when nothing in it is usable.")
            else:
                text += ("Continue them: keep what parses and passes its check, repair what is stale with Edit "
                         "(one row's own lines, several Edit calls in one turn) and add the rest the same way; "
                         "do not write again whole a file that already holds rows.")
        if alone:
            text += "\n\nYour final message is the handoff form only:\n" + HANDOFF_FORM
        return text

    def continue_command(self, drop_absent=()) -> str:
        """The command that goes on after a stop: the story, the project and every flag this run was
        started with that differs from its default - a rerun with fewer flags is a different run
        (S0 reads `--mr` and the rest; `--until` would run past the gate). `--answer <file>` only while
        the question it answers is still open: an answer already taken is refused as "no question is
        open" when it is offered again. `drop_absent` (t-2181 PC-7 F7): the sides a story WAITS for - their `--side <s>=absent` pair is
        left out, so the packet's restart line (`... --branch <the branch with the code>`) never says a side is absent and real in one
        command; every other pair is repeated as before."""
        ns = self.flags

        def q(value) -> str:
            text = str(value)
            return f'"{text}"' if (not text or re.search(r"\s", text)) else text

        parts = ["python", f'"{self.scripts / "story_run.py"}"', "--task", q(self.task), "--project", f'"{self.project}"']
        if getattr(ns, "plugin_dir", None):
            parts += ["--plugin-dir", q(ns.plugin_dir)]
        if self.host == "codex":
            if self.model_explicit:                  # unnamed, the data's default is read again by the rerun
                parts += ["--model", q(ns.model)]
        elif str(getattr(ns, "model", "") or "sonnet") != "sonnet":
            parts += ["--model", q(ns.model)]
        if getattr(ns, "host", None):                # named by the flag (E-15): a rerun goes on in the same host, `claude` too
            parts += ["--host", q(ns.host)]
        if getattr(ns, "until", None) not in (None, "", "end"):
            parts += ["--until", q(ns.until)]
        for attr, flag in (("mr", "--mr"), ("branch", "--branch"), ("commit", "--commit"),
                           ("ticket_file", "--ticket-file"), ("env", "--env"), ("branch_suffix", "--branch-suffix")):
            if getattr(ns, attr, None):
                parts += [flag, q(getattr(ns, attr))]
        for attr, flag in (("side", "--side"), ("reference", "--reference")):      # t-2181 PC-7: pairs, repeated, as the launch gave them
            for name, word in getattr(ns, attr, None) or ():
                if attr == "side" and word == "absent" and name in drop_absent:
                    continue
                parts += [flag, q(f"{name}={word}")]
        if getattr(ns, "ungrounded", False):
            parts.append("--ungrounded")
        if getattr(ns, "no_trace", False):
            parts.append("--no-trace")
        # `--skip-sources` is NOT repeated: S0 keeps it in `launch` (`s0()`), and a story that is past S0
        # meets the flag on a command line only as the person's own late word, which asks (`skip_sources_late`).
        bound = getattr(ns, "max_boundaries", None)
        if bound not in (None, "") and int(bound) != 80:      # 0 is a value: it runs no stage after S0
            parts += ["--max-boundaries", str(int(bound))]
        if getattr(ns, "answer", None) and self.state.get("asked"):
            parts += ["--answer", q(ns.answer)]
        return " ".join(parts)

    def infra_message(self, infra: dict, *, attempts: int) -> str:
        """What the person reads when the infrastructure stopped the driver: what happened in plain
        words - owner the environment, nothing about the story wrong or lost - then the ONE block where
        a command is allowed to appear (references/human-questions.md, rule 5). Nothing is asked: the
        block says there is nothing to answer, and gives the command that goes on."""
        kind = infra["kind"]
        if kind == "auth":
            body = ("The model service would not let the factory in: this machine is not logged in to it, so "
                    "the step that was running could not start. Nothing about the story is wrong and nothing "
                    "was lost; the step goes on from where it stopped once you are logged in.")
            todo = "log in to the model service on this machine"
        elif kind == "limit":
            reset = str(infra.get("reset") or "").strip()
            body = ("The model service says this account has reached its usage limit, and "
                    + (f"it names this reset time: {reset}." if reset else "the service named no reset time.")
                    + " Nothing about the story is wrong and nothing was lost; the step that was running "
                      "goes on from where it stopped.")
            todo = "wait for the limit to reset" + (f" ({reset})" if reset else "")
        else:
            body = ("The model service returned a broken response"
                    + (f" {attempts} times in a row" if attempts > 1 else "")
                    + ", so the step that was running could not finish. This is the service's fault, not the "
                      "story's: nothing about the story is wrong and nothing was lost; the step goes on from "
                      "where it stopped.")
            todo = "wait a few minutes for the service to recover"
        block = f"\n## How to answer\nNothing to answer: {todo}, then run:\n  {self.continue_command()}"
        if kind == "auth":
            if self.env_removed:
                block += ("\nThe driver started the model without these variables of this shell, which may point at "
                          "a host proxy that gives a child process no token: " + ", ".join(self.env_removed) + ".")
            block += ("\nIf you sign in through a gateway or an API key on purpose, list the variables the model "
                      "must keep as `driver.child_env.keep` in qa-factory/config.json.")
        return body + "\n" + block

    def s1_has_no_diff(self) -> bool:
        """Does the scout's context manifest say that no change was found (`implementation.source` / `implementations[].source`
        / `implementation_source` is `none`)? ONE reader (`handoff_check.manifest_impl_source`). Error direction: a manifest that is
        absent or unreadable is False - a misread never invents a special question."""
        try:
            import handoff_check
            return handoff_check.manifest_impl_source(_read_json(self.task_root / "work" / "context-manifest.json")) == "none"
        except Exception:
            return False

    # --- a closed question with its prices (C1-3; references/human-questions.md item 6) ---------------------------

    def priced_section(self, key: str, options: list) -> Priced:
        """"## What each answer costs and does" for the question `key` of references/question-prices.json: `options` are
        `[{answer, token|None, says[, slots]}]` from the site (the words stay in code: they carry names), the three price lines
        come from the data row of each `answer` (`NM.priced_options`, the one resolution). Data or labels that cannot be read:
        the option lines are shown WITHOUT price lines and ONE `defect_found` (owner: factory) says why - a question is never
        withheld for its prices (FR-41)."""
        try:
            verdicts = (hooklib.load_ref_json(NM.VERDICTS_FILE) or {}).get("words") or {}
            priced = NM.priced_options(key, options, NM.data(), verdicts)
            return Priced(NM.render_options(priced, human_text.price_labels()), [o["token"] for o in priced if o["token"]])
        except (NM.DataUnreadable, human_text.LabelsUnreadable) as exc:
            said = f"the prices of the question `{key}` could not be read ({exc}); it was shown without its price lines"
            if self._price_notes is None:
                self.file_defect(self.boundary, f"owner: factory — {said}")
            else:               # inside the seam's fallback: ONE defect per failure, and this reason joins its note (G8)
                self._price_notes.append(said)
            return Priced(NM.render_options([{"token": o.get("token"), "says": str(o.get("says") or "").strip()} for o in options], []))

    def closed_question(self, key: str, lead: str, options: list) -> Priced:
        """The lead, then the priced section of `key` (`priced_section`). The text carries its `priced` tokens."""
        section = self.priced_section(key, options)
        return Priced(str(lead).rstrip() + "\n\n" + section, section.priced)

    # The move each token of a SITE's closed question carries when the site raises it as a seam question (C1-6b, A7): `retry` /
    # `go on` / `stop` are the seam's own moves (`NM.TOKEN_MOVES`, the one table); `by hand` passes the same block as `go on` (its
    # typed record is the site's); `reapprove` is a word only the site reads (`site_door`).
    SITE_MOVES = {**NM.TOKEN_MOVES, "by hand": "go_on_as_is", "reapprove": NM.SITE_DOOR}

    def site_seam_person(self, kind: str, text: "Priced", stage: str, *, block: str = "", details: str = "", answer_note: str = "") -> "Person":
        """A site's own closed question (`text` from `closed_question`) as a SEAM question (A7): the Person carries the tokens the
        text priced, each with its move (`SITE_MOVES`), and the block code knows, so `ask()` writes them into `asked` and
        `take_seam_answer` carries out `retry` / `go on` / `stop` with the seam's own executors."""
        tokens = [token for token in getattr(text, "priced", ()) if token in self.SITE_MOVES]
        person = Person(kind, text, stage, details=details, answer_note=answer_note)
        person.offered = tuple(tokens)      # the SITE_MOVES keys are already the normalized tokens (lower case, one space)
        person.options = [{"token": token, "move": self.SITE_MOVES[token]} for token in tokens]
        person.block = block
        return person

    def file_defect(self, ref: str, notes: str) -> None:
        """One `defect_found` row of the driver's own. `log_append` requires `--ref`: the dispatch the failure belongs to, else the
        boundary (never empty). T2 (C1-7b): a rejected write is said once on stderr WITH the rejection's own words (N12b of
        test_no_move_seam_n2b_n15 pins that line, which `py_trace` does not print) and journalled as `trace_failed` in driver-runs.jsonl,
        and the run goes on: the journal never stalls it."""
        code, out = self.py("log_append.py", "--event", "defect_found", "--task", self.task, "--by", "driver",
                            "--ref", ref or self.boundary, "--notes", notes)
        if code:
            print(f"defect_found not recorded (log_append exit {code}): {' '.join(out.split())[:300]}", file=sys.stderr)
            self.journal_run({"kind": "trace_failed", "script": "log_append.py", "exit": code,
                              "why": "the defect filer cannot file its own failure; the failure goes to driver-runs.jsonl"})

    def py_stdout(self, script: str, *args, echo: bool = True, timeout: float | None = None) -> tuple:
        """(exit code, stdout, stderr) of one factory script, the two streams kept apart.

        `py()` glues them, which is right for a refusal that a person or a conductor reads and
        wrong for a script whose stdout is a contract (FR-14): the snapshot was written from the
        glued text. stderr is printed here - it is the driver's log - and is never part of what
        the caller writes to a file.

        `timeout` (seconds, B-364 R15): None, the default, is no ceiling - every caller that passes none is
        byte-identical to what it was. The freshness calls pass one, because a tracker that never answers must not
        hold a resumed story without a word; a script that does not finish says so as `py` does, exit 124 (as
        `timeout(1)`) and an empty stdout, so the caller reads it as "nothing was said", never as a result."""
        path = self.scripts / script
        try:
            done = subprocess.run([sys.executable, "-B", str(path), *[str(a) for a in args]],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  cwd=str(self.project), env=self.env, timeout=timeout)
        except subprocess.TimeoutExpired:
            return 124, "", f"{script} did not finish within {timeout} seconds"
        if echo and done.stderr.strip():
            print(done.stderr.strip())
        return done.returncode, done.stdout, done.stderr

    def s5_window_files(self, cases) -> set:
        """The project-relative test files (`window_files.key_of` keys) of a window: the claims it holds, and the `tests[].file` of the
        manifest rows that cover one of its cases (and the files such a row was generated from). The launch gate's one reader. An
        unreadable manifest is the claims alone (the guard still stands)."""
        import window_files
        from probe_debt import bare_case_id
        found = set(window_files.files_of(self.task_root, window_files.window_id("S5", cases)))
        try:
            import contract as C
            import proof_level as PL
            manifest = C.load_json(C.artifact(self.task_root, "automation-manifest.json"))
            mine = {bare_case_id(c) for c in cases if bare_case_id(c)}
            for test in C.manifest_tests(manifest) if isinstance(manifest, dict) else []:
                if mine & {bare_case_id(c) for c in C.manifest_test_links(test)}:
                    generated = test.get("generated_from")
                    for name in [PL.test_file_of(test)] + ([f for f in generated if isinstance(f, str)] if isinstance(generated, list) else []):
                        if name:
                            found.add(window_files.key_of(name.replace("\\", "/").strip("/")))
                    from probe_debt import record_files      # t-2180 B: what a replay of the row's recorded probe mutates
                    for name in record_files(self.task_root, test):
                        found.add(window_files.key_of(name.replace("\\", "/").strip("/")))
        except Exception:       # noqa: BLE001 - the claims stand alone
            pass
        return found

    # a script that must say something before the story can go on, and the seconds it has to say it (see `py`)
    PY_TIMEOUTS = {"check_delivery.py": 600}
