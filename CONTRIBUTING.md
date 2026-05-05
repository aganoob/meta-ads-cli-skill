# Contributing

Thanks for improving the Meta Ads CLI skill. Keep changes focused on making
Meta Ads CLI work safer, clearer, and easier to verify.

## Development

Run the full local check before opening a pull request:

```bash
make check
```

The harness intentionally uses Python's standard library so contributors do not
need a package manager or Meta Ads CLI installation for repository checks.

## Skill Changes

- Keep account-changing guidance conservative.
- Prefer read-only discovery before any write workflow.
- Preserve explicit approval requirements for spend, delivery, targeting,
  creative, catalog, dataset, and activation operations.
- Do not include secrets, real access tokens, app secrets, or private account
  data in examples, tests, fixtures, or documentation.
- When exact CLI flags matter, point users to local `meta ads --help` output and
  current official Meta documentation.

## Pull Requests

Before submitting:

- Run `make check`.
- Update `CHANGELOG.md` for user-visible changes.
- Update `README.md` when public commands, repo layout, or supported workflows
  change.
