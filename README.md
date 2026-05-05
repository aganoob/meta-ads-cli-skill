# Meta Ads CLI Skill

A Codex skill for working with Meta Ads through Meta's official Ads CLI.

This skill gives terminal agents a safe operating model for Meta Ads and
Commerce workflows: setup checks, authentication guidance, account discovery,
read-only reporting, campaign/ad set/ad/ad creative operations, catalog work,
dataset/pixel diagnostics, and cautious automation.

The repository is intentionally lightweight. It packages skill instructions,
agent prompt content, command patterns, a local diagnostic script, and a
read-only batch audit helper. CI checks the skill and tests the scripts without
requiring Meta's Ads CLI to be installed.

## Install the Skill

Clone this repository:

```bash
git clone https://github.com/aganoob/meta-ads-cli-skill.git
cd meta-ads-cli-skill
```

### Claude Code

Place the `meta-ads-cli` directory in your Claude Code skills directory:

```bash
mkdir -p ~/.claude/skills
ln -s "$PWD/meta-ads-cli" ~/.claude/skills/meta-ads-cli
```

If your setup does not follow symlinks, copy the directory instead:

```bash
mkdir -p ~/.claude/skills
cp -R meta-ads-cli ~/.claude/skills/meta-ads-cli
```

Restart Claude Code after installing. The skill will be available as
`/meta-ads-cli` and will trigger automatically for Meta Ads requests.

### Codex

Place the `meta-ads-cli` directory in your Codex skills directory:

```bash
mkdir -p ~/.codex/skills
ln -s "$PWD/meta-ads-cli" ~/.codex/skills/meta-ads-cli
```

If your Codex setup does not follow symlinks, copy the directory instead:

```bash
mkdir -p ~/.codex/skills
cp -R meta-ads-cli ~/.codex/skills/meta-ads-cli
```

Restart your Codex session after installing so the new skill can be discovered.

## Install Meta Ads CLI

This repository does not vendor or install Meta's CLI. Install and authenticate
Meta Ads CLI from Meta's current official documentation:

- https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-cli/ads-cli-overview
- https://mcp.facebook.com/ads

The Ads CLI is in beta and may change. For exact install commands, auth flows,
scopes, and flags, prefer the current official docs and your local CLI help:

```bash
meta --help
meta ads --help
```

## Verify Your Setup

Run the repository checks:

```bash
make check
```

After installing Meta Ads CLI, run the local runtime diagnostic:

```bash
python3 meta-ads-cli/scripts/check_meta_ads_cli.py
```

The diagnostic checks:

- Python 3.12 or newer.
- `meta` is available on `PATH`.
- `meta --help` works.
- `meta ads --help` works.

For read-only reporting, run the bundled audit helper:

```bash
python3 meta-ads-cli/scripts/meta_ads_audit.py \
  --accounts all \
  --last-days 30 \
  --preset ua-creative-audit \
  --output reports/meta_ads_audit.json
```

The audit helper enforces `META_ADS_READ_ONLY=1`, redacts CLI output, caches
stable entity and creative payloads under `.cache/meta-ads/`, keeps insights
fresh, downloads creative thumbnails once, reconciles account/campaign/ad set/ad
totals, and writes normalized JSON report tables.

## Use the Skill

Once installed, ask Claude Code or Codex for Meta Ads work in normal language.
The skill triggers automatically for requests involving Meta Ads, Facebook ads,
Instagram ads, campaign reporting, catalog diagnostics, datasets/pixels, or the
`meta ads` CLI. In Claude Code you can also invoke it directly with `/meta-ads-cli`.

Example prompts:

```text
Use the Meta Ads CLI skill to check whether my local Meta CLI setup is ready.
```

```text
List the Meta ad accounts I can access and show the account IDs only.
```

```text
Pull last 7 days campaign insights for account act_... and summarize spend,
clicks, CTR, and conversions.
```

```text
Run a 30-day Meta Ads creative audit for all accessible accounts and write a
JSON report.
```

```text
Draft a paused campaign launch plan for account act_... using Meta Ads CLI,
but do not run any write commands.
```

For writes, the skill follows a plan/preview/apply workflow: discover current
state, draft exact commands, summarize impact, ask for explicit approval, run
one command at a time, then verify final state.

## Safety Model

The skill treats Meta Ads work as account-impacting infrastructure:

- Run read-only discovery before writes.
- Ask for explicit approval before changing spend, delivery, targeting,
  creatives, catalog state, datasets, or entity status.
- Never activate campaigns, ad sets, or ads without explicit approval in the
  current conversation.
- Keep AI-created entities paused unless activation is directly requested.
- Use the narrowest available auth scope and avoid financial scope unless the
  task requires billing or payment work.
- Do not paste access tokens, app secrets, system-user tokens, or private
  account data into chat, docs, shell history, tests, or commits.
- Prefer one CLI call at a time for account-changing operations.

Read the full operating model in [meta-ads-cli/SKILL.md](meta-ads-cli/SKILL.md).

## Repository Layout

```text
meta-ads-cli/
  SKILL.md                         Skill instructions and operating model
  agents/openai.yaml               OpenAI agent prompt surface
  references/command-patterns.md   Command patterns and workflow templates
  scripts/check_meta_ads_cli.py    Local Meta Ads CLI environment diagnostic
  scripts/meta_ads_audit.py        Read-only batch audit/report helper
scripts/
  validate_repo.py                 Repository and skill validation checks
tests/
  test_check_meta_ads_cli.py       Unit tests for the diagnostic script
  test_meta_ads_audit.py           Unit tests for the audit helper
```

## Development

The harness uses Python's standard library only.

```bash
make validate
make test
make check
```

`make check` is the same high-level command used by GitHub Actions. It validates
required files, skill front matter, agent YAML shape, Python syntax, and the
diagnostic script tests.

## Contributing

Keep changes conservative and safety-focused. Documentation and examples should
avoid real tokens, account IDs, business data, or private performance exports.

Before opening a pull request:

```bash
make check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
