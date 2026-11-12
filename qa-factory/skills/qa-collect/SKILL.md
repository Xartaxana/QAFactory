---
name: qa-collect
description: >-
  Pack the QA factory's records of this project (what ran, where it stalled, what it cost, and your own
  words about it) into one file you send to the factory's developers. Asks two questions in one message,
  runs one packing command, changes nothing in your stories. Trigger phrases: "collect the factory's
  records", "send the factory data to its developers", "qa collect", "/qa-factory:qa-collect".
metadata:
  author: Xartaxana
  version: "0.10.0"
allowed-tools:
  - Bash
  - Write
---

# qa-collect

Run from the project folder that holds `qa-factory/config.json`. The installed root is `CLAUDE_PLUGIN_ROOT` when it holds
`scripts/hooklib.py`; if the variable is empty, it is this skill's folder two levels up (an empty variable is not a missing
installation). No agent packs anything: you ask, write the words down, run ONE command, show its summary.

1. Start: `"${CLAUDE_PLUGIN_ROOT}/hooks/run-py.cmd" activity_capture.py --action start --type collect`.
   If it prints `ACTIVITY NOT RECORDED`, go on and add `--activity-not-recorded` in step 4.
2. Send ONE message with exactly this text, and nothing else:

> Before I pack the factory's records for its developers, two questions — answer either, both or neither, in your own words:
> 1. What problems did you have with the QA factory since it was installed (or since the factory last packed them)?
> 2. What would you like the factory to do differently or better?
> Answering costs you only this message; the factory then runs one packing command, no agent works; your stories are unchanged.
> ## How to answer
> reply with your two answers, or "nothing to add".

   Nobody to ask (a run with no person): skip steps 2 and 3 and add `--not-asked` in step 4.
3. Write each answer WORD FOR WORD with Write, a new file each run: `qa-factory/state/words/collect-problems-<stamp>.txt` and
   `qa-factory/state/words/collect-suggestions-<stamp>.txt`; `<stamp>` is the time now as `yyyymmddThhmmss`, the same for both
   (a name that exists already: add `-2`). Never overwrite or delete a words file. Do not shorten, sort or judge the words.
   - An answer that was left out, or is "nothing to add": write no file for it and leave its option out.
   - One text that does not divide into the two answers: write it whole as the problems file, write no suggestions file, and add
     `--answers-not-split` in step 4.
4. ONE Bash, with only the options whose file you wrote in step 3 of THIS run (never a file of an earlier run):
   `"${CLAUDE_PLUGIN_ROOT}/hooks/run-py.cmd" collect_pack.py --root . --problems-file <problems file> --suggestions-file <suggestions file>`
   - If the output or a refusal names `--extra <SET>=` (a line `<SET>: not found at the standard place`), ask where that data
     lives and run it again with `--extra <SET>=<path inside the project>`. Nothing else is searched for.
   - To pack everything since the install again, add `--since install`.
   - Any other refusal (exit 1) is shown to the person as printed. Do not work around it, do not edit the packing rules.
5. Show the summary of the last run, as printed. Right before your final response:
   `"${CLAUDE_PLUGIN_ROOT}/hooks/run-py.cmd" activity_capture.py --action end --type collect --after-response`.

The person sends the file named in the summary to the QA factory developers themselves; nothing is sent from here.
