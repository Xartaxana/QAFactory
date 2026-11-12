# Fixtures of test_grounding_table.py

The test builds every story it needs in a temporary project from text it writes itself (a unified diff made by `hunk()` /
`section()` / `diff_text()`, a seven-line register, an optional context manifest), so this folder holds no data file.

The one real input is `experiments/TP1-13877/` (the 13877 run: 19 files, 35 hunks plus one pseudo-hunk, a manifest with three
entries under the key `repo`, two of them with a null `diff_path`). The test copies it into a temporary project and never edits
it; when the experiment folder is absent from the tree (a package-only install) the 13877 pins are skipped and the synthetic ones
still run.
