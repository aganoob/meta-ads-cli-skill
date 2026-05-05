---
name: meta-ads-cli
description: "Use Meta's official Ads CLI for Meta Ads and Commerce workflows from Codex or terminal agents: setup checks, authentication guidance, account discovery, read-only reporting, campaign/ad set/ad/ad creative operations, catalog management, dataset/pixel diagnostics, and safe automation. Trigger when the user asks to inspect, report on, create, edit, pause, activate, audit, or automate Facebook/Instagram/Meta ad accounts with `meta ads` or the Meta Ads AI Connectors CLI."
---

# Meta Ads CLI

## Operating Model

Use Meta's official Ads CLI (`meta ads ...`) as the execution surface for Meta advertising work. Prefer CLI execution for repeatable workflows, local files, JSON output, scripts, CI, and agent-driven bulk operations.

Treat this tool as account-impacting infrastructure:

- Run read-only discovery first unless the user explicitly asked for a write.
- Ask for explicit approval before any write that changes spend, delivery, targeting, creatives, catalog state, datasets, or entity status.
- Never activate campaigns, ad sets, or ads without explicit user approval in the current conversation.
- Keep AI-created entities in `PAUSED` unless the user directly asks to activate them.
- Use the narrowest available auth scope and avoid financial scope unless the task requires billing/payment work.
- Do not paste access tokens, app secrets, or system-user tokens into chat, docs, shell history, or committed files.
- Prefer one CLI call at a time for account-changing operations and avoid rapid repeated edits that can reset learning or resemble abusive automation.

## First Checks

Start by checking whether the CLI is installed and usable:

```bash
meta --help && meta ads --help && echo "Setup OK"
```

If you know the skill directory path, the bundled check script runs a more detailed diagnostic including the Python version check required by Meta Ads CLI:

```bash
python3 /path/to/meta-ads-cli/scripts/check_meta_ads_cli.py
```

For read-only account audits and batch reporting, prefer the bundled audit script instead of hand-written shell loops:

```bash
python3 /path/to/meta-ads-cli/scripts/meta_ads_audit.py \
  --accounts all \
  --last-days 30 \
  --output reports/meta_ads_audit.json
```

If `meta` is missing, tell the user to install Meta Ads CLI from Meta's current official documentation. The public beta has changed quickly, so verify install/auth commands against the docs before giving exact setup instructions.

When `meta` exists, use the command templates in `references/command-patterns.md` directly for known tasks. Only run `--help` for commands or flags not covered by those templates:

```bash
meta ads campaign --help
meta ads insights --help
```

Use CLI help as the source of truth for exact flag names in the local installation, but skip it when a working template already exists.

## Workflow

1. Identify the user's intent: report, audit, create, update, pause, activate, catalog, or dataset/pixel diagnostics.
2. Determine account context. Use account-listing/config commands or the user's provided `act_...` account ID.
3. For reporting and audits, use `META_ADS_READ_ONLY=1` and prefer `scripts/meta_ads_audit.py` for batch reports; it batches reads, caches stable entities, redacts output, reconciles entity totals, and emits normalized JSON tables.
4. For writes, use the Plan/Preview/Apply pattern: discover current state, draft exact commands, summarize impact, get explicit approval, execute, and verify.
5. Run commands one at a time, inspect output, and stop on non-zero exit status.
6. Summarize results with entity IDs, statuses, changed fields, and any follow-up action the user must review in Ads Manager.

## Operational Patterns

Use these patterns to choose the right amount of structure:

- **Plan/Preview/Apply**: Use for every account-changing operation.
- **Spec File**: Use when launches, reports, or catalog changes will repeat or need review in version control.
- **Audit Report**: Use for "check my account", performance drops, tracking concerns, and read-only health checks.
- **Entity State Snapshot**: Use before and after updates to prove the minimal field change.
- **Naming And Idempotency**: Use before creates and retries to avoid duplicate campaigns, ad sets, ads, creatives, catalogs, or datasets.

See `references/command-patterns.md` for the detailed steps and templates.

## Entity Taxonomy

Use this map to choose the right command group and ask for missing IDs:

- **Account**: Ad account context, usually `act_...`; owns campaigns and billing context.
- **Campaign**: Top-level delivery container; owns objective and campaign status.
- **Ad Set**: Owns budget, schedule, targeting, optimization goal, and billing event.
- **Ad**: Binds an ad creative to an ad set for delivery.
- **Creative**: Owns media, copy, destination URL, call to action, and Page identity.
- **Page**: Public identity surface required for many ad creatives.
- **Catalog**: Ecommerce product container for commerce and catalog ads.
- **Product Feed**: Source that populates catalog products.
- **Product Set**: Filtered subset of catalog products.
- **Dataset/Pixel**: Event source for tracking, Conversions API, diagnostics, and optimization signals.

## Common Tasks

Use `references/command-patterns.md` for current command patterns, safety notes, and example prompts.

### Reporting

Prefer the bundled audit helper for account-level reporting, creative audits, wasted-spend reviews, and any request that needs campaign/ad set/ad reconciliation:

```bash
python3 /path/to/meta-ads-cli/scripts/meta_ads_audit.py \
  --accounts act_123456789 \
  --since 2026-04-06 \
  --until 2026-05-05 \
  --preset ua-creative-audit \
  --output reports/meta_ads_audit.json
```

The audit helper is read-only, wraps CLI output with redaction, avoids manual TSV parsing, caches stable entity/creative payloads, downloads creative thumbnails once, and warns when account/campaign/ad set totals do not reconcile to listed ads.

For narrow one-off checks, use insights commands with bounded dates and explicit fields. Use the global `--output json` flag (before `ads`) for machine-readable output:

```bash
AD_ACCOUNT_ID=act_123456789 meta --output json ads insights get --campaign_id CAMPAIGN_ID --date-preset last_7d --fields spend,impressions,clicks,ctr,cpc,reach,actions
```

Key rules:
- `--output json` is a global flag and must come before `ads` — not at the end of the command.
- Account scope is set via the `AD_ACCOUNT_ID` env var, not a CLI flag.
- There is no top-level `conversions` field. Request `actions` and filter by `action_type` (e.g. `purchase`, `lead`, `complete_registration`). See the Known CLI Quirks section in `references/command-patterns.md` for the full mapping.
- See `references/command-patterns.md` for copy-paste templates for common reporting tasks.

### Campaign Management

For creates and updates:

- Confirm objective, budget units, account ID, Page, creative assets, destination URL, schedule, and targeting before execution.
- Preserve paused-by-default behavior.
- For budget or status changes, repeat back the exact account and entity IDs before running.
- Do not run activation commands unless the user explicitly says to activate the named entity.

### Catalog And Dataset Work

Use catalog and dataset commands for product catalog inspection, diagnostics, product details, product set checks, pixel/dataset quality, and connection checks. Prefer read-only diagnostics before attempting fixes.

For dataset/pixel work, clarify whether the user means Meta Pixel, Conversions API dataset, or a product-catalog connection. Meta documentation often uses "dataset" for event-source/pixel surfaces.

## Output Handling

Prefer machine-readable output for agent workflows:

- `json` for parsing, summaries, diffs, and reports.
- `plain` or tab-separated output for shell pipelines.
- `table` for quick human inspection.

If command output includes sensitive account names, IDs, or business data, summarize only what is needed for the task.

## Error Handling

Stop and diagnose on non-zero exit codes. Known patterns from launch coverage:

- `0`: success
- `3`: authentication/authorization error
- `4`: Meta API error

Run `meta auth --help`, `meta config --help`, or the failed subcommand's `--help` before retrying. Do not repeatedly retry write commands without understanding whether the first call partially succeeded.

## Current-Docs Rule

The Ads CLI was announced in open beta in April 2026 and may change. When exact commands, auth setup, scopes, or supported operations matter, verify against Meta's current official docs:

- Ads CLI overview: https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-cli/ads-cli-overview
- Meta Ads MCP endpoint: https://mcp.facebook.com/ads
