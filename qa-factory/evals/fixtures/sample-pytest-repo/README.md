# inventory-sample

A tiny in-memory inventory service used as the application under test in qa-factory fixtures and evals.

## Testing conventions

- Tests live in `tests/`, run with `python -m pytest -q`. One test file per module of `src/inventory`.
- Every test creates its own data through fixtures in `tests/conftest.py`; never rely on records created by another test.
- Plain `assert` statements; no assertion helper libraries.
- Each test documents the case it covers with a `TC-NNN coverage:` line in its docstring.
- Before committing run `python -m ruff check src tests`.

## Branches

`main` holds the current behaviour. Feature work arrives on `feature/<ticket>` branches with a merge request.
