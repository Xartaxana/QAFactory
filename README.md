# QA Factory

QA Factory is a Claude Code plugin for ticket-driven functional testing with two human gates. It reads a
ticket and its change, derives the requirements, plans and writes the tests, runs them, analyses the
failures and reports what is proved and what is left with you.

This repository carries the released plugin only. The package lives in `qa-factory/`; its own
`README.md`, `INSTALL.md`, `UPGRADE.md` and `CHANGELOG.md` are the documentation.

## Install

```
claude plugin marketplace add Xartaxana/QAFactory
claude plugin install qa-factory@qafactory
```

Then follow `qa-factory/INSTALL.md`. To update an installed plugin, see `qa-factory/UPGRADE.md`.

## Releases

Every release is a tagged version (`vX.Y.Z`) with the matching section of `qa-factory/CHANGELOG.md`.
The `package-check` workflow runs the package's own self-test and install smoke test on every push,
pull request and tag.

## License

Apache-2.0, see `LICENSE`.
