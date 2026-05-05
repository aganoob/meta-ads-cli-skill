# Meta Ads CLI Skill

A Codex-compatible skill for operating Meta Ads through Meta's official Ads CLI.

This repository packages the skill instructions, agent prompt, safety rules, command
patterns, and a small local diagnostic script for Meta Ads and Commerce workflows.
It is intentionally dependency-light: CI validates the skill files and tests the
diagnostic script without requiring the Meta Ads CLI to be installed.

## What This Skill Covers

- Meta Ads CLI setup checks and authentication guidance.
- Account, campaign, ad set, ad, creative, catalog, and dataset/pixel workflows.
- Read-only reporting and audit patterns.
- Safe write workflows using plan, preview, approval, apply, and verify steps.
- Guardrails for spend-impacting, delivery-impacting, and activation operations.

## Repository Layout

```text
meta-ads-cli/
  SKILL.md                         Skill instructions and operating model
  agents/openai.yaml               OpenAI agent prompt surface
  references/command-patterns.md   Detailed command patterns and templates
  scripts/check_meta_ads_cli.py    Local Meta Ads CLI environment diagnostic
scripts/
  validate_repo.py                 Repository and skill validation checks
tests/
  test_check_meta_ads_cli.py       Unit tests for the diagnostic script
```

## Local Checks

```bash
make validate
make test
make check
```

`make check` is the same high-level command used by CI. It performs repository
validation and runs the unit test suite.

## Runtime Diagnostic

After installing Meta's Ads CLI locally, run:

```bash
python3 meta-ads-cli/scripts/check_meta_ads_cli.py
```

The diagnostic checks the local Python version, confirms that `meta` is on
`PATH`, and verifies that `meta --help` and `meta ads --help` are callable.

## Safety Model

The skill treats Meta Ads work as account-impacting infrastructure:

- Run read-only discovery before writes.
- Require explicit approval before changing spend, delivery, targeting,
  creatives, catalog state, dataset connections, or entity status.
- Never activate campaigns, ad sets, or ads without explicit current-turn
  approval.
- Keep AI-created entities paused unless activation is directly requested.
- Never commit or paste access tokens, app secrets, or system-user tokens.

See [meta-ads-cli/SKILL.md](meta-ads-cli/SKILL.md) for the full operating model.

## Official Meta Docs

The Ads CLI is in beta and may change. For exact install, auth, scope, and
command details, verify against Meta's current official documentation:

- https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-cli/ads-cli-overview
- https://mcp.facebook.com/ads

## License

MIT. See [LICENSE](LICENSE).
