# Changelog fragments

A batch does not edit `CHANGELOG.md`. It adds one file here, and the release folds the files into the next
version section. Two developers' batches therefore never touch the same file.

## One fragment per batch

- File name: `<pile>-<batch>-<slug>.md`, ASCII, lower case, dashes only. Example: `forge-1-changelog-fragments.md`.
  Fragments are assembled in file-name order, so the pile and the batch lead the name.
- Content: the lines exactly as they will appear under the version heading, in the style of the existing sections of
  `CHANGELOG.md`: one bullet per change, `- what changed (`file.py`): why it matters; what a reader must know
  (B-nnn)`, continuation lines indented by two spaces and wrapped near 120 columns.
- No heading inside a fragment: a Markdown heading line (`#` to `######` followed by a space, or alone on the line) is refused, even inside
  a code fence; a line such as `#123 closes the gap` is not a heading and is kept. The version heading is written by
  the release, from `--version`, `--date` and `--title`.
- English, no Cyrillic character and no control byte (`selftest.py --lang` scans this folder like any package file).
  Typographic characters such as the em dash are fine. Trailing whitespace and blank lines at either end are
  normalised, not refused. An empty fragment is refused.
- `README.md` is never a fragment. Any other file here must be named `*.md` with a lower-case extension; a `.MD`, a
  `.txt` or anything else is refused by name (it would otherwise ship unseen), and `--list` shows it as
  `REFUSED <name>`.

## At release

```
python scripts/changelog_assemble.py --list
python scripts/changelog_assemble.py --version 0.9.1 --date 2026-10-15 --title "what this release is" --dry-run
python scripts/changelog_assemble.py --version 0.9.1 --date 2026-10-15 --title "what this release is"
```

The script inserts `## <version> - <date> - <title>` (em dashes) with the fragments' text right after the title block
of `CHANGELOG.md`, before the current top section, deletes the fragment files and prints the inserted section. It
refuses (exit 2, with what is wrong and how to pass) when there are no fragments, when a fragment breaks the rules
above, when a file here is not a lower-case `*.md`, when `CHANGELOG.md` already has a `## <version>` heading for the
version (a `## ` line inside a code fence does not count), when `--version` is not `N.N.N`, when `--date` is not an
ISO date, or when `CHANGELOG.md` has no title line.
`--dry-run` prints the section and writes nothing. The version bump itself (manifests, INSTALL, SKILL) is not done here.
