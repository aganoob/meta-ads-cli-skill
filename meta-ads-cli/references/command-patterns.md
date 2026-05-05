# Meta Ads CLI Command Patterns

Use this reference after `SKILL.md` when planning or executing Meta Ads CLI work. Prefer the installed CLI help over examples here when they disagree.

## Known CLI Quirks

These are confirmed behaviors that cause wasted calls if you guess wrong:

**`--output` is a global flag — place it before `ads`:**
```bash
# correct
meta --output json ads campaign list
meta --output json ads insights get ...

# wrong — fails silently or errors
meta ads campaign list --output json
meta ads campaign list -o json
```

**Scope insights by env var, not flag:**
`insights get` and similar commands do not accept `--ad-account-id` as a flag. Use the `AD_ACCOUNT_ID` environment variable:
```bash
AD_ACCOUNT_ID=act_123456789 meta --output json ads insights get --date-preset last_7d --fields spend,impressions,clicks
```
The `--ad-account-id` top-level flag also does not work for most subcommands; always prefer the env var.

**No top-level `conversions` field — use `actions`:**
`--fields conversions` returns no data. Conversions live in `actions[]` as typed entries. Request `--fields actions` and filter by `action_type`:

| Goal | `action_type` value |
|---|---|
| Purchase / sale | `purchase` |
| Lead form | `lead` |
| Registration | `complete_registration` |
| Add to cart | `add_to_cart` |
| View content | `view_content` |
| App install | `mobile_app_install` |
| Custom event | `other` or event name |

Example: count purchases from an insights response:
```bash
# parse actions[] from JSON and filter action_type == purchase
```

**Skip `--help` for commands in the cheat sheet below.** Only run `--help` for commands or flags not covered by the templates in this file.

## Safety Defaults

- Run read-only commands first.
- For reporting and audit tasks, set `META_ADS_READ_ONLY=1` or use `scripts/meta_ads_audit.py`, which enforces that mode.
- Use `meta --output json ads ...` (global flag before `ads`) when parsing output.
- Use `--no-input` only when the user already approved the exact operation.
- Use `--force` only when the user understands what prompt or safety confirmation is being bypassed.
- Keep new campaigns, ad sets, ads, and creatives paused unless the user explicitly asks otherwise.
- Avoid automated budget, audience, or creative edits more than once per 24 hours on the same ad set unless the user knowingly accepts learning-phase resets.

## Plan/Preview/Apply

Use this pattern for every write.

1. Discover current state with read-only commands and local CLI help.
2. Draft the exact command sequence without executing it.
3. Summarize account ID, target entity IDs, fields to change, spend/delivery impact, and rollback or pause plan.
4. Ask for explicit approval to run the drafted commands.
5. Execute one command at a time and stop on the first error.
6. Verify final state with a read-only fetch and summarize what changed.

Approval prompt:

```text
I am ready to run these commands against account act_... . They will change FIELD on ENTITY_ID and may affect delivery/spend. Should I execute them?
```

## Spec File Pattern

Use a local spec when a workflow needs review, repetition, or versioned history. Good candidates include campaign launches, weekly reports, bulk catalog updates, and repeated audit jobs.

Keep specs declarative and free of secrets. Include:

- Account ID, Page ID, catalog ID, dataset ID, and target entity IDs.
- Objective, budget, schedule, targeting, destination URLs, URL parameters, creative file paths, and naming convention.
- Output fields, date ranges, attribution notes, and report destination for reporting specs.
- Activation policy, usually `create_paused: true`.

Suggested file names:

```text
meta-ads-launch.spec.json
meta-ads-report.spec.json
meta-ads-catalog-update.spec.json
```

Before applying a spec, validate required IDs and fetch existing entities that match intended names.

## Audit Report Pattern

Use this for "check my account", "why is performance down", "audit my tracking", and similar read-only requests.

Default flow for batch reporting:

```bash
python3 meta-ads-cli/scripts/meta_ads_audit.py \
  --accounts all \
  --last-days 30 \
  --preset ua-creative-audit \
  --output reports/meta_ads_audit.json
```

For an explicit inclusive window:

```bash
python3 meta-ads-cli/scripts/meta_ads_audit.py \
  --accounts act_123456789 \
  --since 2026-04-06 \
  --until 2026-05-05 \
  --output reports/meta_ads_audit.json
```

`--last-days 30` includes today. For example, when today is `2026-05-05`, the 30-day inclusive window is `2026-04-06` through `2026-05-05`. Warn if a user supplies a 31-day inclusive range such as `2026-04-05` through `2026-05-05`.

The audit helper emits normalized JSON tables for accounts, campaigns, ad sets, ads, creatives, account/campaign/adset/ad insights, country/platform breakdowns, downloaded assets, warnings, and preset reports. It checks `meta ads insights get --help` once; if `--level` is supported, it uses batch level calls such as `--level ad`, otherwise it falls back to bounded per-entity calls with retry/backoff.

Use this manual flow only for small one-off reports or when the helper cannot express the request:

1. Confirm account ID and date window.
2. List active campaigns and relevant ad sets/ads.
3. Pull insights for `last_7d` and, when useful, compare with `previous_7d` or `last_30d`.
4. Inspect dataset/pixel quality and catalog diagnostics when relevant.
5. Rank findings by likely impact and confidence.
6. Recommend actions without making changes unless the user asks for a follow-up write.

Report format:

- Scope: account, date range, entity level, and fields.
- Findings: ranked issues with evidence.
- Opportunities: concrete next actions.
- Tracking/catalog notes: dataset or catalog health if checked.
- Caveats: attribution windows, currency, incomplete current-day data, and unsupported fields.

### Audit Cache Policy

The audit helper caches stable reads under:

```text
.cache/meta-ads/{account_id}/{entity_type}/{entity_id}.json
```

Each file wraps data with `_cache` metadata: `schema_version`, `cached_at`, `account_id`, `entity_type`, `entity_id`, `ttl_seconds`, `source_command`, and `redacted`.

Default TTLs:

| Entity | TTL |
|---|---:|
| ad accounts | 24h |
| campaigns, ad sets, ads | 6h |
| creatives | 7d |
| thumbnails/assets | 30d |
| insights | always fresh |

Refresh the cache when a file is missing, corrupt, expired, has mismatched metadata/schema, or when the user passes `--refresh-entities` or `--refresh-creatives`. Retain stale cache files by default for inspection, but do not trust them for fresh reads. Use `--prune-cache-days N` to delete old cache files.

### Reconciliation Rules

For audits, compare conversions through the hierarchy:

```text
account total -> campaign totals -> ad set totals -> ad totals
```

If a parent level has more purchases than the child rows explain, emit a warning such as:

```text
2 purchases are visible at ad set/campaign level but not traceable to listed ads. Possible deleted/hidden ads, attribution delay, or API visibility gap.
```

Do not hide these gaps in the final report. They are usually high-signal caveats for deleted/hidden ads, attribution timing, or API visibility limits.

### Parsing Rules

Use JSON end to end for entity and insights processing. Entity names can contain spaces, pipes, tabs, and punctuation, so do not manually parse TSV rows by splitting on whitespace or `|`.

If shell looping is unavoidable, encode each JSON row before passing it through the shell:

```bash
jq -r '.data[] | @base64' report.json | while read -r row; do
  python3 -c 'import base64,json,sys; print(json.loads(base64.b64decode(sys.argv[1]))["id"])' "$row"
done
```

Prefer Python or `jq` JSON parsing over ad hoc shell text parsing for all batch reports.

## Entity State Snapshot

Use this before updates, pauses, activations, and retries.

1. Fetch the target entity as JSON.
2. Record or summarize ID, name, status, budget, objective, schedule, targeting, creative, destination URL, and updated time when available.
3. Execute the minimal update command.
4. Fetch the entity again.
5. Compare before/after and report only the fields that changed.

If the first update command fails or times out, fetch state before retrying. Do not assume the operation was fully rolled back.

## Naming And Idempotency

Use this before creates and after failed create attempts.

- Search for existing entities with the intended name before creating a new one.
- If a match exists, ask whether to reuse, update, duplicate, or create a suffixed variant.
- Use deterministic names that encode date, offer, audience, objective, and variant where useful.
- Include stable external IDs or source spec names in labels when the CLI supports them.
- On retry, fetch matching entities first to avoid duplicates from a partially successful previous command.

Example naming shape:

```text
2026-05-05 | Spring Sale | US Broad | Sales | V01
```

## Discovery

```bash
meta --help
meta auth --help
meta config --help
meta ads --help
meta ads campaign --help
meta ads insights --help
```

Useful discovery prompts:

- "List ad accounts I can access and show IDs only."
- "List active campaigns for account `act_...` with objective, status, spend, and campaign ID."
- "Show me the local CLI help for campaign creation before drafting a command."

## Entity Mapping

Use this mapping when translating user language into CLI work:

- "Account", "ad account", "business account": resolve an `act_...` account ID before other calls.
- "Campaign": inspect or change objective, campaign-level status, and campaign grouping.
- "Ad set", "audience", "targeting", "budget", "schedule", "optimization": usually ad set work.
- "Ad", "placement of a creative", "turn this ad on/off": usually ad-level work.
- "Creative", "image", "video", "copy", "headline", "CTA", "URL": creative work, often requiring Page ID and asset path or URL.
- "Page", "Facebook page", "Instagram identity": identity/asset discovery before creative creation.
- "Catalog", "shop", "commerce catalog": catalog diagnostics, product sets, feeds, and product inspection.
- "Feed", "product feed": feed status, rules, and ingestion diagnostics.
- "Product set", "collection": subset of catalog products used by catalog ads.
- "Pixel", "dataset", "events", "CAPI", "tracking": dataset/pixel diagnostics, connection checks, and event quality.

Common ownership boundaries:

- Campaigns contain ad sets.
- Ad sets contain ads.
- Ads reference creatives.
- Creatives often reference a Page and destination URL.
- Catalogs contain products and product sets populated by feeds.
- Datasets/pixels provide event signals to accounts, catalogs, and optimization workflows.

## Common Task Templates

These are copy-paste ready for the most frequent tasks. Use them directly without running `--help` first.

**List ad accounts:**
```bash
meta --output json ads adaccount list
```

**List campaigns for an account:**
```bash
AD_ACCOUNT_ID=act_123456789 meta --output json ads campaign list
```

**7-day performance insights for a campaign:**
```bash
meta --output json ads insights get --campaign_id CAMPAIGN_ID --date-preset last_7d --fields spend,impressions,clicks,ctr,cpc,reach,actions
```

**7-day account-level insights (all campaigns):**
```bash
AD_ACCOUNT_ID=act_123456789 meta --output json ads insights get --date-preset last_7d --fields spend,impressions,clicks,ctr,cpc,reach,actions
```

**List active ad sets for a campaign:**
```bash
meta --output json ads adset list --campaign_id CAMPAIGN_ID
```

## Reporting And Insights

Common pattern:

```bash
AD_ACCOUNT_ID=act_123456789 meta --output json ads campaign list
AD_ACCOUNT_ID=act_123456789 meta --output json ads insights get --campaign_id CAMPAIGN_ID --date-preset last_7d --fields spend,impressions,clicks,ctr,cpc,reach,actions
```

Use bounded date windows such as `yesterday`, `last_7d`, `last_30d`, or `this_month` when supported by the installed CLI. Ask the user before running wide historical queries on large accounts.

For reports, include:

- Date range and account ID.
- Entity level: account, campaign, ad set, or ad.
- Fields requested.
- Caveats for attribution windows, conversion definitions, currency, and incomplete current-day data.

## Campaign Creation

Canonical launch shape:

```bash
meta ads campaign create --name "Campaign Name" --objective OUTCOME_SALES --daily-budget 5000
meta ads adset create CAMPAIGN_ID --name "Ad Set Name" --optimization-goal LINK_CLICKS --billing-event IMPRESSIONS --targeting-countries US
meta ads creative create --name "Creative Name" --page-id PAGE_ID --image ./asset.jpg --body "Primary text" --title "Headline" --link-url https://example.com --call-to-action SHOP_NOW
meta ads ad create ADSET_ID --name "Ad Name" --creative-id CREATIVE_ID
```

Before executing creation commands, confirm:

- Account ID and Page ID.
- Objective and optimization goal.
- Budget unit and currency interpretation.
- Targeting country/region and exclusions.
- Destination URL and URL parameters.
- Creative file paths or public URLs.
- Whether the user wants drafts only or activation after review.

## Updates And Status Changes

Before updates, fetch the current entity state. Then propose a minimal command that changes only the requested field.

Activation requires explicit current-turn approval. Use phrasing like:

```text
This will activate campaign CAMPAIGN_ID in account act_... and can begin spending. Should I run it?
```

Do not infer approval from earlier high-level goals like "launch a campaign"; ask immediately before the activation command.

## Catalogs

Use catalog commands for ecommerce workflows:

- List catalogs.
- Inspect catalog details and diagnostics.
- Inspect products, product sets, feeds, and feed rules.
- Fix only after reading diagnostics and confirming with the user.

Check local help for the current names:

```bash
meta ads catalog --help
```

## Datasets And Pixels

Meta may refer to pixels/event sources as datasets in this CLI surface.

Useful patterns:

```bash
meta ads dataset --help
meta ads dataset connect DATASET_ID --ad-account-id AD_ACCOUNT_ID --catalog-id CATALOG_ID
```

For diagnostics, prefer read-only dataset detail, quality, stats, and error commands before making changes.

## Sources To Recheck

- Meta Ads CLI overview: https://developers.facebook.com/documentation/ads-commerce/ads-ai-connectors/ads-cli/ads-cli-overview
- Meta Ads MCP endpoint: https://mcp.facebook.com/ads
- Meta developer launch coverage reported the CLI was announced on April 29, 2026 and designed for developers and AI agents working with Meta Marketing API.
