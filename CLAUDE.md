# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
make check       # full CI check: validate + test
make validate    # structural validation only (no Meta CLI needed)
make test        # unit tests only
```

Run a single test:
```bash
python3 -m unittest tests.test_check_meta_ads_cli.CheckMetaAdsCliTests.test_succeeds_when_meta_help_commands_work
```

No dependencies beyond Python's standard library.

## Architecture

This repo packages a **terminal agent skill** for Meta Ads CLI workflows. The skill directory (`meta-ads-cli/`) is symlinked or copied into `~/.claude/skills/` (Claude Code) or `~/.codex/skills/` (Codex) to install it.

```
meta-ads-cli/         The installable skill package
  SKILL.md            Skill entry point: front matter + operating model for Claude/Codex
  agents/openai.yaml  OpenAI agent prompt surface
  references/
    command-patterns.md  Workflow templates (Plan/Preview/Apply, audit, spec file, etc.)
  scripts/
    check_meta_ads_cli.py  Runtime diagnostic (checks Python ≥3.12, meta binary, help commands)

scripts/
  validate_repo.py    CI structural checks; no Meta CLI required

tests/
  test_check_meta_ads_cli.py  Unit tests for the diagnostic script; all subprocess calls are mocked
```

## Structural Constraints (enforced by validate_repo.py)

**`meta-ads-cli/SKILL.md`** must:
- Start with YAML front matter (`---`)
- Contain `name: meta-ads-cli` and `description:` fields
- Include the sections `## Operating Model`, `## First Checks`, and `## Workflow`

**`meta-ads-cli/agents/openai.yaml`** must match these regex patterns:
- `^interface:\s*$`
- `^\s{2}display_name:\s+.+$`
- `^\s{2}short_description:\s+.+$`
- `^\s{2}default_prompt:\s+\|$`
- Literal strings `Safety rules` and `Current docs`

**`meta-ads-cli/references/command-patterns.md`** must contain the string `Plan/Preview/Apply`.

All files listed in `REQUIRED_FILES` inside `validate_repo.py` must exist and be non-empty.
